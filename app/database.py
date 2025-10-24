import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent.parent  # ajusta si es necesario
load_dotenv(BASE_DIR / ".env")

raw_url = os.getenv("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL no está definido (revisa tu .env)")

engine = create_async_engine(
    raw_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
