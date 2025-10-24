from pydantic import BaseModel, EmailStr, Field
from typing import List
from datetime import datetime
from pydantic import BaseModel, Field, conint, confloat
from datetime import date
from typing import Optional


class UsuarioBase(BaseModel):
    nombre: str
    email: EmailStr
    rol: str

class UsuarioCreate(UsuarioBase):
    contraseña: str

class UsuarioOut(UsuarioBase):
    id: int
    fecha_registro: datetime

    model_config = {
        "from_attributes": True
    }

# --- Formulario de Cliente (Entrenamiento) ---

class FormularioClienteBase(BaseModel):
    altura_cm: Optional[int]
    edad: Optional[int]
    experiencia_entrenamiento: Optional[str]
    tiempo_disponible: Optional[str]
    sexo: Optional[str]
    preferencias_entrenamiento: List[str] = Field(default_factory=list)
    objetivos_entrenamiento: List[str] = Field(default_factory=list)
    deporte_especifico: Optional[str]
    aspectos_mejorar: Optional[str]
    semanas: Optional[int]  # Añadido para generación de rutina

class FormularioClienteCreate(FormularioClienteBase):
    pass

class FormularioClienteDB(FormularioClienteBase):
    id: int
    usuario_id: int
    fecha_creacion: datetime

    model_config = {
        "from_attributes": True
    }

# --- Formulario de Dieta ---

# schemas.py
from pydantic import BaseModel, Field, ConfigDict, field_validator

# schemas.py
from pydantic import BaseModel, Field, ConfigDict, field_validator

class FormularioDietaCreate(BaseModel):
    altura: int = Field(..., ge=100, le=250)
    edad: int = Field(..., ge=1, le=120)
    sexo: str = Field(..., pattern="^(hombre|mujer|otro)$")
    objetivos: List[str] = Field(default_factory=list)
    calorias_objetivo: int = Field(2000, ge=800, le=6000)
    preferencias_alimentarias: List[str] = Field(default_factory=list)
    # el front manda "semanas" ⇒ lo aceptamos, pero el atributo expuesto es duracion_dieta
    duracion_dieta: int = Field(12, ge=1, le=52, alias="semanas")

    tipo_dieta: Optional[str] = None
    alergias: Optional[str] = None
    alimentos_no_deseados: Optional[str] = None
    tiempo_comidas: Optional[str] = None
    comidas_al_dia: int = Field(3, ge=1, le=10)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("preferencias_alimentarias", mode="before")
    @classmethod
    def _coerce_pref(cls, v):
        if v is None: return []
        if isinstance(v, str): return [v]
        return list(v)

    @field_validator("objetivos", mode="before")
    @classmethod
    def _coerce_obj(cls, v):
        if v is None: return []
        if isinstance(v, str): return [v]
        return list(v)

class FormularioDietaDB(FormularioDietaCreate):
    id: int
    usuario_id: int
    fecha: datetime

    model_config = {
        "from_attributes": True
    }

# --- Formulario Mixto (Entreno + Dieta) ---

class FormularioMixtoCreate(BaseModel):
    # Entrenamiento
    altura_cm: Optional[int]
    edad: Optional[int]
    sexo: Optional[str]
    experiencia_entrenamiento: Optional[str]
    tiempo_disponible: Optional[str]
    preferencias_entrenamiento: List[str] = Field(default_factory=list)
    objetivos_entrenamiento: List[str] = Field(default_factory=list)
    deporte_especifico: Optional[str]
    aspectos_mejorar: Optional[str]
    semanas: Optional[int]
    # Dieta
    calorias_objetivo: Optional[int]
    tipo_dieta: Optional[str]
    preferencias_alimentarias: Optional[str]
    alergias: Optional[str]
    alimentos_no_deseados: Optional[str]
    tiempo_comidas: Optional[str]
    comidas_al_dia: Optional[int]
    semanas: Optional[int]

class FormularioMixtoDB(FormularioMixtoCreate):
    id: int
    usuario_id: int
    fecha: datetime

    model_config = {
        "from_attributes": True
    }


class ProgressDailyBase(BaseModel):
    date: date
    bodyweight_kg: Optional[confloat(ge=20, le=400)] = None
    calories_in: Optional[conint(ge=0, le=10000)] = None
    protein_g: Optional[confloat(ge=0, le=1000)] = None
    carbs_g: Optional[confloat(ge=0, le=2000)] = None
    fat_g: Optional[confloat(ge=0, le=1000)] = None
    steps: Optional[conint(ge=0, le=200000)] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

class ProgressDailyCreate(ProgressDailyBase):
    pass

class ProgressDailyUpdate(BaseModel):
    # todos opcionales en el patch
    bodyweight_kg: Optional[confloat(ge=20, le=400)] = None
    calories_in: Optional[conint(ge=0, le=10000)] = None
    protein_g: Optional[confloat(ge=0, le=1000)] = None
    carbs_g: Optional[confloat(ge=0, le=2000)] = None
    fat_g: Optional[confloat(ge=0, le=1000)] = None
    steps: Optional[conint(ge=0, le=200000)] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

class ProgressDailyOut(ProgressDailyBase):
    id: int

    class Config:
        from_attributes = True