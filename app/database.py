# database.py - VERSIÓN CORREGIDA
import os
from dotenv import load_dotenv
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import ssl

load_dotenv()

class Base(DeclarativeBase):
    pass

# URL de conexión CON asyncpg
DATABASE_URL = "postgresql+asyncpg://postgres.whkclbhcvpxfbaznkcvm:Antwtocumpo@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"

print("🚀 Conectando con asyncpg...")

# Configuración SSL para asyncpg
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Engine CON asyncpg - VERSIÓN CORREGIDA
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=True,
    connect_args={
        "ssl": ssl_context,
        "prepared_statement_cache_size": 0,  # ✅ SOLUCIÓN AL ERROR
        "statement_cache_size": 0,           # ✅ SOLUCIÓN ALTERNATIVA
    },
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db():
    async with SessionLocal() as session:
        yield session