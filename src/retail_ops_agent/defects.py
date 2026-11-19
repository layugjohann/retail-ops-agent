"""Defects: things wrong with an Upload itself, and the fixed table of which have a Safe Fix."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict


class DefectKind(StrEnum):
    MISSING_COLUMN = "missing_column"
    UNREADABLE_VALUE = "unreadable_value"
    UNKNOWN_SKU = "unknown_sku"
    SALES_CHANNEL_MISMATCH = "sales_channel_mismatch"
    DATE_MISMATCH = "date_mismatch"
    IMPOSSIBLE_QUANTITY = "impossible_quantity"
    SWAPPED_COLUMNS = "swapped_columns"
    DUPLICATE_DAY = "duplicate_day"
    RENAMED_COLUMN = "renamed_column"
    STRAY_WHITESPACE = "stray_whitespace"
    WRONG_DELIMITER = "wrong_delimiter"
    BYTE_ORDER_MARK = "byte_order_mark"
    # Quantities counted in cases where units were due. Every value still looks plausible, so
    # validation passes it on purpose; an Investigation catches it later as a Data Problem.
    UNITS_IN_CASES = "units_in_cases"


# Which Defect kinds have a Safe Fix. This table decides, never the model. A kind is here as True
# only if its correction needs no guessing at the Uploader's intent.
SAFE_FIX_TABLE: Mapping[DefectKind, bool] = MappingProxyType(
    {
        DefectKind.MISSING_COLUMN: False,
        DefectKind.UNREADABLE_VALUE: False,
        DefectKind.UNKNOWN_SKU: False,
        DefectKind.SALES_CHANNEL_MISMATCH: False,
        DefectKind.DATE_MISMATCH: False,
        DefectKind.IMPOSSIBLE_QUANTITY: False,
        # Two columns whose values each look like the other's: the header or the values could be
        # the ones out of place, so correcting it would be a guess.
        DefectKind.SWAPPED_COLUMNS: False,
        # The same day's rows more than once in one file: which copy is right is the Uploader's call.
        DefectKind.DUPLICATE_DAY: False,
        # A header that matches exactly one expected, missing column, ignoring case, spacing and
        # punctuation or using a known alias, is renamed to that column.
        DefectKind.RENAMED_COLUMN: True,
        # Spaces around a cell's value are removed.
        DefectKind.STRAY_WHITESPACE: True,
        # Values separated by ';', tab or '|' in an Upload with no commas at all are re-separated.
        DefectKind.WRONG_DELIMITER: True,
        # A UTF-8 byte order mark before the header is removed.
        DefectKind.BYTE_ORDER_MARK: True,
        # Which quantities are in cases, and with what case pack, is the Uploader's to say.
        DefectKind.UNITS_IN_CASES: False,
    }
)


# The Defect kind an Upload sent back to Intake by a Data Problem is recorded with: the one kind
# validation passes on purpose, so only an Investigation can catch it.
DATA_PROBLEM_DEFECT = DefectKind.UNITS_IN_CASES


def has_safe_fix(kind: DefectKind) -> bool:
    return SAFE_FIX_TABLE[kind]


class Defect(BaseModel):
    """Something wrong with an Upload itself."""

    model_config = ConfigDict(frozen=True)

    kind: DefectKind
    row: int | None = None
    column: str | None = None
    detail: str


def defect_location(defect: Defect) -> str:
    """Where a Defect is, in words: a row and column, a column, or the whole Upload."""
    return location_in_words(defect.row, defect.column)


def location_in_words(row: int | None, column: str | None) -> str:
    """A row (row 1 is the header) and column in an Upload, in words; neither means the whole Upload."""
    if row == 1:
        return f"the header (row 1), column {column}" if column else "the header (row 1)"
    if row is not None and column:
        return f"row {row}, column {column}"
    if row is not None:
        return f"row {row}"
    if column:
        return f"column {column}"
    return "the whole file"
