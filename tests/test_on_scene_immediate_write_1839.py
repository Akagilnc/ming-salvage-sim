"""#1839 C2 当场实况直写（夜内直写白名单第四类）。

转译声明为「已发生」的实况当场落世界账本：人物生死 / 下狱 / 革职 / 在场、
文字事实、公开说法、边事件、入册；均带源轮，撤回本轮以前像日志逆转。
交办仍走暂存 → 应允 → 收夜成案 → 颁布关。

Seams:
- dispatch_declaration（C0 分派入口 + 源轮 chat_turn_id）
- NIGHT_DIRECT_WRITE_WHITELIST 第四类
- capture_chat_rollback_snapshot / record_chat_turn_rollback_diffs / undo_chat_turn
- prepare_scene_materials（下一句目录可见实况）
"""

from __future__ import annotations

import json

from ming_sim import audience_night as an
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.materials import list_materials, prepare_scene_materials, read_material
from ming_sim.public_sayings import list_public_sayings


def _active_minister(db, *, exclude: set[str] | None = None) -> str:
    skip = exclude or set()
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' AND office_type NOT IN ('后宫','宗藩','未仕') "
        "ORDER BY name"
    ).fetchall()
    for r in row:
        name = str(r["name"])
        if name not in skip:
            return name
    raise AssertionError("no active minister")


def _run_round_with_declaration(db, state, minister: str, declaration: dict, *, night_id: int = 0):
    """一轮窗口：前像 → 对话轮 → 分派声明（源轮绑定）→ 后像 → 记 diff。"""
    before = db.capture_chat_rollback_snapshot()
    if night_id <= 0 and an.get_open_night(db) is None:
        an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id, chat_id = an.attach_chat_turn_to_night(db, state, minister)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (minister, state.turn, "卿以为如何？"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, "臣遵旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    result = dispatch_declaration(
        db, state, declaration,
        minister_name=minister, night_id=int(night_id), chat_turn_id=int(chat_id),
    )
    db.conn.execute(
        "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?", (int(chat_id),),
    )
    db.conn.commit()
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(chat_id), before, after)
    return int(night_id), int(chat_id), result


def test_whitelist_fourth_category_covers_declared_on_scene_tables():
    """ADR 0038 后出：第四类「转译声明的当场实况」；原②③并入。"""
    wl = an.NIGHT_DIRECT_WRITE_WHITELIST
    assert "密令落地" in wl
    assert "转译声明的当场实况" in wl
    # 原第②③项并入第四类，不再并列。
    assert "未在册人物入册" not in wl
    assert "召对口关系边事件" not in wl
    fourth = wl["转译声明的当场实况"]
    for table in (
        "characters", "character_offices", "factions", "relation_edge_events",
        "textual_facts", "public_sayings", "story_ledger_entries",
    ):
        assert table in fourth


def test_kill_lands_status_and_next_materials_show_it(game, tmp_path):
    """AC1：当场落生死，下一句目录里已是实况。"""
    db, state, _ = game
    victim = _active_minister(db)
    witness = _active_minister(db, exclude={victim})
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    an.summon_enter(db, night_id, victim, body="宣入", empty_scaffold=True)
    an.summon_enter(db, night_id, witness, body="宣入", empty_scaffold=True)

    declaration = {
        "on_scene_facts": [{
            "name": victim, "动作": "处置", "status": "dead",
            "reason": "陛下率领内侍当场斩杀",
        }],
    }
    _run_round_with_declaration(
        db, state, witness, declaration, night_id=night_id,
    )

    status, reason = db.get_character_status(victim)
    assert status == "dead"
    assert "斩杀" in reason or reason  # 理由原样落库

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "after-kill")
    listed = list_materials(prepared.root)
    # 在场见证者的朝臣名册不再把死者列为 active 在朝
    roster_paths = [p for p in listed if p.endswith("朝臣名册.txt")]
    assert roster_paths
    for path in roster_paths:
        text = read_material(prepared.root, path)
        # 名册只列 active；死者不得再以 active 行出现
        assert f"{victim}：" not in text or "dead" in text
    # 若死者仍在场，其人物档料须写明当前状态
    victim_dossier = f"人物/{victim}/人物档料.txt"
    if victim_dossier in listed:
        dossier = read_material(prepared.root, victim_dossier)
        assert "dead" in dossier or "死" in dossier or "斩杀" in dossier


def test_textual_fact_and_public_saying_land_and_show_in_materials(game, tmp_path):
    """AC2：孙传庭伤臂 → 文字事实；袁崇焕对外死讯 → 公开说法；目录可见。"""
    db, state, _ = game
    sun = _active_minister(db)
    yuan = _active_minister(db, exclude={sun})
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    an.summon_enter(db, night_id, sun, body="宣入", empty_scaffold=True)

    arm_injury = "左臂中箭，血透重甲，犹力战不退"
    death_rumour = "关外传袁崇焕已死于宁远城下"
    declaration = {
        "textual_facts": [{
            "subject_kind": "character", "subject_id": sun, "body": arm_injury,
        }],
        "public_sayings": [{
            "body": death_rumour, "involved_characters": [yuan],
        }],
    }
    _run_round_with_declaration(db, state, sun, declaration, night_id=night_id)

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=sun)
    assert any(f.body == arm_injury for f in facts)
    sayings = list_public_sayings(db, involved_character=yuan)
    assert any(s["body"] == death_rumour for s in sayings)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "after-facts")
    listed = list_materials(prepared.root)
    # 文字事实进场景目录 人物/<名>/按月实况.txt
    facts_rel = f"人物/{sun}/按月实况.txt"
    assert facts_rel in listed
    assert arm_injury in read_material(prepared.root, facts_rel)
    # 公开说法经见闻公开层进 人物/<名>/公开说法/
    public_files = [p for p in listed if "/公开说法/" in p]
    assert public_files
    public_blob = "\n".join(read_material(prepared.root, p) for p in public_files)
    assert death_rumour in public_blob


def test_undo_reverses_round_on_scene_writes(game):
    """AC3：撤回本轮后该轮直写的实况像逆转，账本与对话轮不分叉。"""
    db, state, _ = game
    victim = _active_minister(db)
    partner = _active_minister(db, exclude={victim})
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    an.summon_enter(db, night_id, victim, body="宣入", empty_scaffold=True)
    an.summon_enter(db, night_id, partner, body="宣入", empty_scaffold=True)

    arm_injury = "臂骨已折，不能挽弓"
    declaration = {
        "on_scene_facts": [{
            "name": victim, "动作": "处置", "status": "imprisoned",
            "reason": "殿前拿下，下狱待勘",
        }],
        "textual_facts": [{
            "subject_kind": "character", "subject_id": partner, "body": arm_injury,
        }],
        "public_sayings": [{
            "body": "坊间盛传某尚书已在殿上被拿",
            "involved_characters": [victim],
        }],
        "presence": [{
            "person_name": victim, "effect": "exit",
            "body": "校尉拥之出殿",
        }],
        "edge_events": [{
            "source": partner, "target": victim,
            "event_kind": "结怨", "context": "见其被拿而不救",
        }],
    }
    night_id, chat_id, result = _run_round_with_declaration(
        db, state, partner, declaration, night_id=night_id,
    )
    assert result.on_scene_facts.rejected == []
    assert result.textual_facts.rejected == []
    assert result.public_sayings.rejected == []
    assert result.presence.rejected == []
    assert result.edge_events.rejected == []

    assert db.get_character_status(victim)[0] == "imprisoned"
    assert any(
        f.body == arm_injury
        for f in db.textual_facts.readable_materials(
            subject_kind="character", subject_id=partner,
        )
    )
    assert list_public_sayings(db, involved_character=victim)
    assert victim not in an.present_names_at(db, night_id)
    edges_before = db.get_relation_edge_events(source=partner, target=victim)
    assert edges_before

    # 白名单审计：本轮直写须落在第四类，不得越权咬住
    observed = an.audit_night_direct_writes(db, night_id)
    assert "转译声明的当场实况" in observed

    db.undo_chat_turn(chat_id)

    assert db.get_character_status(victim)[0] == "active"
    assert not any(
        f.body == arm_injury
        for f in db.textual_facts.readable_materials(
            subject_kind="character", subject_id=partner,
        )
    )
    assert not list_public_sayings(db, involved_character=victim)
    # 告退账随源轮删 → 在场复原
    assert victim in an.present_names_at(db, night_id)
    assert not db.get_relation_edge_events(source=partner, target=victim)
    # 对话轮标 undone，消息已删
    turn_row = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (chat_id,),
    ).fetchone()
    assert turn_row["status"] == "undone"


def test_night_bound_sections_reject_missing_or_foreign_source_chat_turn(game):
    """#1839 AC3：夜上下文第四类（presence/scene_facts/edge_events）须带属本夜
    的正源轮；缺失或不属本夜 → missing_ref，不落 origin=0 / turn:N 孤儿账。
    过月无夜路径（night_id=0）不在本案。"""
    db, state, _ = game
    minister = _active_minister(db)
    other = _active_minister(db, exclude={minister})
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    # night_id=0 的对话轮＝不属本夜的源轮。
    foreign_ctid = db.create_chat_turn(
        state, minister, "t1839:foreign", 0, night_id=0,
    )

    declaration = {
        "presence": [{
            "person_name": minister, "effect": "enter",
            "body": "内侍宣入。",
        }],
        "scene_facts": [{
            "body": "臣领旨。", "audibility": "殿上公开",
            "person_names": [minister],
        }],
        "edge_events": [{
            "source": minister, "target": other, "event_kind": "撑腰",
            "context": "当殿举荐",
        }],
    }
    before_ledger = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    before_edges = db.conn.execute(
        "SELECT COUNT(*) c FROM relation_edge_events"
    ).fetchone()["c"]

    missing = dispatch_declaration(
        db, state, declaration, night_id=night_id, chat_turn_id=0,
    )
    foreign = dispatch_declaration(
        db, state, declaration, night_id=night_id, chat_turn_id=int(foreign_ctid),
    )

    for result in (missing, foreign):
        assert result.presence.applied == []
        assert result.scene_facts.applied == []
        assert result.edge_events.applied == []
        assert len(result.presence.rejected) == 1
        assert len(result.scene_facts.rejected) == 1
        assert len(result.edge_events.rejected) == 1
        assert result.presence.rejected[0].category == "missing_ref"
        assert result.scene_facts.rejected[0].category == "missing_ref"
        assert result.edge_events.rejected[0].category == "missing_ref"

    after_ledger = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    after_edges = db.conn.execute(
        "SELECT COUNT(*) c FROM relation_edge_events"
    ).fetchone()["c"]
    assert after_ledger == before_ledger
    assert after_edges == before_edges


def test_commission_stays_staged_not_bypassing_promulgation(game):
    """AC4：任洪承畴、拨三十万仍是暂存交办，不因「当场」绕过颁布关。"""
    db, state, _ = game
    minister = _active_minister(db)
    army = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    army_id = str(army["id"]) if army else ""

    before_directives = db.conn.execute(
        "SELECT COUNT(*) c FROM turn_directives"
    ).fetchone()["c"]
    before_pending = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions"
    ).fetchone()["c"]

    # 交办正文 + 拨帑载荷（purpose 闭集＝补饷，沿 #1503）；仍只落 pending_actions。
    commission: dict = {"text": "任命洪承畴为陕西巡抚，调银三十万两赈灾"}
    if army_id:
        commission["grant"] = {
            "amount": 300000, "account": "国库", "purpose": "补饷",
            "target_kind": "army", "target_id": army_id,
        }
    result = dispatch_declaration(
        db, state, {"commissions": [commission]}, minister_name=minister,
    )
    assert len(result.commissions.applied) == 1
    assert result.commissions.rejected == []

    after_pending = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions"
    ).fetchone()["c"]
    assert after_pending == before_pending + 1

    row = db.conn.execute(
        "SELECT kind, night_approved, payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    assert row["kind"] == "directive"
    assert int(row["night_approved"] or 0) == 0  # 未应允，更未收夜成案
    payload = json.loads(row["payload_json"])
    assert "洪承畴" in payload["text"]

    # 不得当场写成 turn_directives（颁布关之前）
    after_directives = db.conn.execute(
        "SELECT COUNT(*) c FROM turn_directives"
    ).fetchone()["c"]
    assert after_directives == before_directives
