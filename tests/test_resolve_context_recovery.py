"""S2+S3 (ADR 0008 PR1) — resolve_context 无条件持久化 + validate 前置 + 事务内清理。

重跑契约第一件：每回合进入结算后半段前必存 resolve_context（extractor delta + 叙事），
持久化前先过 validate_delta_shape（毒 payload 绝不入真源），clear 移到 settle 写序列内
（settle 完成 = context 干净；中途崩 = context 仍在可重试）。
"""

from __future__ import annotations

import pytest

from ming_sim.decree import persist_resolve_context, settle_with_delta


def test_persist_resolve_context_stores_extracted_delta(game):
    """持久化后能 load 回 extractor 产出的 delta（重灌真源）。"""
    db, state, content = game
    turn = state.turn
    extracted = {"region_delta": {"shanxi": {"unrest": 5}}}

    persist_resolve_context(
        db, turn, extracted,
        decree_text="减赋诏", narrative="本月邸报……",
        simulator_payload={"k": "v"}, secret_orders=[], relevant_memories=[],
    )

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["decree_text"] == "减赋诏"
    assert ctx["narrative"] == "本月邸报……"
    assert ctx["extracted"] == extracted


def test_persist_rejects_malformed_delta_and_writes_nothing(game):
    """畸形 delta（region_delta 应为 dict 实得 list）→ 响亮抛 ValueError，
    且 resolve_context **未被写入**（防毒 payload 钉进重试真源）。"""
    db, state, content = game
    turn = state.turn
    bad = {"region_delta": ["not", "a", "dict"]}  # validate_delta_shape 要求 dict 容器

    with pytest.raises(ValueError):
        persist_resolve_context(
            db, turn, bad,
            decree_text="x", narrative="y",
            simulator_payload={}, secret_orders=[], relevant_memories=[],
        )

    assert db.get_resolve_context(turn) is None


def test_settle_clears_resolve_context_on_completion(game):
    """正常结算完成后 resolve_context 已清（clear 在 settle 写序列内，settle 完成 = context 干净）。"""
    db, state, content = game
    turn = state.turn
    extracted = {"region_delta": {"shanxi": {"unrest": 1}}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn) is not None

    settle_with_delta(state, db, extracted, before_turn=turn, content=content)

    # next_period 后 turn 已 +1，但 clear 按 before_turn 清本回合那一行。
    assert db.get_resolve_context(turn) is None


def test_resolve_context_survives_mid_settle_crash(game):
    """settle 中途（clear 之前）崩 → resolve_context 仍在（可重试）。
    用注入异常模拟：on_stage 在落库后的「记起居注」阶段抛错，此时尚未走到 clear。"""
    db, state, content = game
    turn = state.turn
    extracted = {"region_delta": {"shanxi": {"unrest": 1}}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    class _Boom(RuntimeError):
        pass

    def _explode(label):
        if label == "记起居注":   # 落库之后、clear 之前的阶段
            raise _Boom("中途崩")

    with pytest.raises(_Boom):
        settle_with_delta(
            state, db, extracted, before_turn=turn, content=content,
            on_stage=_explode,
        )

    # 崩在 clear 之前 → resolve_context 仍在，重进可重试。
    assert db.get_resolve_context(turn) is not None


def test_hitl_phase1_save_path_not_regressed(game):
    """HITL 回合行为不回退：phase1 暂停时按原签名（不带 extracted）存 resolve_context，
    仍能 load 回叙事/决策上下文；extracted 缺省为空 dict（phase1 尚未跑 extractor）。"""
    db, state, content = game
    turn = state.turn

    # 复刻 decree.py:326 HITL 暂停时的原始调用（不带 extracted）。
    db.save_resolve_context(
        turn, "HITL诏书", "含决策点的邸报", {"payload": 1},
        secret_orders=[{"id": 7}], relevant_memories=[{"m": "x"}],
    )

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["decree_text"] == "HITL诏书"
    assert ctx["narrative"] == "含决策点的邸报"
    assert ctx["simulator_payload"] == {"payload": 1}
    assert ctx["secret_orders"] == [{"id": 7}]
    assert ctx["extracted"] == {}   # phase1 无 delta，缺省空

    # phase2 无条件持久化时 upsert 灌入实际 delta，叙事/上下文保留。
    extracted = {"metric_delta": {"国库": 30}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="HITL诏书", narrative="含决策点的邸报",
        simulator_payload={"payload": 1},
        secret_orders=[{"id": 7}], relevant_memories=[{"m": "x"}],
    )
    ctx2 = db.get_resolve_context(turn)
    assert ctx2["extracted"] == extracted
    assert ctx2["secret_orders"] == [{"id": 7}]
