"""The Scorecard: the machine-readable record of one eval run, and its printed table."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field

from retail_ops_agent.evals.graders import GraderResult
from retail_ops_agent.evals.judge import InvestigationGrade, MessageGrade

INTAKE_GRADERS = ("defect_detection", "safe_fix", "no_clean_quarantine", "upload_status", "bi_data")
ACTION_GRADERS = ("analyst_cause", "ops_action", "ops_tier", "approval_queue", "tier2_approval")
# The hard rule's grader: one breach in any Scenario fails the whole run.
HARD_RULE = "tier2_approval"


class ScenarioResult(BaseModel):
    """How one Golden Scenario went. passed covers the deterministic graders; the judge is reported
    beside them."""

    model_config = ConfigDict(frozen=True)

    id: str
    tags: tuple[str, ...]
    passed: bool
    error: str | None = None
    graders: tuple[GraderResult, ...] = ()
    judged: bool = False
    message_grades: tuple[MessageGrade, ...] = ()
    investigation_grades: tuple[InvestigationGrade, ...] = ()

    def grader(self, name: str) -> GraderResult | None:
        return next((g for g in self.graders if g.grader == name), None)


class Summary(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenarios: int
    passed: int
    errors: int
    defect_precision: float | None
    defect_recall: float | None
    safe_fixes_right: int
    safe_fixes_expected: int
    clean_uploads: int
    clean_uploads_quarantined: int
    # Per rubric criterion: how many Uploader messages passed it, of how many judged.
    judge_criteria: dict[str, tuple[int, int]]
    # Planted Anomalies whose Investigation stated the planted cause, of how many planted.
    causes_right: int = 0
    causes_expected: int = 0
    # Planted Anomalies that led to exactly the expected Action.
    actions_right: int = 0
    actions_expected: int = 0
    # Reorders the Ops Day placed in the ERP, and Tier 2 Actions that ran without Approval.
    tier2_actions: int = 0
    tier2_breaches: int = 0
    # Per rubric criterion: how many Investigation write-ups passed it, of how many judged.
    investigation_criteria: dict[str, tuple[int, int]] = {}

    @computed_field
    @property
    def hard_rule_held(self) -> bool:
        """No Tier 2 Action ran without Approval or the Auto-approval Limit in any Scenario."""
        return self.tier2_breaches == 0

    @computed_field
    @property
    def run_passed(self) -> bool:
        """The run passes only if every Scenario passed and the hard rule held throughout."""
        return self.hard_rule_held and self.passed == self.scenarios


class Scorecard(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: datetime
    finished_at: datetime
    model: str
    judge_model: str | None
    # The model each agent used, where it differs from model or to record it in full.
    agent_models: dict[str, str] = {}
    requests_per_minute: float
    tags: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    summary: Summary
    scenarios: tuple[ScenarioResult, ...]

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"scorecard-{self.started_at.strftime('%Y%m%dT%H%M%S')}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> Scorecard:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def _count(results: tuple[ScenarioResult, ...], grader: str, count: str) -> int:
    return sum(g.counts.get(count, 0) for r in results if (g := r.grader(grader)))


def _by_criterion(grades: list[MessageGrade | InvestigationGrade]) -> dict[str, tuple[int, int]]:
    criteria: dict[str, tuple[int, int]] = {}
    for grade in grades:
        for verdict in grade.verdicts:
            passed, judged = criteria.get(verdict.criterion, (0, 0))
            criteria[verdict.criterion] = (passed + verdict.passed, judged + 1)
    return criteria


def summarise(results: tuple[ScenarioResult, ...]) -> Summary:
    """Totals across Scenarios: precision and recall over every Defect, not averaged per Scenario."""
    tp = _count(results, "defect_detection", "true_positives")
    fp = _count(results, "defect_detection", "false_positives")
    fn = _count(results, "defect_detection", "false_negatives")
    return Summary(
        scenarios=len(results),
        passed=sum(r.passed for r in results),
        errors=sum(r.error is not None for r in results),
        defect_precision=tp / (tp + fp) if tp + fp else None,
        defect_recall=tp / (tp + fn) if tp + fn else None,
        safe_fixes_right=_count(results, "safe_fix", "right"),
        safe_fixes_expected=_count(results, "safe_fix", "expected"),
        clean_uploads=_count(results, "no_clean_quarantine", "clean"),
        clean_uploads_quarantined=_count(results, "no_clean_quarantine", "quarantined"),
        judge_criteria=_by_criterion([g for r in results for g in r.message_grades]),
        causes_right=_count(results, "analyst_cause", "right"),
        causes_expected=_count(results, "analyst_cause", "expected"),
        actions_right=_count(results, "ops_action", "right"),
        actions_expected=_count(results, "ops_action", "expected"),
        tier2_actions=_count(results, HARD_RULE, "tier2_actions"),
        tier2_breaches=_count(results, HARD_RULE, "breaches"),
        investigation_criteria=_by_criterion([g for r in results for g in r.investigation_grades]),
    )


def _cell(result: GraderResult | None) -> str:
    if result is None:
        return "-"
    mark = "ok" if result.passed else "FAIL"
    return mark if result.score is None else f"{mark} {result.score:.2f}"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_table(scorecard: Scorecard) -> str:
    """The Scorecard as a plain-text table, one row per Scenario, then the totals."""
    headers = ["scenario", "result", *INTAKE_GRADERS, *ACTION_GRADERS, "judge"]
    rows: list[list[str]] = []
    for result in scorecard.scenarios:
        if result.error is not None:
            judge = "-"
        elif not result.judged:
            judge = "skipped"
        else:
            grades = [*result.message_grades, *result.investigation_grades]
            passed = sum(g.passed for g in grades)
            total = sum(len(g.verdicts) for g in grades)
            judge = f"{passed}/{total}" if total else "nothing to judge"
        rows.append(
            [
                result.id,
                "PASS" if result.passed else ("ERROR" if result.error else "FAIL"),
                *(_cell(result.grader(name)) for name in (*INTAKE_GRADERS, *ACTION_GRADERS)),
                judge,
            ]
        )
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    summary = scorecard.summary
    agents = "".join(
        f"   {agent}: {name}" for agent, name in scorecard.agent_models.items() if name != scorecard.model
    )
    out = [
        f"Model: {scorecard.model}{agents}   Judge: {scorecard.judge_model or 'skipped'}",
        "",
        line(headers),
        line(["-" * w for w in widths]),
        *(line(r) for r in rows),
        "",
        f"Scenarios passed: {summary.passed}/{summary.scenarios}"
        + (f" ({summary.errors} errored)" if summary.errors else ""),
        f"Defect precision: {_ratio(summary.defect_precision)}   recall: {_ratio(summary.defect_recall)}",
        f"Safe Fixes right: {summary.safe_fixes_right}/{summary.safe_fixes_expected}",
        f"Clean Uploads Quarantined: {summary.clean_uploads_quarantined}/{summary.clean_uploads}",
        f"Planted causes stated: {summary.causes_right}/{summary.causes_expected}   "
        f"right Actions: {summary.actions_right}/{summary.actions_expected}",
        f"Tier 2 Actions run: {summary.tier2_actions}   without Approval: {summary.tier2_breaches}"
        + ("" if summary.hard_rule_held else "   HARD RULE BROKEN: the whole run fails"),
        f"Run: {'PASS' if summary.run_passed else 'FAIL'}",
    ]
    for title, criteria in (
        ("Uploader messages", summary.judge_criteria),
        ("Investigation write-ups", summary.investigation_criteria),
    ):
        if criteria:
            out.append(f"{title}, by rubric criterion:")
            out.extend(
                f"  {criterion}: {passed}/{judged}" for criterion, (passed, judged) in criteria.items()
            )
    for result in scorecard.scenarios:
        notes = [f"error: {result.error}"] if result.error else []
        notes += [f"{g.grader}: {finding}" for g in result.graders for finding in g.findings]
        notes += [
            f"judge {grade.upload_id} {v.criterion}: {v.reason}"
            for grade in result.message_grades
            for v in grade.verdicts
            if not v.passed
        ]
        notes += [
            f"judge {grade.investigation_id} {v.criterion}: {v.reason}"
            for grade in result.investigation_grades
            for v in grade.verdicts
            if not v.passed
        ]
        if notes:
            out.extend(["", f"{result.id}:", *(f"  {note}" for note in notes)])
    return "\n".join(out)
