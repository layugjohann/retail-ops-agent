from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic_ai.models.test import TestModel

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.data_source import InMemoryDataSource
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.evals.throttle import ThrottledModel
from retail_ops_agent.generator import AnomalyPlan, DefectPlan
from retail_ops_agent.models import DEFAULT_GEMINI_MODEL, paced_models_from_environment
from retail_ops_agent.notifier import Notifier
from retail_ops_agent.sandbox import Sandbox
from retail_ops_agent.trigger import OpsDayTrigger, make_server
from retail_ops_agent.uploads import UploadKind

from .conftest import SEED, scripted_models

FIRST_DAY = date(2026, 3, 2)
DAYS = 12
SUBMITTED = ("ST02", "ST03")
N8N = Path(__file__).resolve().parent.parent / "n8n"
WORKFLOW = N8N / "workflows" / "ops-day.json"


def _sandbox(notifier: Notifier) -> Sandbox:
    return Sandbox(
        seed=SEED,
        models=scripted_models(),
        first_day=FIRST_DAY,
        days=DAYS,
        data_source=InMemoryDataSource(),
        sales_channels=SUBMITTED,
        defects=[
            DefectPlan(
                sales_channel="ST03",
                day=FIRST_DAY,
                upload_kind=UploadKind.SALES,
                defect_kind=DefectKind.MISSING_COLUMN,
            )
        ],
        anomalies=[AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 3, 12))],
        notifier=notifier,
    )


class Server:
    def __init__(self, trigger: OpsDayTrigger) -> None:
        self.trigger = trigger
        self._server = make_server(trigger, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def request(self, method: str, path: str, body: object = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def server() -> Iterator[Server]:
    running = Server(OpsDayTrigger(_sandbox))
    yield running
    running.close()


def test_each_call_runs_the_next_ops_day_and_returns_its_notifications_to_forward(server: Server) -> None:
    status, health = server.request("GET", "/health")
    assert status == 200
    assert health["next_day"] == FIRST_DAY.isoformat()
    assert health["days_left"] == DAYS

    results: list[dict[str, Any]] = []
    for _ in range(DAYS):
        status, result = server.request("POST", "/ops-day/run")
        assert status == 200
        results.append(result)

    assert [r["day"] for r in results] == [date(2026, 3, 2 + i).isoformat() for i in range(DAYS)]
    assert results[-1]["days_left"] == 0
    assert all(r["summary"].startswith(f"Ops Day {r['day']}") for r in results)

    first_day = results[0]["notifications"]
    [message] = [n for n in first_day if n["kind"] == "uploader_message"]
    assert message["recipient"] == "manager.st03@cobalthome.example"
    assert "quarantined" in results[0]["summary"]

    alerts = [n for r in results for n in r["notifications"] if n["kind"] == "alert"]
    assert alerts, "the planted stockout risk should be alerted"
    for notification in [message, *alerts]:
        assert notification["subject"] in notification["text"]
        assert notification["body"] in notification["text"]
        assert notification["recipient"] in notification["text"]


def test_once_every_day_has_run_the_trigger_says_so_and_runs_nothing(server: Server) -> None:
    for _ in range(DAYS):
        server.request("POST", "/ops-day/run")

    status, body = server.request("POST", "/ops-day/run")

    assert status == 409
    assert "every generated day has already run" in body["error"]


def test_notifications_n8n_forwards_to_the_local_inbox_are_kept(server: Server) -> None:
    status, _ = server.request("POST", "/inbox", {"text": "[Alert] Stockout risk"})
    assert status == 200

    status, inbox = server.request("GET", "/inbox")

    assert status == 200
    assert inbox["messages"] == [{"text": "[Alert] Stockout risk"}]


def test_an_unknown_endpoint_is_not_found(server: Server) -> None:
    assert server.request("POST", "/ops-day/approve")[0] == 404


# The exported workflow


def test_a_free_tier_model_is_paced_below_its_per_minute_limit() -> None:
    """Gemini's free tier allows 15 requests a minute; an Ops Day makes more than that in a burst."""
    models, label = paced_models_from_environment(
        {"GEMINI_API_KEY": "key"}, requests_per_minute=10, build_model=lambda _: TestModel()
    )

    assert label == DEFAULT_GEMINI_MODEL
    for model in (models.intake, models.analyst, models.ops):
        assert isinstance(model, ThrottledModel)
        assert model.throttle.interval == 6.0
    # One Throttle for all three agents, since they count against the same limit.
    assert models.intake is models.analyst is models.ops


def test_without_a_key_the_offline_scripted_model_runs_unpaced() -> None:
    models, label = paced_models_from_environment({}, 10)

    assert label.startswith("offline scripted model")
    assert not isinstance(models.intake, ThrottledModel)


def _workflow() -> dict[str, Any]:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_runs_an_ops_day_on_a_schedule_and_forwards_every_notification() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    def next_of(name: str) -> list[str]:
        return [link["node"] for branch in workflow["connections"][name]["main"] for link in branch]

    [schedule] = [n for n in nodes.values() if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    [run] = next_of(schedule["name"])
    assert nodes[run]["type"] == "n8n-nodes-base.httpRequest"
    assert nodes[run]["parameters"]["method"] == "POST"
    assert nodes[run]["parameters"]["url"].endswith("/ops-day/run")
    [split] = next_of(run)
    assert nodes[split]["parameters"]["fieldToSplitOut"] == "notifications"
    [forward] = next_of(split)
    assert nodes[forward]["type"] == "n8n-nodes-base.httpRequest"
    assert "$json.text" in nodes[forward]["parameters"]["jsonBody"]


def test_the_workflow_holds_no_business_rules() -> None:
    """Only triggers, HTTP calls and a split: no code, branching or filtering nodes, and its only
    expressions read URLs from the environment and pass the notification text through."""
    workflow = _workflow()
    allowed = {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.manualTrigger",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.splitOut",
    }
    assert {node["type"] for node in workflow["nodes"]} <= allowed

    expressions = [
        value for node in workflow["nodes"] for value in _strings(node["parameters"]) if value.startswith("=")
    ]
    assert sorted(expressions) == sorted(
        [
            "={{ $env.OPS_DAY_URL }}/ops-day/run",
            "={{ $env.NOTIFY_WEBHOOK_URL }}",
            "={{ JSON.stringify({ text: $json.text }) }}",
        ]
    )


def test_the_compose_file_gives_n8n_the_urls_and_the_workflow() -> None:
    compose = (N8N / "docker-compose.yml").read_text(encoding="utf-8")
    for needed in (
        "OPS_DAY_URL",
        "NOTIFY_WEBHOOK_URL",
        'N8N_BLOCK_ENV_ACCESS_IN_NODE: "false"',
        "./workflows",
    ):
        assert needed in compose


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _strings(item)
