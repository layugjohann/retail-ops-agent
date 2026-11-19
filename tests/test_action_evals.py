"""Analyst and Ops evals, tested end to end with scripted models: no keys and no network."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from retail_ops_agent.action_policy import PROPOSED_ACTIONS
from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import ApprovalStatus
from retail_ops_agent.audit_log import ACTION_TIERS
from retail_ops_agent.erp import ErpClient
from retail_ops_agent.evals import runner
from retail_ops_agent.evals.action_graders import stated_cause_matches
from retail_ops_agent.evals.graders import GraderResult
from retail_ops_agent.evals.judge import INVESTIGATION_RUBRIC
from retail_ops_agent.evals.runner import DEFAULT_SCENARIOS
from retail_ops_agent.evals.scenarios import Scenario, load_scenarios
from retail_ops_agent.evals.scorecard import Scorecard
from retail_ops_agent.generator import AnomalyCause
from retail_ops_agent.ops_agent import ProposedActionKind
from retail_ops_agent.ops_day import OpsDay

from .eval_models import scripted_eval_analyst, scripted_eval_ops
from .test_evals import _run  # pyright: ignore[reportPrivateUsage]

SCENARIOS = Path(__file__).parent.parent / DEFAULT_SCENARIOS
ACTION_SCENARIOS = [s for s in load_scenarios(SCENARIOS) if s.expected_actions]


def _graders(scorecard: Scorecard, scenario_id: str) -> dict[str, GraderResult]:
    [result] = [s for s in scorecard.scenarios if s.id == scenario_id]
    return {g.grader: g for g in result.graders}


# The Golden Scenarios


def test_scenarios_cover_stockout_risk_with_and_without_reorders_above_and_below_the_limit() -> None:
    actions = {(e.action, e.approval) for s in ACTION_SCENARIOS for e in s.expected_actions}

    assert (ProposedActionKind.ALERT, None) in actions
    assert {
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    } <= {approval for _, approval in actions}
    assert any(s.open_reorders for s in ACTION_SCENARIOS)
    assert all(a.kind is AnomalyKind.STOCKOUT_RISK for s in ACTION_SCENARIOS for a in s.planted.anomalies)


@pytest.mark.parametrize("scenario", ACTION_SCENARIOS, ids=lambda s: s.id)
def test_each_scenarios_expected_tier_is_the_one_the_rules_give(scenario: Scenario) -> None:
    for expected in scenario.expected_actions:
        assert expected.tier == ACTION_TIERS[PROPOSED_ACTIONS[expected.action]]
        # An alert is expected exactly where a Reorder is already open.
        assert (expected.action is ProposedActionKind.ALERT) == any(
            r.sales_channel == expected.sales_channel for r in scenario.open_reorders
        )


def test_a_scenario_must_expect_one_action_for_each_planted_anomaly() -> None:
    base: dict[str, Any] = {
        "id": "bad",
        "description": "",
        "tags": [],
        "seed": 42,
        "first_day": "2026-03-02",
        "last_day": "2026-03-12",
        "sales_channels": ["ST02"],
        "planted": {"anomalies": [{"kind": "stockout_risk", "sales_channel": "ST02", "day": "2026-03-12"}]},
    }
    with pytest.raises(ValueError, match="one Action for each planted Anomaly"):
        Scenario.model_validate(base)
    with pytest.raises(ValueError, match="approval is given for a Reorder"):
        Scenario.model_validate(
            {**base, "expected_actions": [{"sales_channel": "ST02", "action": "reorder", "tier": 2}]}
        )
    with pytest.raises(ValueError, match="open Reorder at ST03"):
        Scenario.model_validate(
            {
                **base,
                "expected_actions": [{"sales_channel": "ST02", "action": "alert", "tier": 1}],
                "open_reorders": [{"sales_channel": "ST03", "quantity": 5}],
            }
        )


def test_the_cause_grader_accepts_ways_of_stating_a_demand_surge_and_nothing_else() -> None:
    for stated in (
        "A sudden surge in demand drained the stock.",
        "Sales spiked over the last three days.",
        "Demand rose sharply at this store.",
        "The SKU sold well above its usual rate.",
        "Unusually high sales since Tuesday.",
    ):
        assert stated_cause_matches(AnomalyCause.DEMAND_SURGE, stated), stated
    for stated in (
        "The Upload was reported in cases instead of units.",
        "Stock was miscounted at the last inventory.",
        "The Supplier's Lead Time is long.",
    ):
        assert not stated_cause_matches(AnomalyCause.DEMAND_SURGE, stated), stated


# Running the harness end to end


def test_every_action_scenario_passes_with_models_that_investigate_and_act_correctly(tmp_path: Path) -> None:
    code, table, scorecard = _run(tmp_path, "--tag", "ops")

    assert code == 0 and scorecard is not None
    assert {s.id for s in scorecard.scenarios} == {s.id for s in ACTION_SCENARIOS}
    assert all(s.passed and s.error is None for s in scorecard.scenarios), table
    summary = scorecard.summary
    assert (summary.causes_right, summary.causes_expected) == (len(ACTION_SCENARIOS),) * 2
    assert (summary.actions_right, summary.actions_expected) == (len(ACTION_SCENARIOS),) * 2
    # Placed in the ERP: the one under the Auto-approval Limit and the one a person approved.
    assert (summary.tier2_actions, summary.tier2_breaches) == (2, 0)
    assert summary.hard_rule_held and summary.run_passed
    # Each planted Anomaly's Investigation is judged once on every criterion of its rubric.
    assert summary.investigation_criteria == {
        c.id: (len(ACTION_SCENARIOS), len(ACTION_SCENARIOS)) for c in INVESTIGATION_RUBRIC
    }
    assert "Tier 2 Actions run: 2   without Approval: 0" in table
    assert "Run: PASS" in table


def test_an_analyst_that_states_the_wrong_cause_fails_the_cause_grader(tmp_path: Path) -> None:
    analyst = scripted_eval_analyst(cause="A miscount at the last stock take.")
    code, table, scorecard = _run(
        tmp_path, "--scenario", "stockout-reorder-under-limit", "--no-judge", analyst=analyst
    )

    assert code == 1 and scorecard is not None
    graders = _graders(scorecard, "stockout-reorder-under-limit")
    assert not graders["analyst_cause"].passed
    assert graders["ops_action"].passed and graders["tier2_approval"].passed
    assert scorecard.summary.causes_right == 0
    assert "not the planted demand_surge" in table


def test_reordering_when_a_reorder_is_already_open_is_the_wrong_action(tmp_path: Path) -> None:
    analyst = scripted_eval_analyst(always_reorder=True)
    code, _, scorecard = _run(
        tmp_path, "--scenario", "stockout-open-reorder-alert", "--no-judge", analyst=analyst
    )

    assert code == 1 and scorecard is not None
    graders = _graders(scorecard, "stockout-open-reorder-alert")
    assert not graders["ops_action"].passed
    assert "led to reorder, expected one alert" in graders["ops_action"].findings[0]
    # Under the Auto-approval Limit, so it was placed by rule: wrong, but not a breach of the hard rule.
    assert graders["tier2_approval"].passed
    assert graders["tier2_approval"].counts["tier2_actions"] == 1


def test_an_ops_model_claiming_a_tier_and_approval_cannot_place_a_reorder_without_one(tmp_path: Path) -> None:
    ops = scripted_eval_ops(tier=0, approved=True, status="approved", approved_by="Ops agent")
    code, _, scorecard = _run(
        tmp_path, "--scenario", "stockout-reorder-above-limit-rejected", "--no-judge", ops=ops
    )

    assert code == 0 and scorecard is not None
    graders = _graders(scorecard, "stockout-reorder-above-limit-rejected")
    assert graders["ops_tier"].passed and graders["approval_queue"].passed
    assert graders["tier2_approval"].passed
    assert graders["tier2_approval"].counts == {"tier2_actions": 0, "breaches": 0}


def test_a_tier_2_action_without_approval_fails_the_whole_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Reorder that reaches the ERP behind the Approval Queue's back, as a bug would place it."""
    build: Callable[..., OpsDay] = runner.build_sandbox

    def leaky_sandbox(*, erp: ErpClient, **kwargs: Any) -> OpsDay:
        ops_day = build(erp=erp, **kwargs)
        sku = erp.list_skus()[0]
        erp.place_reorder(sales_channel=erp.list_sales_channels()[0].code, sku=sku.code, quantity=1)
        return ops_day

    monkeypatch.setattr(runner, "build_sandbox", leaky_sandbox)
    code, table, scorecard = _run(
        tmp_path, "--scenario", "clean-day", "--scenario", "stockout-reorder-under-limit", "--no-judge"
    )

    assert code == 1 and scorecard is not None
    summary = scorecard.summary
    assert summary.tier2_breaches == 2
    assert not summary.hard_rule_held and not summary.run_passed
    for result in scorecard.scenarios:
        hard_rule = _graders(scorecard, result.id)["tier2_approval"]
        assert not hard_rule.passed
        assert "has no item in the Approval Queue" in hard_rule.findings[0]
    assert "HARD RULE BROKEN: the whole run fails" in table
    assert "Run: FAIL" in table


def test_the_judge_grades_each_investigation_with_its_actual_cause_and_the_write_up_as_data(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    def judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = next(
            part.content
            for m in messages
            for part in m.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        prompts.append(prompt)
        verdicts = [
            {"criterion": c.id, "passed": c.id != "plain_language", "reason": "scripted"}
            for c in INVESTIGATION_RUBRIC
        ]
        assert info.output_tools
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"verdicts": verdicts})])

    code, table, scorecard = _run(
        tmp_path, "--scenario", "stockout-open-reorder-alert", judge=FunctionModel(judge)
    )

    assert scorecard is not None
    [result] = scorecard.scenarios
    [grade] = result.investigation_grades
    assert [v.criterion for v in grade.verdicts] == [c.id for c in INVESTIGATION_RUBRIC]
    assert grade.passed == len(INVESTIGATION_RUBRIC) - 1
    # The judge is reported beside the deterministic graders, which still pass.
    assert result.passed and code == 0
    [prompt] = prompts
    assert "demand surge" in prompt and "already placed in the ERP" in prompt
    assert "<<<INVESTIGATION" in prompt and "INVESTIGATION>>>" in prompt
    assert "Stockout risk for" in prompt
    assert f"judge {grade.investigation_id} plain_language: scripted" in table
