# app/routers/estadisticas.py
from datetime import datetime, timedelta, date
from enum import Enum
from typing import Literal, Tuple, List, Dict, Any, Optional

import pytz
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_, cast, Float, literal_column, extract, text
from sqlalchemy.orm import Session

from app.database import get_db   # <-- tu dependencia para obtener Session
from app.main import get_current_user  # <-- ajusta a tu auth
from app.models import Progreso, WorkoutSession, SetRecord, ExerciseSession  # <-- ajusta los import a tus modelos

router = APIRouter(prefix="/api", tags=["estadisticas"])

TZ = pytz.timezone("Europe/Madrid")


class StatKey(str, Enum):
    peso = "peso"
    tiempo_entreno = "tiempo_entreno"
    adherencia_entrenos = "adherencia_entrenos"
    adherencia_dieta = "adherencia_dieta"
    distancia = "distancia"
    peso_levantado = "peso_levantado"


IntervalKey = Literal["7d", "14d", "30d", "12w", "6m", "1y"]


# ---------- Utilidades de tiempo / buckets ----------
def now_madrid() -> datetime:
    return datetime.now(TZ)


def parse_interval(interval: IntervalKey) -> Tuple[datetime, str, int]:
    """
    Devuelve: (inicio_UTC, granularity, num_points)
    granularity: 'day' | 'week' | 'month'
    """
    today = now_madrid().replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "7d":
        start = today - timedelta(days=6)
        return start, "day", 7
    if interval == "14d":
        start = today - timedelta(days=13)
        return start, "day", 14
    if interval == "30d":
        start = today - timedelta(days=29)
        return start, "day", 30
    if interval == "12w":
        start = today - timedelta(weeks=11)
        return start, "week", 12
    if interval == "6m":
        # aproximación: 30 días * 6
        start = today - timedelta(days=30 * 6 - 1)
        return start, "month", 6
    if interval == "1y":
        start = today - timedelta(days=365 - 1)
        return start, "month", 12
    # fallback
    start = today - timedelta(days=6)
    return start, "day", 7


def daterange_labels(start: datetime, granularity: str, points: int) -> List[str]:
    """Genera las etiquetas legibles para el eje X en Madrid."""
    labels: List[str] = []
    cur = start
    for _ in range(points):
        if granularity == "day":
            labels.append(cur.strftime("%d/%m"))
            cur = cur + timedelta(days=1)
        elif granularity == "week":
            # etiqueta por la semana que empieza en 'cur'
            labels.append(f"S{cur.isocalendar()[1]} ({cur.strftime('%d/%m')})")
            cur = cur + timedelta(weeks=1)
        else:  # month
            labels.append(cur.strftime("%b %Y"))
            # avanzar aprox a siguiente mes (día 28 + 4 para saltar al próximo)
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return labels


def bucket_key_sql(dt_col, granularity: str):
    """
    Devuelve una expresión SQL para agrupar por día/semana/mes con Postgres.
    Se usa DATE_TRUNC con zona horaria local.
    """
    # Asegura trunc en horario de Madrid (si guardas UTC, aplica AT TIME ZONE)
    # dt_col AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Madrid'  -> timestamp en Madrid
    # Si ya guardas en hora local, simplifica a date_trunc(granularity, dt_col)
    madrid_trunc = func.date_trunc(
        granularity,
        func.timezone('Europe/Madrid', dt_col)  # Postgres: convert tz
    )
    return madrid_trunc


def fill_series(start: datetime, granularity: str, points: int, rows: Dict[date, float]) -> List[Optional[float]]:
    """
    rows: dict { bucket_date: value }
    Devuelve lista de longitud 'points' con None en buckets sin dato.
    """
    out: List[Optional[float]] = []
    cur = start
    for _ in range(points):
        key: Optional[date]
        if granularity == "day":
            key = cur.date()
            cur = cur + timedelta(days=1)
        elif granularity == "week":
            key = cur.date()
            cur = cur + timedelta(weeks=1)
        else:
            key = cur.date().replace(day=1)
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append(rows.get(key))
    return out


# ---------- Consultas por estadística ----------
def q_peso(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    Peso corporal desde progreso.progreso_detallado JSONB -> 'peso_kg'
    Campos inferidos: Progreso(usuario_id, fecha, progreso_detallado JSONB)
    """
    # Extraer JSONB -> texto -> float
    peso_json_text = Progreso.progreso_detallado['peso_kg'].astext
    peso_float = cast(peso_json_text, Float)

    bucket = bucket_key_sql(Progreso.fecha, "day") if granularity == "day" else (
        bucket_key_sql(Progreso.fecha, "week") if granularity == "week" else
        bucket_key_sql(Progreso.fecha, "month")
    )

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.avg(peso_float).label("valor")
        )
        .filter(
            Progreso.usuario_id == user_id,
            Progreso.fecha >= start
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )

    return {r.bucket_date: float(r.valor) for r in rows if r.valor is not None}


def q_tiempo_entreno(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    Tiempo total entrenado por bucket (minutos).
    Tabla inferida: WorkoutSession(usuario_id, started_at, ended_at)
    """
    dt_col = WorkoutSession.started_at  # ajusta si tu columna es distinta
    end_col = WorkoutSession.ended_at

    bucket = bucket_key_sql(dt_col, "day") if granularity == "day" else (
        bucket_key_sql(dt_col, "week") if granularity == "week" else
        bucket_key_sql(dt_col, "month")
    )

    duration_min = (func.extract('epoch', end_col) - func.extract('epoch', dt_col)) / 60.0

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.sum(duration_min).label("valor")
        )
        .filter(
            WorkoutSession.usuario_id == user_id,
            dt_col >= start,
            end_col.isnot(None)
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )
    return {r.bucket_date: float(r.valor) for r in rows if r.valor is not None}


def q_peso_levantado(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    Suma de peso levantado (kg * reps) por bucket.
    Tablas inferidas: SetRecord(user_id, created_at, weight_kg, reps)
    Si el user_id está en otra tabla relacionada (p.ej. sesión), ajusta el join.
    """
    dt_col = SetRecord.created_at  # ajusta
    bucket = bucket_key_sql(dt_col, "day") if granularity == "day" else (
        bucket_key_sql(dt_col, "week") if granularity == "week" else
        bucket_key_sql(dt_col, "month")
    )

    total_kg = (cast(SetRecord.weight_kg, Float) * cast(SetRecord.reps, Float))

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.sum(total_kg).label("valor")
        )
        .filter(
            SetRecord.usuario_id == user_id,   # ajusta si la FK es distinta
            dt_col >= start
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )
    return {r.bucket_date: float(r.valor) for r in rows if r.valor is not None}


def q_distancia(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    Distancia recorrida (km) por bucket.
    Tabla inferida: ExerciseSession(usuario_id, started_at, distance_km, modality)
    """
    dt_col = ExerciseSession.started_at
    bucket = bucket_key_sql(dt_col, "day") if granularity == "day" else (
        bucket_key_sql(dt_col, "week") if granularity == "week" else
        bucket_key_sql(dt_col, "month")
    )

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.sum(cast(ExerciseSession.distance_km, Float)).label("valor")
        )
        .filter(
            ExerciseSession.usuario_id == user_id,
            dt_col >= start
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )
    return {r.bucket_date: float(r.valor) for r in rows if r.valor is not None}


def q_adherencia_entrenos(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    % de adherencia a entrenos por bucket: (completados/planificados)*100.
    Si no tienes tabla de planificados aún, usa una heurística temporal:
    - Si hubo al menos una sesión en el día → 100, si no → 0.
    """
    # Heurística simple basada en workout_sessions (ajusta cuando tengas planificados)
    dt_col = WorkoutSession.started_at
    bucket = bucket_key_sql(dt_col, "day") if granularity == "day" else (
        bucket_key_sql(dt_col, "week") if granularity == "week" else
        bucket_key_sql(dt_col, "month")
    )

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.count(WorkoutSession.id).label("sesiones")
        )
        .filter(
            WorkoutSession.usuario_id == user_id,
            dt_col >= start
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )
    # Heurística: si hay >=1 sesión → 100, si 0 → 0
    return {r.bucket_date: 100.0 if r.sesiones and r.sesiones > 0 else 0.0 for r in rows}


def q_adherencia_dieta(db: Session, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    """
    % adherencia dieta.
    O bien de una tabla específica, o de progreso.progreso_detallado['adherencia_dieta'].
    """
    # Lectura desde JSONB en 'progreso'
    adh_json_text = Progreso.progreso_detallado['adherencia_dieta'].astext
    adh_float = cast(adh_json_text, Float)

    bucket = bucket_key_sql(Progreso.fecha, "day") if granularity == "day" else (
        bucket_key_sql(Progreso.fecha, "week") if granularity == "week" else
        bucket_key_sql(Progreso.fecha, "month")
    )

    rows = (
        db.query(
            func.date(bucket).label("bucket_date"),
            func.avg(adh_float).label("valor")
        )
        .filter(
            Progreso.usuario_id == user_id,
            Progreso.fecha >= start
        )
        .group_by(func.date(bucket))
        .order_by(func.date(bucket))
        .all()
    )
    return {r.bucket_date: float(r.valor) for r in rows if r.valor is not None}


# ---------- Dispatcher ----------
def run_query(db: Session, stat: StatKey, user_id: int, start: datetime, granularity: str) -> Dict[date, float]:
    if stat == StatKey.peso:
        return q_peso(db, user_id, start, granularity)
    if stat == StatKey.tiempo_entreno:
        return q_tiempo_entreno(db, user_id, start, granularity)
    if stat == StatKey.peso_levantado:
        return q_peso_levantado(db, user_id, start, granularity)
    if stat == StatKey.distancia:
        return q_distancia(db, user_id, start, granularity)
    if stat == StatKey.adherencia_entrenos:
        return q_adherencia_entrenos(db, user_id, start, granularity)
    if stat == StatKey.adherencia_dieta:
        return q_adherencia_dieta(db, user_id, start, granularity)
    return {}


# ---------- Endpoint ----------
@router.get("/estadisticas")
def estadisticas(
    stat: StatKey = Query(..., description="Clave de estadística"),
    interval: IntervalKey = Query("7d", description="Intervalo de tiempo"),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
):
    """
    Devuelve {labels, data} para la UI del dashboard.
    - labels: lista de strings legibles
    - data: lista de floats o None (para huecos)
    """
    start, granularity, points = parse_interval(interval)
    # trunc a 00:00 Europe/Madrid
    start = start.replace(tzinfo=TZ)

    rows_by_bucket = run_query(db, stat, user.id, start, granularity)

    labels = daterange_labels(start, granularity, points)
    data = fill_series(start, granularity, points, rows_by_bucket)

    # Si todo None → la UI mostrará placeholder
    # No devolvemos 404; siempre 200 con arrays (vacíos o con None)
    # Si prefieres arrays vacíos cuando no hay nada, descomenta:
    # if all(v is None for v in data):
    #     return {"labels": [], "data": []}

    return {"labels": labels, "data": data}
