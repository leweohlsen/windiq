from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error import Error
from ...models.issue_token_auth_token_post_data_token_request import IssueTokenAuthTokenPostDataTokenRequest
from ...models.issue_token_auth_token_post_json_token_request import IssueTokenAuthTokenPostJsonTokenRequest
from ...models.token_response import TokenResponse
from ...types import UNSET, Response


def _get_kwargs(
    *,
    body: IssueTokenAuthTokenPostJsonTokenRequest | IssueTokenAuthTokenPostDataTokenRequest | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/token",
    }

    if isinstance(body, IssueTokenAuthTokenPostJsonTokenRequest):
        _kwargs["json"] = body.to_dict()

        headers["Content-Type"] = "application/json"
    if isinstance(body, IssueTokenAuthTokenPostDataTokenRequest):
        _kwargs["data"] = body.to_dict()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Error | TokenResponse | None:
    if response.status_code == 200:
        response_200 = TokenResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = Error.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = Error.from_dict(response.json())

        return response_401

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Error | TokenResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: IssueTokenAuthTokenPostJsonTokenRequest | IssueTokenAuthTokenPostDataTokenRequest | Unset = UNSET,
) -> Response[Error | TokenResponse]:
    """Access Token anfordern

     Tauscht `client_id` und `client_secret` gegen ein Bearer Token.

    Args:
        body (IssueTokenAuthTokenPostJsonTokenRequest):
        body (IssueTokenAuthTokenPostDataTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Error | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: IssueTokenAuthTokenPostJsonTokenRequest | IssueTokenAuthTokenPostDataTokenRequest | Unset = UNSET,
) -> Error | TokenResponse | None:
    """Access Token anfordern

     Tauscht `client_id` und `client_secret` gegen ein Bearer Token.

    Args:
        body (IssueTokenAuthTokenPostJsonTokenRequest):
        body (IssueTokenAuthTokenPostDataTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Error | TokenResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: IssueTokenAuthTokenPostJsonTokenRequest | IssueTokenAuthTokenPostDataTokenRequest | Unset = UNSET,
) -> Response[Error | TokenResponse]:
    """Access Token anfordern

     Tauscht `client_id` und `client_secret` gegen ein Bearer Token.

    Args:
        body (IssueTokenAuthTokenPostJsonTokenRequest):
        body (IssueTokenAuthTokenPostDataTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Error | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: IssueTokenAuthTokenPostJsonTokenRequest | IssueTokenAuthTokenPostDataTokenRequest | Unset = UNSET,
) -> Error | TokenResponse | None:
    """Access Token anfordern

     Tauscht `client_id` und `client_secret` gegen ein Bearer Token.

    Args:
        body (IssueTokenAuthTokenPostJsonTokenRequest):
        body (IssueTokenAuthTokenPostDataTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Error | TokenResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
