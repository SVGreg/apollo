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

"""Device Live Screen Streaming Service.

Provides real-time device screen frames over HTTP MJPEG for the console's live view.

iOS: frames come from the WebDriverAgent MJPEG server when the runner is up (12 fps,
no extra device load), otherwise from `simctl io screenshot` polling (~4 fps). Both
run alongside the agent's own perception without interfering with it. The Android
adb `screencap` path is kept for reference but is not used on this platform.
"""

import asyncio
import logging
import subprocess
import time
from collections.abc import AsyncGenerator

import httpx

from apollo.clients import simctl
from apollo.runtime.runner_manager import RunnerManager, registered_endpoint
from apollo.toolchain import find_adb


def _to_preview_jpeg(png: bytes) -> bytes:
    """Half-size JPEG for the browser: a 1206x2622 PNG is ~3 MB, the preview ~60 KB."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        img = img.convert("RGB")
        img.thumbnail((img.width // 2, img.height // 2))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70, optimize=True)
        return out.getvalue()


logger = logging.getLogger("apollo.stream_service")


class DeviceStreamService:
    """Manages real-time screen capture and distribution to web clients."""

    def __init__(self):
        self._active_listeners = 0
        self._lock = asyncio.Lock()
        self._latest_frame: bytes | None = None
        self._frame_media_type: bytes = b"image/png"
        self._last_frame_time: float = 0.0
        self._is_capturing = False
        self._capture_task: asyncio.Task | None = None

    async def get_device_serial(self) -> str | None:
        """Find the active target: a booted iOS Simulator first, else an adb device."""
        try:
            if simctl.simctl_available():
                booted = await asyncio.wait_for(
                    simctl.SimBridge.list_devices(booted_only=True), timeout=5.0
                )
                if booted:
                    return booted[0].udid
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(f"simctl device lookup failed: {e}")
        try:
            adb_bin = find_adb()
            if not adb_bin:
                return None
            proc = await asyncio.create_subprocess_exec(
                adb_bin,
                "devices",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode().strip().splitlines()
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    return parts[0]
        except Exception as e:
            logger.warning(f"Error checking adb devices: {e}")
        return None

    async def _wda_mjpeg_loop(self, udid: str) -> bool:
        """Consume the runner's MJPEG stream while it answers. Returns False if unavailable."""
        # Tasks run in a separate runner process, so this process's registry is usually
        # empty; the port allocation is deterministic per udid, so probe that endpoint.
        endpoint = registered_endpoint(udid) or RunnerManager().endpoint_for(udid)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, read=4.0)) as client:
                async with client.stream("GET", endpoint.mjpeg_url + "/") as resp:
                    if resp.status_code != 200:
                        return False
                    buf = b""
                    async for chunk in resp.aiter_bytes():
                        if self._active_listeners <= 0:
                            return True
                        buf += chunk
                        while True:
                            start = buf.find(b"\xff\xd8")
                            end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                            if start < 0 or end < 0:
                                break
                            self._latest_frame = buf[start : end + 2]
                            self._frame_media_type = b"image/jpeg"
                            self._last_frame_time = time.time()
                            buf = buf[end + 2 :]
                        if len(buf) > 4_000_000:
                            buf = buf[-1_000_000:]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(f"[StreamService] WDA MJPEG unavailable on {udid}: {e}")
            return False
        return True

    async def _simctl_capture_loop(self, udid: str) -> None:
        """Poll `simctl io screenshot` (~4 fps) while the runner is not streaming."""
        bridge = simctl.SimBridge(udid)
        while self._active_listeners > 0:
            start_t = time.time()
            try:
                png = await bridge.screenshot()
                if len(png) > 1000:
                    self._latest_frame = await asyncio.to_thread(_to_preview_jpeg, png)
                    self._frame_media_type = b"image/jpeg"
                    self._last_frame_time = time.time()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug(f"[StreamService] simctl screenshot failed: {e}")
                await asyncio.sleep(0.5)
                continue
            # Try to upgrade to the runner's MJPEG server (cheap 50 KB JPEG frames at 12 fps);
            # it answers only while a task has WDA running, so re-probe every few frames.
            probe_counter = getattr(self, "_mjpeg_probe_counter", 0) + 1
            self._mjpeg_probe_counter = probe_counter
            if probe_counter % 8 == 0 and await self._wda_mjpeg_loop(udid):
                if self._active_listeners <= 0:
                    return
            await asyncio.sleep(max(0.05, 0.25 - (time.time() - start_t)))

    async def _capture_loop(self):
        """Background frame capture loop that runs while listeners > 0."""
        logger.info("[StreamService] Starting live screen capture loop...")
        serial = await self.get_device_serial()
        if serial and simctl.simctl_available() and "-" in serial and len(serial) == 36:
            try:
                await self._simctl_capture_loop(serial)
            except asyncio.CancelledError:
                pass
            logger.info("[StreamService] Stopping live screen capture loop (0 listeners).")
            self._is_capturing = False
            return
        while self._active_listeners > 0:
            try:
                start_t = time.time()
                serial = await self.get_device_serial()
                adb_bin = find_adb()
                cmd = (
                    [adb_bin, "-s", serial, "exec-out", "screencap", "-p"]
                    if serial
                    else [adb_bin, "exec-out", "screencap", "-p"]
                )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and len(stdout) > 1000:
                    self._latest_frame = stdout
                    self._last_frame_time = time.time()

                elapsed = time.time() - start_t
                delay = max(0.03, 0.08 - elapsed)
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[StreamService] Capture error: {e}")
                await asyncio.sleep(0.5)

        logger.info("[StreamService] Stopping live screen capture loop (0 listeners).")
        self._is_capturing = False

    async def start_capturing(self):
        """Register a new listener and start background capture if needed."""
        async with self._lock:
            self._active_listeners += 1
            if not self._is_capturing or self._capture_task is None or self._capture_task.done():
                self._is_capturing = True
                self._capture_task = asyncio.create_task(self._capture_loop())

    async def stop_capturing(self):
        """Deregister a listener and stop capture loop when count reaches 0."""
        async with self._lock:
            self._active_listeners = max(0, self._active_listeners - 1)
            if self._active_listeners == 0 and self._capture_task and not self._capture_task.done():
                self._capture_task.cancel()
                self._is_capturing = False

    async def mjpeg_frame_generator(self) -> AsyncGenerator[bytes, None]:
        """Async generator streaming MJPEG multipart bytes to HTTP response."""
        await self.start_capturing()
        try:
            last_sent_time = 0.0
            while True:
                if self._latest_frame and self._last_frame_time > last_sent_time:
                    last_sent_time = self._last_frame_time
                    frame_bytes = self._latest_frame
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: " + self._frame_media_type + b"\r\n"
                        b"Content-Length: "
                        + str(len(frame_bytes)).encode()
                        + b"\r\n\r\n"
                        + frame_bytes
                        + b"\r\n"
                    )
                await asyncio.sleep(0.04)
        finally:
            await self.stop_capturing()


device_stream_service = DeviceStreamService()
