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
