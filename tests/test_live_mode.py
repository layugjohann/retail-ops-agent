from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRateLimitError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from retail_ops_agent import data_source, live
from retail_ops_agent.live import (
    FIRST_DAY,
    SEEDED_DAYS,
    KeyProvider,
    OwnKeyNeeded,
    SharedKeyLimit,
    SharedKeyLimiter,
    VisitorKey,
    new_live_sandbox,
    run_live_day,
    visitor_models,
)
from retail_ops_agent.models import offline_analyst_model, offline_intake_model, offline_ops_model
from retail_ops_agent.ops_day import Models
from retail_ops_agent.sandbox import Sandbox
from retail_ops_agent.uploads import UploadKind, UploadStatus

NEXT_DAY = date(2026, 11, 14)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _limiter(runs: int = 5) -> SharedKeyLimiter:
    return SharedKeyLimiter(SharedKeyLimit(runs=runs, window_hours=1))


def _status(sandbox: Sandbox, upload_id: str) -> UploadStatus:
    [upload] = [u for u in sandbox.ops_day.upload_statuses() if u.upload_id == upload_id]
    return upload.status


def _without_last_column(csv: str) -> str:
    return "\n".join(",".join(line.split(",")[:-1]) for line in csv.splitlines()) + "\n"


@pytest.fixture
def sandbox() -> Sandbox:
    return new_live_sandbox()


def test_a_live_sandbox_is_seeded_from_the_generator_with_days_left_to_run(sandbox: Sandbox) -> None:
    assert sandbox.days[0] == FIRST_DAY
    assert len(sandbox.days_run) == SEEDED_DAYS
    assert sandbox.next_day == NEXT_DAY
    assert {u.day for u in sandbox.ops_day.upload_statuses()} == set(sandbox.days_run)
    assert len(sandbox.ops_day.approval_queue()) == 1


def test_a_live_sandbox_writes_nothing_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a Live Mode sandbox must keep everything in memory")

    monkeypatch.setattr(tempfile, "mkdtemp", refuse)
    monkeypatch.setattr(data_source.CsvDataSource, "put", refuse)
    monkeypatch.setattr(Path, "write_text", refuse)
    monkeypatch.setattr(Path, "mkdir", refuse)

    sandbox = new_live_sandbox()
    sandbox.submit_own_upload(
        sales_channel="ST01",
        day=NEXT_DAY,
        kind=UploadKind.SALES,
        content=sandbox.generated_upload("ST01", NEXT_DAY, UploadKind.SALES),
    )
    run_live_day(sandbox, env={}, limiter=_limiter())

    assert sandbox.days_run[-1] == NEXT_DAY


def test_each_visitors_sandbox_is_isolated() -> None:
    mine, theirs = new_live_sandbox(), new_live_sandbox()
    [pending] = mine.ops_day.approval_queue()

    mine.ops_day.approve(pending.action_id, approved_by="Visitor")
    run_live_day(mine, env={}, limiter=_limiter())

    assert mine.ops_day.approval_queue() == []
    assert [q.action_id for q in theirs.ops_day.approval_queue()] == [pending.action_id]
    assert theirs.next_day == NEXT_DAY
    assert NEXT_DAY not in {u.day for u in theirs.ops_day.upload_statuses()}
    assert len(theirs.ops_day.audit_log()) < len(mine.ops_day.audit_log())


def test_run_day_processes_the_next_days_uploads_through_the_ops_day_boundary(sandbox: Sandbox) -> None:
    run = run_live_day(sandbox, env={}, limiter=_limiter())

    assert run.outcome.day == NEXT_DAY
    assert run.used_shared_key
    assert sandbox.next_day == date(2026, 11, 15)
    assert len([u for u in run.outcome.uploads if u.day == NEXT_DAY]) == 2 * len(sandbox.sales_channels)


def test_an_upload_of_ones_own_for_the_next_day_takes_the_generated_ones_place(sandbox: Sandbox) -> None:
    broken = _without_last_column(sandbox.generated_upload("ST01", NEXT_DAY, UploadKind.SALES))

    upload_id = sandbox.submit_own_upload(
        sales_channel="ST01", day=NEXT_DAY, kind=UploadKind.SALES, content=broken
    )
    outcome = sandbox.run_day()

    assert _status(sandbox, upload_id) is UploadStatus.QUARANTINED
    st01_sales = [u for u in outcome.uploads if u.sales_channel == "ST01" and u.kind is UploadKind.SALES]
    assert [u.upload_id for u in st01_sales] == [upload_id]
    assert [m.upload_id for m in outcome.uploader_messages] == [upload_id]


def test_an_upload_of_ones_own_for_a_day_already_run_supersedes_the_earlier_one(sandbox: Sandbox) -> None:
    day = sandbox.days_run[-1]
    earlier = f"ST01-{day.isoformat()}-inventory-001"

    upload_id = sandbox.submit_own_upload(
        sales_channel="ST01",
        day=day,
        kind=UploadKind.INVENTORY,
        content=sandbox.generated_upload("ST01", day, UploadKind.INVENTORY),
    )
    sandbox.run_day()

    assert _status(sandbox, earlier) is UploadStatus.SUPERSEDED
    assert _status(sandbox, upload_id) is UploadStatus.ACCEPTED


def test_an_upload_for_a_day_not_yet_reachable_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(ValueError):
        sandbox.submit_own_upload(
            sales_channel="ST01", day=date(2026, 11, 20), kind=UploadKind.SALES, content="x\n"
        )


def test_once_every_day_has_run_run_day_asks_for_a_reset() -> None:
    sandbox = Sandbox(
        seed=live.SEED,
        models=live.offline_models(),
        first_day=FIRST_DAY,
        days=2,
        data_source=data_source.InMemoryDataSource(),
        sales_channels=["ST01"],
    )
    sandbox.run_day()
    sandbox.run_day()

    assert sandbox.next_day is None
    with pytest.raises(ValueError, match="reset"):
        sandbox.run_day()


def test_the_shared_key_limiter_allows_its_runs_per_window_then_refuses() -> None:
    clock = FakeTime()
    limiter = SharedKeyLimiter(SharedKeyLimit(runs=2, window_hours=1), now=clock)

    assert limiter.try_acquire()
    clock.now = 600
    assert limiter.try_acquire()
    assert not limiter.try_acquire()
    assert limiter.remaining() == 0
    clock.now = 3601
    assert limiter.remaining() == 1
    assert limiter.try_acquire()
    assert not limiter.try_acquire()


def test_the_shared_key_limit_comes_from_the_environment() -> None:
    assert SharedKeyLimit.from_environment({}) == SharedKeyLimit(
        runs=live.DEFAULT_SHARED_RUNS, window_hours=live.DEFAULT_SHARED_WINDOW_HOURS
    )
    assert SharedKeyLimit.from_environment(
        {"LIVE_SHARED_RUNS": "3", "LIVE_SHARED_WINDOW_HOURS": "0.5"}
    ) == SharedKeyLimit(runs=3, window_hours=0.5)


def test_once_the_shared_key_limit_is_reached_the_visitor_needs_their_own_key(sandbox: Sandbox) -> None:
    limiter = _limiter(runs=1)
    run_live_day(sandbox, env={}, limiter=limiter)

    with pytest.raises(OwnKeyNeeded, match="your own key"):
        run_live_day(sandbox, env={}, limiter=limiter)

    assert sandbox.next_day == date(2026, 11, 15)


def test_a_provider_rate_limit_on_the_shared_key_asks_for_the_visitors_own_key(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rate_limited(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ModelRateLimitError("shared", "rate limit reached")

    model = FunctionModel(rate_limited)

    def shared_models(_env: Mapping[str, str]) -> tuple[Models, str]:
        return Models(intake=model, analyst=model, ops=model), "shared"

    monkeypatch.setattr(live, "models_from_environment", shared_models)
    limiter = _limiter(runs=5)

    with pytest.raises(OwnKeyNeeded, match="rate limit"):
        run_live_day(sandbox, env={}, limiter=limiter)

    assert limiter.remaining() == 0
    # The day was not lost: it runs again once a key is available.
    assert sandbox.next_day == NEXT_DAY


def test_the_visitors_own_key_runs_the_day_without_touching_the_shared_limit(sandbox: Sandbox) -> None:
    limiter = _limiter(runs=1)
    assert limiter.try_acquire()
    key = VisitorKey(provider=KeyProvider.GROQ, api_key="gsk-visitor-secret")

    # Unit tests may not reach a real model, so reaching for the Visitor's model is refused, which
    # shows it was their model and not the shared one that ran the day.
    with pytest.raises(RuntimeError, match="not allowed"):
        run_live_day(sandbox, env={}, limiter=limiter, visitor_key=key)

    assert limiter.remaining() == 0
    assert sandbox.next_day == NEXT_DAY
    assert "gsk-visitor-secret" not in repr(key)


@pytest.mark.parametrize("provider", list(KeyProvider))
def test_a_visitors_key_builds_their_models_and_the_label_never_shows_the_key(provider: KeyProvider) -> None:
    models, label = visitor_models(VisitorKey(provider=provider, api_key="secret-123"))

    assert models.intake is models.analyst is models.ops
    assert "secret-123" not in label
    assert "your key" in label


class GptOssLike(WrapperModel):
    """Answers like gpt-oss-120b on Groq: it gives its final answer through a tool it calls "json",
    whatever the agent named its output tool."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await super().request(messages, model_settings, model_request_parameters)
        output_tools = {tool.name for tool in model_request_parameters.output_tools}
        parts = [
            replace(part, tool_name="json")
            if isinstance(part, ToolCallPart) and part.tool_name in output_tools
            else part
            for part in response.parts
        ]
        return replace(response, parts=parts)


def test_a_model_that_answers_through_a_tool_named_json_runs_every_agent(sandbox: Sandbox) -> None:
    models = Models(
        intake=GptOssLike(offline_intake_model()),
        analyst=GptOssLike(offline_analyst_model()),
        ops=GptOssLike(offline_ops_model()),
    )

    outcomes = [sandbox.run_day(models) for _ in range(len(sandbox.days) - SEEDED_DAYS)]

    # Every agent ran: Intake on each Upload, the Analyst and Ops agents on each Anomaly.
    assert any(outcome.anomalies for outcome in outcomes)
    assert any(outcome.reorders for outcome in outcomes)


def test_a_shared_key_day_that_fails_for_another_reason_gives_its_slot_back(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def misbehaving(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise UnexpectedModelBehavior("Tool 'json' exceeded max retries count of 1")

    model = FunctionModel(misbehaving)

    def shared_models(_env: Mapping[str, str]) -> tuple[Models, str]:
        return Models(intake=model, analyst=model, ops=model), "shared"

    monkeypatch.setattr(live, "models_from_environment", shared_models)
    limiter = _limiter(runs=1)

    with pytest.raises(UnexpectedModelBehavior):
        run_live_day(sandbox, env={}, limiter=limiter)

    assert limiter.remaining() == 1
    assert sandbox.next_day == NEXT_DAY
