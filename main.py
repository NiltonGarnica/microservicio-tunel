"""Rutas del microservicio: /health, /suma y /process."""

import math
import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from scalar_fastapi import get_scalar_api_reference
from sqlalchemy.orm import Session

# Importar database primero: es quien carga el archivo .env.
from database import Persona, crear_tablas, get_db

API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()
if not API_BEARER_TOKEN:
    # Sin token el servicio no arranca: mejor un error claro que rutas
    # "protegidas" por un token vacío.
    raise RuntimeError(
        "Falta API_BEARER_TOKEN. Copia .env.example a .env y escribe un token "
        "(mira el README para generarlo)."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    crear_tablas()  # se ejecuta una vez, al arrancar Uvicorn
    yield


app = FastAPI(
    title="Microservicio de práctica",
    description="API local para practicar Cloudflare Tunnel y ngrok.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def error_de_validacion(request: Request, exc: RequestValidationError):
    # El error por defecto de FastAPI repite el valor recibido. Si ese valor
    # es NaN o Infinity no se puede escribir en JSON y la respuesta acabaría
    # en 500. Devolvemos solo dónde está el error y qué falló.
    errores = [
        {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errores})


# ---------- Bearer token ----------

# HTTPBearer hace que Swagger muestre el botón "Authorize".
# auto_error=False nos deja responder nosotros con 401 cuando falta el token.
esquema_bearer = HTTPBearer(
    auto_error=False,
    description="Pega aquí el valor de API_BEARER_TOKEN de tu archivo .env",
)


def verificar_token(
    credenciales: Annotated[
        HTTPAuthorizationCredentials | None, Depends(esquema_bearer)
    ],
) -> None:
    # compare_digest compara en tiempo constante, para no filtrar pistas
    # sobre el token según cuánto tarde la comparación.
    valido = credenciales is not None and secrets.compare_digest(
        credenciales.credentials.encode("utf-8"), API_BEARER_TOKEN.encode("utf-8")
    )
    if not valido:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ausente o incorrecto",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------- Modelos de entrada y salida (Pydantic) ----------

# Acepta enteros y decimales; rechaza NaN, Infinity, textos ("3") y booleanos.
NumeroFinito = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class SumaEntrada(BaseModel):
    a: NumeroFinito
    b: NumeroFinito

    model_config = ConfigDict(json_schema_extra={"example": {"a": 3, "b": 5.2}})


class SumaSalida(BaseModel):
    resultado: float


def texto(max_length: int):
    """Texto obligatorio: quita espacios de los extremos y exige contenido."""
    return Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length),
    ]


class PersonaEntrada(BaseModel):
    nombre: texto(120)
    # Es un str: "+59170000000" y "0044..." se guardan tal cual.
    telefono: Annotated[
        str,
        StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9]{6,15}$"),
    ]
    email: EmailStr
    genero: texto(30)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "nombre": "Ana Pérez",
                "telefono": "+59170000000",
                "email": "ana@example.com",
                "genero": "femenino",
            }
        }
    )


class PersonaCreada(BaseModel):
    id: int


# ---------- Rutas ----------


@app.get("/health", tags=["público"])
def health():
    return {"status": "ok"}


# Otra página de documentación, como /docs, que lee el mismo /openapi.json.
# include_in_schema=False: es una página para personas, no una ruta de la API.
@app.get("/scalar", include_in_schema=False)
def scalar():
    return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)


@app.post(
    "/suma",
    response_model=SumaSalida,
    tags=["protegido"],
    dependencies=[Depends(verificar_token)],
)
def suma(datos: SumaEntrada):
    resultado = datos.a + datos.b
    # Dos números finitos muy grandes pueden desbordar a infinito.
    if not math.isfinite(resultado):
        raise HTTPException(
            status_code=422,
            detail="El resultado no es un número finito",
        )
    return {"resultado": resultado}


@app.post(
    "/process",
    response_model=PersonaCreada,
    status_code=status.HTTP_201_CREATED,
    tags=["protegido"],
    dependencies=[Depends(verificar_token)],
)
def process(datos: PersonaEntrada, db: Annotated[Session, Depends(get_db)]):
    persona = Persona(**datos.model_dump())
    db.add(persona)
    db.commit()  # aquí se ejecuta el INSERT y la base genera el id
    return {"id": persona.id}
