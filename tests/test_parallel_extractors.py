"""#83：月末 4 个 extractor 串行改并行（仅 CLI 后端）。

并行只动 LLM 调用阶段（run_agent_text ×4，互不依赖）；解析/sanitizer/合并仍串行按模块顺序，
输出与串行版语义一致。落库在本函数之外、仍串行单事务（ADR 0008）。形态1/api 后端串行不变。
"""
from __future__ import annotations

import threading

import ming_sim.simulation as simulation
from ming_sim.simulation import EXTRACTION_MODULES, extract_scores_by_modules_with_agno

# 各模块一个 allowed 字段的最小 canned 输出（见 MODULE_FIELDS）。
_CANNED = {
    "internal": '{"economy_moves": [{"账户": "国库", "增量": 5, "原因": "测试"}]}',
    "military_external": '{"new_armies": []}',
    "issues": '{"new_issues": []}',
    "personnel_secret": '{"secret_order_updates": []}',
    "relations": '{"大臣互动": []}',
}


def _module_of(tag: str) -> str:
    return tag.split("/", 1)[1]


def _fake_run(agent, prompt, tag):
    if tag.startswith("extractor/"):
        return _CANNED[_module_of(tag)]
    return prompt  # sanitizer 直通（本测试 canned 均合法，不触发）


def _dummy_agents():
    return {m: object() for m in EXTRACTION_MODULES}


def test_parallel_extract_matches_serial(read_game, monkeypatch):
    """并行与串行产出的 merged delta 字节级一致——并行只改取数时机，不改解析/合并。"""
    db, state, content = read_game
    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    serial = extract_scores_by_modules_with_agno(
        _dummy_agents(), db, state, "邸报", parallel=False)
    parallel = extract_scores_by_modules_with_agno(
        _dummy_agents(), db, state, "邸报", parallel=True)
    assert serial[0] == parallel[0]      # merged dict 一致
    assert serial[1] == parallel[1]      # 本地化 JSON 一致


def test_shared_new_issues_from_issues_and_personnel_secret_are_merged(read_game, monkeypatch):
    db, state, content = read_game
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
        "personnel_secret": {"new_issues": {"title": "坏形状"}},  # 非 list
    }
    merged = _merge_module_outputs(outputs)
    assert [item["title"] for item in merged["new_issues"]] == ["公开月拨"]
    # 坏形状不静默吞：留一条模块拒收指明哪个模块产了坏形状（codex correctness，留痕不静默）。
    rejections = merged.get("_module_rejections") or []
    assert any(
        r.get("module") == "personnel_secret" and r.get("field") == "new_issues"
        for r in rejections
    )


def test_merge_dedups_same_origin_commitment_across_modules():
    """integrated cmr Gate2 r3 codex correctness：issues 与 personnel_secret 都能产 new_issues；
    若两模块对同一笔（同 origin_kind+origin_ref）各产一条承诺 issue，合并须去重——否则 apply 建
    两条 active 承诺 → 月度 ongoing 双扣（正是 #340 要消的）。同批同源只留第一条 + 留拒收信号。"""
    from ming_sim.simulation import _merge_module_outputs

    dup = {
        "origin_kind": "decree", "origin_ref": "secret_order:7", "title": "密令月拨",
        "kind": "initiative", "commitment_kind": "until_stop",
        "ongoing_effects": {"economy": [{"account": "内库", "delta": -20, "reason": "密令每月拨款"}]},
    }
    outputs = {
        "issues": {"new_issues": [dict(dup, title="公开误产同源")]},
        "personnel_secret": {"new_issues": [dict(dup)]},
    }
    merged = _merge_module_outputs(outputs)

    # 同源【同额】只留一条（第一个模块 issues 的），不双建
    refs = [it.get("origin_ref") for it in merged["new_issues"]]
    assert refs == ["secret_order:7"]
    rejections = merged.get("_module_rejections") or []
    assert any("同源同额承诺重复" in str(r.get("reason", "")) for r in rejections)


def test_merge_keeps_multiple_distinct_fundings_under_same_origin_ref():
    """integrated cmr Gate2 r4 codex correctness：同一密令编号（固定 origin_ref=secret_order:5）
    下两笔【不同】月拨（内库安抚、国库修边）是两条合法承诺，去重粒度须含 economy 签名——只去
    同源【同额】真重复，不得把同 origin_ref 不同 economy 的两笔误删（原只按 origin_ref 去重的回归）。"""
    from ming_sim.simulation import _merge_module_outputs

    base = {"origin_kind": "decree", "origin_ref": "secret_order:5", "kind": "initiative",
            "commitment_kind": "until_stop"}
    funding_a = dict(base, title="内库月拨安抚诸将",
                     ongoing_effects={"economy": [{"account": "内库", "delta": -20, "reason": "安抚诸将"}]})
    funding_b = dict(base, title="国库月拨修边",
                     ongoing_effects={"economy": [{"account": "国库", "delta": -30, "reason": "修边"}]})
    merged = _merge_module_outputs({"personnel_secret": {"new_issues": [funding_a, funding_b]}})

    titles = [it.get("title") for it in merged["new_issues"]]
    assert titles == ["内库月拨安抚诸将", "国库月拨修边"]   # 两笔都保留，未被同 origin_ref 误删
    assert not (merged.get("_module_rejections") or [])


def test_merge_keeps_distinct_non_recurring_commitments_under_same_origin_ref():
    """integrated cmr Gate2 codex correctness：跨模块承诺去重的唯一目的是消「月度 ongoing 双扣」。
    无月度 economy 的承诺（form③ 未来一次性：仅 end_turn、空 ongoing_effects）根本不产月度扣账、
    无双扣可消；却会因签名同收敛到 (okind, oref, frozenset()) 把同一诏书下两笔合法 form③ 承诺误删
    其一。空 economy 一律不参与去重——两笔都须保留、无拒收（#136 form③）。"""
    from ming_sim.simulation import _merge_module_outputs

    base = {"origin_kind": "decree", "origin_ref": "decree:turn-2:future-reviews",
            "kind": "initiative", "commitment_kind": "until_stop", "ongoing_effects": {}}
    form3_a = dict(base, title="孙承宗三月后复试", end_turn=9)
    form3_b = dict(base, title="袁崇焕半年后核功", end_turn=12)
    merged = _merge_module_outputs({"issues": {"new_issues": [form3_a, form3_b]}})

    titles = [it.get("title") for it in merged["new_issues"]]
    assert titles == ["孙承宗三月后复试", "袁崇焕半年后核功"]   # 两笔 form③ 都保留，未被空 economy 误删
    assert not (merged.get("_module_rejections") or [])


def test_parallel_extract_runs_concurrently(read_game, monkeypatch):
    """parallel=True 时模块 LLM 调用真并发：峰值并发 ≥2（会合证，不赌 sleep 观察窗）。"""
    db, state, content = read_game
    active = 0
    max_active = 0
    lock = threading.Lock()
    # Rendezvous: first arrivals wait until a peer is also in-flight — proves overlap
    # without wall-clock sleep. Serial path would hang here (CI job final line owns hang).
    overlap = threading.Condition(lock)

    def _rendezvous(agent, prompt, tag):
        nonlocal active, max_active
        with overlap:
            active += 1
            max_active = max(max_active, active)
            if max_active >= 2:
                overlap.notify_all()
            else:
                # Wait until a peer has also entered (overlap proven).
                while max_active < 2:
                    overlap.wait()
            active -= 1
        return _fake_run(agent, prompt, tag)

    monkeypatch.setattr(simulation, "run_agent_text", _rendezvous)
    extract_scores_by_modules_with_agno(_dummy_agents(), db, state, "邸报", parallel=True)
    assert max_active >= 2, f"未真正并发，峰值并发={max_active}"


def test_serial_extract_stays_serial(read_game, monkeypatch):
    """parallel=False（形态1/api 默认）峰值并发==1，串行不受影响。"""
    db, state, content = read_game
    active = 0
    max_active = 0
    lock = threading.Lock()

    def _track(agent, prompt, tag):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
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
        simulator_payload={"transit_semantics": []}, relevant_memories=[], secret_orders=[],
        before_turn=state.turn, _emit=lambda *a, **k: None, content=content, registry=None)
    return captured.get("parallel")


def test_settle_passes_parallel_for_any_runner(game, monkeypatch):
    """月末多 extractor 并发对任意 runner 一视同仁——不按模型退串行。

    行为钉：非 codex runner（grok）与 api channel 均 parallel=True。
    """
    from ming_sim.models import LLMConfig
    grok_cfg = LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="grok", cli_model="grok-4.5", cli_timeout_seconds=240,
    )
    api_cfg = LLMConfig(
        api_key="sk-x", base_url="https://api.example/v1", model="gpt-x", channel="api",
    )
    assert _settle_capturing_parallel(game, monkeypatch, grok_cfg) is True
    assert _settle_capturing_parallel(game, monkeypatch, api_cfg) is True


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


def test_parallel_extract_propagates_extractor_error(read_game, monkeypatch):
    """任一 extractor 抛错经并行路径原样上抛（→ 上层 SettlementAbort），不被并发吞掉。"""
    import pytest

    def _one_fails(agent, prompt, tag):
        if tag == "extractor/issues":
            raise RuntimeError("extractor issues 模拟失败")
        return _fake_run(agent, prompt, tag)

    db, state, content = read_game
    monkeypatch.setattr(simulation, "run_agent_text", _one_fails)
    with pytest.raises(RuntimeError, match="extractor issues 模拟失败"):
        extract_scores_by_modules_with_agno(_dummy_agents(), db, state, "邸报", parallel=True)
