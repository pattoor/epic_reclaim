# Decisiones del proyecto (registro de decisiones)

Formato: append-only. Cada decisión nueva agrega una entrada; si supersede a otra, lo indica explícitamente. Cada entrada incluye: contexto, opciones consideradas, decisión, justificación y restricciones que genera.

---

## D-2026-10-18 — Revisión y adjudicación de decisiones tras auditoría

Estado: **adoptadas**. Contexto: la auditoría de octubre 2026 concluyó que el backend core está sólido (93/94 tests en verde), pero la autenticación interactiva remota está rota y ningún flujo fue validado contra Epic real. Estas decisiones guían la re-planificación (ver `ROADMAP.md`, fases R1–R7).

### D1 — Entornos: desarrollo local y despliegue en g7

- **Contexto:** el desarrollo ocurre en una PC Windows; el despliegue objetivo es un servidor doméstico "g7" (Debian 13, 2 cores, 3.7 GB RAM con ~2.5 GB libres conviviendo con otros contenedores Docker, incl. n8n).
- **Decisión:**
  1. Desarrollo local con `.venv` (Python ≥ 3.12, Playwright + Chromium local), sin instalar dependencias globales en la PC.
  2. Despliegue de producción **exclusivamente en Docker** en el g7: imagen autocontenida con Chromium incluido. Este servicio no instala Python/Playwright nativo en el g7.
- **Justificación:** aislamiento, instalación limpia reproducible desde clone, y el stack de pantalla remota (Xvfb/x11vnc/noVNC) es Linux-only; el Windows local queda solo para desarrollo.
- **Restricciones:** el entorno de referencia de recursos pasa a ser el g7 real (~2.5 GB útiles, no los ~4 GB teóricos originales). El código debe seguir siendo multiplataforma en lo razonable, pero la validación de producción es solo Linux.

### D2 — Interfaz principal: CLI por consola; FastAPI/dashboard opcional

- **Contexto:** el usuario gestiona el servidor por SSH y prefiere un menú de consola con opciones numeradas sobre un dashboard web.
- **Opciones:** (a) mantener dashboard web como único punto de gestión, (b) dashboard web mejorado, (c) CLI console (~solo stdlib) + FastAPI opcional.
- **Decisión:** (c).
  1. Interfaz primaria: **CLI stdlib** (`python -m app.cli`): menú enumerado, sin dependencias extra (no Rich/Textual).
  2. FastAPI + dashboard estático se conservan como **modo opcional** (`python -m app.web` arranca scheduler + API + UI).
  3. Por defecto, en el contenedor de producción corre el **modo web desactivado** y solo el runner (scheduler + CLI bajo demanda); el CLI no necesita la API para operar: puede hablar directo con services, o con la API cuando esté disponible.
- **Justificación:** el usuario opera por consola; una CLI reduce memoria y superficie web, y mantener FastAPI opcional conserva n8n/cron externos/`/health` sin obligarlos.
- **Restricciones:** CLI y API **comparten los mismos services/repositories**; ninguna duplica reglas de negocio. La CLI nunca requiere la web para operar.

### D3 — Autenticación interactíva remota (login desde PC, sesión queda en g7)

- **Contexto:** el g7 no tiene GUI. El usuario se loguea desde su PC principal; el flujo debe poder iniciarse desde cualquier lugar de su red confiable (LAN/Tailscale) y la sesión debe quedar almacenada en el contenedor del g7. El diseño previo (proxy noVNC dentro del proceso FastAPI) fallaba runtime con `ERR_INCOMPLETE_CHUNKED_ENCODING` (historial completo en `CAMBIOS.md`).
- **Opciones:** (a) arreglar el proxy interno FastAPI→websockify, (b) noVNC standalone publicado por compose, (c) login local en Windows + copia manual del perfil por scp.
- **Decisión:** (b), con (c) documentado como fallback manual.
  1. `docker-compose.yml` publica el puerto de la pantalla remota; **noVNC/websockify corren como proceso standalone**, no proxyear dentro de la app. Se elimina el proxy HTTP propio (raíz del fallo).
  2. Al ejecutar **Authenticate** desde la CLI, esta imprime: `Abrí http://<ip-g7>:<NOVNC_PORT>/vnc.html?...&password=...` con **token de un solo uso + contraseña efímera por sesión**; el browser headed corre en el contenedor (Xvfb + Chromium).
  3. Al terminar (éxito, timeout o cierre), se revoca el token, se persisten cookies en el **volumen de perfiles persistente** del g7 y se cierran navegador y pantalla remota. No se exponen CDP, cookies ni el perfil.
  4. En desarrollo Windows, la autenticación puede abrir un Chromium headed real en pantalla local (sin noVNC).
- **Justificación:** usa el stack estándar sin capa ad-hoc de proxy HTTP, elimina la pieza que rompía, y cumple "me logueo desde mi PC principal y las credenciales quedan en el g7".
- **Restricciones:** sin exposición pública (LAN/Tailscale). El puerto de pantalla remota solo sirve contenido con token activo; sin autenticación pendiente no hay sesión VNC corriendo.

### D4 — Scheduler por día y hora (reemplaza intervalo fijo)

- **Contexto:** el usuario quiere ejecución por defecto **jueves 14:05**, configurable por días y horario; en temporadas promocionales (ej. navidad) Epic regala juegos **diariamente**. El scheduler anterior era interval-based (default 6 h).
- **Decisión:** reemplazarlo por un **scheduler tipo cron simplificado** (bucle asyncio, stdlib, sin APScheduler/cron externo):
  - Config: lista de días de la semana (`MON..SUN`, default `THU`) + lista de horas `HH:MM` (default `14:05`). Preset "diario" para temporadas promocionales.
  - Set-correct / idempotente: si entre ticks ya se corrió el slot configurado del día, no se repite.
  - Autoflags opcionales (admin): `giveaway_season_mode=true` → fuerza preset diario durante el periodo indicado (rango fecha inicio/fin) para navidad.
  - Conserva `RunLock` (nunca dos ejecuciones concurrentes) y un mínimo razonable entre ejecuciones automáticas (≥ 30 min).
- **Justificación:** match exacto con la expectativa del usuario ("jueves a la tarde"), control fino para temporadas diarias, sin dependencias nuevas y sin encender Chromium cada 6 h cuando no hay nada que reclamar.
- **Restricciones:** nunca asume que los juegos solo cambian los jueves; la actividad de Epic es impredecible. Cambia la config sin reiniciar (lee settings en cada tick).

### D5 — Región/country de Epic Store

- **Contexto:** la sección de juegos gratis debe reflejar la región del despliegue/cuenta. Epic resuelve región por IP del servidor; un mismo usuario ("cuenta") siempre opera con su dominio regional.
- **Decisión:**
  1. Config `LOCALE` (ej. `es-AR|en-US|...`) asigna explícitamente el dominio regional; discovery + claim usan urls construidas con ese locale. Si vacío, se usa el redireccionamiento por IP (comportamiento actual de Epic).
  2. NO hay geo-detección automática por usuario; cada deployment opera un locale (servidor doméstico con usuarios de una misma zona). LosRequestos multi-region multi-usuario quedan fuera de v1.
- **Justificación:** determinismo: locale fijo hace el claim reproducible; auto-detectar por IP activa comportamientos sorpresa (cambios de región del server, VPNs) que rompen el claim idempotente.
- **Restricciones:** las URLs persistidas en DB deben conservar el locale con el que se descubrieron; el idempot wireless usa `epic_id`/slug (no la URL completa con locale), para que un cambio de locale no duplique claims.

### D6 — Presupuesto de recursos (g7)

- **Contexto:** g7 con ~2.5 GB RAM libres (n8n + otros servicios corriendo) y 2 cores.
- **Decisión de presupuesto:**
  - Contenedor `epic-reclaim` idle (solo scheduler + SQLite): **< 100 MB**.
  - Durante ejecución (Chromium headless): pico total **< 700 MB**.
  - Un solo browser headless a la vez, contexts cerrados entre cuentas, Chromium apagado al terminar cada ejecución.
  - Prohibido: workers HTTP extra, browser permanente, claims paralelos, polling rápido, reintentos agresivos.
- **Justificación:** convive con servicios críticos en el mismo host; el pico es breve (2–5 min por ejecución semanal/diaria).

### D7 — Alcance v1 finalizada (re-scope 1.0.0)

- **Decisión:** se mantiene el alcance 1.0.0 de `SPECS.md` con estos ajustes por D1–D6:
  - Interfaz primaria CLI (dashboard/API opcionales).
  - Scheduler día+hora en lugar de intervalo.
  - Login remoto vía noVNC standalone (no proxy interno).
  - Región vía `LOCALE` config.
  - Validación live contra Epic es **obligatoria** antes de declarar 1.0.0 (verify selectores contra la tienda actual).
- Todo lo demás se reaffirma sin cambios: no otras tiendas en v1, no compras de juegos pagos, no evasión de CAPTCHA/MFA/anti-bot, no almacenar contraseñas, no sesiones en backups normales.
