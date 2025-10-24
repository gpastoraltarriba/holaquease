# ───────────────────────────────
# 🧩 Librerías estándar
# ───────────────────────────────
import os
import re
from pydantic import ValidationError
import json
from sqlalchemy import inspect as sa_inspect  # ← evita conflicto con stdlib
import uuid
import base64
import shutil
import inspect as py_inspect  # ← si necesitas stdlib inspect
import logging
import traceback
from types import SimpleNamespace
from statistics import mean
from math import isfinite
from datetime import datetime, date
import datetime as _dt
from pathlib import Path

# ───────────────────────────────
# 🌐 Dependencias externas
# ───────────────────────────────
from dotenv import load_dotenv
from jose import jwt, JWTError
from passlib.context import CryptContext
import aiohttp
import openai
from openai import AsyncOpenAI

# ───────────────────────────────
# ⚙️ FastAPI / Starlette
# ───────────────────────────────
from fastapi import (
    FastAPI, APIRouter, Request, Depends, HTTPException, Form,
    UploadFile, File, Query, Cookie
)
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm

# ───────────────────────────────
# 🧠 SQLAlchemy
# ───────────────────────────────
from sqlalchemy import select, insert, update
# ⚠️ No importes create_async_engine aquí. Lo gestiona app.database.
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession  # si lo necesitas para Depends

# ───────────────────────────────
# 🧱 App interna
# ───────────────────────────────
# Carga .env ANTES de tocar app.database
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from app import models, crud, schemas
from app.database import engine, Base, get_db  # ← usa el engine ASYNC ya configurado
from app.models import (
    Usuario, Gimnasio, UsuarioGimnasio, SesionEntreno, RegistroComida,
    Entrenamiento, Plan, UsuarioPlan, Dieta, InfraestructuraGimnasio,
    FormularioCliente, FormularioDieta, FormularioMixto,
    Rutina, PlanMixtoGenerado, DietaGenerada
)
from app.crud import (
    crear_o_actualizar_formulario,
    crear_o_actualizar_formulario_dieta
)
from app.schemas import (
    FormularioClienteCreate,
    FormularioMixtoCreate
)
from app.utils import (
    generar_imagen_ejercicio,
    generar_alternativas_ia,
    generar_rutina_ia,
    generar_dieta_ia,
    ajustar_rutina_ia,
    construir_prompt,
    construir_prompt_mixto,
    construir_prompt_dieta,
    construir_prompt_alternativas,
    get_current_user_from_token,
)

# ───────────────────────────────
# ⚙️ App y config
# ───────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

SECRET_KEY = "akejngklaengkangkñ"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_AVATAR_REL = "uploads/2571eb2a-583a-490b-aa0d-c2ca737e290f.png"

if not os.getenv("OPENAI_API_KEY"):
    print("[BOOT] OPENAI_API_KEY NO CARGADA (revisa la ruta del .env)")

router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["DEFAULT_AVATAR_REL"] = DEFAULT_AVATAR_REL
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ───────────────────────────────
# 🔌 Startup / Shutdown (DB)
# ───────────────────────────────
from sqlalchemy.engine.url import make_url

@app.on_event("startup")
async def startup() -> None:
    # Log de sanity check del DSN (sin password)
    dsn = os.getenv("DATABASE_URL", "")
    try:
        url = make_url(dsn) if dsn else None
        logger.info(
            "DB driver=%s host=%s port=%s db=%s",
            url.drivername if url else None,
            url.host if url else None,
            url.port if url else None,
            url.database if url else None,
        )
    except Exception as e:
        logger.warning("No se pudo parsear DATABASE_URL: %s", e)

    # (Opcional) crear tablas si no existen
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("DB OK: metadata revisada/creada")
    except Exception as e:
        logger.exception("Fallo al conectar/crear tablas en startup: %s", e)
        # Re-lanza si quieres abortar el arranque:
        # raise

@app.on_event("shutdown")
async def shutdown() -> None:
    try:
        await engine.dispose()
        logger.info("Engine disposed correctamente")
    except Exception as e:
        logger.warning("Error al cerrar engine: %s", e)


async def get_template_context(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Inyecta variables globales a las plantillas (usuario actual, avatar por defecto, etc.)
    """
    user = None
    token_data = request.cookies.get("access_token")
    try:
        user_data = await get_current_user_from_token(token_data, db)
        if user_data:
            user = await db.get(models.Usuario, user_data["id"])
    except Exception:
        user = None

    return {
        "request": request,
        "usuario": user,
        "DEFAULT_AVATAR_REL": DEFAULT_AVATAR_REL
    }

def _safe_slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "_", s)
# Montar carpeta static y templates usando rutas absolutas

# --- KPIs helpers ---
def _pct_change(curr: float | None, prev: float | None) -> float | None:
    try:
        if curr is None or prev in (None, 0):
            return None
        return round(((curr - prev) / abs(prev)) * 100.0, 1)
    except Exception:
        return None

def _safe_float(v):
    try:
        return float(v)
    except Exception:
        return None

def _goal_from_form(objetivos: list[str] | None) -> str:
    """
    Devuelve 'subir_peso', 'bajar_peso' o 'mantener' según texto de objetivos.
    """
    txt = " ".join(objetivos or []).lower()
    if any(k in txt for k in ["subir", "ganar", "volumen"]):
        return "subir_peso"
    if any(k in txt for k in ["bajar", "perder", "definir", "cut"]):
        return "bajar_peso"
    return "mantener"

def _trend_color_and_arrow(delta: float | None, good_when_up: bool) -> tuple[str,str]:
    """
    Devuelve (cssClass, arrowChar)
    - cssClass: 'kpi-up' (verde), 'kpi-down' (rojo), 'kpi-flat' (gris)
    - arrowChar: '▲', '▼' o '—'
    """
    if delta is None:
        return ("kpi-flat", "—")
    if delta == 0:
        return ("kpi-flat", "—")
    # si subir es bueno:
    is_good = delta > 0 if good_when_up else delta < 0
    return ("kpi-up" if is_good else "kpi-down", "▲" if delta > 0 else "▼")

# Carpeta donde guardar uploads de imágenes (asegúrate que existe esta carpeta)


# Reemplaza la función existente por esta
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return PlainTextResponse(f"GENERIC ERROR:\n{tb}", status_code=500)

async def descargar_imagen_ia(url: str, filename: str) -> str | None:
    path = UPLOAD_DIR / filename
    try:
        if url.startswith("data:image/"):
            _, b64 = url.split(",", 1)
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            return f"/static/uploads/{filename}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        with open(path, "wb") as f:
            f.write(data)
        return f"/static/uploads/{filename}"
    except Exception:
        return None
async def get_current_user(request: Request, db: AsyncSession = Depends(get_db),
                           access_token: str | None = Cookie(default=None)):
    if access_token is None:
        logger.warning("No token provided")
        raise HTTPException(status_code=401, detail="No token provided")

    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        rol = payload.get("rol")
        logger.info(f"Usuario autenticado: {email}, Rol: {rol}")
    except JWTError as e:
        logger.error(f"Error decodificando token: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

    usuario = await crud.get_usuario_por_email(db, email)
    if usuario is None:
        logger.warning(f"Usuario no encontrado: {email}")
        raise HTTPException(status_code=404, detail="User not found")

    return {"id": usuario.id, "email": email, "rol": rol}


def role_required(required_roles: list[str]):
    def wrapper(current_user=Depends(get_current_user)):
        if current_user["rol"] not in required_roles:
            logger.warning(f"Acceso denegado. Rol actual: {current_user['rol']}, Roles requeridos: {required_roles}")
            raise HTTPException(status_code=403, detail="Access denied")
        return current_user

    return wrapper


@app.get("/api/ejercicios/generar-imagen")
async def api_generar_imagen_ejercicio(
    rutina_id: int,
    nombre: str,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    logger.info(f"[IMG-IA] req rutina_id={rutina_id} nombre='{nombre}' user={user['email']}")
    try:
        rutina = await db.get(models.Rutina, rutina_id)
        if not rutina or rutina.usuario_id != user["id"]:
            raise HTTPException(404, "Rutina no encontrada")

        # localizar ejercicio
        plan = rutina.rutina_json or {}
        objetivo = None
        for semana in plan.get("plan", []):
            for dia in semana.get("dias", []):
                for ej in dia.get("ejercicios", []):
                    if (ej.get("nombre") or "").strip().lower() == nombre.strip().lower():
                        objetivo = ej
                        break
                if objetivo: break
            if objetivo: break
        if not objetivo:
            raise HTTPException(404, "Ejercicio no existe en la rutina")

        # ya local
        url_existente = (objetivo.get("imagen_url") or "").strip()
        if url_existente.startswith("/static/uploads/"):
            logger.info(f"[IMG-IA] ya local -> {url_existente}")
            return {"url": url_existente}

        # normalizar si era remota previa
        if url_existente.startswith(("http://", "https://", "data:image/")):
            fname_old = f"ia_{_safe_slug(nombre)}_{uuid.uuid4().hex}.png"
            url_local_old = await descargar_imagen_ia(url_existente, fname_old)
            if url_local_old:
                objetivo["imagen_url"] = url_local_old
                rutina.rutina_json = plan
                await db.commit()
                logger.info(f"[IMG-IA] normalizada previa -> {url_local_old}")
                return {"url": url_local_old}

        # GENERAR IA
        motivo = objetivo.get("motivo", "")
        url_tmp = await generar_imagen_ejercicio(nombre, motivo)
        logger.info(f"[IMG-IA] OpenAI OK, tipo={'data' if url_tmp.startswith('data:') else 'url'}")

        # GUARDAR LOCAL SIEMPRE
        fname = f"ia_{_safe_slug(nombre)}_{uuid.uuid4().hex}.png"
        url_local = await descargar_imagen_ia(url_tmp, fname)
        if not url_local:
            logger.error("[IMG-IA] descargar_imagen_ia() devolvió None")
            raise HTTPException(502, "No se pudo guardar la imagen generada")

        try:
            objetivo["imagen_url"] = url_local
            rutina.rutina_json = plan
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(500, f"Error guardando la imagen en la BD: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[IMG-IA] fallo")
        raise HTTPException(500, detail="Error interno generando imagen")

# --- Sugerencias iniciales para semana 1 (sin histórico) ---
from math import isfinite

def _micro_round(x: float, step: float = 2.5) -> float | None:
    if x is None: return None
    return round(x / step) * step

async def _peso_usuario(db: AsyncSession, usuario_id: int) -> float | None:
    # intenta recuperar el peso actual del usuario (ajusta a tu modelo real)
    try:
        u = await db.get(models.Usuario, usuario_id)
        p = getattr(u, "peso_actual", None) or getattr(u, "peso", None)
        return float(p) if p else None
    except Exception:
        return None

async def sugerencia_inicial(
    db: AsyncSession,
    usuario_id: int,
    ejercicio_nombre: str,
    reps_obj: int | None = None,
    micro_step: float = 2.5
) -> float | None:
    """
    Devuelve una carga sugerida:
    1) Si hay histórico: usa tu lógica de sugerencia (Epley + ajuste).
    2) Si NO hay histórico: usa heurística por patrón + peso corporal si existe.
    Solo se usa como 'seed' en la SEMANA 1.
    """
    # 1) Si hay historial, usa tu predictor actual
    sets = await _ultimos_sets_usuario(db, usuario_id, ejercicio_nombre)
    load, _ = _sugerir_carga_desde_sets(sets, target_reps=(5, 8), micro_step=micro_step)
    if load:
        return load

    # 2) Heurística sin historial
    bw = await _peso_usuario(db, usuario_id) or 70.0  # fallback 70 kg
    name = (ejercicio_nombre or "").lower()

    # Mapa de arranque (novato/intermedio bajo) orientativo
    # % sobre peso corporal para compuestos; valores fijos para mancuernas/máquinas.
    base = None
    if any(k in name for k in ["sentadilla", "squat"]):
        base = 0.7 * bw
    elif any(k in name for k in ["peso muerto", "deadlift", "hip hinge"]):
        base = 0.9 * bw
    elif any(k in name for k in ["press banca", "bench", "press de banca"]):
        base = 0.6 * bw
    elif any(k in name for k in ["press militar", "overhead", "hombro barra"]):
        base = 0.35 * bw
    elif any(k in name for k in ["dominada", "pull-up", "chin-up"]):
        # Si es con lastre/ayuda es complejo; sugiere 0 (peso corporal)
        base = 0.0
    elif any(k in name for k in ["remo barra", "barbell row"]):
        base = 0.5 * bw
    elif any(k in name for k in ["remo mancuernas", "dumbbell row"]):
        base = 24  # par 12+12 aprox
    elif any(k in name for k in ["prensa", "leg press"]):
        base = 1.5 * bw
    elif any(k in name for k in ["extensión cuádriceps", "maquina cuadriceps"]):
        base = 25
    elif any(k in name for k in ["curl femoral", "leg curl"]):
        base = 25
    elif any(k in name for k in ["jalón", "lat pulldown"]):
        base = 35
    elif any(k in name for k in ["aperturas", "fly", "cruce", "crossover"]):
        base = 16
    elif any(k in name for k in ["biceps", "curl", "martillo"]):
        base = 16
    elif any(k in name for k in ["triceps", "press francés", "jalón triceps"]):
        base = 20
    else:
        base = 20  # valor seguro por defecto

    # Ajuste por reps objetivo (si el plan pone p.ej. 12 reps, baja algo la carga)
    reps = reps_obj or 8
    if reps >= 10: base *= 0.9
    if reps >= 12: base *= 0.85
    if reps <= 6:  base *= 1.05

    return _micro_round(base, micro_step)



@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Base de datos inicializada")


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def mostrar_login(request: Request):
    logger.info("GET /login solicitado")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"Intento de login: {username}")
    try:
        usuario = await crud.get_usuario_por_email(db, username)
        logger.info(f"Usuario encontrado: {usuario}")

        if not usuario:
            logger.warning("Usuario no encontrado")
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Credenciales incorrectas"}
            )

        if not pwd_context.verify(password, usuario.contraseña):
            logger.warning("Contraseña incorrecta")
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Credenciales incorrectas"}
            )

        # JWT token
        token_data = {
            "sub": usuario.email,
            "rol": usuario.rol
        }
        token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)

        # ¿El usuario ya tiene formulario?
        formulario = await crud.get_formulario_por_usuario(db, usuario.id)
        url_destino = "/seleccion-plan" if not formulario else "/usuarios"
        logger.info(f"Login exitoso. Redirigiendo a: {url_destino}")

        response = RedirectResponse(url=url_destino, status_code=303)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=1800,
            path="/",
            samesite="Lax",
            # domain="127.0.0.1",  # Solo si tienes problemas locales
        )
        logger.info("Cookie establecida correctamente")
        return response

    except Exception as e:
        logger.error("Excepción en login:")
        logger.error(traceback.format_exc())
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Error interno: " + str(e)}
        )


@app.get("/registro", response_class=HTMLResponse)
async def mostrar_registro(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})


@app.post("/registro")
async def registro(request: Request,
                   email: str = Form(...),
                   nombre: str = Form(...),
                   rol: str = Form(...),
                   password: str = Form(...),
                   confirm_password: str = Form(...),
                   db: AsyncSession = Depends(get_db)):
    if password != confirm_password:
        return templates.TemplateResponse("registro.html",
                                          {"request": request, "error": "Las contraseñas no coinciden"})

    usuario_existe = await crud.get_usuario_por_email(db, email)
    if usuario_existe:
        return templates.TemplateResponse("registro.html", {"request": request, "error": "Email ya registrado"})

    usuario_data = schemas.UsuarioCreate(email=email, nombre=nombre, contraseña=password, rol=rol)
    await crud.crear_usuario(db, usuario_data)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/usuarios", response_class=HTMLResponse)
async def leer_usuarios(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]
    logger.info(f"Acceso a /usuarios por: {user['email']}")

    # === Usuario para la plantilla (sidebar, avatar, etc.) ===
    usuario_obj = await db.get(models.Usuario, usuario_id)
    if not usuario_obj:
        usuario_obj = SimpleNamespace(nombre="Tu perfil", imagen_url=DEFAULT_AVATAR_REL)
    elif not getattr(usuario_obj, "imagen_url", None):
        setattr(usuario_obj, "imagen_url", DEFAULT_AVATAR_REL)

    # === Últimos dos progresos para KPIs ===
    res_hist = await db.execute(
        select(models.Progreso)
        .where(models.Progreso.usuario_id == usuario_id)
        .order_by(models.Progreso.fecha.desc())
        .limit(2)
    )
    ultimos = res_hist.scalars().all()
    cur, prev = (ultimos[0] if ultimos else None), (ultimos[1] if len(ultimos) > 1 else None)

    # Parse JSON
    curj = {}
    if cur:
        try: curj = json.loads(cur.progreso_detallado or "{}")
        except: curj = {}
    prevj = {}
    if prev:
        try: prevj = json.loads(prev.progreso_detallado or "{}")
        except: prevj = {}

    # Lectura de métricas actuales
    peso_cur   = _safe_float(curj.get("peso"))
    adher_cur  = _safe_float(curj.get("adherencia"))
    entren_cur = _safe_float(curj.get("entrenos_completados"))
    dias_cur   = _safe_float(curj.get("dias_activo"))

    # Valores anteriores
    peso_prev   = _safe_float(prevj.get("peso"))
    adher_prev  = _safe_float(prevj.get("adherencia"))
    entren_prev = _safe_float(prevj.get("entrenos_completados"))
    dias_prev   = _safe_float(prevj.get("dias_activo"))

    # Formulario/objetivo
    form_res = await db.execute(
        select(models.FormularioCliente).where(models.FormularioCliente.usuario_id == usuario_id)
    )
    form_cli = form_res.scalar_one_or_none()
    objetivos = []
    if form_cli:
        try:
            objetivos = form_cli.objetivos_entrenamiento if isinstance(form_cli.objetivos_entrenamiento, list) else [str(form_cli.objetivos_entrenamiento or "")]
        except:
            objetivos = []
    peso_goal = _goal_from_form(objetivos)

    # Deltas %
    delta_peso   = _pct_change(peso_cur,   peso_prev)
    delta_entren = _pct_change(entren_cur, entren_prev)
    delta_dias   = _pct_change(dias_cur,   dias_prev)

    # Adherencia
    if adher_cur is None:
        nums = [v for v in [entren_cur, dias_cur] if v is not None]
        adher_cur = round((sum(nums)/len(nums)), 1) if nums else None
    if adher_prev is None:
        nums = [v for v in [entren_prev, dias_prev] if v is not None]
        adher_prev = round((sum(nums)/len(nums)), 1) if nums else None
    delta_adher = _pct_change(adher_cur, adher_prev)

    # Reglas de tendencia
    peso_good_up   = True if peso_goal == "subir_peso" else False if peso_goal == "bajar_peso" else False
    entren_good_up = True
    dias_good_up   = True
    adher_good_up  = True

    cls_peso,   arrow_peso   = _trend_color_and_arrow(delta_peso,   peso_good_up)
    cls_entren, arrow_entren = _trend_color_and_arrow(delta_entren, entren_good_up)
    cls_dias,   arrow_dias   = _trend_color_and_arrow(delta_dias,   dias_good_up)
    cls_adher,  arrow_adher  = _trend_color_and_arrow(delta_adher,  adher_good_up)

    # Amigos
    result_amigos = await db.execute(
        select(models.Usuario)  # ojo: usa models.Usuario, no Usuario “pelado” si no lo importaste
        .join(models.Amistad, models.Usuario.id == models.Amistad.amigo_id)
        .where(models.Amistad.usuario_id_1 == usuario_id, models.Amistad.estado == "aceptado")
        .union(
            select(models.Usuario)
            .join(models.Amistad, models.Usuario.id == models.Amistad.usuario_id_1)
            .where(models.Amistad.usuario_id_2 == usuario_id, models.Amistad.estado == "aceptado")
        )
    )
    amigos = result_amigos.scalars().all()

    progreso_amigos = []
    for amigo in amigos:
        r = await db.execute(
            select(models.Progreso)
            .where(models.Progreso.usuario_id == amigo.id)
            .order_by(models.Progreso.fecha.desc())
            .limit(1)
        )
        prog = r.scalar_one_or_none()
        if prog:
            try:
                data = json.loads(prog.progreso_detallado or "{}")
                progreso_amigos.append({
                    "nombre": amigo.nombre,
                    "peso": data.get("peso", "N/A"),
                    "adherencia": data.get("adherencia", "N/A"),
                    "entrenos_completados": data.get("entrenos_completados", "N/A"),
                    "dias_activo": data.get("dias_activo", "N/A")
                })
            except Exception as e:
                logger.warning(f"Error leyendo progreso amigo {getattr(amigo, 'email', '?')}: {e}")

    # Gimnasio principal
    result_gym = await db.execute(
        select(models.Gimnasio)
        .join(models.UsuarioGimnasio, models.UsuarioGimnasio.gimnasio_id == models.Gimnasio.id)
        .where(
            models.UsuarioGimnasio.usuario_id == usuario_id,
            models.UsuarioGimnasio.es_principal == True
        )
    )
    gimnasio_principal = result_gym.scalar_one_or_none()

    # Último plan
    result_plan = await db.execute(
        select(models.Plan)
        .where(models.Plan.usuario_id == usuario_id)
        .order_by(models.Plan.fecha_creacion.desc())
        .limit(1)
    )
    plan = result_plan.scalar_one_or_none()

    # —— Render ——
    return templates.TemplateResponse("usuarios.html", {
        "request": request,

        # KPIs actuales
        "peso": peso_cur or 0,
        "entrenos": int(entren_cur) if entren_cur is not None else 0,
        "dias": int(dias_cur) if dias_cur is not None else 0,
        "adherencia": adher_cur or 0,

        # Deltas y estilos
        "delta_peso": delta_peso,
        "delta_entren": delta_entren,
        "delta_dias": delta_dias,
        "delta_adher": delta_adher,

        "cls_peso": cls_peso, "arrow_peso": arrow_peso,
        "cls_entren": cls_entren, "arrow_entren": arrow_entren,
        "cls_dias": cls_dias, "arrow_dias": arrow_dias,
        "cls_adher": cls_adher, "arrow_adher": arrow_adher,

        # Contexto adicional
        "peso_goal": peso_goal,
        "progreso_amigos": progreso_amigos,
        "gimnasio_principal": gimnasio_principal,
        "plan": plan,

        # Sidebar
        "usuario": usuario_obj,
        "DEFAULT_AVATAR_REL": DEFAULT_AVATAR_REL,
    })


@app.get("/panel-entrenador", response_class=HTMLResponse)
async def panel_entrenador(request: Request, user=Depends(role_required(["entrenador"]))):
    logger.info(f"Acceso a /panel-entrenador por: {user['email']}")
    return templates.TemplateResponse("entrenador_panel.html", {"request": request, "user": user})


@app.get("/formulario-entreno", response_class=HTMLResponse)
async def mostrar_formulario_entreno(request: Request, user=Depends(role_required(["cliente"])), db: AsyncSession = Depends(get_db)):
    formulario = await crud.get_formulario_por_usuario(db, user["id"])
    datos = formulario.__dict__ if formulario else {}
    return templates.TemplateResponse("formulario_entreno.html", {"request": request, "datos": datos})


@app.post("/formulario-entreno")
async def procesar_formulario_entreno(
    request: Request,
    altura: int = Form(...),
    edad: int = Form(...),
    sexo: str = Form(...),
    nivel_experiencia: str = Form(...),
    tiempo_entrenamiento: int = Form(...),
    preferencias: list[str] = Form(...),
    objetivos: list[str] = Form(...),
    nombre_deporte: str = Form(None),
    aspectos_a_mejorar: str = Form(None),
    semanas: int = Form(...),  # <-- Asegúrate de pedir esto en tu formulario
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db)
):
    # 1. Guardar formulario
    form_data = schemas.FormularioClienteCreate(
        altura_cm=altura,
        edad=edad,
        experiencia_entrenamiento=nivel_experiencia,
        tiempo_disponible=str(tiempo_entrenamiento),
        sexo=sexo,
        preferencias_entrenamiento=preferencias,
        objetivos_entrenamiento=objetivos,
        deporte_especifico=nombre_deporte,
        aspectos_mejorar=aspectos_a_mejorar,
        semanas=semanas
    )
    await crud.crear_o_actualizar_formulario(db, user["id"], form_data)

    # 2. Equipamiento del gimnasio (si el usuario está afiliado a uno principal)
    result_gym = await db.execute(
        select(models.Gimnasio)
        .join(models.UsuarioGimnasio, models.UsuarioGimnasio.gimnasio_id == models.Gimnasio.id)
        .where(
            models.UsuarioGimnasio.usuario_id == user["id"],
            models.UsuarioGimnasio.es_principal == True
        )
    )
    gimnasio = result_gym.scalar_one_or_none()
    equipamiento = ""
    if gimnasio:
        res_maquinas = await db.execute(
            select(models.InfraestructuraGimnasio)
            .where(models.InfraestructuraGimnasio.gimnasio_id == gimnasio.id)
        )
        maquinas = res_maquinas.scalars().all()
        equipamiento = ", ".join([m.nombre_maquina for m in maquinas])

    # 3. Llama a OpenAI para generar rutina personalizada
    rutina = await generar_rutina_ia(form_data.__dict__, equipamiento, "", "")

    # 4. Añade imágenes IA a cada ejercicio (iterar sobre rutina['plan'])
    for semana in rutina["plan"]:
        for dia in semana["dias"]:
            for ejercicio in dia["ejercicios"]:
                nombre = ejercicio["nombre"]
                motivo = ejercicio.get("motivo", "")
                # 1. Genera la URL temporal de IA (como antes)
                url_temporal = await generar_imagen_ejercicio(nombre, motivo)
                # 2. Descarga la imagen en tu servidor/local (¡nuevo paso!)
                import uuid
                nombre_archivo = f"ia_{nombre.replace(' ', '_').lower()}_{uuid.uuid4().hex}.png"
                url_local = await descargar_imagen_ia(url_temporal, nombre_archivo)
                # 3. Guarda la ruta local en el JSON (si la descarga falla, guarda la temporal)
                ejercicio["imagen_url"] = url_local if url_local else url_temporal
    # 5. Guarda la rutina (JSON con imágenes) en la base de datos (si tienes modelo Plan o similar)
    # Ejemplo:
    rutina_obj = models.Rutina(
        usuario_id=user["id"],
        nombre="Rutina personalizada",
        descripcion="Rutina generada por IA según tus preferencias",
        rutina_json=rutina,  # Si tu columna es tipo JSON, NO uses dumps aquí.
        semanas=form_data.semanas,
        fecha_creacion=datetime.now(),
    )
    db.add(rutina_obj)
    await db.commit()
    await db.refresh(rutina_obj)

    # 6. Muestra la rutina
    return RedirectResponse(url="/usuarios", status_code=302)

    # O simplemente redirigir:
    # return RedirectResponse(url="/usuarios", status_code=302)

@app.post("/formulario")
async def guardar_formulario(
        form_data: FormularioClienteCreate,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(role_required(["cliente"]))
):
    logger.info(f"Guardando formulario para: {current_user['email']}")
    await crear_o_actualizar_formulario(db, current_user["id"], form_data)
    return {"mensaje": "Formulario guardado correctamente"}


@app.post("/mi-entreno/registrar-progreso")
async def registrar_progreso_entreno(
    semana: int = Form(...),
    dia: str = Form(...),
    rutina_id: int = Form(...),
    ejercicios: str = Form(...),  # JSON string [{"nombre":..., "peso":..., "repes":...}, ...]
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]
    datos_ejercicios = json.loads(ejercicios)
    detalle = {
        "semana": semana,
        "dia": dia,
        "ejercicios": datos_ejercicios,
        "fecha": str(datetime.now().date())
    }

    # Llama a la IA para obtener sugerencias para el próximo día (opcional pero útil)
    try:
        sugerencias = await ajustar_rutina_ia(detalle)
        detalle["sugerencias"] = sugerencias
    except Exception as e:
        detalle["sugerencias"] = []
        print("Error IA sugerencias:", e)

    progreso = models.Progreso(
        usuario_id=usuario_id,
        plan_id=rutina_id,
        fecha=datetime.now(),
        progreso_detallado=json.dumps(detalle)
    )
    db.add(progreso)
    await db.commit()
    return JSONResponse({"msg": "Progreso registrado correctamente", "detalle": detalle})

# --- LISTADO: /mis-entrenos ---
# --- LISTADO: /mis-entrenos ---
@app.get("/mis-entrenos", response_class=HTMLResponse)
async def ver_mis_rutinas(
    request: Request,
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db),
):
    usuario_id = user["id"]
    res = await db.execute(
        select(models.Rutina)
        .where(models.Rutina.usuario_id == usuario_id)
        .order_by(models.Rutina.fecha_creacion.desc())
    )
    rutinas = res.scalars().all()
    return templates.TemplateResponse("mis_entrenos_lista.html", {
        "request": request,
        "rutinas": rutinas,
    })


# --- CALENDARIO: /mis-entrenos/{rutina_id} ---
# --- CALENDARIO: /mis-entrenos/{rutina_id} ---
@app.get("/mis-entrenos/{rutina_id}", response_class=HTMLResponse)
async def ver_calendario_rutina(
    request: Request,
    rutina_id: int,
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db),
):
    rutina = await db.get(models.Rutina, rutina_id)
    if not rutina or rutina.usuario_id != user["id"]:
        return RedirectResponse(url="/mis-entrenos", status_code=303)

    plan = rutina.rutina_json or {}
    semanas = plan.get("plan", [])  # [{ "semana": 1, "dias": [ { "dia": "Lunes", "descanso": false, "tipo": "...", "ejercicios":[...] }, ... ] }, ...]

    orden_semana = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]

    # Normaliza cada semana a exactamente 7 celdas en orden L->D
    calendario = []  # lista de semanas; cada semana es lista de 7 dicts {dia, descanso, tipo, ejercicios}
    for w in semanas:
        mapa = { (d.get("dia") or "").strip().lower(): d for d in w.get("dias", []) }
        fila = []
        for nombre in orden_semana:
            d = mapa.get(nombre.lower())
            if not d:
                d = {"dia": nombre, "descanso": True, "tipo": "Descanso", "ejercicios": []}
            else:
                d.setdefault("tipo", "Entrenamiento")
                d.setdefault("ejercicios", [])
                d.setdefault("descanso", False)
                d.setdefault("dia", nombre)
            fila.append(d)
        calendario.append({"semana": w.get("semana", len(calendario)+1), "dias": fila})

    return templates.TemplateResponse("mis_entrenos_calendario.html", {
        "request": request,
        "rutina": rutina,
        "calendario": calendario,      # [{semana, dias:[...,7]}]
        "orden_semana": orden_semana,  # por si lo necesitas en el template
    })



# --- DÍA: /mis-entrenos/{rutina_id}/dia/{dia} ---
@app.get("/mis-entrenos/{rutina_id}/dia/{dia}", response_class=HTMLResponse)
async def ver_dia_entreno(
    request: Request,
    rutina_id: int,
    dia: str,  # "Lunes", "Martes", etc.
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db),
):
    rutina = await db.get(models.Rutina, rutina_id)
    if not rutina or rutina.usuario_id != user["id"]:
        return RedirectResponse(url="/mis-entrenos", status_code=303)

    ejercicios = []
    try:
        plan = rutina.rutina_json or {}
        semanas = plan.get("plan", [])
        dias = (semanas[0].get("dias", []) if semanas else [])
        for d in dias:
            if str(d.get("dia")).lower() == dia.lower() and not d.get("descanso", False):
                ejercicios = d.get("ejercicios", [])
                break
    except Exception:
        ejercicios = []
    for ej in ejercicios:
        try:
            ej["sugerido"] = await sugerencia_inicial(
                db, user["id"], ej.get("nombre", ""),
                ej.get("repeticiones") or ej.get("reps")
            )

            url_val = ej.get("imagen_url") or ""
            if not isinstance(url_val, str):
                ej["imagen_url"] = ""
                continue
            url_val = url_val.strip()
            if url_val.startswith(("http://", "https://")) and not url_val.startswith("/static/"):
                ej["imagen_url"] = ""
        # fuerza "Sin imagen" y evita 403 por expiración

        except Exception:
            ej["sugerido"] = None
    return templates.TemplateResponse("mis_entrenos_dia.html", {
        "request": request,
        "rutina": rutina,
        "dia": dia,
        "ejercicios": ejercicios,
    })

# Alias a tu sugerencia existente
@app.get("/api/sugerencia-carga")
async def api_sugerencia_carga(
    ejercicio: str,
    micro_step: float = 2.5,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    sets = await _ultimos_sets_usuario(db, user["id"], ejercicio)
    load, note = _sugerir_carga_desde_sets(sets, micro_step=micro_step)
    return {"exercise": ejercicio, "suggested_load": load, "note": note, "samples": sets[:3]}

# Guardar sesión desde la nueva UI (alias al tuyo si quieres)
@app.post("/api/guardar-sesion")
async def api_guardar_sesion(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    try:
        detalle = {
            "semana_dia": payload.get("dia"),
            "ejercicios": payload.get("items", []),
            # nuevos campos opcionales:
            "timing": payload.get("timing", {}),
            "rest_log": payload.get("restLog", []),
            "exercises": payload.get("exercises", []),
            "fecha": datetime.utcnow().isoformat()
        }
        prog = models.Progreso(
            usuario_id=user["id"],
            plan_id=payload["rutina_id"],
            fecha=datetime.utcnow().date(),
            progreso_detallado=json.dumps(detalle)
        )
        db.add(prog)
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, detail=str(e))


# Cambiar ejercicio (placeholder IA)
@app.post("/api/cambiar-ejercicio")
async def api_cambiar_ejercicio(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    actual = (payload.get("actual") or "").strip()
    grupo  = (payload.get("grupo")  or "").strip()
    criterio = (payload.get("criterio") or "movilidad").strip()

    if not actual:
        raise HTTPException(400, "Falta 'actual'")

    try:
        lista = await generar_alternativas_ia(actual, grupo)  # usa utils
        # acepta tanto lista de strings como objetos con "nombre"
        candidatos = []
        for x in lista:
            if isinstance(x, str):
                candidatos.append(x)
            elif isinstance(x, dict) and x.get("nombre"):
                candidatos.append(x["nombre"])
        nuevo = next((n for n in candidatos if n.lower() != actual.lower()), None)
        if not nuevo:
            # fallback suave por si la IA no trae nada usable
            fallback = {"Pectoral": ["Press Mancuernas Plano","Press Inclinado Barra","Fondos en Paralelas","Máquina Press Pecho"]}
            nuevo = next((e for e in fallback.get(grupo, []) if e.lower() != actual.lower()), actual)
        return {"nuevo_ejercicio": nuevo}
    except Exception:
        return {"nuevo_ejercicio": actual}


@app.get("/mis-dietas", response_class=HTMLResponse)
async def ver_mis_dietas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]

    # Usuario para el sidebar (con avatar por defecto)
    usuario_obj = await db.get(models.Usuario, usuario_id)
    DEFAULT_AVATAR_REL = "uploads/2571eb2a-583a-490b-aa0d-c2ca737e290f.png"
    if not usuario_obj:
        from types import SimpleNamespace
        usuario_obj = SimpleNamespace(nombre="Tu perfil", imagen_url=DEFAULT_AVATAR_REL)
    elif not getattr(usuario_obj, "imagen_url", None):
        setattr(usuario_obj, "imagen_url", DEFAULT_AVATAR_REL)

    # Dietas del usuario (usa tu modelo real; aquí muestro Plan.tipo='dieta')
    res = await db.execute(
        select(models.Plan)
        .where(models.Plan.usuario_id == usuario_id, models.Plan.tipo == "dieta")
        .order_by(models.Plan.fecha_creacion.desc())
    )
    dietas = res.scalars().all()

    ctx = {
        "request": request,
        "usuario": usuario_obj,
        "DEFAULT_AVATAR_REL": DEFAULT_AVATAR_REL,
    }

    if not dietas:
        # Fallback cuando el usuario no tiene dietas
        return templates.TemplateResponse("sin_dietas.html", ctx)

    ctx["dietas"] = dietas
    return templates.TemplateResponse("mis_dietas_lista.html", ctx)

@app.post("/registrar-progreso", response_class=HTMLResponse)
async def registrar_progreso(
        request: Request,
        plan_id: int = Form(...),
        peso: float = Form(...),
        adherencia: int = Form(...),
        entrenos_completados: int = Form(...),
        dias_activo: int = Form(...),
        db: AsyncSession = Depends(get_db),
        user=Depends(role_required(["cliente"]))
):
    logger.info(f"Registrando progreso para: {user['email']}")
    progreso_data = {
        "peso": peso,
        "adherencia": adherencia,
        "entrenos_completados": entrenos_completados,
        "dias_activo": dias_activo
    }
    progreso_json = json.dumps(progreso_data)

    result = await db.execute(
        select(models.Progreso).where(
            models.Progreso.usuario_id == user["id"],
            models.Progreso.fecha == date.today()
        )
    )
    progreso = result.scalar_one_or_none()

    if progreso:
        progreso.progreso_detallado = progreso_json
    else:
        nuevo_progreso = models.Progreso(
            usuario_id=user["id"],
            fecha=date.today(),
            progreso_detallado=progreso_json
        )
        db.add(nuevo_progreso)

    await db.commit()
    logger.info("Progreso registrado exitosamente")
    return RedirectResponse(url="/usuarios", status_code=302)


@app.post("/upload-comida")
async def upload_comida(
        file: UploadFile = File(...),
        descripcion: str = Form(...),
        db: AsyncSession = Depends(get_db),
        user=Depends(role_required(["cliente"]))
):
    logger.info(f"Subiendo comida por: {user['email']}")
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    registro_comida = RegistroComida(
        usuario_id=user["id"],
        imagen_url=f"/static/uploads/{filename}",
        descripcion=descripcion,
        fecha=datetime.now()
    )
    db.add(registro_comida)
    await db.commit()
    logger.info("Comida subida exitosamente")
    return {"mensaje": "Comida subida correctamente"}

@app.get("/seleccion-plan", response_class=HTMLResponse)
async def seleccion_plan(request: Request):
    return templates.TemplateResponse("seleccion_plan.html", {"request": request})

@app.post("/seleccion-plan")
async def procesar_seleccion_plan(
    opcion: str = Form(...),
):
    if opcion == "entreno":
        return RedirectResponse("/formulario-entreno", status_code=302)
    elif opcion == "dieta":
        return RedirectResponse("/formulario-dieta", status_code=302)
    elif opcion == "mixto":
        return RedirectResponse("/formulario-mixto", status_code=302)
    else:
        raise HTTPException(status_code=400, detail="Opción no válida")

@app.get("/formulario-dieta", response_class=HTMLResponse)
async def mostrar_formulario_dieta(request: Request, user=Depends(role_required(["cliente"])), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FormularioDieta).where(FormularioDieta.usuario_id == user["id"]))
    formulario = result.scalar_one_or_none()
    datos = formulario.__dict__ if formulario else {}
    return templates.TemplateResponse("formulario_dieta.html", {"request": request, "datos": datos})

from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import PlainTextResponse

@router.post("/formulario-dieta", response_class=HTMLResponse)
async def procesar_formulario_dieta(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    content_type = request.headers.get("content-type", "")
    data: dict

    # --- 1) Parseo robusto de form/JSON ---
    if "application/json" in content_type:
        data = await request.json()
        data.setdefault("preferencias_alimentarias", [])
        data.setdefault("objetivos", [])
    else:
        form = await request.form()
        data = dict(form)
        data["preferencias_alimentarias"] = form.getlist("preferencias_alimentarias")
        data["objetivos"] = form.getlist("objetivos")

    # alias (front manda 'semanas', schema usa 'duracion_dieta')
    if "duracion_dieta" not in data and "semanas" in data:
        data["duracion_dieta"] = data["semanas"]

    # defaults
    data.setdefault("calorias_objetivo", 2000)
    data.setdefault("duracion_dieta", 12)

    # --- 2) Validación Pydantic ---
    try:
        payload = schemas.FormularioDietaCreate(**data)
    except ValidationError as e:
        # Re-pinta el formulario mostrando errores
        return templates.TemplateResponse(
            "formulario_dieta.html",
            {"request": request, "errores": e.errors(), "datos": data},
            status_code=422,
        )

    # --- 3) Guardar el FORM en formularios_dieta ---
    form_row = models.FormularioDieta(
        usuario_id=user["id"],
        altura=payload.altura,
        edad=payload.edad,
        sexo=payload.sexo,
        semanas=payload.duracion_dieta,                 # columna real en DB
        objetivos=payload.objetivos,                    # texto/array según tu modelo
        tipo_dieta=payload.tipo_dieta,
        alergias=payload.alergias,
        alimentos_no_deseados=payload.alimentos_no_deseados,
        tiempo_comidas=payload.tiempo_comidas,
        comidas_al_dia=payload.comidas_al_dia,
        calorias_objetivo=payload.calorias_objetivo,    # existe en tu tabla
        preferencias_alimentarias=payload.preferencias_alimentarias,
    )
    db.add(form_row)
    await db.commit()
    await db.refresh(form_row)

    # --- 4) Crear el PLAN visible en /mis-dietas ---
    # SUGERENCIA: añade una FK opcional en Plan: formulario_dieta_id (nullable)
    plan = models.Plan(
        usuario_id=user["id"],
        nombre=f"Dieta creada desde formulario",
        descripcion="Creada desde el formulario de dieta",
        tipo="dieta",
        creado_por=user["id"],# <- CLAVE para que /mis-dietas la liste
        rutina_json=None,                  # o un JSON mínimo si quieres
        formulario_dieta_id=form_row.id, # si añadiste la FK (recomendado)
                      # si existe el campo en tu modelo
    )
    db.add(plan)
    await db.commit()
    # await db.refresh(plan)  # opcional

    # --- 5) Redirige a Mis dietas ---
    return RedirectResponse(url="/mis-dietas", status_code=303)

@app.get("/formulario-mixto", response_class=HTMLResponse)
async def mostrar_formulario_mixto(request: Request, user=Depends(role_required(["cliente"])), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FormularioMixto).where(FormularioMixto.usuario_id == user["id"]))
    formulario = result.scalar_one_or_none()
    datos = formulario.__dict__ if formulario else {}
    return templates.TemplateResponse("formulario_mixto.html", {"request": request, "datos": datos})

@router.post("/formulario_mixto")
async def formulario_mixto_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    edad: int = Form(...),
    sexo: str = Form(...),
    altura_cm: int = Form(...),
    peso: float = Form(...),
    experiencia_entrenamiento: str = Form(...),
    actividad_fisica: str = Form(...),
    tiempo_disponible: str = Form(...),
    preferencias_entrenamiento: str = Form(...),
    objetivos_entrenamiento: str = Form(...),
    tipo_dieta: str = Form(...),
    objetivos_dieta: str = Form(...),
    alergias: str = Form(...),
    alimentos_no_deseados: str = Form(...),
    comidas_al_dia: int = Form(...),
    deporte_especifico: str = Form(""),
    equipamiento: str = Form(""),
    limitaciones: str = Form(""),
    otros_datos: str = Form(""),
    duracion_mixta: str = Form(...),
):
    form_data = {
        "edad": edad,
        "sexo": sexo,
        "altura_cm": altura_cm,
        "peso": peso,
        "experiencia_entrenamiento": experiencia_entrenamiento,
        "actividad_fisica": actividad_fisica,
        "tiempo_disponible": tiempo_disponible,
        "preferencias_entrenamiento": [s.strip() for s in preferencias_entrenamiento.split(",")],
        "objetivos_entrenamiento": [s.strip() for s in objetivos_entrenamiento.split(",")],
        "tipo_dieta": tipo_dieta,
        "objetivos_dieta": [s.strip() for s in objetivos_dieta.split(",")],
        "alergias": alergias,
        "alimentos_no_deseados": alimentos_no_deseados,
        "comidas_al_dia": comidas_al_dia,
        "deporte_especifico": deporte_especifico,
        "equipamiento": equipamiento,
        "limitaciones": limitaciones,
        "duracion_mixta": duracion_mixta,
    }

    prompt = construir_prompt_mixto(form_data, otros_datos)
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    contenido_json = json.loads(response.choices[0].message.content)

    # Separar entreno y dieta
    rutina_json = contenido_json.get("entrenamiento", {})
    dieta_json = contenido_json.get("dieta", {})

    # Guardar rutina
    rutina = models.Rutina(
        usuario_id=current_user.id,
        nombre="Rutina Mixta IA",
        descripcion="Entrenamiento generado por IA desde formulario mixto",
        rutina_json=rutina_json,
        semanas=int(duracion_mixta),
        fecha_creacion=datetime.now(),
    )
    db.add(rutina)

    # Guardar dieta
    dieta = models.Dieta(
        usuario_id=current_user.id,
        nombre="Dieta Mixta IA",
        descripcion="Dieta generada por IA desde formulario mixto",
        dieta_json=dieta_json,
        semanas=int(duracion_mixta),
        fecha_creacion=datetime.now(),
    )
    db.add(dieta)

    await db.commit()

    return RedirectResponse(url="/usuarios", status_code=302)

@router.get("/gimnasios", response_class=HTMLResponse)
async def listar_gimnasios(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Gimnasio))
    gimnasios = result.scalars().all()
    return templates.TemplateResponse("gimnasios.html", {"request": request, "gimnasios": gimnasios})

@router.post("/gimnasios/unirse")
async def unirse_a_gimnasio(
    gimnasio_id: int = Form(...),
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db)
):
    usuario_id = user["id"]
    existe = await db.execute(
        select(UsuarioGimnasio).where(
            UsuarioGimnasio.usuario_id == usuario_id,
            UsuarioGimnasio.gimnasio_id == gimnasio_id
        )
    )
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ya estás inscrito en este gimnasio")

    nueva_union = UsuarioGimnasio(usuario_id=usuario_id, gimnasio_id=gimnasio_id)
    db.add(nueva_union)
    await db.commit()
    return {"mensaje": "Unido correctamente"}

@app.get("/profesionales", response_class=HTMLResponse)
async def listar_profesionales(
    request: Request,
    tipo: str,  # "entrenador" o "dietista"
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db)
):
    if tipo not in ["entrenador", "dietista"]:
        raise HTTPException(status_code=400, detail="Tipo de profesional no válido")

    result = await db.execute(
        select(Usuario).where(Usuario.rol == tipo)
    )
    profesionales = result.scalars().all()

    return templates.TemplateResponse("profesionales.html", {
        "request": request,
        "profesionales": profesionales,
        "tipo": tipo.capitalize()
    })

@app.post("/profesionales/unirse")
async def unirse_a_profesional(
    profesional_id: int = Form(...),
    tipo: str = Form(...),  # "entrenador" o "dietista"
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    if tipo not in ["entrenador", "dietista"]:
        raise HTTPException(status_code=400, detail="Tipo de profesional no válido")

    result = await db.execute(select(Usuario).where(Usuario.id == profesional_id))
    profesional = result.scalar_one_or_none()

    if not profesional or profesional.rol != tipo:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")

    # Aquí se asume que tienes una tabla llamada UsuarioProfesional con usuario_id, profesional_id, tipo
    nuevo_registro = models.UsuarioProfesional(
        usuario_id=user["id"],
        profesional_id=profesional_id,
        tipo=tipo,
        aceptado=True  # Puedes poner False si quieres agregar lógica de moderación más adelante
    )
    db.add(nuevo_registro)
    await db.commit()

    return {"mensaje": f"Te has unido a {tipo} correctamente"}

@app.get("/explorar", response_class=HTMLResponse)
async def explorar(
    request: Request,
    seccion: str = "gimnasios",
    q: str = "",
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db)
):
    resultados = []

    if seccion == "gimnasios":
        result = await db.execute(select(models.Gimnasio))
        resultados = result.scalars().all()

    elif seccion == "profesionales":
        result = await db.execute(
            select(Usuario).where(Usuario.rol.in_(["entrenador", "dietista"]))
        )
        resultados = result.scalars().all()

    elif seccion == "amigos":
        stmt = select(Usuario).where(
            Usuario.rol == "cliente",
            Usuario.id != user["id"]
        )
        if q:
            stmt = stmt.where(Usuario.nombre.ilike(f"%{q}%") | Usuario.email.ilike(f"%{q}%"))

        result = await db.execute(stmt)
        resultados = result.scalars().all()

    return templates.TemplateResponse("explorar.html", {
        "request": request,
        "seccion": seccion,
        "resultados": resultados
    })

@app.post("/unirse-gimnasio")
async def unirse_gimnasio(
    gimnasio_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    existe = await db.execute(
        select(models.UsuarioGimnasio).where(
            models.UsuarioGimnasio.usuario_id == user["id"],
            models.UsuarioGimnasio.gimnasio_id == gimnasio_id
        )
    )
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ya estás inscrito en este gimnasio")

    nueva_union = models.UsuarioGimnasio(
        usuario_id=user["id"],
        gimnasio_id=gimnasio_id
    )
    db.add(nueva_union)
    await db.commit()
    return RedirectResponse(url="/explorar?seccion=gimnasios", status_code=302)

@app.post("/amigos/agregar")
async def agregar_amigo(
    amigo_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    # Verifica si ya hay amistad en cualquier dirección
    ya_son_amigos = await db.execute(
        select(models.Amistad).where(
            ((models.Amistad.usuario_id == user["id"]) & (models.Amistad.amigo_id == amigo_id)) |
            ((models.Amistad.usuario_id == amigo_id) & (models.Amistad.amigo_id == user["id"]))
        )
    )
    if ya_son_amigos.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ya hay una amistad o solicitud pendiente")

    solicitud = models.Amistad(
        usuario_id=user["id"],
        amigo_id=amigo_id,
        estado="pendiente"
    )
    db.add(solicitud)
    await db.commit()
    return RedirectResponse(url="/explorar?seccion=amigos", status_code=302)

@app.get("/amistades", response_class=HTMLResponse)
async def ver_solicitudes_amistad(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    result = await db.execute(
        select(models.Amistad)
        .where(models.Amistad.amigo_id == user["id"])
        .where(models.Amistad.estado == "pendiente")
        .join(models.Usuario, models.Amistad.usuario_id == models.Usuario.id)
    )
    solicitudes = result.scalars().all()
    return templates.TemplateResponse("amistades.html", {
        "request": request,
        "solicitudes": solicitudes,
        "usuario_id": user["id"]
    })

@app.post("/amistades/aceptar")
async def aceptar_amistad(
    solicitud_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    result = await db.execute(
        select(models.Amistad)
        .where(models.Amistad.id == solicitud_id)
        .where(models.Amistad.amigo_id == user["id"])
    )
    solicitud = result.scalar_one_or_none()

    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "aceptado"
    await db.commit()
    return RedirectResponse(url="/amistades", status_code=302)

@app.get("/amigos", response_class=HTMLResponse)
async def ver_amigos(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    uid = user["id"]

    result = await db.execute(
        select(models.Amistad)
        .where(models.Amistad.estado == "aceptado")
        .where((models.Amistad.usuario_id == uid) | (models.Amistad.amigo_id == uid))
    )
    amistades = result.scalars().all()

    amigos_info = []

    for amistad in amistades:
        amigo_id = amistad.amigo_id if amistad.usuario_id == uid else amistad.usuario_id
        usuario_amigo = await db.get(models.Usuario, amigo_id)

        # Buscar último progreso
        progreso_result = await db.execute(
            select(models.Progreso)
            .where(models.Progreso.usuario_id == amigo_id)
            .order_by(models.Progreso.fecha.desc())
            .limit(1)
        )
        progreso = progreso_result.scalar_one_or_none()

        datos = {}
        if progreso:
            try:
                progreso_data = json.loads(progreso.progreso_detallado)
                datos = {
                    "peso": progreso_data.get("peso"),
                    "adherencia": progreso_data.get("adherencia"),
                    "entrenos": progreso_data.get("entrenos_completados"),
                    "dias": progreso_data.get("dias_activo")
                }
            except:
                datos = {}

        amigos_info.append({
            "nombre": usuario_amigo.nombre,
            "email": usuario_amigo.email,
            "progreso": datos
        })

    return templates.TemplateResponse("amigos.html", {
        "request": request,
        "amigos": amigos_info
    })

@app.get("/mi-gimnasio", response_class=HTMLResponse)
async def mi_gimnasio(request: Request, user=Depends(role_required(["cliente"])), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Gimnasio)
        .join(UsuarioGimnasio)
        .where(UsuarioGimnasio.usuario_id == user["id"], UsuarioGimnasio.es_principal == True)
    )
    gimnasio = result.scalar_one_or_none()
    if not gimnasio:
        return templates.TemplateResponse("sin_gimnasio_principal.html", {"request": request})
    return templates.TemplateResponse("gimnasio_principal.html", {"request": request, "gimnasio": gimnasio})

@app.get("/mis-gimnasios", response_class=HTMLResponse)
async def mis_gimnasios(request: Request, user=Depends(role_required(["cliente"])), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Gimnasio, UsuarioGimnasio.es_principal)
        .join(UsuarioGimnasio)
        .where(UsuarioGimnasio.usuario_id == user["id"])
    )
    gimnasios = result.all()
    return templates.TemplateResponse("mis_gimnasios.html", {"request": request, "gimnasios": gimnasios})

@app.post("/gimnasio/marcar-principal")
async def marcar_principal(
    gimnasio_id: int = Form(...),
    user=Depends(role_required(["cliente"])),
    db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(UsuarioGimnasio)
        .where(UsuarioGimnasio.usuario_id == user["id"])
        .values(es_principal=False)
    )
    await db.execute(
        update(UsuarioGimnasio)
        .where(UsuarioGimnasio.usuario_id == user["id"], UsuarioGimnasio.gimnasio_id == gimnasio_id)
        .values(es_principal=True)
    )
    await db.commit()
    return RedirectResponse("/mi-gimnasio", status_code=302)

@app.post("/gimnasio/infraestructura/upload")
async def subir_infraestructura(
    nombre_maquina: str = Form(...),
    modelo: str = Form(None),
    imagen: UploadFile = File(None),
    user=Depends(role_required(["gimnasio"])),
    db: AsyncSession = Depends(get_db)
):
    gimnasio_id = user["id"]
    imagen_url = None

    if imagen:
        filename = f"{datetime.now().timestamp()}_{imagen.filename}"
        filepath = UPLOAD_DIR / filename
        with open(filepath, "wb") as f:
            shutil.copyfileobj(imagen.file, f)
        imagen_url = f"/static/uploads/{filename}"

    # Si no hay imagen, usar IA para generar imagen del modelo
    if not imagen_url and modelo:
        # IA pendiente de implementar
        imagen_url = f"/static/ia_generada/{modelo.replace(' ', '_')}.png"

    nueva = InfraestructuraGimnasio(
        gimnasio_id=gimnasio_id,
        nombre_maquina=nombre_maquina,
        modelo=modelo,
        imagen_url=imagen_url,
        fecha_subida=datetime.now()
    )
    db.add(nueva)
    await db.commit()
    return {"msg": "Infraestructura añadida correctamente"}

@app.get("/gimnasio/{gimnasio_id}", response_class=HTMLResponse)
async def ver_gimnasio(request: Request, gimnasio_id: int, db: AsyncSession = Depends(get_db)):
    gimnasio = await db.get(models.Usuario, gimnasio_id)
    if not gimnasio or gimnasio.rol != "gimnasio":
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")

    result = await db.execute(
        select(InfraestructuraGimnasio).where(InfraestructuraGimnasio.gimnasio_id == gimnasio_id)
    )
    maquinas = result.scalars().all()

    return templates.TemplateResponse("gimnasio_usuario.html", {
        "request": request,
        "gimnasio": gimnasio,
        "maquinas": maquinas
    })

@router.post("/generar_dieta", response_class=HTMLResponse)
async def generar_dieta(
    request: Request,
    edad: int = Form(...),
    sexo: str = Form(...),
    altura: int = Form(...),
    peso: int = Form(...),
    objetivos: str = Form(...),
    actividad_fisica: str = Form(...),
    experiencia_dietas: str = Form(...),
    tipo_dieta: str = Form(None),
    preferencias_alimentarias: str = Form(None),
    alergias: str = Form(None),
    alimentos_no_deseados: str = Form(None),
    comidas_al_dia: int = Form(...),
    tiempo_comidas: str = Form(None),
    otros_datos: str = Form(None),
    duracion_dieta: str = Form(...),
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user)
):
    # 1. Prepara el prompt (pon el texto largo de arriba aquí, formateado con los datos)
    prompt = f"""Eres un nutricionista clínico experto, especializado en crear dietas totalmente personalizadas, variadas y basadas en evidencia científica para mejorar la salud y el rendimiento de cada usuario. Genera un plan de alimentación detallado y adaptado para el siguiente usuario:

    **Datos del usuario:**
    - Edad: {edad}
    - Sexo: {sexo}
    - Altura: {altura} cm
    - Peso: {peso} kg
    - Objetivos principales: {objetivos}
    - Nivel de actividad física: {actividad_fisica}
    - Experiencia previa con dietas: {experiencia_dietas}
    - Tipo de dieta preferida: {tipo_dieta}
    - Preferencias alimentarias: {preferencias_alimentarias}
    - Alergias o intolerancias: {alergias}
    - Alimentos que no desea incluir: {alimentos_no_deseados}
    - Número de comidas al día: {comidas_al_dia}
    - Momentos preferidos para comer: {tiempo_comidas}
    - Contexto adicional: {otros_datos}
    - Duración total de la dieta: {duracion_dieta}

    [INCLUYE AQUÍ EL RESTO DEL PROMPT, VARIEDAD, REQUISITOS Y FORMATO JSON]
    """

    # 2. Llama a OpenAI
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Responde siempre solo con el JSON solicitado, nunca añadas texto ni explicaciones fuera del JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=2048
    )
    dieta_json = response.choices[0].message.content

    # 3. Guarda en la base de datos
    nueva_dieta = DietaGenerada(
        usuario_id=usuario_actual.id,
        datos_entrada=json.dumps({
            "edad": edad, "sexo": sexo, "altura": altura, "peso": peso,
            "objetivos": objetivos, "actividad_fisica": actividad_fisica,
            "experiencia_dietas": experiencia_dietas, "tipo_dieta": tipo_dieta,
            "preferencias_alimentarias": preferencias_alimentarias, "alergias": alergias,
            "alimentos_no_deseados": alimentos_no_deseados, "comidas_al_dia": comidas_al_dia,
            "tiempo_comidas": tiempo_comidas, "otros_datos": otros_datos, "duracion_dieta": duracion_dieta
        }),
        dieta_json=dieta_json
    )
    db.add(nueva_dieta)
    await db.commit()
    await db.refresh(nueva_dieta)

    # 4. Muestra el resultado (ajusta la ruta de template a la tuya)
    return templates.TemplateResponse(
        "dieta_generada.html",
        {"request": request, "dieta": json.loads(dieta_json)}
    )

@router.post("/formulario_mixto")
async def formulario_mixto_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    edad: int = Form(...),
    sexo: str = Form(...),
    altura_cm: int = Form(...),
    peso: float = Form(None),
    experiencia_entrenamiento: str = Form(""),
    actividad_fisica: str = Form(""),
    tiempo_disponible: str = Form(""),
    preferencias_entrenamiento: str = Form(""),
    objetivos_entrenamiento: str = Form(""),
    tipo_dieta: str = Form(""),
    preferencias_alimentarias: str = Form(""),
    alergias: str = Form(""),
    comidas_al_dia: int = Form(None),
    deporte_especifico: str = Form(""),
    equipamiento: str = Form(""),
    limitaciones: str = Form(""),
    otros_datos: str = Form(""),
    duracion_mixta: str = Form(...),
):
    # Prepara los datos para el prompt
    form_data = {
        "edad": edad,
        "sexo": sexo,
        "altura_cm": altura_cm,
        "peso": peso,
        "experiencia_entrenamiento": experiencia_entrenamiento,
        "actividad_fisica": actividad_fisica,
        "tiempo_disponible": tiempo_disponible,
        "preferencias_entrenamiento": [s.strip() for s in preferencias_entrenamiento.split(",") if s.strip()],
        "objetivos_entrenamiento": [s.strip() for s in objetivos_entrenamiento.split(",") if s.strip()],
        "tipo_dieta": tipo_dieta,
        "preferencias_alimentarias": preferencias_alimentarias,
        "alergias": alergias,
        "comidas_al_dia": comidas_al_dia,
        "deporte_especifico": deporte_especifico,
        "equipamiento": equipamiento,
        "limitaciones": limitaciones,
        "duracion_mixta": duracion_mixta,
    }

    prompt = construir_prompt_mixto(form_data, otros_datos)

    # Llama a OpenAI (o tu proveedor de IA)
    openai_client = AsyncOpenAI(api_key="TU_API_KEY_OPENAI")
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    contenido_json = response.choices[0].message.content

    # Guarda el resultado en la base de datos
    nuevo_plan = PlanMixtoGenerado(
        usuario_id=current_user.id,
        contenido_json=contenido_json
    )
    db.add(nuevo_plan)
    await db.commit()
    await db.refresh(nuevo_plan)

    # Devuelve o redirige como prefieras
    return {"ok": True, "plan_mixto": json.loads(contenido_json)}


@router.post("/alternativas_ejercicio")
async def alternativas_ejercicio(request: Request):
    data = await request.json()
    ejercicio = data.get("ejercicio")
    grupo_muscular = data.get("grupo_muscular")  # Puedes pasarlo desde el frontend si lo tienes
    try:
        alternativas = await generar_alternativas_ia(ejercicio, grupo_muscular)
    except Exception as e:
        return JSONResponse({"error": f"No se pudieron generar alternativas: {e}"}, status_code=500)
    return JSONResponse({"alternativas": alternativas})
app.include_router(router)

@router.post("/rutina/sustituir_ejercicio")
async def sustituir_ejercicio(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    rutina_id = data.get("rutina_id")
    semana = data.get("semana")
    dia = data.get("dia")
    ejercicio_original = data.get("ejercicio_original")
    ejercicio_nuevo = data.get("ejercicio_nuevo")

    # Recupera la rutina (supón que la rutina se guarda en JSON)
    rutina_obj = await db.get(Rutina, rutina_id)
    if not rutina_obj:
        raise HTTPException(status_code=404, detail="Rutina no encontrada")

    rutina_json = rutina_obj.plan  # o como lo tengas guardado

    # Busca y sustituye el ejercicio
    for semana_plan in rutina_json.get("plan", []):
        if semana_plan.get("semana") == semana:
            for dia_plan in semana_plan.get("dias", []):
                if dia_plan.get("dia") == dia:
                    nuevos_ejercicios = []
                    for ejercicio in dia_plan.get("ejercicios", []):
                        if ejercicio["nombre"] == ejercicio_original:
                            nuevos_ejercicios.append(ejercicio_nuevo)
                        else:
                            nuevos_ejercicios.append(ejercicio)
                    dia_plan["ejercicios"] = nuevos_ejercicios

    # Guarda la rutina actualizada
    rutina_obj.plan = rutina_json
    await db.commit()
    await db.refresh(rutina_obj)
    return JSONResponse({"ok": True, "rutina_actualizada": rutina_json})


@app.get("/api/buscar")
async def buscar_global(q: str, db: AsyncSession = Depends(get_db)):
    q = q.lower()

    resultados = []

    # Buscar usuarios (clientes, entrenadores, dietistas)
    res_usuarios = await db.execute(
        select(Usuario).where(Usuario.nombre.ilike(f"%{q}%")).limit(50)
    )
    for u in res_usuarios.scalars().all():
        resultados.append({
            "nombre": u.nombre,
            "tipo": u.rol,
            "url": f"/perfil/{u.id}"  # Asegúrate de tener esta ruta implementada
        })

    # Buscar gimnasios
    res_gym = await db.execute(
        select(models.Gimnasio).where(models.Gimnasio.nombre.ilike(f"%{q}%")).limit(50)
    )
    for g in res_gym.scalars().all():
        resultados.append({
            "nombre": g.nombre,
            "tipo": "Gimnasio",
            "url": f"/gimnasio/{g.id}"
        })

    return resultados[:50]  # máximo 50 resultados combinados


@app.get("/perfil/{id}", response_class=HTMLResponse)
async def ver_perfil_usuario(
        request: Request,
        id: int,
        db: AsyncSession = Depends(get_db),
        user=Depends(role_required(["cliente", "entrenador", "dietista", "gimnasio"]))
):
    usuario = await db.get(Usuario, id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    es_privada = getattr(usuario, "privada", False)

    # Busca amistad (ya lo tienes)
    result_amistad = await db.execute(
        select(models.Amistad)
        .where(
            ((models.Amistad.usuario_id == user["id"]) & (models.Amistad.amigo_id == id)) |
            ((models.Amistad.usuario_id == id) & (models.Amistad.amigo_id == user["id"]))
        )
    )
    amistad = result_amistad.scalar_one_or_none()
    puede_agregarse = (id != user["id"]) and (amistad is None)
    pendiente = amistad and amistad.estado == "pendiente"
    ya_son_amigos = amistad and amistad.estado == "aceptado"

    # --- RESTRICCIÓN ---
    mostrar_datos = True
    if es_privada and not ya_son_amigos and user["id"] != id:
        mostrar_datos = False  # Solo nombre, foto, descripción
    # -------------------

    # Recupera datos solo si procede:
    stats = gimnasio = rutina = dieta = multimedia = None
    if mostrar_datos:
        # ... tu código para cargar el resto de información ...
        pass

    return templates.TemplateResponse("perfil_usuario.html", {
        "request": request,
        "usuario": usuario,
        "stats": stats,
        "gimnasio": gimnasio,
        "rutina": rutina,
        "dieta": dieta,
        "multimedia": multimedia,
        "puede_agregarse": puede_agregarse,
        "pendiente": pendiente,
        "ya_son_amigos": ya_son_amigos,
        "mostrar_datos": mostrar_datos
    })


@app.get("/profesional/{id}", response_class=HTMLResponse)
async def ver_perfil_profesional(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente", "entrenador", "dietista", "gimnasio"]))
):
    profesional = await db.get(Usuario, id)
    if not profesional or profesional.rol not in ["entrenador", "dietista"]:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")

    # Clientes asignados
    result_clientes = await db.execute(
        select(models.UsuarioProfesional)
        .where(models.UsuarioProfesional.profesional_id == id)
    )
    clientes = result_clientes.scalars().all()

    return templates.TemplateResponse("perfil_profesional.html", {
        "request": request,
        "profesional": profesional,
        "clientes": clientes
    })

@app.post("/subir-foto-perfil")
async def subir_foto_perfil(
    imagen: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente", "entrenador", "dietista"]))
):
    filename = f"{datetime.now().timestamp()}_{imagen.filename}"
    filepath = UPLOAD_DIR / filename
    with open(filepath, "wb") as f:
        shutil.copyfileobj(imagen.file, f)

    usuario = await db.get(Usuario, user["id"])
    usuario.imagen_url = f"/static/uploads/{filename}"
    await db.commit()
    return RedirectResponse(url=f"/perfil/{usuario.id}", status_code=302)

@app.post("/amigos/agregar-ajax")
async def agregar_amigo_ajax(
    amigo_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    # Verifica si ya hay amistad
    amistad = await db.execute(
        select(models.Amistad).where(
            ((models.Amistad.usuario_id == user["id"]) & (models.Amistad.amigo_id == amigo_id)) |
            ((models.Amistad.usuario_id == amigo_id) & (models.Amistad.amigo_id == user["id"]))
        )
    )
    amistad = amistad.scalar_one_or_none()
    if amistad:
        return {"status": "error", "msg": "Ya hay una relación."}

    # Lógica pública/privada (ajusta según tu modelo)
    usuario_obj = await db.get(models.Usuario, amigo_id)
    if not usuario_obj:
        return {"status": "error", "msg": "Usuario no encontrado"}

    es_privada = getattr(usuario_obj, "privada", False)  # Cambia esto si tu modelo tiene otro nombre
    estado = "pendiente" if es_privada else "aceptado"

    nueva = models.Amistad(
        usuario_id=user["id"],
        amigo_id=amigo_id,
        estado=estado
    )
    db.add(nueva)
    await db.commit()
    return {"status": "ok", "estado": estado}

@app.post("/amistades/aceptar-ajax")
async def aceptar_amistad_ajax(
    solicitud_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    result = await db.execute(
        select(models.Amistad)
        .where(models.Amistad.id == solicitud_id)
        .where(models.Amistad.amigo_id == user["id"])
    )
    solicitud = result.scalar_one_or_none()

    if not solicitud:
        return {"status": "error", "msg": "Solicitud no encontrada"}

    solicitud.estado = "aceptado"
    await db.commit()
    return {"status": "ok"}

@app.post("/amistades/cancelar-ajax")
async def cancelar_amistad_ajax(
    amigo_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    # Busca la amistad en cualquier dirección
    result = await db.execute(
        select(models.Amistad)
        .where(
            ((models.Amistad.usuario_id == user["id"]) & (models.Amistad.amigo_id == amigo_id)) |
            ((models.Amistad.usuario_id == amigo_id) & (models.Amistad.amigo_id == user["id"]))
        )
    )
    amistad = result.scalar_one_or_none()
    if not amistad:
        return {"status": "error", "msg": "No hay amistad o solicitud"}

    await db.delete(amistad)
    await db.commit()
    return {"status": "ok"}


@app.get("/notificaciones", response_class=HTMLResponse)
async def notificaciones(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente", "entrenador", "dietista", "gimnasio"]))
):
    result = await db.execute(
        select(models.Notificacion)
        .where(models.Notificacion.usuario_id == user["id"])
        .order_by(models.Notificacion.fecha.desc())
    )
    notificaciones = result.scalars().all()
    return templates.TemplateResponse("notificaciones.html", {
        "request": request,
        "notificaciones": notificaciones
    })

@app.get("/api/sugerencias-ejercicios")
async def sugerencias_ejercicios(
    semana: int,
    dia: str,
    rutina_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    # Busca el último progreso guardado para ese día/semana/plan
    result = await db.execute(
        select(models.Progreso)
        .where(models.Progreso.usuario_id == user["id"])
        .where(models.Progreso.plan_id == rutina_id)
    )
    progresos = result.scalars().all()
    progreso_dia = None
    clave = f"{semana}_{dia}"
    for prog in progresos:
        try:
            detalle = json.loads(prog.progreso_detallado)
            if (
                (str(detalle.get("semana")) == str(semana))
                and (detalle.get("dia") == dia)
            ):
                progreso_dia = detalle
                break
        except Exception:
            continue

    if not progreso_dia:
        # Si no hay progreso, no puede haber recomendación IA útil
        return JSONResponse({"sugerencias": []})

    # IA: Sugerencias según progreso de ese día
    sugerencias = await ajustar_rutina_ia(progreso_dia)
    return JSONResponse({"sugerencias": sugerencias})

@app.post("/mi-entreno/guardar-sesion")
async def guardar_sesion_entreno(
    rutina_id: int = Form(...),
    semana: int = Form(...),
    dia: str = Form(...),
    datos_json: str = Form(...),  # JSON.stringify de todo el bloque arriba
    db: AsyncSession = Depends(get_db),
    user=Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]
    datos = json.loads(datos_json)
    progreso = models.Progreso(
        usuario_id=usuario_id,
        plan_id=rutina_id,
        fecha=datetime.now(),
        progreso_detallado=json.dumps(datos)
    )
    db.add(progreso)
    await db.commit()
    return {"msg": "Sesión guardada correctamente"}


def _e1rm_epley(weight: float, reps: int) -> float:
    return float(weight) * (1.0 + (float(reps) / 30.0))

def _round_to_step(x: float, step: float) -> float:
    if not isfinite(x):
        return None
    return round(x / step) * step

async def _ultimos_sets_usuario(db, usuario_id: int, ejercicio_nombre: str, limite_registros: int = 20):
    """
    Lee tus últimos Progreso (JSON) y extrae sets del ejercicio indicado.
    Espera estructuras como las que guardas en registrar_progreso_entreno:
        {"semana":..., "dia":..., "ejercicios":[{"nombre": "...", "peso": 60, "repes": 8, "rir": 2, ...}, ...]}
    """
    from app import models  # evitar import circular al inicio
    res = await db.execute(
        select(models.Progreso)
        .where(models.Progreso.usuario_id == usuario_id)
        .order_by(models.Progreso.fecha.desc())
        .limit(limite_registros)
    )
    sets = []
    for prog in res.scalars().all():
        try:
            detalle = json.loads(prog.progreso_detallado)
            for e in detalle.get("ejercicios", []):
                if (e.get("nombre") or "").strip().lower() == ejercicio_nombre.strip().lower():
                    # Normalizamos claves que ya usas: "peso", "repes" (y opcional "rir")
                    sets.append({
                        "weight": float(e.get("peso", 0) or 0),
                        "reps": int(e.get("repes", 0) or 0),
                        "rir": int(e.get("rir", 2) or 2),
                        "fecha": str(detalle.get("fecha", "")),
                    })
        except Exception:
            continue
    return sets

def _sugerir_carga_desde_sets(sets: list, target_reps=(5,8), micro_step=2.5):
    if not sets:
        return None, "Sin historial para este ejercicio"
    # Tomamos hasta 3 sets más recientes con datos válidos
    valid = [s for s in sets if s["weight"] > 0 and s["reps"] > 0]
    if not valid:
        return None, "Historial sin datos de peso/reps"
    last3 = valid[:3]  # ya vienen ordenados desde Progreso más reciente
    e1rms = [_e1rm_epley(s["weight"], s["reps"]) for s in last3]
    base_e1rm = mean(e1rms)
    # Objetivo 70–80% e1RM ~ 5–8 reps
    target_pct = 0.75
    proposed = base_e1rm * target_pct

    # Ajuste por el último rendimiento
    s = last3[0]
    low, high = target_reps
    rir = s.get("rir", 2)
    if s["reps"] > high and rir >= 2:
        proposed *= 1.025  # +2.5%
    elif s["reps"] < low or rir <= 0:
        proposed *= 0.975  # -2.5%

    load = _round_to_step(proposed, micro_step)
    return load, None

@app.get("/progress/suggestion")
async def sugerencia_carga(
    ejercicio: str,
    micro_step: float = 2.5,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Uso:
    GET /progress/suggestion?ejercicio=Press%20Banca
    Devuelve: {"exercise": "...", "suggested_load": 72.5, "note": "..."}
    """
    sets = await _ultimos_sets_usuario(db, user["id"], ejercicio)
    load, note = _sugerir_carga_desde_sets(sets, micro_step=micro_step)
    return {
        "exercise": ejercicio,
        "suggested_load": load,
        "note": note,
        "samples": sets[:3]  # te deja ver en el front qué datos usó
    }

from urllib.parse import unquote
import re

def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "_", s.strip().lower())

# --- refuerzo de logs/errores para imágenes IA ---
# app/main.py (reemplaza íntegro el endpoint)
@app.get("/api/ejercicios/generar-imagen")
async def api_generar_imagen_ejercicio(
    rutina_id: int,
    nombre: str,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    logger.info(f"[IMG-IA] req rutina_id={rutina_id} nombre='{nombre}' user={user['email']}")
    try:
        rutina = await db.get(models.Rutina, rutina_id)
        if not rutina or rutina.usuario_id != user["id"]:
            raise HTTPException(404, "Rutina no encontrada")

        # Cargar/normalizar el JSON del plan
        plan = rutina.rutina_json or {}
        if isinstance(plan, str):
            import json as _json
            try:
                plan = _json.loads(plan)
            except Exception:
                plan = {}

        # localizar ejercicio dentro del plan
        objetivo = None
        for semana in plan.get("plan", []):
            for dia in semana.get("dias", []):
                for ej in dia.get("ejercicios", []):
                    if (ej.get("nombre") or "").strip().lower() == nombre.strip().lower():
                        objetivo = ej
                        break
                if objetivo: break
            if objetivo: break
        if not objetivo:
            raise HTTPException(404, "Ejercicio no existe en la rutina")

        # Si ya hay una imagen local, devolverla
        url_existente = (objetivo.get("imagen_url") or "").strip()
        if url_existente.startswith("/static/uploads/"):
            logger.info(f"[IMG-IA] ya local -> {url_existente}")
            return {"url": url_existente}

        # Si hay una URL remota anterior (blob de OpenAI o data:), la traemos y guardamos local
        if url_existente.startswith(("http://", "https://", "data:image/")):
            fname_old = f"ia_{_safe_slug(nombre)}_{uuid.uuid4().hex}.png"
            url_local_old = await descargar_imagen_ia(url_existente, fname_old)
            if url_local_old:
                objetivo["imagen_url"] = url_local_old
                rutina.rutina_json = plan
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    raise HTTPException(500, f"Error guardando imagen previa en BD: {e}")
                logger.info(f"[IMG-IA] normalizada previa -> {url_local_old}")
                return {"url": url_local_old}

        # Generar con IA
        motivo = objetivo.get("motivo", "")
        url_tmp = await generar_imagen_ejercicio(nombre, motivo)  # utils.py OK :contentReference[oaicite:1]{index=1}
        logger.info(f"[IMG-IA] OpenAI OK, tipo={'data' if url_tmp.startswith('data:') else 'url'}")

        # Guardar local SIEMPRE (evita 403 de blobs temporales)
        fname = f"ia_{_safe_slug(nombre)}_{uuid.uuid4().hex}.png"
        url_local = await descargar_imagen_ia(url_tmp, fname)
        if not url_local:
            logger.error("[IMG-IA] descargar_imagen_ia() devolvió None")
            raise HTTPException(502, "No se pudo guardar la imagen generada")

        # Persistir en BD y DEVOLVER la URL
        objetivo["imagen_url"] = url_local
        rutina.rutina_json = plan
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(500, f"Error guardando la imagen en la BD: {e}")

        logger.info(f"[IMG-IA] guardada local -> {url_local}")
        return {"url": url_local}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[IMG-IA] fallo")
        raise HTTPException(500, detail="Error interno generando imagen")

@app.get("/diag/openai-key")
async def diag_key():
    import os
    return {"has_key": bool(os.getenv("OPENAI_API_KEY"))}

@app.get("/diag/openai-image")
async def diag_image():
    try:
        url = await generar_imagen_ejercicio("bench press", "test tiny prompt")
        return {"ok": True, "sample": (url[:60] + '...')}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# app/main.py
@app.post("/admin/fix-imagenes-rutina/{rutina_id}")
async def fix_imagenes_rutina(
    rutina_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)  # limita a admin si quieres
):
    rutina = await db.get(models.Rutina, rutina_id)
    if not rutina:
        raise HTTPException(404, "Rutina no encontrada")

    plan = rutina.rutina_json or {}
    cambios = 0

    for semana in plan.get("plan", []):
        for dia in semana.get("dias", []):
            for ej in dia.get("ejercicios", []):
                url = (ej.get("imagen_url") or "").strip()
                if url.startswith("/static/uploads/"):
                    continue  # ya local
                if url.startswith(("http://", "https://")):
                    # intenta descargar la externa
                    filename = f"ia_{_safe_slug(ej.get('nombre','ej'))}_{uuid.uuid4().hex}.png"
                    local = await descargar_imagen_ia(url, filename)
                    if local:
                        ej["imagen_url"] = local
                        cambios += 1
                    else:
                        # si falla, regénérala
                        try:
                            motivo = ej.get("motivo", "")
                            url_tmp = await generar_imagen_ejercicio(ej.get("nombre",""), motivo)
                            local2 = await descargar_imagen_ia(url_tmp, filename)
                            if local2:
                                ej["imagen_url"] = local2
                                cambios += 1
                            else:
                                ej["imagen_url"] = ""
                        except Exception:
                            ej["imagen_url"] = ""
                # si está vacía, no tocamos (el usuario ya pulsará "🪄")

    if cambios:
        rutina.rutina_json = plan
        await db.commit()
    return {"ok": True, "cambios": cambios}

@app.get("/diag/openai-key")
async def diag_key():
    import os
    k = os.getenv("OPENAI_API_KEY") or ""
    return {
        "has_key": bool(k),
        "prefix": k[:7] if k else None,
        "len": len(k) if k else 0
    }

@app.get("/diag/probar-imagen")
async def diag_probar_imagen():
    # Fuerza una llamada directa a la IA sin base de datos ni auth
    try:
        from app.utils import generar_imagen_ejercicio
        tmp = await generar_imagen_ejercicio("Press banca", "Foto realista en gimnasio, técnica correcta")
        return {"ok": True, "tipo": "data" if str(tmp).startswith("data:") else "url"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/estadisticas")
async def api_estadisticas(
    stat: str = Query(..., description="peso | adherencia_dieta | adherencia_entrenos | entrenos_completados | dias_activo | distancia | peso_levantado | tiempo_entreno"),
    interval: str = Query("7d", description="7d | 14d | 30d | 12w | 6m | 1y"),
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Devuelve {labels, data} para la UI.
    Lee de models.Progreso.progreso_detallado (JSON en texto) y agrupa
    de forma simple por día (para empezar). Más adelante podemos cambiar
    a agregaciones SQL si lo deseas.
    """
    # --- calcular rango temporal simple por 'interval' ---
    hoy = _dt.date.today()
    if interval == "14d":
        inicio = hoy - _dt.timedelta(days=13)
    elif interval == "30d":
        inicio = hoy - _dt.timedelta(days=29)
    elif interval == "12w":
        inicio = hoy - _dt.timedelta(weeks=11)
    elif interval == "6m":
        inicio = hoy - _dt.timedelta(days=30*6-1)
    elif interval == "1y":
        inicio = hoy - _dt.timedelta(days=365-1)
    else:  # "7d" por defecto
        inicio = hoy - _dt.timedelta(days=6)

    # --- consulta básica del progreso del usuario en el rango ---
    stmt = (
        select(models.Progreso)
        .where(models.Progreso.usuario_id == user["id"])
        .where(models.Progreso.fecha >= inicio)
        .order_by(models.Progreso.fecha.asc())
    )
    res = await db.execute(stmt)
    filas = res.scalars().all()

    # --- mapear clave solicitada a la del JSON ---
    # en tu main lees claves como "peso", "adherencia", "entrenos_completados", "dias_activo"
    key_map = {
        "peso": "peso",
        "adherencia_dieta": "adherencia",          # si luego tienes una clave distinta, la cambiamos
        "adherencia_entrenos": "adherencia",       # placeholder hasta tener planificados vs completados
        "entrenos_completados": "entrenos_completados",
        "dias_activo": "dias_activo",
        # estas dos requieren tablas específicas; de momento intentamos leer si las guardas en progreso_detallado
        "distancia": "distancia_km",
        "peso_levantado": "peso_levantado_kg",
        "tiempo_entreno": "tiempo_min",
    }
    if stat not in key_map:
        # clave desconocida
        return {"labels": [], "data": []}

    json_key = key_map[stat]

    labels: list[str] = []
    data: list[float | None] = []

    for fila in filas:
        try:
            d = json.loads(fila.progreso_detallado or "{}")
        except Exception:
            d = {}

        # etiqueta por día (dd/mm)
        try:
            fecha = fila.fecha
            if isinstance(fecha, str):
                fecha = _dt.datetime.fromisoformat(fecha).date()
            labels.append(fecha.strftime("%d/%m"))
        except Exception:
            labels.append("")

        val = d.get(json_key)
        # normalizamos a número si se puede
        try:
            if val is None or val == "N/A":
                data.append(None)
            else:
                data.append(float(val))
        except Exception:
            data.append(None)

    # si no hay ningún dato, devolvemos vacío (tu frontend ya muestra placeholder)
    if not any(v is not None for v in data):
        return {"labels": [], "data": []}

    return {"labels": labels, "data": data}

from fastapi import Depends

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

@app.get("/api/amigos")
async def api_amigos(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """
    Devuelve lista de amigos aceptados del usuario autenticado: [{id, nombre}]
    """
    # Ajusta si tienes ORM; aquí tiro de SQL directo por simplicidad
    q = text("""
      SELECT u.id, u.nombre
      FROM usuarios u
      JOIN amistades a ON a.amigo_id = u.id
      WHERE a.usuario_id_1 = :uid AND a.estado = 'aceptado'
      UNION
      SELECT u2.id, u2.nombre
      FROM usuarios u2
      JOIN amistades a2 ON a2.usuario_id_1 = u2.id
      WHERE a2.usuario_id_2 = :uid AND a2.estado = 'aceptado'
      ORDER BY 2
    """)
    res = await db.execute(q, {"uid": user["id"]})
    rows = res.all()
    return [{"id": r[0], "nombre": r[1]} for r in rows]

def _interval_to_start(interval: str) -> _dt.date:
    hoy = _dt.date.today()
    if interval == "14d":
        return hoy - _dt.timedelta(days=13)
    if interval == "30d":
        return hoy - _dt.timedelta(days=29)
    if interval == "12w":
        return hoy - _dt.timedelta(weeks=11)
    if interval == "6m":
        return hoy - _dt.timedelta(days=30 * 6 - 1)
    if interval == "1y":
        return hoy - _dt.timedelta(days=365 - 1)
    return hoy - _dt.timedelta(days=6)

STAT_JSON_KEYS = {
    "peso": "peso",
    "adherencia_dieta": "adherencia",
    "adherencia_entrenos": "adherencia",  # heurística
    "entrenos_completados": "entrenos_completados",
    "dias_activo": "dias_activo",
    "distancia": "distancia_km",
    "peso_levantado": "peso_levantado_kg",
    "tiempo_entreno": "tiempo_min",
}

async def _fetch_series_for_user(
    db: AsyncSession,
    user_id: int,
    start_date: _dt.date,
    json_key: str
):
    stmt = (
        select(models.Progreso)
        .where(models.Progreso.usuario_id == user_id)
        .where(models.Progreso.fecha >= start_date)
        .order_by(models.Progreso.fecha.asc())
    )
    res = await db.execute(stmt)
    filas = res.scalars().all()

    labels: list[str] = []
    values: list[float | None] = []

    for r in filas:
        try:
            d = json.loads(r.progreso_detallado or "{}")
        except Exception:
            d = {}

        fecha = r.fecha
        if isinstance(fecha, str):
            try:
                fecha = _dt.datetime.fromisoformat(fecha).date()
            except Exception:
                fecha = start_date

        labels.append(fecha.strftime("%d/%m"))

        val = d.get(json_key)
        try:
            values.append(None if val is None or val == "N/A" else float(val))
        except Exception:
            values.append(None)

    return labels, values

@app.get("/api/estadisticas/comparativo")
async def api_estadisticas_comparativo(
    stat: str,
    interval: str = "7d",
    friends: str | None = None,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Respuesta:
      {
        "labels": [...],
        "series": [
          {"userId": 16, "name": "Tú", "data":[...]},
          {"userId": 7, "name": "Ana", "data":[...]},
          ...
        ]
      }
    """
    if stat not in STAT_JSON_KEYS:
        return {"labels": [], "series": []}

    json_key = STAT_JSON_KEYS[stat]
    start = _interval_to_start(interval)

    # Serie del usuario actual
    labels, my_values = await _fetch_series_for_user(db, user["id"], start, json_key)
    series = [{
        "userId": user["id"],
        "name": "Tú",
        "data": my_values
    }]

    # Amigos seleccionados
    friend_ids: list[int] = []
    if friends:
        friend_ids = [int(x) for x in friends.split(",") if x.strip().isdigit()]

    if friend_ids:
        # Traer nombres de amigos (ajusta si tu modelo de Usuario tiene otro nombre)
        res = await db.execute(select(models.Usuario).where(models.Usuario.id.in_(friend_ids)))
        users = {u.id: u for u in res.scalars().all()}

        for fid in friend_ids:
            flabels, fvals = await _fetch_series_for_user(db, fid, start, json_key)

            # Alinear por longitud de labels del usuario principal (simple padding/recorte)
            const_len = len(labels) if labels else len(flabels)

            # Si el amigo tiene más puntos que el principal, recortamos por la derecha
            if len(fvals) > const_len:
                fvals = fvals[-const_len:]

            # Si tiene menos, rellenamos por la izquierda con None
            if len(fvals) < const_len:
                fvals = [None] * (const_len - len(fvals)) + fvals

            series.append({
                "userId": fid,
                "name": users.get(fid).nombre if users.get(fid) else f"Usuario {fid}",
                "data": fvals
            })

    # Si nadie tiene datos → vacío
    tiene_mios = any(v is not None for v in (my_values or []))
    tiene_amigos = any(any(v is not None for v in (s["data"] or [])) for s in series[1:])
    if not tiene_mios and not tiene_amigos:
        return {"labels": [], "series": []}

    return {"labels": labels, "series": series}
    return {"labels": labels, "series": series}

# ─── helpers dieta ─────────────────────────────────────────────────────────────
DAY_ORDER = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]

def _as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def _normalize_dieta_json(raw):
    """
    Devuelve: {
      "semanas": int|None,
      "dias": {
        "Lunes": [ { "momento":"Desayuno", "plato":"...", "kcal":..., "macros":{...} }, ... ],
        ...
      }
    }
    Soporta varias estructuras típicas.
    """
    if not raw:
        return {"semanas": None, "dias": {d: [] for d in DAY_ORDER}}

    data = raw
    # Caso: viene como string JSON
    if isinstance(raw, str):
        try:
            import json as _json
            data = _json.loads(raw)
        except Exception:
            return {"semanas": None, "dias": {d: [] for d in DAY_ORDER}}

    out = {"semanas": data.get("semanas"), "dias": {d: [] for d in DAY_ORDER}}

    # Estructuras comunes
    # 1) data["dias"] = {"Lunes":[{...},...], "Martes":[...]}
    if isinstance(data.get("dias"), dict):
        for k, v in data["dias"].items():
            k_cap = k.capitalize()
            if k_cap in out["dias"]:
                out["dias"][k_cap] = _as_list(v)

    # 2) data["plan_semanal"] = [{"dia":"Lunes","comidas":[...]}, ...]
    elif isinstance(data.get("plan_semanal"), list):
        for d in data["plan_semanal"]:
            nombre = str(d.get("dia","")).capitalize()
            if nombre in out["dias"]:
                out["dias"][nombre] = _as_list(d.get("comidas"))

    # 3) data["semanas"] -> lista de semanas, cada una con dias/comidas
    elif isinstance(data.get("semanas_detalle"), list):
        # aplanamos la primera semana como plan por defecto
        semana0 = data["semanas_detalle"][0] if data["semanas_detalle"] else {}
        dias_sem = semana0.get("dias") or []
        for d in dias_sem:
            nombre = str(d.get("dia","")).capitalize()
            if nombre in out["dias"]:
                out["dias"][nombre] = _as_list(d.get("comidas"))

    return out


# ─── Lista de dietas ──────────────────────────────────────────────────────────
@app.get("/mis-dietas", response_class=HTMLResponse)
async def ver_mis_dietas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user = Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]

    # Carga usuario para el sidebar (mismo patrón que en /usuarios)
    usuario_obj = await db.get(models.Usuario, usuario_id)
    if not usuario_obj or not getattr(usuario_obj, "imagen_url", None):
        from types import SimpleNamespace
        DEFAULT_AVATAR_REL = "uploads/2571eb2a-583a-490b-aa0d-c2ca737e290f.png"
        usuario_obj = usuario_obj or SimpleNamespace(nombre="Tu perfil", imagen_url=DEFAULT_AVATAR_REL)
        if getattr(usuario_obj, "imagen_url", None) is None:
            setattr(usuario_obj, "imagen_url", DEFAULT_AVATAR_REL)

    # Dietas del usuario (últimas primero)
    res = await db.execute(
        select(models.Dieta)
        .where(models.Dieta.usuario_id == usuario_id)
        .order_by(models.Dieta.fecha_creacion.desc())
    )
    dietas = res.scalars().all()

    return templates.TemplateResponse("mis_dietas_lista.html", {
        "request": request,
        "usuario": usuario_obj,
        "dietas": dietas,
    })


# ─── Detalle de una dieta ─────────────────────────────────────────────────────
@app.get("/mis-dietas/{dieta_id}", response_class=HTMLResponse)
async def ver_detalle_dieta(
    dieta_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user = Depends(role_required(["cliente"]))
):
    usuario_id = user["id"]

    # Usuario para sidebar
    usuario_obj = await db.get(models.Usuario, usuario_id)
    if not usuario_obj or not getattr(usuario_obj, "imagen_url", None):
        from types import SimpleNamespace
        DEFAULT_AVATAR_REL = "uploads/2571eb2a-583a-490b-aa0d-c2ca737e290f.png"
        usuario_obj = usuario_obj or SimpleNamespace(nombre="Tu perfil", imagen_url=DEFAULT_AVATAR_REL)
        if getattr(usuario_obj, "imagen_url", None) is None:
            setattr(usuario_obj, "imagen_url", DEFAULT_AVATAR_REL)

    # Dieta concreta
    dieta = await db.get(models.Dieta, dieta_id)
    if not dieta or int(dieta.usuario_id) != int(usuario_id):
        raise HTTPException(status_code=404, detail="Dieta no encontrada")

    plan = _normalize_dieta_json(dieta.dieta_json)

    return templates.TemplateResponse("mis_dietas_detalle.html", {
        "request": request,
        "usuario": usuario_obj,
        "dieta": dieta,
        "plan": plan,
        "DAY_ORDER": DAY_ORDER,
    })

