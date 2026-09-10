"""#1831 事务记录与指向：收夜同生、新指旧、当前情况可恢复、代码不判了结。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.audience_night as audience_night
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.session import GameSession
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_extractor_shared_context,
    extract_scores_by_modules_with_agno,
)


NINGYUAN = "宁远护送"
ORIGIN = "拨银、调将、派兵去宁远"
PROGRESS = "护送银两已出京，尚未抵宁远"
ARRIVED = "银两已抵宁远，洪承畴接管防务"
SILENCE = "袁崇焕被灭口，无案可稽"


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _declaration(*, attach="new", birth_key="", affair_id=None):
    body = {"attach": attach}
    if attach == "new":
        body["name"] = NINGYUAN
        body["origin"] = ORIGIN
        if birth_key:
            body["birth_key"] = birth_key
    else:
        body["affair_id"] = int(affair_id)
    return body


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


def test_ningyuan_close_night_one_affair_three_dossiers(game, monkeypatch):
    """玩家一句交办 → 受控拆旨 → 应允 → 收夜：一件事务下三份案卷。"""
    db, state, content = game
    minister = _minister(db)
    army_id = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    night = audience_night.open_night(db, state)
    audience_night.summon_enter(db, int(night["id"]), minister)
    declaration = _declaration()
    drafts = [
        {
            "正文": "拨银三十万解往宁远",
            "动作类型": "grant_allocation",
            "目标类型": "region",
            "目标": "shaanxi",
            "金额": 300000,
            "账户": "国库",
            "执行面": "in_transit",
            "颁布方式": "ordinary",
            "事务声明": declaration,
        },
        {
            "正文": "调洪承畴赴宁远",
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "承办人": minister,
            "颁布方式": "普通",
            "事务声明": declaration,
        },
        {
            "正文": "派兵护送去宁远",
            "动作类型": "military_order",
            "目标类型": "army",
            "目标ID": army_id,
            "承办人": minister,
            "期限月数": 2,
            "颁布方式": "普通",
            "事务声明": declaration,
        },
    ]
    classified = json.dumps(
        [{"动作类型": "拟旨"} for _ in drafts], ensure_ascii=False,
    )

    def scripted_backend(*_args, **kwargs):
        tag = kwargs.get("tag")
        if tag == "action_intent":
            return classified, 0
        if tag == "draft_intent":
            return json.dumps({"成品旨稿": drafts}, ensure_ascii=False), 0
        raise AssertionError(f"unexpected backend call: {tag}")

    monkeypatch.setattr(cb, "_run_backend_for_config", scripted_backend)
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    sess = _session(
        db, state, content,
        reply="臣拟三道：拨银、调将、派兵护送去宁远。",
    )
    sess.chat(minister, ORIGIN)

    pending = [
        row for row in db.list_pending_actions(int(state.turn), minister_name=minister)
        if row["kind"] == "directive"
    ]
    assert len(pending) == 3
    payloads = [json.loads(row["payload_json"] or "{}") for row in pending]
    assert all(payload.get("affair_declaration") == declaration for payload in payloads)

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
    sess.chat(minister, "三事全允")
    audience_night.close_night(db, state, night_id=night["id"], content=content)

    open_affairs = db.affairs.list_open()
    assert len(open_affairs) == 1
    affair = open_affairs[0]
    assert affair.name == NINGYUAN
    assert affair.origin == ORIGIN
    assert affair.status == "open"

    dossiers = db.affairs.dossiers(affair.id)
    assert len(dossiers) == 3
    assert {row["action_type"] for row in dossiers} == {
        "grant_allocation", "assignment", "military_order",
    }
    assert all(int(row["affair_id"]) == affair.id for row in dossiers)

    first_id = int(dossiers[0]["id"])
    db.record_issue_economy_move(
        state, "国库", -1, "奉旨拨帑", "宁远护送银",
        origin_ref=f"dossier:{first_id}",
    )
    origin = db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE origin_ref=?",
        (f"dossier:{first_id}",),
    ).fetchone()["origin_ref"]
    assert origin == f"dossier:{first_id}"

    issue_id = db.insert_issue(
        state, kind="situation", title="宁远护送未达",
        origin_kind="decree", origin_ref=f"dossier:{first_id}",
    )
    assert db.affairs.affair_id_for_issue(issue_id) == affair.id

    db.textual_facts.append(
        subject_kind="affair",
        subject_id=str(affair.id),
        body=PROGRESS,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="character",
        subject_id=minister,
        body=SILENCE,
        year=state.year,
        period=state.period,
        turn=state.turn,
        origin_ref=db.affairs.origin_ref(affair.id),
    )
    affair_origin = db.affairs.origin_ref(affair.id)
    assert db.effect_origin_rejection(affair_origin) is None
    db.record_issue_economy_move(
        state, "国库", -1, "灭口善后", "无案卷后果",
        origin_ref=affair_origin,
    )
    character_facts = db.textual_facts.pointing_at(
        [affair_origin], subject_kind="character",
    )
    assert [fact.body for fact in character_facts] == [SILENCE]
    silent = db.conn.execute(
        "SELECT origin_ref FROM economy_ledger WHERE origin_ref=?",
        (affair_origin,),
    ).fetchone()["origin_ref"]
    assert silent == affair_origin

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        loaded = restored.affairs.get(affair.id)
        assert loaded.name == NINGYUAN
        materials = restored.affairs.current_situation(restored.textual_facts, affair.id)
        assert [fact.body for fact in materials] == [PROGRESS]
        assert restored.affairs.affair_id_for_issue(issue_id) == affair.id
        assert [
            fact.body for fact in restored.textual_facts.pointing_at(
                [restored.affairs.origin_ref(affair.id)], subject_kind="character",
            )
        ] == [SILENCE]
    finally:
        restored.close()


def test_bulk_existing_dossier_receives_declared_affair(game):
    db, state, _ = game
    minister = _minister(db)
    pending_id = 91001
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=pending_id,
        payload={"assignee_id": minister},
    )
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == 0
    affair = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    ids = db.create_decree_dossiers(
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
            "affair_declaration": _declaration(attach="existing", affair_id=affair.id),
        },
    )
    assert ids == [dossier_id]
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == affair.id

    again = db.create_decree_dossiers(
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
            "affair_declaration": _declaration(attach="existing", affair_id=affair.id),
        },
    )
    assert again == [dossier_id]
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == affair.id


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
    dossier_id = db.create_decree_dossier(
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
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == first.id
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
            pending_action_id=pending_id,
            payload={
                "assignee_id": minister,
                "affair_declaration": _declaration(
                    birth_key="orphan-affair",
                ),
            },
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected conflict")
    assert db.affairs.peek_declared_id(_declaration(birth_key="orphan-affair")) is None
    assert int(db.get_decree_dossier(dossier_id)["affair_id"]) == first.id

    issue_id = db.insert_issue(state, kind="situation", title="已指局势")
    db.affairs.point_issue(issue_id, first.id)
    try:
        db.affairs.point_issue(issue_id, other.id)
    except ValueError as exc:
        assert str(first.id) in str(exc)
    else:
        raise AssertionError("expected issue conflict")
    assert db.affairs.affair_id_for_issue(issue_id) == first.id


def test_code_does_not_auto_close_or_merge_affairs(game, monkeypatch):
    db, state, content = game
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
    assert [row.id for row in db.affairs.list_open()] == [first.id, second.id]

    db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        payload={
            "assignee_id": minister,
            "affair_declaration": _declaration(attach="existing", affair_id=first.id),
        },
    )
    still = db.affairs.get(first.id)
    assert still.status == "open"

    spawned = db.insert_issue(state, kind="situation", title="推演新起")
    born = db.affairs.attach_from_declaration(
        "issues", spawned, _declaration(),
        year=state.year, period=state.period, turn=state.turn,
    )
    assert db.affairs.affair_id_for_issue(spawned) == born
    assert born not in {first.id, second.id}

    before_affairs = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    apply_score_extraction(
        db, state,
        {"affair_declarations": [_declaration()]},
        open_affair_ids_at_input=set(),
    )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before_affairs
    assert db.affairs.get(first.id).status == "open"

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
                "affair_declaration": _declaration(
                    attach="close", affair_id=first.id,
                ),
            },
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected birth close to fail")
    assert db.affairs.get(first.id).status == "open"

    extractor_input = build_extractor_shared_context(db, state, "宁远护送已毕，此事了结。", "")
    open_from_input = extractor_input["open_affairs"]
    input_ids = {int(row["id"]) for row in open_from_input}
    assert first.id in input_ids
    assert second.id in input_ids
    close_id = first.id

    import ming_sim.simulation as simulation
    canned = {
        "internal": '{"economy_moves": []}',
        "military_external": '{"new_armies": []}',
        "issues": json.dumps({
            "局势推进": [], "新立局势": [], "事件结局": {},
            "撤销局势": [], "结案局势": [],
            "案卷执行": [], "案卷参与人": [], "拨帑对账": [], "政敌检举": [],
            "事务声明": [{"attach": "close", "affair_id": close_id}],
        }, ensure_ascii=False),
        "personnel_secret": '{"secret_order_updates": []}',
        "relations": '{"大臣互动": []}',
    }

    def _fake_run(_agent, _prompt, tag):
        if str(tag).startswith("extractor/"):
            return canned[tag.split("/", 1)[1]]
        return _prompt

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    merged, _localized, _inputs = extract_scores_by_modules_with_agno(
        {module: object() for module in EXTRACTION_MODULES},
        db, state, "宁远护送已毕，此事了结。", parallel=False,
    )
    assert merged["affair_declarations"] == [
        {"attach": "close", "affair_id": close_id},
    ]
    apply_score_extraction(
        db, state, merged, open_affair_ids_at_input={second.id},
    )
    assert db.affairs.get(first.id).status == "open"
    apply_score_extraction(
        db, state, merged, open_affair_ids_at_input=input_ids,
    )
    assert db.affairs.get(first.id).status == "closed"
    assert db.affairs.get(second.id).status == "open"
    assert db.affairs.get(born).status == "open"
    assert {row.id for row in db.affairs.list_open()} == {second.id, born}
