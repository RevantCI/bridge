import threading
import time

from tc_ai_bridge.navigation import NavigationSyncCoordinator


class FakeOwnership:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.owned = False

    def acquire(self):
        self.owned = self.allowed
        return self.owned

    def release(self):
        self.owned = False


class FakeConnector:
    def __init__(self, reference="TIT 1:1"):
        self.reference = reference
        self.sent = []

    def get_state(self):
        return {"connected": True, "reference": self.reference}

    def set_reference(self, reference, origin_id=""):
        self.reference = reference
        self.sent.append((reference, origin_id))
        return {"connected": True, "reference": reference}


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("navigation coordinator did not settle")


def make_coordinator(paratext, logos, ownership=None):
    return NavigationSyncCoordinator(
        paratext_client=lambda: paratext,
        logos_client=lambda: logos,
        ownership=ownership or FakeOwnership(),
        poll_interval_seconds=0.01,
    )


def test_bridge_reference_is_sent_to_each_enabled_connector_without_blocking():
    paratext = FakeConnector()
    logos = FakeConnector()
    sync = make_coordinator(paratext, logos)
    sync.bridge_changed("TIT 1:2")

    started = time.monotonic()
    state = sync.configure(paratext=True, logos=True)
    assert time.monotonic() - started < 0.1
    assert state["ownsNavigation"] is True

    wait_for(lambda: len(paratext.sent) == 1 and len(logos.sent) == 1)
    assert paratext.sent[0][0] == "TIT 1:2"
    assert logos.sent[0][0] == "TIT 1:2"


def test_external_navigation_is_committed_then_forwarded_only_to_other_connector():
    paratext = FakeConnector("TIT 1:1")
    logos = FakeConnector("TIT 1:1")
    sync = make_coordinator(paratext, logos)
    sync.bridge_changed("TIT 1:1")
    sync.configure(paratext=True, logos=True)
    wait_for(lambda: not sync._polling)
    paratext.sent.clear()
    logos.sent.clear()

    paratext.reference = "TIT 1:2"
    candidate = wait_for(lambda: sync.snapshot(context="clean")["candidate"])
    assert candidate["origin"] == "paratext"
    assert candidate["reference"] == "TIT 1:2"

    sync.resolve(candidate["requestId"], accepted=True, bridge_reference="TIT 1:2")
    wait_for(lambda: len(logos.sent) == 1)
    assert paratext.sent == []
    assert logos.sent[0][0] == "TIT 1:2"


def test_rejected_external_reference_is_reoffered_only_after_context_changes():
    paratext = FakeConnector("TIT 1:1")
    sync = make_coordinator(paratext, FakeConnector())
    sync.bridge_changed("TIT 1:1")
    sync.configure(paratext=True, logos=False)
    wait_for(lambda: not sync._polling)

    paratext.reference = "TIT 1:2"
    candidate = wait_for(lambda: sync.snapshot(context="editing")["candidate"])
    sync.resolve(
        candidate["requestId"], accepted=False, bridge_reference="TIT 1:1", context="editing",
    )

    wait_for(lambda: not sync._polling)
    time.sleep(0.11)
    sync.snapshot(context="editing")
    wait_for(lambda: not sync._polling)
    assert sync.snapshot(schedule_probe=False)["candidate"] is None

    retried = wait_for(lambda: sync.snapshot(context="clean")["candidate"])
    assert retried["reference"] == "TIT 1:2"


def test_owner_conflict_prevents_connector_calls():
    paratext = FakeConnector()
    sync = make_coordinator(paratext, FakeConnector(), FakeOwnership(allowed=False))
    state = sync.configure(paratext=True, logos=False)
    assert state["ownerConflict"] is True
    assert state["ownsNavigation"] is False
    time.sleep(0.03)
    assert paratext.sent == []


def test_slow_connector_probe_does_not_block_snapshot():
    release = threading.Event()

    class SlowConnector(FakeConnector):
        def get_state(self):
            release.wait(1.0)
            return super().get_state()

    sync = make_coordinator(SlowConnector(), FakeConnector())
    started = time.monotonic()
    state = sync.configure(paratext=True, logos=False)
    elapsed = time.monotonic() - started
    try:
        assert elapsed < 0.1
        assert state["paratext"]["checking"] is True
    finally:
        release.set()


def test_latest_bridge_reference_retries_when_connector_starts_late():
    class StartingConnector(FakeConnector):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def set_reference(self, reference, origin_id=""):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connector is still starting")
            return super().set_reference(reference, origin_id)

    paratext = StartingConnector()
    sync = make_coordinator(paratext, FakeConnector())
    sync.bridge_changed("TIT 1:3")
    sync.configure(paratext=True, logos=False)

    wait_for(lambda: paratext.attempts >= 1 and not sync._polling)
    wait_for(lambda: (sync.snapshot()["paratext"]["connected"] and paratext.attempts >= 2))
    assert paratext.reference == "TIT 1:3"
