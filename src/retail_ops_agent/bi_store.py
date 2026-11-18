"""The BI store: DuckDB holding accepted data and every Upload's status."""

from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from retail_ops_agent.intake import Defect, StoreSalesLine
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
CREATE TABLE IF NOT EXISTS store_sales (
    day           DATE NOT NULL,
    sales_channel VARCHAR NOT NULL,
    sku           VARCHAR NOT NULL,
    quantity_sold INTEGER NOT NULL,
    net_sales     DECIMAL(12, 2) NOT NULL,
    upload_id     VARCHAR NOT NULL
);
"""


class BiStore:
    def __init__(self, database: str = ":memory:") -> None:
        self._db = duckdb.connect(database)
        self._db.execute(_SCHEMA)

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

    def load_store_sales(self, upload: Upload, lines: list[StoreSalesLine]) -> None:
        self._db.executemany(
            "INSERT INTO store_sales VALUES (?, ?, ?, ?, ?, ?)",
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
            "FROM store_sales s JOIN uploads u USING (upload_id) "
            "WHERE u.status IN ('accepted', 'safe_fixed') "
            "GROUP BY s.day, s.sales_channel ORDER BY s.day, s.sales_channel"
        ).fetchall()
        return [(r[0], r[1], int(r[2]), float(r[3])) for r in rows]
