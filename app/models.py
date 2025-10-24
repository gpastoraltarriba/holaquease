from __future__ import annotations
from sqlalchemy import Table, String, Integer, DateTime, Text, ForeignKey, Boolean, UniqueConstraint, Column, Numeric
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.database import Base
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, Date, Numeric, Text, ForeignKey, DateTime, text
from typing import Optional
from datetime import date, datetime

class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    contraseña: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), nullable=False)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    imagen_url = Column(String, nullable=True)
    dietas = relationship("Dieta", back_populates="usuario")

    gimnasios = relationship("UsuarioGimnasio", back_populates="usuario", cascade="all, delete-orphan")
    planes_mixtos_generados = relationship("PlanMixtoGenerado", back_populates="usuario", cascade="all, delete-orphan")
    dietas_generadas = relationship("DietaGenerada", back_populates="usuario", cascade="all, delete-orphan")
    rutinas = relationship("Rutina", back_populates="usuario")

class FormularioCliente(Base):
    __tablename__ = "formulario_cliente"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    altura_cm: Mapped[int] = mapped_column(nullable=False)
    edad: Mapped[int] = mapped_column(nullable=False)
    experiencia_entrenamiento: Mapped[str] = mapped_column(String(100), nullable=False)
    tiempo_disponible: Mapped[str] = mapped_column(String(100), nullable=False)
    sexo: Mapped[str] = mapped_column(String(10), nullable=False)
    preferencias_entrenamiento: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    objetivos_entrenamiento: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    deporte_especifico: Mapped[str] = mapped_column(Text)
    semanas: Mapped[int] = mapped_column()
    aspectos_mejorar: Mapped[str] = mapped_column(Text)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Plan(Base):
    __tablename__ = "planes"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))  # <--- ESTA LÍNEA
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    creado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    rutina_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    formulario_dieta_id = Column(Integer, ForeignKey("formularios_dieta.id"), nullable=True)
    formulario_dieta = relationship("FormularioDieta")
    entrenamientos = relationship("Entrenamiento", back_populates="plan", cascade="all, delete")
    dietas = relationship("Dieta", back_populates="plan", cascade="all, delete")

class Entrenamiento(Base):
    __tablename__ = "entrenamientos"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes.id", ondelete="CASCADE"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text)
    duracion_estim: Mapped[int] = mapped_column()
    dificultad: Mapped[str] = mapped_column(String(20))

    plan = relationship("Plan", back_populates="entrenamientos")

class UsuarioPlan(Base):
    __tablename__ = "usuario_planes"
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes.id", ondelete="CASCADE"), primary_key=True)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Dieta(Base):
    __tablename__ = "dietas"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes.id", ondelete="CASCADE"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text)
    calorias_totales: Mapped[int] = mapped_column()
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    usuario = relationship("Usuario", back_populates="dietas")
    plan = relationship("Plan", back_populates="dietas")

class Progreso(Base):
    __tablename__ = "progreso"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes.id", ondelete="CASCADE"))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    progreso_detallado: Mapped[str] = mapped_column(Text)

class SesionEntreno(Base):
    __tablename__ = "sesiones_entrenamiento"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    entrenamiento_id: Mapped[int] = mapped_column(ForeignKey("entrenamientos.id", ondelete="CASCADE"), nullable=False)
    fecha_programada: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completado: Mapped[bool] = mapped_column(Boolean, default=False)
    comentarios: Mapped[str] = mapped_column(Text)

    usuario = relationship("Usuario")
    entrenamiento = relationship("Entrenamiento")

class RegistroComida(Base):
    __tablename__ = "comida_imagenes"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    imagen_url: Mapped[str] = mapped_column(String(255), nullable=False)
    fecha_subida: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analisis_json: Mapped[dict] = mapped_column(JSONB)
    comentarios: Mapped[str] = mapped_column(Text)
    fecha = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario")

class FormularioDieta(Base):
    __tablename__ = "formularios_dieta"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    altura: Mapped[int] = mapped_column()
    edad: Mapped[int] = mapped_column()
    sexo: Mapped[str] = mapped_column(String)
    semanas: Mapped[int] = mapped_column()
    objetivos: Mapped[list[str]] = mapped_column(ARRAY(String))
    tipo_dieta: Mapped[str] = mapped_column(String)
    alergias: Mapped[str] = mapped_column(String)
    alimentos_no_deseados: Mapped[str] = mapped_column(String)
    tiempo_comidas: Mapped[str] = mapped_column(String)
    comidas_al_dia: Mapped[int] = mapped_column()
    calorias_objetivo: Mapped[int] = mapped_column()
    preferencias_alimentarias = Column(ARRAY(String), nullable=False, server_default="{}")
    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class FormularioMixto(Base):
    __tablename__ = "formularios_mixto"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    altura: Mapped[int] = mapped_column()
    edad: Mapped[int] = mapped_column()
    sexo: Mapped[str] = mapped_column(String)
    experiencia_entrenamiento: Mapped[str] = mapped_column(String)
    tiempo_entrenamiento: Mapped[int] = mapped_column()
    preferencias: Mapped[list[str]] = mapped_column(ARRAY(String))
    objetivos_entreno: Mapped[list[str]] = mapped_column(ARRAY(String))
    nombre_deporte: Mapped[str] = mapped_column(String)
    aspectos_a_mejorar: Mapped[str] = mapped_column(String)
    semanas: Mapped[int] = mapped_column()
    tipo_dieta: Mapped[str] = mapped_column(String)
    objetivos_dieta: Mapped[list[str]] = mapped_column(ARRAY(String))
    alergias: Mapped[str] = mapped_column(String)
    alimentos_no_deseados: Mapped[str] = mapped_column(String)
    tiempo_comidas: Mapped[str] = mapped_column(String)
    comidas_al_dia: Mapped[int] = mapped_column()
    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Gimnasio(Base):
    __tablename__ = "gimnasios"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    ciudad: Mapped[str] = mapped_column(String)
    direccion: Mapped[str] = mapped_column(String)
    descripcion: Mapped[str] = mapped_column(String)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuarios = relationship("UsuarioGimnasio", back_populates="gimnasio", cascade="all, delete-orphan")
    infraestructura = relationship("InfraestructuraGimnasio", back_populates="gimnasio", cascade="all, delete-orphan")

class UsuarioGimnasio(Base):
    __tablename__ = "usuarios_gimnasios"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    gimnasio_id: Mapped[int] = mapped_column(ForeignKey("gimnasios.id"))
    es_principal: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("usuario_id", "gimnasio_id", name="uq_usuario_gimnasio"),)

    gimnasio = relationship("Gimnasio", back_populates="usuarios")
    usuario = relationship("Usuario", back_populates="gimnasios")

class InfraestructuraGimnasio(Base):
    __tablename__ = "infraestructura_gimnasio"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    gimnasio_id: Mapped[int] = mapped_column(ForeignKey("gimnasios.id"), nullable=False)
    nombre_maquina: Mapped[str] = mapped_column(String, nullable=False)
    modelo: Mapped[str] = mapped_column(String, nullable=True)
    imagen_url: Mapped[str] = mapped_column(String, nullable=True)
    fecha_subida: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    gimnasio = relationship("Gimnasio", back_populates="infraestructura")

class Amistad(Base):
    __tablename__ = "amistades"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    amigo_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    usuario_id_1 = mapped_column(Integer, ForeignKey("usuarios.id"))
    usuario_id_2 = mapped_column(Integer, ForeignKey("usuarios.id"))
    estado: Mapped[str] = mapped_column(String, default="pendiente")
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UsuarioAmigo(Base):
    __tablename__ = "usuarios_amigos"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    usuario_id_1 = mapped_column(Integer, ForeignKey("usuarios.id"))
    usuario_id_2 = mapped_column(Integer, ForeignKey("usuarios.id"))
    amigo_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    estado: Mapped[str] = mapped_column(String, default="pendiente")
    __table_args__ = (UniqueConstraint("usuario_id", "amigo_id", name="uq_amigos_unicos"),)

class VinculacionProfesional(Base):
    __tablename__ = "vinculaciones_profesionales"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    gimnasio_id: Mapped[int] = mapped_column(ForeignKey("gimnasios.id"), nullable=False)
    rol: Mapped[str] = mapped_column(String, nullable=False)
    fecha_vinculacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class EntrenadorFavorito(Base):
    __tablename__ = "entrenadores_favoritos"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    entrenador_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    __table_args__ = (UniqueConstraint("usuario_id", "entrenador_id", name="uq_entrenador_favorito"),)

class DietistaFavorito(Base):
    __tablename__ = "dietistas_favoritos"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    dietista_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    __table_args__ = (UniqueConstraint("usuario_id", "dietista_id", name="uq_dietista_favorito"),)

class UsuarioProfesional(Base):
    __tablename__ = "usuario_profesional"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    profesional_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    tipo: Mapped[str] = mapped_column(String)
    aceptado: Mapped[bool] = mapped_column(Boolean, default=True)

class DietaGenerada(Base):
    __tablename__ = "dietas_generadas"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    datos_entrada: Mapped[str] = mapped_column(Text)
    dieta_json: Mapped[str] = mapped_column(Text)

    usuario = relationship("Usuario", back_populates="dietas_generadas")

class PlanMixtoGenerado(Base):
    __tablename__ = "planes_mixtos_generados"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    contenido_json: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", back_populates="planes_mixtos_generados")

class EjercicioRutina(Base):
    __tablename__ = "ejercicios_rutina"
    id: Mapped[int] = mapped_column(primary_key=True)
    rutina_id: Mapped[int] = mapped_column(ForeignKey("rutinas.id"))
    nombre: Mapped[str] = mapped_column(String)
    descripcion: Mapped[str] = mapped_column(String)
    series: Mapped[int] = mapped_column()
    repeticiones: Mapped[int] = mapped_column()
    imagen_url: Mapped[str] = mapped_column(String)
    grupo_muscular: Mapped[str] = mapped_column(String)
    equipo: Mapped[str] = mapped_column(String)

class Rutina(Base):
    __tablename__ = "rutinas"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), default="Rutina personalizada")
    descripcion: Mapped[str] = mapped_column(Text)
    rutina_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    semanas: Mapped[int] = mapped_column(nullable=True)

    usuario = relationship("Usuario", back_populates="rutinas")

class Notificacion(Base):
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))  # receptor
    tipo = Column(String)   # 'amistad', 'rutina', 'dieta', etc
    contenido = Column(String)  # texto descriptivo
    fecha = Column(DateTime)
    leida = Column(Boolean, default=False)
    datos_extra = Column(JSON, nullable=True)  # id de la solicitud, rutina, etc

class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    rutina_id: Mapped[int | None] = mapped_column(ForeignKey("rutinas.id", ondelete="SET NULL"), nullable=True)  # si existe
    plan_id:   Mapped[int | None] = mapped_column(ForeignKey("planes.id",  ondelete="SET NULL"), nullable=True)  # fallback
    semana:    Mapped[int] = mapped_column()
    dia_nombre: Mapped[str] = mapped_column(Text)  # "Lunes", etc.
    fecha:     Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_minutos: Mapped[float | None] = mapped_column(Numeric(7,2))
    descanso_total_min: Mapped[float] = mapped_column(Numeric(7,2), default=0)
    estado:    Mapped[str] = mapped_column(String(20), default="creada")
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ejercicios: Mapped[list["ExerciseSession"]] = relationship(
        "ExerciseSession", back_populates="sesion", cascade="all, delete-orphan"
    )

class ExerciseSession(Base):
    __tablename__ = "exercise_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    workout_session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True)
    nombre_ejercicio: Mapped[str] = mapped_column(Text)
    imagen_url: Mapped[str | None] = mapped_column(Text)
    orden_plan: Mapped[int | None] = mapped_column()
    orden_real: Mapped[int | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutos_activo:   Mapped[float | None] = mapped_column(Numeric(7,2))
    descanso_minutos: Mapped[float] = mapped_column(Numeric(7,2), default=0)
    completado: Mapped[bool] = mapped_column(Boolean, default=False)
    notas: Mapped[str | None] = mapped_column(Text)
    sugerencias_ia: Mapped[dict | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion: Mapped["WorkoutSession"] = relationship("WorkoutSession", back_populates="ejercicios")
    series: Mapped[list["SetRecord"]] = relationship("SetRecord", back_populates="ejercicio", cascade="all, delete-orphan")
    descansos: Mapped[list["RestPeriod"]] = relationship("RestPeriod", back_populates="ejercicio", cascade="all, delete-orphan")

class SetRecord(Base):
    __tablename__ = "set_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_session_id: Mapped[int] = mapped_column(ForeignKey("exercise_sessions.id", ondelete="CASCADE"), index=True)
    set_index: Mapped[int] = mapped_column()
    peso: Mapped[float | None] = mapped_column(Numeric(8,2))
    repes: Mapped[int | None] = mapped_column()
    rpe:   Mapped[float | None] = mapped_column(Numeric(4,2))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    descanso_posterior_s: Mapped[float | None] = mapped_column(Numeric(8,2))
    extra_json: Mapped[dict | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ejercicio: Mapped["ExerciseSession"] = relationship("ExerciseSession", back_populates="series")

class RestPeriod(Base):
    __tablename__ = "rest_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    workout_session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True)
    exercise_session_id: Mapped[int | None] = mapped_column(ForeignKey("exercise_sessions.id", ondelete="CASCADE"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(32))  # 'entre_series' | 'entre_ejercicios' | 'manual'
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duracion_s: Mapped[float | None] = mapped_column(Numeric(10,2))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ejercicio: Mapped["ExerciseSession"] = relationship("ExerciseSession", back_populates="descansos")

class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)

class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), index=True)
    weight: Mapped[float] = mapped_column()
    reps: Mapped[int] = mapped_column()
    rir: Mapped[int] = mapped_column(default=2)         # opcional: Reps In Reserve
    rest_sec: Mapped[int] = mapped_column(default=120)  # descanso
    bodyweight: Mapped[float] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    exercise = relationship("Exercise")

#class ProgressDaily(Base):
 #   __tablename__ = "progress_daily"

  #  id: Mapped[int] = mapped_column(Integer, primary_key=True)
   # user_id: Mapped[int] = mapped_column(
    #    Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
    #)
    #date: Mapped[date] = mapped_column(Date, nullable=False)

    #bodyweight_kg: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    #calories_in: Mapped[Optional[int]] = mapped_column(Integer)
    #protein_g: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    #carbs_g: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    #fat_g: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    #steps: Mapped[Optional[int]] = mapped_column(Integer)
    #notes: Mapped[Optional[str]] = mapped_column(Text)

    #created_at: Mapped[datetime] = mapped_column(
     #   DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    #)
    #updated_at: Mapped[datetime] = mapped_column(
     #   DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    #)

    #usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="progress_daily")