"""Optional web mode entrypoint.

`python -m app.web` starts the FastAPI app (API + dashboard + scheduler).
The console CLI (`python -m app.cli`) is the primary interface; both use the
same services via `app.bootstrap`.
"""

from __future__ import annotations

from app.main import app  # noqa: F401  (ASGI entry for "app.web:app")

if __name__ == "__main__":
    import uvicorn

    from app.config import Settings

    settings = Settings.from_env()
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
