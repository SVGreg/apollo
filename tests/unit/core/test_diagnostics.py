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

"""Unit tests for Apollo System Diagnostics & Readiness Engine."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from apollo.core.diagnostics.engine import ReadinessEngine
from apollo.core.diagnostics.probes.credentials_probe import (
    LLMCredentialsProbe,
    VisionOCRProbe,
)
from apollo.core.diagnostics.probes.runtime_probe import (
    PythonRuntimeProbe,
    SystemConfigProbe,
)
from apollo.core.diagnostics.schema import (
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
    SystemReadinessReport,
)


@pytest.mark.asyncio
async def test_readiness_engine_run_all():
    """Verify that ReadinessEngine aggregates probes and builds structured report."""
    engine = ReadinessEngine()
    report: SystemReadinessReport = await engine.run_all()

    assert isinstance(report, SystemReadinessReport)
    assert report.blocker_count >= 3
    assert isinstance(report.probes, list)
    assert len(report.probes) >= 5

    probe_ids = [p.id for p in report.probes]
    assert "python_runtime" in probe_ids
    assert "system_config" in probe_ids
    assert "ios_device" in probe_ids  # the device probe is iOS on Apollo
    assert "gemini_api_key" in probe_ids
    assert "vision_ocr_key" in probe_ids
    assert "toolchain" in probe_ids


@pytest.mark.asyncio
async def test_python_runtime_probe_structure():
    """Verify PythonRuntimeProbe returns valid runtime inspection result."""
    probe = PythonRuntimeProbe()
    assert probe.probe_id == "python_runtime"
    assert probe.category == ProbeCategory.RUNTIME
    assert probe.is_blocker is True

    result: ProbeResult = await probe.probe()
    assert isinstance(result, ProbeResult)
    assert result.status in (ProbeStatus.PASS, ProbeStatus.FAIL)
    assert "version" in result.metadata
    assert "executable" in result.metadata


@pytest.mark.asyncio
async def test_system_config_probe_structure():
    """Verify SystemConfigProbe checks configuration file health."""
    probe = SystemConfigProbe()
    assert probe.probe_id == "system_config"
    assert probe.category == ProbeCategory.RUNTIME
    assert probe.is_blocker is True

    result: ProbeResult = await probe.probe()
    assert isinstance(result, ProbeResult)
    assert result.status in (ProbeStatus.PASS, ProbeStatus.FAIL)
    assert "valid" in result.metadata


@pytest.mark.asyncio
async def test_vision_ocr_probe_structure():
    """Verify VisionOCRProbe returns optional non-blocker status."""
    probe = VisionOCRProbe()
    assert probe.probe_id == "vision_ocr_key"
    assert probe.category == ProbeCategory.CREDENTIALS
    assert probe.is_blocker is False

    result: ProbeResult = await probe.probe()
    assert isinstance(result, ProbeResult)
    assert result.status == ProbeStatus.PASS
    assert "configured" in result.metadata


@pytest.mark.asyncio
async def test_readiness_engine_coalesces_concurrent_full_scans():
    engine = ReadinessEngine()
    result = ProbeResult(
        id="test_probe",
        category=ProbeCategory.RUNTIME,
        title="Test",
        status=ProbeStatus.PASS,
        is_blocker=True,
        summary="Ready",
        description="Ready",
    )

    async def slow_probe():
        await asyncio.sleep(0.01)
        return result

    probe = Mock()
    probe.probe = AsyncMock(side_effect=slow_probe)
    engine._probes = {"test_probe": probe}

    reports = await asyncio.gather(*(engine.run_all() for _ in range(8)))

    assert probe.probe.await_count == 1
    assert all(report.overall_ready for report in reports)


@pytest.mark.asyncio
async def test_readiness_engine_reuses_cache_until_forced():
    engine = ReadinessEngine()
    result = ProbeResult(
        id="test_probe",
        category=ProbeCategory.RUNTIME,
        title="Test",
        status=ProbeStatus.PASS,
        is_blocker=True,
        summary="Ready",
        description="Ready",
    )
    probe = Mock()
    probe.probe = AsyncMock(return_value=result)
    engine._probes = {"test_probe": probe}

    first = await engine.run_all()
    cached = await engine.run_all()
    refreshed = await engine.run_all(force_refresh=True)

    assert probe.probe.await_count == 2
    assert cached.timestamp == first.timestamp
    assert refreshed.timestamp >= first.timestamp


@pytest.mark.asyncio
async def test_invalidation_prevents_in_flight_report_from_becoming_shared_cache():
    engine = ReadinessEngine()
    result = ProbeResult(
        id="test_probe",
        category=ProbeCategory.RUNTIME,
        title="Test",
        status=ProbeStatus.PASS,
        is_blocker=True,
        summary="Ready",
        description="Ready",
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def controlled_probe():
        started.set()
        await release.wait()
        return result

    probe = Mock()
    probe.probe = AsyncMock(side_effect=controlled_probe)
    engine._probes = {"test_probe": probe}

    old_scan = asyncio.create_task(engine.run_all())
    await started.wait()
    engine.invalidate_cache()
    release.set()
    await old_scan
    await engine.run_all()

    assert probe.probe.await_count == 2


@pytest.mark.asyncio
async def test_llm_credentials_probe_structure():
    """Verify LLMCredentialsProbe returns correct category and schema."""
    probe = LLMCredentialsProbe()
    assert probe.probe_id == "gemini_api_key"
    assert probe.category == ProbeCategory.CREDENTIALS
    assert probe.is_blocker is True

    result: ProbeResult = await probe.probe()
    assert isinstance(result, ProbeResult)
    assert result.status in (ProbeStatus.PASS, ProbeStatus.FAIL)
    assert "configured_count" in result.metadata


@pytest.mark.asyncio
async def test_probe_target_serial_forwards_to_adb_probe():
    """Verify the probe target preference reaches the ADB probe and can be cleared."""
    engine = ReadinessEngine()
    engine.set_probe_target_serial("test-emulator-1234")
    assert engine._adb_probe._target_serial == "test-emulator-1234"
    engine.set_probe_target_serial(None)
    assert engine._adb_probe._target_serial is None


@pytest.mark.asyncio
async def test_credentials_probe_and_dynamic_update():
    """Verify dynamic API key updates and metadata reflection."""
    from apollo.config import settings

    settings.set_api_key("google", "test_gemini_key_1234567890", persist_to_env=False)

    probe = LLMCredentialsProbe()
    result = await probe.probe()
    assert result.status == ProbeStatus.PASS
    assert "current_key" in result.metadata
    assert result.metadata["current_key"] == "test_gemini_key_1234567890"
    assert "api_keys" in result.metadata
    assert result.metadata["api_keys"]["google"] == "test_gemini_key_1234567890"


@pytest.mark.asyncio
async def test_build_report_turns_crashing_probe_into_fail_result():
    engine = ReadinessEngine()
    healthy = ProbeResult(
        id="healthy",
        category=ProbeCategory.RUNTIME,
        title="Healthy",
        status=ProbeStatus.PASS,
        is_blocker=True,
        summary="Ready",
        description="Ready",
    )
    good = Mock()
    good.probe_id = "healthy"
    good.category = ProbeCategory.RUNTIME
    good.is_blocker = True
    good.probe = AsyncMock(return_value=healthy)

    bad = Mock()
    bad.probe_id = "integration_host"
    bad.category = ProbeCategory.RUNTIME
    bad.is_blocker = True
    bad.probe = AsyncMock(side_effect=PermissionError(13, "Permission denied", "/ro/traces"))
    engine._probes = {"healthy": good, "integration_host": bad}

    report = await engine._build_report()

    assert report.overall_ready is False
    assert report.blocker_count == 2
    assert report.passed_blocker_count == 1
    by_id = {r.id: r for r in report.probes}
    assert by_id["healthy"].status is ProbeStatus.PASS
    crashed = by_id["integration_host"]
    assert crashed.status is ProbeStatus.FAIL
    assert crashed.is_blocker is True
    assert crashed.category is ProbeCategory.RUNTIME
    assert crashed.summary == "Probe crashed"
    assert "PermissionError" in crashed.description
    assert "Permission denied" in crashed.description
    assert crashed.metadata["exception_type"] == "PermissionError"


@pytest.mark.asyncio
async def test_build_report_does_not_swallow_cancellation():
    engine = ReadinessEngine()
    probe = Mock()
    probe.probe_id = "cancelled"
    probe.category = ProbeCategory.RUNTIME
    probe.is_blocker = True
    probe.probe = AsyncMock(side_effect=asyncio.CancelledError())
    engine._probes = {"cancelled": probe}

    with pytest.raises(asyncio.CancelledError):
        await engine._build_report()
