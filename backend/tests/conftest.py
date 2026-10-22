"""pytest setup: the async auth engine must not pool connections across the TestClients' event loops."""
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTH_DB_NULLPOOL", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

CLEANUP = """DELETE FROM battery_ops.activity_log
             WHERE user_email LIKE 'pytest.%' OR request_id LIKE 'pytest-%' OR detail::text LIKE '%pytest.%'"""


@pytest.fixture(scope="session", autouse=True)
def _purge_test_activity():
    """The test users' requests land in battery_ops.activity_log - remove them when the run ends."""
    yield
    from sqlalchemy import text
    from app.database import SessionLocal
    from bess_common.observability import activity
    activity.flush()
    with SessionLocal() as db:
        db.execute(text(CLEANUP))
        db.commit()
