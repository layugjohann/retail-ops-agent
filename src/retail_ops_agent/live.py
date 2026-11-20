"""Live Mode: each Visitor's own in-memory sandbox of Cobalt Home, run with real models.

A Visitor's sandbox (BI store, fake ERP, clock and Uploads) lives only in memory for their session
and is seeded from the generator: its first Ops Days are run with the offline scripted model, so
seeding costs no model calls. Every later "Run day" uses real models: the shared free-tier key while
its rate limit allows, then the Visitor's own key, which is used for that Ops Day only and never
stored.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from pydantic_ai.exceptions import ModelQuotaExceededError, ModelRateLimitError
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.data_source import InMemoryDataSource
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import AnomalyPlan, DefectPlan, ResubmissionKind, ResubmissionPlan
from retail_ops_agent.models import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    models_from_environment,
    offline_analyst_model,
    offline_intake_model,
    offline_ops_model,
)
from retail_ops_agent.notifier import Notifier
from retail_ops_agent.ops_day import Models
from retail_ops_agent.sandbox import Sandbox
from retail_ops_agent.uploads import UploadKind
from retail_ops_agent.views import OpsDayOutcome

SEED = 7
FIRST_DAY = date(2026, 11, 1)
# Days generated for the sandbox. The first SEEDED_DAYS are run when it is built; the rest are left
# for the Visitor to run one at a time.
DAYS = 21
SEEDED_DAYS = 13
# Defects planted in the sandbox's Uploads: some with a Safe Fix, so the Audit Log has Safe Fixes to
# show, and some without, so there are Quarantined Uploads and Uploader messages.
PLANTED_DEFECTS = [
    DefectPlan(sales_channel=channel, day=date(2026, 11, day), upload_kind=kind, defect_kind=defect)
    for channel, day, kind, defect in [
        ("ST02", 3, UploadKind.SALES, DefectKind.RENAMED_COLUMN),
        ("ONLINE", 5, UploadKind.INVENTORY, DefectKind.WRONG_DELIMITER),
        ("ST04", 8, UploadKind.INVENTORY, DefectKind.STRAY_WHITESPACE),
        ("ONLINE", 11, UploadKind.SALES, DefectKind.BYTE_ORDER_MARK),
        ("ST03", 6, UploadKind.SALES, DefectKind.MISSING_COLUMN),
        ("ST05", 9, UploadKind.INVENTORY, DefectKind.UNKNOWN_SKU),
        ("ONLINE", 12, UploadKind.SALES, DefectKind.DUPLICATE_DAY),
    ]
]
# Resubmissions in the sandbox: a corrected one gets a Quarantined Upload accepted, and a changed one
# revises figures, so the Upload status view has Superseded Uploads to show.
RESUBMISSIONS = [
    ResubmissionPlan(
        sales_channel=channel, day=date(2026, 11, day), upload_kind=kind, resubmission_kind=change
    )
    for channel, day, kind, change in [
        ("ST03", 6, UploadKind.SALES, ResubmissionKind.CORRECTED),
        ("ST01", 10, UploadKind.INVENTORY, ResubmissionKind.CHANGED),
    ]
]
# A demand surge planted at one Store, so there is a stockout risk to investigate. The risk is
# flagged before the planted day (on Nov 13); seeding stops on that day, so its Reorder is still in
# the Approval Queue, not Expired, when the Visitor opens Live Mode.
PLANTED_ANOMALIES = [
    AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 11, 14)),
]


def offline_models() -> Models:
    return Models(intake=offline_intake_model(), analyst=offline_analyst_model(), ops=offline_ops_model())


def new_live_sandbox(
    seeding_models: Models | None = None,
    *,
    notifier: Notifier | None = None,
    days: int = DAYS,
    seeded_days: int = SEEDED_DAYS,
) -> Sandbox:
    """A fresh sandbox for one Visitor, held only in memory, with its first seeded_days run.

    seeding_models run those first days; the offline scripted model by default, so building a
    sandbox makes no model calls. notifier receives its messages to Uploaders and alerts. days is how
    many days are generated in all; at least seeded_days.
    """
    models = seeding_models or offline_models()
    sandbox = Sandbox(
        seed=SEED,
        models=models,
        first_day=FIRST_DAY,
        days=max(days, seeded_days),
        data_source=InMemoryDataSource(),
        defects=PLANTED_DEFECTS,
        resubmissions=RESUBMISSIONS,
        anomalies=PLANTED_ANOMALIES,
        notifier=notifier,
    )
    for _ in range(seeded_days):
        sandbox.run_day()
    return sandbox


# The shared free-tier key's limit: Ops Days run with it, across every Visitor, per window. An Ops
# Day makes one Intake call per Upload (14) plus two per Anomaly, so 40 a day stays well inside the
# free tiers' daily request limits. Both can be overridden with environment variables.
DEFAULT_SHARED_RUNS = 40
DEFAULT_SHARED_WINDOW_HOURS = 24.0
SHARED_RUNS_VARIABLE = "LIVE_SHARED_RUNS"
SHARED_WINDOW_VARIABLE = "LIVE_SHARED_WINDOW_HOURS"


@dataclass(frozen=True)
class SharedKeyLimit:
    runs: int
    window_hours: float

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> SharedKeyLimit:
        runs = env.get(SHARED_RUNS_VARIABLE, "").strip()
        hours = env.get(SHARED_WINDOW_VARIABLE, "").strip()
        return cls(
            runs=int(runs) if runs else DEFAULT_SHARED_RUNS,
            window_hours=float(hours) if hours else DEFAULT_SHARED_WINDOW_HOURS,
        )

    def describe(self) -> str:
        hours = f"{self.window_hours:g} hour{'s' if self.window_hours != 1 else ''}"
        return f"{self.runs} Ops Day{'s' if self.runs != 1 else ''} every {hours}"


class SharedKeyLimiter:
    """A sliding-window count of Ops Days run with the shared key, shared by every Visitor.

    Only the times of recent runs are kept, in memory; nothing about a Visitor is.
    """

    def __init__(self, limit: SharedKeyLimit, now: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self._now = now
        self._runs: deque[float] = deque()
        self._lock = threading.Lock()

    def _forget_old(self) -> None:
        horizon = self._now() - self.limit.window_hours * 3600
        while self._runs and self._runs[0] <= horizon:
            self._runs.popleft()

    def remaining(self) -> int:
        with self._lock:
            self._forget_old()
            return max(self.limit.runs - len(self._runs), 0)

    def limit_reached(self) -> str:
        return (
            f"The shared free-tier key's limit of {self.limit.describe()} is reached. "
            "Add your own key to keep running Ops Days."
        )

    def try_acquire(self) -> bool:
        """Count one run with the shared key if the limit allows it."""
        with self._lock:
            self._forget_old()
            if len(self._runs) >= self.limit.runs:
                return False
            self._runs.append(self._now())
            return True

    def exhaust(self) -> None:
        """The provider itself refused the shared key: treat the window as used up."""
        with self._lock:
            self._forget_old()
            while len(self._runs) < self.limit.runs:
                self._runs.append(self._now())


class KeyProvider(StrEnum):
    GROQ = "Groq"
    GEMINI = "Google Gemini"


DEFAULT_VISITOR_MODELS = {
    KeyProvider.GROQ: DEFAULT_GROQ_MODEL.removeprefix("groq:"),
    KeyProvider.GEMINI: DEFAULT_GEMINI_MODEL.removeprefix("google:"),
}


@dataclass(frozen=True)
class VisitorKey:
    """A Visitor's own key, used for one Ops Day and never stored. Its repr hides the key."""

    provider: KeyProvider
    api_key: str = field(repr=False)
    model_name: str | None = None

    def model(self) -> Model:
        name = self.model_name or DEFAULT_VISITOR_MODELS[self.provider]
        match self.provider:
            case KeyProvider.GROQ:
                return GroqModel(name, provider=GroqProvider(api_key=self.api_key))
            case KeyProvider.GEMINI:
                return GoogleModel(name, provider=GoogleProvider(api_key=self.api_key))

    def label(self) -> str:
        return f"{self.provider.value} {self.model_name or DEFAULT_VISITOR_MODELS[self.provider]} (your key)"


def visitor_models(key: VisitorKey) -> tuple[Models, str]:
    model = key.model()
    return Models(intake=model, analyst=model, ops=model), key.label()


class OwnKeyNeeded(Exception):
    """The shared key cannot run this Ops Day; the Visitor is asked for their own key."""


@dataclass(frozen=True)
class LiveRun:
    outcome: OpsDayOutcome
    model_label: str
    used_shared_key: bool


def run_live_day(
    sandbox: Sandbox,
    *,
    env: Mapping[str, str],
    limiter: SharedKeyLimiter,
    visitor_key: VisitorKey | None = None,
) -> LiveRun:
    """Run the sandbox's next day through the Ops Day boundary.

    With a Visitor's own key, its models run the day and the shared key's limit is not touched.
    Otherwise the shared models (the shared free-tier key from the environment, or the offline
    scripted model when none is set) run it, if the limit allows; OwnKeyNeeded is raised when it does
    not, or when the provider refuses the shared key for its own rate limit.
    """
    if visitor_key is not None:
        models, label = visitor_models(visitor_key)
        return LiveRun(sandbox.run_day(models), label, used_shared_key=False)
    if not limiter.try_acquire():
        raise OwnKeyNeeded(limiter.limit_reached())
    models, label = models_from_environment(env)
    try:
        outcome = sandbox.run_day(models)
    except (ModelRateLimitError, ModelQuotaExceededError) as refused:
        limiter.exhaust()
        raise OwnKeyNeeded(
            "The shared free-tier key hit its provider's rate limit. Add your own key to keep running "
            "Ops Days."
        ) from refused
    return LiveRun(outcome, f"{label} (shared key)", used_shared_key=True)
