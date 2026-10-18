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

### D8 — Descubrimiento con perfil autenticado y clasificación anti-bot (2026-10-18)

- **Contexto:** validación live en g7 (R6): un `chromium` headless de contexto fresco recibe
  el desafío anti-bot del store (Cloudflare, HTTP 403 "One more step / security check") y el
  adaptador devolvía `0` juegos en silencio. Reglas del proyecto: **no evadir ni reintentar
  automáticamente** desafíos anti-bot.
- **Decisión:**
  1. El descubrimiento (`discover_free_games`) puede reutilizar el **perfil persistente de una
     cuenta ya autenticada** del usuario (cookies obtenidas por su login manual legítimo;
     solo lectura de la página pública Free Games). `RunWorkflow` elige la primera cuenta que
     tenga `epic_identity`; configurations sin cuentas autenticadas usan contexto fresco.
  2. Marcadores de desafío (`one more step`, `security check`, `checking your browser`,
     captcha, MFA) se clasifican como `InterventionRequiredError` — el run falla indicando
     intervención, sin retries ni evasión.
  3. Si la página Free Games cambia de estructura (no hay cards ni texto esperado), se
     sube el mismo error de intervención con causa "selectores a revisar", nunca un 0-juegos
     silencioso.
  4. `NoVNCProvider.start()` limpia procesos huérfanos de la propia familia de herramientas
     antes de arrancar, para que una sesión interrumpida no deje los puertos inutilizables.
- **Justificación:** es honesto con el usuario (el desafío requiere acción humana), reusa el
  acceso legítimo que el usuario creó manualmente y mantiene la regla anti-evasión.
- **Restricciones:** no se ocultan ni procesan cookies; el perfil es el propio volumen
  `sessions` protegido; nunca exportarlo ni trasmitirlo.
- **Ajuste (2026-10-18, live):** verificado con un probe pasivo (90 s, muestra cada 5 s)
  que el muro de la store desde la IP del datacenter **es interactivo y no cede**
  (esperar más no lo resuelve). Se mantiene la regla de nunca resolverlo
  automáticamente, así que se sumó el modo **"desbloquear store"**: el usuario humano
  pasa el muro a mano en el browser headed del server mediante la pantalla remota
  (el objetivo de éxito pasa a ser "ofertas visibles"); el perfil persistente guarda
  las cookies de paso y las ejecuciones siguientes las reutilizan sin más. Detalle en
  README, sección "Desbloquear la store cuando el muro anti-bot truena el run".

### D9 — Pantalla remota con Xvnc (TigerVNC) en lugar de x11vnc (2026-10-18)

- **Contexto:** el primer intento real de login remoto en g7 quedó atascado en
  "connecting" del cliente noVNC. El diagnóstico de raíz (probes de TCP/WS dentro del
  contenedor) mostró que `websockify` sirve estáticos y completa el handshake WS, pero
  `x11vnc` nunca hace `accept()`: queda en busy-loop de userspace (60–95 % CPU) incluso
  en un stack aislado (`Xvfb :98` + `x11vnc` limpio, puerto libre, sin auth) en
  Debian 13. No es código de la app.
- **Opciones:** (a) depurar/tunear `x11vnc` (flags, versión, glibc), (b) reemplazarlo por
  `Xvnc` de TigerVNC (servidor X + servidor VNC en un solo proceso; Xvfb y x11vnc
  desaparecen), (c) otra capa de escritorio remota (KasmVNC, xrdp).
- **Decisión:** (b). Valide aislado en el contenedor: `Xvnc :96 -geometry 1280x800
  -depth 24 -rfbport <port> -PasswordFile <passfile> -localhost` responde el banner
  `RFB 003.008` inmediatamente. `NoVNCProvider` pasa de 3 procesos (Xvfb+x11vnc+
  websockify) a 2 (Xvnc+websockify); el passfile se genera con `openssl enc -des-ecb`
  con la clave fija d3des bit-revertida por byte (d3des computa su schedule de clave
  LSB-first, equivalente a DES estándar con cada byte de clave invertido; Debian 13
  no trae `vncpasswd`). Verificación end-to-end: handshake RFB 3.8 VncAuth contra el
  Xvnc vivo da `result=0`, y el e2e de navegador (Chromium + noVNC) autentica
  `Connected (unencrypted)`. El cleanup de procesos huérfanos y locks de display
  (`/tmp/.X99-lock`, `/tmp/.X11-unix/X99`) cubre el nuevo servidor.
- **Justificación:** stack estándar probado, un proceso menos, y elimina la dependencia
  de un binario que falla como busy-loop en el entorno objetivo.
- **Restricciones:** Dockerfile instala `tigervnc-standalone-server` en lugar de
  `xvfb`+`x11vnc`; en modoheaded Windows/macOS sigue sin VNC (`LocalHeadedScreen`).
- **Ajuste sobre la decisión (mismo día, live g7):** el primer intento real daba
  "Failed to connect to server" con HTTP/WS sanos. Hallazgos verificados:
  (1) durante los primeros segundos Xvnc acepta TCP pero responde `RFB 003.003` +
  tipo nulo (rechazo), así que esperar el puerto TCP no basta como readiness;
  (2) TigerVNC cuenta toda negociación abandonada como *security failure* por
  dirección y banea tras N fallos ("Too many security failures"): como todos los
  clientes llegan por websockify (127.0.0.1), un solo abandono bloquea a todos.
  Por eso la sonda de readiness de `NoVNCProvider.start()` completa un handshake
  VncAuth real (challenge-response DES vía `openssl`, mismo password del passfile;
  la auth exitosa resetea el contador) en vez de leer solo el banner, y NO se
  fuerza `-BlacklistThreshold 0` (probarlo lo confirmó: un abandono banearía al
  instante; el default 5 tolera pestañas cerradas a medias). En g7 verificado:
  la primera conexión del navegador tras el arranque conecta de una, y
  reconexiones rápidas repetidas no degradan el servidor.

### D10 — Login por código desde otro dispositivo + restauración silenciosa (2026-10-18)

- **Contexto:** el login por pantalla remota (D9) funciona, pero escribir MFA/CAPTCHA
  dentro de noVNC es lento y el usuario quiere loguearse desde el celular sin copiar
  archivos ni instalar nada. Además, las re-autenticaciones durante runs no debían
  exigir intervención humana si podía evitarse.
- **Opciones:** (a) device-code OAuth de Epic Online Services (requiere registrar una
  app en el portal de developers), (b) authorization code con las credenciales
  públicas del cliente del Epic Games Launcher (los mismos defaults que legendary y
  Heroic usan hace años), (c) no hacer nada más.
- **Decisión:** (b), con restauración silenciosa por refresh token.
  1. **Modo device (CLI opción "código desde otro dispositivo"):** el server genera
     `https://www.epicgames.com/id/login?redirectUrl=<redirect clientId response=code>`;
     el usuario lo abre en el navegador de su celu o PC (cuentas ya logueadas), se
     loguea ahí (MFA en mano, sin noVNC) y Epic muestra un código de un solo uso; lo pega
     en el CLI. El server intercambia el código por tokens OAuth, crea un exchange
     code y lanza Chromium headless en `id/exchange?exchangeCode=...` que asienta las
     cookies SSO en el perfil del g7. Nada queda en el dispositivo del usuario.
  2. **Restauración silenciosa:** el refresh token se guarda SOLO junto al perfil
     (`data/sessions/<id>/epic_session.json`, volumen del server; nunca en la DB,
     logs ni backups). En cada run, las cuentas en `needs_authentication` con token
     guardado se restauran solas antes del loop de claims (hook en `RunWorkflow`);
     también se intenta primero al autenticar desde el CLI. Si Epic rechaza el token,
     la cuenta queda igual que antes (D8) y corresponde login manual.
  3. La identidad del usuario viene del token (`account_id`/`display_name`), no del
     scraping de la página, salvo que este falte.
  4. **Respuesta esperada (2026-10-18, verificado live):** al terminar el login, Epic
     redirige al callback del launcher (`localhost/launcher/authorized?code=...`) y el
     navegador muestra un JSON crudo (a veces con warning "Do not share..."). Es el
     retorno del launcher sin receptor en el cliente; no es un error. El campo a pasar
     al server es `authorizationCode` (el CLI/API acepta el JSON completo o el código
     pelado vía `extract_authorization_code`). El código es de un solo uso y vence en
     ~5 minutos (verificado: un código de un intento previo dio `authorization_code_
     not_found` minutos después); generar y pegar de inmediato.
- **Justificación:** sin registro de app ni secretos propios; login real de Epic en el
  navegador del usuario (nunca pasamos credenciales) y re-auths sin intervención.
  Credenciales del launcher escritas en las constantes de `epic_oauth.py`: son
  públicas de larga data en proyectos OSS del ecosistema; no son secretos del repo.
- **Restricciones:** no resuelve CAPTCHA/MFA automáticamente; todo lo interactivo sigue
  siendo manual (D8). Los tokens nunca se loguean. El modo "device" corre headless,
  así que no requiere pantalla remota ni Xvnc.
