# Apollo — architecture

How Apollo drives iOS, and why it is built this way. Everything described as *built* exists in the
tree today; anything still planned is marked. User-facing instructions are in the
[README](../README.md); phase planning is in [`roadmap.md`](roadmap.md).

---

## 1. Shape of the system

Apollo is [google/artemis](https://github.com/google/artemis) with the device layer replaced.
The agent core, the interfaces and the trace format are Artemis's; the driver, the clients, the
diagnostics and the iOS-specific parts of the prompts are Apollo's.

```
                 IDE / CLI / SDK / Web console
   ┌──────────────┬──────────────┬───────────────┬────────────────┐
   │ mcp_server   │ apollo CLI   │ apollo-client │ admin_console  │   inherited; stream +
   │ mobile_*     │ run/ui/mcp/… │ (HTTP/JSON)   │ FastAPI+Angular│   diagnose retargeted
   └──────┬───────┴──────┬───────┴───────┬───────┴───────┬────────┘
          ▼              ▼               ▼               ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ Agent core: Flash / Pro (Planner, Operator, Checker, Explorer, │   inherited;
   │ Safety Net, memory, perception+OCR, action executor, traces)   │   prompt vocabulary edited
   └───────────────────────────────┬───────────────────────────────┘
                                   ▼  BaseDeviceDriver / MobileDeviceController
   ┌───────────────────────────────────────────────────────────────┐
   │ apollo.drivers.ios.IosDriver                                  │   new
   │  ├─ hierarchy.py   XCUIElement tree → UIAutomator XML         │
   │  ├─ input.py       typing / clearing strategies               │
   │  ├─ keymap.py      BACK / HOME / APP_SWITCH / ENTER / DELETE  │
   │  └─ recorder.py    ffmpeg ← WDA MJPEG | simctl recordVideo    │
   └───────┬───────────────────────────────────┬───────────────────┘
           ▼                                   ▼
   ┌────────────────────────┐        ┌────────────────────────────┐
   │ WdaClient  (HTTP)      │        │ SimBridge   xcrun simctl   │   apollo.clients
   │ RunnerManager          │        │ DeviceBridge go-ios (P3)   │
   └───────┬────────────────┘        └───────────┬────────────────┘
           │ :8100 WDA, :9100 MJPEG              │ CLI + tunnel :60105 + usbmux forward
           ▼                                     ▼
     WebDriverAgentRunner                 iOS Simulator  /  iPhone (Phase 3)
     (XCTest bundle, pinned)              (CoreSimulator)   Developer Mode, signed WDA
```

## 2. Key decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Python 3.12+, same as Artemis.** Go appears only as the prebuilt `ios` binary. | The valuable part of Artemis is the agent stack; every iOS primitive is reachable from Python over HTTP (WDA) or subprocess+JSON (`simctl`, `go-ios`). A rewrite would re-implement the agent layer for no device-layer gain. |
| D2 | **Fork and replace the platform layer** — not a plugin, not a rewrite. | Artemis has no plugin registry; an out-of-tree driver cannot reach the controller, diagnostics or streaming. Forking gives parity on day one; the refactors are kept small so upstream can be merged ([`upstream-sync.md`](upstream-sync.md)). |
| D3 | **WebDriverAgent as the on-device runner**, pinned to v16.12.9 with a sha256 in `runner_manifest.json`. | Mature, BSD, unmodified on Xcode 26.6 / iOS 26.2 and 26.5, both simulator and device, MJPEG stream, W3C actions, tunable snapshots. It is the iOS analogue of the Artemis Accessibility Helper. |
| D4 | **Keep Artemis's UIAutomator-style XML as the internal hierarchy contract**; iOS trees are normalized into it at the driver boundary. | Perception, OCR fusion, `filter_ui_hierarchy`, the prompts, the parity tests and the console all consume that schema, so ~all upstream code stays untouched. |
| D5 | **MCP tool names and the action vocabulary stay unchanged** (`mobile_*`, `run_adb_command`); only `BACK`/`APP_SWITCH` semantics are re-mapped. | Drop-in for existing IDE configs and rules; agents need no new schema. |
| D5b | **The Android device layer is deleted, not disabled** (2026-09-22). `upstream` still has it if it is ever wanted back. | A disabled Android path kept producing wrong behaviour on iOS (an emulator boot attempt when no simulator was named) and stale docs, while adding merge surface for no benefit. |
| D6 | **go-ios for physical devices**, `devicectl` as an optional fallback. | MIT, handles the iOS 17+ tunnel in userspace, signs and runs WDA, forwards ports. idb is dead on iOS 17+ devices; pymobiledevice3 is GPL-3. |
| D7 | **idb and DeviceKit stay optional, non-default backends.** | idb is a *perception* accelerator for simulators only (accessibility leaves, ASCII-only input); DeviceKit is young and FSL-licensed. Neither is implemented yet — see [`roadmap.md`](roadmap.md) Phase 4. |

## 3. Artemis → Apollo mapping

| Artemis (Android), for orientation | Apollo (iOS) |
|---|---|
| adb / `adbutils` | `SimBridge` (`xcrun simctl`); `DeviceBridge` (go-ios) for devices |
| Accessibility Helper APK, port 18888 via `adb forward` | WebDriverAgentRunner: `/source`, `/screenshot`, `/session/*/actions`, port 8100 on simulator loopback (or a go-ios forward on devices) |
| uiautomator2 tier | idb `ui describe-all` + HID, simulators only (planned) |
| Accessibility Helper APK provisioning, adb keys, wireless adb, AVD manager | deleted; the runner is provisioned by `RunnerManager` and simulators are booted with `SimulatorManager` |
| ADBKeyboard IME / clipboard paste | WDA `/wda/keys` into the focused field; `setValue` by element; `simctl pbcopy` as a fallback |
| scrcpy recording | ffmpeg capturing the WDA MJPEG stream; `simctl io recordVideo` without ffmpeg |
| `adb exec-out screencap` polling | WDA MJPEG server passthrough; `simctl io screenshot` polling as fallback |
| `monkey … LAUNCHER` / `am force-stop` | WDA `/wda/apps/launch|terminate`, `simctl launch|terminate` |
| `dumpsys window mCurrentFocus` | WDA `/wda/activeAppInfo` (bundle id, pid) |
| `am start -a VIEW -d url` | `simctl openurl`, WDA `POST /session/:id/url` |
| `pm list packages` | `simctl listapps` (+ `plutil` → JSON); `ios apps --list` |
| `input keyevent BACK` | Navigation-bar back control when present, otherwise a left-edge swipe |
| `input keyevent APP_SWITCH` | Swipe up from the home indicator and hold (W3C actions with a pause) |
| `input keyevent HOME` | WDA `/wda/pressButton {"name":"home"}` |
| ENTER / DELETE | `/wda/keys` with `"\n"` / `"\b"` |
| `run_adb_command` | Same tool name; an **allowlist** of `xcrun simctl` subcommands with argument validation. There is no on-device shell |
| emulator manager (AVD) | `SimulatorManager` (`simctl list -j`, boot, shutdown, runtimes) |
| helper_manager (APK provisioning) | `RunnerManager` (download, verify, install, launch WDA; `/status` health; per-device ports) |
| `artemis helper …` | `apollo runner status|install|stop|uninstall` |
| doctor probes (adb keys, server) | probes: Xcode/CLT, simulator runtimes, booted devices, WDA runner, ffmpeg/go-ios/idb, credentials, physical devices |

## 4. The driver

`IosDriver` implements Artemis's `BaseDeviceDriver`, so everything above it is unchanged.

**Coordinates.** Artemis works in screenshot pixels; WebDriverAgent works in points. The driver
keeps pixels on its public surface and divides by `scale` (2× or 3×, read from `/wda/screen`) at
the WDA boundary; the normalizer multiplies hierarchy bounds by `scale` so XML bounds line up with
the screenshot, exactly as on Android.

**Perception** (`get_screen_data`): settle ≈0.3 s → apply the alert policy → fetch the screenshot
and `/source` concurrently → normalize → `filter_ui_hierarchy` (inherited). After `launch_app`,
`/wda/activeAppInfo` is polled until the bundle id matches, otherwise WDA still reports the
SpringBoard tree. When the Safety Net only needs the tree, `get_ui_elements` fetches `/source`
alone — no screenshot, no settle.

**Normalization** (`hierarchy.py`): one `<node>` per XCUIElement with
`class="XCUIElementType…"`, `text` (label or value), `content-desc`, `resource-id` (identifier),
`bounds="[x1,y1][x2,y2]"` in pixels, plus `clickable`, `enabled`, `visible-to-user`, `focused`,
`selected`, `scrollable`, `password` and `package` (the active bundle id). Off-screen and
zero-area nodes are dropped and wrapper elements collapse unless they carry an identifier.

**Text input** (`input.py`): focus the target, clear via the element's `clear` endpoint when an
element id resolves (otherwise backspaces), then type with `/wda/keys`, falling back to
`setValue` for long text. Newlines are `"\n"`: Return submits in a single-line field and inserts a
newline in a text view — the prompts say so.

**Keys** (`keymap.py`): iOS has no system Back key, so `BACK` taps the navigation-bar back control
when one exists and otherwise performs a left-edge swipe; `APP_SWITCH` is a swipe-and-hold from
the home indicator; `HOME` and hardware buttons go through `/wda/pressButton`.

**Alerts**: system sheets are `XCUIElementTypeAlert` nodes, so the Operator can read and tap them.
With `agent.ios.alerts: accept|dismiss` the driver answers them through `/alert/*` before each
perception instead.

**Recording** (`recorder.py`): with ffmpeg, the WDA MJPEG stream is encoded to H.264 at a constant
12 fps with wall-clock timestamps and a 2 s keyframe interval, written as a **fragmented** MP4 so
the Video Analyzer can cut segments out of it mid-run (a `+faststart` file has no moov atom until
ffmpeg exits). Without ffmpeg it falls back to `simctl io recordVideo`, which is
variable-frame-rate — frames are written only when the display changes — and readable only after
the run, so it has no mid-run segments. The 50 %-scaled MJPEG frames are odd-sized, so the
even-size filter (`scale=trunc(iw/2)*2:trunc(ih/2)*2`) is mandatory for x264.

## 5. Runner provisioning

`RunnerManager` owns the WebDriverAgent lifecycle. The pinned build lives in
`apollo/resources/runner_manifest.json` (version, URLs, sha256). On a simulator: download → verify
the checksum → `simctl install` → `simctl launch` with `SIMCTL_CHILD_USE_PORT` and
`SIMCTL_CHILD_MJPEG_SERVER_PORT` → poll `/status`. Ports are allocated per device (8100+n for WDA,
9100+n for MJPEG), which is what lets several simulators run at once. A runner that already
answers is reused across tasks.

> The v16.12.9 release assets report `16.12.8` in `/status`; the manifest records that as
> `reported_version` so the doctor does not flag a correct install.

On a **physical device** (Phase 3) the bundle must additionally be signed — either
`xcodebuild -allowProvisioningUpdates` with a team, or `ios sign app` with a P12 and a
provisioning profile — then installed with `ios install`, run with `ios runwda` and reached
through `ios forward`, with one userspace tunnel per host. See [`device-setup.md`](device-setup.md).

## 6. Sessions, ports and concurrency

`DevicePool` enumerates simulators through `simctl list -j` (devices join it in Phase 3) and leases
them with Artemis's `device_lock`. One long-lived WDA session per device is kept and recreated
automatically on an invalid-session error; transport failures surface as `WdaError` so the driver
can fall back to `simctl` (launching an app, taking a screenshot) instead of failing the step.

CoreSimulator is slow for tens of seconds after a boot on a loaded host, so `simctl` timeouts are
generous and CI warms the subsystem before the tests run. Readiness is always the runner's
`/status`, never a `simctl` command's return: a `simctl launch` that overruns its timeout while
the XCTest bundle is already starting is logged and left to the status poll to confirm or reject. Quitting Simulator.app shuts down every
simulator, including leased ones.

## 7. What changed in the inherited code

Kept deliberately small, so upstream merges stay cheap (the conflict list in
[`upstream-sync.md`](upstream-sync.md) mirrors this table).

| Area | Change |
|---|---|
| `drivers/factory.py` | iOS and mock only; any other platform is a clear error |
| `drivers/android/`, `clients/{accessibility,ui_automator,screen_client_factory,adb_tunnel}`, `runtime/{helper_manager,awake_*,adb_endpoint}`, `core/diagnostics/{adb_keys,adb_server_connection,emulator_manager,device_smoke,hierarchy_parity,probes/adb_probe}`, `apollo helper` | deleted |
| `runtime/device_target.py` | replaces the adb-endpoint lock scoping: the scope is this host, the key is the UDID |
| `runtime/device_pool.py` | enumerates simulators only (devices join in Phase 3); no adb server warm-up |
| `apps/admin_console/routers/system.py` | the console's legacy `/api/system/adb/*` routes answer "not applicable" instead of running adb |
| `controllers/unified_controller.py` | iOS branches for recording start/stop and video segments; `get_ui_elements` prefers a driver fast path |
| `clients/` | New `wda_client.py`, `simctl.py`, `goios.py` |
| `runtime/runner_manager.py` | Replaces `helper_manager` for iOS |
| `core/diagnostics/` | iOS probes (Xcode, simulators, runner, toolchain, credentials, physical devices) feeding `apollo doctor`, `/api/system/readiness` and `mobile_diagnose` |
| `mcp/device_server.py` | Canonical name for the 13-tool raw device server (`adb_server.py` keeps the implementation for merge friendliness) |
| `mcp_server/tools/diagnose.py`, `rules.md` | iOS facts and vocabulary; `launch_avd` boots a simulator |
| `apps/admin_console/services/device_stream_service.py` | WDA MJPEG proxy with `simctl` polling fallback; provisions the runner for viewers |
| `apps/showcase_ui/` | Setup Guide, device panel, labels and task cards for iOS (the only frontend work) |
| Prompts (`agents/*`) | Bundle ids instead of packages, iOS navigation semantics, permission sheets, no intents or shell |
| `config/apollo.jsonc` | `agent.ios.{alerts, recording_backend, wda_settings}`; model defaults |

## 8. Testing

| Layer | What it covers | Where it runs |
|---|---|---|
| Unit (`make test`) | hierarchy normalizer over saved WDA `/source` fixtures, keymap, input strategy, command allowlist, port allocation, readiness probes, recorder commands, video segments, go-ios argument shapes (mocked CLI) | every push, no device |
| Simulator smoke (`make smoke-sim`, `-m ios_sim`) | boot → WDA provisioning → Settings screenshot + hierarchy parity (geometry, bounds, labelled rows) → HOME; the SDK contract against a fake-LLM daemon; a full Flash run with `APOLLO_FAKE_LLM=1` | `macos-26` in CI, no model key |
| Mock smoke (`make smoke-mock`) | the whole agent loop above the driver, no device at all | every push |
| Manual / model-backed | the built-in app task set, Pro cross-app runs | before phase sign-off |

## 9. Measured baselines

From the Phase 0 spikes and later runs on an M-series Mac (Xcode 26.6, iPhone 17 Pro, iOS 26.2):

| Operation | Measurement |
|---|---|
| WDA `/source` | 0.24–0.73 s typical; ~1.1 s on the Calendar month grid; 2.1 s on SpringBoard |
| WDA `/screenshot` | ~0.06 s (PNG, native pixels) |
| Full `get_screen_data` | 0.86–1.39 s including the 0.3 s settle |
| WDA MJPEG at 12 fps / quality 40 / 50 % scale | 10.7–10.9 fps, 50–180 KB per frame, first frame ~0.2 s |
| ffmpeg MJPEG recording | 602×1310 H.264, ~50 KB/s, real-time timeline |
| `simctl io recordVideo` | native 1206×2622, variable frame rate, ~1 MB/s |
| Simulator cold boot | 2–4 minutes on a loaded CI runner; seconds locally |

These are why the snapshot depth is capped at 60, why the Safety Net's hierarchy budget on iOS is
2 s, and why the live view prefers MJPEG over screenshot polling.

## 10. Sources

- Artemis: <https://github.com/google/artemis>
- WebDriverAgent: <https://github.com/appium/WebDriverAgent>; settings reference:
  <https://appium.github.io/appium-xcuitest-driver/latest/reference/settings/>
- go-ios: <https://github.com/danielpaulus/go-ios>
- idb: <https://github.com/facebook/idb>; DeviceKit: <https://github.com/mobile-next/devicekit-ios>
- iOSWorld: <https://github.com/ljang0/iOSWorld> (paper: <https://arxiv.org/abs/2606.09764>)
- Apple: `xcrun simctl`, `xcrun devicectl`
