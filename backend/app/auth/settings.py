"""Session / login settings of the backend (token signing and verification settings live in bess_common.auth).

REFRESH_TOKEN_HOURS                       absolute lifetime of a refresh-token family (one login session)
LOGIN_MAX_FAILURES / LOGIN_LOCK_MINUTES   brute-force lockout
REFRESH_COOKIE_SECURE                     send the refresh cookie only over HTTPS (set to 1 behind TLS)
WEB_CLIENT_IDS                            clients that get the refresh token as an HttpOnly cookie instead of in the body
"""
import os
from functools import lru_cache


class AuthSettings:
    def __init__(self) -> None:
        self.refresh_hours = int(os.getenv("REFRESH_TOKEN_HOURS", "8"))
        self.max_failures = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
        self.lock_minutes = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
        self.refresh_race_seconds = 15  # a just-rotated token reused within this window is a client race, not theft
        self.cookie_name = "bess_refresh"
        self.cookie_path = "/api/auth"
        self.cookie_secure = os.getenv("REFRESH_COOKIE_SECURE", "0") == "1"
        self.web_clients = set(os.getenv("WEB_CLIENT_IDS", "bess-web").split(","))
        self.password_min_length = int(os.getenv("PASSWORD_MIN_LENGTH", "10"))


@lru_cache
def get_settings() -> AuthSettings:
    return AuthSettings()
