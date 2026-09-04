"""#635 [479·S4] 荐人口：荐人事件消费·原子双边（庭裁 r1-r3）。

真入口验收（F3）：stage→commit_pending_actions（proposed 案卷）→apply_dossier_verdicts
获准任命→_commit_office_action 内 applier.atomic 同事务落 record_recommendation 与两条边
→restore 只读 DB 重建；负向：任命未获准→零边；第二腿注入失败→全回滚零残留；
r3：reason 非空逐字必填，缺失则任命与双边同事务 fail-loud 回滚。
"""

import pytest

from tests.dossier_test_helpers import promulgate_proposed_appointments


def _pick_recommender(content):
    return next(c for c in content.characters.values()
                if c.office_type not in ("后宫", "宗藩"))


def _stage_recommendation(db, state, recommender_name, row, office, reason):
    return db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender_name,
        target_id=None,
        payload={
            "name": row["name"], "office": office,
            "faction": row["faction"], "reason": reason,
            "recommendation": {"candidate": row, "recommender": recommender_name},
        },
    )


def _commit_and_promulgate(db, state, content, action_id):
    """真入口前半：暂存动作落成 proposed 任命案卷；返回后由调用方颁判。"""
    result = db.commit_pending_actions(
        state, content=content, registry=None, action_ids=[action_id])
    assert result and result[0]["id"] == action_id
    promulgate_proposed_appointments(db, state, content)


def _recommendation_origins(db):
    return [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith("recommendation:")]


def test_approved_recommendation_writes_both_edges_atomically(game):
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    reason = "旧任有实绩，罢居后仍可起复"
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", reason)

    _commit_and_promulgate(db, state, content, action_id)

    events = db.list_recommendation_events(state, recommender.name)
    assert len(events) == 1
    event = events[0]
    assert event["candidate"] == row["name"]
    assert event["reason"] == reason
    char_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (row["name"],)).fetchone()
    assert char_row["office"] == "巡盐御史"

    # 恰两条边：荐主→被荐人(恩义) ＋ 君(EMPEROR_NODE)→荐主(知遇)，
    # origin 全串精确断言（含写口自动追加的 |round:{turn} 后缀）。
    legs = [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith(f"recommendation:{event['id']}:")]
    assert len(legs) == 2
    by_origin = {e["origin"]: e for e in legs}
    turn = int(state.turn)
    grace = by_origin[f"recommendation:{event['id']}:恩义|round:{turn}"]
    assert grace["source"] == recommender.name
    assert grace["target"] == row["name"]
    assert grace["event_kind"] == "恩义"
    assert grace["context"] == reason
    zhiyu = by_origin[f"recommendation:{event['id']}:知遇|round:{turn}"]
    assert zhiyu["source"] == "皇帝"
    assert zhiyu["target"] == recommender.name
    assert zhiyu["event_kind"] == "知遇"
    assert zhiyu["context"] == reason

    # restore：只读重建 GameState 后，任命与双边无损接续（P1/TD-5）。
    restored = db.load_state()
    restored_char = content.characters[row["name"]]
    assert restored_char.office == "巡盐御史"
    restored_legs = [e for e in db.get_relation_edge_events()
                     if str(e["origin"]).startswith(f"recommendation:{event['id']}:")]
    assert len(restored_legs) == 2
    assert {e["event_kind"] for e in restored_legs} == {"恩义", "知遇"}


def test_unapproved_appointment_writes_zero_edges(game):
    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(r for r in db.list_recommendation_candidates(state, recommender.name)
               if r["status"] != "dismissed")
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", "边才可用")
    # 快照失效 → 任命未获准。
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE name=?", (row["name"],))
    db.conn.commit()

    with pytest.raises(ValueError):
        _commit_and_promulgate(db, state, content, action_id)

    assert db.list_recommendation_events(state, recommender.name) == []
    assert _recommendation_origins(db) == []


def test_empty_reason_fails_loud_and_rolls_back_everything(game):
    """r3：reason 缺失/空 → 任命与双边同事务 fail-loud 回滚，不落任命、不落边。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", "   ")

    with pytest.raises(ValueError):
        _commit_and_promulgate(db, state, content, action_id)

    assert db.list_recommendation_events(state, recommender.name) == []
    assert _recommendation_origins(db) == []
    char_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (row["name"],)).fetchone()
    assert char_row["office"] != "巡盐御史"


def test_second_leg_failure_rolls_back_everything(game, monkeypatch):
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    original = db.record_relation_edge_event

    def flaky_second_leg(*, source, target, event_kind, context, origin, **kwargs):
        if event_kind == "知遇" and str(origin).startswith("recommendation:"):
            raise RuntimeError("第二腿写入失败")
        return original(source=source, target=target, event_kind=event_kind,
                        context=context, origin=origin, **kwargs)

    monkeypatch.setattr(db, "record_relation_edge_event", flaky_second_leg)
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", "破格之才")

    with pytest.raises(RuntimeError):
        _commit_and_promulgate(db, state, content, action_id)

    # 全回滚零残留：不落任命、不落荐人事件、零边。
    assert db.list_recommendation_events(state, recommender.name) == []
    assert db.get_relation_edge_events() == []
    char_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (row["name"],)).fetchone()
    assert char_row["office"] != "巡盐御史"


def test_real_entry_persists_raw_reason_verbatim(game):
    """r3 逐字透传：真实入口荐词带首尾空白/换行，事件 reason 与两腿 context
    均字节不变落库（写口零改字，只以 strip 判空）。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    reason = "  荐其旧任有实绩，堪当巡盐之任。\n"
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", reason)

    _commit_and_promulgate(db, state, content, action_id)

    event = db.list_recommendation_events(state, recommender.name)[0]
    assert event["reason"] == reason
    legs = [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith(f"recommendation:{event['id']}:")]
    assert len(legs) == 2
    assert all(e["context"] == reason for e in legs)


def test_replay_same_event_with_changed_reason_stays_two_rows(game):
    """r1 F2：幂等身份只锚稳定 origin（recommendation:{id}:{腿别}+|round 口径），
    不含可变 context——同 event_id 换荐词重放，恒 2 行且原文不被改写。"""
    from ming_sim.recommendations import record_recommendation_edges

    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    reason1 = "旧任有实绩，罢居后仍可起复"
    grace1, zhiyu1 = record_recommendation_edges(
        db, state, recommender.name, row["name"], 501, reason1)

    # 换 reason、甚至跨回合重放同一事件 id。
    state.turn = int(state.turn) + 3
    reason2 = "改口：边才可用，堪当巡盐"
    grace2, zhiyu2 = record_recommendation_edges(
        db, state, recommender.name, row["name"], 501, reason2)

    assert (grace1, zhiyu1) == (grace2, zhiyu2)
    legs = [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith("recommendation:501:")]
    assert len(legs) == 2
    assert {e["event_kind"] for e in legs} == {"恩义", "知遇"}
    # 原 context 不被重放改写。
    assert all(e["context"] == reason1 for e in legs)


def test_appointment_without_recommendation_writes_no_edges(game):
    """生成侧缺席时接口幂等待命：无 recommendation 载荷不落边、不阻塞其他写端。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    action_id = db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender.name,
        target_id=None,
        payload={
            "name": row["name"], "office": "巡盐御史",
            "faction": row["faction"], "reason": "",
        },
    )

    _commit_and_promulgate(db, state, content, action_id)

    assert _recommendation_origins(db) == []


# ---------------------------------------------------------------------------
# PR #1519 庭裁 Y1/Y2/Y3：工具受理点唯一准入 + 生产链逐字透传真入口回归。

import inspect
import json

from ming_sim.models import CourtContext
from ming_sim.session import GameSession
from ming_sim.tools import build_minister_tools


def _light_session(db, state, content):
    """轻量 GameSession：仅复用 _stage_appointment_candidate 真 staging 缝。"""
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    return sess


def _recommend_tool(character, context):
    tools = build_minister_tools(character, context)
    return next(t for t in tools if getattr(t, "__name__", "") == "recommend_person")


def test_recommend_person_reason_is_contract_required(game):
    """Y1/Y3：reason 是工具契约必填参数——无默认值，缺失在调用层即拒。

    全空白由受理点空白谓词拒绝；二者都不产生 __pending_recommendation__。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    tool = _recommend_tool(recommender, CourtContext(state=state, db=db))

    param = inspect.signature(tool).parameters["reason"]
    assert param.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        tool(name=row["name"], target_office="巡盐御史")

    for bad in ("", "   ", " \n\t "):
        out = tool(name=row["name"], target_office="巡盐御史", reason=bad)
        assert out.startswith("荐人失败：")
        assert "__pending_recommendation__" not in out


def test_blank_reason_never_forms_durable_payload(game):
    """Y1/Y3：全空白荐词明确失败后，真实结果处理不产任何 durable 载荷——
    非标记结果不接 staging，pending_actions 与 decree_dossiers 均无该案。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    sess = _light_session(db, state, content)
    tool = _recommend_tool(recommender, CourtContext(state=state, db=db))

    out = tool(name=row["name"], target_office="巡盐御史", reason="\n  ")
    assert out.startswith("荐人失败：")

    # 会话分发只对 __pending_recommendation__ 前缀接 staging；失败串即使
    # 直递 staging 缝也零入档。
    assert not out.startswith("__pending_recommendation__")
    assert sess._stage_appointment_candidate(out, recommender) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    assert db.list_recommendation_events(state, recommender.name) == []


def test_full_chain_tool_reason_verbatim_to_both_legs(game):
    """Y2 全真链：build_minister_tools→recommend_person（原句含首尾空白/换行）
    →_stage_appointment_candidate→commit_pending_actions→apply_dossier_verdicts，
    recommendation_events.reason 与两腿 context 字节一致。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    reason = "  其旧任治河有实绩，\n堪当巡盐之任。 "
    sess = _light_session(db, state, content)
    tool = _recommend_tool(recommender, CourtContext(state=state, db=db))

    out = tool(name=row["name"], target_office="巡盐御史", reason=reason)
    assert out.startswith("__pending_recommendation__")
    payload = json.loads(out.removeprefix("__pending_recommendation__"))
    assert payload["reason"] == reason

    action_id = sess._stage_appointment_candidate(
        out.removeprefix("__pending_recommendation__").strip(),
        recommender)
    assert action_id > 0

    _commit_and_promulgate(db, state, content, action_id)

    event = db.list_recommendation_events(state, recommender.name)[0]
    assert event["reason"] == reason
    legs = [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith(f"recommendation:{event['id']}:")]
    assert len(legs) == 2
    assert all(e["context"] == reason for e in legs)


def test_rejected_blank_call_does_not_poison_same_turn(game):
    """Y1：坏调用被工具拒绝后，同轮正常荐人照常落地，兄弟案不受牵连。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = db.list_recommendation_candidates(state, recommender.name)[0]
    sess = _light_session(db, state, content)
    tool = _recommend_tool(recommender, CourtContext(state=state, db=db))

    bad = tool(name=row["name"], target_office="巡盐御史", reason=" ")
    assert bad.startswith("荐人失败：")
    good = tool(name=row["name"], target_office="巡盐御史", reason="边才可用")
    assert good.startswith("__pending_recommendation__")

    action_id = sess._stage_appointment_candidate(
        good.removeprefix("__pending_recommendation__").strip(),
        recommender)
    assert action_id > 0

    _commit_and_promulgate(db, state, content, action_id)

    events = db.list_recommendation_events(state, recommender.name)
    assert len(events) == 1
    assert events[0]["reason"] == "边才可用"
    legs = [e for e in db.get_relation_edge_events()
            if str(e["origin"]).startswith(f"recommendation:{events[0]['id']}:")]
    assert {e["event_kind"] for e in legs} == {"恩义", "知遇"}
