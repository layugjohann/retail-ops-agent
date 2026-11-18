"""The Ops Day boundary: the one interface the dashboard, n8n, Replay and Live Modes and evals call.

Every dependency (models, ERP client, Notifier, Data Source, clock) is passed in, so tests and
evals can swap them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic_ai.models import Model

from retail_ops_agent.bi_store import BiStore
from retail_ops_agent.clock import Clock
from retail_ops_agent.data_source import DataSource
from retail_ops_agent.erp import ErpClient
from retail_ops_agent.intake import run_intake
from retail_ops_agent.notifier import Notification, Notifier
from retail_ops_agent.uploads import Upload, UploadKind, UploadStatus
from retail_ops_agent.views import (
    InventoryBySalesChannel,
    InventoryBySku,
    OpsDayOutcome,
    SalesBySalesChannel,
    UploadOutcome,
)


@dataclass(frozen=True)
class Models:
    """The model each agent uses: a Pydantic AI Model, or a model name such as 'groq:...'."""

    intake: Model | str


class OpsDay:
    def __init__(
        self,
        *,
        models: Models,
        erp: ErpClient,
        notifier: Notifier,
        data_source: DataSource,
        clock: Clock,
        database: str = ":memory:",
    ) -> None:
        self._models = models
        self._erp = erp
        self._notifier = notifier
        self._data_source = data_source
        self._clock = clock
        self._bi = BiStore(database)

    # Operations

    def submit_upload(
        self, *, sales_channel: str, day: date, kind: UploadKind, content: str, uploader: str
    ) -> str:
        """Submit an Upload for a Sales Channel, day and kind. Returns its upload id."""
        if sales_channel not in {c.code for c in self._erp.list_sales_channels()}:
            raise ValueError(f"unknown Sales Channel {sales_channel!r}")
        earlier = [
            u
            for u in self._data_source.uploads_for(day)
            if u.sales_channel == sales_channel and u.kind is kind
        ]
        upload = Upload(
            upload_id=f"{sales_channel}-{day.isoformat()}-{kind.value}-{len(earlier) + 1:03d}",
            sales_channel=sales_channel,
            day=day,
            kind=kind,
            uploader=uploader,
            submitted_at=self._clock.now(),
            content=content,
        )
        self._data_source.put(upload)
        return upload.upload_id

    def run_ops_day(self, day: date) -> OpsDayOutcome:
        """Process every not-yet-processed Upload for the day: Intake, then Load."""
        processed = self._bi.processed_upload_ids()
        known_skus = frozenset(s.code for s in self._erp.list_skus())
        channel_kinds = {c.code: c.kind for c in self._erp.list_sales_channels()}
        outcomes: list[UploadOutcome] = []
        for upload in self._data_source.uploads_for(day):
            if upload.upload_id in processed:
                continue
            result = run_intake(upload, channel_kinds[upload.sales_channel], known_skus, self._models.intake)
            status = UploadStatus.QUARANTINED if result.defects else UploadStatus.ACCEPTED
            now = self._clock.now()
            self._bi.record_upload(upload, status, now, result.defects)
            if status is UploadStatus.ACCEPTED:
                if upload.kind is UploadKind.SALES:
                    self._bi.load_sales(upload, result.sales)
                else:
                    self._bi.load_inventory(upload, result.stock)
            elif result.uploader_message:
                self._notifier.send(
                    Notification(
                        sent_at=now,
                        recipient=upload.uploader,
                        subject=f"Upload {upload.upload_id} is Quarantined",
                        body=result.uploader_message,
                    )
                )
            outcomes.append(
                UploadOutcome(
                    upload_id=upload.upload_id,
                    sales_channel=upload.sales_channel,
                    day=upload.day,
                    kind=upload.kind,
                    uploader=upload.uploader,
                    status=status,
                    processed_at=now,
                    defects=result.defects,
                )
            )
        return OpsDayOutcome(day=day, uploads=outcomes)

    # Read views

    def upload_statuses(self) -> list[UploadOutcome]:
        return self._bi.uploads()

    def sales_by_sales_channel(self) -> list[SalesBySalesChannel]:
        names = self._sales_channel_names()
        return [
            SalesBySalesChannel(
                day=day,
                sales_channel=code,
                sales_channel_name=names.get(code, code),
                quantity_sold=quantity,
                net_sales=net_sales,
            )
            for day, code, quantity, net_sales in self._bi.sales_by_sales_channel()
        ]

    def inventory_by_sales_channel(self) -> list[InventoryBySalesChannel]:
        names = self._sales_channel_names()
        return [
            InventoryBySalesChannel(
                day=day,
                sales_channel=code,
                sales_channel_name=names.get(code, code),
                skus_in_stock=skus_in_stock,
                on_hand=on_hand,
            )
            for day, code, skus_in_stock, on_hand in self._bi.inventory_by_sales_channel()
        ]

    def inventory_by_sku(self, day: date | None = None) -> list[InventoryBySku]:
        """Units on hand per Sales Channel and SKU for the day; the latest inventory day by default."""
        day = day or self._bi.latest_inventory_day()
        if day is None:
            return []
        names = self._sales_channel_names()
        skus = {s.code: s for s in self._erp.list_skus()}
        return [
            InventoryBySku(
                day=day,
                sales_channel=code,
                sales_channel_name=names.get(code, code),
                sku=sku,
                sku_name=skus[sku].name if sku in skus else sku,
                category=skus[sku].category if sku in skus else "",
                on_hand=on_hand,
            )
            for code, sku, on_hand in self._bi.inventory_by_sku(day)
        ]

    def _sales_channel_names(self) -> dict[str, str]:
        return {c.code: c.name for c in self._erp.list_sales_channels()}
