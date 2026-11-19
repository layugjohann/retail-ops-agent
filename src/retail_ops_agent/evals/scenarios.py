"""Golden Scenarios: seeded Ops Days with planted items and the outcomes the agents should reach.

A Golden Scenario is one JSON document. The generator plants its Defects, resubmissions and
Anomalies from its seed, so the ground truth is exact and the same every time it is run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_ops_agent.action_policy import DEFAULT_AUTO_APPROVAL_LIMIT
from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import ApprovalStatus
from retail_ops_agent.audit_log import ActionTier
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import AnomalyPlan, DefectPlan, LookalikePlan, ResubmissionPlan
from retail_ops_agent.ops_agent import ProposedActionKind
from retail_ops_agent.uploads import UploadKind, UploadStatus

FIRST_SUBMISSION = 1


class PlantedItems(BaseModel):
    """What the generator plants in the Scenario's Uploads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    defects: tuple[DefectPlan, ...] = ()
    resubmissions: tuple[ResubmissionPlan, ...] = ()
    anomalies: tuple[AnomalyPlan, ...] = ()
    # Chain-wide patterns that must not be blamed on one Sales Channel; no Action is expected for them.
    lookalikes: tuple[LookalikePlan, ...] = ()


class OpenReorder(BaseModel):
    """A Reorder already placed in the ERP before the Scenario's first Ops Day, outside the Approval
    Queue, for the SKU of the stockout risk planted at the Sales Channel. It stands for one the inventory
    planner placed earlier, so an Investigation should find it rather than order again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sales_channel: str
    quantity: int = Field(ge=1)


class AfterRunStepKind(StrEnum):
    # A person approves every Reorder still waiting in the Approval Queue.
    APPROVE_PENDING = "approve_pending"
    # A person rejects every Reorder still waiting in the Approval Queue.
    REJECT_PENDING = "reject_pending"
    # Simulated time moves on by the given hours, which can make pending Actions Expire.
    ADVANCE_TIME = "advance_time"


class AfterRunStep(BaseModel):
    """Something a person, or the passing of time, does at the Ops Day boundary after the last Ops Day."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: AfterRunStepKind
    hours: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _hours_only_to_advance(self) -> AfterRunStep:
        if (self.step is AfterRunStepKind.ADVANCE_TIME) != (self.hours > 0):
            raise ValueError("hours is given for advance_time, and only for it")
        return self


class SupersedeEffect(StrEnum):
    """What a planted resubmission should do to the Action taken on a planted Anomaly."""

    # The Anomaly still holds against the resubmission, and its Action stands.
    STANDS = "stands"
    # The Anomaly is cleared and its alert undone through the Audit Log.
    UNDONE = "undone"
    # The Anomaly is cleared and its pending Reorder withdrawn from the Approval Queue.
    WITHDRAWN = "withdrawn"
    # The Anomaly is cleared and its Reorder, already placed, is flagged for a person and still placed
    # in the ERP.
    FLAGGED = "flagged"


class ExpectedAction(BaseModel):
    """The Action expected for the Anomaly planted at the Sales Channel, once its Investigation is done.

    tier is the Action Tier the fixed rules give that Action. approval is how a Reorder ends the
    Scenario in the Approval Queue; an alert has none. after_supersede, for a Scenario that resends
    an Upload the Anomaly was built on, is what that resubmission should do to the Action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sales_channel: str
    anomaly_kind: AnomalyKind = AnomalyKind.STOCKOUT_RISK
    action: ProposedActionKind
    tier: ActionTier
    approval: ApprovalStatus | None = None
    after_supersede: SupersedeEffect | None = None

    @model_validator(mode="after")
    def _approval_only_for_reorders(self) -> ExpectedAction:
        if (self.action is ProposedActionKind.REORDER) != (self.approval is not None):
            raise ValueError("approval is given for a Reorder, and only for a Reorder")
        effect = self.after_supersede
        if effect is SupersedeEffect.UNDONE and self.action is not ProposedActionKind.ALERT:
            raise ValueError("only an alert is undone after a Supersede")
        if (effect is SupersedeEffect.WITHDRAWN) != (self.approval is ApprovalStatus.WITHDRAWN):
            raise ValueError("a Reorder ends withdrawn exactly when a Supersede withdraws it")
        if effect is SupersedeEffect.FLAGGED and self.approval not in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.AUTO_APPROVED,
        ):
            raise ValueError("only a placed Reorder is flagged after a Supersede")
        return self


class ExpectedUpload(BaseModel):
    """How one Upload should end the Scenario.

    submission counts the Uploads for its Sales Channel, day and kind: 1 is the first, 2 the
    resubmission that replaces it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sales_channel: str
    day: date
    upload_kind: UploadKind
    submission: int = Field(default=FIRST_SUBMISSION, ge=1)
    status: UploadStatus
    defect_kinds: tuple[DefectKind, ...] = ()

    @property
    def key(self) -> UploadKey:
        return (self.sales_channel, self.day, self.upload_kind, self.submission)


# Sales Channel, day, kind and submission number: one Upload in a Scenario.
type UploadKey = tuple[str, date, UploadKind, int]


class Scenario(BaseModel):
    """One Golden Scenario.

    The generator simulates every day from first_day to last_day. Every listed Sales Channel submits
    each listed kind of Upload on every day up to last_ops_day (last_day by default), and an Ops Day
    runs for each. Uploads not in expected are expected to be accepted with no Defects.

    auto_approval_limit is the Auto-approval Limit the Ops Day uses. open_reorders are placed in the
    ERP before the first Ops Day; after_run steps are taken after the last. expected_actions lists
    the Action expected for each planted Anomaly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str
    tags: tuple[str, ...]
    seed: int
    first_day: date
    last_day: date
    sales_channels: tuple[str, ...] = Field(min_length=1)
    upload_kinds: tuple[UploadKind, ...] = tuple(UploadKind)
    last_ops_day: date | None = None
    planted: PlantedItems = PlantedItems()
    auto_approval_limit: float = Field(default=DEFAULT_AUTO_APPROVAL_LIMIT, ge=0)
    open_reorders: tuple[OpenReorder, ...] = ()
    after_run: tuple[AfterRunStep, ...] = ()
    expected: tuple[ExpectedUpload, ...] = ()
    expected_actions: tuple[ExpectedAction, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if self.last_day < self.first_day:
            raise ValueError("last_day is before first_day")
        if not self.first_day <= self.final_ops_day <= self.last_day:
            raise ValueError("last_ops_day is outside first_day to last_day")
        self._check_anomalies()
        submitted = set(self.submitted())
        planted = [(p.sales_channel, p.day, p.upload_kind) for p in self.planted.defects] + [
            (p.sales_channel, p.day, p.upload_kind) for p in self.planted.resubmissions
        ]
        for channel, day, kind in planted:
            if (channel, day, kind, FIRST_SUBMISSION) not in submitted:
                raise ValueError(
                    f"planted item for {channel} {day} {kind} is not an Upload this Scenario sends"
                )
        keys = [e.key for e in self.expected]
        if len(keys) != len(set(keys)):
            raise ValueError("an Upload is listed more than once in expected")
        for key in keys:
            if key not in submitted:
                raise ValueError(f"expected Upload {key} is not one this Scenario sends")
        return self

    def _check_anomalies(self) -> None:
        planted = [(p.sales_channel, p.kind) for p in self.planted.anomalies]
        if len(planted) != len(set(planted)):
            raise ValueError("more than one Anomaly of a kind is planted at a Sales Channel")
        for channel, _ in planted:
            if channel not in self.sales_channels:
                raise ValueError(f"an Anomaly is planted at {channel}, which sends no Uploads")
        expected = [(e.sales_channel, e.anomaly_kind) for e in self.expected_actions]
        if sorted(expected) != sorted(planted):
            raise ValueError("expected_actions must list one Action for each planted Anomaly")
        channels = [r.sales_channel for r in self.open_reorders]
        if len(channels) != len(set(channels)):
            raise ValueError("more than one open Reorder at a Sales Channel")
        for channel in channels:
            if (channel, AnomalyKind.STOCKOUT_RISK) not in planted:
                raise ValueError(f"an open Reorder at {channel}, where no stockout risk is planted")
        if any(e.after_supersede for e in self.expected_actions) and not self.planted.resubmissions:
            raise ValueError("after_supersede is given, but no resubmission is planted")
        lookalikes = [p.kind for p in self.planted.lookalikes]
        if len(lookalikes) != len(set(lookalikes)):
            raise ValueError("more than one lookalike of a kind is planted")

    @property
    def days(self) -> int:
        """Days the generator simulates."""
        return (self.last_day - self.first_day).days + 1

    @property
    def final_ops_day(self) -> date:
        return self.last_ops_day or self.last_day

    @property
    def ops_days(self) -> int:
        """Days an Ops Day runs for, from first_day."""
        return (self.final_ops_day - self.first_day).days + 1

    def day_range(self) -> list[date]:
        """The days an Ops Day runs for."""
        return [self.first_day + timedelta(days=offset) for offset in range(self.ops_days)]

    def submitted(self) -> list[UploadKey]:
        """Every Upload the Scenario sends, resubmissions included."""
        resubmitted = {(p.sales_channel, p.day, p.upload_kind) for p in self.planted.resubmissions}
        keys: list[UploadKey] = []
        for day in self.day_range():
            for channel in self.sales_channels:
                for kind in self.upload_kinds:
                    keys.append((channel, day, kind, FIRST_SUBMISSION))
                    if (channel, day, kind) in resubmitted:
                        keys.append((channel, day, kind, FIRST_SUBMISSION + 1))
        return keys

    def expected_outcomes(self) -> dict[UploadKey, ExpectedUpload]:
        """The expected outcome of every Upload the Scenario sends, the unlisted ones as accepted."""
        listed = {e.key: e for e in self.expected}
        return {
            key: listed.get(key)
            or ExpectedUpload(
                sales_channel=key[0],
                day=key[1],
                upload_kind=key[2],
                submission=key[3],
                status=UploadStatus.ACCEPTED,
            )
            for key in self.submitted()
        }


def load_scenarios(directory: Path) -> list[Scenario]:
    """Every Scenario in the directory's JSON files, by id."""
    scenarios = [
        Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    ids = [s.id for s in scenarios]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Scenario ids used more than once: {', '.join(duplicates)}")
    return sorted(scenarios, key=lambda s: s.id)


def select_scenarios(
    scenarios: Sequence[Scenario], *, tags: Iterable[str] = (), ids: Iterable[str] = ()
) -> list[Scenario]:
    """The Scenarios with any of the tags or ids; all of them when neither is given.

    An id that names no Scenario is a mistake, not an empty selection.
    """
    tags, ids = set(tags), set(ids)
    unknown = ids - {s.id for s in scenarios}
    if unknown:
        raise ValueError(f"no Scenario with id {', '.join(sorted(unknown))}")
    if not tags and not ids:
        return list(scenarios)
    return [s for s in scenarios if s.id in ids or tags.intersection(s.tags)]
