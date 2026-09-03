from __future__ import annotations

import ctypes
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable

_REF_RE = re.compile(r'^([1-4]?[A-Z]{2,4})\s+(\d+):([0-9]+[A-Za-z]?)$', re.I)


def normalize_reference(reference: str) -> str:
    text = ' '.join(str(reference or '').strip().upper().split())
    m = _REF_RE.match(text)
    if not m:
        return ''
    book, chapter, verse = m.groups()
    return f'{book} {int(chapter)}:{verse.lower() if verse[-1:].isalpha() else int(verse)}'


@dataclass(frozen=True)
class NavigationEvent:
    reference: str
    origin: str
    request_id: str
    timestamp: float


class NavigationBroker:
    """Small deterministic echo/duplicate guard for Bridge, Paratext and Logos.

    Connectors do not directly forward events to one another. The Bridge owns the current
    reference. Every accepted external change enters through this broker, then the UI loads the
    verse and broadcasts the new current reference to every *other* enabled connector.
    """

    def __init__(self, *, echo_window_seconds: float = 2.5, settling_window_seconds: float = 1.4, clock=time.monotonic):
        self.echo_window_seconds = float(echo_window_seconds)
        self.settling_window_seconds = min(float(settling_window_seconds), self.echo_window_seconds)
        self._clock = clock
        self.current_reference = ''
        self.current_origin = 'bridge'
        self._outbound: dict[str, tuple[str, str, float, bool, str]] = {}
        self._observed: dict[str, str] = {}
        # A rejected external candidate stays suppressed while the surrounding Bridge context is
        # unchanged (for example dirty alignment the reviewer chose not to discard). If that
        # context changes, the same still-visible external reference may safely be offered again.
        self._rejected: dict[str, tuple[str, str]] = {}

    def new_event(self, reference: str, origin: str, *, context: str = '') -> NavigationEvent | None:
        ref = normalize_reference(reference)
        if not ref:
            return None
        origin = str(origin or 'bridge').lower()
        now = self._clock()
        # An exact reference sent to a connector moments ago is an echo, not a new user action.
        sent = self._outbound.get(origin)
        if sent and (now - sent[2]) <= self.echo_window_seconds:
            sent_ref, sent_id, sent_at, confirmed, prior_observed = sent
            if sent_ref == ref:
                # The connector has reached the reference we asked it to show. From this point
                # a *different* reference can immediately be treated as a real user change.
                self._outbound[origin] = (sent_ref, sent_id, sent_at, True, prior_observed)
                self._observed[origin] = ref
                return None
            if (not confirmed and prior_observed and ref == prior_observed
                    and (now - sent_at) <= self.settling_window_seconds):
                # A polled connector can briefly report its previous verse while an outbound
                # navigation is still settling. Do not bounce that stale observation back to
                # the other applications. After the short settling window, fail open so a
                # genuine user change or failed navigation is not suppressed indefinitely.
                # Forget the old observed value so that the same differing state can become a
                # real event after the settling window if the connector never confirms target.
                self._observed.pop(origin, None)
                return None
        # Polling the same unchanged connector state repeatedly is not a navigation event. A
        # previously rejected candidate is the one exception: if the Bridge context has changed
        # (dirty state resolved, project selection changed, project list changed, etc.), retry it.
        observed = self._observed.get(origin)
        rejected = self._rejected.get(origin)
        if observed == ref:
            if not (rejected and rejected[0] == ref and rejected[1] != str(context or '')):
                return None
            self._rejected.pop(origin, None)
        elif rejected and rejected[0] != ref:
            self._rejected.pop(origin, None)
        self._observed[origin] = ref
        if self.current_reference == ref:
            return None
        event = NavigationEvent(ref, origin, uuid.uuid4().hex, now)
        self.current_reference = ref
        self.current_origin = origin
        return event

    def commit_event(self, event: NavigationEvent) -> None:
        """Commit a candidate after the Bridge actually loaded the requested destination."""
        origin = str(event.origin or '').lower()
        self._rejected.pop(origin, None)
        self.current_reference = normalize_reference(event.reference)
        self.current_origin = origin or 'bridge'

    def reject_event(self, event: NavigationEvent, bridge_reference: str = '', *, context: str = '') -> None:
        """Roll broker state back when an external candidate could not be loaded.

        Keep the connector's observed value so polling does not repeatedly prompt the reviewer.
        The same reference becomes eligible again when ``context`` changes or when the external
        application first moves to another reference and later returns.
        """
        origin = str(event.origin or '').lower()
        ref = normalize_reference(event.reference)
        if origin and ref:
            self._observed[origin] = ref
            self._rejected[origin] = (ref, str(context or ''))
        actual = normalize_reference(bridge_reference)
        self.current_reference = actual
        self.current_origin = 'bridge'

    def clear_rejection(self, origin: str = '') -> None:
        key = str(origin or '').lower()
        if key:
            self._rejected.pop(key, None)
            return
        self._rejected.clear()

    def set_bridge_reference(self, reference: str, origin: str = 'bridge', request_id: str = '') -> NavigationEvent | None:
        ref = normalize_reference(reference)
        if not ref:
            return None
        event = NavigationEvent(ref, str(origin or 'bridge').lower(), request_id or uuid.uuid4().hex, self._clock())
        self.current_reference = ref
        self.current_origin = event.origin
        self._observed['bridge'] = ref
        return event

    def observe_state(self, target: str, reference: str) -> str:
        """Seed a connector's last known state without treating it as user navigation."""
        ref = normalize_reference(reference)
        if ref:
            self._observed[str(target or '').lower()] = ref
        return ref

    def record_outbound(self, target: str, reference: str, request_id: str = '') -> str:
        ref = normalize_reference(reference)
        if not ref:
            return ''
        rid = request_id or uuid.uuid4().hex
        target_key = str(target or '').lower()
        self._outbound[target_key] = (ref, rid, self._clock(), False, self._observed.get(target_key, ''))
        return rid

    def is_recent_outbound(self, target: str, reference: str) -> bool:
        ref = normalize_reference(reference)
        sent = self._outbound.get(str(target or '').lower())
        return bool(ref and sent and sent[0] == ref and (self._clock() - sent[2]) <= self.echo_window_seconds)


class NavigationOwnership:
    """Per-Windows-user mutex preventing two Bridge processes from driving navigation.

    The mutex is acquired only when external verse synchronization is enabled. A second Bridge
    window remains fully usable, but cannot own Paratext/Logos navigation until the first releases
    it. Non-Windows builds fail open because the external desktop connectors are Windows-only.
    """

    DEFAULT_NAME = r'Local\translationCoreAIBridge.NavigationOwner'
    WAIT_OBJECT_0 = 0x00000000
    WAIT_ABANDONED = 0x00000080

    def __init__(self, name: str = DEFAULT_NAME):
        self.name = str(name)
        self._handle = None
        self._owned = False

    @property
    def owned(self) -> bool:
        return bool(self._owned)

    def acquire(self) -> bool:
        if self._owned:
            return True
        if os.name != 'nt':
            self._owned = True
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return False
        result = int(kernel32.WaitForSingleObject(handle, 0))
        if result not in (self.WAIT_OBJECT_0, self.WAIT_ABANDONED):
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        handle, self._handle = self._handle, None
        self._owned = False
        if os.name == 'nt' and handle:
            try:
                ctypes.windll.kernel32.ReleaseMutex(handle)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)

    def close(self) -> None:
        self.release()


class NavigationSyncCoordinator:
    """Coordinate opt-in Bridge/Paratext/Logos navigation without blocking RPC.

    Connector calls can take seconds when an application is starting or unavailable. ``snapshot``
    therefore starts at most one daemon probe and immediately returns cached state. The Bridge UI
    can poll this object freely without putting its single-threaded stdio dispatcher behind a
    desktop-application timeout.
    """

    TARGETS = ('paratext', 'logos')

    def __init__(
        self,
        *,
        paratext_client: Callable[[], Any],
        logos_client: Callable[[], Any],
        ownership: NavigationOwnership | None = None,
        poll_interval_seconds: float = 0.8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clients = {'paratext': paratext_client, 'logos': logos_client}
        self._ownership = ownership or NavigationOwnership()
        self._poll_interval = max(0.1, float(poll_interval_seconds))
        self._clock = clock
        self._lock = threading.RLock()
        self._broker = NavigationBroker(clock=clock)
        self._enabled = {target: False for target in self.TARGETS}
        self._target_state: dict[str, dict[str, Any]] = {
            target: self._empty_target_state(False) for target in self.TARGETS
        }
        self._outbound: dict[str, tuple[str, str]] = {}
        self._pending: NavigationEvent | None = None
        self._polling = False
        self._next_poll_at = 0.0
        self._closed = False

    @staticmethod
    def _empty_target_state(enabled: bool) -> dict[str, Any]:
        return {
            'enabled': bool(enabled), 'checking': False, 'connected': False,
            'reference': '', 'error': '', 'checkedAt': 0.0,
        }

    @staticmethod
    def _state_dict(value: Any) -> dict[str, Any]:
        if is_dataclass(value):
            return asdict(value)
        return dict(value) if isinstance(value, dict) else {}

    def configure(self, *, paratext: bool, logos: bool) -> dict[str, Any]:
        requested = {'paratext': bool(paratext), 'logos': bool(logos)}
        with self._lock:
            if self._closed:
                return self._snapshot_locked()
            was_enabled = any(self._enabled.values())
            for target, enabled in requested.items():
                newly_enabled = enabled and not self._enabled[target]
                self._enabled[target] = enabled
                self._target_state[target]['enabled'] = enabled
                if not enabled:
                    self._outbound.pop(target, None)
                    self._target_state[target] = self._empty_target_state(False)
                elif newly_enabled and self._broker.current_reference:
                    request_id = uuid.uuid4().hex
                    self._outbound[target] = (self._broker.current_reference, request_id)
            is_enabled = any(self._enabled.values())
            if is_enabled and not self._ownership.owned:
                self._ownership.acquire()
            if was_enabled and not is_enabled:
                self._pending = None
                self._outbound.clear()
                self._ownership.release()
            if is_enabled and self._ownership.owned:
                self._schedule_probe_locked(force=True)
            return self._snapshot_locked()

    def bridge_changed(self, reference: str) -> dict[str, Any]:
        ref = normalize_reference(reference)
        with self._lock:
            if not ref or self._closed:
                return self._snapshot_locked()
            if self._pending and self._pending.reference == ref:
                return self._snapshot_locked()
            superseded_pending = self._pending is not None
            if self._pending:
                self._broker.reject_event(
                    self._pending, ref, context='bridge-reference-changed',
                )
                self._pending = None
            if self._broker.current_reference == ref and not superseded_pending:
                return self._snapshot_locked()
            event = self._broker.set_bridge_reference(ref)
            if event:
                for target, enabled in self._enabled.items():
                    if enabled:
                        self._outbound[target] = (ref, event.request_id)
                self._schedule_probe_locked(force=True)
            return self._snapshot_locked()

    def resolve(
        self,
        request_id: str,
        *,
        accepted: bool,
        bridge_reference: str = '',
        context: str = '',
    ) -> dict[str, Any]:
        with self._lock:
            event = self._pending
            if event is None or event.request_id != str(request_id or ''):
                return self._snapshot_locked()
            self._pending = None
            if accepted:
                self._broker.commit_event(event)
                for target, enabled in self._enabled.items():
                    if enabled and target != event.origin:
                        self._outbound[target] = (event.reference, event.request_id)
            else:
                self._broker.reject_event(event, bridge_reference, context=context)
            self._schedule_probe_locked(context=context, force=True)
            return self._snapshot_locked()

    def snapshot(self, *, context: str = '', schedule_probe: bool = True) -> dict[str, Any]:
        with self._lock:
            if any(self._enabled.values()) and not self._ownership.owned:
                self._ownership.acquire()
            if schedule_probe and self._ownership.owned:
                self._schedule_probe_locked(context=context)
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        pending = self._pending
        return {
            'enabled': any(self._enabled.values()),
            'ownsNavigation': self._ownership.owned,
            'ownerConflict': any(self._enabled.values()) and not self._ownership.owned,
            'currentReference': self._broker.current_reference,
            'currentOrigin': self._broker.current_origin,
            'candidate': None if pending is None else {
                'reference': pending.reference,
                'origin': pending.origin,
                'requestId': pending.request_id,
            },
            'paratext': dict(self._target_state['paratext']),
            'logos': dict(self._target_state['logos']),
        }

    def _schedule_probe_locked(self, *, context: str = '', force: bool = False) -> None:
        if self._closed or self._polling or not any(self._enabled.values()) or not self._ownership.owned:
            return
        now = self._clock()
        if not force and now < self._next_poll_at:
            return
        self._polling = True
        for target, enabled in self._enabled.items():
            if enabled:
                self._target_state[target]['checking'] = True
        thread = threading.Thread(
            target=self._probe,
            args=(str(context or ''),),
            name='BridgeNavigationProbe',
            daemon=True,
        )
        thread.start()

    def _probe(self, context: str) -> None:
        try:
            for target in self.TARGETS:
                with self._lock:
                    if self._closed or not self._enabled[target] or not self._ownership.owned:
                        continue
                    outbound = self._outbound.pop(target, None)
                try:
                    client = self._clients[target]()
                    if outbound:
                        reference, request_id = outbound
                        with self._lock:
                            self._broker.record_outbound(target, reference, request_id)
                        if target == 'paratext':
                            client.set_reference(reference, request_id)
                        else:
                            client.set_reference(reference, origin_id=request_id)
                    raw_state = self._state_dict(client.get_state())
                    raw_state.update({
                        'enabled': True,
                        'checking': False,
                        'error': '',
                        'checkedAt': time.time(),
                    })
                    with self._lock:
                        if self._closed or not self._enabled[target] or not self._ownership.owned:
                            continue
                        self._target_state[target] = raw_state
                        if self._pending is None:
                            event = self._broker.new_event(
                                str(raw_state.get('reference') or ''), target, context=context,
                            )
                            if event:
                                self._pending = event
                except Exception as exc:
                    with self._lock:
                        if outbound and self._enabled[target] and not self._closed:
                            # Keep the latest Bridge destination pending so a connector that
                            # starts later catches up before its old verse can drive Bridge.
                            self._outbound.setdefault(target, outbound)
                        if self._closed or not self._enabled[target]:
                            continue
                        prior = self._target_state[target]
                        self._target_state[target] = {
                            **self._empty_target_state(True),
                            'reference': str(prior.get('reference') or ''),
                            'error': str(exc),
                            'checkedAt': time.time(),
                        }
        finally:
            with self._lock:
                self._polling = False
                self._next_poll_at = self._clock() + self._poll_interval
                for target in self.TARGETS:
                    self._target_state[target]['checking'] = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None
            self._outbound.clear()
            self._ownership.release()
