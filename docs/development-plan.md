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

Revised 2026-09-20 after the Phase 0 review: split into a **thin slice (1a)** that gives a working
`apollo run` on a simulator in about one week, then **parity (1b)** that makes the web console,
MCP server and doctor usable on iOS. Rationale: the mock-driver smoke proved every layer above
`BaseDeviceDriver` runs unchanged, and the seam list below is short; the first demo should land
at the end of week 2, not week 4. The web console (`apollo ui`, `localhost:8000`) already starts
and renders on Apollo today, but its Run button is gated by the Android readiness report and its
device panel/stream are adb-only — those are 1b items.

### Phase 1a — thin slice (week 2)

Goal: `apollo run "<goal>" --profile flash --device <booted-sim-udid>` with a Gemini key completes
Settings / Safari / Reminders / Contacts tasks; `apollo trace` shows the run.

Seams to replace on the `apollo run` path (verified against the code, 2026-09-20):

| Seam | Where | Change |
|---|---|---|
| iOS driver | `apollo/drivers/ios/{driver,hierarchy,keymap,input}.py` (new) | `IosDriver` over `WdaClient` + `SimBridge`; normalizer from the S1 fixtures |
| WDA client | `apollo/clients/wda_client.py` (new) | session, `/source`, `/screenshot`, W3C actions, `/wda/keys`, `pressButton`, `apps/*`, `activeAppInfo` (poll after launch), `/wda/screen`, `appium/settings` |
| Simulator bridge | `apollo/clients/simctl.py` (new) | `list -j`, boot/bootstatus, install/launch/terminate, `listapps`, `openurl`, `io screenshot` |
| Runner provisioning | `apollo/runtime/runner_manager.py` (new) + `apollo/resources/runner_manifest.json` | pinned v16.12.9 zip → sha256 → `simctl install/launch` → `/status` poll; `SIMCTL_CHILD_USE_PORT` per lease |
| Factory | `drivers/factory.py` | dispatch on `DevicePlatform.IOS` |
| Agent init | `sdk/agent.py` (`_init_internal`, `_init_clients`, `_get_device_context`) | iOS branch: no adb, context from `/wda/screen`; skip keyguard check and Chrome-a11y prep; `install_app` → `simctl install` |
| Device discovery | `runtime/device_pool.py`, `utils/cli_helpers.get_first_device`, `display_device_status` | `simctl list -j` booted devices (+ `ios list` later) |
| Controllers | `controllers/unified_controller.open_url`, `platform_specific_commands_controller` | `simctl openurl`; foreground app via `activeAppInfo`; list apps via `listapps`; **recording stubbed** (start returns failure, Artemis tolerates it) |
| `run_adb_command` tool | `tools/command_tool.py`, `agents/operator/prompts.py`, `graph/graph.py` | `run_device_command` with a `simctl`/`ios` allowlist |
| Prompt vocabulary (minimal) | `agents/operator/prompts.py`, `agents/flash/*.md` | BACK = nav-bar back / edge swipe, APP_SWITCH gesture, "bundle id", Return-key behaviour in TextFields (S6) |

Explicitly deferred out of 1a: doctor, device_server tools, idb tier, recording, console changes,
golden-fixture tests beyond the normalizer's own.

Exit criteria (1a): 4 built-in-app Flash tasks pass with `--verification-level final`; Pro profile
runs one of them (platform-neutral, expected to work once Flash does); `uv run pytest` green with a
normalizer test over the 6 saved fixtures.

### Phase 1b — usable interfaces on simulators (weeks 3–4)

Goal: the same task can be launched from the web console, from Claude Code, and checked with
`apollo doctor`.

Deliverables
- **Readiness for iOS** — `core/diagnostics/readiness.py` + probes (Xcode/CLT, simulator runtimes,
  booted sims, WDA `/status`, ffmpeg optional, credentials). One code path feeds `apollo doctor`,
  `GET /api/system/readiness` (this is what enables the console's Run button) and `mobile_diagnose`.
- **Console device panel** — `/api/devices` from the iOS `DevicePool`; `/emulator/launch|status|stop`
  → simulator boot/shutdown; `/adb/*` routes return "not applicable" and the Angular panel hides them.
- **Console live screen** — `device_stream_service` polls `simctl io screenshot` (~5 fps) with the same
  MJPEG response the UI already consumes; WDA MJPEG proxy stays in Phase 2.
- **Angular pass** — Setup Guide steps 1 and 3 (Xcode/simulator instead of adb/scrcpy), labels
  ("Android device", "ADB", "on your phone"), recommended task cards → iOS/iOSWorld apps
  (`smart-tasks.data.ts`), `artemis init` → `apollo init`. Rebuild with `make build-ui` and commit
  `apollo/resources/showcase_ui`. This is the only frontend work in the project.
- `apollo mcp --install claude|codex|cursor|antigravity|all` writes Apollo paths and iOS rules;
  `mcp_server/rules.md` vocabulary; `mcp_server/tools/diagnose.py` → `boot_simulator` + iOS probes.
  (The MCP server only talks to the daemon, so this is nearly free once 1a works.)
- `mcp/actuators/ios.py` + `mcp/device_server.py` (13 low-level tools; `run_device_command` allowlist).
- `apollo runner install|status|uninstall`.
- Unit tests: keymap, input strategy, allowlist, port allocator (mocked WDA with `respx`), readiness
  probes; hierarchy-parity job over the fixtures in CI.

Exit criteria (1b): from `apollo ui` — save a Gemini key, pick a booted simulator, run a Flash task,
watch the live screen, replay it from History; Claude Code runs the same task through
`mobile_run_task` and inspects it with `mobile_inspect_trace`; `apollo doctor` reports `ready`;
Flash completes 8/10 of: Settings toggle, Settings › General › About lookup, Calendar event, Safari
search, Reminders add, Contacts add, Photos open, Maps search, Messages compose (no send), Files
browse (the iOS 26 simulator ships no Notes, Clock or Mail). Integration smoke (no LLM) runs in CI
on `macos-26`.

---

## Phase 2 — Full parity on simulators (weeks 5–6)

Goal: everything Artemis exposes works on simulators: Pro profile at length, recording, MJPEG
streaming, SDK, alerts, hierarchy parity.

Deliverables
- Full prompt/vocabulary pass over `agents/*/prompts.py`, agent `.md/.json`, `mcp_server/rules.md`
  (permission sheets, Control/Notification Center, keyboard "return" labels, no intents). Keep diffs
  surgical for upstream merges.
- `apps/admin_console/services/device_stream_service.py` → WDA MJPEG proxy (12 fps, quality 40)
  with the 1b screenshot polling as fallback.
- `drivers/ios/recorder.py`: `simctl io recordVideo` (variable frame rate — segment metadata from
  presentation timestamps), rolling on rotation; `ffmpeg` MJPEG path with the even-size filter
  prepared for devices.
- SDK (`apollo-client`) smoke test against the daemon; `apollo batch` unchanged.
- Alerts policy (`ios.alerts`) and `simctl privacy grant` task preset.
- Hierarchy-parity job wired into CI; `apollo run --app-path <.app|.ipa>` and `--locked-app <bundle id>`
  verified against an iOSWorld app (Notes) as the first "your own app" test.

Exit criteria: Pro profile passes a 30+ step cross-app task (e.g. "find the address of the last
Calendar event and open it in Maps"); console live view at 12 fps; recording attached to the trace;
`apollo run --app-path` installs and tests an iOSWorld app end to end.

---

## Phase 3 — Physical devices (weeks 7–9)

Goal: same feature set on an iPhone (iOS 17 and iOS 26), USB-connected.

**Gate:** a signing-capable Apple account. S4 showed the free personal team's registered-device cap
blocks WDA provisioning before any code matters; use another Apple ID or a paid team, or the
go-ios P12+profile route. Everything else in this phase is unchanged.

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
| 1 | Fork boots; spikes done | `make smoke-mock`; spike numbers (done 2026-09-20) |
| 2 | **Thin slice** | `apollo run` Flash task on Settings/Safari/Reminders on a simulator |
| 4 | **Simulator alpha** | Same task from `apollo ui` (live screen, replay) and from Claude Code via `mobile_run_task`; `apollo doctor` ready |
| 6 | Full parity (sim) | Pro 30-step cross-app task; recording; `--app-path` on an iOSWorld app |
| 9 | **Device beta** | Same task on iPhone over USB |
| 11 | Performance/backends | ≤5 s Flash steps, idb tier, 3 parallel sims |
| 13 | Benchmark | iOSWorld results table |
| 14 | **v1.0** | Docs, installer, tag |

---

## How Apollo is used (target workflow, same as Artemis)

```sh
make install                      # uv sync --dev
cp .env.example .env              # GOOGLE_API_KEY=… (or ANTHROPIC_API_KEY / OPENAI_API_KEY …)
apollo init                       # wizard: provider/model → .env, config/apollo.jsonc
apollo doctor                     # Xcode, simulator runtimes, WDA, keys → ready

# ad-hoc: built-in app or your own app on a simulator (or a device UDID once Phase 3 lands)
apollo run "Open Settings and turn on Airplane Mode" --profile flash --device <udid>
apollo run "Log in with demo/demo and check the cart badge shows 2" \
    --app-path build/MyApp.app --locked-app com.acme.myapp \
    --profile pro --verification-level final --with-video-recording-tools

# regression: one goal per line, one trace per goal
apollo batch tasks.txt --device <udid>
apollo trace list / apollo trace show <session>

# IDE agents and the web console
apollo mcp --install claude       # mobile_run_task / mobile_manage_task / mobile_inspect_trace / mobile_diagnose
apollo ui                         # localhost:8000 — setup guide (keys, device), task composer, live screen, replay
```

Availability by milestone: `apollo run`/`trace`/`batch` at week 2 (1a); `apollo ui`, `apollo mcp`,
`apollo doctor` at week 4 (1b); `--app-path`, recording, Pro long tasks at week 6; devices at week 9.

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
