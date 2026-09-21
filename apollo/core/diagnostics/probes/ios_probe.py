"""Readiness probes for the iOS side: Xcode/simctl, simulators, the WDA runner, and the
optional host tools (ffmpeg, go-ios, idb).

These feed `apollo doctor`, the console's readiness report (which gates the Run button)
and `mobile_diagnose`, replacing the adb/emulator/scrcpy probes.
"""

import asyncio
import shutil
import subprocess
from typing import Any

from apollo.clients import simctl
from apollo.core.diagnostics.probes.base import BaseProbe
from apollo.core.diagnostics.schema import ProbeAction, ProbeCategory, ProbeResult, ProbeStatus
from apollo.runtime.runner_manager import RunnerManager, registered_endpoint
from apollo.toolchain import toolchain
from apollo.utils.logger import get_logger

logger = get_logger(__name__)

IOS_DEVICE_PROBE_ID = "ios_device"


async def _xcode_version() -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "xcodebuild",
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        first = out.decode(errors="replace").strip().splitlines()
        return first[0] if first else None
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _device_dict(dev: simctl.SimDevice) -> dict[str, Any]:
    return {
        "serial": dev.udid,
        "state": "device" if dev.is_booted else dev.state.lower(),
        "model": dev.name,
        "product": "simulator",
        "os_version": dev.os_version,
        "is_emulator": True,
    }


class IosDeviceProbe(BaseProbe):
    """Xcode + simctl present, at least one iOS Simulator booted, WDA runner status."""

    def __init__(self, target_serial: str | None = None):
        self._target_serial = target_serial

    @property
    def probe_id(self) -> str:
        return IOS_DEVICE_PROBE_ID

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.DEVICE

    @property
    def is_blocker(self) -> bool:
        return True

    def set_target_serial(self, serial: str | None) -> None:
        self._target_serial = serial

    def invalidate_enrichment_cache(self) -> None:  # parity with the adb probe
        return None

    def _title(self) -> str:
        return "iOS Simulator / Device Connected"

    def _missing_xcode(self, *, submission: bool = False) -> ProbeResult:
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title=self._title(),
            status=ProbeStatus.FAIL,
            is_blocker=True,
            summary="Xcode Not Found",
            description=(
                "`xcrun simctl` is not available. Install Xcode 26.x from the App Store, open it "
                "once to accept the license, then select it for the command line."
            ),
            metadata={"installed": False, "submission_probe": submission},
            actions=[
                ProbeAction(
                    action_type="command",
                    label="Select Xcode",
                    payload="sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept",
                ),
                ProbeAction(
                    action_type="link",
                    label="Download Xcode",
                    payload="https://developer.apple.com/xcode/",
                ),
            ],
        )

    async def _list(self) -> list[simctl.SimDevice] | None:
        try:
            return await asyncio.wait_for(simctl.SimBridge.list_devices(), timeout=15.0)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug(f"simctl list failed: {exc}")
            return None

    def _pick(self, booted: list[simctl.SimDevice]) -> simctl.SimDevice | None:
        if not booted:
            return None
        for dev in booted:
            if dev.udid == self._target_serial:
                return dev
        return booted[0]

    async def _runner_status(self, dev: simctl.SimDevice) -> dict[str, Any]:
        manager = RunnerManager()
        endpoint = registered_endpoint(dev.udid) or manager.endpoint_for(dev.udid)
        try:
            return await asyncio.wait_for(
                manager.status(dev.udid, port=endpoint.port), timeout=10.0
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return {"installed": None, "ready": False, "error": str(exc)}

    async def probe_submission_readiness(self, target_serial: str | None = None) -> ProbeResult:
        """Bounded gate used before enqueueing a task: is a simulator booted?"""
        if not simctl.simctl_available():
            return self._missing_xcode(submission=True)
        devices = await self._list()
        if devices is None:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title=self._title(),
                status=ProbeStatus.WARN,
                is_blocker=True,
                summary="Simulator State Unknown",
                description="`xcrun simctl list` did not answer in time.",
                metadata={"installed": True, "submission_probe": True},
            )
        booted = [d for d in devices if d.is_booted]
        if target_serial and target_serial not in {d.udid for d in booted}:
            known = next((d for d in devices if d.udid == target_serial), None)
            if known is not None:
                # Shutdown but present: the driver boots it on first use.
                booted = [known]
        if not booted:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title=self._title(),
                status=ProbeStatus.WARN,
                is_blocker=True,
                summary="No Simulator Booted",
                description="No iOS Simulator is booted; boot one or pass its UDID.",
                metadata={
                    "installed": True,
                    "submission_probe": True,
                    "devices": [_device_dict(d) for d in devices],
                },
            )
        chosen = self._pick(booted) or booted[0]
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title=self._title(),
            status=ProbeStatus.PASS,
            is_blocker=True,
            summary=f"{chosen.name} (iOS {chosen.os_version})",
            description=f"Simulator {chosen.udid} is ready.",
            metadata={
                "installed": True,
                "submission_probe": True,
                "active_device": _device_dict(chosen),
                "devices": [_device_dict(d) for d in devices],
            },
        )

    async def probe(self) -> ProbeResult:
        if not simctl.simctl_available():
            return self._missing_xcode()

        xcode = await _xcode_version()
        devices = await self._list()
        if devices is None:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title=self._title(),
                status=ProbeStatus.FAIL,
                is_blocker=True,
                summary="simctl Unavailable",
                description="`xcrun simctl list devices` failed. Open Xcode once and accept the license.",
                metadata={"installed": True, "xcode_version": xcode},
                actions=[
                    ProbeAction(
                        action_type="command",
                        label="Accept Xcode license",
                        payload="sudo xcodebuild -license accept && sudo xcodebuild -runFirstLaunch",
                    )
                ],
            )

        booted = [d for d in devices if d.is_booted]
        runtimes = sorted({d.os_version for d in devices})
        metadata: dict[str, Any] = {
            "installed": True,
            "xcode_version": xcode,
            "runtimes": runtimes,
            "device_count": len(devices),
            "booted_count": len(booted),
            "devices": [_device_dict(d) for d in devices],
            # Kept for the console, which renders emulator-launch affordances off these keys.
            "installed_avds": [f"{d.name} ({d.os_version})" for d in devices if not d.is_booted][
                :8
            ],
            "emulator_path": "xcrun simctl boot",
            "is_emulator_in_path": True,
        }

        if not devices:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title=self._title(),
                status=ProbeStatus.FAIL,
                is_blocker=True,
                summary="No iOS Runtime",
                description="No iOS Simulator runtime is installed for this Xcode.",
                metadata=metadata,
                actions=[
                    ProbeAction(
                        action_type="command",
                        label="Install iOS platform",
                        payload="xcodebuild -downloadPlatform iOS",
                    )
                ],
            )

        if not booted:
            actions = [
                ProbeAction(
                    action_type="command",
                    label=f"Boot {d.name} ({d.os_version})",
                    payload=f"xcrun simctl boot {d.udid}",
                )
                for d in devices[:6]
            ]
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title=self._title(),
                status=ProbeStatus.WARN,
                is_blocker=True,
                summary="No Simulator Booted",
                description=(
                    f"{xcode or 'Xcode'} with iOS {', '.join(runtimes)} is installed, but no "
                    "simulator is booted. Boot one (headless is fine) or pass --device-serial; "
                    "Apollo boots a named simulator on first use."
                ),
                metadata=metadata,
                actions=actions,
            )

        chosen = self._pick(booted) or booted[0]
        runner = await self._runner_status(chosen)
        active = _device_dict(chosen)
        try:
            apps = await asyncio.wait_for(simctl.SimBridge(chosen.udid).list_apps(), timeout=10.0)
            active["installed_packages"] = sorted(app.bundle_id for app in apps)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug(f"listapps failed for {chosen.udid}: {exc}")
        metadata["active_device"] = active
        metadata["runner"] = runner
        runner_note = (
            f"WebDriverAgent {runner.get('runner_version') or ''} answering on port {runner.get('port')}"
            if runner.get("ready")
            else "WebDriverAgent will be installed/started on the first task"
        )
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title=self._title(),
            status=ProbeStatus.PASS,
            is_blocker=True,
            summary=f"{chosen.name} (iOS {chosen.os_version})",
            description=(
                f"{len(booted)} booted simulator(s); active: {chosen.name} {chosen.udid}. {runner_note}."
            ),
            metadata=metadata,
            actions=[
                ProbeAction(
                    action_type="hint",
                    label="Keep it running",
                    payload="Quitting Simulator.app shuts down every booted simulator.",
                )
            ],
        )


class IosToolchainProbe(BaseProbe):
    """Optional host tools: ffmpeg (recording), go-ios (physical devices), idb (sim fast path)."""

    @property
    def probe_id(self) -> str:
        return "toolchain"

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.TOOLCHAIN

    @property
    def is_blocker(self) -> bool:
        return False

    async def probe(self) -> ProbeResult:
        ffmpeg_path = toolchain.resolve("ffmpeg")
        ios_path = shutil.which("ios")
        idb_path = shutil.which("idb")
        companion_path = shutil.which("idb_companion")

        go_ios_version = None
        if ios_path:
            try:
                res = subprocess.run(
                    [ios_path, "version"], capture_output=True, text=True, timeout=5, check=False
                )
                for line in res.stdout.splitlines():
                    if '"version"' in line:
                        go_ios_version = line.split(":")[-1].strip(' "}')
            except Exception:  # pylint: disable=broad-exception-caught
                go_ios_version = None

        metadata = {
            "ffmpeg": ffmpeg_path is not None,
            "ffmpeg_path": ffmpeg_path,
            "go_ios": ios_path is not None,
            "go_ios_path": ios_path,
            "go_ios_version": go_ios_version,
            "idb": bool(idb_path and companion_path),
            "idb_path": idb_path,
            # Legacy key the console reads; scrcpy is meaningless on iOS.
            "scrcpy": False,
        }
        installed = [
            name
            for name, ok in (("ffmpeg", ffmpeg_path), ("go-ios", ios_path), ("idb", idb_path))
            if ok
        ]
        missing = [name for name, ok in (("ffmpeg", ffmpeg_path), ("go-ios", ios_path)) if not ok]
        actions: list[ProbeAction] = []
        if not ffmpeg_path:
            actions.append(
                ProbeAction(
                    action_type="command", label="Install ffmpeg", payload="brew install ffmpeg"
                )
            )
        if not ios_path:
            actions.append(
                ProbeAction(
                    action_type="command",
                    label="Install go-ios (physical devices)",
                    payload="npm install -g go-ios",
                )
            )
        if not idb_path:
            actions.append(
                ProbeAction(
                    action_type="command",
                    label="Install idb (optional simulator fast path)",
                    payload="brew trust facebook/fb && brew install facebook/fb/idb",
                )
            )

        if not missing:
            status, summary = ProbeStatus.PASS, "Ready (" + ", ".join(installed) + ")"
            description = (
                "ffmpeg (device recording / MJPEG capture) and go-ios (physical devices) are "
                "available." + (" idb simulator fast path available." if idb_path else "")
            )
        else:
            status, summary = ProbeStatus.WARN, "Missing " + ", ".join(missing)
            description = (
                "Simulators work without these. ffmpeg is needed for device recording and "
                "go-ios for physical iPhones/iPads."
            )
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title="Recording & Device Toolchain",
            status=status,
            is_blocker=False,
            summary=summary,
            description=description,
            metadata=metadata,
            actions=actions,
        )


class IosPhysicalDeviceProbe(BaseProbe):
    """USB iPhones/iPads (Phase 3): go-ios detection, Developer Mode, tunnel, signing identity.

    Never a blocker — simulators are the default target. It exists so `apollo doctor`
    tells the user exactly which of the device prerequisites (Developer Mode + reboot,
    trust/pairing, a signing-capable Apple team) is still missing before a device run.
    """

    @property
    def probe_id(self) -> str:
        return "ios_physical_device"

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.DEVICE

    @property
    def is_blocker(self) -> bool:
        return False

    @staticmethod
    def _signing_identities() -> list[str]:
        try:
            res = subprocess.run(
                ["security", "find-identity", "-v", "-p", "codesigning"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        identities: list[str] = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if '"' in line and ("Apple Development" in line or "iPhone Developer" in line):
                identities.append(line.split('"')[1])
        return identities

    async def probe(self) -> ProbeResult:
        from apollo.clients import goios

        metadata: dict[str, Any] = {"go_ios": goios.goios_available(), "devices": []}
        actions: list[ProbeAction] = []
        if not goios.goios_available():
            actions.append(
                ProbeAction(
                    action_type="command",
                    label="Install go-ios (physical devices)",
                    payload="brew install go-ios",
                )
            )
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Physical iOS devices",
                status=ProbeStatus.WARN,
                is_blocker=False,
                summary="go-ios not installed",
                description="Simulators work without it; USB iPhones need go-ios (Phase 3).",
                metadata=metadata,
                actions=actions,
            )

        metadata["go_ios_version"] = await asyncio.to_thread(goios.version_sync)
        try:
            devices = await asyncio.to_thread(goios.list_devices_sync)
        except goios.GoIosError as exc:
            devices = []
            metadata["error"] = str(exc)
        identities = await asyncio.to_thread(self._signing_identities)
        metadata["signing_identities"] = identities
        tunnel_up = await goios.TunnelAgent.is_running()
        metadata["tunnel_agent"] = tunnel_up

        if not devices:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Physical iOS devices",
                status=ProbeStatus.PASS,
                is_blocker=False,
                summary="No USB device attached (simulators only)",
                description=(
                    "Plug in an iPhone with Developer Mode on and trust this Mac to run tasks on "
                    "hardware. Signing identities on this Mac: "
                    + (", ".join(identities) if identities else "none")
                    + "."
                ),
                metadata=metadata,
                actions=actions,
            )

        problems: list[str] = []
        for dev in devices:
            bridge = goios.DeviceBridge(dev.udid)
            devmode = await bridge.developer_mode_enabled()
            entry = {
                "udid": dev.udid,
                "name": dev.name,
                "product_type": dev.product_type,
                "os_version": dev.os_version,
                "developer_mode": devmode,
            }
            metadata["devices"].append(entry)
            if devmode is False:
                problems.append(f"{dev.name or dev.udid}: Developer Mode is off")
            elif devmode is None:
                problems.append(
                    f"{dev.name or dev.udid}: Developer Mode unknown (locked or untrusted?)"
                )
        if not identities:
            problems.append("no Apple Development signing identity in the keychain")
            actions.append(
                ProbeAction(
                    action_type="link",
                    label="Sign in to Xcode with an Apple ID (Settings › Accounts) to get one",
                    payload="https://developer.apple.com/documentation/xcode/signing-capabilities",
                )
            )
        if any(d["developer_mode"] is False for d in metadata["devices"]):
            actions.append(
                ProbeAction(
                    action_type="link",
                    label="Enable Developer Mode (Settings › Privacy & Security), then reboot",
                    payload="https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device",
                )
            )

        names = ", ".join(
            f"{d['name'] or d['udid']} (iOS {d['os_version']})" for d in metadata["devices"]
        )
        if problems:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Physical iOS devices",
                status=ProbeStatus.WARN,
                is_blocker=False,
                summary=f"{len(devices)} attached; not ready",
                description=f"{names}. " + "; ".join(problems) + ".",
                metadata=metadata,
                actions=actions,
            )
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title="Physical iOS devices",
            status=ProbeStatus.PASS,
            is_blocker=False,
            summary=f"{len(devices)} attached, Developer Mode on",
            description=(
                f"{names}. Signing identity: {identities[0]}. Tunnel agent "
                + ("running" if tunnel_up else "not running (started on demand)")
                + ". WDA on device requires a team that can register this device."
            ),
            metadata=metadata,
            actions=actions,
        )
