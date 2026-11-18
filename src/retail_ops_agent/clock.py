"""The clock seam. Everything behind the Ops Day boundary reads time from a Clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def advance(self, delta: timedelta) -> None:
        """Move simulated time forward."""
        ...


class SimulatedClock:
    """A controllable clock for simulated time, tests and sandboxes."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("simulated time only moves forward")
        self._now += delta
