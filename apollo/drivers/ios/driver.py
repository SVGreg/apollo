"""iOS device driver: WebDriverAgent for perception and input, simctl for the simulator.

Coordinates are screenshot pixels at the driver boundary (as on Android); WDA
takes points, so every gesture divides by the device scale, and the normalized
hierarchy multiplies bounds back so XML and PNG agree.
"""

import asyncio
import base64
import time
from pathlib import Path
from typing import Any, Literal

from apollo.clients.simctl import SimBridge, SimctlError
from apollo.clients.wda_client import ScreenInfo, WdaClient, WdaError
from apollo.drivers.base import BaseDeviceDriver, KeyCode, ScreenData, SwipeDirection
from apollo.drivers.ios import input as ios_input
from apollo.drivers.ios import keymap
from apollo.drivers.ios.device_commands import DeviceCommandError, run_device_command
from apollo.drivers.ios.hierarchy import normalize_wda_source
from apollo.drivers.ios.recorder import MJPEG_SETTINGS, SimulatorRecorder
from apollo.utils.logger import get_logger
from apollo.utils.ui_filter import filter_ui_hierarchy

logger = get_logger(__name__)

# WDA snapshot tuning (spike S1): shaves ~0.2 s on busy screens, no fidelity loss.
DEFAULT_WDA_SETTINGS = {
    "snapshotMaxDepth": 60,
    "pageSourceExcludedAttributes": "accessible,index",
    "shouldUseCompactResponses": True,
    # WDA resets session settings whenever a session is created, so every session
    # re-applies the MJPEG tuning the console live view and the recorder rely on.
    **MJPEG_SETTINGS,
}

SETTLE_SECONDS = 0.3


class IosDriver(BaseDeviceDriver):
    """Drives one iOS Simulator (devices arrive in Phase 3 with a DeviceBridge)."""

    is_mock = False

    def __init__(
        self,
        udid: str,
        wda: WdaClient | None = None,
        bridge: SimBridge | None = None,
        *,
        screen: ScreenInfo | None = None,
        wda_settings: dict[str, Any] | None = None,
    ):
        self._udid = udid
        self._wda_client = wda
        self._bridge = bridge or SimBridge(udid)
        self._screen = screen
        self._wda_settings = wda_settings or DEFAULT_WDA_SETTINGS
        self._settings_applied = False
        self._current_bundle: str | None = None
        self._connect_lock = asyncio.Lock()
        self._recorder: SimulatorRecorder | None = None

    # ----------------------------------------------------------------- identity

    @property
    def device_id(self) -> str:
        return self._udid

    @property
    def wda(self) -> WdaClient:
        if self._wda_client is None:
            raise RuntimeError("IosDriver used before connect(); call `await driver.connect()`")
        return self._wda_client

    _wda = wda

    @property
    def scale(self) -> int:
        return self._screen.scale if self._screen else 1

    @property
    def screen_size(self) -> tuple[int, int]:
        if self._screen:
            return (self._screen.width_px, self._screen.height_px)
        return (1206, 2622)

    @property
    def status_bar_height_px(self) -> int:
        return self._screen.status_bar_height_pt * self.scale if self._screen else 0

    async def connect(self) -> None:
        """Provision the runner (boot, install, launch) on first use; idempotent."""
        async with self._connect_lock:
            if self._wda_client is None:
                from apollo.runtime.runner_manager import RunnerManager

                self._wda_client, _ = await RunnerManager().ensure_simulator_runner(self._udid)
            if self._screen is None:
                self._screen = await self._wda.screen_info()
            await self._apply_settings()
        logger.info(
            f"iOS driver connected to {self._udid}: {self._screen.width_pt}x{self._screen.height_pt}pt "
            f"@{self._screen.scale}x ({self.screen_size[0]}x{self.screen_size[1]}px)"
        )

    async def disconnect(self) -> None:
        if self._wda_client is not None:
            await self._wda_client.aclose()
            self._wda_client = None

    async def _ensure(self) -> None:
        if self._wda_client is None or self._screen is None:
            await self.connect()

    async def _apply_settings(self) -> None:
        if self._settings_applied or not self._wda_settings:
            return
        try:
            await self._wda.set_settings(**self._wda_settings)
            self._settings_applied = True
        except WdaError as exc:
            logger.debug(f"WDA settings not applied: {exc}")

    # ----------------------------------------------------------------- perception

    async def get_screen_data(self, skip_settling: bool = False) -> ScreenData:
        await self._ensure()
        if not skip_settling:
            await asyncio.sleep(SETTLE_SECONDS)
        width, height = self.screen_size

        # Screenshot then source back-to-back (WDA has no combined snapshot).
        shot_b64, source_xml = await asyncio.gather(
            self._wda.screenshot_base64(), self._wda.source(), return_exceptions=True
        )
        if isinstance(shot_b64, BaseException):
            logger.warning(f"WDA screenshot failed ({shot_b64}); using simctl")
            shot_bytes = await self._bridge.screenshot()
            shot_b64 = base64.b64encode(shot_bytes).decode()
        else:
            shot_bytes = base64.b64decode(shot_b64)

        ui_xml: str | None = None
        elements: list[dict[str, Any]] = []
        if isinstance(source_xml, BaseException):
            logger.error(f"WDA /source failed: {source_xml}")
        else:
            try:
                normalized = normalize_wda_source(
                    source_xml, scale=self.scale, width_px=width, height_px=height
                )
                ui_xml = normalized.xml
                elements = filter_ui_hierarchy(
                    normalized.elements, screen_width=width, screen_height=height
                )
                if normalized.elements and not self._current_bundle:
                    self._current_bundle = normalized.elements[0].get("package") or None
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(f"Hierarchy normalization failed: {exc}")

        return ScreenData(
            screenshot_bytes=shot_bytes,
            screenshot_base64=shot_b64,
            ui_hierarchy_xml=ui_xml,
            ui_elements=elements,
            width=width,
            height=height,
            timestamp=time.time(),
            platform="ios",
        )

    async def get_ui_elements(self) -> list[dict[str, Any]]:
        """Hierarchy only (no screenshot, no settle) — the Safety Net's live-XML check."""
        await self._ensure()
        width, height = self.screen_size
        source_xml = await self._wda.source()
        normalized = normalize_wda_source(
            source_xml, scale=self.scale, width_px=width, height_px=height
        )
        return filter_ui_hierarchy(normalized.elements, screen_width=width, screen_height=height)

    # ----------------------------------------------------------------- gestures (px → pt)

    def _pt(self, px: int | float) -> float:
        return round(px / self.scale, 1)

    async def tap(
        self, x: int, y: int, duration_ms: int = 100, times: int = 1, delay_ms: int = 100
    ) -> bool:
        await self._ensure()
        try:
            if times > 1:
                await self._wda.multi_tap(self._pt(x), self._pt(y), times=times, delay_ms=delay_ms)
            else:
                await self._wda.tap(self._pt(x), self._pt(y), duration_ms=duration_ms)
            return True
        except WdaError as exc:
            logger.error(f"tap({x},{y}) failed: {exc}")
            return False

    async def long_press(self, x: int, y: int, duration_ms: int = 1000) -> bool:
        await self._ensure()
        try:
            await self._wda.long_press(self._pt(x), self._pt(y), duration_ms=duration_ms)
            return True
        except WdaError as exc:
            logger.error(f"long_press({x},{y}) failed: {exc}")
            return False

    async def swipe(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 800
    ) -> bool:
        await self._ensure()
        try:
            await self._wda.drag(
                self._pt(start_x),
                self._pt(start_y),
                self._pt(end_x),
                self._pt(end_y),
                duration_ms=duration_ms,
            )
            return True
        except WdaError as exc:
            logger.error(f"swipe failed: {exc}")
            return False

    async def swipe_direction(
        self,
        direction: SwipeDirection | Literal["up", "down", "left", "right"],
        duration_ms: int = 800,
    ) -> bool:
        await self._ensure()
        width, height = self.screen_size
        dir_str = str(direction).lower().replace("swipedirection.", "")
        mid_x = int(width * 0.6)  # off-centre, away from edge gestures
        mid_y = height // 2
        if dir_str == "up":
            return await self.swipe(mid_x, int(height * 0.7), mid_x, int(height * 0.3), duration_ms)
        if dir_str == "down":
            return await self.swipe(mid_x, int(height * 0.3), mid_x, int(height * 0.7), duration_ms)
        if dir_str == "left":
            return await self.swipe(int(width * 0.75), mid_y, int(width * 0.25), mid_y, duration_ms)
        if dir_str == "right":
            return await self.swipe(int(width * 0.25), mid_y, int(width * 0.75), mid_y, duration_ms)
        return False

    # ----------------------------------------------------------------- input

    async def input_text(self, text: str, clear_existing: bool = True) -> bool:
        await self._ensure()
        try:
            return await ios_input.type_text(self._wda, text, clear_existing=clear_existing)
        except WdaError as exc:
            logger.error(f"input_text failed: {exc}")
            return False

    async def press_key(self, key: KeyCode | str | int) -> bool:
        await self._ensure()
        try:
            return await keymap.press_key(
                self._wda,
                key,
                width_pt=self._screen.width_pt,
                height_pt=self._screen.height_pt,
            )
        except WdaError as exc:
            logger.error(f"press_key({key}) failed: {exc}")
            return False

    # ----------------------------------------------------------------- apps

    async def launch_app(self, package_name: str) -> bool:
        await self._ensure()
        try:
            ok = await self._wda.launch_app(package_name)
        except WdaError as exc:
            logger.warning(f"WDA launch of {package_name} failed ({exc}); trying simctl")
            try:
                await self._bridge.launch(package_name)
                ok = await self._wda.wait_for_active(package_name, timeout=8.0)
            except SimctlError as exc2:
                logger.error(f"simctl launch {package_name} failed: {exc2}")
                return False
        if ok:
            self._current_bundle = package_name
        else:
            logger.warning(f"{package_name} did not reach the foreground in time")
        return ok

    async def stop_app(self, package_name: str) -> bool:
        await self._ensure()
        try:
            await self._wda.terminate_app(package_name)
            return True
        except WdaError as exc:
            logger.debug(f"WDA terminate {package_name} failed ({exc}); trying simctl")
            return await self._bridge.terminate(package_name)

    async def get_current_package(self) -> str | None:
        await self._ensure()
        try:
            info = await self._wda.active_app()
            self._current_bundle = info.bundle_id or self._current_bundle
            return info.bundle_id or None
        except WdaError as exc:
            logger.debug(f"activeAppInfo failed: {exc}")
            return self._current_bundle

    async def open_url(self, url: str) -> bool:
        await self._ensure()
        try:
            await self._bridge.open_url(url)
            return True
        except SimctlError as exc:
            logger.warning(f"simctl openurl failed ({exc}); trying WDA /url")
            try:
                await self._wda.open_url(url)
                return True
            except WdaError as exc2:
                logger.error(f"open_url failed: {exc2}")
                return False

    async def install_app(self, app_path: str | Path) -> None:
        await self._bridge.install(app_path)

    async def list_apps(self) -> list[tuple[str, str]]:
        """(bundle_id, display_name) pairs of installed apps."""
        return [(app.bundle_id, app.display_name) for app in await self._bridge.list_apps()]

    # ----------------------------------------------------------------- shell

    async def execute_shell(self, command: str, timeout_seconds: float = 15.0) -> str:
        try:
            return await run_device_command(
                command, udid=self._udid, timeout_seconds=timeout_seconds
            )
        except DeviceCommandError as exc:
            return f"Error: {exc}"

    # ----------------------------------------------------------------- recording

    @property
    def recording_path(self) -> Path | None:
        return self._recorder.output_path if self._recorder else None

    async def start_video_recording(self, output_dir: Path | None = None) -> None:
        """Record the screen to ``<output_dir>/recording.mp4`` (see ``recorder.py``)."""
        from apollo.config.paths import get_temp_dir
        from apollo.runtime.runner_manager import registered_endpoint

        if self._recorder and self._recorder.is_running:
            logger.warning("Screen recording already running; ignoring second start")
            return
        await self._ensure()
        out_dir = Path(output_dir) if output_dir else get_temp_dir("recordings")
        endpoint = registered_endpoint(self._udid)
        self._recorder = SimulatorRecorder(
            self._udid,
            out_dir / "recording.mp4",
            wda=self._wda_client,
            mjpeg_url=endpoint.mjpeg_url if endpoint else None,
        )
        await self._recorder.start()

    async def stop_video_recording(self) -> str | None:
        if self._recorder is None:
            return None
        recorder, self._recorder = self._recorder, None
        path = await recorder.stop()
        if path is None:
            logger.warning("Screen recording produced no file")
            return None
        logger.info(f"Screen recording saved ({recorder.backend}): {path}")
        return str(path)
