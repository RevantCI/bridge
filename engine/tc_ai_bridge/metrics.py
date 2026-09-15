"""Observed workflow metrics for one book: counters, token totals and an
append-only event stream.

#77 moved this from ``metrics/<book>.json`` into two workbench tables:
``metrics_events`` (one row per event, append-only, no more 2000-event cap)
and ``metrics_counters`` (one row per book holding the counters, token
totals and estimated cost). ``load()`` returns the same dict shape the file
held, so ``summary()`` is unchanged.

Note for #93: ``event()`` has no production caller today. ``summary()`` is
read by ``reporting.py``, so the store is read and never written -- the same
shape as the terminology finding on that issue. Moved faithfully rather than
deleted, because that is a product call.
"""
from __future__ import annotations

import os
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .workbench_repository import natural_row_id


class MetricsStore:
    def __init__(self, project: Any):
        self.project = project
        self.book_id = project.book_id

    def _counters_row_id(self) -> str:
        return natural_row_id(self.project.workbench_identity.project_id, self.book_id, 'metrics_counters')

    def load(self) -> dict[str, Any]:
        identity = self.project.workbench_identity
        data: dict[str, Any] = {
            'schemaVersion': 1, 'bookId': self.book_id, 'counters': {},
            'tokens': {'input': 0, 'output': 0, 'total': 0}, 'estimatedCostUSD': 0.0, 'events': [],
        }
        counters = self.project.workbench.payloads(
            'metrics_counters', project_id=identity.project_id, book_id=self.book_id,
        )
        if counters:
            row = counters[0]
            data['counters'] = dict(row.get('counters') or {})
            data['tokens'] = {**data['tokens'], **dict(row.get('tokens') or {})}
            data['estimatedCostUSD'] = float(row.get('estimatedCostUSD') or 0.0)
        data['events'] = self.project.workbench.payloads(
            'metrics_events', project_id=identity.project_id, book_id=self.book_id,
        )
        return data

    def event(self, name: str, **fields: Any) -> None:
        if os.getenv('TC_AI_BRIDGE_TEST_MODE') == '1' and not fields.pop('_force_test_write', False):
            return
        d = self.load()
        counters = Counter(d.get('counters', {}))
        counters[name] += 1
        tokens = dict(d.get('tokens') or {})
        for field, key in (('input_tokens', 'input'), ('output_tokens', 'output'), ('total_tokens', 'total')):
            if field in fields:
                tokens[key] = int(tokens.get(key, 0) or 0) + int(fields.get(field, 0) or 0)
        cost = float(d.get('estimatedCostUSD', 0) or 0)
        if 'estimated_cost_usd' in fields:
            cost += float(fields.get('estimated_cost_usd', 0) or 0)
        ev = {
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'name': name, **fields,
        }
        identity = self.project.workbench_identity
        # Rows read back ordered by created_at then id. created_at is only as
        # fine as the platform clock (about a millisecond on Windows), so two
        # events in one tick would otherwise come back in uuid order; a
        # nanosecond prefix on the id keeps the stream in the order it was
        # written.
        event_id = f"{time.time_ns():020d}-{uuid.uuid4().hex[:12]}"
        with self.project.workbench.batch() as batch:
            batch.write(
                'metrics_events', event_id,
                project_id=identity.project_id, book_id=self.book_id, payload=ev,
                actor_id=identity.actor_id, device_id=identity.device_id,
            )
            batch.write(
                'metrics_counters', self._counters_row_id(),
                project_id=identity.project_id, book_id=self.book_id,
                payload={'counters': dict(counters), 'tokens': tokens, 'estimatedCostUSD': cost},
                actor_id=identity.actor_id, device_id=identity.device_id,
            )

    def summary(self) -> dict[str, Any]:
        d = self.load(); c = d.get('counters', {})
        accepted = int(c.get('human_accept', 0)); rejected = int(c.get('human_reject', 0)); edited = int(c.get('human_edit', 0)); discussions = int(c.get('human_discussion', 0)); decisions = accepted + rejected + edited + discussions
        denominator = max(1, accepted + rejected + edited)
        events = d.get('events', []) if isinstance(d.get('events'), list) else []
        prepared_checks = sum(int(e.get('checks', 0) or 0) for e in events if e.get('name') in ('ai_prepared_verse', 'ai_prepared_batch'))
        prepared_issues = sum(int(e.get('issues', 0) or 0) for e in events if e.get('name') in ('ai_prepared_verse', 'ai_prepared_batch'))
        cache_skips = sum(int(e.get('skipped', 0) or 0) for e in events if e.get('name') in ('ai_prepared_batch', 'cache_skip'))
        confirmed = sum(1 for e in events if e.get('name') == 'qa_decision' and e.get('decision') == 'accepted')
        qa_decisions = sum(1 for e in events if e.get('name') == 'qa_decision')
        return {**d,
            'acceptanceRate': accepted / denominator,
            'humanEditRate': edited / denominator,
            'rejectionRate': rejected / denominator,
            'humanDecisionCount': decisions,
            'aiPreparedCheckCount': prepared_checks,
            'aiPreparedFindingCount': prepared_issues,
            'unchangedReviewCacheSkips': cache_skips,
            'confirmedQAFindingRate': (confirmed / qa_decisions if qa_decisions else None),
            'measurementNote': 'These are observed workflow metrics, not an inferred claim of time saved. Compare against a manual-review baseline for the same team/project.'
        }
