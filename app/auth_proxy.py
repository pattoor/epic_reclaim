"""Reverse proxy for noVNC served over the main application port.

Exposes a single temporary URL per authentication session. The URL is only
valid while the session is running and does not expose cookies, CDP or the
persistent browser profile. The proxy forwards HTTP and WebSocket traffic to
the local websockify instance started by NoVNCProvider.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.websockets import WebSocket


class AuthProxy:
    """Proxies requests to the noVNC/websockify backend for a given session."""

    def __init__(self, auth_service, ws_port: int = 6080):
        self._auth_service = auth_service
        self._ws_port = ws_port
        self._client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{ws_port}")

    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/api/remote-screen/{token}", self._http_proxy, methods=["GET"])
        router.add_api_route("/api/remote-screen/{token}/{path:path}", self._http_proxy, methods=["GET"])
        router.add_websocket_route("/api/remote-screen/{token}/websockify", self._ws_proxy)
        return router

    def _session_for(self, token: str):
        session = self._auth_service.get(token)
        if session is None or session.status != "running":
            raise HTTPException(status_code=404, detail="session not found or expired")
        return session

    async def _http_proxy(self, request: Request, token: str, path: str = ""):
        self._session_for(token)
        target_path = f"/{path}" if path else "/vnc.html"
        if target_path == "/":
            target_path = "/vnc.html"
        target_url = f"{target_path}"
        if request.query_params:
            target_url += f"?{request.query_params}"
        try:
            upstream = await self._client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection")},
                content=await request.body(),
                timeout=30.0,
            )
        except httpx.ConnectError as exc:
            raise HTTPException(status_code=503, detail="remote screen proxy unreachable") from exc

        response_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower()
            not in (
                "transfer-encoding",
                "content-length",
                "content-encoding",
                "connection",
            )
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    async def _ws_proxy(self, websocket: WebSocket, token: str):
        await websocket.accept()
        self._session_for(token)
        target_uri = f"ws://127.0.0.1:{self._ws_port}/websockify"
        try:
            import websockets
        except ImportError:  # pragma: no cover
            await websocket.close(code=1011, reason="websocket proxy not available")
            return

        try:
            async with websockets.connect(target_uri) as backend:
                async def client_to_backend():
                    while True:
                        data = await websocket.receive_bytes()
                        await backend.send(data)

                async def backend_to_client():
                    async for data in backend:
                        data_bytes = data if isinstance(data, bytes) else data.encode()
                        await websocket.send_bytes(data_bytes)

                await asyncio.gather(client_to_backend(), backend_to_client())
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    async def close(self):
        await self._client.aclose()
