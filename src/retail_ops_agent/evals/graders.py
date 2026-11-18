"""Deterministic Intake graders: they score what the Ops Day boundary shows against the ground truth.

Each grader reads only the boundary's views (Upload statuses, Audit Log, Uploader messages, BI
data) and the generator's ground truth, never Intake's internals.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.audit_log import AuditAction
from retail_ops_agent.defects import has_safe_fix
from retail_ops_agent.evals.scenarios import FIRST_SUBMISSION, Scenario, UploadKey
from retail_ops_agent.generator import GeneratedUploads, PlantedDefect, ResubmissionKind
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus
from retail_ops_agent.views import UploadOutcome

# Net sales are money: totals within a cent agree.
_MONEY_TOLERANCE = 0.01


class GraderResult(BaseModel):
    """One grader's verdict on one Scenario.

    score is the share of what it checked that was right, or None if there was nothing to check.
    counts holds the raw numbers behind it, so a run's totals can be added up across Scenarios.
    """

    model_config = ConfigDict(frozen=True)

    grader: str
    passed: bool
    score: float | None
    counts: dict[str, int]
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observed:
    """What the Ops Day boundary shows at the end of a Scenario, with each Upload's submission number."""

    uploads: dict[UploadKey, UploadOutcome]
    ops_day: OpsDay


def observe(ops_day: OpsDay) -> Observed:
    """Number each Upload within its Sales Channel, day and kind by following the Superseded chain."""
    by_slot: dict[tuple[str, date, UploadKind], list[UploadOutcome]] = {}
    for upload in ops_day.upload_statuses():
        by_slot.setdefault((upload.sales_channel, upload.day, upload.kind), []).append(upload)
    numbered: dict[UploadKey, UploadOutcome] = {}
    for (channel, day, kind), uploads in by_slot.items():
        by_id = {u.upload_id: u for u in uploads}
        replacements = {u.superseded_by for u in uploads}
        # The first Upload is the one that replaced no other; follow what replaced it.
        firsts = [u for u in uploads if u.upload_id not in replacements]
        chain: list[UploadOutcome] = []
        upload = firsts[0] if len(firsts) == 1 else None
        while upload is not None and len(chain) < len(uploads):
            chain.append(upload)
            upload = by_id.get(upload.superseded_by) if upload.superseded_by else None
        if len(chain) != len(uploads):
            chain = uploads  # Not a single chain: keep the boundary's order rather than guess.
        for number, outcome in enumerate(chain, start=FIRST_SUBMISSION):
            numbered[(channel, day, kind, number)] = outcome
    return Observed(uploads=numbered, ops_day=ops_day)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _describe(key: UploadKey) -> str:
    channel, day, kind, number = key
    return f"{channel} {day.isoformat()} {kind.value} #{number}"


def _planted_by_upload(
    scenario: Scenario, generated: GeneratedUploads
) -> dict[UploadKey, list[PlantedDefect]]:
    """Planted Defects are in the first submission; resubmissions are clean."""
    planted: dict[UploadKey, list[PlantedDefect]] = {key: [] for key in scenario.submitted()}
    for defect in generated.ground_truth.defects:
        planted[(defect.sales_channel, defect.day, defect.upload_kind, FIRST_SUBMISSION)].append(defect)
    return planted


def grade_defect_detection(
    scenario: Scenario, generated: GeneratedUploads, observed: Observed
) -> GraderResult:
    """Defect precision and recall: a reported Defect counts only with the planted kind, row and column."""
    true_positives = false_positives = false_negatives = 0
    findings: list[str] = []
    for key, planted in _planted_by_upload(scenario, generated).items():
        expected = Counter((d.defect_kind, d.row, d.column) for d in planted)
        outcome = observed.uploads.get(key)
        reported = Counter((d.kind, d.row, d.column) for d in (outcome.defects if outcome else []))
        hits = expected & reported
        true_positives += hits.total()
        for kind, row, column in (reported - hits).elements():
            false_positives += 1
            findings.append(
                f"{_describe(key)}: reported {kind.value} at row {row}, column {column} not planted"
            )
        for kind, row, column in (expected - hits).elements():
            false_negatives += 1
            findings.append(f"{_describe(key)}: missed planted {kind.value} at row {row}, column {column}")
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    return GraderResult(
        grader="defect_detection",
        passed=false_positives == 0 and false_negatives == 0,
        score=None
        if precision is None and recall is None
        else min(x for x in (precision, recall) if x is not None),
        counts={
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        },
        findings=tuple(findings),
    )


def grade_upload_status(scenario: Scenario, observed: Observed) -> GraderResult:
    """Every Upload ends in its expected status, and only Quarantined Uploads' Uploaders are messaged,
    once each."""
    expected = scenario.expected_outcomes()
    findings: list[str] = []
    right = 0
    for key, outcome in expected.items():
        actual = observed.uploads.get(key)
        if actual is None:
            findings.append(f"{_describe(key)}: never processed")
        elif actual.status is not outcome.status:
            findings.append(f"{_describe(key)}: {actual.status.value}, expected {outcome.status.value}")
        else:
            right += 1
    for key in observed.uploads.keys() - expected.keys():
        findings.append(f"{_describe(key)}: not an Upload the Scenario sent")
    messaged = Counter(m.upload_id for m in observed.ops_day.uploader_messages())
    for key, actual in observed.uploads.items():
        quarantined = UploadStatus.QUARANTINED in {change.status for change in actual.history}
        count = messaged[actual.upload_id]
        if quarantined and count != 1:
            findings.append(f"{_describe(key)}: Quarantined, but its Uploader got {count} messages")
        if not quarantined and count:
            findings.append(f"{_describe(key)}: never Quarantined, but its Uploader got a message")
    return GraderResult(
        grader="upload_status",
        passed=not findings,
        score=_ratio(right, len(expected)),
        counts={"right": right, "expected": len(expected)},
        findings=tuple(findings),
    )


def grade_no_clean_quarantine(
    scenario: Scenario, generated: GeneratedUploads, observed: Observed
) -> GraderResult:
    """No Upload without a planted Defect is ever Quarantined."""
    clean = [key for key, planted in _planted_by_upload(scenario, generated).items() if not planted]
    quarantined = [
        key
        for key in clean
        if key in observed.uploads
        and UploadStatus.QUARANTINED in {change.status for change in observed.uploads[key].history}
    ]
    return GraderResult(
        grader="no_clean_quarantine",
        passed=not quarantined,
        score=_ratio(len(clean) - len(quarantined), len(clean)),
        counts={"clean": len(clean), "quarantined": len(quarantined)},
        findings=tuple(f"{_describe(key)}: clean Upload Quarantined" for key in quarantined),
    )


def _loaded(ops_day: OpsDay, channel: str, day: date, kind: UploadKind) -> tuple[int, float] | None:
    """Units (sold, or on hand) and net sales in the BI data for one Sales Channel, day and kind."""
    if kind is UploadKind.SALES:
        rows = [r for r in ops_day.sales_by_sales_channel() if (r.sales_channel, r.day) == (channel, day)]
        return (rows[0].quantity_sold, rows[0].net_sales) if rows else None
    stock = [r for r in ops_day.inventory_by_sales_channel() if (r.sales_channel, r.day) == (channel, day)]
    return (stock[0].on_hand, 0.0) if stock else None


def _truth(generated: GeneratedUploads, channel: str, day: date, kind: UploadKind) -> tuple[int, float]:
    if kind is UploadKind.SALES:
        rows = generated.history.sales(channel, day)
        return sum(r.quantity_sold for r in rows), round(sum(r.net_sales for r in rows), 2)
    return sum(r.on_hand for r in generated.history.inventory(channel, day)), 0.0


def _agrees(loaded: tuple[int, float] | None, truth: tuple[int, float] | None) -> bool:
    if loaded is None or truth is None:
        return loaded is None and truth is None
    return loaded[0] == truth[0] and abs(loaded[1] - truth[1]) <= _MONEY_TOLERANCE


def grade_safe_fixes(scenario: Scenario, generated: GeneratedUploads, observed: Observed) -> GraderResult:
    """Safe Fix correctness: every Upload whose planted Defects all have a Safe Fix is Safe-Fixed,
    each fix is in the Audit Log, and its rows reach the BI data exactly as the clean Upload's would.
    No Safe Fix is applied anywhere else."""
    audit = observed.ops_day.audit_log()
    fixes: dict[str, list[str]] = {}
    for entry in audit:
        if entry.action is AuditAction.SAFE_FIX and entry.upload_id and entry.defect:
            fixes.setdefault(entry.upload_id, []).append(entry.defect.kind.value)
    findings: list[str] = []
    expected_fixed = 0
    right = 0
    resubmitted = {(p.sales_channel, p.day, p.upload_kind) for p in scenario.planted.resubmissions}
    for key, planted in _planted_by_upload(scenario, generated).items():
        actual = observed.uploads.get(key)
        logged = sorted(fixes.get(actual.upload_id, [])) if actual else []
        fixable = sorted(d.defect_kind.value for d in planted if d.has_safe_fix)
        if not planted or not all(has_safe_fix(d.defect_kind) for d in planted):
            if logged:
                findings.append(
                    f"{_describe(key)}: Safe Fix applied ({', '.join(logged)}) where none was due"
                )
            continue
        expected_fixed += 1
        problems: list[str] = []
        if actual is None:
            problems.append("never processed")
        else:
            if UploadStatus.SAFE_FIXED not in {change.status for change in actual.history}:
                problems.append(f"{actual.status.value}, never Safe-Fixed")
            if logged != fixable:
                problems.append(f"Audit Log has Safe Fixes {logged}, expected {fixable}")
            channel, day, kind, _ = key
            if (channel, day, kind) not in resubmitted:
                loaded = _loaded(observed.ops_day, channel, day, kind)
                if not _agrees(loaded, _truth(generated, channel, day, kind)):
                    problems.append(f"BI data {loaded} differs from the clean Upload's")
        if problems:
            findings.append(f"{_describe(key)}: {'; '.join(problems)}")
        else:
            right += 1
    return GraderResult(
        grader="safe_fix",
        passed=not findings,
        score=_ratio(right, expected_fixed),
        counts={"right": right, "expected": expected_fixed},
        findings=tuple(findings),
    )


def grade_bi_data(scenario: Scenario, generated: GeneratedUploads, observed: Observed) -> GraderResult:
    """The BI data holds exactly the current accepted Upload for each Sales Channel, day and kind:
    nothing from a Quarantined or Superseded Upload, and nothing counted twice."""
    expected = scenario.expected_outcomes()
    changes = {
        (p.sales_channel, p.day, p.upload_kind): p
        for p in generated.ground_truth.resubmissions
        if p.resubmission_kind is ResubmissionKind.CHANGED
    }
    findings: list[str] = []
    slots = list(dict.fromkeys((channel, day, kind) for channel, day, kind, _ in expected))
    right = 0
    for channel, day, kind in slots:
        last = max(n for c, d, k, n in expected if (c, d, k) == (channel, day, kind))
        truth: tuple[int, float] | None = None
        if expected[(channel, day, kind, last)].status is not UploadStatus.QUARANTINED:
            units, net_sales = _truth(generated, channel, day, kind)
            change = changes.get((channel, day, kind)) if last > FIRST_SUBMISSION else None
            if change:
                units, net_sales = units + change.unit_change, round(net_sales + change.net_sales_change, 2)
            truth = (units, net_sales)
        loaded = _loaded(observed.ops_day, channel, day, kind)
        if _agrees(loaded, truth):
            right += 1
        else:
            findings.append(f"{channel} {day.isoformat()} {kind.value}: BI data {loaded}, expected {truth}")
    return GraderResult(
        grader="bi_data",
        passed=not findings,
        score=_ratio(right, len(slots)),
        counts={"right": right, "expected": len(slots)},
        findings=tuple(findings),
    )


def grade_intake(scenario: Scenario, generated: GeneratedUploads, ops_day: OpsDay) -> list[GraderResult]:
    """Every deterministic Intake grader, in the order the scorecard shows them."""
    observed = observe(ops_day)
    return [
        grade_defect_detection(scenario, generated, observed),
        grade_safe_fixes(scenario, generated, observed),
        grade_no_clean_quarantine(scenario, generated, observed),
        grade_upload_status(scenario, observed),
        grade_bi_data(scenario, generated, observed),
    ]
