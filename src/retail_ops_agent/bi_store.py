"""The BI store: DuckDB holding accepted data and every Upload's status."""

from __future__ import annotations

import json
from datetime import date, datetime

import duckdb
from pydantic import TypeAdapter

from retail_ops_agent.analyst import Investigation
from retail_ops_agent.anomalies import Anomaly
from retail_ops_agent.defects import Defect
from retail_ops_agent.upload_formats import SalesLine, StockLine
from retail_ops_agent.uploads import Upload, UploadKind, UploadStatus
from retail_ops_agent.views import (
    ClearedAnomaly,
    FlaggedReorder,
    UploaderMessage,
    UploadOutcome,
    UploadStatusChange,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    upload_id     VARCHAR PRIMARY KEY,
    sales_channel VARCHAR NOT NULL,
    day           DATE NOT NULL,
    kind          VARCHAR NOT NULL,
    uploader      VARCHAR NOT NULL,
    submitted_at  TIMESTAMP NOT NULL,
    status        VARCHAR NOT NULL,
    processed_at  TIMESTAMP NOT NULL,
    defects       VARCHAR NOT NULL,
    superseded_by VARCHAR
);
CREATE TABLE IF NOT EXISTS upload_status_history (
    upload_id     VARCHAR NOT NULL,
    changed_at    TIMESTAMP NOT NULL,
    status        VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS sales (
    day           DATE NOT NULL,
    sales_channel VARCHAR NOT NULL,
    sku           VARCHAR NOT NULL,
    quantity_sold INTEGER NOT NULL,
    net_sales     DECIMAL(12, 2) NOT NULL,
    upload_id     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    day           DATE NOT NULL,
    sales_channel VARCHAR NOT NULL,
    sku           VARCHAR NOT NULL,
    on_hand       INTEGER NOT NULL,
    upload_id     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id    VARCHAR PRIMARY KEY,
    day           DATE NOT NULL,
    anomaly       VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id VARCHAR PRIMARY KEY,
    anomaly_id       VARCHAR NOT NULL,
    investigated_at  TIMESTAMP NOT NULL,
    investigation    VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS anomaly_clearances (
    anomaly_id    VARCHAR PRIMARY KEY,
    cleared_at    TIMESTAMP NOT NULL,
    clearance     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS flagged_reorders (
    action_id     VARCHAR NOT NULL,
    flagged_at    TIMESTAMP NOT NULL,
    flag          VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS uploader_messages (
    upload_id     VARCHAR NOT NULL,
    sent_at       TIMESTAMP NOT NULL,
    recipient     VARCHAR NOT NULL,
    subject       VARCHAR NOT NULL,
    body          VARCHAR NOT NULL
);
"""

_ANOMALY: TypeAdapter[Anomaly] = TypeAdapter(Anomaly)

# Upload statuses whose rows are in the BI data.
_LOADED = "'accepted', 'safe_fixed'"
# Rows per INSERT statement when loading an Upload.
_INSERT_BATCH = 500


class BiStore:
    def __init__(self, database: str = ":memory:") -> None:
        self._db = duckdb.connect(database)
        self._db.execute(_SCHEMA)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._db

    def processed_upload_ids(self) -> set[str]:
        return {row[0] for row in self._db.execute("SELECT upload_id FROM uploads").fetchall()}

    def record_upload(
        self, upload: Upload, status: UploadStatus, processed_at: datetime, defects: list[Defect]
    ) -> None:
        self._db.execute(
            "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            [
                upload.upload_id,
                upload.sales_channel,
                upload.day,
                upload.kind.value,
                upload.uploader,
                upload.submitted_at,
                status.value,
                processed_at,
                json.dumps([d.model_dump(mode="json") for d in defects]),
            ],
        )
        self._record_status(upload.upload_id, status, processed_at)

    def set_status(self, upload_id: str, status: UploadStatus, changed_at: datetime) -> None:
        """Change an Upload's status, keeping the change in its history; no-op if it is unchanged."""
        if self.status(upload_id) is status:
            return
        self._db.execute("UPDATE uploads SET status = ? WHERE upload_id = ?", [status.value, upload_id])
        self._record_status(upload_id, status, changed_at)

    def supersede(self, upload_id: str, superseded_by: str, changed_at: datetime) -> None:
        """Mark an Upload Superseded by a later one and take its rows out of the BI data."""
        self.unload(upload_id)
        self._db.execute(
            "UPDATE uploads SET superseded_by = ? WHERE upload_id = ?", [superseded_by, upload_id]
        )
        self.set_status(upload_id, UploadStatus.SUPERSEDED, changed_at)

    def add_defects(self, upload_id: str, defects: list[Defect]) -> None:
        """Add Defects found after Intake, by a Data Problem, to an Upload's Defects."""
        row = self._db.execute("SELECT defects FROM uploads WHERE upload_id = ?", [upload_id]).fetchone()
        if row is None:
            raise KeyError(f"no processed Upload {upload_id}")
        merged = [*json.loads(row[0]), *(d.model_dump(mode="json") for d in defects)]
        self._db.execute(
            "UPDATE uploads SET defects = ? WHERE upload_id = ?", [json.dumps(merged), upload_id]
        )

    def status(self, upload_id: str) -> UploadStatus:
        row = self._db.execute("SELECT status FROM uploads WHERE upload_id = ?", [upload_id]).fetchone()
        if row is None:
            raise KeyError(f"no processed Upload {upload_id}")
        return UploadStatus(row[0])

    def superseded_by(self, upload_id: str) -> str | None:
        row = self._db.execute(
            "SELECT superseded_by FROM uploads WHERE upload_id = ?", [upload_id]
        ).fetchone()
        if row is None:
            raise KeyError(f"no processed Upload {upload_id}")
        return row[0]

    def upload_days(self) -> list[date]:
        """Every day with a processed Upload, oldest first."""
        return [r[0] for r in self._db.execute("SELECT DISTINCT day FROM uploads ORDER BY day").fetchall()]

    def current_upload_ids(self, sales_channel: str, day: date, kind: UploadKind) -> list[str]:
        """Processed Uploads for the Sales Channel, day and kind that are not Superseded."""
        rows = self._db.execute(
            "SELECT upload_id FROM uploads WHERE sales_channel = ? AND day = ? AND kind = ? "
            "AND status <> ? ORDER BY submitted_at, upload_id",
            [sales_channel, day, kind.value, UploadStatus.SUPERSEDED.value],
        ).fetchall()
        return [r[0] for r in rows]

    def _record_status(self, upload_id: str, status: UploadStatus, changed_at: datetime) -> None:
        self._db.execute(
            "INSERT INTO upload_status_history VALUES (?, ?, ?)", [upload_id, changed_at, status.value]
        )

    def upload_day(self, upload_id: str) -> date:
        row = self._db.execute("SELECT day FROM uploads WHERE upload_id = ?", [upload_id]).fetchone()
        if row is None:
            raise KeyError(f"no processed Upload {upload_id}")
        return row[0]

    def unload(self, upload_id: str) -> None:
        """Take an Upload's rows out of the BI data."""
        self._db.execute("DELETE FROM sales WHERE upload_id = ?", [upload_id])
        self._db.execute("DELETE FROM inventory WHERE upload_id = ?", [upload_id])

    def record_uploader_message(self, message: UploaderMessage) -> None:
        self._db.execute(
            "INSERT INTO uploader_messages VALUES (?, ?, ?, ?, ?)",
            [message.upload_id, message.sent_at, message.recipient, message.subject, message.body],
        )

    def uploader_messages(self) -> list[UploaderMessage]:
        """Every message sent to an Uploader, newest first."""
        rows = self._db.execute(
            "SELECT upload_id, sent_at, recipient, subject, body FROM uploader_messages ORDER BY rowid DESC"
        ).fetchall()
        return [
            UploaderMessage(upload_id=r[0], sent_at=r[1], recipient=r[2], subject=r[3], body=r[4])
            for r in rows
        ]

    def record_anomaly(self, anomaly: Anomaly) -> None:
        self._db.execute(
            "INSERT INTO anomalies VALUES (?, ?, ?)",
            [anomaly.anomaly_id, anomaly.day, _ANOMALY.dump_json(anomaly).decode()],
        )

    def anomaly_ids(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT anomaly_id FROM anomalies").fetchall()}

    def anomalies(self) -> list[Anomaly]:
        """Every Anomaly flagged, oldest first."""
        rows = self._db.execute("SELECT anomaly FROM anomalies ORDER BY day, anomaly_id").fetchall()
        return [_ANOMALY.validate_json(r[0]) for r in rows]

    def record_clearance(self, cleared: ClearedAnomaly) -> None:
        self._db.execute(
            "INSERT INTO anomaly_clearances VALUES (?, ?, ?)",
            [cleared.anomaly_id, cleared.cleared_at, cleared.model_dump_json()],
        )

    def cleared_anomalies(self) -> list[ClearedAnomaly]:
        """Every Anomaly cleared after a Supersede, newest first."""
        rows = self._db.execute(
            "SELECT clearance FROM anomaly_clearances ORDER BY cleared_at DESC, rowid DESC"
        ).fetchall()
        return [ClearedAnomaly.model_validate_json(r[0]) for r in rows]

    def record_flag(self, flag: FlaggedReorder) -> None:
        self._db.execute(
            "INSERT INTO flagged_reorders VALUES (?, ?, ?)",
            [flag.action_id, flag.flagged_at, flag.model_dump_json()],
        )

    def flagged_reorders(self) -> list[FlaggedReorder]:
        """Every placed Reorder flagged for a person after a Supersede, newest first."""
        rows = self._db.execute(
            "SELECT flag FROM flagged_reorders ORDER BY flagged_at DESC, rowid DESC"
        ).fetchall()
        return [FlaggedReorder.model_validate_json(r[0]) for r in rows]

    def record_investigation(self, investigation: Investigation) -> None:
        self._db.execute(
            "INSERT INTO investigations VALUES (?, ?, ?, ?)",
            [
                investigation.investigation_id,
                investigation.anomaly.anomaly_id,
                investigation.investigated_at,
                investigation.model_dump_json(),
            ],
        )

    def investigations(self) -> list[Investigation]:
        """Every Investigation, newest first."""
        rows = self._db.execute(
            "SELECT investigation FROM investigations ORDER BY investigated_at DESC, rowid DESC"
        ).fetchall()
        return [Investigation.model_validate_json(r[0]) for r in rows]

    def load_sales(self, upload: Upload, lines: list[SalesLine]) -> None:
        if not lines:
            return
        self._insert(
            "sales",
            [
                (
                    line.day,
                    upload.sales_channel,
                    line.sku,
                    line.quantity_sold,
                    line.net_sales,
                    upload.upload_id,
                )
                for line in lines
            ],
        )

    def load_inventory(self, upload: Upload, lines: list[StockLine]) -> None:
        if not lines:
            return
        self._insert(
            "inventory",
            [(line.day, upload.sales_channel, line.sku, line.on_hand, upload.upload_id) for line in lines],
        )

    def _insert(self, table: str, rows: list[tuple[object, ...]]) -> None:
        """Insert rows in one multi-row statement; DuckDB's executemany is slow row by row."""
        for start in range(0, len(rows), _INSERT_BATCH):
            batch = rows[start : start + _INSERT_BATCH]
            placeholders = "(" + ", ".join("?" * len(batch[0])) + ")"
            self._db.execute(
                f"INSERT INTO {table} VALUES " + ", ".join([placeholders] * len(batch)),
                [value for row in batch for value in row],
            )

    def uploads(self) -> list[UploadOutcome]:
        rows = self._db.execute(
            "SELECT upload_id, sales_channel, day, kind, uploader, status, processed_at, defects, "
            "superseded_by FROM uploads ORDER BY day, sales_channel, kind, submitted_at, upload_id"
        ).fetchall()
        history: dict[str, list[UploadStatusChange]] = {}
        for upload_id, changed_at, status in self._db.execute(
            "SELECT upload_id, changed_at, status FROM upload_status_history ORDER BY rowid"
        ).fetchall():
            history.setdefault(upload_id, []).append(
                UploadStatusChange(changed_at=changed_at, status=UploadStatus(status))
            )
        return [
            UploadOutcome(
                upload_id=r[0],
                sales_channel=r[1],
                day=r[2],
                kind=UploadKind(r[3]),
                uploader=r[4],
                status=UploadStatus(r[5]),
                processed_at=r[6],
                defects=[Defect.model_validate(d) for d in json.loads(r[7])],
                superseded_by=r[8],
                history=history.get(r[0], []),
            )
            for r in rows
        ]

    def sales_by_sales_channel(self) -> list[tuple[date, str, int, float]]:
        rows = self._db.execute(
            "SELECT s.day, s.sales_channel, SUM(s.quantity_sold), SUM(s.net_sales) "
            "FROM sales s JOIN uploads u USING (upload_id) "
            "WHERE u.status IN ('accepted', 'safe_fixed') "
            "GROUP BY s.day, s.sales_channel ORDER BY s.day, s.sales_channel"
        ).fetchall()
        return [(r[0], r[1], int(r[2]), float(r[3])) for r in rows]

    def inventory_by_sales_channel(self) -> list[tuple[date, str, int, int]]:
        """Per day and Sales Channel: SKUs stocked and total units on hand."""
        rows = self._db.execute(
            "SELECT i.day, i.sales_channel, COUNT(*) FILTER (WHERE i.on_hand > 0), SUM(i.on_hand) "
            "FROM inventory i JOIN uploads u USING (upload_id) "
            "WHERE u.status IN ('accepted', 'safe_fixed') "
            "GROUP BY i.day, i.sales_channel ORDER BY i.day, i.sales_channel"
        ).fetchall()
        return [(r[0], r[1], int(r[2]), int(r[3])) for r in rows]

    def latest_inventory_day(self) -> date | None:
        row = self._db.execute(
            "SELECT MAX(i.day) FROM inventory i JOIN uploads u USING (upload_id) "
            "WHERE u.status IN ('accepted', 'safe_fixed')"
        ).fetchone()
        return row[0] if row else None

    # Read-only queries for Anomaly detection and the Analyst's tools.

    def stock_on(self, day: date) -> dict[tuple[str, str], int]:
        """Accepted units on hand by (Sales Channel, SKU) at the end of the day."""
        rows = self._db.execute(
            "SELECT i.sales_channel, i.sku, SUM(i.on_hand) "
            "FROM inventory i JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND i.day = ? GROUP BY i.sales_channel, i.sku",
            [day],
        ).fetchall()
        return {(r[0], r[1]): int(r[2]) for r in rows}

    def units_sold_between(self, first: date, last: date) -> dict[tuple[str, str], int]:
        """Accepted units sold by (Sales Channel, SKU) over the days, both included."""
        rows = self._db.execute(
            "SELECT s.sales_channel, s.sku, SUM(s.quantity_sold) "
            "FROM sales s JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND s.day BETWEEN ? AND ? GROUP BY s.sales_channel, s.sku",
            [first, last],
        ).fetchall()
        return {(r[0], r[1]): int(r[2]) for r in rows}

    def sales_days_between(self, first: date, last: date) -> dict[str, int]:
        """By Sales Channel: how many of the days have accepted sales."""
        rows = self._db.execute(
            "SELECT s.sales_channel, COUNT(DISTINCT s.day) "
            "FROM sales s JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND s.day BETWEEN ? AND ? GROUP BY s.sales_channel",
            [first, last],
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def inventory_days_before(self, day: date) -> dict[str, date]:
        """By Sales Channel: the latest day before the given one with accepted inventory."""
        rows = self._db.execute(
            "SELECT i.sales_channel, MAX(i.day) FROM inventory i JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND i.day < ? GROUP BY i.sales_channel",
            [day],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def daily_sales(
        self, sales_channel: str, sku: str, first: date, last: date
    ) -> list[tuple[date, int, float]]:
        """Accepted units and net sales of the SKU at the Sales Channel each day with accepted sales."""
        rows = self._db.execute(
            "SELECT s.day, SUM(s.quantity_sold), SUM(s.net_sales) "
            "FROM sales s JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND s.sales_channel = ? AND s.sku = ? "
            "AND s.day BETWEEN ? AND ? GROUP BY s.day ORDER BY s.day",
            [sales_channel, sku, first, last],
        ).fetchall()
        return [(r[0], int(r[1]), float(r[2])) for r in rows]

    def daily_sales_channel_totals(self, first: date, last: date) -> list[tuple[date, str, int]]:
        """Accepted units sold, every SKU together, per day and Sales Channel with accepted sales."""
        rows = self._db.execute(
            "SELECT s.day, s.sales_channel, SUM(s.quantity_sold) "
            "FROM sales s JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND s.day BETWEEN ? AND ? "
            "GROUP BY s.day, s.sales_channel ORDER BY s.day, s.sales_channel",
            [first, last],
        ).fetchall()
        return [(r[0], r[1], int(r[2])) for r in rows]

    def daily_stock(self, sales_channel: str, sku: str, first: date, last: date) -> list[tuple[date, int]]:
        """Accepted units of the SKU on hand at the Sales Channel at the end of each day."""
        rows = self._db.execute(
            "SELECT i.day, SUM(i.on_hand) FROM inventory i JOIN uploads u USING (upload_id) "
            f"WHERE u.status IN ({_LOADED}) AND i.sales_channel = ? AND i.sku = ? "
            "AND i.day BETWEEN ? AND ? GROUP BY i.day ORDER BY i.day",
            [sales_channel, sku, first, last],
        ).fetchall()
        return [(r[0], int(r[1])) for r in rows]

    def inventory_by_sku(self, day: date) -> list[tuple[str, str, int]]:
        """Per Sales Channel and SKU: units on hand at the end of the day."""
        rows = self._db.execute(
            "SELECT i.sales_channel, i.sku, SUM(i.on_hand) "
            "FROM inventory i JOIN uploads u USING (upload_id) "
            "WHERE u.status IN ('accepted', 'safe_fixed') AND i.day = ? "
            "GROUP BY i.sales_channel, i.sku ORDER BY i.sales_channel, i.sku",
            [day],
        ).fetchall()
        return [(r[0], r[1], int(r[2])) for r in rows]
