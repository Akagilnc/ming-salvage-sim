"""#1831 事务记录与指向：收夜同生、新指旧、当前情况可恢复、代码不判了结。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.audience_night as audience_night
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
import ming_sim.simulation as simulation
from ming_sim.audience_extraction import parse_extraction_facts
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.public_sayings import list_public_sayings, record_public_saying
from ming_sim.session import GameSession
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_extractor_shared_context,
    extract_scores_by_modules_with_agno,
)


NINGYUAN = "宁远护送"
ORIGIN = "拨银、调将、派兵去宁远"
PROGRESS = "护送银两已出京，尚未抵宁远"


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _declaration(*, attach="new", birth_key="", affair_id=None, identity=""):
    body = {"attach": attach}
    if attach == "new":
        body["name"] = NINGYUAN
        body["origin"] = ORIGIN
        if birth_key:
            body["birth_key"] = birth_key
        if identity:
            body["identity"] = identity
    else:
        body["affair_id"] = int(affair_id)
    return body


def _persist_reply(db, state, minister, reply="臣记下此事。"):
    night = audience_night.open_night(db, state)
    nid = int(night["id"])
    audience_night.summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)
    row = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()
    return nid, ctid, int(row["night_seq"])


def _session(db, state, content, *, reply):
    class FakeAgent:
        def run(self, _msg):
            return SimpleNamespace(content=reply, tools=[])

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(get=lambda _c: FakeAgent())
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="agy")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message
    return sess


def _script_split(monkeypatch, drafts, *, batch_declaration):
    classified = json.dumps(
        [{"动作类型": "拟旨"} for _ in drafts], ensure_ascii=False,
    )

    def scripted_backend(*_args, **kwargs):
        tag = kwargs.get("tag")
        if tag == "action_intent":
            return classified, 0
        if tag == "draft_intent":
            return json.dumps(
                {"事务声明": batch_declaration, "成品旨稿": drafts},
                ensure_ascii=False,
            ), 0
        raise AssertionError(f"unexpected backend call: {tag}")

    monkeypatch.setattr(cb, "_run_backend_for_config", scripted_backend)
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(
        cb, "extract_confirmation_intent",
        lambda *a, **k: {"confirmation": "应允", "target_ids": [], "new_content": ""},
    )
    monkeypatch.setattr(
        cb, "extract_directive_confirmation",
        lambda player_message, minister_reply, candidates, llm_config=None: {
            "decision": "应允",
            "target_ids": [int(item["id"]) for item in candidates],
        },
    )


def _ningyuan_drafts(db, minister):
    army_id = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    return [
        {
            "正文": "拨银三十万解往宁远",
            "动作类型": "grant_allocation",
            "目标类型": "region",
            "目标": "shaanxi",
            "金额": 300000,
            "账户": "国库",
            "执行面": "in_transit",
            "颁布方式": "ordinary",
        },
        {
            "正文": "调洪承畴赴宁远",
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "承办人": minister,
            "颁布方式": "普通",
        },
        {
            "正文": "派兵护送去宁远",
            "动作类型": "military_order",
            "目标类型": "army",
            "目标ID": army_id,
            "承办人": minister,
            "期限月数": 2,
            "颁布方式": "普通",
        },
    ]


def _promulgated_origin(db, state, minister):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="推演结果来源旨",
        target_kind="issue",
        target_id="ningyuan-result",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=92000,
        payload={"assignee_id": minister},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _extract(monkeypatch, db, state, canned):
    def _fake_run(_agent, _prompt, tag):
        if str(tag).startswith("extractor/"):
            return canned[tag.split("/", 1)[1]]
        return _prompt

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    return extract_scores_by_modules_with_agno(
        {module: object() for module in EXTRACTION_MODULES},
        db, state, "宁远护送已毕。", parallel=False,
    )


def test_ningyuan_close_night_one_affair_three_dossiers(game, monkeypatch):
    """玩家一句交办 → 受控拆旨（批顶层声明）→ 应允 → 收夜：一件事务下三份案卷。"""
    db, state, content = game
    minister = _minister(db)
    night = audience_night.open_night(db, state)
    audience_night.summon_enter(db, int(night["id"]), minister)
    drafts = _ningyuan_drafts(db, minister)
    _script_split(monkeypatch, drafts, batch_declaration=_declaration())
    sess = _session(db, state, content, reply="臣拟三道：拨银、调将、派兵护送去宁远。")
    sess.chat(minister, ORIGIN)

    pending = [
        row for row in db.list_pending_actions(int(state.turn), minister_name=minister)
        if row["kind"] == "directive"
    ]
    assert len(pending) == 3
    sess.chat(minister, "三事全允")
    audience_night.close_night(db, state, night_id=night["id"], content=content)

    open_affairs = db.affairs.list_open()
    assert len(open_affairs) == 1
    affair = open_affairs[0]
    assert (affair.name, affair.origin, affair.status) == (NINGYUAN, ORIGIN, "open")
    dossiers = db.affairs.dossiers(affair.id)
    assert len(dossiers) == 3
    first_id = int(dossiers[0]["id"])
    db.record_issue_economy_move(
        state, "国库", -1, "奉旨拨帑", "宁远护送银",
        origin_ref=f"dossier:{first_id}",
    )
    issue_id = db.insert_issue(
        state, kind="situation", title="宁远护送未达",
        origin_kind="decree", origin_ref=f"dossier:{first_id}",
    )
    assert db.affairs.affair_id_for_issue(issue_id) == affair.id
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=PROGRESS,
        year=state.year, period=state.period, turn=state.turn,
    )
    record_public_saying(
        db, state, "银两已出京", involved_characters=[minister],
        affair_ref=db.affairs.origin_ref(affair.id),
    )
    pubs = [
        entry for entry in audience_night.list_ledger(db, night["id"])
        if audience_night.TAG_MINGFA in (entry.get("tags") or [])
        and str(entry.get("origin_ref") or "")
    ]
    assert pubs
    refs = set(db.affairs.origin_refs(affair.id))
    assert {str(entry["origin_ref"]) for entry in pubs} <= refs
    brief = build_extractor_shared_context(db, state, "宁远护送", "")
    row = next(item for item in brief["open_affairs"] if int(item["id"]) == affair.id)
    assert "experiences" not in row
    assert row["current_situation"] == PROGRESS

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        loaded = restored.affairs.get(affair.id)
        assert loaded.name == NINGYUAN
        materials = restored.affairs.current_situation(restored.textual_facts, affair.id)
        assert [fact.body for fact in materials] == [PROGRESS]
        restored_pubs = [
            entry for entry in audience_night.list_ledger(restored, night["id"])
            if audience_night.TAG_MINGFA in (entry.get("tags") or [])
            and str(entry.get("origin_ref") or "")
        ]
        assert restored_pubs
        restored_refs = set(restored.affairs.origin_refs(affair.id))
        assert {str(entry["origin_ref"]) for entry in restored_pubs} <= restored_refs
        restored_brief = build_extractor_shared_context(restored, state, "宁远护送", "")
        restored_row = next(
            item for item in restored_brief["open_affairs"] if int(item["id"]) == affair.id
        )
        assert "experiences" not in restored_row
        assert restored_row["current_situation"] == PROGRESS
        assert list_public_sayings(
            restored, affair_ref=restored.affairs.origin_ref(affair.id),
        )
    finally:
        restored.close()


def test_existing_open_affair_grounds_split_declaration(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    existing = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    night = audience_night.open_night(db, state)
    audience_night.summon_enter(db, int(night["id"]), minister)
    _script_split(
        monkeypatch, _ningyuan_drafts(db, minister),
        batch_declaration=_declaration(attach="existing", affair_id=existing.id),
    )
    sess = _session(db, state, content, reply="臣拟三道接到前案。")
    sess.chat(minister, ORIGIN)
    sess.chat(minister, "三事全允")
    audience_night.close_night(db, state, night_id=night["id"], content=content)
    assert [row.id for row in db.affairs.list_open()] == [existing.id]
    assert len(db.affairs.dossiers(existing.id)) == 3


def test_conflicting_affair_declaration_on_existing_dossier_fails_loud(game):
    db, state, _ = game
    minister = _minister(db)
    pending_id = 91002
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    other = db.affairs.open(
        name="另事", origin="另一件交办",
        year=state.year, period=state.period, turn=state.turn,
    )
    db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=pending_id,
        payload={
            "assignee_id": minister,
            "affair_declaration": _declaration(attach="existing", affair_id=first.id),
        },
    )
    before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    try:
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="调洪承畴赴宁远",
            target_kind="issue",
            target_id="ningyuan-general",
            executor_kind="character",
            executor_id=minister,
            pending_action_id=pending_id,
            payload={
                "assignee_id": minister,
                "affair_declaration": _declaration(
                    attach="existing", affair_id=other.id,
                ),
            },
        )
    except ValueError as exc:
        assert str(first.id) in str(exc)
    else:
        raise AssertionError("expected conflict")
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before


def test_extractor_result_declarations_survive_sanitize_and_bind(game, monkeypatch):
    db, state, content = game
    minister = _minister(db)
    origin = _promulgated_origin(db, state, minister)
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    second = db.affairs.open(
        name="另事", origin="另一件交办",
        year=state.year, period=state.period, turn=state.turn,
    )
    grouped = _declaration(identity="ningyuan-escort")
    canned = {
        "internal": json.dumps({
            "钱粮收支": [{
                "账户": "国库", "增量": -1, "分类": "善后", "原因": "无案卷后果",
                "事务声明": grouped,
            }],
        }, ensure_ascii=False),
        "military_external": '{"new_armies": []}',
        "issues": json.dumps({
            "局势推进": [],
            "新立局势": [{
                "origin_kind": "decree",
                "origin_ref": origin,
                "kind": "situation",
                "title": "推演新起",
                "事务声明": grouped,
            }],
            "事件结局": {}, "撤销局势": [], "结案局势": [],
            "案卷执行": [], "案卷参与人": [], "拨帑对账": [], "政敌检举": [],
            "事务声明": [],
        }, ensure_ascii=False),
        "personnel_secret": json.dumps({
            "人物变更": [{
                "name": minister, "动作": "评定", "loyalty": 1,
                "事务声明": grouped,
            }],
        }, ensure_ascii=False),
        "relations": '{"大臣互动": []}',
    }
    merged, _localized, _inputs = _extract(monkeypatch, db, state, canned)
    applied = apply_score_extraction(
        db, state, merged, content=content,
        open_affair_ids_at_input={first.id, second.id},
    )
    created = applied["issue_summary"]["new_issues"][0]
    assert created["rejected"] is False
    born = db.affairs.affair_id_for_issue(int(created["issue_id"]))
    assert born > 0
    affair_ref = db.affairs.origin_ref(born)
    assert db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE origin_ref=?",
        (affair_ref,),
    ).fetchone()
    assert db.conn.execute(
        "SELECT origin_ref FROM person_logs WHERE origin_ref=?",
        (affair_ref,),
    ).fetchone()
    # canonical affair 来源精确匹配：故事经历后缀不得被 durable-effect 来源校验放行。
    assert db.effect_origin_rejection(f"{affair_ref}/turn:1/0") is not None

    denied = apply_score_extraction(
        db, state,
        {"new_issues": [{
            "origin_kind": "decree", "origin_ref": origin,
            "kind": "situation", "title": "越权挂接",
            "affair_declaration": _declaration(attach="existing", affair_id=second.id),
        }]},
        content=content, open_affair_ids_at_input={first.id},
    )
    assert denied["issue_summary"]["new_issues"][0]["rejected"] is True

    raw_denied = apply_score_extraction(
        db, state,
        {"economy_moves": [{
            "account": "国库", "delta": -1, "category": "善后", "reason": "越权来源",
            "origin_ref": db.affairs.origin_ref(second.id),
        }]},
        content=content, open_affair_ids_at_input={first.id},
    )
    assert raw_denied["economy_moves_rejections"][0]["rejected"] is True
    assert db.conn.execute(
        "SELECT 1 FROM economy_ledger WHERE origin_ref=?",
        (db.affairs.origin_ref(second.id),),
    ).fetchone() is None

    before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库", "delta": -2, "category": "善后", "reason": "另起",
                "affair_declaration": _declaration(identity="escort-a"),
            }],
            "人物变更": [{
                "name": minister, "动作": "评定", "loyalty": 1,
                "affair_declaration": _declaration(identity="escort-b"),
            }],
        },
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before + 2

    planted = _declaration(birth_key="result:planted-key")
    before_planted = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    apply_score_extraction(
        db, state,
        {"economy_moves": [{
            "account": "国库", "delta": -3, "category": "善后", "reason": "跨次甲",
            "affair_declaration": planted,
        }]},
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": minister, "动作": "评定", "loyalty": 1,
            "affair_declaration": planted,
        }]},
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM affairs",
    ).fetchone()["n"] == before_planted + 2

    # 同批同 identity 但 name/origin 冲突：坏项逐项拒收，合法 sibling 照落——不
    # 得从预处理抛穿中止整批（ADR 0005，#1831）。
    before_conflict = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    conflict_result = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库", "delta": -4, "category": "善后", "reason": "冲突甲",
                "affair_declaration": _declaration(identity="conflict-id"),
            }],
            "人物变更": [{
                "name": minister, "动作": "评定", "loyalty": 1,
                "affair_declaration": {
                    "attach": "new", "name": "另一名", "origin": "另一起因",
                    "identity": "conflict-id",
                },
            }],
        },
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    # sibling（economy_moves，先声明 identity 的一项）照落，新建一事务。
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM affairs",
    ).fetchone()["n"] == before_conflict + 1
    # 冲突项（人物变更，identity 相同但 name/origin 不符）单项拒收，不落地。
    assert conflict_result["applied_person_changes"] == []
    assert any(
        rejection.get("report_section") == "人物变更"
        and "identity" in str(rejection.get("reason"))
        for rejection in conflict_result["validate_shape_rejections"]
    )

    # Carrier validation and affair birth are one itemwise transaction.
    before_invalid = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    invalid = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "不存在账户", "delta": -1, "category": "善后", "reason": "坏载体",
                "affair_declaration": _declaration(identity="invalid-economy"),
            }],
            "人物变更": [{
                "name": minister, "动作": "瞎搞一通",
                "affair_declaration": _declaration(identity="invalid-person"),
            }],
        },
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    assert invalid["economy_moves_rejections"][0]["rejected"] is True
    assert any(row.get("rejected") for row in invalid["applied_person_changes"])
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before_invalid

    # A conflicting new-issue declaration is dropped before either its issue or affair is born.
    issues_before = db.conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
    affairs_before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    new_conflict = apply_score_extraction(
        db, state,
        {"new_issues": [
            {"origin_kind": "decree", "kind": "situation", "title": "合法同批项",
             "affair_declaration": _declaration(identity="new-conflict")},
            {"origin_kind": "decree", "kind": "situation", "title": "冲突项",
             "affair_declaration": {
                 "attach": "new", "name": "另一事务", "origin": "另一来源",
                 "identity": "new-conflict",
             }},
        ]},
        content=content, open_affair_ids_at_input={first.id, second.id},
    )
    assert len(new_conflict["issue_summary"]["new_issues"]) == 1
    assert any(row.get("report_section") == "new_issues"
               for row in new_conflict["validate_shape_rejections"])
    assert db.conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"] == issues_before + 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == affairs_before + 1


def test_same_name_affairs_are_not_merged_and_birth_close_is_rejected(game):
    db, state, _ = game
    minister = _minister(db)
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    second = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    assert first.id != second.id
    before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    apply_score_extraction(
        db, state, {"affair_declarations": [_declaration()]},
        open_affair_ids_at_input=set(),
    )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before
    try:
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="调洪承畴赴宁远",
            target_kind="issue",
            target_id="ningyuan-general",
            executor_kind="character",
            executor_id=minister,
            payload={
                "assignee_id": minister,
                "affair_declaration": _declaration(attach="close", affair_id=first.id),
            },
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected birth close to fail")
    assert db.affairs.get(first.id).status == "open"


def test_translation_experience_marks_affair_without_dossier(game):
    db, state, content = game
    minister = _minister(db)
    affair = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    assert db.affairs.dossiers(affair.id) == ()
    nid, ctid, seq = _persist_reply(db, state, minister)
    facts = parse_extraction_facts({
        "facts": [{
            "person_names": [minister],
            "body": "护送途中闻边报，尚无案卷",
            "事务声明": _declaration(attach="existing", affair_id=affair.id),
        }],
    })
    db.settle_story_extraction(
        ctid, nid, facts, seq, authorized_open_ids={affair.id},
    )
    rows = db.affairs.experiences(affair.id)
    assert len(rows) == 1
    assert minister in rows[0]["person_names"]
    assert str(rows[0]["origin_ref"]).startswith(f"affair:{affair.id}/")
    brief = build_extractor_shared_context(db, state, "宁远护送", "")
    row = next(item for item in brief["open_affairs"] if int(item["id"]) == affair.id)
    assert "experiences" not in row

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        restored_rows = restored.affairs.experiences(affair.id)
        assert minister in restored_rows[0]["person_names"]
        assert restored_rows[0]["origin_ref"] == rows[0]["origin_ref"]
    finally:
        restored.close()


def test_close_requires_open_affairs_visible_in_batch(game, monkeypatch):
    db, state, _ = game
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    second = db.affairs.open(
        name="另事", origin="另一件交办",
        year=state.year, period=state.period, turn=state.turn,
    )
    extractor_input = build_extractor_shared_context(db, state, "宁远护送已毕，此事了结。", "")
    input_ids = {int(row["id"]) for row in extractor_input["open_affairs"]}
    canned = {
        "internal": '{"economy_moves": []}',
        "military_external": '{"new_armies": []}',
        "issues": json.dumps({
            "局势推进": [], "新立局势": [], "事件结局": {},
            "撤销局势": [], "结案局势": [],
            "案卷执行": [], "案卷参与人": [], "拨帑对账": [], "政敌检举": [],
            "事务声明": [{"attach": "close", "affair_id": first.id}],
        }, ensure_ascii=False),
        "personnel_secret": '{"secret_order_updates": []}',
        "relations": '{"大臣互动": []}',
    }
    merged, _localized, _inputs = _extract(monkeypatch, db, state, canned)
    apply_score_extraction(db, state, merged, open_affair_ids_at_input={second.id})
    assert db.affairs.get(first.id).status == "open"

    issue_id = db.conn.execute(
        "INSERT INTO issues (kind, title, origin_turn, affair_id) VALUES (?, ?, ?, ?)",
        ("situation", "护送仍在途中", state.turn, first.id),
    ).lastrowid
    rejected = apply_score_extraction(
        db, state, merged, open_affair_ids_at_input=input_ids,
    )
    assert db.affairs.get(first.id).status == "open"
    assert rejected["validate_shape_rejections"][0]["report_section"] == "affair_declarations"

    db.conn.execute("UPDATE issues SET status='resolved' WHERE id=?", (issue_id,))
    apply_score_extraction(db, state, merged, open_affair_ids_at_input=input_ids)
    assert db.affairs.get(first.id).status == "closed"
    assert db.affairs.get(second.id).status == "open"


def test_typed_affair_new_issues_share_provenance_and_close_final_state(game):
    db, state, content = game
    existing = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    result = apply_score_extraction(
        db, state,
        {
            "affair_declarations": [
                _declaration(attach="close", affair_id=existing.id),
            ],
            "new_issues": [
                {
                    "origin_kind": "decree", "kind": "situation",
                    "title": "护送仍在途中",
                    "affair_declaration": _declaration(
                        attach="existing", affair_id=existing.id,
                    ),
                },
                {
                    "origin_kind": "decree", "kind": "situation",
                    "title": "推演另起风波",
                    "affair_declaration": _declaration(identity="new-storm"),
                },
            ],
        },
        content=content, open_affair_ids_at_input={existing.id},
    )
    created = result["issue_summary"]["new_issues"]
    assert [item["rejected"] for item in created] == [False, False]
    assert db.affairs.affair_id_for_issue(created[0]["issue_id"]) == existing.id
    assert db.affairs.affair_id_for_issue(created[1]["issue_id"]) != existing.id
    assert db.affairs.get(existing.id).status == "open"
    assert any(
        row["report_section"] == "affair_declarations"
        and "未了局势" in row["reason"]
        for row in result["validate_shape_rejections"]
    )
