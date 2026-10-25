import time
from collections.abc import AsyncGenerator, Generator

import httpx

from .errors import WindIQAuthError
from .retry import retrying

TOKEN_URL = "/auth/token"

# Re-authenticate slightly before the token actually expires.
EXPIRY_MARGIN_S = 30.0


class BearerTokenAuth(httpx.Auth):
    """httpx auth flow that keeps a bearer token fresh.

    Exchanges client credentials for an access token on first use and
    transparently re-authenticates when the token expires or a 401 is received.
    Token fetches go through the shared retryer for resilience against a
    flaky auth endpoint.
    """

    def __init__(self, base_url, client_id, client_secret, retryer=None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._retryer = retryer or retrying()
        self._token: str | None = None
        self._expires_at = 0.0

    def _has_token(self) -> bool:
        return self._token is not None and time.monotonic() < self._expires_at - EXPIRY_MARGIN_S

    def _apply(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = f"Bearer {self._token}"

    def _extract(self, response: httpx.Response) -> None:
        if response.status_code in (400, 401):
            detail = response.json().get("detail", "missing or invalid credentials")
            raise WindIQAuthError(f"{response.status_code}: {detail}")
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        self._expires_at = time.monotonic() + float(data.get("expires_in", 3600))

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if not self._has_token():
            self._fetch_token_sync()
        self._apply(request)
        response = yield request
        if response.status_code == 401:
            self._fetch_token_sync()
            self._apply(request)
            yield request

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._has_token():
            await self._fetch_token_async()
        self._apply(request)
        response = yield request
        if response.status_code == 401:
            await self._fetch_token_async()
            self._apply(request)
            yield request

    def _fetch_token_sync(self) -> None:
        with httpx.Client(base_url=self._base_url, timeout=15.0) as client:
            response = client.post(
                TOKEN_URL,
                json={"client_id": self._client_id, "client_secret": self._client_secret},
            )
        self._extract(response)

    async def _do_fetch_once(self) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=15.0) as client:
            return await client.post(
                TOKEN_URL,
                json={"client_id": self._client_id, "client_secret": self._client_secret},
            )

    async def _fetch_token_async(self) -> None:
        async def attempt() -> None:
            self._extract(await self._do_fetch_once())

        await self._retryer(attempt)

    async def fetch_token(self) -> str:
        """Fetch/refresh the access token explicitly. Useful for smoke checks."""
        await self._fetch_token_async()
        assert self._token is not None
        return self._token
