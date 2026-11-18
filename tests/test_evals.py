"""The eval harness, tested end to end with scripted models: no keys and no network."""

from __future__ import annotations

import asyncio
import io
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from retail_ops_agent.defects import SAFE_FIX_TABLE, DefectKind
from retail_ops_agent.evals.judge import UPLOADER_MESSAGE_RUBRIC
from retail_ops_agent.evals.runner import DEFAULT_SCENARIOS, generate_scenario, main
from retail_ops_agent.evals.scenarios import FIRST_SUBMISSION, Scenario, load_scenarios, select_scenarios
from retail_ops_agent.evals.scorecard import Scorecard
from retail_ops_agent.evals.throttle import Throttle, ThrottledModel
from retail_ops_agent.generator import PLANTABLE_DEFECTS
from retail_ops_agent.uploads import UploadStatus

from .conftest import scripted_intake_model

SCENARIOS = Path(__file__).parent.parent / DEFAULT_SCENARIOS
INTAKE = "scripted-intake"
JUDGE = "scripted-judge"
STARTED = datetime(2026, 11, 19, 9, 30)


def _judge(failing: frozenset[str] = frozenset(), *, omit: frozenset[str] = frozenset()) -> TestModel:
    return TestModel(
        custom_output_args={
            "verdicts": [
                {"criterion": c.id, "passed": c.id not in failing, "reason": f"scripted verdict on {c.id}"}
                for c in UPLOADER_MESSAGE_RUBRIC
                if c.id not in omit
            ]
        }
    )


def _run(
    tmp_path: Path, *args: str, intake: Model | None = None, judge: Model | None = None
) -> tuple[int, str, Scorecard | None]:
    models_by_name: dict[str, Model] = {INTAKE: intake or scripted_intake_model(), JUDGE: judge or _judge()}
    out = io.StringIO()
    output = tmp_path / "results"
    code = main(
        ["--model", INTAKE, "--judge-model", JUDGE, "--rpm", "0", "--output", str(output), *args],
        env={},
        build_model=models_by_name.__getitem__,
        now=lambda: STARTED,
        out=out,
    )
    scorecards = sorted(output.glob("scorecard-*.json"))
    return code, out.getvalue(), Scorecard.read(scorecards[0]) if scorecards else None


# The starter Scenarios


def test_starter_scenarios_cover_every_plantable_defect_kind_and_a_resubmission() -> None:
    scenarios = load_scenarios(SCENARIOS)

    planted = {d.defect_kind for s in scenarios for d in s.planted.defects}
    assert planted == set(PLANTABLE_DEFECTS)
    assert any(s.planted.resubmissions for s in scenarios)
    assert any(not s.planted.defects and not s.planted.resubmissions for s in scenarios)


@pytest.mark.parametrize("scenario", load_scenarios(SCENARIOS), ids=lambda s: s.id)
def test_each_starter_scenarios_expected_outcomes_agree_with_the_generators_ground_truth(
    scenario: Scenario,
) -> None:
    truth = generate_scenario(scenario).ground_truth
    expected = scenario.expected_outcomes()
    resubmitted = {(r.sales_channel, r.day, r.upload_kind): r for r in truth.resubmissions}
    planted: dict[tuple[str, date, str], list[DefectKind]] = {}
    for defect in truth.defects:
        planted.setdefault((defect.sales_channel, defect.day, defect.upload_kind), []).append(
            defect.defect_kind
        )
        slot = (defect.sales_channel, defect.day, defect.upload_kind)
        first = expected[(*slot, FIRST_SUBMISSION)]
        status = UploadStatus.SUPERSEDED if slot in resubmitted else defect.expected_status
        assert first.status is status
    for (channel, day, kind, number), outcome in expected.items():
        assert sorted(outcome.defect_kinds) == sorted(
            planted.get((channel, day, kind), []) if number == FIRST_SUBMISSION else []
        )
        if number > FIRST_SUBMISSION:
            assert outcome.status is resubmitted[(channel, day, kind)].expected_status


# Running the harness end to end


def test_every_starter_scenario_passes_when_intake_reports_only_what_the_checks_find(tmp_path: Path) -> None:
    code, table, scorecard = _run(tmp_path)

    assert code == 0
    assert scorecard is not None
    assert {s.id for s in scorecard.scenarios} == {s.id for s in load_scenarios(SCENARIOS)}
    assert all(s.passed and s.error is None for s in scorecard.scenarios)
    summary = scorecard.summary
    assert (summary.defect_precision, summary.defect_recall) == (1.0, 1.0)
    assert (
        summary.safe_fixes_right
        == summary.safe_fixes_expected
        == sum(SAFE_FIX_TABLE[k] for k in PLANTABLE_DEFECTS)
    )
    assert summary.clean_uploads > 0 and summary.clean_uploads_quarantined == 0
    assert (scorecard.model, scorecard.judge_model) == (INTAKE, JUDGE)
    # One message per Quarantined Upload, each judged once on every criterion.
    quarantining = sum(1 for k in PLANTABLE_DEFECTS if not SAFE_FIX_TABLE[k]) + 1  # and the resubmission
    assert summary.judge_criteria == {c.id: (quarantining, quarantining) for c in UPLOADER_MESSAGE_RUBRIC}
    assert "missing-column-store-sales" in table
    assert "Defect precision: 1.00   recall: 1.00" in table
    assert "Scorecard written to" in table


def test_the_scorecard_is_machine_readable_json(tmp_path: Path) -> None:
    _run(tmp_path, "--scenario", "clean-day", "--no-judge")

    [path] = (tmp_path / "results").glob("scorecard-*.json")
    data = json.loads(path.read_text())
    assert path.name == "scorecard-20261119T093000.json"
    assert data["summary"]["passed"] == 1
    assert [g["grader"] for g in data["scenarios"][0]["graders"]] == [
        "defect_detection",
        "safe_fix",
        "no_clean_quarantine",
        "upload_status",
        "bi_data",
    ]


def test_runs_filter_by_tag_or_scenario(tmp_path: Path) -> None:
    _, _, by_tag = _run(tmp_path / "tag", "--tag", "safe-fix", "--no-judge")
    _, _, by_both = _run(tmp_path / "both", "--tag", "resubmission", "--scenario", "clean-day", "--no-judge")

    assert by_tag is not None and by_both is not None
    assert {s.id for s in by_tag.scenarios} == {
        s.id for s in load_scenarios(SCENARIOS) if "safe-fix" in s.tags
    }
    assert len(by_tag.scenarios) == 4
    assert {s.id for s in by_both.scenarios} == {
        "clean-day",
        "resubmission-corrects-quarantine",
        "resubmission-changes-figures",
    }
    assert by_tag.tags == ("safe-fix",)


def test_skipping_the_judge_grades_no_messages(tmp_path: Path) -> None:
    code, table, scorecard = _run(tmp_path, "--tag", "quarantine", "--no-judge")

    assert code == 0 and scorecard is not None
    assert scorecard.judge_model is None
    assert all(not s.judged and s.message_grades == () for s in scorecard.scenarios)
    assert "Judge: skipped" in table


def test_an_intake_model_that_invents_defects_loses_precision_and_quarantines_clean_uploads(
    tmp_path: Path,
) -> None:
    invented = {"kind": "unknown_sku", "row": 2, "column": "sku", "detail": "made up"}
    code, table, scorecard = _run(
        tmp_path, "--scenario", "clean-day", "--no-judge", intake=scripted_intake_model(defects=[invented])
    )

    assert code == 1 and scorecard is not None
    [result] = scorecard.scenarios
    assert not result.passed
    assert scorecard.summary.defect_precision == 0.0
    assert scorecard.summary.clean_uploads_quarantined == scorecard.summary.clean_uploads == 4
    no_clean = result.grader("no_clean_quarantine")
    assert no_clean is not None and not no_clean.passed
    assert "clean Upload Quarantined" in table


def test_quarantining_an_upload_a_safe_fix_was_due_for_fails_safe_fix_and_bi_data(tmp_path: Path) -> None:
    invented = {"kind": "unknown_sku", "row": 2, "column": "sku", "detail": "made up"}
    _, _, scorecard = _run(
        tmp_path, "--tag", "safe-fix", "--no-judge", intake=scripted_intake_model(defects=[invented])
    )

    assert scorecard is not None
    for result in scorecard.scenarios:
        safe_fix, bi_data = result.grader("safe_fix"), result.grader("bi_data")
        assert safe_fix is not None and (safe_fix.passed, safe_fix.score) == (False, 0.0)
        assert bi_data is not None and not bi_data.passed
    assert scorecard.summary.safe_fixes_right == 0


def test_the_judge_gives_one_verdict_per_criterion_and_a_missing_one_fails(tmp_path: Path) -> None:
    judge = _judge(failing=frozenset({"plain_and_polite"}), omit=frozenset({"asks_to_resend"}))
    code, table, scorecard = _run(tmp_path, "--scenario", "missing-column-store-sales", judge=judge)

    assert scorecard is not None
    [result] = scorecard.scenarios
    [grade] = result.message_grades
    assert [v.criterion for v in grade.verdicts] == [c.id for c in UPLOADER_MESSAGE_RUBRIC]
    failed = {v.criterion: v.reason for v in grade.verdicts if not v.passed}
    assert failed == {
        "plain_and_polite": "scripted verdict on plain_and_polite",
        "asks_to_resend": "the judge gave no verdict",
    }
    assert grade.passed == len(UPLOADER_MESSAGE_RUBRIC) - 2
    # The judge is reported beside the deterministic graders, which still pass.
    assert result.passed and code == 0
    assert "judge" in table and "asks_to_resend: the judge gave no verdict" in table


def test_the_judge_sees_the_message_as_data_beside_the_actual_defects(tmp_path: Path) -> None:
    prompts: list[str] = []

    def judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts.extend(
            part.content
            for m in messages
            for part in m.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        verdicts = [{"criterion": c.id, "passed": True, "reason": "ok"} for c in UPLOADER_MESSAGE_RUBRIC]
        assert info.output_tools
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"verdicts": verdicts})])

    _run(tmp_path, "--scenario", "unknown-sku-online-shop-inventory", judge=FunctionModel(judge))

    [prompt] = prompts
    assert "Unknown SKU at row" in prompt and "column SKU Code" in prompt
    assert "<<<MESSAGE" in prompt and "MESSAGE>>>" in prompt
    assert "is in Quarantine" in prompt


def test_a_scenario_that_raises_is_recorded_as_an_error_and_the_run_goes_on(tmp_path: Path) -> None:
    def retired(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(404, "retired-model", {"error": "model_not_found"})

    code, table, scorecard = _run(
        tmp_path, "--tag", "resubmission", "--no-judge", intake=FunctionModel(retired)
    )

    assert code == 1 and scorecard is not None
    assert len(scorecard.scenarios) == 2
    assert all(s.error and "404" in s.error and not s.passed for s in scorecard.scenarios)
    assert scorecard.summary.errors == 2
    assert "ERROR" in table


def test_bad_options_are_refused_before_any_model_is_called(tmp_path: Path) -> None:
    assert _run(tmp_path, "--scenario", "no-such-scenario")[0] == 2
    assert _run(tmp_path, "--tag", "no-such-tag")[0] == 2
    no_key = main(["--output", str(tmp_path)], env={}, out=io.StringIO())
    assert no_key == 2
    assert not (tmp_path / "results").exists()


def test_listing_shows_the_selected_scenarios(tmp_path: Path) -> None:
    out = io.StringIO()

    assert main(["--list", "--tag", "resubmission"], env={}, out=out) == 0
    assert out.getvalue().splitlines()[0].startswith("resubmission-changes-figures  [intake, resubmission")


def test_scenario_ids_are_unique_and_selecting_an_unknown_one_is_refused() -> None:
    scenarios = load_scenarios(SCENARIOS)

    assert len({s.id for s in scenarios}) == len(scenarios)
    with pytest.raises(ValueError, match="no Scenario with id nope"):
        select_scenarios(scenarios, ids=["nope"])


def test_a_scenario_cannot_plant_in_an_upload_it_does_not_send() -> None:
    with pytest.raises(ValueError, match="not an Upload this Scenario sends"):
        Scenario.model_validate(
            {
                "id": "bad",
                "description": "",
                "tags": [],
                "seed": 1,
                "first_day": "2026-03-02",
                "last_day": "2026-03-02",
                "sales_channels": ["ST01"],
                "planted": {
                    "defects": [
                        {
                            "sales_channel": "ST02",
                            "day": "2026-03-02",
                            "upload_kind": "sales",
                            "defect_kind": "unknown_sku",
                        }
                    ]
                },
            }
        )


# Throttling


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_the_throttle_spaces_requests_evenly_within_the_rate_limit() -> None:
    time = _FakeTime()
    throttle = Throttle(30, monotonic=time.monotonic, sleep=time.sleep)

    async def three_requests() -> None:
        await throttle.wait()
        await throttle.wait()
        time.now += 5
        await throttle.wait()

    asyncio.run(three_requests())

    assert time.slept == [2.0]  # 30 a minute is one every 2 seconds; the third came late enough.


def test_a_throttled_model_paces_every_request_and_waits_out_rate_limits() -> None:
    time = _FakeTime()
    calls: list[float] = []

    def flaky(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(time.now)
        if len(calls) == 1:
            raise ModelHTTPError(429, "free-tier", {"error": "rate_limit_exceeded"}, retry_after=7.0)
        if len(calls) == 2:
            raise ModelHTTPError(429, "free-tier", {"error": "rate_limit_exceeded"})
        return ModelResponse(parts=[TextPart("ok")])

    model = ThrottledModel(
        FunctionModel(flaky), Throttle(60, monotonic=time.monotonic, sleep=time.sleep), backoff_seconds=3.0
    )
    with models.override_allow_model_requests(True):
        output = Agent(model).run_sync("hello").output

    assert output == "ok"
    # Waited the 7 seconds the provider asked for, then backed off 3 x 2 on the second refusal
    # (it said nothing); the 1-second pacing never had to wait on top.
    assert calls == [0.0, 7.0, 13.0]
    assert time.slept == [7.0, 6.0]


def test_a_throttled_model_gives_up_after_its_retries_and_never_retries_other_failures() -> None:
    time = _FakeTime()
    statuses = iter([429, 429, 500])

    def failing(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(next(statuses), "free-tier")

    model = ThrottledModel(
        FunctionModel(failing), Throttle(0, monotonic=time.monotonic, sleep=time.sleep), max_retries=1
    )
    with pytest.raises(ModelHTTPError) as raised:
        Agent(model).run_sync("hello")
    assert raised.value.status_code == 429

    with pytest.raises(ModelHTTPError) as raised:
        Agent(model).run_sync("hello")
    assert raised.value.status_code == 500
