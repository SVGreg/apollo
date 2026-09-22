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


def test_safety_net_hierarchy_budget_is_wider_on_ios():
    from apollo.constants import (
        VALIDATOR_UI_HIERARCHY_TIMEOUT,
        VALIDATOR_UI_HIERARCHY_TIMEOUT_IOS,
        ui_hierarchy_timeout_for,
    )
    from apollo.context import DevicePlatform

    assert ui_hierarchy_timeout_for(DevicePlatform.IOS) == VALIDATOR_UI_HIERARCHY_TIMEOUT_IOS
    assert ui_hierarchy_timeout_for("ios") == VALIDATOR_UI_HIERARCHY_TIMEOUT_IOS
    assert ui_hierarchy_timeout_for(DevicePlatform.ANDROID) == VALIDATOR_UI_HIERARCHY_TIMEOUT
    assert ui_hierarchy_timeout_for(None) == VALIDATOR_UI_HIERARCHY_TIMEOUT


def test_mjpeg_command_is_fragmented_so_segments_can_be_cut_mid_run(tmp_path):
    from apollo.drivers.ios.recorder import KEYFRAME_INTERVAL_S

    cmd = build_mjpeg_command("/usr/bin/ffmpeg", "http://127.0.0.1:9100", tmp_path / "rec.mp4")
    movflags = cmd[cmd.index("-movflags") + 1]
    assert "frag_keyframe" in movflags and "empty_moov" in movflags
    assert "faststart" not in movflags  # faststart finalizes only on exit
    gop = int(cmd[cmd.index("-g") + 1])
    assert gop == KEYFRAME_INTERVAL_S * int(MJPEG_SETTINGS["mjpegServerFramerate"])


def test_probe_duration_returns_none_for_an_unreadable_file(tmp_path):
    from apollo.drivers.ios.recorder import probe_duration

    missing = tmp_path / "nope.mp4"
    assert probe_duration(missing) is None
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert probe_duration(empty) is None


@pytest.mark.asyncio
async def test_only_the_mjpeg_backend_advertises_live_segments(monkeypatch, tmp_path):
    monkeypatch.delenv("APOLLO_IOS_RECORDING_BACKEND", raising=False)
    monkeypatch.setattr(recorder, "ffmpeg_path", lambda: None)

    async def fake_simctl(self):
        self.backend = "simctl"
        self.started_at = 123.0

    monkeypatch.setattr(SimulatorRecorder, "_start_simctl", fake_simctl)
    rec = SimulatorRecorder(UDID, tmp_path / "rec.mp4")
    await rec.start()
    assert rec.backend == "simctl" and rec.supports_live_segments is False
