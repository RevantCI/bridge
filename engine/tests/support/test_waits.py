"""Tests for the background-job wait budgets (#85)."""
from __future__ import annotations

import pytest

from tests.support.waits import FLOOR_SECONDS, job_timeout, worker_count


def test_worker_count_is_one_when_not_running_under_xdist(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    assert worker_count() == 1


def test_worker_count_reads_the_xdist_environment_variable(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "12")
    assert worker_count() == 12


@pytest.mark.parametrize("raw", ["", "auto", "-3", "0"])
def test_worker_count_falls_back_to_serial_on_a_value_it_cannot_use(monkeypatch, raw):
    """A malformed or nonsensical count must not crash collection or go below 1."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", raw)
    assert worker_count() == 1


def test_budget_never_drops_below_the_floor(monkeypatch):
    """The serial CI failure this floor exists for had a 10 s base (#85)."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    assert job_timeout(10) == FLOOR_SECONDS
    assert job_timeout(0.001) == FLOOR_SECONDS


def test_budget_scales_past_the_floor_with_worker_count(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "12")
    assert job_timeout(10) == 120.0


def test_a_generous_base_survives_scaling(monkeypatch):
    """An explicit long budget at a call site is scaled, never capped back down."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")
    assert job_timeout(60) == 240.0
