"""Replay Mode: recorded Ops Day outcomes, played back stage by stage with no model and no key.

A Recording is made by running a seeded sandbox through the Ops Day boundary and keeping each Ops
Day's outcome, the BI data it loaded, and any Approval decisions taken after it. Recordings are
stored in the repository as JSON. Playing one back only reads that JSON: nothing calls a model, the
ERP or the network.

Record again (with free-tier keys in .env.local, or the offline scripted model without):

    make record
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic_ai.models import Model, infer_model

from retail_ops_agent.action_policy import DEFAULT_AUTO_APPROVAL_LIMIT
from retail_ops_agent.analyst import Investigation
from retail_ops_agent.anomalies import Anomaly, AnomalyKind
from retail_ops_agent.approval_queue import QueuedReorder
from retail_ops_agent.audit_log import AuditAction, AuditEntry
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.evals.throttle import Throttle, ThrottledModel
from retail_ops_agent.generator import AnomalyPlan, DefectPlan, ResubmissionKind, ResubmissionPlan
from retail_ops_agent.models import model_name_from_environment, models_from_environment
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploads import UploadKind, UploadStatus
from retail_ops_agent.views import (
    ClearedAnomaly,
    FlaggedReorder,
    InventoryBySalesChannel,
    OpsDayOutcome,
    SalesBySalesChannel,
    UploaderMessage,
    UploadOutcome,
)

RECORDINGS_DIRECTORY = Path(__file__).resolve().parent / "recordings"
# Who takes a Recording's Approval decisions, as the Approval Queue and Audit Log record it.
RECORDED_APPROVER = "inventory planner (recorded)"
# Below the tightest free tier the models default to, as for evals.
DEFAULT_REQUESTS_PER_MINUTE = 10.0


class ReplayStage(StrEnum):
    """The stages of an Ops Day, in the order the pipeline runs them (ADR 0003)."""

    INTAKE = "intake"
    LOAD = "load"
    DETECTION = "detection"
    INVESTIGATION = "investigation"
    ACTIONS = "actions"


STAGE_TITLES: dict[ReplayStage, str] = {
    ReplayStage.INTAKE: "Intake",
    ReplayStage.LOAD: "Load",
    ReplayStage.DETECTION: "Detection",
    ReplayStage.INVESTIGATION: "Investigation",
    ReplayStage.ACTIONS: "Actions",
}

# Audit Log entries Intake makes about Uploads; every other entry is shown with the Actions.
_INTAKE_ACTIONS = frozenset({AuditAction.SAFE_FIX, AuditAction.QUARANTINE})
_LOADED = frozenset({UploadStatus.ACCEPTED, UploadStatus.SAFE_FIXED})


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RecordedDecision(BaseModel):
    """A person's Approval decision on a pending Reorder, taken after an Ops Day."""

    model_config = ConfigDict(frozen=True)

    reorder: QueuedReorder
    audit_entries: list[AuditEntry] = []


class RecordedOpsDay(BaseModel):
    """One Ops Day's outcome, the BI data it loaded, and the decisions a person took after it."""

    model_config = ConfigDict(frozen=True)

    outcome: OpsDayOutcome
    # Accepted sales and inventory in the BI data, for the days of the Uploads this Ops Day processed.
    sales: list[SalesBySalesChannel] = []
    inventory: list[InventoryBySalesChannel] = []
    decisions: list[RecordedDecision] = []


class Recording(BaseModel):
    """Recorded Ops Days from one run of a seeded sandbox."""

    model_config = ConfigDict(frozen=True)

    recording_id: str
    title: str
    description: str
    # The model the agents used when it was recorded.
    model: str
    seed: int
    auto_approval_limit: float
    ops_days: list[RecordedOpsDay]


class ReplayStep(BaseModel):
    """What one stage of one recorded Ops Day did, ready to show a Visitor."""

    model_config = ConfigDict(frozen=True)

    position: int
    total: int
    day: date
    stage: ReplayStage
    title: str
    narration: str
    uploads: list[UploadOutcome] = []
    uploader_messages: list[UploaderMessage] = []
    sales: list[SalesBySalesChannel] = []
    inventory: list[InventoryBySalesChannel] = []
    anomalies: list[Anomaly] = []
    cleared_anomalies: list[ClearedAnomaly] = []
    investigations: list[Investigation] = []
    audit_entries: list[AuditEntry] = []
    reorders: list[QueuedReorder] = []
    approval_queue: list[QueuedReorder] = []
    withdrawn_reorders: list[QueuedReorder] = []
    flagged_reorders: list[FlaggedReorder] = []
    decisions: list[RecordedDecision] = []


# Playing back


def load_recordings(directory: Path = RECORDINGS_DIRECTORY) -> list[Recording]:
    """Every Recording stored in the directory, in file name order."""
    return [Recording.model_validate_json(p.read_text()) for p in sorted(directory.glob("*.json"))]


def step_count(recording: Recording) -> int:
    return len(recording.ops_days) * len(ReplayStage)


def replay_step(recording: Recording, position: int) -> ReplayStep:
    """The step at position (0-based): each recorded Ops Day's stages in pipeline order."""
    total = step_count(recording)
    if not 0 <= position < total:
        raise ValueError(f"step {position} is outside the Recording's {total} steps")
    recorded = recording.ops_days[position // len(ReplayStage)]
    stage = list(ReplayStage)[position % len(ReplayStage)]
    outcome = recorded.outcome
    step = ReplayStep(
        position=position,
        total=total,
        day=outcome.day,
        stage=stage,
        title=f"Ops Day {outcome.day.isoformat()}: {STAGE_TITLES[stage]}",
        narration="",
    )
    match stage:
        case ReplayStage.INTAKE:
            entries = [e for e in outcome.audit_entries if _intake_entry(e)]
            return step.model_copy(
                update={
                    "narration": _intake_narration(outcome.uploads, entries, outcome.uploader_messages),
                    "uploads": outcome.uploads,
                    "uploader_messages": outcome.uploader_messages,
                    "audit_entries": entries,
                }
            )
        case ReplayStage.LOAD:
            loaded = [u for u in outcome.uploads if u.status in _LOADED]
            return step.model_copy(
                update={
                    "narration": _load_narration(loaded, outcome.uploads, recorded.sales),
                    "uploads": loaded,
                    "sales": recorded.sales,
                    "inventory": recorded.inventory,
                }
            )
        case ReplayStage.DETECTION:
            return step.model_copy(
                update={
                    "narration": _detection_narration(outcome.anomalies, outcome.cleared_anomalies),
                    "anomalies": outcome.anomalies,
                    "cleared_anomalies": outcome.cleared_anomalies,
                }
            )
        case ReplayStage.INVESTIGATION:
            return step.model_copy(
                update={
                    "narration": _investigation_narration(outcome.investigations),
                    "investigations": outcome.investigations,
                }
            )
        case ReplayStage.ACTIONS:
            entries = [e for e in outcome.audit_entries if not _intake_entry(e)]
            return step.model_copy(
                update={
                    "narration": _actions_narration(
                        entries, outcome.reorders, outcome.approval_queue, recorded.decisions, outcome
                    ),
                    "audit_entries": entries + [e for d in recorded.decisions for e in d.audit_entries],
                    "reorders": outcome.reorders,
                    "approval_queue": outcome.approval_queue,
                    "withdrawn_reorders": outcome.withdrawn_reorders,
                    "flagged_reorders": outcome.flagged_reorders,
                    "decisions": recorded.decisions,
                }
            )


def _intake_entry(entry: AuditEntry) -> bool:
    return entry.action in _INTAKE_ACTIONS and entry.investigation_id is None


def _count(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def _intake_narration(
    uploads: list[UploadOutcome], entries: list[AuditEntry], messages: list[UploaderMessage]
) -> str:
    if not uploads:
        return "No Uploads arrived for Intake to check."
    by_status = {s: sum(1 for u in uploads if u.status is s) for s in UploadStatus}
    parts = [f"{n} {s.value.replace('_', '-')}" for s, n in by_status.items() if n]
    safe_fixes = sum(1 for e in entries if e.action is AuditAction.SAFE_FIX)
    return (
        f"The Intake agent checked {_count(len(uploads), 'Upload')} ({', '.join(parts)}). "
        f"It applied {_count(safe_fixes, 'Safe Fix', 'Safe Fixes')} and sent "
        f"{_count(len(messages), 'message')} to Uploaders."
    )


def _load_narration(
    loaded: list[UploadOutcome], uploads: list[UploadOutcome], sales: list[SalesBySalesChannel]
) -> str:
    held = len(uploads) - len(loaded)
    net = sum(s.net_sales for s in sales)
    return (
        f"{_count(len(loaded), 'Upload')} loaded into the BI data; {held} held out "
        f"(Quarantined or Superseded). Accepted net sales on the days they cover: {net:,.2f}."
    )


def _detection_narration(anomalies: list[Anomaly], cleared: list[ClearedAnomaly]) -> str:
    flagged = _count(len(anomalies), "Anomaly", "Anomalies") if anomalies else "no Anomalies"
    text = f"Deterministic statistics flagged {flagged}; no model is involved in detection."
    if cleared:
        text += f" {_count(len(cleared), 'earlier Anomaly', 'earlier Anomalies')} cleared after a Supersede."
    return text


def _investigation_narration(investigations: list[Investigation]) -> str:
    if not investigations:
        return "Nothing to investigate."
    problems = sum(1 for i in investigations if i.data_problem is not None)
    text = (
        f"The Analyst agent investigated {_count(len(investigations), 'Anomaly', 'Anomalies')} "
        "with read-only tools."
    )
    if problems:
        text += f" {problems} concluded Data Problem and sent Uploads back to Intake."
    return text


def _actions_narration(
    entries: list[AuditEntry],
    reorders: list[QueuedReorder],
    queue: list[QueuedReorder],
    decisions: list[RecordedDecision],
    outcome: OpsDayOutcome,
) -> str:
    alerts = sum(1 for e in entries if e.action is AuditAction.ALERT)
    parts = [f"{_count(alerts, 'alert')} posted"]
    if reorders:
        statuses = ", ".join(f"{r.action_id} {r.status.value.replace('_', '-')}" for r in reorders)
        parts.append(f"{_count(len(reorders), 'Reorder')} proposed ({statuses})")
    parts.append(f"{len(queue)} waiting in the Approval Queue")
    if outcome.flagged_reorders:
        parts.append(f"{_count(len(outcome.flagged_reorders), 'placed Reorder')} flagged for a person")
    text = "The Ops agent proposed and the Action policy decided: " + "; ".join(parts) + "."
    for d in decisions:
        r = d.reorder
        text += f" Afterwards {r.decided_by} {r.status.value} {r.action_id}"
        text += f", placing Reorder {r.reorder_id} in the ERP." if r.reorder_id else "."
    return text


# Recording


class RecordingPlan(BaseModel):
    """What to run through a seeded sandbox to make one Recording."""

    model_config = ConfigDict(frozen=True)

    recording_id: str
    title: str
    description: str
    seed: int
    first_day: date
    days: int
    run_days: int | None = None
    # Earlier Ops Days run to build up history but are not kept.
    record_from: date
    sales_channels: list[str]
    upload_kinds: list[UploadKind] = list(UploadKind)
    defects: list[DefectPlan] = []
    resubmissions: list[ResubmissionPlan] = []
    anomalies: list[AnomalyPlan] = []
    auto_approval_limit: float = DEFAULT_AUTO_APPROVAL_LIMIT
    # The decision a person takes on every pending Reorder after the last Ops Day, if any.
    decide_pending: Decision | None = None


RECORDING_PLANS: list[RecordingPlan] = [
    RecordingPlan(
        recording_id="01-defect-day",
        title="Defect day: Safe Fixes, a Quarantine and a corrected resend",
        description=(
            "ST02 sends sales with a renamed column, which Intake fixes safely. ST03 sends sales with a "
            "missing column, which is Quarantined with a message to its Uploader, who resends a "
            "corrected Upload that Supersedes it the next Ops Day. The Online Shop's Stock Snapshot "
            "arrives with the wrong delimiter."
        ),
        seed=7,
        first_day=date(2026, 11, 1),
        days=3,
        record_from=date(2026, 11, 1),
        sales_channels=["ST02", "ST03", "ONLINE"],
        defects=[
            DefectPlan(
                sales_channel="ST02",
                day=date(2026, 11, 2),
                upload_kind=UploadKind.SALES,
                defect_kind=DefectKind.RENAMED_COLUMN,
            ),
            DefectPlan(
                sales_channel="ST03",
                day=date(2026, 11, 2),
                upload_kind=UploadKind.SALES,
                defect_kind=DefectKind.MISSING_COLUMN,
            ),
            DefectPlan(
                sales_channel="ONLINE",
                day=date(2026, 11, 3),
                upload_kind=UploadKind.INVENTORY,
                defect_kind=DefectKind.WRONG_DELIMITER,
            ),
        ],
        resubmissions=[
            ResubmissionPlan(
                sales_channel="ST03",
                day=date(2026, 11, 2),
                upload_kind=UploadKind.SALES,
                resubmission_kind=ResubmissionKind.CORRECTED,
            )
        ],
    ),
    RecordingPlan(
        recording_id="02-stockout-auto-approved-reorder",
        title="Stockout risk: a Reorder under the Auto-approval Limit",
        description=(
            "A demand surge drains a SKU at ST02 until its days of cover fall below its Lead Time. "
            "The Analyst investigates, the Ops agent proposes a Reorder, and because its cost is "
            "under the Auto-approval Limit the Action policy approves it by rule and places it in "
            "the ERP."
        ),
        seed=42,
        first_day=date(2026, 3, 2),
        days=11,
        run_days=9,
        record_from=date(2026, 3, 9),
        sales_channels=["ST02"],
        anomalies=[AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 3, 12))],
        auto_approval_limit=100_000.0,
    ),
    RecordingPlan(
        recording_id="03-stockout-reorder-approval",
        title="Stockout risk: a Reorder waits for Approval",
        description=(
            "A demand surge drains a SKU at ST05. With an Auto-approval Limit of 0 the proposed "
            "Reorder waits in the Approval Queue; the inventory planner approves it, which places "
            "it in the ERP and records it in the Audit Log."
        ),
        seed=42,
        first_day=date(2026, 3, 2),
        days=11,
        run_days=9,
        record_from=date(2026, 3, 9),
        sales_channels=["ST05"],
        anomalies=[AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST05", day=date(2026, 3, 12))],
        auto_approval_limit=0.0,
        decide_pending=Decision.APPROVE,
    ),
]


def record(plan: RecordingPlan, models: Models, model_label: str) -> Recording:
    """Run the plan through the Ops Day boundary and keep its outcomes."""
    kept: list[RecordedOpsDay] = []

    def keep(ops_day: OpsDay, outcome: OpsDayOutcome) -> None:
        if outcome.day >= plan.record_from:
            kept.append(_snapshot(ops_day, outcome))

    with tempfile.TemporaryDirectory(prefix="cobalt-home-recording-") as directory:
        ops_day = build_sandbox(
            seed=plan.seed,
            models=models,
            first_day=plan.first_day,
            days=plan.days,
            defects=plan.defects,
            resubmissions=plan.resubmissions,
            anomalies=plan.anomalies,
            upload_directory=Path(directory),
            sales_channels=plan.sales_channels,
            upload_kinds=plan.upload_kinds,
            auto_approval_limit=plan.auto_approval_limit,
            run_days=plan.run_days,
            on_ops_day=keep,
        )
        if plan.decide_pending is not None and kept:
            decisions = [_decide(ops_day, item, plan.decide_pending) for item in ops_day.approval_queue()]
            kept[-1] = kept[-1].model_copy(update={"decisions": decisions})
    return Recording(
        recording_id=plan.recording_id,
        title=plan.title,
        description=plan.description,
        model=model_label,
        seed=plan.seed,
        auto_approval_limit=plan.auto_approval_limit,
        ops_days=kept,
    )


def _snapshot(ops_day: OpsDay, outcome: OpsDayOutcome) -> RecordedOpsDay:
    days = {u.day for u in outcome.uploads} | {outcome.day}
    return RecordedOpsDay(
        outcome=outcome,
        sales=[s for s in ops_day.sales_by_sales_channel() if s.day in days],
        inventory=[i for i in ops_day.inventory_by_sales_channel() if i.day in days],
    )


def _decide(ops_day: OpsDay, item: QueuedReorder, decision: Decision) -> RecordedDecision:
    before = {e.entry_id for e in ops_day.audit_log()}
    if decision is Decision.APPROVE:
        decided = ops_day.approve(item.action_id, approved_by=RECORDED_APPROVER)
    else:
        decided = ops_day.reject(item.action_id, rejected_by=RECORDED_APPROVER)
    new = sorted((e for e in ops_day.audit_log() if e.entry_id not in before), key=lambda e: e.entry_id)
    return RecordedDecision(reorder=decided, audit_entries=new)


def write_recording(recording: Recording, directory: Path = RECORDINGS_DIRECTORY) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{recording.recording_id}.json"
    path.write_text(recording.model_dump_json(indent=1) + "\n")
    return path


def recording_models(
    env: Mapping[str, str],
    requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
    build_model: Callable[[str], Model] = infer_model,
) -> tuple[Models, str]:
    """The environment's real model, paced for its free tier, or the offline scripted model."""
    name = model_name_from_environment(env)
    if name is None:
        return models_from_environment(env)
    model = ThrottledModel(build_model(name), Throttle(requests_per_minute))
    return Models(intake=model, analyst=model, ops=model), name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record Ops Days for Replay Mode.")
    parser.add_argument("--only", action="append", help="record only this recording id (repeatable)")
    parser.add_argument("--rpm", type=float, default=DEFAULT_REQUESTS_PER_MINUTE)
    parser.add_argument("--output", type=Path, default=RECORDINGS_DIRECTORY)
    args = parser.parse_args(argv)
    models, label = recording_models(os.environ, args.rpm)
    plans = [p for p in RECORDING_PLANS if not args.only or p.recording_id in args.only]
    for plan in plans:
        print(f"Recording {plan.recording_id} with {label}...", file=sys.stderr)
        recording = record(plan, models, label)
        path = write_recording(recording, args.output)
        reorders = sum(len(d.outcome.reorders) for d in recording.ops_days)
        print(f"  wrote {path} ({len(recording.ops_days)} Ops Days, {reorders} Reorders)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
