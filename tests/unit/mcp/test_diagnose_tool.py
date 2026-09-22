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

"""Unit tests for the mobile_diagnose MCP tool."""

import asyncio
from contextlib import ExitStack
import inspect
import shutil
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apollo.core.diagnostics.simulator_manager import EmulatorLaunchStage
from apollo.core.diagnostics.probes.host_probe import IntegrationHostProbe
from apollo.core.diagnostics.schema import (
    DeviceInfo,
    ProbeAction,
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
    SystemReadinessReport,
)
from apollo.runtime import trace_store
from apollo.runtime.device_lock import DeviceLockOwner
from mcp_server.tools import diagnose
from mcp_server.tools.diagnose import mobile_diagnose

_IDLE_EMULATOR = {
    "avd_name": None,
    "status": EmulatorLaunchStage.IDLE,
    "pid": None,
    "serial": None,
    "stage_message": "Ready to launch",
    "progress_percent": 0,
    "started_at": None,
    "elapsed_seconds": 0,
    "error": None,
    "logs": [],
    "can_retry": True,
}


def _emulator_state(status: EmulatorLaunchStage, avd: str = "Pixel_8", **extra) -> dict:
    state = dict(_IDLE_EMULATOR)
    state.update(
        {
            "avd_name": avd,
            "status": status,
            "pid": 4242,
            "stage_message": f"stage {status.value}",
            "progress_percent": 30,
            "started_at": time.time() - 12,
            "elapsed_seconds": 12,
            "logs": ["emulator: INFO: boot", "second log line"],
        }
    )
    state.update(extra)
    return state


@pytest.fixture
def temp_trace_env(monkeypatch):
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setattr(trace_store, "TRACES_DIR", temp_dir)
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def _probe(
    probe_id: str,
    status: ProbeStatus,
    *,
    blocker: bool = True,
    category: ProbeCategory = ProbeCategory.RUNTIME,
    summary: str = "",
    description: str = "",
    metadata: dict | None = None,
    actions: list[ProbeAction] | None = None,
) -> ProbeResult:
    return ProbeResult(
        id=probe_id,
        category=category,
        title=probe_id.replace("_", " ").title(),
        status=status,
        is_blocker=blocker,
        summary=summary or status.value,
        description=description or f"{probe_id} is {status.value}",
        metadata=metadata or {},
        actions=actions or [],
    )


def _credentials_metadata() -> dict:
    return {
        "providers": [
            {
                "provider": "google",
                "label": "Gemini",
                "masked": "AIza...abcd",
                "raw_key": "SECRET-GOOGLE",
                "key": "SECRET-GOOGLE",
            },
            {
                "provider": "openai",
                "label": "ChatGPT",
                "masked": "sk-...wxyz",
                "raw_key": "SECRET-OPENAI",
                "key": "SECRET-OPENAI",
            },
        ],
        "api_keys": {
            "google": "SECRET-GOOGLE",
            "gemini": "SECRET-GOOGLE",
            "openai": "SECRET-OPENAI",
            "ocr": "SECRET-OCR",
        },
        "current_key": "SECRET-GOOGLE",
        "current_gemini_key": "SECRET-GOOGLE",
        "has_ocr_key": True,
    }


def _healthy_probes() -> list[ProbeResult]:
    return [
        _probe("python_runtime", ProbeStatus.PASS),
        _probe("system_config", ProbeStatus.PASS),
        _probe("toolchain", ProbeStatus.PASS, blocker=False, category=ProbeCategory.TOOLCHAIN),
        _probe(
            "gemini_api_key",
            ProbeStatus.PASS,
            category=ProbeCategory.CREDENTIALS,
            metadata=_credentials_metadata(),
        ),
        _probe(
            "vision_ocr_key", ProbeStatus.PASS, blocker=False, category=ProbeCategory.CREDENTIALS
        ),
        _probe(
            "ios_device",
            ProbeStatus.PASS,
            category=ProbeCategory.DEVICE,
            metadata={
                "installed": True,
                "installed_avds": [],
                "devices": [
                    {
                        "serial": "sim-1",
                        "state": "device",
                        "name": "iPhone 17 Pro",
                        "installed_packages": ["a", "b", "c"],
                    }
                ],
            },
        ),
    ]


def _no_device_probes(installed_avds: list[str] | None = None) -> list[ProbeResult]:
    probes = _healthy_probes()
    avds = installed_avds if installed_avds is not None else ["Pixel_8", "Tablet_API_35"]
    actions = [
        ProbeAction(
            action_type="command",
            label=f"Launch {avd}",
            payload=f"xcrun simctl boot {avd}",
        )
        for avd in avds
    ] or [
        ProbeAction(
            action_type="command",
            label="Start Default Emulator",
            payload="xcrun simctl boot 'iPhone 17 Pro'",
        )
    ]
    actions.append(
        ProbeAction(
            action_type="hint",
            label="Connect via USB",
            payload="Connect an iPhone via USB and trust this Mac.",
        )
    )
    probes[5] = _probe(
        "ios_device",
        ProbeStatus.WARN,
        category=ProbeCategory.DEVICE,
        summary="No Device",
        description="No booted simulator or attached device was detected.",
        metadata={
            "installed": True,
            "adb_keys": {"is_corrupted": False},
            "installed_avds": avds,
            "devices": [],
        },
        actions=actions,
    )
    return probes


def _host(status: ProbeStatus = ProbeStatus.PASS, **metadata) -> ProbeResult:
    base = {
        "os": "win32",
        "project_root": "/proj",
        "server_python": "/proj/.venv/bin/python",
        "runner_python": "/proj/.venv/bin/python",
        "venv_python": "/proj/.venv/bin/python",
        "venv_exists": True,
        "interpreter_matches_venv": True,
        "env_file": "/proj/.env",
        "env_file_exists": True,
        "traces_dir": "/proj/traces",
        "traces_dir_writable": True,
        "traces_dir_error": None,
        "daemon": {
            "host": "127.0.0.1",
            "port": 8000,
            "standalone_forced": False,
            "reachable": False,
            "port_in_use": False,
            "port_held_by_other_process": False,
            "log_path": "/logs/daemon.log",
        },
    }
    base.update(metadata)
    # Mirrors the real probe: a WARN there degrades, it does not block.
    return _probe("integration_host", status, blocker=status is not ProbeStatus.WARN, metadata=base)


def _report(probes: list[ProbeResult], active_device: DeviceInfo | None = None):
    blockers = [p for p in probes if p.is_blocker]
    passed = [p for p in blockers if p.status is ProbeStatus.PASS]
    return SystemReadinessReport(
        overall_ready=len(blockers) == len(passed),
        blocker_count=len(blockers),
        passed_blocker_count=len(passed),
        probes=probes,
        active_device=active_device,
        os_type="linux",
        timestamp=time.time(),
    )


def _owner(device_id: str = "sim-1", session_id: str = "trace-123") -> DeviceLockOwner:
    return DeviceLockOwner(
        pid=777,
        process_created_at=1.0,
        token="tok-1",
        device_id=device_id,
        description="Open settings and toggle wifi",
        acquired_at="2026-09-09T10:00:00+00:00",
        session_id=session_id,
        ingress="mcp",
        lock_scope=None,
    )


def _run(
    probes,
    host=None,
    *,
    report=None,
    run_all=None,
    emulator_status=None,
    launch=None,
    active_owners=None,
    queued=None,
    cleanup=0,
    validate=None,
    **kwargs,
):
    """Run the tool with every side-effecting collaborator stubbed."""
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                diagnose.readiness_engine,
                "run_all",
                run_all or AsyncMock(return_value=report or _report(probes)),
            )
        )
        stack.enter_context(
            patch.object(IntegrationHostProbe, "probe", AsyncMock(return_value=host or _host()))
        )
        stack.enter_context(
            patch.object(
                diagnose.readiness_engine,
                "get_emulator_status",
                MagicMock(return_value=emulator_status or dict(_IDLE_EMULATOR)),
            )
        )
        stack.enter_context(
            patch.object(
                diagnose.readiness_engine,
                "launch_emulator",
                launch or AsyncMock(return_value=_emulator_state(EmulatorLaunchStage.STARTING)),
            )
        )
        stack.enter_context(
            patch.object(
                diagnose.DeviceExecutionLock,
                "get_active_owners",
                MagicMock(return_value=active_owners or {}),
            )
        )
        stack.enter_context(
            patch.object(
                diagnose.DeviceExecutionLock,
                "get_queued_tasks",
                MagicMock(return_value=queued or []),
            )
        )
        stack.enter_context(
            patch.object(
                diagnose.DeviceExecutionLock,
                "cleanup_stale_locks",
                cleanup if isinstance(cleanup, MagicMock) else MagicMock(return_value=cleanup),
            )
        )
        stack.enter_context(
            patch.object(
                diagnose,
                "validate_api_key",
                validate or AsyncMock(return_value=(True, "verified")),
            )
        )
        return asyncio.run(mobile_diagnose(**kwargs))


# --------------------------------------------------------------------------- #
# Schema / shape
# --------------------------------------------------------------------------- #


def test_host_mcp_client_is_forwarded_when_probe_reports_it(temp_trace_env):
    result = _run(_healthy_probes(), host=_host(mcp_client={"name": "cursor", "key": "SECRET"}))
    assert result["host"]["mcp_client"] == {"name": "cursor"}
    assert result["device"] is None


def test_failing_checks_keep_scrubbed_facts_and_fix_list(temp_trace_env):
    probes = _healthy_probes()
    probes[3].status = ProbeStatus.WARN
    probes[5].status = ProbeStatus.WARN
    result = _run(probes)

    creds = next(c for c in result["checks"] if c["id"] == "gemini_api_key")
    assert creds["category"] == "auth"
    assert creds["facts"]["providers"] == [
        {"provider": "google", "label": "Gemini", "masked": "AIza...abcd"},
        {"provider": "openai", "label": "ChatGPT", "masked": "sk-...wxyz"},
    ]
    assert "api_keys" not in creds["facts"]
    assert creds["fix"] == []
    assert "SECRET" not in repr(result)

    adb = next(c for c in result["checks"] if c["id"] == "ios_device")
    device = adb["facts"]["devices"][0]
    assert device["installed_package_count"] == 3
    assert "installed_packages" not in device


def test_optional_toolchain_failure_is_degraded(temp_trace_env):
    probes = _healthy_probes()
    probes[2] = _probe(
        "toolchain",
        ProbeStatus.FAIL,
        blocker=False,
        category=ProbeCategory.TOOLCHAIN,
        summary="Missing scrcpy",
        description="scrcpy is not installed; video capture is disabled.",
        actions=[
            ProbeAction(action_type="command", label="Install", payload="brew install scrcpy")
        ],
    )
    result = _run(probes)

    assert result["verdict"] == "degraded"
    assert result["next_steps"][0] == (
        "[OPTIONAL] Toolchain: scrcpy is not installed; video capture is disabled."
    )
    assert "  Run: brew install scrcpy" in result["next_steps"]


# --------------------------------------------------------------------------- #
# Command hygiene
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Credentials guidance
# --------------------------------------------------------------------------- #


def test_missing_credentials_point_to_env_file_not_chat(temp_trace_env):
    probes = _healthy_probes()
    probes[3] = _probe(
        "gemini_api_key",
        ProbeStatus.FAIL,
        category=ProbeCategory.CREDENTIALS,
        summary="Key Missing",
        actions=[
            ProbeAction(action_type="command", label="Init", payload="apollo init"),
            ProbeAction(action_type="link", label="Key", payload="https://aistudio.google.com"),
        ],
    )
    result = _run(probes, host=_host(env_file="/home/u/apollo/.env"))

    steps = result["next_steps"]
    assert result["verdict"] == "blocked"
    assert not any(s.strip() == "Run: apollo init" for s in steps)
    assert any("/home/u/apollo/.env" in s and "Never ask them to paste" in s for s in steps)
    assert any("interactive" in s for s in steps)
    assert steps[-1].startswith("After changing the env file")


def test_host_problems_come_before_credentials_and_request_restart(temp_trace_env):
    """A host WARN (interpreter mismatch, missing venv, squatted port) is a
    degradation the runner works around: the verdict is degraded, never
    blocked, so a pip/conda checkout is not stuck in a diagnose loop."""
    host = _host(ProbeStatus.WARN, summary="Host Warning")
    host.actions = [
        ProbeAction(
            action_type="command", label="Regen", payload="uv run apollo mcp --install claude"
        )
    ]
    result = _run(_healthy_probes(), host=host)

    steps = result["next_steps"]
    assert result["verdict"] == "degraded"
    assert steps[0].startswith("[OPTIONAL] Integration Host")
    assert "  Run: uv run apollo mcp --install claude" in steps
    assert "restart the MCP server" in steps[-1]


def test_unwritable_traces_dir_blocks(temp_trace_env):
    host = _host(ProbeStatus.FAIL, summary="Host Misconfigured", traces_dir_writable=False)
    result = _run(_healthy_probes(), host=host)
    assert result["verdict"] == "blocked"
    assert result["next_steps"][0].startswith("[REQUIRED] Integration Host")


# --------------------------------------------------------------------------- #
# Requested device
# --------------------------------------------------------------------------- #


def test_requested_device_missing_blocks_even_when_environment_is_ready(temp_trace_env):
    result = _run(_healthy_probes(), device_serial=" sim-missing ")

    assert result["verdict"] == "blocked"
    assert result["next_steps"][0].startswith(
        "[REQUIRED] Requested device 'sim-missing' is not attached. Attached: sim-1 (device)."
    )


def test_requested_device_attached_and_ready_stays_ready(temp_trace_env):
    result = _run(_healthy_probes(), device_serial="sim-1")
    assert result["verdict"] == "ready"


def test_multiple_ready_devices_ask_user_to_choose(temp_trace_env):
    probes = _healthy_probes()
    probes[5].metadata["devices"].append({"serial": "pixel-2", "state": "device"})
    result = _run(probes)

    assert result["verdict"] == "ready"
    assert any(
        s.startswith("Several devices are ready") and "pixel-2" in s for s in result["next_steps"]
    )


# --------------------------------------------------------------------------- #
# launch_avd
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# verify_credentials
# --------------------------------------------------------------------------- #


def test_verify_credentials_reports_every_provider_without_leaking_keys(temp_trace_env):
    validate = AsyncMock(return_value=(True, "verified"))
    result = _run(_healthy_probes(), validate=validate, verify_credentials=True)

    assert result["verdict"] == "ready"
    assert result["credentials"] == [
        {"provider": "google", "label": "Gemini", "valid": True, "message": "verified"},
        {"provider": "openai", "label": "ChatGPT", "valid": True, "message": "verified"},
        {"provider": "ocr", "label": "Vision OCR", "valid": True, "message": "verified"},
    ]
    called = {call.args[0]: call.args[1] for call in validate.await_args_list}
    assert called == {"google": "SECRET-GOOGLE", "openai": "SECRET-OPENAI", "ocr": "SECRET-OCR"}
    assert all(call.kwargs["timeout"] == 12.0 for call in validate.await_args_list)
    assert "SECRET" not in repr(result)


def test_verify_credentials_calls_endpoint_providers_by_url(temp_trace_env):
    """A custom / Ollama / vLLM entry carries its base URL as the "key": the
    check must hit that endpoint (no auth header) instead of validating the
    URL as if it were an API key."""
    validate = AsyncMock(return_value=(True, "verified"))
    cred = _probe(
        "gemini_api_key",
        ProbeStatus.PASS,
        category=ProbeCategory.CREDENTIALS,
        metadata={
            "providers": [
                {
                    "provider": "ollama",
                    "label": "Local Ollama",
                    "raw_key": "http://localhost:11434/v1",
                },
                {"provider": "google", "label": "Gemini", "raw_key": "SECRET-GOOGLE"},
            ],
            "api_keys": {},
        },
    )
    probes = [p for p in _healthy_probes() if p.id != "gemini_api_key"] + [cred]
    _run(probes, validate=validate, verify_credentials=True)

    calls = {call.args[0]: call for call in validate.await_args_list}
    assert calls["ollama"].args[1] == "EMPTY"
    assert calls["ollama"].kwargs["base_url"] == "http://localhost:11434/v1"
    assert calls["google"].args[1] == "SECRET-GOOGLE"
    assert "base_url" not in calls["google"].kwargs


def test_invalid_primary_credential_blocks_and_redacts_message(temp_trace_env):
    async def _validate(provider, api_key, timeout=12.0):
        if provider == "google":
            return False, f"Gemini API verification failed (400): key {api_key} invalid"
        if provider == "ocr":
            raise RuntimeError("boom SECRET-OCR")
        return True, "ok"

    result = _run(
        _healthy_probes(),
        host=_host(env_file="/home/u/.env"),
        validate=AsyncMock(side_effect=_validate),
        verify_credentials=True,
    )

    assert result["verdict"] == "blocked"
    assert "SECRET" not in repr(result)
    google, openai, ocr = result["credentials"]
    assert google["valid"] is False and "***" in google["message"]
    assert openai["valid"] is True
    assert ocr["valid"] is False and ocr["message"].startswith("verification raised RuntimeError")
    steps = result["next_steps"]
    required = next(s for s in steps if s.startswith("[REQUIRED] Gemini API key (google)"))
    assert "failed live verification" in required
    assert steps[steps.index(required) + 1].startswith("  Ask the user to add a provider key")
    assert any("/home/u/.env" in s for s in steps)
    assert any(s.startswith("[OPTIONAL] Vision OCR API key (ocr)") for s in steps)
    assert steps[-1].startswith("After changing the env file")
    assert "Gemini key verification" in result["summary"]


def test_invalid_secondary_credential_only_degrades(temp_trace_env):
    async def _validate(provider, api_key, timeout=12.0):
        return (provider != "openai", "ok" if provider != "openai" else "401 unauthorized")

    result = _run(
        _healthy_probes(), validate=AsyncMock(side_effect=_validate), verify_credentials=True
    )
    assert result["verdict"] == "degraded"
    assert any(s.startswith("[OPTIONAL] ChatGPT API key (openai)") for s in result["next_steps"])


# --------------------------------------------------------------------------- #
# Task / lock state
# --------------------------------------------------------------------------- #


def test_tasks_surface_active_and_queued_and_busy_device_step(temp_trace_env):
    queued_ticket = {
        "session_id": "trace-456",
        "goal": "Queued goal",
        "device_id": "sim-1",
        "device_serial": "sim-1",
        "adb_endpoint_id": None,
        "pid": 888,
        "token": "tok-2",
        "ingress": "cli",
        "status": "pending",
        "created_at": 1700000000.0,
        "start_time": 1700000000.0,
    }
    result = _run(_healthy_probes(), active_owners={"sim-1": _owner()}, queued=[queued_ticket])

    assert result["tasks"] == {
        "active": [
            {
                "device": "sim-1",
                "session_id": "trace-123",
                "pid": 777,
                "description": "Open settings and toggle wifi",
                "ingress": "mcp",
                "started_at": "2026-09-09T10:00:00+00:00",
            }
        ],
        "queued": [
            {
                "device": "sim-1",
                "session_id": "trace-456",
                "pid": 888,
                "description": "Queued goal",
                "ingress": "cli",
                "created_at": 1700000000.0,
            }
        ],
    }
    assert result["verdict"] == "ready"
    busy = next(s for s in result["next_steps"] if s.startswith("Device 'sim-1' is busy"))
    assert "task trace-123 (pid 777)" in busy
    assert 'mobile_manage_task(action="stop", trace_id="trace-123")' in busy


def test_busy_step_only_for_the_targeted_device(temp_trace_env):
    probes = _healthy_probes()
    probes[5].metadata["devices"].append({"serial": "pixel-2", "state": "device"})

    result = _run(probes, active_owners={"pixel-2": _owner("pixel-2")}, device_serial="sim-1")
    assert not any("is busy" in s for s in result["next_steps"])

    result = _run(probes, active_owners={"pixel-2": _owner("pixel-2")}, device_serial="pixel-2")
    assert any(s.startswith("Device 'pixel-2' is busy") for s in result["next_steps"])

    # Two ready devices and no requested serial: nothing to single out.
    result = _run(probes, active_owners={"pixel-2": _owner("pixel-2")})
    assert not any("is busy" in s for s in result["next_steps"])


# --------------------------------------------------------------------------- #
# attempt_fix
# --------------------------------------------------------------------------- #


def test_attempt_fix_records_stale_lock_cleanup_only_when_something_was_removed(temp_trace_env):
    run_all = AsyncMock(return_value=_report(_healthy_probes()))

    result = _run(_healthy_probes(), run_all=run_all, cleanup=0, attempt_fix=True)
    assert result["fixes_applied"] == []
    assert run_all.await_count == 1

    result = _run(_healthy_probes(), run_all=run_all, cleanup=2, attempt_fix=True)
    assert result["fixes_applied"] == [
        {
            "fix": "cleanup_stale_locks",
            "success": True,
            "skipped": False,
            "message": "removed 2 stale device lock(s) / queue ticket(s)",
        }
    ]
    assert run_all.await_count == 2  # lock cleanup does not change probe results: no re-run
    assert any(s.startswith("Auto-fix cleanup_stale_locks applied") for s in result["next_steps"])

    failing = MagicMock(side_effect=PermissionError("locked dir"))
    result = _run(_healthy_probes(), cleanup=failing, attempt_fix=True)
    assert result["fixes_applied"] == [
        {
            "fix": "cleanup_stale_locks",
            "success": False,
            "skipped": False,
            "message": "cleanup raised PermissionError: locked dir",
        }
    ]

    # Without attempt_fix the cleanup is never attempted.
    failing.reset_mock()
    _run(_healthy_probes(), cleanup=failing)
    failing.assert_not_called()


# --------------------------------------------------------------------------- #
# probe_device
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Timeout / logs
# --------------------------------------------------------------------------- #


def test_logs_surface_recent_errors_and_last_failed_task(temp_trace_env, monkeypatch):
    monkeypatch.setattr(diagnose.env_utils, "get_project_root", lambda: temp_trace_env)
    scratch = diagnose.Path(temp_trace_env) / "scratch"
    scratch.mkdir()
    (scratch / "mcp_stderr.log").write_text(
        "info: booted\n\x1b[33mTraceback (most recent call last):\x1b[0m\nModuleNotFoundError: No module named 'x'\nall good\n",
        encoding="utf-8",
    )
    trace_store.init_trace("ok-trace", "fine", "Flash", None)
    trace_store.update_trace_status("ok-trace", "completed")
    trace_store.init_trace("bad-trace", "broken", "Flash", None)
    trace_store.update_trace_status("bad-trace", "failed", error="adb: device offline")
    with open(trace_store.get_trace_stderr_log_path("bad-trace"), "w", encoding="utf-8") as fh:
        fh.write("starting runner\n")
        fh.write("ERROR adb: device offline\n")
        fh.write("Traceback (most recent call last):\n")
        fh.write("RuntimeError: device offline\n")

    result = _run(_healthy_probes())

    logs = result["logs"]
    assert logs["recent_mcp_errors"] == [
        "Traceback (most recent call last):",
        "ModuleNotFoundError: No module named 'x'",
    ]
    failed = logs["last_failed_task"]
    assert failed["trace_id"] == "bad-trace"
    assert failed["error"] == "adb: device offline"
    assert failed["stderr_log"].endswith("stderr.log")
    assert failed["recent_errors"] == [
        "ERROR adb: device offline",
        "Traceback (most recent call last):",
        "RuntimeError: device offline",
    ]


# --------------------------------------------------------------------------- #
# Accessibility helper (UI hierarchy backend)
# --------------------------------------------------------------------------- #
