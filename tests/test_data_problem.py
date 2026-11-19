"""The Data Problem loop: an Upload in cases instead of units passes validation and shows as a sales
spike; the Analyst concludes Data Problem and the Upload goes back to Intake, which Quarantines it and
messages the Uploader. Tested through the Ops Day boundary with scripted models."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.audit_log import ActionTier, AuditAction, UndoOperation
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.defects import DATA_PROBLEM_DEFECT, DefectKind
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    DefectPlan,
    GeneratedUploads,
    PlantedDefect,
    generate_history,
    generate_uploads,
    upload_csv,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus

from .conftest import scripted_analyst_model, scripted_intake_model, scripted_ops_model
from .eval_models import _data, _output, _prompt  # pyright: ignore[reportPrivateUsage]
from .test_action_evals import _graders  # pyright: ignore[reportPrivateUsage]
from .test_evals import _run as _run_evals  # pyright: ignore[reportPrivateUsage]

FIRST_DAY = date(2026, 3, 2)
CASES_DAYS = (date(2026, 3, 16), date(2026, 3, 17), date(2026, 3, 18))
LAST_DAY = CASES_DAYS[-1]
CHANNEL = "ST02"
SUBMITTED = ("ST01", "ST02", "ST06")
UPLOADER = "manager.st02@cobalthome.example"


def _generate(catalog: Catalog, days: Sequence[date] = CASES_DAYS) -> GeneratedUploads:
    history = generate_history(catalog, FIRST_DAY, (LAST_DAY - FIRST_DAY).days + 1)
    return generate_uploads(
        history,
        [
            DefectPlan(
                sales_channel=CHANNEL,
                day=day,
                upload_kind=UploadKind.SALES,
                defect_kind=DefectKind.UNITS_IN_CASES,
            )
            for day in days
        ],
    )


def _data_problem(days: Sequence[date] = CASES_DAYS, **extra: Any) -> dict[str, Any]:
    return {
        "cause": "The SKU's quantities are in cases, not single units.",
        "evidence": ["Its price a unit fell to a twelfth of the usual on exactly these days."],
        "data_problem": {
            "upload_kind": "sales",
            "days": [d.isoformat() for d in days],
            "what_is_wrong": "The quantity sold of the SKU is in cases, not single units.",
        },
        **extra,
    }


def _never_called(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    raise AssertionError("the Ops agent was asked to act on a Data Problem")


def _run(
    catalog: Catalog,
    tmp_path: Path,
    generated: GeneratedUploads,
    *,
    analyst: dict[str, Any] | None = None,
    notifier: LogNotifier | None = None,
    erp: InMemoryErp | None = None,
) -> tuple[OpsDay, list[Any]]:
    ops_day = OpsDay(
        models=Models(
            intake=scripted_intake_model(),
            analyst=scripted_analyst_model(**analyst) if analyst else scripted_analyst_model(),
            ops=FunctionModel(_never_called) if analyst else scripted_ops_model(),
        ),
        erp=erp or InMemoryErp(catalog),
        notifier=notifier or LogNotifier(),
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=SimulatedClock(datetime.combine(FIRST_DAY, time(21, 0))),
    )
    outcomes: list[Any] = []
    for day in generated.history.days:
        for channel in SUBMITTED:
            ops_day.submit_upload(
                sales_channel=channel,
                day=day,
                kind=UploadKind.SALES,
                content=generated.content(channel, day, UploadKind.SALES),
                uploader=UPLOADER if channel == CHANNEL else f"manager.{channel.lower()}@cobalthome.example",
            )
        outcomes.append(ops_day.run_ops_day(day))
    return ops_day, outcomes


def _planted(generated: GeneratedUploads) -> list[PlantedDefect]:
    return [d for d in generated.ground_truth.defects if d.defect_kind is DefectKind.UNITS_IN_CASES]


def _row(content: str, row: int) -> dict[str, str]:
    return list(csv.DictReader(io.StringIO(content)))[row - 2]


# The generator


def test_the_generator_plants_one_sku_in_cases_with_its_net_sales_unchanged(catalog: Catalog) -> None:
    generated = _generate(catalog)
    planted = _planted(generated)

    assert [p.day for p in planted] == list(CASES_DAYS)
    [(sku, case_pack)] = {(p.sku, p.case_pack) for p in planted}
    assert sku is not None and case_pack is not None and case_pack > 1
    assert {sku: case_pack} == {s.code: s.case_pack for s in catalog.skus if s.code == sku}
    for p in planted:
        assert (p.column, p.has_safe_fix, p.expected_status) == (
            "quantity_sold",
            False,
            UploadStatus.QUARANTINED,
        )
        assert p.row is not None
        sent = _row(generated.content(CHANNEL, p.day, UploadKind.SALES), p.row)
        clean = _row(upload_csv(generated.history, CHANNEL, p.day, UploadKind.SALES), p.row)
        assert sent["sku"] == clean["sku"] == sku
        assert int(sent["quantity_sold"]) == int(clean["quantity_sold"]) * case_pack
        assert sent["net_sales"] == clean["net_sales"]


def test_units_in_cases_can_only_be_planted_in_a_stores_sales(catalog: Catalog) -> None:
    history = generate_history(catalog, FIRST_DAY, 1)
    for channel, kind in (("ONLINE", UploadKind.SALES), ("ST01", UploadKind.INVENTORY)):
        plan = DefectPlan(
            sales_channel=channel, day=FIRST_DAY, upload_kind=kind, defect_kind=DefectKind.UNITS_IN_CASES
        )
        with pytest.raises(ValueError, match="only be planted in a Store's sales"):
            generate_uploads(history, [plan])


def test_an_upload_in_cases_passes_validation_and_shows_as_a_sales_spike(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(catalog)
    ops_day, outcomes = _run(catalog, tmp_path, generated)

    assert all(u.status is UploadStatus.ACCEPTED and not u.defects for u in ops_day.upload_statuses())
    [sku] = {p.sku for p in _planted(generated)}
    [spike] = outcomes[-1].anomalies
    assert (spike.kind, spike.sales_channel, spike.sku, spike.day) == (
        AnomalyKind.SALES_SPIKE,
        CHANNEL,
        sku,
        LAST_DAY,
    )
    # Every other day, nothing is flagged.
    assert all(not o.anomalies for o in outcomes[:-1])


# The Data Problem loop


def test_a_data_problem_sends_the_uploads_back_to_intake_which_quarantines_them_and_messages_the_uploader(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(catalog)
    notifier = LogNotifier()
    ops_day, outcomes = _run(catalog, tmp_path, generated, analyst=_data_problem(), notifier=notifier)
    outcome = outcomes[-1]

    [investigation] = outcome.investigations
    assert investigation.data_problem is not None and investigation.recommended_action is None
    assert investigation.conclusion == "Data Problem"
    sent_back = investigation.data_problem.upload_ids
    assert sent_back == [f"{CHANNEL}-{d.isoformat()}-sales-001" for d in CASES_DAYS]
    # Each Upload is Quarantined with the Defect validation missed, where the generator planted it.
    statuses = {u.upload_id: u for u in ops_day.upload_statuses()}
    planted = {p.day: p for p in _planted(generated)}
    for upload_id in sent_back:
        upload = statuses[upload_id]
        assert upload.status is UploadStatus.QUARANTINED
        assert [s.status for s in upload.history] == [UploadStatus.ACCEPTED, UploadStatus.QUARANTINED]
        [defect] = upload.defects
        assert (defect.kind, defect.row, defect.column) == (
            DATA_PROBLEM_DEFECT,
            planted[upload.day].row,
            "quantity_sold",
        )
    assert {u.upload_id for u in outcome.uploads} >= set(sent_back)
    # Its rows leave the BI data; every other Upload stays.
    loaded = {(r.sales_channel, r.day) for r in ops_day.sales_by_sales_channel()}
    assert not loaded & {(CHANNEL, d) for d in CASES_DAYS}
    assert all(u.status is UploadStatus.ACCEPTED for u in statuses.values() if u.upload_id not in sent_back)
    # The Quarantine is a Tier 1 Action in the Audit Log, taken by Intake for the Investigation.
    quarantines = [e for e in outcome.audit_entries if e.action is AuditAction.QUARANTINE]
    assert [e.upload_id for e in quarantines] == sent_back
    for entry in quarantines:
        assert (entry.tier, entry.taken_by, entry.investigation_id) == (
            ActionTier.INTERNAL,
            "Intake agent",
            investigation.investigation_id,
        )
        assert entry.undo.operation is UndoOperation.RELEASE_UPLOAD
    # The Uploader is messaged once for each Upload, saying what is wrong and what to do.
    assert [m.upload_id for m in outcome.uploader_messages] == sent_back
    assert [n.recipient for n in notifier.sent] == [UPLOADER] * 3
    for message in outcome.uploader_messages:
        assert "Quantity not in units" in message.body
        assert "row" in message.body and "quantity_sold" in message.body
        assert "single units" in message.body and "resend" in message.body


def test_no_business_action_is_taken_for_a_data_problem_even_if_the_model_also_recommends_one(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(catalog)
    erp = InMemoryErp(catalog)
    analyst = _data_problem(recommended_action={"kind": "reorder", "description": "Reorder 500 units now."})
    ops_day, outcomes = _run(catalog, tmp_path, generated, analyst=analyst, erp=erp)

    [investigation] = outcomes[-1].investigations
    assert investigation.recommended_action is None
    assert {e.action for e in ops_day.audit_log()} == {AuditAction.QUARANTINE}
    assert not ops_day.reorders() and not ops_day.approval_queue() and not erp.list_reorders()


def test_only_loaded_uploads_from_the_anomalys_sales_channel_and_days_go_back(
    catalog: Catalog, tmp_path: Path
) -> None:
    """The model names the days; the rule decides which Uploads. A day after the Anomaly or with no
    Upload sends nothing back, and no other Sales Channel's Upload is ever touched."""
    generated = _generate(catalog)
    days = [*CASES_DAYS, LAST_DAY + timedelta(days=1), FIRST_DAY - timedelta(days=1)]
    ops_day, outcomes = _run(catalog, tmp_path, generated, analyst=_data_problem(days))

    [investigation] = outcomes[-1].investigations
    assert investigation.data_problem is not None
    assert investigation.data_problem.upload_ids == [
        f"{CHANNEL}-{d.isoformat()}-sales-001" for d in CASES_DAYS
    ]
    quarantined = {u.upload_id for u in ops_day.upload_statuses() if u.status is UploadStatus.QUARANTINED}
    assert quarantined == set(investigation.data_problem.upload_ids)


def test_undoing_a_data_problems_quarantine_puts_the_upload_back_in_the_bi_data(
    catalog: Catalog, tmp_path: Path
) -> None:
    generated = _generate(catalog)
    ops_day, _ = _run(catalog, tmp_path, generated, analyst=_data_problem())
    entry = next(e for e in ops_day.audit_log() if e.action is AuditAction.QUARANTINE)

    ops_day.undo(entry.entry_id, taken_by="bi.analyst@cobalthome.example")

    upload = next(u for u in ops_day.upload_statuses() if u.upload_id == entry.upload_id)
    assert upload.status is UploadStatus.ACCEPTED
    loaded = {(r.sales_channel, r.day) for r in ops_day.sales_by_sales_channel()}
    assert (CHANNEL, upload.day) in loaded


# Evals


def test_the_data_problem_scenarios_pass_when_the_analyst_catches_it(tmp_path: Path) -> None:
    code, table, scorecard = _run_evals(tmp_path, "--tag", "data-problem", "--no-judge")

    assert code == 0 and scorecard is not None, table
    assert {s.id for s in scorecard.scenarios} == {
        "data-problem-units-in-cases",
        "data-problem-beside-a-real-spike",
    }
    summary = scorecard.summary
    assert (summary.data_problems_caught, summary.data_problems_planted) == (2, 2)
    assert summary.data_problem_false_alarms == 0
    # The real spike beside it still gets its alert.
    assert (summary.actions_right, summary.actions_expected) == (1, 1)
    assert "Data Problems caught: 2/2   false alarms: 0" in table


def test_an_analyst_that_misses_the_data_problem_fails_the_data_problem_grader(tmp_path: Path) -> None:
    code, _, scorecard = _run_evals(
        tmp_path, "--scenario", "data-problem-units-in-cases", "--no-judge", analyst=_price_cut_analyst()
    )

    assert code == 1 and scorecard is not None
    graders = _graders(scorecard, "data-problem-units-in-cases")
    assert not graders["data_problems"].passed
    assert "never concluded Data Problem" in graders["data_problems"].findings[0]
    assert "led to a business Action" in graders["data_problems"].findings[1]
    # The Uploads stay loaded, so the Intake graders fail too.
    assert not graders["upload_status"].passed and not graders["bi_data"].passed


def test_concluding_a_data_problem_on_a_real_spike_is_a_false_alarm(tmp_path: Path) -> None:
    code, _, scorecard = _run_evals(
        tmp_path, "--scenario", "sales-spike-one-store", "--no-judge", analyst=_always_data_problem_analyst()
    )

    assert code == 1 and scorecard is not None
    graders = _graders(scorecard, "sales-spike-one-store")
    assert not graders["data_problems"].passed
    assert graders["data_problems"].counts["false_alarms"] == 1
    assert "no Defect was planted" in graders["data_problems"].findings[0]
    assert not graders["no_clean_quarantine"].passed


def _price_cut_analyst() -> FunctionModel:
    """Blames every spike on a price cut without looking: it never spots the Data Problem."""

    def analyst(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _output(
            info,
            {
                "cause": "A local price cut: the SKU sold at a discount here only.",
                "evidence": ["It sold several times its usual rate here only."],
                "recommended_action": {"kind": "alert", "description": "Tell the merchandiser."},
            },
        )

    return FunctionModel(analyst)


def _always_data_problem_analyst() -> FunctionModel:
    """Calls every spike a Data Problem, whatever the data shows."""

    def analyst(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        anomaly = _data(_prompt(messages))
        return _output(info, _data_problem([date.fromisoformat(anomaly["day"])]))

    return FunctionModel(analyst)
