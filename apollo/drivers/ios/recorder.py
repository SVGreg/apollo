"""Screen recording for iOS Simulators.

Two backends, picked by ``APOLLO_IOS_RECORDING_BACKEND`` (``auto`` by default):

- ``mjpeg``: ``ffmpeg`` reads the WebDriverAgent MJPEG server (12 fps, quality 40,
  50 % scale — spike S5) and writes H.264 with wall-clock timestamps, so the file's
  timeline matches the trace's step times. Also the path physical devices will use.
- ``simctl``: ``xcrun simctl io recordVideo`` — no extra tooling, but the stream is
  change-driven with a variable frame rate: a static screen yields a handful of
  frames and the file duration is not real time (spike S2).

``auto`` prefers ``mjpeg`` when ``ffmpeg`` is on the PATH and the runner is up.
"""

import asyncio
import os
import shutil
import signal
from pathlib import Path

from apollo.clients.simctl import find_xcrun
from apollo.clients.wda_client import WdaClient, WdaError
from apollo.utils.logger import get_logger

logger = get_logger(__name__)

MJPEG_SETTINGS = {
    "mjpegServerFramerate": 12,
    "mjpegServerScreenshotQuality": 40,
    "mjpegScalingFactor": 50,
}
# 50 % scale of a 3x device is odd-sized (603×1311); x264 needs even dimensions.
_EVEN_SIZE_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
_STOP_TIMEOUT_S = 20.0


def recording_backend() -> str:
    value = (os.environ.get("APOLLO_IOS_RECORDING_BACKEND") or "auto").strip().lower()
    return value if value in ("auto", "simctl", "mjpeg") else "auto"


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def build_mjpeg_command(ffmpeg: str, mjpeg_url: str, output_path: Path) -> list[str]:
    """ffmpeg reading the WDA MJPEG server into constant-fps H.264 with a real-time timeline."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-use_wallclock_as_timestamps",
        "1",
        "-f",
        "mjpeg",
        "-i",
        mjpeg_url.rstrip("/") + "/",
        "-vf",
        _EVEN_SIZE_FILTER,
        "-r",
        str(MJPEG_SETTINGS["mjpegServerFramerate"]),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_simctl_command(xcrun: str, udid: str, output_path: Path) -> list[str]:
    return [
        xcrun,
        "simctl",
        "io",
        udid,
        "recordVideo",
        "--codec=h264",
        "--force",
        str(output_path),
    ]


class SimulatorRecorder:
    """One recording (start → stop) of a simulator screen into ``output_path``."""

    def __init__(
        self,
        udid: str,
        output_path: Path,
        *,
        wda: WdaClient | None = None,
        mjpeg_url: str | None = None,
    ):
        self._udid = udid
        self._output_path = Path(output_path)
        self._wda = wda
        self._mjpeg_url = mjpeg_url
        self._process: asyncio.subprocess.Process | None = None
        self.backend: str | None = None

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        wanted = recording_backend()
        if wanted in ("auto", "mjpeg") and await self._start_mjpeg():
            return
        if wanted == "mjpeg":
            logger.warning("MJPEG recording unavailable (ffmpeg or runner missing); using simctl")
        await self._start_simctl()

    async def _start_mjpeg(self) -> bool:
        ffmpeg = ffmpeg_path()
        if not ffmpeg or not self._mjpeg_url or self._wda is None:
            return False
        try:
            await self._wda.set_settings(**MJPEG_SETTINGS)
        except WdaError as exc:
            logger.debug(f"MJPEG settings not applied: {exc}")
        cmd = build_mjpeg_command(ffmpeg, self._mjpeg_url, self._output_path)
        self._process = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.sleep(0.5)
        if self._process.returncode is not None:
            err = (
                (await self._process.stderr.read()).decode(errors="replace")
                if self._process.stderr
                else ""
            )
            logger.warning(f"ffmpeg MJPEG recorder exited immediately: {err.strip()[:300]}")
            self._process = None
            return False
        self.backend = "mjpeg"
        logger.info(f"Recording {self._udid} from WDA MJPEG via ffmpeg → {self._output_path}")
        return True

    async def _start_simctl(self) -> None:
        xcrun = find_xcrun()
        if not xcrun:
            raise RuntimeError("xcrun not found; cannot record the simulator")
        cmd = build_simctl_command(xcrun, self._udid, self._output_path)
        self._process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
        await asyncio.sleep(0.5)
        if self._process.returncode is not None:
            err = (
                (await self._process.stderr.read()).decode(errors="replace")
                if self._process.stderr
                else ""
            )
            self._process = None
            raise RuntimeError(f"simctl recordVideo exited immediately: {err.strip()[:300]}")
        self.backend = "simctl"
        logger.info(f"Recording {self._udid} with simctl recordVideo → {self._output_path}")

    async def stop(self) -> Path | None:
        """Finish the file (SIGINT lets both tools write the MP4 trailer) and return it."""
        proc, self._process = self._process, None
        if proc is None:
            return self._existing_output()
        if proc.returncode is None:
            try:
                if self.backend == "mjpeg" and proc.stdin is not None:
                    proc.stdin.write(b"q")  # ffmpeg's graceful quit
                    await proc.stdin.drain()
                else:
                    proc.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError, ConnectionError, BrokenPipeError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT_S)
            except TimeoutError:
                logger.warning("Recorder did not stop in time; terminating")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
        if proc.stderr is not None:
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            if err and proc.returncode not in (0, None):
                logger.debug(f"Recorder ({self.backend}) stderr: {err[:400]}")
        return self._existing_output()

    def _existing_output(self) -> Path | None:
        if self._output_path.exists() and self._output_path.stat().st_size > 0:
            return self._output_path
        return None
