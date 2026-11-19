"""Read views and outcomes returned by the Ops Day boundary."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.analyst import Investigation
from retail_ops_agent.anomalies import Anomaly
from retail_ops_agent.approval_queue import QueuedReorder
from retail_ops_agent.audit_log import AuditEntry
from retail_ops_agent.defects import Defect
from retail_ops_agent.uploads import UploadKind, UploadStatus


class UploadStatusChange(BaseModel):
    """One status an Upload took, and when."""

    model_config = ConfigDict(frozen=True)

    changed_at: datetime
    status: UploadStatus


class UploadOutcome(BaseModel):
    """One Upload's status after Intake, with its Defects, including any corrected by a Safe Fix.

    A Superseded Upload names the later Upload for the same Sales Channel, day and kind that
    replaced it. history is every status the Upload has had, oldest first.
    """

    model_config = ConfigDict(frozen=True)

    upload_id: str
    sales_channel: str
    day: date
    kind: UploadKind
    uploader: str
    status: UploadStatus
    processed_at: datetime
    defects: list[Defect]
    superseded_by: str | None = None
    history: list[UploadStatusChange] = []


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
    anomalies: list[Anomaly] = []
    investigations: list[Investigation] = []
    # Reorders proposed this Ops Day, with what the Action policy did with each.
    reorders: list[QueuedReorder] = []
    # Every Tier 2 Action waiting for Approval once the day is processed.
    approval_queue: list[QueuedReorder] = []
    # Anomalies cleared because an Upload they were built on was Superseded and they no longer hold.
    cleared_anomalies: list[ClearedAnomaly] = []
    # Pending Reorders withdrawn from the Approval Queue because their Anomaly was cleared.
    withdrawn_reorders: list[QueuedReorder] = []
    # Reorders already placed for a cleared Anomaly, flagged for a person and not undone.
    flagged_reorders: list[FlaggedReorder] = []


class ClearedAnomaly(BaseModel):
    """An Anomaly that no longer holds: an Upload it was built on was Superseded, and the statistics
    no longer flag it in the data that replaced it."""

    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    cleared_at: datetime
    superseded_upload_id: str
    replaced_by: str
    summary: str


class FlaggedReorder(BaseModel):
    """A Reorder already placed in the ERP for an Anomaly that no longer holds after a Supersede.

    It is never undone automatically: a person decides what to do with it, for example by undoing it
    from the Audit Log, which cancels it in the ERP.
    """

    model_config = ConfigDict(frozen=True)

    action_id: str
    reorder_id: str
    audit_entry_id: int
    investigation_id: str
    anomaly_id: str
    sales_channel: str
    sku: str
    quantity: int
    cost: float
    supplier_name: str
    flagged_at: datetime
    superseded_upload_id: str
    replaced_by: str
    reason: str


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
