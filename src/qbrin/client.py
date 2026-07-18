"""The qbrin client — zero-dependency (stdlib only).

    from qbrin import Qbrin

    qb = Qbrin(api_key="qbrin_...")            # hosted default
    v = qb.verify("Can I refund $500 for order ORD-200?")
    if v.is_verified:
        act(v.answer, sources=v.evidence)
    else:
        print(v.decision, "-", v.explanation)

Auth is a Bearer API token (create one in Console → Settings → API tokens).
``transport`` is injectable for tests: any callable
``(method, url, headers, body_bytes, timeout) -> (status, headers, body_bytes)``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .errors import (
    APIError,
    AuthenticationError,
    FeatureDisabledError,
    QbrinError,
    RateLimitError,
    TransportError,
)
from .models import AskResult, VerifyResult

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://app.qbrin.com/api"
_RETRYABLE = {429, 502, 503, 504}


def credentials_path() -> Path:
    """Where `qbrin login` stores the token (override dir with QBRIN_HOME)."""
    home = os.environ.get("QBRIN_HOME") or os.path.join(Path.home(), ".qbrin")
    return Path(home) / "credentials"


def _load_credentials() -> Dict[str, Any]:
    """Read ~/.qbrin/credentials if present; never raise on a missing/bad file."""
    try:
        return json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

Transport = Callable[[str, str, Dict[str, str], Optional[bytes], float],
                     Tuple[int, Dict[str, str], bytes]]


def _urllib_transport(method: str, url: str, headers: Dict[str, str],
                      body: Optional[bytes], timeout: float) -> Tuple[int, Dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - https only
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TransportError(str(e)) from e


class Qbrin:
    """Synchronous client for the qbrin verification layer."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: Optional[Transport] = None,
    ):
        # Credential resolution: explicit arg → QBRIN_API_KEY env → the file
        # `qbrin login` writes (~/.qbrin/credentials). base_url follows the same
        # order, defaulting to the hosted API.
        stored = _load_credentials()
        api_key = api_key or os.environ.get("QBRIN_API_KEY") or stored.get("token")
        base_url = base_url or os.environ.get("QBRIN_BASE_URL") or stored.get("base_url") or DEFAULT_BASE_URL
        if not api_key or not isinstance(api_key, str):
            raise QbrinError(
                "No API key found. Run `qbrin login`, set QBRIN_API_KEY, or pass api_key=."
            )
        if not base_url.lower().startswith("https://") and "localhost" not in base_url and "127.0.0.1" not in base_url:
            raise QbrinError("base_url must use https (plain http is allowed only for localhost).")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._transport = transport or _urllib_transport

    # ── public surface ────────────────────────────────────────────────

    def verify(self, question: str, k: Optional[int] = None) -> VerifyResult:
        """Verify a question against the org's connected sources.

        Returns the tri-state contract: ``verified`` (with an answer whose
        every claim passed the citation-support gate), ``rejected`` (the
        sources contradict the premise), or ``need_more_evidence``.
        Requires ``VERIFY_API=1`` on the server (beta).
        """
        body: Dict[str, Any] = {"question": question}
        if k is not None:
            body["k"] = int(k)
        data = self._request("POST", "/verify", body)
        return VerifyResult.from_dict(data)

    def ask(self, question: str, k: Optional[int] = None) -> AskResult:
        """Ask a question; returns a grounded, citation-first answer.

        qbrin abstains (a fixed sentence) instead of guessing when the
        sources don't contain the answer.
        """
        body: Dict[str, Any] = {"question": question}
        if k is not None:
            body["k"] = int(k)
        data = self._request("POST", "/ask", body)
        return AskResult.from_dict(data)

    def search(self, query: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Universal search (no LLM): documents, knowledge nodes, people."""
        params = {"q": query}
        if limit is not None:
            params["limit"] = str(int(limit))
        return self._request("GET", "/search?" + urllib.parse.urlencode(params))

    # ── plumbing ──────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._base_url + path
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": f"qbrin-python/{__version__}",
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")

        attempt = 0
        while True:
            status, resp_headers, raw = self._transport(method, url, headers, payload, self._timeout)
            if status in _RETRYABLE and attempt < self._max_retries:
                attempt += 1
                time.sleep(self._retry_delay(resp_headers, attempt))
                continue
            return self._parse(status, resp_headers, raw, path)

    @staticmethod
    def _retry_delay(headers: Dict[str, str], attempt: int) -> float:
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if ra:
            try:
                return min(30.0, max(0.0, float(ra)))
            except ValueError:
                pass
        return min(8.0, 0.5 * (2 ** attempt))

    @staticmethod
    def _parse(status: int, headers: Dict[str, str], raw: bytes, path: str) -> Dict[str, Any]:
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        if 200 <= status < 300:
            return data
        message = str(data.get("error") or data.get("message") or "request failed")
        if status in (401, 403):
            raise AuthenticationError(status, message, data)
        if status == 429:
            ra = headers.get("Retry-After") or headers.get("retry-after")
            retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
            raise RateLimitError(status, message, data, retry_after=retry_after)
        if status == 404 and path.startswith("/verify"):
            raise FeatureDisabledError(
                status,
                "The verification endpoint is not enabled on this server (VERIFY_API=1 required).",
                data,
            )
        raise APIError(status, message, data)
