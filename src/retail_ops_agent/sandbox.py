"""Builds a seeded Cobalt Home sandbox behind the Ops Day boundary, with some Ops Days run."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import generate_catalog, generate_history, upload_csv
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind

UPLOAD_TIME = time(21, 0)


def build_sandbox(
    *, seed: int, models: Models, first_day: date, days: int, upload_directory: Path | None = None
) -> OpsDay:
    """Submit every Sales Channel's clean sales and inventory Uploads for each day and run those Ops Days."""
    catalog = generate_catalog(seed)
    history = generate_history(catalog, first_day, days)
    clock = SimulatedClock(datetime.combine(first_day, UPLOAD_TIME))
    directory = upload_directory or Path(tempfile.mkdtemp(prefix="cobalt-home-uploads-"))
    ops_day = OpsDay(
        models=models,
        erp=InMemoryErp(catalog),
        notifier=LogNotifier(),
        data_source=CsvDataSource(directory),
        clock=clock,
    )
    for day in history.days:
        for channel in catalog.sales_channels:
            for kind in UploadKind:
                ops_day.submit_upload(
                    sales_channel=channel.code,
                    day=day,
                    kind=kind,
                    content=upload_csv(history, channel.code, day, kind),
                    uploader=_uploader(channel.code, channel.kind),
                )
        ops_day.run_ops_day(day)
        clock.advance(timedelta(days=1))
    return ops_day


def _uploader(sales_channel: str, kind: SalesChannelKind) -> str:
    if kind is SalesChannelKind.ONLINE_SHOP:
        return "ecommerce@cobalthome.example"
    return f"manager.{sales_channel.lower()}@cobalthome.example"
