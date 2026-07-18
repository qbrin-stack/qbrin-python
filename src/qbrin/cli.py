"""`qbrin` CLI — zero-copy-paste auth.

    qbrin login     # browser → Google → token written to ~/.qbrin/credentials
    qbrin whoami    # show the logged-in org + token expiry
    qbrin logout    # revoke the token and remove the file

`login` opens a browser at the qbrin server, which relays a Google sign-in and
mints a scoped token server-side; the CLI just polls until it's ready. No
secret, no loopback, nothing pasted. Stdlib only.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from .client import DEFAULT_BASE_URL, credentials_path

_POLL_INTERVAL_S = 1.5
_POLL_MAX_S = 300


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:  # nosec B310 - https base
        return json.loads(r.read().decode("utf-8"))


def _write_credentials(payload: dict) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def login(base_url: str) -> int:
    # Confirm the server has CLI login enabled (else /config is 404).
    try:
        _get_json(f"{base_url}/auth/cli/config")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("qbrin login isn't enabled on this server yet.", file=sys.stderr)
            return 1
        raise

    session = _b64url(secrets.token_bytes(32))
    start = f"{base_url}/auth/cli/start?session={urllib.parse.quote(session)}"
    print("Opening your browser to sign in with Google…")
    print(f"If it doesn't open, visit:\n  {start}\n")
    threading.Thread(target=lambda: webbrowser.open(start), daemon=True).start()

    poll = f"{base_url}/auth/cli/poll?session={urllib.parse.quote(session)}"
    deadline = time.monotonic() + _POLL_MAX_S
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        try:
            r = _get_json(poll)
        except Exception:
            continue  # transient — keep polling
        status = r.get("status")
        if status == "complete":
            path = _write_credentials({
                "token": r["token"], "tokenId": r.get("tokenId"),
                "base_url": base_url, "org": r.get("org"), "expiresAt": r.get("expiresAt"),
            })
            org = (r.get("org") or {}).get("slug", "your workspace")
            print(f"✓ Signed in to {org}. Token saved to {path}.")
            print("  Now `Qbrin()` works with no api_key.")
            return 0
        if status == "error":
            print(f"Sign-in failed: {r.get('error')}", file=sys.stderr)
            return 1
        if status == "expired":
            print("Sign-in session expired — run `qbrin login` again.", file=sys.stderr)
            return 1
        # pending → keep polling
    print("Timed out waiting for sign-in.", file=sys.stderr)
    return 1


def whoami() -> int:
    try:
        creds = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Not logged in. Run `qbrin login`.")
        return 1
    print(f"org:      {(creds.get('org') or {}).get('slug', '?')}")
    print(f"expires:  {creds.get('expiresAt') or 'never'}")
    print(f"base_url: {creds.get('base_url') or DEFAULT_BASE_URL}")
    return 0


def logout() -> int:
    path = credentials_path()
    try:
        creds = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Already logged out.")
        return 0
    tid, base = creds.get("tokenId"), creds.get("base_url") or DEFAULT_BASE_URL
    if tid and creds.get("token"):
        try:
            req = urllib.request.Request(
                f"{base}/auth/tokens/{tid}", method="DELETE",
                headers={"Authorization": f"Bearer {creds['token']}"},
            )
            urllib.request.urlopen(req, timeout=15)  # nosec B310 - best-effort revoke
        except Exception:
            pass
    try:
        path.unlink()
    except OSError:
        pass
    print("Logged out.")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "help"
    base_url = os.environ.get("QBRIN_BASE_URL") or DEFAULT_BASE_URL
    if cmd == "login":
        return login(base_url)
    if cmd == "whoami":
        return whoami()
    if cmd == "logout":
        return logout()
    print("qbrin — the Universal Trust Layer\n\nUsage:\n  qbrin login    sign in with Google\n  qbrin whoami   show the current login\n  qbrin logout   revoke and forget the token")
    return 0 if cmd in ("help", "-h", "--help") else 1


if __name__ == "__main__":
    raise SystemExit(main())
