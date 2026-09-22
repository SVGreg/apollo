"""Driver-level smoke against a real iOS Simulator (no LLM).

Exercises the whole device stack below the agent: ``simctl`` discovery, WDA
provisioning (download, install, launch, ``/status``), ``/wda/screen``,
screenshot + ``/source`` normalization, app launch/foreground detection and
the HOME button. It is what CI runs on ``macos-26``; locally, run it with

    APOLLO_SIM_UDID=<udid> uv run pytest -m ios_sim tests/integration/test_ios_simulator_smoke.py

or leave ``APOLLO_SIM_UDID`` unset to use the first booted iPhone simulator.
"""

import asyncio
import os
import time

import pytest
import pytest_asyncio

from apollo.clients.simctl import list_devices_sync, simctl_available
from apollo.drivers.ios.driver import IosDriver

pytestmark = pytest.mark.ios_sim

SETTINGS_BUNDLE = "com.apple.Preferences"
SPRINGBOARD_BUNDLE = "com.apple.springboard"


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


async def _wait_for_foreground(driver: IosDriver, bundle_id: str, *, timeout: float = 20.0) -> str:
    """Poll activeAppInfo: a loaded CI host can report SpringBoard for a moment after a launch."""
    deadline = time.monotonic() + timeout
    current = None
    while time.monotonic() < deadline:
        current = await driver.get_current_package()
        if current == bundle_id:
            return current
        await asyncio.sleep(0.5)
    return current or ""


@pytest_asyncio.fixture
async def driver():
    drv = IosDriver(_select_udid())
    await drv.connect()  # boots if needed and provisions WDA from the pinned manifest
    try:
        yield drv
    finally:
        await drv.disconnect()


@pytest.mark.asyncio
async def test_settings_screen_round_trip(driver: IosDriver):
    width, height = driver.screen_size
    assert width > 0 and height > 0 and driver.scale in (2, 3)

    await driver.stop_app(SETTINGS_BUNDLE)  # a resumed Settings may be scrolled or nested
    assert await driver.launch_app(SETTINGS_BUNDLE) is True
    assert await _wait_for_foreground(driver, SETTINGS_BUNDLE) == SETTINGS_BUNDLE

    screen = await driver.get_screen_data()
    assert screen.platform == "ios"
    assert (screen.width, screen.height) == (width, height)
    assert screen.screenshot_bytes[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")
    assert screen.ui_hierarchy_xml, "WDA /source returned nothing"
    texts = {str(el.get("text", "")) for el in screen.ui_elements}
    known_rows = ("General", "Accessibility", "Privacy & Security", "Apps", "Screen Time")
    assert any(row in t for t in texts for row in known_rows), (
        f"Settings rows not found in hierarchy: {sorted(texts)[:20]}"
    )
    assert all(
        el.get("package") == SETTINGS_BUNDLE for el in screen.ui_elements if el.get("package")
    )

    # Hierarchy parity with the screenshot geometry: every element inside the screen,
    # no inverted or negative bounds, and interactive rows carry a label.
    import io
    import re

    from PIL import Image

    shot_w, shot_h = Image.open(io.BytesIO(screen.screenshot_bytes)).size
    assert (shot_w, shot_h) == (width, height), "screenshot pixels disagree with /wda/screen"
    bounds_re = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
    labelled_clickable = 0
    for el in screen.ui_elements:
        m = bounds_re.match(str(el.get("bounds", "")))
        assert m, f"element without bounds: {el}"
        x1, y1, x2, y2 = map(int, m.groups())
        assert 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height, f"bounds off-screen: {el}"
        if el.get("clickable") == "true" and (el.get("text") or el.get("content-desc")):
            labelled_clickable += 1
    assert labelled_clickable >= 5, "expected labelled tappable rows on the Settings screen"

    assert await driver.press_key("HOME") is True
    assert await _wait_for_foreground(driver, SPRINGBOARD_BUNDLE) == SPRINGBOARD_BUNDLE
