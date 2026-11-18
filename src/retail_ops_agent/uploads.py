"""Uploads and their statuses."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class UploadKind(StrEnum):
    SALES = "sales"
    INVENTORY = "inventory"


class UploadStatus(StrEnum):
    ACCEPTED = "accepted"
    SAFE_FIXED = "safe_fixed"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"


class Upload(BaseModel):
    """One CSV submitted for one Sales Channel, one day and one kind."""

    model_config = ConfigDict(frozen=True)

    upload_id: str
    sales_channel: str
    day: date
    kind: UploadKind
    uploader: str
    submitted_at: datetime
    content: str
