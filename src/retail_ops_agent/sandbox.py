"""Builds a seeded Cobalt Home sandbox behind the Ops Day boundary, with some Ops Days run."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    DefectPlan,
    ResubmissionPlan,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind

UPLOAD_TIME = time(21, 0)
# How long after the first Uploads a planned resubmission arrives, before the Ops Day runs.
RESUBMISSION_DELAY = timedelta(hours=1)
GROUND_TRUTH_FILE = "ground_truth.json"


def build_sandbox(
    *,
    seed: int,
    models: Models,
    first_day: date,
    days: int,
    defects: Sequence[DefectPlan] = (),
    resubmissions: Sequence[ResubmissionPlan] = (),
    upload_directory: Path | None = None,
) -> OpsDay:
    """Submit every Sales Channel's sales and inventory Uploads for each day and process those Ops Days.

    Uploads are clean except for the planned Defects. Each planned resubmission is submitted after
    its day's Ops Day and processed by the next one, so it Supersedes the first Upload. The
    ground-truth record of what was planted is written beside the Uploads.
    """
    catalog = generate_catalog(seed)
    generated = generate_uploads(generate_history(catalog, first_day, days), defects, resubmissions)
    clock = SimulatedClock(datetime.combine(first_day, UPLOAD_TIME))
    directory = upload_directory or Path(tempfile.mkdtemp(prefix="cobalt-home-uploads-"))
    directory.mkdir(parents=True, exist_ok=True)
    generated.ground_truth.write(directory / GROUND_TRUTH_FILE)
    ops_day = OpsDay(
        models=models,
        erp=InMemoryErp(catalog),
        notifier=LogNotifier(),
        data_source=CsvDataSource(directory),
        clock=clock,
    )
    channel_kinds = {c.code: c.kind for c in catalog.sales_channels}
    days_run = generated.history.days
    for day in days_run:
        for channel in catalog.sales_channels:
            for kind in UploadKind:
                ops_day.submit_upload(
                    sales_channel=channel.code,
                    day=day,
                    kind=kind,
                    content=generated.content(channel.code, day, kind),
                    uploader=_uploader(channel.code, channel.kind),
                )
        ops_day.run_ops_day(day)
        # Resubmissions arrive after the Ops Day has processed the first Uploads; the next Ops Day
        # picks them up.
        clock.advance(RESUBMISSION_DELAY)
        for plan in resubmissions:
            if plan.day == day:
                ops_day.submit_upload(
                    sales_channel=plan.sales_channel,
                    day=day,
                    kind=plan.upload_kind,
                    content=generated.resubmission(plan.sales_channel, day, plan.upload_kind),
                    uploader=_uploader(plan.sales_channel, channel_kinds[plan.sales_channel]),
                )
        clock.advance(datetime.combine(day + timedelta(days=1), UPLOAD_TIME) - clock.now())
    if any(plan.day == days_run[-1] for plan in resubmissions):
        ops_day.run_ops_day(days_run[-1])
    return ops_day


def _uploader(sales_channel: str, kind: SalesChannelKind) -> str:
    if kind is SalesChannelKind.ONLINE_SHOP:
        return "ecommerce@cobalthome.example"
    return f"manager.{sales_channel.lower()}@cobalthome.example"
