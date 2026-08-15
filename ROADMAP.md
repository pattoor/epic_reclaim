# Roadmap de Implementacion

Ruta de trabajo para construir el MVP de **Epic Games Free Games Auto-Claimer**, derivada de `SPEC.md`. El orden prioriza correccion, seguridad, mantenibilidad y simplicidad.

## Fase 0: Arquitectura y decisiones

- Confirmar el alcance del MVP y mantener Epic Games Store como unica plataforma.
- Definir la estructura modular del backend, frontend, integraciones y adaptadores especificos de Epic.
- Elegir dependencias minimas compatibles con FastAPI, SQLite, Playwright, scheduler y testing.
- Documentar el modelo de estados para cuentas, claims, ejecuciones, errores e intervenciones.
- Diseñar el esquema SQLite, indices y restricciones de unicidad para `account + game`.
- Definir el contrato REST y el formato de eventos/progreso de ejecuciones.
- Diseñar la estrategia de perfiles persistentes de Playwright, sin almacenar contrasenas.
- Definir limites de recursos, bloqueo de ejecuciones concurrentes y politica de reintentos.
- Registrar cualquier requisito que no pueda satisfacerse exactamente antes de implementar.

## Fase 1: Base del proyecto y configuracion

- Crear la estructura del repositorio para backend, frontend, tests y despliegue.
- Configurar FastAPI, SQLite, migraciones/inicializacion de base de datos y logging estructurado.
- Crear el sistema de configuracion por variables de entorno.
- Incluir `.env.example`, `.gitignore` y `requirements.txt` sin secretos reales.
- Definir rutas configurables para base de datos, perfiles de navegador y otros datos persistentes.
- Implementar `GET /health` con comprobaciones de aplicacion, SQLite y Playwright sin contactar Epic.
- Agregar una base de tests unitarios y de integracion.

## Fase 2: Persistencia y dominio

- Implementar entidades `Account`, `Game`, `Claim`, `Run` y `Settings`.
- Persistir estados de cuenta: `active`, `disabled`, `needs_authentication`, `needs_intervention` y `paused`.
- Persistir resultados de claim: `claimed`, `already_owned`, `failed` y `skipped`.
- Guardar intentos, errores, retryability, intervenciones y timestamps necesarios para diagnostico.
- Aplicar constraints e idempotencia para evitar registros logicos duplicados por cuenta y juego.
- Implementar repositorios/servicios de consulta de historial y filtros.
- Verificar persistencia tras reinicios y retencion indefinida del historial por defecto.

## Fase 3: Descubrimiento y adaptador de Epic

- Implementar el adaptador de Epic usando exclusivamente la seccion oficial de juegos gratis.
- Detectar cualquier cantidad de juegos elegibles en el momento de la ejecucion.
- Ignorar juegos "coming soon", descuentos, demos y contenido fuera de la seccion objetivo.
- Persistir identificador Epic, nombre, URL y metadatos tecnicos estrictamente necesarios.
- Separar el comportamiento especifico de Epic del workflow generico de claims.
- Crear mocks/fixtures para probar descubrimiento sin depender continuamente del sitio real.

## Fase 4: Sesiones y autenticacion interactiva

- Crear un perfil persistente de Playwright por cuenta.
- Implementar alta, autenticacion y reautenticacion iniciadas desde el dashboard.
- Ejecutar el navegador en el servidor y exponer de forma segura el flujo interactivo remoto.
- Detectar autenticacion exitosa y guardar la sesion en el volumen persistente.
- Detectar CAPTCHA, MFA, expiracion de sesion y otros bloqueos sin intentar resolverlos automaticamente.
- Transicionar la cuenta al estado correcto y evitar reintentos agresivos.
- Cerrar el navegador interactivo cuando termine la autenticacion y liberar recursos cuando sea posible.

## Fase 5: Workflow de claims

- Implementar un unico workflow compartido por scheduler, dashboard y API externa.
- Adquirir un lock para impedir ejecuciones concurrentes.
- Descubrir y persistir juegos antes de procesar cuentas.
- Procesar cuentas habilitadas en el orden configurado y juegos secuencialmente.
- Comprobar propiedad antes de reclamar y registrar `already_owned` cuando corresponda.
- Confirmar que Epic agrego el juego a la biblioteca antes de registrar `claimed`.
- Continuar con otros juegos cuando un fallo lo permita y continuar con otras cuentas de forma segura.
- Implementar hasta 3 intentos con backoff para timeouts, red y fallos transitorios.
- No reintentar automaticamente CAPTCHA, MFA, rate limits, bloqueos ni problemas de autenticacion.
- Aplicar delays configurables y conservadores de 2 a 5 segundos entre acciones relevantes.
- Persistir el progreso de cada ejecucion y permitir recuperacion segura posterior.

## Fase 6: API y scheduler

- Implementar CRUD de cuentas y operaciones de autenticacion, reautenticacion, activacion y eliminacion.
- Implementar endpoints de juegos, claims, ejecuciones y configuracion.
- Implementar `POST /api/runs` como trigger externo del mismo workflow.
- Devolver claramente que una ejecucion ya esta en curso cuando se solicite otra.
- Implementar scheduler interno habilitable/deshabilitable y configurable por intervalo.
- Soportar intervalos diarios, semanales y promocionales sin asumir solo los jueves.
- Hacer que el scheduler respete el lock y sobreviva a errores sin bucles infinitos.
- Agregar opcionalmente API key para triggers expuestos fuera de una red confiable.

## Fase 7: Dashboard

- Construir una interfaz simple y responsive consumiendo exclusivamente la API.
- Crear la vista general con salud, scheduler, proxima/ultima ejecucion, resumen y alertas.
- Crear la gestion de cuentas con orden, estados, autenticacion, intervencion y acciones destructivas confirmadas.
- Crear una vista dedicada de ejecucion con progreso por cuenta y juego.
- Crear historial global con filtros por cuenta, fecha y estado.
- Agregar exportacion CSV/JSON por cuenta y filtros de fecha cuando sea aplicable.
- Crear configuracion para scheduler, delays, Telegram y opciones no secretas.
- Mostrar logs recientes y diagnostico sin exponer cookies, tokens, contrasenas o sesiones.
- Permitir iniciar y resolver autenticaciones/intervenciones desde el dashboard.

## Fase 8: Integraciones opcionales

- Implementar notificaciones Telegram solo cuando esten configuradas.
- Enviar resumen de ejecucion y alertas de CAPTCHA, MFA, cuenta pausada y fallos importantes.
- Evitar spam y marcar como resueltas las acciones de intervencion antiguas.
- Documentar un workflow n8n basado en `Schedule Trigger -> POST /api/runs`.
- Verificar que la ausencia de n8n o Telegram no degrade dashboard, scheduler ni historial.

## Fase 9: Backup, restore y despliegue

- Implementar exportacion/backup de SQLite y configuracion no secreta.
- Excluir perfiles de navegador, cookies y sesiones de los backups normales.
- Implementar importacion con validacion, confirmacion explicita y proteccion contra sobrescritura silenciosa.
- Crear `Dockerfile`, `docker-compose.yml` y volumenes para base de datos, sesiones y estado.
- Mantener la aplicacion completa en un unico contenedor con modulos internos separados.
- Documentar ejecucion Docker y no Docker, Playwright/Chromium, frontend, puertos y troubleshooting.
- Documentar acceso por LAN/Tailscale, cambio del puerto por defecto `8765`, actualizaciones y reinicios.
- Verificar que reiniciar o recrear el contenedor no pierda datos ni sesiones persistentes.

## Fase 10: Pruebas, seguridad y entrega

- Cubrir descubrimiento, claims secuenciales, idempotencia y workflow manual/scheduled compartido.
- Cubrir reintentos, limite de intentos, CAPTCHA/MFA, rate limit, bloqueo y recuperacion.
- Cubrir continuidad cuando falla una cuenta o un juego, lock de ejecuciones y persistencia.
- Cubrir CRUD, settings, health check y trigger externo.
- Mantener tests unitarios, integracion y E2E controlados separados de pruebas live/manuales.
- Ejecutar lint, type checks, tests y build del frontend antes de cada entrega.
- Revisar que logs, exports, backups y respuestas API no filtren secretos o sesiones.
- Validar el flujo completo desde clonacion hasta claim, backup y restauracion.
- Revisar la Definition of Done de `SPEC.md` y cerrar solo requisitos demostrablemente cumplidos.

## Criterio de finalizacion

- El usuario puede desplegar el proyecto con Docker o sin Docker siguiendo el README.
- Puede autenticar varias cuentas mediante el navegador remoto persistente.
- El sistema detecta y reclama juegos gratis elegibles secuencialmente, sin duplicar claims.
- Las ejecuciones, resultados, errores e intervenciones son visibles y recuperables desde el dashboard.
- Scheduler, `Run now`, API externa, exportaciones, backup/restore y pruebas funcionan sin requerir n8n ni Telegram.
