"""
GreekRoomEngine: the one class the rest of our application is allowed to
call. Nothing outside this package should import wildebeest, owl, or any
other upstream module directly (doc §3, §31-32).
"""
from __future__ import annotations

import uuid
from typing import Any

from .adapters.base import CheckAdapter
from .adapters.wildebeest_adapter import WildebeestAdapter
from .models.finding import QaFinding
from .protocol import EngineRequest, EngineResponse, Methods

ENGINE_VERSION = "0.7.5-dev"


class GreekRoomEngine:
    def __init__(self) -> None:
        self._adapters: dict[str, CheckAdapter] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        self.register_adapter(WildebeestAdapter())
        # OWL, USFM, Versification, Uroman/SED, UAlign adapters are added in
        # later roadmap stages (v0.7.6+) per doc §35-41 — register here when ready.

    def register_adapter(self, adapter: CheckAdapter) -> None:
        self._adapters[adapter.engine_name] = adapter

    def info(self) -> dict[str, Any]:
        return {
            "engineVersion": ENGINE_VERSION,
            "adapters": {
                name: {
                    "available": a.is_available(),
                    "usingRealEngine": a.using_real_engine(),
                    "version": a.version(),
                }
                for name, a in self._adapters.items()
            },
        }

    def check_verse(self, *, project_id: str, lang_code: str, ref: str,
                     text: str, checks: list[str]) -> list[QaFinding]:
        """Run the requested checks (by adapter/engine name) against one verse.

        A missing/unavailable adapter is skipped, not fatal — the whole
        request should never fail just because one upstream engine (e.g.
        USFM checker, which needs more integration work) isn't ready yet.
        """
        findings: list[QaFinding] = []
        run_id = str(uuid.uuid4())

        for check_name in checks:
            adapter = self._adapters.get(check_name)
            if adapter is None or not adapter.is_available():
                continue
            result = adapter.check_verse(
                project_id=project_id, lang_code=lang_code, ref=ref,
                text=text, params={},
            )
            for f in result:
                f.run_id = run_id
            findings.extend(result)

        return findings

    # -- protocol dispatch --------------------------------------------------

    def handle_request(self, request: EngineRequest) -> EngineResponse:
        try:
            if request.method == Methods.PING:
                return EngineResponse.ok(request.id, result={"pong": True})

            if request.method == Methods.ENGINE_INFO:
                return EngineResponse.ok(request.id, result=self.info())

            if request.method == Methods.VERSE_CHECK:
                p = request.params
                verse = p["verse"]
                findings = self.check_verse(
                    project_id=p.get("projectId", ""),
                    lang_code=p.get("langCode", ""),
                    ref=verse["ref"],
                    text=verse["text"],
                    checks=p.get("checks", ["wildebeest"]),
                )
                return EngineResponse.ok(request.id, findings=findings)

            return EngineResponse.fail(
                request.id, "unknown_method", f"No handler for method '{request.method}'"
            )
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
