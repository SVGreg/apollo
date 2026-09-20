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

"""Device Pool Manager for discovering, tracking, and allocating mobile devices."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from apollo.runtime.device_lock import DeviceExecutionLock
from apollo.toolchain import toolchain
from apollo.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DeviceStatus:
    """State and lock allocation metadata for a connected device."""

    serial: str
    state: str  # "device", "offline", "unauthorized", etc.
    model: str | None = None
    product: str | None = None
    is_emulator: bool = False
    is_busy: bool = False
    active_pid: int | None = None
    active_task_desc: str | None = None
    active_session_id: str | None = None
    acquired_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "state": self.state,
            "model": self.model,
            "product": self.product,
            "is_emulator": self.is_emulator,
            "is_busy": self.is_busy,
            "active_pid": self.active_pid,
            "active_task_desc": self.active_task_desc,
            "active_session_id": self.active_session_id,
            "acquired_at": self.acquired_at,
        }


class DevicePool:
    """Manages discovery and assignment across all connected Android devices."""

    # A snapshot younger than this is returned without touching adb, so a burst
    # of concurrent enumerations (UI polling, readiness probes, submissions)
    # collapses into a single `adb devices` call.
    CACHE_TTL = 1.0
    # When enumeration fails outright (adb server restarting, subprocess error),
    # the last successful snapshot keeps answering for this long. Real
    # disconnects are not failures -- adb reports them as a successful listing
    # without the device -- so serving stale here only bridges server-level blips.
    STALE_ON_ERROR_TTL = 10.0
    # Until one enumeration has succeeded, `adb devices` may need to spawn the
    # adb server itself, which routinely exceeds the hot-path budget.
    HOT_QUERY_TIMEOUT = 2.0
    COLD_QUERY_TIMEOUT = 8.0

    def __init__(self, adb_path: str | None = None):
        self._adb_path = adb_path
        self._cache_lock = threading.Lock()
        self._cached_raw: list[tuple[str, str, str | None, str | None]] | None = None
        self._cached_at = 0.0
        self._warmed = False
        self._sync_query_gate = threading.Lock()
        self._async_inflight: tuple[asyncio.AbstractEventLoop, asyncio.Task] | None = None

    def _resolve_adb(self) -> str | None:
        if self._adb_path:
            return self._adb_path
        try:
            return toolchain.resolve("adb") or shutil.which("adb")
        except Exception:
            return shutil.which("adb")

    def _current_query_timeout(self) -> float:
        return self.HOT_QUERY_TIMEOUT if self._warmed else self.COLD_QUERY_TIMEOUT

    def _query_adb_devices_sync(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        """Run `adb devices -l` synchronously. Returns None when the query
        itself failed, as opposed to an empty list of attached devices."""
        adb = self._resolve_adb()
        if not adb:
            return None
        try:
            res = subprocess.run(
                [adb, "devices", "-l"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self._current_query_timeout(),
                check=False,
            )
            if res.returncode != 0:
                return None
            return self._parse_device_lines(res.stdout.splitlines())
        except Exception as exc:
            logger.debug(f"Error querying adb devices: {exc}")
            return None

    async def _query_adb_devices_async(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        """Run `adb devices -l` asynchronously. Returns None when the query
        itself failed, as opposed to an empty list of attached devices."""
        adb = self._resolve_adb()
        if not adb:
            return None
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                adb,
                "devices",
                "-l",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout if timeout is not None else self._current_query_timeout(),
            )
            if proc.returncode != 0:
                return None
            return self._parse_device_lines(stdout.decode(errors="replace").splitlines())
        except Exception as exc:
            logger.debug(f"Error querying adb devices asynchronously: {exc}")
            if proc is not None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    # Process already exited; nothing left to clean up.
                    pass
            return None

    # ------------------------------------------------------------------ iOS
    # Simulators are enumerated with `xcrun simctl list -j`; booted ones map to
    # the adb "device" state so the rest of the pool (locks, selection, UI)
    # works unchanged. Shutdown simulators are listed as "shutdown" so callers
    # can offer to boot them.

    @staticmethod
    def _ios_rows(devices: list[Any]) -> list[tuple[str, str, str | None, str | None]]:
        rows: list[tuple[str, str, str | None, str | None]] = []
        for dev in devices:
            state = "device" if dev.is_booted else dev.state.lower()
            rows.append((dev.udid, state, dev.name, f"simulator iOS {dev.os_version}"))
        return rows

    def _query_ios_devices_sync(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        try:
            from apollo.clients import simctl

            if not simctl.simctl_available():
                return None
            return self._ios_rows(
                simctl.list_devices_sync(
                    timeout=timeout if timeout is not None else self._current_query_timeout()
                )
            )
        except Exception as exc:
            logger.debug(f"Error querying simulators: {exc}")
            return None

    async def _query_ios_devices_async(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        try:
            from apollo.clients import simctl

            if not simctl.simctl_available():
                return None
            devices = await asyncio.wait_for(
                simctl.SimBridge.list_devices(),
                timeout=timeout if timeout is not None else self._current_query_timeout(),
            )
            return self._ios_rows(devices)
        except Exception as exc:
            logger.debug(f"Error querying simulators asynchronously: {exc}")
            return None

    def _query_devices_sync(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        """iOS simulators first, then any adb devices; None only if both queries failed."""
        ios = self._query_ios_devices_sync(timeout)
        android = (
            self._query_adb_devices_sync()
            if timeout is None
            else self._query_adb_devices_sync(timeout)
        )
        if ios is None and android is None:
            return None
        return (ios or []) + (android or [])

    async def _query_devices_async(
        self, timeout: float | None = None
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        ios = await self._query_ios_devices_async(timeout)
        android = (
            await self._query_adb_devices_async()
            if timeout is None
            else await self._query_adb_devices_async(timeout)
        )
        if ios is None and android is None:
            return None
        return (ios or []) + (android or [])

    @staticmethod
    def _parse_device_lines(lines: list[str]) -> list[tuple[str, str, str | None, str | None]]:
        results: list[tuple[str, str, str | None, str | None]] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            state = parts[1]
            model = None
            product = None
            for token in parts[2:]:
                if token.startswith("model:"):
                    model = token.split(":", 1)[1].replace("_", " ")
                elif token.startswith("product:"):
                    product = token.split(":", 1)[1]
            results.append((serial, state, model, product))
        return results

    def _cached_snapshot(
        self, *, allow_stale: bool
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        with self._cache_lock:
            if self._cached_raw is None:
                return None
            age = time.monotonic() - self._cached_at
            if age <= self.CACHE_TTL or (allow_stale and age <= self.STALE_ON_ERROR_TTL):
                return list(self._cached_raw)
        return None

    def _store_snapshot(self, raw: list[tuple[str, str, str | None, str | None]]) -> None:
        with self._cache_lock:
            self._cached_raw = list(raw)
            self._cached_at = time.monotonic()
            self._warmed = True

    def _enumerate_sync(self) -> list[tuple[str, str, str | None, str | None]] | None:
        """Return the raw enumeration, or None when the query failed and no
        usable snapshot exists -- never an ambiguous empty list on failure."""
        cached = self._cached_snapshot(allow_stale=False)
        if cached is not None:
            return cached
        # The gate serializes concurrent enumerations: followers block until the
        # leader finishes, then hit the snapshot it just stored.
        with self._sync_query_gate:
            cached = self._cached_snapshot(allow_stale=False)
            if cached is not None:
                return cached
            raw = self._query_devices_sync()
            if raw is None:
                return self._cached_snapshot(allow_stale=True)
            self._store_snapshot(raw)
            return raw

    async def _enumerate_async(self) -> list[tuple[str, str, str | None, str | None]] | None:
        cached = self._cached_snapshot(allow_stale=False)
        if cached is not None:
            return cached
        loop = asyncio.get_running_loop()
        inflight = self._async_inflight
        if inflight is not None and inflight[0] is loop and not inflight[1].done():
            # Shield followers so one cancelled waiter cannot abort the shared query.
            return await asyncio.shield(inflight[1])
        task = loop.create_task(self._enumerate_async_uncached())
        self._async_inflight = (loop, task)
        try:
            return await task
        finally:
            if self._async_inflight is not None and self._async_inflight[1] is task:
                self._async_inflight = None

    async def _enumerate_async_uncached(
        self,
    ) -> list[tuple[str, str, str | None, str | None]] | None:
        raw = await self._query_devices_async()
        if raw is None:
            return self._cached_snapshot(allow_stale=True)
        self._store_snapshot(raw)
        return raw

    async def _start_adb_server(self, timeout: float) -> None:
        """Best-effort bounded `adb start-server` so later queries hit a warm daemon."""
        adb = self._resolve_adb()
        if not adb:
            return
        proc = None
        try:
            clean_env = os.environ.copy()
            clean_env.pop("ADB_SERVER_SOCKET", None)
            proc = await asyncio.create_subprocess_exec(
                adb,
                "start-server",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_env,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except Exception as exc:
            logger.debug(f"adb start-server warm-up did not complete: {exc}")
            if proc is not None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    # Process already exited; nothing left to clean up.
                    pass

    async def warm_up_async(
        self,
        *,
        server_timeout: float = 10.0,
        settle_timeout: float = 3.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Start the adb server and complete one successful enumeration.

        Meant to run once before an entrypoint starts accepting task
        submissions, so the first requests never race an adb cold start.
        Devices reconnect asynchronously after the server comes up, so the
        settle window keeps polling until at least one device reaches the
        ready state (or the window closes). Returns True once any enumeration
        succeeded -- zero attached devices is still a warm pool.
        """
        from apollo.clients import simctl

        if self._resolve_adb() is None and not simctl.simctl_available():
            return False
        if self._resolve_adb() is not None:
            await self._start_adb_server(timeout=server_timeout)
        deadline = time.monotonic() + max(settle_timeout, 0.0)
        succeeded = False
        while True:
            raw = await self._query_devices_async()
            if raw is not None:
                succeeded = True
                self._store_snapshot(raw)
                if any(state == "device" for _, state, _, _ in raw):
                    return True
            if time.monotonic() >= deadline:
                return succeeded
            await asyncio.sleep(poll_interval)

    def _build_statuses(
        self, raw_devices: list[tuple[str, str, str | None, str | None]]
    ) -> list[DeviceStatus]:
        active_owners = DeviceExecutionLock.get_active_owners()

        devices: list[DeviceStatus] = []
        for serial, state, model, product in raw_devices:
            is_emu = (
                serial.startswith("emulator-")
                or "127.0.0.1" in serial
                or "localhost" in serial
                or (product or "").startswith("simulator")
            )
            clean_id = DeviceExecutionLock._normalize_lock_id(
                serial,
                os.getenv(DeviceExecutionLock.LOCK_SCOPE_ENV) or None,
            )
            owner = active_owners.get(clean_id) or active_owners.get(
                DeviceExecutionLock._normalize_device_id(serial)
            )

            status = DeviceStatus(
                serial=serial,
                state=state,
                model=model,
                product=product,
                is_emulator=is_emu,
                is_busy=owner is not None,
                active_pid=owner.pid if owner else None,
                active_task_desc=owner.description if owner else None,
                active_session_id=owner.session_id if owner else None,
                acquired_at=owner.acquired_at if owner else None,
            )
            devices.append(status)
        return devices

    def list_devices(self) -> list[DeviceStatus]:
        """Synchronously list all connected devices along with their active lock state.

        The raw adb enumeration may be served from a short-lived snapshot;
        lock ownership is always computed fresh. A failed enumeration collapses
        to an empty list -- use try_list_devices when the caller must tell the
        two apart.
        """
        return self._build_statuses(self._enumerate_sync() or [])

    async def list_devices_async(self) -> list[DeviceStatus]:
        """Asynchronously list all connected devices along with their active lock state.

        The raw adb enumeration may be served from a short-lived snapshot;
        lock ownership is always computed fresh. A failed enumeration collapses
        to an empty list -- use try_list_devices_async when the caller must tell
        the two apart.
        """
        return self._build_statuses(await self._enumerate_async() or [])

    def try_list_devices(self) -> list[DeviceStatus] | None:
        """Like list_devices, but returns None when enumeration failed and no
        usable snapshot exists, so callers can distinguish "could not ask adb"
        from "adb answered: no devices attached"."""
        raw = self._enumerate_sync()
        return None if raw is None else self._build_statuses(raw)

    async def try_list_devices_async(self) -> list[DeviceStatus] | None:
        """Async variant of try_list_devices."""
        raw = await self._enumerate_async()
        return None if raw is None else self._build_statuses(raw)

    @staticmethod
    def _explicit_serial_error(
        requested_serial: str, devices: list[DeviceStatus] | None
    ) -> str | None:
        # Fail open on an indeterminate or empty enumeration (adb missing, server
        # blip, devices still handshaking): the submission proceeds and fails
        # downstream with a clear no-device error instead of a false hard reject.
        if not devices:
            return None
        norm = DeviceExecutionLock._normalize_device_id
        state_by_serial = {norm(d.serial): d.state for d in devices}
        dev_state = state_by_serial.get(norm(requested_serial))
        if dev_state == "device":
            return None
        if dev_state is None:
            return (
                f"Device '{requested_serial}' is not connected. "
                f"Attached devices: {sorted(state_by_serial)}."
            )
        return f"Device '{requested_serial}' is attached but not ready (state: '{dev_state}')."

    def validate_explicit_serial(self, requested_serial: str) -> str | None:
        """Return a rejection message for an explicitly requested serial, or None.

        Only a successful, non-empty enumeration may reject: it is the single
        authority for the strict device-binding check shared by the admission
        paths (admin console router/queue and the MCP task runner).
        """
        return self._explicit_serial_error(requested_serial, self.try_list_devices())

    async def validate_explicit_serial_async(self, requested_serial: str) -> str | None:
        """Async variant of validate_explicit_serial."""
        return self._explicit_serial_error(requested_serial, await self.try_list_devices_async())

    def get_ready_devices(self) -> list[DeviceStatus]:
        """Return devices in authorized 'device' state."""
        return [d for d in self.list_devices() if d.state == "device"]

    def get_idle_devices(self) -> list[DeviceStatus]:
        """Return ready devices that are not currently holding an execution lock."""
        return [d for d in self.list_devices() if d.state == "device" and not d.is_busy]

    def get_claimed_serials(self) -> set[str]:
        """Return device serials Apollo currently claims on the ADB server.

        A device is claimed while any Apollo process holds its execution lock
        or has a live pending queue reservation targeting it. Placeholder
        reservations not yet bound to a concrete device ("pending"/"any")
        claim nothing. Read-only: computed purely from cross-process lock and
        queue metadata, without any adb traffic.
        """
        claimed: set[str] = set()
        try:
            for owner in DeviceExecutionLock.get_active_owners().values():
                if owner.device_id:
                    claimed.add(str(owner.device_id))
            for item in DeviceExecutionLock.get_queued_tasks():
                serial = item.get("device_serial")
                if serial:
                    claimed.add(str(serial))
        except Exception as exc:
            logger.debug(f"Could not compute claimed device serials: {exc}")
        claimed.discard("pending")
        claimed.discard("any")
        return claimed

    def select_device(self, preferred_serial: str | None = None) -> str | None:
        """Select a target device serial for task execution.

        If `preferred_serial` is provided:
            Returns preferred_serial if it is present or online.
        Otherwise:
            Selects the first idle/unlocked ready device. If all are busy,
            selects the first ready device so the task will queue on it.
            Returns None if no devices are attached.
        """
        return self._pick_device(self.list_devices(), preferred_serial)

    async def select_device_async(self, preferred_serial: str | None = None) -> str | None:
        """Select a device without blocking the caller on ADB enumeration."""
        return self._pick_device(await self.list_devices_async(), preferred_serial)

    def _pick_device(
        self, all_devs: list[DeviceStatus], preferred_serial: str | None
    ) -> str | None:
        ready_devs = [d for d in all_devs if d.state == "device"]

        if preferred_serial:
            # Check if preferred is available or exists
            for dev in all_devs:
                if dev.serial == preferred_serial:
                    return dev.serial
            # If not detected by ADB, still return it so ADB can attempt connection
            return preferred_serial

        # Pick first idle device
        for dev in ready_devs:
            if not dev.is_busy:
                return dev.serial

        # If all busy, return the first ready device (it will queue)
        if ready_devs:
            return ready_devs[0].serial

        # Fallback to any attached device if none ready
        if all_devs:
            return all_devs[0].serial

        return None


# Global device pool instance
device_pool = DevicePool()
