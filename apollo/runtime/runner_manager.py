"""Provision and supervise the WebDriverAgent runner on simulators.

The runner is the iOS counterpart of Artemis's Accessibility Helper APK: a
prebuilt XCTest bundle pinned in ``apollo/resources/runner_manifest.json``,
downloaded once into the app-data cache, installed with ``simctl install`` and
launched with per-device ports through ``SIMCTL_CHILD_USE_PORT``.
"""

import asyncio
import hashlib
import json
import platform as host_platform
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from apollo.clients.simctl import SimBridge, SimctlError
from apollo.clients.wda_client import WdaClient
from apollo.config.paths import get_app_dir
from apollo.utils.logger import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "resources" / "runner_manifest.json"


class RunnerError(RuntimeError):
    """Raised when the runner cannot be provisioned or does not come up."""


@dataclass
class RunnerEndpoint:
    udid: str
    port: int
    mjpeg_port: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def mjpeg_url(self) -> str:
        return f"http://127.0.0.1:{self.mjpeg_port}"


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def runner_cache_dir() -> Path:
    path = get_app_dir() / "runner"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _host_arch() -> str:
    machine = host_platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# udid -> endpoint for runners this process has provisioned; ports stay stable per device.
_ENDPOINTS: dict[str, RunnerEndpoint] = {}
_ENDPOINT_LOCK = threading.Lock()


def allocate_endpoint(udid: str, *, runner_base: int, mjpeg_base: int) -> RunnerEndpoint:
    """Return the endpoint registered for ``udid``, allocating the next free port pair."""
    with _ENDPOINT_LOCK:
        if udid in _ENDPOINTS:
            return _ENDPOINTS[udid]
        used = {ep.port for ep in _ENDPOINTS.values()}
        offset = 0
        while runner_base + offset in used:
            offset += 1
        endpoint = RunnerEndpoint(
            udid=udid, port=runner_base + offset, mjpeg_port=mjpeg_base + offset
        )
        _ENDPOINTS[udid] = endpoint
        return endpoint


def registered_endpoint(udid: str) -> RunnerEndpoint | None:
    return _ENDPOINTS.get(udid)


class RunnerManager:
    """Ensures WDA is installed and answering on a simulator."""

    def __init__(self, manifest: dict[str, Any] | None = None):
        self.manifest = manifest or load_manifest()
        self.bundle_id: str = self.manifest["bundle_id"]
        self.version: str = self.manifest["version"]
        # What the pinned build answers in /status (release assets sometimes lag the tag).
        self.reported_version: str = self.manifest.get("reported_version") or self.version
        ports = self.manifest.get("ports") or {}
        self.runner_base: int = int(ports.get("runner_base", 8100))
        self.mjpeg_base: int = int(ports.get("mjpeg_base", 9100))

    def endpoint_for(self, udid: str) -> RunnerEndpoint:
        return allocate_endpoint(udid, runner_base=self.runner_base, mjpeg_base=self.mjpeg_base)

    # ------------------------------------------------------------- artifacts

    def simulator_bundle_dir(self) -> Path:
        return runner_cache_dir() / f"wda-{self.version}-sim-{_host_arch()}"

    async def ensure_simulator_bundle(self) -> Path:
        """Download + verify + unzip the prebuilt simulator runner; returns the .app path."""
        entry = self.manifest["simulator"][_host_arch()]
        target = self.simulator_bundle_dir()
        app_path = target / entry["app_dir"]
        if (app_path / "Info.plist").is_file():
            return app_path

        target.mkdir(parents=True, exist_ok=True)
        zip_path = target / "runner.zip"
        logger.info(f"Downloading WebDriverAgent {self.version} runner ({_host_arch()})…")
        async with httpx.AsyncClient(follow_redirects=True, timeout=300.0) as client:
            async with client.stream("GET", entry["url"]) as resp:
                resp.raise_for_status()
                with zip_path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        fh.write(chunk)
        expected = entry.get("sha256")
        actual = await asyncio.to_thread(_sha256, zip_path)
        if expected and actual != expected:
            zip_path.unlink(missing_ok=True)
            raise RunnerError(
                f"WDA runner checksum mismatch: expected {expected}, got {actual}. "
                "The manifest pin and the release asset disagree; refusing to install."
            )
        await asyncio.to_thread(lambda: zipfile.ZipFile(zip_path).extractall(target))
        zip_path.unlink(missing_ok=True)
        if not (app_path / "Info.plist").is_file():
            raise RunnerError(f"Runner bundle missing after extraction: {app_path}")
        logger.info(f"WDA runner ready at {app_path}")
        return app_path

    # ------------------------------------------------------------- simulator

    async def ensure_installed(self, bridge: SimBridge) -> None:
        if await bridge.is_installed(self.bundle_id):
            return
        app_path = await self.ensure_simulator_bundle()
        logger.info(f"Installing WDA runner on simulator {bridge.udid}")
        await bridge.install(app_path)

    async def launch(self, bridge: SimBridge, endpoint: RunnerEndpoint) -> None:
        """Start the runner. Readiness is `/status`, not this command's return.

        On a loaded host `simctl launch` can sit past its timeout while the XCTest
        bundle is already coming up, so a timeout here is logged and left to
        ``wait_ready`` to confirm or reject; any other simctl failure (not installed,
        bad bundle id) still raises.
        """
        try:
            await bridge.launch(
                self.bundle_id,
                child_env={
                    "USE_PORT": str(endpoint.port),
                    "MJPEG_SERVER_PORT": str(endpoint.mjpeg_port),
                },
                terminate_running=True,
            )
        except SimctlError as exc:
            if "timed out" not in str(exc):
                raise
            logger.warning(f"simctl launch did not return in time ({exc}); polling /status anyway")

    async def wait_ready(self, endpoint: RunnerEndpoint, *, timeout: float = 60.0) -> WdaClient:
        client = WdaClient(endpoint.base_url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await client.is_ready():
                return client
            await asyncio.sleep(0.5)
        await client.aclose()
        raise RunnerError(f"WDA did not answer on {endpoint.base_url} within {timeout:.0f}s")

    async def ensure_simulator_runner(
        self,
        udid: str,
        *,
        port: int | None = None,
        mjpeg_port: int | None = None,
        timeout: float = 90.0,
    ) -> tuple[WdaClient, RunnerEndpoint]:
        """Boot-if-needed, install-if-needed, launch-if-needed; returns a ready client.

        Ports default to the process-wide allocation for this udid, so every
        driver instance for the same simulator talks to the same runner.
        """
        if port is None:
            endpoint = self.endpoint_for(udid)
        else:
            endpoint = RunnerEndpoint(udid=udid, port=port, mjpeg_port=mjpeg_port or port + 1000)
            with _ENDPOINT_LOCK:
                _ENDPOINTS[udid] = endpoint
        port, mjpeg_port = endpoint.port, endpoint.mjpeg_port
        bridge = SimBridge(udid)

        # Already answering on this port? Reuse (a runner survives across tasks).
        probe = WdaClient(endpoint.base_url)
        if await probe.is_ready():
            return probe, endpoint
        await probe.aclose()

        device = await bridge.get_device()
        if device is None:
            raise RunnerError(f"Simulator {udid} not found (xcrun simctl list devices)")
        if not device.is_booted:
            logger.info(f"Booting simulator {device.name} ({udid})…")
            await bridge.boot(wait=True)

        await self.ensure_installed(bridge)
        logger.info(f"Launching WDA runner on {device.name} (port {port}, mjpeg {mjpeg_port})")
        await self.launch(bridge, endpoint)
        client = await self.wait_ready(endpoint, timeout=timeout)
        return client, endpoint

    async def stop(self, udid: str) -> None:
        await SimBridge(udid).terminate(self.bundle_id)

    async def status(self, udid: str, *, port: int) -> dict[str, Any]:
        bridge = SimBridge(udid)
        installed = await bridge.is_installed(self.bundle_id)
        client = WdaClient(f"http://127.0.0.1:{port}")
        try:
            info = await client.status() if installed else {}
        except Exception:
            info = {}
        finally:
            await client.aclose()
        build = (info.get("build") or {}) if isinstance(info, dict) else {}
        return {
            "installed": installed,
            "ready": bool(info.get("ready")) if info else False,
            "port": port,
            "runner_version": build.get("version"),
            "pinned_version": self.version,
            "expected_runner_version": self.reported_version,
            "os_version": (info.get("os") or {}).get("version") if info else None,
        }

    def clear_cache(self) -> None:
        shutil.rmtree(self.simulator_bundle_dir(), ignore_errors=True)
