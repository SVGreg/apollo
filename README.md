# Apollo

Apollo is an autonomous, natural-language iOS automation framework: a fork of
[Google Artemis](https://github.com/google/artemis) with the Android device layer replaced by
iOS Simulators and physical iPhones/iPads driven through WebDriverAgent, `xcrun simctl` and
`go-ios`.

> **Status: Phase 1a (simulator thin slice).** `apollo run` drives a booted iOS Simulator through
> WebDriverAgent with the Flash profile. Web console, MCP install and `apollo doctor` are next
> (Phase 1b). See [`docs/development-plan.md`](docs/development-plan.md) for the roadmap and
> [`docs/technical-design.md`](docs/technical-design.md) for the design.

## Quick start

Requirements: macOS with Xcode 26.x and an iOS 26 simulator runtime, [`uv`](https://docs.astral.sh/uv/)
(Python 3.12 is pinned in `.python-version` and downloaded by `uv`), and an LLM API key.

```sh
git clone git@github.com:SVGreg/apollo.git && cd apollo
make install                              # uv sync --dev
cp .env.example .env                      # then set ANTHROPIC_API_KEY=… (default provider)
                                          # or GOOGLE_API_KEY=… / OPENAI_API_KEY=…
xcrun simctl list devices available | grep iPhone
xcrun simctl boot <udid>                  # e.g. "iPhone 17 Pro" (boots headless; keep Simulator.app open if you launch it)
```

Run a task:

```sh
uv run apollo run "Open Settings, go to General > About and tell me the iOS version" \
    --profile flash --standalone --device-serial <udid> --verification-level final
```

The first run downloads WebDriverAgent (pinned v16.12.9, checksum-verified), installs it on the
simulator and starts it; later runs reuse it. The Operator sees a screenshot plus the accessibility
tree of the foreground app and acts through taps, swipes, typing and app launches.

### Everyday commands

```sh
# Flash (fast, single loop) or Pro (Planner + Operator + Checker); final verification on
uv run apollo run "<goal>" --profile flash|pro --standalone --device-serial <udid> --verification-level final

# Test your own app: install a simulator build, keep the agent inside it
uv run apollo run "Log in as demo/demo and confirm the cart badge shows 2" \
    --app-path build/MyApp.app --locked-app com.acme.myapp --standalone --device-serial <udid>

# Regression list, one goal per line
uv run apollo batch --file tasks.txt --profile flash --standalone

# Inspect what happened (screenshots, hierarchy, actions, reasoning per step)
uv run apollo trace list
uv run apollo trace view <session>
```

Traces land in `traces/<session>_PASS|FAIL_<timestamp>/`.

### Choosing the model

Models live in `config/apollo.jsonc`. The default is `anthropic/claude-sonnet-5` with
`claude-opus-5` as fallback and `claude-haiku-4-5` for background summaries. Presets:
`anthropic-opus`, `anthropic-sonnet`, `gemini-flagship`, `gemini-flash`, `openai-gpt4o`,
`cost-saving`, `local-ollama`. Switch for one run without editing the file:

```sh
APOLLO_LLM_PRESET=gemini-flagship uv run apollo run "…" --standalone --device-serial <udid>
```

Free-tier Gemini keys rate-limit long tasks (429 with 40–50 s retry delays); Claude keys have no
such issue in our runs.

### Without a device or key

```sh
make smoke-mock     # Flash loop against the in-memory mock driver with a fake LLM
```

### Known limits (Phase 1a)

- Simulators only; physical devices arrive in Phase 3 (needs a signing-capable Apple account).
- The simulator's Settings has no Airplane Mode / Wi-Fi / Bluetooth / Cellular rows; ask for
  things the simulator has (General, Accessibility, Display, Calendar, Reminders, Contacts, Safari,
  Maps, Photos, Files, Messages). There is no Notes, Clock or Mail app on the iOS 26 runtime.
- Screen recording, the web console's device panel/live view, `apollo doctor` and `apollo mcp
  --install` still assume Android; they are Phase 1b/2 work.
- `run_adb_command` is replaced by an allowlisted `simctl` host command on iOS
  (`simctl openurl …`, `simctl listapps`, `simctl privacy grant …`); there is no on-device shell.

## Inherited from Artemis

Everything platform-neutral is reused unchanged and is documented upstream:

- Flash / Pro execution profiles (Planner, Operator, Checker, Explorer, Safety Net, history
  compression, verification levels).
- `apollo run | ui | mcp | doctor | batch | trace | server` CLI, `apollo-client` Python SDK,
  MCP tools `mobile_run_task`, `mobile_manage_task`, `mobile_get_device_state`,
  `mobile_inspect_trace`, `mobile_diagnose` for Claude Code / Codex / Cursor / Antigravity.
- Web console (FastAPI + Angular) with live screen, step replay and trace inspection.
- LLM provider matrix: Gemini, Vertex, OpenAI, Anthropic, OpenRouter, xAI, Ollama, vLLM, custom.


## Development

```sh
make install      # uv sync --dev
make lint         # ruff format --check + ruff check
make test         # hermetic unit suite (a placeholder GOOGLE_API_KEY is supplied)
uv run pyright --project pyright-core.json
```

Upstream tracking: [`docs/upstream-sync.md`](docs/upstream-sync.md). Phase 0 spike results:
[`docs/spikes.md`](docs/spikes.md). Target workflow (`apollo run` / `batch` / `ui` / `mcp`) and when each
lands: [`docs/development-plan.md#how-apollo-is-used`](docs/development-plan.md#how-apollo-is-used-target-workflow-same-as-artemis).

## License

[Apache License 2.0](LICENSE). Apollo is derived from Artemis (Copyright 2026 Google LLC), which
includes code from [Minitap, Inc.](https://github.com/minitap-ai/mobile-use); see [`NOTICE`](NOTICE).
