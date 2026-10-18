"""Console CLI (project's primary management interface).

Stdlib-only menus for accounts, authentication, runs, history and settings.
It calls exactly the same services as the web mode (docs/DECISIONS.md D2).
"""

from __future__ import annotations

import sys
import time

if sys.platform == "win32":  # avoid mojibake accents in Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover - exotic stdout
        pass

from .bootstrap import Runtime, build_runtime, database_ok, playwright_status
from .config import Settings
from .domain import scheduling
from .domain.models import AccountState, ClaimState, RunTrigger

AUTH_TIMEOUT_MINUTES = 15
CLAIM_STATUSES = [ClaimState.CLAIMED, ClaimState.ALREADY_OWNED, ClaimState.FAILED, ClaimState.SKIPPED]

MENU = """
================ Epic Reclaim ================
 1) Estado del sistema
 2) Cuentas
 3) Run now (reclamar ahora)
 4) Historial de runs
 5) Historial de claims
 6) Settings
 0) Salir
"""


def main() -> int:  # pragma: no cover - interactive entry used by module
    runtime = build_runtime(Settings.from_env(), with_scheduler=False)
    runtime.database.initialize()
    print("Nota: la CLI no ejecuta el scheduler. En producción vive en el modo web del contenedor.")
    while True:
        print(MENU)
        choice = _input("Opción> ")
        try:
            if choice == "1":
                _status(runtime)
            elif choice == "2":
                _accounts_menu(runtime)
            elif choice == "3":
                _run_now(runtime)
            elif choice == "4":
                _runs_history(runtime)
            elif choice == "5":
                _claims_history(runtime)
            elif choice == "6":
                _settings_menu(runtime)
            elif choice in {"0", "q", "Q", "salir", "exit"}:
                return 0
            else:
                print("Opción inválida.")
        except KeyboardInterrupt:
            print("\n(interrumpido; el flujo en curso sigue en segundo plano)")
        except Exception as exc:  # keep the menu alive on runtime errors
            print(f"Error: {exc}")


def _input(prompt: str) -> str:  # pragma: no cover - interactive
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


# ------------------------------------------------------------------ status


def _status(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
        runs = runtime.runs_repository.list(connection, limit=1)
        settings = runtime.settings_service.load(connection)
    attention = [a for a in accounts if a.state == AccountState.NEEDS_INTERVENTION]
    need_auth = [a for a in accounts if a.state == AccountState.NEEDS_AUTHENTICATION]
    last = runs[0] if runs else None
    print("\n--- Estado ---")
    print(f"database      : {'ok' if database_ok(runtime.database) else 'error'}")
    print(f"playwright    : {playwright_status()}")
    print(f"remote screen : {_screen_summary(runtime.screen)}")
    print(f"scheduler     : {'ON' if settings.scheduler_enabled else 'OFF'} ({_schedule_summary(settings)})")
    if last is not None:
        print(
            f"last run      : #{last.id} {last.trigger_source} {last.status} "
            f"(claimed={last.claimed_count}, owned={last.already_owned_count}, failed={last.failed_count})"
        )
    else:
        print("last run      : ninguna")
    print(
        f"accounts      : {len(accounts)} "
        f"({len(attention)} intervención / {len(need_auth)} sin autenticar)"
    )


def _schedule_summary(settings) -> str:
    if settings.scheduler_daily:
        return f"diario @ {settings.scheduler_times}"
    return f"días {settings.scheduler_days} @ {settings.scheduler_times}"


def _screen_summary(screen) -> str:
    if screen is None:
        return "n/a"
    info = screen.diagnostics()
    if info.get("mode") == "local-headed":
        return "local (headed en esta máquina)"
    return "standalone noVNC (servidor)"


# ---------------------------------------------------------------- accounts


def _accounts_menu(runtime: Runtime) -> None:
    while True:
        with runtime.database.connect() as connection:
            accounts = runtime.account_service.list(connection)
        print("\n--- Cuentas ---")
        if not accounts:
            print("(sin cuentas)")
        for account in accounts:
            flag = "" if account.enabled else " [disabled]"
            print(
                f" {account.id}) {account.display_name} "
                f"[{account.state}]{flag} order={account.processing_order}"
            )
        print("\n 1) Agregar cuenta")
        print(" 2) Autenticar cuenta")
        print(" 3) Editar cuenta (nombre / orden / enabled)")
        print(" 4) Resolver intervención")
        print(" 5) Detener sesión de autenticación activa")
        print(" 6) Eliminar permanentemente")
        print(" 7) Login local (fallback: PC + copiar perfil)")
        print(" 0) Volver")
        choice = _input("Cuentas> ")
        if choice == "1":
            _add_account(runtime)
        elif choice == "2":
            _authenticate(runtime)
        elif choice == "3":
            _edit_account(runtime)
        elif choice == "4":
            _resolve_intervention(runtime)
        elif choice == "5":
            _stop_auth_session(runtime)
        elif choice == "6":
            _delete_account(runtime)
        elif choice == "7":
            _local_login_fallback()
        elif choice in {"0", "q", "Q"}:
            return
        else:
            print("Opción inválida.")


def _add_account(runtime: Runtime) -> None:
    name = _input("Nombre visible> ")
    if not name:
        print("Nombre vacío: cancelado.")
        return
    with runtime.database.connect() as connection:
        account = runtime.account_service.create(connection, name)
    print(f"✓ Cuenta #{account.id} ({account.display_name}) creada. Pasá a Autenticar.")


def _pick_account_id(runtime: Runtime) -> int | None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
    if not accounts:
        print("No hay cuentas.")
        return None
    raw = _input("ID de cuenta> ")
    try:
        account_id = int(raw)
    except ValueError:
        print("ID inválido.")
        return None
    return account_id if any(account.id == account_id for account in accounts) else None


def _authenticate(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
    if not accounts:
        print("No hay cuentas.")
        return
    for account in accounts:
        print(f" {account.id}) {account.display_name} [{account.state}]")
    raw = _input("ID de cuenta a autenticar> ")
    try:
        account_id = int(raw)
    except ValueError:
        print("ID inválido.")
        return
    session = runtime.auth_service.start(account_id)
    status = session.status
    if status == "unavailable":
        print(f"Autenticación no disponible: {session.error}")
        return
    if status == "failed":
        print(f"No se pudo iniciar: {session.error}")
        return
    if session.screen_url:
        print("\n" + "=" * 64)
        print("Abrí esta URL en tu navegador (PC o celular, LAN o Tailscale):")
        print(f"  {session.screen_url}")
        print("Completá el login / MFA / CAPTCHA de Epic ahí dentro.")
        print("Las credenciales quedan SOLO en el servidor; no en esta máquina.")
        print("=" * 64 + "\n")
    else:
        print("\nSe abrirá un Chromium local: completá el login en la ventana que aparece.")
    print("Esperando confirmación de login (15 min de timeout)...")
    deadline = time.time() + AUTH_TIMEOUT_MINUTES * 60
    current = session
    while time.time() < deadline:
        time.sleep(3)
        current = runtime.auth_service.get(session.token) or current
        if current.status != "running":
            break
    if current.status == "completed" and not current.error:
        print("✓ Autenticación confirmada: la cuenta está activa.")
    else:
        reason = current.error or "timeout esperando el login"
        print(f"✗ {reason}")
        print("Resolvé el problema desde el menú y volvé a autenticar.")


def _local_login_fallback() -> None:
    """Instructions for the documented manual login fallback (SPECS 15).

    The server cannot spawn processes on the user's PC, so this prints the
    exact command to run there; the resulting profile is copied explicitly
    by the user to the server volume.
    """
    print("\n--- Login local (fallback manual) ---")
    print("En tu PC corré UNO de estos dos comandos (repo epic_reclaim):")
    print(" a) Perfil persistente (recomendado: Google/Epic quedan enlazados):")
    print("      py tools\\local_login.py")
    print(" b) Perfil aislado (arranca de cero):")
    print("      py tools\\local_login.py --fresh")
    print("Logueate en la ventana de Chrome que se abre y cerrá Chrome.")
    print("Luego copiá el perfil al volumen del server (vía Tailscale/scp) y")
    print("dispará 'Autenticar cuenta': detecta la sesión y activa la cuenta.")
    print("Nunca uses el perfil diario: expondría sesiones no relacionadas.")
    return


def _edit_account(runtime: Runtime) -> None:
    account_id = _pick_account_id(runtime)
    if account_id is None:
        return
    with runtime.database.connect() as connection:
        account = runtime.account_service.get(connection, account_id)
    name = _input(f"Nombre visible [{account.display_name}]> ") or account.display_name
    order = _input(f"Orden de procesamiento [{account.processing_order}]> ") or str(account.processing_order)
    enabled = _input(f"Enabled true/false [{account.enabled}]> ") or str(account.enabled)
    if not order.isdigit():
        print("Orden inválido.")
        return
    with runtime.database.connect() as connection:
        updated = runtime.account_service.update(
            connection,
            account.id,
            display_name=name,
            processing_order=int(order),
            enabled=enabled.lower() in {"1", "true", "yes", "on"},
        )
    print(f"✓ Cuenta #{updated.id} actualizada.")


def _resolve_intervention(runtime: Runtime) -> None:
    account_id = _pick_account_id(runtime)
    if account_id is None:
        return
    with runtime.database.connect() as connection:
        resolved = runtime.account_service.resolve_intervention(connection, account_id)
    print(f"✓ Cuenta #{resolved.id} vuelve a {resolved.state}.")


def _stop_auth_session(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
    if not accounts:
        print("No hay cuentas.")
        return
    for account in accounts:
        print(f" {account.id}) {account.display_name}")
    raw = _input("ID de cuenta cuya autenticación detener> ")
    try:
        account_id = int(raw)
    except ValueError:
        print("ID inválido.")
        return
    runtime.auth_service.revoke_account(account_id)
    print("✓ Sesión de autenticación detenida (si estaba activa).")


def _delete_account(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
    if not accounts:
        return
    for account in accounts:
        print(f" {account.id}) {account.display_name}")
    raw = _input("ID de cuenta a eliminar PERMANENTEMENTE> ")
    try:
        account_id = int(raw)
    except ValueError:
        print("ID inválido.")
        return
    target = next((account for account in accounts if account.id == account_id), None)
    if target is None:
        print("Cuenta no encontrada.")
        return
    confirmation = _input(f"Escribí '{target.display_name}' para confirmar> ")
    if confirmation != target.display_name:
        print("Cancelado.")
        return
    runtime.auth_service.revoke_account(target.id)
    with runtime.database.connect() as connection:
        runtime.account_service.delete(connection, target.id)
    print(f"Cuenta #{target.id} eliminada (incluye historial de claims).")


# ---------------------------------------------------------------- runs


def _run_now(runtime: Runtime) -> None:
    outcome = runtime.workflow.start(RunTrigger.MANUAL)
    if outcome.status == "conflict":
        print(f"Ya hay una ejecución en progreso (run #{outcome.run_id}).")
        return
    print(f"RUN #{outcome.run_id} iniciado. Ctrl+C deja de mirar sin parar el run.")
    try:
        _follow_run(runtime, run_id=outcome.run_id, deadline_seconds=30 * 60)
    except KeyboardInterrupt:
        print("(sigue corriendo en segundo plano)")


def _follow_run(runtime: Runtime, run_id: int, deadline_seconds: int) -> None:
    last_event_id = 0
    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        time.sleep(2)
        try:
            with runtime.database.connect() as connection:
                run = runtime.runs_repository.get(connection, run_id)
                events = runtime.events_repository.list_by_run(connection, run_id, limit=200)
        except Exception:
            continue
        for event in reversed(events):
            if event.id <= last_event_id:
                continue
            last_event_id = event.id
            extra = ""
            if event.account_id:
                extra += f" account={event.account_id}"
            if event.game_id:
                extra += f" game={event.game_id}"
            message = f" {event.message}" if event.message else ""
            print(f"  {event.event_type}{message}{extra}")
        if run.status != "running":
            print(
                f"RUN #{run_id} = {run.status} (games={run.games_detected}, "
                f"claimed={run.claimed_count}, owned={run.already_owned_count}, "
                f"failed={run.failed_count}, skipped={run.skipped_count})"
            )
            return
    print("Timeout esperando el fin del run (sigue en background).")


def _runs_history(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        runs = runtime.runs_repository.list(connection, limit=20)
    if not runs:
        print("No hay runs registrados.")
        return
    print("\n--- Últimos runs ---")
    for run in runs:
        print(
            f" #{run.id} {run.started_at} {run.trigger_source:<9} {run.status:<9} "
            f"games={run.games_detected} claimed={run.claimed_count} "
            f"owned={run.already_owned_count} failed={run.failed_count} "
            f"skipped={run.skipped_count}"
        )


def _claims_history(runtime: Runtime) -> None:
    with runtime.database.connect() as connection:
        accounts = runtime.account_service.list(connection)
        games = {game.id: game.name for game in runtime.games_repository.list(connection)}
    name_by_id = {account.id: account.display_name for account in accounts}
    print(f"Estados posibles: {', '.join(CLAIM_STATUSES)} (Enter = todos)")
    raw_account = _input("  account id (Enter = todos)> ") or None
    raw_status = _input("  estado (Enter = todos)> ") or None
    raw_since = _input("  desde YYYY-MM-DD (Enter = siempre)> ") or None
    try:
        account_id = int(raw_account) if raw_account else None
    except ValueError:
        print("ID inválido.")
        return
    with runtime.database.connect() as connection:
        claims = runtime.claims_repository.list(
            connection, account_id=account_id, status=raw_status, since=raw_since
        )
    if not claims:
        print("(sin claims para ese filtro)")
        return
    print("\n--- Claims ---")
    for claim in claims:
        account_name = name_by_id.get(claim.account_id, str(claim.account_id))
        error = f" error='{claim.error}'" if claim.error else ""
        print(
            f" [{account_name}] {games.get(claim.game_id, claim.game_id)!s:<30} "
            f"{claim.status:<13} attempts={claim.attempts}{error} "
            f"updated={claim.updated_at}"
        )


# ---------------------------------------------------------------- settings


def _settings_menu(runtime: Runtime) -> None:
    while True:
        with runtime.database.connect() as connection:
            settings = runtime.settings_service.load(connection)
            raw = runtime.settings_service.view(connection)
        print("\n--- Settings ---")
        print(f" 1) scheduler : {'ON' if settings.scheduler_enabled else 'OFF'} ({_schedule_summary(settings)})")
        print(f" 2) delays    : min={settings.claim_delay_min_seconds} max={settings.claim_delay_max_seconds}")
        if raw:
            for key in sorted(raw):
                print(f"    {key} = {raw[key]}")
        print(" 3) Editar scheduler")
        print(" 4) Editar delays")
        print(" 0) Volver")
        choice = _input("Settings> ")
        if choice == "3":
            _edit_scheduler(runtime, settings)
        elif choice == "4":
            _edit_delays(runtime, settings)
        elif choice in {"0", "q", "Q"}:
            return
        else:
            print("Opción inválida.")


def _edit_scheduler(runtime: Runtime, current) -> None:
    print("Días válidos: MON,TUE,WED,THU,FRI,SAT,SUN. Preset navidad = daily=true.")
    enable = _input(f"scheduler enabled true/false [{current.scheduler_enabled}]> ")
    days = _input(f"días [{current.scheduler_days}]> ")
    times = _input(f"horarios HH:MM, coma: [{current.scheduler_times}]> ")
    daily = _input(f"diario true/false [{current.scheduler_daily}]> ")

    updates: dict[str, str] = {}
    if enable:
        updates["scheduler_enabled"] = enable
    if days:
        updates["scheduler_days"] = days
    if times:
        updates["scheduler_times"] = times
    if daily:
        updates["scheduler_daily"] = daily
    try:
        _validate_scheduler_edits(current, updates)
    except scheduling.ScheduleError as exc:
        print(f"Config inválida: {exc}")
        return
    with runtime.database.connect() as connection:
        runtime.settings_service.update(
            connection,
            updates,
            {"scheduler_enabled", "scheduler_days", "scheduler_times", "scheduler_daily"},
        )
    print("✓ Scheduler actualizado (aplica sin reiniciar).")


def _validate_scheduler_edits(current, updates: dict[str, str]) -> None:
    days = updates.get("scheduler_days", current.scheduler_days)
    times = updates.get("scheduler_times", current.scheduler_times)
    daily = updates.get("scheduler_daily", str(current.scheduler_daily)).lower() in {
        "1", "true", "yes", "on",
    }
    scheduling.normalize_days(days)
    scheduling.normalize_times(times)
    if not scheduling.build_slots(days, times, daily=daily):
        raise scheduling.ScheduleError("el horario debe tener al menos un día y hora")


def _edit_delays(runtime: Runtime, current) -> None:
    min_raw = _input(f"delay mínimo en segundos [{current.claim_delay_min_seconds}]> ")
    max_raw = _input(f"delay máximo en segundos [{current.claim_delay_max_seconds}]> ")
    try:
        delay_min = float(min_raw) if min_raw else current.claim_delay_min_seconds
        delay_max = float(max_raw) if max_raw else current.claim_delay_max_seconds
    except ValueError:
        print("Valores inválidos.")
        return
    if delay_min < 0 or delay_max < delay_min:
        print("Rango inválido (min >= 0 y min <= max).")
        return
    with runtime.database.connect() as connection:
        runtime.settings_service.update(
            connection,
            {
                "claim_delay_min_seconds": str(delay_min),
                "claim_delay_max_seconds": str(delay_max),
            },
            {"claim_delay_min_seconds", "claim_delay_max_seconds"},
        )
    print("✓ Delays actualizados.")


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nSaliendo.")
        sys.exit(130)
