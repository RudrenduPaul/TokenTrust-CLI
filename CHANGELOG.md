# Changelog

All notable changes to this project are documented in this file. This file covers both the npm
package (`tokentrust-cli`, TypeScript, repo root) and the PyPI package (`tokentrust-cli`,
Python, `python/`) -- since they run the same verification categories against the same task
corpus, entries note which distribution they apply to.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [0.3.3] - 2026-08-08 (PyPI)

Bug fix. `python/src/tokentrust/__init__.py`'s `__version__` was a
hardcoded `"0.2.0"` string that had drifted from the real published
version -- the live PyPI package was already 0.3.1, so
`import tokentrust; tokentrust.__version__` reported a stale, wrong
version to any caller. `__version__` now reads live from the installed
package's own metadata via `importlib.metadata.version("tokentrust-cli")`.
Also ships the previously-committed-but-never-published 0.3.2 metadata
bump (README FAQ, demo GIFs).

## [0.3.0] - 2026-07-18

### Added

- **MCP (Model Context Protocol) server mode.** `tokentrust mcp` starts an MCP server over
  stdio, exposing one tool, `verify_proxy_savings`, so any MCP-compatible agent (Claude Code,
  Claude Desktop, or any other MCP client) can call TokenTrust programmatically instead of
  shelling out to the CLI and parsing terminal output. The tool's input mirrors `verify`'s flags
  one-for-one (`proxy`, `repo`, `tasks`, `live`, `confirmCost`, `liveMaxTasks`) minus `--format`
  -- an MCP tool call is always machine-facing, so the tool always returns the same structured
  JSON report `tokentrust verify --format json` already produces. New module
  `src/mcp/server.ts` calls straight into the existing `runVerify()` engine (`src/verify.ts`);
  no verification logic is duplicated. The `--live`/`--confirm-cost` safety gate is enforced
  identically to the CLI: no live, provider-billed API call is made from a tool call unless both
  are explicitly set to `true` in the same call. Added `@modelcontextprotocol/sdk` and `zod` as
  dependencies. Same dual CLI + MCP-server pattern already shipped by Semgrep, Trivy, Snyk, and
  SonarQube: one binary, one underlying engine, a thin additional transport.
- `VerifyDependencies.printProgress` (`src/verify.ts`): the per-task progress ticker
  (`report/terminal.ts`'s `printProgress()`) previously wrote straight to `process.stdout`,
  bypassing the existing `print()` dependency entirely. That's fine for the CLI, but wrong for
  the new MCP stdio transport, where stdout is a live JSON-RPC stream and a stray progress line
  would corrupt it. This is now an injectable dependency (defaulting to the original
  stdout-writing behavior, so `tokentrust verify`'s own output is unchanged); the MCP server
  overrides it to route to stderr instead.

## [Python 0.3.0] - 2026-07-18

### Added

- **MCP (Model Context Protocol) server mode**, mirroring the npm package's `[0.3.0]` entry
  above one-for-one: `tokentrust mcp` (the `tokentrust` console script's new subcommand) starts
  an MCP server over stdio, exposing one tool, `verify_proxy_savings`, so any MCP-compatible
  agent can call TokenTrust programmatically instead of shelling out to the CLI. The tool's wire
  schema is byte-identical to the npm package's (`proxy`, `repo`, `tasks`, `live`, `confirmCost`,
  `liveMaxTasks`, no `format`) so a real MCP client sees the same tool contract from either
  language's server, even though the field names stay camelCase on the wire while the rest of
  this port uses snake_case internally. New modules `python/src/tokentrust/mcp/tool_schema.py`
  (the JSON Schema `inputSchema` plus `normalize_proxy_input()`) and
  `python/src/tokentrust/mcp/server.py` (`create_tokentrust_mcp_server()`, `start_mcp_server()`)
  call straight into the existing `run_verify()` engine (`python/src/tokentrust/verify.py`); no
  verification logic is duplicated. The `--live`/`--confirm-cost` safety gate is enforced
  identically to the CLI: no live, provider-billed API call is made from a tool call unless both
  are explicitly `true` in the same call -- covered by a real request/response round trip test
  (`python/tests/test_mcp_server.py`, using the official MCP Python SDK's in-memory session
  helper) asserting the injected live API client is never invoked. Built on the official `mcp`
  PyPI package (the Python counterpart of `@modelcontextprotocol/sdk`), added as a new
  dependency; `run_verify()` itself is synchronous, so the tool handler offloads it to a worker
  thread (`anyio.to_thread.run_sync`) instead of blocking the server's event loop.
- `VerifyDependencies.print_progress` (`python/src/tokentrust/verify.py`): the same fix as the
  npm package's `VerifyDependencies.printProgress` above, for the same reason. The per-task
  progress ticker (`report/terminal.py`'s `print_progress()`) previously wrote straight to
  `sys.stdout`, bypassing the existing `print_fn` dependency entirely -- fine for the CLI, wrong
  for the new MCP stdio transport, where stdout is the live JSON-RPC wire. Now an injectable
  dependency (defaulting to the original stdout-writing behavior, so `tokentrust verify`'s own
  output is unchanged); the MCP server overrides it to route to stderr instead. Verified with a
  real spawned `tokentrust mcp` subprocess talking real stdio to a real MCP client session: the
  child's stderr was captured separately from the JSON-RPC stdout stream, confirming the
  "Measuring..." trace and the printed report only ever appear on stderr.

### Changed

- **`requires-python` raised from `>=3.9` to `>=3.10`** (Python 3.9 support dropped). The `mcp`
  PyPI package this release depends on requires Python `>=3.10`; every other dependency and this
  port's own code remain compatible with 3.10 unchanged. `python/pyproject.toml`'s classifiers
  updated to match (3.9 removed).
- Dev-only dependency `pytest` raised from `>=7.0,<9` to `>=9.0.3,<10`, per `pip-audit`: `pytest`
  `<9.0.3` is `CVE-2025-71176` / `GHSA-6w46-j5rx-g56g` (predictable `/tmp/pytest-of-{user}`
  directory naming on UNIX, local privilege/DoS risk). Dev-only, never shipped inside an
  installed `tokentrust-cli`, fixed anyway to keep the dependency tree clean of known
  vulnerabilities. `pytest-cov` (already required by `CONTRIBUTING.md`'s documented
  `pytest --cov=tokentrust --cov-report=term-missing` command but previously undeclared) added
  to the `dev` extra.

## [Python 0.2.1] - 2026-07-16

Docs-only patch release. No source or behavior changes.

### Changed

- `python/README.md` expanded from a thin 114-line quickstart into the full reference-depth
  structure other ported packages in this project use: added a real "Why this exists" section
  (independently verifying rtk/headroom's own reported token and cost savings against a real
  local tokenizer and labeled task corpus, grounded in the same real `rtk` issue-tracker evidence
  the npm README cites), a real "Security" section (subprocess invocation with no shell, the
  `TOKENTRUST_LIVE_API_KEY` env-var-only credential path for opt-in `--live` mode, disclosure via
  GitHub Security Advisories, and an honest statement of what security automation is and isn't
  configured today), and a real "CI integration" section (a runnable GitHub Actions example gating
  a build on `tokentrust verify`'s exit code and JSON report). No other section was changed.

## [Python 0.2.0] - 2026-07-17

Initial public release of the Python port, published to PyPI as `tokentrust-cli`
(`pip install tokentrust-cli`). Complementary to, not a replacement for, the existing npm
package -- both are first-class and maintained together, and both ship the version-matched
`0.2.0` verification logic (the two-proxy `rtk`/`headroom` registry, the `ProxyName` shape after
the third adapter's removal). See `python/README.md` for Python-specific usage.

### Added

- `tokentrust verify --proxy <name> [options]` CLI (console script `tokentrust`, package
  `tokentrust`), with the same flags, defaults, and `--help` text as the npm CLI: `--repo`,
  `--tasks`, `--live`, `--confirm-cost`, `--live-max-tasks` (default 5), `--format`
  (terminal/json).
- Programmatic library API: `from tokentrust.verify import run_verify, VerifyOptions,
  VerifyDependencies`, returning the same `VerifyOutcome` shape (`exit_code`, `report_path`,
  `report`) as the underlying pipeline the CLI itself calls.
- TT01-TT05 verification categories reimplemented as genuine Python logic against the same
  `fixtures/tasks.yml` corpus (23 tasks) bundled inside the npm package, copied verbatim into
  the Python wheel -- the two distributions read byte-identical fixture content.
- Local tokenizer wrapper using `tiktoken` (`cl100k_base` encoding), verified to produce
  byte-for-byte identical token counts to the npm package's `js-tiktoken` dependency on real
  sample text before this port shipped (see `CONTRIBUTING.md`'s tokenizer-parity note). One real
  behavioral difference: `tiktoken` fetches and caches the `cl100k_base` rank data from a public
  endpoint on first use in a fresh environment, where `js-tiktoken` bundles the same data inside
  the npm package for fully offline operation from the first run -- documented in
  `python/docs/getting-started.md`.
- `rtk` and `headroom` proxy adapters, each shelling out to the proxy binary via
  `subprocess.run`, mirroring the npm package's `child_process.spawn`-based `BaseAdapter`.
  `headroom` remains recognized but not yet drivable in v0.1, for the same real reason as the
  npm package: its CLI surface is an HTTP proxy server, not a one-shot compress command.
- Structured JSON report writer and human-readable terminal report, with a live progress
  indicator during measurement -- output format matches the npm CLI line for line (aside from
  the underlying language's default whitespace/serialization conventions).
- Full pytest suite (100+ tests) ported from the TypeScript vitest suite, covering the
  tokenizer's named failure path, task-corpus schema validation (including the
  path-traversal/absolute-path security checks), every TT01-TT05 category, the CLI flag parser,
  and an end-to-end `run_verify()` pass with an injected fake adapter -- all TT01-TT05 category
  modules at 99-100% statement coverage.
- `docs/getting-started.md`, `docs/concepts.md`, and `docs/integrations/ci.md`, plus three
  runnable `examples/` scripts (basic verify, a JSON-report CI gate, and a direct TT04
  cross-tool-comparison call) using the real library API.

### Verified

- A live run of this Python package's `tokentrust verify --proxy rtk` against the real,
  installed `rtk 0.43.0` binary and the bundled 23-task corpus produced measured numbers
  identical to the npm package's `dist/cli.js` run against the same corpus at the same moment:
  60.7% average TT01 reduction, the same min/max tasks and percentages, and 2/23 TT03
  regressions -- see `python/docs/getting-started.md`'s real captured output.

## [0.2.0] - 2026-07-15

### Removed

- **Third proxy adapter removed**, dropped entirely: its source file and test suite are
  deleted, `ProxyName` is now `'rtk' | 'headroom'`, and the adapter registry, CLI `--proxy`
  validation/help text, README, and GitHub Action example all updated to reflect only `rtk`
  and `headroom` as supported proxies. This is a breaking change for anyone passing the
  removed proxy's flag value to `--proxy` — it is no longer recognized. Reason: the adapter's
  name collided with an unrelated internal tool name, and removing it eliminates the
  ambiguity going forward.

## [0.1.2] - 2026-07-13

### Changed

- **Package renamed from `tokentrust` to `tokentrust-cli`** on the npm registry, and the
  GitHub repo renamed from `TokenTrust` to `TokenTrust-CLI`, to make the project's CLI
  identity explicit for discoverability. The installed command itself is unchanged --
  it's still `tokentrust` (e.g. `npx tokentrust-cli verify --proxy rtk` installs the
  renamed package and runs the same `tokentrust` binary as before). The old `tokentrust`
  package on npm is deprecated and points to `tokentrust-cli`; it is not unpublished.
- Bundled GitHub Action (`action/action.yml`) updated to invoke `npx tokentrust-cli`
  internally instead of the now-deprecated `npx tokentrust`.
- All repo/package references in README and CONTRIBUTING.md updated to the
  new names.

## [0.1.1] - 2026-07-12

### Changed

- README: updated the Install section and npm badge now that `tokentrust` is
  live on the npm registry -- `npx tokentrust verify --proxy rtk` replaces
  the old "install from source" instructions.

## [0.1.0] - 2026-07-12

### Added

- `tokentrust verify` CLI — benchmark harness for token/context-reduction
  proxies (`rtk`, `headroom`, and a third adapter later removed in 0.2.0 —
  see [0.2.0](#020---2026-07-15)), with `--proxy` (repeatable),
  `--repo` (defaults to the current working directory), `--tasks` (defaults
  to the bundled 12-task corpus), `--live`, `--confirm-cost`,
  `--live-max-tasks`, and `--format` flags.
- TT01 Compression Ratio Verification — measures actual context-token
  reduction with a local tokenizer against a labeled task corpus.
- TT02 Cost-Savings Delta — computes actual dollar-cost savings at
  published model pricing from TT01's measured token delta. Ships an
  opt-in `--live` mode that verifies the local-tokenizer estimate against a
  real, provider-billed sample — gated behind `--confirm-cost` and a
  default 5-task cap (`--live-max-tasks`), with the API key read only from
  an environment variable, never a CLI flag.
- TT03 Never-Worse Output Guard — checks whether a proxy's compressed
  output drops content a task's fixture marks as required to survive
  compression.
- TT04 Cross-Tool Comparative Benchmark — runs the identical task corpus
  through every supported proxy side by side; errors if the compared
  proxies were not run against identical corpora.
- TT05 Version-Drift Regression Detection — compares a run's measured
  savings against the last-verified baseline for the same proxy/repo pair,
  chained via `prior_run_id`; degrades gracefully to "no drift comparison
  available" if the local report store is missing or corrupted.
- `ProxyAdapter` interface and three concrete adapters (`rtk`, `headroom`,
  and a third later removed in 0.2.0), each shelling out to its proxy as
  an external process.
- Local, dependency-free tokenizer wrapper (`js-tiktoken`), with a named
  failure path for malformed/non-UTF8 input (WARN + skip, never crash the
  batch).
- Structured JSON report writer (`run_id`, `proxy`, `proxy_version`,
  `category`, `claimed_savings_pct`, `measured_savings_pct`,
  `task_corpus_size`, `prior_run_id`) and a human-readable terminal report
  with a live progress indicator during the measurement phase.
- Bundled default 12-task fixture corpus (`fixtures/tasks.yml` +
  `fixtures/repos/`), varying difficulty and task type, so
  `npx tokentrust verify --proxy rtk` works with zero other flags.
- GitHub Action wrapper (`action/action.yml`) for CI-triggered
  re-verification on proxy version bumps.
- CI workflow (lint → typecheck → test → npm audit) and a tagged-release
  npm publish workflow.

### Changed

- `RtkAdapter` now invokes rtk's real CLI surface instead of an invented
  `rtk compress --stdin` command that never existed on the real binary:
  `rtk pipe --filter <name>` (stdin-based, for filter-tagged tasks) or
  `rtk read -l aggressive <files>` (file-based, for the 12 original fixture
  tasks), chosen per task. `BaseAdapter` gained an overridable
  `buildCompressInvocation()` hook so each adapter can express this without
  duplicating `run()`'s spawn/error-handling logic.
- Task schema gained an additive, optional `filter` field
  (`fixtures/tasks.yml` / `src/tasks/types.ts`) naming one of rtk's 18 real
  `rtk pipe --filter` values. `loadFixtureContext()` now returns a filter
  task's fixture content completely raw (no `--- path ---` header, no
  `--- PROMPT ---` suffix) so the measured "before" and "after" text match
  the literal shape a real `<tool> | rtk pipe --filter X` invocation sees.
  Omitting `filter` keeps a task's previous file-based behavior unchanged.
- Bundled default corpus grew from 12 to 15 tasks: three new filter-tagged
  tasks (`verify-git-log-filter`, `verify-git-diff-filter`,
  `verify-vitest-filter`) built from real captured `git log`, `git diff`,
  and `vitest run` output from this repo's own history and test suite.
- `--proxy headroom` is now intercepted in `runVerify()`'s dispatch loop,
  before a `HeadroomAdapter` is ever constructed, and prints a documented
  message explaining that headroom's real CLI surface is an HTTP proxy
  server (`headroom proxy`), not a one-shot compression command, so it
  cannot be driven by v0.1's subprocess-based harness. `--proxy headroom`
  remains a recognized flag value; it just doesn't produce a verification
  report yet. `--proxy rtk --proxy headroom` still verifies rtk and
  produces a report -- only headroom is skipped.

### Notes

- TT06 (telemetry/data-handling disclosure) and TT07 (hosted team
  budget/quota enforcement) are out of scope for v0.1.
- headroom support (behind a real HTTP-proxy-traffic test harness) and
  the third adapter's support (removed in 0.2.0) are both out of scope
  for v0.1.
