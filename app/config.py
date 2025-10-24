from pydantic_settings import BaseSettings
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    OPENAI_API_KEY: str | None = None
    DATABASE_URL: str | None = None  # <-- añade este campo

    # Lee del .env (por si no vieniera del entorno) y NO rompas por otras claves
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",          # <-- clave: ignora variables no declaradas
        case_sensitive=False,    # <-- 'database_url' o 'DATABASE_URL' sirven
    )

settings = Settings()

# Fallback: si tras lo anterior sigue vacía, intenta cargar otra vez con dotenv
if not settings.OPENAI_API_KEY:
    load_dotenv(dotenv_path=str(ENV_PATH))
    settings.OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()

if not settings.OPENAI_API_KEY:
    raise RuntimeError(f"OPENAI_API_KEY no encontrada. Revisa {ENV_PATH}.")