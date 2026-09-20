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

import sys

from typing import Any

try:
    from adbutils import AdbClient
except ImportError:  # Android tooling is optional in Apollo
    AdbClient = Any
from rich.console import Console


def display_device_status(console: Console, adb_client: AdbClient | None = None):
    """Checks for connected devices and displays the status."""
    console.print("\n[bold]📱 Device Status[/bold]")
    # iOS simulators (booted ones are targets; shutdown ones are listed as hints).
    try:
        from apollo.clients import simctl

        sims = simctl.list_devices_sync() if simctl.simctl_available() else []
    except Exception:  # pylint: disable=broad-exception-caught
        sims = []
    booted = [d for d in sims if d.is_booted]
    if booted:
        console.print("✅ [bold green]iOS simulator(s) booted:[/bold green]")
        for dev in booted:
            console.print(f"  - {dev.udid}  {dev.name} (iOS {dev.os_version})")
    elif sims:
        console.print("⚠️  [yellow]No iOS simulator is booted.[/yellow] Available:")
        for dev in sims[:6]:
            console.print(f"  - {dev.udid}  {dev.name} (iOS {dev.os_version})")
        console.print("Boot one with: [bold]xcrun simctl boot <udid>[/bold]")
    devices = None
    if adb_client is not None:
        try:
            devices = adb_client.device_list()
        except Exception:  # pylint: disable=broad-exception-caught
            devices = None
    if booted and not devices:
        return
    if devices:
        console.print("✅ [bold green]Android device(s) connected:[/bold green]")
        for device in devices:
            console.print(f"  - {device.serial}")
    else:
        console.print("❌ [bold red]No Android device found.[/bold red]")
        command = "emulator -avd <avd_name>"
        if sys.platform not in ["win32", "darwin"]:
            command = f"./{command}"
            console.print(
                f"You can start an emulator using a command like: [bold]'{command}'[/bold]"
            )
