# Contributing to Apollo

Bug reports, feature ideas, documentation fixes and code are all welcome. Apollo is an iOS-only
fork of [Artemis](https://github.com/google/artemis); changes that belong upstream are better sent
there, so they reach Apollo through the [monthly sync](docs/upstream-sync.md).

## Sending a change

1. Fork the repository and branch (`git checkout -b feat/my-feature`).
2. Make the change, then run the gates below.
3. Open a pull request describing what changed and how you verified it. CI runs the same gates on
   `macos-26` plus the simulator smoke.

```sh
make lint         # ruff format --check, ruff check, quality ratchet
make test         # hermetic unit suite — no device, no credentials
make typecheck    # pyright on the protected core
```

If your change touches the device layer, also run the integration smoke on a Mac with Xcode:

```sh
make smoke-sim    # boots a simulator, provisions WebDriverAgent, driver + SDK smoke, fake-LLM task
```

Keep edits to inherited Artemis files as small as possible — every line changed there is a line to
re-resolve at the next upstream merge. Prefer adding an iOS file over editing a shared one.

## Test layers

| Command | Scope | Needs |
|---|---|---|
| `make test` | deterministic unit suite; the required gate for every PR | nothing |
| `make smoke-mock` | the agent loop against the in-memory mock driver and a fake LLM | nothing |
| `make smoke-sim` | real simulator: WDA provisioning, driver smoke, hierarchy parity, SDK contract, one fake-LLM task | macOS + Xcode |
| `make test-integration` | cross-component tests | may need model credentials |
| `make test-all` | every tree | a fully provisioned machine |

Tests that need external state must carry the right marker so the default suite stays collectable
without it: `ios_sim` (a booted simulator), `integration`, `e2e`, `cloud`, `manual`. The default
`pytest` run deselects all of them.

## Conventions

- Python 3.12, `ruff format` (line length as configured), type hints on new public functions.
- No new broad `except Exception` handlers or `# type: ignore` comments — `scripts/quality_ratchet.py`
  fails the build when the counts rise. Catch the specific error instead.
- User-facing strings (CLI help, probe descriptions, prompts) should say what to do next.
