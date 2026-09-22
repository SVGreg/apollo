# Apollo

Apollo turns a sentence into actions on an iPhone. It is an autonomous, natural-language iOS
automation framework — a fork of [Google Artemis](https://github.com/google/artemis) with the
Android device layer replaced by iOS Simulators (and, from Phase 3, physical iPhones/iPads)
driven through WebDriverAgent, `xcrun simctl` and `go-ios`.

<p align="center">
  <img src="./docs/assets/apollo-demo.gif" alt="Apollo driving an iOS Simulator from the web console: a Maps task typed into the composer, executed step by step on the iPhone 17 Pro simulator" width="100%" />
</p>

You describe a goal; an LLM agent looks at the screen and the accessibility tree, decides the next
action, and taps, swipes, types or launches apps until the goal is met — then reports what it found
and leaves a replayable trace behind.

> **Status.** Everything below works on iOS Simulators and is exercised by CI on every push.
> Physical devices are in progress (Phase 3): the go-ios client, the `apollo doctor` device probe
> and [`docs/device-setup.md`](docs/device-setup.md) have landed, but driving a real iPhone still
> needs WebDriverAgent signed for that device. See [`docs/roadmap.md`](docs/roadmap.md).

---

## Requirements

| | |
|---|---|
| Host | macOS with **Xcode 26.x** and an iOS 26 simulator runtime (`xcodebuild -showsdks`) |
| Python | supplied by [`uv`](https://docs.astral.sh/uv/) — 3.12 is pinned in `.python-version` |
| Model key | one of `GOOGLE_API_KEY` (default), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … |
| Optional | `ffmpeg` (recording, video analysis), `go-ios` (physical devices), `idb` |

Nothing is installed on the simulator by hand: Apollo downloads a pinned, checksum-verified
WebDriverAgent build on first use and installs it itself.

## Quick start

```sh
git clone git@github.com:SVGreg/apollo.git && cd apollo
make install                                   # uv sync --dev
cp .env.example .env                           # then set GOOGLE_API_KEY=…
xcrun simctl list devices available | grep iPhone
xcrun simctl boot <udid>                       # e.g. "iPhone 17 Pro"

uv run apollo run "Open Settings, go to General > About and tell me the iOS version" \
    --profile flash --standalone --device-serial <udid> --verification-level final
```

The first run downloads and installs WebDriverAgent (~30 s); later runs reuse it.

### Easy start: `./start.sh`

One script prepares the machine and opens the web console — use it if you would rather not
assemble the steps above:

```sh
./start.sh                    # or: make start
```

It normalizes `PATH`, installs `uv` if missing, verifies Xcode Command Line Tools and `simctl`
(and warns about optional tools — `make install-deps` adds them), creates `.env` from the example,
runs `uv sync`, builds the Angular console on first use (needs Node ≥ 22.22; it tries nvm,
Homebrew, then a portable Node in `~/.local`, so no admin rights are needed — a few minutes once),
offers to install the MCP server and rules into your IDE agents, then serves
<http://localhost:8000> and opens your browser.

Worth knowing:

- **The key can come later.** The console's Setup Guide saves one for you. Until a key is present
  the Run button stays disabled and `apollo doctor` says why.
- **Boot a simulator** from the console's device panel, or beforehand with `xcrun simctl boot`.
  Never quit Simulator.app while a task runs — it shuts every simulator down.
- **Arguments pass through** to `apollo ui`: `./start.sh --port 8080`, `./start.sh --no-open`.
- **Remote Macs**: over SSH the browser is not opened and the script prints the tunnel to use.
- **Stop / restart** with `Ctrl+C`, or `uv run apollo stop | restart | status` from another shell.
- It never touches Xcode, never needs `sudo` on macOS, and does not pick a simulator or a model
  for you — those live in the console and `config/apollo.jsonc`.

---

## Features

### Run a task — `apollo run`

Two execution profiles, both inherited from Artemis and platform-neutral:

- **Flash** — a single reactive observe-think-act loop. Fast (3–5 s per step), best for everyday
  goals with a clear path.
- **Pro** — Planner → Operator → Checker graph with a written plan, checkpoints and a final
  review. Use it for long, multi-app or verification-heavy work; a 30-step cross-app task (create
  a contact → add a reminder → create a calendar event → read the contact back) passes on a
  simulator.

```sh
uv run apollo run "<goal>" --profile flash|pro --standalone \
    --device-serial <udid> --verification-level final
```

`--verification-level off | final | checkpoints | strict` controls how much the Checker audits.
Omit `--device-serial` to use the only booted simulator.

### Test your own app — `--app-path`

Install a simulator build and keep the agent inside it for the whole task:

```sh
uv run apollo run "Log in as demo/demo and confirm the cart badge shows 2" \
    --app-path build/MyApp.app --locked-app com.acme.myapp \
    --standalone --device-serial <udid>
```

### Regression lists — `apollo batch`

One goal per line, one trace per goal:

```sh
uv run apollo batch --file tasks.txt --profile flash --standalone
```

### Traces and replay — `apollo trace`

Every run records per-step screenshots, the normalized hierarchy, the action taken and the
agent's reasoning into `traces/<session>_PASS|FAIL_<timestamp>/`.

```sh
uv run apollo trace list
uv run apollo trace view <session>
```

The web console replays the same traces step by step.

### Web console — `apollo ui`

```sh
uv run apollo ui            # http://localhost:8000
```

Setup Guide (keys, Xcode, simulators), device panel (list / boot / shut down simulators), task
composer with Flash/Pro selection, **live screen**, task queue and step replay from history. The
live view streams the WebDriverAgent MJPEG server (~11 fps, half scale) and provisions the runner
on first view, falling back to `simctl` screenshot polling while the runner is down.

### IDE agents over MCP — `apollo mcp`

```sh
uv run apollo mcp --install claude        # also: codex, cursor, antigravity, all
```

Installs the server plus iOS testing rules into the IDE's global config and exposes
`mobile_run_task`, `mobile_manage_task`, `mobile_get_device_state`, `mobile_inspect_trace` and
`mobile_diagnose`. `mobile_diagnose(launch_avd="iPhone 17 Pro")` boots a simulator from the IDE.
A second, lower-level server offers the 13 raw device actions (tap, swipe, launch, screenshot,
hierarchy, …):

```sh
uv run apollo mcp --type device
```

See [`mcp_server/README.md`](mcp_server/README.md) for the tool reference and notification setup.

### Python SDK — `apollo-client`

A remote-only client for a running daemon (`apollo ui` or `apollo server`):

```python
from apollo_client import ApolloClient

client = ApolloClient("http://127.0.0.1:8000", device_serial="<udid>", default_profile="flash")
result = await client.run("Open Settings and report the iOS version")
```

`health`, `readiness`, `capabilities`, `list_devices`, `submit`, `get_task`, `wait_for_task`,
`run`, `stop`. It never imports a driver or an LLM provider.

### Recording and video analysis

```sh
uv run apollo run "…" --with-video-recording-tools --standalone --device-serial <udid>
```

Writes `recording.mp4` into the trace. With `ffmpeg` present the video is encoded from the WDA
MJPEG stream at a constant 12 fps with a real-time timeline (a fragmented MP4, so the Video
Analyzer can cut segments out of it *while the task is still running*); without `ffmpeg` it falls
back to `simctl io recordVideo`, whose file is variable-frame-rate and readable only once the run
ends. Override with `APOLLO_IOS_RECORDING_BACKEND=auto|mjpeg|simctl` or
`agent.ios.recording_backend`.

### WebDriverAgent management — `apollo runner`

Tasks and the live view provision the runner themselves; these commands cover the rest:

```sh
uv run apollo runner status              # installed / answering / version / ports
uv run apollo runner install [--force]   # re-download the pinned build and start it
uv run apollo runner stop | uninstall
```

### Environment check — `apollo doctor`

```sh
uv run apollo doctor [--json] [--fix]
```

Checks Xcode and `simctl`, simulator runtimes and booted devices, the WDA runner, the
recording/device toolchain, model credentials, and attached physical iPhones (go-ios, Developer
Mode, tunnel agent, signing identities). Each failed check carries the command or the step that
fixes it.

### Permission sheets and device commands

System alerts are ordinary elements, so by default the Operator reads and taps them
(`agent.ios.alerts: "observe"`). Set `"accept"` or `"dismiss"` to have the driver answer them
through WebDriverAgent before each perception. To pre-authorize instead, the agent can run
allowlisted host commands — `simctl privacy grant <service> <bundle id>`, `simctl openurl`,
`simctl listapps` — through its `run_adb_command` tool (the Artemis name is kept as a drop-in; on
iOS it runs `simctl`, and there is no on-device shell).

---

## Configuration

**Models** live in `config/apollo.jsonc`. The default is `google/gemini-3.8-flash` (with
`gemini-3.5-flash-lite` for background summaries) and Anthropic Claude models as fallbacks, so a
`GOOGLE_API_KEY` alone runs everything. Presets: `anthropic-opus`, `anthropic-sonnet`,
`gemini-flagship`, `gemini-flash`, `openai-gpt4o`, `cost-saving`, `local-ollama`. Switch for one
run without editing the file:

```sh
APOLLO_LLM_PRESET=gemini-flagship uv run apollo run "…" --standalone --device-serial <udid>
```

**iOS options** live under `agent.ios` in the same file:

| Key | Default | Meaning |
|---|---|---|
| `alerts` | `observe` | `observe` \| `accept` \| `dismiss` — what to do with system permission sheets |
| `recording_backend` | `auto` | `auto` \| `mjpeg` \| `simctl` |
| `wda_settings` | `{}` | extra WebDriverAgent session settings, e.g. `{"snapshotMaxDepth": 40}` |

**Useful environment variables**: `APOLLO_LLM_PRESET`, `APOLLO_IOS_RECORDING_BACKEND`,
`APOLLO_DEFAULT_PROFILE`, `APOLLO_APP_DIR` (cache location), and `APOLLO_MOCK_DRIVER=1` /
`APOLLO_FAKE_LLM=1` for the key-free smokes below.

## Running without a model key

```sh
make smoke-mock     # Flash loop against the in-memory mock driver with a fake LLM — no device
make smoke-sim      # boots a simulator, provisions WDA, runs the driver + SDK smoke and a task
```

`make smoke-sim` is what CI runs on `macos-26`; it needs Xcode but no key.

## Troubleshooting and limits

- **Simulators only for now.** Physical devices need WebDriverAgent signed for the device — see
  [`docs/device-setup.md`](docs/device-setup.md). `apollo doctor` reports what is missing.
- **The iOS 26 simulator is not a phone.** Settings has no Airplane Mode / Wi-Fi / Bluetooth /
  Cellular rows, and there is no Notes, Clock or Mail app. Ask for what the simulator has:
  General, Accessibility, Display, Calendar, Reminders, Contacts, Safari, Maps, Photos, Files,
  Messages.
- **Never quit Simulator.app during a run** — it shuts down every simulator, including the one
  under test.
- **Free-tier Gemini keys** rate-limit long tasks (429 with 40–50 s retry delays). Paid Gemini or
  Claude keys do not.
- **Slow steps on dense screens**: WDA's `/source` takes about a second on screens like the
  Calendar month grid. Lower `agent.ios.wda_settings.snapshotMaxDepth` if steps need to be faster.
- **`apollo doctor` shows a different runner version**: the pinned WebDriverAgent release reports
  `16.12.8` in `/status` although its tag is v16.12.9 — expected, and recorded in
  `apollo/resources/runner_manifest.json`.

---

## Inherited from Artemis

Everything platform-neutral is reused unchanged and documented upstream: the Flash/Pro agent core
(Planner, Operator, Checker, Explorer, Safety Net, history compression, verification levels), the
CLI, the MCP servers, the web console, the SDK, and the LLM provider matrix (Gemini, Vertex,
OpenAI, Anthropic, OpenRouter, xAI, Ollama, vLLM, custom). Apollo replaces the device layer and
the iOS-specific parts of the prompts, diagnostics and console.

## Development

```sh
make install      # uv sync --dev
make lint         # ruff format --check + ruff check + quality ratchet
make test         # hermetic unit suite (no device, no credentials)
make typecheck    # pyright on the protected core
make smoke-sim    # integration smoke on a booted simulator (no model key)
```

CI (`.github/workflows/ci.yml`) runs the unit suite, the frontend build, a wheel smoke test and
the simulator smoke on `macos-26` for every push.

**Documentation**

| Document | What it is for |
|---|---|
| [`docs/roadmap.md`](docs/roadmap.md) | what is delivered, and what each remaining phase contains |
| [`docs/architecture.md`](docs/architecture.md) | how the iOS device layer works, and why |
| [`docs/device-setup.md`](docs/device-setup.md) | preparing a physical iPhone (Phase 3) |
| [`docs/upstream-sync.md`](docs/upstream-sync.md) | merging new work from google/artemis |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | test layers and how to send changes |

## License

[Apache License 2.0](LICENSE). Apollo is derived from Artemis (Copyright 2026 Google LLC), which
includes code from [Minitap, Inc.](https://github.com/minitap-ai/mobile-use); see [`NOTICE`](NOTICE).
