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
