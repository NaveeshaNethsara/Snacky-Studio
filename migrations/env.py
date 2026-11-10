from pathlib import Path
import os
from alembic import context
from sqlalchemy import create_engine, pool
from app.config import Settings
from app.cloud_store import metadata

if not os.environ.get("SNACKY_DATABASE_URL"):
    for env_file in [Path(".env.cloud"), Path(".env")]:
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SNACKY_DATABASE_URL="):
                    _, v = line.split("=", 1)
                    os.environ["SNACKY_DATABASE_URL"] = v.strip().strip('"').strip("'")
                    break
            if os.environ.get("SNACKY_DATABASE_URL"):
                break

url = Settings().database_url
if not url:
    raise RuntimeError("Set SNACKY_DATABASE_URL before running migrations")
if context.is_offline_mode():
    context.configure(url=url,target_metadata=metadata,literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    engine = create_engine(url,poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection,target_metadata=metadata)
        with context.begin_transaction(): context.run_migrations()
