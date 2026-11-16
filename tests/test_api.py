"""Pruebas de las rutas con una base SQLite temporal.

Uso:  python -m pytest -v
"""

import json
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
    monkeypatch.setenv("WEBHOOK_SECRET", "secreto-de-prueba")
    monkeypatch.setenv("PERMITIR_WEBHOOK_LOCAL", "true")
    for modulo in ("main", "database", "ai_validator"):
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


# ---------- /ai_validator (asíncrono, con webhook) ----------

URL_PRODUCTO = "https://www.ejemplo.com/tarjeta-grafica"
WEBHOOK = "https://receptor.ejemplo.com/avisos"
FICHA = {
    "es_producto": True,
    "nombre": "Radeon RX 7600 XT",
    "marca": "AMD",
    "categoria": "Tarjeta gráfica",
    "precio": "$329",
    "especificaciones": [{"nombre": "Memoria", "valor": "16 GB GDDR6"}],
    "resumen": "Tarjeta gráfica para juegos en 1080p.",
}


class RespuestaFalsa:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture()
def ia_simulada(cliente, monkeypatch):
    """Reemplaza Lightpanda, el LLM y el envío del webhook: no sale a internet ni gasta saldo.

    Los webhooks enviados quedan en la lista `enviados` para revisarlos.
    """
    import ai_validator

    enviados = []
    monkeypatch.setattr(ai_validator, "verificar_host_publico", lambda url: None)
    monkeypatch.setattr(ai_validator, "obtener_dom", lambda url: (url, "Radeon RX 7600 XT 16 GB"))
    monkeypatch.setattr(ai_validator, "pedir_ficha", lambda url, texto: ai_validator.FichaProducto(**FICHA))
    monkeypatch.setattr(ai_validator.time, "sleep", lambda s: None)

    def post_falso(url, content, headers, timeout):
        enviados.append({"url": url, "cuerpo": content, "cabeceras": headers})
        return RespuestaFalsa(200)

    monkeypatch.setattr(ai_validator.httpx, "post", post_falso)
    return cliente, enviados


def test_ai_validator_sin_token_da_401(cliente):
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO, "webhook_url": WEBHOOK})
    assert r.status_code == 401


def test_ai_validator_exige_webhook(cliente):
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO}, headers=AUTH)
    assert r.status_code == 422


def test_ai_validator_responde_202_y_avisa_por_webhook(ia_simulada):
    import ai_validator

    cliente, enviados = ia_simulada
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO, "webhook_url": WEBHOOK}, headers=AUTH)
    assert r.status_code == 202
    trabajo_id = r.json()["id"]
    assert r.json()["consultar_en"] == f"/ai_validator/{trabajo_id}"

    # El webhook se envió una vez, firmado, con la ficha completa.
    assert len(enviados) == 1
    aviso = enviados[0]
    assert aviso["url"] == WEBHOOK
    assert aviso["cabeceras"]["X-Firma-Sha256"] == ai_validator.firmar(aviso["cuerpo"])
    cuerpo = json.loads(aviso["cuerpo"])
    assert cuerpo["evento"] == "ai_validator.completado"
    assert cuerpo["ficha"]["precio"] == "$329"

    # El trabajo quedó guardado como completado.
    estado = cliente.get(f"/ai_validator/{trabajo_id}", headers=AUTH).json()
    assert estado["estado"] == "completado"
    assert estado["ficha"]["nombre"] == "Radeon RX 7600 XT"
    assert estado["webhook_estado"] == "entregado: HTTP 200"
    assert estado["webhook_intentos"] == 1


def test_ai_validator_avisa_cuando_falla_la_pagina(ia_simulada, monkeypatch):
    import ai_validator

    cliente, enviados = ia_simulada

    def falla(url):
        raise ai_validator.ErrorDePagina("La página respondió HTTP 404")

    monkeypatch.setattr(ai_validator, "obtener_dom", falla)
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO, "webhook_url": WEBHOOK}, headers=AUTH)
    cuerpo = json.loads(enviados[0]["cuerpo"])
    assert cuerpo["evento"] == "ai_validator.fallido"
    assert cuerpo["error"] == "La página respondió HTTP 404"
    estado = cliente.get(f"/ai_validator/{r.json()['id']}", headers=AUTH).json()
    assert estado["estado"] == "fallido"


def test_ai_validator_reintenta_el_webhook(ia_simulada, monkeypatch):
    import ai_validator

    cliente, enviados = ia_simulada

    def receptor_caido(url, content, headers, timeout):
        enviados.append(url)
        return RespuestaFalsa(500)

    monkeypatch.setattr(ai_validator.httpx, "post", receptor_caido)
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO, "webhook_url": WEBHOOK}, headers=AUTH)
    assert len(enviados) == ai_validator.REINTENTOS_WEBHOOK
    estado = cliente.get(f"/ai_validator/{r.json()['id']}", headers=AUTH).json()
    assert estado["estado"] == "completado"
    assert estado["webhook_estado"] == "falló: HTTP 500"


def test_ai_validator_rechaza_direcciones_locales(cliente):
    r = cliente.post(
        "/ai_validator", json={"url": "http://127.0.0.1:5432/", "webhook_url": WEBHOOK}, headers=AUTH
    )
    assert r.status_code == 422
    assert "privada o local" in r.json()["detail"]


def test_webhook_local_solo_si_se_permite(cliente, monkeypatch):
    import ai_validator

    real = ai_validator.verificar_host_publico
    # La página de ejemplo pasa sin consultar DNS; el webhook usa la regla real.
    monkeypatch.setattr(
        ai_validator, "verificar_host_publico", lambda url: None if url == URL_PRODUCTO else real(url)
    )
    monkeypatch.setenv("PERMITIR_WEBHOOK_LOCAL", "false")
    datos = {"url": URL_PRODUCTO, "webhook_url": "http://127.0.0.1:8000/webhook_demo"}
    r = cliente.post("/ai_validator", json=datos, headers=AUTH)
    assert r.status_code == 422
    assert "privada o local" in r.json()["detail"]


def test_estado_de_trabajo_inexistente_da_404(cliente):
    assert cliente.get("/ai_validator/999", headers=AUTH).status_code == 404


def test_webhook_demo_acepta_firma_valida_y_guarda(cliente):
    import ai_validator
    from database import SessionLocal, WebhookRecibido

    cuerpo = json.dumps({"id": 7, "estado": "completado"}).encode()
    r = cliente.post("/webhook_demo", content=cuerpo, headers={"X-Firma-Sha256": ai_validator.firmar(cuerpo)})
    assert r.status_code == 200
    with SessionLocal() as db:
        guardado = db.query(WebhookRecibido).one()
    assert guardado.trabajo_id == 7
    assert guardado.firma_valida is True


def test_webhook_demo_rechaza_firma_falsa(cliente):
    cuerpo = json.dumps({"id": 7}).encode()
    r = cliente.post("/webhook_demo", content=cuerpo, headers={"X-Firma-Sha256": "firma-inventada"})
    assert r.status_code == 401


def test_respuesta_invalida_del_llm_es_error(monkeypatch):
    import httpx

    import ai_validator

    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-de-prueba")
    respuesta = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "esto no es JSON"}}]},
        request=httpx.Request("POST", ai_validator.OPENROUTER_URL),
    )
    monkeypatch.setattr(ai_validator.httpx, "post", lambda *a, **k: respuesta)
    with pytest.raises(ai_validator.ErrorDelLLM):
        ai_validator.pedir_ficha(URL_PRODUCTO, "texto")


def test_extrae_solo_el_texto_visible():
    import ai_validator

    html = (
        "<html><head><title>RX 7600</title><style>p{}</style></head>"
        "<body><script>var x=1</script><p>16 GB  GDDR6</p></body></html>"
    )
    assert ai_validator.texto_visible(html) == "16 GB GDDR6"


def test_get_webhook_demo_muestra_lo_que_guardo_el_post(cliente):
    import ai_validator

    for trabajo in (1, 2):
        cuerpo = json.dumps({"id": trabajo, "estado": "completado"}).encode()
        cliente.post("/webhook_demo", content=cuerpo, headers={"X-Firma-Sha256": ai_validator.firmar(cuerpo)})

    assert cliente.get("/webhook_demo").status_code == 401  # pide el Bearer token
    r = cliente.get("/webhook_demo", headers=AUTH)
    assert r.status_code == 200
    avisos = r.json()
    assert [a["trabajo_id"] for a in avisos] == [2, 1]  # el más nuevo primero
    assert avisos[0]["firma_valida"] is True
    assert avisos[0]["cuerpo"]["estado"] == "completado"


# ---------- Misma página, misma ficha ----------


def _validar(cliente):
    r = cliente.post("/ai_validator", json={"url": URL_PRODUCTO, "webhook_url": WEBHOOK}, headers=AUTH)
    return cliente.get(f"/ai_validator/{r.json()['id']}", headers=AUTH).json()


def test_misma_pagina_reutiliza_la_ficha_sin_llamar_al_llm(ia_simulada, monkeypatch):
    import ai_validator

    cliente, _ = ia_simulada
    llamadas = []

    def llm_que_varia(url, texto):
        # Simula al LLM real: cada llamada devuelve una cantidad distinta.
        llamadas.append(texto)
        especificaciones = [{"nombre": f"Dato {i}", "valor": "x"} for i in range(24 + 3 * len(llamadas))]
        return ai_validator.FichaProducto(**{**FICHA, "especificaciones": especificaciones})

    monkeypatch.setattr(ai_validator, "pedir_ficha", llm_que_varia)
    primero, segundo = _validar(cliente), _validar(cliente)

    assert len(llamadas) == 1  # la segunda vez no se llamó al LLM
    assert segundo["ficha"] == primero["ficha"]
    assert len(segundo["ficha"]["especificaciones"]) == 27


def test_si_la_pagina_cambia_se_vuelve_a_llamar_al_llm(ia_simulada, monkeypatch):
    import ai_validator

    cliente, _ = ia_simulada
    llamadas = []
    textos = iter(["Precio $329", "Precio $299"])
    monkeypatch.setattr(ai_validator, "obtener_dom", lambda url: (url, next(textos)))
    monkeypatch.setattr(
        ai_validator, "pedir_ficha", lambda url, texto: llamadas.append(texto) or ai_validator.FichaProducto(**FICHA)
    )
    _validar(cliente)
    _validar(cliente)
    assert llamadas == ["Precio $329", "Precio $299"]


def test_un_trabajo_fallido_no_se_reutiliza(ia_simulada, monkeypatch):
    import ai_validator

    cliente, _ = ia_simulada
    respuestas = iter([ai_validator.ErrorDelLLM("OpenRouter respondió HTTP 500"), ai_validator.FichaProducto(**FICHA)])

    def llm(url, texto):
        r = next(respuestas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(ai_validator, "pedir_ficha", llm)
    assert _validar(cliente)["estado"] == "fallido"
    assert _validar(cliente)["estado"] == "completado"


def test_crear_tablas_agrega_la_columna_huella_a_una_base_antigua(tmp_path, monkeypatch):
    import sqlite3

    ruta = tmp_path / "antigua.db"
    with sqlite3.connect(ruta) as con:
        con.execute("CREATE TABLE validaciones (id INTEGER PRIMARY KEY, url TEXT, webhook_url TEXT, estado VARCHAR(20))")
        con.execute("INSERT INTO validaciones (url, webhook_url, estado) VALUES ('u', 'w', 'completado')")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ruta}")
    sys.modules.pop("database", None)
    import database

    database.crear_tablas()
    database.crear_tablas()  # una segunda vez no falla
    with sqlite3.connect(ruta) as con:
        columnas = [fila[1] for fila in con.execute("PRAGMA table_info(validaciones)")]
        filas = con.execute("SELECT COUNT(*) FROM validaciones").fetchone()[0]
    database.engine.dispose()
    assert "huella" in columnas
    assert filas == 1  # los datos anteriores siguen ahí
