"""Bearer token for the batch loaders (realtime snapshot, static data, historical): they call the backend's bulk APIs, which
are deny-by-default, as the service account batch.service@bess.local (role Data Engineer).

    from bess_service_auth import auth_headers
    request = urllib.request.Request(url, headers={**auth_headers(api), ...})

Credentials: BESS_SERVICE_EMAIL / BESS_SERVICE_PASSWORD, else <project>/keys/service_account.json (written by
backend/setup/bootstrap_auth.py). The access / refresh tokens are cached in keys/.service_token.json, so the
every-minute realtime batch reuses one login session (refresh rotation) instead of logging in each run.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KEYS = Path(__file__).resolve().parent / "keys"
CACHE = KEYS / ".service_token.json"
_memory: dict = {}


def _credentials() -> tuple[str, str]:
    email, password = os.getenv("BESS_SERVICE_EMAIL"), os.getenv("BESS_SERVICE_PASSWORD")
    if email and password:
        return email, password
    data = json.loads((KEYS / "service_account.json").read_text(encoding="utf-8"))
    return data["email"], data["password"]


def _post_token(api: str, form: dict) -> dict:
    body = urllib.parse.urlencode({**form, "client_id": "bess-batch"}).encode()
    req = urllib.request.Request(api + "/api/auth/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        tok = json.loads(resp.read())
    now = time.time()
    return {"api": api, "access_token": tok["access_token"], "access_exp": now + tok["expires_in"],
            "refresh_token": tok["refresh_token"], "refresh_exp": now + tok["refresh_expires_in"]}


def _load_cache(api: str) -> dict:
    if _memory.get("api") == api:
        return _memory
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        return data if data.get("api") == api else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    _memory.clear()
    _memory.update(data)
    try:
        CACHE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def access_token(api: str) -> str:
    now = time.time()
    data = _load_cache(api)
    if data and data.get("access_exp", 0) - 60 > now:
        return data["access_token"]
    if data and data.get("refresh_exp", 0) - 60 > now:
        try:
            fresh = _post_token(api, {"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
            _save(fresh)
            return fresh["access_token"]
        except urllib.error.HTTPError:
            pass  # rotated elsewhere / revoked / expired -> log in again
    email, password = _credentials()
    fresh = _post_token(api, {"grant_type": "password", "username": email, "password": password})
    _save(fresh)
    return fresh["access_token"]


def invalidate_access_token() -> None:
    """Forget the cached access token (keep the refresh token), so the next call fetches a fresh one - used after a
    401, e.g. when an admin changed the account's role and the old token is refused as out of date."""
    data = dict(_memory)
    if not data:
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if data:
        data["access_exp"] = 0
        _save(data)


def open_authed(api: str, request: urllib.request.Request, timeout: float):
    """urlopen with the service account's bearer token; on 401 refresh the token once and retry."""
    for attempt in (1, 2):
        for name, value in auth_headers(api).items():
            request.add_header(name, value)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 1:
                invalidate_access_token()
                continue
            raise


def auth_headers(api: str) -> dict:
    """Bearer token, plus the loader run's id as X-Request-ID so backend log lines match the loader's."""
    headers = {"Authorization": f"Bearer {access_token(api)}"}
    try:
        from bess_common.observability import current_context
        rid = current_context().get("request_id")
        if rid:
            headers["X-Request-ID"] = rid
    except ImportError:
        pass
    return headers
