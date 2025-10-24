from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.models import FormularioCliente, FormularioDieta, FormularioMixto
from app.schemas import FormularioClienteCreate, FormularioDietaCreate, FormularioMixtoCreate
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

# ---------- USUARIOS ----------
async def get_usuario_por_email(db: AsyncSession, email: str):
    result = await db.execute(select(models.Usuario).filter(models.Usuario.email == email))
    return result.scalars().first()

async def crear_usuario(db: AsyncSession, usuario):
    hashed_password = hash_password(usuario.contraseña)
    db_usuario = models.Usuario(
        nombre=usuario.nombre,
        email=usuario.email,
        contraseña=hashed_password,
        rol=usuario.rol
    )
    db.add(db_usuario)
    await db.commit()
    await db.refresh(db_usuario)
    return db_usuario

# ---------- FORMULARIO CLIENTE ----------
async def get_formulario_por_usuario(db: AsyncSession, usuario_id: int):
    result = await db.execute(select(FormularioCliente).where(FormularioCliente.usuario_id == usuario_id))
    return result.scalars().first()

async def crear_o_actualizar_formulario(db: AsyncSession, usuario_id: int, datos: FormularioClienteCreate):
    existente = await get_formulario_por_usuario(db, usuario_id)
    if existente:
        for field, value in datos.dict().items():
            setattr(existente, field, value)
    else:
        nuevo = FormularioCliente(usuario_id=usuario_id, **datos.dict())
        db.add(nuevo)
    await db.commit()

# ---------- FORMULARIO ENTRENO ----------
async def get_formulario_entreno(db: AsyncSession, usuario_id: int):
    result = await db.execute(select(models.FormularioCliente).where(models.FormularioCliente.usuario_id == usuario_id))
    return result.scalars().first()

async def crear_o_actualizar_formulario_entreno(db: AsyncSession, usuario_id: int, datos: dict):
    existente = await get_formulario_entreno(db, usuario_id)
    if existente:
        for key, value in datos.items():
            setattr(existente, key, value)
    else:
        nuevo = models.FormularioCliente(usuario_id=usuario_id, **datos)
        db.add(nuevo)
    await db.commit()

# ---------- FORMULARIO DIETA ----------
async def get_formulario_dieta(db: AsyncSession, usuario_id: int):
    result = await db.execute(select(models.FormularioDieta).where(models.FormularioDieta.usuario_id == usuario_id))
    return result.scalars().first()

async def crear_o_actualizar_formulario_dieta(db: AsyncSession, usuario_id: int, datos: dict):
    existente = await get_formulario_dieta(db, usuario_id)
    if existente:
        for key, value in datos.items():
            setattr(existente, key, value)
    else:
        nuevo = models.FormularioDieta(usuario_id=usuario_id, **datos)
        db.add(nuevo)
    await db.commit()

# ---------- FORMULARIO MIXTO ----------
async def get_formulario_mixto(db: AsyncSession, usuario_id: int):
    result = await db.execute(select(models.FormularioMixto).where(models.FormularioMixto.usuario_id == usuario_id))
    return result.scalars().first()

async def crear_o_actualizar_formulario_mixto(db: AsyncSession, usuario_id: int, datos: dict):
    existente = await get_formulario_mixto(db, usuario_id)
    if existente:
        for key, value in datos.items():
            setattr(existente, key, value)
    else:
        nuevo = models.FormularioMixto(usuario_id=usuario_id, **datos)
        db.add(nuevo)
    await db.commit()

