"""The BI store: DuckDB holding accepted data and every Upload's status."""

from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from retail_ops_agent.defects import Defect
from retail_ops_agent.upload_formats import SalesLine, StockLine
from retail_ops_agent.uploads import Upload, UploadKind, UploadStatus
from retail_ops_agent.views import UploadOutcome

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
    defects       VARCHAR NOT NULL
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
"""


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
            "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def set_status(self, upload_id: str, status: UploadStatus) -> None:
        self._db.execute("UPDATE uploads SET status = ? WHERE upload_id = ?", [status.value, upload_id])

    def upload_day(self, upload_id: str) -> date:
        row = self._db.execute("SELECT day FROM uploads WHERE upload_id = ?", [upload_id]).fetchone()
        if row is None:
            raise KeyError(f"no processed Upload {upload_id}")
        return row[0]

    def unload(self, upload_id: str) -> None:
        """Take an Upload's rows out of the BI data."""
        self._db.execute("DELETE FROM sales WHERE upload_id = ?", [upload_id])
        self._db.execute("DELETE FROM inventory WHERE upload_id = ?", [upload_id])

    def load_sales(self, upload: Upload, lines: list[SalesLine]) -> None:
        if not lines:
            return
        self._db.executemany(
            "INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)",
            [
                [
                    line.day,
                    upload.sales_channel,
                    line.sku,
                    line.quantity_sold,
                    line.net_sales,
                    upload.upload_id,
                ]
                for line in lines
            ],
        )

    def load_inventory(self, upload: Upload, lines: list[StockLine]) -> None:
        if not lines:
            return
        self._db.executemany(
            "INSERT INTO inventory VALUES (?, ?, ?, ?, ?)",
            [[line.day, upload.sales_channel, line.sku, line.on_hand, upload.upload_id] for line in lines],
        )

    def uploads(self) -> list[UploadOutcome]:
        rows = self._db.execute(
            "SELECT upload_id, sales_channel, day, kind, uploader, status, processed_at, defects "
            "FROM uploads ORDER BY day, sales_channel, kind, submitted_at, upload_id"
        ).fetchall()
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
