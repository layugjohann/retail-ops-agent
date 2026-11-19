"""Hours Saved: the staff time the prototype saved, from the Audit Log and the documented baseline.

The baseline is the machine-readable part of the (simulated) discovery documents in
docs/discovery/: for each kind of task the Client's staff did by hand, the Audit Log Action that now
does it, the minutes it took each time, how often it came up, and the public source or stated
assumption behind the minutes.

Hours Saved = for each baseline task, the Audit Log entries of its Action that still stand (not
undone) times its minutes each time. Undos, and entries an undo reversed, save nothing.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from retail_ops_agent.audit_log import AuditAction, AuditEntry

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"


class Basis(StrEnum):
    # The minutes come from a public source, named in source.
    SOURCE = "source"
    # The minutes are the engagement's stated assumption, explained in reasoning.
    ASSUMPTION = "assumption"


class BaselineTask(BaseModel):
    """One manual task, timed."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    task: str
    persona: str
    # The Audit Log Action that now does this task; each standing entry of it counts once.
    audit_action: AuditAction
    minutes_each: float
    how_often: str
    basis: Basis
    source: str | None = None
    reasoning: str

    @model_validator(mode="after")
    def _cited_or_assumed(self) -> BaselineTask:
        if self.minutes_each <= 0:
            raise ValueError(f"{self.task_id}: minutes each time must be positive")
        if self.basis is Basis.SOURCE and not self.source:
            raise ValueError(f"{self.task_id}: a timing based on a source must name it")
        return self


class Baseline(BaseModel):
    """The manual timings Hours Saved is computed from. Simulated: written for the fictional Client."""

    model_config = ConfigDict(frozen=True)

    simulated: bool
    label: str
    tasks: list[BaselineTask]

    @model_validator(mode="after")
    def _one_task_per_action(self) -> Baseline:
        actions = [t.audit_action for t in self.tasks]
        if len(actions) != len(set(actions)):
            raise ValueError("each Audit Log Action may match at most one baseline task")
        return self


class HoursSavedLine(BaseModel):
    """One baseline task's share of Hours Saved, with the assumption behind it."""

    model_config = ConfigDict(frozen=True)

    task: BaselineTask
    matching_entries: int
    minutes_saved: float


class HoursSaved(BaseModel):
    """Hours Saved and every input behind it, to show next to the figure."""

    model_config = ConfigDict(frozen=True)

    label: str
    lines: list[HoursSavedLine]
    # Entries of a baseline task's Action left out because an undo reversed them.
    undone_entries: int

    @property
    def minutes(self) -> float:
        return sum(line.minutes_saved for line in self.lines)

    @property
    def hours(self) -> float:
        return round(self.minutes / 60, 2)


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    return Baseline.model_validate_json(path.read_text())


def hours_saved(entries: list[AuditEntry], baseline: Baseline) -> HoursSaved:
    """Hours Saved from Audit Log entries, in any order.

    Which entries an undo has reversed is worked out from the entries themselves, as the Audit Log
    does: an entry is undone while some undo of it is itself not undone.
    """
    ordered = sorted(entries, key=lambda e: e.entry_id)
    undone: set[int] = set()
    for entry in reversed(ordered):
        if entry.undoes is not None and entry.entry_id not in undone:
            undone.add(entry.undoes)
    lines: list[HoursSavedLine] = []
    undone_entries = 0
    for task in baseline.tasks:
        of_action = [e for e in ordered if e.action is task.audit_action]
        standing = [e for e in of_action if e.entry_id not in undone]
        undone_entries += len(of_action) - len(standing)
        lines.append(
            HoursSavedLine(
                task=task,
                matching_entries=len(standing),
                minutes_saved=len(standing) * task.minutes_each,
            )
        )
    return HoursSaved(label=baseline.label, lines=lines, undone_entries=undone_entries)
