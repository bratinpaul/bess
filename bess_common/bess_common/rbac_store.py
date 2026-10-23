"""Database side of the RBAC: token freshness and the privilege registry - shared by the backend and the ML service.

TokenFreshness(engine)
    The check bess_common.auth.authenticated runs on every request (set_freshness_check). Access tokens carry the role
    version (rv) and the user's token version (uv) from when they were issued; a role whose grants changed, or a user
    whose role / tenant / status changed, has a newer version in battery_users, and the token is refused with 401 - the
    frontend (and the batch loaders) refresh and retry, so changes take effect within the cache TTL without a logout.
    Versions are cached per process (default 30 s); invalidate() drops the cache at once (the backend calls it after an
    admin change, so its own checks are immediate).

sync_privilege_registry(engine, service, codes)
    At start-up each service records the permission codes it enforces (bess_common.auth.enforced_permissions()):
    unknown codes are added as system privileges, `registered_by` gains / loses the service, and `enforced` says whether
    any service still checks the code. Custom privileges (added by an admin) stay `enforced = false` until code checks them.
"""
import logging
import threading
import time
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("bess.rbac")


class TokenFreshness:
    def __init__(self, engine: Engine, ttl_seconds: float = 30.0):
        self.engine, self.ttl = engine, ttl_seconds
        self._roles: dict[str, int] = {}
        self._users: dict[str, tuple[int, bool]] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    def _load(self) -> None:
        with self.engine.connect() as conn:
            self._roles = {code: v for code, v in conn.execute(text("SELECT role_code, version FROM battery_users.role"))}
            self._users = {uid: (v, active) for uid, v, active in conn.execute(
                text("SELECT id::text, token_version, is_active FROM battery_users.app_user"))}
        self._loaded_at = time.monotonic()

    def _reload_if_older(self, seconds: float) -> bool:
        if time.monotonic() - self._loaded_at <= seconds:
            return True
        with self._lock:
            if time.monotonic() - self._loaded_at > seconds:
                try:
                    self._load()
                except Exception as exc:  # noqa: BLE001 - a DB hiccup must not lock everyone out
                    log.error("token freshness: could not read versions", extra={"error": str(exc)[:200]})
                    return False
        return True

    def _refresh_one(self, principal) -> None:
        """Re-read just this token's role and user (one small query) - the cache may be behind: a user created or changed
        after the last full read, or a change made through the other service. Only validly signed tokens get here."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""SELECT (SELECT version FROM battery_users.role WHERE role_code = :r),
                                                  u.token_version, u.is_active
                                           FROM (SELECT 1) one
                                           LEFT JOIN battery_users.app_user u ON u.id::text = :u"""),
                                   {"r": principal.role, "u": principal.user_id}).first()
        except Exception as exc:  # noqa: BLE001
            log.error("token freshness: could not re-read a user", extra={"error": str(exc)[:200]})
            return
        role_version, token_version, active = row
        if role_version is not None:
            self._roles[principal.role] = role_version
        if token_version is not None:
            self._users[principal.user_id] = (token_version, active)
        else:
            self._users.pop(principal.user_id, None)

    def __call__(self, principal) -> Optional[str]:
        if not self._reload_if_older(self.ttl):
            return None
        reason = self._evaluate(principal)
        if reason and reason != "token_without_versions":
            self._refresh_one(principal)
            reason = self._evaluate(principal)
        return reason

    def _evaluate(self, principal) -> Optional[str]:
        if principal.role_version is None or principal.user_version is None:
            return "token_without_versions"  # issued before versions existed
        if self._roles.get(principal.role) != principal.role_version:
            return "role_changed"
        user = self._users.get(principal.user_id)
        if user is None or not user[1]:
            return "user_disabled"
        if user[0] != principal.user_version:
            return "user_changed"
        return None


def sync_privilege_registry(engine: Engine, service: str, codes: Iterable[str]) -> dict:
    codes = sorted({c for c in codes if ":" in c})
    with engine.begin() as conn:
        for code in codes:
            resource, action = code.split(":", 1)
            conn.execute(text("""
                INSERT INTO battery_users.privilege (resource, action, source, enforced, registered_by)
                VALUES (:r, :a, 'system', true, ARRAY[:svc])
                ON CONFLICT (resource, action) DO UPDATE SET
                    source = 'system',
                    registered_by = ARRAY(SELECT DISTINCT unnest(battery_users.privilege.registered_by || ARRAY[:svc])
                                          ORDER BY 1)"""), {"r": resource, "a": action, "svc": service})
        conn.execute(text("""UPDATE battery_users.privilege SET registered_by = array_remove(registered_by, :svc)
                             WHERE :svc = ANY(registered_by) AND NOT (code = ANY(:codes))"""),
                     {"svc": service, "codes": codes})
        conn.execute(text("""UPDATE battery_users.privilege SET enforced = (source = 'system' AND cardinality(registered_by) > 0)
                             WHERE enforced IS DISTINCT FROM (source = 'system' AND cardinality(registered_by) > 0)"""))
        stale = conn.execute(text("SELECT count(*) FROM battery_users.privilege WHERE NOT enforced")).scalar()
    log.info("privilege registry synced", extra={"event": "rbac.registry_synced", "service": service,
                                                 "codes": len(codes), "not_enforced": stale})
    return {"service": service, "codes": len(codes), "not_enforced": stale}
