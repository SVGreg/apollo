# Apollo

Apollo is an autonomous, natural-language iOS automation framework: a fork of
[Google Artemis](https://github.com/google/artemis) with the Android device layer replaced by
iOS Simulators and physical iPhones/iPads driven through WebDriverAgent, `xcrun simctl` and
`go-ios`.

> **Status: Phase 0 (bootstrap).** The Artemis agent core, CLI, MCP server, SDK and web console
> are imported and renamed; the iOS driver does not exist yet. Today the only runnable target is
> the in-memory mock driver. See [`docs/development-plan.md`](docs/development-plan.md) for the
> roadmap and [`docs/technical-design.md`](docs/technical-design.md) for the design.

## What works today

```sh
uv sync --dev
APOLLO_MOCK_DRIVER=1 APOLLO_FAKE_LLM=1 uv run apollo run "Open Settings" --profile flash --standalone --device-serial mock-device
```

That exercises the Flash agent loop, trace store and CLI without a device or an LLM key.

Requirements: macOS with Xcode 26.x, [`uv`](https://docs.astral.sh/uv/) (Python 3.12 is pinned in
`.python-version` and downloaded by `uv`).

## Inherited from Artemis

Everything platform-neutral is reused unchanged and is documented upstream:

- Flash / Pro execution profiles (Planner, Operator, Checker, Explorer, Safety Net, history
  compression, verification levels).
- `apollo run | ui | mcp | doctor | batch | trace | server` CLI, `apollo-client` Python SDK,
  MCP tools `mobile_run_task`, `mobile_manage_task`, `mobile_get_device_state`,
  `mobile_inspect_trace`, `mobile_diagnose` for Claude Code / Codex / Cursor / Antigravity.
- Web console (FastAPI + Angular) with live screen, step replay and trace inspection.
- LLM provider matrix: Gemini, Vertex, OpenAI, Anthropic, OpenRouter, xAI, Ollama, vLLM, custom.

`apollo doctor`, `apollo helper`, the device probes and the live-screen stream still target
Android until Phase 1–2 replace them (`docs/technical-design.md` §7).

## Development

```sh
make install      # uv sync --dev
make lint         # ruff format --check + ruff check
make test         # hermetic unit suite (needs GOOGLE_API_KEY set to any value)
uv run pyright --project pyright-core.json
```

Upstream tracking: [`docs/upstream-sync.md`](docs/upstream-sync.md). Phase 0 spike results:
[`docs/spikes.md`](docs/spikes.md). Target workflow (`apollo run` / `batch` / `ui` / `mcp`) and when each
lands: [`docs/development-plan.md#how-apollo-is-used`](docs/development-plan.md#how-apollo-is-used-target-workflow-same-as-artemis).

## License

[Apache License 2.0](LICENSE). Apollo is derived from Artemis (Copyright 2026 Google LLC), which
includes code from [Minitap, Inc.](https://github.com/minitap-ai/mobile-use); see [`NOTICE`](NOTICE).
