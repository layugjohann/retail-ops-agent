"""Pacing model requests to stay inside free-tier rate limits (ADR 0001).

Free tiers cap requests (and tokens) per minute. A Throttle spaces requests evenly, and a model
that is refused for a rate limit anyway waits as long as the provider asks, or backs off, and tries
again.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, ModelRateLimitError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

type Sleep = Callable[[float], Awaitable[None]]

TOO_MANY_REQUESTS = 429


class Throttle:
    """Lets at most requests_per_minute requests start each minute, evenly spaced.

    0 means no pacing. Share one Throttle between models that count against the same limit.
    """

    def __init__(
        self,
        requests_per_minute: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if requests_per_minute < 0:
            raise ValueError("requests_per_minute cannot be negative")
        self.interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self.sleep = sleep
        self._monotonic = monotonic
        self._next_start: float | None = None

    async def wait(self) -> None:
        """Wait until the next request may start."""
        now = self._monotonic()
        if self._next_start is not None and now < self._next_start:
            await self.sleep(self._next_start - now)
            now = self._next_start
        self._next_start = now + self.interval


def _rate_limited(error: ModelAPIError) -> bool:
    return isinstance(error, ModelRateLimitError) or (
        isinstance(error, ModelHTTPError) and error.status_code == TOO_MANY_REQUESTS
    )


class ThrottledModel(WrapperModel):
    """A model whose requests go through a Throttle and are retried when rate-limited."""

    def __init__(
        self,
        wrapped: Model,
        throttle: Throttle,
        *,
        max_retries: int = 5,
        backoff_seconds: float = 10.0,
    ) -> None:
        super().__init__(wrapped)
        self.throttle = throttle
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        retries = 0
        while True:
            await self.throttle.wait()
            try:
                return await self.wrapped.request(messages, model_settings, model_request_parameters)
            except ModelAPIError as error:
                if not _rate_limited(error) or retries >= self.max_retries:
                    raise
                await self.throttle.sleep(error.retry_after or self.backoff_seconds * 2**retries)
                retries += 1
