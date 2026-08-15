# Reglas Operativas para Agentes

Este archivo define cómo implementar y verificar cambios en el proyecto. No reemplaza los documentos de diseño:

- `SPECS.md`: requisitos, límites y Definition of Done.
- `ARCHITECTURE.md`: módulos, interfaces, estados y flujo técnico.
- `CODESTYLE.md`: convenciones de código, nombres, comentarios y tests.
- `ROADMAP.md`: orden de milestones y criterios de salida.

## Antes de modificar

- Leer el milestone activo de `ROADMAP.md` y el apartado relevante de `ARCHITECTURE.md`.
- Confirmar que el cambio satisface un requisito existente; no introducir funcionalidades por interés técnico.
- Revisar el estado del repositorio y conservar cambios ajenos.
- Mantener los cambios enfocados. No reformatear ni reorganizar archivos no relacionados.
- Si una decisión contradice los documentos fuente, detenerse y documentar la discrepancia antes de implementarla.

## Orden de implementación

- Respetar la secuencia de milestones de `ROADMAP.md`.
- No construir la UI para compensar reglas de negocio ausentes en backend.
- Implementar primero dominio, persistencia y servicios; después API, frontend e integraciones.
- Hacer que scheduler, `Run now` y API externa llamen al mismo `RunWorkflow.run(trigger)`.
- Mantener `EpicAdapter` sustituible por un fake desde el primer uso.
- No avanzar un milestone sin cumplir su criterio de salida y sus tests.

## Reglas de seguridad

- Nunca almacenar ni registrar contraseñas, cookies, tokens, headers sensibles o contenido de perfiles.
- No incluir sesiones/cookies en exports ni backups normales.
- No resolver, evadir ni reintentar automáticamente CAPTCHA, MFA, rate limits, bloqueos o desafíos anti-bot.
- Pausar o marcar la cuenta para intervención cuando el adaptador indique una condición de seguridad.
- Mantener el dashboard orientado a LAN/Tailscale; no asumir exposición pública.
- Tratar Telegram, n8n y cualquier API key como integraciones opcionales.
- Validar y confirmar explícitamente eliminaciones permanentes e imports que puedan sobrescribir datos.

## Reglas de dominio

- Procesar cuentas por `processing_order` y juegos secuencialmente.
- Adquirir el lock antes de iniciar una ejecución; nunca ejecutar dos workflows concurrentes.
- Mantener la idempotencia lógica con la unicidad `account_id + game_id`.
- Conservar el historial de cada ejecución mediante `ClaimAttempt`; no sustituirlo por únicamente el último resultado.
- Registrar `already_owned` antes de intentar reclamar y `claimed` solo después de confirmar la biblioteca de Epic.
- Reintentar únicamente errores clasificados como transitorios, con el límite de tres intentos y backoff definido.
- Continuar con otros juegos o cuentas solo si el estado del adaptador indica que es seguro.
- No asumir que existe una cantidad fija de juegos ni que cambian únicamente los jueves.

## Límites de módulos

- Los controladores API validan entrada, invocan servicios y serializan respuestas; no contienen reglas de claims.
- Los repositories encapsulan SQLite; los servicios expresan reglas de negocio y transacciones de alto nivel.
- El adaptador de Epic contiene selectores, navegación y clasificación de resultados externos.
- El frontend consume la API y no duplica estados, retries, idempotencia ni workflow.
- Los logs deben incluir contexto útil (`run_id`, `account_id`, `game_id`) sin datos sensibles.
- Cerrar Playwright, páginas, contextos y recursos remotos en rutas normales y de error.

## Tests y verificación

- Escribir o actualizar tests junto con cada cambio de comportamiento.
- Probar comportamiento observable, no detalles internos innecesarios.
- Usar fakes/mocks para Epic y Playwright; los tests normales no contactan la tienda real.
- Mantener separados tests unitarios, integración, E2E controlada y live/manual.
- Inyectar reloj, delays, aleatoriedad y adaptadores cuando afecten determinismo.
- Como mínimo, proteger éxito, ya adquirido, idempotencia, orden secuencial, retry limit, intervención, recuperación y lock.
- Antes de declarar un cambio terminado, ejecutar las comprobaciones aplicables del milestone: formatter, lint, type checks, tests y build frontend cuando corresponda.
- Verificar que `GET /health` no ejecuta claims ni genera tráfico innecesario a Epic.
- Usar `git diff --check` antes de finalizar.

## Cambios documentales y configuración

- Actualizar `README.md` si cambia instalación, configuración, despliegue o troubleshooting.
- Actualizar `ARCHITECTURE.md` si cambia una frontera, interfaz, estado o decisión técnica.
- Actualizar `ROADMAP.md` solo al completar o reordenar trabajo real, no para ocultar tareas pendientes.
- Mantener `.env.example` sin secretos y sincronizado con las variables soportadas.
- No editar `SPECS.md` para hacer que una implementación incumplida parezca válida.
- Mantener comentarios breves; explicar únicamente decisiones no obvias, invariantes o límites de seguridad. Para el detalle de estilo, consultar `CODESTYLE.md`.

## Cierre de una tarea

- Revisar el diff completo y confirmar que solo contiene cambios intencionados.
- Confirmar que no se filtraron secretos, sesiones ni datos sensibles en código, tests, fixtures, logs o documentación.
- Ejecutar la verificación relevante y reportar cualquier test omitido o requisito pendiente.
- No afirmar que un milestone o la versión `1.0.0` está completa sin evidencia de su criterio de salida.
