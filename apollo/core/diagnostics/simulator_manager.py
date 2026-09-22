"""Boot / shut down iOS Simulators for the console and `mobile_diagnose`.

Keeps the launch-state schema Artemis used for AVDs so the console's launch panel and
its progress polling work unchanged; ``avd_name`` carries the simulator name or UDID.
"""

import asyncio
from enum import Enum
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from apollo.clients import simctl
from apollo.utils.logger import get_logger

logger = get_logger(__name__)


class EmulatorLaunchStage(str, Enum):
    """Lifecycle stages of booting a simulator."""

    IDLE = "idle"
    STARTING = "starting"
    WAITING_FOR_ADB = "waiting_for_adb"  # unused on iOS; kept for the console's schema
    BOOTING = "booting"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


class EmulatorLaunchState(BaseModel):
    """State schema for real-time boot tracking."""

    avd_name: str | None = None
    status: EmulatorLaunchStage = EmulatorLaunchStage.IDLE
    pid: int | None = None
    serial: str | None = None
    stage_message: str = "Ready to launch"
    progress_percent: int = 0
    started_at: float | None = None
    elapsed_seconds: int = 0
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    can_retry: bool = True


class SimulatorManager:
    BOOT_TIMEOUT_SECONDS = 180.0

    def __init__(self):
        self._state = EmulatorLaunchState()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def get_status(self) -> EmulatorLaunchState:
        state = self._state.model_copy(deep=True)
        if state.started_at and state.status in (
            EmulatorLaunchStage.STARTING,
            EmulatorLaunchStage.BOOTING,
        ):
            state.elapsed_seconds = int(time.time() - state.started_at)
        return state

    async def _resolve(self, name_or_udid: str) -> simctl.SimDevice | None:
        devices = await simctl.SimBridge.list_devices()
        for dev in devices:
            if dev.udid.lower() == name_or_udid.lower():
                return dev
        # "iPhone 17 Pro (26.2)" — the label the readiness probe lists — pins the runtime.
        labelled = re.match(r"^(.*?)\s*\((\d+(?:\.\d+)*)\)$", name_or_udid.strip())
        if labelled:
            name, version = labelled.group(1).strip().lower(), labelled.group(2)
            exact = [d for d in devices if d.name.lower() == name and d.os_version == version]
            if exact:
                return exact[0]
            name_or_udid = labelled.group(1).strip()
        matches = [d for d in devices if d.name.lower() == name_or_udid.lower()]
        if not matches:
            matches = [d for d in devices if name_or_udid.lower() in d.name.lower()]
        # Prefer a booted one, then the newest runtime.
        matches.sort(key=lambda d: (not d.is_booted, d.os_version), reverse=False)
        booted = [d for d in matches if d.is_booted]
        if booted:
            return booted[0]
        return max(matches, key=lambda d: d.os_version) if matches else None

    async def launch(self, name_or_udid: str) -> EmulatorLaunchState:
        target = (name_or_udid or "").strip()
        if not target:
            self._state = EmulatorLaunchState(
                status=EmulatorLaunchStage.FAILED,
                error="Simulator name or UDID cannot be empty.",
                stage_message="Launch failed: no simulator given.",
            )
            return self.get_status()
        async with self._lock:
            if self._task and not self._task.done():
                return self.get_status()
            # Resolve synchronously (one `simctl list`, ~0.3 s) so an unknown name fails
            # immediately and no background task is spawned for it.
            try:
                dev = await asyncio.wait_for(self._resolve(target), timeout=20.0)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                dev = None
                logger.debug(f"simulator resolve failed: {exc}")
            if dev is None:
                self._state = EmulatorLaunchState(
                    avd_name=target,
                    status=EmulatorLaunchStage.FAILED,
                    error=f"No simulator named '{target}'.",
                    stage_message=f"No simulator named '{target}'.",
                    logs=["xcrun simctl list devices: no match"],
                )
                return self.get_status()
            self._state = EmulatorLaunchState(
                avd_name=dev.name,
                serial=dev.udid,
                status=EmulatorLaunchStage.STARTING,
                stage_message=f"Booting {dev.name} (iOS {dev.os_version})…",
                progress_percent=5,
                started_at=time.time(),
                logs=[f"xcrun simctl boot {dev.udid}"],
            )
            if dev.is_booted:
                self._state.status = EmulatorLaunchStage.READY
                self._state.progress_percent = 100
                self._state.stage_message = f"{dev.name} is already booted"
                return self.get_status()
            self._task = asyncio.create_task(self._boot(dev))
        return self.get_status()

    async def _boot(self, dev: simctl.SimDevice) -> None:
        try:
            self._state.status = EmulatorLaunchStage.BOOTING
            self._state.progress_percent = 30
            self._state.stage_message = f"Booting {dev.name} (iOS {dev.os_version})…"
            bridge = simctl.SimBridge(dev.udid)
            await asyncio.wait_for(bridge.boot(wait=True), timeout=self.BOOT_TIMEOUT_SECONDS)
            self._state.status = EmulatorLaunchStage.READY
            self._state.progress_percent = 100
            self._state.stage_message = f"{dev.name} booted ({dev.udid})"
            self._state.logs.append("bootstatus: booted")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(f"Simulator boot failed: {exc}")
            self._state.status = EmulatorLaunchStage.FAILED
            self._state.error = str(exc)
            self._state.stage_message = f"Boot failed: {exc}"

    async def stop(self) -> dict[str, Any]:
        serial = self._state.serial
        if not serial:
            return {"success": False, "message": "No simulator was launched from here."}
        try:
            await simctl.SimBridge(serial).shutdown()
            self._state.status = EmulatorLaunchStage.STOPPED
            self._state.stage_message = "Simulator shut down"
            return {"success": True, "message": f"Shut down {serial}"}
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return {"success": False, "message": str(exc)}

    def dismiss(self) -> dict[str, Any]:
        self._state = EmulatorLaunchState()
        return {"success": True}


simulator_manager = SimulatorManager()
