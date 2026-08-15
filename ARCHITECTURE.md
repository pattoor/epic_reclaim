# Architecture

## Scope

The MVP is a single FastAPI process that serves the dashboard and API, owns the SQLite database, runs the internal scheduler, and executes one claim workflow at a time. Epic-specific browser behavior is isolated behind an adapter so generic persistence and orchestration do not depend on page selectors.

## Modules

```text
app/
  main.py             FastAPI application and lifecycle
  config.py           Environment configuration
  database.py         SQLite connection and schema initialization
  models.py           Domain dataclasses and state constants
  repositories.py     Persistence operations
  epic.py             Epic discovery and claim adapter
  workflow.py         Shared sequential run workflow
  scheduler.py        Internal interval scheduler
  api.py              REST endpoints
  static/             Dashboard assets
tests/
```

The API, manual trigger, and scheduler call the same `RunWorkflow` service. `EpicAdapter` is injected into that service and can be replaced by a test double without contacting the live store.

## Persistence

SQLite is initialized on startup. The schema contains `accounts`, `games`, `claims`, `runs`, and `settings`. A unique constraint on `(account_id, game_id)` provides the logical claim idempotency boundary. Claim attempts and latest outcomes are retained in the claim record; runs retain trigger, timestamps, status, counters, and errors.

Browser profiles are stored under `SESSIONS_PATH`, one directory per account. They are never returned by API responses or included in application backups.

## Browser and authentication

Playwright is loaded as an optional runtime capability so health and database operations remain usable when Chromium has not been installed. The Epic adapter uses a persistent context per account and raises typed intervention errors for authentication, CAPTCHA, MFA, rate limiting, and blocking conditions. The MVP does not solve or bypass those conditions.

## Workflow safety

- A process-local async lock prevents concurrent runs.
- Accounts are ordered by `processing_order` and games are processed sequentially.
- Transient failures are retried at most three times with bounded backoff.
- Intervention and blocking failures stop the affected account without hammering Epic.
- Configurable delays default to 2-5 seconds and are applied only by the adapter workflow.

## Deployment

The Docker image contains the API, static dashboard, Python dependencies, and Playwright Chromium. Docker volumes mount `/app/data/database`, `/app/data/sessions`, and `/app/data/state`. No public exposure or dashboard authentication is assumed for this trusted home-server MVP.

## Deliberate boundaries

The first version supports only Epic Games Store. No speculative multi-platform abstraction, user authentication, mobile client, or analytics subsystem is included.
