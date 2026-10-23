"""BESS ML service: mounts every use case's router under /<use case> (see usecases/ and "ML model/README.md")."""
import logging
import re

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bess_common.errors import api_docs_kwargs, install_exception_handlers
from bess_common.observability import RequestContextMiddleware, enable_activity_log, setup_logging

setup_logging("ml")  # JSON lines to stdout + logs/ml/ml.log, before the use cases import

from bess_common.auth import enforced_permissions, set_freshness_check  # noqa: E402
from bess_common.rbac_store import TokenFreshness, sync_privilege_registry  # noqa: E402
from bess_common.tenant import TenantResponseFilter  # noqa: E402
from core.auth import ML_RBAC, TENANT_GUARD, TENANT_SCOPE, authenticated  # noqa: E402
from core.db import engine  # noqa: E402
from usecases import USE_CASES, soh  # noqa: E402

app = FastAPI(title="BESS ML Service", **api_docs_kwargs())  # no /docs, /redoc, /openapi.json when APP_ENV=prod
# one error shape for every 4xx/5xx; safe messages only, 5xx logged with the stack trace (bess_common/errors.py)
install_exception_handlers(app)

# deny by default: every use case needs a bearer token issued by the backend (/api/auth/token) AND the RBAC permission
# for the request (core.auth.ML_RBAC: GET -> ml.results:read, POST incl. what-if predictions -> ml.run:execute,
# DELETE -> ml.run:delete, default / activate / deactivate / publish -> ml.model:approve, candidate review ->
# fault.review:write). Only /health is public.
PROTECTED = [Depends(authenticated), Depends(ML_RBAC), Depends(TENANT_GUARD)]
app.add_middleware(TenantResponseFilter, resolver=TENANT_SCOPE)
for use_case in USE_CASES:
    app.include_router(use_case.router, prefix=f"/{getattr(use_case, 'PREFIX', use_case.NAME)}", dependencies=PROTECTED)

# the URLs from before use-case namespaces (/predict, /train, /runs ...) stay as aliases of /soh/...
app.include_router(soh.router, include_in_schema=False, dependencies=PROTECTED)

TRAINING = re.compile(r"^/(?:(?P<uc>[a-z-]+)/)?(?:runs|train|studies)$")
SCORING = re.compile(r"^/(?P<uc>[a-z-]+)/(?:runs/\d+/score|live/score)$")


def classify(method: str, path: str):
    """Requests logged as operations (start / end / duration / run id): model training and scoring runs."""
    if method != "POST":
        return None
    m = TRAINING.match(path)
    if m:
        return "training", f"{m.group('uc') or 'soh'}_training"
    m = SCORING.match(path)
    if m:
        return "training", f"{m.group('uc')}_scoring"
    return None


# tokens whose role / user changed since they were issued are refused (401) and refreshed by the client
set_freshness_check(TokenFreshness(engine, ttl_seconds=30))


@app.on_event("startup")
def register_privileges() -> None:
    """Record the permission codes the ML service enforces (battery_users.privilege.registered_by / enforced)."""
    try:
        sync_privilege_registry(engine, "ml", enforced_permissions())
    except Exception as exc:  # noqa: BLE001 - the service must still start
        logging.getLogger("bess.rbac").error("privilege registry sync failed", extra={"error": str(exc)[:200]})


enable_activity_log(engine)
app.add_middleware(RequestContextMiddleware, classify=classify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:4300"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health")
def health():
    status = {uc.NAME: uc.status() for uc in USE_CASES}
    # model_version: kept for older callers (the SOH default model)
    return {"status": "ok", "model_version": status["soh"]["model_version"], "use_cases": status}
