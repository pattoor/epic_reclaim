# Code Style

Convenciones para mantener el MVP pequeño, legible y barato de mantener. Si una regla contradice el formatter, el type checker o una convención ya establecida por el proyecto, prevalecen las herramientas y la consistencia local.

## Principios

- Priorizar corrección, seguridad, mantenibilidad y simplicidad antes que micro-optimizaciones.
- Reutilizar conceptos, tipos, constantes y nombres existentes; no crear sinónimos para el mismo dato.
- Mantener cada módulo con una responsabilidad clara.
- Preferir funciones pequeñas y lineales. Extraer una función solo cuando se reutiliza, aisla una decisión compleja o mejora una prueba.
- No añadir dependencias, capas, abstracciones multi-plataforma o helpers genéricos sin una necesidad concreta.
- Mantener el backend como fuente única de reglas de negocio; el frontend consume la API.

## Nombres

- Python: `snake_case` para módulos, funciones y variables; `PascalCase` para clases; `UPPER_SNAKE_CASE` para constantes.
- JavaScript/TypeScript: `camelCase` para variables y funciones; `PascalCase` para componentes y clases.
- Usar nombres de dominio: `account_id`, `game_id`, `run_id`, `processing_order`.
- No abreviar nombres si se pierde significado. `retry_count` es preferible a `rc`.
- Un mismo concepto debe tener un solo nombre en dominio, persistencia, API y frontend.
- Los estados deben reutilizar enums/constantes compartidos, no literales dispersos.

## Funciones y flujo

- Mantener una función enfocada en una decisión o transformación principal.
- Validar entradas en el borde de la aplicación; mantener los servicios con tipos ya válidos.
- Usar retornos tempranos para errores y casos excluidos, evitando anidamiento profundo.
- Pasar dependencias explícitamente, especialmente repositorios, reloj, delays y adaptadores; facilita tests sin Epic real.
- No duplicar el workflow de claims para scheduler, API o dashboard.
- Mantener los claims secuenciales y el lock de ejecución en el servicio de workflow.
- Hacer visibles los efectos importantes: escritura en DB, navegación, retry y cambio de estado.
- No ocultar errores con `except Exception` sin registrar contexto seguro y clasificar la recuperación.

## Comentarios y documentación

- El código debe explicar el `qué` mediante nombres claros; los comentarios explican solo el `por qué` no obvio.
- Preferir un comentario breve de una o dos líneas. No comentar asignaciones, getters ni código evidente.
- Documentar una función cuando su contrato, efectos, invariantes o decisión de seguridad no se deduzcan del nombre y tipos.
- En una función compleja, explicar al inicio la estrategia y sus límites, no cada línea.
- Actualizar el comentario cuando cambie la lógica; evitar comentarios que repitan implementación.
- No usar comentarios como registro de tareas. Las decisiones de arquitectura van en `ARCHITECTURE.md`.

Ejemplo adecuado:

```python
# No reintentar desafíos de seguridad: repetirlos puede bloquear la cuenta.
if result.requires_intervention:
    return pause_account(result)
```

Ejemplo innecesario:

```python
# Incrementa el contador de intentos.
attempts += 1
```

## Errores, logs y secretos

- Usar errores tipados para distinguir retryable, autenticación, intervención, rate limit y bloqueo.
- Registrar `run_id`, `account_id` y `game_id` cuando estén disponibles.
- Los mensajes deben indicar contexto y acción posible sin filtrar secretos.
- Nunca registrar contraseñas, cookies, tokens, headers de autorización ni rutas/contenido sensible de sesiones.
- No reintentar ciegamente CAPTCHA, MFA, autenticación inválida, rate limits o bloqueos.
- Usar niveles de log coherentes: `debug` para diagnóstico local, `info` para ciclos normales, `warning` para recuperación/intervención y `error` para fallos no recuperados.

## Persistencia y API

- Mantener SQL y detalles de SQLite en repositories/database; los servicios expresan reglas de negocio.
- Usar transacciones para cambios que deban ser atómicos.
- Conservar la restricción única de `account_id + game_id` para idempotencia.
- No borrar historial al desactivar una cuenta.
- Validar payloads y devolver errores HTTP consistentes; no filtrar excepciones internas al cliente.
- Mantener DTOs/respuestas API estables y no exponer modelos internos o sesiones.

## Playwright y recursos

- Encapsular selectores y navegación específica de Epic en el adaptador.
- Cerrar contextos, páginas y navegadores en `finally` cuando ya no sean necesarios.
- Evitar recargas y requests innecesarias.
- Procesar cuentas y juegos en orden, con delay configurable de 2 a 5 segundos por defecto.
- No automatizar ni intentar evadir CAPTCHA, MFA, rate limits o controles anti-bot.
- Mantener Playwright sustituible por un fake en unit/integration tests.

## Frontend

- Componentes enfocados en presentación y eventos de usuario; la lógica de claims vive en backend.
- Mantener cuatro áreas claras: resumen, cuentas, historial y configuración.
- Separar la vista de progreso de ejecución del resumen principal.
- Mostrar estados y acciones de intervención explícitamente.
- Confirmar dos veces acciones destructivas como eliminar cuentas o importar backups.
- Evitar polling excesivo; detener actualizaciones cuando la ejecución termine o el componente se desmonte.
- Diseñar responsive para LAN/Tailscale en escritorio y móvil, sin crear una aplicación móvil aparte.

## Tests

- Probar comportamiento observable y casos de recuperación, no implementación interna.
- Usar fakes/mocks para Epic y Playwright; la suite normal nunca depende de la tienda en vivo.
- Nombrar tests con contexto y resultado esperado: `test_retryable_failure_stops_after_three_attempts`.
- Cubrir como mínimo éxito, ya adquirido, idempotencia, orden secuencial, intervención, recuperación y lock concurrente.
- Separar tests unitarios, integración, E2E controlada y live/manual.
- Mantener los tests deterministas: reloj, delay, aleatoriedad y adaptadores deben poder inyectarse.

## Dependencias y cambios

- Preferir la librería estándar cuando cubra la necesidad.
- Antes de añadir una dependencia, comprobar si el código existente ya resuelve el problema.
- Cada dependencia debe justificar tamaño, mantenimiento y compatibilidad con el contenedor de aproximadamente 4 GB de RAM.
- Evitar cambios de formato masivos no relacionados con la tarea.
- Actualizar `README.md`, `ARCHITECTURE.md` o `.env.example` cuando cambie comportamiento operativo, configuración o estructura.
- Mantener ASCII por defecto en código, nombres de archivos y configuración.
