from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.protocol import EngineRequest, Methods


def test_ping():
    engine = GreekRoomEngine()
    resp = engine.handle_request(EngineRequest(id="1", method=Methods.PING))
    assert resp.success is True
    assert resp.result == {"pong": True}


def test_engine_info_lists_wildebeest_adapter():
    engine = GreekRoomEngine()
    resp = engine.handle_request(EngineRequest(id="2", method=Methods.ENGINE_INFO))
    assert resp.success is True
    assert "wildebeest" in resp.result["adapters"]


def test_verse_check_mixed_script_flagged_by_mock_adapter(monkeypatch):
    # Force the mock path regardless of whether the optional real
    # wildebeest-nlp package happens to be installed in this environment —
    # this test is specifically about the fallback mock's own behavior
    # (see test_wildebeest_real.py for the real-engine equivalent, skipped
    # automatically when the real package isn't installed).
    from greek_room_engine.adapters import wildebeest_adapter
    monkeypatch.setattr(wildebeest_adapter, "_WILDEBEEST_AVAILABLE", False)

    engine = GreekRoomEngine()
    req = EngineRequest(
        id="3",
        method=Methods.VERSE_CHECK,
        params={
            "projectId": "proj-1",
            "langCode": "tam",
            "verse": {"ref": "GEN 1:1", "text": "ஆதியிலேa தேவன்"},
            "checks": ["wildebeest"],
        },
    )
    resp = engine.handle_request(req)
    assert resp.success is True
    assert len(resp.findings) >= 1
    assert resp.findings[0].check_type == "wildebeest.script.mixed"


def test_verse_check_clean_text_no_findings():
    engine = GreekRoomEngine()
    req = EngineRequest(
        id="4",
        method=Methods.VERSE_CHECK,
        params={
            "projectId": "proj-1",
            "langCode": "tam",
            "verse": {"ref": "GEN 1:1", "text": "ஆதியிலே தேவன் வானத்தையும்"},
            "checks": ["wildebeest"],
        },
    )
    resp = engine.handle_request(req)
    assert resp.success is True
    assert resp.findings == []


def test_unknown_method_fails_gracefully():
    engine = GreekRoomEngine()
    resp = engine.handle_request(EngineRequest(id="5", method="nonsense.method"))
    assert resp.success is False
    assert resp.error.code == "unknown_method"
