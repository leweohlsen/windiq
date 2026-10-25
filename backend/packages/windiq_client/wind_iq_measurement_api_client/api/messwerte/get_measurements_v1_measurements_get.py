import datetime
from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error import Error
from ...models.http_validation_error import HTTPValidationError
from ...models.measurement_page import MeasurementPage
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    since: datetime.datetime | None | Unset = UNSET,
    updated_since: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_since: None | str | Unset
    if isinstance(since, Unset):
        json_since = UNSET
    elif isinstance(since, datetime.datetime):
        json_since = since.isoformat()
    else:
        json_since = since
    params["since"] = json_since

    json_updated_since: None | str | Unset
    if isinstance(updated_since, Unset):
        json_updated_since = UNSET
    elif isinstance(updated_since, datetime.datetime):
        json_updated_since = updated_since.isoformat()
    else:
        json_updated_since = updated_since
    params["updated_since"] = json_updated_since

    params["limit"] = limit

    json_cursor: None | str | Unset
    if isinstance(cursor, Unset):
        json_cursor = UNSET
    else:
        json_cursor = cursor
    params["cursor"] = json_cursor

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/measurements",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Error | HTTPValidationError | MeasurementPage | None:
    if response.status_code == 200:
        response_200 = MeasurementPage.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = Error.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = Error.from_dict(response.json())

        return response_401

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Error | HTTPValidationError | MeasurementPage]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    since: datetime.datetime | None | Unset = UNSET,
    updated_since: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Response[Error | HTTPValidationError | MeasurementPage]:
    """Stündliche Messwerte

     Messwerte des Masts auf Messhöhe, standardmäßig nach `timestamp` sortiert.

    Ohne Filter beginnt die Liste mit dem ältesten verfügbaren Wert. Weitere Seiten
    über `cursor` abrufen, solange `next_cursor` nicht `null` ist.

    Args:
        since (datetime.datetime | None | Unset): Nur Werte mit `timestamp` >= since (Messzeit)
        updated_since (datetime.datetime | None | Unset): Nur Werte mit `updated_at` >=
            updated_since (Änderungszeit). Sortierung dann nach `updated_at`.
        limit (int | Unset): Maximale Anzahl Werte pro Seite Default: 100.
        cursor (None | str | Unset): `next_cursor` der vorherigen Seite

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Error | HTTPValidationError | MeasurementPage]
    """

    kwargs = _get_kwargs(
        since=since,
        updated_since=updated_since,
        limit=limit,
        cursor=cursor,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    since: datetime.datetime | None | Unset = UNSET,
    updated_since: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Error | HTTPValidationError | MeasurementPage | None:
    """Stündliche Messwerte

     Messwerte des Masts auf Messhöhe, standardmäßig nach `timestamp` sortiert.

    Ohne Filter beginnt die Liste mit dem ältesten verfügbaren Wert. Weitere Seiten
    über `cursor` abrufen, solange `next_cursor` nicht `null` ist.

    Args:
        since (datetime.datetime | None | Unset): Nur Werte mit `timestamp` >= since (Messzeit)
        updated_since (datetime.datetime | None | Unset): Nur Werte mit `updated_at` >=
            updated_since (Änderungszeit). Sortierung dann nach `updated_at`.
        limit (int | Unset): Maximale Anzahl Werte pro Seite Default: 100.
        cursor (None | str | Unset): `next_cursor` der vorherigen Seite

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Error | HTTPValidationError | MeasurementPage
    """

    return sync_detailed(
        client=client,
        since=since,
        updated_since=updated_since,
        limit=limit,
        cursor=cursor,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    since: datetime.datetime | None | Unset = UNSET,
    updated_since: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Response[Error | HTTPValidationError | MeasurementPage]:
    """Stündliche Messwerte

     Messwerte des Masts auf Messhöhe, standardmäßig nach `timestamp` sortiert.

    Ohne Filter beginnt die Liste mit dem ältesten verfügbaren Wert. Weitere Seiten
    über `cursor` abrufen, solange `next_cursor` nicht `null` ist.

    Args:
        since (datetime.datetime | None | Unset): Nur Werte mit `timestamp` >= since (Messzeit)
        updated_since (datetime.datetime | None | Unset): Nur Werte mit `updated_at` >=
            updated_since (Änderungszeit). Sortierung dann nach `updated_at`.
        limit (int | Unset): Maximale Anzahl Werte pro Seite Default: 100.
        cursor (None | str | Unset): `next_cursor` der vorherigen Seite

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Error | HTTPValidationError | MeasurementPage]
    """

    kwargs = _get_kwargs(
        since=since,
        updated_since=updated_since,
        limit=limit,
        cursor=cursor,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    since: datetime.datetime | None | Unset = UNSET,
    updated_since: datetime.datetime | None | Unset = UNSET,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Error | HTTPValidationError | MeasurementPage | None:
    """Stündliche Messwerte

     Messwerte des Masts auf Messhöhe, standardmäßig nach `timestamp` sortiert.

    Ohne Filter beginnt die Liste mit dem ältesten verfügbaren Wert. Weitere Seiten
    über `cursor` abrufen, solange `next_cursor` nicht `null` ist.

    Args:
        since (datetime.datetime | None | Unset): Nur Werte mit `timestamp` >= since (Messzeit)
        updated_since (datetime.datetime | None | Unset): Nur Werte mit `updated_at` >=
            updated_since (Änderungszeit). Sortierung dann nach `updated_at`.
        limit (int | Unset): Maximale Anzahl Werte pro Seite Default: 100.
        cursor (None | str | Unset): `next_cursor` der vorherigen Seite

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Error | HTTPValidationError | MeasurementPage
    """

    return (
        await asyncio_detailed(
            client=client,
            since=since,
            updated_since=updated_since,
            limit=limit,
            cursor=cursor,
        )
    ).parsed
