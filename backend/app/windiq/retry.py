import os

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

from .errors import WindIQAPIError

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF = 0.5
DEFAULT_MAX_WAIT = 8.0

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def is_transient(exc: BaseException) -> bool:
    """Whether a failure is transient and worth retrying.

    Timeouts and connection errors count; so do 429/5xx responses. Deliberate
    API errors (4xx, auth failures) do not — they will not succeed on retry.
    """
    if isinstance(exc, WindIQAPIError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TransportError)


def _retry_after_hint(exc: BaseException | None) -> float | None:
    """Retry-After in seconds if the API suggested one, else None."""
    if isinstance(exc, WindIQAPIError):
        return exc.retry_after
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return float(exc.response.headers.get("Retry-After"))
        except (TypeError, ValueError):
            pass
    return None


class _wait_with_retry_after(wait_base):
    """Exponential backoff with jitter, honoring a Retry-After hint when the
    last exception carries one (capped so a hostile header can't stall us)."""

    def __init__(self, fallback: wait_base, cap: float) -> None:
        self._fallback = fallback
        self._cap = cap

    def __call__(self, retry_state: RetryCallState) -> float:
        retry_after = _retry_after_hint(retry_state.outcome.exception())
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self._cap)
        return self._fallback(retry_state)


def retrying(
    max_attempts: int | None = None,
    backoff: float | None = None,
    max_wait: float | None = None,
    sleep=None,
) -> AsyncRetrying:
    """Build an async retryer; unset args fall back to env or built-in defaults."""
    max_attempts = max_attempts if max_attempts is not None else int(
        os.getenv("WIQ_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    )
    backoff = backoff if backoff is not None else float(
        os.getenv("WIQ_RETRY_BACKOFF", DEFAULT_BACKOFF)
    )
    max_wait = max_wait if max_wait is not None else float(
        os.getenv("WIQ_RETRY_MAX_WAIT", DEFAULT_MAX_WAIT)
    )
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return AsyncRetrying(
        retry=retry_if_exception(is_transient),
        wait=_wait_with_retry_after(
            wait_exponential_jitter(multiplier=backoff, max=max_wait, jitter=backoff / 2),
            cap=max_wait,
        ),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
        **kwargs,
    )
