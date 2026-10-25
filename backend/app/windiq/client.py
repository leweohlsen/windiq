import os

from dotenv import load_dotenv

from wind_iq_measurement_api_client import Client
from wind_iq_measurement_api_client.api.messwerte import get_measurements_v1_measurements_get
from wind_iq_measurement_api_client.api.stammdaten import (
    get_mast_v1_mast_get,
    get_site_v1_site_get,
    get_turbine_v1_turbine_get,
)
from wind_iq_measurement_api_client.models import (
    Mast,
    MeasurementPage,
    Site,
    Turbine,
)

from .auth import BearerTokenAuth
from .errors import WindIQAPIError, WindIQCredentialsError
from .retry import retrying

DEFAULT_BASE_URL = "https://windiq-mock-api.sliplane.app"


class WindIQClient:
    """Facade over the generated client with bearer-token auth.

    Credentials, token exchange and refresh are handled internally; callers
    just await the typed helpers and get parsed models back. Transient
    failures (timeouts, connection errors, 429/5xx) are retried with
    exponential backoff and jitter.
    """

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        max_attempts: int | None = None,
        backoff: float | None = None,
        max_wait: float | None = None,
        sleep=None,
    ) -> None:
        load_dotenv()
        base_url = base_url or os.getenv("WIQ_API_BASE_URL", DEFAULT_BASE_URL)
        client_id = client_id or os.getenv("WIQ_CLIENT_ID")
        client_secret = client_secret or os.getenv("WIQ_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise WindIQCredentialsError(
                "Set WIQ_CLIENT_ID and WIQ_CLIENT_SECRET (see .env.example)."
            )

        self.base_url = base_url
        self._retryer = retrying(max_attempts, backoff, max_wait, sleep)
        self._auth = BearerTokenAuth(base_url, client_id, client_secret, self._retryer)
        self._client = Client(
            base_url=base_url,
            httpx_args={"auth": self._auth},
            timeout=30.0,
        )

    def _expect(self, response):
        if response.status_code != 200:
            retry_after = None
            try:
                retry_after = float(response.headers.get("Retry-After"))
            except (TypeError, ValueError):
                pass
            detail = getattr(response.parsed, "detail", None) or str(response.parsed)
            raise WindIQAPIError(response.status_code, detail, retry_after)
        return response.parsed

    async def _with_retry(self, fn, /, **kwargs):
        async def attempt():
            return self._expect(await fn(**kwargs))

        return await self._retryer(attempt)

    async def mast(self) -> Mast:
        return await self._with_retry(
            get_mast_v1_mast_get.asyncio_detailed, client=self._client
        )

    async def turbine(self) -> Turbine:
        return await self._with_retry(
            get_turbine_v1_turbine_get.asyncio_detailed, client=self._client
        )

    async def site(self) -> Site:
        return await self._with_retry(
            get_site_v1_site_get.asyncio_detailed, client=self._client
        )

    async def measurements(
        self,
        *,
        since=None,
        updated_since=None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> MeasurementPage:
        return await self._with_retry(
            get_measurements_v1_measurements_get.asyncio_detailed,
            client=self._client,
            since=since,
            updated_since=updated_since,
            limit=limit,
            cursor=cursor,
        )

    async def token(self) -> str:
        """Fetch/refresh the access token explicitly (useful for smoke checks)."""
        return await self._auth.fetch_token()
