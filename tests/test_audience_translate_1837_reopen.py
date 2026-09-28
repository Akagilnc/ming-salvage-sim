"""#1837 reopen：旧 agent 退役后，转译承接禁摊派/荐人/查访/催办/行程语气。

Seams:
- dispatch_declaration（声明 → 既有暂存 / 查访写口 / 传召账）
- GameSession.scene_chat 建轮 agno_session_id = scene-night-{night_id}
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    list_unsettled_summons,
    open_night,
    record_summon_fresh,
)
from ming_sim.audience_translate import normalize_audience_declaration
from ming_sim.covert_levy import PROHIBITION_ACTION, write_exposure_todos
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.session import GameSession
from tests.settlement_seam_helpers import make_light_session


def _hong(db, content) -> str:
    if "洪承畴" in getattr(content, "characters", {}):
        return "洪承畴"
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _active_minister(db, content, *, office_type: str | None = None):
    for c in content.characters.values():
        if c.status != "active":
            continue
        if office_type and c.office_type != office_type:
            continue
        if c.office_type in ("后宫", "宗藩"):
            continue
        return c
    row = db.conn.execute(
        "SELECT name, office_type FROM characters WHERE status='active' LIMIT 1"
    ).fetchone()
    assert row is not None
    return SimpleNamespace(name=str(row["name"]), office_type=str(row["office_type"] or ""))


def _bound_exposure(db, state, monkeypatch):
    army = db.conn.execute("SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()
    executor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' LIMIT 1"
    ).fetchone()[0]
    did = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="整饬边军",
        target_kind="army", target_id=army["id"],
        executor_kind="character", executor_id=executor,
    )
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,))
    db.conn.execute(
        "INSERT INTO issues(kind,title,origin_ref,origin_turn,commitment_kind) "
        "VALUES ('差务','边军事',?,?, 'promise')",
        (f"dossier:{did}", state.turn),
    )
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    db.conn.execute(
        "INSERT INTO decree_dossier_links"
        "(source_dossier_id,target_dossier_id,relation_type,note) "
        "VALUES (?,?, '稽核','查账')",
        (did, did),
    )
    assert write_exposure_todos(db, state) == 1
    return int(did), str(executor)


def _scene_declaration(db, state, content, monkeypatch, words, declaration, *, minister_name="殿上", scene_reply=None):
    from tests.conftest import persist_and_schedule_scene, stub_audience_translate, stub_scene_agent
    from tests.test_audience_translation_1838 import _scene_session

    sess = _scene_session(db, state, content, monkeypatch)
    if scene_reply is not None:
        stub_scene_agent(monkeypatch, SimpleNamespace(
            tools=[], run=lambda message: SimpleNamespace(content=scene_reply, tools=[]),
        ))
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        **declaration,
        "scene_facts": [{"body": scene_reply or "殿上应对。", "role": "scene",
                         "audibility": "殿上公开", "person_names": []}],
    })
    night = open_night(db, state)
    ctid = db.create_chat_turn(
        state, minister_name, "s", 0, night_id=int(night["id"]), status="active",
    )
    reply = sess.scene_chat(words, chat_turn_id=ctid, minister_name=minister_name)
    future = persist_and_schedule_scene(sess, db, reply, speaker=minister_name)
    assert future is not None
    return future.result()


def _close_offline(db, state, content, night_id):
    from ming_sim.audience_night import close_night
    return close_night(
        db, state, night_id=night_id, content=content,
        endorsement_extractor_agent=SimpleNamespace(
            run=lambda _: SimpleNamespace(content='{"endorsements": []}'),
        ),
    )


def _player_month(db, state, content, monkeypatch, dossier_id, *, effects=None):
    """Drive the player month entry with only model outputs supplied offline."""
    import threading
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate
    from ming_sim.decree_forecast import decree_ref_for_dossier, stage_declaration

    dossier = db.get_decree_dossier(dossier_id)
    stage_declaration(
        db, decree_ref=decree_ref_for_dossier(db, dossier),
        declaration={"effects": {}}, turn=int(state.turn),
        verdict={"decision": "promulgated"}, forecast_text="",
    )
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "世界段" if effects else "")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": effects or {}})
    monkeypatch.setattr("ming_sim.session.write_decree_with_agno", lambda *a, **k: "诏")
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    before = int(state.turn)
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.stage == "gazette"
    # The same player entry resumes after the (offline) gazette is archived.
    db.save_turn_report(state, "月报", title="月报", public_body="月报")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced and int(state.turn) > before


def test_prohibit_covert_levy_commission_binds_exposed_dossier(game, monkeypatch):
    db, state, content = game
    did, actor = _bound_exposure(db, state, monkeypatch)
    decl = {
        "commissions": [{
            "text": "此等借饷扰民之举，即刻禁绝。",
            "dossier_action_type": PROHIBITION_ACTION,
            "target_id": did,
        }],
    }
    result = _scene_declaration(db, state, content, monkeypatch, "此等借饷扰民之举，即刻禁绝。", decl)
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    row = db.conn.execute(
        "SELECT payload_json, night_approved, kind, action FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert row["kind"] == "directive" and row["action"] == "拟旨"
    assert payload["dossier_action_type"] == PROHIBITION_ACTION
    assert payload["target_kind"] == "dossier" and payload["target_id"] == str(did)
    assert int(row["night_approved"] or 0) == 1
    _close_offline(db, state, content, int(open_night(db, state)["id"]))
    dossier = db.conn.execute(
        "SELECT id, action_type, target_id FROM decree_dossiers WHERE pending_action_id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    assert dossier is not None
    assert dossier["action_type"] == PROHIBITION_ACTION
    assert dossier["target_id"] == str(did)
    from ming_sim.covert_levy import active_prohibition_dossier
    army_id = db.conn.execute("SELECT target_id FROM decree_dossiers WHERE id=?", (did,)).fetchone()[0]
    db.conn.execute("UPDATE armies SET arrears=10 WHERE id=?", (army_id,))
    before = int(state.turn)
    _player_month(db, state, content, monkeypatch, int(dossier["id"]), effects={
        "fiscal_creates": [{
            "key": "禁后摊派", "account": "国库", "direction": "income", "init_value": 2,
            "origin_ref": f"dossier:{did}", "beyond_intent": True,
        }],
    })
    assert active_prohibition_dossier(db, did)["id"] == dossier["id"]
    assert int(state.turn) > before
    assert db.get_fiscal_config().get("禁后摊派_base") is None
    from ming_sim.due_review import list_due_review_scenes
    scenes = list_due_review_scenes(db, state)
    assert any(s["decision"] == "禁摊派" and s["shortfall_reopened"] for s in scenes)


def test_commission_failure_does_not_erase_prior_staged_item(game):
    db, state, content = game
    night = open_night(db, state)
    actor = _active_minister(db, content).name
    decl = normalize_audience_declaration({"commissions": [
        {"text": "着户部核实边饷。"},
        {"text": ""},
    ]})
    result = dispatch_declaration(
        db, state, decl, minister_name=actor, night_id=int(night["id"]),
    )
    assert len(result.commissions.applied) == 1
    assert len(result.commissions.rejected) == 1
    staged_id = result.commissions.applied[0]["id"]
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,)
    ).fetchone()["status"] == "pending"


def test_recommendation_commission_stages_office_with_reason(game, monkeypatch):
    db, state, content = game
    recommender = _active_minister(db, content, office_type="兵部")
    same_faction = next(
        c for c in content.characters.values()
        if c.name != recommender.name
        and c.faction == recommender.faction
        and c.office_type not in ("后宫", "宗藩")
    )
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?",
        (same_faction.name,),
    )
    db.conn.commit()
    reason = "请予试任巡盐御史，臣敢以身家保。"
    words = "陛下，巡盐之事可有合适人选？"
    scene_reply = f"臣荐{same_faction.name}任巡盐御史。{reason}"
    decl = {
        "commissions": [{
            "text": scene_reply,
            "appointment": {
                "name": same_faction.name,
                "office": "巡盐御史",
                "appoint_action": "任命",
            },
            "recommendation": {
                "recommender": recommender.name,
                "reason": reason,
            },
        }],
    }
    result = _scene_declaration(db, state, content, monkeypatch, words, decl,
                                minister_name=recommender.name, scene_reply=scene_reply)
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    row = db.conn.execute(
        "SELECT kind, action, payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    assert row["kind"] == "office" and row["action"] == "任命"
    payload = json.loads(row["payload_json"])
    assert payload["name"] == same_faction.name
    assert payload["office"] == "巡盐御史"
    assert payload["reason"] == reason
    assert payload["recommendation"]["recommender"] == recommender.name
    assert payload["recommendation"]["candidate"]["name"] == same_faction.name
    approval = _scene_declaration(db, state, content, monkeypatch, "准", {
        "promises": [{"action_id": result.commissions.applied[0]["id"], "decision": "应允"}],
    })
    assert len(approval.promises.applied) == 1
    _close_offline(db, state, content, int(open_night(db, state)["id"]))
    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    assert dossier is not None
    _player_month(db, state, content, monkeypatch, int(dossier["id"]))
    appointed = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (same_faction.name,),
    ).fetchone()
    assert appointed["office"] == "巡盐御史"
    events = db.list_recommendation_events(state, recommender.name)
    assert any(e["candidate"] == same_faction.name and e["reason"] == reason for e in events)


def test_recommendation_outside_slice_is_rejected(game):
    db, state, content = game
    night = open_night(db, state)
    recommender = _active_minister(db, content, office_type="兵部")
    hidden = next(
        c for c in content.characters.values()
        if c.name != recommender.name
        and c.faction != recommender.faction
        and c.office_type not in ("后宫", "宗藩")
        and c.status == "active"
    )
    decl = normalize_audience_declaration({
        "commissions": [{
            "text": f"荐{hidden.name}为巡抚",
            "appointment": {
                "name": hidden.name, "office": "陕西巡抚", "appoint_action": "任命",
            },
            "recommendation": {
                "recommender": recommender.name,
                "reason": "臣闻其贤。",
            },
        }],
    })
    result = dispatch_declaration(
        db, state, decl,
        minister_name=recommender.name, night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}


def test_inquiry_declaration_persists_return_report(game, monkeypatch):
    db, state, content = game
    attendant = _active_minister(db, content)
    db.conn.execute(
        "UPDATE characters SET office='御前近臣' WHERE name=?", (attendant.name,)
    )
    query = "请查访各镇欠饷军情如何？"
    result = _scene_declaration(db, state, content, monkeypatch, query, {
        "inquiries": [{"attendant": attendant.name, "query": query}],
    })
    assert result.inquiries.rejected == []
    assert len(result.inquiries.applied) == 1
    sources = db.conn.execute(
        "SELECT source_id FROM character_knowledge_sources "
        "WHERE source_id LIKE 'near_minister:%'"
    ).fetchall()
    assert sources
    known = db.get_character_knowledge(state, attendant.name)
    report_events = [event for event in known["events"]
                     if event["source_id"] in {r["source_id"] for r in sources}]
    assert report_events
    from ming_sim.audience_night import summon_enter
    from ming_sim.materials import prepare_scene_materials, release_material_tree
    # A fresh night must make this report readable, not merely list a carrier.
    _close_offline(db, state, content, int(open_night(db, state)["id"]))
    night = open_night(db, state)
    summon_enter(db, int(night["id"]), attendant.name, empty_scaffold=True)
    prepared = prepare_scene_materials(db, state)
    try:
        from pathlib import Path
        carrier = f"人物/{attendant.name}/经历.txt"
        assert carrier in prepared.index_lines
        experience = (Path(prepared.root) / carrier).read_text(encoding="utf-8")
        assert all(event["body"] in experience for event in report_events)
    finally:
        release_material_tree(prepared.root)


def test_rush_commitment_stages_pending_催办(game, monkeypatch):
    db, state, content = game
    minister = _active_minister(db, content)
    cur = db.conn.execute(
        "INSERT INTO issues(kind, title, status, stages_json, origin_turn) "
        "VALUES ('差务', '分段试办', 'active', ?, ?)",
        (
            json.dumps([
                {"stage_idx": 0, "due_turn": int(state.turn) + 2, "criterion_text": "首段"},
                {"stage_idx": 1, "due_turn": int(state.turn) + 3, "criterion_text": "次段"},
            ], ensure_ascii=False),
            int(state.turn),
        ),
    )
    issue_id = int(cur.lastrowid)
    db.conn.commit()
    reason = "限期下月办结" * 25
    decl = {
        "rushes": [{
            "target_kind": "commitment",
            "target_id": issue_id,
            "stage_idx": 1,
            "deadline_months": 1,
            "reason": reason,
        }],
    }
    result = _scene_declaration(db, state, content, monkeypatch,
                                "分段试办限期下月办结", decl, minister_name=minister.name)
    assert result.rushes.rejected == []
    assert len(result.rushes.applied) == 1
    row = db.conn.execute(
        "SELECT kind, action, target_id, payload_json FROM pending_actions WHERE id=?",
        (result.rushes.applied[0]["id"],),
    ).fetchone()
    assert row["kind"] == "commitment" and row["action"] == "催办"
    assert int(row["target_id"]) == issue_id
    payload = json.loads(row["payload_json"])
    assert int(payload["stage_idx"]) == 1
    assert int(payload["deadline_months"]) == 1
    assert payload["reason"] == reason
    db.commit_pending_actions(state, content=content, registry=None)
    from ming_sim.staged_commitment import normalize_commitment_stages
    stages = normalize_commitment_stages(db.conn.execute(
        "SELECT stages_json FROM issues WHERE id=?", (issue_id,)
    ).fetchone()["stages_json"])
    assert int(stages[0]["due_turn"]) == int(state.turn) + 2
    assert int(stages[1]["due_turn"]) == int(state.turn) + 1
    committed = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=? AND status='committed'",
        (result.rushes.applied[0]["id"],),
    ).fetchone()
    assert committed is not None
    assert json.loads(committed["payload_json"])["reason"] == reason


def test_repeated_urgent_summons_have_independent_rollback_origins(game, monkeypatch):
    from tests.conftest import persist_and_schedule_scene, stub_audience_translate
    from tests.test_audience_translation_1838 import _scene_session

    db, state, content = game
    night = open_night(db, state)
    person = _hong(db, content)
    db.conn.execute(
        "UPDATE characters SET location='shaanxi', transit_to='' WHERE name=?", (person,)
    )
    sess = _scene_session(db, state, content, monkeypatch)
    tones = iter(("星夜兼程", "加急"))
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        "scene_facts": [{"body": "殿上应对。", "role": "scene",
                         "audibility": "殿上公开", "person_names": []}],
        "travel_tones": [{"person_name": person, "tone": next(tones)}],
    })
    turns = []
    for words in (f"星夜宣{person}来京", f"加急宣{person}来京"):
        ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=int(night["id"]), status="active")
        reply = sess.scene_chat(words, chat_turn_id=ctid)
        future = persist_and_schedule_scene(sess, db, reply)
        assert future is not None
        future.result()
        turns.append(ctid)
    rows = [row for row in list_unsettled_summons(db) if row["person_name"] == person]
    assert len(rows) == 2
    assert [row["travel_tone"] for row in rows] == ["星夜兼程", "加急"]
    db.fail_chat_turn(turns[0])
    rows = [row for row in list_unsettled_summons(db) if row["person_name"] == person]
    assert len(rows) == 1 and rows[0]["travel_tone"] == "加急"


def test_travel_tone_updates_this_round_summon_ledger(game, monkeypatch):
    from tests.conftest import persist_and_schedule_scene, stub_audience_translate, stub_scene_agent
    from tests.test_audience_translation_1838 import _scene_session

    db, state, content = game
    night = open_night(db, state)
    person = _hong(db, content)
    db.conn.execute(
        "UPDATE characters SET location='shaanxi', transit_to='' WHERE name=?", (person,)
    )
    if db.get_character_status(person)[0] != "active":
        db.set_character_status(state, person, "active")

    class SceneAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="殿上回奏。", tools=[])

    sess = _scene_session(db, state, content, monkeypatch)
    stub_scene_agent(monkeypatch, SceneAgent())
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        "scene_facts": [{"body": "殿上回奏。", "role": "scene",
                         "audibility": "殿上公开", "person_names": []}],
        "travel_tones": [{"person_name": person, "tone": "星夜兼程"}],
    })
    old_id = record_summon_fresh(
        db, int(night["id"]), person, origin_id="earlier-summon",
        origin_chat_turn_id=0,
    )
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=int(night["id"]), status="active")
    reply = sess.scene_chat(f"星夜宣{person}来京", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, reply)
    assert future is not None
    future.result()
    matched = [item for item in list_unsettled_summons(db) if item["person_name"] == person]
    assert matched and matched[-1].get("travel_tone") == "星夜兼程"
    assert db.conn.execute(
        "SELECT origin_chat_turn_id FROM story_ledger_entries WHERE id=?",
        (matched[-1]["entry_id"],),
    ).fetchone()[0] == ctid
    assert matched[0]["entry_id"] == old_id
    assert matched[0]["travel_tone"] == "常行"
    from ming_sim.audience_night import commit_fresh_summons_for_night
    ordinary = "毕自严"
    db.conn.execute(
        "UPDATE characters SET location='shaanxi', transit_to='' WHERE name=?", (ordinary,)
    )
    record_summon_fresh(db, int(night["id"]), ordinary, origin_id="ordinary-comparison")
    commit_fresh_summons_for_night(db, state, int(night["id"]), content=content)
    trip = db.conn.execute(
        "SELECT transit_to, transit_speed_factor, transit_distance_remaining "
        "FROM characters WHERE name=?", (person,)
    ).fetchone()
    assert trip["transit_to"] == "beizhili"
    assert trip["transit_distance_remaining"] > 0
    ordinary_trip = db.conn.execute(
        "SELECT transit_to, transit_speed_factor, transit_distance_remaining "
        "FROM characters WHERE name=?", (ordinary,)
    ).fetchone()
    assert ordinary_trip["transit_to"] == "beizhili"
    assert trip["transit_distance_remaining"] == ordinary_trip["transit_distance_remaining"]
    assert trip["transit_speed_factor"] > ordinary_trip["transit_speed_factor"]
    from ming_sim.decree import tick_transit_arrivals
    from math import ceil
    arrival_turns = {}
    for turn in range(int(state.turn) + 1, int(state.turn) + ceil(ordinary_trip["transit_distance_remaining"]) + 2):
        state.turn = turn
        for arrived in tick_transit_arrivals(db, state, content):
            if arrived["name"] in (person, ordinary):
                arrival_turns[arrived["name"]] = turn
    assert arrival_turns[person] < arrival_turns[ordinary]


@pytest.mark.parametrize("ineligible", ["enemy", "vassal"])
def test_urgent_summons_cannot_bypass_audience_admission(game, monkeypatch, ineligible):
    from tests.conftest import persist_and_schedule_scene, stub_audience_translate
    from tests.test_audience_translation_1838 import _scene_session

    db, state, content = game
    person = _hong(db, content)
    db.conn.execute(
        "UPDATE characters SET status='active', location='shaanxi', transit_to='' WHERE name=?",
        (person,),
    )
    if ineligible == "enemy":
        db.conn.execute("UPDATE characters SET power_id='houjin' WHERE name=?", (person,))
    else:
        content.characters[person].office_type = "宗藩"
    night = open_night(db, state)
    sess = _scene_session(db, state, content, monkeypatch)
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        "scene_facts": [{"body": "殿上应对。", "role": "scene",
                         "audibility": "殿上公开", "person_names": []}],
        "travel_tones": [{"person_name": person, "tone": "星夜兼程"}],
    })
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=int(night["id"]), status="active")
    reply = sess.scene_chat(f"星夜宣{person}来京", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, reply)
    assert future is not None
    future.result()
    assert not [row for row in list_unsettled_summons(db) if row["person_name"] == person]
