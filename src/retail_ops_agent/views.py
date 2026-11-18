"""Read views and outcomes returned by the Ops Day boundary."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.audit_log import AuditEntry
from retail_ops_agent.defects import Defect
from retail_ops_agent.uploads import UploadKind, UploadStatus


class UploadOutcome(BaseModel):
    """One Upload's status after Intake, with its Defects, including any corrected by a Safe Fix."""

    model_config = ConfigDict(frozen=True)

    upload_id: str
    sales_channel: str
    day: date
    kind: UploadKind
    uploader: str
    status: UploadStatus
    processed_at: datetime
    defects: list[Defect]


class UploaderMessage(BaseModel):
    """A plain-language message Intake sent an Uploader through the Notifier about one Upload."""

    model_config = ConfigDict(frozen=True)

    upload_id: str
    sent_at: datetime
    recipient: str
    subject: str
    body: str


class OpsDayOutcome(BaseModel):
    """What happened in one Ops Day."""

    model_config = ConfigDict(frozen=True)

    day: date
    uploads: list[UploadOutcome]
    audit_entries: list[AuditEntry]
    uploader_messages: list[UploaderMessage]


class SalesBySalesChannel(BaseModel):
    """Accepted sales for one Sales Channel and day."""

    model_config = ConfigDict(frozen=True)

    day: date
    sales_channel: str
    sales_channel_name: str
    quantity_sold: int
    net_sales: float


class InventoryBySalesChannel(BaseModel):
    """Accepted inventory for one Sales Channel at the end of one day."""

    model_config = ConfigDict(frozen=True)

    day: date
    sales_channel: str
    sales_channel_name: str
    skus_in_stock: int
    on_hand: int


class InventoryBySku(BaseModel):
    """Accepted units on hand of one SKU at one Sales Channel at the end of one day."""

    model_config = ConfigDict(frozen=True)

    day: date
    sales_channel: str
    sales_channel_name: str
    sku: str
    sku_name: str
    category: str
    on_hand: int
