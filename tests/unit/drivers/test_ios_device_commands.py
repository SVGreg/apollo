"""run_device_command allowlist for iOS (there is no on-device shell)."""

import pytest

from apollo.drivers.ios.device_commands import DeviceCommandError, build_host_command

UDID = "5A3587F9-040D-40C5-B3E8-6A29A4286978"


def _tail(argv: list[str]) -> list[str]:
    assert argv[0].endswith("xcrun") and argv[1] == "simctl"
    return argv[2:]


def test_udid_is_inserted_for_device_scoped_subcommands(monkeypatch):
    monkeypatch.setattr("apollo.drivers.ios.device_commands.find_xcrun", lambda: "/usr/bin/xcrun")
    assert _tail(build_host_command("simctl openurl https://example.com", udid=UDID)) == [
        "openurl",
        UDID,
        "https://example.com",
    ]
    assert _tail(build_host_command("xcrun simctl listapps booted", udid=UDID)) == [
        "listapps",
        UDID,
    ]
    assert _tail(build_host_command(f"simctl launch {UDID} com.apple.Preferences", udid=UDID)) == [
        "launch",
        UDID,
        "com.apple.Preferences",
    ]


@pytest.mark.parametrize(
    "command", ["simctl erase", "simctl delete", "simctl shutdown", "simctl boot"]
)
def test_destructive_subcommands_are_refused(monkeypatch, command):
    monkeypatch.setattr("apollo.drivers.ios.device_commands.find_xcrun", lambda: "/usr/bin/xcrun")
    with pytest.raises(DeviceCommandError, match="not permitted"):
        build_host_command(command, udid=UDID)


@pytest.mark.parametrize("command", ["adb shell ls", "ls /", "", "simctl", "simctl frobnicate"])
def test_non_allowlisted_commands_are_refused_with_guidance(monkeypatch, command):
    monkeypatch.setattr("apollo.drivers.ios.device_commands.find_xcrun", lambda: "/usr/bin/xcrun")
    with pytest.raises(DeviceCommandError, match="Allowed"):
        build_host_command(command, udid=UDID)
