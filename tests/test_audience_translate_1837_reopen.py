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
    attendant = next(
        (c for c in content.characters.values()
         if c.status == "active" and (
             "司礼" in (c.office or "") or c.office_type in ("司礼监", "内廷")
         )),
        None,
    )
    if attendant is None:
        attendant = _active_minister(db, content)
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
                {"stage_idx": 0, "due_turn": int(state.turn) + 3, "label": "首段"},
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
            "stage_idx": 0,
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
    assert int(payload["deadline_months"]) == 1
    assert "限期下月" in payload["reason"]


def test_travel_tone_updates_this_round_summon_ledger(game):
    db, state, content = game
    night = open_night(db, state)
    person = _hong(db, content)
    # 模拟「宣 X」当场落下的传召账（常行）
    entry_id = record_summon_fresh(
        db, int(night["id"]), person,
        origin_id=f"scene:xuan:{int(state.turn)}:{person}",
        origin_chat_turn_id=0,
        travel_tone="常行",
    )
    before = list_unsettled_summons(db)
    assert any(
        item["person_name"] == person and item.get("travel_tone") == "常行"
        for item in before
    )
    decl = normalize_audience_declaration({
        "travel_tones": [{"person_name": person, "tone": "星夜兼程"}],
    })
    result = dispatch_declaration(
        db, state, decl, minister_name="殿上", night_id=int(night["id"]),
    )
    assert result.travel_tones.rejected == []
    assert len(result.travel_tones.applied) == 1
    after = list_unsettled_summons(db)
    matched = [item for item in after if item["person_name"] == person]
    assert matched and matched[0].get("travel_tone") == "星夜兼程"
    # 同一条账被更新，不另起行
    assert int(matched[0]["entry_id"]) == int(entry_id)


def test_scene_chat_turn_agno_session_id_is_scene_night(game, monkeypatch):
    """殿上建轮的 agno_session_id 对准场景会话，撤回/失败才截得到。"""
    from ming_sim.audience_night import SCENE_CHAT_SPEAKER, ensure_open_night_for_audience

    db, state, content = game
    night = ensure_open_night_for_audience(db, state)
    night_id = int(night["id"])

    class _FakeWeb:
        def __init__(self):
            self.db = db
            self.state = state
            self.session = SimpleNamespace(registry=None, temporary_characters={})

        def _persistent_chat_minister(self, name):
            return True

        def _minister_agno_session_id(self, minister_name: str) -> str:
            # production seam under test — copy of intended web_app behavior
            if minister_name == SCENE_CHAT_SPEAKER:
                open_n = ensure_open_night_for_audience(self.db, self.state)
                return f"scene-night-{int(open_n['id'])}"
            return f"minister-{minister_name}-turn-{self.state.turn}"

    web = _FakeWeb()
    sid = web._minister_agno_session_id(SCENE_CHAT_SPEAKER)
    assert sid == f"scene-night-{night_id}"


def test_old_minister_agent_surface_gone():
    """生成链零动作工具：旧大臣 agent / 动作工具入口不复存在。"""
    import importlib
    import ming_sim.registry as registry_mod

    assert not hasattr(registry_mod, "MinisterRegistry")
    assert not hasattr(registry_mod, "create_minister_agent")
    assert hasattr(registry_mod, "create_scene_agent")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ming_sim.tools")
