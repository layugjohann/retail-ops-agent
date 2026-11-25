"""Pacing model requests to stay inside free-tier rate limits (ADR 0001).

Free tiers cap requests (and tokens) per minute. A Throttle spaces requests evenly, and a model
that is refused for a rate limit anyway, or told the provider is briefly overloaded (503), waits as
long as the provider asks, or backs off, and tries again. A request the provider never answers
times out and is retried the same way, so one dropped connection cannot stall a whole run.

Every retry is logged (as a warning, so it reaches stderr with no logging set up), and a wait longer
than max_wait_seconds is refused with ProviderWaitTooLong instead of slept out: a free tier whose
daily quota is spent asks for hours, which would otherwise look like a hang.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError, ModelRateLimitError
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
# The longest wait a provider may ask for before the request is given up. A per-minute limit asks
# for seconds; a spent daily quota asks for hours.
MAX_WAIT_SECONDS = 300.0
# A wait at least this long means a daily quota, not a per-minute limit.
DAILY_LIMIT_WAIT_SECONDS = 3600.0
PROVIDER_NAMES = {"groq": "Groq", "google-gla": "Gemini", "google-vertex": "Gemini"}

logger = logging.getLogger(__name__)


class ProviderWaitTooLong(AgentRunError):
    """The provider asked to wait longer than the model's max_wait_seconds, so it was not waited out."""


def format_wait(seconds: float) -> str:
    """A wait as a person reads it: 45s, 3m20s, 2h24m."""
    whole = round(seconds)
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        minutes, rest = divmod(whole, 60)
        return f"{minutes}m{rest:02d}s" if rest else f"{minutes}m"
    hours, rest = divmod(whole, 3600)
    minutes = rest // 60
    return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"


def provider_message(error: ModelAPIError) -> str:
    """The provider's own words about the error, when its body has them."""
    body = error.body
    if isinstance(body, dict):
        detail = body.get("error")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            message = detail.get("message")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(message, str):
                return message
    return error.message


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
        max_wait_seconds: float = MAX_WAIT_SECONDS,
    ) -> None:
        super().__init__(wrapped)
        self.throttle = throttle
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.max_wait_seconds = max_wait_seconds

    async def _wait_to_retry(self, status: str, attempt: int, seconds: float, message: str) -> None:
        """Log the retry and wait, or raise ProviderWaitTooLong when the wait is over the cap."""
        if seconds > self.max_wait_seconds:
            provider = PROVIDER_NAMES.get(self.wrapped.system, self.wrapped.system)
            reason = (
                "daily token limit likely spent"
                if seconds >= DAILY_LIMIT_WAIT_SECONDS
                else f"longer than the {format_wait(self.max_wait_seconds)} this run waits"
            )
            raise ProviderWaitTooLong(
                f"{provider} asks to wait {format_wait(seconds)}: {reason} "
                f"(model {self.model_name}, {status}: {message})"
            )
        logger.warning(
            "%s: %s on attempt %d, retrying in %s: %s",
            self.model_name,
            status,
            attempt,
            format_wait(seconds),
            message,
        )
        await self.throttle.sleep(seconds)

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
                await self._wait_to_retry(
                    "timeout",
                    retries + 1,
                    self.backoff_seconds * 2**retries,
                    f"no answer within {format_wait(self.request_timeout_seconds)}",
                )
            except ModelAPIError as error:
                if not _worth_retrying(error) or retries >= self.max_retries:
                    raise
                status = str(error.status_code) if isinstance(error, ModelHTTPError) else "429"
                await self._wait_to_retry(
                    status,
                    retries + 1,
                    error.retry_after or self.backoff_seconds * 2**retries,
                    provider_message(error),
                )
            retries += 1
