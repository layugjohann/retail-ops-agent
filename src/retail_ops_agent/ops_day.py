"""The Ops Day boundary: the one interface the dashboard, n8n, Replay and Live Modes and evals call.

Every dependency (models, ERP client, Notifier, Data Source, clock) is passed in, so tests and
evals can swap them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic_ai.models import Model

from retail_ops_agent.audit_log import AuditAction, AuditEntry, AuditLog, UndoOperation, UndoRecipe
from retail_ops_agent.bi_store import BiStore
from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.clock import Clock
from retail_ops_agent.data_source import DataSource
from retail_ops_agent.defects import Defect
from retail_ops_agent.erp import ErpClient
from retail_ops_agent.intake import run_intake
from retail_ops_agent.notifier import Notification, Notifier
from retail_ops_agent.upload_formats import SalesLine, StockLine, parse_upload
from retail_ops_agent.uploads import Upload, UploadKind, UploadStatus
from retail_ops_agent.views import (
    InventoryBySalesChannel,
    InventoryBySku,
    OpsDayOutcome,
    SalesBySalesChannel,
    UploadOutcome,
)

INTAKE_AGENT = "Intake agent"


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
        self._audit = AuditLog(self._bi.connection)

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
        known_skus = self._known_skus()
        channel_kinds = self._channel_kinds()
        outcomes: list[UploadOutcome] = []
        entries: list[AuditEntry] = []
        for upload in self._data_source.uploads_for(day):
            if upload.upload_id in processed:
                continue
            result = run_intake(upload, channel_kinds[upload.sales_channel], known_skus, self._models.intake)
            if result.defects:
                status = UploadStatus.QUARANTINED
            elif result.safe_fixed:
                status = UploadStatus.SAFE_FIXED
            else:
                status = UploadStatus.ACCEPTED
            now = self._clock.now()
            defects = [*result.safe_fixed, *result.defects]
            self._bi.record_upload(upload, status, now, defects)
            if status is UploadStatus.QUARANTINED:
                if result.uploader_message:
                    self._notifier.send(
                        Notification(
                            sent_at=now,
                            recipient=upload.uploader,
                            subject=f"Upload {upload.upload_id} is Quarantined",
                            body=result.uploader_message,
                        )
                    )
            else:
                self._load(upload, result.sales, result.stock)
                entries.extend(self._record_safe_fix(upload, defect) for defect in result.safe_fixed)
            outcomes.append(
                UploadOutcome(
                    upload_id=upload.upload_id,
                    sales_channel=upload.sales_channel,
                    day=upload.day,
                    kind=upload.kind,
                    uploader=upload.uploader,
                    status=status,
                    processed_at=now,
                    defects=defects,
                )
            )
        return OpsDayOutcome(day=day, uploads=outcomes, audit_entries=entries)

    def undo(self, entry_id: int, *, taken_by: str) -> AuditEntry:
        """Undo an Audit Log entry. The undo is a new entry; the undone entry is never changed.

        Undoing a Safe Fix takes its Upload back to how it arrived: the Upload's rows leave the BI
        data and, with its Defect no longer fixed, it is held in Quarantine. Undoing an undo
        reinstates what it reversed.
        """
        try:
            target = self._audit.entry(entry_id)
        except KeyError:
            raise ValueError(f"no Audit Log entry {entry_id}") from None
        if target.undone_by is not None:
            raise ValueError(f"Audit Log entry {entry_id} is already undone by entry {target.undone_by}")
        entry = self._audit.append(
            recorded_at=self._clock.now(),
            action=AuditAction.UNDO,
            triggered_by=f"undo of Audit Log entry {target.entry_id} requested by {taken_by}",
            taken_by=taken_by,
            summary=f"Undid entry {target.entry_id}: {target.summary}",
            upload_id=target.upload_id,
            defect=target.defect,
            undo=UndoRecipe(
                operation=UndoOperation.REINSTATE_ENTRY,
                upload_id=target.upload_id,
                entry_id=target.entry_id,
                description=f"Undo this entry to reinstate entry {target.entry_id}.",
            ),
            undoes=target.entry_id,
        )
        self._settle_safe_fixes(target.upload_id)
        return entry

    def _record_safe_fix(self, upload: Upload, defect: Defect) -> AuditEntry:
        where = ", ".join(
            part
            for part in (
                f"row {defect.row}" if defect.row is not None else "",
                f"column {defect.column}" if defect.column else "",
            )
            if part
        )
        return self._audit.append(
            recorded_at=self._clock.now(),
            action=AuditAction.SAFE_FIX,
            triggered_by=f"Defect {defect.kind.value} in Upload {upload.upload_id}"
            + (f" ({where})" if where else ""),
            taken_by=INTAKE_AGENT,
            summary=f"Safe Fix on Upload {upload.upload_id}: {defect.detail}",
            upload_id=upload.upload_id,
            defect=defect,
            undo=UndoRecipe(
                operation=UndoOperation.RESTORE_ORIGINAL_UPLOAD,
                upload_id=upload.upload_id,
                description=(
                    f"Take Upload {upload.upload_id}'s rows out of the BI data and hold the Upload, "
                    "as it arrived, in Quarantine."
                ),
            ),
        )

    def _settle_safe_fixes(self, upload_id: str) -> None:
        """Bring an Upload's data and status in line with which of its Safe Fixes stand."""
        fixes = [
            e for e in self._audit.entries() if e.upload_id == upload_id and e.action is AuditAction.SAFE_FIX
        ]
        upload = self._processed_upload(upload_id)
        self._bi.unload(upload_id)
        if any(e.undone_by is not None for e in fixes):
            self._bi.set_status(upload_id, UploadStatus.QUARANTINED)
            return
        # Safe Fixes are deterministic, so reading the Upload again gives the rows first loaded.
        parsed = parse_upload(upload, self._channel_kinds()[upload.sales_channel], self._known_skus())
        self._load(upload, parsed.sales, parsed.stock)
        self._bi.set_status(upload_id, UploadStatus.SAFE_FIXED)

    def _processed_upload(self, upload_id: str) -> Upload:
        day = self._bi.upload_day(upload_id)
        for upload in self._data_source.uploads_for(day):
            if upload.upload_id == upload_id:
                return upload
        raise KeyError(f"Upload {upload_id} is not in the Data Source")

    def _load(self, upload: Upload, sales: list[SalesLine], stock: list[StockLine]) -> None:
        if upload.kind is UploadKind.SALES:
            self._bi.load_sales(upload, sales)
        else:
            self._bi.load_inventory(upload, stock)

    def _known_skus(self) -> frozenset[str]:
        return frozenset(s.code for s in self._erp.list_skus())

    def _channel_kinds(self) -> dict[str, SalesChannelKind]:
        return {c.code: c.kind for c in self._erp.list_sales_channels()}

    # Read views

    def audit_log(self) -> list[AuditEntry]:
        """Every Audit Log entry, newest first, with the undo currently reversing it, if any."""
        return list(reversed(self._audit.entries()))

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
