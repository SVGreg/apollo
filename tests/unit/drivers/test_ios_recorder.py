"""iOS simulator recorder: backend selection and command construction."""

from pathlib import Path

import pytest

from apollo.drivers.ios import recorder
from apollo.drivers.ios.recorder import (
    MJPEG_SETTINGS,
    SimulatorRecorder,
    build_mjpeg_command,
    build_simctl_command,
    recording_backend,
)

UDID = "5A3587F9-040D-40C5-B3E8-6A29A4286978"


@pytest.mark.parametrize(
    ("env", "expected"),
    [(None, "auto"), ("simctl", "simctl"), ("MJPEG ", "mjpeg"), ("bogus", "auto")],
)
def test_recording_backend_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("APOLLO_IOS_RECORDING_BACKEND", raising=False)
    else:
        monkeypatch.setenv("APOLLO_IOS_RECORDING_BACKEND", env)
    assert recording_backend() == expected


def test_mjpeg_command_has_real_time_timeline_and_even_dimensions(tmp_path):
    cmd = build_mjpeg_command("/usr/bin/ffmpeg", "http://127.0.0.1:9100", tmp_path / "rec.mp4")
    assert cmd[0] == "/usr/bin/ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "http://127.0.0.1:9100/"
    assert "-use_wallclock_as_timestamps" in cmd
    assert cmd[cmd.index("-r") + 1] == str(MJPEG_SETTINGS["mjpegServerFramerate"])
    assert "trunc(iw/2)*2" in cmd[cmd.index("-vf") + 1]
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd[-1] == str(tmp_path / "rec.mp4")


def test_simctl_command_targets_the_udid(tmp_path):
    cmd = build_simctl_command("/usr/bin/xcrun", UDID, tmp_path / "rec.mp4")
    assert cmd[:5] == ["/usr/bin/xcrun", "simctl", "io", UDID, "recordVideo"]
    assert "--codec=h264" in cmd and "--force" in cmd
    assert cmd[-1] == str(tmp_path / "rec.mp4")


@pytest.mark.asyncio
async def test_auto_falls_back_to_simctl_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.delenv("APOLLO_IOS_RECORDING_BACKEND", raising=False)
    monkeypatch.setattr(recorder, "ffmpeg_path", lambda: None)
    started: list[str] = []

    async def fake_simctl(self):
        started.append("simctl")
        self.backend = "simctl"

    monkeypatch.setattr(SimulatorRecorder, "_start_simctl", fake_simctl)
    rec = SimulatorRecorder(UDID, tmp_path / "rec.mp4", mjpeg_url="http://127.0.0.1:9100")
    await rec.start()
    assert started == ["simctl"] and rec.backend == "simctl"


@pytest.mark.asyncio
async def test_stop_without_process_reports_existing_file(tmp_path):
    out = tmp_path / "rec.mp4"
    rec = SimulatorRecorder(UDID, out)
    assert await rec.stop() is None
    out.write_bytes(b"\x00" * 10)
    assert await rec.stop() == out
