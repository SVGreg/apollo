"""go-ios (`ios`) wrapper for physical iPhones over USB — the device counterpart of `simctl`.

Phase 3 groundwork (see `docs/spikes.md` S4): device discovery, info, apps, install /
launch / kill, screenshot, Developer Mode, the iOS 17+ userspace tunnel agent, port
forwarding and `runwda`. Everything that touches an iOS 17+ device goes through the
tunnel, so every call carries ``--tunnel-info-port`` pointing at the agent this module
starts (go-ios's CLI default, 28100, does not match a tunnel started with
``ios tunnel start --userspace``).

Signing WDA for a device is deliberately not here: it is either ``xcodebuild`` with a
free team (RunnerManager, Phase 3) or ``ios sign app`` with a P12 + profile.
"""

import asyncio
import contextlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from apollo.utils.logger import get_logger

logger = get_logger(__name__)

TUNNEL_INFO_PORT = 60105  # what `ios tunnel start --userspace` serves its info API on
TUNNEL_INFO_URL = f"http://127.0.0.1:{TUNNEL_INFO_PORT}"


class GoIosError(RuntimeError):
    """A go-ios command failed, timed out, or the CLI is missing."""


@dataclass
class IosDevice:
    udid: str
    name: str = ""
    product_type: str = ""
    os_version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_iphone(self) -> bool:
        return self.product_type.startswith("iPhone") or "iPhone" in self.name


def find_ios() -> str | None:
    return shutil.which("ios")


def goios_available() -> bool:
    return find_ios() is not None


def _base_args(udid: str | None, *, tunnel: bool = True) -> list[str]:
    args: list[str] = []
    if udid:
        args.append(f"--udid={udid}")
    if tunnel:
        args.append(f"--tunnel-info-port={TUNNEL_INFO_PORT}")
    return args


def _parse_json(raw: str) -> Any:
    """go-ios prints one JSON document per line; the last complete one is the result."""
    text = raw.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                with contextlib.suppress(json.JSONDecodeError):
                    return json.loads(line)
    return {"raw": text}


def _run_sync(args: list[str], *, timeout: float = 30.0) -> str:
    ios = find_ios()
    if ios is None:
        raise GoIosError("go-ios not found; `brew install go-ios` (or `npm i -g go-ios`)")
    res = subprocess.run(
        [ios, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if res.returncode != 0:
        raise GoIosError(
            f"ios {' '.join(args)} failed ({res.returncode}): {res.stderr.strip()[:400]}"
        )
    return res.stdout


async def _run(args: list[str], *, timeout: float = 30.0) -> str:
    ios = find_ios()
    if ios is None:
        raise GoIosError("go-ios not found; `brew install go-ios` (or `npm i -g go-ios`)")
    proc = await asyncio.create_subprocess_exec(
        ios,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise GoIosError(f"ios {' '.join(args)} timed out after {timeout}s") from None
    except asyncio.CancelledError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    if proc.returncode != 0:
        raise GoIosError(
            f"ios {' '.join(args)} failed ({proc.returncode}): "
            f"{err.decode(errors='replace').strip()[:400]}"
        )
    return out.decode(errors="replace")


def parse_device_list(raw: str) -> list[IosDevice]:
    """`ios list [--details]` → devices. Without --details the entries are bare UDIDs."""
    payload = _parse_json(raw)
    entries = payload.get("deviceList", []) if isinstance(payload, dict) else payload
    devices: list[IosDevice] = []
    for entry in entries or []:
        if isinstance(entry, str):
            devices.append(IosDevice(udid=entry))
            continue
        if not isinstance(entry, dict):
            continue
        devices.append(
            IosDevice(
                udid=str(entry.get("Udid") or entry.get("udid") or ""),
                name=str(entry.get("DeviceName") or entry.get("ProductName") or ""),
                product_type=str(entry.get("ProductType") or ""),
                os_version=str(entry.get("ProductVersion") or ""),
                raw=entry,
            )
        )
    return [d for d in devices if d.udid]


def list_devices_sync(*, timeout: float = 15.0) -> list[IosDevice]:
    """USB-connected devices (no tunnel needed)."""
    return parse_device_list(_run_sync(["list", "--details"], timeout=timeout))


def version_sync() -> str | None:
    try:
        payload = _parse_json(_run_sync(["version"], timeout=10.0))
    except (GoIosError, subprocess.TimeoutExpired):
        return None
    return str(payload.get("version")) if isinstance(payload, dict) else None


class TunnelAgent:
    """Supervises `ios tunnel start --userspace` (iOS 17+; no sudo) and its info API."""

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None

    @staticmethod
    async def tunnels(*, timeout: float = 2.0) -> list[dict[str, Any]]:
        """Tunnels the agent currently holds; [] when the agent is not running."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(TUNNEL_INFO_URL + "/tunnels")
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        return (
            data
            if isinstance(data, list)
            else list(data.values())
            if isinstance(data, dict)
            else []
        )

    @classmethod
    async def is_running(cls) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                return (await client.get(TUNNEL_INFO_URL + "/tunnels")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure(self, udid: str, *, timeout: float = 30.0) -> dict[str, Any]:
        """Start the agent if needed and wait until it lists a tunnel for ``udid``."""
        if not await self.is_running():
            ios = find_ios()
            if ios is None:
                raise GoIosError("go-ios not found; cannot start the tunnel agent")
            logger.info("Starting go-ios userspace tunnel agent…")
            self._process = await asyncio.create_subprocess_exec(
                ios,
                "tunnel",
                "start",
                "--userspace",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for tunnel in await self.tunnels():
                if str(tunnel.get("udid") or tunnel.get("Udid")) == udid:
                    return tunnel
            if self._process is not None and self._process.returncode is not None:
                err = (
                    (await self._process.stderr.read()).decode(errors="replace")
                    if self._process.stderr
                    else ""
                )
                raise GoIosError(
                    f"tunnel agent exited ({self._process.returncode}): {err.strip()[:400]}"
                )
            await asyncio.sleep(0.5)
        raise GoIosError(
            f"No tunnel for {udid} within {timeout:.0f}s (is the device unlocked and trusted?)"
        )

    async def stop(self) -> None:
        proc, self._process = self._process, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=5.0)


class DeviceBridge:
    """One physical device, addressed by UDID, through go-ios."""

    def __init__(self, udid: str):
        self.udid = udid
        self._forwards: list[asyncio.subprocess.Process] = []
        self._wda: asyncio.subprocess.Process | None = None

    async def info(self) -> dict[str, Any]:
        payload = _parse_json(
            await _run(["info", *_base_args(self.udid, tunnel=False)], timeout=15.0)
        )
        return payload if isinstance(payload, dict) else {}

    async def developer_mode_enabled(self) -> bool | None:
        try:
            payload = _parse_json(
                await _run(["devmode", "get", *_base_args(self.udid)], timeout=15.0)
            )
        except GoIosError as exc:
            logger.debug(f"devmode get failed: {exc}")
            return None
        if isinstance(payload, dict):
            for key in ("DeveloperModeEnabled", "enabled", "developerModeEnabled"):
                if key in payload:
                    return bool(payload[key])
        return None

    async def apps(self) -> list[dict[str, Any]]:
        payload = _parse_json(
            await _run(["apps", "--list", *_base_args(self.udid, tunnel=False)], timeout=30.0)
        )
        if isinstance(payload, list):
            return [a for a in payload if isinstance(a, dict)]
        if isinstance(payload, dict):
            return [a for a in payload.get("apps", payload.get("raw", [])) if isinstance(a, dict)]
        return []

    async def is_installed(self, bundle_id: str) -> bool:
        return any(
            (a.get("CFBundleIdentifier") or a.get("bundleId") or a.get("BundleID")) == bundle_id
            for a in await self.apps()
        )

    async def install(self, app_path: str | Path) -> None:
        await _run(["install", f"--path={app_path}", *_base_args(self.udid)], timeout=300.0)

    async def launch(self, bundle_id: str, *, kill_existing: bool = False) -> None:
        args = ["launch", bundle_id, *_base_args(self.udid)]
        if kill_existing:
            args.insert(2, "--kill-existing")
        await _run(args, timeout=30.0)

    async def kill(self, bundle_id: str) -> bool:
        try:
            await _run(["kill", bundle_id, *_base_args(self.udid)], timeout=15.0)
            return True
        except GoIosError as exc:
            logger.debug(f"kill {bundle_id} failed: {exc}")
            return False

    async def screenshot(self) -> bytes:
        """PNG via the instruments service (Developer Mode + tunnel required; ~2 s)."""
        with tempfile.TemporaryDirectory(prefix="apollo-shot-") as tmp:
            out = Path(tmp) / "screen.png"
            await _run(["screenshot", f"--output={out}", *_base_args(self.udid)], timeout=30.0)
            return out.read_bytes()

    async def forward(self, host_port: int, device_port: int) -> asyncio.subprocess.Process:
        """`ios forward` stays alive for the mapping's lifetime; returns the process."""
        ios = find_ios()
        if ios is None:
            raise GoIosError("go-ios not found")
        proc = await asyncio.create_subprocess_exec(
            ios,
            "forward",
            str(host_port),
            str(device_port),
            *_base_args(self.udid),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(0.3)
        if proc.returncode is not None:
            err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
            raise GoIosError(f"ios forward {host_port}->{device_port} exited: {err.strip()[:300]}")
        self._forwards.append(proc)
        return proc

    async def run_wda(
        self,
        *,
        bundle_id: str,
        test_runner_bundle_id: str,
        xctest_config: str = "WebDriverAgentRunner.xctest",
        env: dict[str, str] | None = None,
        log_output: Path | None = None,
    ) -> asyncio.subprocess.Process:
        """`ios runwda` keeps WDA alive while it runs; returns the supervising process."""
        ios = find_ios()
        if ios is None:
            raise GoIosError("go-ios not found")
        args = [
            "runwda",
            f"--bundleid={bundle_id}",
            f"--testrunnerbundleid={test_runner_bundle_id}",
            f"--xctestconfig={xctest_config}",
        ]
        for key, value in (env or {}).items():
            args.append(f"--env={key}={value}")
        if log_output:
            args.append(f"--log-output={log_output}")
        args += _base_args(self.udid)
        proc = await asyncio.create_subprocess_exec(
            ios,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._wda = proc
        return proc

    async def close(self) -> None:
        for proc in [*self._forwards, self._wda]:
            if proc is not None and proc.returncode is None:
                proc.terminate()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
        self._forwards.clear()
        self._wda = None
