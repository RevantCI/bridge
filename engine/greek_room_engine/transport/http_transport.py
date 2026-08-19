"""
HTTP transport (future web deployment path).

Same EngineRequest/EngineResponse protocol as stdio_transport.py — only the
wire format changes. This lets the frontend swap its transport
implementation (Tauri invoke/stdio vs. fetch/HTTP) without the
GreekRoomEngine or the protocol schema changing at all.

Not wired into the desktop build. Kept here so the web deployment path
doesn't require redesigning the protocol later — only requires this file
plus a WSGI/ASGI wrapper (e.g. FastAPI) when that milestone is prioritized.
"""
from __future__ import annotations

from typing import Any

from ..engine import GreekRoomEngine
from ..protocol import EngineRequest, EngineResponse


def handle_http_body(engine: GreekRoomEngine, body: dict[str, Any]) -> dict[str, Any]:
    """Given a parsed JSON request body, return a JSON-serializable response dict.

    Example FastAPI wiring (not included as a dependency here):

        app = FastAPI()
        engine = GreekRoomEngine()

        @app.post("/rpc")
        def rpc(body: dict):
            return handle_http_body(engine, body)
    """
    request = EngineRequest.from_dict(body)
    response = engine.handle_request(request)
    return response.to_dict()
