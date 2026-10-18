# Arquitectura

## Objetivo y límites

El sistema se despliega como un único contenedor Docker con dos modos de uso del mismo core:

- **CLI principal** (`python -m app.cli`): interfaz de gestión por consola (menús stdlib numerados) sobre SSH, para cualquier operación. No arranca servidor web.
- **Modo web opcional** (`python -m app.web`): FastAPI sirve API + dashboard estático y arranca el scheduler; pensado para integraciones externas (n8n, curl, `/health`) o para quien prefiera el dashboard. En producción el scheduler corre bajo el modo elegido; CLI y API nunca corren en procesos separados con lógica duplicada.

Ambos modos llaman exactamente los mismos services y `RunWorkflow.run(trigger)`. El componente que corre con scheduler es el "runner"; en deployments reales el contenedor ejecuta `app.web` (con scheduler y API) y la administración diaria se hace por SSH con la CLI local del mismo contenedor (`docker compose exec epic-reclaim python -m app.cli`), que opera contra los mismos services.

La prioridad es `corrección -> seguridad -> mantenibilidad -> simplicidad -> rendimiento`. La versión 1 solo implementa Epic Games Store. No se automatizan ni evaden CAPTCHA, MFA, rate limits o controles anti-bot, y no se guardan contraseñas de Epic.

La separación interna permite sustituir el adaptador de Epic en el futuro sin convertir el MVP en un framework multi-plataforma especulativo.

## Decisiones técnicas

- **Python 3.12+** como runtime; CLI con solo stdlib (menús enumerados, sin Rich/Textual).
- **FastAPI 0.115+** (modo web opcional) para la API, el ciclo de vida y el dashboard estático.
- **SQLite** (stdlib `sqlite3`) como base de datos única; sin ORM ni migraciones ajenas.
- **Playwright 1.45+** para navegación persistente; es una capacidad opcional comprobada por `/health` y por el diagnóstico de la CLI.
- **Scheduler interno asyncio tipo cron simplificado**: días de semana + horas (default `THU 14:05`, preset "diario" para temporadas promocionales), sin APScheduler ni procesos adicionales, respetando `RunLock`. Detalle en `DECISIONS.md` (D4).
- **Pantalla remota standalone** (Xvnc de TigerVNC + websockify + noVNC; D9) para autenticación interactiva: proceso propio del contenedor, nunca proxied dentro de FastAPI (el diseño previo con proxy interno es la causa documentada del fallo `ERR_INCOMPLETE_CHUNKED_ENCODING`). Detalle en `DECISIONS.md` (D3, D9).
- **httpx** para Telegram y para los tests de la API con `TestClient`.
- **pytest** como runner de tests; sin dependencias de framework adicionales en runtime.
- Frontend del modo web sin build step: HTML/CSS/JS estáticos servidos por FastAPI desde `static/`.

Razón del conjunto: cabe en el servidor real de ~2.5 GB disponibles (2 cores), mantiene un solo contenedor y evita dependencias que no aporten a corrección o mantenibilidad. En reposo el footprint objetivo es < 100 MB; el pico con Chromium headless < 700 MB.

## Estructura del repositorio

```text
app/
  cli.py                  # CLI principal: menús stdlib; llama services; sin servidor web.
  web.py                  # Modo web opcional: ASGI app FastAPI + scheduler (python -m app.web).
  main.py                 # create_app de FastAPI y entrypoint uvicorn `app.main:app`.
  bootstrap.py            # Runtime compartido CLI/web: DB, repos, services, workflow, lock.
  config.py               # Variables de entorno y validación de configuración (incluye LOCALE).
  database.py             # Conexión SQLite, migraciones/esquema e integridad.
  domain/
    models.py             # Entidades, enums y tipos del dominio.
    scheduling.py         # Helpers puros de slots (días + horas) y cálculo de próxima ejecución.
    errors.py             # Errores clasificados por recuperación/intervención.
  repositories/            # Consultas y escrituras de persistencia.
  services/
    run_workflow.py       # Workflow único de scheduler, CLI, API y Run now.
    locks.py              # RunLock combinado: hilo + archivo O_EXCL entre procesos.
    account_service.py    # Estados, orden y operaciones de cuentas.
    auth_service.py       # Ciclo de autenticación interactiva y pantalla remota.
    backup_service.py     # Backup/import validado sin sesiones.
    settings_service.py   # Config no secreta (scheduler día+hora, delays, integraciones).
    discovery_service.py  # Descubrimiento de juegos vía adaptador.
  integrations/
    epic_adapter.py       # Interfaz de descubrimiento, ownership y claim.
    epic_playwright.py    # Selectores y comportamiento específico de Playwright.
    auth_browser.py       # Contexto headed de autenticación (local GUI o Xvfb).
    remote_screen.py      # noVNC/Xvnc/websockify standalone (proceso del entorno, no proxied).
    telegram.py           # Notificaciones opcionales, sin lógica de negocio.
  scheduler.py            # Scheduler cron simplificado: días + horas, RunLock.
  api.py                  # Rutas, validación HTTP y serialización (modo web).
  logging_config.py       # Logs estructurados y filtrado de secretos.
  static/                 # UI estática del modo web opcional.
tests/
  unit/                   # Dominio, estados, retry, idempotencia, scheduler cron.
  integration/            # SQLite, CLI, API, scheduler y workflow con dobles.
  e2e/                    # Flujos controlados sin depender de Epic en vivo.
Dockerfile
docker-compose.yml
requirements.txt
.env.example
.gitignore
README.md
docs/                     # Fuente de verdad (ver docs/INDEX.md).
```

Los nombres son una guía de responsabilidades, no una razón para crear capas vacías. Una implementación pequeña puede agrupar archivos mientras conserve estas fronteras.

## Flujo de ejecución

Scheduler, `POST /api/runs` y `Run now` llaman a `RunWorkflow.run(trigger)`. Ningún controlador ni componente del frontend contiene reglas de claim.

```text
Trigger
  -> adquirir RunLock
  -> crear Run(status=running)
  -> descubrir juegos elegibles en Free Games
  -> upsert de juegos por identificador Epic/URL estable
  -> cuentas activas ordenadas por processing_order
  -> por cada juego, secuencialmente:
       comprobar ownership
       -> already_owned: persistir resultado
       -> no owned: claim y confirmar biblioteca
       -> fallo transitorio: hasta 3 intentos con backoff
       -> CAPTCHA/MFA/auth/rate-limit/block: pausar cuenta
  -> actualizar progreso y resultados
  -> finalizar Run(status=completed/partial/failed)
  -> liberar RunLock
  -> notificación Telegram opcional
```

La adquisición del lock debe ocurrir antes de crear un workflow. Si ya existe una ejecución, el trigger devuelve `409` o una respuesta equivalente con el `run_id` activo; nunca inicia una segunda ejecución. El lock combina un lock de proceso (hilo) y un lock a nivel de archivo del SO (`state/run.lock` con detección de obsolescencia): el modo web (scheduler) y la CLI corren en procesos separados del mismo contenedor.

La cuenta afectada por una intervención deja de procesarse para evitar solicitudes repetidas. Los demás juegos y cuentas continúan solo cuando el adaptador indica que es seguro. Un fallo de un juego no detiene automáticamente los siguientes juegos.

## Dominio y estados

Entidades persistidas:

- `Account`: `id`, identidad Epic descubierta, nombre visible, estado, `enabled`, `processing_order`, timestamps y motivo del último bloqueo. La desactivación conserva historial; la eliminación permanente exige confirmación adicional y elimina sus datos asociados según la política de integridad.
- `Game`: `id`, identificador Epic cuando exista, nombre, URL, metadata técnica mínima, primera/última detección y timestamps.
- `Claim`: relación lógica única `(account_id, game_id)` con estado agregado y último resultado. La unicidad evita claims lógicos duplicados sin saltarse futuras detecciones.
- `ClaimAttempt`: resultado histórico de cada combinación `run_id + claim_id`, con estado, intentos, retryable, intervention_required, error seguro y timestamps. Esta relación conserva indefinidamente el resultado de cada ejecución sin romper la idempotencia lógica.
- `Run`: trigger (`scheduler`, `manual`, `api`), estado, inicio/fin, progreso, contadores y error resumido.
- `Settings`: configuración no secreta del scheduler, delays, retry y preferencias de integraciones.
- `RunEvent` o equivalente: eventos breves de progreso si el dashboard necesita actualización en vivo; se retienen de forma acotada para no convertirlos en analytics.

Estados de cuenta: `active`, `disabled`, `needs_authentication`, `needs_intervention`, `paused`.

Estados de claim: `claimed`, `already_owned`, `failed`, `skipped`. Los campos `retryable` e `intervention_required`, junto con el error clasificado, indican si puede reintentarse.

Estados de run: `running`, `completed`, `partial`, `failed`, `cancelled` si se incorpora cancelación explícita. `partial` representa cuentas/juegos que terminaron con errores o intervención sin ocultar resultados exitosos.

SQLite debe tener foreign keys activas, índices para historial (`account_id`, fecha, estado), `processing_order` y la restricción única de claims. Las migraciones deben ser explícitas y seguras; no se debe destruir la base al actualizar.

## Adaptador de Epic y Playwright

`EpicAdapter` expone solo capacidades necesarias para el workflow:

```text
discover_free_games() -> list[GameCandidate]
open_account_session(account_id) -> AccountSession
is_owned(session, game) -> bool
claim(session, game) -> ClaimResult
authenticate(account_id, mode) -> AuthProgress
```

Los tipos de resultado deben distinguir éxito, ya existente, error transitorio, autenticación requerida, CAPTCHA/MFA, rate limit y bloqueo. El workflow decide estados y persistencia; el adaptador conoce páginas, selectores y navegación de Epic.

La sección oficial `Free Games` es la única fuente de elegibilidad. Se excluyen "coming soon", descuentos, demos y contenido fuera de esa sección. El adaptador no asume una cantidad fija ni un cambio semanal.

Cada cuenta usa un perfil persistente independiente bajo `SESSIONS_PATH/{account_id}`. El navegador se abre bajo demanda, se reutiliza dentro de una ejecución cuando sea práctico y se cierra al finalizar para conservar RAM.

La autenticación interactiva se inicia desde la CLI (o API en modo web). Ejecuta Chromium headed dentro del contenedor bajo Xvnc (TigerVNC: servidor X + VNC en un proceso) y expone la pantalla mediante el stack noVNC como proceso standalone del entorno, publicado en su propio puerto (`NOVNC_PORT`, default 6080) sin pasar por un proxy de la aplicación. La CLI imprime la URL de acceso con token de un solo uso y contraseña efímera; el usuario la abre desde su PC o teléfono (LAN/Tailscale), completa login/MFA/CAPTCHA y la aplicación detecta el éxito, revoca el token, persiste el perfil y cierra navegador y pantalla remota. El puerto solo sirve contenido mientras exista un token activo; fuera de una autenticación no hay sesión VNC corriendo. Nunca se exponen CDP, cookies ni el perfil. Si el entorno no soporta el stack remoto (ej. desarrollo Windows), la autenticación puede usar Chromium headed local o queda marcada como no disponible en health/diagnóstico; nunca se simula como completada.

Playwright/Chromium es una capacidad comprobada por `/health`; la API y la base deben seguir disponibles si Chromium no está instalado. Las sesiones nunca aparecen en respuestas, logs, exports ni backups normales.

## API y dashboard

La API es la única interfaz del frontend. El contrato mínimo es:

```text
GET    /api/accounts
POST   /api/accounts
PATCH  /api/accounts/{id}
DELETE /api/accounts/{id}
POST   /api/accounts/{id}/authenticate
POST   /api/accounts/{id}/resolve-intervention

GET    /api/games
GET    /api/claims
GET    /api/runs
GET    /api/runs/{id}
POST   /api/runs
GET    /api/runs/{id}/events

GET    /api/settings
PATCH  /api/settings
GET    /health
```

`POST /api/runs` acepta trigger externo y opcionalmente exige `EXTERNAL_API_KEY` cuando esa protección esté habilitada. Las respuestas de ejecución incluyen estado, `run_id` y conflicto activo de forma explícita.

El dashboard tiene cuatro áreas: resumen, cuentas, historial y configuración. La ejecución tiene una vista/panel separado con eventos de detección, cuenta/juego actual, retry, intervención y resultado final. Las acciones destructivas requieren confirmación adicional. La UI no duplica reglas del backend.

Para progreso se prefiere polling corto de `/api/runs/{id}` o `/events`; no se introduce WebSocket salvo que el frontend lo necesite realmente. Esto reduce procesos y dependencias en el servidor doméstico.

## Scheduler, delays y recuperación

El scheduler interno se inicia y detiene con el ciclo de vida del runner (modo web por defecto). Es un cron simplificado: lista de días de semana (`MON..SUN`, default `THU`) + horas `HH:MM` (default `14:05`), con preset diario configurable para temporadas promocionales (ej. navidad). El núcleo determinista (`SlotRunner`, reloj inyectable) dispara a lo sumo una vez por slot y día: marca en memoria + consultas de runs ya iniciados dentro de la ventana (tolerante a reinicios; un slot perdido del día **no** se dispara retroactivamente). Se aplica un mínimo de 30 minutos entre ejecuciones automáticas. Consulta configuración en cada tick (los cambios aplican sin reiniciar) y respeta `RunLock`; un error del scheduler se registra y no crea un loop agresivo. Configuración legacy de intervalo (segundos) se migra explícitamente a slots (intervalo >= 86400 s = 24 h → días completos "diario"; otro intervalo → `THU 14:05` + nota en logs). Los helpers de días/horas viven en `app/domain/scheduling.py`.

Los delays entre acciones relevantes son aleatorios y configurables, por defecto mínimo 2 y máximo 5 segundos. Son una medida de pacing conservador, no una técnica para evadir controles de Epic.

Solo se reintentan timeouts, errores de red, cargas temporales y fallos transitorios clasificados. El máximo por operación es 3 intentos con backoff acotado. CAPTCHA, MFA, autenticación inválida, rate limit, bloqueo y desafíos anti-bot no se reintentan automáticamente. Todo error inesperado se registra con contexto seguro y puede pausar la cuenta.

Resolver una intervención cambia la cuenta a `active`, invalida acciones pendientes antiguas de Telegram y permite reanudar únicamente trabajo seguro en la siguiente ejecución o mediante una reanudación simple explícita.

## Integraciones y observabilidad

Telegram es un notificador opcional. Recibe un resumen por ejecución y alertas importantes, con deduplicación básica para evitar spam. La ausencia de Telegram no afecta scheduler, dashboard, historial ni workflow. n8n tampoco es parte del proceso: solo llama `POST /api/runs`.

Los logs estructurados deben incluir `run_id`, `account_id` y `game_id` cuando existan, además de inicio/fin, detección, resultado, retry, intervención y scheduler. Nunca incluyen contraseñas, cookies, tokens, headers sensibles ni contenido de sesión. El dashboard muestra solo logs recientes o un diagnóstico equivalente.

## Backup, export y almacenamiento

Volúmenes mínimos:

```text
/app/data/database  -> SQLite
/app/data/sessions  -> perfiles Playwright privados
/app/data/state     -> configuración/estado no secreto
```

El backup normal contiene SQLite y configuración no secreta. No contiene sesiones/cookies. Importar valida formato y versión, exige confirmación explícita y no sobrescribe datos sin autorización. Después de migrar puede ser necesario reautenticar cuentas.

La exportación de historial soporta CSV y JSON, con filtros por cuenta, estado y rango de fechas cuando aplique. Nunca exporta secretos ni sesiones.

## Despliegue y recursos

El contenedor incluye el runner (FastAPI opcional + scheduler), la CLI, dependencias Python, Chromium de Playwright y el stack de pantalla remota (Xvnc/websockify/noVNC). Puertos configurables: `APP_PORT` (default 8765, modo web) y `NOVNC_PORT` (default 6080, solo activo durante autenticaciones). Docker Compose monta los volúmenes, publica `NOVNC_PORT` (LAN/Tailscale) y el README documenta ejecución Docker y no Docker, port conflicts, LAN/Tailscale, reinicios, backups y troubleshooting.

El diseño evita workers adicionales, Chromium permanente y claims paralelos. Una sola ejecución y una cuenta/juego por vez mantienen el consumo compatible con el servidor de referencia: ~2.5 GB disponibles, 2 cores; reposo < 100 MB, pico con Chromium < 700 MB.

## Pruebas

- Unitarias: elegibilidad, transición de estados, retry, idempotencia y orden.
- Integración: SQLite, restricciones, repositorios, API, scheduler, lock y workflow con `EpicAdapter` falso.
- E2E controlada: un flujo completo con navegador/mock aislado.
- Live/manual: autenticación real y validación puntual contra Epic, nunca requisito de la suite continua.

Debe probarse el flujo normal, juegos ya adquiridos, repetición idempotente, fallos por juego/cuenta, límite de retries, CAPTCHA/MFA, rate limit, recuperación, concurrencia, persistencia, health y trigger externo. Los tests no deben contactar Epic salvo los marcados explícitamente como live/manual.

## Decisiones no negociables

- Un único workflow para scheduler, CLI, dashboard y API.
- Procesamiento secuencial y sin claims paralelos.
- SQLite como base del MVP.
- Perfiles Playwright persistentes por cuenta, fuera del filesystem efímero.
- Sin contraseñas almacenadas y sin sesiones en backups normales.
- n8n y Telegram opcionales.
- Dashboard pensado para LAN/Tailscale, sin exposición pública por defecto.
- No agregar abstracciones, usuarios, móvil, analytics ni otras plataformas sin una necesidad concreta.
