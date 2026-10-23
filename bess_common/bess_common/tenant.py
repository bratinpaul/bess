"""Tenant data scoping for tenant-scoped callers (Tenant Viewer: token claim tenant_id) - shared by the backend and the ML
service. Unscoped callers are untouched.

    ScopeResolver        the ids a tenant may see, by entity type, from battery_master (cached briefly per tenant):
                         site -> system -> container -> pack -> module; pcs / ems / hvac via the system;
                         metering_point / station via the site
    tenant_guard(...)    request dependency: every entity id in the query string, path or JSON body must be in scope,
                         else 404 (not 403 - don't reveal that the record exists)
    TenantResponseFilter ASGI middleware for GET JSON responses: list items carrying an out-of-scope id are dropped, id
                         lists inside objects are narrowed, and a top-level object for an out-of-scope entity becomes 404
Aggregates that a filter can't see into (counts, sums) are scoped in the endpoints themselves.
"""
import json
import re
import time
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from bess_common.auth import Principal, authenticated
from bess_common.observability import security_log

# field / parameter name -> entity type
ID_KEYS = {
    "site_id": "site", "system_id": "system", "battery_system_id": "system", "holdout_system_id": "system",
    "container_id": "container", "pack_id": "pack", "module_id": "module", "pcs_id": "pcs", "ems_id": "ems",
    "hvac_id": "hvac", "metering_point_id": "metering_point", "mp_id": "metering_point", "station_id": "station",
}
LIST_KEYS = {"site_ids": "site", "system_ids": "system", "pcs_ids": "pcs", "ems_ids": "ems", "hvac_ids": "hvac",
             "module_ids": "module", "mp_ids": "metering_point", "metering_point_ids": "metering_point"}
# generic names whose entity depends on the URL (KPI domains)
PATH_RULES: tuple[tuple[str, dict[str, str]], ...] = (
    (r"^/api/bms-kpi", {"entity_id": "system", "id": "system"}),  # /entities returns {id, name, samples}
    (r"^/api/pcs-kpi", {"entity_id": "pcs", "id": "pcs"}),
    (r"^/api/ems-kpi", {"entity_id": "ems", "id": "ems"}),
)
_COMPILED = tuple((re.compile(rx), keys) for rx, keys in PATH_RULES)


def keys_for(path: str) -> dict[str, str]:
    keys = dict(ID_KEYS)
    for rx, extra in _COMPILED:
        if rx.search(path):
            keys.update(extra)
    return keys


class ScopeResolver:
    """{entity type: frozenset(ids)} visible to a tenant, cached for `ttl` seconds."""

    SQL = {
        "site": "SELECT site_id FROM battery_master.tenant_site WHERE tenant_id = :t",
        "system": "SELECT battery_system_id FROM battery_master.battery_system WHERE site_id = ANY(:site)",
        "container": "SELECT container_id FROM battery_master.battery_container WHERE battery_system_id = ANY(:system)",
        "pack": "SELECT pack_id FROM battery_master.battery_pack WHERE container_id = ANY(:container)",
        "module": "SELECT module_id FROM battery_master.battery_module WHERE pack_id = ANY(:pack)",
        "pcs": "SELECT pcs_id FROM battery_master.pcs WHERE system_id = ANY(:system)",
        "ems": "SELECT ems_id FROM battery_master.ems_controller WHERE battery_system_id = ANY(:system)",
        "hvac": "SELECT hvac_id FROM battery_master.hvac_unit WHERE battery_system_id = ANY(:system)",
        "metering_point": "SELECT metering_point_id FROM battery_master.metering_point WHERE site_id = ANY(:site)",
        "station": "SELECT station_id FROM battery_master.weather_station WHERE site_id = ANY(:site)",
    }

    def __init__(self, engine: Engine, ttl: float = 60.0):
        self.engine, self.ttl = engine, ttl
        self._cache: dict[int, tuple[float, dict[str, frozenset]]] = {}

    def get(self, tenant_id: int) -> dict[str, frozenset]:
        hit = self._cache.get(tenant_id)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        out: dict[str, frozenset] = {}
        with self.engine.connect() as conn:
            for kind, sql in self.SQL.items():  # dict order = dependency order
                params = {"t": tenant_id, **{k: list(v) for k, v in out.items()}}
                out[kind] = frozenset(int(r[0]) for r in conn.execute(text(sql), params))
        self._cache[tenant_id] = (time.monotonic(), out)
        return out


def _ints(values: Iterable) -> list[int]:
    out = []
    for v in values:
        if v is None or v == "":
            continue
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _violations(pairs: Iterable[tuple[str, object]], keys: dict[str, str], scope: dict[str, frozenset]) -> list[str]:
    bad = []
    for name, value in pairs:
        kind = keys.get(name) or LIST_KEYS.get(name)
        if not kind:
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        if any(i not in scope.get(kind, frozenset()) for i in _ints(values)):
            bad.append(name)
    return bad


def tenant_guard(resolver: ScopeResolver):
    """Router-include-level dependency: a tenant-scoped caller may only address entities of its own tenant (404)."""
    async def guard(request: Request, principal: Principal = Depends(authenticated)) -> None:
        if principal.tenant_id is None:
            return
        scope = resolver.get(principal.tenant_id)
        keys = keys_for(request.url.path)
        pairs: list[tuple[str, object]] = [(k, request.query_params.getlist(k)) for k in request.query_params.keys()]
        pairs += list(request.path_params.items())
        if request.method in ("POST", "PUT", "PATCH") and "json" in request.headers.get("content-type", ""):
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 - malformed bodies are rejected by the endpoint's own validation
                body = None
            if isinstance(body, dict):
                pairs += list(body.items())
        bad = _violations(pairs, keys, scope)
        if bad:
            security_log.warning("tenant scope refused", extra={"event": "auth.tenant_scope",
                                                                "tenant_id": principal.tenant_id, "fields": bad,
                                                                "method": request.method, "path": request.url.path})
            raise HTTPException(status_code=404, detail="Not found")
    guard.tenant_guard = True
    return guard


def _out_of_scope(obj: dict, keys: dict[str, str], scope: dict[str, frozenset]) -> bool:
    return bool(_violations(obj.items(), keys, scope))


def _filter(node, keys, scope):
    if isinstance(node, list):
        return [_filter(x, keys, scope) for x in node if not (isinstance(x, dict) and _out_of_scope(x, keys, scope))]
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            kind = LIST_KEYS.get(k)
            if kind and isinstance(v, list):  # e.g. defaults.hvac_ids -> only the tenant's units
                allowed = scope.get(kind, frozenset())
                out[k] = [i for i in v if not _ints([i]) or _ints([i])[0] in allowed]
            else:
                out[k] = _filter(v, keys, scope)
        return out
    return node


class TenantResponseFilter(BaseHTTPMiddleware):
    """Narrows GET JSON responses for tenant-scoped callers (see module doc). `exclude` paths pass untouched."""

    def __init__(self, app, resolver: ScopeResolver, exclude: tuple[str, ...] = ()):
        super().__init__(app)
        self.resolver, self.exclude = resolver, exclude

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        principal: Optional[Principal] = getattr(request.state, "principal", None)
        if (principal is None or principal.tenant_id is None or request.method != "GET" or response.status_code != 200
                or "application/json" not in response.headers.get("content-type", "")
                or request.url.path.startswith(self.exclude)):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            data = json.loads(body)
        except ValueError:
            return Response(body, status_code=response.status_code, media_type=response.media_type)
        scope = self.resolver.get(principal.tenant_id)
        keys = keys_for(request.url.path)
        # keep the inner response's headers (CORS headers included - this middleware sits outside CORSMiddleware)
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        if isinstance(data, dict) and _out_of_scope(data, keys, scope):
            security_log.warning("tenant scope refused", extra={"event": "auth.tenant_scope",
                                                                "tenant_id": principal.tenant_id, "method": "GET",
                                                                "path": request.url.path})
            return JSONResponse(status_code=404, content={"detail": "Not found"}, headers=headers)
        return JSONResponse(content=_filter(data, keys, scope), status_code=200, headers=headers)
