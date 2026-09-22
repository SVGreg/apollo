# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from apollo.runtime.device_lock import DeviceExecutionLock
from apollo.runtime.device_pool import DevicePool, DeviceStatus

device_pool_module = importlib.import_module("apollo.runtime.device_pool")


@pytest.fixture(autouse=True)
def isolated_lock_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apollo.runtime.device_lock.get_temp_dir",
        lambda _name: tmp_path,
    )


@pytest.fixture(autouse=True)
def no_host_simulators(monkeypatch):
    """Keep the host's real simulators out of these enumeration-semantics tests."""
    monkeypatch.setattr("apollo.clients.simctl.simctl_available", lambda: True)


def test_device_pool_parse_lines():
    lines = [
        "List of devices attached",
        "sim-udid-1          device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64 device:emu64a",
        "9A123XYZ               device product:husky model:Pixel_8_Pro device:husky",
        "offline-dev            offline",
        "",
    ]
    parsed = DevicePool._parse_device_lines(lines)
    assert len(parsed) == 3
    assert parsed[0] == ("sim-udid-1", "device", "sdk gphone64 arm64", "sdk_gphone64_arm64")
    assert parsed[1] == ("9A123XYZ", "device", "Pixel 8 Pro", "husky")
    assert parsed[2] == ("offline-dev", "offline", None, None)


def test_device_pool_list_devices_and_busy_status(monkeypatch):
    pool = DevicePool()
    monkeypatch.setattr(
        pool,
        "_query_ios_devices_sync",
        lambda timeout=None: [
            ("sim-udid-1", "device", "Emulator", "sdk"),
            ("sim-udid-2", "device", "Pixel 8 Pro", "husky"),
        ],
    )

    # Initially neither is busy
    devs = pool.list_devices()
    assert len(devs) == 2
    assert not devs[0].is_busy
    assert not devs[1].is_busy

    # Acquire lock for sim-udid-1
    lock = DeviceExecutionLock("sim-udid-1", "test automation")
    lock.acquire()
    try:
        devs = pool.list_devices()
        emu = next(d for d in devs if d.serial == "sim-udid-1")
        pixel = next(d for d in devs if d.serial == "sim-udid-2")

        assert emu.is_busy is True
        assert emu.active_task_desc == "test automation"
        assert pixel.is_busy is False

        # Test idle device filtering
        idle = pool.get_idle_devices()
        assert len(idle) == 1
        assert idle[0].serial == "sim-udid-2"

        # Test select_device picks the idle device automatically
        selected = pool.select_device()
        assert selected == "sim-udid-2"

        # Test explicit selection returns requested device
        assert pool.select_device("sim-udid-1") == "sim-udid-1"
    finally:
        lock.release()


def test_get_claimed_serials_reflects_locks_and_reservations():
    pool = DevicePool()
    assert pool.get_claimed_serials() == set()

    lock = DeviceExecutionLock("sim-udid-1", "claimed by test")
    lock.acquire()
    bound_ticket = DeviceExecutionLock.reserve(
        description="queued task",
        device_id="sim-udid-2",
        session_id="queued-session",
    )
    unbound_ticket = DeviceExecutionLock.reserve(
        description="unbound task",
        device_id="pending",
        session_id="pending-session",
    )
    try:
        # Locked and reserved serials are claimed; the unbound placeholder is not.
        assert pool.get_claimed_serials() == {"sim-udid-1", "sim-udid-2"}
    finally:
        DeviceExecutionLock.cancel_reservation(bound_ticket)
        DeviceExecutionLock.cancel_reservation(unbound_ticket)
        lock.release()

    assert pool.get_claimed_serials() == set()


RAW_DEVICE = ("sim-udid-1", "device", "Emulator", "sdk")


def _install_fake_clock(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        device_pool_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
    )
    return clock


def test_enumeration_snapshot_collapses_repeat_queries(monkeypatch):
    pool = DevicePool()
    calls = {"count": 0}

    def fake_query(timeout=None):
        calls["count"] += 1
        return [RAW_DEVICE]

    monkeypatch.setattr(pool, "_query_ios_devices_sync", fake_query)

    first = pool.list_devices()
    second = pool.list_devices()
    assert calls["count"] == 1
    assert [d.serial for d in first] == [d.serial for d in second] == ["sim-udid-1"]


def test_enumeration_failure_serves_last_known_snapshot(monkeypatch):
    clock = _install_fake_clock(monkeypatch)
    pool = DevicePool()
    responses = iter([[RAW_DEVICE], None, None])
    monkeypatch.setattr(pool, "_query_ios_devices_sync", lambda timeout=None: next(responses))

    assert [d.serial for d in pool.list_devices()] == ["sim-udid-1"]

    # Past the fresh TTL but inside the stale-on-error window, a failed query
    # keeps answering with the last successful snapshot.
    clock["now"] += pool.CACHE_TTL + 1.0
    assert [d.serial for d in pool.list_devices()] == ["sim-udid-1"]

    # Once the stale window closes, persistent failure is reported honestly.
    clock["now"] += pool.STALE_ON_ERROR_TTL + 1.0
    assert pool.list_devices() == []


def test_query_timeout_widens_until_first_success(monkeypatch):
    pool = DevicePool()
    assert pool._current_query_timeout() == pool.COLD_QUERY_TIMEOUT
    monkeypatch.setattr(pool, "_query_ios_devices_sync", lambda timeout=None: [RAW_DEVICE])
    pool.list_devices()
    assert pool._current_query_timeout() == pool.HOT_QUERY_TIMEOUT


def test_async_enumeration_single_flight(monkeypatch):
    pool = DevicePool()
    calls = {"count": 0}

    async def fake_query(timeout=None):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return [RAW_DEVICE]

    monkeypatch.setattr(pool, "_query_ios_devices_async", fake_query)

    async def run():
        results = await asyncio.gather(
            pool.list_devices_async(),
            pool.list_devices_async(),
            pool.list_devices_async(),
        )
        return results

    results = asyncio.run(run())
    assert calls["count"] == 1
    for devices in results:
        assert [d.serial for d in devices] == ["sim-udid-1"]


def test_warm_up_waits_for_device_handshake(monkeypatch):
    pool = DevicePool()
    responses = iter([[], [("sim-udid-1", "shutdown", None, None)], [RAW_DEVICE]])

    async def fake_query(timeout=None):
        return next(responses)

    monkeypatch.setattr(pool, "_query_ios_devices_async", fake_query)

    warmed = asyncio.run(pool.warm_up_async(settle_timeout=2.0, poll_interval=0.01))
    assert warmed is True
    # The settled enumeration is cached for the first post-startup listings.
    assert pool._cached_raw == [RAW_DEVICE]


def test_warm_up_accepts_empty_enumeration_at_deadline(monkeypatch):
    pool = DevicePool()

    async def fake_query(timeout=None):
        return []

    monkeypatch.setattr(pool, "_query_ios_devices_async", fake_query)

    warmed = asyncio.run(pool.warm_up_async(settle_timeout=0.0))
    assert warmed is True
    assert pool._current_query_timeout() == pool.HOT_QUERY_TIMEOUT


def test_warm_up_without_simctl_returns_false(monkeypatch):
    pool = DevicePool()
    monkeypatch.setattr("apollo.clients.simctl.simctl_available", lambda: False)
    assert asyncio.run(pool.warm_up_async(settle_timeout=0.0)) is False


def test_try_list_devices_distinguishes_failure_from_empty(monkeypatch):
    pool = DevicePool()
    monkeypatch.setattr(pool, "_query_ios_devices_sync", lambda timeout=None: None)
    assert pool.try_list_devices() is None
    assert pool.list_devices() == []

    fresh_pool = DevicePool()
    monkeypatch.setattr(fresh_pool, "_query_ios_devices_sync", lambda timeout=None: [])
    assert fresh_pool.try_list_devices() == []


def test_validate_explicit_serial_fails_open_on_indeterminate_enumeration(monkeypatch):
    pool = DevicePool()
    monkeypatch.setattr(pool, "_query_ios_devices_sync", lambda timeout=None: None)
    assert pool.validate_explicit_serial("pixel-10") is None

    empty_pool = DevicePool()
    monkeypatch.setattr(empty_pool, "_query_ios_devices_sync", lambda timeout=None: [])
    assert empty_pool.validate_explicit_serial("pixel-10") is None


def test_validate_explicit_serial_rejects_only_on_authoritative_enumeration(monkeypatch):
    pool = DevicePool()
    monkeypatch.setattr(
        pool,
        "_query_ios_devices_sync",
        lambda timeout=None: [
            ("pixel-10", "device", None, None),
            ("pixel-11", "unauthorized", None, None),
        ],
    )

    assert pool.validate_explicit_serial("pixel-10") is None
    assert "not ready" in pool.validate_explicit_serial("pixel-11")
    missing = pool.validate_explicit_serial("pixel-12")
    assert "not connected" in missing
    assert "pixel-10" in missing


def test_validate_explicit_serial_async_matches_sync(monkeypatch):
    pool = DevicePool()

    async def fake_query(timeout=None):
        return [("pixel-10", "device", None, None)]

    monkeypatch.setattr(pool, "_query_ios_devices_async", fake_query)

    async def run():
        return (
            await pool.validate_explicit_serial_async("pixel-10"),
            await pool.validate_explicit_serial_async("pixel-12"),
        )

    ok, missing = asyncio.run(run())
    assert ok is None
    assert "not connected" in missing


def test_ios_rows_maps_simulators_to_pool_rows():
    """Booted simulators must map to the "device" state the pool selects on.

    Pinned because every other test here stubs the query out: a bound-method slip
    in `_ios_rows` empties the pool and nothing but a live run notices.
    """
    from types import SimpleNamespace

    from apollo.runtime.device_pool import DevicePool

    devices = [
        SimpleNamespace(
            udid="udid-booted",
            name="iPhone 17 Pro",
            os_version="26.2",
            state="Booted",
            is_booted=True,
        ),
        SimpleNamespace(
            udid="udid-off",
            name="iPhone Air",
            os_version="26.5",
            state="Shutdown",
            is_booted=False,
        ),
    ]
    assert DevicePool._ios_rows(devices) == [
        ("udid-booted", "device", "iPhone 17 Pro", "simulator iOS 26.2"),
        ("udid-off", "shutdown", "iPhone Air", "simulator iOS 26.5"),
    ]
