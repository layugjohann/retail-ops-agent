"""Safe Fixes: deterministic corrections for the Defect kinds the fixed table marks as safe.

Each Safe Fix is reported as the Defect it corrected. Nothing here guesses at the Uploader's
intent: a fix is applied only when exactly one reading of the Upload is possible.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from retail_ops_agent.defects import Defect, DefectKind, has_safe_fix

BYTE_ORDER_MARK = "﻿"
OTHER_DELIMITERS = (";", "\t", "|")

# Other names Uploaders give each expected column, in normalised form (see normalise_header).
COLUMN_ALIASES: dict[str, frozenset[str]] = {
    "date": frozenset({"day", "sale_date", "sales_date", "business_date", "stock_date"}),
    "store_code": frozenset({"store", "store_id", "store_no", "shop_code"}),
    "sku": frozenset({"sku_code", "sku_id", "item_sku"}),
    "quantity_sold": frozenset({"qty_sold", "units_sold", "sold_qty"}),
    "net_sales": frozenset({"net_sales_amount", "net_revenue", "sales_net"}),
    "on_hand": frozenset({"qty_on_hand", "on_hand_qty", "stock_on_hand", "units_on_hand"}),
    "order_id": frozenset({"order_number", "order_no", "order_ref"}),
    "created_at": frozenset({"created", "created_time", "order_created_at"}),
    "quantity": frozenset({"qty", "units"}),
    "line_total": frozenset({"line_amount", "total"}),
    "status": frozenset({"order_status", "line_status"}),
    "SKU Code": frozenset({"sku"}),
    "Available Quantity": frozenset({"available", "available_qty", "qty_available"}),
    "Snapshot Time": frozenset({"snapshot_at", "snapshot", "as_of"}),
}


def normalise_header(header: str) -> str:
    """Lower case, with every stretch of spaces or punctuation turned into one underscore."""
    return re.sub(r"[^0-9a-z]+", "_", header.strip().lower()).strip("_")


@dataclass(frozen=True)
class SafeFixResult:
    """The Upload's content with every Safe Fix applied, and the Defects those fixes corrected.

    unfixed holds the Defects of a kind this module can correct but SAFE_FIX_TABLE says has no
    Safe Fix: they were left in the content, and any one of them keeps the Upload out of the BI data.
    """

    content: str
    fixed: list[Defect]
    unfixed: list[Defect] = field(default_factory=list[Defect])


def apply_safe_fixes(
    content: str, expected_columns: tuple[str, ...], optional_columns: tuple[str, ...] = ()
) -> SafeFixResult:
    """Apply every Safe Fix that applies. Content with nothing to fix is returned unchanged.

    Each fix runs only if SAFE_FIX_TABLE marks its Defect kind as safe; otherwise the Defect is
    reported as unfixed and the content is left as it was.
    optional_columns may appear in the header beside the expected ones, such as a free-text column.
    """
    fixed: list[Defect] = []
    unfixed: list[Defect] = []

    def found(defect: Defect) -> bool:
        """Record the Defect, and say whether its fix may be applied."""
        if has_safe_fix(defect.kind):
            fixed.append(defect)
            return True
        unfixed.append(defect)
        return False

    text = content
    if text.startswith(BYTE_ORDER_MARK) and found(
        Defect(
            kind=DefectKind.BYTE_ORDER_MARK,
            detail="the Upload starts with a byte order mark, which was removed",
        )
    ):
        text = text.removeprefix(BYTE_ORDER_MARK)

    delimiter = _delimiter(text, expected_columns, optional_columns)
    if delimiter != "," and not found(
        Defect(
            kind=DefectKind.WRONG_DELIMITER,
            detail=f"values are separated by {delimiter!r} instead of commas",
        )
    ):
        delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return SafeFixResult(content=content, fixed=fixed, unfixed=unfixed)

    header = rows[0]
    for index, name in _renames(header, expected_columns).items():
        if found(
            Defect(
                kind=DefectKind.RENAMED_COLUMN,
                row=1,
                column=name,
                detail=f"column {header[index]!r} was read as {name}",
            )
        ):
            header[index] = name

    for number, row in enumerate(rows[1:], start=2):
        for index, value in enumerate(row):
            stripped = value.strip()
            if stripped != value:
                column = header[index] if index < len(header) else f"column {index + 1}"
                if found(
                    Defect(
                        kind=DefectKind.STRAY_WHITESPACE,
                        row=number,
                        column=column,
                        detail=f"value {value!r} in {column} had spaces around it",
                    )
                ):
                    row[index] = stripped

    if not fixed:
        return SafeFixResult(content=content, fixed=[], unfixed=unfixed)
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return SafeFixResult(content=buffer.getvalue(), fixed=fixed, unfixed=unfixed)


def _delimiter(text: str, expected_columns: tuple[str, ...], optional_columns: tuple[str, ...]) -> str:
    """The delimiter the Upload uses: another one only if it is the only possible reading."""
    if "," in text:
        return ","
    first_line = text.split("\n", 1)[0]
    candidates = [
        d
        for d in OTHER_DELIMITERS
        if _header_matches([h for h in _split(first_line, d) if h not in optional_columns], expected_columns)
    ]
    return candidates[0] if len(candidates) == 1 else ","


def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), list[str]())


def _header_matches(header: list[str], expected_columns: tuple[str, ...]) -> bool:
    if len(header) != len(expected_columns):
        return False
    renamed = _renames(header, expected_columns)
    return {renamed.get(i, h) for i, h in enumerate(header)} == set(expected_columns)


def _renames(header: list[str], expected_columns: tuple[str, ...]) -> dict[int, str]:
    """Header positions to rename, each matching exactly one expected column nobody else claims.

    Renames apply only when together they complete the expected header; a header that would still
    lack columns is some other layout, and renaming part of it would be a guess.
    """
    missing = [c for c in expected_columns if c not in header]
    matches: dict[int, str] = {}
    for index, name in enumerate(header):
        if name in expected_columns:
            continue
        candidates = [c for c in missing if _matches(name, c)]
        if len(candidates) == 1:
            matches[index] = candidates[0]
    claimed = list(matches.values())
    renames = {i: c for i, c in matches.items() if claimed.count(c) == 1}
    if set(missing) - set(renames.values()):
        return {}
    return renames


def _matches(header: str, column: str) -> bool:
    normalised = normalise_header(header)
    return normalised == normalise_header(column) or normalised in COLUMN_ALIASES.get(column, frozenset())
