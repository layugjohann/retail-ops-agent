"""The four Upload formats: parsing each one and normalising it to daily sales or stock levels.

Stores send one row per SKU. The Online Shop sends an Order Line export, which is totalled to daily
sales per SKU with cancelled and refunded lines left out, and a Stock Snapshot with its own headers.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.defects import Defect, DefectKind
from retail_ops_agent.safe_fixes import apply_safe_fixes
from retail_ops_agent.uploads import Upload, UploadKind

# One Sales Channel selling more than this many units of one SKU in a day is not believable.
MAX_PLAUSIBLE_DAILY_UNITS = 1000
# No Sales Channel holds more than this many units of one SKU.
MAX_PLAUSIBLE_ON_HAND = 100_000


class UploadFormat(StrEnum):
    STORE_SALES = "store_sales"
    STORE_INVENTORY = "store_inventory"
    ONLINE_SHOP_ORDER_LINES = "online_shop_order_lines"
    ONLINE_SHOP_STOCK_SNAPSHOT = "online_shop_stock_snapshot"


class OrderLineStatus(StrEnum):
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


STORE_SALES_COLUMNS = ("date", "store_code", "sku", "quantity_sold", "net_sales")
STORE_INVENTORY_COLUMNS = ("date", "store_code", "sku", "on_hand")
ONLINE_SHOP_ORDER_LINE_COLUMNS = ("order_id", "created_at", "sku", "quantity", "line_total", "status")
ONLINE_SHOP_STOCK_SNAPSHOT_COLUMNS = ("SKU Code", "Available Quantity", "Snapshot Time")

COLUMNS: dict[UploadFormat, tuple[str, ...]] = {
    UploadFormat.STORE_SALES: STORE_SALES_COLUMNS,
    UploadFormat.STORE_INVENTORY: STORE_INVENTORY_COLUMNS,
    UploadFormat.ONLINE_SHOP_ORDER_LINES: ONLINE_SHOP_ORDER_LINE_COLUMNS,
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: ONLINE_SHOP_STOCK_SNAPSHOT_COLUMNS,
}

# Per format: the column holding each row's SKU, and its quantity (units sold, or units on hand).
SKU_COLUMN: dict[UploadFormat, str] = {
    UploadFormat.STORE_SALES: "sku",
    UploadFormat.STORE_INVENTORY: "sku",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "sku",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "SKU Code",
}
QUANTITY_COLUMN: dict[UploadFormat, str] = {
    UploadFormat.STORE_SALES: "quantity_sold",
    UploadFormat.STORE_INVENTORY: "on_hand",
    UploadFormat.ONLINE_SHOP_ORDER_LINES: "quantity",
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: "Available Quantity",
}


def rows_of_sku(content: str, upload_format: UploadFormat, sku: str) -> list[int]:
    """The rows of an Upload that are for the SKU, numbered with the header as row 1.

    Read leniently, as a loaded Upload may have needed a Safe Fix: a byte order mark, another
    delimiter, or spaces around the header and values. Empty if the SKU column cannot be found.
    """
    text = content.removeprefix("\ufeff")
    first_line = text.split("\n", 1)[0]
    delimiter = next((d for d in (",", ";", "\t", "|") if d in first_line), ",")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [cell.strip().lower() for cell in next(reader, list[str]())]
    column = SKU_COLUMN[upload_format].lower()
    if column not in header:
        return []
    index = header.index(column)
    return [
        number for number, row in enumerate(reader, start=2) if index < len(row) and row[index].strip() == sku
    ]


def format_for(sales_channel_kind: SalesChannelKind, kind: UploadKind) -> UploadFormat:
    """The format a Sales Channel uses for an Upload of the given kind."""
    if sales_channel_kind is SalesChannelKind.STORE:
        return UploadFormat.STORE_SALES if kind is UploadKind.SALES else UploadFormat.STORE_INVENTORY
    if kind is UploadKind.SALES:
        return UploadFormat.ONLINE_SHOP_ORDER_LINES
    return UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT


@dataclass(frozen=True)
class SalesLine:
    """One SKU's sales for one day, whatever format it arrived in."""

    day: date
    sku: str
    quantity_sold: int
    net_sales: float


@dataclass(frozen=True)
class StockLine:
    """One SKU's units on hand at the end of one day, whatever format it arrived in."""

    day: date
    sku: str
    on_hand: int


@dataclass
class ParsedUpload:
    format: UploadFormat
    columns: list[str]
    row_count: int = 0
    # Defects with no Safe Fix: any one of them keeps the Upload out of the BI data.
    defects: list[Defect] = field(default_factory=list[Defect])
    # Defects corrected by a Safe Fix before the rows were read.
    safe_fixed: list[Defect] = field(default_factory=list[Defect])
    sales: list[SalesLine] = field(default_factory=list[SalesLine])
    stock: list[StockLine] = field(default_factory=list[StockLine])


def parse_upload(
    upload: Upload, sales_channel_kind: SalesChannelKind, known_skus: frozenset[str]
) -> ParsedUpload:
    """Apply Safe Fixes, then check the Upload's structure and content and normalise its rows.

    Sales and stock lines are only meaningful when no Defects without a Safe Fix were found.
    """
    upload_format = format_for(sales_channel_kind, upload.kind)
    fixes = apply_safe_fixes(upload.content, COLUMNS[upload_format])
    reader = csv.DictReader(io.StringIO(fixes.content))
    parsed = ParsedUpload(
        format=upload_format, columns=list(reader.fieldnames or []), safe_fixed=list(fixes.fixed)
    )
    missing = [c for c in COLUMNS[upload_format] if c not in parsed.columns]
    for column in missing:
        parsed.defects.append(
            Defect(kind=DefectKind.MISSING_COLUMN, column=column, detail=f"column {column} is missing")
        )
    rows = list(reader)
    parsed.row_count = len(rows)
    if missing:
        return parsed
    swapped = _swapped_columns(upload, upload_format, rows, known_skus)
    if swapped:
        # Every row would fail on both columns; the swap is the one thing to report.
        parsed.defects.extend(swapped)
        return parsed

    parse_row = _ROW_PARSERS[upload_format]
    repeat_column, repeats = _repeated_rows(upload_format, rows)
    repeated = {number for number, _ in repeats}
    paid: list[SalesLine] = []
    row_defects: list[Defect] = []
    for row_number, cells in enumerate(rows, start=2):  # row 1 is the header
        if row_number in repeated:
            # A repeat is never read twice, even if the Upload is released from Quarantine.
            continue
        row = _Row(upload, cells, row_number, known_skus)
        line = parse_row(row)
        row_defects.extend(row.defects)
        if isinstance(line, StockLine):
            parsed.stock.append(line)
        elif line is not None:
            paid.append(line)
    parsed.defects.extend(_merge_every_row(row_defects, len(rows) - len(repeated)))
    parsed.defects.extend(_duplicate_day(repeat_column, repeats))

    parsed.sales = _daily_totals(paid) if upload_format is UploadFormat.ONLINE_SHOP_ORDER_LINES else paid
    return parsed


class _ColumnType(StrEnum):
    DAY = "a date"
    TIMESTAMP = "a date and time"
    SALES_CHANNEL = "a store code"
    SKU = "a SKU"
    QUANTITY = "a whole number"
    AMOUNT = "an amount"
    STATUS = "an order status"


# The type of each column whose values can be told apart from other columns', for spotting swaps.
_COLUMN_TYPES: dict[UploadFormat, dict[str, _ColumnType]] = {
    UploadFormat.STORE_SALES: {
        "date": _ColumnType.DAY,
        "store_code": _ColumnType.SALES_CHANNEL,
        "sku": _ColumnType.SKU,
        "quantity_sold": _ColumnType.QUANTITY,
        "net_sales": _ColumnType.AMOUNT,
    },
    UploadFormat.STORE_INVENTORY: {
        "date": _ColumnType.DAY,
        "store_code": _ColumnType.SALES_CHANNEL,
        "sku": _ColumnType.SKU,
        "on_hand": _ColumnType.QUANTITY,
    },
    UploadFormat.ONLINE_SHOP_ORDER_LINES: {
        "created_at": _ColumnType.TIMESTAMP,
        "sku": _ColumnType.SKU,
        "quantity": _ColumnType.QUANTITY,
        "line_total": _ColumnType.AMOUNT,
        "status": _ColumnType.STATUS,
    },
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: {
        "SKU Code": _ColumnType.SKU,
        "Available Quantity": _ColumnType.QUANTITY,
        "Snapshot Time": _ColumnType.TIMESTAMP,
    },
}


def _fits(column_type: _ColumnType, value: str, upload: Upload, known_skus: frozenset[str]) -> bool:
    try:
        match column_type:
            case _ColumnType.DAY:
                date.fromisoformat(value)
            case _ColumnType.TIMESTAMP:
                datetime.fromisoformat(value)
            case _ColumnType.SALES_CHANNEL:
                return value == upload.sales_channel
            case _ColumnType.SKU:
                return value in known_skus
            case _ColumnType.QUANTITY:
                int(value)
            case _ColumnType.AMOUNT:
                float(value)
            case _ColumnType.STATUS:
                OrderLineStatus(value.lower())
    except ValueError:
        return False
    return True


def _swapped_columns(
    upload: Upload, upload_format: UploadFormat, rows: list[dict[str, str]], known_skus: frozenset[str]
) -> list[Defect]:
    """Pairs of columns where no value fits its own column but every value fits the other's."""
    if not rows:
        return []
    types = _COLUMN_TYPES[upload_format]

    def all_fit(column: str, column_type: _ColumnType) -> bool:
        return all(_fits(column_type, (r.get(column) or "").strip(), upload, known_skus) for r in rows)

    def none_fit(column: str) -> bool:
        return not any(_fits(types[column], (r.get(column) or "").strip(), upload, known_skus) for r in rows)

    order = COLUMNS[upload_format]
    defects: list[Defect] = []
    paired: set[str] = set()
    for a in order:
        for b in order:
            if a == b or a not in types or b not in types or types[a] is types[b] or {a, b} & paired:
                continue
            if none_fit(a) and all_fit(a, types[b]) and all_fit(b, types[a]):
                first, second = sorted((a, b), key=order.index)
                paired.update((a, b))
                defects.append(
                    Defect(
                        kind=DefectKind.SWAPPED_COLUMNS,
                        row=1,
                        column=first,
                        detail=(
                            f"columns {first} and {second} look swapped: {first} holds "
                            f"{types[second].value} in every row and {second} holds {types[first].value}"
                        ),
                    )
                )
    return defects


def _merge_every_row(defects: list[Defect], row_count: int) -> list[Defect]:
    """One Defect for a whole column with the same Defect on every row, as in another day's file."""
    if row_count < 2:
        return defects
    groups: dict[tuple[DefectKind, str | None, str], list[Defect]] = {}
    for defect in defects:
        groups.setdefault((defect.kind, defect.column, defect.detail), []).append(defect)
    merged: list[Defect] = []
    for (kind, column, detail), group in groups.items():
        if len({d.row for d in group}) == row_count:
            merged.append(Defect(kind=kind, column=column, detail=f"in every row, {detail}"))
        else:
            merged.extend(group)
    return merged


# The cells that identify one row of the day: the same key twice means the day is in the file twice.
_DAY_KEYS: dict[UploadFormat, tuple[str, ...]] = {
    UploadFormat.STORE_SALES: ("date", "sku"),
    UploadFormat.STORE_INVENTORY: ("date", "sku"),
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: ("SKU Code",),
}


def _repeated_rows(
    upload_format: UploadFormat, rows: list[dict[str, str]]
) -> tuple[str, list[tuple[int, int]]]:
    """The column identifying a row within the day, and each row repeating an earlier one, with it.

    Store rows and the Stock Snapshot have one row per SKU for the day. The Order Line export lists
    each order's lines together, and one order can rightly hold the same SKU twice (a paid and a
    cancelled line), so there a repeat is an order that turns up again after other orders.
    """
    repeats: list[tuple[int, int]] = []  # (row, the earlier row it repeats)
    if upload_format is UploadFormat.ONLINE_SHOP_ORDER_LINES:
        column = "order_id"
        first_row: dict[str, int] = {}
        previous: str | None = None
        repeating = False
        for number, cells in enumerate(rows, start=2):
            order_id = (cells.get(column) or "").strip()
            if order_id != previous:
                repeating = order_id in first_row
            if repeating:
                repeats.append((number, first_row[order_id]))
            first_row.setdefault(order_id, number)
            previous = order_id
    else:
        keys = _DAY_KEYS[upload_format]
        column = keys[-1]
        seen: dict[tuple[str, ...], int] = {}
        for number, cells in enumerate(rows, start=2):
            key = tuple((cells.get(k) or "").strip() for k in keys)
            if key in seen:
                repeats.append((number, seen[key]))
            else:
                seen[key] = number
    return column, repeats


def _duplicate_day(column: str, repeats: list[tuple[int, int]]) -> list[Defect]:
    """One Defect at the first row that repeats an earlier one, counting all the repeats."""
    if not repeats:
        return []
    row, earlier = repeats[0]
    more = f", and {len(repeats) - 1} more rows repeat earlier ones" if len(repeats) > 1 else ""
    return [
        Defect(
            kind=DefectKind.DUPLICATE_DAY,
            row=row,
            column=column,
            detail=f"row {row} repeats row {earlier}{more}, so the day is reported more than once",
        )
    ]


def _store_sales(row: _Row) -> SalesLine | None:
    day = row.day("date")
    row.sales_channel("store_code")
    sku = row.sku("sku")
    quantity = row.quantity("quantity_sold", low=0, high=MAX_PLAUSIBLE_DAILY_UNITS)
    net_sales = row.amount("net_sales")
    if row.defects or day is None or sku is None or quantity is None or net_sales is None:
        return None
    return SalesLine(day=day, sku=sku, quantity_sold=quantity, net_sales=net_sales)


def _store_inventory(row: _Row) -> StockLine | None:
    day = row.day("date")
    row.sales_channel("store_code")
    sku = row.sku("sku")
    on_hand = row.quantity("on_hand", low=0, high=MAX_PLAUSIBLE_ON_HAND)
    if row.defects or day is None or sku is None or on_hand is None:
        return None
    return StockLine(day=day, sku=sku, on_hand=on_hand)


def _online_shop_order_line(row: _Row) -> SalesLine | None:
    """A paid Order Line as a sale; cancelled and refunded lines are checked but not counted."""
    row.text("order_id")
    created_at = row.timestamp("created_at")
    sku = row.sku("sku")
    quantity = row.quantity("quantity", low=1, high=MAX_PLAUSIBLE_DAILY_UNITS)
    line_total = row.amount("line_total")
    status = row.status("status")
    if (
        row.defects
        or created_at is None
        or sku is None
        or quantity is None
        or line_total is None
        or status is not OrderLineStatus.PAID
    ):
        return None
    return SalesLine(day=created_at.date(), sku=sku, quantity_sold=quantity, net_sales=line_total)


def _online_shop_stock_snapshot(row: _Row) -> StockLine | None:
    sku = row.sku("SKU Code")
    on_hand = row.quantity("Available Quantity", low=0, high=MAX_PLAUSIBLE_ON_HAND)
    snapshot_time = row.timestamp("Snapshot Time")
    if row.defects or sku is None or on_hand is None or snapshot_time is None:
        return None
    return StockLine(day=snapshot_time.date(), sku=sku, on_hand=on_hand)


_ROW_PARSERS: dict[UploadFormat, Callable[[_Row], SalesLine | StockLine | None]] = {
    UploadFormat.STORE_SALES: _store_sales,
    UploadFormat.STORE_INVENTORY: _store_inventory,
    UploadFormat.ONLINE_SHOP_ORDER_LINES: _online_shop_order_line,
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: _online_shop_stock_snapshot,
}


def _daily_totals(lines: list[SalesLine]) -> list[SalesLine]:
    """Total paid Order Lines to one sales line per SKU and day."""
    totals: dict[tuple[date, str], tuple[int, float]] = {}
    for line in lines:
        quantity, net_sales = totals.get((line.day, line.sku), (0, 0.0))
        totals[(line.day, line.sku)] = (quantity + line.quantity_sold, net_sales + line.net_sales)
    return [
        SalesLine(day=day, sku=sku, quantity_sold=quantity, net_sales=round(net_sales, 2))
        for (day, sku), (quantity, net_sales) in sorted(totals.items())
    ]


class _Row:
    """Reads one row's cells, collecting a Defect for each cell that fails its check."""

    def __init__(self, upload: Upload, cells: dict[str, str], number: int, known_skus: frozenset[str]):
        self._upload = upload
        self._cells = cells
        self._number = number
        self._known_skus = known_skus
        self.defects: list[Defect] = []

    def text(self, column: str) -> str | None:
        value = self._cell(column)
        if not value:
            self._unreadable(column, value)
            return None
        return value

    def day(self, column: str) -> date | None:
        value = self._cell(column)
        try:
            day = date.fromisoformat(value)
        except ValueError:
            self._unreadable(column, value)
            return None
        self._check_day(column, day)
        return day

    def timestamp(self, column: str) -> datetime | None:
        value = self._cell(column)
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            self._unreadable(column, value)
            return None
        self._check_day(column, moment.date())
        return moment

    def quantity(self, column: str, *, low: int, high: int) -> int | None:
        value = self._cell(column)
        try:
            quantity = int(value)
        except ValueError:
            self._unreadable(column, value)
            return None
        if not low <= quantity <= high:
            self._add(DefectKind.IMPOSSIBLE_QUANTITY, column, f"{column} {quantity} is impossible")
            return None
        return quantity

    def amount(self, column: str) -> float | None:
        value = self._cell(column)
        try:
            return float(value)
        except ValueError:
            self._unreadable(column, value)
            return None

    def sku(self, column: str) -> str | None:
        sku = self._cell(column)
        if sku not in self._known_skus:
            self._add(DefectKind.UNKNOWN_SKU, column, f"SKU {sku} is unknown")
            return None
        return sku

    def sales_channel(self, column: str) -> None:
        code = self._cell(column)
        if code != self._upload.sales_channel:
            self._add(
                DefectKind.SALES_CHANNEL_MISMATCH,
                column,
                f"store code {code} does not match Sales Channel {self._upload.sales_channel}",
            )

    def status(self, column: str) -> OrderLineStatus | None:
        value = self._cell(column)
        try:
            return OrderLineStatus(value.lower())
        except ValueError:
            self._unreadable(column, value)
            return None

    def _check_day(self, column: str, day: date) -> None:
        if day != self._upload.day:
            self._add(
                DefectKind.DATE_MISMATCH,
                column,
                f"date {day.isoformat()} does not match the Upload day {self._upload.day.isoformat()}",
            )

    def _cell(self, column: str) -> str:
        # DictReader fills cells missing from a short row with None.
        value: str | None = self._cells.get(column)
        return (value or "").strip()

    def _unreadable(self, column: str, value: str) -> None:
        self._add(DefectKind.UNREADABLE_VALUE, column, f"value {value!r} in {column} cannot be read")

    def _add(self, kind: DefectKind, column: str, detail: str) -> None:
        self.defects.append(Defect(kind=kind, row=self._number, column=column, detail=detail))
