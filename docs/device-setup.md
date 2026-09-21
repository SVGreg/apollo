# Physical device setup (Phase 3)

What a USB-connected iPhone needs before `apollo run --device-serial <udid>` can drive it. The
simulator needs none of this. Verify each step with `apollo doctor` ("Physical iOS devices" row).

## 1. One-time on the phone

1. **Trust this Mac** — plug in over USB, unlock, tap *Trust*. `xcrun devicectl list devices`
   shows the phone as `available (paired)`; `ios list --details` shows it once it is connected.
2. **Developer Mode** — Settings › Privacy & Security › Developer Mode (the menu appears only
   after Xcode or `ios devmode reveal` has talked to the phone once) → on → reboot → confirm.
   `ios devmode get` must report `DeveloperModeEnabled: true`. Without it the instruments
   services (screenshot, WDA launch) refuse with `DVTSecureSocketProxy unavailable`.
3. **Auto-Lock → Never** (Settings › Display & Brightness) for the duration of a session, or the
   screen locks mid-task and WDA sees the lock screen. Keep the phone unlocked when a task starts.
4. Optional: a fixed passcode is fine; Apollo never types it. Face ID prompts appear as alerts.

## 2. One-time on the Mac

- **Xcode 26.x** with the iOS platform matching the phone's major version installed
  (`xcodebuild -showsdks`; Xcode › Settings › Components).
- **go-ios** (`brew install go-ios`, verified with 1.3.2): device discovery, tunnel, forwarding,
  `runwda`. Nothing needs `sudo` — Apollo uses `ios tunnel start --userspace`.
- **ffmpeg** (`brew install ffmpeg`): device recording is captured from the WDA MJPEG stream.
- **A signing-capable Apple account** — this is the gate found in the Phase 0 spike (S4):
  WebDriverAgent has to be signed for *this* device.
  - *Free personal team* (Xcode › Settings › Accounts): works for personal phones but a free team
    may register at most 3 devices per membership year and cannot remove them. When the cap is hit
    `xcodebuild -allowProvisioningUpdates` fails with *"Your development team has reached the
    maximum number of registered iPhone devices"* — use another Apple ID or a paid team.
  - *Paid team* (lab devices, CI): export a **P12** development certificate and a **development
    provisioning profile** that lists the device; `ios sign app --p12file … --profile …` (or
    `ios ui install wda …`) signs the prebuilt runner without Xcode.
  `apollo doctor` lists the `Apple Development` identities in the keychain.

## 3. How Apollo provisions WDA on a device (RunnerManager device path)

```
ios tunnel start --userspace              # once per Mac session; info API on :60105
sign  → xcodebuild build-for-testing -destination id=<udid> -allowProvisioningUpdates
         DEVELOPMENT_TEAM=<team> (free/paid team)       …or…
         ios sign app --path <runner.app> --p12file <p12> --profile <profile>
ios install --path <signed WebDriverAgentRunner-Runner.app> --udid <udid>
ios runwda --bundleid … --testrunnerbundleid … --xctestconfig WebDriverAgentRunner.xctest
           --env USE_PORT=8100 --env MJPEG_SERVER_PORT=9100 --udid <udid>
ios forward 8100 8100 ; ios forward 9100 9100          # host ↔ device
GET http://127.0.0.1:8100/status                        # ready
```

Every go-ios call carries `--tunnel-info-port=60105` (the CLI default 28100 does not match a
userspace tunnel). `apollo/clients/goios.py` wraps all of the above; signing lands with Phase 3.

## 4. Checklist before the first device run

| Check | Command | Expect |
|---|---|---|
| Phone visible | `ios list --details` | its UDID, `ProductVersion` |
| Developer Mode | `ios devmode get --udid <udid> --tunnel-info-port 60105` | `true` |
| Tunnel | `ios tunnel start --userspace` (background) → `curl :60105/tunnels` | the UDID listed |
| Screenshot | `ios screenshot --udid <udid> --tunnel-info-port 60105 --output /tmp/s.png` | ~2 s, PNG |
| Signing | `security find-identity -v -p codesigning` | an *Apple Development* identity |
| Everything | `apollo doctor` | "Physical iOS devices: 1 attached, Developer Mode on" |

Known device facts (test iPhone 14, iOS 26.6.2): Developer Mode on; the free personal team
`T6VGM6ZBBG` is at its device cap, so WDA signing waits on another Apple ID or a paid team.
