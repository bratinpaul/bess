import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# tables live in battery_master / battery_telemetry (see migrations/2026_09_27_split_schemas.py);
# public stays last for the timescaledb functions (time_bucket, ...)
SEARCH_PATH = "battery_master,battery_telemetry,battery_raw,public"

engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={SEARCH_PATH}"})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
