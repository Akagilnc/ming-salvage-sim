"""#635 [479·S4] 荐人口：荐人事件消费·原子双边（庭裁 r1-r3）。

真入口验收（F3）：stage→commit_pending_actions（proposed 案卷）→apply_dossier_verdicts
获准任命→_commit_office_action 内 applier.atomic 同事务落 record_recommendation 与两条边
→restore 只读 DB 重建；负向：任命未获准→零边；第二腿注入失败→全回滚零残留；
r3：reason 非空逐字必填，缺失则任命与双边同事务 fail-loud 回滚。
"""


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
    legs = [e for e in db.person_logs.get_relation_edge_events()
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
        payload={"text": "测试任免原文",
            "name": row["name"], "office": "巡盐御史",
            "faction": row["faction"], "reason": "",
        },
    )

    _commit_and_promulgate(db, state, content, action_id)

    assert _recommendation_origins(db) == []


# ---------------------------------------------------------------------------
# PR #1519 庭裁 Y1/Y2/Y3：工具受理点唯一准入 + 生产链逐字透传真入口回归。
