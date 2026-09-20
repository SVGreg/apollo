# Apollo — Technical Design

Apollo is the iOS counterpart of [google/artemis](https://github.com/google/artemis): a
natural-language → device-automation framework with a Flash/Pro multi-agent core, an MCP server
for coding assistants, a CLI, a Python SDK, and a web console. Artemis drives Android through
adb + an on-device Accessibility Helper; Apollo drives iOS Simulators and physical iPhones/iPads
through XCTest-based runners (WebDriverAgent) plus Apple's `simctl`/`devicectl` and `go-ios`.

Status: design baseline 2026-09-16, revised 2026-09-20 after the Phase 0 spikes (`spikes.md`).
Companion document: `development-plan.md`.

---

## 1. Goals and non-goals

**Goals**

1. Feature parity with Artemis: same task model (Flash/Pro profiles, Planner/Operator/Checker,
   Safety Net, history compression, verification levels), same interfaces (`apollo run|ui|mcp|
   doctor|batch|trace|server`, MCP tools `mobile_*`, Python SDK, web console with live screen),
   same trace/replay artifacts.
2. iOS Simulator support first-class (macOS host), physical devices (iOS 17–26) second.
3. Same LLM provider matrix (Gemini / Vertex / OpenAI / Anthropic / OpenRouter / xAI / Ollama /
   vLLM / custom) — inherited unchanged.
4. Benchmarkable on an AndroidWorld-style suite for iOS (iOSWorld).
5. Apache-2.0, no copyleft or source-available dependencies in the required path.

**Non-goals**

- Cross-platform (Android+iOS) in one binary. Apollo is iOS-only; it stays structurally close
  to Artemis so the two can converge later if desired.
- Running without a Mac. Simulators need macOS/Xcode; real devices could in principle be
  driven from Linux via go-ios, but that is out of scope for v1 (see §9).

---

## 2. Artemis anatomy (as analysed)

Repository `google/artemis` (Python ≥3.12, Apache-2.0, ~21 commits/week as of Sept 2026).

| Layer | Modules | Notes |
|---|---|---|
| Agents (LangGraph) | `artemis/agents/{planner,operator,checker,explorer,flash,summarizer,validator,video_analyzer,object_detector,diagnoser,log_analyzer,history_analyzer,hopper,outputter,image_processor}` each with `.py` + prompt `.md/.json` | Platform-neutral except vocabulary in prompts (BACK, APP_SWITCH, "package", `run_adb_command`). |
| Graph / perception / memory | `artemis/graph/*`, `artemis/memory/*`, `artemis/data_engine/*` | Perception = screenshot + XML hierarchy (+ optional OCR fused into XML, status-bar cropped). 0–1000 normalized coordinates. |
| Action vocabulary | `artemis/mcp/action_specs.py` (12 actions: click, click_sequence, long_press, input_text, swipe, press_key[ENTER/BACK/HOME/APP_SWITCH], manage_app[launch/stop], wait_for_delay, wait_for_text, open_link, erase_one_char, focus_and_clear_text) | Platform-neutral. |
| Controllers | `artemis/controllers/{device_controller,unified_controller,platform_specific_commands_controller,controller_factory}` | `unified_controller.open_url` shells `am start`; recording uses scrcpy; `platform_specific_commands_controller` uses `pm list packages`, `dumpsys window`. **Needs a platform split.** |
| Drivers | `artemis/drivers/base.py` (`BaseDeviceDriver`, `ScreenData`), `drivers/android/{adb_driver,hierarchy,input_ime,recorder}`, `drivers/mock`, `drivers/cloud`, `drivers/factory.py` | `DeviceInfo.platform` already admits `"ios"`; `factory.create_driver` only knows android/mock/cloud. **Extension point.** |
| Clients | `artemis/clients/{accessibility_client,ui_automator_client,adb_tunnel,screen_client_factory}` | Helper protocol: HTTP over `adb forward`, endpoints `/snapshot`, `/dump_xml`, `/dump`, `/action`, token header. Tier 2 = uiautomator2. |
| MCP actuator server | `artemis/mcp/{adb_server,actuators/*,action_executor}` | 13 low-level tools incl. `run_adb_command` (no allowlist). |
| Runtime | `artemis/runtime/{device_pool,device_lock,helper_manager,awake_service,server_lifecycle,trace_store,daemon_client}` | Helper APK bundled, `adb install -r -g`, `adb forward tcp:0 tcp:18888`. |
| Diagnostics | `artemis/core/diagnostics/{engine,readiness,device_smoke,emulator_manager,adb_keys,adb_server_connection,hierarchy_parity,probes/}` | Android-only probes; framework reusable. |
| Interfaces | `artemis/interfaces/cli/commands/{run,ui,mcp,helper,doctor,batch,trace,server,init}`, `artemis/interfaces/sdk`, `packages/artemis-client` (async HTTP client to daemon) | Neutral except `helper` and `doctor` internals. |
| MCP server (IDE-facing) | `mcp_server/{server,tools/{task_runner,task_manager,device_state,inspect_trace,diagnose},notifiers,rules.md}` | Tools: `mobile_run_task`, `mobile_manage_task`, `mobile_get_device_state`, `mobile_inspect_trace`, `mobile_diagnose`. `diagnose.py` (50 KB) is adb-heavy. |
| Web console | `apps/admin_console` (FastAPI: sessions, steps, traces, replay, media, stream) + `apps/showcase_ui` (Angular) | Live screen = `adb exec-out screencap -p` polling at ~12 fps → MJPEG. |
| Platform bootstrap | `artemis/platform/{darwin,linux,windows}`, `start.sh`, `Makefile install-deps` | Installs adb/scrcpy/ffmpeg/uv. |

**Android-coupled surface (must be replaced):** `drivers/android/*`, `clients/*` (adb),
`mcp/actuators/adb.py`, `mcp/adb_server.py`, `runtime/helper_manager.py`,
`runtime/awake_service.py`, `core/diagnostics/*` (probes), `controllers/platform_specific_commands_controller.py`,
parts of `controllers/unified_controller.py` (open_url, recording), `apps/admin_console/services/device_stream_service.py`,
`interfaces/cli/commands/{helper,doctor}`, `mcp_server/tools/diagnose.py`, `platform/*` installers,
prompt vocabulary in `agents/*/prompts.py` and `mcp_server/rules.md`.

**Platform-neutral surface (reuse as-is):** agents, graph, memory, data_engine, llm, config engine,
action specs/executor, sdk, admin console except streaming, showcase UI, trace store, batch runner.

Roughly 85 % of Artemis by module count is reusable unchanged.

---

## 3. iOS component evaluation

Criteria: simulator support, real-device support (iOS 17–26), accessibility tree, input synthesis,
screenshot/streaming, app lifecycle, Xcode 26 status, license, interop from Python, maintenance.

| Component | Sim | Device | AX tree | Input | Screen / stream | App lifecycle | Xcode 26 / iOS 26 | License | Interop | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **WebDriverAgent** (Appium) | ✔ | ✔ (signed) | ✔ `/source` XML/JSON, tunable (`snapshotMaxDepth`, excluded attrs) | ✔ W3C actions, `/wda/keys`, `/wda/pressButton` | ✔ `/screenshot`; MJPEG server :9100 | ✔ `/wda/apps/*`, `/wda/activeAppInfo`, `/url` | ✔ fixed in WDA 11.4.1 (2026-03) | BSD-3 | HTTP/JSON (httpx) | **Primary on-device runner** (analog of Artemis Helper) |
| **DeviceKit** (mobile-next/devicekit-ios) | ✔ | ✔ | ✔ `device.dump.ui` | ✔ | ✔ PNG/JPEG, MJPEG :12004, H264 | ✔ | ✔ (Xcode 15+) | FSL-1.1 → Apache-2.0 after 2 yrs | JSON-RPC/HTTP+WS | Optional backend behind a flag; not in required path (license, 60 commits) |
| **idb** (Meta) | ✔ | ✗ on iOS 17+ (issue #853 open since 2023) | ✔ sim-only `ui describe-all` (private AX, **accessibility leaves only**, 0.15–0.2 s) | ✔ HID tap/swipe/key; `ui text` ASCII-only | ✔ screenshot, record-video | ✔ | ✔ 1.6.1 via `brew install facebook/fb/idb` | MIT | CLI `--json` only — `fb-idb` (protobuf ≥7.35) conflicts with the Vertex SDK | **Simulator fast path** for a compact element list + HID (analog of uiautomator2 tier) |
| **AXe** (cameroncooke) | ✔ | ✗ | ✔ `describe-ui` JSON | ✔ HID | ✔ | – | ✔ (26/27) | MIT | CLI JSON | Alternative to idb for sim fast path; same frameworks, lighter install. Pick one (idb) |
| **go-ios** (danielpaulus) | ✗ | ✔ iOS ≤26; tunnel (userspace, no sudo, <1 s) | inspector-only (`ios ax`), no bulk dump | via runner (`ios runwda`, `ios ui …`) | ✔ screenshot/MJPEG (needs Developer Mode) | ✔ install/launch/kill/apps | ✔ v1.3.2 (`npm i -g go-ios`; no brew formula) | MIT | CLI `--json` / REST API / Go module | **Real-device bridge** (the "adb" for devices); signs WDA only with a P12+profile or an App Store Connect key — free-team signing goes through `xcodebuild` |
| **pymobiledevice3** | ✗ | ✔ | audit only | via xctest | ✔ | ✔ | ✔ | **GPL-3** | Python lib | Rejected as dependency (copyleft); go-ios covers the same ground |
| **`xcrun simctl`** (Apple) | ✔ | ✗ | ✗ | ✗ | ✔ `io screenshot`, `io recordVideo` | ✔ boot/install/launch/terminate/openurl/clone/pbcopy/privacy/push/status_bar | ✔ | Apple | CLI | **Simulator bridge** |
| **`xcrun devicectl`** (Apple, Xcode 15+) | ✗ | ✔ | ✗ | ✗ | ✗ | ✔ list/install/launch/kill/copy | ✔ | Apple | CLI JSON | Optional official fallback for device app lifecycle; no tunnel needed |
| **mobile-mcp** (mobile-next) | ✔ | ✔ | via WDA | via WDA | via WDA | simctl / go-ios | ✔ | Apache-2.0 | Node | Not reused (Node, flat toolset, no agents); **validates the sim=simctl+WDA, device=go-ios+WDA recipe** |
| **mobilecli** (mobile-next) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | FSL-1.1 | Go CLI/HTTP | Rejected (license; overlaps go-ios+simctl) |
| **Appium XCUITest driver** | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | Apache-2.0 | Node server + W3C HTTP | Not needed at runtime (WDA direct is thinner); used by iOSWorld harness |
| **Maestro** | ✔ | ✔ | own runner | ✔ | ✔ | ✔ | ✔ | Apache-2.0 | YAML CLI | Not needed |

**Benchmarks:** [iOSWorld](https://github.com/ljang0/iOSWorld) (Apache-2.0, 133 tasks, 26 purpose-built
SwiftUI apps, Xcode 26 + iOS 26 simulator, Appium harness, rubric + LLM judge; SOTA 52 % with
Opus 4.6 vision+XML) is the AndroidWorld counterpart. MobileWorld / AndroidDaily are Android-only.

---

## 4. Key decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Implementation language: Python 3.12+** (same as Artemis). Go is used only as prebuilt tool binaries (`ios` from go-ios), never as Apollo source. | The expensive, differentiating part of Artemis is the agent stack (LangGraph, ~100 modules, prompts, memory, MCP, console). Every iOS primitive we need is reachable from Python over HTTP (WDA, DeviceKit), gRPC (idb) or subprocess+JSON (simctl, devicectl, go-ios). A Go rewrite would re-implement the agent layer for no device-layer gain. |
| D2 | **Fork Artemis, replace the platform layer** (not a plugin, not a rewrite). Apollo = Artemis tree with `drivers/android`→`drivers/ios`, adb clients→iOS bridges, Android diagnostics→iOS diagnostics, and a small set of refactors that make controllers/factory platform-dispatched. | Artemis has no plugin registry; a pure out-of-tree driver cannot reach `unified_controller`, `diagnose`, streaming, `helper`. Forking gives exact parity on day one. The refactors are kept minimal and upstream-friendly so Artemis changes can be merged periodically (see §10). |
| D3 | **On-device runner: WebDriverAgent** (Appium fork), pinned at **v16.12.9** (prebuilt `WebDriverAgentRunner-Build-Sim-arm64.zip`, sha256 in `runner_manifest.json`); devices get `xcodebuild -allowProvisioningUpdates` (free team) or go-ios P12 signing. | Mature, BSD, works on Xcode 26.6 / iOS 26.2 and 26.5 unmodified, both targets, MJPEG stream, W3C actions, tunable source. Measured `/source` 0.24–0.73 s on real screens (spikes S1). It is the iOS analog of the Artemis Accessibility Helper. |
| D4 | **Simulator fast path: idb** (`ui describe-all --json`, HID tap/swipe/key) as tier-2 backend on simulators, driven through the CLI (no `fb-idb` dependency). | 2× faster than WDA `/source` and independent of the XCTest session, but it returns accessibility leaves only and types ASCII only — so it is a *perception* accelerator and tap backend, never the text-input path. Optional; WDA alone is sufficient (S1 met the latency target). |
| D5 | **Real-device bridge: go-ios** (`ios` CLI, JSON output). `devicectl` as optional official fallback for install/launch. | MIT, cross-platform, handles iOS 17+ tunnel in userspace, signs and runs WDA, MJPEG screenshots, syslog/crash. idb is dead on iOS 17+ devices; pymobiledevice3 is GPL. |
| D6 | **DeviceKit** supported as an alternate runner behind `ios.runner: devicekit`, not default. | Attractive API (atomic dump, H264) but FSL license and youth. Keeps the door open. |
| D7 | **Keep Artemis's UIAutomator-style XML as the internal hierarchy contract**; iOS trees are normalized into it. | Perception, OCR fusion, `filter_ui_hierarchy`, prompts, hierarchy-parity tests, and the console all consume that schema. Normalizing at the driver boundary keeps ~all upstream code untouched. |
| D8 | **MCP tool names stay `mobile_*`** and the 12-action vocabulary is unchanged; only semantics of `BACK`/`APP_SWITCH` are re-mapped. | Drop-in for existing IDE configs and `rules.md`; agents need no retraining of the tool schema. |
| D9 | **Benchmark: iOSWorld adapter** (`apollo bench iosworld`), keeping iOSWorld's app bootstrap, simulator cloning and rubric judge; Apollo replaces the Appium-driven agent loop. | Same role AndroidWorld plays for Artemis. |

---

## 5. Architecture

```
                 IDE / CLI / SDK / Web console
   ┌──────────────┬──────────────┬───────────────┬────────────────┐
   │ mcp_server   │ apollo CLI   │ apollo-client │ admin_console  │   (Artemis, unchanged
   │ mobile_*     │ run/ui/mcp/… │ (HTTP/JSON)   │ FastAPI+Angular│    except stream+diagnose)
   └──────┬───────┴──────┬───────┴───────┬───────┴───────┬────────┘
          ▼              ▼               ▼               ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ Agent core: Flash / Pro (Planner, Operator, Checker, Explorer, │  (Artemis, unchanged;
   │ Safety Net, memory, perception+OCR, action executor, traces)   │   prompt vocabulary edited)
   └───────────────────────────────┬───────────────────────────────┘
                                   ▼  BaseDeviceDriver / MobileDeviceController
   ┌───────────────────────────────────────────────────────────────┐
   │ apollo.drivers.ios.IosDriver                                   │  (new)
   │  ├─ hierarchy.py   XCUIElement tree → UIAutomator XML          │
   │  ├─ input.py       keys / paste / clear strategies             │
   │  ├─ recorder.py    simctl recordVideo | ffmpeg←MJPEG           │
   │  └─ keymap.py      HOME/BACK/APP_SWITCH/ENTER/DELETE           │
   └───────┬───────────────────┬───────────────────┬───────────────┘
           ▼                   ▼                   ▼
   ┌───────────────┐   ┌───────────────┐   ┌────────────────────────┐
   │ RunnerClient  │   │ SimBridge     │   │ DeviceBridge           │  apollo.clients (new)
   │ WdaClient     │   │ xcrun simctl  │   │ go-ios `ios --json`    │
   │ DeviceKitCli. │   │ idb (opt.)    │   │ devicectl (opt.)       │
   └───────┬───────┘   └───────┬───────┘   └───────────┬────────────┘
           │ HTTP :81xx/:91xx  │ CLI/gRPC              │ CLI + tunnel :60105 + usbmux fwd
           ▼                   ▼                       ▼
     WebDriverAgentRunner   iOS Simulator          iPhone / iPad (Developer Mode, trusted)
     (XCTest bundle)        (CoreSimulator)        WDA signed with team id
```

### 5.1 Artemis ↔ Apollo mapping

| Artemis | Apollo |
|---|---|
| adb / `adbutils` | `SimBridge` (simctl) for simulators; `DeviceBridge` (go-ios) for devices |
| Accessibility Helper APK (`/snapshot`, `/action`, port 18888 via `adb forward`) | WebDriverAgentRunner (`/source`, `/screenshot`, `/session/*/actions`, port 8100 via simulator loopback or go-ios/usbmux forward) |
| uiautomator2 tier | idb `ui describe-all` + HID (simulators only) |
| ADBKeyboard IME / clipboard paste | WDA `/wda/keys` into focused field; `setValue` by element; `simctl pbcopy` / WDA pasteboard + paste as fallback |
| scrcpy recording | `simctl io recordVideo` (sim); `ffmpeg` capturing WDA MJPEG (sim + device) |
| `adb exec-out screencap` polling → MJPEG | WDA MJPEG server passthrough (`mjpegServerFramerate`, `…Quality`); fallback `simctl io screenshot` polling |
| `monkey -p … LAUNCHER` / `am force-stop` | `simctl launch|terminate`, `ios launch|kill`, or WDA `/wda/apps/launch|terminate` |
| `dumpsys window mCurrentFocus` | WDA `/wda/activeAppInfo` (bundleId, pid) |
| `am start -a VIEW -d url` | `simctl openurl` / WDA `POST /session/:id/url` / `ios launch` with URL |
| `pm list packages` | `simctl listapps` (+`plutil` → JSON) / `ios apps --list` / `devicectl device info apps` |
| `input keyevent BACK` | Nav-bar back button via AX (first `XCUIElementTypeButton` in `NavigationBar` with label "Back"/"‹"), else edge swipe from x=2 → 40 % width; in-app "Cancel/Close/Done" heuristics as Safety-Net hint |
| `input keyevent APP_SWITCH` | Swipe up from home indicator and hold (W3C actions with pause); on simulator optionally `simctl` has no equivalent — gesture only |
| `input keyevent HOME` | WDA `/wda/pressButton {"name":"home"}` (also idb `ui button HOME`) |
| ENTER / DELETE | `/wda/keys` with `"\n"` / `"\b"` (XCUIKeyboardKeyDelete) |
| `run_adb_command` tool | `run_device_command` with an **allowlist** of `simctl`, `ios`, `devicectl`, `idb` subcommands and arg validation |
| emulator_manager (AVD boot) | `SimulatorManager` (`simctl list -j`, `boot`, `clone`, `shutdown`, `erase`, runtime discovery) |
| helper_manager (APK provision) | `RunnerManager` (download/verify/install/launch WDA; sign for devices; health `/status`; per-device port allocation) |
| `artemis helper install|uninstall|status` | `apollo runner install|uninstall|status|build` |
| doctor probes (adb keys, server, smoke) | probes: Xcode/CLT, simulator runtimes, WDA bundle & version, hardware-keyboard setting, idb companion, go-ios version/tunnel, Developer Mode, pairing/trust, signing identity, `/status` round-trip, hierarchy-parity smoke |

---

## 6. Device layer design

### 6.1 `IosDriver` (implements `BaseDeviceDriver`)

```python
class IosDriver(BaseDeviceDriver):
    def __init__(self, target: IosTarget, runner: RunnerClient, bridge: SimBridge | DeviceBridge,
                 fast_path: IdbClient | None, settings: IosSettings): ...
    device_id -> udid
    screen_size -> (pixel_w, pixel_h)               # from /wda/screen (points × scale)
    connect()      # ensure target booted/paired, runner installed+running, session created
    get_screen_data(skip_settling)                   # §6.3
    tap/long_press/swipe/swipe_direction             # W3C actions in points (pixels ÷ scale)
    input_text(text, clear_existing)                 # §6.4
    press_key(key)                                   # keymap.py
    launch_app/stop_app/get_current_package          # bridge first, WDA fallback
    execute_shell(cmd)                               # routed to run_device_command allowlist
    start/stop_video_recording                       # recorder.py
```

`IosTarget` = `{udid, kind: simulator|device, name, os_version, model, scale, runner_port, mjpeg_port, tunnel_port}`.

**Coordinate system.** Artemis works in screenshot pixels and 0–1000 normalized units. WDA
accepts *points*. `IosDriver` keeps pixels externally and divides by `scale` (2×/3×) at the
WDA boundary; hierarchy bounds are multiplied by `scale` when normalizing so XML bounds match
the screenshot, exactly as on Android.

### 6.2 Backends

- **`WdaClient`** (`httpx`, async): `/status`, session create with `{"capabilities":{"alwaysMatch":{"platformName":"iOS","bundleId"?:…}}}`, `/screenshot`, `/source?format=xml`, `/session/:id/actions` (pointer sequences for tap/long-press/drag), `/wda/keys`, `/wda/pressButton`, `/wda/apps/{launch,terminate,activate,state}`, `/wda/activeAppInfo`, `/url`, `/alert/{text,accept,dismiss}`, `/wda/screen`, `/appium/settings` (set `snapshotMaxDepth`, `pageSourceExcludedAttributes`, `mjpegServerFramerate/Quality`, `waitForIdleTimeout`). One long-lived session per device; auto-recreate on 404/invalid session.
- **`DeviceKitClient`** (optional): JSON-RPC `device.dump.ui`, `device.io.*`, `device.screenshot`, `/mjpeg`.
- **`SimBridge`**: `xcrun simctl` wrappers with `-j` where available; `listapps` → `plutil -convert json`; `io screenshot --type=png`; `io recordVideo --codec=h264`; `openurl`; `pbcopy`; `privacy grant`; `status_bar override`; `clone` for parallel benchmark runs; `spawn … defaults write com.apple.Preferences`… for keyboard settings.
- **`DeviceBridge`**: `ios --udid … --json` for `list`, `info`, `apps --list`, `install --path`, `launch`, `kill`, `screenshot`, `syslog`, `crash`, `forward`, `tunnel start --userspace`, `ui download|install|run wda`, `devmodearm`, `pair`. Managed `tunnel` process per host (iOS ≥17). `devicectl` used only if `ios` is missing or fails for install/launch.
- **`IdbClient`** (optional, simulators): subprocess `idb … --udid … --json` (companion auto-spawns, ~5 s cold): `ui describe-all --nested`, `ui tap`, `ui swipe`, `ui key`, `ui button`, `screenshot`, `launch`, `terminate`. No `ui text` (ASCII-only) — text goes through WDA.

### 6.3 Screen data pipeline

1. Settle 0.3 s (as Artemis) unless `skip_settling`.
2. Hierarchy source by tier (config `ios.hierarchy_backend`, default `auto`):
   1. WDA `/source` (XML). Settings: `snapshotMaxDepth` 60, exclude `visible`? **No** — `visible` is needed for filtering; instead exclude `accessible`,`index` and cap `snapshotMaxChildren` 200. Timeout 8 s.
   2. On simulators, idb `describe-all` if WDA source exceeds 3 s twice in a row or errors (tier switch is sticky per task, logged). idb yields a flat accessibility-leaf list (Heading/Button/TextField… with label, value, frame in points), which the normalizer wraps as leaf `<node>`s under a synthetic root.
   3. DeviceKit `device.dump.ui` if selected runner.
3. Screenshot: WDA `/screenshot` (PNG, 0.06 s, native pixels). On simulators `simctl io screenshot` is used when WDA is busy (parallel); both return native pixels.
   **After `launch_app`, poll `/wda/activeAppInfo` until `bundleId` matches before the first dump** — otherwise WDA returns the Springboard tree (S1).
4. Normalize to UIAutomator XML (`hierarchy.py`): one `<node>` per XCUIElement with
   `class="XCUIElementType<Type>"`, `text=label|value`, `content-desc=label`, `resource-id=identifier`
   (AXUniqueId / `name` when it differs from label), `bounds="[x1,y1][x2,y2]"` in pixels,
   `clickable` (Button, Cell, Link, Switch, TextField, SecureTextField, SearchField, Image with
   identifier, Icon, Tab, MenuItem, Key…), `enabled`, `visible-to-user` (=`visible`), `focused`,
   `selected`, `scrollable` (ScrollView/Table/CollectionView), `password` (SecureTextField),
   `package`=active bundleId, `index`. Off-screen and zero-area nodes dropped, Window/Other wrappers
   collapsed unless they carry an identifier. Artemis's `filter_ui_hierarchy` then runs unchanged.
5. Status bar: `/wda/screen` returns `statusBarSize` (54 pt on iPhone 17 Pro) and `scale`; `IosDriver` multiplies by scale for perception's OCR crop. No model table needed.
6. Atomicity: WDA has no combined snapshot; Apollo captures screenshot → source back-to-back and
   stamps both; DeviceKit provides a single call. Drift is acceptable (same as Artemis's pre-Android-11 path).

### 6.4 Text input strategy (`input.py`)

1. If `target` given: tap to focus; if `clear_existing`: element `clear` via WDA when an element id
   is resolvable from the tree (`/session/:id/element/:eid/clear`, 0.9 s), else send
   `"\b"×len(value)` using the value from the tree.
2. Type: `/wda/keys {"value": [text]}` (XCTest `typeText`; Unicode OK; needs software keyboard —
   doctor enforces `ConnectHardwareKeyboard=0` on simulators).
3. Fallback for long/multiline text: element `setValue` (`POST /element/:eid/value`, Unicode OK,
   works on simulators and devices). Pasteboard (`/wda/setPasteboard`) is available but paste needs a
   long-press menu, so it is not used by default.
4. Newlines → `"\n"` — in a single-line `TextField` Return moves focus/submits, in a `TextView` it
   inserts a newline; the Operator prompt says so. `erase_one_char` → `"\b"`.
5. Never `POST /wda/element/:id/scroll` with a predicate (60 s timeouts observed); scroll with W3C
   `actions` swipes (0.3–0.5 s).

### 6.5 App identity

`manage_app.app_name` → bundle id resolution: exact bundle id → display-name match from
`listapps` (case-insensitive, then fuzzy ≥0.8) → well-known table (`Settings`=`com.apple.Preferences`,
`Safari`=`com.apple.mobilesafari`, `Messages`, `Mail`, `Photos`, `Calendar`, `Notes`, `Maps`, …).
`get_current_package` returns the active bundle id.

### 6.6 Alerts and permissions

System permission sheets (location, notifications, camera…) are XCUIElementTypeAlert in the tree, so
the Operator sees and taps them like any element. Additionally: `wait_for_text`/Safety Net gain an
`auto_alert` policy (config `ios.alerts: observe|accept|dismiss`) applied via `/alert/*` before each
perception when enabled, and `simctl privacy grant` is offered in task presets for simulators.

### 6.7 Streaming and recording

- Console live view: `device_stream_service` proxies WDA MJPEG (`http://127.0.0.1:<mjpeg_port>`),
  10–15 fps, quality 40. If WDA is down: `simctl io screenshot` polling (sim) / `ios screenshot`.
- Recording (`recorder.py`): simulator → `simctl io recordVideo --codec=h264 -f out.mp4` (H.264,
  **variable frame rate: frames are written only when the display changes**, so a static screen
  yields one frame); device → `ffmpeg -use_wallclock_as_timestamps 1 -f mjpeg -i http://127.0.0.1:<mjpeg_port>
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p out.mp4` (the even-size filter is
  mandatory: scaled MJPEG frames have odd dimensions). Segment metadata (Artemis
  `extract_segment_metadata`) must use presentation timestamps, not frame counts.

### 6.8 Device pool, ports, concurrency

`DevicePool` enumerates `simctl list -j devices` (booted or bootable) and `ios list --json`;
each lease allocates `runner_port` 8100+n, `mjpeg_port` 9100+n, passed to the simulator runner as
`SIMCTL_CHILD_USE_PORT` / `SIMCTL_CHILD_MJPEG_SERVER_PORT` on `simctl launch` (verified: two WDAs on
8100/8101); devices need `ios forward <host> 8100` (usbmux) per lease. One go-ios tunnel daemon
per host (`ios tunnel start --userspace`, info API :60105) serves all iOS-17+ devices. Locks reuse
Artemis `device_lock`. `simctl clone` only accepts a **shutdown** source, so parallel runs clone
from a shutdown template device and install WDA on each clone. Never quit Simulator.app while
simulators are leased — quitting it shuts them all down.

### 6.9 Runner provisioning (`RunnerManager`)

- Pinned WDA version in `apollo/resources/runner_manifest.json` (version, sha256, URLs of Appium's
  `WebDriverAgentRunner-Runner.app` simulator zips; git tag for device builds).
- Simulator: download zip → verify → `simctl install` → `simctl launch com.facebook.WebDriverAgentRunner.xctrunner`
  → poll `/status`. (Same recipe mobile-mcp validated.)
- Device, two signing routes: (a) default, free personal team — `xcodebuild -project
  WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner -destination id=<udid>
  -allowProvisioningUpdates DEVELOPMENT_TEAM=<team> build-for-testing`, install the runner with `ios
  install`; (b) labs/CI — `ios ui download wda` + `ios sign app --p12file … --profile … --install`.
  Then `ios runwda` (needs `ios tunnel start --userspace` running) and `ios forward 8100 8100`.
  Prerequisites the doctor checks: Developer Mode (`ios devmode get`; on a passcode-locked phone
  `ios devmode enable` only reveals the Settings menu — the user toggles and reboots), CoreDevice
  pairing (`devicectl list devices`), a codesigning identity (`security find-identity -p codesigning`), and the team's registered-device quota (free teams: 3/year, non-removable — the S4 blocker).
- Health: `/status` sessionless probe; restart on 3 consecutive failures; `apollo runner status`.

---

## 7. Changes to the inherited (Artemis) code

| Area | Change |
|---|---|
| `drivers/factory.py` | Dispatch on `ctx.device.mobile_platform` (`ios`, `mock`, `cloud`); `ios` → `IosDriver`. Env `APOLLO_MOCK_DRIVER`, `APOLLO_CLOUD_MODE`. |
| `controllers/unified_controller.py` | `open_url` → `driver.open_url()` (new method on driver; Android impl keeps `am start`); recording → `driver.recorder`. Remove scrcpy import. |
| `controllers/platform_specific_commands_controller.py` | Becomes a thin protocol with `IosPlatformCommands` (list apps, foreground app, device date via `simctl`/`ios`/WDA). |
| `mcp/adb_server.py` → `mcp/device_server.py`, `mcp/actuators/ios.py` | Same 13 tools; `back` implemented via keymap; `run_device_command` allowlisted. |
| `clients/*` | Replace with `wda_client.py`, `devicekit_client.py`, `simctl.py`, `goios.py`, `devicectl.py`, `idb_client.py`, `runner_manager.py`. |
| `runtime/helper_manager.py`, `awake_service.py` | `runner_manager.py`; awake → `simctl` idle timer off / WDA `waitForIdleTimeout`; device: disable auto-lock via `ios mdm`? No — document "Auto-Lock: Never" as a doctor check + Settings deep link `App-prefs:` reminder. |
| `core/diagnostics/*` | New probes (§5.1 last row); `emulator_manager.py` → `simulator_manager.py`; `hierarchy_parity.py` kept and pointed at the normalizer (golden XML fixtures for known screens). |
| `mcp_server/tools/diagnose.py` | Re-target probes; `launch_avd` → `boot_simulator`. |
| `interfaces/cli/commands/{helper→runner, doctor}` | As above. New `bench` command. |
| `apps/admin_console/services/device_stream_service.py` | MJPEG proxy. |
| `platform/{darwin,linux,windows}.py`, `start.sh`, `Makefile install-deps` | Install: Xcode CLT check, `brew install facebook/fb/idb` (opt.), `go-ios` (brew or npm), `ffmpeg`, `uv`. Linux/Windows: devices-only mode stub (not v1). |
| Prompts (`agents/*/prompts.py`, `*.md`, `mcp_server/rules.md`) | Vocabulary: "package"→"bundle id", BACK semantics ("iOS has no system back: use the navigation bar back control or edge swipe; expect Cancel/Done/Close"), APP_SWITCH gesture, Control Center / Notification Center swipes, permission sheets, iOS keyboard behaviours ("return" key labels), Home indicator, no intents. |
| `config/artemis.jsonc` → `apollo.jsonc` | Add `device.platform: "ios"`, `ios.runner`, `ios.hierarchy_backend`, `ios.wda.{version,port_base,mjpeg_port_base,snapshot_max_depth}`, `ios.signing.{team_id,identity}`, `ios.tunnel.mode: userspace`, `ios.alerts`, `ios.prefer_devicectl`. |
| Package naming | `artemis` → `apollo` package; `artemis-client` → `apollo-client`; CLI `apollo`; env prefix `APOLLO_`. Keep Apache-2.0, add NOTICE crediting Google LLC (Artemis) and Minitap (mobile-use). |

---

## 8. Interfaces (parity checklist)

- CLI: `apollo run "<task>" [--profile flash|pro] [--device <udid>] [--verification-level …] [--explorer-mode …]`,
  `apollo ui`, `apollo mcp --install [claude|codex|cursor|antigravity|all]`, `apollo runner install|status|uninstall`,
  `apollo doctor [--probe-device] [--boot-simulator <name>]`, `apollo batch`, `apollo trace`, `apollo server|restart|stop|status`, `apollo bench iosworld`.
- MCP (IDE-facing): `mobile_run_task`, `mobile_manage_task`, `mobile_get_device_state`, `mobile_inspect_trace`, `mobile_diagnose` — identical schemas; `device_serial` accepts simulator or device UDID.
- SDK: `ApolloClient(url, token)` with `health/readiness/capabilities/list_devices/submit/get_task/wait_for_task/run/stop`.
- Web console: unchanged UI; live view via MJPEG proxy; replay from traces.
- Docker: simulators cannot run in Linux containers; the `playground` deployment is replaced by a macOS-host runbook (and optional EC2 Mac, as iOSWorld uses).

---

## 9. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| WDA `/source` latency on deep trees (seconds) | slows Flash loop | depth/children caps, excluded attributes, idb fast path on sims, sticky tier switching, `activeAppInfo`-scoped session |
| XCTest changes with each Xcode (WDA broke on Xcode 26 until 11.4.1) | runner outage after Xcode update | pin WDA + Xcode matrix in `runner_manifest.json`; doctor blocks unsupported combos; CI job on latest Xcode beta |
| Real-device friction: Developer Mode, trust, signing, Auto-Lock, tunnel | onboarding failures | `apollo doctor --probe-device` with ordered `next_steps`; go-ios signing; documented checklist |
| idb private-API fragility / device support dead | tier-2 unavailable | optional; WDA-only path is always complete |
| DeviceKit FSL license | legal | off by default, never vendored, user-installed |
| Python 3.14 on host vs Artemis deps (langgraph, opencv, grpc) | install failures | `uv` pins Python 3.12/3.13 in `.python-version`; CI matrix |
| Artemis upstream churn (~21 commits/week) | merge cost | keep refactors small; `upstream` remote + monthly sync; `docs/upstream-sync.md`; prefer additive files over edits |
| iOS has no "force stop" of arbitrary apps on device without WDA | `manage_app stop` partial | `ios kill` (go-ios) works for any pid; WDA `terminate` for launched apps; document |
| No intents / deep control (Android `am`, `settings put`) | some Artemis tricks unavailable | simulator: `simctl privacy/status_bar/push/pbcopy`; device: Settings deep links `App-prefs:`; prompt guidance |
| Parallel simulators contend for CPU/WDA ports | benchmark throughput | `simctl clone`, port allocator, concurrency cap in config |
| Cython in Artemis build | packaging | build pure-Python by default; Cython optional |

---

## 10. Repository layout (Apollo)

```
apollo/
├── apollo/                    # forked artemis/ package, renamed
│   ├── agents/  graph/  memory/  data_engine/  llm/  config/  sdk/  (unchanged)
│   ├── drivers/{base.py, factory.py, ios/{driver.py,hierarchy.py,input.py,keymap.py,recorder.py}, mock/}
│   ├── clients/{wda_client.py, devicekit_client.py, simctl.py, goios.py, devicectl.py, idb_client.py, runner_manager.py}
│   ├── controllers/  mcp/{device_server.py, actuators/ios.py, …}  runtime/  core/diagnostics/
│   ├── interfaces/cli/commands/{…, runner.py, bench.py}
│   ├── platform/  resources/{config/apollo.jsonc, runner_manifest.json, showcase_ui/}
├── mcp_server/                # tools re-targeted, rules.md (iOS)
├── packages/apollo-client/
├── apps/{admin_console, showcase_ui}
├── bench/iosworld/            # adapter, task import, trajectory export
├── tests/{unit, integration, e2e, fixtures/wda_source/*.xml, fixtures/idb/*.json}
├── docs/{technical-design.md, development-plan.md, upstream-sync.md, device-setup.md}
├── scripts/, start.sh, Makefile, pyproject.toml, NOTICE, LICENSE
```

**Upstream sync:** `git remote add upstream https://github.com/google/artemis`; Apollo's first commit
is an unmodified import of Artemis at a recorded SHA, then rename and platform commits. Monthly
`git merge upstream/main` with conflicts confined to the files in §7.

---

## 11. Testing strategy

- **Unit**: hierarchy normalizer against recorded WDA `/source` fixtures (Settings, Safari, Messages,
  iOSWorld apps) and idb `describe-all` fixtures; keymap; input strategies; port allocator; command
  allowlist; bundle-id resolver. Mock `WdaClient` via `respx`.
- **Hierarchy parity**: golden XML per fixture, diffed on every change (extends Artemis `hierarchy_parity.py`).
- **Integration (macOS, no LLM)**: boot simulator, provision WDA, `IosDriver` smoke: screenshot,
  source, tap on Settings → "General", type into Safari URL bar, launch/terminate, MJPEG frame,
  recordVideo 3 s. Runs in GitHub Actions `macos-26` (Xcode 26.x) nightly.
- **E2E (LLM)**: Artemis's `tests/e2e` task set ported to iOS built-ins (Settings toggles, Notes
  create, Calendar event, Safari search) with `--verification-level final`; weekly.
- **Device lab**: manual checklist on one iOS 17 and one iOS 26 device per release.
- **Benchmark**: iOSWorld single-app subset in CI (smoke, 5 tasks); full 133 weekly on a Mac runner.

---

## 12. Sources

- Artemis: https://github.com/google/artemis (README, `pyproject.toml`, `artemis/drivers/base.py`,
  `drivers/factory.py`, `drivers/android/*`, `clients/*`, `controllers/*`, `mcp/*`, `mcp_server/*`,
  `runtime/helper_manager.py`, `graph/perception.py`, `apps/admin_console/services/device_stream_service.py`, `Makefile`, LICENSE)
- WebDriverAgent: https://github.com/appium/WebDriverAgent ; settings reference
  https://appium.github.io/appium-xcuitest-driver/latest/reference/settings/ ; Xcode 26 fix (WDA 11.4.1, XCUITest driver 9.5.0)
- DeviceKit: https://github.com/mobile-next/devicekit-ios
- idb: https://github.com/facebook/idb , https://fbidb.io/docs/idb/ui/ , iOS 17 device issue https://github.com/facebook/idb/issues/853 , PyPI `fb-idb` 1.5.9
- AXe: https://github.com/cameroncooke/AXe
- go-ios: https://github.com/danielpaulus/go-ios (releases v1.2.0–v1.3.2), https://pkg.go.dev/github.com/danielpaulus/go-ios/ios/accessibility
- pymobiledevice3: https://github.com/doronz88/pymobiledevice3 (GPL-3)
- mobile-mcp: https://github.com/mobile-next/mobile-mcp (`src/iphone-simulator.ts`, `src/ios.ts`, `src/webdriver-agent.ts`); mobilecli: https://github.com/mobile-next/mobilecli
- iOSWorld: https://github.com/ljang0/iOSWorld , paper https://arxiv.org/abs/2606.09764 ; MobileWorld https://github.com/Tongyi-MAI/MobileWorld
- Apple: `xcrun simctl`, `xcrun devicectl` (Xcode 15+)
