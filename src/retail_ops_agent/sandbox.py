"""Builds a seeded Cobalt Home sandbox behind the Ops Day boundary, with some Ops Days run."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from retail_ops_agent.action_policy import DEFAULT_AUTO_APPROVAL_LIMIT
from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource, DataSource
from retail_ops_agent.erp import ErpClient, InMemoryErp
from retail_ops_agent.generator import (
    AnomalyPlan,
    DefectPlan,
    GroundTruth,
    InjectionPlan,
    LookalikePlan,
    ResubmissionPlan,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier, Notifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.uploads import UploadKind
from retail_ops_agent.views import OpsDayOutcome

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
    anomalies: Sequence[AnomalyPlan] = (),
    lookalikes: Sequence[LookalikePlan] = (),
    injections: Sequence[InjectionPlan] = (),
    upload_directory: Path | None = None,
    sales_channels: Sequence[str] | None = None,
    upload_kinds: Sequence[UploadKind] = tuple(UploadKind),
    auto_approval_limit: float = DEFAULT_AUTO_APPROVAL_LIMIT,
    run_days: int | None = None,
    erp: ErpClient | None = None,
    on_ops_day: Callable[[OpsDay, OpsDayOutcome], None] | None = None,
) -> OpsDay:
    """Submit every Sales Channel's sales and inventory Uploads for each day and process those Ops Days.

    sales_channels and upload_kinds narrow which Uploads are submitted (every Sales Channel and both
    kinds by default), so an eval can keep its model calls few.

    run_days, if given, runs only that many of the generated days, so the sandbox can stop while a
    Reorder queued from a planted Anomaly is still within its 48 simulated hours.

    Uploads are clean except for the planned Defects, Anomalies, lookalikes and prompt injections.
    Each planned resubmission is submitted after its day's Ops Day and processed by the next one, so
    it Supersedes the first Upload. The ground-truth record of what was planted is written beside the Uploads.

    erp is the ERP the sandbox's Ops Day uses; by default a fresh in-memory fake seeded from the
    catalog. An eval passes its own so it can see every Reorder that reached the ERP.

    on_ops_day, if given, is called with the Ops Day and its outcome after each Ops Day is processed,
    so Replay Mode can record it.
    """
    directory = upload_directory or Path(tempfile.mkdtemp(prefix="cobalt-home-uploads-"))
    directory.mkdir(parents=True, exist_ok=True)
    sandbox = Sandbox(
        seed=seed,
        models=models,
        first_day=first_day,
        days=days,
        defects=defects,
        resubmissions=resubmissions,
        anomalies=anomalies,
        lookalikes=lookalikes,
        injections=injections,
        data_source=CsvDataSource(directory),
        sales_channels=sales_channels,
        upload_kinds=upload_kinds,
        auto_approval_limit=auto_approval_limit,
        erp=erp,
    )
    sandbox.ground_truth.write(directory / GROUND_TRUTH_FILE)
    days_run = sandbox.days[:run_days]
    for _ in days_run:
        _ran(sandbox.ops_day, sandbox.run_day(), on_ops_day)
    if any(plan.day == days_run[-1] for plan in resubmissions):
        _ran(sandbox.ops_day, sandbox.ops_day.run_ops_day(days_run[-1]), on_ops_day)
    return sandbox.ops_day


class Sandbox:
    """A seeded Cobalt Home behind the Ops Day boundary whose generated days are run one at a time.

    Every Sales Channel's Uploads for a day are submitted only when that day is run, so Uploads of
    one's own (a Live Mode Visitor's) can be submitted first and take their place.
    """

    def __init__(
        self,
        *,
        seed: int,
        models: Models,
        first_day: date,
        days: int,
        data_source: DataSource,
        defects: Sequence[DefectPlan] = (),
        resubmissions: Sequence[ResubmissionPlan] = (),
        anomalies: Sequence[AnomalyPlan] = (),
        lookalikes: Sequence[LookalikePlan] = (),
        injections: Sequence[InjectionPlan] = (),
        sales_channels: Sequence[str] | None = None,
        upload_kinds: Sequence[UploadKind] = tuple(UploadKind),
        auto_approval_limit: float = DEFAULT_AUTO_APPROVAL_LIMIT,
        erp: ErpClient | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        """notifier receives the sandbox's messages to Uploaders and alerts; a LogNotifier by default."""
        catalog = generate_catalog(seed)
        self._generated = generate_uploads(
            generate_history(catalog, first_day, days, anomalies, lookalikes),
            defects,
            resubmissions,
            injections,
        )
        self._resubmissions = tuple(resubmissions)
        self._upload_kinds = tuple(upload_kinds)
        self._clock = SimulatedClock(datetime.combine(first_day, UPLOAD_TIME))
        self.ops_day = OpsDay(
            models=models,
            erp=erp if erp is not None else InMemoryErp(catalog),
            notifier=notifier if notifier is not None else LogNotifier(),
            data_source=data_source,
            clock=self._clock,
            auto_approval_limit=auto_approval_limit,
        )
        self._channel_kinds = {c.code: c.kind for c in catalog.sales_channels}
        self._submitting = [
            c.code for c in catalog.sales_channels if sales_channels is None or c.code in sales_channels
        ]
        self._next = 0
        # The day whose generated Uploads are already submitted, though its Ops Day has not finished.
        self._submitted: date | None = None
        # Uploads submitted by hand for a day not yet run; the generated ones are left out for them.
        self._own: set[tuple[str, date, UploadKind]] = set()

    @property
    def days(self) -> tuple[date, ...]:
        """Every generated day, in order."""
        return tuple(self._generated.history.days)

    @property
    def ground_truth(self) -> GroundTruth:
        return self._generated.ground_truth

    @property
    def sales_channels(self) -> list[str]:
        return list(self._channel_kinds)

    @property
    def next_day(self) -> date | None:
        """The next generated day to run, or None once every one has run."""
        return self.days[self._next] if self._next < len(self.days) else None

    @property
    def days_run(self) -> tuple[date, ...]:
        return self.days[: self._next]

    def run_day(self, models: Models | None = None) -> OpsDayOutcome:
        """Submit the next day's generated Uploads and run its Ops Day, then submit any planned
        resubmissions for it and move simulated time on to the next day's Uploads.

        models, if given, are used for this Ops Day only. If the Ops Day fails (a model outage or
        rate limit), the day stays next and its Uploads are not submitted again when it is retried.
        """
        day = self.next_day
        if day is None:
            raise ValueError("every generated day has already run; reset the sandbox to start again")
        if self._submitted != day:
            for channel in self._submitting:
                for kind in self._upload_kinds:
                    if (channel, day, kind) in self._own:
                        continue
                    self.ops_day.submit_upload(
                        sales_channel=channel,
                        day=day,
                        kind=kind,
                        content=self._generated.content(channel, day, kind),
                        uploader=_uploader(channel, self._channel_kinds[channel]),
                    )
            self._submitted = day
        outcome = self.ops_day.run_ops_day(day, models=models)
        self._next += 1
        # Resubmissions arrive after the Ops Day has processed the first Uploads; the next Ops Day
        # picks them up.
        self.ops_day.advance_time(RESUBMISSION_DELAY)
        for plan in self._resubmissions:
            if plan.day == day:
                self.ops_day.submit_upload(
                    sales_channel=plan.sales_channel,
                    day=day,
                    kind=plan.upload_kind,
                    content=self._generated.resubmission(plan.sales_channel, day, plan.upload_kind),
                    uploader=_uploader(plan.sales_channel, self._channel_kinds[plan.sales_channel]),
                )
        next_uploads = datetime.combine(day + timedelta(days=1), UPLOAD_TIME)
        self.ops_day.advance_time(max(next_uploads - self._clock.now(), timedelta(0)))
        return outcome

    def generated_upload(self, sales_channel: str, day: date, kind: UploadKind) -> str:
        """The generated Upload for a Sales Channel, day and kind, as a starting point to edit."""
        return self._generated.content(sales_channel, day, kind)

    def submit_own_upload(self, *, sales_channel: str, day: date, kind: UploadKind, content: str) -> str:
        """Submit an Upload of one's own through the Ops Day boundary. Returns its upload id.

        For the next day to run it takes the place of the generated Upload for that Sales Channel and
        kind. For a day already run it is a resubmission: the next Ops Day processes it and it
        Supersedes the earlier Upload.
        """
        if sales_channel not in self._channel_kinds:
            raise ValueError(f"unknown Sales Channel {sales_channel!r}")
        if day not in self.days_run and day != self.next_day:
            raise ValueError(f"{day} is neither a day already run nor the next day to run")
        upload_id = self.ops_day.submit_upload(
            sales_channel=sales_channel,
            day=day,
            kind=kind,
            content=content,
            uploader=_uploader(sales_channel, self._channel_kinds[sales_channel]),
        )
        if day == self.next_day:
            self._own.add((sales_channel, day, kind))
        return upload_id


def _ran(
    ops_day: OpsDay, outcome: OpsDayOutcome, on_ops_day: Callable[[OpsDay, OpsDayOutcome], None] | None
) -> None:
    if on_ops_day is not None:
        on_ops_day(ops_day, outcome)


def _uploader(sales_channel: str, kind: SalesChannelKind) -> str:
    if kind is SalesChannelKind.ONLINE_SHOP:
        return "ecommerce@cobalthome.example"
    return f"manager.{sales_channel.lower()}@cobalthome.example"
