from __future__ import annotations

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
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import Models, OpsDay

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


@pytest.fixture
def ops_day(catalog: Catalog, clock: SimulatedClock, notifier: LogNotifier, tmp_path: Path) -> OpsDay:
    return OpsDay(
        models=Models(intake=scripted_intake_model()),
        erp=InMemoryErp(catalog),
        notifier=notifier,
        data_source=CsvDataSource(tmp_path / "uploads"),
        clock=clock,
    )
