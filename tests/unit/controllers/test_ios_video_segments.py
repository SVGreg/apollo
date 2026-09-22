"""iOS branch of `extract_segment_metadata` (Video Analyzer support)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from apollo.controllers import unified_controller as uc
from apollo.controllers.unified_controller import UnifiedMobileController


class FakeIosDriver:
    is_mock = False

    def __init__(self, info):
        self.recording_info = info
        self.device_id = "5A3587F9-040D-40C5-B3E8-6A29A4286978"


def _controller(info, *, engine_start: float | None = 100.0) -> UnifiedMobileController:
    ctx = SimpleNamespace(
        device=SimpleNamespace(mobile_platform="ios", device_id="udid"),
        data_engine=SimpleNamespace(session_start_time=engine_start) if engine_start else None,
    )
    controller = UnifiedMobileController.__new__(UnifiedMobileController)
    controller.ctx = ctx
    controller._driver = FakeIosDriver(info)
    controller._segment_cache = {}
    return controller


def _info(tmp_path: Path, *, backend: str = "mjpeg", started_at: float = 105.0) -> dict:
    path = tmp_path / "recording.mp4"
    path.write_bytes(b"\x00" * 64)
    return {
        "path": path,
        "started_at": started_at,
        "backend": backend,
        "supports_live_segments": backend == "mjpeg",
    }


@pytest.mark.asyncio
async def test_without_a_recording_it_says_so():
    result = await _controller(None).extract_segment_metadata(0.0, 5.0)
    assert not result.success and "No active iOS recording" in result.message


@pytest.mark.asyncio
async def test_simctl_backend_explains_why_there_are_no_segments(tmp_path):
    result = await _controller(_info(tmp_path, backend="simctl")).extract_segment_metadata(0.0, 5.0)
    assert not result.success
    assert "cannot be read while it records" in result.message


@pytest.mark.asyncio
async def test_no_readable_fragment_yet_asks_the_caller_to_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("apollo.drivers.ios.recorder.probe_duration", lambda path: None)
    result = await _controller(_info(tmp_path)).extract_segment_metadata(0.0, 5.0)
    assert not result.success and "no readable fragment yet" in result.message


@pytest.mark.asyncio
async def test_window_is_shifted_by_the_recording_offset_and_clamped(tmp_path, monkeypatch):
    """T0 is the DataEngine start; recording began 5 s later, so 8 s → 3 s in the file."""
    captured: dict = {}

    async def fake_render(segments, start, end, out_path):
        captured.update(segments=segments, start=start, end=end)
        Path(out_path).write_bytes(b"\x00" * 2048)
        return True

    monkeypatch.setattr("apollo.drivers.ios.recorder.probe_duration", lambda path: 12.0)
    monkeypatch.setattr(uc, "render_timeline_clip", fake_render)

    result = await _controller(_info(tmp_path, started_at=105.0)).extract_segment_metadata(
        8.0, 10.0
    )
    assert result.success, result.message
    assert captured["start"] == pytest.approx(3.0)
    assert captured["end"] == pytest.approx(5.0)
    assert result.duration_seconds == pytest.approx(2.0)
    assert result.actual_start_relative_time == pytest.approx(8.0)
    assert result.warning is None


@pytest.mark.asyncio
async def test_end_beyond_the_written_file_is_truncated_with_a_warning(tmp_path, monkeypatch):
    async def fake_render(segments, start, end, out_path):
        Path(out_path).write_bytes(b"\x00" * 2048)
        return True

    monkeypatch.setattr("apollo.drivers.ios.recorder.probe_duration", lambda path: 12.0)
    monkeypatch.setattr(uc, "render_timeline_clip", fake_render)

    result = await _controller(_info(tmp_path, started_at=105.0)).extract_segment_metadata(
        6.0, 999.0
    )
    assert result.success and result.warning and "truncated" in result.warning
    # 12 s written minus the 0.5 s safety margin, starting 1 s into the file.
    assert result.duration_seconds == pytest.approx(11.5 - 1.0)


@pytest.mark.asyncio
async def test_a_range_past_the_end_fails_with_what_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr("apollo.drivers.ios.recorder.probe_duration", lambda path: 12.0)
    result = await _controller(_info(tmp_path)).extract_segment_metadata(900.0, 950.0)
    assert not result.success and "of video is available" in result.message
