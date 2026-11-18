"""The Audit Log: an append-only record of every Action, who or what took it, and how to undo it.

Entries are only ever inserted. Undoing an entry appends a new entry that points at it; whether an
entry is currently undone is worked out when the log is read, never written back.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import IntEnum, StrEnum

import duckdb
from pydantic import BaseModel, ConfigDict

from retail_ops_agent.defects import Defect


class ActionTier(IntEnum):
    READ = 0
    INTERNAL = 1
    EXTERNAL = 2


class AuditAction(StrEnum):
    SAFE_FIX = "safe_fix"
    QUARANTINE = "quarantine"
    ALERT = "alert"
    UNDO = "undo"


# Each Action's Tier, by fixed rule. The model never sets a Tier (ADR 0002).
ACTION_TIERS: dict[AuditAction, ActionTier] = {
    AuditAction.SAFE_FIX: ActionTier.INTERNAL,
    AuditAction.QUARANTINE: ActionTier.INTERNAL,
    AuditAction.ALERT: ActionTier.INTERNAL,
    AuditAction.UNDO: ActionTier.INTERNAL,
}


class UndoOperation(StrEnum):
    # Take the Upload back to how it arrived: its Safe-Fixed rows leave the BI data and, with its
    # Defect no longer fixed, it is held in Quarantine.
    RESTORE_ORIGINAL_UPLOAD = "restore_original_upload"
    # Release the Upload from Quarantine: the rows that passed every check are loaded into the BI
    # data and the Upload is accepted; rows with Defects stay out.
    RELEASE_UPLOAD = "release_upload"
    # Withdraw an alert: it stays in the log, marked withdrawn, and no longer stands.
    WITHDRAW_ALERT = "withdraw_alert"
    # Reinstate the entry an undo reversed.
    REINSTATE_ENTRY = "reinstate_entry"


class UndoRecipe(BaseModel):
    """How to undo an entry."""

    model_config = ConfigDict(frozen=True)

    operation: UndoOperation
    upload_id: str | None = None
    entry_id: int | None = None
    description: str


class AuditEntry(BaseModel):
    """One Action in the Audit Log."""

    model_config = ConfigDict(frozen=True)

    entry_id: int
    recorded_at: datetime
    action: AuditAction
    tier: ActionTier
    triggered_by: str
    taken_by: str
    summary: str
    # The Upload the Action was about, for Actions on Uploads.
    upload_id: str | None
    defect: Defect | None
    undo: UndoRecipe
    # The Investigation that recommended the Action, for Actions on Anomalies.
    investigation_id: str | None = None
    # The entry this one undoes, for an undo.
    undoes: int | None = None
    # The undo currently reversing this entry, worked out when the log is read.
    undone_by: int | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id      INTEGER PRIMARY KEY,
    recorded_at   TIMESTAMP NOT NULL,
    action        VARCHAR NOT NULL,
    tier          INTEGER NOT NULL,
    triggered_by  VARCHAR NOT NULL,
    taken_by      VARCHAR NOT NULL,
    summary       VARCHAR NOT NULL,
    upload_id     VARCHAR,
    defect        VARCHAR,
    undo          VARCHAR NOT NULL,
    undoes        INTEGER,
    investigation_id VARCHAR
);
"""


class AuditLog:
    """Append-only: there is no operation that changes or removes an entry."""

    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db
        self._db.execute(_SCHEMA)

    def append(
        self,
        *,
        recorded_at: datetime,
        action: AuditAction,
        triggered_by: str,
        taken_by: str,
        summary: str,
        upload_id: str | None,
        defect: Defect | None,
        undo: UndoRecipe,
        undoes: int | None = None,
        investigation_id: str | None = None,
    ) -> AuditEntry:
        row = self._db.execute("SELECT COALESCE(MAX(entry_id), 0) + 1 FROM audit_log").fetchone()
        entry_id = int(row[0]) if row else 1
        self._db.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                entry_id,
                recorded_at,
                action.value,
                int(ACTION_TIERS[action]),
                triggered_by,
                taken_by,
                summary,
                upload_id,
                defect.model_dump_json() if defect else None,
                undo.model_dump_json(),
                undoes,
                investigation_id,
            ],
        )
        return self.entry(entry_id)

    def entries(self) -> list[AuditEntry]:
        """Every entry, oldest first, with which undo (if any) currently reverses it."""
        rows = self._db.execute(
            "SELECT entry_id, recorded_at, action, tier, triggered_by, taken_by, summary, upload_id, "
            "defect, undo, undoes, investigation_id FROM audit_log ORDER BY entry_id"
        ).fetchall()
        entries = [
            AuditEntry(
                entry_id=r[0],
                recorded_at=r[1],
                action=AuditAction(r[2]),
                tier=ActionTier(r[3]),
                triggered_by=r[4],
                taken_by=r[5],
                summary=r[6],
                upload_id=r[7],
                defect=Defect.model_validate(json.loads(r[8])) if r[8] else None,
                undo=UndoRecipe.model_validate(json.loads(r[9])),
                undoes=r[10],
                investigation_id=r[11],
            )
            for r in rows
        ]
        # An undo always comes after what it undoes, so walking newest first settles each undo
        # before the entry it points at. An entry is undone while some undo of it is itself not undone.
        undone_by: dict[int, int] = {}
        for entry in reversed(entries):
            if entry.undoes is not None and entry.entry_id not in undone_by:
                undone_by.setdefault(entry.undoes, entry.entry_id)
        return [e.model_copy(update={"undone_by": undone_by.get(e.entry_id)}) for e in entries]

    def entry(self, entry_id: int) -> AuditEntry:
        for entry in self.entries():
            if entry.entry_id == entry_id:
                return entry
        raise KeyError(f"no Audit Log entry {entry_id}")
