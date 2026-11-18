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

    parse_row = _ROW_PARSERS[upload_format]
    paid: list[SalesLine] = []
    for row_number, cells in enumerate(rows, start=2):  # row 1 is the header
        row = _Row(upload, cells, row_number, known_skus)
        line = parse_row(row)
        parsed.defects.extend(row.defects)
        if isinstance(line, StockLine):
            parsed.stock.append(line)
        elif line is not None:
            paid.append(line)

    parsed.sales = _daily_totals(paid) if upload_format is UploadFormat.ONLINE_SHOP_ORDER_LINES else paid
    return parsed


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
