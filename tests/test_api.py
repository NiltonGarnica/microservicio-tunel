"""Pruebas de las rutas con una base SQLite temporal.

Uso:  python -m pytest -v
"""

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TOKEN = "token-de-prueba"


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    # Variables de entorno antes de importar la app: no usa tu .env ni tu base real.
    monkeypatch.setenv("API_BEARER_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'prueba.db'}")
    for modulo in ("main", "database"):
        sys.modules.pop(modulo, None)

    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}
PERSONA = {"nombre": "Ana Pérez", "telefono": "+59170000000", "email": "ana@example.com", "genero": "femenino"}


def test_health(cliente):
    assert cliente.get("/health").json() == {"status": "ok"}


def test_scalar_muestra_la_documentacion(cliente):
    r = cliente.get("/scalar")
    assert r.status_code == 200
    assert "/openapi.json" in r.text


def test_suma(cliente):
    r = cliente.post("/suma", json={"a": 3, "b": 5.2}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"resultado": pytest.approx(8.2)}


def test_suma_sin_token_da_401(cliente):
    assert cliente.post("/suma", json={"a": 1, "b": 2}).status_code == 401


def test_suma_con_texto_da_422(cliente):
    assert cliente.post("/suma", json={"a": "3", "b": 2}, headers=AUTH).status_code == 422


def test_process_guarda_y_devuelve_id(cliente):
    r1 = cliente.post("/process", json=PERSONA, headers=AUTH)
    r2 = cliente.post("/process", json=PERSONA, headers=AUTH)
    assert r1.status_code == 201
    assert r2.json()["id"] == r1.json()["id"] + 1


def test_process_correo_invalido_da_422(cliente):
    datos = {**PERSONA, "email": "no-es-correo"}
    assert cliente.post("/process", json=datos, headers=AUTH).status_code == 422


# ---------- /ai_validator ----------

URL_PRODUCTO = "https://www.ejemplo.com/tarjeta-grafica"
FICHA = {
    "es_producto": True,
    "nombre": "Radeon RX 7600 XT",
    "marca": "AMD",
    "categoria": "Tarjeta gráfica",
    "precio": None,
    "especificaciones": [{"nombre": "Memoria", "valor": "16 GB GDDR6"}],
    "resumen": "Tarjeta gráfica para juegos en 1080p.",
}


@pytest.fixture()
def ia_simulada(cliente, monkeypatch):
    """Reemplaza la descarga y el LLM: las pruebas no salen a internet ni gastan saldo."""
    import ai_validator

    monkeypatch.setattr(ai_validator, "descargar_pagina", lambda url: (url, "Radeon RX 7600 XT 16 GB"))
    monkeypatch.setattr(
        ai_validator, "pedir_ficha", lambda url, texto: ai_validator.FichaProducto(**FICHA)
    )
    return cliente


def test_ai_validator_sin_token_da_401(cliente):
    assert cliente.post("/ai_validator", json={"url": URL_PRODUCTO}).status_code == 401


def test_ai_validator_guarda_la_ficha(ia_simulada):
    r = ia_simulada.post("/ai_validator", json={"url": URL_PRODUCTO}, headers=AUTH)
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["ficha"]["nombre"] == "Radeon RX 7600 XT"

    from database import FichaGuardada, SessionLocal

    with SessionLocal() as db:
        guardada = db.get(FichaGuardada, cuerpo["id"])
    assert guardada.url == URL_PRODUCTO
    assert guardada.ficha["especificaciones"][0]["valor"] == "16 GB GDDR6"


def test_ai_validator_rechaza_direcciones_locales(cliente):
    r = cliente.post("/ai_validator", json={"url": "http://127.0.0.1:5432/"}, headers=AUTH)
    assert r.status_code == 422
    assert "privada o local" in r.json()["detail"]


def test_ai_validator_sin_clave_de_openrouter_da_503(cliente, monkeypatch):
    import ai_validator

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ai_validator, "descargar_pagina", lambda url: (url, "texto"))
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO}, headers=AUTH)
    assert r.status_code == 503


def test_ai_validator_respuesta_invalida_del_llm_da_502(cliente, monkeypatch):
    import httpx

    import ai_validator

    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(ai_validator, "descargar_pagina", lambda url: (url, "texto"))
    respuesta = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "esto no es JSON"}}]},
        request=httpx.Request("POST", ai_validator.OPENROUTER_URL),
    )
    monkeypatch.setattr(ai_validator.httpx, "post", lambda *a, **k: respuesta)
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO}, headers=AUTH)
    assert r.status_code == 502


def test_extrae_solo_el_texto_visible():
    import ai_validator

    lector = ai_validator._TextoVisible()
    lector.feed(
        "<html><head><title>RX 7600</title><style>p{}</style></head>"
        "<body><script>var x=1</script><p>16 GB  GDDR6</p></body></html>"
    )
    assert lector.titulo == "RX 7600"
    assert lector.lineas == ["16 GB GDDR6"]
