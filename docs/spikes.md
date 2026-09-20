# Phase 0 spikes — results

Recorded 2026-09-20 on the authoring Mac: Xcode 26.6 (17F113), iOS 26.2 + 26.5 simulator
runtimes, macOS 26, Apple Silicon. Tools installed during the spikes: ffmpeg 9.0.2 (brew),
idb 1.6.1 + idb_companion 1.6.1 (`brew trust facebook/fb && brew install facebook/fb/idb`),
go-ios 1.3.2 (`npm i -g go-ios`). WDA: Appium release **v16.12.9** (`/status` reports build
16.12.8, Sep 19 2026), `WebDriverAgentRunner-Build-Sim-arm64.zip`
sha256 `6a853e005887b8e48eb11a686561658a10de8834416d389487500e3c4a704ed5`.

Simulator under test: iPhone 17 Pro, iOS 26.2 (402×874 pt, scale 3 → 1206×2622 px, status bar 54 pt).
Fixtures saved: `tests/fixtures/wda_source/*.xml` (6 screens), `tests/fixtures/idb/*.json` (3 screens).

| Spike | Result | Target | Design impact |
|---|---|---|---|
| S1 WDA `/source` | **PASS** — 0.37–0.73 s | < 1.5 s | idb stays optional (Phase 4). |
| S2 simctl | **PASS** with two caveats (clone, recordVideo) | sanity | Clone from shutdown template; recording is change-driven. |
| S3 idb | **PASS** — 0.14–0.20 s, but leaf-only tree, ASCII-only typing | vs S1 | Tier-2 = compact AX list, not a full tree; input via WDA. |
| S4 go-ios | **PARTIAL** — USB/info/apps/tunnel pass; WDA-on-device pending | device | Signing needs P12+profile or xcodebuild free team; Developer Mode + passcode flow. |
| S5 MJPEG | **PASS** — 11.6 fps, first frame 0.18 s, 53 KB/frame | fps/latency | Even-dimension scale filter for x264. |
| S6 `/wda/keys` | **PASS** — Unicode, `\n`, `\b`, `clear`, `setValue`, pasteboard | — | `\n` in single-line fields advances focus; typing works with hardware keyboard on. |
| S7 iOSWorld | **PASS (harness)** — 3 apps built+installed; task run needs LLM key + Appium | learn format | Trajectory schema captured below. |

## S1 — WDA `/source` latency (simulator)

Session created with `{"capabilities":{"alwaysMatch":{"platformName":"iOS"}}}`; app launched with
`POST /wda/apps/launch`; each number is the median of 3 calls.

| Screen | nodes | XML | default settings | `snapshotMaxDepth=60, snapshotMaxChildren=200, pageSourceExcludedAttributes=accessible,index` |
|---|---|---|---|---|
| Settings root | 167 | 40 KB | 0.45 s | 0.39 s |
| Settings › General › About | 143 | 34 KB | 0.37 s | 0.37 s |
| Safari start page | 130 | 33 KB | 0.73 s | 0.50 s |
| Springboard (home) | 222 | 46 KB | 2.1 s | — |
| iOSWorld Clock (iOS 26.5 sim) | 74 | — | 0.24 s | — |
| iOSWorld Notes | 123 | — | 0.40 s | — |
| iOSWorld Weather | 278 | — | 0.62 s | — |

`/screenshot` (PNG, native 1206×2622): 0.06 s, 250–540 KB base64. `/wda/screen`:
`{statusBarSize: 402×54, scale: 3, screenSize: 402×874}`.

Gotchas
- **Wait for the foreground app.** Right after `/wda/apps/launch`, `/source` can still return the
  Springboard tree. Poll `/wda/activeAppInfo.bundleId` until it matches (≈0.25–1 s) before dumping;
  otherwise the agent perceives the home screen. `IosDriver.launch_app` must do this.
- Springboard is the slowest tree (2.1 s, 222 nodes of icons). Fine for an occasional HOME step.
- Boot: `simctl boot` + `bootstatus -b` 19–21 s; WDA `simctl install` + `launch` → `/status` in 3–12 s.
- **Quitting Simulator.app shuts down every booted simulator** (and kills WDA). Boot headless with
  `simctl boot`; if the GUI is wanted, `open -a Simulator` and never quit it while a task runs.

## S2 — simctl

| Command | Result |
|---|---|
| `io recordVideo --codec=h264 -f out.mp4` (SIGINT to stop) | Works: 1206×2622 H.264, **variable frame rate, frames only on display change** — 5 s of a static screen yields a 1-frame 67 KB file; 9 s of scrolling yields 693 frames / 11.6 MB. Segment metadata must not assume constant fps. |
| `openurl https://…` / `openurl App-prefs:General` | Both open (Safari / Settings › General). |
| `listapps <udid> \| plutil -convert json -o - -` | 23 apps on iOS 26.2. **No Notes, Clock, Mail, Calculator, Weather on the simulator runtime** — Phase 1 task set must use Settings, Safari, Calendar, Reminders, Contacts, Photos, Maps, Messages, Files. |
| `pbcopy` / `pbpaste` | Round-trips. |
| `status_bar override --time 9:41 --batteryLevel 100`, `privacy grant location <bundle>` | OK. |
| `clone` | **Source must be Shutdown** (`Unable to clone device in current state: Booted`). Clone of a shutdown iPhone 17: 0 s; boot 19 s; WDA must be installed on the clone separately. `DevicePool` keeps a shutdown template and clones from it. |
| Per-simulator WDA port | Two WDAs on one host: the second `simctl launch` with `SIMCTL_CHILD_USE_PORT=8101 SIMCTL_CHILD_MJPEG_SERVER_PORT=9101` binds 8101; both `/status` OK. This is the port allocator mechanism (design §6.8). |

## S3 — idb (simulator only)

`idb` CLI 1.6.1 talks to an auto-spawned `idb_companion` (first call 5.5 s cold; warm after).
No `fb-idb` Python package is used: every fb-idb release pins `protobuf>=7.35`, which conflicts
with `google-cloud-aiplatform` (<7) in the Artemis dependency set — **the `sim-fastpath` extra is
dropped; `IdbClient` shells out to `idb … --json`.**

| Screen | `idb ui describe-all --nested --json` | nodes | WDA `/source` same moment |
|---|---|---|---|
| Settings root | 0.20 s | 14 | 0.39 s |
| Settings › General › About | 0.19 s | 15 | 0.32 s |
| Safari | 0.14 s | 7 | 0.15 s |

- `describe-all` returns **accessibility leaves only** (Application → Heading/Button/TextField/…
  with `AXLabel`, `AXValue`, `frame`, `traits`, `enabled`, `AXUniqueId`), not the XCUIElement
  container tree. It is a good "minimal element list" but drops StaticText inside cells and any
  non-accessible node. Non-nested mode returns a flat list (57 elements on the new-contact form).
- HID: `ui tap` 0.14–0.21 s, `ui button HOME`, `screenshot` OK. `ui text` is **ASCII-only**
  (`No keycode found for ü`) → Unicode input always goes through WDA `/wda/keys`.
- Frames are in points (float); normalizer multiplies by scale.

## S4 — go-ios on a physical device (iPhone 14, iOS 26.6.2, USB)

| Step | Result |
|---|---|
| `ios list` / `ios info` | Detected over USB: `00008110-001A10AC14B9401E`, iPhone14,7, 26.6.2, `PasswordProtected: true`. |
| `ios apps --list` | Works without tunnel. |
| `ios tunnel start --userspace` (background) | Negotiated in < 1 s, no sudo; `GET :60105/tunnels` lists the device (`userspaceTunPort` 60106). |
| `ios screenshot` (instruments) | Fails until Developer Mode is on (`DVTSecureSocketProxy unavailable`). |
| `ios devmode get/enable` | Reported `false`; `enable` on a passcode-locked phone cannot flip it, it only reveals the Settings › Privacy & Security › Developer Mode menu (user toggles + reboot). `devicectl` pairing succeeded (`connected (no DDI)`). |
| WDA on device | **Pending** at time of writing: needs Developer Mode on and a signing path. go-ios 1.3.2 signs only with `ios sign app --p12file --profile` or `ios sign provision appstoreconnect` (API key) — **no free-personal-team signing**; that route is `xcodebuild -project WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner -destination id=<udid> -allowProvisioningUpdates DEVELOPMENT_TEAM=<team> build-for-testing` + `ios runwda`. `ios ui download wda` fetches Appium's `WebDriverAgentRunner-Runner.zip` for the P12 path. |

Design changes: RunnerManager device path offers both signing routes (Xcode free team by default,
P12+profile for labs/CI); doctor gains probes for Developer Mode, passcode, CoreDevice pairing,
signing identity (`security find-identity -p codesigning`), and the tunnel. `docs/device-setup.md`
(Phase 3) documents the passcode → Developer Mode menu → reboot flow.

## S5 — WDA MJPEG server

`POST /session/:id/appium/settings {"mjpegServerFramerate":12,"mjpegServerScreenshotQuality":40,"mjpegScalingFactor":50}`
then `GET http://127.0.0.1:9100/` (raw socket): **58 frames / 5 s = 11.6 fps, first frame after
0.18 s, 53 KB per JPEG** (603×1311). Defaults are 10 fps / quality 25 / scale 100.

`ffmpeg -f mjpeg -i http://127.0.0.1:9100 -t 5 -c:v libx264 -pix_fmt yuv420p out.mp4` →
**fails at 50 % scale because 603×1311 is odd**; with `-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2"`
it writes 602×1310 H.264 (125 frames, 600 KB). Add `-use_wallclock_as_timestamps 1` (or
`-r 12`) so the timeline matches real time instead of ffmpeg's 25 fps MJPEG assumption. The console
proxy can pass the stream through untouched.

## S6 — Text input

Target: Contacts › new contact (iOS 26.2 sim has no Notes app).

| Action | Result |
|---|---|
| `/wda/keys ["héllo 👋 wörld"]` | 0.42 s, value exact. |
| `/wda/keys ["\n"]` in a **TextField** | 0.31 s — **advances focus to the next field** (Return = Next/Done), subsequent text lands in "Last name". |
| `/wda/keys ["\n"]` in a **TextView** | Inserts a newline (`'line one\nline two'`). |
| `/wda/keys ["\b\b\b"]` | Deletes 3 characters (0.31 s). |
| `POST /element/:id/clear` | 0.88 s, field back to placeholder; works on TextView too. |
| `POST /element/:id/value ["…值"]` | Sets value directly (Unicode OK) — this is the long-text fallback (design §6.4 step 3). |
| `/wda/setPasteboard` + `/wda/getPasteboard` | Round-trips (base64, `contentType: plaintext`). |
| Software keyboard visible | `XCUIElementTypeKeyboard` present; return-key names seen: `Done`, `Return`. |
| `ConnectHardwareKeyboard=YES` + Simulator.app attached | Keyboard still shown and `/wda/keys` works — the doctor check is a warning, not a blocker. |
| `/wda/pressButton {"name":"home"}` | 0.47 s. |
| `POST /wda/element/:id/scroll {predicateString}` | **Timed out at 60 s** — use W3C `actions` swipes (0.3–0.5 s each) instead. |

Design change: `press_key ENTER` = `"\n"` but the prompt must tell the Operator that Return in a
single-line field moves focus/submits; `erase_one_char` = `"\b"`; `focus_and_clear_text` = tap +
`element/clear` (fall back to N×`"\b"` from the tree value).

## S7 — iOSWorld

Clone `ljang0/iOSWorld` @ `e91f4cb` (2026-06-09). Layout: `tasks.json` (133 tasks: 27 single_app,
60 multi_app, 46 memory; 26 easy / 61 medium / 46 hard; 26 apps), `iphone/apps/<app>/xproj`,
`iphone/bootstrap/bootstrap_ios_apps.sh` (`--repos <list> --device <name> --no-open-simulator
--no-env-file`; erases the simulator by default, writes `.app_manifest.json` with bundle ids +
built `.app` paths for per-task reinstall), `scripts/appium_agent.py` (runner),
`scripts/judge_trajectories.py` + `llm_action_generator.evaluate_trajectory` (judge; default
OpenAI `gpt-5.4-mini`, `EVAL_PROVIDER/EVAL_MODEL` override).

- Bootstrap of `clock`, `notes`, `weather` on a fresh iPhone 17 (iOS 26.5): **179 s, 3/3 success**.
  Building requires the iOS platform matching Xcode (26.5) to be installed — with only the 26.2
  runtime present `xcodebuild` fails with "iOS 26.5 is not installed".
- Running a task needs Appium (`appium` + `appium-xcuitest-driver`) and an LLM key; neither was
  available in this session, so no trajectory was produced. Apollo replaces that loop anyway.
- Task schema: `{name, goal, apps[], category, difficulty, memory_type?, rubric[{criterion}]}`.
- Result layout the judge reads, per task dir: `task.json`
  `{task, goal, status: ok|failed|safety_blocked, error, steps, wall_time_seconds, agent_answer, task_dir}`
  and `trajectory.json` = list of `{step, screenshot, action | actions[], post_action_screenshot,
  llm_error?}` with screenshots under `steps/NN/screenshot.png` (+ `observation.json`). Score =
  satisfied criteria / criteria; pass = all satisfied. `judge_trajectories.py --run-dir <dir>`
  re-scores; `--no-evaluate` skips scoring.
- Apollo's `bench/iosworld` exporter therefore writes `task.json` + `trajectory.json` +
  `steps/NN/screenshot.png` from the Artemis trace and calls the judge unchanged.

## Environment findings not tied to one spike

- `uv lock` with Python 3.12 resolves the Artemis set cleanly once `adbutils`/`uiautomator2` are
  removed; `.python-version` = 3.12 (host has only 3.14 via pyenv; `uv` downloads 3.12.13).
- Unit suite needs `GOOGLE_API_KEY` set to any value (one Flash test constructs a Gemini client).
- 8 upstream unit tests fail on any host without `adb`; they are tagged `android` in Apollo.
