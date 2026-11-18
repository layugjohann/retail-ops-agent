"""Golden Scenarios: seeded Ops Days with planted items and the outcomes Intake should reach.

A Golden Scenario is one JSON file. The generator plants its Defects and resubmissions from its
seed, so the ground truth is exact and the same every time it is run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import DefectPlan, ResubmissionPlan
from retail_ops_agent.uploads import UploadKind, UploadStatus

FIRST_SUBMISSION = 1


class PlantedItems(BaseModel):
    """What the generator plants in the Scenario's Uploads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    defects: tuple[DefectPlan, ...] = ()
    resubmissions: tuple[ResubmissionPlan, ...] = ()


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

    Every listed Sales Channel submits each listed kind of Upload on every day in the range. Uploads
    not in expected are expected to be accepted with no Defects.
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
    planted: PlantedItems = PlantedItems()
    expected: tuple[ExpectedUpload, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if self.last_day < self.first_day:
            raise ValueError("last_day is before first_day")
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

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1

    def day_range(self) -> list[date]:
        return [self.first_day + timedelta(days=offset) for offset in range(self.days)]

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
