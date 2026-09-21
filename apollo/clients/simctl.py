"""`xcrun simctl` bridge for iOS Simulators (the simulator counterpart of adb).

Every call shells out to ``xcrun simctl`` and parses its JSON/plist output.
Sync variants exist for the device pool and CLI status paths that run outside
an event loop; the driver uses the async ones.
"""

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apollo.utils.logger import get_logger

logger = get_logger(__name__)

WDA_RUNNER_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"

# Env vars simctl forwards to the launched process when prefixed with SIMCTL_CHILD_.
SIMCTL_CHILD_PREFIX = "SIMCTL_CHILD_"


class SimctlError(RuntimeError):
    """Raised when a simctl command fails."""


@dataclass
class SimDevice:
    udid: str
    name: str
    state: str  # "Booted" | "Shutdown" | "Booting" | ...
    runtime: str  # e.g. "com.apple.CoreSimulator.SimRuntime.iOS-26-2"
    is_available: bool = True
    device_type: str | None = None

    @property
    def os_version(self) -> str:
        tail = self.runtime.rsplit(".", 1)[-1]  # "iOS-26-2"
        parts = tail.split("-")
        return ".".join(parts[1:]) if len(parts) > 1 else tail

    @property
    def platform_family(self) -> str:
        return self.runtime.rsplit(".", 1)[-1].split("-")[0]  # "iOS" | "watchOS" | ...

    @property
    def is_booted(self) -> bool:
        return self.state == "Booted"


@dataclass
class SimApp:
    bundle_id: str
    display_name: str
    app_type: str | None = None  # "System" | "User"
    path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def find_xcrun() -> str | None:
    return shutil.which("xcrun")


def simctl_available() -> bool:
    return find_xcrun() is not None


def _run_sync(args: list[str], *, timeout: float = 60.0, env: dict[str, str] | None = None) -> str:
    xcrun = find_xcrun()
    if xcrun is None:
        raise SimctlError("xcrun not found; install Xcode and its Command Line Tools")
    res = subprocess.run(
        [xcrun, "simctl", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if res.returncode != 0:
        raise SimctlError(
            f"simctl {' '.join(args)} failed ({res.returncode}): {res.stderr.strip()}"
        )
    return res.stdout


async def _run(args: list[str], *, timeout: float = 60.0, env: dict[str, str] | None = None) -> str:
    xcrun = find_xcrun()
    if xcrun is None:
        raise SimctlError("xcrun not found; install Xcode and its Command Line Tools")
    proc = await asyncio.create_subprocess_exec(
        xcrun,
        "simctl",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise SimctlError(f"simctl {' '.join(args)} timed out after {timeout}s") from None
    except asyncio.CancelledError:
        # A cancelled caller must not leave simctl running (it would block loop shutdown).
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    if proc.returncode != 0:
        raise SimctlError(
            f"simctl {' '.join(args)} failed ({proc.returncode}): {err.decode(errors='replace').strip()}"
        )
    return out.decode(errors="replace")


def _parse_device_list(raw_json: str, *, ios_only: bool = True) -> list[SimDevice]:
    data = json.loads(raw_json)
    devices: list[SimDevice] = []
    for runtime, entries in (data.get("devices") or {}).items():
        for entry in entries:
            dev = SimDevice(
                udid=entry.get("udid", ""),
                name=entry.get("name", ""),
                state=entry.get("state", ""),
                runtime=runtime,
                is_available=bool(entry.get("isAvailable", True)),
                device_type=entry.get("deviceTypeIdentifier"),
            )
            if ios_only and dev.platform_family != "iOS":
                continue
            devices.append(dev)
    return devices


def _parse_listapps(raw_plist: str) -> list[SimApp]:
    """``simctl listapps`` prints an old-style plist; plutil converts it to JSON."""
    res = subprocess.run(
        ["plutil", "-convert", "json", "-o", "-", "-"],
        input=raw_plist,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise SimctlError(f"plutil failed: {res.stderr.strip()}")
    data = json.loads(res.stdout)
    apps: list[SimApp] = []
    for bundle_id, info in data.items():
        apps.append(
            SimApp(
                bundle_id=bundle_id,
                display_name=info.get("CFBundleDisplayName")
                or info.get("CFBundleName")
                or bundle_id,
                app_type=info.get("ApplicationType"),
                path=info.get("Path"),
                raw=info,
            )
        )
    return apps


# --------------------------------------------------------------------------- sync API


def list_devices_sync(*, booted_only: bool = False, timeout: float = 60.0) -> list[SimDevice]:
    args = ["list", "devices", "-j"]
    if booted_only:
        args.append("booted")
    devices = _parse_device_list(_run_sync(args, timeout=timeout))
    return [d for d in devices if d.is_available]


def list_apps_sync(udid: str) -> list[SimApp]:
    return _parse_listapps(_run_sync(["listapps", udid]))


# --------------------------------------------------------------------------- async API


class SimBridge:
    """Async simctl operations for one simulator."""

    def __init__(self, udid: str):
        self.udid = udid

    @staticmethod
    async def list_devices(*, booted_only: bool = False) -> list[SimDevice]:
        args = ["list", "devices", "-j"]
        if booted_only:
            args.append("booted")
        devices = _parse_device_list(await _run(args, timeout=60.0))
        return [d for d in devices if d.is_available]

    async def get_device(self) -> SimDevice | None:
        for dev in await self.list_devices():
            if dev.udid == self.udid:
                return dev
        return None

    async def boot(self, *, wait: bool = True, timeout: float = 120.0) -> None:
        try:
            await _run(["boot", self.udid], timeout=timeout)
        except SimctlError as exc:
            # "Unable to boot device in current state: Booted" is not an error for us.
            if "current state: Booted" not in str(exc):
                raise
        if wait:
            await _run(["bootstatus", self.udid, "-b"], timeout=timeout)

    async def shutdown(self) -> None:
        try:
            await _run(["shutdown", self.udid], timeout=60.0)
        except SimctlError as exc:
            if "current state: Shutdown" not in str(exc):
                raise

    async def install(self, app_path: str | Path) -> None:
        await _run(["install", self.udid, str(app_path)], timeout=120.0)

    async def uninstall(self, bundle_id: str) -> None:
        await _run(["uninstall", self.udid, bundle_id], timeout=60.0)

    async def launch(
        self,
        bundle_id: str,
        *,
        child_env: dict[str, str] | None = None,
        terminate_running: bool = False,
    ) -> int | None:
        """Launch an app; returns its pid when simctl reports one.

        ``child_env`` entries are forwarded to the app with the SIMCTL_CHILD_ prefix
        (this is how WDA gets USE_PORT / MJPEG_SERVER_PORT).
        """
        env = os.environ.copy()
        for key, value in (child_env or {}).items():
            env[f"{SIMCTL_CHILD_PREFIX}{key}"] = value
        args = ["launch"]
        if terminate_running:
            args.append("--terminate-running-process")
        args += [self.udid, bundle_id]
        out = await _run(args, timeout=60.0, env=env)
        # "<bundle>: <pid>"
        tail = out.strip().rsplit(":", 1)[-1].strip()
        return int(tail) if tail.isdigit() else None

    async def terminate(self, bundle_id: str) -> bool:
        try:
            await _run(["terminate", self.udid, bundle_id], timeout=30.0)
            return True
        except SimctlError as exc:
            logger.debug(f"simctl terminate {bundle_id}: {exc}")
            return False

    async def list_apps(self) -> list[SimApp]:
        raw = await _run(["listapps", self.udid], timeout=30.0)
        return await asyncio.to_thread(_parse_listapps, raw)

    async def is_installed(self, bundle_id: str) -> bool:
        return any(app.bundle_id == bundle_id for app in await self.list_apps())

    async def open_url(self, url: str) -> None:
        await _run(["openurl", self.udid, url], timeout=30.0)

    async def screenshot(self) -> bytes:
        """PNG screenshot in native pixels via `io screenshot` (simctl cannot write to stdout)."""
        fd, tmp = tempfile.mkstemp(prefix="apollo-sim-", suffix=".png")
        os.close(fd)
        try:
            await _run(["io", self.udid, "screenshot", "--type=png", tmp], timeout=30.0)
            return await asyncio.to_thread(Path(tmp).read_bytes)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def pbcopy(self, text: str) -> None:
        xcrun = find_xcrun()
        if xcrun is None:
            raise SimctlError("xcrun not found")
        proc = await asyncio.create_subprocess_exec(
            xcrun,
            "simctl",
            "pbcopy",
            self.udid,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(text.encode()), timeout=30.0)
        if proc.returncode != 0:
            raise SimctlError(f"simctl pbcopy failed: {err.decode(errors='replace').strip()}")

    async def privacy_grant(self, service: str, bundle_id: str) -> None:
        await _run(["privacy", self.udid, "grant", service, bundle_id], timeout=30.0)

    async def run(self, args: list[str], *, timeout: float = 60.0) -> str:
        """Run an arbitrary simctl subcommand against this device (callers allowlist)."""
        return await _run([*args], timeout=timeout)
