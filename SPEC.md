# SPEC.md — Epic Games Free Games Auto-Claimer

## 1. Purpose

Build a self-hosted MVP that automatically detects and claims currently available free games from the official Epic Games Store "Free Games" section for one or more configured Epic accounts.

The system is intended primarily as a personal/home-server automation. It must minimize unnecessary interaction with Epic and must not attempt to bypass CAPTCHA, MFA, rate limits, anti-bot protections, or other security controls.

The project must remain useful without n8n or Telegram. Both are optional integrations.

This specification defines requirements, constraints, expected behavior, and acceptance criteria. It intentionally does **not** prescribe the final code structure, detailed architecture, library choices, or implementation roadmap. A later architecture/design phase should derive those from this specification.

---

## 2. Goals

The MVP must:

1. Detect currently available free games from Epic's official "Free Games" section.
2. Support a configurable number of Epic accounts.
3. Claim all currently available eligible games for each active account.
4. Process accounts and games sequentially.
5. Persist accounts, games, claims, executions, settings, and relevant errors.
6. Avoid duplicate claims through idempotent behavior.
7. Persist browser sessions so accounts do not need to log in on every execution.
8. Support interactive authentication/re-authentication when required.
9. Detect situations requiring human intervention, such as CAPTCHA or MFA.
10. Allow intervention through the dashboard and optionally through Telegram.
11. Provide a web dashboard for management and monitoring.
12. Provide a manual "Run now" operation.
13. Provide an internal configurable scheduler.
14. Allow external triggers through an API endpoint.
15. Work without n8n.
16. Support optional n8n integration.
17. Support optional Telegram notifications.
18. Run as a single Docker container while remaining modular internally.
19. Support persistent data through Docker volumes.
20. Provide documentation for Docker and non-Docker execution.
21. Provide tests for the normal flow and important failure/recovery paths.
22. Provide backup/export and import functionality without exposing browser sessions through normal dashboard backups.

---

## 3. Non-Goals

The MVP must NOT:

- Support other stores such as Steam, GOG, Ubisoft, etc.
- Purchase paid games.
- Claim discounted games that are not actually free.
- Claim demos or free-to-play titles unless they are presented as eligible games in Epic's official "Free Games" section.
- Claim games listed only as "coming soon".
- Automate CAPTCHA solving.
- Bypass CAPTCHA.
- Bypass MFA.
- Bypass Epic anti-bot or rate-limit mechanisms.
- Attempt to evade bans or security controls.
- Use aggressive parallel requests.
- Require n8n.
- Require Telegram.
- Require multiple users.
- Require dashboard authentication for the MVP.
- Expose the dashboard publicly by default.
- Build a mobile application.
- Add recommendation or analytics features unrelated to claiming games.
- Depend on a fixed number of free games per week.
- Assume that free games only change on Thursdays.
- Store Epic passwords as application data.
- Export browser sessions/cookies through ordinary dashboard backups.

---

## 4. Target Environment

Primary target:

- Self-hosted home server.
- Linux/Debian compatible.
- Docker available.
- Approximately 4 GB RAM in the reference environment.
- Other Docker services may already be running.
- Access primarily through LAN/Wi-Fi and/or Tailscale.
- No public port forwarding required.

Default application port:

- `8765`

The port must be configurable through environment configuration.

Documentation must explain how to change the port when it conflicts with another service.

The project must not assume that port 8765 is universally free.

---

## 5. Deployment Requirements

### 5.1 Docker

The complete application must be deployable as one Docker container.

The container must contain the required application components while keeping their responsibilities modular in code.

Persistent data must live outside the ephemeral container filesystem through mounted volumes.

At minimum, persistent data must include:

- SQLite database.
- Browser session/profile data.
- Other required application state.

### 5.2 Non-Docker execution

The project must also document how to run without Docker.

Documentation must cover:

- Python environment.
- `requirements.txt`.
- Frontend dependencies/build.
- Playwright/Chromium dependencies.
- Environment configuration.
- Database location.
- Session storage.
- Running the application.
- Running the internal scheduler.
- Optional external triggering.
- Troubleshooting.

### 5.3 Configuration

The repository must contain:

- `.env.example`
- `.gitignore`
- `requirements.txt`
- `README.md`

Secrets must never be committed.

---

## 6. Accounts

The system must support an arbitrary practical number of accounts without requiring source-code changes.

For each account:

- The account must have an internal application ID.
- The default display name should be derived from the Epic account identity discovered during authentication.
- The user may optionally change the display name.
- The account can be enabled/disabled.
- The account has a configurable processing order.
- The account has a persistent browser session.
- The system must not store the Epic password as a normal application field.

The dashboard must allow:

- Add account.
- Authenticate account.
- Re-authenticate account.
- Change display name.
- Enable/disable account.
- Change processing order.
- Deactivate account.
- Permanently delete account through an explicit destructive action.

Normal deactivation must preserve account history.

Permanent deletion must require an additional explicit confirmation.

---

## 7. Account States

The system must support at least these conceptual states:

- `active`
- `disabled`
- `needs_authentication`
- `needs_intervention`
- `paused`

Meaning:

### active
The account may participate in automatic and manual runs.

### disabled
The user intentionally disabled the account.

### needs_authentication
The persistent session is no longer authenticated or valid.

### needs_intervention
A human action is required, such as CAPTCHA or MFA.

### paused
The account should not be automatically retried immediately due to a blocking/rate-limit/unexpected condition.

The exact internal representation may differ if the behavior remains equivalent.

---

## 8. Epic Game Discovery

The system must use the official Epic Games Store "Free Games" section as the source of eligible games.

Eligibility is based on what is currently presented as available in that section at execution time.

The system must:

- Detect any number of currently free eligible games.
- Not assume there is exactly one or two games.
- Not assume a weekly-only schedule.
- Support periods where free games change daily.
- Ignore games marked as coming soon/not currently available.
- Avoid unrelated discounted/free-to-play content outside the intended "Free Games" section.

For each detected game, the minimum persisted information is:

- Internal game record ID.
- Epic game identifier when available.
- Name.
- URL.
- Claim date/time when claimed.

The design may retain additional technical metadata if needed for reliable operation, but it should not introduce unnecessary persisted data solely for analytics.

---

## 9. Claim Behavior

For every execution:

1. Discover currently eligible free games.
2. Process enabled accounts according to their configured order.
3. Process games sequentially.
4. Determine whether the game is already owned.
5. If already owned, record `already_owned`.
6. If not owned, attempt to claim it.
7. If Epic confirms the game was added to the library, record `claimed`.
8. If a recoverable temporary failure occurs, retry according to the retry policy.
9. If a non-recoverable intervention/blocking condition occurs, stop processing that account and continue with other accounts when safe.
10. Continue processing remaining games when one game fails, provided doing so is safe.
11. Persist all relevant outcomes.

No parallel claiming is required.

---

## 10. Idempotency

The claiming operation must be idempotent.

The system must prevent duplicate logical claim records for the same:

`account + game`

A later execution must still check Epic for newly available games.

The existence of a previous run must NOT cause the entire future run to be skipped.

Example:

- Run 1 detects Game A and claims it.
- Run 2 detects A and B.
- A is skipped/already known.
- B is claimed.

Manual execution and scheduled execution must use the same underlying claim workflow.

---

## 11. Claim States

The system must distinguish at least:

- `claimed`
- `already_owned`
- `failed`
- `skipped`

A claim should also retain enough information to determine whether a failure is retryable and/or requires intervention.

Failed claims that are retryable should be eligible for retry during a later execution.

The exact additional state model may be refined during architecture design.

---

## 12. Retry Policy

Temporary/recoverable errors may be retried automatically.

Default policy:

- Maximum 3 attempts.
- Backoff between attempts.
- Do not retry indefinitely.

Examples of potentially retryable conditions:

- Timeout.
- Temporary page-load failure.
- Temporary network error.
- Recoverable transient HTTP/application failure.

The system must NOT blindly retry:

- CAPTCHA.
- MFA requirement.
- Expired/invalid authentication requiring user action.
- Explicit rate limiting.
- Explicit account blocking.
- Security/anti-bot challenges.

Those conditions must transition the account into an appropriate intervention/paused state.

Retry behavior must be documented.

---

## 13. Unexpected Errors and Recovery

Unexpected conditions must be handled conservatively.

When the system encounters an unknown or potentially dangerous condition:

1. Record the error with useful diagnostic context.
2. Avoid repeatedly hammering Epic.
3. Stop or pause the affected account when appropriate.
4. Continue other accounts only if doing so is safe.
5. Allow the next scheduler trigger to retry states that are safely retryable.
6. Allow manual retry from the dashboard where appropriate.
7. Do not create infinite retry loops.

The system must favor safe recovery over maximizing automation.

---

## 14. Browser Sessions

Browser automation should use Playwright with a persistent browser profile/session per account.

The objective is to avoid repeated manual logins.

Session data must persist across:

- Application restarts.
- Container restarts.
- Normal deployments where the persistent volume is retained.

Browser session data must be stored outside the ephemeral container layer.

The system must not expose session/cookie contents in normal dashboard views or ordinary backups.

---

## 15. Interactive Authentication

Adding or re-authenticating an account requires an interactive browser flow.

Expected behavior:

1. User starts authentication from the dashboard.
2. The server starts the browser session.
3. The user accesses the interactive browser remotely.
4. The user performs the normal Epic login.
5. If MFA is requested, the user completes it manually.
6. If CAPTCHA is requested, the user completes it manually.
7. The application detects successful authentication.
8. The persistent session is saved.
9. The interactive browser is closed when authentication is complete.

The browser must run on the server, not on the user's local PC.

The dashboard must provide a way to initiate and complete this process.

---

## 16. Human Intervention

When CAPTCHA, MFA, authentication expiry, or another supported intervention is detected:

- The affected account enters `needs_intervention` or `needs_authentication`.
- The account must not be repeatedly hammered with retries.
- The dashboard must clearly show the required action.
- The user must be able to resolve the issue through the dashboard.

Optional Telegram integration may provide a shortcut to the relevant dashboard action.

After successful resolution:

- The account returns to `active`.
- The dashboard reflects the successful recovery.
- Any stale Telegram "resolve" action must no longer be treated as pending.
- If a run was safely paused waiting for intervention, the system may resume that account's pending work automatically.

The implementation must favor the simplest safe mechanism for resuming.

---

## 17. Delays and Request Behavior

Claims must be sequential.

Between relevant browser/claim actions, the system should use a moderate randomized delay.

Default:

- Minimum: 2 seconds.
- Maximum: 5 seconds.

These values must be configurable.

The system must avoid unnecessary requests and unnecessary page reloads.

The system must not attempt to emulate or bypass anti-bot behavior. Randomized delays are solely a conservative pacing mechanism.

The architecture should allow delays to be changed through configuration/dashboard without changing source code.

---

## 18. Runs

Each execution must have a persistent run record.

A run represents one complete attempt initiated by:

- Internal scheduler.
- Manual dashboard action.
- External API trigger.

The system must prevent concurrent runs.

If a run is already in progress and another trigger occurs:

- The second trigger must not start another claim workflow.
- It should return/show that an execution is already in progress.

A run should record enough information to understand:

- Start time.
- End time.
- Trigger source.
- Status.
- Games detected.
- Accounts processed.
- Claims/outcomes.
- Errors/interventions.

---

## 19. Manual Run

The dashboard must provide:

`Run now`

This must execute the same workflow used by automatic scheduling.

It must not duplicate business logic.

The UI should provide access to the live/progress state of the execution in a separate execution view/panel rather than cluttering the main dashboard.

---

## 20. Execution Monitoring

A dedicated execution view should display progress such as:

- Detecting games.
- Games found.
- Current account.
- Current game.
- Claim result.
- Retry.
- Intervention required.
- Final status.

Example conceptual flow:

```text
RUN #142

Detecting games...       ✓
Found 2 games            ✓

Personal
 ├─ Game A               ✓ claimed
 └─ Game B               ✓ claimed

Friend 1
 ├─ Game A               ✓ already owned
 └─ Game B               ✓ claimed

Friend 2
 └─ CAPTCHA              ⚠ intervention required
```

The exact frontend implementation is open.

---

## 21. Scheduler

The application must have an internal scheduler.

The scheduler must be:

- Enabled/disabled.
- Configurable by interval.
- Independent from n8n.
- Independent from Telegram.

Example:

- Enabled: `true`
- Interval: `6 hours`

The system must not hard-code Thursday as the only execution day.

The scheduler must support daily, weekly, and special promotional periods through configurable intervals.

The scheduler must not start duplicate runs if another run is active.

---

## 22. External Triggers

The application must expose an API operation to start a run.

Conceptually:

`POST /api/runs`

This endpoint exists so external tools can trigger the same execution workflow.

Potential callers include:

- n8n.
- Debian cron.
- Another local automation.
- Another external scheduler.

n8n is optional.

An optional API-key mechanism may be implemented/configured for deployments where external triggering crosses a less-trusted boundary.

It must not be mandatory for the default personal/home-server deployment.

---

## 23. n8n Integration

n8n must be treated as an optional external orchestrator.

The system must not depend on n8n.

Documentation should include an example workflow concept:

```text
Schedule Trigger
      ↓
POST /api/runs
```

The application remains fully functional when n8n is absent.

---

## 24. Notifications

Telegram is optional.

Without Telegram:

- Dashboard remains fully functional.
- Errors/interventions remain visible in the dashboard.
- Runs remain persisted.

With Telegram configured, notifications should include:

### Successful summary

Example:

```text
Epic Claim finished
3 accounts
2 games detected
5 successful claims
1 already owned
0 failures
```

### Important alerts

Examples:

- CAPTCHA required.
- MFA/authentication required.
- Account paused.
- Significant unexpected failure.

Telegram should avoid unnecessary spam.

When an intervention is resolved, Telegram should notify the user that it was resolved and no longer present an active resolution action.

---

## 25. Dashboard

The dashboard is the primary management interface.

It should contain four main conceptual areas:

### Dashboard

Show:

- Overall system health.
- Scheduler state.
- Next run.
- Last run.
- Last result summary.
- Accounts requiring intervention.
- Recent claims.
- `Run now` action.

### Accounts

Allow:

- Add.
- Authenticate.
- Re-authenticate.
- Change display name.
- Enable/disable.
- Change processing order.
- Deactivate.
- Permanently delete with explicit confirmation.
- Resolve intervention.

### History

Allow:

- View global claim history.
- Filter by account.
- Filter by date.
- Filter by status where useful.
- Export history by account.
- Export CSV/JSON.

### Settings

Allow:

- Scheduler enabled/disabled.
- Scheduler interval.
- Claim delay minimum.
- Claim delay maximum.
- Telegram enabled/disabled.
- Other non-secret behavioral configuration.

The UI should remain intentionally simple and focused on the purpose of the application.

---

## 26. Health Check

The application must provide:

`GET /health`

It should be able to report at least:

- API/application status.
- Database status.
- Browser/Playwright availability.

The implementation may include additional lightweight checks if useful, but health checking must not cause a real Epic claim or unnecessary external traffic.

---

## 27. API

The application must expose a REST API that serves both the dashboard and external integrations.

At minimum, conceptually support:

```text
GET    /api/accounts
POST   /api/accounts
PATCH  /api/accounts/{id}
DELETE /api/accounts/{id}

POST   /api/accounts/{id}/authenticate
POST   /api/accounts/{id}/resolve-intervention

GET    /api/games
GET    /api/claims

GET    /api/runs
POST   /api/runs

GET    /api/settings
PATCH  /api/settings

GET    /health
```

The final API contract may be refined during architecture design.

The frontend must consume the API rather than duplicate backend business logic.

---

## 28. Data Persistence

SQLite is the required database for the MVP.

Conceptual entities:

- Account
- Game
- Claim
- Run
- Settings

Conceptual relationship:

```text
Account 1 ─── N Claim N ─── 1 Game
Run     1 ─── N Claim
```

The exact schema should be designed during the architecture phase.

The schema must support:

- Multiple accounts.
- Repeated appearances of the same game.
- Historical claims.
- Run history.
- Retry/error information.
- Account state.
- Configurable account ordering.

History must be retained indefinitely by default.

---

## 29. History Export

The user must be able to export history by account.

Supported formats:

- CSV.
- JSON.

Exports should support useful filtering, including date range where practical.

The export must not include secrets or browser session data.

---

## 30. Backup and Restore

The application should support backup/export and import for migration or reinstallation.

A normal application backup should contain:

- SQLite database.
- Non-secret application configuration necessary for restoration.

It must NOT include browser sessions/cookies by default.

Import must:

1. Validate the backup.
2. Require explicit confirmation.
3. Restore compatible application data safely.
4. Avoid silently overwriting current data without confirmation.

Documentation must explain that browser sessions may need to be re-authenticated after migration/reinstallation.

---

## 31. Security

The application is primarily designed for a trusted home-server environment.

Default assumptions:

- Dashboard is accessed over LAN and/or Tailscale.
- No public Internet exposure is required.
- No public port forwarding is required.
- Dashboard authentication is not required for the MVP.

Nevertheless:

- Secrets must be configurable through environment variables.
- `.env` must be ignored by Git.
- Browser session data must remain in persistent private storage.
- Session data must not be displayed in the UI.
- Session data must not be included in ordinary exports/backups.
- Optional API-key protection should be available for externally exposed trigger endpoints.
- The application must not attempt to circumvent Epic security mechanisms.

---

## 32. Platform Boundary

Version 1 implements only Epic Games Store.

However, platform-specific behavior must be conceptually isolated from generic application functionality.

The architecture should make it possible to add another platform in the future without requiring a rewrite of:

- Accounts management.
- Runs.
- Claims/history.
- Notifications.
- Scheduler.
- Dashboard foundations.

The specification does NOT require implementation of another platform.

The architecture must not assume that another platform behaves identically to Epic.

Platform-specific data may be stored separately or through an extensible mechanism where necessary.

Do not over-generalize the MVP with speculative abstractions.

---

## 33. Testing Requirements

Tests must focus on behavior that affects the normal flow and important recovery paths.

Required coverage should include:

### Core flow

- Free game discovery result handling.
- Sequential account processing.
- Sequential game processing.
- Successful claim.
- Already-owned game.
- Idempotent repeated execution.
- Manual and scheduled runs using the same workflow.

### Failure/recovery

- Retryable failure.
- Retry limit.
- CAPTCHA/intervention state.
- Authentication-required state.
- Rate-limit/blocking state.
- One account failing while another continues.
- One game failing while later games continue when safe.
- Run concurrency lock.
- Recovery after intervention.

### Persistence/API

- Account CRUD behavior.
- Claim persistence.
- Run persistence.
- Settings persistence.
- Health endpoint.
- External run trigger.

### Integration/E2E

At least one controlled end-to-end flow should exist where practical.

Tests must NOT depend continuously on the live Epic Store.

Epic/browser behavior should be mocked or isolated for most automated tests.

Documentation must identify which tests are:

- Unit.
- Integration.
- E2E.
- External/live/manual tests.

This allows future debugging to target the appropriate test layer.

---

## 34. Logging

The application must provide useful structured/application logs.

Logs should allow troubleshooting of:

- Run start/end.
- Game discovery.
- Account processing.
- Claim outcomes.
- Retries.
- Intervention states.
- Authentication issues.
- Unexpected errors.
- Scheduler actions.

The dashboard should provide a simple log/debug view or an equivalent recent-log presentation.

Logs must not expose passwords, session cookies, tokens, or other secrets.

---

## 35. Documentation Requirements

The repository must document at least:

### README

- Project purpose.
- Features.
- Architecture overview.
- Requirements.
- Quick start.
- Docker setup.
- Non-Docker setup.
- Configuration.
- Dashboard access.
- Initial account authentication.
- Scheduler.
- Optional n8n integration.
- Optional Telegram integration.
- Backup/restore.
- Troubleshooting.
- Testing.

### Configuration documentation

Explain:

- `.env`.
- `.env.example`.
- Application port.
- Database path.
- Session path.
- Telegram configuration.
- Optional external API-key.
- Other runtime configuration.

### Deployment documentation

Explain:

- Docker Compose.
- Volumes.
- Updating.
- Restarting.
- Backups.
- LAN access.
- Tailscale access.
- Port conflicts.

### Troubleshooting

Include common cases:

- Port already in use.
- Chromium/Playwright failure.
- Authentication expired.
- CAPTCHA/MFA.
- Telegram not configured.
- Database problems.
- Session lost.
- Container restart.
- Backup restore.

---

## 36. Environment Example

The repository must include a `.env.example`.

It should demonstrate configuration without containing real secrets.

Conceptually it may contain variables such as:

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

The final environment variable names may be refined during implementation.

---

## 37. Dependencies

The backend must provide a `requirements.txt`.

The project should avoid unnecessary dependencies.

The architecture/design phase should prefer the smallest reasonable dependency set compatible with:

- FastAPI.
- SQLite.
- Playwright.
- Scheduler.
- Testing.
- Required backend functionality.

Frontend dependencies must be defined through the frontend package manager.

---

## 38. Resource Constraints

The reference server has approximately 4 GB RAM and runs other containers.

The application should be conservative with resources.

Requirements:

- Avoid unnecessary background processes.
- Do not keep Chromium running permanently unless technically justified.
- Prefer a single browser instance when practical.
- Process accounts sequentially.
- Avoid parallel claims.
- Avoid unnecessary page loads.
- Release browser resources after operations when possible.
- Keep database lightweight.

The final architecture should consider these constraints explicitly.

---

## 39. Operational Behavior Summary

A normal scheduled execution should conceptually behave as:

```text
Trigger
  ↓
Acquire run lock
  ↓
Discover currently free eligible games
  ↓
Persist/update game records
  ↓
Process enabled accounts in configured order
  ↓
For each game:
    determine ownership
    ├── already owned → record
    └── not owned
          ↓
        claim
          ├── success → record claimed
          ├── retryable failure → retry
          └── intervention/block → pause account
  ↓
Finish safe accounts
  ↓
Persist run
  ↓
Release lock
  ↓
Send optional Telegram summary
```

---

## 40. Definition of Done

The MVP is considered complete when a user can:

1. Clone the repository.
2. Configure `.env`.
3. Run the application with Docker or documented non-Docker instructions.
4. Open the dashboard through the server's LAN/Tailscale address.
5. Add an Epic account.
6. Authenticate once through the remote interactive browser.
7. Configure one or more accounts.
8. Configure the scheduler.
9. Leave the application running unattended.
10. Have the system detect currently available Epic free games.
11. Have the system claim them sequentially.
12. Have repeated executions avoid duplicate logical claims.
13. See successful and already-owned claims in history.
14. See failures and interventions.
15. Recover an account requiring CAPTCHA/MFA through the dashboard.
16. Optionally receive Telegram summaries and intervention alerts.
17. Trigger a run manually.
18. Trigger a run externally through the API.
19. Export account history.
20. Backup/import application data without exposing browser sessions by default.
21. Restart the container without losing database/session state.
22. Diagnose common failures through logs and documentation.
23. Run the relevant automated test suite successfully.

---

## 41. Design/Architecture Phase Instructions

This specification is intentionally implementation-agnostic.

The next phase should produce:

1. Architecture proposal.
2. Technology/dependency decisions with justification.
3. Repository/module structure.
4. Database schema.
5. API contract.
6. Browser/session strategy.
7. Dashboard information architecture.
8. Scheduler design.
9. Error/state machine design.
10. Docker/deployment design.
11. Testing strategy.
12. Security considerations.
13. Development roadmap broken into small implementation phases.

The architecture must respect this specification and explicitly identify any requirement it cannot satisfy as written.

Do not add features merely because they are technically interesting.

Prioritize:

**correctness → safety → maintainability → simplicity → performance.**

The implementation should remain an MVP rather than becoming an over-engineered multi-platform automation framework.
