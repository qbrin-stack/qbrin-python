"""Errors raised by the qbrin client."""

from __future__ import annotations

from typing import Any, Dict, Optional


class QbrinError(Exception):
    """Base class for every error this SDK raises."""


class TransportError(QbrinError):
    """The request never produced an HTTP response (network/DNS/timeout)."""


class APIError(QbrinError):
    """The API answered with a non-2xx status."""

    def __init__(self, status: int, message: str, body: Optional[Dict[str, Any]] = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.body = body or {}


class AuthenticationError(APIError):
    """401/403 — the API key is missing, invalid, or lacks the needed scope."""


class RateLimitError(APIError):
    """429 — slow down; ``retry_after`` carries the server's hint in seconds."""

    def __init__(self, status: int, message: str, body=None, retry_after: Optional[float] = None):
        super().__init__(status, message, body)
        self.retry_after = retry_after


class FeatureDisabledError(APIError):
    """404 on a known endpoint — the feature flag (e.g. VERIFY_API) is off server-side."""
