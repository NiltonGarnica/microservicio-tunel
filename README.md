# Microservicio de práctica: FastAPI + Cloudflare Tunnel / ngrok

API local para aprender a exponer un servicio a internet mediante un túnel.

| Método y ruta | Qué hace | Acceso |
|---|---|---|
| `GET /health` | Devuelve `{"status": "ok"}` | Público |
| `GET /docs` | Swagger UI para probar las rutas | Público |
| `POST /suma` | Recibe `{"a": 3, "b": 5.2}` y devuelve `{"resultado": 8.2}` | Bearer token |
| `POST /process` | Valida y guarda una persona en la tabla `personas`; responde `201` con el `id` | Bearer token |
| `POST /ai_validator` | Recibe `url` y `webhook_url`, responde `202` al instante y envía la ficha del producto al webhook (sección 7) | Bearer token |
| `GET /ai_validator/{id}` | Consulta el estado de un trabajo de `/ai_validator` | Bearer token |
| `POST /webhook_demo` | Receptor de prueba: guarda los avisos en `webhooks_recibidos` | Firma `X-Firma-Sha256` |
| `GET /scalar` | Otra página de documentación, como `/docs` | Público |

Archivos:

- `main.py`: rutas, validación con Pydantic y comprobación del Bearer token.
- `database.py`: conexión con SQLAlchemy y modelos `Persona`, `Validacion` y `WebhookRecibido`.
- `ai_validator.py`: flujo de `/ai_validator`: Lightpanda, LLM, base de datos y webhook.
- `docker-compose.yml`: levanta Lightpanda, el navegador que obtiene el DOM.
- `preparar_postgres.py`: crea la base en PostgreSQL y copia los datos de SQLite (sección 5).
- `tests/test_api.py`: pruebas automáticas de las rutas.
- `.env.example`: plantilla de configuración. Tu configuración real va en `.env`, que no se sube a git.

## 1. Preparar el entorno (PowerShell)

```powershell
cd C:\Users\garni\microservicio-tunel
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si PowerShell bloquea `Activate.ps1`, ejecuta una vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Configurar `.env`

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
code .env
```

Pega el token generado después de `API_BEARER_TOKEN=` y guarda. Sin token, el servicio no arranca.

Hay dos tokens distintos, no los confundas:

- **`API_BEARER_TOKEN`** protege las rutas `/suma` y `/process` de tu API. Lo inventas tú y lo envía quien llama a la API.
- **El authtoken de ngrok** identifica a tu agente ngrok ante tu cuenta de ngrok. Se configura con `ngrok config add-authtoken` y nunca va en `.env` ni en las peticiones a tu API.

## 3. Terminal 1: arrancar Uvicorn

```powershell
cd C:\Users\garni\microservicio-tunel
.\.venv\Scripts\Activate.ps1
uvicorn main:app --host 127.0.0.1 --port 8000
```

Deja esta terminal abierta. Con `127.0.0.1`, Uvicorn solo acepta conexiones desde tu propia PC; la única entrada desde internet será el túnel.

1. Abre <http://127.0.0.1:8000/health>. Debes ver `{"status":"ok"}`.
2. Abre <http://127.0.0.1:8000/docs>.
3. Pulsa **Authorize**, pega el valor de `API_BEARER_TOKEN` (solo el token, sin la palabra `Bearer`) y confirma.
4. En `POST /suma`, pulsa **Try it out** y **Execute** con `{"a": 3, "b": 5.2}`. Respuesta: `{"resultado": 8.2}`.
5. En `POST /process`, ejecuta el ejemplo:

```json
{
  "nombre": "Ana Pérez",
  "telefono": "+59170000000",
  "email": "ana@example.com",
  "genero": "femenino"
}
```

Respuesta: `201` con `{"id": 1}` (el número aumenta con cada registro).

Para ver lo guardado en SQLite, desde otra terminal con el entorno activado:

```powershell
python -c "import sqlite3; [print(f) for f in sqlite3.connect('personas.db').execute('SELECT * FROM personas')]"
```

También puedes probar sin Swagger:

```powershell
$token = "PEGA_AQUI_TU_TOKEN"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/suma `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" -Body '{"a": 3, "b": 5.2}'
```

Respuestas de error que verás:

- `401`: falta el token o es incorrecto.
- `422`: los datos no son válidos (texto en lugar de número, `NaN`, correo mal escrito, campo vacío, teléfono con letras...).

El teléfono admite un `+` opcional seguido de 6 a 15 dígitos, sin espacios ni guiones.

## 4. Terminal 2: abrir el túnel

Abre una segunda terminal **sin cerrar la primera**. Elige una de las dos opciones. Las dos apuntan solo al puerto HTTP de Uvicorn (8000); la base de datos no se expone.

### Opción A: Cloudflare Tunnel

Requisitos: tener `cloudflared` instalado. Para este túnel rápido no hace falta cuenta ni dominio.

```powershell
winget install --id Cloudflare.cloudflared
```

Cierra y vuelve a abrir la terminal tras instalar. Luego:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

En la salida aparece una URL como `https://palabras-al-azar.trycloudflare.com`.

### Opción B: ngrok

Requisitos: tener `ngrok` instalado, una cuenta gratuita en <https://ngrok.com> y el authtoken configurado una sola vez.

```powershell
winget install --id Ngrok.Ngrok
ngrok config add-authtoken TU_AUTHTOKEN_DE_NGROK
```

Luego:

```powershell
ngrok http 8000
```

La URL aparece en la línea `Forwarding`, por ejemplo `https://algo.ngrok-free.app`.

### Probar desde el celular

1. Copia la URL `https://...` de la terminal 2.
2. Añade `/health` al final: `https://palabras-al-azar.trycloudflare.com/health`.
3. En el celular, apaga el Wi-Fi para usar datos móviles. Así compruebas que la petición llega desde internet y no desde tu red local.
4. Abre esa dirección en el navegador del celular. Debes ver `{"status":"ok"}`, y en la terminal 1 aparece la línea `GET /health`.
5. Para probar `/suma` y `/process`, abre `https://.../docs` en el celular, pulsa **Authorize** y pega tu token.

Con el plan gratuito de ngrok, el navegador puede mostrar primero una página de aviso; pulsa **Visit Site** para continuar.

Mientras el túnel esté abierto, cualquiera que tenga la URL puede ver `/health` y `/docs`. `/suma` y `/process` siguen exigiendo el token. Usa solo datos ficticios, no compartas la URL junto con el token y cierra el túnel al terminar.

### Qué pasa si cierras el túnel y dejas Uvicorn encendido

Cierra el túnel con `Ctrl+C` en la terminal 2.

- La URL pública deja de funcionar: el celular recibe un error de Cloudflare o de ngrok, porque ya no hay nadie que lleve la petición hasta tu PC.
- Uvicorn sigue funcionando: `http://127.0.0.1:8000/health` responde igual que antes desde tu PC, y los datos guardados siguen ahí.
- Si abres el túnel de nuevo, la URL será distinta. Las URL de `trycloudflare.com` son temporales; en ngrok cambian salvo que uses un dominio fijo de tu cuenta.

Al revés, si cierras Uvicorn y dejas el túnel abierto, la URL pública responde con un error `502`: el túnel existe pero no encuentra nada en el puerto 8000.

## 5. Cambiar de base de datos

El motor se elige con `DATABASE_URL` en `.env`. El servicio usa un solo motor a la vez, y las tablas se crean solas al arrancar. La base de datos (`practica` en los ejemplos) debe existir antes.

| Motor | Driver a instalar | `DATABASE_URL` |
|---|---|---|
| SQLite (inicial) | ninguno | `sqlite:///./personas.db` |
| PostgreSQL (recomendado como servidor) | `pip install "psycopg[binary]"` | `postgresql+psycopg://usuario:clave@localhost:5432/practica` |
| MySQL | `pip install "PyMySQL[rsa]"` | `mysql+pymysql://usuario:clave@localhost:3306/practica?charset=utf8mb4` |
| MariaDB | `pip install "PyMySQL[rsa]"` | `mariadb+pymysql://usuario:clave@localhost:3306/practica?charset=utf8mb4` |

El driver de PostgreSQL ya viene en `requirements.txt`; el de MySQL/MariaDB está comentado: descomenta si lo usas. Después de cambiar `.env`, reinicia Uvicorn.

### Pasar a PostgreSQL paso a paso

PostgreSQL 18 ya está instalado en esta PC (servicio `postgresql-x64-18`).

1. Abre `.env` (`code .env`).
2. En la línea de PostgreSQL cambia `ESCRIBE_TU_CLAVE` por la clave del usuario `postgres` (la que pusiste al instalar PostgreSQL).
3. Quita el `#` del inicio de esa línea y pon `#` al inicio de la línea de SQLite:
   ```
   # DATABASE_URL=sqlite:///./personas.db
   DATABASE_URL=postgresql+psycopg://postgres:TU_CLAVE@localhost:5432/practica
   ```
4. Con el entorno activado, ejecuta:
   ```powershell
   python preparar_postgres.py
   ```
   El script crea la base `practica` si no existe, crea la tabla `personas` y copia las personas que ya tenías en `personas.db` (sin duplicarlas si lo ejecutas de nuevo).
5. Reinicia Uvicorn y prueba `POST /process`. Para ver lo guardado:
   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d practica -c "SELECT * FROM personas;"
   ```

Para volver a SQLite, invierte el `#` de las dos líneas y reinicia Uvicorn.

## Pruebas automáticas

```powershell
python -m pytest -v
```

Usan una base SQLite temporal y un token de prueba: no tocan tu `.env` ni tus datos.

Si la clave contiene caracteres como `@`, `:` o `/`, escríbelos codificados en la URL (por ejemplo `@` como `%40`).

## 6. Cómo viaja una petición

Ejemplo: desde el celular envías `POST https://tu-url/suma` con `{"a": 3, "b": 5.2}`.

1. **Celular a Cloudflare/ngrok.** El celular se conecta por HTTPS al servidor de Cloudflare o de ngrok. Tu PC no recibe conexiones entrantes.
2. **Túnel.** `cloudflared` o `ngrok` en tu PC mantiene una conexión saliente con ese servidor. La petición baja por esa conexión y el agente la reenvía a `http://127.0.0.1:8000`.
3. **Uvicorn.** Es el servidor web: recibe la petición HTTP y se la entrega a la aplicación FastAPI.
4. **FastAPI.** Busca la ruta `POST /suma` y ejecuta sus dependencias.
5. **Bearer token.** `verificar_token` lee `Authorization: Bearer <token>` y lo compara con `API_BEARER_TOKEN`. Si no coincide, responde `401` y la petición termina ahí.
6. **Pydantic.** Convierte el JSON en `SumaEntrada` y comprueba que `a` y `b` sean números finitos. Si no, responde `422`.
7. **Tu función.** Calcula `3 + 5.2` y devuelve `{"resultado": 8.2}`. FastAPI lo convierte a JSON.
8. **Vuelta.** La respuesta recorre el mismo camino al revés: Uvicorn, agente del túnel, Cloudflare/ngrok, celular.

En `/process` el recorrido es el mismo hasta el paso 6. **SQLAlchemy** entra en el paso 7: con los datos ya validados, la función crea un objeto `Persona`, y `db.commit()` ejecuta el `INSERT` en la tabla `personas`. La base de datos genera el `id` y la función lo devuelve con `201`.

## 7. `/ai_validator`: Lightpanda, LLM y webhook

Flujo asíncrono: la API responde `202` en el acto y hace el trabajo en segundo plano.

```text
POST /ai_validator {url, webhook_url}  ->  202 {"id": 3, "estado": "pendiente"}
   en segundo plano:
   1. Lightpanda abre la página, ejecuta su JavaScript y devuelve el DOM
   2. El LLM de OpenRouter saca la ficha del producto
   3. Se guarda en la tabla validaciones (pendiente -> procesando -> completado o fallido)
   4. Se envía el resultado a webhook_url, firmado con WEBHOOK_SECRET (hasta 3 intentos)
```

Requisitos en `.env`: `OPENROUTER_API_KEY`, `LIGHTPANDA_CDP_URL`, `WEBHOOK_SECRET` y, para probar con `/webhook_demo`, `PERMITIR_WEBHOOK_LOCAL=true`.

Arranca Lightpanda (necesita Docker Desktop abierto):

```powershell
docker compose up -d
```

Prueba desde `/docs` o `/scalar` con:

```json
{
  "url": "https://www.amd.com/es/products/graphics/desktops/radeon/7000-series/amd-radeon-rx-7600-xt.html",
  "webhook_url": "http://127.0.0.1:8000/webhook_demo"
}
```

Mira el resultado:

```powershell
psql -U postgres -h localhost -d practica -c "SELECT id, estado, webhook_estado FROM validaciones ORDER BY id;"
psql -U postgres -h localhost -d practica -c "SELECT id, trabajo_id, firma_valida, recibido_en FROM webhooks_recibidos ORDER BY id;"
```

**Verificar la firma del webhook.** Quien recibe el aviso calcula `HMAC-SHA256(WEBHOOK_SECRET, cuerpo)` y lo compara con la cabecera `X-Firma-Sha256`. Si coincide, el aviso viene de esta API y no fue modificado. `/webhook_demo` hace exactamente eso.

Limitaciones:

- El trabajo corre dentro del mismo proceso de Uvicorn (`BackgroundTasks`). Si apagas o reinicias la API mientras un trabajo está `procesando`, ese trabajo se pierde y queda en ese estado. En producción se usa una cola de trabajos (por ejemplo Celery o RQ).
- `PERMITIR_WEBHOOK_LOCAL=true` es solo para desarrollo. Con la API expuesta por el túnel, déjalo en `false`.
