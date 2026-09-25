"""
End-to-end tests for run_verify() with injected fake adapters/clock/print --
no real subprocess spawn, no real network call. Ported in spirit from
src/verify.test.ts and src/cli.smoke.test.ts.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from tokentrust.categories.tt02_cost_delta import LIVE_API_KEY_ENV_VAR
from tokentrust.verify import (
    HEADROOM_NOT_YET_SUPPORTED_MESSAGE,
    VerifyDependencies,
    VerifyOptions,
    resolve_default_tasks_path,
    run_verify,
)

from .conftest import FakeAdapter


@pytest.fixture()
def tmp_repo():
    d = tempfile.mkdtemp(prefix="tokentrust-repo-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _options(tmp_repo, **overrides) -> VerifyOptions:
    defaults = dict(
        proxies=["rtk"],
        repo=tmp_repo,
        tasks_path=resolve_default_tasks_path(),
        live=False,
        confirm_cost=False,
        live_max_tasks=5,
        format="terminal",
    )
    defaults.update(overrides)
    return VerifyOptions(**defaults)


def _deps(tmp_repo, adapters: dict, lines: list, **overrides) -> VerifyDependencies:
    defaults = dict(
        get_adapter=lambda name: adapters[name],
        now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        print_fn=lines.append,
        store_path=os.path.join(tmp_repo, ".tokentrust", "report-store.json"),
        report_out_path=os.path.join(tmp_repo, "report.json"),
        env={},
    )
    defaults.update(overrides)
    return VerifyDependencies(**defaults)


def test_full_run_against_rtk_adapter_exits_zero(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x" * 200, compressed=lambda t: "x" * 100)
    lines: list = []
    outcome = run_verify(_options(tmp_repo), _deps(tmp_repo, {"rtk": fake}, lines))
    assert outcome.exit_code == 0
    assert outcome.report is not None
    assert outcome.report.proxies == ["rtk"]
    assert any("MEASURED" in line for line in lines)


def test_missing_binary_reports_exit_1(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x", compressed=lambda t: "x")
    fake.installed = False
    lines: list = []
    outcome = run_verify(_options(tmp_repo), _deps(tmp_repo, {"rtk": fake}, lines))
    assert outcome.exit_code == 1
    assert any("not found on PATH" in line for line in lines)


def test_headroom_prints_not_yet_supported_and_skips(tmp_repo):
    rtk = FakeAdapter("rtk", baseline=lambda t: "x" * 20, compressed=lambda t: "x" * 10)
    lines: list = []
    outcome = run_verify(
        _options(tmp_repo, proxies=["rtk", "headroom"]),
        _deps(tmp_repo, {"rtk": rtk}, lines),
    )
    assert outcome.exit_code == 0
    assert HEADROOM_NOT_YET_SUPPORTED_MESSAGE in lines
    assert outcome.report.proxies == ["rtk"]


def test_json_format_prints_serialized_report(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x" * 20, compressed=lambda t: "x" * 10)
    lines: list = []
    outcome = run_verify(_options(tmp_repo, format="json"), _deps(tmp_repo, {"rtk": fake}, lines))
    assert outcome.exit_code == 0
    assert any('"run_id"' in line for line in lines)


def test_live_without_confirm_cost_refuses_and_exits_1(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x" * 20, compressed=lambda t: "x" * 10)
    lines: list = []
    outcome = run_verify(
        _options(tmp_repo, live=True, confirm_cost=False),
        _deps(tmp_repo, {"rtk": fake}, lines),
    )
    assert outcome.exit_code == 1
    assert any("--confirm-cost" in line for line in lines)


def test_live_confirmed_but_missing_api_key_exits_1(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x" * 20, compressed=lambda t: "x" * 10)
    lines: list = []
    outcome = run_verify(
        _options(tmp_repo, live=True, confirm_cost=True, live_max_tasks=100),
        _deps(tmp_repo, {"rtk": fake}, lines, env={}),
    )
    assert outcome.exit_code == 1
    assert any(LIVE_API_KEY_ENV_VAR in line for line in lines)


def test_missing_live_key_message_names_the_configured_env_var():
    from tokentrust.verify import MISSING_LIVE_KEY_MESSAGE

    assert LIVE_API_KEY_ENV_VAR in MISSING_LIVE_KEY_MESSAGE


def test_multi_proxy_flag_with_headroom_still_only_verifies_rtk(tmp_repo):
    """
    `--proxy rtk --proxy headroom` is real, documented CLI usage (TT04's
    cross-tool comparison), but in v0.1 headroom is unconditionally
    intercepted in the dispatch loop BEFORE a HeadroomAdapter is ever
    constructed (see HEADROOM_NOT_YET_SUPPORTED_MESSAGE) -- so TT04 never
    actually fires today with only rtk fully supported. This locks in that
    real, current behavior; run_tt04() itself is unit-tested directly in
    test_tt04_cross_tool_benchmark.py.
    """
    rtk = FakeAdapter("rtk", baseline=lambda t: "x" * 200, compressed=lambda t: "x" * 100)
    lines: list = []
    outcome = run_verify(
        _options(tmp_repo, proxies=["rtk", "headroom"]),
        _deps(tmp_repo, {"rtk": rtk}, lines),
    )
    assert outcome.exit_code == 0
    assert outcome.report.proxies == ["rtk"]
    assert HEADROOM_NOT_YET_SUPPORTED_MESSAGE in lines
    assert not any("TT04" in line for line in lines)


def test_second_run_establishes_version_drift_baseline_comparison(tmp_repo):
    fake = FakeAdapter("rtk", baseline=lambda t: "x" * 200, compressed=lambda t: "x" * 100)
    lines: list = []
    deps = _deps(tmp_repo, {"rtk": fake}, lines)
    first = run_verify(_options(tmp_repo), deps)
    assert first.exit_code == 0

    lines2: list = []
    deps2 = _deps(tmp_repo, {"rtk": fake}, lines2)
    second = run_verify(_options(tmp_repo), deps2)
    assert second.exit_code == 0
    assert "rtk" in second.report.tt05
    # Same measured savings on both runs -- no regression -- TT05 must pass.
    assert second.report.tt05["rtk"].pass_ is True
