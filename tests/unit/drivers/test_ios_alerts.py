"""``ios.alerts`` policy applied by the iOS driver before perception."""

import pytest

from apollo.clients.wda_client import ScreenInfo, WdaError
from apollo.drivers.ios.driver import DEFAULT_WDA_SETTINGS, IosDriver

UDID = "5A3587F9-040D-40C5-B3E8-6A29A4286978"


class FakeWda:
    def __init__(self, alert: str | None):
        self.alert = alert
        self.calls: list[str] = []
        self.settings: dict = {}

    async def alert_text(self):
        return self.alert

    async def alert_accept(self):
        self.calls.append("accept")
        self.alert = None

    async def alert_dismiss(self):
        self.calls.append("dismiss")
        self.alert = None

    async def set_settings(self, **settings):
        self.settings.update(settings)
        return self.settings


def _driver(policy: str, alert: str | None, **kwargs) -> tuple[IosDriver, FakeWda]:
    wda = FakeWda(alert)
    screen = ScreenInfo(width_pt=402, height_pt=874, scale=3, status_bar_height_pt=54)
    return IosDriver(UDID, wda=wda, screen=screen, alert_policy=policy, **kwargs), wda


@pytest.mark.asyncio
async def test_observe_leaves_alerts_alone():
    driver, wda = _driver("observe", "“Maps” Would Like to Use Your Location")
    assert await driver.handle_alert() is None
    assert wda.calls == [] and wda.alert is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["accept", "dismiss"])
async def test_accept_and_dismiss_answer_the_sheet(policy, monkeypatch):
    monkeypatch.setattr("apollo.drivers.ios.driver.SETTLE_SECONDS", 0)
    driver, wda = _driver(policy, "Allow notifications?")
    assert await driver.handle_alert() == "Allow notifications?"
    assert wda.calls == [policy] and wda.alert is None
    assert await driver.handle_alert() is None  # nothing left to answer


@pytest.mark.asyncio
async def test_accept_tolerates_wda_errors(monkeypatch):
    driver, wda = _driver("accept", "Allow?")

    async def failing_accept():
        raise WdaError("alert vanished")

    wda.alert_accept = failing_accept
    assert await driver.handle_alert() is None


def test_unknown_policy_falls_back_to_observe():
    driver, _ = _driver("explode", None)
    assert driver._alert_policy == "observe"


def test_configured_wda_settings_merge_over_defaults():
    driver, _ = _driver(
        "observe", None, wda_settings={"snapshotMaxDepth": 40, "waitForIdleTimeout": 2}
    )
    assert driver._wda_settings["snapshotMaxDepth"] == 40
    assert driver._wda_settings["waitForIdleTimeout"] == 2
    assert (
        driver._wda_settings["mjpegServerFramerate"] == DEFAULT_WDA_SETTINGS["mjpegServerFramerate"]
    )
