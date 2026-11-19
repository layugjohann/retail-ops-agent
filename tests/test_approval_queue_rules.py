"""Approval Queue rules at the Ops Day boundary: one pending Reorder per SKU and Sales Channel,
replacement by a newer Investigation, and Expiry after 48 simulated hours."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from retail_ops_agent.action_policy import QUEUE_RULES
from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import ApprovalStatus
from retail_ops_agent.audit_log import ActionTier, AuditAction
from retail_ops_agent.catalog import Catalog, Sku
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp, ReorderStatus
from retail_ops_agent.generator import (
    AnomalyPlan,
    GeneratedUploads,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind
from retail_ops_agent.views import OpsDayOutcome

from .conftest import SEED, scripted_analyst_model, scripted_intake_model

FIRST_DAY = date(2026, 3, 2)
DAYS = 12
SALES_CHANNEL = "ST02"
SUBMITTED = ("ST02", "ST03")
FLAGGED_ON = date(2026, 3, 10)
# With a restock, the Store reports the at-risk SKU well stocked on this day, so the risk clears; on
# the next day it is back, and is flagged and investigated again.
RESTOCKED_ON = date(2026, 3, 11)
FLAGGED_AGAIN_ON = date(2026, 3, 12)
# Planted for this day, the surge drives cover below the Lead Time from FLAGGED_ON.
PLAN = AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel=SALES_CHANNEL, day=date(2026, 3, 12))
FIRST_QUANTITY = 24
SECOND_QUANTITY = 36
PLANNER = "inventory planner"
EXPIRY = timedelta(hours=48)


@pytest.fixture(scope="module")
def generated() -> GeneratedUploads:
    return generate_uploads(generate_history(generate_catalog(SEED), FIRST_DAY, DAYS, [PLAN]))


@pytest.fixture
def sku(catalog: Catalog, generated: GeneratedUploads) -> Sku:
    [planted] = generated.ground_truth.anomalies
    return next(s for s in catalog.skus if s.code == planted.sku)


def reorders_of(*quantities: int) -> FunctionModel:
    """A scripted Ops model proposing a Reorder of each quantity in turn, one per Investigation."""
    remaining: Iterator[int] = iter(quantities)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        output = {
            "kind": "reorder",
            "quantity": next(remaining),
            "subject": "Reorder to cover the Lead Time",
            "body": "Covers the Lead Time at the recent rate.",
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    return FunctionModel(respond)


class Run:
    def __init__(self, catalog: Catalog, tmp_path: Path, *, limit: float = 0) -> None:
        self.erp = InMemoryErp(catalog)
        self.clock = SimulatedClock(datetime.combine(FIRST_DAY, time(21, 0)))
        self.ops_day = OpsDay(
            models=Models(
                intake=scripted_intake_model(),
                analyst=scripted_analyst_model(),
                ops=reorders_of(FIRST_QUANTITY, SECOND_QUANTITY),
            ),
            erp=self.erp,
            notifier=LogNotifier(),
            data_source=CsvDataSource(tmp_path / "uploads"),
            clock=self.clock,
            auto_approval_limit=limit,
        )
        self.outcomes: list[OpsDayOutcome] = []

    def run(
        self,
        generated: GeneratedUploads,
        *,
        through: date,
        step: timedelta,
        restock: str | None = None,
    ) -> Run:
        """Run each Ops Day through the given day, step apart in simulated time. With restock, that
        SKU is reported well stocked at the Sales Channel on RESTOCKED_ON."""
        for day in [d for d in generated.history.days if d <= through]:
            if self.outcomes:
                self.ops_day.advance_time(step)
            for channel in SUBMITTED:
                for kind in UploadKind:
                    content = generated.content(channel, day, kind)
                    if (channel, day, kind) == (
                        SALES_CHANNEL,
                        RESTOCKED_ON,
                        UploadKind.INVENTORY,
                    ) and restock:
                        content = _restocked(content, restock)
                    self.ops_day.submit_upload(
                        sales_channel=channel,
                        day=day,
                        kind=kind,
                        content=content,
                        uploader=f"manager.{channel.lower()}@cobalthome.example",
                    )
            self.outcomes.append(self.ops_day.run_ops_day(day))
        return self


def _restocked(content: str, sku: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        fields = line.split(",")
        if len(fields) == 4 and fields[2] == sku:
            fields[3] = "500"
        lines.append(",".join(fields))
    return "\n".join(lines) + "\n"


def flagged_twice(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku, *, limit: float = 0
) -> Run:
    """The risk is investigated, clears, and is investigated again a day later, within the Expiry."""
    return Run(catalog, tmp_path, limit=limit).run(
        generated, through=FLAGGED_AGAIN_ON, step=timedelta(hours=12), restock=sku.code
    )


def test_a_newer_investigation_replaces_the_pending_reorder(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    run = flagged_twice(catalog, tmp_path, generated, sku)

    first, second = sorted(run.ops_day.investigations(), key=lambda i: i.investigated_at)
    assert (first.anomaly.day, second.anomaly.day) == (FLAGGED_ON, FLAGGED_AGAIN_ON)
    [pending] = run.ops_day.approval_queue()
    assert pending.investigation_id == second.investigation_id
    assert (pending.sales_channel, pending.sku, pending.quantity) == (
        SALES_CHANNEL,
        sku.code,
        SECOND_QUANTITY,
    )
    replaced = next(r for r in run.ops_day.reorders() if r.investigation_id == first.investigation_id)
    assert replaced.status is ApprovalStatus.REPLACED
    assert replaced.replaced_by == pending.action_id
    assert replaced.decided_by == QUEUE_RULES
    assert run.ops_day.decided_reorders() == [replaced]
    assert run.erp.list_reorders() == []
    assert run.outcomes[-1].approval_queue == [pending]


def test_the_replacement_is_recorded_in_the_audit_log(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    run = flagged_twice(catalog, tmp_path, generated, sku)

    [pending] = run.ops_day.approval_queue()
    replaced = next(r for r in run.ops_day.reorders() if r.status is ApprovalStatus.REPLACED)
    [entry] = [e for e in run.ops_day.audit_log() if e.action is AuditAction.REPLACE_REORDER]
    assert entry.tier is ActionTier.INTERNAL
    assert entry.taken_by == QUEUE_RULES
    assert entry.investigation_id == pending.investigation_id
    assert replaced.action_id in entry.summary and pending.action_id in entry.summary
    assert replaced.investigation_id in entry.triggered_by
    assert entry in run.outcomes[-1].audit_entries
    with pytest.raises(ValueError, match="cannot be undone"):
        run.ops_day.undo(entry.entry_id, taken_by=PLANNER)
    assert len(run.ops_day.approval_queue()) == 1


def test_a_replaced_reorder_can_no_longer_be_decided(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    run = flagged_twice(catalog, tmp_path, generated, sku)
    replaced = next(r for r in run.ops_day.reorders() if r.status is ApprovalStatus.REPLACED)

    with pytest.raises(ValueError, match="replaced"):
        run.ops_day.approve(replaced.action_id, approved_by=PLANNER)
    with pytest.raises(ValueError, match="replaced"):
        run.ops_day.reject(replaced.action_id, rejected_by=PLANNER)
    assert run.erp.list_reorders() == []

    [pending] = run.ops_day.approval_queue()
    run.ops_day.approve(pending.action_id, approved_by=PLANNER)
    [reorder] = run.erp.list_reorders()
    assert reorder.quantity == SECOND_QUANTITY


def test_an_auto_approved_reorder_also_replaces_the_pending_one_so_nothing_is_ordered_twice(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    """The first Reorder is above the Auto-approval Limit and waits; the newer, smaller one is under it
    and is placed. The first can then never be approved as well."""
    limit = round((FIRST_QUANTITY + SECOND_QUANTITY) / 2 * sku.unit_cost, 2)
    run = Run(catalog, tmp_path, limit=limit)
    run.ops_day = OpsDay(
        models=Models(
            intake=scripted_intake_model(),
            analyst=scripted_analyst_model(),
            ops=reorders_of(SECOND_QUANTITY, FIRST_QUANTITY),
        ),
        erp=run.erp,
        notifier=LogNotifier(),
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=run.clock,
        auto_approval_limit=limit,
    )
    run.run(generated, through=FLAGGED_AGAIN_ON, step=timedelta(hours=12), restock=sku.code)

    assert run.ops_day.approval_queue() == []
    [reorder] = run.erp.list_reorders()
    assert reorder.quantity == FIRST_QUANTITY
    statuses = {r.quantity: r.status for r in run.ops_day.reorders()}
    assert statuses == {
        SECOND_QUANTITY: ApprovalStatus.REPLACED,
        FIRST_QUANTITY: ApprovalStatus.AUTO_APPROVED,
    }


def test_there_is_never_more_than_one_pending_reorder_per_sku_and_sales_channel(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    run = flagged_twice(catalog, tmp_path, generated, sku)

    for outcome in run.outcomes:
        keys = [(q.sales_channel, q.sku) for q in outcome.approval_queue]
        assert len(keys) == len(set(keys))
    assert len(run.ops_day.reorders()) == 2


def test_advancing_simulated_time_is_an_ops_day_operation(catalog: Catalog, tmp_path: Path) -> None:
    run = Run(catalog, tmp_path)
    start = run.ops_day.now()

    assert run.ops_day.advance_time(timedelta(hours=5)) == []

    assert run.ops_day.now() == start + timedelta(hours=5) == run.clock.now()
    with pytest.raises(ValueError, match="forward"):
        run.ops_day.advance_time(timedelta(hours=-1))


def test_a_pending_reorder_expires_48_simulated_hours_after_being_queued(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    run = Run(catalog, tmp_path).run(generated, through=FLAGGED_ON, step=timedelta(days=1))
    [queued] = run.ops_day.approval_queue()
    assert queued.expires_at == queued.queued_at + EXPIRY

    assert run.ops_day.advance_time(EXPIRY - timedelta(minutes=1)) == []
    assert run.ops_day.approval_queue() == [queued]

    [expired] = run.ops_day.advance_time(timedelta(minutes=1))

    assert expired.action_id == queued.action_id
    assert expired.status is ApprovalStatus.EXPIRED
    assert (expired.decided_at, expired.decided_by) == (queued.expires_at, QUEUE_RULES)
    assert run.ops_day.approval_queue() == []
    assert run.ops_day.decided_reorders() == [expired]
    with pytest.raises(ValueError, match="Expired"):
        run.ops_day.approve(queued.action_id, approved_by=PLANNER)
    with pytest.raises(ValueError, match="Expired"):
        run.ops_day.reject(queued.action_id, rejected_by=PLANNER)
    assert run.erp.list_reorders() == []
    assert not [e for e in run.ops_day.audit_log() if e.action is AuditAction.REORDER]


def test_an_expired_reorder_cannot_be_approved_however_time_was_advanced(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    """The clock is moved on directly rather than through the Ops Day; approving still finds the
    Reorder Expired, as of when its 48 hours ran out."""
    run = Run(catalog, tmp_path).run(generated, through=FLAGGED_ON, step=timedelta(days=1))
    [queued] = run.ops_day.approval_queue()
    run.clock.advance(timedelta(days=5))

    with pytest.raises(ValueError, match="Expired"):
        run.ops_day.approve(queued.action_id, approved_by=PLANNER)
    [expired] = run.ops_day.reorders()
    assert expired.decided_at == queued.expires_at
    assert run.erp.list_reorders() == []


def test_an_expired_reorder_is_not_replaced_and_a_newer_one_waits_on_its_own(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, sku: Sku
) -> None:
    """Ops Days a day apart: the first Reorder has Expired by the time the risk is investigated again."""
    run = Run(catalog, tmp_path).run(
        generated, through=FLAGGED_AGAIN_ON, step=timedelta(days=1), restock=sku.code
    )

    first, second = sorted(run.ops_day.reorders(), key=lambda r: r.queued_at)
    assert first.status is ApprovalStatus.EXPIRED
    assert first.replaced_by is None
    assert second.status is ApprovalStatus.PENDING
    assert not [e for e in run.ops_day.audit_log() if e.action is AuditAction.REPLACE_REORDER]


def test_an_approved_reorder_is_not_expired_later(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path).run(generated, through=FLAGGED_ON, step=timedelta(days=1))
    [queued] = run.ops_day.approval_queue()
    approved = run.ops_day.approve(queued.action_id, approved_by=PLANNER)

    assert run.ops_day.advance_time(EXPIRY * 2) == []

    assert run.ops_day.reorders() == [approved]
    [reorder] = run.erp.list_reorders()
    assert reorder.status is ReorderStatus.PLACED
