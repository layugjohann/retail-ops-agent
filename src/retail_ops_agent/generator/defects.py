"""Plants Defects in generated Uploads and records each one in a ground-truth record (ADR 0005).

Every planted Defect is placed by a random generator seeded from the catalog seed and the plan, so
the same plan always gives the same Uploads and the same ground truth.
"""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.defects import DefectKind, has_safe_fix
from retail_ops_agent.generator.formats import upload_csv
from retail_ops_agent.generator.history import History
from retail_ops_agent.uploads import UploadKind, UploadStatus

# The Defect kinds the generator can plant so far.
PLANTABLE_DEFECTS = frozenset(
    {
        DefectKind.RENAMED_COLUMN,
        DefectKind.STRAY_WHITESPACE,
        DefectKind.WRONG_DELIMITER,
        DefectKind.BYTE_ORDER_MARK,
    }
)

# Names Uploaders really give columns, beside case and spacing variants of the expected name.
_RENAMES: dict[str, tuple[str, ...]] = {
    "date": ("Sale Date", "business_date"),
    "store_code": ("Store", "store_id"),
    "sku": ("SKU ID", "item_sku"),
    "quantity_sold": ("Qty Sold", "units_sold"),
    "net_sales": ("Net Revenue",),
    "on_hand": ("Qty On Hand", "stock_on_hand"),
    "order_id": ("Order Number", "order_no"),
    "created_at": ("Created", "order_created_at"),
    "quantity": ("Qty",),
    "line_total": ("Line Amount",),
    "status": ("Order Status",),
    "SKU Code": ("sku",),
    "Available Quantity": ("available_qty",),
    "Snapshot Time": ("as_of",),
}
_DELIMITERS = (";", "\t", "|")
_PADDING = (" ", "  ", "   ")


class DefectPlan(BaseModel):
    """One Defect to plant in the Upload a Sales Channel sends for a day and kind."""

    model_config = ConfigDict(frozen=True)

    sales_channel: str
    day: date
    upload_kind: UploadKind
    defect_kind: DefectKind


class PlantedDefect(BaseModel):
    """Ground truth for one planted Defect: where it is and what should happen to its Upload."""

    model_config = ConfigDict(frozen=True)

    sales_channel: str
    day: date
    upload_kind: UploadKind
    defect_kind: DefectKind
    # Row 1 is the header; no row or column means the Defect is in the Upload as a whole.
    row: int | None
    column: str | None
    has_safe_fix: bool
    expected_status: UploadStatus


class GroundTruth(BaseModel):
    """Everything planted in a set of generated Uploads, for tests and graders."""

    model_config = ConfigDict(frozen=True)

    seed: int
    days: tuple[date, ...]
    defects: tuple[PlantedDefect, ...]

    def write(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> GroundTruth:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class GeneratedUploads:
    """Every Sales Channel's Uploads for every day, with any planted Defects, and the ground truth."""

    history: History
    ground_truth: GroundTruth
    _planted: dict[tuple[str, date, UploadKind], str] = field(
        default_factory=dict[tuple[str, date, UploadKind], str]
    )

    def content(self, sales_channel: str, day: date, kind: UploadKind) -> str:
        planted = self._planted.get((sales_channel, day, kind))
        return planted if planted is not None else upload_csv(self.history, sales_channel, day, kind)


def generate_uploads(history: History, plans: Sequence[DefectPlan] = ()) -> GeneratedUploads:
    """Plant each planned Defect; Uploads with none planted are the clean ones from the history."""
    by_upload: dict[tuple[str, date, UploadKind], list[DefectPlan]] = {}
    for plan in plans:
        if plan.defect_kind not in PLANTABLE_DEFECTS:
            raise ValueError(f"Defect kind {plan.defect_kind} cannot be planted yet")
        if plan.day not in history.days:
            raise ValueError(f"{plan.day} is not one of the generated days")
        by_upload.setdefault((plan.sales_channel, plan.day, plan.upload_kind), []).append(plan)

    planted_contents: dict[tuple[str, date, UploadKind], str] = {}
    planted: list[PlantedDefect] = []
    for key, upload_plans in by_upload.items():
        draft = _Draft.parse(upload_csv(history, *key))
        locations: list[tuple[DefectPlan, int | None, str | None]] = []
        for plan in upload_plans:
            rng = random.Random(
                f"defect:{history.catalog.seed}:{plan.sales_channel}:{plan.day.isoformat()}:"
                f"{plan.upload_kind.value}:{plan.defect_kind.value}"
            )
            row, column = _PLANTERS[plan.defect_kind](draft, rng)
            locations.append((plan, row, column))
        planted_contents[key] = draft.render()
        expected = (
            UploadStatus.SAFE_FIXED
            if all(has_safe_fix(p.defect_kind) for p in upload_plans)
            else UploadStatus.QUARANTINED
        )
        planted.extend(
            PlantedDefect(
                sales_channel=plan.sales_channel,
                day=plan.day,
                upload_kind=plan.upload_kind,
                defect_kind=plan.defect_kind,
                row=row,
                column=column,
                has_safe_fix=has_safe_fix(plan.defect_kind),
                expected_status=expected,
            )
            for plan, row, column in locations
        )

    return GeneratedUploads(
        history=history,
        ground_truth=GroundTruth(seed=history.catalog.seed, days=history.days, defects=tuple(planted)),
        _planted=planted_contents,
    )


@dataclass
class _Draft:
    """An Upload being edited: the expected header, the header as it will be sent, and the rows."""

    columns: list[str]
    header: list[str]
    rows: list[list[str]]
    delimiter: str = ","
    byte_order_mark: bool = False

    @classmethod
    def parse(cls, content: str) -> _Draft:
        header, *rows = list(csv.reader(io.StringIO(content)))
        return cls(columns=list(header), header=list(header), rows=rows)

    def render(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=self.delimiter, lineterminator="\n")
        writer.writerow(self.header)
        writer.writerows(self.rows)
        return ("﻿" if self.byte_order_mark else "") + buffer.getvalue()


def _rename_column(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    unrenamed = [i for i, name in enumerate(draft.header) if name == draft.columns[i]]
    if not unrenamed:
        raise ValueError("every column is already renamed")
    index = rng.choice(unrenamed)
    column = draft.columns[index]
    variants = [column.upper(), column.replace("_", " ").title(), *_RENAMES.get(column, ())]
    draft.header[index] = rng.choice([v for v in variants if v != column])
    return 1, column


def _stray_whitespace(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    if not draft.rows:
        raise ValueError("the Upload has no rows to pad")
    index = rng.randrange(len(draft.rows))
    column_index = rng.randrange(len(draft.columns))
    row = draft.rows[index]
    padding = rng.choice(_PADDING)
    row[column_index] = rng.choice((padding + row[column_index], row[column_index] + padding))
    return index + 2, draft.columns[column_index]


def _wrong_delimiter(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    draft.delimiter = rng.choice(_DELIMITERS)
    return None, None


def _byte_order_mark(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    draft.byte_order_mark = True
    return None, None


_PLANTERS = {
    DefectKind.RENAMED_COLUMN: _rename_column,
    DefectKind.STRAY_WHITESPACE: _stray_whitespace,
    DefectKind.WRONG_DELIMITER: _wrong_delimiter,
    DefectKind.BYTE_ORDER_MARK: _byte_order_mark,
}
