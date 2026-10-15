"""#1916 大臣主动许诺记账、到期复命。

Seams:
- scene_chat → 转译声明 → dispatch_declaration（真实召对入口）
- issues 承诺账（commitment_kind + participant_roster）
- resolve_turn 过月机械尾 write_due_staged_commitment_todos
  → list_due_review_scenes / prepare_scene_materials 开场材料
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ming_sim.audience_night import close_night, ensure_summon_enter, open_night
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.due_review import list_due_review_scenes
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import (
    _scene_pending_audience_facts,
    prepare_scene_materials,
    release_material_tree,
)
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.staged_commitment import TODO_STATUS_PENDING
from tests.conftest import (
    offline_empty_audience_translate,
    stub_scene_agent,
    wait_for_background_jobs,
)
from tests.test_audience_translate_1837 import _scene_turn, _sess
from tests.test_month_chain_1843 import _prepare_player_month


def _active_commitments_for(db, name: str):
    rows = []
    for row in db.issues.active_commitments():
        roster = row["participant_roster"]
        if isinstance(roster, str):
            roster = json.loads(roster)
        names = []
        for item in roster or []:
            if isinstance(item, dict):
                names.append(str(item.get("character_id") or ""))
            else:
                names.append(str(item))
        if name in names:
            rows.append(row)
    return rows


def test_minister_self_promise_timed_and_open_land_without_emperor_approval(
    game, monkeypatch,
):
    """有期限与无期限自诺都进承诺账；承诺人=该大臣；不经皇帝应允。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    promisor = "魏忠贤"
    dossiers_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers",
    ).fetchone()["n"])

    def translate(prompt, llm_config):
        base = offline_empty_audience_translate(prompt, llm_config)
        return {
            **base,
            "commissions": [
                {
                    "text": "臣明日就办田尔耕。",
                    "minister_promise": {
                        "title": "办田尔耕",
                        "content": "明日就办田尔耕",
                        "promisor": promisor,
                        "deadline_months": 1,
                    },
                },
                {
                    "text": "臣愿扩到五万流民。",
                    "minister_promise": {
                        "title": "扩到五万流民",
                        "content": "扩到五万流民",
                        "promisor": "杨嗣昌",
                    },
                },
            ],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(
                content="臣明日就办田尔耕。臣另愿扩到五万流民。", tools=[],
            )

    stub_scene_agent(monkeypatch, FakeAgent())
    sess = _sess(db, state, content, monkeypatch, translate_fn=translate)
    _scene_turn(sess, db, state, "尔等有何话说", night_id=nid)

    timed = _active_commitments_for(db, promisor)
    open_ended = _active_commitments_for(db, "杨嗣昌")
    assert len(timed) == 1
    assert len(open_ended) == 1

    timed_row = timed[0]
    open_row = open_ended[0]
    assert str(timed_row["commitment_kind"] or "").strip()
    assert str(open_row["commitment_kind"] or "").strip()
    assert int(timed_row["end_turn"] or 0) == int(state.turn) + 1
    assert int(open_row["end_turn"] or 0) == 0
    # form③：有期不写 stages，避免段派生 end_turn 堵住 acknowledged 收尾。
    stages_raw = timed_row["stages_json"]
    assert stages_raw in (None, "", "[]") or stages_raw == b"[]"
    assert str(timed_row["origin_kind"] or "") != "decree"
    assert str(open_row["origin_kind"] or "") != "decree"

    # 不经应允：无 pending 交办挂此自诺，亦无案卷颁布路径。
    pending = db.conn.execute(
        "SELECT COUNT(*) AS n FROM pending_actions "
        "WHERE turn=? AND status='pending'",
        (int(state.turn),),
    ).fetchone()["n"]
    assert int(pending) == 0
    dossiers_after = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers",
    ).fetchone()["n"])
    assert dossiers_after == dossiers_before


def test_timed_minister_promise_due_appears_in_promisor_opening_materials(
    game, monkeypatch,
):
    """有期自诺经真实过月入口到期后，承诺人下一场入对开场材料可见到期项。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    promisor = "魏忠贤"

    result = dispatch_declaration(
        db, state,
        {
            "commissions": [{
                "text": "臣明日就办田尔耕。",
                "minister_promise": {
                    "title": "办田尔耕",
                    "content": "明日就办田尔耕",
                    "promisor": promisor,
                    "deadline_months": 1,
                },
            }],
        },
        minister_name=promisor,
        night_id=nid,
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    issue_id = int(result.commissions.applied[0]["issue_id"])

    close_night(db, state, content=content)
    before = int(state.turn)
    # 真实过月入口。deadline_months=1 → end_turn=turn+1；
    # write_due 在当月结算机械尾扫（尚未 next_period），故到期月本身再过一次月才写入待办。
    session = _prepare_player_month(db, state, content, monkeypatch)

    def _one_month() -> None:
        session.resolve_turn(allow_empty_decree=True)
        wait_for_background_jobs(db)
        db.save_turn_report(state, "邸报", public_body="邸报")
        session.resolve_turn(allow_empty_decree=True)
        wait_for_background_jobs(db)

    _one_month()
    assert int(state.turn) == before + 1
    _one_month()
    assert int(state.turn) == before + 2

    todos = [
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"]) == issue_id
    ]
    assert len(todos) == 1

    scenes = [
        s for s in list_due_review_scenes(db)
        if int(s.get("commitment_ref") or 0) == issue_id
    ]
    assert len(scenes) == 1

    # 承诺人入对：开场材料吃 _scene_pending_audience_facts（结构化场面）。
    night2 = open_night(db, state, location="乾清宫", time_of_day="昼")
    ensure_summon_enter(db, int(night2["id"]), promisor)
    pending_facts = _scene_pending_audience_facts(db, state)
    parsed = [json.loads(fact) for fact in pending_facts]
    assert any(
        isinstance(item, dict) and int(item.get("commitment_ref") or 0) == issue_id
        for item in parsed
    ), pending_facts
    # 记录持久：承诺人 knowledge 仍可见该 issue。
    knowledge = build_character_knowledge(db, state, promisor)
    assert any(int(i.get("id") or 0) == issue_id for i in knowledge.get("issues") or [])
    prepared = prepare_scene_materials(db, state)
    try:
        assert prepared.opening  # 开场由 pending_facts 组成；上已核结构化身份
    finally:
        release_material_tree(prepared.root)

    # 条款2：兑现或落空沿既有 form③ acknowledged 收尾（无案卷、不伪造皇命）。
    close_out = settle_delta(
        state, db,
        {
            "close_issues": [{
                "issue_id": issue_id,
                "reason": "acknowledged",
                "narrative": "田尔耕事已复命，此诺了结。",
            }],
        },
        SettlementContext(content=content),
    )
    assert close_out.issue is not None
    assert close_out.issue.rejected == []
    assert any(
        int(c.get("issue_id") or 0) == issue_id for c in close_out.issue.closes
    )
    row = db.conn.execute(
        "SELECT status, closed_turn FROM issues WHERE id=?", (issue_id,),
    ).fetchone()
    assert str(row["status"]) == "dropped"
    assert int(row["closed_turn"] or 0) == int(state.turn)
    # knowledge 不再把已收尾自诺当 active 承诺。
    knowledge_after = build_character_knowledge(db, state, promisor)
    assert not any(
        int(i.get("id") or 0) == issue_id for i in knowledge_after.get("issues") or []
    )
