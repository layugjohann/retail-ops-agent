"""Sales drops, spikes and slow movers, and the chain-wide lookalikes that must not be blamed on one
Sales Channel, through the Ops Day boundary with scripted models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from retail_ops_agent.action_policy import ALERT_RECIPIENTS, MERCHANDISING, REGIONAL_MANAGER
from retail_ops_agent.anomalies import AnomalyKind, SalesDrop, SalesSpike, SlowMover
from retail_ops_agent.audit_log import ActionTier, AuditAction
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    AnomalyCause,
    AnomalyPlan,
    GeneratedUploads,
    LookalikeCause,
    LookalikePlan,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind

from .conftest import scripted_analyst_model, scripted_intake_model, scripted_ops_model

FIRST_DAY = date(2026, 3, 2)
CAUSE_DAY = date(2026, 3, 11)
FADE_DAY = date(2026, 3, 23)


@dataclass(frozen=True)
class Case:
    kind: AnomalyKind
    sales_channel: str
    day: date
    submitted: tuple[str, ...]
    kinds: tuple[UploadKind, ...]
    cause: AnomalyCause
    recipient: str


CASES = [
    Case(
        AnomalyKind.SALES_DROP,
        "ST02",
        CAUSE_DAY,
        ("ST01", "ST02", "ST03"),
        (UploadKind.SALES,),
        AnomalyCause.FOOTFALL_DROP,
        REGIONAL_MANAGER,
    ),
    Case(
        AnomalyKind.SALES_SPIKE,
        "ST02",
        CAUSE_DAY,
        ("ST01", "ST02", "ST06"),
        (UploadKind.SALES,),
        AnomalyCause.PRICE_CUT,
        MERCHANDISING,
    ),
    Case(
        AnomalyKind.SLOW_MOVER,
        "ST06",
        FADE_DAY,
        ("ST06",),
        tuple(UploadKind),
        AnomalyCause.FADING_DEMAND,
        ALERT_RECIPIENTS[AnomalyKind.SLOW_MOVER],
    ),
]


def _generate(
    catalog: Catalog,
    day: date,
    anomalies: Sequence[AnomalyPlan] = (),
    lookalikes: Sequence[LookalikePlan] = (),
) -> GeneratedUploads:
    days = (day - FIRST_DAY).days + 1
    return generate_uploads(generate_history(catalog, FIRST_DAY, days, anomalies, lookalikes))


def _run(
    catalog: Catalog,
    tmp_path: Path,
    generated: GeneratedUploads,
    submitted: Sequence[str],
    kinds: Sequence[UploadKind],
    models: Models | None = None,
) -> tuple[OpsDay, LogNotifier]:
    notifier = LogNotifier()
    clock = SimulatedClock(datetime.combine(FIRST_DAY, time(21, 0)))
    ops_day = OpsDay(
        models=models
        or Models(intake=scripted_intake_model(), analyst=scripted_analyst_model(), ops=scripted_ops_model()),
        erp=InMemoryErp(catalog),
        notifier=notifier,
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=clock,
    )
    for day in generated.history.days:
        for channel in submitted:
            for kind in kinds:
                ops_day.submit_upload(
                    sales_channel=channel,
                    day=day,
                    kind=kind,
                    content=generated.content(channel, day, kind),
                    uploader=f"manager.{channel.lower()}@cobalthome.example",
                )
        ops_day.run_ops_day(day)
        clock.advance(timedelta(days=1))
    return ops_day, notifier


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.kind.value)
def test_each_planted_kind_is_flagged_once_investigated_and_alerted_to_its_owner_at_tier_1(
    catalog: Catalog, tmp_path: Path, case: Case
) -> None:
    generated = _generate(
        catalog, case.day, [AnomalyPlan(kind=case.kind, sales_channel=case.sales_channel, day=case.day)]
    )
    [planted] = generated.ground_truth.anomalies
    assert (planted.kind, planted.cause, planted.sales_channel) == (case.kind, case.cause, case.sales_channel)

    ops_day, notifier = _run(catalog, tmp_path, generated, case.submitted, case.kinds)

    [anomaly] = ops_day.anomalies()
    assert (anomaly.kind, anomaly.sales_channel, anomaly.sku) == (case.kind, case.sales_channel, planted.sku)
    assert planted.cause_starts_on <= anomaly.day <= planted.day
    [investigation] = ops_day.investigations()
    assert investigation.anomaly == anomaly
    [alert] = [e for e in ops_day.audit_log() if e.action is AuditAction.ALERT]
    assert alert.tier is ActionTier.INTERNAL
    assert alert.investigation_id == investigation.investigation_id
    [sent] = notifier.sent
    assert sent.recipient == case.recipient


def test_a_sales_drop_is_about_the_whole_sales_channel_against_its_history_and_the_others(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(
        catalog, CAUSE_DAY, [AnomalyPlan(kind=AnomalyKind.SALES_DROP, sales_channel="ST02", day=CAUSE_DAY)]
    )
    [planted] = generated.ground_truth.anomalies
    assert planted.sku is None

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST01", "ST02", "ST03"), (UploadKind.SALES,))

    [drop] = ops_day.anomalies()
    assert isinstance(drop, SalesDrop)
    assert drop.sku is None
    assert drop.change <= 0.6 and drop.others_change > 0.8
    assert drop.other_sales_channels == 2


def test_a_sales_drop_needs_other_sales_channels_to_compare_with(catalog: Catalog, tmp_path: Path) -> None:
    generated = _generate(
        catalog, CAUSE_DAY, [AnomalyPlan(kind=AnomalyKind.SALES_DROP, sales_channel="ST02", day=CAUSE_DAY)]
    )

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST02",), (UploadKind.SALES,))

    assert ops_day.anomalies() == []


def test_a_chain_wide_dip_is_not_blamed_on_one_sales_channel(catalog: Catalog, tmp_path: Path) -> None:
    generated = _generate(
        catalog, CAUSE_DAY, lookalikes=[LookalikePlan(kind=AnomalyKind.SALES_DROP, day=CAUSE_DAY)]
    )
    [lookalike] = generated.ground_truth.lookalikes
    assert lookalike.cause is LookalikeCause.CHAIN_WIDE_DIP
    history = generated.history
    before = sum(r.quantity_sold for r in history.sales("ST02", CAUSE_DAY - timedelta(days=7)))
    during = sum(r.quantity_sold for r in history.sales("ST02", CAUSE_DAY))
    # Each Store falls as far as in a one-store drop ...
    assert during < 0.6 * before

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST01", "ST02", "ST03"), (UploadKind.SALES,))

    # ... but so does every other Sales Channel.
    assert ops_day.anomalies() == []
    assert ops_day.investigations() == []


def test_a_chain_wide_promotion_is_not_blamed_on_one_sales_channel(catalog: Catalog, tmp_path: Path) -> None:
    generated = _generate(
        catalog, CAUSE_DAY, lookalikes=[LookalikePlan(kind=AnomalyKind.SALES_SPIKE, day=CAUSE_DAY)]
    )
    [lookalike] = generated.ground_truth.lookalikes
    assert lookalike.cause is LookalikeCause.CHAIN_WIDE_PROMOTION and lookalike.sku is not None

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST01", "ST02", "ST06"), (UploadKind.SALES,))

    assert ops_day.anomalies() == []


def test_a_local_price_cut_spike_is_compared_with_the_other_sales_channels(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(
        catalog, CAUSE_DAY, [AnomalyPlan(kind=AnomalyKind.SALES_SPIKE, sales_channel="ST02", day=CAUSE_DAY)]
    )
    [planted] = generated.ground_truth.anomalies

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST01", "ST02", "ST06"), (UploadKind.SALES,))

    [spike] = ops_day.anomalies()
    assert isinstance(spike, SalesSpike)
    assert spike.daily_units == planted.units_sold
    assert spike.lowest_ratio >= 2.5
    assert spike.others_ratio is not None and spike.others_ratio < 1.5


def test_a_slow_mover_has_stock_on_hand_and_all_but_no_sales(catalog: Catalog, tmp_path: Path) -> None:
    generated = _generate(
        catalog, FADE_DAY, [AnomalyPlan(kind=AnomalyKind.SLOW_MOVER, sales_channel="ST06", day=FADE_DAY)]
    )

    ops_day, _ = _run(catalog, tmp_path, generated, ("ST06",), tuple(UploadKind))

    [slow] = ops_day.anomalies()
    assert isinstance(slow, SlowMover)
    assert slow.recent_daily_units <= 0.1 * slow.usual_daily_units
    assert slow.on_hand >= 20


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.kind.value)
def test_only_a_stockout_risk_can_lead_to_a_reorder_whatever_the_models_propose(
    catalog: Catalog, tmp_path: Path, case: Case
) -> None:
    generated = _generate(
        catalog, case.day, [AnomalyPlan(kind=case.kind, sales_channel=case.sales_channel, day=case.day)]
    )
    models = Models(
        intake=scripted_intake_model(),
        analyst=scripted_analyst_model(
            recommended_action={"kind": "reorder", "description": "Reorder 500 units now."}
        ),
        ops=scripted_ops_model(kind="reorder", quantity=500, subject="Reorder now", body="Order 500."),
    )

    ops_day, notifier = _run(catalog, tmp_path, generated, case.submitted, case.kinds, models)

    assert ops_day.reorders() == []
    [alert] = [e for e in ops_day.audit_log() if e.action is AuditAction.ALERT]
    assert alert.tier is ActionTier.INTERNAL
    assert [n.recipient for n in notifier.sent] == [case.recipient]
