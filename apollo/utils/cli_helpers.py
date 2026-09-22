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

from rich.console import Console


def display_device_status(console: Console) -> None:
    """Show which simulators are booted, and how to boot one when none is."""
    console.print("\n[bold]📱 Device Status[/bold]")
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
        return
    if sims:
        console.print("⚠️  [yellow]No iOS simulator is booted.[/yellow] Available:")
        for dev in sims[:6]:
            console.print(f"  - {dev.udid}  {dev.name} (iOS {dev.os_version})")
        console.print("Boot one with: [bold]xcrun simctl boot <udid>[/bold]")
        return
    console.print(
        "❌ [bold red]No iOS simulator found.[/bold red] Install a runtime in Xcode › Settings "
        "› Components, then boot one with [bold]xcrun simctl boot <udid>[/bold]."
    )
