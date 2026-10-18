# Roadmap de Desarrollo

Roadmap para construir **Epic Games Free Games Auto-Claimer** hasta la versión funcional `1.0.0`.

**Revisión 2026-10-18:** se re-planó el cierre del proyecto tras una auditoría backend (ver `DECISIONS.md` D-2026-10-18 y las fases R1–R7 al final). Los milestones 0–8 se conservan como historial ya completado.

El orden prioriza:

`corrección -> seguridad -> mantenibilidad -> simplicidad -> rendimiento`

## Reglas del roadmap

- Cada milestone debe dejar una parte ejecutable y verificable del producto.
- No avanzar si el criterio de salida del milestone anterior no está demostrado.
- Scheduler, dashboard y API deben reutilizar `RunWorkflow.run(trigger)`.
- Los claims siempre se procesan de forma secuencial.
- Los tests automáticos no dependen de Epic en vivo.
- CAPTCHA, MFA, rate limits y controles anti-bot se resuelven manualmente; nunca se evaden.
- No almacenar contraseñas, cookies ni sesiones en la base de datos, logs, exports o backups normales.
- No agregar otras plataformas, usuarios, móvil, analytics o abstracciones especulativas.

## Milestone 0: Contrato de implementación

**Objetivo:** convertir la arquitectura aprobada en decisiones concretas antes de escribir funcionalidad.

- [x] Confirmar que el alcance de `v1.0.0` se limita a Epic Games Store.
- [x] Confirmar versiones mínimas de Python, Node.js, FastAPI, Playwright y SQLite.
- [x] Elegir el scheduler y las dependencias mínimas; documentar la razón de cada dependencia.
- [x] Definir el esquema SQLite y sus migraciones iniciales.
- [x] Definir estados y transiciones de `Account`, `Claim`, `ClaimAttempt` y `Run`.
- [x] Definir el contrato de `EpicAdapter` y los tipos de resultados del adaptador.
- [x] Definir payloads y respuestas de la API mínima.
- [x] Definir el flujo VNC/noVNC de autenticación interactiva y su ciclo de vida.
- [x] Definir formato de eventos de progreso y estrategia inicial de polling.
- [x] Definir qué requisitos se validarán manualmente contra Epic.

**Criterio de salida:** la implementación puede comenzar sin decisiones abiertas sobre persistencia, workflow, API, autenticación o despliegue.

## Milestone 1: Base ejecutable

**Objetivo:** iniciar la aplicación, comprobar su salud y cargar configuración sin secretos.

- [x] Crear la estructura backend, frontend, tests y despliegue indicada en `ARCHITECTURE.md`.
- [x] Configurar el entorno Python y `requirements.txt`.
- [x] Crear `.env.example` con `APP_HOST`, `APP_PORT`, `DATABASE_PATH`, `SESSIONS_PATH` y opciones de integraciones.
- [x] Crear o revisar `.gitignore` para excluir `.env`, sesiones, bases locales y artefactos de build.
- [x] Implementar validación centralizada de configuración.
- [x] Crear FastAPI con ciclo de vida explícito de startup/shutdown.
- [x] Inicializar SQLite con foreign keys activas y migración inicial segura.
- [x] Configurar logging estructurado con filtrado de secretos.
- [x] Implementar `GET /health` para aplicación, SQLite y Playwright sin tráfico a Epic.
- [x] Crear tests unitarios de configuración y tests de integración para health/database.

**Criterio de salida:** la aplicación arranca con `.env.example`, devuelve un health válido y falla con mensajes claros ante configuración inválida.

## Milestone 2: Dominio y persistencia

**Objetivo:** guardar cuentas, juegos, claims, ejecuciones, resultados históricos y settings.

- [x] Implementar modelos y enums de dominio sin duplicar literales de estados.
- [x] Crear tablas `accounts`, `games`, `claims`, `claim_attempts`, `runs` y `settings`.
- [x] Aplicar foreign keys, índices de historial y unicidad `(account_id, game_id)` en `claims`.
- [x] Mantener un `ClaimAttempt` por ejecución para conservar el historial indefinidamente.
- [x] Implementar repositories con transacciones para operaciones atómicas.
- [x] Implementar CRUD de cuentas, incluyendo `enabled`, nombre, orden y estados.
- [x] Preservar historial al desactivar una cuenta.
- [x] Definir eliminación permanente con confirmación y política de integridad.
- [x] Implementar consultas de claims con filtros por cuenta, fecha y estado.
- [x] Persistir settings no secretos del scheduler, retry, delays e integraciones.
- [x] Verificar persistencia tras cerrar y volver a iniciar la aplicación.
- [x] Crear tests de constraints, CRUD, historial, estados e idempotencia de persistencia.

**Criterio de salida:** el estado del sistema se recupera desde SQLite y una segunda escritura lógica para la misma cuenta y juego no crea un claim duplicado.

## Milestone 3: Descubrimiento de juegos

**Objetivo:** detectar juegos elegibles desde la sección oficial `Free Games` sin depender de una cantidad o calendario fijo.

- [x] Implementar `discover_free_games()` detrás de `EpicAdapter`.
- [x] Limitar la fuente a la sección oficial de juegos gratis de Epic.
- [x] Detectar cualquier cantidad de juegos disponibles en el momento de la ejecución.
- [x] Excluir juegos `coming soon`, descuentos, demos y contenido fuera de la sección objetivo.
- [x] Persistir identificador Epic cuando exista, nombre, URL y metadata técnica mínima.
- [x] Implementar upsert de juegos sin crear duplicados por detecciones repetidas.
- [x] Aislar selectores y navegación de Playwright en el módulo específico de Epic.
- [x] Crear fixtures y fakes para respuestas normales, cero juegos, varios juegos y contenido excluido.
- [x] Añadir tests de elegibilidad y de persistencia de detecciones.

**Criterio de salida:** una ejecución de descubrimiento produce una lista confiable de juegos elegibles sin contactar Epic en los tests normales.

## Milestone 4: Sesiones y autenticación interactiva

**Objetivo:** permitir autenticar y reautenticar cuentas en un navegador que corre en el servidor.

- [x] Crear un perfil persistente por cuenta en `SESSIONS_PATH/{account_id}`.
- [x] Implementar apertura y cierre seguro del contexto Playwright.
- [x] Implementar `POST /api/accounts/{id}/authenticate` para iniciar autenticación.
- [x] Implementar reautenticación usando el mismo flujo sin almacenar contraseñas.
- [x] Ejecutar Chromium headed mediante VNC/noVNC de vida corta dentro del despliegue definido.
- [x] Entregar un token de sesión de un solo uso para el panel remoto y revocarlo al terminar.
- [x] Evitar exponer CDP, cookies, tokens o el perfil persistente.
- [x] Detectar autenticación exitosa, timeout, cierre, sesión expirada, CAPTCHA y MFA.
- [x] Cambiar la cuenta a `active`, `needs_authentication` o `needs_intervention` según el resultado.
- [x] Cerrar navegador y pantalla remota después de completar o abandonar la autenticación.
- [x] Exponer la disponibilidad de Chromium y del mecanismo remoto en `/health`.
- [x] Crear tests con Playwright fake y una prueba manual documentada de login/MFA/CAPTCHA.

**Criterio de salida:** una cuenta puede autenticarse manualmente desde el dashboard, conserva su sesión después de reiniciar y no expone credenciales ni cookies.

## Milestone 5: Workflow funcional de claims

**Objetivo:** completar el flujo central con un único servicio reutilizable por todos los triggers.

- [x] Implementar `RunWorkflow.run(trigger)` con dependencias inyectables.
- [x] Adquirir `RunLock` antes de crear una ejecución.
- [x] Rechazar una segunda ejecución con el `run_id` de la ejecución activa.
- [x] Crear y actualizar `Run` con trigger, timestamps, progreso, contadores y errores.
- [x] Descubrir y persistir juegos antes de procesar cuentas.
- [x] Procesar cuentas activas en `processing_order` y juegos secuencialmente.
- [x] Comprobar ownership antes de intentar reclamar.
- [x] Registrar `already_owned` cuando el juego ya pertenezca a la cuenta.
- [x] Confirmar que Epic agregó el juego a la biblioteca antes de registrar `claimed`.
- [x] Registrar `failed` o `skipped` con contexto seguro cuando corresponda.
- [x] Crear `ClaimAttempt` para cada resultado de cada ejecución.
- [x] Reintentar solo fallos transitorios, con máximo 3 intentos y backoff acotado.
- [x] Aplicar delay aleatorio configurable entre 2 y 5 segundos por defecto.
- [x] Pausar la cuenta ante CAPTCHA, MFA, auth inválida, rate limit, bloqueo o error peligroso.
- [x] Continuar con otros juegos/cuentas solo cuando sea seguro.
- [x] Emitir eventos de progreso sin filtrar datos sensibles.
- [x] Crear tests de éxito, ya adquirido, idempotencia, orden, retry, intervención, recuperación y lock.

**Criterio de salida:** con un `EpicAdapter` fake se completa una ejecución end-to-end y se puede repetir sin duplicar claims lógicos.

## Milestone 6: API y scheduler

**Objetivo:** hacer operable el backend sin depender todavía de una interfaz completa.

- [x] Implementar `GET/POST/PATCH/DELETE /api/accounts` y acciones de autenticación/intervención.
- [x] Implementar `GET /api/games` y `GET /api/claims` con filtros útiles.
- [x] Implementar `GET /api/runs`, `GET /api/runs/{id}` y progreso de ejecución.
- [x] Implementar `POST /api/runs` como trigger externo del workflow compartido.
- [x] Devolver conflicto claro cuando ya exista una ejecución activa.
- [x] Implementar `GET/PATCH /api/settings` para opciones no secretas.
- [x] Validar payloads en los endpoints y evitar filtrar excepciones internas.
- [x] Implementar scheduler interno habilitable/deshabilitable.
- [x] Soportar intervalos configurables sin asumir únicamente jueves o cambios semanales.
- [x] Iniciar y detener el scheduler con el ciclo de vida de FastAPI.
- [x] Asegurar que el scheduler respete `RunLock` y no genere loops agresivos ante errores.
- [x] Añadir protección opcional por `EXTERNAL_API_KEY` para triggers externos.
- [x] Crear tests de contrato API, scheduler, lock, trigger externo y settings.

**Criterio de salida:** una ejecución puede iniciarse manualmente por API, automáticamente por scheduler o desde un cliente externo, siempre con el mismo workflow.

## Milestone 7: Dashboard mínimo utilizable

**Objetivo:** administrar el sistema desde la interfaz principal sin duplicar lógica de negocio.

- [x] Crear frontend compilable y servido por FastAPI o por el mecanismo definido.
- [x] Implementar resumen con salud, scheduler, próxima/última ejecución y alertas.
- [x] Implementar listado de cuentas con nombre, estado, enabled y orden.
- [x] Implementar alta, edición, activación/desactivación y reordenamiento de cuentas.
- [x] Implementar inicio y finalización de autenticación/reautenticación remota.
- [x] Mostrar y resolver cuentas en `needs_authentication`, `needs_intervention` o `paused`.
- [x] Requerir confirmación adicional para eliminación permanente.
- [x] Crear vista de ejecución separada con progreso por cuenta y juego.
- [x] Implementar polling moderado y detenerlo al finalizar una ejecución.
- [x] Crear historial con filtros por cuenta, fecha y estado.
- [x] Implementar exportación CSV y JSON sin secretos ni sesiones.
- [x] Crear settings para scheduler, delays, Telegram y otras opciones no secretas.
- [x] Mostrar logs recientes o diagnóstico equivalente sin datos sensibles.
- [x] Verificar responsive en escritorio y móvil.
- [x] Crear una prueba E2E controlada del dashboard usando API/adaptador fake.

**Criterio de salida:** un usuario puede administrar cuentas, lanzar una ejecución, observarla, resolver una intervención y consultar/exportar su historial desde el dashboard.

## Milestone 8: Integraciones opcionales

**Objetivo:** añadir notificaciones sin convertirlas en una dependencia del producto.

- [x] Implementar Telegram solo cuando esté habilitado y configurado.
- [x] Enviar resumen de ejecución con cuentas, juegos y resultados.
- [x] Enviar alertas de CAPTCHA, MFA, cuenta pausada y fallos significativos.
- [x] Evitar spam mediante deduplicación o agrupación de alertas.
- [x] Marcar como resueltas las acciones de intervención antiguas después de recuperar la cuenta.
- [x] Documentar workflow n8n `Schedule Trigger -> POST /api/runs`.
- [x] Verificar que el sistema funciona igual sin Telegram ni n8n.
- [x] Crear tests de Telegram deshabilitado, errores de integración y resumen sin secretos.

**Criterio de salida:** Telegram y n8n mejoran la operación, pero eliminarlos no rompe dashboard, scheduler, API, historial ni claims.

## Milestone 9: Backup, restore y despliegue

**Objetivo:** ejecutar el producto de forma persistente en Docker y fuera de Docker.

- [x] Implementar backup de SQLite y configuración no secreta.
- [x] Excluir perfiles, cookies, tokens y sesiones de backups normales.
- [x] Implementar importación con validación de formato y versión.
- [x] Exigir confirmación explícita y evitar sobrescritura silenciosa.
- [x] Crear `Dockerfile` con frontend compilado, backend, dependencias y Chromium.
- [x] Crear `docker-compose.yml` con volúmenes para database, sessions y state.
- [x] Configurar el puerto publicado a partir de `APP_PORT`, por defecto `8765`.
- [ ] Verificar reinicio/recreación del contenedor sin pérdida de DB ni sesiones (requiere Docker en el entorno de despliegue).
- [x] Documentar ejecución Docker, no Docker, Playwright/Chromium y frontend.
- [x] Documentar LAN/Tailscale, cambio de puerto, permisos, actualización y reinicio.
- [x] Documentar backup/restore, pérdida de sesiones y reautenticación posterior.
- [x] Documentar troubleshooting de puerto, Chromium, auth, Telegram, DB y volúmenes.
- [ ] Probar instalación limpia desde clone usando solo la documentación (requiere el entorno de despliegue).

**Criterio de salida:** el sistema funciona en un servidor doméstico con Docker y tiene una ruta documentada para ejecución no Docker y recuperación de datos.

## Milestone 10: Hardening y release candidate

**Objetivo:** demostrar que el producto cumple los requisitos importantes antes de etiquetar `1.0.0`.

- [x] Ejecutar suite unitaria completa.
- [x] Ejecutar suite de integración con SQLite temporal y adaptadores fake.
- [x] Ejecutar E2E controlada sin dependencia continua de Epic.
- [ ] Ejecutar pruebas live/manuales de descubrimiento y autenticación bajo demanda (requiere acceso real a Epic).
- [x] Verificar flujo de varias cuentas en orden y varios juegos secuenciales.
- [x] Verificar repetición idempotente con juegos nuevos y ya conocidos.
- [x] Verificar recuperación tras CAPTCHA/MFA, auth expirada, rate limit y bloqueo.
- [x] Verificar que un fallo de juego no detiene juegos posteriores cuando es seguro.
- [x] Verificar que un fallo de cuenta no impide continuar cuentas seguras.
- [x] Verificar lock de ejecuciones desde scheduler, dashboard y API.
- [x] Revisar logs, respuestas API, exports y backups buscando secretos o sesiones.
- [x] Ejecutar tests y compilación; formatter/lint no configurados en el proyecto.
- [ ] Revisar uso de memoria y cierre de Chromium en el entorno de referencia (requiere navegadores Playwright instalados).
- [x] Revisar README, `ARCHITECTURE.md`, `CODESTYLE.md`, `.env.example` y este roadmap.
- [x] Validar cada punto de la Definition of Done de `SPECS.md`.
- [x] Resolver hallazgos críticos antes de publicar la release candidate.

**Criterio de salida:** no quedan fallos críticos conocidos, las pruebas requeridas pasan y el flujo completo está documentado y reproducible.

## Re-plan 2026-10-18: fases R1–R7 (camino a 1.0.0)

Contexto y justificación de cada fase en `DECISIONS.md`. Orden de adversación: "corrección -> seguridad -> simplicidad -> rendimiento". Se hace una fase por vez con criterio de salida verificable.

### R1 — Limpieza y entorno reproducible
- [x] Confirmar `.venv` local funcional en Windows (dev): `pip install -r requirements.txt` + `playwright install chromium`.
- [x] Suite completa en verde en local; el test del proxy remoto quedó obsoleto con la eliminación del proxy (R3): reemplazado por tests de URL standalone (sin websockify).
- [x] `.env.example` actualizado con `LOCALE`, `NOVNC_PORT`, `PUBLIC_HOST` y nuevos settings de scheduler (`SCHEDULER_DAYS/TIMES/DAILY`).

**Criterio de salida:** clone limpio + venv + pytest en verde (118/118) sin Epic live. **CUMPLIDO 2026-10-18.**

### R2 — CLI principal (menú stdlib)
- [x] `app/cli.py`: menú enumerado (cuentas, autenticar, run now, historial con filtros, settings, estado).
- [x] Progreso de ejecución renderizado en consola (cuenta/juego/resultado) reutilizando eventos de run.
- [x] Confirmaciones explícitas para eliminación permanente e imports.
- [x] Tests de integración de la CLI con los services actuales (sin depender de la API).

**Criterio de salida:** gestión completa del sistema por consola sin arrancar FastAPI. **CUMPLIDO 2026-10-18** (runtime compartido en `app/bootstrap.py`).

### R3 — Autenticación interactiva funcional (noVNC standalone)
- [x] Eliminar el proxy HTTP interno de noVNC (`app/auth_proxy.py` y rutas asociadas).
- [x] noVNC/x11vnc/websockify como procesos standalone del contenedor, publicados en `NOVNC_PORT`, sin contenido sirvible sin sesión activa.
- [x] `Authenticate` desde CLI imprime URL de un solo uso (token + contraseña efímera) con instrucciones.
- [x] Detección de éxito/timeout/cierre, revocación de token, cierre de navegador y pantalla, perfil persistido.
- [x] Flujo headed local en Windows dev (sin remote screen; `LocalHeadedScreen`).
- [ ] Verificación manual completa del login remoto desde PC (éxito y timeout). Documentar resultado en `CAMBIOS.md` y resolver la deuda histórica.

**Criterio de salida:** login remoto real desde la PC del usuario con sesión persistida en el servidor y pantalla cerrada al terminar. (Código listo; verificación manual empotrada en R6 sobre g7.)

### R4 — Scheduler día+hora
- [x] Implementar cron simplificado (días + horas, slots single-shot por día, gap mínimo 30 min).
- [x] Migrar settings legacy de intervalo a slots.
- [x] Preset "diario" para temporadas promocionales; display de próxima ejecución en CLI/health.
- [x] Tests: slots, single-shot, cambios sin reiniciar, lock respetado.

**Criterio de salida:** runs automáticos solo en las ventanas configuradas, default jueves 14:05. **CUMPLIDO 2026-10-18.**

### R5 — Región (LOCALE)
- [x] Config `LOCALE` aplicada a discovery y URLs; vacío = comportamiento por IP.
- [x] Idempotencia basada en `epic_id`, independiente del locale en la URL.
- [x] Test unitario de construcción de URLs y elegibilidad por locale.

**Criterio de salida:** discovery+claim deterministas contra el dominio regional configurado. **CUMPLIDO 2026-10-18 (código y tests; confirmación live en R6).**

### R6 — Validación live contra Epic (bloqueante para release)
- [ ] Descubrimiento real de la sección Free Games (validar/ajustar selectores vigentes).
- [ ] Login real + MFA/CAPTCHA manual si Epic lo pide.
- [ ] Claim real de un juego y registro `claimed` con confirmación de biblioteca; repetir para ver `already_owned`.
- [ ] Registrar hallazgos y ajustar selectores/clasificación según la tienda actual.

**Criterio de salida:** un ciclo completo real por al menos una cuenta en el g7.

### R7 — Despliegue en g7 y release
- [ ] `docker compose up -d --build` en el g7; puertos y volúmenes verificados.
- [ ] Verificar reinicio/recreación del contenedor sin pérdida de DB ni sesiones.
- [ ] Verificar footprint: reposo < 100 MB, pico < 700 MB.
- [ ] Instalación limpia desde clone usando solo documentación.
- [ ] Cierre de milestones 9/10 y release 1.0.0 según checklist inferior.

**Criterio de salida:** checklist de Release `1.0.0` completo.

## Release `1.0.0`

Publicar `1.0.0` únicamente cuando se cumplan todos estos puntos:

- [ ] El usuario puede clonar, configurar `.env` y ejecutar con Docker o sin Docker.
- [ ] La CLI es operable por SSH y los puertos web/noVNC son configurables (dashboard opcional).
- [ ] Se pueden añadir y autenticar varias cuentas mediante el navegador remoto (noVNC standalone) desde la PC del usuario.
- [ ] Las sesiones sobreviven a reinicios normales con el volumen persistente.
- [ ] Se detectan los juegos elegibles actuales de la sección oficial `Free Games` en la región configurada.
- [ ] Los juegos se reclaman por cuenta y en orden, sin claims paralelos.
- [x] Las ejecuciones repetidas son idempotentes y conservan historial por ejecución.
- [x] Se muestran resultados `claimed`, `already_owned`, `failed` y `skipped`.
- [x] Se registran retries, errores, intervenciones y estados de cuenta.
- [x] Se puede recuperar una cuenta con CAPTCHA/MFA/auth desde el dashboard.
- [x] `Run now`, scheduler y `POST /api/runs` usan el mismo workflow.
- [x] Se puede consultar y exportar historial CSV/JSON.
- [x] Backup/import funciona sin incluir sesiones por defecto.
- [x] Telegram y n8n son opcionales y están documentados.
- [x] `GET /health` funciona sin ejecutar claims ni tráfico innecesario a Epic.
- [x] Los tests automáticos requeridos pasan sin depender continuamente de Epic.
- [x] Los logs, exports, backups y respuestas API no exponen secretos.

## Fuera de `1.0.0`

- Soporte para Steam, GOG, Ubisoft u otras plataformas.
- Compra de juegos pagos o reclamación de descuentos no gratuitos.
- Resolución o evasión automática de CAPTCHA, MFA, rate limits o bloqueos.
- Aplicación móvil, multiusuario o autenticación pública del dashboard.
- Analytics, recomendaciones o automatizaciones no necesarias para reclamar juegos.
- Paralelismo de cuentas o claims para acelerar ejecuciones.
