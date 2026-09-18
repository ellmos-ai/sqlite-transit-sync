# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SingleFlightLock in sqlite-transit-sync."""

import json
import time
from pathlib import Path

import pytest

from sqlite_transit_sync.network_lock import SingleFlightLock, SingleFlightLockError


def test_single_flight_acquire_release(tmp_path: Path):
    lock_file = tmp_path / "transfer-attempt.json"
    lock = SingleFlightLock(lock_file, ttl_seconds=60)

    assert not lock_file.exists()
    with lock:
        assert lock_file.exists()
        info = json.loads(lock_file.read_text(encoding="utf-8"))
        assert info["purpose"] == "sqlite-transit-sync"
        assert info["pid"] > 0
    assert not lock_file.exists()


def test_single_flight_contention(tmp_path: Path):
    lock_file = tmp_path / "transfer-attempt.json"
    l1 = SingleFlightLock(lock_file, ttl_seconds=60)
    l2 = SingleFlightLock(lock_file, ttl_seconds=60)

    with l1:
        with pytest.raises(SingleFlightLockError):
            l2.acquire()


def test_single_flight_stale_recovery(tmp_path: Path):
    lock_file = tmp_path / "transfer-attempt.json"
    stale = {
        "machine_token": "host",
        "pid": 111,
        "session_token": "old",
        "started_at": time.time() - 400,
        "expires_at": time.time() - 10,
        "purpose": "test",
    }
    lock_file.write_text(json.dumps(stale), encoding="utf-8")

    l = SingleFlightLock(lock_file, ttl_seconds=60)
    with l:
        assert lock_file.exists()
        assert json.loads(lock_file.read_text(encoding="utf-8"))["session_token"] == l.session_token
    assert not lock_file.exists()
