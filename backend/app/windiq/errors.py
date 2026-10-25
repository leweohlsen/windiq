class WindIQError(Exception):
    """Base error for the WindIQ API client."""


class WindIQCredentialsError(WindIQError):
    """WIQ_CLIENT_ID / WIQ_CLIENT_SECRET are missing from the environment."""


class WindIQAuthError(WindIQError):
    """The token endpoint rejected the client credentials."""


class WindIQAPIError(WindIQError):
    """A WindIQ API endpoint returned a documented error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")
