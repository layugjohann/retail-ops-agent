"""Scripted Analyst and Ops models that behave as a good real model should, for eval harness tests.

For a stockout risk the Analyst looks up open Reorders with its read-only tool, blames a demand surge
and recommends a Reorder only when none is open. For a sales spike it reads the SKU's sales history:
if the spike's days sold at well under half the usual price a unit, the quantities cannot be single
units, so it concludes a Data Problem in those days' sales Uploads; otherwise it blames a local price
cut. For any other kind it states that kind's planted cause and recommends an alert. The Ops agent
proposes whatever the Investigation recommends.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

SURGE_CAUSE = "A demand surge: the SKU sold far above its usual rate over the last few days."
CAUSES = {
    "sales_drop": "Footfall fell: every category sold well under its usual rate at this Store only.",
    "sales_spike": "A local price cut: the SKU sold at a discount here only, so it sold far more.",
    "slow_mover": "Demand for the SKU faded: it has all but stopped selling here while stock sits.",
}


def _prompt(messages: list[ModelMessage]) -> str:
    return next(
        part.content
        for m in messages
        if isinstance(m, ModelRequest)
        for part in m.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )


def _data(prompt: str) -> dict[str, Any]:
    """The first JSON object in the prompt: the Anomaly or Investigation passed as data."""
    start = prompt.index("{")
    return json.JSONDecoder().raw_decode(prompt[start:])[0]


def _output(info: AgentInfo, args: dict[str, Any]) -> ModelResponse:
    assert info.output_tools
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])


DATA_PROBLEM_CAUSE = (
    "A Data Problem: the SKU's quantities on these days are in cases, not single units, so it did not "
    "really sell more."
)


def _data_problem_days(history: list[dict[str, Any]], spike_days: int) -> list[str]:
    """The spike's days, if each sold at under half the usual price a unit; otherwise none."""
    earlier = [d["price_per_unit"] for d in history[:-spike_days] if d["price_per_unit"]]
    recent = history[-spike_days:]
    if not earlier or len(recent) < spike_days:
        return []
    usual = statistics.median(earlier)
    if all(d["price_per_unit"] and d["price_per_unit"] < usual / 2 for d in recent):
        return [d["day"] for d in recent]
    return []


def scripted_eval_analyst(*, cause: str = SURGE_CAUSE, always_reorder: bool = False) -> FunctionModel:
    def analyst(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [
            part
            for m in messages
            if isinstance(m, ModelRequest)
            for part in m.parts
            if isinstance(part, ToolReturnPart)
        ]
        anomaly = _data(_prompt(messages))
        if anomaly["kind"] == "sales_spike" and not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "sales_history",
                        {"sales_channel": anomaly["sales_channel"], "sku": anomaly["sku"], "days": 17},
                    )
                ]
            )
        if anomaly["kind"] == "sales_spike":
            days = _data_problem_days(
                json.loads(returns[0].model_response_str()), len(anomaly["daily_units"])
            )
            if days:
                return _output(
                    info,
                    {
                        "cause": DATA_PROBLEM_CAUSE,
                        "evidence": [
                            "Its price a unit fell to a fraction of the usual on exactly these days."
                        ],
                        "data_problem": {
                            "upload_kind": "sales",
                            "days": days,
                            "what_is_wrong": f"The quantities of {anomaly['sku']} are in cases, not units.",
                        },
                    },
                )
        if anomaly["kind"] in CAUSES:
            return _output(
                info,
                {
                    "cause": CAUSES[anomaly["kind"]] if cause == SURGE_CAUSE else cause,
                    "evidence": ["Units a day well away from the usual rate, at this Sales Channel only."],
                    "recommended_action": {
                        "kind": "reorder" if always_reorder else "alert",
                        "description": "Tell whoever handles this what the data shows.",
                    },
                },
            )
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "open_reorders", {"sales_channel": anomaly["sales_channel"], "sku": anomaly["sku"]}
                    )
                ]
            )
        reorder = always_reorder or not returns[0].content
        return _output(
            info,
            {
                "cause": cause,
                "evidence": ["Sales over the last days far above the SKU's usual rate."],
                "recommended_action": {
                    "kind": "reorder" if reorder else "alert",
                    "description": "Reorder to cover the Lead Time."
                    if reorder
                    else "An open Reorder covers it; tell the planner.",
                },
            },
        )

    return FunctionModel(analyst)


def scripted_eval_ops(*, quantity: int = 24, **extra: object) -> FunctionModel:
    """Proposes the Investigation's recommended Action; extra fields are added to its output, so a test
    can have it claim a Tier or an Approval it has no say over."""

    def ops(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        kind = _data(_prompt(messages))["recommended_action"]["kind"]
        args: dict[str, Any] = {"kind": kind, "subject": f"Stockout risk: {kind}", "body": "As investigated."}
        if kind == "reorder":
            args["quantity"] = quantity
        return _output(info, {**args, **extra})

    return FunctionModel(ops)
