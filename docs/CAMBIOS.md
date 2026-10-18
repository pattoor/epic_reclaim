# Cambios recientes - Autenticación remota

> **Estado 2026-10-18:** el pipeline antiguo (proxy noVNC dentro de FastAPI) queda **descartado**. La re-arquitectura adoptada (noVNC standalone + CLI) está definida en `docs/DECISIONS.md` (D3) y el plan en `docs/ROADMAP.md` (R3). Este archivo conserva el historial del diseño previo solo como referencia de diagnosticación; ya no define dirección del proyecto.

## Estado
La autenticación interactiva aún no funciona en producción. Se acumulan problemas en el pipeline noVNC → proxy interno → navegador cliente.

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
