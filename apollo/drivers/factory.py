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

"""Device Driver Factory & Registry."""

import os
from typing import TYPE_CHECKING

try:
    from adbutils import AdbClient
except ImportError:  # Android tooling is optional in Apollo
    AdbClient = None

from apollo.config import settings
from apollo.drivers.android.adb_driver import AndroidAdbDriver
from apollo.drivers.base import BaseDeviceDriver
from apollo.drivers.mock.mock_driver import MockDeviceDriver
from apollo.utils.logger import get_logger

if TYPE_CHECKING:
    from apollo.context import ApolloContext

logger = get_logger(__name__)


def create_driver(ctx: "ApolloContext") -> BaseDeviceDriver:
    """Instantiates the appropriate BaseDeviceDriver based on the runtime context."""
    # 1. Cloud mode check. Cloud devices are reached through the gateway's
    # RemoteUIAutomatorClient; APOLLO_HIERARCHY_BACKEND does not apply there
    # because the Accessibility Helper needs a local adb forward.
    if os.environ.get("APOLLO_CLOUD_MODE") == "1":
        if ctx.adb_client is None:
            from cloud_service.virtualization import RemoteAdbClient

            ctx.adb_client = RemoteAdbClient()
        if ctx.ui_adb_client is None:
            from cloud_service.virtualization import RemoteUIAutomatorClient

            ctx.ui_adb_client = RemoteUIAutomatorClient(adb_client=ctx.adb_client)

    # 2. Mock mode check
    if (
        getattr(ctx.device, "mobile_platform", None) == "mock"
        or os.environ.get("APOLLO_MOCK_DRIVER") == "1"
    ):
        return MockDeviceDriver(
            device_id=ctx.device.device_id if ctx.device else "mock-device",
            width=ctx.device.device_width if ctx.device else 1080,
            height=ctx.device.device_height if ctx.device else 2400,
        )

    # 3. iOS simulators and devices (WebDriverAgent + simctl / go-ios)
    platform = getattr(ctx.device, "mobile_platform", None)
    if platform == "ios" or getattr(platform, "value", None) == "ios":
        from apollo.drivers.ios.driver import IosDriver

        ios_cfg = None
        try:
            from apollo.config import load_agent_config

            ios_cfg = load_agent_config().ios
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug(f"iOS config unavailable; using driver defaults: {exc}")
        return IosDriver(
            udid=ctx.device.device_id,
            wda_settings=dict(ios_cfg.wda_settings) if ios_cfg else None,
            alert_policy=ios_cfg.alerts if ios_cfg else "observe",
            recording_backend=ios_cfg.recording_backend if ios_cfg else "auto",
        )

    # 4. Default Android ADB driver
    if ctx.adb_client is None:
        if AdbClient is None:
            raise RuntimeError(
                "Android driver requested but adbutils is not installed; Apollo targets iOS "
                "(use an iOS device platform or APOLLO_MOCK_DRIVER=1)."
            )
        ctx.adb_client = AdbClient(
            host=settings.ADB_HOST or "localhost", port=settings.ADB_PORT or 5037
        )

    return AndroidAdbDriver(
        device_id=ctx.device.device_id,
        adb_client=ctx.adb_client,
        ui_adb_client=getattr(ctx, "ui_adb_client", None),
        width=ctx.device.device_width,
        height=ctx.device.device_height,
    )


def get_driver(ctx: "ApolloContext") -> BaseDeviceDriver:
    """Cached accessor for device driver in the current context."""
    if not hasattr(ctx, "_active_driver") or getattr(ctx, "_active_driver") is None:
        driver = create_driver(ctx)
        setattr(ctx, "_active_driver", driver)
    return getattr(ctx, "_active_driver")
