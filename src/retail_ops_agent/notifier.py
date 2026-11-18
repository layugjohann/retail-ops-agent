"""The Notifier seam: messages to Uploaders and alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Notification(BaseModel):
    model_config = ConfigDict(frozen=True)

    sent_at: datetime
    recipient: str
    subject: str
    body: str


class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...


class LogNotifier:
    """Keeps notifications in a log the dashboard can show. Slack or Teams can replace it later."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)
