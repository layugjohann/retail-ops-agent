"""The Ops Day boundary: the one interface the dashboard, n8n, Replay and Live Modes and evals call.

Every dependency (models, ERP client, Notifier, Data Source, clock) is passed in, so tests and
evals can swap them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic_ai.models import Model

from retail_ops_agent.action_policy import ALERT_RECIPIENT, PolicyDecision, decide
from retail_ops_agent.analyst import Investigation, investigate
from retail_ops_agent.anomalies import Anomaly, detect_stockout_risks
from retail_ops_agent.audit_log import AuditAction, AuditEntry, AuditLog, UndoOperation, UndoRecipe
from retail_ops_agent.bi_store import BiStore
from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.clock import Clock
from retail_ops_agent.data_source import DataSource
from retail_ops_agent.defects import Defect, defect_location
from retail_ops_agent.erp import ErpClient
from retail_ops_agent.intake import run_intake
from retail_ops_agent.notifier import Notification, Notifier
from retail_ops_agent.ops_agent import OPS_AGENT, ActionProposal, propose_action
from retail_ops_agent.upload_formats import SalesLine, StockLine, parse_upload
from retail_ops_agent.uploader_messages import quarantine_subject
from retail_ops_agent.uploads import Upload, UploadKind, UploadStatus
from retail_ops_agent.views import (
    InventoryBySalesChannel,
    InventoryBySku,
    OpsDayOutcome,
    SalesBySalesChannel,
    UploaderMessage,
    UploadOutcome,
)

INTAKE_AGENT = "Intake agent"


def _key(upload: Upload) -> tuple[str, date, UploadKind]:
    return (upload.sales_channel, upload.day, upload.kind)


@dataclass(frozen=True)
class Models:
    """The model each agent uses: a Pydantic AI Model, or a model name such as 'groq:...'."""

    intake: Model | str
    analyst: Model | str
    ops: Model | str


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
        """Process the day: Intake, then Load, then Detect, then the Analyst, then Ops (ADR 0003).

        The handoff between stages is this fixed pipeline; no model decides what runs next.

        Resubmissions for earlier days that already had an Ops Day are processed too.

        An Upload with any Defect that has no Safe Fix is Quarantined: none of its rows are loaded,
        the Quarantine is a Tier 1 Action in the Audit Log, and Intake's message telling the
        Uploader what is wrong, where, and what to do goes out through the Notifier.

        The latest Upload for a Sales Channel, day and kind replaces every earlier one, which
        becomes Superseded and leaves the BI data, whatever its own status was. Earlier Uploads
        superseded before they were processed never go through Intake.

        Deterministic statistics then flag the day's new Anomalies in the accepted data. The Analyst
        agent investigates each with read-only tools, the Ops agent proposes an Action from the
        Investigation, and the Action policy, not the model, sets its Tier. A Tier 1 alert is posted
        through the Notifier and recorded in the Audit Log.
        """
        processed = self._bi.processed_upload_ids()
        days = sorted({d for d in self._bi.upload_days() if d < day} | {day})
        pending = [u for d in days for u in self._data_source.uploads_for(d) if u.upload_id not in processed]
        latest: dict[tuple[str, date, UploadKind], Upload] = {}
        for upload in sorted(pending, key=lambda u: (u.submitted_at, u.upload_id)):
            latest[_key(upload)] = upload
        known_skus = self._known_skus()
        channel_kinds = self._channel_kinds()
        touched: list[str] = []
        entries: list[AuditEntry] = []
        messages: list[UploaderMessage] = []
        for upload in pending:
            touched.append(upload.upload_id)
            later = latest[_key(upload)]
            if later is not upload:
                now = self._clock.now()
                self._bi.record_upload(upload, UploadStatus.SUPERSEDED, now, [])
                self._bi.supersede(upload.upload_id, later.upload_id, now)
                continue
            for earlier in self._bi.current_upload_ids(upload.sales_channel, upload.day, upload.kind):
                self._bi.supersede(earlier, upload.upload_id, self._clock.now())
                touched.append(earlier)
            result = run_intake(upload, channel_kinds[upload.sales_channel], known_skus, self._models.intake)
            if result.defects:
                status = UploadStatus.QUARANTINED
            elif result.safe_fixed:
                status = UploadStatus.SAFE_FIXED
            else:
                status = UploadStatus.ACCEPTED
            defects = [*result.safe_fixed, *result.defects]
            self._bi.record_upload(upload, status, self._clock.now(), defects)
            if status is UploadStatus.QUARANTINED:
                entries.append(self._record_quarantine(upload, result.defects))
                if result.uploader_message:
                    messages.append(self._message_uploader(upload, result.uploader_message))
            else:
                self._load(upload, result.sales, result.stock)
                entries.extend(self._record_safe_fix(upload, defect) for defect in result.safe_fixed)
        by_id = {u.upload_id: u for u in self._bi.uploads()}
        outcomes = [by_id[upload_id] for upload_id in dict.fromkeys(touched)]
        anomalies = self._detect(day)
        investigations: list[Investigation] = []
        for anomaly in anomalies:
            investigation = investigate(
                anomaly,
                bi=self._bi,
                erp=self._erp,
                model=self._models.analyst,
                investigated_at=self._clock.now(),
            )
            self._bi.record_investigation(investigation)
            investigations.append(investigation)
            proposal = propose_action(investigation, self._models.ops)
            decision = decide(proposal)
            if decision.runs_on_its_own:
                entries.append(self._post_alert(investigation, proposal, decision))
        return OpsDayOutcome(
            day=day,
            uploads=outcomes,
            audit_entries=entries,
            uploader_messages=messages,
            anomalies=anomalies,
            investigations=investigations,
        )

    def _detect(self, day: date) -> list[Anomaly]:
        """The day's Anomalies not already flagged, recorded in the BI store."""
        skus = {s.code: s for s in self._erp.list_skus()}
        known = self._bi.anomaly_ids()
        anomalies = [a for a in detect_stockout_risks(self._bi, day, skus) if a.anomaly_id not in known]
        for anomaly in anomalies:
            self._bi.record_anomaly(anomaly)
        return anomalies

    def _post_alert(
        self, investigation: Investigation, proposal: ActionProposal, decision: PolicyDecision
    ) -> AuditEntry:
        self._notifier.send(
            Notification(
                sent_at=self._clock.now(),
                recipient=ALERT_RECIPIENT,
                subject=proposal.subject,
                body=proposal.body,
            )
        )
        return self._audit.append(
            recorded_at=self._clock.now(),
            action=decision.action,
            triggered_by=f"{investigation.anomaly.summary} ({investigation.investigation_id})",
            taken_by=OPS_AGENT,
            summary=f"Alerted {ALERT_RECIPIENT}: {proposal.subject}",
            upload_id=None,
            defect=None,
            investigation_id=investigation.investigation_id,
            undo=UndoRecipe(
                operation=UndoOperation.WITHDRAW_ALERT,
                description="Withdraw the alert: it stays in the Audit Log, marked withdrawn.",
            ),
        )

    def undo(self, entry_id: int, *, taken_by: str) -> AuditEntry:
        """Undo an Audit Log entry. The undo is a new entry; the undone entry is never changed.

        Undoing a Safe Fix takes its Upload back to how it arrived: the Upload's rows leave the BI
        data and, with its Defect no longer fixed, it is held in Quarantine. Undoing a Quarantine
        releases the Upload: the rows that passed every check are loaded and it is accepted. Undoing
        an alert withdraws it. Undoing an undo reinstates what it reversed.
        """
        try:
            target = self._audit.entry(entry_id)
        except KeyError:
            raise ValueError(f"no Audit Log entry {entry_id}") from None
        if target.undone_by is not None:
            raise ValueError(f"Audit Log entry {entry_id} is already undone by entry {target.undone_by}")
        superseded_by = self._bi.superseded_by(target.upload_id) if target.upload_id else None
        if superseded_by is not None:
            raise ValueError(
                f"Upload {target.upload_id} is Superseded by Upload {superseded_by}; "
                f"Audit Log entry {entry_id} can no longer be undone"
            )
        entry = self._audit.append(
            recorded_at=self._clock.now(),
            action=AuditAction.UNDO,
            triggered_by=f"undo of Audit Log entry {target.entry_id} requested by {taken_by}",
            taken_by=taken_by,
            summary=f"Undid entry {target.entry_id}: {target.summary}",
            upload_id=target.upload_id,
            defect=target.defect,
            investigation_id=target.investigation_id,
            undo=UndoRecipe(
                operation=UndoOperation.REINSTATE_ENTRY,
                upload_id=target.upload_id,
                entry_id=target.entry_id,
                description=f"Undo this entry to reinstate entry {target.entry_id}.",
            ),
            undoes=target.entry_id,
        )
        if target.upload_id is not None:
            self._settle_upload(target.upload_id)
        return entry

    def _record_quarantine(self, upload: Upload, defects: list[Defect]) -> AuditEntry:
        kinds = ", ".join(dict.fromkeys(d.kind.value for d in defects))
        return self._audit.append(
            recorded_at=self._clock.now(),
            action=AuditAction.QUARANTINE,
            triggered_by=f"Defects without a Safe Fix in Upload {upload.upload_id}: {kinds}",
            taken_by=INTAKE_AGENT,
            summary=(
                f"Quarantined Upload {upload.upload_id} with {len(defects)} "
                f"Defect{'s' if len(defects) != 1 else ''} ({kinds}) and messaged {upload.uploader}"
            ),
            upload_id=upload.upload_id,
            defect=defects[0] if len(defects) == 1 else None,
            undo=UndoRecipe(
                operation=UndoOperation.RELEASE_UPLOAD,
                upload_id=upload.upload_id,
                description=(
                    f"Release Upload {upload.upload_id} from Quarantine: load the rows that passed every "
                    "check into the BI data and accept it; rows with Defects stay out."
                ),
            ),
        )

    def _message_uploader(self, upload: Upload, body: str) -> UploaderMessage:
        message = UploaderMessage(
            upload_id=upload.upload_id,
            sent_at=self._clock.now(),
            recipient=upload.uploader,
            subject=quarantine_subject(upload),
            body=body,
        )
        self._notifier.send(
            Notification(
                sent_at=message.sent_at,
                recipient=message.recipient,
                subject=message.subject,
                body=message.body,
            )
        )
        self._bi.record_uploader_message(message)
        return message

    def _record_safe_fix(self, upload: Upload, defect: Defect) -> AuditEntry:
        return self._audit.append(
            recorded_at=self._clock.now(),
            action=AuditAction.SAFE_FIX,
            triggered_by=f"Defect {defect.kind.value} in Upload {upload.upload_id} "
            f"({defect_location(defect)})",
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

    def _settle_upload(self, upload_id: str) -> None:
        """Bring an Upload's data and status in line with which of its Actions stand.

        It is Quarantined while its Quarantine stands or any of its Safe Fixes is undone; otherwise
        its rows are loaded.
        """
        entries = [e for e in self._audit.entries() if e.upload_id == upload_id]
        quarantines = [e for e in entries if e.action is AuditAction.QUARANTINE]
        fixes = [e for e in entries if e.action is AuditAction.SAFE_FIX]
        upload = self._processed_upload(upload_id)
        self._bi.unload(upload_id)
        if (quarantines and quarantines[-1].undone_by is None) or any(e.undone_by is not None for e in fixes):
            self._bi.set_status(upload_id, UploadStatus.QUARANTINED, self._clock.now())
            return
        # Checks and Safe Fixes are deterministic, so reading the Upload again gives the rows they
        # passed. Rows with a Defect are never among them.
        parsed = parse_upload(upload, self._channel_kinds()[upload.sales_channel], self._known_skus())
        self._load(upload, parsed.sales, parsed.stock)
        if not fixes:
            # A released Upload's Safe Fixes were never logged while it was Quarantined; every
            # Safe Fix behind loaded rows must be in the Audit Log and undoable.
            for defect in parsed.safe_fixed:
                self._record_safe_fix(upload, defect)
        self._bi.set_status(
            upload_id,
            UploadStatus.SAFE_FIXED if parsed.safe_fixed else UploadStatus.ACCEPTED,
            self._clock.now(),
        )

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
        """Every processed Upload by Sales Channel, day and kind, oldest first: Superseded ones too,
        each with the Upload that replaced it and the history of its status."""
        return self._bi.uploads()

    def anomalies(self) -> list[Anomaly]:
        """Every Anomaly flagged, oldest first."""
        return self._bi.anomalies()

    def investigations(self) -> list[Investigation]:
        """Every Investigation with its cause, evidence and recommended Action, newest first."""
        return self._bi.investigations()

    def uploader_messages(self) -> list[UploaderMessage]:
        """Every message Intake sent an Uploader, newest first."""
        return self._bi.uploader_messages()

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
