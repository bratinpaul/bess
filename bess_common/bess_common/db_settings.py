"""Database connection settings for scripts outside the backend app (migrations, generators, the ML service).

The single source is DATABASE_URL: the environment variable if set, else the line in <project>/backend/.env
(git-ignored). No credentials live in code.
"""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "backend" / ".env"


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        raise RuntimeError(f"DATABASE_URL is not set and not found in {ENV_FILE} (see backend/.env.example)")
    return url


def psycopg2_dsn(**extra) -> dict:
    """psycopg2.connect(**psycopg2_dsn()) keyword arguments from DATABASE_URL."""
    u = urlparse(database_url().replace("postgresql+psycopg2://", "postgresql://"))
    return dict(host=u.hostname, port=u.port or 5432, dbname=u.path.lstrip("/"), user=unquote(u.username or ""),
                password=unquote(u.password or ""), **extra)
