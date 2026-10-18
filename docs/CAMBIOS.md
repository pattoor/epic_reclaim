# Cambios recientes - Autenticación remota

> **Estado 2026-10-18:** el pipeline antiguo (proxy noVNC dentro de FastAPI) queda **descartado**. La re-arquitectura adoptada (noVNC standalone + CLI) está definida en `docs/DECISIONS.md` (D3) y el plan en `docs/ROADMAP.md` (R3). Este archivo conserva el historial del diseño previo solo como referencia de diagnosticación; ya no define dirección del proyecto.

## Estado
La autenticación interactiva aún no funciona en producción. Se acumulan problemas en el pipeline noVNC → proxy interno → navegador cliente.

## 2026-10-18 (ter) — Muro anti-bot de la store: probe en vivo + modo "desbloquear store"

- Run now real en g7 (runs #42/#45): discovery toca el muro anti-bot de la store y, por
  D8, la cuenta pasa a `needs_intervention` (trazas en eventos y CLI auditables).
- Proof de behavior: probe pasivo en el contenedor con el perfil real (headless) durante
  90 s: el desafío ("just a moment...") **no cede solo**; exige interacción humana.
  Conclusión: esperar no sirve y no se puede resolver solo (regla D8 intacta).
- Nuevo modo de autenticación `4) Desbloquear store`: browser headed en la pantalla
  remota abre `store.epicgames.com/free-games` con el perfil del usuario; el humano pasa
  el muro a mano; el criterio de éxito es "ofertas visibles en la página" (`_offers_
  visible`), momento en que el server cierra con `completed` y el perfil queda con las
  cookies de paso para discovery/claims. `AuthService.start(mode="unlock")` +
  `_start_urls` por sesión (start_url del browser); API `mode=unlock` también válida.
- Tests: unlock mode on screen (start_url correcto), run_auth firma extendida en fakes;
  suite 153/153.

## 2026-10-18 (bis) — Login device validado live + UX de código/JSON crudo

- **Validación end-to-end live en g7:** login real desde el PC del usuario por el modo
  device → código → tokens → headless `id/exchange` → cuenta `active`. Queda grabado
  el comportamiento: Epic muestra **JSON crudo** (callback del launcher); a pasarle al
  server el campo `authorizationCode`, y el código vence en ~5 min (un código viejo
  dio `authorization_code_not_found`). Documentado en README y D10.
- `epic_oauth.extract_authorization_code`: acepta el JSON completo que devuelve el
  redirect del launcher (o el código pelado); `submit_code` lo usa — ya no importa si
  el usuario pega el JSON entero en la CLI o por API.
- CLI: `Agregar cuenta` ofrece **encadenar el login** ("Autenticar ahora?");
  en modo device el prompt aclara el JSON crudo, el campo a copiar y el TTL del código.
- Historial de movimientos verificado: runs/claims/eventos en CLI (opciones 4/5) y
  API (`GET /api/runs`, eventos por run); logs de app en `docker logs epic-reclaim`
  (stdout redactado).

## 2026-10-18 — Login por codigo desde otro dispositivo + restauracion silenciosa (D10)

- Nuevo modo de autenticacion: la CLI (`Cuentas > Autenticar`) pide modo:
  `1) pantalla remota noVNC`, `2) codigo desde otro dispositivo`, `3) Chromium local`.
  Antes de pedir modo intenta **restauracion silenciosa** si hay refresh token guardado.
- Modo device (D10): el server imprime la URL oficial de login de Epic; el usuario abre
  el navegador de su celu/PC, completa login/MFA/captcha AHÍ, Epic muestra un codigo de
  un solo uso, se pega en la CLI, y el server lo intercambia por tokens OAuth y asienta
  la sesion en el perfil del contenedor con Chromium **headless** (no requiere Xvnc ni
  pantalla remota). Nada queda en el dispositivo del usuario.
- Nuevo modulo `app/integrations/epic_oauth.py` (stdlib): OAuth de cuentas Epic con las
  credenciales publicas del cliente del Epic Games Launcher (defaults de legendary/Heroic
  sin Registro en el portal de developers). Endpoints: `/account/api/oauth/token`
  (grants `authorization_code`/`refresh_token`), `/account/api/oauth/exchange`
  (exchange para `id/exchange` web). Tokens NUNCA se loguean; el refresh token vive SOLO
  en `data/sessions/<id>/epic_session.json` (volumen; fuera de DB/logs/backups).
- `PlaywrightAuthBrowser.run_auth` acepta `start_url` (para `id/exchange`) y `headless`;
  `AuthService.start(mode=...)`, `submit_code(token, code)` y `silent_restore(account_id)`.
- Restauracion silenciosa en runs: `RunWorkflow` recibe `restore_hook` (cableado desde
  `bootstrap` a `AuthService.silent_restore`); al inicio de cada run, cuentas
  `needs_authentication` con token guardado se re-autentican solas (evento
  `account_started: session silently restored`); si falla quedan pausadas (D8).
- API: `POST /api/accounts/{id}/authenticate?mode=device|screen|local` (devuelve
  `auth_url`) y `POST /api/auth/{token}/code` `{"code": "..."}`.
- Documentacion: D10 en `DECISIONS.md`, seccion "Login por codigo desde otro
  dispositivo" en README. Suite 149/149 verde (tests unit de epic_oauth, device flow y
  silent_restore en auth_service, restore_hook en run_workflow).

## 2026-10-18 — Reemplazo de x11vnc por Xvnc (D9)

- Diagnóstico de raíz del primer intento real: el navegador quedaba en "connecting" porque
  `x11vnc` entra en busy-loop de userspace en Debian 13 (60–95 % CPU, nunca `accept()`,
  backlog acumulado), incluso con stack aislado y puertos libres. No era código de la app.
- `NoVNCProvider` migrado de Xvfb+x11vnc+websockify a **Xvnc (TigerVNC) + websockify**;
  passfile generado con `openssl enc -des-ecb` (Debian 13 no trae `vncpasswd`; formato
  obfuscated TigerVNC idéntico, con la clave fija d3des bit-revertida por byte porque d3des
  lee los bits de la clave LSB-first). Valide aislado: el banner `RFB 003.008` responde
  inmediatamente y el e2e de noVNC autentica (`Connected (unencrypted) ...`).
- Cleanup de huérfanos extiende el patrón `pkill -f` a `Xvnc` y remueve locks/socket del
  display (`/tmp/.X99-lock`, `/tmp/.X11-unix/X99`) para evitar "Server is already active
  for display" tras cierres forzados.
- Dockerfile: `tigervnc-standalone-server` reemplaza `xvfb`+`x11vnc`. Suite 126/126 verde.
- **2026-10-18 (bis):** passfile VNC corregido d3des → auth VncAuth OK en noVNC (D9 ajustado).
  Nuevo caso de recuperación: `clear_stale_profile_locks` (nuevo módulo
  `app/integrations/profile_locks.py`, usado por los 3 `launch_persistent_context`) borra
  `SingletonLock/Cookie/Socket` huérfanos del perfil tras un cierre brusco o rebuild;
  sin esto el Chromium no arranca ("profile appears to be in use by another Chromium
  process"). Suite 131/131 verde.

## Historial de cambios del día

### 1. Dashboard: alta de cuentas, tarjetas y settings
- Formulario de alta de cuentas con validación visible, soporte Enter y feedback.
- Rediseño de `.cards` en grid responsive con estados de color.
- Settings: toggles para scheduler/Telegram e intervalo en días/horas/minutos/segundos.
- Commit: `4ebfe2f`.

### 2. Diagnóstico de noVNC
- `NoVNCProvider.diagnostics()` reporta herramientas, directorio noVNC, puertos y último error.
- Health check expone `remote_screen_diagnostics`.
- Mejoras en mensajes 503.
- Commit: `c00854d`.

### 3. Ruta de pantalla remota
- Corregido `screen_url` de `/auth-screen` a `/api/auth-screen`.
- Commit: `dbda00c`.

### 4. Proxy interno de noVNC
- Eliminado iframe y `/api/auth-screen`.
- noVNC se sirve por el mismo puerto `8765` vía `/api/remote-screen/{token}`.
- Dashboard abre noVNC en pestaña nueva.
- Puerto `6080` removido de `docker-compose.yml`.
- Commit: `5755217`.

### 5. Espera de puertos y captura de errores
- `NoVNCProvider` espera a que `x11vnc` y `websockify` escuchen antes de reportar éxito.
- Captura stderr de cada proceso.
- Corregido orden de argumentos de `websockify`.
- Commit: `ee71cb6`.

### 6. Bufferizado del proxy HTTP
- Reemplazado `StreamingResponse` por `Response` bufferizada.
- Eliminados headers problemáticos (`transfer-encoding`, `content-encoding`).
- Commit: `e20e877`.

## Problema actual
El navegador carga la URL del proxy pero la pestaña queda congelada.
Último error observado: `Failed to load ... net::ERR_INCOMPLETE_CHUNKED_ENCODING`.

## Próximos pasos sugeridos
1. Revisar logs detallados de `websockify` en producción (`docker logs -f epic-reclaim`).
2. Verificar que `websockify` realmente sirve los archivos estáticos de `/usr/share/novnc`.
3. Probar acceder directamente dentro del contenedor a `http://127.0.0.1:6080/vnc.html`.
4. Evaluar alternativas:
   - Servir noVNC con un endpoint FastAPI propio en lugar de depender de websockify como servidor web.
   - Usar un reverse proxy más robusto (por ejemplo `httpx` con `mount`) o un middleware ASGI.
   - Simplificar el flujo a una sola URL que sirva el HTML de noVNC con la contraseña inyectada.
5. Considerar test local con Docker antes del próximo deploy.

## Notas
- No ejecutar tests automáticos hasta que el flujo manual en producción funcione.
- `Dockerfile` y `docker-compose.yml` fueron modificados; recordar reconstruir la imagen en cada prueba.

## Cierre del pipeline de autenticación (2026-10-18)

El problema histórico del proxy HTTP interno quedó **descartado y eliminado**: la app ya
no sirve noVNC por su propio puerto (`app/auth_proxy.py` eliminado). noVNC corre como
stack standalone (Xvfb + x11vnc + websockify) publicado por compose en `NOVNC_PORT`, y la
URL de un solo uso apunta directo a ese puerto (`/vnc.html?host=...&password=<efímera>`).

Validación técnica en g7 (18/10/2026):

- Arranque de sesión: procesos vivos, URL correcta, `vnc.html` servido en `6080`.
- Revocación: la pantalla deja de responder al revocar (noVNC cerrado).
- Zombie-proof: si una sesión anterior queda colgada, el siguiente `start()` limpia los
  procesos huérfanos de la propia familia (`Xvfb`, `x11vnc`, `websockify`).
- El cierre del navegador es cooperativo: al revocar se activa un flag que el thread del
  login chequea cada 3 s y cierra Chromium con gracia por el propio thread de Playwright.

Login real del usuario (éxito y timeout) queda como paso manual documentado en R3/R6.

## 2026-10-18 (tarde) — Fix "Failed to connect to server" en noVNC (g7)

Causa raíz doble, diagnosticada con chrome-devtools-mcp (consola real del navegador)
más sondas TCP/WS/RFB dentro del contenedor:

1. **Readiness de Xvnc:** acepta TCP desde el arranque pero rechaza handshakes
   (`RFB 003.003` + tipo nulo) durante los primeros segundos. El provider soltaba la
   URL cuando el puerto abría → la primera conexión del navegador fallaba.
2. **Blacklist de TigerVNC:** toda negociación RFB abandonada es un *security
   failure* por dirección; al compartir 127.0.0.1 vía websockify, unos pocos
   abandonos banearon el servidor ("Too many security failures") y persistieron los
   reintentos.

Cambios (commit `0b4b068`):
- `NoVNCProvider.start()` ahora espera un **handshake VncAuth completo** local
  (banner 3.8 + challenge/response DES con el password de la sesión vía `openssl`).
- No se fuerza `-BlacklistThreshold 0`; queda el default de TigerVNC.
- Tests actualizados (`test_remote_screen.py`); suite 131/131.

## 2026-10-18 (noche) — Auth: abrir /id/login directo en vez de la portada

El intento real quedaba atascado en el desafío "verify you are human" de la
portada de la store (nunca llegaba a la página de login). `PlaywrightAuthBrowser`
ahora abre `www.epicgames.com/id/login?redirectUrl=<store base>` directamente:
es la página real de login, sin el muro anti-bot de la storefront, y tras el
login vuelve al home de la store donde corre la sonda de éxito existente.
Verificado en g7 con la pantalla remota: el formulario "Sign in to Epic Games"
se renderiza sin desafío. El desafío anti-bot sigue clasificado como
intervención (D8): el usuario lo completa a mano, nunca se evade.

## 2026-10-18 (noche II) — Helper local_login.py para el fallback manual (SPECS 15)

El login via noVNC quedo bloqueado en la verificacion humana de Google en el
Chromium remoto. Se implemento el fallback documentado: `tools/local_login.py`
abre un Chrome **con perfil dedicado persistente** (default) o aislado (`--fresh`)
en la PC del usuario; luego el perfil se copia al volumen del server y la
deteccion de sesion activa completa la autenticacion. La deteccion de login en
`auth_browser.py` ahora reconoce controles en espanol e ingles y la store ya
logueada. Nunca se usa el perfil diario del usuario (expondria sesiones
no relacionadas al copiar).
