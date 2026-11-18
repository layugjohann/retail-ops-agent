"""Defects: things wrong with an Upload itself."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DefectKind(StrEnum):
    MISSING_COLUMN = "missing_column"
    UNREADABLE_VALUE = "unreadable_value"
    UNKNOWN_SKU = "unknown_sku"
    SALES_CHANNEL_MISMATCH = "sales_channel_mismatch"
    DATE_MISMATCH = "date_mismatch"
    IMPOSSIBLE_QUANTITY = "impossible_quantity"


class Defect(BaseModel):
    """Something wrong with an Upload itself."""

    model_config = ConfigDict(frozen=True)

    kind: DefectKind
    row: int | None = None
    column: str | None = None
    detail: str
