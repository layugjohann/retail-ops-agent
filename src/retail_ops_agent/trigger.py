"""The entry point n8n calls: a local HTTP server that runs the next Ops Day of a seeded sandbox.

n8n is only a trigger (spec, "Orchestration"). Every decision stays behind the Ops Day boundary;
this server runs the next day and hands back what the Notifier sent during it, each notification
already formatted, so the n8n workflow only forwards them and holds no business rules.

    uv run retail-ops-trigger              # http://127.0.0.1:8765
    uv run retail-ops-trigger --host 0.0.0.0 --port 8765

Endpoints:

    GET  /health        the next day to run and how many are left
    POST /ops-day/run   run the next Ops Day; returns its summary and notifications to forward
    POST /inbox         a local stand-in for Slack or Teams: prints what n8n forwards to it
    GET  /inbox         everything forwarded to /inbox so far

The sandbox (BI store, fake ERP, clock and Uploads) lives in this process's memory, so each run
continues where the last one stopped. Models come from the environment as everywhere else: a
free-tier key if set, else the offline scripted model. A real model's requests are paced (--rpm)
and retried when rate-limited, as for Recordings, so one Ops Day stays inside the free tier's
per-minute limit; it takes a few minutes, well inside the workflow's 15-minute timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import date, datetime
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai.exceptions import AgentRunError

from retail_ops_agent.live import new_live_sandbox
from retail_ops_agent.models import DEFAULT_REQUESTS_PER_MINUTE, paced_models_from_environment
from retail_ops_agent.notifier import LogNotifier, Notification, Notifier
from retail_ops_agent.ops_day import Models
from retail_ops_agent.sandbox import Sandbox
from retail_ops_agent.uploads import UploadStatus
from retail_ops_agent.views import OpsDayOutcome

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Days generated for the trigger's sandbox, so a schedule has plenty of Ops Days to run.
DEFAULT_DAYS = 90
# Days run with the offline scripted model before the first trigger, as history for Anomaly
# detection. Few, so the Defects and the stockout risk planted in Live Mode's sandbox fall in days
# n8n triggers, and there are Uploader messages and alerts to forward.
DEFAULT_SEEDED_DAYS = 2


class NotificationKind(StrEnum):
    UPLOADER_MESSAGE = "uploader_message"
    ALERT = "alert"


class ForwardedNotification(BaseModel):
    """One thing the Notifier sent during the Ops Day, ready for n8n to forward as it is."""

    model_config = ConfigDict(frozen=True)

    kind: NotificationKind
    sent_at: datetime
    recipient: str
    subject: str
    body: str
    # The whole notification as one plain-text message, for a chat webhook's "text" field.
    text: str


class TriggerResult(BaseModel):
    """What one triggered Ops Day did, in short, and what to forward."""

    model_config = ConfigDict(frozen=True)

    day: date
    model: str
    summary: str
    days_left: int
    notifications: list[ForwardedNotification]


class NoDaysLeft(Exception):
    """Every generated day of the sandbox has run."""


class OpsDayTrigger:
    """Runs a sandbox's next Ops Day on request and returns the notifications it sent.

    sandbox_factory builds the sandbox around the Notifier it is given. models, if given, run every
    triggered Ops Day; otherwise the sandbox's own models do.
    """

    def __init__(
        self,
        sandbox_factory: Callable[[Notifier], Sandbox],
        *,
        models: Models | None = None,
        model_label: str = "the sandbox's own models",
    ) -> None:
        self._notifier = LogNotifier()
        self._sandbox = sandbox_factory(self._notifier)
        self._models = models
        self._model_label = model_label
        self._lock = threading.Lock()
        self.inbox: list[dict[str, Any]] = []

    @property
    def next_day(self) -> date | None:
        return self._sandbox.next_day

    @property
    def days_left(self) -> int:
        return len(self._sandbox.days) - len(self._sandbox.days_run)

    def run_next_day(self) -> TriggerResult:
        with self._lock:
            if self._sandbox.next_day is None:
                raise NoDaysLeft("every generated day has already run; restart the trigger to start again")
            already_sent = len(self._notifier.sent)
            outcome = self._sandbox.run_day(self._models)
            sent = self._notifier.sent[already_sent:]
            return TriggerResult(
                day=outcome.day,
                model=self._model_label,
                summary=summarise(outcome),
                days_left=self.days_left,
                notifications=_forwarded(outcome, sent),
            )

    def receive(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.inbox.append(message)


def summarise(outcome: OpsDayOutcome) -> str:
    """One plain-language line about an Ops Day."""
    counts = {status: 0 for status in UploadStatus}
    for upload in outcome.uploads:
        counts[upload.status] += 1
    upload_parts = ", ".join(f"{n} {status.value.replace('_', '-')}" for status, n in counts.items() if n)
    return (
        f"Ops Day {outcome.day.isoformat()}: {len(outcome.uploads)} Uploads"
        + (f" ({upload_parts})" if upload_parts else "")
        + f", {len(outcome.anomalies)} Anomalies, {len(outcome.investigations)} Investigations,"
        f" {len(outcome.reorders)} Reorders proposed, {len(outcome.approval_queue)} waiting for Approval,"
        f" {len(outcome.uploader_messages)} Uploader messages."
    )


def _forwarded(outcome: OpsDayOutcome, sent: Sequence[Notification]) -> list[ForwardedNotification]:
    to_uploaders = {(m.sent_at, m.recipient, m.subject, m.body) for m in outcome.uploader_messages}
    forwarded: list[ForwardedNotification] = []
    for n in sent:
        kind = (
            NotificationKind.UPLOADER_MESSAGE
            if (n.sent_at, n.recipient, n.subject, n.body) in to_uploaders
            else NotificationKind.ALERT
        )
        label = "Message to Uploader" if kind is NotificationKind.UPLOADER_MESSAGE else "Alert"
        forwarded.append(
            ForwardedNotification(
                kind=kind,
                sent_at=n.sent_at,
                recipient=n.recipient,
                subject=n.subject,
                body=n.body,
                text=f"[{label}] {n.subject}\nTo: {n.recipient}\n\n{n.body}",
            )
        )
    return forwarded


# HTTP


def make_server(trigger: OpsDayTrigger, host: str, port: int) -> ThreadingHTTPServer:
    """An HTTP server for the trigger. Port 0 picks a free port."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                next_day = trigger.next_day
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "next_day": next_day.isoformat() if next_day else None,
                        "days_left": trigger.days_left,
                    },
                )
            elif self.path == "/inbox":
                self._json(HTTPStatus.OK, {"messages": trigger.inbox})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": f"no such endpoint: GET {self.path}"})

        def do_POST(self) -> None:
            if self.path == "/ops-day/run":
                self._run()
            elif self.path == "/inbox":
                self._receive()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": f"no such endpoint: POST {self.path}"})

        def _run(self) -> None:
            try:
                result = trigger.run_next_day()
            except NoDaysLeft as done:
                self._json(HTTPStatus.CONFLICT, {"error": str(done)})
                return
            except AgentRunError as failed:
                # A model outage or rate limit: the day stays next and is retried on the next trigger.
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"the Ops Day failed: {failed}"})
                return
            print(result.summary, file=sys.stderr, flush=True)
            self._json(HTTPStatus.OK, result.model_dump(mode="json"))

        def _receive(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                message = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "the body is not JSON"})
                return
            if not isinstance(message, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "the body is not a JSON object"})
                return
            trigger.receive(message)  # pyright: ignore[reportUnknownArgumentType]
            print(f"--- forwarded by n8n ---\n{message.get('text', message)}\n", file=sys.stderr, flush=True)  # pyright: ignore[reportUnknownMemberType]
            self._json(HTTPStatus.OK, {"received": True})

        def _json(self, status: HTTPStatus, body: object) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} {format % args}", file=sys.stderr, flush=True)

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the Ops Day trigger n8n calls.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="use 0.0.0.0 on Linux so Docker can reach it")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="days to generate for the sandbox")
    parser.add_argument(
        "--seeded-days", type=int, default=DEFAULT_SEEDED_DAYS, help="days to run before the first trigger"
    )
    parser.add_argument(
        "--rpm",
        type=float,
        default=DEFAULT_REQUESTS_PER_MINUTE,
        help="model requests per minute, below the free tier's limit (0: no pacing)",
    )
    args = parser.parse_args(argv)
    models, label = paced_models_from_environment(os.environ, args.rpm)
    print("Seeding the Cobalt Home sandbox...", file=sys.stderr, flush=True)
    trigger = OpsDayTrigger(
        lambda notifier: new_live_sandbox(notifier=notifier, days=args.days, seeded_days=args.seeded_days),
        models=models,
        model_label=label,
    )
    server = make_server(trigger, args.host, args.port)
    print(
        f"Ops Day trigger on http://{args.host}:{server.server_port} using {label}; "
        f"next day {trigger.next_day}, {trigger.days_left} left.",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
