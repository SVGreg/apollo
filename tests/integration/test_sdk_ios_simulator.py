"""`apollo-client` SDK contract against a local daemon driving an iOS Simulator (no LLM).

Spawns `apollo ui` on a free port with APOLLO_FAKE_LLM=1, then exercises the remote-only
SDK: readiness, capabilities, device listing (the booted simulator shows as a ready
device), submit → wait (the fake model completes on its first turn), duplicate-submit
idempotency, and scheduler release. Runs in CI's `simulator-smoke` job; locally:

    APOLLO_SIM_UDID=<udid> uv run pytest -m ios_sim tests/integration/test_sdk_ios_simulator.py
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from apollo.clients.simctl import list_devices_sync, simctl_available
from apollo_client import ApolloClient, TaskRejectedError

pytestmark = pytest.mark.ios_sim

REPO_ROOT = Path(__file__).resolve().parents[2]


def _select_udid() -> str:
    explicit = os.environ.get("APOLLO_SIM_UDID", "").strip()
    if explicit:
        return explicit
    if not simctl_available():
        pytest.skip("xcrun simctl is not available on this host")
    booted = [d for d in list_devices_sync(booted_only=True) if "iPhone" in d.name]
    if not booted:
        pytest.skip("No booted iPhone simulator; boot one or set APOLLO_SIM_UDID")
    return booted[0].udid


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def daemon_url():
    port = _free_port()
    env = {**os.environ, "APOLLO_FAKE_LLM": "1"}
    env.setdefault("GOOGLE_API_KEY", "test-placeholder")
    proc = subprocess.Popen(
        [sys.executable, "-m", "apollo.interfaces.cli.main", "ui", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"apollo ui exited early with code {proc.returncode}")
            try:
                if httpx.get(url + "/api/system/readiness", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        else:
            pytest.fail("apollo ui did not become ready within 90 s")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.asyncio
async def test_sdk_runs_a_task_on_the_simulator(daemon_url):
    udid = _select_udid()
    client = ApolloClient(
        daemon_url, device_serial=udid, default_profile="flash", poll_interval=0.5
    )

    assert (await client.health()).get("status") in ("idle", "running", "busy")
    assert (await client.capabilities()).supports("tasks.submit")
    # The daemon's device pool fills in shortly after the readiness endpoint answers.
    deadline = time.monotonic() + 60
    while True:
        devices = await client.list_devices()
        if any(d.serial == udid and d.state == "device" for d in devices):
            break
        assert time.monotonic() < deadline, f"simulator {udid} never listed: {devices}"
        await asyncio.sleep(1.0)

    task_id = str(uuid.uuid4())
    handle = await client.submit("Open Settings", task_id=task_id)
    assert handle.task_id == task_id
    duplicate = await client.submit("Open Settings", task_id=task_id)
    assert duplicate.task_id == task_id  # idempotent resubmit

    result = await client.wait_for_task(task_id, timeout=300)
    assert result.succeeded, result.error or result.raw

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        scheduler = await client.health()
        if scheduler.get("status") == "idle" and not scheduler.get("active_tasks"):
            break
        await asyncio.sleep(0.5)
    else:
        pytest.fail("scheduler did not release the simulator after the task completed")


@pytest.mark.asyncio
async def test_sdk_rejects_unknown_simulator(daemon_url):
    client = ApolloClient(daemon_url, default_profile="flash")
    deadline = time.monotonic() + 60  # wait for the pool so the rejection is a real verdict
    while not await client.list_devices() and time.monotonic() < deadline:
        await asyncio.sleep(1.0)
    with pytest.raises(TaskRejectedError):
        await client.submit("Must never run", device_serial="00000000-0000-0000-0000-000000000000")
