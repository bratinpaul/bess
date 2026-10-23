import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# tables live in battery_master / battery_telemetry (see BESS DESIGN/Database/DDL);
# public stays last for the timescaledb functions (time_bucket, ...)
SEARCH_PATH = "battery_master,battery_telemetry,battery_raw,public"

engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={SEARCH_PATH}"},
                       hide_parameters=True)  # bound values never appear in exception text / logs
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """One session per request. A failing request is rolled back here and the exception travels on to the handlers in
    bess_common/errors.py (an IntegrityError becomes the constraint's catalog message), so routers just commit."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
