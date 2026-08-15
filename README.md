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

- Linux/Debian recomendado.
- Docker y Docker Compose para el despliegue recomendado.
- Aproximadamente 4 GB de RAM en el servidor de referencia.
- Para ejecucion local: Python, Node.js, dependencias del frontend y Chromium de Playwright.
- Acceso LAN o Tailscale al puerto de la aplicacion.

El puerto por defecto es `8765`, pero es configurable y no se asume que este libre.

## Inicio rapido con Docker

```bash
git clone <repository-url>
cd epic_reclaim
cp .env.example .env
docker compose up -d --build
```

Abrir `http://<IP_DEL_SERVIDOR>:8765` desde la red local o la direccion Tailscale del servidor.

Los volumenes deben conservar, como minimo:

- Base de datos SQLite.
- Perfiles persistentes de Playwright.
- Estado requerido por la aplicacion.

Para cambiar el puerto publicado, ajustar `APP_PORT` o el mapeo correspondiente en Compose y reiniciar el servicio.

## Ejecucion sin Docker

La documentacion de desarrollo debe cubrir el siguiente flujo:

1. Crear un entorno virtual de Python.
2. Instalar `requirements.txt`.
3. Instalar las dependencias del frontend y generar su build.
4. Instalar Chromium y dependencias de Playwright.
5. Copiar `.env.example` a `.env` y definir las rutas de datos.
6. Iniciar la API y el frontend segun la configuracion del proyecto.
7. Mantener habilitado el scheduler interno o usar un trigger externo.

La base de datos y los perfiles de navegador deben apuntar a ubicaciones persistentes fuera de directorios temporales.

## Configuracion

Ejemplo minimo:

```env
APP_HOST=0.0.0.0
APP_PORT=8765

DATABASE_PATH=/app/data/database/epic.db
SESSIONS_PATH=/app/data/sessions

TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

EXTERNAL_API_KEY_ENABLED=false
EXTERNAL_API_KEY=
```

`.env` contiene configuracion local y secretos, por lo que debe permanecer ignorado por Git. La aplicacion nunca guarda contrasenas Epic como campos normales.

Entre las opciones de comportamiento se incluyen el intervalo del scheduler, su habilitacion, los delays minimo/maximo entre acciones y la configuracion de Telegram. Los nombres definitivos de variables pueden evolucionar junto con el contrato de configuracion.

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

El scheduler interno puede activarse o desactivarse y configurarse por intervalo. No depende de un dia concreto de la semana y no inicia una segunda ejecucion mientras otra siga activa.

Para integraciones locales o n8n:

```text
Schedule Trigger -> POST /api/runs
```

El endpoint usa el mismo workflow del dashboard. Una API key opcional puede proteger triggers expuestos fuera de una red confiable.

Comprobacion de salud:

```text
GET /health
```

La respuesta comprueba el estado de la aplicacion, SQLite y la disponibilidad de Playwright sin realizar claims ni trafico innecesario contra Epic.

## Intervenciones humanas

CAPTCHA, MFA, autenticacion expirada, rate limits y bloqueos no se resuelven ni se reintentan ciegamente. La cuenta pasa a `needs_intervention`, `needs_authentication` o `paused`, con el motivo visible en el dashboard.

Una vez resuelto el problema desde el dashboard, la cuenta vuelve a `active` y puede continuar el trabajo pendiente de forma segura. Telegram puede avisar de estas situaciones, pero no es necesario para resolverlas.

## Backup y restore

El backup normal incluye SQLite y la configuracion no secreta necesaria para restaurar el estado. No incluye perfiles de navegador, cookies ni sesiones.

La importacion valida el archivo y requiere confirmacion explicita antes de restaurar. Tras migrar o reinstalar, las cuentas pueden necesitar autenticarse nuevamente.

## Seguridad y limites

- El dashboard esta pensado para LAN/Tailscale y no se expone publicamente por defecto.
- No se almacenan contrasenas Epic en la base de datos.
- No se muestran ni exportan cookies, tokens o sesiones.
- No se automatiza ni evade CAPTCHA, MFA, rate limits o controles anti-bot.
- Los claims son secuenciales y usan delays conservadores configurables.
- Los logs excluyen secretos y datos sensibles.

## Pruebas

La suite debe separar:

- **Unitarias:** reglas de elegibilidad, estados, reintentos e idempotencia.
- **Integracion:** SQLite, API, scheduler, lock y persistencia del workflow.
- **E2E controladas:** flujo completo con Epic/browser aislados o mockeados.
- **Live/manuales:** autenticacion real y validaciones contra Epic, ejecutadas bajo demanda.

Los tests automatizados no deben depender continuamente de la tienda Epic en vivo.

## Troubleshooting

- **Puerto ocupado:** cambiar `APP_PORT` y el puerto publicado por Docker Compose.
- **Chromium o Playwright falla:** instalar las dependencias del navegador y revisar logs del contenedor.
- **Sesion expirada:** iniciar reautenticacion desde **Accounts**.
- **CAPTCHA o MFA:** completar la accion manualmente en el navegador del servidor.
- **Telegram no configurado:** dashboard, historial y scheduler siguen funcionando sin Telegram.
- **Base de datos con problemas:** revisar la ruta persistente, permisos y el estado del volumen.
- **Sesion perdida tras reinicio:** verificar que `SESSIONS_PATH` este montado en un volumen persistente.
- **Restauracion:** validar el backup, confirmar la importacion y reautenticar cuentas si las sesiones no estaban incluidas.

## Alcance

La version 1 soporta unicamente Epic Games Store. No compra juegos pagos, no reclama descuentos que no sean realmente gratuitos y no incluye aplicacion movil, multiusuario, recomendaciones ni analytics no relacionados con claims.
