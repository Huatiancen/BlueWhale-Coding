"""Per-launch authentication for the loopback desktop web server."""

from __future__ import annotations

import hmac
import secrets

DESKTOP_COOKIE = "bluewhale_desktop_session"


class DesktopSessionGuard:
    """Validate a one-time bootstrap token and its derived session cookie."""

    def __init__(self, bootstrap_token: str) -> None:
        if not bootstrap_token:
            raise ValueError("desktop token must not be empty")
        self._bootstrap_token = bootstrap_token
        self._session_token = secrets.token_urlsafe(32)
        self._cache_token = secrets.token_urlsafe(8)

    def accepts_bootstrap(self, candidate: str | None) -> bool:
        return candidate is not None and hmac.compare_digest(
            self._bootstrap_token,
            candidate,
        )

    def accepts_session(self, candidate: str | None) -> bool:
        return candidate is not None and hmac.compare_digest(
            self._session_token,
            candidate,
        )

    @property
    def session_token(self) -> str:
        return self._session_token

    @property
    def cache_token(self) -> str:
        return self._cache_token
