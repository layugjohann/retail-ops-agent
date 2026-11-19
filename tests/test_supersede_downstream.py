"""What Supersede does further down the pipeline, at the Ops Day boundary with scripted models.

A stockout risk is planted at ST02 and flagged on 2026-03-10. After that Ops Day, ST02's Uploader
resends the day's inventory Upload: either counting a Restock the first one missed, so the risk no
longer holds, or unchanged, so it still does.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from retail_ops_agent.action_policy import SUPERSEDE_RULES
from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import ApprovalStatus
from retail_ops_agent.audit_log import ActionTier, AuditAction, AuditEntry
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp, ReorderStatus
from retail_ops_agent.generator import (
    AnomalyPlan,
    GeneratedUploads,
    ResubmissionKind,
    ResubmissionPlan,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus
from retail_ops_agent.views import OpsDayOutcome

from .conftest import SEED, scripted_analyst_model, scripted_intake_model, scripted_ops_model

FIRST_DAY = date(2026, 3, 2)
DAYS = 12
SALES_CHANNEL = "ST02"
SUBMITTED = ("ST02", "ST03")
PLAN = AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel=SALES_CHANNEL, day=date(2026, 3, 12))
# The day detection flags the planted stockout risk.
FLAGGED_ON = date(2026, 3, 10)
PLANNER = "inventory planner"


def _generated(resubmission: ResubmissionKind, sales_channel: str = SALES_CHANNEL) -> GeneratedUploads:
    return generate_uploads(
        generate_history(generate_catalog(SEED), FIRST_DAY, DAYS, [PLAN]),
        resubmissions=[
            ResubmissionPlan(
                sales_channel=sales_channel,
                day=FLAGGED_ON,
                upload_kind=UploadKind.INVENTORY,
                resubmission_kind=resubmission,
            )
        ],
    )


@pytest.fixture(scope="module")
def restock_counted() -> GeneratedUploads:
    return _generated(ResubmissionKind.RESTOCK_COUNTED)


@pytest.fixture(scope="module")
def unchanged() -> GeneratedUploads:
    return _generated(ResubmissionKind.CORRECTED)


def scripted_reorder_model() -> Model:
    return TestModel(
        custom_output_args={"kind": "reorder", "quantity": 24, "subject": "Reorder", "body": "Covers it."}
    )


class Run:
    def __init__(self, catalog: Catalog, tmp_path: Path, *, ops: Model, auto_approval_limit: float) -> None:
        self.erp = InMemoryErp(catalog)
        self.clock = SimulatedClock(datetime.combine(FIRST_DAY, time(21, 0)))
        self.ops_day = OpsDay(
            models=Models(intake=scripted_intake_model(), analyst=scripted_analyst_model(), ops=ops),
            erp=self.erp,
            notifier=LogNotifier(),
            data_source=CsvDataSource(tmp_path / "uploads"),
            clock=self.clock,
            auto_approval_limit=auto_approval_limit,
        )

    def run_to_flagged_day(self, generated: GeneratedUploads) -> OpsDayOutcome:
        outcome: OpsDayOutcome | None = None
        for i, day in enumerate(d for d in generated.history.days if d <= FLAGGED_ON):
            if i:
                self.ops_day.advance_time(timedelta(days=1))
            for channel in SUBMITTED:
                for kind in UploadKind:
                    self.ops_day.submit_upload(
                        sales_channel=channel,
                        day=day,
                        kind=kind,
                        content=generated.content(channel, day, kind),
                        uploader=f"manager.{channel.lower()}@cobalthome.example",
                    )
            outcome = self.ops_day.run_ops_day(day)
        assert outcome is not None
        return outcome

    def resubmit(self, generated: GeneratedUploads, sales_channel: str = SALES_CHANNEL) -> OpsDayOutcome:
        """The Uploader resends the flagged day's inventory, and the Ops Day runs again."""
        self.ops_day.advance_time(timedelta(hours=1))
        self.ops_day.submit_upload(
            sales_channel=sales_channel,
            day=FLAGGED_ON,
            kind=UploadKind.INVENTORY,
            content=generated.resubmission(sales_channel, FLAGGED_ON, UploadKind.INVENTORY),
            uploader=f"manager.{sales_channel.lower()}@cobalthome.example",
        )
        return self.ops_day.run_ops_day(FLAGGED_ON)


def _entries(ops_day: OpsDay, action: AuditAction) -> list[AuditEntry]:
    return [e for e in ops_day.audit_log() if e.action is action]


def test_an_anomaly_that_no_longer_holds_is_cleared_and_its_alert_undone_as_a_new_entry(
    catalog: Catalog, tmp_path: Path, restock_counted: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, ops=scripted_ops_model(), auto_approval_limit=0)
    flagged = run.run_to_flagged_day(restock_counted)
    [anomaly] = flagged.anomalies
    assert anomaly.kind is AnomalyKind.STOCKOUT_RISK and anomaly.sales_channel == SALES_CHANNEL
    [alert] = _entries(run.ops_day, AuditAction.ALERT)

    outcome = run.resubmit(restock_counted)

    first = f"{SALES_CHANNEL}-{FLAGGED_ON.isoformat()}-inventory-001"
    second = f"{SALES_CHANNEL}-{FLAGGED_ON.isoformat()}-inventory-002"
    [cleared] = outcome.cleared_anomalies
    assert (cleared.anomaly_id, cleared.superseded_upload_id, cleared.replaced_by) == (
        anomaly.anomaly_id,
        first,
        second,
    )
    assert run.ops_day.cleared_anomalies() == [cleared]
    # The alert entry itself is unchanged; a new undo entry reverses it.
    [still_there] = _entries(run.ops_day, AuditAction.ALERT)
    assert still_there.model_copy(update={"undone_by": None}) == alert
    [undo] = [e for e in outcome.audit_entries if e.action is AuditAction.UNDO]
    assert still_there.undone_by == undo.entry_id
    assert (undo.undoes, undo.taken_by, undo.tier) == (alert.entry_id, SUPERSEDE_RULES, ActionTier.INTERNAL)
    assert first in undo.triggered_by and second in undo.triggered_by
    # The cleared Anomaly is not investigated again, and nothing new is flagged.
    assert outcome.anomalies == [] and outcome.investigations == []
    statuses = {u.upload_id: u.status for u in run.ops_day.upload_statuses()}
    assert (statuses[first], statuses[second]) == (UploadStatus.SUPERSEDED, UploadStatus.ACCEPTED)


def test_a_person_can_reinstate_an_alert_the_supersede_undid(
    catalog: Catalog, tmp_path: Path, restock_counted: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, ops=scripted_ops_model(), auto_approval_limit=0)
    run.run_to_flagged_day(restock_counted)
    [undo] = [e for e in run.resubmit(restock_counted).audit_entries if e.action is AuditAction.UNDO]

    run.ops_day.undo(undo.entry_id, taken_by=PLANNER)

    [alert] = _entries(run.ops_day, AuditAction.ALERT)
    assert alert.undone_by is None


def test_a_pending_reorder_for_a_cleared_anomaly_is_withdrawn_from_the_approval_queue(
    catalog: Catalog, tmp_path: Path, restock_counted: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, ops=scripted_reorder_model(), auto_approval_limit=0)
    [queued] = run.run_to_flagged_day(restock_counted).approval_queue

    outcome = run.resubmit(restock_counted)

    [withdrawn] = outcome.withdrawn_reorders
    assert withdrawn.action_id == queued.action_id
    assert withdrawn.status is ApprovalStatus.WITHDRAWN
    assert withdrawn.decided_by == SUPERSEDE_RULES and withdrawn.withdrawn_because
    assert outcome.approval_queue == [] and run.ops_day.approval_queue() == []
    [entry] = [e for e in outcome.audit_entries if e.action is AuditAction.WITHDRAW_REORDER]
    assert (entry.tier, entry.taken_by, entry.investigation_id) == (
        ActionTier.INTERNAL,
        SUPERSEDE_RULES,
        queued.investigation_id,
    )
    with pytest.raises(ValueError, match="withdrawn"):
        run.ops_day.approve(queued.action_id, approved_by=PLANNER)
    with pytest.raises(ValueError, match="cannot be undone"):
        run.ops_day.undo(entry.entry_id, taken_by=PLANNER)
    assert run.erp.list_reorders() == []
    assert outcome.flagged_reorders == []


def test_a_reorder_already_placed_for_a_cleared_anomaly_is_flagged_and_never_cancelled(
    catalog: Catalog, tmp_path: Path, restock_counted: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, ops=scripted_reorder_model(), auto_approval_limit=100_000)
    [placed] = run.run_to_flagged_day(restock_counted).reorders
    assert placed.status is ApprovalStatus.AUTO_APPROVED
    entries_before = len(run.ops_day.audit_log())

    outcome = run.resubmit(restock_counted)

    [flag] = outcome.flagged_reorders
    assert (flag.action_id, flag.reorder_id, flag.audit_entry_id) == (
        placed.action_id,
        placed.reorder_id,
        placed.audit_entry_id,
    )
    assert run.ops_day.flagged_reorders() == [flag]
    [reorder] = run.erp.list_reorders()
    assert reorder.status is ReorderStatus.PLACED
    [reorder_entry] = _entries(run.ops_day, AuditAction.REORDER)
    assert reorder_entry.undone_by is None
    assert len(run.ops_day.audit_log()) == entries_before
    assert run.ops_day.reorders()[0].status is ApprovalStatus.AUTO_APPROVED

    # A person who decides to cancel it does so from the Audit Log.
    run.ops_day.undo(flag.audit_entry_id, taken_by=PLANNER)
    [reorder] = run.erp.list_reorders()
    assert reorder.status is ReorderStatus.CANCELLED


def test_an_anomaly_that_still_holds_after_a_resubmission_keeps_its_actions(
    catalog: Catalog, tmp_path: Path, unchanged: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, ops=scripted_ops_model(), auto_approval_limit=0)
    run.run_to_flagged_day(unchanged)

    outcome = run.resubmit(unchanged)

    assert outcome.cleared_anomalies == [] and run.ops_day.cleared_anomalies() == []
    [alert] = _entries(run.ops_day, AuditAction.ALERT)
    assert alert.undone_by is None
    assert _entries(run.ops_day, AuditAction.UNDO) == []
    assert outcome.anomalies == []


def test_a_resubmission_at_another_sales_channel_leaves_a_stockout_risk_alone(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generated(ResubmissionKind.CHANGED, sales_channel="ST03")
    run = Run(catalog, tmp_path, ops=scripted_ops_model(), auto_approval_limit=0)
    run.run_to_flagged_day(generated)

    outcome = run.resubmit(generated, sales_channel="ST03")

    assert outcome.cleared_anomalies == []
    [alert] = _entries(run.ops_day, AuditAction.ALERT)
    assert alert.undone_by is None
