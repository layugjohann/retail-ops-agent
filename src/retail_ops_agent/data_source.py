"""The Data Source seam: how Uploads arrive. CSV files on disk are the only implementation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Protocol

from retail_ops_agent.uploads import Upload


class DataSource(Protocol):
    def put(self, upload: Upload) -> None: ...

    def uploads_for(self, day: date) -> list[Upload]:
        """Every Upload submitted for the day, oldest first."""
        ...


class CsvDataSource:
    """Stores each Upload as a CSV with a small JSON sidecar describing it."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def put(self, upload: Upload) -> None:
        day_dir = self._directory / upload.day.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / f"{upload.upload_id}.csv").write_text(upload.content, encoding="utf-8")
        meta = upload.model_dump(mode="json", exclude={"content"})
        (day_dir / f"{upload.upload_id}.json").write_text(json.dumps(meta), encoding="utf-8")

    def uploads_for(self, day: date) -> list[Upload]:
        day_dir = self._directory / day.isoformat()
        if not day_dir.is_dir():
            return []
        uploads: list[Upload] = []
        for meta_path in day_dir.glob("*.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = meta_path.with_suffix(".csv").read_text(encoding="utf-8")
            uploads.append(Upload.model_validate({**meta, "content": content}))
        return sorted(uploads, key=lambda u: (u.submitted_at, u.upload_id))


class InMemoryDataSource:
    """Keeps Uploads in memory only, so nothing is written to disk (a Live Mode Visitor's sandbox)."""

    def __init__(self) -> None:
        self._uploads: list[Upload] = []

    def put(self, upload: Upload) -> None:
        self._uploads.append(upload)

    def uploads_for(self, day: date) -> list[Upload]:
        return sorted((u for u in self._uploads if u.day == day), key=lambda u: (u.submitted_at, u.upload_id))
