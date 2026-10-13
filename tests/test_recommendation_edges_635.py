from ming_sim.recommendations import list_recommendation_candidates
import pytest
from tests.dossier_test_helpers import promulgate_proposed_appointments
"""#635 [479·S4] 荐人口：荐人事件消费·原子双边（庭裁 r1-r3）。

真入口验收（F3）：stage→commit_pending_actions（proposed 案卷）→apply_dossier_verdicts
获准任命→_commit_office_action 内 applier.atomic 同事务落 record_recommendation 与两条边
→restore 只读 DB 重建；负向：任命未获准→零边；第二腿注入失败→全回滚零残留；
r3：reason 非空逐字必填，缺失则任命与双边同事务 fail-loud 回滚。
"""




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
            "text": f"准荐{row['name']}任{office}",
            "recommendation": {"candidate": row, "recommender": recommender_name},
        },
    )


def _commit_and_promulgate(db, state, content, action_id):
    """真入口前半：暂存动作落成 proposed 任命案卷；返回后由调用方颁判。"""
    result = db.commit_pending_actions(
        state, content=content, action_ids=[action_id])
    assert result and result[0]["id"] == action_id
    promulgate_proposed_appointments(db, state, content)


def _recommendation_origins(db):
    return [e for e in db.person_logs.get_relation_edge_events()
            if str(e["origin"]).startswith("recommendation:")]












@pytest.mark.parametrize("candidate_kind", ["荐起复", "荐在职"])
def test_replay_same_event_with_changed_reason_stays_two_rows(game, candidate_kind):
    """r1 F2：幂等身份只锚稳定 origin（recommendation:{id}:{腿别}+|round 口径），
    不含可变 context——同 event_id 换荐词重放，恒 2 行且原文不被改写。"""
    from ming_sim.recommendations import record_recommendation_edges

    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(r for r in list_recommendation_candidates(db, state, recommender.name)
               if r["candidate_kind"] == candidate_kind)
    reason = "  旧任有实绩，罢居后仍可起复。\r\n "
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", reason)
    _commit_and_promulgate(db, state, content, action_id)
    event = db.conn.execute("SELECT * FROM recommendation_events WHERE recommender=?", (recommender.name,)).fetchone()
    assert (event["candidate"], event["candidate_kind"], event["reason"]) == (
        row["name"], {"荐起复": "起复", "荐在职": "在职"}[candidate_kind], reason,
    )
    legs = _recommendation_origins(db)
    assert {(e["source"], e["target"], e["event_kind"], e["context"]) for e in legs} == {
        (recommender.name, row["name"], "恩义", reason),
        ("皇帝", recommender.name, "知遇", reason),
    }
    assert content.characters[row["name"]].office == "巡盐御史"

    # Same durable event, changed reason and turn: no duplicate or rewritten edges.
    state.turn += 3
    record_recommendation_edges(db, state, recommender.name, row["name"], event["id"], "改口")
    db.load_state()
    assert tuple(db.conn.execute("SELECT * FROM recommendation_events WHERE id=?", (event["id"],)).fetchone()) == tuple(event)
    assert _recommendation_origins(db) == legs
    assert content.characters[row["name"]].office == "巡盐御史"


def test_appointment_without_recommendation_writes_no_edges(game):
    """生成侧缺席时接口幂等待命：无 recommendation 载荷不落边、不阻塞其他写端。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = list_recommendation_candidates(db, state, recommender.name)[0]
    action_id = db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender.name,
        target_id=None,
        payload={"text": "测试任免原文",
            "name": row["name"], "office": "巡盐御史",
            "faction": row["faction"], "reason": "",
        },
    )

    _commit_and_promulgate(db, state, content, action_id)

    assert _recommendation_origins(db) == []


# ---------------------------------------------------------------------------
# PR #1519 庭裁 Y1/Y2/Y3：工具受理点唯一准入 + 生产链逐字透传真入口回归。


def test_unapproved_appointment_writes_zero_edges(game):
    db, state, content = game
    recommender = _pick_recommender(content)
    row = next(r for r in list_recommendation_candidates(db, state, recommender.name)
               if r["status"] != "dismissed")
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", "边才可用")
    # 快照失效 → 任命未获准。
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE name=?", (row["name"],))
    db.conn.commit()

    with pytest.raises(ValueError):
        _commit_and_promulgate(db, state, content, action_id)

    assert db.conn.execute("SELECT COUNT(*) AS n FROM recommendation_events WHERE recommender=?", (recommender.name,)).fetchone()["n"] == 0
    assert _recommendation_origins(db) == []


def test_empty_reason_fails_loud_and_rolls_back_everything(game):
    """r3：reason 缺失/空 → 任命与双边同事务 fail-loud 回滚，不落任命、不落边。"""
    db, state, content = game
    recommender = _pick_recommender(content)
    row = list_recommendation_candidates(db, state, recommender.name)[0]
    action_id = _stage_recommendation(db, state, recommender.name, row, "巡盐御史", "   ")

    with pytest.raises(ValueError):
        _commit_and_promulgate(db, state, content, action_id)

    assert db.conn.execute("SELECT COUNT(*) AS n FROM recommendation_events WHERE recommender=?", (recommender.name,)).fetchone()["n"] == 0
    assert _recommendation_origins(db) == []
    char_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (row["name"],)).fetchone()
    assert char_row["office"] != "巡盐御史"


def test_second_leg_failure_rolls_back_everything(game, monkeypatch):
    db, state, content = game
    recommender = _pick_recommender(content)
    row = list_recommendation_candidates(db, state, recommender.name)[0]
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
    assert db.conn.execute("SELECT COUNT(*) AS n FROM recommendation_events WHERE recommender=?", (recommender.name,)).fetchone()["n"] == 0
    assert db.person_logs.get_relation_edge_events() == []
    char_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (row["name"],)).fetchone()
    assert char_row["office"] != "巡盐御史"
