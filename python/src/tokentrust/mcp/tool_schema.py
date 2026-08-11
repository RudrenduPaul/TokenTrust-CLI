"""Ported from src/mcp/tool-schema.ts."""

from __future__ import annotations

from typing import Any, Dict, List, Union

from ..adapters.registry import SUPPORTED_PROXIES
from ..adapters.types import ProxyName
from ..verify import DEFAULT_LIVE_MAX_TASKS_OPTION

# Name of the single MCP tool this package exposes. Kept as a named constant (not
# inlined) so the server module and its tests can never drift on the string an MCP
# client actually has to call. Matches the npm package's src/mcp/tool-schema.ts.
VERIFY_TOOL_NAME = "verify_proxy_savings"

VERIFY_TOOL_TITLE = "Verify proxy token/cost savings"

VERIFY_TOOL_DESCRIPTION = (
    "Runs an independent, adversarial verification of an AI-coding-agent context-reduction proxy's "
    "(rtk, headroom) claimed token and cost savings, using the same TT01-TT05 engine as `tokentrust "
    "verify` on the command line: a real local tokenizer (tiktoken, cl100k_base) and the bundled "
    "23-task labeled corpus, with the proxy invoked as a real subprocess rather than re-running the "
    "vendor's own benchmark script. Call this when an agent needs a trustworthy, third-party number "
    "for a proxy's actual compression ratio, cost delta, or output-safety guard -- e.g. before "
    "recommending a proxy, evaluating a version upgrade, or checking a CI regression -- not for "
    "general token counting or for proxies outside {rtk, headroom} (headroom is recognized but not "
    "yet runnable; the report notes this rather than failing). No API key or network access is "
    "required in the default (non-live) mode, which estimates cost from published pricing tables; "
    "it only needs the proxy binary and a task corpus to already be present on disk.\n\n"
    "Side effects: read-only against `repo` (the proxy runs against the task corpus; the target repo "
    "itself is never modified) and it appends a versioned run record keyed by `run_id` to local "
    "on-disk history so a later TT05 call can diff a new run against the prior one for the same "
    "proxy/repo pair -- safe to retry, but not idempotent output-wise, since every run gets a fresh "
    "`run_id`. Setting BOTH `live` and `confirmCost` to true additionally makes real, provider-billed "
    "API calls against your own key (env-configured, never passed as a parameter) for up to "
    "`liveMaxTasks` tasks; omit either one and zero network calls are made. A failed or refused run "
    "(missing proxy binary, invalid task corpus, or the live safety gate declining the call) still "
    "returns a CallToolResult with isError=true and a JSON `{ok: false, exit_code, message}` body "
    "explaining why, instead of throwing.\n\n"
    "Parameters: `proxy` (required) is a proxy name or array of names from {rtk, headroom} -- pass an "
    "array to run TT04's cross-tool comparison in one call. `repo` (optional) is a filesystem path, "
    "defaulting to this server's own working directory. `tasks` (optional) is a path to a "
    "tokentrust-tasks.yml corpus, defaulting to the bundled 23-task set. `live`/`confirmCost` "
    "(optional booleans, both false by default) gate real billed sampling as described above. "
    "`liveMaxTasks` (optional integer, default 5) caps how many tasks live mode samples. Example "
    "calls: {\"proxy\": \"rtk\"} for a standard estimated-cost run against the bundled corpus; "
    "{\"proxy\": [\"rtk\", \"headroom\"], \"repo\": \"/path/to/target-repo\"} for a side-by-side TT04 "
    "comparison against a specific repo; {\"proxy\": \"rtk\", \"live\": true, \"confirmCost\": true, "
    "\"liveMaxTasks\": 3} to verify the cost estimate against 3 real, billed samples.\n\n"
    "Returns: the same structured JSON `tokentrust verify --format json` produces on success -- "
    "`run_id`, `timestamp`, `repo`, `task_corpus_size`, `proxies`, a `records` array (one entry per "
    "proxy/category with `claimed_savings_pct` vs `measured_savings_pct`), plus `tt03` (never-worse "
    "guard pass/fail per proxy) and `tt05` (version-drift regression pass/fail per proxy) maps. Run "
    "`tokentrust verify --help` on the command line for the full flag reference this schema mirrors."
)

# Raw JSON Schema for the tool's `inputSchema`, handed straight to mcp.types.Tool(inputSchema=...).
# Field names are deliberately camelCase (confirmCost, liveMaxTasks) even though the rest of this
# Python port uses snake_case -- this is the tool's WIRE contract, and it must match the npm
# package's verify_proxy_savings tool (src/mcp/tool-schema.ts) exactly, since a real MCP client
# calling either language's server should see an identical tool. mcp/server.py translates a parsed
# call's camelCase arguments into the snake_case VerifyOptions fields internally.
#
# Mirrors cli.py's `verify` flags one-for-one, MINUS `--format`: an MCP tool call is always
# machine-facing, so this tool always returns the structured JSON report and never exposes a
# format choice.
VERIFY_PROXY_SAVINGS_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "proxy": {
            "anyOf": [
                {"type": "string", "enum": list(SUPPORTED_PROXIES)},
                {
                    "type": "array",
                    "items": {"type": "string", "enum": list(SUPPORTED_PROXIES)},
                    "minItems": 1,
                },
            ],
            "description": (
                'Proxy name to verify. Pass a single name (e.g. "rtk") or an array of names to run '
                "the TT04 cross-tool comparison across all of them in one call -- mirrors the CLI's "
                f"repeatable --proxy flag. Supported: {', '.join(SUPPORTED_PROXIES)}."
            ),
        },
        "repo": {
            "type": "string",
            "description": (
                "Filesystem path to the repo to measure against. Defaults to the MCP server "
                "process's current working directory, same as the CLI's --repo default."
            ),
        },
        "tasks": {
            "type": "string",
            "description": (
                "Path to a task corpus YAML file. Defaults to the bundled task corpus shipped with "
                "the package, same as the CLI's --tasks default."
            ),
        },
        "live": {
            "type": "boolean",
            "description": (
                "Sample real, provider-billed tokens for the first proxy instead of estimating from "
                "local pricing tables. Requires confirmCost=true in the SAME call, exactly like the "
                "CLI's --live/--confirm-cost safety gate -- setting only one of the two makes zero "
                "API calls and reports the refusal instead. Defaults to false."
            ),
        },
        "confirmCost": {
            "type": "boolean",
            "description": (
                "Confirms the estimated spend `live` mode would print before any real, billed API "
                "call is made. Defaults to false. Has no effect unless `live` is also true."
            ),
        },
        "liveMaxTasks": {
            "type": "integer",
            "exclusiveMinimum": 0,
            "description": f"Max tasks sampled in live mode. Defaults to {DEFAULT_LIVE_MAX_TASKS_OPTION}.",
        },
    },
    "required": ["proxy"],
}


def normalize_proxy_input(proxy: Union[ProxyName, List[ProxyName]]) -> List[ProxyName]:
    """Normalizes the tool's `proxy` field (single name or array) into the list run_verify() expects."""
    if isinstance(proxy, list):
        return proxy
    return [proxy]
