"""The backend's token-freshness check (role / user versions in the access token vs battery_users) - see
bess_common.rbac_store. main.py installs it with set_freshness_check; the admin API calls invalidate() after a change so
the backend's own checks see it at once (the ML service picks it up within its cache TTL)."""
from bess_common.rbac_store import TokenFreshness

from app.database import engine

freshness = TokenFreshness(engine, ttl_seconds=30)
