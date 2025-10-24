# alembic/env.py
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, create_engine

# Cargar .env si existe (opcional, pero cómodo en desarrollo)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
import os
from dotenv import load_dotenv
load_dotenv()


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Importa Base y modelos para que Alembic detecte los mapeos
from app.database import Base  # tu Base declarativa
from app import models         # importa tus modelos (NO debe disparar llamadas a OpenAI)

# Config de Alembic
config = context.config
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL_SYNC"))
# Asegura que 'app/' esté en el sys.path
# Logging de Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadatos de tus modelos
target_metadata = Base.metadata

def _get_sqlalchemy_url() -> str:
    """
    Prioriza env var DATABASE_URL si existe; si no, usa lo de alembic.ini (sqlalchemy.url).
    Ojo: Alembic usa motor síncrono; para async usa un DSN compatible (psycopg2/psycopg).
    """
    return os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
import os
from alembic import context
from sqlalchemy import create_engine, pool

def _get_sqlalchemy_url() -> str:
    return (
        os.getenv("ALEMBIC_DATABASE_URL")          # preferida para alembic
        or os.getenv("DATABASE_URL")               # fallback (si trae +asyncpg, Alembic fallará)
        or context.config.get_main_option("sqlalchemy.url"))

def run_migrations_offline():
    url = _get_sqlalchemy_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    url = _get_sqlalchemy_url()
    # Para Alembic usa motor síncrono
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
