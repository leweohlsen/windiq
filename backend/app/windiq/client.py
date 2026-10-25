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

DEFAULT_BASE_URL = "https://windiq-mock-api.sliplane.app"


class WindIQClient:
    """Facade over the generated client with bearer-token auth.

    Credentials, token exchange and refresh are handled internally; callers
    just await the typed helpers and get parsed models back.
    """

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
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
        self._auth = BearerTokenAuth(base_url, client_id, client_secret)
        self._client = Client(
            base_url=base_url,
            httpx_args={"auth": self._auth},
            timeout=30.0,
        )

    async def _expect(self, response):
        if response.status_code != 200:
            detail = getattr(response.parsed, "detail", None) or str(response.parsed)
            raise WindIQAPIError(response.status_code, detail)
        return response.parsed

    async def mast(self) -> Mast:
        return await self._expect(await get_mast_v1_mast_get.asyncio_detailed(client=self._client))

    async def turbine(self) -> Turbine:
        return await self._expect(
            await get_turbine_v1_turbine_get.asyncio_detailed(client=self._client)
        )

    async def site(self) -> Site:
        return await self._expect(await get_site_v1_site_get.asyncio_detailed(client=self._client))

    async def measurements(
        self,
        *,
        since=None,
        updated_since=None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> MeasurementPage:
        return await self._expect(
            await get_measurements_v1_measurements_get.asyncio_detailed(
                client=self._client,
                since=since,
                updated_since=updated_since,
                limit=limit,
                cursor=cursor,
            )
        )

    async def token(self) -> str:
        """Fetch/refresh the access token explicitly (useful for smoke checks)."""
        return await self._auth.fetch_token()
