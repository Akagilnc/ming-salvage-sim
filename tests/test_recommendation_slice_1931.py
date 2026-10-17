"""#1931：删荐人切片；荐人受理与任命前校验只留账上事实拒收。

Seams:
- prepare_scene_materials / write_identity_materials（材料目录）
- dispatch_declaration（荐人受理）
- close_night + resolve_turn 月链（应允、收夜、颁布落账）
"""

from __future__ import annotations

import json

from ming_sim.audience_night import close_night, open_night, summon_enter
from ming_sim.audience_translate import normalize_audience_declaration
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.materials import (
    list_materials,
    prepare_scene_materials,
    release_material_tree,
)
from tests.conftest import wait_for_background_jobs
from tests.month_chain_helpers import make_light_session
from tests.material_helpers import prepare_identity_materials


def _no_recommendation_slice(paths) -> None:
    assert not any("可荐人" in path or path.rstrip("/").endswith("/荐人") or "/荐人/" in path
                   for path in paths)


def test_single_and_scene_materials_have_no_recommendation_slice(game, tmp_path):
    db, state, content = game
    yang = content.characters["杨嗣昌"]

    identity = prepare_identity_materials(
        db, state, yang, dest_root=tmp_path / "identity",
    )
    try:
        _no_recommendation_slice(list_materials(identity.root))
    finally:
        release_material_tree(identity.root)

    night = open_night(db, state)
    summon_enter(db, int(night["id"]), yang.name)
    scene = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    try:
        _no_recommendation_slice(list_materials(scene.root))
    finally:
        release_material_tree(scene.root)


def test_cross_faction_recommendation_accepts_and_lands_office_via_month_chain(
    game, monkeypatch,
):
    """一条贯穿：跨派受理 → 应允收夜 → 月链颁布 → 官职落账。"""
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    qiao = content.characters["乔允升"]
    assert yang.faction != qiao.faction
    night = open_night(db, state)
    office = "礼部尚书"
    decl = normalize_audience_declaration({
        "commissions": [{
            "text": f"荐{qiao.name}改任{office}",
            "appointment": {
                "name": qiao.name, "office": office, "appoint_action": "任命",
            },
            "recommendation": {
                "recommender": yang.name,
                "reason": "刑名老成，可转掌礼部。",
            },
        }],
    })
    result = dispatch_declaration(
        db, state, decl, minister_name=yang.name, night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    staged_id = int(result.commissions.applied[0]["id"])
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["payload_json"])
    assert payload["recommendation"]["recommender"] == yang.name
    assert payload["recommendation"]["candidate"]["name"] == qiao.name

    db.mark_pending_night_approved([staged_id], night_id=int(night["id"]))
    close_night(db, state, night_id=int(night["id"]), content=content)

    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?",
        (staged_id,),
    ).fetchone()
    assert dossier is not None
    dossier_id = int(dossier["id"])

    from ming_sim.decree_forecast import decree_ref_for_dossier, stage_declaration
    from tests.month_chain_helpers import empty_rescript_response
    import ming_sim.month_chain as month_chain

    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", empty_rescript_response)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate._default_month_translate_runner",
        lambda *a, **k: {"effects": {}},
    )
    stage_declaration(
        db,
        decree_ref=decree_ref_for_dossier(db, db.dossiers.get(dossier_id)),
        declaration={"effects": {}},
        turn=int(state.turn),
        verdict={"decision": "promulgated"},
        forecast_text="",
    )
    session = make_light_session(db, state, content)
    before = int(state.turn)
    advanced = session.resolve_turn(allow_empty_decree=True)
    wait_for_background_jobs(db)
    if getattr(advanced, "stage", None) == "gazette":
        db.save_turn_report(state, "月报", title="月报", public_body="月报")
        advanced = session.resolve_turn(allow_empty_decree=True)
        wait_for_background_jobs(db)
    assert advanced.advanced and int(state.turn) > before
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (qiao.name,),
    ).fetchone()["office"] == office


def _recommend_decl(recommender, target, office, reason):
    return normalize_audience_declaration({
        "commissions": [{
            "text": f"荐{target}任{office}",
            "appointment": {
                "name": target, "office": office, "appoint_action": "任命",
            },
            "recommendation": {
                "recommender": recommender,
                "reason": reason,
            },
        }],
    })


def test_deceased_recommendation_is_fact_rejected(game):
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    qiao = content.characters["乔允升"]
    db.conn.execute(
        "UPDATE characters SET status='dead', office='' WHERE name=?",
        (qiao.name,),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = dispatch_declaration(
        db, state,
        _recommend_decl(yang.name, qiao.name, "刑部尚书", "旧部可起。"),
        minister_name=yang.name, night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}


def test_future_debut_recommendation_is_fact_rejected(game):
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    target = next(
        c for c in content.characters.values()
        if c.name != yang.name and c.office_type not in ("后宫", "宗藩", "未仕")
    )
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', debut_year=?, debut_month=1 "
        "WHERE name=?",
        (state.year + 1, target.name),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = dispatch_declaration(
        db, state,
        _recommend_decl(yang.name, target.name, "巡盐御史", "来日可期。"),
        minister_name=yang.name, night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}


def test_displaced_holder_recommendation_kind_is_recovery_via_dispatch(game):
    """ADR 0009：听用候铨+被顶替 → 荐起复；经受理真入口落载荷。"""
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    target = next(
        c for c in content.characters.values()
        if c.name != yang.name and c.office_type not in ("后宫", "宗藩", "未仕")
    )
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='被顶替' "
        "WHERE name=?",
        (target.name,),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = dispatch_declaration(
        db, state,
        _recommend_decl(yang.name, target.name, "巡盐御史", "候铨可起。"),
        minister_name=yang.name, night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()["payload_json"])
    assert payload["recommendation"]["candidate"]["candidate_kind"] == "荐起复"


def test_hearing_title_without_displacement_is_in_post_via_dispatch(game):
    """ADR 0009：听用候铨但非被顶替 → 荐在职。"""
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    target = next(
        c for c in content.characters.values()
        if c.name != yang.name and c.office_type not in ("后宫", "宗藩", "未仕")
    )
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='登场' "
        "WHERE name=?",
        (target.name,),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = dispatch_declaration(
        db, state,
        _recommend_decl(yang.name, target.name, "巡盐御史", "现职可调。"),
        minister_name=yang.name, night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()["payload_json"])
    assert payload["recommendation"]["candidate"]["candidate_kind"] == "荐在职"


def test_off_ledger_recommender_is_fact_rejected_with_zero_side_effects(game):
    """#1931 F1：账外荐者拒收；不落暂存、不落荐人事件、不落关系边。"""
    db, state, content = game
    qiao = content.characters["乔允升"]
    night = open_night(db, state)
    phantom = "账外荐者"
    decl = normalize_audience_declaration({
        "commissions": [{
            "text": f"荐{qiao.name}改任礼部尚书",
            "appointment": {
                "name": qiao.name, "office": "礼部尚书", "appoint_action": "任命",
            },
            "recommendation": {
                "recommender": phantom,
                "reason": "臣闻其贤。",
            },
        }],
    })
    # 调用上下文用在册大臣；声明里的荐者是账外名。
    result = dispatch_declaration(
        db, state, decl,
        minister_name=content.characters["杨嗣昌"].name,
        night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM pending_actions",
    ).fetchone()["n"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM recommendation_events",
    ).fetchone()["n"] == 0
    assert db.person_logs.get_relation_edge_events() == []
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (phantom,),
    ).fetchone() is None
