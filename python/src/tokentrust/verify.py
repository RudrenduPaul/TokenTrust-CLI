"""Ported from src/verify.ts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .adapters.registry import get_adapter as _default_get_adapter
from .adapters.types import MissingBinaryError, ProxyAdapter, ProxyExecutionError, ProxyName
from .categories.claims import get_claimed_savings
from .categories.live_api_client import anthropic_live_api_client
from .categories.tt01_compression_ratio import Tt01Result, run_tt01
from .categories.tt02_cost_delta import (
    DEFAULT_LIVE_MAX_TASKS,
    LiveModeOptions,
    estimate_live_cost,
    evaluate_live_gate,
    resolve_live_api_key,
    run_live_verification,
    run_tt02_default,
)
from .categories.tt03_never_worse_guard import run_tt03
from .categories.tt04_cross_tool_benchmark import CorpusMismatchError, run_tt04
from .categories.tt05_version_drift import (
    DEFAULT_STORE_PATH,
    ReportStoreRun,
    append_run,
    load_report_store,
    run_tt05,
    write_report_store,
)
from .report.json_report import build_report_record, generate_run_id, serialize_report, write_report
from .report.terminal import (
    Tt01Summary,
    Tt02Summary,
    Tt03Summary,
    Tt04Summary,
    Tt05Summary,
    TerminalReportInput,
    print_progress,
    render_terminal_report,
)
from .report.types import FullReport, Tt03ReportEntry, Tt05ReportEntry
from .tasks.loader import TaskSchemaError, load_fixture_context, load_task_corpus


class CliUsageError(Exception):
    pass


# headroom's real CLI surface is an HTTP proxy server (`headroom proxy`),
# not a one-shot compression command -- this port's subprocess-based
# harness (spawn a binary, pipe stdin, read stdout) cannot drive it. This
# is printed and the proxy is skipped BEFORE a HeadroomAdapter is ever
# constructed, rather than letting a (nonexistent) compress invocation fail
# "naturally". `--proxy headroom` remains a recognized flag value
# (is_supported_proxy('headroom') stays True) -- it just doesn't produce a
# verification report yet.
HEADROOM_NOT_YET_SUPPORTED_MESSAGE = (
    "headroom is recognized but not yet supported for verification in TokenTrust v0.1: headroom's "
    'real CLI surface is an HTTP proxy server ("headroom proxy"), not a one-shot compression command, '
    "so it cannot be driven by this version's subprocess-based harness (spawn a binary, pipe stdin, "
    "read stdout). Support is planned for a future version behind a real HTTP-proxy-traffic test "
    "harness -- see CONTRIBUTING.md."
)

DEFAULT_LIVE_MAX_TASKS_OPTION = DEFAULT_LIVE_MAX_TASKS

# The variable name is spelled out as a literal (a test pins it to
# tt02_cost_delta.LIVE_API_KEY_ENV_VAR) so that no value derived from a
# credential-named identifier flows into the printed output.
MISSING_LIVE_KEY_MESSAGE = (
    "Error: --live requires TOKENTRUST_LIVE_API_KEY to be set in the environment. No API call was made."
)


def resolve_default_tasks_path() -> str:
    """Resolves the bundled default task corpus shipped inside the pip package."""
    here = Path(__file__).resolve().parent
    return str(here / "fixtures" / "tasks.yml")


@dataclass(frozen=True)
class VerifyOptions:
    proxies: List[ProxyName]
    repo: str
    tasks_path: str
    live: bool
    confirm_cost: bool
    live_max_tasks: int
    format: str  # 'terminal' | 'json'


@dataclass
class VerifyDependencies:
    get_adapter: Optional[Callable[[ProxyName], ProxyAdapter]] = None
    now: Optional[Callable[[], datetime]] = None
    live_api_client: Optional[Callable] = None
    store_path: Optional[str] = None
    print_fn: Optional[Callable[[str], None]] = None
    env: Optional[Dict[str, str]] = None
    report_out_path: Optional[str] = None
    # The per-task progress ticker (report/terminal.py's print_progress()) writes
    # straight to sys.stdout, bypassing print_fn entirely -- fine for the CLI, but
    # wrong for the MCP stdio transport (mcp/server.py), where stdout is a live
    # JSON-RPC stream and a stray progress line would corrupt it. Injectable here
    # (defaulting to the original stdout-writing behavior, so `tokentrust verify`'s
    # own output is unchanged) so the MCP server can override it to route to
    # stderr instead. Mirrors src/verify.ts's VerifyDependencies.printProgress.
    print_progress: Optional[Callable[[int, int], None]] = None


@dataclass
class VerifyOutcome:
    exit_code: int
    report_path: Optional[str] = None
    report: Optional[FullReport] = None


def _to_iso_millis(dt: datetime) -> str:
    """Matches JS `Date.prototype.toISOString()`: millisecond precision, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _compute_min_max_task(tt01: Tt01Result) -> dict:
    counted = [t for t in tt01.per_task if not t.skipped]
    if not counted:
        return {"min": {"id": "n/a", "pct": 0}, "max": {"id": "n/a", "pct": 0}}
    min_t = counted[0]
    max_t = counted[0]
    for t in counted:
        if t.reduction_pct < min_t.reduction_pct:
            min_t = t
        if t.reduction_pct > max_t.reduction_pct:
            max_t = t
    return {
        "min": {"id": min_t.task_id, "pct": min_t.reduction_pct},
        "max": {"id": max_t.task_id, "pct": max_t.reduction_pct},
    }


def run_verify(options: VerifyOptions, deps: Optional[VerifyDependencies] = None) -> VerifyOutcome:
    """
    Core verify pipeline, deliberately separated from argv parsing and
    sys.exit (tokentrust/cli.py) so it can be exercised directly in tests
    with injected dependencies (fake adapters, fake clock, fake live API
    client) without spawning a real subprocess.
    """
    deps = deps or VerifyDependencies()
    get_adapter_fn = deps.get_adapter or _default_get_adapter
    now = deps.now or (lambda: datetime.now(timezone.utc))
    print_fn = deps.print_fn or print
    env = deps.env if deps.env is not None else dict(os.environ)
    live_api_client = deps.live_api_client or anthropic_live_api_client
    store_path = deps.store_path or str(Path(options.repo) / DEFAULT_STORE_PATH)
    progress_fn = deps.print_progress or print_progress

    try:
        tasks = load_task_corpus(options.tasks_path)
    except TaskSchemaError as err:
        print_fn(f"Error: {err}")
        return VerifyOutcome(exit_code=1)

    available_adapters: List[ProxyAdapter] = []
    for proxy_name in options.proxies:
        if proxy_name == "headroom":
            print_fn(HEADROOM_NOT_YET_SUPPORTED_MESSAGE)
            continue
        adapter = get_adapter_fn(proxy_name)
        installed = adapter.is_installed()
        if not installed:
            err = MissingBinaryError(adapter.name, adapter.binary_name, adapter.install_command)
            print_fn(str(err))
        else:
            available_adapters.append(adapter)

    if not available_adapters:
        return VerifyOutcome(exit_code=1)

    if options.live and len(available_adapters) > 1:
        rest_names = ", ".join(a.name for a in available_adapters[1:])
        next_name = available_adapters[1].name if len(available_adapters) > 1 else "<name>"
        print_fn(
            f"Note: --live only verifies the first proxy ({available_adapters[0].name}). "
            f"{rest_names} will use the free local-tokenizer estimate only, not a real API call. "
            f"Run --proxy {next_name} --live separately to verify another proxy."
        )

    run_id = generate_run_id(now())
    timestamp = _to_iso_millis(now())

    records = []
    tt03_entries: Dict[str, Tt03ReportEntry] = {}
    tt05_entries: Dict[str, Tt05ReportEntry] = {}
    version_by_proxy: Dict[str, str] = {}
    tt01_results_by_proxy: List[dict] = []
    new_store_runs: List[ReportStoreRun] = []

    primary_tt01 = None
    primary_tt02 = None
    primary_tt03 = None
    primary_tt05 = None
    live_note = None

    loaded_store = load_report_store(store_path)

    for index, adapter in enumerate(available_adapters):
        proxy_version = adapter.get_version()
        version_by_proxy[adapter.name] = proxy_version
        print_fn(f"Measuring... ({adapter.name} {proxy_version}, {len(tasks)}-task corpus, {options.repo})")

        claimed = get_claimed_savings(adapter.name)
        try:
            tt01 = run_tt01(adapter, tasks, claimed.pct, lambda done, total: progress_fn(done, total))
        except ProxyExecutionError as err:
            print_fn(f"Error: {err}")
            return VerifyOutcome(exit_code=1)
        tt01_results_by_proxy.append({"proxy": adapter.name, "tt01": tt01})

        tt02 = run_tt02_default(tt01.per_task, claimed.pct)

        # --live is scoped to the first available proxy only, to keep real
        # API spend bounded to a single --live-max-tasks sample per
        # invocation even when multiple --proxy flags are passed.
        if options.live and index == 0:
            estimated_cost_usd = estimate_live_cost(tt01.per_task)
            gate = evaluate_live_gate(
                LiveModeOptions(
                    live=options.live, confirm_cost=options.confirm_cost, live_max_tasks=options.live_max_tasks
                ),
                len(tasks),
                estimated_cost_usd,
            )
            print_fn(gate.message)
            if not gate.allowed:
                return VerifyOutcome(exit_code=gate.exit_code or 1)

            api_key = resolve_live_api_key(env)
            if not api_key:
                print_fn(MISSING_LIVE_KEY_MESSAGE)
                return VerifyOutcome(exit_code=1)

            capped_tasks = tasks[: options.live_max_tasks]
            baseline_contexts = [{"id": t.id, "contextText": load_fixture_context(t)} for t in capped_tasks]
            compressed_samples = []
            for t in capped_tasks:
                result = adapter.run(t, "compressed")
                compressed_samples.append({"id": t.id, "contextText": result.raw_output})

            baseline_live = run_live_verification(baseline_contexts, api_key, options.live_max_tasks, live_api_client)
            compressed_live = run_live_verification(compressed_samples, api_key, options.live_max_tasks, live_api_client)
            baseline_usd = baseline_live["billed_usd"]
            compressed_usd = compressed_live["billed_usd"]
            live_savings_pct = 0 if baseline_usd == 0 else ((baseline_usd - compressed_usd) / baseline_usd) * 100
            live_note = (
                f"Live verification sample ({len(capped_tasks)} tasks): provider-billed savings "
                f"{live_savings_pct:.1f}% (baseline ${baseline_usd:.4f}, "
                f"compressed ${compressed_usd:.4f}) vs. local-tokenizer estimate {tt02.savings_pct:.1f}%."
            )

        try:
            tt03 = run_tt03(adapter, tasks, lambda done, total: progress_fn(done, total))
        except ProxyExecutionError as err:
            print_fn(f"Error: {err}")
            return VerifyOutcome(exit_code=1)
        tt03_entries[adapter.name] = Tt03ReportEntry(
            pass_=tt03.pass_, regressed_count=tt03.regressed_count, task_corpus_size=tt03.task_corpus_size
        )

        tt05 = run_tt05(loaded_store, adapter.name, options.repo, tt02.savings_pct)
        tt05_entries[adapter.name] = Tt05ReportEntry(
            pass_=tt05.pass_, message=tt05.message, prior_run_id=tt05.prior_run_id, degraded=tt05.degraded
        )
        new_store_runs.append(
            ReportStoreRun(
                run_id=run_id,
                timestamp=timestamp,
                proxy=adapter.name,
                proxy_version=proxy_version,
                repo=options.repo,
                measured_savings_pct=tt02.savings_pct,
                prior_run_id=tt05.prior_run_id,
            )
        )

        records.append(
            build_report_record(
                run_id, timestamp, adapter.name, proxy_version, options.repo, "TT01",
                claimed.pct, tt01.measured_savings_pct, len(tasks), None,
            )
        )
        records.append(
            build_report_record(
                run_id, timestamp, adapter.name, proxy_version, options.repo, "TT02",
                claimed.pct, tt02.savings_pct, len(tasks), None,
            )
        )
        records.append(
            build_report_record(
                run_id, timestamp, adapter.name, proxy_version, options.repo, "TT05",
                claimed.pct, tt02.savings_pct, len(tasks), tt05.prior_run_id,
            )
        )

        if index == 0:
            primary_tt01, primary_tt02, primary_tt03, primary_tt05 = tt01, tt02, tt03, tt05

    tt04_summary = None
    if len(available_adapters) > 1:
        try:
            tt04 = run_tt04(tt01_results_by_proxy)
            for r in tt04.results:
                records.append(
                    build_report_record(
                        run_id, timestamp, r.proxy, version_by_proxy.get(r.proxy, "unknown"), options.repo,
                        "TT04", get_claimed_savings(r.proxy).pct, r.measured_savings_pct, tt04.task_corpus_size, None,
                    )
                )
            tt04_summary = Tt04Summary(
                results=[{"proxy": r.proxy, "measured_savings_pct": r.measured_savings_pct} for r in tt04.results],
                task_corpus_size=tt04.task_corpus_size,
                primary_proxy=available_adapters[0].name,
            )
        except CorpusMismatchError as err:
            print_fn(f"Error: {err}")
            return VerifyOutcome(exit_code=1)

    updated_store = loaded_store.store
    for run in new_store_runs:
        updated_store = append_run(updated_store, run)
    write_report_store(store_path, updated_store)

    full_report = FullReport(
        run_id=run_id,
        timestamp=timestamp,
        repo=options.repo,
        task_corpus_size=len(tasks),
        proxies=[a.name for a in available_adapters],
        records=records,
        tt03=tt03_entries,
        tt05=tt05_entries,
    )

    report_path = deps.report_out_path or str(Path(options.repo) / f"tokentrust-report-{timestamp[:10]}.json")
    write_report(full_report, report_path)

    if options.format == "json":
        print_fn(serialize_report(full_report))
    elif primary_tt01 and primary_tt02 and primary_tt03 and primary_tt05:
        min_max = _compute_min_max_task(primary_tt01)
        primary_proxy = available_adapters[0]
        claimed = get_claimed_savings(primary_proxy.name)

        tt01_summary = Tt01Summary(
            claimed_label=claimed.label,
            measured_savings_pct=primary_tt01.measured_savings_pct,
            task_corpus_size=primary_tt01.task_corpus_size,
            min_task=min_max["min"],
            max_task=min_max["max"],
        )
        tt02_summary = Tt02Summary(
            baseline_usd=primary_tt02.baseline_usd,
            compressed_usd=primary_tt02.compressed_usd,
            savings_pct=primary_tt02.savings_pct,
            savings_usd=primary_tt02.savings_usd,
            claimed_pct=claimed.pct,
            task_corpus_size=primary_tt02.task_corpus_size,
            pricing_model=primary_tt02.pricing_model,
            live_verified=bool(live_note),
        )
        tt03_summary = Tt03Summary(
            pass_=primary_tt03.pass_, regressed_count=primary_tt03.regressed_count,
            task_corpus_size=primary_tt03.task_corpus_size,
        )
        tt05_summary = Tt05Summary(pass_=primary_tt05.pass_, message=primary_tt05.message)

        print_fn(
            render_terminal_report(
                TerminalReportInput(
                    proxy=primary_proxy.name,
                    proxy_version=version_by_proxy.get(primary_proxy.name, "unknown"),
                    repo=options.repo,
                    task_corpus_size=len(tasks),
                    tt01=tt01_summary,
                    tt02=tt02_summary,
                    tt03=tt03_summary,
                    tt04=tt04_summary,
                    tt05=tt05_summary,
                    report_path=report_path,
                )
            )
        )
        if live_note:
            print_fn(live_note)

    return VerifyOutcome(exit_code=0, report_path=report_path, report=full_report)
