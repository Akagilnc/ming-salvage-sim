"""#1916 大臣主动许诺记账、到期复命。

Seams:
- scene_chat → 转译声明 → dispatch_declaration（真实召对入口）
- issues 承诺账（commitment_kind + participant_roster）
- undo_chat_turn 前像逆转（issues 入 TABLES）
- resolve_turn 过月机械尾 write_due_staged_commitment_todos
  → list_due_review_scenes / prepare_scene_materials 开场材料
- affair_declaration → insert_issue_with_affair_declaration
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    append_ledger_entry,
    close_night,
    ensure_summon_enter,
    open_night,
)
from ming_sim.audience_translate import build_c0_declaration_shape
from ming_sim.breach_plea import scan_and_write_breach_pleas
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.due_review import apply_pending_due_reviews, list_due_review_scenes
from ming_sim.knowledge import build_character_knowledge, origin_visible_to
from ming_sim.materials import (
    _scene_pending_audience_facts,
    list_materials,
    prepare_scene_materials,
    release_material_tree,
)
from ming_sim.month_chain import _gazette_feed, prepare_gazette_author_materials
from ming_sim.relations import summon_edge_origin
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement_payload import list_due_commitments
from ming_sim.staged_commitment import ENTRY_KIND_STAGED, TODO_STATUS_PENDING
from tests.conftest import (
    offline_empty_audience_translate,
    open_hall_turn,
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


def _one_month(session, db, state) -> None:
    session.resolve_turn(allow_empty_decree=True)
    wait_for_background_jobs(db)
    db.save_turn_report(state, "邸报", public_body="邸报")
    session.resolve_turn(allow_empty_decree=True)
    wait_for_background_jobs(db)


def test_minister_self_promise_timed_and_open_land_without_emperor_approval(
    game, monkeypatch,
):
    """有期限与无期限自诺都进承诺账；承诺人=该大臣；不经皇帝应允；撤回逆转。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    promisor = "魏忠贤"
    dossiers_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers",
    ).fetchone()["n"])
    issues_before = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM issues").fetchall()
    }
    affairs_before = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM affairs").fetchall()
    }

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
                    # R1：attach=new 创建事务须随撤回删除。
                    "affair_declaration": {
                        "attach": "new",
                        "name": "自诺事务0",
                        "origin": "大臣自诺",
                    },
                },
                {
                    "text": "臣愿扩到五万流民。",
                    "minister_promise": {
                        "title": "扩到五万流民",
                        "content": "扩到五万流民",
                        "promisor": "杨嗣昌",
                    },
                    "affair_declaration": {
                        "attach": "new",
                        "name": "自诺事务1",
                        "origin": "大臣自诺",
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
    _result, chat_turn_id = _scene_turn(
        sess, db, state, "尔等有何话说", night_id=nid,
    )

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
    assert str(timed_row["origin_kind"] or "") != "decree"
    assert str(open_row["origin_kind"] or "") != "decree"

    # C1-R1：同轮多人自诺各有唯一来源，承诺人各自可见己诺，互不覆盖。
    timed_origin = str(timed_row["origin_ref"] or "")
    open_origin = str(open_row["origin_ref"] or "")
    assert timed_origin and open_origin and timed_origin != open_origin
    assert f":minister_promise:{int(timed_row['id'])}" in timed_origin
    assert f":minister_promise:{int(open_row['id'])}" in open_origin
    assert origin_visible_to(db, timed_origin, promisor) is True
    assert origin_visible_to(db, open_origin, "杨嗣昌") is True
    assert origin_visible_to(db, timed_origin, "杨嗣昌") is False
    assert origin_visible_to(db, open_origin, promisor) is False
    assert origin_visible_to(db, timed_origin) is False
    assert any(
        int(i.get("id") or 0) == int(timed_row["id"])
        for i in build_character_knowledge(db, state, promisor).get("issues") or []
    )
    assert any(
        int(i.get("id") or 0) == int(open_row["id"])
        for i in build_character_knowledge(db, state, "杨嗣昌").get("issues") or []
    )
    assert not any(
        int(i.get("id") or 0) == int(open_row["id"])
        for i in build_character_knowledge(db, state, promisor).get("issues") or []
    )

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

    # 落账后应新建了两个事务（attach=new）。
    affairs_landed = {
        int(r["id"]) for r in db.conn.execute(
            "SELECT id FROM affairs WHERE status='open'",
        ).fetchall()
    }
    assert len(affairs_landed - affairs_before) == 2

    # J1/R1：issues + 本轮新建 affairs 均入前像——undo 后回到前像。
    db.reign.set_chat_turn_status("active", int(chat_turn_id))
    db.conn.commit()
    db.undo_chat_turn(int(chat_turn_id))
    issues_after_undo = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM issues").fetchall()
    }
    assert issues_after_undo == issues_before
    affairs_after_undo = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM affairs").fetchall()
    }
    assert affairs_after_undo == affairs_before
    assert _active_commitments_for(db, promisor) == []
    assert _active_commitments_for(db, "杨嗣昌") == []


def test_timed_minister_promise_due_appears_in_promisor_opening_materials(
    game, monkeypatch,
):
    """有期自诺到期后，首次入对开场可见；跨月未召见不丢；事务关联保留；ACK 收尾。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    promisor = "魏忠贤"

    # 既有 open 事务，供声明关联（J3）。
    affair = db.affairs.open(
        name="田尔耕案",
        origin="test",
        year=int(state.year),
        period=int(state.period),
        turn=int(state.turn),
    )
    # 源轮：dispatch 入口自记前像；收夜前须非在飞（有回话 id + active）。
    night_id, chat_id = open_hall_turn(db, state, promisor)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (promisor, int(state.turn), "尔有何话说"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (promisor, int(state.turn), "臣明日就办田尔耕。"),
    ).lastrowid
    db.conn.commit()
    db.reign.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )

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
                "affair_declaration": {
                    "attach": "existing", "affair_id": int(affair.id),
                },
            }],
        },
        minister_name=promisor,
        night_id=int(night_id),
        chat_turn_id=int(chat_id),
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    issue_id = int(result.commissions.applied[0]["issue_id"])
    # J3：已声明事务关联落库。
    assert int(db.issues.affair_id_of(issue_id)) == int(affair.id)

    close_night(db, state, content=content)
    before = int(state.turn)
    # 真实过月入口。deadline_months=1 → end_turn=turn+1；
    # write_due 在当月结算机械尾扫（尚未 next_period），故到期月本身再过一次月才写入待办。
    session = _prepare_player_month(db, state, content, monkeypatch)

    _one_month(session, db, state)
    assert int(state.turn) == before + 1
    _one_month(session, db, state)
    assert int(state.turn) == before + 2

    todos = [
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"]) == issue_id
    ]
    assert len(todos) == 1
    assert len([
        s for s in list_due_review_scenes(db)
        if int(s.get("commitment_ref") or 0) == issue_id
    ]) == 1

    # J2：到期后未召见再过一月，首次入对仍可见（不得因无案卷过早消费而丢）。
    _one_month(session, db, state)
    assert int(state.turn) == before + 3
    todos_after_skip = [
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"]) == issue_id
    ]
    assert len(todos_after_skip) == 1
    scenes_after_skip = [
        s for s in list_due_review_scenes(db)
        if int(s.get("commitment_ref") or 0) == issue_id
    ]
    assert len(scenes_after_skip) == 1

    # 承诺人首次入对：真实 prepare_scene_materials 开场须含到期项身份（J4 接缝）。
    night2 = open_night(db, state, location="乾清宫", time_of_day="昼")
    ensure_summon_enter(db, int(night2["id"]), promisor)
    pending_facts = _scene_pending_audience_facts(db, state)
    parsed = [json.loads(fact) for fact in pending_facts]
    assert any(
        isinstance(item, dict) and int(item.get("commitment_ref") or 0) == issue_id
        for item in parsed
    ), pending_facts
    knowledge = build_character_knowledge(db, state, promisor)
    assert any(int(i.get("id") or 0) == issue_id for i in knowledge.get("issues") or [])
    prepared = prepare_scene_materials(db, state)
    try:
        # R2：对交付 opening 中 JSON 事实反序列化，按字段等值核对身份
        # （禁子串：commitment_ref=4 不得匹配 40）。
        opening_facts = []
        for line in str(prepared.opening or "").splitlines():
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                opening_facts.append(obj)
        assert any(
            int(item.get("commitment_ref") or 0) == int(issue_id)
            for item in opening_facts
        ), opening_facts
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
    knowledge_after = build_character_knowledge(db, state, promisor)
    assert not any(
        int(i.get("id") or 0) == issue_id for i in knowledge_after.get("issues") or []
    )


def _land_minister_promise(db, state, *, promisor: str, title: str, deadline_months=1,
                           affair_declaration=None, extra=None):
    """真实召对分派入口落一笔自诺；返回 (issue_id, chat_id, night_id, applied)。"""
    night_id, chat_id = open_hall_turn(db, state, promisor)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (promisor, int(state.turn), "尔有何话说"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (promisor, int(state.turn), title),
    ).lastrowid
    db.conn.commit()
    db.reign.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    item = {
        "text": title,
        "minister_promise": {
            "title": title,
            "content": title,
            "promisor": promisor,
            "deadline_months": deadline_months,
        },
    }
    if affair_declaration is not None:
        item["affair_declaration"] = affair_declaration
    if extra:
        item.update(extra)
    result = dispatch_declaration(
        db, state, {"commissions": [item]},
        minister_name=promisor,
        night_id=int(night_id),
        chat_turn_id=int(chat_id),
    )
    return result, int(chat_id), int(night_id)


def test_c1_minister_promise_origin_not_public_visible(game, monkeypatch):
    """C1：自诺来源受限；真实公开作者写手不消费私语/私诺新建，保留既有公开事务。"""
    import ming_sim.materials as materials_mod

    db, state, content = game
    promisor = "魏忠贤"
    public_affair = db.affairs.open(
        name="公开边饷事务", origin="廷议边饷",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    public_affair_id = int(public_affair.id)
    result, chat_id, night_id = _land_minister_promise(
        db, state, promisor=promisor, title="私密自诺不入邸报",
        deadline_months=0,
        affair_declaration={
            "attach": "new",
            "name": "魏忠贤私下许诺查案",
            "origin": "御前私诺查办田尔耕",
        },
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    applied = result.commissions.applied[0]
    assert applied["kind"] == "minister_promise"
    issue_id = int(applied["issue_id"])
    private_affair_id = int(db.issues.affair_id_of(issue_id))
    assert private_affair_id > 0
    assert private_affair_id != public_affair_id
    row = db.conn.execute(
        "SELECT origin_ref, end_turn FROM issues WHERE id=?", (issue_id,),
    ).fetchone()
    origin_ref = str(row["origin_ref"] or "")
    assert origin_ref
    assert origin_visible_to(db, origin_ref) is False
    assert origin_visible_to(db, origin_ref, promisor) is True
    assert origin_visible_to(db, origin_ref, "杨嗣昌") is False

    private_entry_id = append_ledger_entry(
        db, int(night_id),
        person_names=[promisor],
        audibility=AUDIBILITY_PRIVATE,
        body="臣暗中查办田尔耕，明月具奏。",
        tags=["scroll_role:minister"],
        source_chat_turn_id=int(chat_id),
        origin_chat_turn_id=int(chat_id),
    )
    public_entry_id = append_ledger_entry(
        db, int(night_id),
        person_names=[promisor],
        audibility=AUDIBILITY_PUBLIC,
        body="朝堂共闻：整饬边饷。",
        tags=["scroll_role:minister"],
        source_chat_turn_id=int(chat_id),
        origin_chat_turn_id=int(chat_id),
    )

    # 密源边挂私诺事务：元数据门须用真实密令轮集合，不得因空集合误放行。
    secret_turn = 99
    edge_id = db.record_relation_edge_event(
        source=promisor, target="杨嗣昌", event_kind="协作",
        context="密源边夹具", origin=summon_edge_origin(secret_turn),
    )
    db.conn.execute(
        "UPDATE relation_edge_events SET affair_id=? WHERE id=?",
        (private_affair_id, int(edge_id)),
    )
    db.conn.commit()
    monkeypatch.setattr(
        materials_mod, "_secret_order_chat_turn_ids", lambda _db: {secret_turn},
    )

    db.conn.execute(
        "UPDATE issues SET end_turn=? WHERE id=?",
        (int(state.turn), issue_id),
    )
    db.conn.commit()
    due_ids = {int(i["issue_id"]) for i in list_due_commitments(db, state)}
    assert issue_id in due_ids
    feed = _gazette_feed(db, state)
    public_ids = {int(i["issue_id"]) for i in feed.get("due_commitments") or []}
    assert issue_id not in public_ids

    knowledge = build_character_knowledge(db, state, promisor)
    assert any(int(i.get("id") or 0) == issue_id for i in knowledge.get("issues") or [])

    # 一次安装写手观测：事务键 + audience id；密源 history 由事务键排除覆盖。
    captured = {"affair_keys": set(), "audience_ids": []}
    real_write = materials_mod._write_world_tree
    real_exp = materials_mod._experience_text

    def spy_exp(knowledge, audible_entries=()):
        captured["audience_ids"].extend(
            int(entry.get("id") or 0) for entry in audible_entries
        )
        return real_exp(knowledge, audible_entries)

    def spy_write(
        tmp, db_, state_, public_events, affair_lines, board_text, roster_text,
        world_facts, include_fact=None, include_event=None,
        secret_turn_ids=None, exclude_dossier_ids=None, public_only=False,
    ):
        captured["affair_keys"] = {line[0] for line in affair_lines}
        return real_write(
            tmp, db_, state_, public_events, affair_lines, board_text, roster_text,
            world_facts, include_fact, include_event,
            secret_turn_ids, exclude_dossier_ids, public_only,
        )

    monkeypatch.setattr(materials_mod, "_experience_text", spy_exp)
    monkeypatch.setattr(materials_mod, "_write_world_tree", spy_write)

    prepared = prepare_gazette_author_materials(db, state)
    try:
        assert f"affair-{private_affair_id}" not in captured["affair_keys"]
        assert f"affair-{public_affair_id}" in captured["affair_keys"]
        assert private_entry_id not in captured["audience_ids"]
        assert public_entry_id in captured["audience_ids"]
        paths = list_materials(prepared.root)
        assert not any(
            part.startswith(f"affair-{private_affair_id}-")
            for path in paths for part in str(path).split("/")
        )
        assert any(
            part.startswith(f"affair-{public_affair_id}-")
            for path in paths for part in str(path).split("/")
        )
    finally:
        release_material_tree(prepared.root)

    src_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_sources WHERE source_id=?",
        (origin_ref,),
    ).fetchone()["n"])
    assert src_before == 1
    db.reign.set_chat_turn_status("active", int(chat_id))
    db.conn.commit()
    db.undo_chat_turn(int(chat_id))
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_sources WHERE source_id=?",
        (origin_ref,),
    ).fetchone()["n"]) == 0

    # 反例：既有公开事务落公开收支后挂私诺，同一写手观测仍收到该事务身份。
    public_origin = db.affairs.origin_ref(public_affair_id)
    db.record_issue_economy_move(
        state, "国库", -1, "边饷", "公开收支",
        origin_ref=public_origin,
    )
    assert any(db.list_world_effect_history(public_origin).values())
    linked, _chat, _nid = _land_minister_promise(
        db, state, promisor=promisor, title="私诺挂既有公开事务",
        deadline_months=0,
        affair_declaration={"attach": "existing", "affair_id": public_affair_id},
    )
    assert linked.commissions.rejected == []
    linked_issue = int(linked.commissions.applied[0]["issue_id"])
    assert int(db.issues.affair_id_of(linked_issue)) == public_affair_id
    captured["affair_keys"] = set()
    prepared_after = prepare_gazette_author_materials(db, state)
    try:
        assert f"affair-{public_affair_id}" in captured["affair_keys"]
        assert any(
            part.startswith(f"affair-{public_affair_id}-")
            for path in list_materials(prepared_after.root)
            for part in str(path).split("/")
        )
    finally:
        release_material_tree(prepared_after.root)


def test_c2_correction_ids_rejected_on_minister_promise(game):
    """C2：自诺不得挂 resolves_rejection_ids；不崩批、不污染 pending_actions。"""
    from ming_sim.applier import Provenance

    db, state, content = game
    promisor = "魏忠贤"
    affair = db.affairs.open(
        name="拒收夹具", origin="test", year=int(state.year),
        period=int(state.period), turn=int(state.turn),
    )
    bad = {
        "origin_ref": f"affair:{affair.id}",
        "account": "不存在", "delta": -1,
        "category": "待修正", "reason": "原旨",
    }
    dispatch_declaration(
        db, state, {"effects": {"economy_moves": [bad]}},
        source=Provenance.player_decree,
    )
    rid = int(db.conn.execute(
        "SELECT id FROM rejection_reports ORDER BY id DESC LIMIT 1",
    ).fetchone()["id"])

    # 先塞一条无关 pending，id 可能与后续 issue 撞号时也不得被改。
    pending_before = {
        int(r["id"]): str(r["payload_json"] or "")
        for r in db.conn.execute("SELECT id, payload_json FROM pending_actions").fetchall()
    }

    result, _chat_id, _nid = _land_minister_promise(
        db, state, promisor=promisor, title="自诺不得修正旨意",
        extra={"resolves_rejection_ids": [rid]},
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert all(r.category in {"invalid_shape", "hallucinated_id", "missing_ref"}
               for r in result.commissions.rejected)
    pending_after = {
        int(r["id"]): str(r["payload_json"] or "")
        for r in db.conn.execute("SELECT id, payload_json FROM pending_actions").fetchall()
    }
    assert pending_after == pending_before
    assert _active_commitments_for(db, promisor) == []


def test_c2_minister_promise_applied_has_no_pending_id_field(game):
    """C2：自诺 applied 只报 issue_id，不冒充 pending_actions.id。"""
    db, state, content = game
    result, _c, _n = _land_minister_promise(
        db, state, promisor="魏忠贤", title="字段隔离",
    )
    assert result.commissions.rejected == []
    applied = result.commissions.applied[0]
    assert "issue_id" in applied
    assert "id" not in applied


def test_c3_real_scene_translation_supplies_affair_and_lands_link(game, monkeypatch):
    """C3/T1：真实召对转译收到事务身份供料，并据此关联落账（禁只测 builder/手工注入）。"""
    db, state, content = game
    promisor = "魏忠贤"
    affair = db.affairs.open(
        name="田尔耕案", origin="test",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    seen_prompts: list[str] = []

    def translate(prompt, llm_config):
        text = str(prompt or "")
        seen_prompts.append(text)
        # 从真实 prompt 契约输入解析 affair 身份，不手工旁路。
        affair_id = None
        for line in text.splitlines():
            if not line.startswith("affair\t"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2] == "田尔耕案":
                affair_id = int(parts[1])
                break
        assert affair_id == int(affair.id), text
        base = offline_empty_audience_translate(prompt, llm_config)
        return {
            **base,
            "commissions": [{
                "text": "臣明日就办田尔耕。",
                "minister_promise": {
                    "title": "办田尔耕",
                    "content": "明日就办田尔耕",
                    "promisor": promisor,
                    "deadline_months": 1,
                },
                "affair_declaration": {
                    "attach": "existing",
                    "affair_id": int(affair_id),
                },
            }],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣明日就办田尔耕。", tools=[])

    stub_scene_agent(monkeypatch, FakeAgent())
    sess = _sess(db, state, content, monkeypatch, translate_fn=translate)
    _result, _chat_turn_id = _scene_turn(
        sess, db, state, "尔有何话说", night_id=nid,
    )
    assert seen_prompts, "真实转译未接到 prompt"
    assert "affair_declaration" in build_c0_declaration_shape()
    rows = _active_commitments_for(db, promisor)
    assert len(rows) == 1
    issue_id = int(rows[0]["id"])
    assert int(db.issues.affair_id_of(issue_id)) == int(affair.id)


def test_c4_due_retention_only_for_minister_promise(game):
    """C4：无案卷桥时仅自诺保留 pending；旧分段承诺仍消费。"""
    db, state, content = game
    # 旧分段：active、无案卷桥（origin 非 dossier）。
    old_id = db.insert_issue(
        state,
        kind="initiative",
        title="旧分段无桥之诺",
        origin_kind="decree",
        origin_ref="legacy-no-dossier",
        stage_text="中段待办",
        participants=[{"character_id": "徐光启", "tier": "主办"}],
        end_turn=int(state.turn) + 5,
        commitment_kind="until_stop",
        stages_json=[
            {"stage_idx": 0, "due_turn": int(state.turn), "criterion_text": "中段"},
            {"stage_idx": 1, "due_turn": int(state.turn) + 3, "criterion_text": "末段"},
        ],
        commit=True,
    )
    db.dossiers.insert_next_audience_todo(
        commitment_ref=int(old_id),
        stage_idx=0,
        due_turn=int(state.turn),
        criterion_text="中段",
        origin_context="中段",
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=int(state.turn) - 1,
    )

    # 自诺：无案卷桥，应保留。
    result, _c, _n = _land_minister_promise(
        db, state, promisor="魏忠贤", title="自诺待办保留",
        deadline_months=1,
    )
    promise_id = int(result.commissions.applied[0]["issue_id"])
    db.dossiers.insert_next_audience_todo(
        commitment_ref=int(promise_id),
        stage_idx=0,
        due_turn=int(state.turn),
        criterion_text="自诺到期",
        origin_context="自诺到期",
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=int(state.turn) - 1,
        payload_json={"origin_ref": str(
            db.conn.execute(
                "SELECT origin_ref FROM issues WHERE id=?", (promise_id,),
            ).fetchone()["origin_ref"] or ""
        )},
    )

    outcomes = {
        int(r["todo_id"]): r
        for r in apply_pending_due_reviews(db, state)
    }
    old_todos = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t["commitment_ref"]) == int(old_id)
    ]
    promise_todos = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t["commitment_ref"]) == int(promise_id)
    ]
    assert old_todos and str(old_todos[0]["status"]) != TODO_STATUS_PENDING
    assert promise_todos and str(promise_todos[0]["status"]) == TODO_STATUS_PENDING
    old_todo_id = int(old_todos[0]["id"])
    promise_todo_id = int(promise_todos[0]["id"])
    if old_todo_id in outcomes:
        assert outcomes[old_todo_id].get("consumed") is True
    if promise_todo_id in outcomes:
        assert outcomes[promise_todo_id].get("consumed") is False


def test_c5_minister_promise_excluded_from_imperial_breach_scan(game):
    """C5：罢免自诺承诺人不得写皇命违诺哭谏/辜负边。"""
    db, state, content = game
    promisor = "魏忠贤"
    result, _c, _n = _land_minister_promise(
        db, state, promisor=promisor, title="臣下自诺非皇命",
        deadline_months=0,
    )
    issue_id = int(result.commissions.applied[0]["issue_id"])
    edges_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events",
    ).fetchone()["n"])

    db.conn.execute(
        "UPDATE characters SET status='dismissed' WHERE name=?", (promisor,),
    )
    db.conn.commit()
    written = scan_and_write_breach_pleas(db, state)

    linked = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t.get("commitment_ref") or 0) == issue_id
        and str(t.get("entry_kind") or "") == "midcourse_breach_plea"
    ]
    assert linked == []
    if written:
        written_refs = {
            int(t.get("commitment_ref") or 0)
            for t in db.dossiers.list_next_audience_todos()
            if int(t["id"]) in {int(x) for x in written}
        }
        assert issue_id not in written_refs
    edges_after = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events",
    ).fetchone()["n"])
    assert edges_after == edges_before
    assert str(db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"]) == "active"

