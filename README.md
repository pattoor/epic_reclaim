# Epic Games Free Games Auto-Claimer

Aplicacion self-hosted para detectar y reclamar automaticamente los juegos actualmente gratuitos de la seccion oficial **Free Games** de Epic Games Store para una o mas cuentas configuradas.

El proyecto terminado esta pensado para un servidor domestico Linux/Debian, con acceso por LAN o Tailscale. Funciona sin n8n y sin Telegram; ambas integraciones son opcionales.

## Caracteristicas

- Descubrimiento de cualquier cantidad de juegos gratis elegibles en cada ejecucion.
- Soporte para multiples cuentas Epic sin contrasenas almacenadas por la aplicacion.
- Perfiles de navegador Playwright persistentes por cuenta.
- Autenticacion y reautenticacion interactiva en el navegador del servidor.
- Deteccion de CAPTCHA, MFA, expiracion de sesion y bloqueos que requieren intervencion humana.
- Claims secuenciales, idempotentes y con resultados `claimed`, `already_owned`, `failed` o `skipped`.
- Reintentos limitados para fallos transitorios, con backoff y delays configurables.
- Dashboard web para cuentas, ejecuciones, historial, configuracion y diagnostico.
- `Run now`, scheduler interno y `POST /api/runs` para triggers externos.
- Exportacion CSV/JSON de historial por cuenta.
- Backup e importacion de datos sin incluir sesiones/cookies por defecto.
- Notificaciones Telegram opcionales y ejemplo de integracion con n8n.
- Despliegue en un unico contenedor Docker con datos persistentes.

## Como luce el proyecto terminado

Al abrir el dashboard, el usuario encuentra una vista compacta con el estado de la aplicacion, la salud de SQLite y Playwright, el estado del scheduler, la proxima ejecucion, el resultado de la ultima ejecucion y las cuentas que necesitan atencion.

La seccion **Accounts** muestra cada cuenta con su nombre, orden de procesamiento y estado. Desde alli se puede agregar una cuenta, abrir la autenticacion remota, reautenticarla, activarla o desactivarla, resolver una intervencion y eliminarla con confirmacion explicita.

La seccion **Execution** presenta el progreso de una ejecucion sin recargar la pagina:

```text
RUN #142

Detecting games...       OK
Found 2 games            OK

Personal
  - Game A               claimed
  - Game B               claimed

Friend 1
  - Game A               already_owned
  - Game B               claimed

Friend 2
  - CAPTCHA              intervention required
```

La seccion **History** permite revisar claims por cuenta, fecha y estado, y descargar CSV o JSON. **Settings** permite ajustar el scheduler, los delays de claim y las integraciones opcionales sin cambiar el codigo.

## Arquitectura

```text
Dashboard web
      |
REST API (FastAPI) ---- Scheduler interno
      |                         |
      +-------- Claim workflow -+
                    |
             SQLite + logs
                    |
       Epic adapter + Playwright
                    |
       Per-account persistent sessions
```

El workflow de claims es unico: scheduler, boton `Run now` y API externa llaman la misma logica. El adaptador de Epic contiene la automatizacion especifica de la tienda, mientras que cuentas, ejecuciones, historial, scheduler y notificaciones permanecen desacoplados.

## Requisitos

- Linux/Debian recomendado, con acceso por LAN o Tailscale.
- Docker y Docker Compose para el despliegue recomendado.
- Aproximadamente 4 GB de RAM en el servidor de referencia.
- Para ejecucion local: Python 3.12+ y Chromium de Playwright.
- El dashboard es HTML/JS/CSS estatico servido por FastAPI; no requiere Node ni build step.

El puerto por defecto es `8765`, pero es configurable y no se asume que este libre.

## Ejecucion con Docker

```bash
git clone <repository-url>
cd epic_reclaim
cp .env.example .env
# editar .env con APP_PORT y demas opciones si se desea
docker compose up -d --build
```

Abrir `http://<IP_DEL_SERVIDOR>:8765` desde la red local o la direccion Tailscale del servidor. El puerto `6080` se publica para la pantalla noVNC durante autenticaciones.

Los volumenes conservan:

- Base de datos SQLite (`database`).
- Perfiles persistentes de Playwright (`sessions`).
- Estado de la aplicacion (`state`).

Para cambiar el puerto publicado, ajustar `APP_PORT` en `.env` y reiniciar: `docker compose down && docker compose up -d`.

### Detener y resetear

```bash
docker compose down            # detener
docker compose down -v         # detener y borrar volumenes (RESET: pierde DB y sesiones)
docker compose up -d --build   # reconstruir tras cambios
```

### Autenticacion interactiva con noVNC

La imagen instala Xvfb, x11vnc, websockify y el cliente web noVNC. Al iniciar **Authenticate** desde el dashboard, la aplicacion lanza un navegador headed en el servidor y lo expone en una pantalla remota protegida con una contrasena por sesion; el usuario completa login, MFA o CAPTCHA manualmente desde esa pantalla. Si la pantalla remota no esta disponible (por ejemplo, sin las herramientas instaladas), el endpoint de autenticacion devuelve 503 y `/health` reporta `remote_screen: unavailable`.

## Ejecucion sin Docker

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# editar .env con rutas locales persistentes
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

El scheduler interno se inicia con la aplicacion. Para ejecutar solo una vez o desde un cron, usar `POST /api/runs` (ver seccion Scheduler).

## Configuracion

Variables soportadas (ver `.env.example`):

```env
APP_HOST=0.0.0.0
APP_PORT=8765
NOVNC_PORT=6080
DATABASE_PATH=./data/database/epic.db
SESSIONS_PATH=./data/sessions
STATE_PATH=./data/state
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=21600
CLAIM_DELAY_MIN_SECONDS=2
CLAIM_DELAY_MAX_SECONDS=5
MAX_RETRY_ATTEMPTS=3
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EXTERNAL_API_KEY_ENABLED=false
EXTERNAL_API_KEY=
```

`.env` contiene configuracion local y secretos, por lo que debe permanecer ignorado por Git. La aplicacion nunca guarda contrasenas Epic como campos normales.

Los delays y el intervalo del scheduler tambien pueden ajustarse desde el dashboard (**Settings**). El intervalo se configura como dias, horas, minutos y segundos; los cambios se guardan en la base y aplican sin reiniciar.

### Nota de seguridad

- El dashboard esta pensado para LAN/Tailscale y no se expone publicamente por defecto.
- Al habilitar `EXTERNAL_API_KEY_ENABLED=true`, `POST /api/runs` exige el header `X-API-Key`; el boton **Run now** del dashboard usa `/api/runs/manual` y no requiere esa key.
- Eliminar una cuenta de forma permanente exige confirmacion explicita (el cliente envia `confirm=true`).
- Los backups y exports nunca incluyen sesiones ni secretos (tokens de Telegram, chat id o API key).

## Primer uso

1. Iniciar la aplicacion y abrir el dashboard.
2. Agregar una cuenta Epic.
3. Iniciar **Authenticate**.
4. Abrir el navegador interactivo remoto que ejecuta el servidor.
5. Completar manualmente login, MFA o CAPTCHA si Epic los solicita.
6. Esperar la confirmacion de autenticacion y el cierre del navegador.
7. Ajustar nombre, orden, estado y scheduler de la cuenta.
8. Ejecutar **Run now** para validar el flujo.

Las cuentas se procesan en orden y los juegos uno por uno. Si un juego ya pertenece a la cuenta, se registra `already_owned`; si Epic confirma que se agrego, se registra `claimed`.

## Scheduler y API externa

El scheduler es **interno**: un bucle `asyncio` dentro del mismo proceso FastAPI que ejecuta `RunWorkflow.run("scheduler")` en el intervalo configurado. No requiere n8n, cron ni ningun otro sistema externo para funcionar.

Desde **Settings** puedes activar o desactivar el scheduler y establecer el intervalo en dias, horas, minutos y segundos. El valor por defecto es 6 horas. El scheduler nunca inicia una segunda ejecucion mientras otra siga activa.

Triggers de ejecucion (todos usan el mismo workflow):

- **Scheduler interno** — ejecuta automaticamente `RunWorkflow.run("scheduler")` segun el intervalo configurado.
- **`Run now`** en el dashboard — llama a `POST /api/runs/manual` y no requiere API key.
- **`POST /api/runs`** — trigger externo para n8n, cron, scripts u otro orquestador. Si `EXTERNAL_API_KEY_ENABLED=true`, exige el header `X-API-Key`.

Ejemplo de integracion externa con n8n o cron:

```text
Schedule Trigger -> POST /api/runs
```

Si una ejecucion ya esta en curso, cualquier trigger devuelve `409` indicando que hay una ejecucion activa. n8n y Telegram son opcionales: el sistema funciona igual sin ellos.

Comprobacion de salud:

```text
GET /health
```

La respuesta comprueba el estado de la aplicacion, SQLite, Playwright y la disponibilidad de la pantalla remota sin realizar claims ni trafico innecesario contra Epic.

## Telegram (opcional)

Para activar notificaciones, configurar en `.env` (o en **Settings**):

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<token-del-bot>
TELEGRAM_CHAT_ID=<chat-id>
```

Al habilitarse, el bot envia un resumen por cada ejecucion y alertas de CAPTCHA, MFA, cuenta pausada y fallos significativos, con deduplicacion basica. Si Telegram no esta configurado, dashboard, historial, scheduler y workflow siguen funcionando igual.

## Intervenciones humanas

CAPTCHA, MFA, autenticacion expirada, rate limits y bloqueos no se resuelven ni se reintentan ciegamente. La cuenta pasa a `needs_intervention`, `needs_authentication` o `paused`, con el motivo visible en el dashboard.

Una vez resuelto el problema desde el dashboard, la cuenta vuelve a `active` y puede continuar el trabajo pendiente de forma segura. Telegram puede avisar de estas situaciones, pero no es necesario para resolverlas.

## Backup y restore

Backup y export de historial se hacen desde el dashboard o la API:

- `GET /api/backup` — descarga el backup (SQLite + configuracion no secreta). Nunca incluye sesiones, cookies ni secretos (tokens de Telegram, chat id o API key).
- `POST /api/backup/import?overwrite=true` — restaura un backup; sin `overwrite=true` y con datos existentes devuelve `400`.
- `GET /api/claims/export?format=csv|json` — exporta historial con filtros opcionales por cuenta, estado y fecha.

Tras migrar o reinstalar, las cuentas pueden necesitar autenticarse nuevamente (las sesiones no viajan en el backup).

## Seguridad y limites

- El dashboard esta pensado para LAN/Tailscale y no se expone publicamente por defecto.
- No se almacenan contrasenas Epic en la base de datos.
- No se muestran ni exportan cookies, tokens o sesiones.
- Los backups excluyen siempre los secretos (tokens de Telegram, chat id, API key).
- No se automatiza ni evade CAPTCHA, MFA, rate limits o controles anti-bot.
- Los claims son secuenciales y usan delays conservadores configurables.
- Los logs excluyen secretos y datos sensibles.

## Pruebas

Ejecutar la suite completa:

```bash
python -m pytest
```

La suite se separa en:

- **Unitarias** (`tests/unit/`): elegibilidad, estados, reintentos e idempotencia.
- **Integracion** (`tests/integration/`): SQLite, API, scheduler, lock y workflow con dobles.
- **E2E controladas** (`tests/e2e/`): flujo completo con Epic/browser aislados o mockeados.
- **Live/manuales:** autenticacion real y validaciones contra Epic, ejecutadas bajo demanda (no forman parte de la suite).

Los tests automatizados no deben depender continuamente de la tienda Epic en vivo.

## Troubleshooting

- **Puerto ocupado:** cambiar `APP_PORT` y el puerto publicado por Docker Compose.
- **Chromium o Playwright falla:** instalar las dependencias del navegador y revisar logs del contenedor.
- **Remote screen unavailable / error 503 al autenticar:** revisar `GET /health` y `remote_screen_diagnostics`. Puede deberse a puertos ocupados (`5900`, `6080`), procesos que no arrancan, noVNC web dir no encontrado o falta de permisos. Los logs del contenedor mostraran el motivo exacto.
- **Sesion expirada:** iniciar reautenticacion desde **Accounts**.
- **CAPTCHA o MFA:** completar la accion manualmente en el navegador del servidor.
- **Telegram no configurado:** dashboard, historial y scheduler siguen funcionando sin Telegram.
- **Base de datos con problemas:** revisar la ruta persistente, permisos y el estado del volumen.
- **Sesion perdida tras reinicio:** verificar que `SESSIONS_PATH` este montado en un volumen persistente.
- **Restauracion:** validar el backup, confirmar la importacion y reautenticar cuentas si las sesiones no estaban incluidas.

## Alcance

La version 1 soporta unicamente Epic Games Store. No compra juegos pagos, no reclama descuentos que no sean realmente gratuitos y no incluye aplicacion movil, multiusuario, recomendaciones ni analytics no relacionados con claims.
