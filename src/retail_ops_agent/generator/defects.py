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
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.defects import DefectKind, has_safe_fix
from retail_ops_agent.generator.formats import upload_csv
from retail_ops_agent.generator.history import History
from retail_ops_agent.generator.resubmissions import PlantedResubmission, ResubmissionPlan, resubmission_csv
from retail_ops_agent.upload_formats import (
    MAX_PLAUSIBLE_DAILY_UNITS,
    MAX_PLAUSIBLE_ON_HAND,
    UploadFormat,
    format_for,
)
from retail_ops_agent.uploads import UploadKind, UploadStatus

# The Defect kinds the generator can plant so far.
PLANTABLE_DEFECTS = frozenset(
    {
        DefectKind.RENAMED_COLUMN,
        DefectKind.STRAY_WHITESPACE,
        DefectKind.WRONG_DELIMITER,
        DefectKind.BYTE_ORDER_MARK,
        DefectKind.MISSING_COLUMN,
        DefectKind.SWAPPED_COLUMNS,
        DefectKind.DUPLICATE_DAY,
        DefectKind.IMPOSSIBLE_QUANTITY,
        DefectKind.UNKNOWN_SKU,
        DefectKind.DATE_MISMATCH,
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

# Per format: pairs of columns whose values cannot pass for each other's, so a swap is visible.
_SWAPPABLE: dict[UploadFormat, tuple[tuple[str, str], ...]] = {
    UploadFormat.STORE_SALES: (("date", "store_code"), ("quantity_sold", "net_sales")),
    UploadFormat.STORE_INVENTORY: (("date", "store_code"), ("sku", "on_hand")),
    UploadFormat.ONLINE_SHOP_ORDER_LINES: (("quantity", "line_total"), ("sku", "status")),
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: (("SKU Code", "Available Quantity"),),
}
# Per format: the column holding the day, the SKU, and the quantity of each row.
_DAY_COLUMN = {
    UploadFormat.STORE_SALES: "date",
    UploadFormat.STORE_INVENTORY: "date",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "created_at",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "Snapshot Time",
}
_SKU_COLUMN = {
    UploadFormat.STORE_SALES: "sku",
    UploadFormat.STORE_INVENTORY: "sku",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "sku",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "SKU Code",
}
_QUANTITY_COLUMN = {
    UploadFormat.STORE_SALES: "quantity_sold",
    UploadFormat.STORE_INVENTORY: "on_hand",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "quantity",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "Available Quantity",
}
# The column a repeated day is reported at: what identifies a row within the day.
_REPEAT_COLUMN = {
    UploadFormat.STORE_SALES: "sku",
    UploadFormat.STORE_INVENTORY: "sku",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "order_id",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "SKU Code",
}


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
    resubmissions: tuple[PlantedResubmission, ...] = ()

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
    _resubmitted: dict[tuple[str, date, UploadKind], str] = field(
        default_factory=dict[tuple[str, date, UploadKind], str]
    )

    def content(self, sales_channel: str, day: date, kind: UploadKind) -> str:
        """The Upload as first submitted, with any planted Defects."""
        planted = self._planted.get((sales_channel, day, kind))
        return planted if planted is not None else upload_csv(self.history, sales_channel, day, kind)

    def resubmission(self, sales_channel: str, day: date, kind: UploadKind) -> str:
        """The planned resubmission that replaces the Upload."""
        try:
            return self._resubmitted[(sales_channel, day, kind)]
        except KeyError:
            raise KeyError(
                f"no resubmission planned for {sales_channel} {day.isoformat()} {kind.value}"
            ) from None


def generate_uploads(
    history: History,
    plans: Sequence[DefectPlan] = (),
    resubmissions: Sequence[ResubmissionPlan] = (),
) -> GeneratedUploads:
    """Plant each planned Defect and resubmission; Uploads with no Defect planted are the clean
    ones from the history."""
    resubmitted: dict[tuple[str, date, UploadKind], str] = {}
    planted_resubmissions: list[PlantedResubmission] = []
    for resubmission in resubmissions:
        key = (resubmission.sales_channel, resubmission.day, resubmission.upload_kind)
        if key in resubmitted:
            raise ValueError(f"more than one resubmission planned for {key}")
        resubmitted[key], truth = resubmission_csv(history, resubmission)
        planted_resubmissions.append(truth)
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
        channel, day, kind = key
        draft = _Draft.parse(
            upload_csv(history, *key),
            upload_format=format_for(_channel_kind(history, channel), kind),
            day=day,
            known_skus=frozenset(s.code for s in history.catalog.skus),
        )
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
        ground_truth=GroundTruth(
            seed=history.catalog.seed,
            days=history.days,
            defects=tuple(planted),
            resubmissions=tuple(planted_resubmissions),
        ),
        _planted=planted_contents,
        _resubmitted=resubmitted,
    )


@dataclass
class _Draft:
    """An Upload being edited: the expected header, the header as it will be sent, and the rows."""

    upload_format: UploadFormat
    day: date
    known_skus: frozenset[str]
    columns: list[str]
    header: list[str]
    rows: list[list[str]]
    delimiter: str = ","
    byte_order_mark: bool = False

    @classmethod
    def parse(
        cls, content: str, *, upload_format: UploadFormat, day: date, known_skus: frozenset[str]
    ) -> _Draft:
        header, *rows = list(csv.reader(io.StringIO(content)))
        return cls(
            upload_format=upload_format,
            day=day,
            known_skus=known_skus,
            columns=list(header),
            header=list(header),
            rows=rows,
        )

    def index(self, column: str) -> int:
        if column not in self.columns:
            raise ValueError(f"the Upload has no {column} column")
        return self.columns.index(column)

    def random_row(self, rng: random.Random) -> int:
        if not self.rows:
            raise ValueError("the Upload has no rows")
        return rng.randrange(len(self.rows))

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


def _missing_column(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    index = rng.randrange(len(draft.columns))
    column = draft.columns.pop(index)
    draft.header.pop(index)
    for row in draft.rows:
        del row[index]
    return None, column


def _swapped_columns(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    """Swap the values of two columns that cannot pass for each other, under unchanged headers."""
    first, second = rng.choice(_SWAPPABLE[draft.upload_format])
    a, b = draft.index(first), draft.index(second)
    for row in draft.rows:
        row[a], row[b] = row[b], row[a]
    return 1, first


def _duplicate_day(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    """Send the day twice in one file: every row again after the last."""
    if not draft.rows:
        raise ValueError("the Upload has no rows to repeat")
    first_repeat = len(draft.rows) + 2
    draft.rows.extend([list(row) for row in draft.rows])
    return first_repeat, _REPEAT_COLUMN[draft.upload_format]


def _impossible_quantity(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    column = _QUANTITY_COLUMN[draft.upload_format]
    index = draft.random_row(rng)
    high = (
        MAX_PLAUSIBLE_DAILY_UNITS
        if draft.upload_format in (UploadFormat.STORE_SALES, UploadFormat.ONLINE_SHOP_ORDER_LINES)
        else MAX_PLAUSIBLE_ON_HAND
    )
    value = rng.choice((-rng.randint(1, 40), rng.randint(high * 5, high * 50)))
    draft.rows[index][draft.index(column)] = str(value)
    return index + 2, column


def _unknown_sku(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    column = _SKU_COLUMN[draft.upload_format]
    index = draft.random_row(rng)
    cell = draft.index(column)
    known = draft.rows[index][cell]
    candidates = [
        known.replace("0", "O", 1),  # a letter O typed for a zero
        known[:-1],  # a digit dropped
        f"{known.split('-')[0]}-{rng.randint(5000, 9999)}",  # a SKU not in the catalog yet
    ]
    draft.rows[index][cell] = rng.choice([c for c in candidates if c not in draft.known_skus])
    return index + 2, column


def _date_mismatch(draft: _Draft, rng: random.Random) -> tuple[int | None, str | None]:
    """Send another day's file: every row dated a day or two before the Upload day."""
    column = _DAY_COLUMN[draft.upload_format]
    cell = draft.index(column)
    other = (draft.day - timedelta(days=rng.choice((1, 2)))).isoformat()
    for row in draft.rows:
        row[cell] = other + row[cell][len(other) :]
    return None, column


def _channel_kind(history: History, sales_channel: str) -> SalesChannelKind:
    for channel in history.catalog.sales_channels:
        if channel.code == sales_channel:
            return channel.kind
    raise ValueError(f"{sales_channel!r} is not a Sales Channel in the catalog")


_PLANTERS = {
    DefectKind.RENAMED_COLUMN: _rename_column,
    DefectKind.STRAY_WHITESPACE: _stray_whitespace,
    DefectKind.WRONG_DELIMITER: _wrong_delimiter,
    DefectKind.BYTE_ORDER_MARK: _byte_order_mark,
    DefectKind.MISSING_COLUMN: _missing_column,
    DefectKind.SWAPPED_COLUMNS: _swapped_columns,
    DefectKind.DUPLICATE_DAY: _duplicate_day,
    DefectKind.IMPOSSIBLE_QUANTITY: _impossible_quantity,
    DefectKind.UNKNOWN_SKU: _unknown_sku,
    DefectKind.DATE_MISMATCH: _date_mismatch,
}
