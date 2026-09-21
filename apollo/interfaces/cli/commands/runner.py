"""``apollo runner``: manage the WebDriverAgent runner on simulators.

Tasks (and the console live view) provision the runner themselves, so these
commands cover what the automatic path leaves alone: inspecting a simulator,
forcing a reinstall of the pinned build, stopping the runner, and removing it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from rich.console import Console
from rich.table import Table
import typer

from apollo.clients.simctl import SimBridge, SimctlError, list_devices_sync, simctl_available
from apollo.runtime.runner_manager import RunnerError, RunnerManager
from apollo.utils.logger import get_logger

logger = get_logger(__name__)
runner_app = typer.Typer(help="Install, inspect, stop or remove the WebDriverAgent runner.")

UdidOption = Annotated[
    str | None,
    typer.Option("--udid", "-u", help="Simulator UDID. Defaults to the only booted simulator."),
]


def _resolve_udid(udid: str | None) -> str:
    if udid:
        return udid
    if not simctl_available():
        typer.secho("xcrun simctl is not available (install Xcode).", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    booted = list_devices_sync(booted_only=True)
    if len(booted) == 1:
        return booted[0].udid
    if not booted:
        typer.secho(
            "No booted simulator. Boot one (xcrun simctl boot <udid>) or pass --udid.",
            fg=typer.colors.RED,
        )
    else:
        typer.secho(
            "Several simulators are booted; pass --udid: "
            + ", ".join(f"{d.name} {d.udid}" for d in booted),
            fg=typer.colors.RED,
        )
    raise typer.Exit(code=1)


def _bool(value: object) -> str:
    return "[green]yes[/green]" if value else "[red]no[/red]"


@runner_app.command("status")
def runner_status(
    udid: UdidOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Show whether the pinned runner is installed and answering on a simulator."""
    target = _resolve_udid(udid)
    manager = RunnerManager()
    endpoint = manager.endpoint_for(target)
    status = asyncio.run(manager.status(target, port=endpoint.port))
    status["mjpeg_port"] = endpoint.mjpeg_port
    status["bundle_id"] = manager.bundle_id
    status["cached_bundle"] = (manager.simulator_bundle_dir() / "Info.plist").parent.exists()
    if as_json:
        typer.echo(json.dumps(status, indent=2))
        return
    table = Table(title=f"WebDriverAgent runner on {target}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Installed", _bool(status["installed"]))
    table.add_row("Answering", _bool(status["ready"]))
    version = str(status["runner_version"] or "-")
    if status["runner_version"] and status["runner_version"] != status["expected_runner_version"]:
        version += (
            f"  [yellow](pinned v{status['pinned_version']} reports "
            f"{status['expected_runner_version']}; reinstall with --force)[/yellow]"
        )
    table.add_row("Runner version", version)
    table.add_row("Pinned version", str(status["pinned_version"]))
    table.add_row("iOS", str(status["os_version"] or "-"))
    table.add_row("Ports", f"WDA {status['port']}, MJPEG {status['mjpeg_port']}")
    table.add_row("Bundle id", status["bundle_id"])
    table.add_row("Bundle cached on host", _bool(status["cached_bundle"]))
    Console().print(table)


@runner_app.command("install")
def runner_install(
    udid: UdidOption = None,
    force: Annotated[
        bool, typer.Option("--force", help="Uninstall first and re-download the pinned bundle.")
    ] = False,
    start: Annotated[
        bool, typer.Option("--start/--no-start", help="Launch the runner after installing.")
    ] = True,
) -> None:
    """Install the pinned runner on a simulator (booting it if needed) and start it."""
    target = _resolve_udid(udid)
    manager = RunnerManager()

    async def _go() -> None:
        bridge = SimBridge(target)
        device = await bridge.get_device()
        if device is None:
            raise RunnerError(f"Simulator {target} not found")
        if not device.is_booted:
            typer.echo(f"Booting {device.name}…")
            await bridge.boot(wait=True)
        if force:
            typer.echo("Removing the installed runner and cached bundle…")
            await manager.stop(target)
            await bridge.uninstall(manager.bundle_id)
            manager.clear_cache()
        await manager.ensure_installed(bridge)
        typer.secho(f"{target}: runner v{manager.version} installed.", fg=typer.colors.GREEN)
        if start:
            client, endpoint = await manager.ensure_simulator_runner(target)
            await client.aclose()
            typer.secho(
                f"{target}: runner answering on {endpoint.base_url} (MJPEG {endpoint.mjpeg_url}).",
                fg=typer.colors.GREEN,
            )

    try:
        asyncio.run(_go())
    except (RunnerError, SimctlError) as exc:
        typer.secho(f"{target}: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@runner_app.command("stop")
def runner_stop(udid: UdidOption = None) -> None:
    """Terminate the runner process on a simulator (it stays installed)."""
    target = _resolve_udid(udid)
    asyncio.run(RunnerManager().stop(target))
    typer.secho(f"{target}: runner stopped.", fg=typer.colors.GREEN)


@runner_app.command("uninstall")
def runner_uninstall(
    udid: UdidOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    clear_cache: Annotated[
        bool, typer.Option("--clear-cache", help="Also delete the downloaded bundle.")
    ] = False,
) -> None:
    """Remove the runner from a simulator; the next task reinstalls it from the cache."""
    target = _resolve_udid(udid)
    if not yes and not typer.confirm(f"Remove the WebDriverAgent runner from {target}?"):
        raise typer.Exit(code=0)
    manager = RunnerManager()

    async def _go() -> None:
        await manager.stop(target)
        await SimBridge(target).uninstall(manager.bundle_id)

    try:
        asyncio.run(_go())
    except SimctlError as exc:
        typer.secho(f"{target}: uninstall failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    if clear_cache:
        manager.clear_cache()
    typer.secho(f"{target}: runner removed.", fg=typer.colors.GREEN)


__all__ = ["runner_app"]
