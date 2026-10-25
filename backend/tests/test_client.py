import httpx
import pytest

import app.windiq.client as client_module
from app.windiq.client import WindIQClient
from app.windiq.errors import WindIQAPIError, WindIQAuthError


async def noop_sleep(_duration: float) -> None:
    pass


PARSED = object()


class FakeResponse:
    def __init__(self, status_code: int, parsed=None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.parsed = parsed
        self.headers = headers or {}


def make_client() -> WindIQClient:
    return WindIQClient(
        client_id="test-id",
        client_secret="test-secret",
        base_url="https://api.example.com",
        max_attempts=3,
        sleep=noop_sleep,
    )


async def test_measurements_retries_on_503(monkeypatch):
    client = make_client()
    calls = 0

    async def fake_detailed(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return FakeResponse(503, parsed={"detail": "overloaded"})
        return FakeResponse(200, parsed=PARSED)

    monkeypatch.setattr(
        client_module.get_measurements_v1_measurements_get, "asyncio_detailed", fake_detailed
    )
    assert await client.measurements() is PARSED
    assert calls == 3


async def test_timeout_retries_then_reraises(monkeypatch):
    client = make_client()
    calls = 0

    async def fake_detailed(**kwargs):
        nonlocal calls
        calls += 1
        raise httpx.TimeoutException("took too long")

    monkeypatch.setattr(client_module.get_mast_v1_mast_get, "asyncio_detailed", fake_detailed)
    with pytest.raises(httpx.TimeoutException):
        await client.mast()
    assert calls == 3


async def test_client_error_not_retried(monkeypatch):
    client = make_client()
    calls = 0

    async def fake_detailed(**kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(404, parsed={"detail": "missing"})

    monkeypatch.setattr(client_module.get_site_v1_site_get, "asyncio_detailed", fake_detailed)
    with pytest.raises(WindIQAPIError):
        await client.site()
    assert calls == 1


async def test_token_fetch_retries_on_connect_error(monkeypatch):
    client = make_client()
    calls = 0

    async def flaky_fetch():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(
            200,
            json={"access_token": "tok", "expires_in": 3600},
            request=httpx.Request("POST", client.base_url + "/auth/token"),
        )

    monkeypatch.setattr(client._auth, "_do_fetch_once", flaky_fetch)
    assert await client.token() == "tok"
    assert calls == 3


async def test_token_fetch_does_not_retry_auth_rejection(monkeypatch):
    client = make_client()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"detail": "invalid credentials"},
            request=httpx.Request("POST", client.base_url + "/auth/token"),
        )

    monkeypatch.setattr(client._auth, "_do_fetch_once", fetch)
    with pytest.raises(WindIQAuthError):
        await client.token()
    assert calls == 1
