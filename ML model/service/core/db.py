from sqlalchemy import create_engine

from bess_common.db_settings import database_url

DATABASE_URL = database_url()  # env var, else backend/.env

# plant local time, like the backend (date filters and timestamps)
engine = create_engine(DATABASE_URL, connect_args={"options": "-c timezone=Asia/Kolkata"},
                       hide_parameters=True)  # bound values never appear in exception text / logs
