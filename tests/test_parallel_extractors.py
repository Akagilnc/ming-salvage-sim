"""#83：月末 4 个 extractor 串行改并行（仅 CLI 后端）。

并行只动 LLM 调用阶段（run_agent_text ×4，互不依赖）；解析/sanitizer/合并仍串行按模块顺序，
输出与串行版语义一致。落库在本函数之外、仍串行单事务（ADR 0008）。形态1/api 后端串行不变。
"""
from __future__ import annotations

import threading
import time

import ming_sim.simulation as simulation
from ming_sim.simulation import EXTRACTION_MODULES, extract_scores_by_modules_with_agno

# 各模块一个 allowed 字段的最小 canned 输出（见 MODULE_FIELDS）。
_CANNED = {
    "internal": '{"economy_moves": [{"账户": "国库", "增量": 5, "原因": "测试"}]}',
    "military_external": '{"new_armies": []}',
    "issues": '{"new_issues": []}',
    "personnel_secret": '{"secret_order_updates": []}',
}


def _module_of(tag: str) -> str:
    return tag.split("/", 1)[1]


def _fake_run(agent, prompt, tag):
    if tag.startswith("extractor/"):
        return _CANNED[_module_of(tag)]
    return prompt  # sanitizer 直通（本测试 canned 均合法，不触发）


def _dummy_agents():
    return {m: object() for m in EXTRACTION_MODULES}


def test_parallel_extract_matches_serial(game, monkeypatch):
    """并行与串行产出的 merged delta 字节级一致——并行只改取数时机，不改解析/合并。"""
    db, state, content = game
    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    serial = extract_scores_by_modules_with_agno(
        _dummy_agents(), db, state, "邸报", parallel=False)
    parallel = extract_scores_by_modules_with_agno(
        _dummy_agents(), db, state, "邸报", parallel=True)
    assert serial[0] == parallel[0]      # merged dict 一致
    assert serial[1] == parallel[1]      # 本地化 JSON 一致


def test_shared_new_issues_from_issues_and_personnel_secret_are_merged(game, monkeypatch):
    db, state, content = game
    canned = {
        **_CANNED,
        "issues": '{"new_issues": [{"origin_kind": "decree", "title": "公开月拨", "kind": "initiative", "ongoing_effects": {"economy": [{"account": "国库", "delta": -10, "reason": "公开每月拨款"}]}, "commitment_kind": "until_stop"}]}',
        "personnel_secret": '{"new_issues": [{"origin_kind": "decree", "origin_ref": "secret_order:7", "title": "密令月拨", "kind": "initiative", "ongoing_effects": {"economy": [{"account": "内库", "delta": -20, "reason": "密令每月拨款"}]}, "commitment_kind": "until_stop"}], "secret_order_updates": []}',
    }

    def _fake_run_shared(agent, prompt, tag):
        if tag.startswith("extractor/"):
            return canned[_module_of(tag)]
        return prompt

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run_shared)
    merged, _localized, _inputs = extract_scores_by_modules_with_agno(
        _dummy_agents(), db, state, "邸报", parallel=False)

    assert [item["title"] for item in merged["new_issues"]] == ["公开月拨", "密令月拨"]


def test_merge_non_list_new_issues_does_not_clobber_merged_list():
    """integrated cmr Gate2 codex correctness：某模块输出非 list 的 new_issues（坏形状）时，
    合并必须跳过、绝不清掉前一模块已合并的承诺列表（否则 personnel_secret 的坏形状会吃掉
    issues 已合并的承诺）。"""
    from ming_sim.simulation import _merge_module_outputs

    outputs = {
        "issues": {"new_issues": [{"title": "公开月拨"}]},
        "personnel_secret": {"new_issues": {}},  # 坏形状：非 list
    }
    merged = _merge_module_outputs(outputs)
    assert [item["title"] for item in merged["new_issues"]] == ["公开月拨"]


def test_parallel_extract_runs_concurrently(game, monkeypatch):
    """parallel=True 时 4 个 LLM 调用真并发：峰值并发 ≥2，wall-clock 明显短于串行总和。"""
    db, state, content = game
    active = 0
    max_active = 0
    lock = threading.Lock()
    delay = 0.25

    def _slow(agent, prompt, tag):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(delay)
        with lock:
            active -= 1
        return _fake_run(agent, prompt, tag)

    monkeypatch.setattr(simulation, "run_agent_text", _slow)
    t0 = time.monotonic()
    extract_scores_by_modules_with_agno(_dummy_agents(), db, state, "邸报", parallel=True)
    elapsed = time.monotonic() - t0
    assert max_active >= 2, f"未真正并发，峰值并发={max_active}"
    assert elapsed < delay * len(EXTRACTION_MODULES), (
        f"wall-clock {elapsed:.2f}s 未短于串行总和 {delay*len(EXTRACTION_MODULES):.2f}s")


def test_serial_extract_stays_serial(game, monkeypatch):
    """parallel=False（形态1/api 默认）峰值并发==1，串行不受影响。"""
    db, state, content = game
    active = 0
    max_active = 0
    lock = threading.Lock()

    def _track(agent, prompt, tag):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _fake_run(agent, prompt, tag)

    monkeypatch.setattr(simulation, "run_agent_text", _track)
    extract_scores_by_modules_with_agno(_dummy_agents(), db, state, "邸报", parallel=False)
    assert max_active == 1, f"串行路径出现并发，峰值={max_active}"


def _settle_capturing_parallel(game, monkeypatch, cfg):
    """跑一遍 _settle_after_narrative（绕真 extractor），返回传给 extract 的 parallel 值。"""
    import ming_sim.decree as decree
    import ming_sim.cli_backend as _cb
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    monkeypatch.setattr(decree, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "record_chapter_memory", lambda *a, **k: None)
    captured = {}

    def _capture(*a, **k):
        captured["parallel"] = k.get("parallel")
        return ({}, "extractor-out", "extractor-in")

    monkeypatch.setattr(decree, "extract_scores_by_modules_with_agno", _capture)
    decree._settle_after_narrative(
        state, db, None, cfg, decree_text="试旨", narrative="本月邸报。",
        simulator_payload={}, relevant_memories=[], secret_orders=[],
        before_turn=state.turn, _emit=lambda *a, **k: None, content=content, registry=None)
    return captured.get("parallel")


def test_settle_passes_parallel_for_cli_backend(game, monkeypatch):
    """decree 按 cli_backend_parallel_safe 决定 parallel：codex CLI 后端 → True。"""
    from ming_sim.models import LLMConfig
    cli_cfg = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback",
                        channel="cli", cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240)
    assert _settle_capturing_parallel(game, monkeypatch, cli_cfg) is True


def test_settle_serial_for_non_cli_backend(game, monkeypatch):
    """非 CLI 后端（api channel / 形态1）→ parallel=False，串行不变。"""
    from ming_sim.models import LLMConfig
    api_cfg = LLMConfig(api_key="sk-x", base_url="https://api.example/v1", model="gpt-x", channel="api")
    assert _settle_capturing_parallel(game, monkeypatch, api_cfg) is False


def test_settle_serial_for_non_codex_cli_runner(game, monkeypatch):
    """非 codex 的 CLI runner（agy/claude，并发安全未证）→ parallel=False（cmr #83 codex R2：
    --ephemeral 隔离只对 codex 成立，门控收窄到 codex）。"""
    from ming_sim.models import LLMConfig
    agy_cfg = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback",
                        channel="cli", cli_runner="agy", cli_model="", cli_timeout_seconds=240)
    assert _settle_capturing_parallel(game, monkeypatch, agy_cfg) is False


def test_cli_backend_parallel_safe_resolution(monkeypatch):
    """门控 cli_backend_parallel_safe 与 create_chat_model 同口径解 runner（cmr #83 codex R3）：
    codex（显式 cli / legacy env / cli channel 无 runner+env）→ True；agy/claude/api/形态1 → False。"""
    import ming_sim.cli_backend as cb
    from ming_sim.models import LLMConfig

    def cfg(**kw):
        kw.setdefault("api_key", "cli-backend")
        kw.setdefault("base_url", "")
        kw.setdefault("model", "m")
        return LLMConfig(**kw)

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    # 显式 cli channel
    assert cb.cli_backend_parallel_safe(cfg(channel="cli", cli_runner="codex")) is True
    assert cb.cli_backend_parallel_safe(cfg(channel="cli", cli_runner="agy")) is False
    assert cb.cli_backend_parallel_safe(cfg(channel="cli", cli_runner="claude")) is False
    # api / 形态1（空 channel 无 env）
    assert cb.cli_backend_parallel_safe(cfg(channel="api", base_url="https://x/v1", model="gpt")) is False
    assert cb.cli_backend_parallel_safe(cfg(channel="")) is False
    # legacy env（空 channel + 旧 env）——须与 create_chat_model 一致
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    assert cb.cli_backend_parallel_safe(cfg(channel="")) is True            # legacy env=codex → 并行
    assert cb.cli_backend_parallel_safe(cfg(channel="cli")) is True         # cli channel 无 runner → env codex
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    assert cb.cli_backend_parallel_safe(cfg(channel="")) is False           # legacy env=agy → 串行


def test_cli_trace_concurrent_writes_not_corrupted(tmp_path, monkeypatch):
    """并发 _trace 写盘不交错损坏：N 线程各写一条大记录，文件行数正确且每行都是合法 JSON
    （cmr #83 线上 gemini high：CliChat.invoke 并发下 trace 写须加锁）。"""
    import json as _json
    import threading
    import ming_sim.cli_backend as cb
    p = tmp_path / "trace.jsonl"
    monkeypatch.setattr(cb, "_TRACE_PATH", str(p))
    monkeypatch.setattr(cb, "_TRACE_DISABLED", False)
    monkeypatch.setattr(cb, "_trace_announced", True)  # 免 announce print
    n = 24

    def _w(i):
        cb._trace({"ts": "t", "seq": i, "tag": f"t{i}", "backend": "codex", "model_id": "m",
                   "dur_s": 0, "attempts": 1, "wants_json": False, "prompt_chars": 0,
                   "resp_chars": 0, "error": None, "prompt": "p" * 800, "response": "r" * 800})

    threads = [threading.Thread(target=_w, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n, f"行数 {len(lines)} != {n}（并发写交错/丢行）"
    for ln in lines:
        _json.loads(ln)  # 每行合法 JSON = 无交错损坏


def test_parallel_extract_propagates_extractor_error(game, monkeypatch):
    """任一 extractor 抛错经并行路径原样上抛（→ 上层 SettlementAbort），不被并发吞掉。"""
    import pytest

    def _one_fails(agent, prompt, tag):
        if tag == "extractor/issues":
            raise RuntimeError("extractor issues 模拟失败")
        return _fake_run(agent, prompt, tag)

    db, state, content = game
    monkeypatch.setattr(simulation, "run_agent_text", _one_fails)
    with pytest.raises(RuntimeError, match="extractor issues 模拟失败"):
        extract_scores_by_modules_with_agno(_dummy_agents(), db, state, "邸报", parallel=True)
