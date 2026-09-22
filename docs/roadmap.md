# Apollo — roadmap

What is delivered, and what each remaining phase contains. Design rationale lives in
[`architecture.md`](architecture.md); user-facing instructions live in the
[README](../README.md).

## Delivered

**The simulator path is complete and CI-verified.** On a booted iOS Simulator, Apollo runs Flash
and Pro tasks from the CLI, the web console, an IDE agent over MCP, or the Python SDK; records
video; streams a live screen; and leaves replayable traces.

| Area | What works |
|---|---|
| Device layer | `IosDriver` over WebDriverAgent + `simctl`: screenshot, normalized hierarchy, taps/swipes/typing, keys (BACK / HOME / APP_SWITCH / ENTER semantics), app launch & identity, URL open, alerts policy, allowlisted host commands |
| Runner | `RunnerManager` downloads the pinned, checksum-verified WDA build, installs and launches it per simulator with its own ports; `apollo runner status/install/stop/uninstall` |
| Profiles | Flash on the built-in app set (Settings, Safari, Reminders, Contacts, Calendar, Maps, Photos, Messages, Files); Pro including a 30-step cross-app task |
| Interfaces | `apollo run/batch/trace/ui/doctor/mcp/runner`, web console (setup, device panel, composer, live view, replay), MCP agent server + 13-tool device server, `apollo-client` SDK |
| Media | Recording (ffmpeg over WDA MJPEG, or `simctl recordVideo`), mid-run video segments for the Video Analyzer, ~11 fps console live view |
| Quality | Unit suite (hierarchy normalizer over saved fixtures, keymap, input, allowlist, ports, probes, recorder, segments), simulator integration smoke + SDK contract + hierarchy-parity assertions on `macos-26`, wheel build smoke, ruff/pyright/quality ratchet |

Not yet verified on the simulator path: `--app-path` against a third-party app build (the code
path is wired — `simctl install` plus app lock — but has only been exercised with built-in apps).
Deferred by choice: rolling a recording on device rotation.

Phase 3 groundwork has also landed: `apollo/clients/goios.py` (device list/info/apps,
install/launch/kill, screenshot, Developer Mode, userspace tunnel agent, port forwarding,
`runwda`), the `apollo doctor` physical-device probe, and [`device-setup.md`](device-setup.md).

---

## Phase 3 — Physical devices

**Goal:** the same feature set on a USB-connected iPhone (iOS 17 and iOS 26).

**Gate:** an Apple account that can sign WebDriverAgent for the test device. A free personal team
registers at most three devices per membership year and cannot release them; when the cap is hit,
`xcodebuild -allowProvisioningUpdates` fails with *"Your development team has reached the maximum
number of registered iPhone devices"*. Resolution: another Apple ID, a paid team, or the P12 +
provisioning-profile route through `ios sign app`. Nothing else in this phase is blocked by code.

Deliverables

- `RunnerManager` device path: sign → install → `runwda` → `ios forward` → `/status`, with
  restart-on-failure and per-device ports.
- `DevicePool` merges simulators and devices; `device_serial` accepts both UDID kinds.
- `apollo/clients/devicectl.py` as an optional install/launch/kill fallback.
- Doctor: `--probe-device` smoke (screenshot + source + tap), tunnel and pairing checks,
  Auto-Lock reminder.
- Recording and streaming on device via ffmpeg over the WDA MJPEG stream.
- The device checklist in [`device-setup.md`](device-setup.md) executed on both test devices.

**Exit criteria:** the simulator task set passes on a real device; `apollo doctor --probe-device`
reports ready; cold start (plug in → first action) under 90 s after one-time setup.

## Phase 4 — Performance and optional backends

**Goal:** Flash step time on simulators comparable to Artemis (~3–5 s) and resilient long runs.

- `IdbClient` tier for simulators (`describe-all` leaf list, HID tap/swipe) with sticky tier
  switching and metrics; doctor detects the companion.
- WDA snapshot tuning per screen complexity (`snapshotMaxDepth`, `snapshotMaxChildren`,
  `pageSourceExcludedAttributes`, `waitForIdleTimeout`) and source caching keyed by
  `activeAppInfo` plus a screenshot hash.
- Session recovery: invalid session, WDA crash, simulator reboot.
- Parallel runs: `simctl clone` support in `DevicePool` with a concurrency cap.

**Exit criteria:** median Flash step ≤ 5 s across the task set; a 100-step monitoring loop
survives 30 minutes; three cloned simulators run the batch runner without port or lock conflicts.

## Phase 5 — Benchmark: iOSWorld

**Goal:** reproducible [iOSWorld](https://github.com/ljang0/iOSWorld) numbers (133 tasks, 26
purpose-built apps) — the AndroidWorld equivalent for Apollo.

- `bench/iosworld/`: import `tasks.json`, reuse the upstream app bootstrap and simulator cloning,
  run each task through `apollo run`, export trajectories in iOSWorld's format
  (`task.json` + `trajectory.json` + `steps/NN/screenshot.png`), call `judge_trajectories.py`.
- `apollo bench iosworld [--subset single-app|multi-app|memory] [--profile] [--parallel N]`.
- CI smoke: five single-app tasks nightly; the full suite weekly on a dedicated Mac.

**Exit criteria:** an unattended full-suite run, with results and a model/profile matrix published
in `docs/benchmarks.md` (target: beat the paper's 52 % vision+XML baseline with Pro; report
honestly if not).

## Phase 6 — Release v1.0

- `make install-deps` polish, README/device-setup/benchmarks final pass.
- `packages/apollo-client` published; tag `v1.0.0`; first upstream sync performed and documented.

---

## Live risks

| Risk | Trigger to re-plan |
|---|---|
| No signing-capable Apple team for the test devices | blocks Phase 3 entirely; escalate before starting it |
| XCTest/WebDriverAgent break with a new Xcode | pin WDA and the Xcode matrix in `runner_manifest.json`; doctor blocks unsupported combinations |
| Upstream Artemis refactors touch `controllers/` or `factory.py` heavily | rebase platform commits at each sync; keep an adapter shim ([`upstream-sync.md`](upstream-sync.md)) |
| iOSWorld harness assumes Appium | vendor `tasks.json` and the judge at a pinned SHA |
| Parallel simulators contend for CPU and ports | `simctl clone`, the port allocator and a concurrency cap (Phase 4) |

## Open decisions

1. Keep the disabled Android driver in-tree (`apollo/drivers/android/`, `apollo helper`) or delete
   it and rely on the upstream remote. Leaning delete — it is dead weight on an iOS-only fork.
2. DeviceKit as an optional backend, or drop it. Evaluate during Phase 4.
3. Linux/Windows device-only mode through go-ios. Not planned for v1.
