# Upstream sync — google/artemis

Apollo is a fork of [google/artemis](https://github.com/google/artemis). The Android device layer
is replaced (see [`architecture.md`](architecture.md) §7), everything else is meant to track upstream.

## Baseline

| | |
|---|---|
| Upstream remote | `https://github.com/google/artemis` |
| Imported SHA | `371aa6df56880643da57b30da936e9812fb0ec66` (2026-09-11, "fix: complete README and relevant file headers per Apache 2.0 requirements") |
| Import commit | `2c20d70` — `git merge --allow-unrelated-histories` of that SHA into `main`, so upstream history is a shared ancestor and later syncs are ordinary merges. |
| Last synced | 2026-09-20 (initial import) |

## One-time setup on a fresh clone

```sh
git remote add upstream https://github.com/google/artemis
git config merge.renames true
git config diff.renameLimit 10000       # artemis/ → apollo/ is a whole-tree rename
git config merge.renameLimit 10000
```

## Monthly sync recipe

```sh
git fetch upstream
git checkout -b sync/upstream-$(date +%Y%m%d) main
git merge upstream/main
```

Git's rename detection maps `artemis/**` → `apollo/**` and `packages/artemis-client/**` →
`packages/apollo-client/**` automatically because the rename commit is a pure `git mv` plus text
substitution. Expect conflicts only in:

- **Identifier text** — any upstream hunk that mentions `artemis`, `Artemis`, `ARTEMIS_`,
  `artemis_client` in code or prose. Resolve by taking upstream's hunk and applying the
  substitution table below.
- **Files replaced by design** (see [`architecture.md`](architecture.md) §7):
  `apollo/drivers/factory.py`, `apollo/drivers/ios/*`,
  `apollo/controllers/{unified_controller,platform_specific_commands_controller}.py`,
  `apollo/mcp/{adb_server,device_server}.py`, `apollo/clients/{wda_client,simctl,goios}.py`,
  `apollo/runtime/runner_manager.py`, `apollo/core/diagnostics/*`,
  `mcp_server/tools/diagnose.py`, `mcp_server/rules.md`,
  `apollo/interfaces/cli/commands/{runner,doctor}.py`,
  `apps/admin_console/services/device_stream_service.py`, `apps/showcase_ui/src/*`,
  `start.sh`, `Makefile`, `scripts/install_deps.sh`, `.github/workflows/ci.yml`, `README.md`,
  prompts under `apollo/agents/*`, `config/apollo.jsonc`, `pyproject.toml`, `uv.lock`.
  For these, read the upstream diff and port the intent; do not take upstream's version.
- **Deleted in Apollo**: `packages/artemis-accessibility-helper/`, `playground/`, `Dockerfile`,
  `.dockerignore`, `start.bat`, `scripts/*.ps1`. Upstream changes there are dropped
  (`git rm` on conflict).

After resolving: `uv lock`, `uv sync --dev --locked`, `make lint`, `make test`, `make typecheck`,
`make smoke-mock` and `make smoke-sim` (needs a Mac with Xcode), then update the **Last synced**
row above in the same commit. CI runs the same gates on the sync branch.

## Substitution table (rename commit)

Applied in this order to every tracked text file except `LICENSE`, `NOTICE`, `docs/*.md`,
Google copyright headers and the upstream GitHub URL:

| From | To |
|---|---|
| `artemis_client` | `apollo_client` |
| `artemis-client` | `apollo-client` |
| `ArtemisContext` | `ApolloContext` |
| `ARTEMIS_` | `APOLLO_` |
| `artemis.jsonc` | `apollo.jsonc` |
| `\bartemis\b` | `apollo` |
| `Artemis` | `Apollo` |
| `ARTEMIS` | `APOLLO` |
