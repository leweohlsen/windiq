import httpx
import pytest
from tenacity import RetryCallState
from tenacity.wait import wait_base

from app.windiq.errors import WindIQAPIError, WindIQAuthError
from app.windiq.retry import _wait_with_retry_after, is_transient, retrying

REQUEST = httpx.Request("GET", "https://api.example.com")


def status_error(code: int, headers: dict | None = None) -> httpx.HTTPStatusError:
    response = httpx.Response(code, headers=headers, request=REQUEST)
    return httpx.HTTPStatusError(f"{code}", request=REQUEST, response=response)


async def noop_sleep(_duration: float) -> None:
    pass


def make_state(exception: BaseException) -> RetryCallState:
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
    state.set_exception((type(exception), exception, None))
    return state


def test_is_transient():
    assert is_transient(httpx.TimeoutException("slow")) is True
    assert is_transient(httpx.ConnectError("boom")) is True
    assert is_transient(status_error(429)) is True
    assert is_transient(status_error(503)) is True
    assert is_transient(WindIQAPIError(500, "x")) is True

    assert is_transient(status_error(400)) is False
    assert is_transient(WindIQAPIError(404, "x")) is False
    assert is_transient(WindIQAuthError("rejected")) is False
    assert is_transient(ValueError("oops")) is False


async def test_retries_until_success():
    waits = []

    async def sleep(duration: float) -> None:
        waits.append(duration)

    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.TimeoutException("timeout")
        return "ok"

    result = await retrying(max_attempts=4, sleep=sleep)(flaky)
    assert result == "ok"
    assert calls == 3
    assert all(0 < w <= 8 for w in waits)


async def test_no_retry_on_client_error():
    calls = 0

    async def bad() -> str:
        nonlocal calls
        calls += 1
        raise WindIQAPIError(404, "nope")

    retryer = retrying(max_attempts=4, sleep=noop_sleep)
    with pytest.raises(WindIQAPIError):
        await retryer(bad)
    assert calls == 1


async def test_exhaustion_reraises_original():
    calls = 0

    async def always_fails() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    retryer = retrying(max_attempts=3, sleep=noop_sleep)
    with pytest.raises(httpx.ConnectError):
        await retryer(always_fails)
    assert calls == 3


def test_wait_prefers_retry_after_within_cap():
    fallback_calls = 0

    class FixedWait(wait_base):
        def __call__(self, retry_state):
            nonlocal fallback_calls
            fallback_calls += 1
            return 0.125

    strategy = _wait_with_retry_after(FixedWait(), cap=8)
    assert strategy(make_state(WindIQAPIError(429, "slow", retry_after=3.0))) == 3.0
    assert fallback_calls == 0

    assert strategy(make_state(WindIQAPIError(503, "x", retry_after=999.0))) == 8

    assert strategy(make_state(status_error(503, {"Retry-After": "2"}))) == 2.0
    assert strategy(make_state(status_error(429, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))) == 0.125
    assert strategy(make_state(WindIQAPIError(429, "no hint"))) == 0.125
    assert strategy(make_state(WindIQAPIError(400, "permanent"))) == 0.125
    assert fallback_calls == 3


def test_env_defaults(monkeypatch):
    monkeypatch.setenv("WIQ_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("WIQ_RETRY_BACKOFF", "1.5")
    monkeypatch.setenv("WIQ_RETRY_MAX_WAIT", "20")
    retryer = retrying()
    assert retryer.stop.max_attempt_number == 7
    assert retryer.wait._fallback.multiplier == 1.5
    assert retryer.wait._fallback.max == 20
