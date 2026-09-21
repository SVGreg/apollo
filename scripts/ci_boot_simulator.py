"""Boot one iPhone simulator for the CI integration smoke and print its UDID.

Picks the newest available iOS runtime (or ``APOLLO_SIM_RUNTIME``, e.g. ``26.2``)
and the first iPhone on it (or ``APOLLO_SIM_DEVICE_NAME``), preferring one that
is already booted. Boots it, waits for SpringBoard, appends ``APOLLO_SIM_UDID``
to ``$GITHUB_ENV`` when set, and prints the UDID on stdout.

    uv run python scripts/ci_boot_simulator.py
    export APOLLO_SIM_UDID=$(uv run python scripts/ci_boot_simulator.py)
"""

import json
import os
import re
import subprocess
import sys
import time


def _simctl(*args: str) -> str:
    return subprocess.run(
        ["xcrun", "simctl", *args], check=True, capture_output=True, text=True, timeout=300
    ).stdout


def pick_simulator(
    devices_json: dict, *, runtime: str = "", name: str = ""
) -> tuple[str, str, str]:
    candidates = []
    for runtime_id, devices in devices_json["devices"].items():
        match = re.search(r"iOS-(\d+)-(\d+)$", runtime_id)
        if not match:
            continue
        version = (int(match.group(1)), int(match.group(2)))
        if runtime and f"{version[0]}.{version[1]}" != runtime:
            continue
        for dev in devices:
            if not dev.get("isAvailable", True) or "iPhone" not in dev["name"]:
                continue
            if name and dev["name"] != name:
                continue
            booted = dev["state"] == "Booted"
            candidates.append((not booted, tuple(-v for v in version), dev["name"], dev["udid"]))
    if not candidates:
        raise SystemExit("no available iPhone simulator matches the requested runtime/name")
    candidates.sort()
    _, neg_version, dev_name, udid = candidates[0]
    return udid, dev_name, ".".join(str(-v) for v in neg_version)


def main() -> None:
    devices = json.loads(_simctl("list", "devices", "available", "-j"))
    udid, name, version = pick_simulator(
        devices,
        runtime=os.environ.get("APOLLO_SIM_RUNTIME", ""),
        name=os.environ.get("APOLLO_SIM_DEVICE_NAME", ""),
    )
    print(f"Using {name} (iOS {version}) {udid}", file=sys.stderr)

    state = next(
        d["state"] for devs in devices["devices"].values() for d in devs if d["udid"] == udid
    )
    if state != "Booted":
        _simctl("boot", udid)
    # bootstatus reports on stdout; keep stdout for the UDID alone so callers can capture it.
    subprocess.run(
        ["xcrun", "simctl", "bootstatus", udid, "-b"], check=True, timeout=300, stdout=sys.stderr
    )
    # CoreSimulator stays sluggish for a while after a boot on a loaded runner; one slow
    # `list` here absorbs that so the tests' own calls answer within their budgets.
    started = time.monotonic()
    for args in (["list", "devices", "-j"], ["listapps", udid]):
        subprocess.run(["xcrun", "simctl", *args], check=True, capture_output=True, timeout=300)
    print(f"CoreSimulator responsive after {time.monotonic() - started:.1f}s", file=sys.stderr)
    print(f"CoreSimulator responsive after {time.monotonic() - started:.1f}s", file=sys.stderr)

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"APOLLO_SIM_UDID={udid}\n")
    print(udid)


if __name__ == "__main__":
    main()
