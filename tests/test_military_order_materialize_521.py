"""#521 军令·调遣：候选→收夜案卷→0055 判后 station/office/due_turn。

Seams:
- ACTION_CLUSTERS military_order 行 + materialize_fn
- run_materialize_pipeline / apply_cli_conversation_actions
- commit_pending_actions（收夜落案卷，不成 station/office 效果）
- apply_dossier_verdicts（0055 顺颁才落 army 写核 / 人物变更核 / due_turn）
- reload_state_from_db（只读 DB 无损接续）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    candidates_from_classifier_payload,
    cluster_by_kind,
)
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import reload_state_from_db
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


def _ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )


def _army_row(db, army_id):
    return db.conn.execute(
        "SELECT * FROM armies WHERE id=?", (army_id,),
    ).fetchone()


def _army_count(db):
    return int(db.conn.execute("SELECT COUNT(*) AS n FROM armies").fetchone()["n"])


def _stage_military_order(
    db, turn, *,
    target_id,
    assignee=None,
    station="",
    deadline_months=3,
    due_turn=0,
    office="",
    message=None,
    reply=None,
    actor=None,
):
    actor = actor or db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    assignee = assignee or actor
    payload = {
        "kind": "military_order",
        "target_id": target_id,
        "name": assignee,
    }
    if station:
        payload["station"] = station
    if deadline_months:
        payload["deadline_months"] = deadline_months
    if due_turn:
        payload["due_turn"] = due_turn
    if office:
        payload["office"] = office
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or f"调{target_id}部{station or '限期出战'}。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or f"臣请奉行军令。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


# ── catalog 挂点 ──────────────────────────────────────────────────────


def test_military_order_cluster_registered_with_materialize_fn():
    cluster = cluster_by_kind("military_order")
    assert cluster is not None
    assert cluster.materialize_fn is not None
    assert cluster in ACTION_CLUSTERS
    names = {f.name for f in cluster.fields}
    assert "target_id" in names
    assert "station" in names
    assert "deadline_months" in names


# ── 三锚例顺颁 ────────────────────────────────────────────────────────


def test_redeploy_existing_army_changes_station_only_after_verdict(game):
    """锚例1 调 X 部入卫：收夜只落案卷；顺颁后改既有军 station，不得 new_armies。"""
    db, state, content = game
    army_id = "guanning"
    before = _army_row(db, army_id)
    assert before is not None
    old_station = str(before["station"])
    new_station = "北直隶 / 京师"
    assert old_station != new_station
    armies_before = _army_count(db)
    actor = _active_ming(db, content)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        deadline_months=2,
        message=f"调关宁军入卫京师，着{actor.name}承办。",
        reply=f"臣请调关宁军入卫。请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "military_order"
    assert pending["target_id"] == army_id
    assert pending["station"] == new_station
    assert str(_army_row(db, army_id)["station"]) == old_station

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "military_order"
    assert dossier["status"] == "proposed"
    assert dossier["target_id"] == army_id
    assert str(_army_row(db, army_id)["station"]) == old_station, "收夜只落案卷，不得先改驻地"
    assert _army_count(db) == armies_before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    after = _army_row(db, army_id)
    assert str(after["station"]) == new_station
    assert _army_count(db) == armies_before, "既有军调驻不得写 new_armies"
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"
    assert int(db.get_decree_dossier(dossier["id"])["due_turn"] or 0) > int(state.turn)


def test_yizhen_lands_station_and_optional_office_after_verdict(game):
    """锚例2 移镇：顺颁后军队 station；职守真变才走人物变更核。"""
    db, state, content = game
    army_id = "xuan_da"
    before = _army_row(db, army_id)
    assert before is not None
    old_station = str(before["station"])
    new_station = "山西 / 大同"
    assert old_station != new_station
    actor = _active_ming(db, content)
    old_office = str(getattr(actor, "office", "") or "")
    new_office = "大同总兵" if old_office != "大同总兵" else "宣府总兵"
    armies_before = _army_count(db)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        office=new_office,
        deadline_months=3,
        message=f"着{actor.name}移镇大同，改任{new_office}。",
        reply="臣请移镇。请陛下定夺准驳。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert str(_army_row(db, army_id)["station"]) == old_station
    assert db.get_character_status(actor.name)[0] == "active"
    office_before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"]

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == new_station
    assert _army_count(db) == armies_before
    office_after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"]
    assert str(office_after) == new_office
    assert str(office_before) != str(office_after) or office_before == new_office


def test_deadline_sortie_lands_due_turn_without_battle_outcome(game):
    """锚例3 限期出战：案卷 due_turn 为限期载体；无胜负字段/效果。"""
    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    armies_before = _army_count(db)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="",  # 限期出战不改驻地
        deadline_months=3,
        message=f"着{actor.name}督关宁军三月内出战。",
        reply="臣请限期出师。请陛下定夺准驳。",
    )
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "military_order"
    assert int(pending.get("due_turn") or 0) == state.turn + 3 or int(
        pending.get("deadline_months") or 0
    ) == 3
    # 不得夹带胜负字段
    for banned in ("victory", "defeat", "battle_result", "胜负", "战果"):
        assert banned not in pending

    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert dossier["action_type"] == "military_order"
    assert int(dossier["due_turn"] or 0) == state.turn + 3
    assert str(_army_row(db, army_id)["station"]) == old_station

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    # 限期载体仍在案卷；驻地不变；无新建军
    got = db.get_decree_dossier(dossier["id"])
    assert int(got["due_turn"] or 0) == state.turn + 3
    assert got["status"] == "executing"
    assert str(_army_row(db, army_id)["station"]) == old_station
    assert _army_count(db) == armies_before
    payload = json.loads(got["payload_json"] or "{}")
    for banned in ("victory", "defeat", "battle_result", "胜负", "战果"):
        assert banned not in payload


# ── 各自负例 ──────────────────────────────────────────────────────────


def test_redeploy_existing_army_never_creates_new_army_row(game):
    """负例1：既有军调驻路径不得产生新 armies 行。"""
    db, state, content = game
    army_id = "jingying"
    armies_before = _army_count(db)
    ids_before = {
        str(r["id"]) for r in db.conn.execute("SELECT id FROM armies").fetchall()
    }
    actor = _active_ming(db, content)
    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="北直隶 / 通州",
        deadline_months=1,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert _army_count(db) == armies_before
    ids_after = {
        str(r["id"]) for r in db.conn.execute("SELECT id FROM armies").fetchall()
    }
    assert ids_after == ids_before


def test_yizhen_office_field_does_not_substitute_for_station(game):
    """负例2：只用任免字段不得代替军队驻地写面。"""
    db, state, content = game
    army_id = "jizhen"
    old_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    old_office = str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"] or "")
    new_office = "蓟辽总督" if old_office != "蓟辽总督" else "兵部尚书"

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="",  # 故意不给 station
        office=new_office,
        deadline_months=2,
        message=f"着{actor.name}改任{new_office}，移镇事宜另议。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == old_station, (
        "无 station 字段时不得借 office 改驻地"
    )


def test_deadline_sortie_without_future_due_fails_at_admission(game):
    """负例3：限期出战缺未来 due_turn → 成案失败，零效果。"""
    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    # 直接 stage 缺期限的军令候选（绕过 classifier 默认 deadline）
    pending_id = db.stage_directive_candidate(state.turn, actor.name, {
        "text": "着即日出战。",
        "actor": actor.name,
        "dossier_action_type": "military_order",
        "target_kind": "army",
        "target_id": army_id,
        "assignee": actor.name,
        # 无 due_turn / deadline_months
    })
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id], directive_status="draft",
    )
    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        d["pending_action_id"] == pending_id for d in db.list_decree_dossiers()
    )
    assert str(_army_row(db, army_id)["station"]) == old_station


# ── #521 r1：无期限调驻/移镇成案 + 同站 noop ───────────────────────────


def test_redeploy_without_deadline_admits_and_lands_station(game):
    """无期限调驻：admission 不得强索 due_turn；顺颁后只改 station。"""
    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    new_station = "北直隶 / 京师"
    assert old_station != new_station
    armies_before = _army_count(db)
    actor = _active_ming(db, content)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        deadline_months=0,
        message=f"调关宁军入卫京师，着{actor.name}承办。",
        reply="臣请调关宁军入卫。请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "military_order"
    assert int(pending.get("due_turn") or 0) == 0
    assert int(pending.get("deadline_months") or 0) == 0

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "military_order"
    assert dossier["status"] == "proposed"
    assert int(dossier["due_turn"] or 0) == 0
    assert str(_army_row(db, army_id)["station"]) == old_station

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == new_station
    assert _army_count(db) == armies_before
    got = db.get_decree_dossier(dossier["id"])
    assert got["status"] == "executing"
    assert int(got["due_turn"] or 0) == 0


def test_yizhen_without_deadline_admits_and_lands_station_office(game):
    """无期限移镇：无 due 亦成案；顺颁后 station + 职守变更。"""
    db, state, content = game
    army_id = "xuan_da"
    old_station = str(_army_row(db, army_id)["station"])
    new_station = "山西 / 大同"
    assert old_station != new_station
    actor = _active_ming(db, content)
    old_office = str(getattr(actor, "office", "") or "")
    new_office = "大同总兵" if old_office != "大同总兵" else "宣府总兵"
    armies_before = _army_count(db)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        office=new_office,
        deadline_months=0,
        message=f"着{actor.name}移镇大同，改任{new_office}。",
        reply="臣请移镇。请陛下定夺准驳。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert int(dossier["due_turn"] or 0) == 0
    assert str(_army_row(db, army_id)["station"]) == old_station

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == new_station
    assert _army_count(db) == armies_before
    office_after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"]
    assert str(office_after) == new_office
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"


def test_same_station_noop_still_lands_office_change(game):
    """同站调驻=成功 noop；伴随职守变更不得整批判后失败/回滚。"""
    db, state, content = game
    army_id = "guanning"
    current_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    old_office = str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"] or "")
    new_office = "宁远总兵" if old_office != "宁远总兵" else "辽东总兵"
    armies_before = _army_count(db)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=current_station,  # 目标站=当前站
        office=new_office,
        deadline_months=0,
        message=f"着{actor.name}仍镇{current_station}，改任{new_office}。",
        reply="臣请仍驻原镇、改任新职。请陛下定夺准驳。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert str(_army_row(db, army_id)["station"]) == current_station

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    # station 保持；职守变更必须落成；案卷 executing（不得因 noop 整批回滚）
    assert str(_army_row(db, army_id)["station"]) == current_station
    assert _army_count(db) == armies_before
    office_after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"]
    assert str(office_after) == new_office
    got = db.get_decree_dossier(dossier["id"])
    assert got["status"] == "executing"


# ── 打回零效果 ────────────────────────────────────────────────────────


def test_military_order_rejected_verdict_zero_effect(game):
    """打回：案卷在、station/office/due 效果零落。"""
    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    old_office = str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"] or "")
    armies_before = _army_count(db)

    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="北直隶 / 京师",
        office="京营提督" if old_office != "京营提督" else "戎政尚书",
        deadline_months=2,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    due_on_dossier = int(dossier["due_turn"] or 0)
    assert due_on_dossier > int(state.turn)

    db.apply_dossier_verdicts(
        state, [_rejected_verdict(dossier["id"])], content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == old_station
    assert str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (actor.name,),
    ).fetchone()["office"] or "") == old_office
    assert _army_count(db) == armies_before
    got = db.get_decree_dossier(dossier["id"])
    assert got["status"] in {"rejected", "closed", "proposed"} or got["status"] != "executing"
    # 打回不得把驻地写成目的地
    assert str(_army_row(db, army_id)["station"]) != "北直隶 / 京师" or old_station == "北直隶 / 京师"


# ── 正常/无诏结算 + restore ──────────────────────────────────────────


def test_military_order_survives_ordinary_and_no_edict_paths(game):
    """正常顺颁 / 无诏：无诏不改 station；顺颁后案卷·判决·station·due_turn 一致。"""
    from ming_sim.decree import project_dossiers_for_simulator

    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    new_station = "北直隶 / 京师"
    assert old_station != new_station
    actor = _active_ming(db, content)
    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        deadline_months=2,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    due = int(dossier["due_turn"] or 0)

    # 无诏路径：不调用顺颁 → 驻地不得变；打回不进推演上下文
    assert str(_army_row(db, army_id)["station"]) == old_station
    visible_no = []
    for row in db.list_decree_dossiers_for_simulation(state.turn):
        item = dict(row)
        if int(item["id"]) == int(dossier["id"]):
            item["settlement_verdict"] = "rejected"
        visible_no.append(item)
    rejected_ids = {
        int(r["id"]) for r in project_dossiers_for_simulator(
            visible_no, db=db, state=state,
        )
    }
    assert int(dossier["id"]) not in rejected_ids
    assert str(_army_row(db, army_id)["station"]) == old_station

    # 正常顺颁
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert str(_army_row(db, army_id)["station"]) == new_station
    got = db.get_decree_dossier(dossier["id"])
    assert int(got["due_turn"] or 0) == due
    assert got["status"] == "executing"

    visible = []
    for row in db.list_decree_dossiers_for_simulation(state.turn):
        item = dict(row)
        if int(item["id"]) == int(dossier["id"]):
            item["settlement_verdict"] = "promulgated"
        visible.append(item)
    projected = project_dossiers_for_simulator(visible, db=db, state=state)
    hit = next(r for r in projected if int(r["id"]) == int(dossier["id"]))
    assert hit["action_type"] == "military_order"
    assert hit["target_id"] == army_id


def test_military_order_restore_from_db_only_is_lossless(game):
    """restore 只读 DB 能接续 station、due_turn 与案卷。"""
    db, state, content = game
    army_id = "guanning"
    new_station = "北直隶 / 京师"
    actor = _active_ming(db, content)
    ctx = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        deadline_months=2,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    due = int(db.get_decree_dossier(dossier["id"])["due_turn"] or 0)
    assert str(_army_row(db, army_id)["station"]) == new_station

    # 污染内存后再 reload
    db.conn.execute(
        "UPDATE armies SET station=? WHERE id=?",
        (new_station, army_id),
    )  # keep DB truth
    reload_state_from_db(db, state, content=content)
    assert str(_army_row(db, army_id)["station"]) == new_station
    restored = db.get_decree_dossier(dossier["id"])
    assert restored["action_type"] == "military_order"
    assert restored["target_id"] == army_id
    assert int(restored["due_turn"] or 0) == due
    assert restored["status"] == "executing"


# ── #521 r2：成案前军队存在 / 同军独立候选 / 分类契约 / 复杂度 ──────────


def _military_pending_payloads(db, turn, *, target_id):
    rows = []
    for row in db.list_pending_actions(int(turn)):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "military_order":
            continue
        if str(payload.get("target_id") or "").strip() != target_id:
            continue
        rows.append((int(row["id"]), payload))
    return rows


def _military_field_zh(field_name: str) -> str:
    cluster = cluster_by_kind("military_order")
    assert cluster is not None
    for field in cluster.fields:
        if field.name == field_name:
            return field.zh
    raise AssertionError(f"military_order FieldSpec 缺少 {field_name}")


def test_fake_army_deadline_sortie_rejected_at_admission(game):
    """虚假 army id 催战：admission 成案前拒绝，不得进 proposed/executing。"""
    db, state, content = game
    fake_army = "no_such_army_521"
    assert _army_row(db, fake_army) is None
    actor = _active_ming(db, content)
    armies_before = _army_count(db)

    pending_id = db.stage_directive_candidate(state.turn, actor.name, {
        "text": f"着{actor.name}督{fake_army}三月内出战。",
        "actor": actor.name,
        "dossier_action_type": "military_order",
        "target_kind": "army",
        "target_id": fake_army,
        "assignee": actor.name,
        "due_turn": state.turn + 3,
    })
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id], directive_status="draft",
    )
    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        d["pending_action_id"] == pending_id for d in db.list_decree_dossiers()
    )
    assert _army_count(db) == armies_before


def test_two_independent_orders_same_army_do_not_overwrite(game):
    """同军两道独立军令：不得仅凭 target_id 当改草互相覆盖。"""
    db, state, content = game
    army_id = "guanning"
    actor = _active_ming(db, content)
    old_station = str(_army_row(db, army_id)["station"])
    new_station = "北直隶 / 京师"
    assert old_station != new_station

    first = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station=new_station,
        deadline_months=0,
        message=f"调关宁军入卫京师，着{actor.name}承办。",
        reply="臣请调关宁军入卫。请陛下定夺准驳。",
    )
    first_id = int(first.out["pending_action_id"])
    second = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="",
        deadline_months=3,
        message=f"着{actor.name}督关宁军三月内出战。",
        reply="臣请限期出师。请陛下定夺准驳。",
    )
    second_id = int(second.out["pending_action_id"])

    assert second_id != first_id
    staged = _military_pending_payloads(db, state.turn, target_id=army_id)
    assert len(staged) == 2, f"同军两道独立军令应各自成条，实际 {len(staged)} 条"
    first_payload = next(p for i, p in staged if i == first_id)
    second_payload = next(p for i, p in staged if i == second_id)
    assert first_payload.get("station") == new_station
    assert int(first_payload.get("due_turn") or 0) == 0
    assert not str(second_payload.get("station") or "").strip()
    assert int(second_payload.get("due_turn") or 0) == state.turn + 3 or int(
        second_payload.get("deadline_months") or 0
    ) == 3

    d1 = _close_night_dossier(db, state, content, first_id)
    d2 = _close_night_dossier(db, state, content, second_id)
    assert d1["id"] != d2["id"]
    db.apply_dossier_verdicts(state, [
        {"dossier_id": d1["id"], "decision": "promulgated"},
        {"dossier_id": d2["id"], "decision": "promulgated"},
    ], content=content)
    assert str(_army_row(db, army_id)["station"]) == new_station
    assert int(db.get_decree_dossier(d2["id"])["due_turn"] or 0) == state.turn + 3


def test_explicit_target_candidate_still_updates_named_military_order(game):
    """明确改草：target_candidate 点名才更新该道军令候选。"""
    db, state, content = game
    army_id = "guanning"
    actor = _active_ming(db, content)

    first = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="北直隶 / 京师",
        deadline_months=0,
    )
    other = _stage_military_order(
        db, state.turn,
        target_id=army_id,
        assignee=actor.name,
        station="",
        deadline_months=2,
    )
    first_id = int(first.out["pending_action_id"])
    other_id = int(other.out["pending_action_id"])
    assert first_id != other_id

    target_zh = _military_field_zh("target_id")
    candidate_zh = _military_field_zh("target_candidate")
    payload = {
        "动作类型": "军令·调遣",
        target_zh: army_id,
        "姓名": actor.name,
        "驻地": "山西 / 大同",
        "期限月数": 0,
        candidate_zh: str(first_id),
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    assert len(candidates) == 1
    assert candidates[0].get("target_candidate") == str(first_id)

    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message="前道入卫改调大同。",
        reply="臣请将前道军令改调大同。",
    )
    run_materialize_pipeline(ctx)
    assert int(ctx.out["pending_action_id"]) == first_id

    staged = dict(_military_pending_payloads(db, state.turn, target_id=army_id))
    assert staged[first_id]["station"] == "山西 / 大同"
    assert int(staged[other_id].get("deadline_months") or 0) == 2 or int(
        staged[other_id].get("due_turn") or 0
    ) == state.turn + 2


def test_military_order_classifier_materialize_keeps_target_kind_army(game):
    """真实 classifier→materialize：军令 target_kind 必须为 army，不得静默改写。"""
    db, state, content = game
    army_id = "guanning"
    actor = _active_ming(db, content)
    payload = {
        "动作类型": "军令·调遣",
        _military_field_zh("target_id"): army_id,
        "姓名": actor.name,
        "驻地": "北直隶 / 京师",
        "期限月数": 2,
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "military_order"
    assert candidates[0].get("target_id") == army_id

    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message=f"调关宁军入卫京师，着{actor.name}承办。",
        reply="臣请调关宁军入卫。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    pending_id = int(ctx.out["pending_action_id"])
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "military_order"
    assert pending["target_kind"] == "army"
    assert pending["target_id"] == army_id

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["target_kind"] == "army"
    assert dossier["target_id"] == army_id


def test_multi_draft_schema_example_uses_army_target_kind_for_military_order():
    """多旨稿 schema 示例：military_order 的目标类型须为 army（与票面一致）。"""
    import inspect

    import ming_sim.cli_backend as cli_backend

    source = inspect.getsource(cli_backend.extract_draft_intent)
    assert '"动作类型":"military_order","目标类型":"army"' in source.replace(" ", ""), (
        "多旨稿 schema 示例须写目标类型=army，不得 region"
    )
    assert '"动作类型":"military_order","目标类型":"region"' not in source.replace(" ", "")


def test_apply_military_order_verdict_effect_within_line_limit():
    """_apply_military_order_verdict_effect 本体 ≤100 行（职责拆到辅助单元）。"""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("ming_sim/db.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if (
                isinstance(item, ast.FunctionDef)
                and item.name == "_apply_military_order_verdict_effect"
            ):
                n = item.end_lineno - item.lineno + 1
                assert n <= 100, f"_apply_military_order_verdict_effect 仍超上限：{n} 行"
                return
    raise AssertionError("未找到 _apply_military_order_verdict_effect")
