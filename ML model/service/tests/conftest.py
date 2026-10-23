"""pytest setup: remove the test users' rows from battery_itops.activity_log when the run ends."""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _purge_test_activity():
    yield
    from sqlalchemy import text
    from bess_common.observability import activity
    from core.db import engine
    activity.flush()
    with engine.begin() as conn:
        conn.execute(text("""DELETE FROM battery_itops.activity_log
                             WHERE user_email LIKE 'pytest.%' OR request_id LIKE 'pytest-%'"""))


@pytest.fixture(scope="session", autouse=True)
def _no_token_freshness():
    """These tests sign tokens for a made-up user id to exercise the ML path rules; the freshness check (role / user
    versions against battery_users) is covered by the backend's test_user_admin.py."""
    import main  # noqa: F401 - installs the real check first
    from bess_common.auth import set_freshness_check
    set_freshness_check(lambda principal: None)
    yield
