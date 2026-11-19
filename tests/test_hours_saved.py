"""Hours Saved from the Audit Log and the discovery documents' baseline, at the Ops Day boundary."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.audit_log import AuditAction
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    AnomalyPlan,
    DefectPlan,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.hours_saved import Baseline, BaselineTask, Basis, hours_saved, load_baseline
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.replay import load_recordings, replay_step, step_count
from retail_ops_agent.uploads import UploadKind

from .conftest import SEED, scripted_analyst_model, scripted_intake_model, scripted_models

DAY = date(2026, 3, 2)
UPLOADER = "uploader@cobalthome.example"
DISCOVERY = Path(__file__).resolve().parent.parent / "docs" / "discovery"


def _minutes(action: AuditAction) -> float:
    [task] = [t for t in load_baseline().tasks if t.audit_action is action]
    return task.minutes_each


def _defect_day(ops_day: OpsDay, catalog: Catalog) -> None:
    """One Ops Day with two Safe-Fixable Defects and one Defect that Quarantines its Upload."""
    plans = [
        DefectPlan(sales_channel=channel, day=DAY, upload_kind=kind, defect_kind=defect)
        for channel, kind, defect in [
            ("ST01", UploadKind.SALES, DefectKind.RENAMED_COLUMN),
            ("ST02", UploadKind.INVENTORY, DefectKind.STRAY_WHITESPACE),
            ("ST03", UploadKind.SALES, DefectKind.MISSING_COLUMN),
        ]
    ]
    generated = generate_uploads(generate_history(catalog, DAY, 1), plans)
    for channel in ("ST01", "ST02", "ST03"):
        for kind in UploadKind:
            ops_day.submit_upload(
                sales_channel=channel,
                day=DAY,
                kind=kind,
                content=generated.content(channel, DAY, kind),
                uploader=UPLOADER,
            )
    ops_day.run_ops_day(DAY)


def test_hours_saved_is_matching_audit_log_entries_times_baseline_minutes(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    assert ops_day.hours_saved().minutes == 0

    _defect_day(ops_day, catalog)

    saved = ops_day.hours_saved()
    entries = ops_day.audit_log()
    by_action = {line.task.audit_action: line for line in saved.lines}
    safe_fixes = sum(1 for e in entries if e.action is AuditAction.SAFE_FIX)
    quarantines = sum(1 for e in entries if e.action is AuditAction.QUARANTINE)
    assert (safe_fixes, quarantines) == (2, 1)
    assert by_action[AuditAction.SAFE_FIX].matching_entries == safe_fixes
    assert by_action[AuditAction.QUARANTINE].matching_entries == quarantines
    expected = safe_fixes * _minutes(AuditAction.SAFE_FIX) + quarantines * _minutes(AuditAction.QUARANTINE)
    assert saved.minutes == expected
    assert saved.hours == round(expected / 60, 2)
    assert saved.undone_entries == 0


def test_an_undone_entry_saves_nothing_and_undoing_the_undo_counts_it_again(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    _defect_day(ops_day, catalog)
    before = ops_day.hours_saved().minutes
    fix = next(e for e in ops_day.audit_log() if e.action is AuditAction.SAFE_FIX)

    undo = ops_day.undo(fix.entry_id, taken_by="BI analyst")

    undone = ops_day.hours_saved()
    assert undone.minutes == before - _minutes(AuditAction.SAFE_FIX)
    assert undone.undone_entries == 1

    ops_day.undo(undo.entry_id, taken_by="BI analyst")

    assert ops_day.hours_saved().minutes == before
    assert ops_day.hours_saved().undone_entries == 0


def test_hours_saved_counts_alerts_and_reorders_from_investigations(catalog: Catalog, tmp_path: Path) -> None:
    first_day = date(2026, 3, 2)
    plan = AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 3, 12))
    generated = generate_uploads(generate_history(generate_catalog(SEED), first_day, 12, [plan]))
    reorder_model = TestModel(
        custom_output_args={"kind": "reorder", "quantity": 1, "subject": "Reorder", "body": "Restock."}
    )
    clock = SimulatedClock(datetime.combine(first_day, time(21, 0)))
    ops_day = OpsDay(
        models=Models(intake=scripted_intake_model(), analyst=scripted_analyst_model(), ops=reorder_model),
        erp=InMemoryErp(catalog),
        notifier=LogNotifier(),
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=clock,
        auto_approval_limit=1_000_000,
    )
    for i, day in enumerate(d for d in generated.history.days if d <= date(2026, 3, 11)):
        if i:
            ops_day.advance_time(timedelta(days=1))
        for channel in ("ST02", "ST03"):
            for kind in UploadKind:
                ops_day.submit_upload(
                    sales_channel=channel,
                    day=day,
                    kind=kind,
                    content=generated.content(channel, day, kind),
                    uploader=UPLOADER,
                )
        ops_day.run_ops_day(day)

    reorders = [e for e in ops_day.audit_log() if e.action is AuditAction.REORDER]
    assert reorders
    by_action = {line.task.audit_action: line for line in ops_day.hours_saved().lines}
    assert by_action[AuditAction.REORDER].matching_entries == len(reorders)
    assert by_action[AuditAction.REORDER].minutes_saved == len(reorders) * _minutes(AuditAction.REORDER)


def test_hours_saved_uses_the_baseline_passed_in(catalog: Catalog, tmp_path: Path) -> None:
    baseline = Baseline(
        simulated=True,
        label="test baseline",
        tasks=[
            BaselineTask(
                task_id="fix",
                task="Fix an Upload",
                persona="BI analyst",
                audit_action=AuditAction.SAFE_FIX,
                minutes_each=60,
                how_often="daily",
                basis=Basis.ASSUMPTION,
                reasoning="for the test",
            )
        ],
    )
    ops_day = OpsDay(
        models=scripted_models(),
        erp=InMemoryErp(catalog),
        notifier=LogNotifier(),
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=SimulatedClock(datetime.combine(DAY, time(21, 0))),
        baseline=baseline,
    )

    _defect_day(ops_day, catalog)

    saved = ops_day.hours_saved()
    assert saved.label == "test baseline"
    assert [line.matching_entries for line in saved.lines] == [2]
    assert saved.hours == 2.0


def test_the_baseline_is_simulated_and_every_timing_is_cited_or_an_assumption() -> None:
    baseline = load_baseline()

    assert baseline.simulated
    assert "SIMULATED" in baseline.label
    assert {t.audit_action for t in baseline.tasks} == {
        AuditAction.SAFE_FIX,
        AuditAction.QUARANTINE,
        AuditAction.ALERT,
        AuditAction.REORDER,
    }
    for task in baseline.tasks:
        assert task.reasoning
        assert task.how_often
        assert task.source if task.basis is Basis.SOURCE else task.basis is Basis.ASSUMPTION


def test_a_timing_based_on_a_source_must_name_it() -> None:
    with pytest.raises(ValidationError, match="must name it"):
        BaselineTask(
            task_id="fix",
            task="Fix an Upload",
            persona="BI analyst",
            audit_action=AuditAction.SAFE_FIX,
            minutes_each=10,
            how_often="daily",
            basis=Basis.SOURCE,
            reasoning="cited",
        )


def test_every_discovery_document_is_labelled_simulated_and_the_baseline_document_lists_every_task() -> None:
    documents = sorted(DISCOVERY.glob("*.md"))
    assert {d.name for d in documents} >= {
        "engagement-brief.md",
        "personas.md",
        "manual-processes.md",
        "baseline.md",
    }
    for document in documents:
        assert "SIMULATED" in document.read_text().splitlines()[2], document.name
    baseline_document = (DISCOVERY / "baseline.md").read_text()
    for task in load_baseline().tasks:
        assert task.task_id in baseline_document
        assert f"| {task.minutes_each:g} |" in baseline_document


def test_replay_hours_saved_counts_every_entry_shown_so_far() -> None:
    reorders_counted = 0
    for recording in load_recordings():
        every_entry = [
            e
            for day in recording.ops_days
            for e in day.outcome.audit_entries + [x for d in day.decisions for x in d.audit_entries]
        ]
        steps = [replay_step(recording, p) for p in range(step_count(recording))]
        saved = [s.hours_saved for s in steps if s.hours_saved is not None]
        assert len(saved) == len(steps)
        assert saved[-1] == hours_saved(every_entry, load_baseline())
        # The recordings hold no undos, so the figure only grows as the Visitor steps through.
        assert [s.minutes for s in saved] == sorted(s.minutes for s in saved)
        reorders_counted += sum(
            line.matching_entries for line in saved[-1].lines if line.task.audit_action is AuditAction.REORDER
        )
    assert reorders_counted > 0
