import asyncio
import json
import types

import pytest
import ming_sim.cli_backend as cli_backend
import ming_sim.issues as issue_engine
from ming_sim.session import GameSession


def _rejected_verdict(dossier_id):
    return {
        "dossier_id": dossier_id, "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": None, "reason": "科臣封驳。",
        "affected_parties": [
            {"kind": "faction", "key": "东林", "severity": "不满"},
        ],
        "midzhi_unpromulgatable": False,
        "criteria_snapshot": {
            "imperial_authority_band": "偏弱", "involved_office_types": ["言官"],
            "authorization_ids": [], "endorsement_entry_ids": [],
        },
    }


def _active_people(db, count):
    people = [
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT ?",
            (count,),
        ).fetchall()
    ]
    assert len(people) == count
    return people


def _active_minister(db):
    return _active_people(db, 1)[0]


def test_dossier_roster_preserves_multiple_leads_support_roles_and_knowers(game):
    db, state, _content = game
    people = _active_people(db, 4)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="倪黄合力，杨某接应。",
        target_kind="issue", target_id="land-survey",
        participants=[
            {"character_id": people[0], "tier": "主办", "role": "主持清丈"},
            {"character_id": people[1], "tier": "主办", "role": "会同清丈"},
            {"character_id": people[2], "tier": "协办", "role": "接应钱粮"},
            {"character_id": people[3], "tier": "知情", "role": "备悉"},
        ],
    )

    restored = db.get_decree_dossier(dossier_id)
    assert restored["participant_roster"] == [
        {"character_id": people[0], "tier": "主办", "role": "主持清丈", "delegator_id": None},
        {"character_id": people[1], "tier": "主办", "role": "会同清丈", "delegator_id": None},
        {"character_id": people[2], "tier": "协办", "role": "接应钱粮", "delegator_id": None},
        {"character_id": people[3], "tier": "知情", "role": "备悉", "delegator_id": None},
    ]


@pytest.mark.parametrize("participants", [
    ["not-an-object"],
    [{}],
    [{"character_id": "", "tier": "主办"}],
    [{"character_id": "placeholder"}],
    [{"character_id": "placeholder", "tier": ""}],
    [{"character_id": "placeholder", "tier": "旁听"}],
])
def test_dossier_create_rejects_malformed_structured_roster(game, participants):
    db, state, _content = game

    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type="assignment", decree_text="命查仓储。",
            target_kind="issue", target_id="granary", participants=participants,
        )

    assert db.list_decree_dossiers() == []


def test_dossier_roster_rejects_unknown_character_references_at_write_boundary(game):
    db, state, _content = game
    person = _active_minister(db)

    with pytest.raises(ValueError, match="参与人物不存在"):
        db.create_decree_dossier(
            state, action_type="assignment", decree_text="命查仓储。",
            target_kind="issue", target_id="granary",
            participants=[{"character_id": "不存在的人", "tier": "主办"}],
        )
    assert db.list_decree_dossiers() == []

    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命查仓储。",
        target_kind="issue", target_id="granary",
        participants=[{"character_id": person, "tier": "主办"}],
    )
    with pytest.raises(ValueError, match="委派人不存在"):
        db.append_decree_dossier_participants(dossier_id, [{
            "character_id": person, "tier": "协办", "delegator_id": "不存在的委派人",
        }])
    assert db.get_decree_dossier(dossier_id)["participant_roster"] == [{
        "character_id": person, "tier": "主办", "role": "", "delegator_id": None,
    }]


def test_conversation_draft_roster_reaches_committed_dossier(game, monkeypatch):
    db, state, content = game
    people = _active_people(db, 3)
    minister = people[0]
    character = next(ch for ch in content.characters.values() if ch.name == minister)
    active_names = {
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active'"
        ).fetchall()
    }
    aliased, alias = next(
        (ch, alias)
        for ch in content.characters.values() if ch.name in active_names
        for alias in ch.aliases if alias != ch.name
    )
    roster = [
        {"character_id": people[0], "tier": "主办", "role": "总理"},
        {"character_id": alias, "tier": "主办", "role": "会办"},
        {"character_id": people[2], "tier": "协办", "role": "核账"},
    ]
    expected_roster = [
        roster[0], {**roster[1], "character_id": aliased.name}, roster[2],
    ]
    canned = {
        "拟旨意图": "拟旨", "动作类型": "assignment", "目标类型": "issue",
        "目标ID": "granary-audit", "承办人": minister, "参与人": roster,
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *args, **kwargs: (json.dumps(canned, ensure_ascii=False), 1),
    )
    session = types.SimpleNamespace(
        db=db, state=state, content=content, registry=None,
        llm_config=types.SimpleNamespace(channel="cli"),
    )

    out = GameSession.apply_cli_conversation_actions(
        session, character, player_message="拟旨查仓。", answer="着会同清查仓储。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[out["pending_action_id"]],
        directive_status="draft",
    )

    dossier = db.list_decree_dossiers()[-1]
    assert dossier["participant_roster"] == [
        {**item, "delegator_id": None} for item in expected_roster
    ]


@pytest.mark.parametrize("draft_count", [1, 2])
@pytest.mark.parametrize("bad_roster", [
    ["not-an-object"],
    [{"character_id": "placeholder"}],
    {"character_id": "placeholder", "tier": "主办"},
    {},
    "",
    0,
    False,
])
def test_conversation_draft_rejects_malformed_roster_without_staging(
    game, monkeypatch, bad_roster, draft_count,
):
    db, state, content = game
    minister = _active_minister(db)
    character = next(ch for ch in content.characters.values() if ch.name == minister)
    draft = {
        "正文": "着会同清查仓储。", "动作类型": "assignment", "目标类型": "issue",
        "目标ID": "granary-audit", "承办人": minister, "参与人": bad_roster,
        "颁布方式": "普通",
    }
    canned = (
        {"拟旨意图": "拟旨", **draft}
        if draft_count == 1
        else {"成品旨稿": [draft, {**draft, "正文": "再核各仓旧账。"}]}
    )
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *args, **kwargs: (json.dumps(canned, ensure_ascii=False), 1),
    )
    session = types.SimpleNamespace(
        db=db, state=state, content=content, registry=None,
        llm_config=types.SimpleNamespace(channel="cli"),
    )

    with pytest.raises(ValueError):
        GameSession.apply_cli_conversation_actions(
            session, character, player_message="拟旨查仓。", answer="着会同清查仓储。",
            has_directive=False, secret_order_id=None,
            preclassified_intent=[{"kind": "draft"}] * draft_count,
        )

    assert db.list_pending_actions(state.turn) == []
    assert db.list_directives(state) == []
    assert db.list_decree_dossiers() == []


@pytest.mark.parametrize("write_path", ["create", "append"])
@pytest.mark.parametrize("delegation", ["self", "unrelated"])
def test_dossier_roster_write_boundary_rejects_invalid_delegator(
    game, write_path, delegation,
):
    db, state, _content = game
    lead, worker, outsider = _active_people(db, 3)
    delegator = worker if delegation == "self" else outsider
    invalid = [
        {"character_id": lead, "tier": "主办"},
        {"character_id": worker, "tier": "知情", "delegator_id": delegator},
    ]

    if write_path == "create":
        with pytest.raises(ValueError, match="委派人须为同案主办/协办且不得自委派"):
            db.create_decree_dossier(
                state, action_type="assignment", decree_text="命查仓储。",
                target_kind="issue", target_id="granary", participants=invalid,
            )
        assert db.list_decree_dossiers() == []
    else:
        dossier_id = db.create_decree_dossier(
            state, action_type="assignment", decree_text="命查仓储。",
            target_kind="issue", target_id="granary",
            participants=[{"character_id": lead, "tier": "主办"}],
        )
        with pytest.raises(ValueError, match="委派人须为同案主办/协办且不得自委派"):
            db.append_decree_dossier_participants(dossier_id, invalid[1:])
        assert len(db.get_decree_dossier(dossier_id)["participant_roster"]) == 1


def test_dossier_roster_append_keeps_existing_entries_and_delegator(game):
    db, state, _content = game
    people = _active_people(db, 3)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命办西法历书。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": people[0], "tier": "主办", "role": "总理"}],
    )

    db.append_decree_dossier_participants(
        dossier_id,
        [{"character_id": people[1], "tier": "协办", "role": "推算", "delegator_id": people[0]}],
    )
    db.append_decree_dossier_participants(
        dossier_id,
        [{"character_id": people[2], "tier": "知情", "role": "知会"}],
    )

    assert db.get_decree_dossier(dossier_id)["participant_roster"] == [
        {"character_id": people[0], "tier": "主办", "role": "总理", "delegator_id": None},
        {"character_id": people[1], "tier": "协办", "role": "推算", "delegator_id": people[0]},
        {"character_id": people[2], "tier": "知情", "role": "知会", "delegator_id": None},
    ]


def test_dossier_append_is_idempotent_only_for_identical_character_entry(game):
    db, state, _content = game
    lead = _active_minister(db)
    original = {"character_id": lead, "tier": "主办", "role": "总理"}
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar", participants=[original],
    )

    assert db.append_decree_dossier_participants(dossier_id, [original]) == []
    with pytest.raises(ValueError, match="机械档不同"):
        db.append_decree_dossier_participants(
            dossier_id, [{**original, "tier": "协办"}],
        )
    with pytest.raises(ValueError, match="机械档不同"):
        db.append_decree_dossier_participants(
            dossier_id, [
                {"character_id": lead, "tier": "主办", "role": "另职"},
                original,
            ],
        )

    assert db.get_decree_dossier(dossier_id)["participant_roster"] == [{
        **original, "delegator_id": None,
    }]


def test_month_end_extractor_appends_self_dispatched_participant(game):
    db, state, _content = game
    people = _active_people(db, 2)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": people[0], "tier": "主办", "role": "总理"}],
    )

    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_participants": [{
            "dossier_id": dossier_id,
            "character_id": people[1],
            "tier": "协办",
            "role": "推算历法",
            "delegator_id": people[0],
        }],
    }, dossier_ids_at_input={dossier_id})

    assert result["dossier_participants"] == [{
        "dossier_id": dossier_id, "character_id": people[1], "tier": "协办",
    }]
    assert db.get_decree_dossier(dossier_id)["participant_roster"][-1] == {
        "character_id": people[1], "tier": "协办", "role": "推算历法",
        "delegator_id": people[0],
    }


@pytest.mark.parametrize("bad_patch", [
    {"character_id": "", "tier": "协办", "delegator_id": "lead"},
    {"character_id": "worker", "tier": "", "delegator_id": "lead"},
    {"character_id": "worker", "tier": "旁听", "delegator_id": "lead"},
    {"character_id": "worker", "tier": "协办", "delegator_id": ""},
])
def test_month_end_participant_batch_rejects_each_malformed_item(game, bad_patch):
    db, state, _content = game
    lead, worker, good = _active_people(db, 3)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    bad = {key: ({"lead": lead, "worker": worker}.get(value, value))
           for key, value in bad_patch.items()}
    bad["dossier_id"] = dossier_id
    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_participants": [bad, {
            "dossier_id": dossier_id, "character_id": good,
            "tier": "协办", "delegator_id": lead,
        }],
    }, dossier_ids_at_input={dossier_id})

    assert result["dossier_participants"][0]["rejected"] is True
    assert result["dossier_participants"][1]["character_id"] == good
    roster = db.get_decree_dossier(dossier_id)["participant_roster"]
    assert [item["character_id"] for item in roster] == [lead, good]


def test_driver_settle_freezes_dossier_roster_authority_at_input(game, monkeypatch):
    import driver

    db, state, content = game
    lead, worker = _active_people(db, 2)
    visible_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    closed_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="旧案已结。",
        target_kind="issue", target_id="closed-calendar",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    db.conn.execute("UPDATE decree_dossiers SET status='closed' WHERE id=?", (closed_id,))
    secret_order_id = db.create_secret_order(
        state, lead, "密修历", "暗修历书。", [], deadline_months=0,
    )
    secret_id = next(
        row["id"] for row in db.list_decree_dossiers()
        if row["secret_order_id"] == secret_order_id
    )
    created = {}
    real_pre_settle = driver.pre_settle

    def create_during_settle(state_arg, db_arg):
        real_pre_settle(state_arg, db_arg)
        created["id"] = db_arg.create_decree_dossier(
            state_arg, action_type="assignment", decree_text="同批新案。",
            target_kind="issue", target_id="same-batch",
            participants=[{"character_id": lead, "tier": "主办"}],
        )

    monkeypatch.setattr(driver, "pre_settle", create_during_settle)
    real_persist = driver.persist_resolve_context

    def persist_with_same_batch_item(db_arg, turn, extracted, **kwargs):
        extracted["dossier_participants"].append({
            "dossier_id": created["id"], "character_id": worker,
            "tier": "协办", "delegator_id": lead,
        })
        return real_persist(db_arg, turn, extracted, **kwargs)

    monkeypatch.setattr(driver, "persist_resolve_context", persist_with_same_batch_item)
    additions = [
        {"dossier_id": dossier_id, "character_id": worker, "tier": "协办", "delegator_id": lead}
        for dossier_id in (visible_id, closed_id, secret_id)
    ]
    driver.run_settle(db, state, content, {"dossier_participants": additions})

    assert len(db.get_decree_dossier(visible_id)["participant_roster"]) == 2
    assert len(db.get_decree_dossier(closed_id)["participant_roster"]) == 1
    assert len(db.get_decree_dossier(secret_id)["participant_roster"]) == 0
    assert len(db.get_decree_dossier(created["id"])["participant_roster"]) == 1


def test_settlement_replay_uses_only_persisted_dossier_authority(game, monkeypatch):
    import ming_sim.decree as decree

    db, state, content = game
    lead, worker = _active_people(db, 2)
    allowed = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="replay-allowed",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    denied = db.create_decree_dossier(
        state, action_type="assignment", decree_text="未入冻结输入。",
        target_kind="issue", target_id="replay-denied",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    extracted = {"dossier_participants": [
        {"dossier_id": dossier_id, "character_id": worker, "tier": "协办", "delegator_id": lead}
        for dossier_id in (allowed, denied)
    ]}
    decree.pre_settle(state, db)
    db.save_resolve_context(
        state.turn, "", "", {"decree_dossiers": [{"id": allowed}]},
        extracted=extracted,
    )
    ctx = db.get_resolve_context(state.turn)
    monkeypatch.setattr(decree, "create_chapter_memory_agent", lambda *args, **kwargs: None)
    monkeypatch.setattr(decree, "record_chapter_memory", lambda *args, **kwargs: None)

    result = decree.resolve_settling_recovery(
        state, db, None, types.SimpleNamespace(), ctx, content=content,
    )

    assert result.awaiting is False
    assert len(db.get_decree_dossier(allowed)["participant_roster"]) == 2
    assert len(db.get_decree_dossier(denied)["participant_roster"]) == 1


def test_driver_crash_persists_frozen_dossier_authority_for_replay(game, monkeypatch):
    import driver
    import ming_sim.decree as decree

    db, state, content = game
    lead, worker = _active_people(db, 2)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    delta = {"dossier_participants": [{
        "dossier_id": dossier_id, "character_id": worker,
        "tier": "协办", "delegator_id": lead,
    }]}
    monkeypatch.setattr(
        driver, "settle_with_delta",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("crash after ready")),
    )

    with pytest.raises(RuntimeError, match="crash after ready"):
        driver.run_settle(db, state, content, delta)

    ctx = db.get_resolve_context(state.turn)
    assert ctx["simulator_payload"]["decree_dossiers"] == [{"id": dossier_id}]
    monkeypatch.setattr(decree, "create_chapter_memory_agent", lambda *args, **kwargs: None)
    monkeypatch.setattr(decree, "record_chapter_memory", lambda *args, **kwargs: None)
    result = decree.resolve_settling_recovery(
        state, db, None, types.SimpleNamespace(), ctx, content=content,
    )
    assert result.awaiting is False
    assert len(db.get_decree_dossier(dossier_id)["participant_roster"]) == 2


@pytest.mark.parametrize("authority", [None, set()])
def test_extractor_never_reconstructs_missing_dossier_authority_from_live_db(
    game, authority,
):
    db, state, _content = game
    lead, worker = _active_people(db, 2)
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="命修历。",
        target_kind="issue", target_id="calendar",
        participants=[{"character_id": lead, "tier": "主办"}],
    )

    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_participants": [{
            "dossier_id": dossier_id, "character_id": worker,
            "tier": "协办", "delegator_id": lead,
        }],
    }, dossier_ids_at_input=authority)

    assert result["dossier_participants"][0]["rejected"] is True
    assert len(db.get_decree_dossier(dossier_id)["participant_roster"]) == 1


def test_committing_each_directive_creates_independent_restoreable_dossier(game):
    db, state, _content = game
    minister = _active_minister(db)
    ids = [
        db.stage_directive_candidate(
            state.turn, minister, {
                "text": text, "actor": minister,
                "dossier_action_type": "policy",
                "target_kind": "issue", "target_id": target,
            }
        )
        for text, target in (
            ("着户部清核辽饷。", "liao-pay"),
            ("着兵部点验军械。", "arsenal"),
        )
    ]

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=ids, directive_status="draft"
    )

    dossiers = db.list_decree_dossiers(status="proposed")
    assert [row["decree_text"] for row in dossiers[-2:]] == [
        "着户部清核辽饷。",
        "着兵部点验军械。",
    ]
    assert len({row["id"] for row in dossiers[-2:]}) == 2
    assert all(row["pending_action_id"] in ids for row in dossiers[-2:])


def test_explicit_directive_without_extractor_payload_becomes_narrative_dossier(game):
    db, state, content = game
    minister = _active_minister(db)

    candidate_id = db.stage_explicit_directive(
        state.turn, minister, "着有司清核河工。",
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[candidate_id],
    )

    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == candidate_id
    )
    assert dossier["action_type"] == "special_decree"
    assert dossier["target_kind"] == "policy"
    assert dossier["target_id"] == f"pending-directive:{candidate_id}"


def test_pending_directive_only_enters_settlement_after_final_approval(game):
    db, state, content = game
    minister = _active_minister(db)
    before = state.metrics["国库"]

    rejected_candidate_id = db.stage_directive_candidate(
        state.turn, minister, {
            "text": "拟拨十两赈济", "actor": minister,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief-rejected",
            "amount": 10, "account": "国库",
            "execution_surface": "immediate",
        },
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[rejected_candidate_id],
        directive_status="pending",
    )
    rejected_directive_id = int(db.conn.execute(
        "SELECT committed_directive_id FROM pending_actions WHERE id=?",
        (rejected_candidate_id,),
    ).fetchone()["committed_directive_id"])

    assert db.get_dossier_for_directive(rejected_directive_id) is None
    assert db.list_decree_dossiers_for_simulation(state.turn) == []
    db.reject_directive(rejected_directive_id)
    assert db.get_dossier_for_directive(rejected_directive_id) is None
    assert db.list_decree_dossiers_for_simulation(state.turn) == []
    assert state.metrics["国库"] == before

    approved_candidate_id = db.stage_directive_candidate(
        state.turn, minister, {
            "text": "准拨十两赈济", "actor": minister,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief-approved",
            "amount": 10, "account": "国库",
            "execution_surface": "immediate",
        },
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[approved_candidate_id],
        directive_status="pending",
    )
    approved_directive_id = int(db.conn.execute(
        "SELECT committed_directive_id FROM pending_actions WHERE id=?",
        (approved_candidate_id,),
    ).fetchone()["committed_directive_id"])
    db.confirm_directive(approved_directive_id, state)

    dossier = db.get_dossier_for_directive(approved_directive_id)
    assert [row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)] == [
        dossier["id"],
    ]
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
    )
    assert state.metrics["国库"] == before - 10


def test_secret_pending_action_carries_chat_turn_and_pending_provenance(game):
    db, state, content = game
    minister = _active_minister(db)
    chat_turn_id = db.create_chat_turn(state, minister, "session-571", 0)
    message_id = db.conn.execute(
        """
        INSERT INTO chat_messages (minister_name,turn,role,content)
        VALUES (?,?,'user','卿暗中核清关宁军饷')
        """,
        (minister, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_turn_id, user_message_id=int(message_id))

    pending_id = db.stage_pending_action(
        state.turn,
        kind="secret_order",
        action="新建",
        minister_name=minister,
        payload={
            "title": "密查饷银",
            "content": "暗中核清关宁军饷",
            "assignee": minister,
            "origin_chat_message_id": int(message_id),
        },
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id]
    )

    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["pending_action_id"] == pending_id
    assert dossier["source_chat_turn_id"] == chat_turn_id
    assert dossier["executor_kind"] == "character"
    assert dossier["executor_id"] == minister
    assert dossier["decree_text"] == "暗中核清关宁军饷"


def test_terminal_target_does_not_interrupt_another_executor(game):
    db, state, _content = game
    people = _active_people(db, 2)
    target, executor = people
    dossier_id = db.create_decree_dossier(
        state, action_type="punishment", decree_text="命查其罪",
        target_kind="character", target_id=target,
        executor_kind="character", executor_id=executor,
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    db.set_character_status(state, target, "imprisoned", reason="下狱")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "executing"
    assert dossier["participant_roster"] == []


def test_office_action_waits_for_verdict_then_materializes_from_same_payload(game):
    db, state, content = game
    minister = _active_minister(db)
    pending_id = db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=minister,
        target_id=None,
        payload={"name": minister, "office": "兵部主事"},
    )

    before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"]
    db.commit_pending_actions(state, content=content, registry=None)

    dossier = next(
        row for row in db.list_decree_dossiers(target_kind="character", target_id=minister)
        if row["pending_action_id"] == pending_id
    )
    assert dossier["status"] == "proposed"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"] == before

    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content, registry=None
    )
    dossier = db.get_decree_dossier(dossier["id"])
    assert dossier["status"] == "executing"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,)
    ).fetchone()["office"] == "兵部主事"


@pytest.mark.parametrize("status", ("executing", "closed"))
def test_dossier_cannot_start_in_execution_state(game, status):
    db, state, _content = game
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type="appointment", decree_text="非法初态",
            target_kind="character", target_id="invalid",
            status=status,
        )


def test_secret_order_and_dossier_roll_back_as_one_unit(game, monkeypatch):
    db, state, _content = game
    minister = _active_minister(db)

    def fail_dossier(*_args, **_kwargs):
        raise RuntimeError("dossier write failed")

    monkeypatch.setattr(db, "create_decree_dossier", fail_dossier)
    with pytest.raises(RuntimeError):
        db.create_secret_order(state, minister, "密查", "查账", [])
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 0


def test_character_terminal_state_closes_secret_order_and_execution_slot(game):
    db, state, _content = game
    minister = _active_minister(db)
    order_id = db.create_secret_order(state, minister, "密查", "查账", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    db.transition_decree_dossier(dossier["id"], "executing")

    db.set_character_status(state, minister, "imprisoned", reason="下狱")

    order = db.get_secret_order(order_id)
    dossier = db.get_dossier_for_secret_order(order_id)
    assert order["status"] == "failed"
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    assert dossier["closed_turn"] == state.turn
    assert dossier["interruption_reason"]


def test_commitments_bind_explicitly_when_multiple_dossiers_share_a_turn(game):
    db, state, content = game
    first_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月赈济灾民",
        target_kind="issue", target_id="relief",
    )
    second_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="今后每月修河",
        target_kind="issue", target_id="river-works",
    )
    db.apply_dossier_verdicts(state, [
        {"dossier_id": first_id, "decision": "promulgated"},
        {"dossier_id": second_id, "decision": "promulgated"},
    ])

    issue_engine.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{second_id}",
                "kind": "initiative",
                "title": "每月赈济",
                "end_turn": state.turn + 2,
                "commitment_kind": "until_stop",
            }],
        },
        content=content,
    )

    commitments = db.list_commitments_for_dossier(second_id)
    assert len(commitments) == 1
    assert commitments[0]["origin_ref"] == f"dossier:{second_id}"
    assert db.list_commitments_for_dossier(first_id) == []


def test_allocation_rejected_is_zero_effect_and_force_promulgation_keeps_rejection(game):
    db, state, _content = game
    before = state.metrics["国库"]
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨国库十两赈济",
        target_kind="issue", target_id="relief",
        payload={
            "account": "国库", "amount": 10, "category": "赈济",
            "reason": "奉旨赈济", "execution_surface": "immediate",
        },
    )
    db.apply_dossier_verdicts(
        state, [_rejected_verdict(dossier_id)]
    )
    assert state.metrics["国库"] == before
    rejected = db.get_decree_dossier(dossier_id)
    assert rejected["promulgation_blocked_layer"] == "six_offices"
    assert rejected["promulgation_reason"] == "科臣封驳。"

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "force_promulgated"}]
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == before - 10
    assert dossier["status"] == "closed"
    assert dossier["promulgation_decision"] == "rejected"
    moves = db.list_economy_moves_for_dossier(dossier_id)
    assert len(moves) == 1
    assert moves[0]["dossier_id"] is None
    assert moves[0]["origin_ref"] == f"dossier:{dossier_id}"


def test_assignment_promulgation_tracks_executor_until_terminal_state(game):
    db, state, content = game
    assignee = _active_minister(db)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=assignee,
        payload={
            "text": "着其查核仓场", "actor": assignee,
            "dossier_action_type": "assignment",
            "assignee": assignee, "target_kind": "issue", "target_id": "warehouse",
        },
    )
    db.commit_pending_actions(state, content=content)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["action_type"] == "assignment"
    assert dossier["executor_id"] == assignee

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"

    db.set_character_status(state, assignee, "dead", reason="病故")
    assert db.get_decree_dossier(dossier["id"])["status"] == "closed"


@pytest.mark.parametrize("entry", ("pending_commit", "confirm"))
@pytest.mark.parametrize(
    ("action_type", "expected_executor_kind"),
    (("military_order", "character"), ("policy", "")),
)
def test_directive_assignee_projects_to_executor_only_for_executable_types(
    game, entry, action_type, expected_executor_kind,
):
    db, state, content = game
    assignee = _active_minister(db)
    assignee_input = assignee
    if action_type == "military_order":
        active_names = {
            str(row["name"]) for row in db.conn.execute(
                "SELECT name FROM characters WHERE status='active'"
            ).fetchall()
        }
        character, alias = next(
            (character, alias)
            for character in content.characters.values()
            if character.name in active_names
            for alias in character.aliases
            if alias != character.name
        )
        assignee = character.name
        assignee_input = alias
    candidate_id = db.stage_directive_candidate(
        state.turn,
        assignee,
        {
            "text": "命兵部整饬边备",
            "actor": assignee,
            "dossier_action_type": action_type,
            "target_kind": "issue",
            "target_id": f"executor-{entry}-{action_type}",
            "assignee": assignee_input,
            "deadline_months": 3,
        },
    )
    db.commit_pending_actions(
        state,
        content=content,
        action_ids=[candidate_id],
        directive_status="pending" if entry == "confirm" else "draft",
    )
    directive_id = int(db.conn.execute(
        "SELECT committed_directive_id FROM pending_actions WHERE id=?",
        (candidate_id,),
    ).fetchone()["committed_directive_id"])
    if entry == "confirm":
        db.confirm_directive(directive_id, state)

    dossier = db.get_dossier_for_directive(directive_id)
    assert dossier["executor_kind"] == expected_executor_kind
    assert dossier["executor_id"] == (assignee if expected_executor_kind else "")

    if action_type == "military_order":
        db.apply_dossier_verdicts(
            state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
            content=content,
        )
        assert db.get_decree_dossier(dossier["id"])["status"] == "executing"
        terminal_status = "dead" if entry == "pending_commit" else "dismissed"
        db.set_character_status(state, assignee, terminal_status, reason="人物终态")
        assert db.get_decree_dossier(dossier["id"])["status"] == "closed"


def test_real_resolve_entry_applies_promulgation_verdict_and_payload_effect(
    game, monkeypatch,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    published_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="本月已颁之旨",
        target_kind="issue", target_id="published-policy",
    )
    db.record_dossier_decision(published_id, "promulgated")
    secret_order_id = db.create_secret_order(
        state, actor, "密查军饷", "暗中核清关宁军饷", [],
    )
    secret_dossier_id = db.get_dossier_for_secret_order(secret_order_id)["id"]
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={
            "text": "拨国库十两赈济",
            "actor": actor,
                "dossier_action_type": "grant_allocation",
                "target_kind": "issue",
                "target_id": "relief",
                "account": "国库",
            "amount": 10,
            "category": "赈济",
        },
    )
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=actor,
        payload={
            "text": "拟拨国库二十两修堤",
            "actor": actor,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue",
            "target_id": "dyke-repair",
            "account": "国库",
            "amount": 20,
            "category": "河工",
        },
    )
    seen = {}

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _promulgation_verdicts(dossiers, _state):
        return [
            ({"dossier_id": row["id"], "decision": "promulgated"}
             if row["target_id"] == "relief" else _rejected_verdict(row["id"]))
            for row in dossiers
        ]

    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            seen.setdefault("payload", k["simulator_payload"]) and "本月奉旨赈济。",
            k["simulator_payload"],
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "不应作为真源",
        content=content,
        promulgation_verdict_provider=_promulgation_verdicts,
    )
    assert result.awaiting is True
    decision = result.decisions[0]
    withdraw = next(
        option for option in decision["options"] if option["label"] == "收回"
    )
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?,status='decided' WHERE turn=? AND idx=?",
        (json.dumps(withdraw, ensure_ascii=False), state.turn, decision["idx"]),
    )
    db.conn.commit()
    decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )

    staged, rejected = [
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] > 0
    ]
    # Narrative-owned policy reaches the simulator; payload-owned allocation
    # is consumed only by the deterministic post-verdict dispatcher.
    assert [row["id"] for row in seen["payload"]["decree_dossiers"]] == [
        published_id,
    ]
    db.update_secret_order_progress(
        secret_order_id, "密查仍在推进", state.year, state.period,
    )
    assert db.get_decree_dossier(secret_dossier_id)["status"] == "executing"
    assert seen["payload"]["decree_text"] == "本月已颁之旨"
    assert all(
        "settlement_verdict" not in row
        for row in seen["payload"]["decree_dossiers"]
    )
    assert db.get_decree_dossier(staged["id"])["status"] == "executing"
    assert db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE origin_ref=?",
        (f"dossier:{staged['id']}",),
    ).fetchone()["delta"] == -10
    assert db.get_decree_dossier(rejected["id"])["status"] == "closed"
    assert db.get_decree_dossier(rejected["id"])["promulgation_decision"] == "rejected"
    assert db.conn.execute(
        "SELECT 1 FROM economy_ledger WHERE dossier_id=?",
        (rejected["id"],),
    ).fetchone() is None

    from ming_sim.db import GameDB
    reopened = GameDB(db.path, content=content)
    try:
        audit = next(
            row for row in reopened.list_decree_dossier_decisions(rejected["id"])
            if row["decision"] == "rejected"
        )
        expected = _rejected_verdict(rejected["id"])
        assert audit["primary_opponents"] == expected["primary_opponents"]
        assert audit["gatekeeper_id"] is None
        assert audit["criteria_snapshot"] == expected["criteria_snapshot"]
        assert audit["affected_parties"] == expected["affected_parties"]
        assert audit["midzhi_unpromulgatable"] is False
    finally:
        reopened.close()


def test_real_resolve_entry_without_pending_dossiers_skips_promulgation_llm(
    game, monkeypatch,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    monkeypatch.setattr(
        decree_mod,
        "stub_promulgation_verdicts",
        lambda *a, **k: pytest.fail("无待判案卷不得调用颁布判决 seam"),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )

    assert result.awaiting is False
    assert state.turn == 2


@pytest.mark.parametrize(
    ("choice_label", "expected_status", "expected_delta"),
    (
        ("强颁", "closed", -10),
        ("收回", "closed", 0),
        ("留中", "proposed", 0),
    ),
)
def test_rejected_dossier_uses_player_rescript_choice_and_resume(
    game, monkeypatch, choice_label, expected_status, expected_delta,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    candidate_id = db.stage_directive_candidate(
        state.turn, actor, {
            "text": "拨国库十两赈济", "actor": actor,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "rescript-relief",
            "account": "国库", "amount": 10, "execution_surface": "immediate",
        },
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[candidate_id],
    )
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == candidate_id
    )

    monkeypatch.setattr(
        decree_mod, "stub_promulgation_verdicts",
        lambda _dossiers, _state: [
            _rejected_verdict(dossier["id"]) if state.turn == 1 else
            {"dossier_id": dossier["id"], "decision": "promulgated"}
        ],
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("本月邸报。", k["simulator_payload"]),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "拨帑赈济", content=content,
    )
    assert result.awaiting is True
    decision = result.decisions[0]
    choice = next(
        option for option in decision["options"]
        if option["label"] == choice_label
    )
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?,status='decided' WHERE turn=? AND idx=?",
        (json.dumps(choice, ensure_ascii=False), state.turn, decision["idx"]),
    )
    db.conn.commit()

    decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )

    restored = db.get_decree_dossier(dossier["id"])
    assert restored["status"] == expected_status
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert sum(int(move["delta"]) for move in moves) == expected_delta
    if choice_label == "留中":
        assert restored["held_turn"] == 1
        assert restored["rescript_pending"] is False
        assert dossier["id"] in {
            row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
        }
        rejudged = decree_mod.resolve_directives(
            state, db, None, None, [object()], "留中重判", content=content,
        )
        assert rejudged.awaiting is False
        assert db.get_decree_dossier(dossier["id"])["status"] == "closed"
        assert sum(
            int(move["delta"])
            for move in db.list_economy_moves_for_dossier(dossier["id"])
        ) == -10


def test_rejected_dossier_survives_simulator_failure_on_rescript_rail(
    game, monkeypatch,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    candidate_id = db.stage_directive_candidate(
        state.turn, actor, {
            "text": "拨国库十两赈济", "actor": actor,
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "failed-simulator-relief",
            "account": "国库", "amount": 10, "execution_surface": "immediate",
        },
    )
    db.commit_pending_actions(state, content=content, action_ids=[candidate_id])
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == candidate_id
    )

    monkeypatch.setattr(
        decree_mod, "stub_promulgation_verdicts",
        lambda _dossiers, _state: [_rejected_verdict(dossier["id"])],
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _fail_simulator(*args, **kwargs):
        raise RuntimeError("simulator unavailable")

    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload", _fail_simulator,
    )

    turn = state.turn
    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "拨帑赈济", content=content,
    )

    assert result.awaiting is True
    assert state.turn == turn
    assert state.turn_phase == "awaiting_decision"
    assert db.get_resolve_context(turn) is not None
    assert [option["label"] for option in result.decisions[0]["options"]] == [
        "强颁", "收回", "留中",
    ]

    withdraw = result.decisions[0]["options"][1]
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?,status='decided' "
        "WHERE turn=? AND idx=?",
        (json.dumps(withdraw, ensure_ascii=False), turn, result.decisions[0]["idx"]),
    )
    db.conn.commit()
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )

    resolved = db.get_decree_dossier(dossier["id"])
    assert state.turn == turn + 1
    assert resolved["status"] == "closed"
    assert resolved["promulgation_decision"] == "rejected"
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []


def test_rejected_narrative_dossier_is_not_an_executable_or_extractor_origin(
    game, monkeypatch,
):
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    ids = [
        db.stage_directive_candidate(
            state.turn, actor, {
                "text": text,
                "actor": actor,
                "dossier_action_type": "policy",
                "target_kind": "issue",
                "target_id": target,
            },
        )
        for text, target in (
            ("此道改革已被打回", "rejected-reform"),
            ("此道新政准予施行", "promulgated-policy"),
        )
    ]
    db.commit_pending_actions(state, content=content, action_ids=ids)
    rejected, promulgated = [
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] in ids
    ]
    raw_decree = "此道改革已被打回\n此道新政准予施行"
    seen = {}

    monkeypatch.setattr(
        decree_mod, "stub_promulgation_verdicts",
        lambda _dossiers, _state: [
            _rejected_verdict(rejected["id"]),
            {"dossier_id": promulgated["id"], "decision": "promulgated"},
        ],
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            seen.setdefault("payload", k["simulator_payload"]) and "本月邸报。",
            k["simulator_payload"],
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    original_build_context = decree_mod.build_extractor_shared_context

    def _capture_context(*args, **kwargs):
        context = original_build_context(*args, **kwargs)
        seen.setdefault("extractor_contexts", []).append(context)
        return context

    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", _capture_context)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )

    def _extract(*args, **kwargs):
        seen["extractor_decree_text"] = kwargs["decree_text"]
        leaked = "此道改革已被打回" in kwargs["decree_text"] or any(
            "此道改革已被打回" in context
            for context in seen["extractor_contexts"]
        )
        moves = [
            {
                "account": "国库", "delta": -13,
                "category": "被打回改革不得生效",
                "origin_ref": f"dossier:{rejected['id']}",
            },
            {
                "account": "国库", "delta": -7,
                "category": "已颁新政合法生效",
                "origin_ref": f"dossier:{promulgated['id']}",
            },
        ]
        if leaked:
            moves.append({
                "account": "国库", "delta": -19,
                "category": "无案卷来源的打回拨款旁路",
            })
        return {"economy_moves": moves}, "", ""

    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno", _extract,
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], raw_decree, content=content,
    )

    assert result.awaiting is True
    assert seen["payload"]["decree_text"] == "此道新政准予施行"
    assert [row["id"] for row in seen["payload"]["decree_dossiers"]] == [
        promulgated["id"],
    ]
    assert db.get_resolve_context(state.turn)["decree_text"] == raw_decree
    withdraw = next(
        option for option in result.decisions[0]["options"]
        if option["label"] == "收回"
    )
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?,status='decided' "
        "WHERE turn=? AND idx=?",
        (
            json.dumps(withdraw, ensure_ascii=False),
            state.turn,
            result.decisions[0]["idx"],
        ),
    )
    db.conn.commit()

    decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )

    assert seen["extractor_decree_text"] == "此道新政准予施行"
    assert all(
        "此道改革已被打回" not in context
        for context in seen["extractor_contexts"]
    )
    applied = {
        str(row["category"]): int(row["delta"])
        for row in db.conn.execute(
            "SELECT category,delta FROM economy_ledger WHERE category IN (?,?,?)",
            (
                "被打回改革不得生效", "已颁新政合法生效",
                "无案卷来源的打回拨款旁路",
            ),
        ).fetchall()
    }
    assert applied == {"已颁新政合法生效": -7}


@pytest.mark.parametrize("invalid_id", [True, 1.5, "1.5", 2 ** 63])
def test_dossier_execution_rejects_non_sqlite_integer_ids(game, invalid_id):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="奉旨办理",
        target_kind="issue", target_id="strict-execution-id",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_executions": [{
            "dossier_id": invalid_id, "outcome": "fulfilled", "note": "办理完毕",
        }],
    }, content=content)

    assert result["dossier_executions"][0]["rejected"] is True
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"


def test_dossier_execution_accepts_sqlite_integer_id(game):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="奉旨办理",
        target_kind="issue", target_id="valid-execution-id",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_executions": [{
            "dossier_id": dossier_id, "outcome": "fulfilled", "note": "办理完毕",
        }],
    }, content=content)

    assert result["dossier_executions"] == [{
        "dossier_id": dossier_id, "outcome": "fulfilled",
    }]
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"


def test_structured_dossier_origin_deduplicates_extractor_but_narrative_applies(game):
    db, state, content = game
    before = state.metrics["国库"]
    structured_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨十两赈济",
        target_kind="issue",
        target_id="structured-relief",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "immediate",
        },
    )
    narrative_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="兴修水利",
        target_kind="issue",
        target_id="narrative-irrigation",
    )
    db.apply_dossier_promulgation(
        state, structured_id, "promulgated", content=content,
    )
    db.apply_dossier_promulgation(
        state, narrative_id, "promulgated", content=content,
    )

    issue_engine.apply_score_extraction(
        db, state, {
            "economy_moves": [
                {
                    "account": "国库", "delta": -10, "category": "重复拨帑",
                    "origin_ref": f"dossier:{structured_id}",
                },
                {
                    "account": "国库", "delta": -5, "category": "水利涌现",
                    "origin_ref": f"dossier:{narrative_id}",
                },
            ],
        }, content=content,
    )

    assert state.metrics["国库"] == before - 15
    assert len(db.list_economy_moves_for_dossier(structured_id)) == 1


def test_payload_owned_appointment_dedup_removes_only_exact_mechanical_effect(game):
    db, state, content = game
    person = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' LIMIT 1"
    ).fetchone()
    dossier_id = db.create_decree_dossier(
        state,
        action_type="appointment",
        decree_text="授官",
        target_kind="person",
        target_id=person["name"],
        payload={
            "_minister_name": person["name"],
            "_office_action": "任命",
            "office": "兵部尚书",
            "office_type": "central",
        },
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    result = issue_engine.apply_score_extraction(db, state, {
        "人物变更": [{
            "name": person["name"], "动作": "调任", "office": "兵部尚书",
            "office_type": "central", "任别": "真除",
            "origin_ref": f"dossier:{dossier_id}",
        }],
    }, content=content)

    assert result["applied_person_changes"] == []


def test_payload_owned_appointment_dedup_uses_prior_item_runtime_office_type(game):
    db, state, content = game
    person = db.conn.execute(
        "SELECT name FROM characters "
        "WHERE status='active' AND office_type != '地方' LIMIT 1"
    ).fetchone()
    dossier_id = db.create_decree_dossier(
        state,
        action_type="appointment",
        decree_text="授未知官",
        target_kind="person",
        target_id=person["name"],
        payload={
            "_minister_name": person["name"],
            "_office_action": "任命",
            "office": "同名未知官",
            "office_type": "地方",
        },
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    result = issue_engine.apply_score_extraction(db, state, {
        "人物变更": [
            {
                "name": person["name"], "动作": "调任", "office": "前置异官",
                "office_type": "地方", "任别": "真除",
                "origin_ref": f"dossier:{dossier_id}",
            },
            {
                "name": person["name"], "动作": "调任", "office": "同名未知官",
                "任别": "真除", "origin_ref": f"dossier:{dossier_id}",
            },
        ],
    }, content=content)

    assert [item["new_office"] for item in result["applied_person_changes"]] == ["前置异官"]
    assert content.characters[person["name"]].office == "前置异官"
    assert content.characters[person["name"]].office_type == "地方"
    persisted = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (person["name"],)
    ).fetchone()
    assert (persisted["office"], persisted["office_type"]) == ("前置异官", "地方")


def test_payload_owned_appointment_dedup_preserves_same_person_different_effect(game):
    db, state, content = game
    person = db.conn.execute(
        "SELECT name, loyalty FROM characters WHERE status='active' AND loyalty < 100 LIMIT 1"
    ).fetchone()
    dossier_id = db.create_decree_dossier(
        state,
        action_type="appointment",
        decree_text="授官",
        target_kind="person",
        target_id=person["name"],
        payload={
            "_minister_name": person["name"],
            "_office_action": "任命",
            "name": person["name"],
            "office": "兵部尚书",
        },
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    result = issue_engine.apply_score_extraction(db, state, {
        "人物变更": [{
            "name": person["name"], "动作": "评定", "loyalty": 1,
            "origin_ref": f"dossier:{dossier_id}",
        }],
    }, content=content)

    assert result["applied_person_changes"][0]["动作"] == "评定"
    assert db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (person["name"],)
    ).fetchone()[0] == person["loyalty"] + 1


def test_executing_execution_record_never_closes_or_stamps_closed_turn(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="持续办理",
        target_kind="issue", target_id="ongoing-policy",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    with pytest.raises(ValueError):
        db.record_dossier_execution(
            dossier_id, "executing", "仍在办理", state.turn, close=True,
        )
    db.record_dossier_execution(
        dossier_id, "executing", "仍在办理", state.turn, close=False,
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "executing"
    assert dossier["closed_turn"] == 0


def test_force_promulgated_dossier_authorizes_same_batch_effect_after_execution_close(game):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="强颁赈济",
        target_kind="issue", target_id="forced-relief",
    )
    db.apply_dossier_promulgation(state, dossier_id, "rejected", reason="封驳")
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    before = state.metrics["国库"]

    result = issue_engine.apply_score_extraction(db, state, {
        "dossier_executions": [{
            "dossier_id": dossier_id, "outcome": "fulfilled", "note": "赈济已毕",
        }],
        "economy_moves": [{
            "account": "国库", "delta": -3, "category": "强颁赈济",
            "origin_ref": f"dossier:{dossier_id}",
        }],
    }, content=content)

    assert result["dossier_executions"] == [{
        "dossier_id": dossier_id, "outcome": "fulfilled",
    }]
    assert state.metrics["国库"] == before - 3


def test_extractor_accepts_transformed_execution_outcome(game):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="奉旨办理而借题行私",
        target_kind="issue", target_id="transformed-policy",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")

    result = issue_engine.apply_score_extraction(
        db, state, {"dossier_executions": [{
            "dossier_id": dossier_id,
            "outcome": "transformed",
            "note": "名义奉行，实则借旨行私",
        }]}, content=content,
    )

    assert result["dossier_executions"] == [{
        "dossier_id": dossier_id, "outcome": "transformed",
    }]
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "transformed"


def test_appointment_alias_uses_canonical_dossier_identity(game):
    db, state, content = game
    target = next(
        character for character in content.characters.values()
        if character.aliases and character.name != character.aliases[0]
        and db.conn.execute(
            "SELECT 1 FROM characters WHERE name=? AND status='active'",
            (character.name,),
        ).fetchone()
    )
    alias = target.aliases[0]
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=_active_minister(db), target_id=None,
        payload={"name": alias, "office": "兵部主事"},
    )
    db.commit_pending_actions(state, content=content, registry=None)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    assert dossier["target_id"] == target.name
    assert dossier["executor_id"] == target.name
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content, registry=None,
    )
    assert [
        row["dossier_id"]
        for row in db.list_office_effects_for_dossier(dossier["id"])
    ] == [dossier["id"]]
    db.record_dossier_execution(
        dossier["id"], "fulfilled", "任事已毕", state.turn,
    )
    assert db.get_decree_dossier(dossier["id"])["status"] == "closed"


@pytest.mark.parametrize(
    ("entry", "case", "model_fields"),
    (
        ("web", "allocation", {
            "动作类型": "grant_allocation", "目标类型": "issue",
            "目标ID": "relief", "金额": 30000, "账户": "内库",
            "执行面": "immediate",
        }),
        ("cli", "authorization", {
            "动作类型": "secret_authorization", "目标类型": "character",
            "授权ID": "理财",
        }),
        ("web", "controlled_verb", {
            "动作类型": "secret_investigation", "目标类型": "issue",
            "目标ID": "granary-corruption",
        }),
        ("cli", "controlled_verb", {
            "动作类型": "protection", "目标类型": "character",
        }),
        ("cli", "dismiss", {"动作类型": "dismiss_assignment"}),
        ("web", "dismiss", {"动作类型": "dismiss_assignment"}),
    ),
)
def test_manual_directive_capture_reaches_structured_dossier(
    game, monkeypatch, entry, case, model_fields,
):
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    actor = _active_minister(db)
    active = {row["name"] for row in db.conn.execute(
        "SELECT name FROM characters WHERE status='active'"
    ).fetchall()}
    aliased = next(ch for ch in content.characters.values()
                   if ch.name in active and ch.aliases)
    response = {
        "拟旨意图": "拟旨", **model_fields,
        "参与人": [{"character_id": aliased.aliases[0], "tier": "主办"}],
    }
    if case == "authorization" or model_fields.get("动作类型") == "protection":
        response.update({"目标ID": actor, "承办人": actor})
    elif case == "dismiss":
        response.update({"目标类型": "character", "目标ID": actor})
    directive_text = "着内库拨银三万两赈灾" if case == "allocation" else "手工旨意"

    def prompt_faithful_backend(prompt, *_args, **_kwargs):
        emperor = prompt.split("【皇帝】", 1)[1].split("【大臣回话】", 1)[0]
        if "请据此拟旨" not in emperor or directive_text not in emperor:
            return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", prompt_faithful_backend)
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    if entry == "web":
        import web_app

        web_game = types.SimpleNamespace(
            db=db, state=state, content=content, session=session,
            directive_rows=lambda: db.list_directives(
                state, statuses=("pending", "draft"),
            ),
            directive_payload=lambda row: dict(row),
        )
        monkeypatch.setattr(web_app, "get_game", lambda: web_game)
        result = asyncio.run(web_app.api_create_directive(
            web_app.DirectiveRequest(text=directive_text),
        ))
        directive_id = int(result["directive"]["id"])
    else:
        payload = cli_backend.capture_manual_directive_payload(
            directive_text, None, db=db, content=content,
        )
        directive_id = session.add_directive(
            directive_text, dossier_payload=payload,
        ).id
    account = "内库" if case == "allocation" else "国库"
    before = state.metrics[account]

    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    assert dossier["decree_text"] == directive_text
    assert dossier["target_id"]
    assert dossier["participant_roster"][0]["character_id"] == aliased.name
    if case == "controlled_verb":
        assert dossier["action_type"] in {"secret_investigation", "protection"}
        if dossier["action_type"] == "secret_investigation":
            assert dossier["target_id"] == "granary-corruption"
        db.apply_dossier_promulgation(state, dossier["id"], "promulgated")
        assert db.get_decree_dossier(dossier["id"])["status"] == "executing"
        assert db.get_decree_dossier(dossier["id"])["execution_outcome"] == ""
        return

    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content,
    )
    if case == "allocation":
        payload = json.loads(dossier["payload_json"])
        assert (dossier["action_type"], payload["amount"], payload["account"]) == (
            "grant_allocation", 30000, "内库",
        )
        assert state.metrics["内库"] == 0
        assert db.list_economy_moves_for_dossier(dossier["id"])[0]["delta"] == -before
    elif case == "dismiss":
        assert json.loads(dossier["payload_json"])["name"] == actor
        row = db.conn.execute(
            "SELECT status,office FROM characters WHERE name=?", (actor,),
        ).fetchone()
        assert (row["status"], row["office"]) == ("dismissed", "")
    else:
        assert "理财" in db.active_skill_grants(actor)
        assert db.list_skill_grants_for_dossier(dossier["id"])[0]["dossier_id"] == dossier["id"]


@pytest.mark.parametrize(("entry", "bad_roster"), [
    ("web", ["韩阁老"]),
    ("cli", [{"tier": "主办"}]),
    ("cli", {"character_id": "韩阁老", "tier": "主办"}),
])
def test_manual_directive_capture_rejects_malformed_roster(
    game, monkeypatch, capsys, entry, bad_roster,
):
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    response = {
        "拟旨意图": "拟旨", "动作类型": "assignment",
        "目标类型": "issue", "目标ID": "granary-audit",
        "参与人": bad_roster,
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content

    if entry == "web":
        import web_app
        from fastapi import HTTPException

        web_game = types.SimpleNamespace(
            db=db, state=state, content=content, session=session,
            directive_rows=lambda: db.list_directives(
                state, statuses=("pending", "draft"),
            ),
            directive_payload=lambda row: dict(row),
        )
        monkeypatch.setattr(web_app, "get_game", lambda: web_game)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(web_app.api_create_directive(
                web_app.DirectiveRequest(text="手工旨意"),
            ))
        assert exc_info.value.status_code == 409
        assert "参与人" in str(exc_info.value.detail)
    else:
        import ming_sim.cli.terminal as terminal

        answers = iter(["add", "手工旨意", "back"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
        assert terminal.review_directives(session) == "back"
        assert "参与人" in capsys.readouterr().out

    assert db.list_pending_actions(state.turn) == []
    assert db.list_directives(state) == []
    assert db.list_decree_dossiers() == []


@pytest.mark.parametrize(("entry", "tier"), [
    ("web", None),
    ("cli", ""),
    ("web", "旁听"),
])
def test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes(
    game, monkeypatch, entry, tier,
):
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    participant = _active_minister(db)
    roster_item = {"character_id": participant}
    if tier is not None:
        roster_item["tier"] = tier
    response = {
        "拟旨意图": "拟旨", "动作类型": "assignment",
        "目标类型": "issue", "目标ID": "granary-audit",
        "参与人": [roster_item],
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content

    if entry == "web":
        import web_app
        from fastapi import HTTPException

        web_game = types.SimpleNamespace(
            db=db, state=state, content=content, session=session,
            directive_rows=lambda: db.list_directives(
                state, statuses=("pending", "draft"),
            ),
            directive_payload=lambda row: dict(row),
        )
        monkeypatch.setattr(web_app, "get_game", lambda: web_game)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(web_app.api_create_directive(
                web_app.DirectiveRequest(text="手工旨意"),
            ))
        assert exc_info.value.status_code == 409
        assert "参与人" in str(exc_info.value.detail)
    else:
        with pytest.raises(ValueError, match="参与人"):
            payload = cli_backend.capture_manual_directive_payload(
                "手工旨意", None, db=db, content=content,
            )
            session.add_directive("手工旨意", dossier_payload=payload)

    assert db.list_pending_actions(state.turn) == []
    assert db.list_directives(state) == []
    assert db.list_decree_dossiers() == []


def test_final_decree_edit_cannot_bypass_frozen_dossier(game):
    from ming_sim.session import GameSession

    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "拨十两赈济", "手动新增",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief",
            "amount": 10, "account": "国库",
            "execution_surface": "immediate",
        },
    )
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state

    with pytest.raises(ValueError, match="逐道旨意入口"):
        session.set_decree("不再拨款")
    assert db.get_dossier_for_directive(directive_id) is None
    assert db.list_directives(state)[0]["text"] == "拨十两赈济"

    db.delete_directive(directive_id)
    with pytest.raises(ValueError, match="逐道旨意入口"):
        session.set_decree("孤立聚合正文")
    assert not getattr(session, "last_decree", "")


def test_cli_dossiered_directive_is_not_listed_editable_or_deletable(
    game, monkeypatch, capsys,
):
    import ming_sim.cli.terminal as terminal
    from ming_sim.session import GameSession

    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "着修河工", "手动新增",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "river-works",
        },
    )
    db.ensure_dossiers_for_draft_directives(state)
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.enter_review = lambda: None
    session.back_to_summoning = lambda: None
    answers = iter([f"edit {directive_id}", f"del {directive_id}", "back"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert session.list_directives() == []
    assert terminal.review_directives(session) == "back"
    assert capsys.readouterr().out.count("没有这条草案。") == 2
    assert db.get_dossier_for_directive(directive_id) is not None
    assert db.list_directives(state)[0]["text"] == "着修河工"


def test_cli_no_edict_route_rejudges_held_proposed_dossier(game):
    from ming_sim.session import GameSession

    db, state, _content = game
    db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    called = []
    session.resolve_turn = lambda: called.append("resolve")

    session.advance_without_decree()

    assert called == ["resolve"]


def test_cli_edit_replaces_text_and_mechanics_before_promulgation(game, monkeypatch):
    import ming_sim.cli.terminal as terminal
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    directive = session.add_directive(
        "拨十两赈济",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue",
            "target_id": "relief",
            "amount": 10,
            "account": "国库",
            "execution_surface": "immediate",
            "mode": "midzhi",
        },
    )
    revised_text = "改拨二十五两赈济"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "grant_allocation",
        "目标类型": "issue",
        "目标ID": "relief",
        "金额": 25,
        "账户": "国库",
        "执行面": "immediate",
        "颁布方式": "普通",
    }
    prompts = []

    def prompt_faithful_backend(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        emperor = prompt.split("【皇帝】", 1)[1].split("【大臣回话】", 1)[0]
        if "请据此拟旨" not in emperor or revised_text not in emperor:
            return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", prompt_faithful_backend)
    monkeypatch.setattr(session, "write_decree", lambda: revised_text)
    answers = iter([f"edit {directive.id}", revised_text, "issue", "yes"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    before = state.metrics["国库"]

    assert terminal.review_directives(session) == "issue"
    assert len(prompts) == 1

    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive.id)
    payload = json.loads(dossier["payload_json"])
    assert dossier["decree_text"] == revised_text
    assert dossier["action_type"] == "grant_allocation"
    assert (payload["amount"], payload["account"], payload["mode"]) == (
        25, "国库", "midzhi",
    )
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content,
    )
    assert state.metrics["国库"] == before - 25
    assert db.list_economy_moves_for_dossier(dossier["id"])[0]["delta"] == -25


def test_extractor_context_origin_ref_round_trips_to_commitment(game):
    from ming_sim.simulation import build_extractor_shared_context

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="今后每月修河",
        target_kind="issue", target_id="river-works",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    extractor_context = build_extractor_shared_context(
        db, state, "河工已经开办", "今后每月修河", module="issues",
    )
    origin_ref = next(
        row["origin_ref"] for row in extractor_context["decree_dossiers"]
        if row["id"] == dossier_id
    )

    issue_engine.apply_score_extraction(
        db, state, {"new_issues": [{
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": "逐月修河",
            "end_turn": state.turn + 2,
            "commitment_kind": "until_stop",
        }]}, content=content,
    )

    assert db.list_commitments_for_dossier(dossier_id)[0]["origin_ref"] == origin_ref


def test_secret_order_progress_persists_executing_until_terminal(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    order_id = db.create_secret_order(state, actor, "密查仓储", "核清仓储", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier["status"] == "promulgated"

    db.update_secret_order_progress(
        order_id, "已开始核账", state.year, state.period,
    )
    assert db.get_dossier_for_secret_order(order_id)["status"] == "executing"
    reopened = GameDB(db.path, content=content)
    try:
        assert reopened.get_dossier_for_secret_order(order_id)["status"] == "executing"
    finally:
        reopened.close()

    db.close_secret_order(order_id, "done", "账目核清", state.turn)
    terminal = db.get_dossier_for_secret_order(order_id)
    assert terminal["status"] == "closed"
    assert terminal["execution_outcome"] == "fulfilled"


def test_secret_order_progress_undo_restores_order_and_dossier_axes(game):
    db, state, _content = game
    actor = _active_minister(db)
    order_id = db.create_secret_order(
        state, actor, "密查仓储", "核清仓储", [],
    )
    chat_turn_id = db.create_chat_turn(state, actor, "dossier-undo", 0)
    db.update_chat_turn_messages(
        chat_turn_id,
        db.append_chat_message(actor, state.turn, "user", "继续查办"),
        db.append_chat_message(actor, state.turn, "minister", "臣遵旨"),
    )
    before = db.capture_chat_rollback_snapshot()
    db.update_secret_order_progress(
        order_id, "已开始核账", state.year, state.period,
    )
    db.record_chat_turn_rollback_diffs(
        chat_turn_id, before, db.capture_chat_rollback_snapshot(),
    )

    db.undo_chat_turn(chat_turn_id)

    assert db.get_secret_order(order_id)["result"] == ""
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier["status"] == "promulgated"
    assert dossier["execution_outcome"] == ""


def test_secret_order_close_failure_rolls_back_only_its_two_axes(game, monkeypatch):
    from ming_sim.applier import atomic

    db, state, _content = game
    order_id = db.create_secret_order(
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    dossier_before = db.get_dossier_for_secret_order(order_id)

    def fail_execution(*_args, **_kwargs):
        raise RuntimeError("dossier close failed")

    monkeypatch.setattr(db, "record_dossier_execution", fail_execution)
    with atomic(db):
        with pytest.raises(RuntimeError, match="dossier close failed"):
            db.close_secret_order(
                order_id, "done", "账目核清", state.turn, commit=False,
            )
        db.conn.execute(
            "UPDATE game_state SET ending_status='caller-continued' WHERE id=1"
        )

    assert db.get_secret_order(order_id)["status"] == "active"
    assert db.get_secret_order(order_id)["result"] == ""
    assert db.get_dossier_for_secret_order(order_id) == dossier_before
    assert db.conn.execute(
        "SELECT ending_status FROM game_state WHERE id=1"
    ).fetchone()["ending_status"] == "caller-continued"


def test_secret_order_progress_rolls_back_both_axes_in_outer_atomic(game):
    from ming_sim.applier import atomic

    db, state, _content = game
    order_id = db.create_secret_order(
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    with pytest.raises(RuntimeError):
        with atomic(db):
            db.update_secret_order_sim_note(
                order_id, "已惊动仓场", state.year, state.period,
            )
            raise RuntimeError("rollback")

    assert db.get_secret_order(order_id)["sim_note"] == ""
    assert db.get_dossier_for_secret_order(order_id)["status"] == "promulgated"


@pytest.mark.parametrize(
    "action_type",
    (
        "extraordinary_summons", "summons", "inquiry",
        "pressure_inquiry", "public_support",
    ),
)
def test_dialogue_and_engine_action_types_cannot_create_dossiers(
    game, action_type,
):
    db, state, _content = game
    with pytest.raises(ValueError):
        db.create_decree_dossier(
            state, action_type=action_type, decree_text="非旨意动作",
            target_kind="issue", target_id="not-a-decree",
        )


def test_legacy_secret_orders_restore_with_unique_resumable_dossiers(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    order_ids = {}
    for status in ("active", "pending_review", "done", "failed"):
        order_ids[status] = int(db.conn.execute(
            """
            INSERT INTO secret_orders
                (turn_issued,year_issued,period_issued,minister_name,title,
                 content,status,result,turn_closed)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                state.turn, state.year, state.period, actor, status,
                f"{status}密令", status,
                "已有进展" if status != "active" else "",
                state.turn if status in {"done", "failed"} else None,
            ),
        ).lastrowid)
    db.conn.commit()

    restored = GameDB(db.path, content=content)
    try:
        assert {
            status: restored.get_dossier_for_secret_order(order_id)["status"]
            for status, order_id in order_ids.items()
        } == {
            "active": "promulgated",
            "pending_review": "executing",
            "done": "closed",
            "failed": "closed",
        }
        assert restored.update_secret_order_progress(
            order_ids["active"], "继续查办", state.year, state.period,
        )
        assert restored.get_dossier_for_secret_order(
            order_ids["active"]
        )["status"] == "executing"
    finally:
        restored.close()

    reopened = GameDB(db.path, content=content)
    try:
        assert len([
            row for row in reopened.list_decree_dossiers()
            if row["secret_order_id"] in order_ids.values()
        ]) == len(order_ids)
    finally:
        reopened.close()


def test_legacy_secret_order_migration_ignores_free_text_progress(game):
    from ming_sim.db import GameDB

    db, state, content = game
    actor = _active_minister(db)
    ids = []
    for result, sim_note in (("", ""), ("任意说明", "另一段任意说明")):
        ids.append(int(db.conn.execute(
            """
            INSERT INTO secret_orders
                (turn_issued,year_issued,period_issued,minister_name,title,
                 content,status,result,sim_note)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                state.turn, state.year, state.period, actor, "旧密令",
                "相同结构化密令", "active", result, sim_note,
            ),
        ).lastrowid))
    db.conn.commit()

    restored = GameDB(db.path, content=content)
    try:
        assert [
            restored.get_dossier_for_secret_order(order_id)["status"]
            for order_id in ids
        ] == ["promulgated", "promulgated"]
    finally:
        restored.close()


def test_held_dossier_reenters_only_for_next_month_rejudgment(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="着核边饷",
        target_kind="issue", target_id="frontier-pay",
    )
    db.record_dossier_decision(
        dossier_id, "rejected", blocked_layer="six_offices",
        reason="封驳",
    )
    db.record_dossier_decision(dossier_id, "hold")

    assert dossier_id not in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(
            state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
        )
    state.next_period()
    db.save_state(state)
    assert dossier_id in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    db.apply_dossier_verdicts(
        state, [{
            "dossier_id": dossier_id, "decision": "promulgated",
        }],
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"


def test_interim_verdict_rejects_reserved_legal_reason_code(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="着核边饷",
        target_kind="issue", target_id="frontier-pay",
    )
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(state, [{
            "dossier_id": dossier_id, "decision": "rejected",
            "legal_reason_code": "statute-42",
        }])


def test_session_manual_directive_keeps_structured_action_at_submission(
    game, monkeypatch,
):
    from ming_sim.db import GameDB
    from ming_sim.models import LLMConfig
    from ming_sim.session import GameSession
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("add_directive 不得触发 backend")
        ),
    )
    session = GameSession(
        db.path,
        LLMConfig(
            api_key="", base_url="http://unused", model="unused", channel="api",
        ),
        content=content,
        verify_llm=False,
    )
    try:
        directive = session.add_directive(
            "着查河南河工",
            dossier_payload={
                "dossier_action_type": "assignment",
                "target_kind": "region",
                "target_id": "河南",
                "assignee": _active_minister(session.db),
            },
        )
        assert session.db.get_dossier_for_directive(directive.id) is None

        session.db.ensure_dossiers_for_draft_directives(session.state)
        reopened = GameDB(db.path, content=content)
        try:
            dossier = reopened.get_dossier_for_directive(directive.id)
            assert dossier["action_type"] == "assignment"
            assert dossier["target_kind"] == "region"
            assert dossier["target_id"] == "河南"
            assert dossier["directive_id"] == directive.id
        finally:
            reopened.close()
    finally:
        session.db.close()


def test_probe_directive_shared_entry_creates_and_settles_structured_dossier(game):
    from ming_sim.decree import settle_with_delta
    from ming_sim.session import GameSession
    from scripts.probe_directive_contract import add_narrative_probe_directive

    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state

    directive = add_narrative_probe_directive(
        session,
        "着有司整饬河工",
        probe_id="contract-smoke",
        notes="probe smoke",
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive.id)
    assert dossier["action_type"] == "policy"
    assert dossier["target_kind"] == "issue"
    assert dossier["target_id"] == "probe:contract-smoke:1"

    settle_with_delta(
        state,
        db,
        {},
        before_turn=state.turn,
        content=content,
        dossier_verdicts=[{
            "dossier_id": dossier["id"],
            "decision": "promulgated",
        }],
    )

    assert state.turn == 2
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"


def test_directive_freezes_at_dossier_birth(game):
    db, state, _content = game
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "river-works",
    }
    editable_id = db.add_directive(
        state, None, "河工初稿", "手动新增", dossier_payload=payload,
    )
    db.update_directive_text(
        editable_id, "河工改稿", dossier_payload=payload,
    )
    db.delete_directive(editable_id)

    directive_id = db.add_directive(
        state, None, "着修河工", "手动新增", dossier_payload=payload,
    )
    db.ensure_dossiers_for_draft_directives(state)
    with pytest.raises(ValueError):
        db.update_directive_text(directive_id, "成案后改稿")
    with pytest.raises(ValueError):
        db.delete_directive(directive_id)

def test_directive_edit_replaces_mechanical_payload_before_submission(game):
    db, state, _content = game
    before = state.metrics["国库"]
    ten = {
        "dossier_action_type": "grant_allocation",
        "target_kind": "issue", "target_id": "relief",
        "account": "国库", "amount": 10, "execution_surface": "immediate",
    }
    hundred = {**ten, "amount": 100}
    directive_id = db.add_directive(
        state, None, "拨十两赈济", "手动新增", dossier_payload=ten,
    )

    db.update_directive_text(
        directive_id, "改拨百两赈济", dossier_payload=hundred,
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    assert json.loads(dossier["payload_json"])["amount"] == 100

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
    )
    assert state.metrics["国库"] == before - 100


def test_allocation_rejects_unknown_economy_account_before_dossier_birth(game):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "发太仓银十两赈济", "手动新增",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief",
            "account": "太仓", "amount": 10, "execution_surface": "immediate",
        },
    )

    with pytest.raises(ValueError, match="account"):
        db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None


def test_underfunded_in_transit_allocation_closes_from_execution_state(game):
    db, state, _content = game
    state.metrics["国库"] = 5
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )

    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == 0
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    assert "不足额" in dossier["execution_note"]


def test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled(game):
    db, state, _content = game
    state.metrics["国库"] = 5
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两赈济",
        target_kind="issue",
        target_id="relief",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "immediate",
        },
    )

    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert state.metrics["国库"] == 0
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "failed"
    assert "不足额" in dossier["execution_note"]


@pytest.mark.parametrize(
    "payload",
    (
        {
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "relief", "account": "国库",
        },
        {
            "dossier_action_type": "assignment",
            "assignee": "不存在的人",
        },
    ),
)
def test_incomplete_mechanical_directive_is_rejected_instead_of_retyped(
    game, payload,
):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "不完整机械旨意", "手动新增", dossier_payload=payload,
    )
    with pytest.raises(ValueError):
        db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None


def test_mechanical_directive_missing_target_fails_loudly_at_real_entry(game):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "拨银十两但未指明去处", "手动新增",
        dossier_payload={
            "dossier_action_type": "grant_allocation",
            "target_kind": "issue",
            "account": "国库",
            "amount": 10,
            "execution_surface": "immediate",
        },
    )
    with pytest.raises(ValueError, match="canonical target"):
        db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None


def test_secret_order_commitment_origin_maps_to_its_own_dossier(game):
    db, state, _content = game
    order_id = db.create_secret_order(
        state, _active_minister(db), "安抚诸将", "每月拨银安抚诸将", [],
        deadline_months=3,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    assert db.resolve_commitment_origin_ref(
        state, f"secret_order:{order_id}", origin_kind="decree",
    ) == f"dossier:{dossier['id']}"


def test_military_directive_projects_normalized_due_turn_to_dossier(game):
    db, state, _content = game
    directive_id = db.add_directive(
        state, None, "命洪承畴四月内出师", "手动新增",
        dossier_payload={
            "dossier_action_type": "military_order",
            "target_kind": "region", "target_id": "shaanxi",
            "assignee": _active_minister(db),
            "deadline_months": 4,
        },
    )

    db.ensure_dossiers_for_draft_directives(state)

    dossier = db.get_dossier_for_directive(directive_id)
    payload = json.loads(dossier["payload_json"])
    assert payload["due_turn"] == state.turn + 4
    assert dossier["due_turn"] == state.turn + 4


@pytest.mark.parametrize("draft_count", (1, 2))
def test_draft_extraction_does_not_capture_acting_appointment(monkeypatch, draft_count):
    import ming_sim.cli_backend as cli_backend

    acting = {
        "正文": "命洪承畴暂署兵部尚书",
        "动作类型": "acting_appointment",
        "目标类型": "office",
        "目标ID": "兵部尚书",
    }
    second_acting = {
        "正文": "命卢象升暂署五军都督府都督同知",
        "动作类型": "acting_appointment",
        "目标类型": "office",
        "目标ID": "五军都督府都督同知",
    }
    raw = (
        {"拟旨意图": "拟旨", **acting}
        if draft_count == 1 else {"成品旨稿": [acting, second_acting]}
    )
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (json.dumps(raw, ensure_ascii=False), {}),
    )

    result = cli_backend.extract_draft_intent(
        "命洪承畴暂署兵部尚书", "臣已拟妥", draft_count=draft_count,
    )

    if draft_count == 1:
        assert result["dossier_action_type"] != "acting_appointment"
    else:
        assert result["drafts"] == []


def test_batch_draft_extraction_preserves_each_mechanical_payload(monkeypatch):
    import ming_sim.cli_backend as cli_backend

    raw = json.dumps({
        "成品旨稿": [
            {
                "正文": "拨国库银一万两赈陕",
                "动作类型": "grant_allocation",
                "目标类型": "region",
                "目标ID": "shaanxi",
                "金额": 10000,
                "账户": "国库",
                "执行面": "in_transit",
                "颁布方式": "普通",
            },
            {
                "正文": "命洪承畴三月出师",
                "动作类型": "military_order",
                "目标类型": "region",
                "目标ID": "shaanxi",
                "承办人": "洪承畴",
                "期限月数": 3,
                "颁布方式": "中旨直发",
            },
        ],
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_args, **_kwargs: (raw, {}),
    )
    result = cli_backend.extract_draft_intent(
        "分别拟旨拨款、出师", "臣已拟妥", draft_count=2,
    )
    assert result["drafts"][0]["amount"] == 10000
    assert result["drafts"][0]["dossier_action_type"] == "grant_allocation"
    assert result["drafts"][0]["mode"] == "ordinary"
    assert result["drafts"][1]["deadline_months"] == 3
    assert result["drafts"][1]["dossier_action_type"] == "military_order"
    assert result["drafts"][1]["mode"] == "midzhi"


def test_executing_dossier_stays_visible_and_extractor_can_close_it(game):
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="military_order", decree_text="三月后出师",
        target_kind="region", target_id="shaanxi",
        executor_kind="character", executor_id=_active_minister(db),
        due_turn=state.turn + 3,
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    state.turn += 1
    db.save_state(state)
    assert dossier_id in {
        row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    result = apply_score_extraction(
        db, state, {
            "dossier_executions": [{
                "dossier_id": dossier_id,
                "outcome": "fulfilled",
                "note": "奉旨出师，军令已毕",
            }],
        },
        content=content,
    )
    assert result["dossier_executions"] == [{
        "dossier_id": dossier_id, "outcome": "fulfilled",
    }]
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"


@pytest.mark.parametrize("origin_ref", (
    "dossier:not-a-number", "dossier:1:extra", f"dossier:{2 ** 63}",
))
def test_malformed_dossier_origin_is_rejected_fail_closed(game, origin_ref):
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    before = state.metrics["国库"]
    result = apply_score_extraction(db, state, {
        "economy_moves": [{
            "account": "国库", "delta": -9, "category": "伪造案卷",
            "origin_ref": origin_ref,
        }],
    }, content=content)

    assert state.metrics["国库"] == before
    assert result["economy_moves"] == []
    assert '"category": "invalid_origin_ref"' in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("bad_id,bad_decision,match", [
    ("abc", "promulgated", "dossier_id"),
    ({"id": 1}, "promulgated", "dossier_id"),
    (True, "promulgated", "dossier_id"),
    (1.0, "promulgated", "dossier_id"),
    (2 ** 63, "promulgated", "dossier_id"),
    (None, "approve", "decision"),
])
def test_invalid_promulgation_decision_stops_before_simulation(
    game, monkeypatch, bad_id, bad_decision, match,
):
    import ming_sim.decree as decree_mod
    from ming_sim.exceptions import LLMContractError, SettlementAbort

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    monkeypatch.setattr(
        decree_mod, "stub_promulgation_verdicts",
        lambda *_a, **_k: [{"dossier_id": bad_id, "decision": bad_decision}],
    )
    forbidden = lambda *_a, **_k: pytest.fail("判官契约失败后不得调用推演或 extractor")
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", forbidden)
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", forbidden)

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
        )
    assert exc_info.value.stage == "promulgation"
    assert exc_info.value.error_pack_path
    assert isinstance(exc_info.value.__cause__, LLMContractError)
    assert match in str(exc_info.value.__cause__)


def test_withdrawn_rescript_records_closed_turn(game):
    from ming_sim.db import GameDB

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="暂缓河工",
        target_kind="issue", target_id="river-works",
    )
    db.record_dossier_decision(
        dossier_id, "rejected", blocked_layer="six_offices", reason="封驳",
    )
    db.record_dossier_decision(dossier_id, "withdrawn", reason="收回成命")
    restored = GameDB(db.path, content=content)
    try:
        dossier = restored.get_decree_dossier(dossier_id)
        assert dossier["status"] == "closed"
        assert dossier["closed_turn"] == state.turn
    finally:
        restored.close()


def test_secret_order_target_survives_restore_and_is_queryable(game):
    from ming_sim.db import GameDB

    db, state, content = game
    order_id = db.create_secret_order(
        state, _active_minister(db), "密查仓储", "核清仓储", [],
    )
    restored = GameDB(db.path, content=content)
    try:
        matches = restored.list_decree_dossiers(
            target_kind="secret_order", target_id=order_id,
        )
        assert [row["secret_order_id"] for row in matches] == [order_id]
    finally:
        restored.close()


def test_allocation_candidate_edit_preserves_mechanical_payload(game):
    db, state, content = game
    actor = _active_minister(db)
    before = state.metrics["国库"]
    candidate_id = db.stage_directive_candidate(
        state.turn, actor, {
            "text": "初稿拨帑", "actor": actor,
            "dossier_action_type": "grant_allocation",
            "target_kind": "account", "target_id": "国库",
            "amount": 10, "account": "国库",
            "execution_surface": "immediate",
        },
    )
    db.update_directive_candidate(
        candidate_id, {"text": "改稿拨帑赈济", "actor": actor},
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[candidate_id],
    )
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == candidate_id
    )
    payload = json.loads(dossier["payload_json"])
    assert payload["amount"] == 10
    assert payload["account"] == "国库"
    assert dossier["decree_text"] == "改稿拨帑赈济"
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
    )
    assert state.metrics["国库"] == before - 10


def test_immediate_terminal_payload_cannot_bypass_execution_surface(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="着查仓储",
        target_kind="issue", target_id="granary-audit",
        executor_kind="character",
        executor_id=_active_minister(db),
        payload={"immediate_terminal": True},
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    with pytest.raises(ValueError):
        db.record_dossier_execution(
            dossier_id, "fulfilled", "伪造直结", state.turn,
        )
    with pytest.raises(ValueError):
        db.transition_decree_dossier(dossier_id, "closed")

    db.transition_decree_dossier(dossier_id, "executing")
    db.record_dossier_execution(
        dossier_id, "fulfilled", "真实执行完毕", state.turn,
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"


@pytest.mark.parametrize(("balance", "expected_actual", "status", "outcome"), [
    (20, -10, "executing", ""),
    (4, -4, "closed", "failed"),
    (0, 0, "closed", "failed"),
])
def test_inner_treasury_admission_uses_actual_once_and_preserves_surface(
    game, balance, expected_actual, status, outcome,
):
    db, state, _content = game
    state.metrics["内库"] = balance
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="内帑拨银押解赈济",
        target_kind="issue", target_id="relief",
        payload={
            "account": "内库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )

    assert state.metrics["内库"] == max(0, balance - 10)
    assert [row["delta"] for row in db.list_economy_moves_for_dossier(dossier_id)] == (
        [] if expected_actual == 0 else [expected_actual]
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == status
    assert dossier["execution_outcome"] == outcome
    assert state.metrics["内库"] == max(0, balance - 10)
    assert len(db.list_economy_moves_for_dossier(dossier_id)) == int(expected_actual != 0)
    if outcome == "failed":
        assert "应拨10两" in dossier["execution_note"]
        assert f"实拨{abs(expected_actual)}两" in dossier["execution_note"]
    else:
        assert status == "executing"
        assert dossier_id in {
            row["id"] for row in db.list_decree_dossiers_for_simulation(state.turn)
        }
        db.record_dossier_execution(
            dossier_id, "fulfilled", "赈银押解到达", state.turn,
        )
        assert db.get_decree_dossier(dossier_id)["status"] == "closed"


def _complete_session(game):
    """GameSession construction contract on the fixture's real DB/state."""
    from ming_sim.session import GameSession

    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.content = content
    session.llm_config = None
    session.db = db
    session.agno_db = None
    session.state = state
    session.deaths_this_turn = []
    session.debuts_this_turn = []
    session.power_renames_this_turn = []
    session.previous_summary = ""
    session.registry = None
    session.temporary_characters = {}
    session.last_decree = ""
    session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._begun = False
    return session


def test_web_inner_treasury_allocation_closes_next_month_without_replay(
    game, monkeypatch,
):
    import ming_sim.cli_backend as cli_backend
    import ming_sim.decree as decree_mod
    import web_app

    db, state, content = game
    state.metrics["内库"] = 50
    responses = iter((
        {
            "拟旨意图": "拟旨", "动作类型": "grant_allocation",
            "目标类型": "issue", "目标ID": "relief", "金额": 10,
            "账户": "内库", "执行面": "in_transit",
        },
        {
            "拟旨意图": "拟旨", "动作类型": "grant_allocation",
            "目标类型": "issue", "目标ID": "relief", "金额": 15,
            "账户": "内库", "执行面": "in_transit",
        },
    ))
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(next(responses), ensure_ascii=False), 1),
    )
    session = _complete_session(game)
    web_game = types.SimpleNamespace(
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: db.list_directives(
            state, statuses=("pending", "draft"),
        ),
        directive_payload=lambda row: dict(row),
        refresh_turn=lambda: None,
        state_payload=lambda: {},
    )
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)

    commands = ("内帑拨银押解赈济", "再拨十五两内帑押解赈济")
    directive_ids = []
    for command in commands:
        result = asyncio.run(web_app.api_create_directive(
            web_app.DirectiveRequest(text=command),
        ))
        directive_ids.append(int(result["directive"]["id"]))
    db.ensure_dossiers_for_draft_directives(state)
    dossiers = [db.get_dossier_for_directive(item) for item in directive_ids]
    for dossier in dossiers:
        db.apply_dossier_promulgation(
            state, dossier["id"], "promulgated", content=content,
        )
    assert state.metrics["内库"] == 25
    assert [
        [row["delta"] for row in db.list_economy_moves_for_dossier(dossier["id"])]
        for dossier in dossiers
    ] == [[-10], [-15]]
    assert all(
        db.get_decree_dossier(dossier["id"])["status"] == "executing"
        for dossier in dossiers
    )

    state.turn += 1
    db.save_state(state)
    seen = {}
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "apply_fixed_period_flows", lambda *_a, **_k: None)

    def _simulate(*_args, **kwargs):
        seen["dossiers"] = kwargs["simulator_payload"]["decree_dossiers"]
        return "赈银已经押解到达。", kwargs["simulator_payload"]

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _simulate)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"dossier_executions": [
            {
                "dossier_id": dossier["id"], "outcome": "fulfilled",
                "note": "赈银押解到达",
            }
            for dossier in dossiers
        ]}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    result = web_app.api_advance_without_edict()

    assert result["awaiting_decision"] is False
    projected = seen["dossiers"]
    assert [row["id"] for row in projected] == [row["id"] for row in dossiers]
    assert all(row["status"] == "executing" for row in projected)
    assert all("decree_text" not in row for row in projected)
    assert all("payload" not in row for row in projected)
    assert all("payload_json" not in row for row in projected)
    assert [row["execution_summary"] for row in projected] == [
        {"command": commands[0], "amount": 10, "account": "内库"},
        {"command": commands[1], "amount": 15, "account": "内库"},
    ]
    assert state.metrics["内库"] == 25
    assert [
        [row["delta"] for row in db.list_economy_moves_for_dossier(dossier["id"])]
        for dossier in dossiers
    ] == [[-10], [-15]]
    for dossier in dossiers:
        closed = db.get_decree_dossier(dossier["id"])
        assert closed["status"] == "closed"
        assert closed["execution_outcome"] == "fulfilled"
        assert closed["execution_note"] == "赈银押解到达"


def test_cli_protection_execution_closes_from_next_month_extractor(game, monkeypatch):
    import ming_sim.cli_backend as cli_backend
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = _active_minister(db)
    response = {
        "拟旨意图": "拟旨", "动作类型": "protection",
        "目标类型": "character", "目标ID": actor, "承办人": actor,
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    session = _complete_session(game)
    payload = cli_backend.capture_manual_directive_payload("护行此臣", None)
    directive_id = session.add_directive("护行此臣", dossier_payload=payload).id
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    db.apply_dossier_promulgation(state, dossier["id"], "promulgated", content=content)
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"

    state.turn += 1
    db.save_state(state)
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("护行已妥。", k["simulator_payload"]),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"dossier_executions": [{
            "dossier_id": dossier["id"], "outcome": "fulfilled",
            "note": "护行已妥",
        }]}, "", ""),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

    session.advance_without_decree()

    closed = db.get_decree_dossier(dossier["id"])
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "fulfilled"
    assert closed["execution_note"] == "护行已妥"


def test_secret_authorization_uses_canonical_authorization_boundary(game):
    db, state, content = game
    character = next(
        item for item in content.characters.values()
        if item.aliases and db.conn.execute(
            "SELECT 1 FROM characters WHERE name=? AND status='active'",
            (item.name,),
        ).fetchone()
    )
    directive_id = db.add_directive(
        state, None, "密授权理财", "player_decree",
        dossier_payload={
            "dossier_action_type": "secret_authorization",
            "target_kind": "character", "target_id": character.aliases[0],
            "assignee": character.aliases[0], "authorization_id": "理财",
        },
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    assert dossier is not None
    assert dossier["target_id"] == character.name
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    grants = db.list_skill_grants_for_dossier(dossier["id"])
    assert [(row["character_name"], row["skill_id"]) for row in grants] == [
        (character.name, "理财"),
    ]


@pytest.mark.parametrize("missing", ("assignee", "authorization_id"))
def test_secret_authorization_rejects_incomplete_payload_without_grant(
    game, missing,
):
    db, state, content = game
    actor = _active_minister(db)
    payload = {
        "dossier_action_type": "secret_authorization",
        "target_kind": "character", "target_id": actor,
        "assignee": actor, "authorization_id": "理财",
    }
    payload.pop(missing)
    before = db.conn.execute("SELECT COUNT(*) FROM skill_grants").fetchone()[0]
    directive_id = db.add_directive(
        state, None, "残缺密授权", "player_decree", dossier_payload=payload,
    )
    with pytest.raises(ValueError, match="canonical assignee 或授权字段"):
        db.ensure_dossiers_for_draft_directives(state)
    assert db.get_dossier_for_directive(directive_id) is None
    assert db.conn.execute("SELECT COUNT(*) FROM skill_grants").fetchone()[0] == before
    assert db.conn.execute(
        "SELECT COUNT(*) FROM skill_grants WHERE TRIM(character_name)='' OR TRIM(skill_id)=''"
    ).fetchone()[0] == 0


def test_in_transit_allocation_requires_execution_verdict(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    with pytest.raises(ValueError):
        db.close_decree_dossier(dossier_id)
    db.record_dossier_execution(
        dossier_id, "fulfilled", "押解到陕", state.turn,
    )
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "closed"
    assert dossier["execution_note"] == "押解到陕"
    assert dossier["interruption_reason"] == ""


@pytest.mark.parametrize("value", [True, 1.5, 2.9, "3"])
def test_durable_allocation_rejects_non_integer_amount_without_downgrade(game, value):
    db, state, _content = game
    minister = _active_minister(db)
    candidate_id = db.stage_directive_candidate(state.turn, minister, {
        "text": "拨帑赈济。", "actor": minister,
        "dossier_action_type": "grant_allocation",
        "target_kind": "issue", "target_id": "invalid-allocation",
        "amount": value, "account": "国库", "execution_surface": "immediate",
    })

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=[candidate_id],
        directive_status="draft",
    )

    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (candidate_id,)
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        row["pending_action_id"] == candidate_id for row in db.list_decree_dossiers()
    )


def test_durable_military_order_without_assignee_fails_loudly(game):
    db, state, _content = game
    minister = _active_minister(db)
    candidate_id = db.stage_directive_candidate(state.turn, minister, {
        "text": "三月内整军。", "actor": minister,
        "dossier_action_type": "military_order",
        "target_kind": "army", "target_id": "capital-army",
        "deadline_months": 3, "assignee": "",
    })

    db.commit_pending_actions(
        state, kind_filter="directive", action_ids=[candidate_id],
        directive_status="draft",
    )

    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (candidate_id,)
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        row["pending_action_id"] == candidate_id for row in db.list_decree_dossiers()
    )


def test_complete_rejection_verdict_is_restoreable_audit_record(game):
    from ming_sim.db import GameDB

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict["gatekeeper_id"] = _active_minister(db)
    verdict["criteria_snapshot"]["endorsement_entry_ids"] = [1]
    db.apply_dossier_verdicts(state, [verdict])

    restored = GameDB(db.path, content=content)
    try:
        row = restored.list_decree_dossier_decisions(dossier_id)[-1]
        assert row["primary_opponents"] == verdict["primary_opponents"]
        assert row["gatekeeper_id"] == verdict["gatekeeper_id"]
        assert row["criteria_snapshot"] == verdict["criteria_snapshot"]
        assert row["affected_parties"] == verdict["affected_parties"]
        assert row["midzhi_unpromulgatable"] is False
        assert restored.get_decree_dossier(dossier_id)["promulgation_reason"] == verdict["reason"]
    finally:
        restored.close()


def test_rejection_verdict_defaults_omitted_midzhi_marker_to_false(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict.pop("midzhi_unpromulgatable")

    db.apply_dossier_verdicts(state, [verdict])

    row = db.list_decree_dossier_decisions(dossier_id)[-1]
    assert row["midzhi_unpromulgatable"] is False


@pytest.mark.parametrize("missing", [
    "blocked_layer", "primary_opponents", "gatekeeper_id", "reason", "criteria_snapshot",
])
def test_rejection_runtime_contract_rejects_each_missing_field(game, missing):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict.pop(missing)
    with pytest.raises(ValueError, match="打回判决缺少"):
        db.apply_dossier_verdicts(state, [verdict])


@pytest.mark.parametrize(("field", "bad_value"), [
    ("primary_opponents", [{"kind": "faction", "key": "not-a-real-faction"}]),
    ("primary_opponents", [{"kind": "class", "key": "士绅"}]),
    ("primary_opponents", [{"kind": "faction", "key": "东林", "score": 1}]),
    ("gatekeeper_id", "not-a-real-character"),
])
def test_rejection_runtime_contract_rejects_unknown_references(game, field, bad_value):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict[field] = bad_value
    with pytest.raises(ValueError, match="打回判决缺少"):
        db.apply_dossier_verdicts(state, [verdict])


@pytest.mark.parametrize(("field", "bad_value"), [
    ("imperial_authority_band", "low"),
    ("involved_office_types", [1]),
    ("authorization_ids", [{}]),
    ("endorsement_entry_ids", [True]),
    ("endorsement_entry_ids", ["1"]),
])
def test_rejection_snapshot_rejects_malformed_typed_values(game, field, bad_value):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict["criteria_snapshot"][field] = bad_value
    with pytest.raises(ValueError, match="typed 判据快照"):
        db.apply_dossier_verdicts(state, [verdict])


@pytest.mark.parametrize("contamination", [
    {"primary_opponents": [{"kind": "faction", "key": 1}]},
    {"primary_opponents": [{"kind": "faction", "key": 1.5}]},
    {"primary_opponents": [{"kind": "faction", "key": True}]},
    {"resistance_scores": [99.5]},
    {"resistance_detail": {"score": 99.5}},
    {"resistance_detail": {"nested": [{"blocked": True}]}},
])
def test_rejection_contract_rejects_numeric_contamination_without_history(
    game, contamination,
):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    verdict = _rejected_verdict(dossier_id)
    verdict.update(contamination)

    with pytest.raises(ValueError, match="打回判决缺少"):
        db.apply_dossier_verdicts(state, [verdict])

    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"
