"""Pacing model requests to stay inside free-tier rate limits (ADR 0001).

Free tiers cap requests (and tokens) per minute. A Throttle spaces requests evenly, and a model
that is refused for a rate limit anyway, or told the provider is briefly overloaded (503), waits as
long as the provider asks, or backs off, and tries again. A request the provider never answers
times out and is retried the same way, so one dropped connection cannot stall a whole run.
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
# Free tiers answer this during demand spikes ("This model is currently experiencing high demand"),
# which pass in seconds to minutes.
SERVICE_UNAVAILABLE = 503
RETRIED_STATUSES = {TOO_MANY_REQUESTS, SERVICE_UNAVAILABLE}
# Long enough for a slow free-tier answer; a request still unanswered after this has been dropped.
REQUEST_TIMEOUT_SECONDS = 120.0


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


def _worth_retrying(error: ModelAPIError) -> bool:
    return isinstance(error, ModelRateLimitError) or (
        isinstance(error, ModelHTTPError) and error.status_code in RETRIED_STATUSES
    )


class ThrottledModel(WrapperModel):
    """A model whose requests go through a Throttle and are retried when rate-limited, the
    provider is briefly overloaded, or the provider never answers."""

    def __init__(
        self,
        wrapped: Model,
        throttle: Throttle,
        *,
        max_retries: int = 5,
        backoff_seconds: float = 10.0,
        request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(wrapped)
        self.throttle = throttle
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_timeout_seconds = request_timeout_seconds

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
                return await asyncio.wait_for(
                    self.wrapped.request(messages, model_settings, model_request_parameters),
                    timeout=self.request_timeout_seconds,
                )
            except TimeoutError:
                if retries >= self.max_retries:
                    raise
                await self.throttle.sleep(self.backoff_seconds * 2**retries)
            except ModelAPIError as error:
                if not _worth_retrying(error) or retries >= self.max_retries:
                    raise
                await self.throttle.sleep(error.retry_after or self.backoff_seconds * 2**retries)
            retries += 1
