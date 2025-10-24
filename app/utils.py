# app/utils.py
import os
import json
from .config import settings
from typing import List, Optional
from openai import AsyncOpenAI
from openai import AsyncOpenAI, BadRequestError, AuthenticationError
from fastapi import HTTPException
from .config import settings
import os
from typing import Optional
from jose import jwt, JWTError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app import crud
# ===========================
#  Cliente OpenAI (lazy-load)
# ===========================
# No rompemos el import si aún no hay key. La resolvemos al primer uso.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "akejngklaengkangkñ")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
_openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
async def get_current_user_from_token(token: str, db: AsyncSession) -> Optional[dict]:
    """
    Decodifica el JWT y devuelve {id, email, rol} si es válido.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        rol = payload.get("rol")
        if not email:
            return None
    except JWTError:
        return None

    usuario = await crud.get_usuario_por_email(db, email)
    if not usuario:
        return None

    return {"id": usuario.id, "email": email, "rol": rol}

def _get_client(api_key: str | None = None) -> AsyncOpenAI:
    key = (api_key or settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        # Lanza 401 controlado en vez de RuntimeError que se traduce en 500 genérico
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="OPENAI_API_KEY no está configurada")
    return AsyncOpenAI(api_key=key)

def construir_prompt(form_data, equipamiento, limitaciones, otros_datos):
    prompt = f"""
Eres un entrenador personal experto y fisioterapeuta, especializado en crear rutinas de ejercicio personalizadas, variadas y basadas en evidencia científica para obtener los mejores resultados de cada usuario. Genera una rutina detallada y adaptada para el siguiente usuario:

**Datos del usuario:**
- Edad: {form_data['edad']}
- Sexo: {form_data['sexo']}
- Altura: {form_data['altura_cm']} cm
- Experiencia en entrenamiento: {form_data['experiencia_entrenamiento']}
- Tiempo disponible a la semana: {form_data['tiempo_disponible']}
- Preferencias de entrenamiento: {form_data['preferencias_entrenamiento']}
- Objetivos principales: {form_data['objetivos_entrenamiento']}
- ¿Deporte específico?: {form_data.get('deporte_especifico', '')}
- Aspectos a mejorar: {form_data.get('aspectos_mejorar', '')}
- Equipamiento disponible: {equipamiento}
- Lesiones/limitaciones: {limitaciones}
- Otros datos relevantes: {otros_datos}
- Duración total de la rutina: {form_data['semanas']} semanas

**REQUISITO**
Diseña una rutina COMPLETA para la duración especificada. Incluye:
- Plan estructurado por semanas y días.
- Tipo de entrenamiento diario.
- Ejercicios concretos, series, repeticiones/duración.
- Motivo para cada ejercicio.
- Consejos y advertencias.
- Adapta si hay objetivo deportivo o limitaciones.
- Variedad y progresión.

**FORMATO DE RESPUESTA (JSON):**
{{
  "duracion": "{form_data['semanas']} semanas",
  "plan": [
    {{
      "semana": 1,
      "dias": [
        {{
          "dia": "Lunes",
          "tipo_entrenamiento": "Fuerza tren superior",
          "ejercicios": [
            {{
              "nombre": "Flexiones",
              "series": 4,
              "repeticiones": 12,
              "motivo": "Mejora la fuerza de pectorales y tríceps."
            }}
          ],
          "consejo": "Céntrate en la técnica y calienta bien antes."
        }}
      ]
    }}
  ],
  "consejos_generales": "Mantén una buena hidratación, escucha a tu cuerpo y ajusta los pesos si es necesario.",
  "advertencias": "Detén el ejercicio ante dolor agudo. Consulta a un profesional si tienes lesiones previas."
}}
"""
    return prompt

def construir_prompt_alternativas(ejercicio, grupo_muscular=None):
    prompt = f"""
Eres un entrenador personal experto en biomecánica y fisioterapia.

Sugiere **exactamente tres alternativas de ejercicio** para sustituir el ejercicio "{ejercicio}"{f" (grupo muscular principal: {grupo_muscular})" if grupo_muscular else ""}.
Cada alternativa debe trabajar el mismo grupo muscular o cumplir la misma función principal, pero variar en ejecución, equipamiento o dificultad.

Por cada alternativa, incluye:
- nombre
- breve descripción del movimiento
- una frase de por qué es una buena alternativa

Devuelve la respuesta en JSON, con esta estructura:

[
  {{
    "nombre": "Nombre del ejercicio alternativo",
    "descripcion": "Descripción concisa del movimiento y su función.",
    "motivo": "Por qué es buena alternativa.",
    "imagen_prompt": "Prompt en inglés para generar una imagen realista, clara, educativa del ejercicio."
  }},
  ...
]

No inventes datos, no repitas alternativas.
"""
    return prompt

def construir_prompt_mixto(form_data, otros_datos=""):
    prompt = f"""
Eres entrenador personal, nutricionista clínico y fisioterapeuta, especializado en crear **rutinas de entrenamiento y dietas personalizadas** basadas en evidencia científica. Tu objetivo es maximizar el progreso, salud y adherencia del usuario. Genera un **plan combinado** adaptado y realista.

**Datos del usuario:**
- Edad: {form_data['edad']}
- Sexo: {form_data['sexo']}
- Altura: {form_data['altura_cm']} cm
- Peso: {form_data.get('peso', 'N/A')} kg
- Experiencia en entrenamiento: {form_data.get('experiencia_entrenamiento', '')}
- Nivel de actividad física: {form_data.get('actividad_fisica', '')}
- Tiempo disponible para entrenar: {form_data.get('tiempo_disponible', '')}
- Preferencias de entrenamiento: {', '.join(form_data.get('preferencias_entrenamiento', []))}
- Objetivos principales: {', '.join(form_data.get('objetivos_entrenamiento', []))}
- Tipo de dieta preferida: {form_data.get('tipo_dieta', '')}
- Preferencias alimentarias: {form_data.get('preferencias_alimentarias', '')}
- Alergias o intolerancias: {form_data.get('alergias', '')}
- Número de comidas al día: {form_data.get('comidas_al_dia', '')}
- Deporte específico: {form_data.get('deporte_especifico', '')}
- Equipamiento disponible: {form_data.get('equipamiento', '')}
- Lesiones, limitaciones o enfermedades: {form_data.get('limitaciones', '')}
- Otros datos: {otros_datos}
- Duración total del plan: {form_data.get('duracion_mixta', '')}

**REQUISITO**
Diseña una planificación COMPLETA (entreno + dieta) para toda la duración. Responde **solo JSON**.
"""
    return prompt

def construir_prompt_dieta(form_data, otros_datos=""):
    # Usa .get con defaults sensatos
    edad = form_data.get("edad", "N/D")
    sexo = form_data.get("sexo", "N/D")
    altura = form_data.get("altura", "N/D")
    peso = form_data.get("peso", "N/D")
    objetivos = ", ".join(form_data.get("objetivos", []))
    actividad_fisica = form_data.get("actividad_fisica", "N/D")
    experiencia_dietas = form_data.get("experiencia_dietas", "N/D")
    tipo_dieta = form_data.get("tipo_dieta", "N/D")
    pref = form_data.get("preferencias_alimentarias", "N/D")
    alergias = form_data.get("alergias", "N/D")
    no_deseados = form_data.get("alimentos_no_deseados", "N/D")
    comidas = form_data.get("comidas_al_dia", "N/D")
    tiempo = form_data.get("tiempo_comidas", "N/D")
    semanas = form_data.get("semanas", "N/D")

    prompt = f"""
Eres un nutricionista clínico experto...
- Edad: {edad}
- Sexo: {sexo}
- Altura: {altura} cm
- Peso: {peso} kg
- Objetivos principales: {objetivos}
- Nivel de actividad física: {actividad_fisica}
- Experiencia previa con dietas: {experiencia_dietas}
- Tipo de dieta preferida: {tipo_dieta}
- Preferencias alimentarias: {pref}
- Alergias o intolerancias: {alergias}
- Alimentos que no desea incluir: {no_deseados}
- Número de comidas al día: {comidas}
- Momentos preferidos para comer: {tiempo}
- Contexto adicional: {otros_datos}
- Duración total de la dieta: {semanas}
...
"""
    return prompt


def _normalize_size(s: str | None) -> str:
    allowed = {"1024x1024", "1024x1536", "1536x1024", "auto"}
    if not s:
        return "1024x1024"
    s = s.lower().strip()
    if s in allowed:
        return s
    # mapeos legacy
    if s in {"256x256", "512x512"}:
        return "1024x1024"
    return "1024x1024"  # fallback seguro
# ===========================


#  Funciones IA (unificadas)
# ===========================
# app/utils.py
# app/utils.py
async def generar_imagen_ejercicio(nombre: str, motivo: str, size: str | None = None) -> str:
    client = _get_client()
    prompt = f"Ejercicio: {nombre}. Motivo: {motivo}"
    size = _normalize_size(size)
    try:
        resp = await client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
        )
        # prioriza b64 si existe, si no URL
        d = resp.data[0]
        if getattr(d, "b64_json", None):
            return f"data:image/png;base64,{d.b64_json}"
        if getattr(d, "url", None):
            return d.url
        raise RuntimeError("La API de imágenes no devolvió contenido útil")
    except AuthenticationError:
        raise HTTPException(401, "OpenAI: autenticación fallida (revisa tu API key)")
    except BadRequestError as e:
        raise HTTPException(
            400,
            f"OpenAI: parámetro inválido ({e.body.get('error',{}).get('param','?')}): "
            f"{e.body.get('error',{}).get('message','')}"
        )
    except Exception as e:
        # captura cualquier otra excepción (rate limit, red, etc.) -> 502 amigable
        raise HTTPException(status_code=502, detail=f"OpenAI imágenes: {type(e).__name__}: {e}")

async def generar_alternativas_ia(ejercicio: str, grupo_muscular: str = "", criterio: str = "movilidad", api_key: Optional[str] = None) -> List[str]:
    """
    Devuelve una lista de alternativas para un ejercicio (strings).
    Acepta que el modelo devuelva lista de strings o de objetos con 'nombre'.
    """
    client = _get_client(api_key)
    prompt = construir_prompt_alternativas(ejercicio, grupo_muscular)
    r = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    txt = r.choices[0].message.content.strip()

    # Intenta parsear como JSON
    try:
        data = json.loads(txt)
        if isinstance(data, list):
            # lista de strings o de objetos {"nombre": ...}
            out: List[str] = []
            for item in data:
                if isinstance(item, str):
                    out.append(item.strip())
                elif isinstance(item, dict) and item.get("nombre"):
                    out.append(str(item["nombre"]).strip())
            return [x for x in out if x]
    except Exception:
        pass

    # Fallback: separar por líneas (por si no vino un JSON limpio)
    alts = [line.strip("-• ").strip() for line in txt.splitlines() if line.strip()]
    return [a for a in alts if a and a.lower() != ejercicio.lower()][:5]

async def generar_rutina_ia(form_data, equipamiento: str = "", limitaciones: str = "", otros_datos: str = "", api_key: Optional[str] = None):
    """
    Genera rutina en formato dict (parseado).
    """
    client = _get_client(api_key)
    prompt = construir_prompt(form_data, equipamiento, limitaciones, otros_datos)
    r = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Responde ÚNICAMENTE con JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )
    txt = (r.choices[0].message.content or "").strip()

    # Extrae el primer bloque {...} para tolerar basura alrededor
    try:
        start = txt.index("{")
        end = txt.rindex("}") + 1
        return json.loads(txt[start:end])
    except Exception:
        # estructura mínima para no romper el flujo
        return {"duracion": "", "plan": [], "error": "Formato inesperado"}

async def generar_dieta_ia(formulario, api_key: Optional[str] = None):
    """
    Genera dieta en formato dict (parseado).
    """
    client = _get_client(api_key)
    prompt = construir_prompt_dieta(formulario)
    r = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Responde ÚNICAMENTE con JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=1800,
    )
    txt = (r.choices[0].message.content or "").strip()
    try:
        start = txt.index("{")
        end = txt.rindex("}") + 1
        return json.loads(txt[start:end])
    except Exception:
        return {"duracion": "", "plan": [], "error": "Formato inesperado"}

async def ajustar_rutina_ia(progreso_dia, api_key: Optional[str] = None):
    """
    Dado el progreso (sets/pesos/tiempos), devuelve lista de sugerencias por ejercicio:
      [ {"nombre": "...", "peso_sugerido": ..., "repeticiones_sugeridas": ...}, ... ]
    """
    client = _get_client(api_key)
    prompt = (
        "Eres entrenador personal. Con el siguiente progreso del usuario, sugiere el peso y "
        "repeticiones recomendadas por ejercicio para la próxima sesión. Devuelve SOLO un JSON válido "
        "con una lista de objetos con las claves 'nombre', 'peso_sugerido', 'repeticiones_sugeridas'.\n\n"
        f"{json.dumps(progreso_dia, ensure_ascii=False, indent=2)}"
    )
    r = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=800,
    )
    txt = (r.choices[0].message.content or "").strip()
    try:
        data = json.loads(txt)
        return data if isinstance(data, list) else []
    except Exception:
        return []
