from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import generate_catalog
from retail_ops_agent.live import new_live_sandbox
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.sandbox import Sandbox

# Unit tests never reach a real model.
models.ALLOW_MODEL_REQUESTS = False

SEED = 42


@pytest.fixture(autouse=True)
def _no_model_keys(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "RETAIL_OPS_MODEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def catalog() -> Catalog:
    return generate_catalog(SEED)


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(datetime(2026, 3, 2, 21, 0))


@pytest.fixture
def notifier() -> LogNotifier:
    return LogNotifier()


def scripted_intake_model(**output: object) -> TestModel:
    """A scripted Intake model; by default it reports no Defects of its own."""
    return TestModel(custom_output_args={"defects": [], "uploader_message": None, **output})


def scripted_analyst_model(**output: object) -> TestModel:
    """A scripted Analyst model that calls every read-only tool, then returns its Investigation."""
    return TestModel(
        custom_output_args={
            "cause": "A demand surge drained the stock.",
            "evidence": ["Sales over the last three days far above the SKU's usual rate."],
            "recommended_action": {"kind": "alert", "description": "Alert the inventory planner."},
            **output,
        }
    )


def scripted_ops_model(**output: object) -> TestModel:
    """A scripted Ops model that proposes an alert."""
    return TestModel(
        custom_output_args={"kind": "alert", "subject": "Stockout risk", "body": "Check stock.", **output}
    )


def scripted_models(intake: TestModel | None = None) -> Models:
    return Models(
        intake=intake or scripted_intake_model(),
        analyst=scripted_analyst_model(),
        ops=scripted_ops_model(),
    )


@pytest.fixture
def ops_day(catalog: Catalog, clock: SimulatedClock, notifier: LogNotifier, tmp_path: Path) -> OpsDay:
    return OpsDay(
        models=scripted_models(),
        erp=InMemoryErp(catalog),
        notifier=notifier,
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=clock,
    )


@pytest.fixture(scope="session")
def seeded_live_sandbox() -> Sandbox:
    """The Live Mode sandbox, seeded once per session (once per xdist worker): seeding runs its first
    Ops Days, which takes seconds. Tests never use it directly, only a copy from live_sandbox."""
    return new_live_sandbox()


@pytest.fixture
def live_sandbox(seeded_live_sandbox: Sandbox) -> Sandbox:
    """A freshly seeded Live Mode sandbox of this test's own: a copy, so no test sees another's changes."""
    return deepcopy(seeded_live_sandbox)
