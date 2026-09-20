"""Allowlisted host commands exposed to the agent as `run_device_command`.

iOS has no on-device shell. What the agent may run is a small set of host
tools scoped to the current device: ``simctl <sub> …`` (udid inserted) and,
once devices land, ``ios <sub> …``. Everything else is refused with guidance.
"""

import asyncio
import shlex

from apollo.clients.simctl import find_xcrun

# simctl subcommands that are safe for an agent to call against its own device.
SIMCTL_ALLOWED = {
    "openurl",
    "listapps",
    "launch",
    "terminate",
    "get_app_container",
    "appinfo",
    "privacy",
    "status_bar",
    "ui",
    "push",
    "pbcopy",
    "pbpaste",
    "getenv",
    "location",
    "keychain",
    "spawn",
    "io",
    "diagnose",
}
# Subcommands that would drop or mutate the device itself.
SIMCTL_DENIED = {"erase", "delete", "shutdown", "boot", "clone", "create", "install", "uninstall"}

# simctl subcommands whose first positional argument is the device udid.
_UDID_FIRST = SIMCTL_ALLOWED | {"boot", "shutdown", "install", "uninstall", "erase"}

HELP = (
    "Allowed: `simctl <subcommand> [args]` (the device udid is inserted for you), e.g. "
    "`simctl openurl https://example.com`, `simctl listapps`, `simctl launch com.apple.Preferences`, "
    "`simctl privacy grant location com.apple.mobilesafari`, `simctl status_bar override --time 9:41`. "
    "There is no on-device shell on iOS; use the UI actions for everything else."
)


class DeviceCommandError(RuntimeError):
    pass


def build_host_command(command: str, *, udid: str) -> list[str]:
    """Translate an agent command line into an argv on the host, or raise."""
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise DeviceCommandError(f"Could not parse command: {exc}. {HELP}") from exc
    if not parts:
        raise DeviceCommandError(f"Empty command. {HELP}")

    if parts[0] == "xcrun":
        parts = parts[1:]
    if not parts or parts[0] != "simctl":
        raise DeviceCommandError(f"`{parts[0] if parts else ''}` is not available. {HELP}")
    if len(parts) < 2:
        raise DeviceCommandError(f"simctl needs a subcommand. {HELP}")
    sub = parts[1]
    if sub in SIMCTL_DENIED:
        raise DeviceCommandError(f"`simctl {sub}` is not permitted for the agent. {HELP}")
    if sub not in SIMCTL_ALLOWED:
        raise DeviceCommandError(f"`simctl {sub}` is not in the allowlist. {HELP}")
    args = parts[2:]
    # Insert the udid unless the agent already named this device (or "booted").
    if sub in _UDID_FIRST and not (args and args[0] in (udid, "booted")):
        args = [udid, *args]
    elif args and args[0] == "booted":
        args = [udid, *args[1:]]
    xcrun = find_xcrun()
    if xcrun is None:
        raise DeviceCommandError("xcrun not found on this host")
    return [xcrun, "simctl", sub, *args]


async def run_device_command(command: str, *, udid: str, timeout_seconds: float = 15.0) -> str:
    argv = build_host_command(command, udid=udid)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        proc.kill()
        raise DeviceCommandError(
            f"Command did not finish within {timeout_seconds:.0f}s: {' '.join(argv[1:])}"
        ) from None
    text = out.decode(errors="replace")
    if proc.returncode != 0:
        return f"[exit {proc.returncode}] {text.strip()}"
    return text
