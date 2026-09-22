"""Runner launch: `/status` decides readiness, not `simctl launch`'s return."""

import pytest

from apollo.clients.simctl import SimctlError
from apollo.runtime.runner_manager import RunnerEndpoint, RunnerManager

ENDPOINT = RunnerEndpoint(udid="sim-udid", port=8100, mjpeg_port=9100)


class FakeBridge:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    async def launch(self, bundle_id, *, child_env=None, terminate_running=False):
        self.calls.append(
            {
                "bundle_id": bundle_id,
                "child_env": child_env,
                "terminate_running": terminate_running,
            }
        )
        if self.error is not None:
            raise self.error
        return 4242


@pytest.mark.asyncio
async def test_launch_passes_the_leased_ports_to_the_runner():
    bridge = FakeBridge()
    await RunnerManager().launch(bridge, ENDPOINT)
    assert bridge.calls == [
        {
            "bundle_id": "com.facebook.WebDriverAgentRunner.xctrunner",
            "child_env": {"USE_PORT": "8100", "MJPEG_SERVER_PORT": "9100"},
            "terminate_running": True,
        }
    ]


@pytest.mark.asyncio
async def test_a_slow_launch_is_left_to_the_status_poll():
    """A loaded host can blow simctl's timeout while WDA is already starting."""
    bridge = FakeBridge(SimctlError("simctl launch … timed out after 60.0s"))
    await RunnerManager().launch(bridge, ENDPOINT)  # must not raise


@pytest.mark.asyncio
async def test_a_real_launch_failure_still_raises():
    bridge = FakeBridge(SimctlError("simctl launch … failed (4): app not installed"))
    with pytest.raises(SimctlError, match="not installed"):
        await RunnerManager().launch(bridge, ENDPOINT)
