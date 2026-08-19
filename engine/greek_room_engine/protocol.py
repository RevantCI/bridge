"""
Stable JSON protocol for talking to the GreekRoomEngine.

This is intentionally transport-agnostic: the same request/response shapes
are used whether the engine is reached over stdio (desktop sidecar) or HTTP
(future web deployment). Only the transport layer changes; this schema does
not.

Request:
{
  "id": "request-001",
  "method": "verse.check",
  "params": { ... }
}

Response (success):
{
  "id": "request-001",
  "success": true,
  "findings": [ QaFinding, ... ]
}

Response (error):
{
  "id": "request-001",
  "success": false,
  "error": { "code": "...", "message": "..." }
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .models.finding import QaFinding

PROTOCOL_VERSION = "1.0"


@dataclass
class EngineRequest:
    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_json(raw: str) -> "EngineRequest":
        d = json.loads(raw)
        return EngineRequest(id=d["id"], method=d["method"], params=d.get("params", {}))

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EngineRequest":
        return EngineRequest(id=d["id"], method=d["method"], params=d.get("params", {}))


@dataclass
class EngineError:
    code: str
    message: str


@dataclass
class EngineResponse:
    id: str
    success: bool
    findings: Optional[list[QaFinding]] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[EngineError] = None
    protocol_version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "success": self.success,
            "protocolVersion": self.protocol_version,
        }
        if self.findings is not None:
            d["findings"] = [f.to_dict() for f in self.findings]
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = {"code": self.error.code, "message": self.error.message}
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def ok(request_id: str, findings: Optional[list[QaFinding]] = None,
           result: Optional[dict[str, Any]] = None) -> "EngineResponse":
        return EngineResponse(id=request_id, success=True, findings=findings, result=result)

    @staticmethod
    def fail(request_id: str, code: str, message: str) -> "EngineResponse":
        return EngineResponse(id=request_id, success=False, error=EngineError(code, message))


# Known methods for v0.7.5 (Wildebeest + OWL only; more added per roadmap stage)
class Methods:
    PING = "ping"
    ENGINE_INFO = "engine.info"
    VERSE_CHECK = "verse.check"
    CORPUS_PROFILE_BUILD = "corpus.profile.build"
