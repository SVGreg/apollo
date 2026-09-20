# Apollo — Development Plan

Companion to `technical-design.md`. Estimates assume one senior engineer full-time with a Mac
(Xcode 26.x), one iOS 17+ test device, and LLM API credentials; a second engineer on the
benchmark/bench work from Phase 5 shortens the tail by ~2 weeks. Total: **~14 weeks to v1.0**,
with a usable simulator-only alpha at the end of week 4.

Local baseline on the authoring machine (2026-09-16): Go 1.26.5, Python 3.14.2 (pyenv),
Xcode 26.6; `idb`, `go-ios`, `ffmpeg` not installed. **Phase 0 completed 2026-09-20** — see
`spikes.md`; numbers and design changes are folded into `technical-design.md`.

---

## Phase 0 — Bootstrap and spikes (week 1)

Goal: a renamed fork that installs, lints and runs the mock driver; every risky assumption in the
design verified by hand before code is written against it.

Tasks
1. Import `google/artemis` at a pinned SHA as the first commit; add `upstream` remote; write `docs/upstream-sync.md`.
2. Rename package `artemis`→`apollo`, CLI, env prefix (`ARTEMIS_*`→`APOLLO_*`), `artemis-client`→`apollo-client`, config `apollo.jsonc`. Keep module paths otherwise identical to ease merges.
3. `pyproject.toml`: drop `adbutils`, `uiautomator2`; add `respx` (dev). Pin Python 3.12 via `.python-version`; verify the LangGraph/opencv/grpc stack installs with `uv`. *(Done. No `fb-idb` extra: its protobuf ≥7.35 pin conflicts with the Vertex SDK; idb is used via CLI.)*
4. Apache-2.0 LICENSE kept; `NOTICE` crediting Google LLC (Artemis) and Minitap (mobile-use); file headers.
5. CI: GitHub Actions `macos-26` — lint (ruff), pyright, unit tests, `apollo run --mock`.
6. **Spikes (each ≤ half a day, results recorded in `docs/spikes.md`):**
   - S1 Build/launch Appium WDA prebuilt simulator bundle on Xcode 26.6 + iOS 26 sim; time `/source` on Settings, Safari, a deep list (target < 1.5 s).
   - S2 `xcrun simctl io recordVideo`, `openurl`, `listapps | plutil`, `pbcopy`, `clone` sanity.
   - S3 `brew install facebook/fb/idb`; `idb ui describe-all --nested` timing vs S1; HID tap/text.
   - S4 go-ios: `ios tunnel start --userspace`, `ios ui download/install/run wda` on the test device with a personal team; `/status` through `ios forward`.
   - S5 WDA MJPEG server: latency/fps at quality 40; `ffmpeg` capture to MP4.
   - S6 `/wda/keys` Unicode + newline; `element/clear`; hardware-keyboard setting impact.
   - S7 iOSWorld: clone, bootstrap 3 apps, run one task with their Appium loop to learn the trajectory format.

Exit criteria: CI green on mock driver; spike table filled with numbers; any design change from spikes reflected in `technical-design.md`.

Status 2026-09-20: tasks 1–5 done (`APOLLO_MOCK_DRIVER=1 APOLLO_FAKE_LLM=1 apollo run … --standalone` passes end-to-end; `make smoke-mock`); S1–S3, S5–S7 done, S4 partial (device detection, tunnel, screenshot verified; WDA build blocked by the personal team's registered-device cap — needs another Apple ID or a paid team before Phase 3).

---

## Phase 1 — Simulator MVP (weeks 2–4)

Goal: `apollo run "Open Settings and turn on Airplane Mode" --profile flash` succeeds end-to-end on a booted simulator.

Deliverables
- `apollo/clients/simctl.py` — device discovery (`list -j`), boot/shutdown, install/launch/terminate, `listapps`, `io screenshot`, `openurl`, `pbcopy`.
- `apollo/clients/wda_client.py` — async httpx client, session lifecycle, `/source`, `/screenshot`, W3C `actions` builders (tap, long-press, drag), `/wda/keys`, `/wda/pressButton`, `/wda/apps/*`, `/wda/activeAppInfo`, `/url`, `/alert/*`, `/appium/settings`.
- `apollo/clients/runner_manager.py` — manifest-pinned WDA download, sha256 verify, `simctl install`, launch, `/status` poll, port allocation (8100+n / 9100+n).
- `apollo/drivers/ios/hierarchy.py` — XCUIElement XML → UIAutomator XML normalizer (points→pixels, class/text/content-desc/resource-id/bounds/clickable/enabled/visible-to-user/focused/selected/scrollable/password/package).
- `apollo/drivers/ios/driver.py` — `IosDriver` implementing every `BaseDeviceDriver` method; `keymap.py` (HOME, ENTER, DELETE, BACK-via-navbar/edge-swipe, APP_SWITCH gesture); `input.py` (focus/clear/type/setValue).
- `drivers/factory.py` dispatch; `controllers/unified_controller.open_url` via driver; `platform_specific_commands_controller` iOS impl (list apps, foreground app, date).
- `mcp/actuators/ios.py` + `mcp/device_server.py` (13 low-level tools; `run_device_command` with allowlist).
- Minimal `apollo doctor` (Xcode, runtimes, booted sims, WDA status, hardware-keyboard setting).
- Unit tests: normalizer golden fixtures (≥6 screens), keymap, input strategy, allowlist, port allocator (mocked WDA with `respx`).

Exit criteria: Flash profile completes 8/10 built-in-app tasks with `--verification-level final`; integration smoke (no LLM) runs in CI on `macos-26`. The iOS 26 simulator runtime ships **no Notes, Clock or Mail**, so the task set is: Settings toggle, Settings › General › About lookup, Calendar event, Safari search, Reminders add, Contacts add, Photos open, Maps search, Messages compose (no send), Files browse.

---

## Phase 2 — Full interface parity on simulators (weeks 5–6)

Goal: everything Artemis exposes works on simulators: Pro profile, MCP server, web console, SDK, recording, traces.

Deliverables
- Prompt/vocabulary pass over `agents/*/prompts.py`, agent `.md/.json`, `mcp_server/rules.md` (BACK/APP_SWITCH semantics, bundle ids, permission sheets, Control/Notification Center, keyboard "return" labels). Keep diffs surgical for upstream merges.
- `mcp_server/tools/diagnose.py` re-targeted (`boot_simulator` instead of `launch_avd`; iOS probes; `next_steps`).
- `apps/admin_console/services/device_stream_service.py` → WDA MJPEG proxy with `simctl io screenshot` fallback; console shows live simulator.
- `drivers/ios/recorder.py`: `simctl io recordVideo` with segment rolling on rotation; `extract_segment_metadata` parity; `ffmpeg` path prepared for devices.
- `apollo runner install|status|uninstall`; `apollo mcp --install claude|codex|cursor|antigravity|all` writes Apollo paths and iOS rules.
- SDK rename + smoke test against the daemon; `apollo batch` unchanged.
- Alerts policy (`ios.alerts`) and `simctl privacy grant` task preset.
- Hierarchy-parity job wired into CI.

Exit criteria: Pro profile passes a 30+ step cross-app task (e.g. "find the address of the last Calendar event and open it in Maps"); Claude Code drives a task through `mobile_run_task` and inspects it with `mobile_inspect_trace`; console live view and replay work.

---

## Phase 3 — Physical devices (weeks 7–9)

Goal: same feature set on an iPhone (iOS 17 and iOS 26), USB-connected.

Deliverables
- `apollo/clients/goios.py` — device list/info, apps, install/launch/kill, screenshot, syslog/crash, `forward`, tunnel daemon supervision (`tunnel start --userspace`, health on :60105), `ui download/install/run wda` with `team_id`/identity from config, Developer-Mode/pairing helpers.
- `apollo/clients/devicectl.py` — optional install/launch/kill fallback.
- `RunnerManager` device path (sign → install → run → forward); restart-on-failure; per-device ports.
- `DevicePool` merges simulators and devices; `device_serial` accepts both UDID kinds.
- Doctor probes: go-ios version, tunnel, Developer Mode, trust/pairing, signing identity, Auto-Lock reminder, `/status` round-trip; `--probe-device` smoke (screenshot + source + tap).
- Recording via `ffmpeg` from MJPEG; streaming via MJPEG proxy.
- `docs/device-setup.md` (Developer Mode, trust, Apple ID/team, Auto-Lock Never, guided-access notes).
- Device integration checklist executed on both test devices.

Exit criteria: Phase 1's 10 tasks pass on a real device; `apollo doctor --probe-device` yields `ready`; cold start (plug in → first action) < 90 s after one-time setup.

---

## Phase 4 — Performance, robustness, optional backends (weeks 10–11)

Goal: Flash step time on simulators comparable to Artemis (~3–5 s), resilient long runs.

Deliverables
- `IdbClient` tier (CLI `--json`): `describe-all` leaf list + HID tap/swipe on simulators; sticky tier switching with metrics; `apollo doctor` detects companion.
- WDA snapshot tuning per screen complexity (`snapshotMaxDepth`, `snapshotMaxChildren`, `pageSourceExcludedAttributes`, `waitForIdleTimeout`), exposed in `apollo.jsonc`; source caching keyed by `activeAppInfo` + screenshot hash for action bursts.
- Session recovery (invalid session, WDA crash, simulator reboot); awake handling.
- `DeviceKitClient` behind `ios.runner: devicekit` (user-built bundle; not vendored); `device.dump.ui` normalizer; MJPEG at :12004.
- Parallel runs: `simctl clone` support in `DevicePool`, concurrency cap.
- Telemetry parity (posthog opt-out flag kept as in Artemis).

Exit criteria: median Flash step ≤ 5 s on simulator across the Phase 1 task set; 100-step monitoring loop survives 30 minutes; 3 parallel cloned simulators run the batch runner without port/lock conflicts.

---

## Phase 5 — Benchmark: iOSWorld (weeks 12–13)

Goal: reproducible iOSWorld numbers, the AndroidWorld equivalent for Apollo.

Deliverables
- `bench/iosworld/`: import `tasks.json`; reuse iOSWorld's `bootstrap_ios_apps.sh` and simulator cloning; run each task through `apollo run` (Flash and Pro); export trajectories (screenshots, actions, reasoning) in iOSWorld's format; call `judge_trajectories.py`.
- `apollo bench iosworld [--subset single-app|multi-app|memory] [--profile] [--parallel N]` with a results table and per-task trace links.
- CI smoke: 5 single-app tasks nightly; weekly full 133 on a dedicated Mac.
- Prompt/Safety-Net tuning informed by failures; regression guard on the smoke subset.

Exit criteria: full-suite run completes unattended; results published in `docs/benchmarks.md` with model/profile matrix (target: beat the paper's 52 % vision+XML baseline with Pro; report honestly if not).

---

## Phase 6 — Release v1.0 (week 14)

- `start.sh` / `Makefile install-deps` for macOS (Xcode CLT check, `uv`, `ffmpeg`, `go-ios`, optional `idb`).
- README (feature table vs Artemis, quick start, MCP setup for Claude Code/Codex/Cursor/Antigravity), `docs/device-setup.md`, `docs/upstream-sync.md`, `docs/benchmarks.md`.
- `packages/apollo-client` published (git subdirectory install as Artemis does).
- Tag v1.0.0; first upstream sync performed and documented.

---

## Milestone summary

| Week | Milestone | Demo |
|---|---|---|
| 1 | Fork boots; spikes done | `apollo run --mock`; spike numbers |
| 4 | **Simulator alpha** | Flash task on Settings/Notes/Safari |
| 6 | Interface parity (sim) | Claude Code → `mobile_run_task` → console replay |
| 9 | **Device beta** | Same task on iPhone over USB |
| 11 | Performance/backends | ≤5 s Flash steps, idb tier, 3 parallel sims |
| 13 | Benchmark | iOSWorld results table |
| 14 | **v1.0** | Docs, installer, tag |

---

## Dependencies and prerequisites

- macOS 15+ with Xcode 26.x and an iOS 26 simulator runtime (iOSWorld requirement too); Xcode license accepted.
- Apple Developer account (free personal team suffices for WDA on a personal device; paid team for lab devices).
- Test devices: one iOS 17.x, one iOS 26.x, Developer Mode enabled.
- Tools: `uv`, `ffmpeg`, `go-ios` (`brew install go-ios` or `npm i -g go-ios`), optional `idb` (`brew install facebook/fb/idb`).
- LLM keys: Gemini (default preset) plus Anthropic/OpenAI for the benchmark matrix.
- A dedicated Mac (or EC2 Mac) for nightly integration + weekly benchmark.

## Risks tracked against the plan

| Risk | Phase | Trigger to re-plan |
|---|---|---|
| WDA `/source` > 3 s on typical screens (S1) | 0→1 | Not triggered: measured 0.24–0.73 s (Springboard 2.1 s). idb stays in Phase 4. |
| go-ios signing/tunnel unreliable on iOS 26 (S4) | 3 | Tunnel verified (<1 s, userspace). go-ios has no free-team signing: `xcodebuild -allowProvisioningUpdates` is the default device signing route, go-ios P12 signing for labs. |
| Upstream Artemis refactors touch `controllers/` or `factory.py` heavily | any | Rebase platform commits at each sync; keep an adapter shim |
| Python 3.12 dependency conflicts under `uv` | 0 | Resolved cleanly (2026-09-20) once Android deps were dropped. |
| iOSWorld harness changes (Appium-specific assumptions) | 5 | Vendor a copy of `tasks.json` + judge at a pinned SHA |

## Open decisions (defaults chosen; revisit at Phase 0 review)

1. Name for `press_key BACK` semantics in prompts — keep `BACK` (drop-in) vs add `NAV_BACK`. Default: keep `BACK`.
2. Whether to keep Android driver code in-tree (disabled) for a future dual-platform merge. Default: delete, rely on upstream remote.
3. DeviceKit: keep as optional backend or drop entirely. Default: optional, evaluated at Phase 4.
4. Linux/Windows devices-only mode via go-ios. Default: not in v1.
