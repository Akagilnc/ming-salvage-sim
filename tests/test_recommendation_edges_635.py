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
