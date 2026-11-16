"""Receptor de webhooks de prueba, aparte de la API, para VER llegar los avisos.

Simula el sistema de un cliente que recibe el resultado de /ai_validator.

Arranque (en otra terminal, con la API ya corriendo en el puerto 8000):
    .\\.venv\\Scripts\\python.exe -m uvicorn receptor_webhook:app --host 127.0.0.1 --port 9000

- Abre http://127.0.0.1:9000 en el navegador: la página se actualiza sola.
- En /ai_validator usa  "webhook_url": "http://127.0.0.1:9000/webhook"
"""

import hashlib
import hmac
import html
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv(Path(__file__).resolve().parent / ".env")
SECRETO = os.getenv("WEBHOOK_SECRET", "").encode("utf-8")

app = FastAPI(title="Receptor de webhooks (prueba)")
avisos: list[dict] = []  # en memoria: se borran al apagar el receptor


@app.post("/webhook")
async def recibir(request: Request):
    """Aquí llega el aviso que envía la API cuando termina un trabajo."""
    cuerpo = await request.body()
    firma_recibida = request.headers.get("X-Firma-Sha256", "")
    firma_esperada = hmac.new(SECRETO, cuerpo, hashlib.sha256).hexdigest()
    firma_valida = hmac.compare_digest(firma_recibida, firma_esperada)

    try:
        datos = json.loads(cuerpo)
    except ValueError:
        datos = {"cuerpo_no_json": cuerpo.decode("utf-8", errors="replace")}

    hora = datetime.now().strftime("%H:%M:%S")
    avisos.insert(0, {"hora": hora, "firma_valida": firma_valida, "datos": datos})

    ficha = datos.get("ficha") or {}
    print(f"\n🔔 [{hora}] ¡Llegó un aviso!")
    print(f"   Trabajo {datos.get('id')} | estado: {datos.get('estado')} | firma: {'válida ✅' if firma_valida else 'INVÁLIDA ❌'}")
    if ficha:
        print(f"   Producto: {ficha.get('nombre')} ({len(ficha.get('especificaciones', []))} especificaciones)")
    if datos.get("error"):
        print(f"   Error: {datos['error']}")

    if not firma_valida:
        return JSONResponse({"detail": "Firma inválida"}, status_code=401)
    return {"recibido": True}


@app.get("/cantidad")
def cantidad() -> int:
    return len(avisos)


@app.get("/", response_class=HTMLResponse)
def pagina():
    """Lista los avisos recibidos. Se recarga sola cuando llega uno nuevo."""
    if not avisos:
        filas = "<p class='vacio'>Todavía no llegó ningún aviso. Manda un POST /ai_validator con "\
                "<code>\"webhook_url\": \"http://127.0.0.1:9000/webhook\"</code> y espera unos segundos.</p>"
    else:
        filas = ""
        for a in avisos:
            d = a["datos"]
            ficha = d.get("ficha") or {}
            firma = "✅ firma válida" if a["firma_valida"] else "❌ firma inválida"
            resumen = html.escape(ficha.get("resumen") or d.get("error") or "")
            filas += f"""
            <details class="aviso">
              <summary><b>{a['hora']}</b> · trabajo {d.get('id')} · {html.escape(str(d.get('estado')))}
                · {html.escape(str(ficha.get('nombre') or ''))} · {firma}</summary>
              <p>{resumen}</p>
              <pre>{html.escape(json.dumps(d, ensure_ascii=False, indent=2))}</pre>
            </details>"""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Receptor de webhooks</title>
<script>
 // Cada 2 s pregunta cuántos avisos hay; si llegó uno nuevo, recarga la página.
 setInterval(async () => {{
   const r = await fetch('/cantidad'); const n = await r.json();
   if (n !== {len(avisos)}) location.reload();
 }}, 2000);
</script>
<style>
 body{{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;background:#111;color:#eee}}
 h1{{font-size:22px}} .vacio{{color:#aaa}} code{{color:#8cf}}
 .aviso{{background:#1c1c1c;border:1px solid #333;border-radius:8px;padding:10px 14px;margin:10px 0}}
 summary{{cursor:pointer}} pre{{white-space:pre-wrap;font-size:12px;color:#ccc}}
</style></head><body>
<h1>🔔 Receptor de webhooks · puerto 9000</h1>
<p>Avisos recibidos: <b>{len(avisos)}</b> (la página se actualiza sola cuando llega uno; haz clic en un aviso para ver todo)</p>
{filas}
</body></html>"""
