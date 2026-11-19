"""The Approval Queue: Tier 2 Actions waiting for a human's yes or no, and the decisions taken on them.

Only the Ops Day boundary writes to it. A Reorder in it reaches the ERP only once it is approved by
a person, or approved by rule because its cost is under the Auto-approval Limit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

import duckdb
from pydantic import BaseModel, ConfigDict, computed_field

# A pending Action Expires this long, in simulated time, after it was queued: it can no longer be
# approved and will never run.
EXPIRY = timedelta(hours=48)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    AUTO_APPROVED = "auto_approved"
    REJECTED = "rejected"
    # A newer Investigation of the same SKU and Sales Channel queued a Reorder that took its place.
    REPLACED = "replaced"
    # Nobody decided within the Expiry; it will never run.
    EXPIRED = "expired"
    # The Anomaly it answered no longer holds, because an Upload it was built on was Superseded; it
    # will never run.
    WITHDRAWN = "withdrawn"


class QueuedReorder(BaseModel):
    """A Reorder the Ops agent proposed from an Investigation, and what became of it."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    queued_at: datetime
    investigation_id: str
    sales_channel: str
    sku: str
    sku_name: str
    supplier_code: str
    supplier_name: str
    quantity: int
    unit_cost: float
    cost: float
    subject: str
    reason: str
    status: ApprovalStatus
    decided_at: datetime | None = None
    decided_by: str | None = None
    # Why a person rejected it, if they said.
    note: str | None = None
    # The Reorder in the ERP, once placed.
    reorder_id: str | None = None
    # The Audit Log entry recording the Reorder's placement.
    audit_entry_id: int | None = None
    # The Action that replaced it, once a newer Investigation of the same SKU and Sales Channel did.
    replaced_by: str | None = None
    # Why it was withdrawn from the Approval Queue, once it was.
    withdrawn_because: str | None = None

    @computed_field
    @property
    def expires_at(self) -> datetime:
        """When it Expires if it is still pending."""
        return self.queued_at + EXPIRY


_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_queue (
    action_id     VARCHAR PRIMARY KEY,
    queued_at     TIMESTAMP NOT NULL,
    status        VARCHAR NOT NULL,
    item          VARCHAR NOT NULL
);
"""

_COLUMNS = "SELECT item FROM approval_queue"


class ApprovalQueue:
    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db
        self._db.execute(_SCHEMA)

    def next_action_id(self) -> str:
        row = self._db.execute("SELECT COUNT(*) FROM approval_queue").fetchone()
        return f"A-{(int(row[0]) if row else 0) + 1:05d}"

    def add(self, item: QueuedReorder) -> QueuedReorder:
        self._db.execute(
            "INSERT INTO approval_queue VALUES (?, ?, ?, ?)",
            [item.action_id, item.queued_at, item.status.value, item.model_dump_json()],
        )
        return item

    def save(self, item: QueuedReorder) -> QueuedReorder:
        """Record a decision on an item."""
        self._db.execute(
            "UPDATE approval_queue SET status = ?, item = ? WHERE action_id = ?",
            [item.status.value, item.model_dump_json(), item.action_id],
        )
        return item

    def get(self, action_id: str) -> QueuedReorder:
        row = self._db.execute(_COLUMNS + " WHERE action_id = ?", [action_id]).fetchone()
        if row is None:
            raise KeyError(f"no Action {action_id} in the Approval Queue")
        return QueuedReorder.model_validate_json(row[0])

    def pending(self) -> list[QueuedReorder]:
        """Items waiting for Approval, oldest first."""
        rows = self._db.execute(
            _COLUMNS + " WHERE status = ? ORDER BY queued_at, action_id", [ApprovalStatus.PENDING.value]
        ).fetchall()
        return [QueuedReorder.model_validate_json(r[0]) for r in rows]

    def pending_for(self, sales_channel: str, sku: str) -> QueuedReorder | None:
        """The pending Reorder for the SKU and Sales Channel; there is never more than one."""
        found = [q for q in self.pending() if (q.sales_channel, q.sku) == (sales_channel, sku)]
        return found[0] if found else None

    def all(self) -> list[QueuedReorder]:
        """Every item, decided or not, newest first."""
        rows = self._db.execute(_COLUMNS + " ORDER BY queued_at DESC, action_id DESC").fetchall()
        return [QueuedReorder.model_validate_json(r[0]) for r in rows]
