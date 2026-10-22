"""Login and RBAC for the BESS backend (fastapi-users over battery_users, RS256 JWT access tokens, rotating refresh
tokens). Public routes: /api/auth/token, /api/auth/revoke, /api/health; everything else needs a bearer token."""
from app.auth import rbac_map  # noqa: F401  (router -> resource map)
from app.auth.security import Principal, authenticated, require

__all__ = ["Principal", "authenticated", "require"]
