# Arquitectura

## Objetivo y límites

El MVP se ejecuta como un único proceso FastAPI dentro de un contenedor Docker. El proceso sirve la API y el dashboard, mantiene SQLite, ejecuta el scheduler y lanza un único workflow de claims a la vez.

La prioridad es `corrección -> seguridad -> mantenibilidad -> simplicidad -> rendimiento`. La versión 1 solo implementa Epic Games Store. No se automatizan ni evaden CAPTCHA, MFA, rate limits o controles anti-bot, y no se guardan contraseñas de Epic.

La separación interna permite sustituir el adaptador de Epic en el futuro sin convertir el MVP en un framework multi-plataforma especulativo.

## Decisiones técnicas

- **Python 3.12+** como runtime; **FastAPI 0.115+** para la API, el ciclo de vida y el servidor de la UI.
- **SQLite** (stdlib `sqlite3`) como base de datos única; sin ORM ni migraciones ajenas.
- **Playwright 1.45+** para navegación persistente; es una capacidad opcional comprobada por `/health`.
- **Scheduler interno asyncio**: un bucle propio, sin APScheduler ni procesos adicionales, respetando `RunLock`. Cada ejecución se lanza con el mismo `RunWorkflow.run(trigger)`.
- **httpx** para Telegram y para los tests de la API con `TestClient`.
- **pytest** como runner de tests; sin dependencias de framework adicionales en runtime.
- Frontend sin build step: HTML/CSS/JS estáticos servidos por FastAPI desde `static/`, consumiendo exclusivamente la API. `frontend/` queda reservado para futuras herramientas si hicieran falta.

Razón del conjunto: el proyecto debe caber en un servidor de ~4 GB, mantener un solo proceso y evitar dependencias que no aporten a corrección o mantenibilidad.

## Estructura del repositorio

```text
app/
  main.py                 # Crea la aplicación y gestiona startup/shutdown.
  config.py               # Variables de entorno y validación de configuración.
  database.py             # Conexión SQLite, migraciones/esquema e integridad.
  domain/
    models.py             # Entidades, enums y tipos del dominio.
    errors.py             # Errores clasificados por recuperación/intervención.
  repositories/            # Consultas y escrituras de persistencia.
  services/
    run_workflow.py       # Workflow único de scheduler, API y Run now.
    account_service.py    # Estados, orden y operaciones de cuentas.
    backup_service.py     # Backup/import validado sin sesiones.
    export_service.py     # Exportación CSV/JSON de historial.
  integrations/
    epic_adapter.py       # Interfaz de descubrimiento, ownership y claim.
    epic_playwright.py    # Selectores y comportamiento específico de Playwright.
    telegram.py           # Notificaciones opcionales, sin lógica de negocio.
  scheduler.py            # Scheduler interno y coordinación del ciclo de vida.
  api.py                  # Rutas, validación HTTP y serialización.
  logging_config.py       # Logs estructurados y filtrado de secretos.
  static/                 # Build del frontend servido por FastAPI.
tests/
  unit/                   # Dominio, estados, retry e idempotencia.
  integration/            # SQLite, API, scheduler y workflow con dobles.
  e2e/                    # Flujos controlados sin depender de Epic en vivo.
frontend/                 # Código fuente y dependencias del dashboard.
Dockerfile
docker-compose.yml
requirements.txt
.env.example
.gitignore
README.md
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

La adquisición del lock debe ocurrir antes de crear un workflow. Si ya existe una ejecución, el trigger devuelve `409` o una respuesta equivalente con el `run_id` activo; nunca inicia una segunda ejecución. El lock es de proceso porque el despliegue del MVP tiene una sola instancia.

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

Cada cuenta usa un perfil persistente independiente bajo `SESSIONS_PATH/{account_id}`. El navegador se abre bajo demanda, se reutiliza dentro de una ejecución cuando sea práctico y se cierra al finalizar para conservar RAM. La autenticación interactiva se inicia desde el dashboard, ejecuta el navegador en el servidor y permite que el usuario complete login, MFA o CAPTCHA manualmente. Para el MVP, el contexto headed se publica mediante una pantalla VNC/noVNC de vida corta, servida por el mismo contenedor y vinculada a un token de autenticación de un solo uso devuelto por `POST /api/accounts/{id}/authenticate`. El dashboard abre esa pantalla dentro del panel de autenticación; no se exponen CDP, cookies ni el perfil. Al confirmar autenticación o detectar timeout/cierre, se revoca el token, se persiste el perfil y se cierran navegador y pantalla remota. Si el despliegue no habilita noVNC, la autenticación interactiva queda marcada como no disponible en health y no se simula como completada.

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

El scheduler interno se inicia y detiene con el ciclo de vida de FastAPI. Consulta configuración de forma controlada, soporta intervalos configurables y no asume jueves. Antes de ejecutar usa el mismo `RunLock`; un error del scheduler se registra y no crea un loop agresivo.

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

El contenedor incluye FastAPI, frontend compilado, dependencias Python y Chromium de Playwright. `APP_HOST`, `APP_PORT` (por defecto `8765`), `DATABASE_PATH` y `SESSIONS_PATH` son configurables. Docker Compose monta los volúmenes y el README documenta ejecución Docker y no Docker, port conflicts, LAN/Tailscale, reinicios, backups y troubleshooting.

El diseño evita workers adicionales, Chromium permanente y claims paralelos. Una sola ejecución y una cuenta/juego por vez mantienen el consumo compatible con el servidor de referencia de aproximadamente 4 GB de RAM.

## Pruebas

- Unitarias: elegibilidad, transición de estados, retry, idempotencia y orden.
- Integración: SQLite, restricciones, repositorios, API, scheduler, lock y workflow con `EpicAdapter` falso.
- E2E controlada: un flujo completo con navegador/mock aislado.
- Live/manual: autenticación real y validación puntual contra Epic, nunca requisito de la suite continua.

Debe probarse el flujo normal, juegos ya adquiridos, repetición idempotente, fallos por juego/cuenta, límite de retries, CAPTCHA/MFA, rate limit, recuperación, concurrencia, persistencia, health y trigger externo. Los tests no deben contactar Epic salvo los marcados explícitamente como live/manual.

## Decisiones no negociables

- Un único workflow para scheduler, dashboard y API.
- Procesamiento secuencial y sin claims paralelos.
- SQLite como base del MVP.
- Perfiles Playwright persistentes por cuenta, fuera del filesystem efímero.
- Sin contraseñas almacenadas y sin sesiones en backups normales.
- n8n y Telegram opcionales.
- Dashboard pensado para LAN/Tailscale, sin exposición pública por defecto.
- No agregar abstracciones, usuarios, móvil, analytics ni otras plataformas sin una necesidad concreta.
