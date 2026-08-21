"""#656 / ADR 0093 前半：phase2 五路 fan-out 并发 oracle（庭裁修正案 r3）。

唯一并发 oracle＝计数=5 受控 barrier：五路（四 extractor＋票拟生成）LLM 调用替换为
受控 fake 腿，每腿起跑即到 barrier 会合，全部五腿到齐后才放行任一腿完成。任何实现若
存在先跑完某腿再起下一腿的串行段（含前缀串行），barrier 永不齐 → 超时失败。
禁生产计时状态/标志：barrier 与 fake 全在测试夹具内，生产代码零感知。

墙钟契约（r2 表述照录）：fan-out 段总时长 ≈ max(票拟, 四 extractor)＋常数开销。
"""
from __future__ import annotations

import threading

import ming_sim.simulation as simulation
from ming_sim.simulation import EXTRACTION_MODULES, extract_scores_by_modules_with_agno

_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'


def test_phase2_fanout_five_legs_meet_at_barrier(game, monkeypatch):
    """r3 oracle：五腿全部在任一腿完成前已起跑＝真五路 fan-out。

    串行形（逐腿跑、先完成后起）永远凑不齐 count=5 → Barrier 超时 BrokenBarrierError
    → 测试失败；真五路启动则统一释放。
    """
    db, state, _content = game
    barrier = threading.Barrier(5)
    started: list[str] = []
    lock = threading.Lock()

    def _fake_leg(agent, prompt, tag):
        with lock:
            started.append(tag)
        # 一进入即阻塞：五调用全部进入前没有任何调用能返回。
        barrier.wait(timeout=30)
        if tag.startswith("extractor/"):
            return _CANNED
        return prompt  # 票拟腿原样返回 prompt（本测只验并发时机）

    monkeypatch.setattr(simulation, "run_agent_text", _fake_leg)

    side_results: dict = {}
    merged, _, _ = extract_scores_by_modules_with_agno(
        {m: object() for m in EXTRACTION_MODULES}, db, state, "邸报",
        parallel=True,
        side_legs={"rescript_draft": lambda: _fake_leg(object(), "draft-prompt", "rescript-draft")},
        side_results=side_results,
    )
    assert len(started) == 5
    assert set(started) == {f"extractor/{m}" for m in EXTRACTION_MODULES} | {"rescript-draft"}
    assert side_results["rescript_draft"] == "draft-prompt"


def test_settle_wires_rescript_draft_into_single_fanout(game, monkeypatch):
    """接线证明：_settle_after_narrative 把票拟腿交进与四 extractor 同一个 fan-out 调用
    （side_legs 同批提交、parallel=True），不另起串行 LLM 步。"""
    import ming_sim.decree as decree_mod
    from tests.test_rescript_draft_656 import (
        _add_character,
        _retire_existing_actors,
        _stub_settle_agents,
    )

    db, state, content = game
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    captured: dict = {}

    def _capture(*args, **kwargs):
        captured["parallel"] = kwargs.get("parallel")
        captured["side_legs"] = kwargs.get("side_legs")
        captured["side_results"] = kwargs.get("side_results")
        return ({}, "out", "in")

    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _capture)

    decree_mod._settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={},
        relevant_memories=[], secret_orders={},
        before_turn=state.turn, _emit=lambda *a: None, content=content,
    )
    assert captured["parallel"] is True
    assert set(captured["side_legs"]) == {"rescript_draft"}
    assert callable(captured["side_legs"]["rescript_draft"])
