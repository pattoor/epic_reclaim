# Epic Games Free Games Auto-Claimer

Aplicacion self-hosted para detectar y reclamar automaticamente los juegos actualmente gratuitos de la seccion oficial **Free Games** de Epic Games Store para una o mas cuentas configuradas.

> **Fuente de verdad del proyecto:** `docs/` (ver [`docs/INDEX.md`](docs/INDEX.md)). Este README solo cubre uso/instalacion rapida.

## Interfaz principal

La administracion se hace por **CLI de consola** (menus numerados, solo stdlib), pensada para SSH:

```text
docker compose exec epic-reclaim python -m app.cli
```

o, en desarrollo local:

```text
python -m app.cli
```

El modo web (FastAPI + dashboard + API + scheduler) es opcional (`python -m app.web` / `main.py` historico) para quien prefiera el dashboard o integraciones externas (n8n, curl).

## Como funciona

1. Se agrega la(s) cuenta(s) Epic por CLI.
2. `Authenticate` ofrece modos: pantalla remota noVNC (URL de un solo uso `http://<ip-g7>:<NOVNC_PORT>`), **codigo desde otro dispositivo** (logueate en el celu/PC y pega el codigo) o Chromium local; el browser del server queda en el contenedor y la sesion se guarda alla (volumen `sessions`). Si hay un refresh token guardado, primero intenta restaurar la sesion sola.
3. El scheduler interno ejecuta el workflow unico por cron simplificado: por defecto **jueves 14:05**, configurable (dias + horas, preset "diario" para temporadas como navidad).
4. Cada run: descubre los juegos gratuitos vigentes (locale configurable `LOCALE`, default por IP), procesa cuentas en orden, verifica ownership y reclama secuencialmente guardando historial completo.

El proyecto terminado esta pensado para un servidor domestico Linux/Debian (referencia: g7, 2 cores / ~2.5 GB disponibles), con acceso por LAN o Tailscale. Funciona sin n8n y sin Telegram; ambas integraciones son opcionales.

## Caracteristicas

- Interfaz principal por consola (CLI stdlib) y dashboard web opcional servido por FastAPI.
- Descubrimiento de cualquier cantidad de juegos gratis elegibles en cada ejecucion.
- Soporte para multiples cuentas Epic sin contrasenas almacenadas por la aplicacion.
- Perfiles de navegador Playwright persistentes por cuenta.
- Autenticacion interactiva remota: el browser corre en el servidor y el usuario completa login/MFA/CAPTCHA desde la URL de un solo uso en su PC.
- Deteccion de CAPTCHA, MFA, expiracion de sesion y bloqueos que requieren intervencion humana.
- Claims secuenciales, idempotentes y con resultados `claimed`, `already_owned`, `failed` o `skipped`.
- Reintentos limitados para fallos transitorios, con backoff y delays configurables.
- Scheduler interno por dia y hora (default jueves 14:05; preset diario para temporadas promocionales).
- Dashboard web para cuentas, ejecuciones, historial, configuracion y diagnostico (opcional).
- `Run now`, scheduler interno y `POST /api/runs` para triggers externos.
- Exportacion CSV/JSON de historial por cuenta.
- Backup e importacion de datos sin incluir sesiones/cookies por defecto.
- Notificaciones Telegram opcionales y ejemplo de integracion con n8n.
- Despliegue en un unico contenedor Docker con datos persistentes.

## Como luce el proyecto terminado

Como luce el proyecto terminado:

Al abrir la CLI, el usuario ves un estado compacto con la salud de SQLite y Playwright, el estado del scheduler, la proxima ejecucion, el resultado de la ultima ejecucion y las cuentas que necesitan atencion, con menus numerados para todas las operaciones.

La seccion **Accounts** muestra cada cuenta con su nombre, orden de procesamiento y estado. Desde alli se puede agregar una cuenta, iniciar la autenticacion remota (URL de un solo uso), reautenticarla, activarla o desactivarla, resolver una intervencion y eliminarla con confirmacion explicita.

La seccion **Execution** presenta el progreso de una ejecucion en consola (o en el dashboard opcional) sin recargar ni refrescar manualmente:

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

Abrir `http://<IP_DEL_SERVIDOR>:8765` desde la red local o la direccion Tailscale del servidor. La pantalla remota de autenticacion (noVNC) se publica standalone en `NOVNC_PORT` (default 6080) y solo esta activa mientras haya una sesion de autenticacion en curso.

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

La imagen instala Xvnc (TigerVNC), websockify y el cliente web noVNC, ejecutados como **procesos standalone** (no proxied por la app). Al iniciar **Authenticate** desde la CLI, esta imprime la URL directa `http://<PUBLIC_HOST>:<NOVNC_PORT>/vnc.html?...` (token de un solo uso + contrasena efimera para VNC). El navegador remoto corre en `g7-server`; el usuario completa login, MFA o CAPTCHA manualmente desde su PC. Una vez detectado el inicio de sesion, el servidor detiene noVNC, cierra el navegador y conserva unicamente el perfil persistente de Playwright. No se exponen cookies, CDP ni credenciales. Si la pantalla remota no esta disponible, el comando lo informa y `/health` reporta `remote_screen: unavailable` junto con el diagnostico.

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
PUBLIC_HOST=
DATABASE_PATH=./data/database/epic.db
SESSIONS_PATH=./data/sessions
STATE_PATH=./data/state
LOCALE=es-AR
SCHEDULER_ENABLED=true
SCHEDULER_DAYS=THU
SCHEDULER_TIMES=14:05
SCHEDULER_DAILY=false
CLAIM_DELAY_MIN_SECONDS=2
CLAIM_DELAY_MAX_SECONDS=5
MAX_RETRY_ATTEMPTS=3
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EXTERNAL_API_KEY_ENABLED=false
EXTERNAL_API_KEY=
```

`LOCALE` fija la region del store (default: region por IP del servidor). `PUBLIC_HOST` es la IP/nombre con el que la CLI arma la URL de la pantalla remota (IP LAN o Tailscale del g7). El scheduler se configura por dias de semana y horas desde la CLI/API (los valores en env son simplemente el default inicial).

`.env` contiene configuracion local y secretos, por lo que debe permanecer ignorado por Git. La aplicacion nunca guarda contrasenas Epic como campos normales.

Los delays y el scheduler tambien pueden ajustarse desde el dashboard (**Settings**): dias (MON..SUN), horarios (HH:MM, varios por coma) y preset "diario". Los cambios se guardan en la base y aplican sin reiniciar.

### Nota de seguridad

- El dashboard esta pensado para LAN/Tailscale y no se expone publicamente por defecto.
- Al habilitar `EXTERNAL_API_KEY_ENABLED=true`, `POST /api/runs` exige el header `X-API-Key`; el boton **Run now** del dashboard usa `/api/runs/manual` y no requiere esa key.
- Eliminar una cuenta de forma permanente exige confirmacion explicita (el cliente envia `confirm=true`).
- Los backups y exports nunca incluyen sesiones ni secretos (tokens de Telegram, chat id o API key).

## Primer uso

1. Ejecutar la CLI: `python -m app.cli` (dev local) o `docker compose exec epic-reclaim python -m app.cli` (g7).
2. **Add account**: agregar la cuenta Epic (nombre y orden de procesamiento).
3. **Authenticate**: la CLI imprime la URL del navegador remoto (noVNC) con token de un solo uso.
4. Abrir la URL desde la PC o celular (LAN o Tailscale) y completar login, RFA o CAPTCHA manualmente.
5. Al confirmar, el servidor guarda la sesion y cierra pantalla y navegador.
6. Ajustar scheduler (dias + hora; default jueves 14:05) y delays desde Settings.
7. Ejecutar **Run now** para validar el flujo completo.

Las cuentas se procesan en orden y los juegos uno por uno. Si un juego ya pertenece a la cuenta, se registra `already_owned`; si Epic confirma que se agrego, se registra `claimed`.

## Scheduler y API externa

El scheduler es **interno y tipo cron simplificado**: un bucle `asyncio` dentro del mismo runner que ejecuta `RunWorkflow.run("scheduler")` en los dias/horas configurados (por defecto jueves 14:05), con preset "diario" para temporadas promocionales. No requiere n8n, cron de sistema ni ningun otro orquestador para funcionar.

Desde **Settings** (CLI o dashboard) puedes activar/desactivar el scheduler, elegir dias de la semana y horarios. Los cambios se guardan en la base y aplican sin reiniciar. El scheduler nunca inicia una segunda ejecucion mientras otra siga activa.

Triggers de ejecucion (todos usan el mismo workflow):

- **Scheduler interno** — ejecuta automaticamente `RunWorkflow.run("scheduler")` en los dias y horarios configurados.
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

### Login por codigo desde otro dispositivo (celular o PC, modo device)

Alternativa que no usa ni noVNC ni archivos: la CLI pide elegir el modo al autenticar (`1 = pantalla remota, 2 = codigo desde otro dispositivo, 3 = Chromium local`). En modo device:

1. Antes de pedir modo, la CLI intenta una **restauracion silenciosa**: si la cuenta tiene un refresh token guardado, se re-autentica sola (tambien ocurre al inicio de cada run) sin que el usuario haga nada.
2. El CLI imprime la URL oficial de login de Epic (`epicgames.com/id/login?...`); abrila en el navegador de tu celu o PC (con tus cuentas ya logueadas) y completa MFA/captcha ahi.
3. Epic muestra un **codigo de un solo uso**; pegalo en la CLI. El servidor lo intercambia por tokens OAuth y asienta la sesion en el perfil del contenedor (Chromium headless sobre `id/exchange`); nada queda en tu dispositivo. En la API: `POST /api/accounts/{id}/authenticate?mode=device` y `POST /api/auth/{token}/code` con `{"code": "..."}`.
4. El refresh token queda solo en el volumen del server (`data/sessions/<id>/epic_session.json`), nunca en DB, logs ni backups, y permite restauraciones silenciosas futuras.

Usa las credenciales publicas del cliente del Epic Games Launcher (los mismos defaults que legendary/Heroic); no requiere registrar nada en el portal de developers de Epic. CAPTCHA/MFA se completan manualmente en TU navegador (regla D8 intacta).

### Fallback manual: login en la PC y copia del perfil (SPECS 15)

Si la pantalla remota no permite completar el login (por ejemplo, un desafio anti-bot imposible en un Chromium remoto), se puede incluir el login en una PC grafica y copiar el perfil al servidor:

1. En la PC con GUI: `py tools/local_login.py` abre Chrome con un **perfil dedicado persistente** (`%LOCALAPPDATA%\epic_reclaim\local_auth_profile`) en la pagina de login de Epic. Las cuentas de Google/Epic quedan enlazadas dentro de ese perfil para reusos futuros.
   - `--profile-dir <ruta>` — usar otro perfil ya existente.
   - `--fresh` — borrar el perfil dedicado antes (caso login aislado/limpio).
2. Loguearse normalmente y terminar Chrome.
3. Copiar el perfil al volumen del servidor (ejecucion explicita del usuario; via scp/Tailscale, cookies de solo el perfil dedicado):
   `scp -r %LOCALAPPDATA%\epic_reclaim\local_auth_profile <server>:<sesiones>/<id>` y dejarlo como `<data>/sessions/<id>`.
4. En el server disparar `authenticate`: detecta la sesion activa del perfil y deja la cuenta `active`.

Nunca usar el perfil diario de Chrome del usuario: la copia al servidor expondria sesiones no relacionadas (mail, banca, etc.).

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
- **Remote screen unavailable / error 503 al autenticar:** revisar `GET /health` y `remote_screen_diagnostics`. Puede deberse a procesos que no arrancan, noVNC web dir no encontrado o falta de permisos. El puerto `6080` solo se usa internamente dentro del contenedor; no necesita estar expuesto fuera de el.
- **Sesion expirada:** iniciar reautenticacion desde **Accounts**.
- **CAPTCHA o MFA:** completar la accion manualmente en el navegador del servidor.
- **Telegram no configurado:** dashboard, historial y scheduler siguen funcionando sin Telegram.
- **Base de datos con problemas:** revisar la ruta persistente, permisos y el estado del volumen.
- **Sesion perdida tras reinicio:** verificar que `SESSIONS_PATH` este montado en un volumen persistente.
- **Restauracion:** validar el backup, confirmar la importacion y reautenticar cuentas si las sesiones no estaban incluidas.

## Alcance

La version 1 soporta unicamente Epic Games Store. No compra juegos pagos, no reclama descuentos que no sean realmente gratuitos y no incluye aplicacion movil, multiusuario, recomendaciones ni analytics no relacionados con claims.
