"""Builds a seeded Cobalt Home sandbox behind the Ops Day boundary, with some Ops Days run."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import generate_catalog, generate_store_sales, store_sales_csv
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind

UPLOAD_TIME = time(21, 0)


def build_sandbox(
    *, seed: int, models: Models, first_day: date, days: int, upload_directory: Path | None = None
) -> OpsDay:
    """Submit each Store's clean sales Upload for each day and run those Ops Days."""
    catalog = generate_catalog(seed)
    clock = SimulatedClock(datetime.combine(first_day, UPLOAD_TIME))
    directory = upload_directory or Path(tempfile.mkdtemp(prefix="cobalt-home-uploads-"))
    ops_day = OpsDay(
        models=models,
        erp=InMemoryErp(catalog),
        notifier=LogNotifier(),
        data_source=CsvDataSource(directory),
        clock=clock,
    )
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for store in catalog.stores:
            ops_day.submit_upload(
                sales_channel=store.code,
                day=day,
                kind=UploadKind.SALES,
                content=store_sales_csv(generate_store_sales(catalog, store.code, day)),
                uploader=f"manager.{store.code.lower()}@cobalthome.example",
            )
        ops_day.run_ops_day(day)
        clock.advance(timedelta(days=1))
    return ops_day
