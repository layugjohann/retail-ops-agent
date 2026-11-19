"""Runs Golden Scenarios through the Ops Day boundary with real models and writes a Scorecard.

    uv run --env-file .env.local python -m retail_ops_agent.evals --tag quarantine

Evals are not part of the unit test run; they reach real models and are paced for free tiers.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from pydantic_ai.models import Model, infer_model

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.defects import location_in_words
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.evals.action_graders import ActionsObserved, grade_actions, investigations_of
from retail_ops_agent.evals.graders import grade_intake, observe
from retail_ops_agent.evals.judge import (
    ActualDefect,
    InvestigationGrade,
    MessageGrade,
    judge_investigation,
    judge_message,
)
from retail_ops_agent.evals.scenarios import (
    FIRST_SUBMISSION,
    AfterRunStepKind,
    Scenario,
    load_scenarios,
    select_scenarios,
)
from retail_ops_agent.evals.scorecard import ScenarioResult, Scorecard, render_table, summarise
from retail_ops_agent.evals.throttle import Throttle, ThrottledModel
from retail_ops_agent.generator import (
    AnomalyCause,
    GeneratedUploads,
    PlantedAnomaly,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.models import model_name_from_environment
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploader_messages import DEFECT_NAMES

DEFAULT_SCENARIOS = Path("evals/scenarios")
DEFAULT_OUTPUT = Path("evals/results")
# Below the tightest free tier we default to (Gemini Flash-Lite, 15 requests a minute), with room
# for the judge sharing the limit.
DEFAULT_REQUESTS_PER_MINUTE = 10.0
# Who takes a Scenario's after-run Approval decisions, as the Approval Queue records it.
EVAL_APPROVER = "inventory planner (eval)"


def generate_scenario(scenario: Scenario) -> GeneratedUploads:
    """The Scenario's Uploads and ground truth. Deterministic, so it matches what the sandbox submits."""
    return generate_uploads(
        generate_history(
            generate_catalog(scenario.seed),
            scenario.first_day,
            scenario.days,
            scenario.planted.anomalies,
            scenario.planted.lookalikes,
        ),
        scenario.planted.defects,
        scenario.planted.resubmissions,
    )


def run_scenario(
    scenario: Scenario, generated: GeneratedUploads, models: Models, directory: Path
) -> ActionsObserved:
    """Place the Scenario's open Reorders, submit its Uploads and run its Ops Days through the Ops Day
    boundary, then take its after-run steps. Returns the Ops Day with every Reorder in the ERP."""
    erp = InMemoryErp(generate_catalog(scenario.seed))
    # An open Reorder is for the SKU of the stockout risk planted at its Sales Channel.
    planted = {
        a.sales_channel: a.sku
        for a in generated.ground_truth.anomalies
        if a.kind is AnomalyKind.STOCKOUT_RISK and a.sku is not None
    }
    preexisting = frozenset(
        erp.place_reorder(
            sales_channel=open_reorder.sales_channel,
            sku=planted[open_reorder.sales_channel],
            quantity=open_reorder.quantity,
        ).reorder_id
        for open_reorder in scenario.open_reorders
    )
    ops_day = build_sandbox(
        seed=scenario.seed,
        models=models,
        first_day=scenario.first_day,
        days=scenario.days,
        defects=scenario.planted.defects,
        resubmissions=scenario.planted.resubmissions,
        anomalies=scenario.planted.anomalies,
        lookalikes=scenario.planted.lookalikes,
        upload_directory=directory,
        sales_channels=scenario.sales_channels,
        upload_kinds=scenario.upload_kinds,
        auto_approval_limit=scenario.auto_approval_limit,
        run_days=scenario.ops_days,
        erp=erp,
    )
    for step in scenario.after_run:
        if step.step is AfterRunStepKind.ADVANCE_TIME:
            ops_day.advance_time(timedelta(hours=step.hours))
        for item in ops_day.approval_queue():
            if step.step is AfterRunStepKind.APPROVE_PENDING:
                ops_day.approve(item.action_id, approved_by=EVAL_APPROVER)
            elif step.step is AfterRunStepKind.REJECT_PENDING:
                ops_day.reject(item.action_id, rejected_by=EVAL_APPROVER)
    return ActionsObserved(
        ops_day=ops_day, erp_reorders=tuple(erp.list_reorders()), preexisting_reorders=preexisting
    )


_CAUSES: dict[AnomalyCause, str] = {
    AnomalyCause.DEMAND_SURGE: "a demand surge. The SKU sold far beyond its usual rate at the Sales "
    "Channel for a few days, draining its stock faster than a Restock could arrive",
    AnomalyCause.FOOTFALL_DROP: "a footfall drop. Fewer shoppers came to the Sales Channel for a few "
    "days, so every category sold well under its usual rate there while stock stayed on hand and the "
    "other Sales Channels sold as usual",
    AnomalyCause.PRICE_CUT: "a local price cut. The SKU was sold at a 30% discount at this Sales Channel "
    "only for a few days, so its net sales a unit fell and it sold several times its usual rate, while "
    "the other Sales Channels sold it as usual at the full price",
    AnomalyCause.FADING_DEMAND: "fading demand. The SKU, which used to sell steadily at the Sales "
    "Channel, all but stopped selling there while its stock stayed on hand",
}

# The right recommendation for each kind of planted Anomaly other than a stockout risk.
_RECOMMENDATIONS: dict[AnomalyKind, str] = {
    AnomalyKind.SALES_DROP: "an alert to the regional manager to find out what kept shoppers away "
    "at this Sales Channel; no Reorder",
    AnomalyKind.SALES_SPIKE: "an alert to the merchandiser to check the local price cut and keep an eye "
    "on stock; no Reorder",
    AnomalyKind.SLOW_MOVER: "an alert to the inventory planner to stop reordering the SKU at this "
    "Sales Channel and consider a markdown or moving the stock; no Reorder",
}


def actual_cause(planted: PlantedAnomaly, open_reorder: int | None) -> str:
    """The planted cause in words, as the LLM judge is told it."""
    sold = ", ".join(str(u) for u in planted.units_sold)
    what = f"of {planted.sku}" if planted.sku is not None else "of every SKU together"
    words = (
        f"{_CAUSES[planted.cause]}: from {planted.cause_starts_on.isoformat()} it sold {sold} units "
        f"a day {what} at {planted.sales_channel}."
    )
    if planted.kind is not AnomalyKind.STOCKOUT_RISK:
        words += f" The right recommendation is {_RECOMMENDATIONS[planted.kind]}."
    elif open_reorder is not None:
        words += (
            f" A Reorder of {open_reorder} units was already placed in the ERP before the Investigation, "
            "so the right recommendation is an alert, not another Reorder."
        )
    else:
        words += " No Reorder was open, so the right recommendation is a Reorder."
    return words


def judge_investigations(
    scenario: Scenario, generated: GeneratedUploads, observed: ActionsObserved, judge_model: Model
) -> tuple[InvestigationGrade, ...]:
    """Grade every Investigation of a planted Anomaly against the rubric, telling the judge its cause."""
    open_reorders = {r.sales_channel: r.quantity for r in scenario.open_reorders}
    investigations = observed.ops_day.investigations()
    return tuple(
        judge_investigation(
            investigation,
            actual_cause=actual_cause(planted, open_reorders.get(planted.sales_channel)),
            model=judge_model,
        )
        for planted in generated.ground_truth.anomalies
        for investigation in investigations_of(planted, investigations)
    )


def judge_messages(
    generated: GeneratedUploads, ops_day: OpsDay, judge_model: Model
) -> tuple[MessageGrade, ...]:
    """Grade every Uploader message against the rubric, telling the judge the Upload's actual Defects."""
    observed = observe(ops_day)
    uploads = {outcome.upload_id: key for key, outcome in observed.uploads.items()}
    grades: list[MessageGrade] = []
    for message in reversed(ops_day.uploader_messages()):
        channel, day, kind, number = uploads[message.upload_id]
        planted = [
            d
            for d in generated.ground_truth.defects
            if number == FIRST_SUBMISSION and (d.sales_channel, d.day, d.upload_kind) == (channel, day, kind)
        ]
        # Located the way the generator records it; named the way an Uploader would recognise.
        defects = [
            ActualDefect(kind=DEFECT_NAMES[d.defect_kind], location=location_in_words(d.row, d.column))
            for d in planted
        ]
        grades.append(
            judge_message(
                message, sales_channel=channel, day=day, kind=kind, defects=defects, model=judge_model
            )
        )
    return tuple(grades)


def run_evals(
    scenarios: Sequence[Scenario],
    *,
    models: Models,
    judge_model: Model | None,
    model_label: str,
    judge_label: str | None,
    agent_labels: Mapping[str, str] | None = None,
    output: Path,
    now: Callable[[], datetime],
    requests_per_minute: float = 0.0,
    tags: Sequence[str] = (),
    scenario_ids: Sequence[str] = (),
    log: TextIO | None = None,
) -> tuple[Scorecard, Path]:
    """Run each Scenario, grade it and write the Scorecard to the output directory.

    A Scenario that raises (a retired model, a quota running out) is recorded as an error and the
    run moves on to the next one.

    A Scenario passes when every deterministic grader passes. The hard rule (no Tier 2 Action without
    Approval or the Auto-approval Limit) is one of them, and the Scorecard's summary fails the whole
    run if it breaks anywhere.
    """
    started_at = now()
    run_directory = output / f"uploads-{started_at.strftime('%Y%m%dT%H%M%S')}"
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        if log:
            print(f"Running {scenario.id} ...", file=log, flush=True)
        try:
            generated = generate_scenario(scenario)
            observed = run_scenario(scenario, generated, models, run_directory / scenario.id)
            ops_day = observed.ops_day
            graders = (
                *grade_intake(scenario, generated, ops_day),
                *grade_actions(scenario, generated, observed),
            )
            grades = judge_messages(generated, ops_day, judge_model) if judge_model else ()
            investigation_grades = (
                judge_investigations(scenario, generated, observed, judge_model) if judge_model else ()
            )
        except Exception as error:  # Any failure belongs in the Scorecard, not a crashed run.
            results.append(
                ScenarioResult(
                    id=scenario.id, tags=scenario.tags, passed=False, error=f"{type(error).__name__}: {error}"
                )
            )
            continue
        results.append(
            ScenarioResult(
                id=scenario.id,
                tags=scenario.tags,
                passed=all(g.passed for g in graders),
                graders=graders,
                judged=judge_model is not None,
                message_grades=grades,
                investigation_grades=investigation_grades,
            )
        )
    scorecard = Scorecard(
        started_at=started_at,
        finished_at=now(),
        model=model_label,
        judge_model=judge_label,
        agent_models=dict(agent_labels or {}),
        requests_per_minute=requests_per_minute,
        tags=tuple(tags),
        scenario_ids=tuple(scenario_ids),
        summary=summarise(tuple(results)),
        scenarios=tuple(results),
    )
    return scorecard, scorecard.write(output)


AGENTS = ("intake", "analyst", "ops")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m retail_ops_agent.evals",
        description="Run Golden Scenarios through the Ops Day boundary and write a Scorecard.",
    )
    parser.add_argument(
        "--scenarios", type=Path, default=DEFAULT_SCENARIOS, help="directory of Scenario JSON"
    )
    parser.add_argument("--tag", action="append", default=[], help="run Scenarios with this tag (repeatable)")
    parser.add_argument("--scenario", action="append", default=[], help="run this Scenario id (repeatable)")
    parser.add_argument(
        "--model", help="model for every agent, e.g. groq:openai/gpt-oss-120b (default: from keys)"
    )
    for agent in AGENTS:
        parser.add_argument(f"--{agent}-model", help=f"the {agent.title()} agent's model (default: --model)")
    parser.add_argument("--judge-model", help="LLM judge model (default: --model)")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where the Scorecard is written")
    parser.add_argument(
        "--rpm",
        type=float,
        default=DEFAULT_REQUESTS_PER_MINUTE,
        help="model requests per minute, per model (0 for no pacing)",
    )
    parser.add_argument("--list", action="store_true", help="list the selected Scenarios and exit")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    build_model: Callable[[str], Model] = infer_model,
    now: Callable[[], datetime] = datetime.now,
    out: TextIO = sys.stdout,
) -> int:
    """The eval command. Exit status 0 if the run passed (every Scenario passed and no Tier 2 Action
    ran without Approval), 1 if not, 2 on bad options."""
    parser = _parser()
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        scenarios = select_scenarios(load_scenarios(args.scenarios), tags=args.tag, ids=args.scenario)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.list:
        for scenario in scenarios:
            print(f"{scenario.id}  [{', '.join(scenario.tags)}]  {scenario.description}", file=out)
        return 0
    if not scenarios:
        print("error: no Scenario matches the filters", file=sys.stderr)
        return 2
    model_name: str | None = args.model or model_name_from_environment(env)
    if model_name is None:
        print(
            "error: no model key set; pass --model or fill in .env.local (see .env.example)", file=sys.stderr
        )
        return 2
    judge_name: str | None = None if args.no_judge else (args.judge_model or model_name)
    throttles: dict[str, Throttle] = {}

    def throttled(name: str) -> Model:
        # Models with the same name share one rate limit, so they share one Throttle.
        return ThrottledModel(build_model(name), throttles.setdefault(name, Throttle(args.rpm)))

    agent_names: dict[str, str] = {agent: getattr(args, f"{agent}_model") or model_name for agent in AGENTS}
    try:
        agent_models = {agent: throttled(name) for agent, name in agent_names.items()}
        judge_model = throttled(judge_name) if judge_name else None
    except Exception as error:  # A missing key or an unknown provider, reported plainly.
        print(f"error: cannot use model: {error}", file=sys.stderr)
        return 2
    scorecard, path = run_evals(
        scenarios,
        models=Models(**agent_models),
        judge_model=judge_model,
        model_label=model_name,
        judge_label=judge_name,
        agent_labels=agent_names,
        output=args.output,
        now=now,
        requests_per_minute=args.rpm,
        tags=args.tag,
        scenario_ids=args.scenario,
        log=sys.stderr,
    )
    print(render_table(scorecard), file=out)
    print(f"\nScorecard written to {path}", file=out)
    return 0 if scorecard.summary.run_passed else 1
