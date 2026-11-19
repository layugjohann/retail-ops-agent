from __future__ import annotations

import socket
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from retail_ops_agent import ops_day as ops_day_module
from retail_ops_agent import sandbox
from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import ApprovalStatus
from retail_ops_agent.audit_log import AuditAction
from retail_ops_agent.models import models_from_environment
from retail_ops_agent.replay import (
    RECORDED_APPROVER,
    RECORDING_PLANS,
    Recording,
    RecordingPlan,
    ReplayStage,
    load_recordings,
    record,
    replay_step,
    step_count,
    write_recording,
)
from retail_ops_agent.uploads import UploadStatus

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def _plan(recording_id: str) -> RecordingPlan:
    [plan] = [p for p in RECORDING_PLANS if p.recording_id == recording_id]
    return plan


def _offline_record(recording_id: str) -> Recording:
    models, label = models_from_environment({})
    return record(_plan(recording_id), models, label)


# The committed Recordings


def test_committed_recordings_cover_a_defect_day_a_stockout_reorder_and_an_approval() -> None:
    recordings = load_recordings()
    days = [d for r in recordings for d in r.ops_days]

    assert any(
        u.status in (UploadStatus.QUARANTINED, UploadStatus.SAFE_FIXED) and u.defects
        for d in days
        for u in d.outcome.uploads
    )
    assert any(
        d.outcome.reorders and AnomalyKind.STOCKOUT_RISK in {a.kind for a in d.outcome.anomalies}
        for d in days
    )
    assert any(
        dec.reorder.status is ApprovalStatus.APPROVED and dec.reorder.reorder_id
        for d in days
        for dec in d.decisions
    )


def test_every_committed_recording_matches_a_plan() -> None:
    assert {r.recording_id for r in load_recordings()} == {p.recording_id for p in RECORDING_PLANS}


# Recording


def test_recording_keeps_ops_days_from_the_plans_first_recorded_day() -> None:
    recording = _offline_record("02-stockout-auto-approved-reorder")
    plan = _plan("02-stockout-auto-approved-reorder")

    assert [d.outcome.day for d in recording.ops_days] == [plan.record_from, date(2026, 3, 10)]
    last = recording.ops_days[-1].outcome
    assert [a.kind for a in last.anomalies] == [AnomalyKind.STOCKOUT_RISK]
    [reorder] = last.reorders
    assert reorder.status is ApprovalStatus.AUTO_APPROVED
    assert reorder.reorder_id is not None
    assert recording.ops_days[-1].sales


def test_recording_an_approval_keeps_the_decision_and_its_audit_log_entry() -> None:
    recording = _offline_record("03-stockout-reorder-approval")

    last = recording.ops_days[-1]
    [queued] = last.outcome.approval_queue
    [decision] = last.decisions
    assert decision.reorder.action_id == queued.action_id
    assert decision.reorder.status is ApprovalStatus.APPROVED
    assert decision.reorder.decided_by == RECORDED_APPROVER
    [entry] = decision.audit_entries
    assert entry.action is AuditAction.REORDER
    assert int(entry.tier) == 2
    assert entry.taken_by == RECORDED_APPROVER


def test_recording_a_defect_day_keeps_the_quarantine_its_message_and_the_resend() -> None:
    recording = _offline_record("01-defect-day")

    statuses = {u.upload_id: u.status for d in recording.ops_days for u in d.outcome.uploads}
    assert statuses["ST02-2026-11-02-sales-001"] is UploadStatus.SAFE_FIXED
    assert statuses["ST03-2026-11-02-sales-001"] is UploadStatus.SUPERSEDED
    assert statuses["ST03-2026-11-02-sales-002"] is UploadStatus.ACCEPTED
    messages = [m for d in recording.ops_days for m in d.outcome.uploader_messages]
    assert [m.upload_id for m in messages] == ["ST03-2026-11-02-sales-001"]


def test_a_written_recording_loads_back_unchanged(tmp_path: Path) -> None:
    recording = _offline_record("03-stockout-reorder-approval")

    write_recording(recording, tmp_path)

    assert load_recordings(tmp_path) == [recording]


# Stepping through a Recording


def test_steps_go_through_each_ops_days_stages_in_pipeline_order() -> None:
    [recording, *_] = load_recordings()

    steps = [replay_step(recording, i) for i in range(step_count(recording))]

    assert len(steps) == len(recording.ops_days) * 5
    assert [s.stage for s in steps[:5]] == [
        ReplayStage.INTAKE,
        ReplayStage.LOAD,
        ReplayStage.DETECTION,
        ReplayStage.INVESTIGATION,
        ReplayStage.ACTIONS,
    ]
    assert [s.day for s in steps[::5]] == [d.outcome.day for d in recording.ops_days]
    assert all(s.narration for s in steps)
    with pytest.raises(ValueError, match="outside"):
        replay_step(recording, len(steps))


def test_each_stage_shows_only_what_that_stage_did() -> None:
    recording = load_recordings()[2]
    base = (len(recording.ops_days) - 1) * 5

    intake, load, detection, investigation, actions = (replay_step(recording, base + i) for i in range(5))

    assert intake.uploads and not intake.investigations
    assert all(u.status in (UploadStatus.ACCEPTED, UploadStatus.SAFE_FIXED) for u in load.uploads)
    assert load.sales
    assert [a.kind for a in detection.anomalies] == [AnomalyKind.STOCKOUT_RISK]
    assert len(investigation.investigations) == 1 and not investigation.reorders
    assert actions.reorders and actions.decisions
    assert AuditAction.REORDER in {e.action for e in actions.audit_entries}
    assert "approved" in actions.narration


# The dashboard in Replay Mode


@pytest.fixture
def no_model_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if anything tries to reach the network, build a sandbox or construct an Ops Day, even with a
    key set."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Replay Mode must make no model or network calls")

    monkeypatch.setenv("GROQ_API_KEY", "not-a-real-key")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(sandbox, "build_sandbox", refuse)
    monkeypatch.setattr(ops_day_module.OpsDay, "__init__", refuse)


@pytest.mark.usefixtures("no_model_or_network")
def test_dashboard_opens_in_replay_mode_without_a_model_or_network() -> None:
    app = AppTest.from_file(str(APP), default_timeout=60).run()

    assert not app.exception
    assert app.radio(key="mode").value == "Replay Mode"
    assert app.header[0].value.endswith(": Intake")
    assert app.dataframe
    assert "Hours Saved so far" in [h.value for h in app.header]
    assert any(m.label == "Hours Saved" for m in app.metric)


@pytest.mark.usefixtures("no_model_or_network")
def test_a_visitor_can_step_through_every_recorded_ops_day_stage_by_stage() -> None:
    app = AppTest.from_file(str(APP), default_timeout=60).run()

    for recording in load_recordings():
        app = app.selectbox(key="recording").set_value(recording.recording_id).run()
        app = app.button(key="replay-restart").click().run()
        seen = [app.header[0].value]
        for _ in range(step_count(recording) - 1):
            app = app.button(key="replay-next").click().run()
            assert not app.exception
            seen.append(app.header[0].value)
        assert seen == [replay_step(recording, i).title for i in range(step_count(recording))]
        assert app.button(key="replay-next").disabled

    app = app.button(key="replay-previous").click().run()
    assert app.header[0].value.endswith(": Investigation")


@pytest.mark.usefixtures("no_model_or_network")
def test_replay_shows_the_recorded_approval() -> None:
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    recording = next(r for r in load_recordings() if any(d.decisions for d in r.ops_days))
    app = app.selectbox(key="recording").set_value(recording.recording_id).run()

    for _ in range(step_count(recording) - 1):
        app = app.button(key="replay-next").click().run()

    decisions = [
        df.value for df in app.dataframe if "status" in df.value and "approved" in set(df.value["status"])
    ]
    assert decisions
    assert decisions[0]["ERP Reorder"].iloc[0].startswith("RO-")
