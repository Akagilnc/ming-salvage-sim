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
from ming_sim.covert_levy import ENTRY_KIND, PROHIBITION_ACTION, write_exposure_todos
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.session import GameSession


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
    army = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
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


def test_prohibit_covert_levy_commission_binds_exposed_dossier(game, monkeypatch):
    db, state, content = game
    night = open_night(db, state)
    did, actor = _bound_exposure(db, state, monkeypatch)
    decl = normalize_audience_declaration({
        "commissions": [{
            "text": "此等借饷扰民之举，即刻禁绝。",
            "dossier_action_type": PROHIBITION_ACTION,
            "target_id": did,
        }],
    })
    result = dispatch_declaration(
        db, state, decl, minister_name=actor, night_id=int(night["id"]),
    )
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


def test_recommendation_commission_stages_office_with_reason(game):
    db, state, content = game
    night = open_night(db, state)
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
    decl = normalize_audience_declaration({
        "commissions": [{
            "text": f"臣荐{same_faction.name}任巡盐御史。{reason}",
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
    })
    result = dispatch_declaration(
        db, state, decl,
        minister_name=recommender.name, night_id=int(night["id"]),
    )
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


def test_inquiry_declaration_persists_return_report(game):
    db, state, content = game
    night = open_night(db, state)
    attendant = _active_minister(db, content)
    db.conn.execute(
        "UPDATE characters SET office='御前近臣' WHERE name=?", (attendant.name,)
    )
    query = "请查访各镇欠饷军情如何？"
    # 建一轮对话轮，查访可绑源轮
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES ('殿上', ?, 'user', ?, 'held')",
        (int(state.turn), query),
    )
    uid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES ('殿上', ?, 'minister', '奴婢领旨。', 'held')",
        (int(state.turn),),
    )
    mid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name, turn, year, period, user_message_id, minister_message_id, "
        " status, night_id, night_seq) "
        "VALUES ('殿上', ?, ?, ?, ?, ?, 'active', ?, 1)",
        (int(state.turn), int(state.year), int(state.period), uid, mid, int(night["id"])),
    )
    ctid = int(cur.lastrowid)
    db.conn.commit()
    decl = normalize_audience_declaration({
        "inquiries": [{"attendant": attendant.name, "query": query}],
    })
    result = dispatch_declaration(
        db, state, decl, minister_name="殿上",
        night_id=int(night["id"]), chat_turn_id=ctid,
    )
    assert result.inquiries.rejected == []
    assert len(result.inquiries.applied) == 1
    sources = db.conn.execute(
        "SELECT source_id, title, body FROM character_knowledge_sources "
        "WHERE source_id LIKE 'near_minister:%'"
    ).fetchall()
    assert sources
    assert any("查访" in str(r["title"] or "") or "见闻" in str(r["title"] or "")
               for r in sources)


def test_rush_commitment_stages_pending_催办(game):
    db, state, content = game
    night = open_night(db, state)
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
    decl = normalize_audience_declaration({
        "rushes": [{
            "target_kind": "commitment",
            "target_id": issue_id,
            "stage_idx": 1,
            "deadline_months": 1,
            "reason": "限期下月办结",
        }],
    })
    result = dispatch_declaration(
        db, state, decl, minister_name=minister.name, night_id=int(night["id"]),
    )
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
    assert "限期下月" in payload["reason"]
    db.commit_pending_actions(state, content=content, registry=None)
    from ming_sim.staged_commitment import normalize_commitment_stages
    stages = normalize_commitment_stages(db.conn.execute(
        "SELECT stages_json FROM issues WHERE id=?", (issue_id,)
    ).fetchone()["stages_json"])
    assert int(stages[0]["due_turn"]) == int(state.turn) + 2
    assert int(stages[1]["due_turn"]) == int(state.turn) + 1


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

    stub_scene_agent(monkeypatch, SceneAgent())
    sess = _scene_session(db, state, content, monkeypatch)
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        "scene_facts": [{
            "body": prompt.split("【本轮回话】", 1)[1].removesuffix("\n"),
            "role": "scene", "audibility": "殿上公开", "person_names": [],
        }],
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


def test_old_minister_agent_surface_gone():
    """生成链零动作工具：旧大臣 agent / 动作工具入口不复存在。"""
    import importlib
    import ming_sim.registry as registry_mod

    assert not hasattr(registry_mod, "MinisterRegistry")
    assert not hasattr(registry_mod, "create_minister_agent")
    assert hasattr(registry_mod, "create_scene_agent")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ming_sim.tools")
