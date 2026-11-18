"""Runs Golden Scenarios through the Ops Day boundary with real models and writes a Scorecard.

    uv run --env-file .env.local python -m retail_ops_agent.evals --tag quarantine

Evals are not part of the unit test run; they reach real models and are paced for free tiers.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from pydantic_ai.models import Model, infer_model

from retail_ops_agent.defects import location_in_words
from retail_ops_agent.evals.graders import grade_intake, observe
from retail_ops_agent.evals.judge import ActualDefect, MessageGrade, judge_message
from retail_ops_agent.evals.scenarios import FIRST_SUBMISSION, Scenario, load_scenarios, select_scenarios
from retail_ops_agent.evals.scorecard import ScenarioResult, Scorecard, render_table, summarise
from retail_ops_agent.evals.throttle import Throttle, ThrottledModel
from retail_ops_agent.generator import GeneratedUploads, generate_catalog, generate_history, generate_uploads
from retail_ops_agent.models import model_name_from_environment
from retail_ops_agent.ops_day import Models, OpsDay
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploader_messages import DEFECT_NAMES

DEFAULT_SCENARIOS = Path("evals/scenarios")
DEFAULT_OUTPUT = Path("evals/results")
# Below the tightest free tier we default to (Gemini Flash-Lite, 15 requests a minute), with room
# for the judge sharing the limit.
DEFAULT_REQUESTS_PER_MINUTE = 10.0


def generate_scenario(scenario: Scenario) -> GeneratedUploads:
    """The Scenario's Uploads and ground truth. Deterministic, so it matches what the sandbox submits."""
    return generate_uploads(
        generate_history(generate_catalog(scenario.seed), scenario.first_day, scenario.days),
        scenario.planted.defects,
        scenario.planted.resubmissions,
    )


def run_scenario(
    scenario: Scenario, generated: GeneratedUploads, intake_model: Model, directory: Path
) -> OpsDay:
    """Submit the Scenario's Uploads and run its Ops Days through the Ops Day boundary."""
    return build_sandbox(
        seed=scenario.seed,
        models=Models(intake=intake_model),
        first_day=scenario.first_day,
        days=scenario.days,
        defects=scenario.planted.defects,
        resubmissions=scenario.planted.resubmissions,
        upload_directory=directory,
        sales_channels=scenario.sales_channels,
        upload_kinds=scenario.upload_kinds,
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
    intake_model: Model,
    judge_model: Model | None,
    model_label: str,
    judge_label: str | None,
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
    """
    started_at = now()
    run_directory = output / f"uploads-{started_at.strftime('%Y%m%dT%H%M%S')}"
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        if log:
            print(f"Running {scenario.id} ...", file=log, flush=True)
        try:
            generated = generate_scenario(scenario)
            ops_day = run_scenario(scenario, generated, intake_model, run_directory / scenario.id)
            graders = tuple(grade_intake(scenario, generated, ops_day))
            grades = judge_messages(generated, ops_day, judge_model) if judge_model else ()
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
            )
        )
    scorecard = Scorecard(
        started_at=started_at,
        finished_at=now(),
        model=model_label,
        judge_model=judge_label,
        requests_per_minute=requests_per_minute,
        tags=tuple(tags),
        scenario_ids=tuple(scenario_ids),
        summary=summarise(tuple(results)),
        scenarios=tuple(results),
    )
    return scorecard, scorecard.write(output)


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
    parser.add_argument("--model", help="Intake model, e.g. groq:openai/gpt-oss-120b (default: from keys)")
    parser.add_argument("--judge-model", help="LLM judge model (default: the Intake model)")
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
    """The eval command. Exit status 0 if every Scenario passed, 1 if any failed, 2 on bad options."""
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

    try:
        intake_model = throttled(model_name)
        judge_model = throttled(judge_name) if judge_name else None
    except Exception as error:  # A missing key or an unknown provider, reported plainly.
        print(f"error: cannot use model: {error}", file=sys.stderr)
        return 2
    scorecard, path = run_evals(
        scenarios,
        intake_model=intake_model,
        judge_model=judge_model,
        model_label=model_name,
        judge_label=judge_name,
        output=args.output,
        now=now,
        requests_per_minute=args.rpm,
        tags=args.tag,
        scenario_ids=args.scenario,
        log=sys.stderr,
    )
    print(render_table(scorecard), file=out)
    print(f"\nScorecard written to {path}", file=out)
    return 0 if scorecard.summary.passed == scorecard.summary.scenarios else 1
