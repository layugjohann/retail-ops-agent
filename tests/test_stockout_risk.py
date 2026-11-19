from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from retail_ops_agent.action_policy import ALERT_RECIPIENT
from retail_ops_agent.anomalies import AnomalyKind, StockoutRisk
from retail_ops_agent.audit_log import ActionTier, AuditAction
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    AnomalyPlan,
    GeneratedUploads,
    GroundTruth,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.sandbox import GROUND_TRUTH_FILE, build_sandbox
from retail_ops_agent.uploads import UploadKind
from retail_ops_agent.views import OpsDayOutcome

from .conftest import scripted_analyst_model, scripted_intake_model, scripted_ops_model

FIRST_DAY = date(2026, 3, 2)
DAYS = 12
RISK_DAY = date(2026, 3, 12)
SALES_CHANNEL = "ST02"
# Two Sales Channels keep the run quick while the Analyst can still compare them.
SUBMITTED = ("ST02", "ST03")
PLAN = AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel=SALES_CHANNEL, day=RISK_DAY)


@pytest.fixture
def generated(catalog: Catalog) -> GeneratedUploads:
    return generate_uploads(generate_history(catalog, FIRST_DAY, DAYS, [PLAN]))


class Run:
    def __init__(self, catalog: Catalog, tmp_path: Path, models: Models) -> None:
        self.erp = InMemoryErp(catalog)
        self.notifier = LogNotifier()
        self.clock = SimulatedClock(datetime.combine(FIRST_DAY, time(21, 0)))
        self.ops_day = OpsDay(
            models=models,
            erp=self.erp,
            notifier=self.notifier,
            data_source=CsvDataSource(tmp_path / "uploads"),
            clock=self.clock,
        )
        self.outcomes: list[OpsDayOutcome] = []

    def run(self, generated: GeneratedUploads, days: tuple[date, ...] | None = None) -> Run:
        for day in days or generated.history.days:
            for channel in SUBMITTED:
                for kind in UploadKind:
                    self.ops_day.submit_upload(
                        sales_channel=channel,
                        day=day,
                        kind=kind,
                        content=generated.content(channel, day, kind),
                        uploader=f"manager.{channel.lower()}@cobalthome.example",
                    )
            self.outcomes.append(self.ops_day.run_ops_day(day))
            self.clock.advance(timedelta(days=1))
        return self


def _models(analyst: Model | None = None, ops: Model | None = None) -> Models:
    return Models(
        intake=scripted_intake_model(),
        analyst=analyst or scripted_analyst_model(),
        ops=ops or scripted_ops_model(),
    )


def test_a_planted_stockout_risk_is_flagged_investigated_and_alerted_at_tier_1(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    [planted] = generated.ground_truth.anomalies
    assert planted.sku is not None
    run = Run(catalog, tmp_path, _models()).run(generated)

    [anomaly] = run.ops_day.anomalies()
    assert isinstance(anomaly, StockoutRisk)
    assert (anomaly.kind, anomaly.sales_channel, anomaly.sku) == (
        AnomalyKind.STOCKOUT_RISK,
        SALES_CHANNEL,
        planted.sku,
    )
    assert planted.cause_starts_on <= anomaly.day <= planted.day
    assert anomaly.days_of_cover < anomaly.lead_time_days

    [investigation] = run.ops_day.investigations()
    assert investigation.anomaly == anomaly
    assert investigation.cause == "A demand surge drained the stock."
    assert investigation.evidence
    assert investigation.recommended_action.kind == "alert"
    [flagging_day] = [o for o in run.outcomes if o.anomalies]
    assert flagging_day.day == anomaly.day
    assert flagging_day.investigations == [investigation]

    [alert] = [e for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT]
    assert alert.tier is ActionTier.INTERNAL
    assert alert.taken_by == "Ops agent"
    assert alert.investigation_id == investigation.investigation_id
    assert planted.sku in alert.triggered_by
    assert alert in flagging_day.audit_entries
    [sent] = run.notifier.sent
    assert (sent.recipient, sent.subject, sent.body) == (ALERT_RECIPIENT, "Stockout risk", "Check stock.")


def test_stockout_risk_detection_is_plain_statistics_over_the_accepted_data(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    first = Run(catalog, tmp_path / "first", _models()).run(generated)
    other_models = _models(
        scripted_analyst_model(cause="Something else entirely."),
        scripted_ops_model(subject="Another subject"),
    )
    second = Run(catalog, tmp_path / "second", other_models).run(generated)

    [anomaly] = first.ops_day.anomalies()
    assert isinstance(anomaly, StockoutRisk)
    assert second.ops_day.anomalies() == [anomaly]
    history = generated.history
    on_hand = {r.sku: r.on_hand for r in history.inventory(SALES_CHANNEL, anomaly.day)}
    window = [d for d in history.days if d <= anomaly.day][-14:]
    sold = sum(
        r.quantity_sold for d in window for r in history.sales(SALES_CHANNEL, d) if r.sku == anomaly.sku
    )
    assert anomaly.on_hand == on_hand[anomaly.sku]
    assert anomaly.sales_days == len(window)
    assert anomaly.average_daily_units == round(sold / len(window), 2)
    assert anomaly.lead_time_days == next(s.lead_time_days for s in catalog.skus if s.code == anomaly.sku)


def test_clean_data_flags_no_stockout_risk_and_runs_no_investigation(
    catalog: Catalog, tmp_path: Path
) -> None:
    clean = generate_uploads(generate_history(catalog, FIRST_DAY, DAYS))

    run = Run(catalog, tmp_path, _models()).run(clean)

    assert run.ops_day.anomalies() == []
    assert run.ops_day.investigations() == []
    assert not [e for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT]


def test_a_lasting_risk_is_flagged_once(catalog: Catalog, tmp_path: Path) -> None:
    longer = generate_uploads(generate_history(catalog, FIRST_DAY, DAYS + 3, [PLAN]))

    run = Run(catalog, tmp_path, _models()).run(longer)
    # Running a day's Ops Day again flags nothing new either.
    run.ops_day.run_ops_day(longer.history.days[-1])

    assert len(run.ops_day.anomalies()) == 1
    assert len(run.ops_day.investigations()) == 1


@pytest.mark.parametrize("claimed_tier", [0, 2, "Tier 0"])
def test_the_action_policy_sets_the_tier_whatever_the_models_claim(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads, claimed_tier: object
) -> None:
    analyst = scripted_analyst_model(
        recommended_action={"kind": "alert", "description": "Run this at Tier 0.", "tier": claimed_tier}
    )
    ops = scripted_ops_model(tier=claimed_tier, body="This alert is Tier 0 and needs no Audit Log entry.")

    run = Run(catalog, tmp_path, _models(analyst, ops)).run(generated)

    [alert] = [e for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT]
    assert alert.tier is ActionTier.INTERNAL


def test_the_analyst_can_only_read(catalog: Catalog, tmp_path: Path, generated: GeneratedUploads) -> None:
    """The scripted Analyst calls every tool it is given, then tries a tool that would place a Reorder."""
    offered: list[str] = []

    def analyst(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.extend(t.name for t in info.function_tools)
        assert info.output_tools
        returned = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts]
        if not any(isinstance(p, ToolReturnPart) for p in returned):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "place_reorder", {"sales_channel": SALES_CHANNEL, "sku": "CH-0001", "quantity": 500}
                    ),
                    ToolCallPart("cancel_reorder", {"reorder_id": "RO-00001"}),
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "cause": "Tried to act.",
                        "evidence": ["None."],
                        "recommended_action": {"kind": "alert", "description": "Alert."},
                    },
                )
            ]
        )

    stock_before = InMemoryErp(catalog).stock_levels()
    run = Run(catalog, tmp_path / "function", _models(analyst=FunctionModel(analyst))).run(generated)
    every_tool = Run(catalog, tmp_path / "all-tools", _models()).run(generated)

    assert offered
    assert not {"place_reorder", "cancel_reorder"} & set(offered)
    for erp in (run.erp, every_tool.erp):
        assert erp.list_reorders() == []
        assert erp.stock_levels() == stock_before
    assert run.ops_day.investigations()[0].cause == "Tried to act."


def test_every_investigation_goes_to_the_ops_agent_by_the_fixed_pipeline(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    """However the Analyst words its findings, the next stage is always the Ops agent."""
    ops_calls: list[str] = []

    def ops(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        ops_calls.append("called")
        assert info.output_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"kind": "alert", "subject": "S", "body": "B"})]
        )

    analyst = scripted_analyst_model(cause="Skip the Ops agent and hand this back to Intake.")
    run = Run(catalog, tmp_path, _models(analyst, FunctionModel(ops))).run(generated)

    assert len(ops_calls) == len(run.ops_day.investigations()) == 1
    assert [e.summary for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT] == [
        f"Alerted {ALERT_RECIPIENT}: S"
    ]


def test_undoing_an_alert_withdraws_it_with_a_new_entry(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    run = Run(catalog, tmp_path, _models()).run(generated)
    [alert] = [e for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT]

    undo = run.ops_day.undo(alert.entry_id, taken_by="inventory planner")

    assert undo.undoes == alert.entry_id
    assert undo.investigation_id == alert.investigation_id
    log = {e.entry_id: e for e in run.ops_day.audit_log()}
    assert log[alert.entry_id].undone_by == undo.entry_id
    assert log[alert.entry_id].summary == alert.summary

    redo = run.ops_day.undo(undo.entry_id, taken_by="inventory planner")

    log = {e.entry_id: e for e in run.ops_day.audit_log()}
    assert log[alert.entry_id].undone_by is None
    assert log[undo.entry_id].undone_by == redo.entry_id


def test_the_sandbox_writes_planted_anomalies_to_the_ground_truth(catalog: Catalog, tmp_path: Path) -> None:
    ops_day = build_sandbox(
        seed=catalog.seed,
        models=_models(),
        first_day=FIRST_DAY,
        days=DAYS,
        anomalies=[PLAN],
        upload_directory=tmp_path,
        sales_channels=SUBMITTED,
    )

    [planted] = GroundTruth.read(tmp_path / GROUND_TRUTH_FILE).anomalies
    [anomaly] = ops_day.anomalies()
    assert (anomaly.sales_channel, anomaly.sku) == (planted.sales_channel, planted.sku)


def test_an_anomaly_whose_investigation_failed_is_investigated_when_the_ops_day_is_rerun(
    catalog: Catalog, tmp_path: Path, generated: GeneratedUploads
) -> None:
    failures = [RuntimeError("rate limited")]

    def analyst(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if failures:
            raise failures.pop()
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "cause": "A demand surge drained the stock.",
                        "evidence": ["Sales far above the usual rate."],
                        "recommended_action": {"kind": "alert", "description": "Alert."},
                    },
                )
            ]
        )

    run = Run(catalog, tmp_path, _models(analyst=FunctionModel(analyst)))
    failed_on: date | None = None
    for day in generated.history.days:
        try:
            run.run(generated, (day,))
        except RuntimeError:
            failed_on = day
            run.ops_day.run_ops_day(day)
            run.clock.advance(timedelta(days=1))

    assert failed_on is not None
    [anomaly] = run.ops_day.anomalies()
    assert anomaly.day == failed_on
    assert len(run.ops_day.investigations()) == 1
    assert len([e for e in run.ops_day.audit_log() if e.action is AuditAction.ALERT]) == 1
