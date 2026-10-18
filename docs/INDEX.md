# docs/ — Fuente de verdad del proyecto

Esta carpeta es la **única fuente de verdad** para requisitos, arquitectura, decisiones, roadmap y estilo de código. El `README.md` en la raíz solo cubre instalación y uso rápido; todo lo demás vive acá.

## Jerarquía de documentos

Orden de lectura y autoridad. Si dos documentos se contradicen, gana el de mayor rango y se corrige el menor.

| Documento | Rol |
|---|---|
| `SPECS.md` | **Requisitos**: qué debe hacer el sistema, qué no debe hacer, criterios de aceptación. No define implementación. |
| `DECISIONS.md` | **Decisiones adjudicadas**: cada decisión tomada con contexto, opciones, justificación y consecuencias. Es el registro de "por qué es así". |
| `ARCHITECTURE.md` | **Arquitectura técnica**: módulos, fronteras, interfaces, estados y flujo. Deriva de SPECS + DECISIONS. |
| `ROADMAP.md` | **Plan de trabajo**: milestones, orden y criterios de salida. Se actualiza solo con trabajo real completado o reordenado. |
| `CODESTYLE.md` | **Convenciones de código**: nombres, comentarios, tests. |
| `CAMBIOS.md` | **Bitácora de cambios recientes** (histórico, no especifica nada). |

## Reglas de la fuente de verdad

1. Toda modificación de requisitos, estados, fronteras o decisiones se documenta **antes o junto con** el código que la implementa.
2. No se edita `SPECS.md` para hacer que algo incumplido parezca válido.
3. `ROADMAP.md` solo refleja trabajo real; no se tachan tareas pendientes.
4. `DECISIONS.md` es append-only: las decisiones no se reescriben, se supersedea con una nueva entrada que referencia a la anterior.
5. `README.md` (raíz) y `AGENTS.md` (raíz) complementan: README = operación/uso; AGENTS = reglas operativas para agentes de código que trabajen en este repo, y apunta a `docs/`.

## Estado actual del proyecto

- Backend core (dominio, SQLite, workflow, scheduler por intervalo, API) implementado y con suite en verde (93/94).
- **Pivote** (ver `DECISIONS.md` D-2026-10-18): CLI por consola como interfaz principal, FastAPI/dashboard opcional, scheduler por día+hora (default jueves 14:05), login remoto desde la PC del usuario con sesión almacenada en el servidor, y `LOCALE` para la región del store.
- Pendiente crítico: pipeline de autenticación interactiva remota (historial en `CAMBIOS.md`) y validación live contra Epic real.
