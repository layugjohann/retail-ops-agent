"""Read views and outcomes returned by the Ops Day boundary."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.intake import Defect
from retail_ops_agent.uploads import UploadKind, UploadStatus


class UploadOutcome(BaseModel):
    """One Upload's status after Intake, with its Defects."""

    model_config = ConfigDict(frozen=True)

    upload_id: str
    sales_channel: str
    day: date
    kind: UploadKind
    uploader: str
    status: UploadStatus
    processed_at: datetime
    defects: list[Defect]


class OpsDayOutcome(BaseModel):
    """What happened in one Ops Day."""

    model_config = ConfigDict(frozen=True)

    day: date
    uploads: list[UploadOutcome]


class SalesBySalesChannel(BaseModel):
    """Accepted sales for one Sales Channel and day."""

    model_config = ConfigDict(frozen=True)

    day: date
    sales_channel: str
    sales_channel_name: str
    quantity_sold: int
    net_sales: float
