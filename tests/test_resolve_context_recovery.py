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


def test_persist_resolve_context_stores_source_for_recovery(game):
    """#144 / ADR 0008 决定 5：provenance source 一并持久化，崩溃恢复重放（resolve_settling_recovery
    读 ctx['source'] → _replay_settle → settle source）据此还原原始来源——否则玩家来源拒收被恢复路
    记成 system_simulation、静默不提示。"""
    from ming_sim.applier import Provenance
    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {"region_delta": {"shanxi": {"unrest": 1}}},
        decree_text="x", narrative="y",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        source=Provenance.player_decree,
    )
    assert db.get_resolve_context(turn)["source"] == "player_decree", "玩家来源须持久化进 resolve_context"


def test_persist_resolve_context_source_defaults_system_simulation(game):
    """未传 source（旧档/引擎实流）→ 默认 system_simulation（恢复路行为不变，老档兼容）。"""
    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {"region_delta": {"shanxi": {"unrest": 1}}},
        decree_text="x", narrative="y",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn)["source"] == "system_simulation"


def test_persist_sanitizes_malformed_delta_and_records_rejection(game):
    """ADR0015：可拆 section 畸形逐项/逐段拒收，净化后写入 resolve_context。"""
    db, state, content = game
    turn = state.turn
    bad = {"region_delta": ["not", "a", "dict"]}  # validate_delta_shape 要求 dict 容器

    persist_resolve_context(
        db, turn, bad,
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    assert db.get_resolve_context(turn)["extracted"]["region_delta"] == {}
    row = db.conn.execute("SELECT section, item_json FROM rejection_reports").fetchone()
    assert row["section"] == "region_delta"
    assert '"raw_value"' in row["item_json"]


def test_persist_accepts_person_change_delta_after_applier_is_wired(game):
    """人物变更写路径接入后，resolve_context 可保存新 key，供重试/回放恢复同一 delta。"""
    db, state, content = game
    turn = state.turn
    extracted = {
        "人物变更": [
            {"name": "孔有德", "动作": "处置", "status": "dismissed", "reason": "削职听勘"}
        ]
    }

    persist_resolve_context(
        db, turn, extracted,
        decree_text="x", narrative="y",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] == extracted


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


def test_resolve_context_survives_mid_settle_crash(game, monkeypatch, tmp_path):
    """settle 中途（clear 之前）崩 → resolve_context 仍在（可重试）。
    用注入异常模拟：on_stage 在落库后的「记起居注」阶段抛错，此时尚未走到 clear。
    S7：settle 整段包 atomic，代码异常上抛后被包成 SettlementAbort(stage="settle")，
    DB 整体回滚——而 resolve_context 在 settle 之外单独 commit，回滚不动它，故仍在可重试。"""
    from ming_sim.exceptions import SettlementAbort
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    extracted = {"region_delta": {"shanxi": {"unrest": 1}}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    class _Boom(RuntimeError):
        pass

    def _explode(payload):
        # stage 现为 typed payload dict；content 仍是显示标签。
        label = payload.get("content") if isinstance(payload, dict) else payload
        if label == "记起居注":   # 落库之后、clear 之前的阶段
            raise _Boom("中途崩")

    with pytest.raises(SettlementAbort) as ei:
        settle_with_delta(
            state, db, extracted, before_turn=turn, content=content,
            on_stage=_explode,
        )
    assert ei.value.stage == "settle"
    assert isinstance(ei.value.__cause__, _Boom)

    # 崩在 clear 之前 → resolve_context 仍在，重进可重试。
    assert db.get_resolve_context(turn) is not None


def test_hitl_phase1_save_path_not_regressed(game):
    """HITL 回合行为不回退：phase1 暂停时按原签名（不带 extracted）存 resolve_context，
    仍能 load 回叙事/决策上下文；extracted 为 None（占位 ready=0 不可见，cmr F1）。"""
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
    assert ctx["extracted"] is None  # phase1 占位，判别位 ready=0 → 不可见

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


# ---------------------------------------------------------------------------
# cmr S2+S3 r1 修复回归（F1 判别位 + F3 端到端接线）
# ---------------------------------------------------------------------------



def test_hitl_phase1_placeholder_extracted_is_none(game):
    """HITL phase1 save（无 extracted）→ get 返回 extracted=None（cmr F1 案 i）。

    占位不可见：恢复入口据此判「extractor 未产出 → 重跑」，不会重放占位。
    """
    db, state, content = game
    turn = state.turn
    db.save_resolve_context(turn, "d", "n", {"k": "v"},
                            secret_orders=[], relevant_memories=[])
    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    db.clear_resolve_context(turn)


def test_genuinely_empty_delta_distinguishable_from_placeholder(game):
    """extractor 成功产出空 delta → get 返回 {}（非 None，cmr F1 案 iii 可分）。"""
    db, state, content = game
    turn = state.turn
    db.save_resolve_context(turn, "d", "n", {"k": "v"},
                            secret_orders=[], relevant_memories=[], extracted={})
    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] == {}
    assert ctx["extracted"] is not None
    db.clear_resolve_context(turn)


# ---------------------------------------------------------------------------
# cmr S2+S3 r4 修复回归（F1 stale context / F3 corruption）
# ---------------------------------------------------------------------------

def test_advance_without_edict_clears_stale_context(game, monkeypatch):
    """退朝无诏推进回合时清掉本回合 stale context（cmr S2+S3 r4 F1）。

    #1274：无旨走完整结算；settle_with_delta 尾 clear_resolve_context。
    崩溃重试后改走无诏路推进，留下的 ready=1 行会被 S4 恢复入口
    当「未完成回合」重放=double-apply。推进回合的路都得清。
    """
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.session import GameSession

    db, state, content = game
    turn = state.turn
    db.save_resolve_context(turn, "d", "n", {}, secret_orders=[],
                            relevant_memories=[], extracted={"metric_delta": {"国库": 1}})
    assert db.get_resolve_context(turn) is not None

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("stale-ctx 测邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    sess.advance_without_decree()

    # #1843：无旨也走主链，邸报未成不得推进，也不重放旧 extractor ready delta。
    assert state.turn == turn
    assert state.turn_phase != "issued"


def test_corrupt_extracted_json_returns_none_not_empty(game):
    """ready=1 但 extracted JSON 损坏 → extracted=None（重跑 extractor），不吞成 {}。

    吞成 {} 会复活判别位刚消掉的歧义：恢复入口重放空 delta=整月效果静默丢（cmr r4 F3）。
    """
    db, state, content = game
    turn = state.turn
    db.save_resolve_context(turn, "d", "n", {}, secret_orders=[],
                            relevant_memories=[], extracted={"metric_delta": {"国库": 1}})
    db.conn.execute(
        "UPDATE pending_resolve_context SET extracted_delta_json='not json' WHERE turn=?",
        (turn,),
    )
    db.conn.commit()

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    db.clear_resolve_context(turn)


def test_type_corrupt_extracted_json_returns_none(game):
    """ready=1 但 JSON 合法非 dict（如 [1,2]）→ extracted=None（重抽），不原样返回（ship-pre r1）。

    原样返回会让恢复叉抛 LLMContractError（非 SettlementAbort）→ 逃生口不触发=corruption 软死锁。
    """
    db, state, content = game
    turn = state.turn
    db.save_resolve_context(turn, "d", "n", {}, secret_orders=[],
                            relevant_memories=[], extracted={"metric_delta": {"国库": 1}})
    db.conn.execute(
        "UPDATE pending_resolve_context SET extracted_delta_json='[1, 2]' WHERE turn=?",
        (turn,))
    db.conn.commit()

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    db.clear_resolve_context(turn)
