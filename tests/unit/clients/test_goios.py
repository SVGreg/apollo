"""go-ios wrapper: argument shapes and output parsing (no device, no CLI)."""

import json

import pytest

from apollo.clients import goios
from apollo.clients.goios import (
    TUNNEL_INFO_PORT,
    DeviceBridge,
    GoIosError,
    IosDevice,
    _base_args,
    _parse_json,
    parse_device_list,
)

UDID = "00008110-001A10AC14B9401E"


def test_parse_device_list_details_and_bare_udids():
    details = json.dumps(
        {
            "deviceList": [
                {
                    "Udid": UDID,
                    "ProductName": "iPhone OS",
                    "ProductType": "iPhone14,7",
                    "ProductVersion": "26.6.2",
                    "DeviceName": "Sergii's iPhone 14",
                }
            ]
        }
    )
    devices = parse_device_list(details)
    assert devices == [
        IosDevice(
            udid=UDID,
            name="Sergii's iPhone 14",
            product_type="iPhone14,7",
            os_version="26.6.2",
            raw=json.loads(details)["deviceList"][0],
        )
    ]
    assert devices[0].is_iphone
    assert parse_device_list('{"deviceList":["' + UDID + '"]}') == [IosDevice(udid=UDID)]
    assert parse_device_list('{"deviceList":[]}') == []


def test_parse_json_takes_the_last_document_of_a_log_stream():
    raw = '{"level":"info","msg":"starting"}\n{"version":"1.3.2"}\n'
    assert _parse_json(raw) == {"version": "1.3.2"}
    assert _parse_json("") == {}
    assert _parse_json("not json") == {"raw": "not json"}


def test_every_tunnel_call_carries_the_agent_info_port():
    assert _base_args(UDID) == [f"--udid={UDID}", f"--tunnel-info-port={TUNNEL_INFO_PORT}"]
    assert _base_args(UDID, tunnel=False) == [f"--udid={UDID}"]
    assert _base_args(None) == [f"--tunnel-info-port={TUNNEL_INFO_PORT}"]


@pytest.mark.asyncio
async def test_bridge_commands_are_shaped_for_go_ios(monkeypatch):
    calls: list[list[str]] = []

    async def fake_run(args, *, timeout=30.0):
        calls.append(args)
        if args[0] == "devmode":
            return json.dumps({"DeveloperModeEnabled": True})
        if args[0] == "apps":
            return json.dumps([{"CFBundleIdentifier": "com.apple.Preferences"}])
        return "{}"

    monkeypatch.setattr(goios, "_run", fake_run)
    bridge = DeviceBridge(UDID)
    assert await bridge.developer_mode_enabled() is True
    assert await bridge.is_installed("com.apple.Preferences")
    assert not await bridge.is_installed("com.example.missing")
    await bridge.install("/tmp/WDA.app")
    await bridge.launch("com.apple.Preferences", kill_existing=True)
    assert await bridge.kill("com.apple.Preferences")

    assert (
        calls[0][:2] == ["devmode", "get"] and f"--tunnel-info-port={TUNNEL_INFO_PORT}" in calls[0]
    )
    assert calls[1][:2] == ["apps", "--list"] and "--tunnel-info-port" not in " ".join(calls[1])
    assert calls[3][:2] == ["install", "--path=/tmp/WDA.app"]
    assert calls[4][:3] == ["launch", "com.apple.Preferences", "--kill-existing"]
    assert calls[5][:2] == ["kill", "com.apple.Preferences"]


@pytest.mark.asyncio
async def test_missing_cli_raises_a_helpful_error(monkeypatch):
    monkeypatch.setattr(goios, "find_ios", lambda: None)
    with pytest.raises(GoIosError, match="brew install go-ios"):
        await goios._run(["list"])
    assert goios.version_sync() is None
