"""#1931：删荐人切片；荐人受理与任命前校验只留账上事实拒收。

Seams:
- prepare_scene_materials / write_identity_materials（材料目录）
- dispatch_declaration（荐人受理）
- close_night + resolve_turn 月链（应允、收夜、颁布落账）
"""

from __future__ import annotations

import json

import pytest

from ming_sim.audience_night import close_night, open_night, summon_enter
from ming_sim.audience_translate import normalize_audience_declaration
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.materials import (
    list_materials,
    prepare_scene_materials,
    release_material_tree,
)
from tests.material_helpers import prepare_identity_materials
from tests.test_audience_translate_1837_reopen import _player_month


def _no_recommendation_slice(paths) -> None:
    assert not any("可荐人" in path or path.rstrip("/").endswith("/荐人") or "/荐人/" in path
                   for path in paths)


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


def _dispatch_recommend(db, state, *, minister, target, office, reason, night_id):
    return dispatch_declaration(
        db, state,
        _recommend_decl(minister, target, office, reason),
        minister_name=minister, night_id=night_id,
    )


def _applied_payload(db, result):
    return json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()["payload_json"])


def _non_self_target(content, minister_name):
    return next(
        c for c in content.characters.values()
        if c.name != minister_name and c.office_type not in ("后宫", "宗藩", "未仕")
    )


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
    result = _dispatch_recommend(
        db, state,
        minister=yang.name, target=qiao.name, office=office,
        reason="刑名老成，可转掌礼部。", night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    staged_id = int(result.commissions.applied[0]["id"])
    payload = _applied_payload(db, result)
    assert payload["recommendation"]["recommender"] == yang.name
    assert payload["recommendation"]["candidate"]["name"] == qiao.name

    db.mark_pending_night_approved([staged_id], night_id=int(night["id"]))
    close_night(db, state, night_id=int(night["id"]), content=content)

    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?",
        (staged_id,),
    ).fetchone()
    assert dossier is not None
    _player_month(db, state, content, monkeypatch, int(dossier["id"]))
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (qiao.name,),
    ).fetchone()["office"] == office


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
    result = _dispatch_recommend(
        db, state,
        minister=yang.name, target=qiao.name, office="刑部尚书",
        reason="旧部可起。", night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}


def test_future_debut_recommendation_is_fact_rejected(game):
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    target = _non_self_target(content, yang.name)
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', debut_year=?, debut_month=1 "
        "WHERE name=?",
        (state.year + 1, target.name),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = _dispatch_recommend(
        db, state,
        minister=yang.name, target=target.name, office="巡盐御史",
        reason="来日可期。", night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert result.commissions.rejected[0].category in {"invalid_state", "hallucinated_id"}


@pytest.mark.parametrize(
    "reason_code,expected_kind,reason",
    [
        ("被顶替", "荐起复", "候铨可起。"),
        ("登场", "荐在职", "现职可调。"),
    ],
    ids=["displaced-recovery", "hearing-in-post"],
)
def test_hearing_title_recommendation_kind_via_dispatch(
    game, reason_code, expected_kind, reason,
):
    """ADR 0009：听用候铨 + reason_code 决定 荐起复／荐在职；经受理真入口落载荷。"""
    db, state, content = game
    yang = content.characters["杨嗣昌"]
    target = _non_self_target(content, yang.name)
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code=? "
        "WHERE name=?",
        (reason_code, target.name),
    )
    db.conn.commit()
    night = open_night(db, state)
    result = _dispatch_recommend(
        db, state,
        minister=yang.name, target=target.name, office="巡盐御史",
        reason=reason, night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    payload = _applied_payload(db, result)
    assert payload["recommendation"]["candidate"]["candidate_kind"] == expected_kind


def test_off_ledger_recommender_is_fact_rejected_with_zero_side_effects(game):
    """#1931 F1：账外荐者拒收；不落暂存、不落荐人事件、不落关系边。"""
    db, state, content = game
    qiao = content.characters["乔允升"]
    night = open_night(db, state)
    phantom = "账外荐者"
    # 调用上下文用在册大臣；声明里的荐者是账外名。
    result = dispatch_declaration(
        db, state,
        _recommend_decl(phantom, qiao.name, "礼部尚书", "臣闻其贤。"),
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
