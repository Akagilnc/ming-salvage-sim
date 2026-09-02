"""#1624 结构化旨意共同契约：真实入口主干（禁 helper 直调冒充入口；禁 prompt 文本锁）。"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    assemble_structured_decree,
)
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client  # noqa: F401

_OWNER_OPTION = {
    "label": "着户部继续核查陕西赈务，按月具报。",
    "hint": "督赈",
    "action_type": "assignment",
    "target_kind": "region",
    "target_id": "shaanxi",
    "locality_scope": "single",
    "region_id": "shaanxi",
    "assignee_name": "",
    "transaction_category": "督赈",
    "deadline_months": 2,
}


def _owner_manual_backend_json() -> str:
    return json.dumps({
        "拟旨意图": "拟旨",
        "动作类型": "assignment",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "地区ID": "shaanxi",
        "施行范围": "单省",
        "事务类别": "督赈",
        "承办人": "",
        "颁布方式": "普通",
        "参与人": [],
    }, ensure_ascii=False)


def _assert_hubu_duty_leads(db, dossier: dict) -> None:
    """外部可见：未点将督赈案卷的主办须为户部在任（职司路由结果）。"""
    roster = dossier.get("participant_roster") or []
    leads = [
        str(e.get("character_id") or "").strip()
        for e in roster
        if isinstance(e, dict) and str(e.get("tier") or "") == "主办"
    ]
    leads = [name for name in leads if name]
    assert leads, f"expected duty-route 主办, roster={roster!r} signal={dossier.get('execution_signal')!r}"
    for name in leads:
        row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (name,),
        ).fetchone()
        assert row is not None, f"主办未建档：{name!r}"
        assert str(row["office_type"] or "") == "户部", (
            f"主办 {name!r} office_type={row['office_type']!r}，期望户部"
        )
    signal = dossier.get("execution_signal") or {}
    # 出缺怠办时 chain 亦须为户部；有主办时 signal 可为空
    if signal.get("chain") not in (None, ""):
        assert signal["chain"] == "户部"


def _seed_hubu_in_shaanxi(db) -> None:
    db.conn.execute(
        "UPDATE characters SET location='shaanxi' "
        "WHERE status='active' AND power_id='ming' AND office_type='户部'"
    )
    db.conn.commit()


def test_shared_contract_rejects_office_single_without_overwrite():
    """显式 office+single 不得被覆盖成 none；typed 拒绝。"""
    with pytest.raises(StructuredDecreeCombinationError):
        assemble_structured_decree({
            "action_type": "assignment",
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "transaction_category": "督赈",
        })


def test_month_end_entry_owner_canonical(monkeypatch, game):
    """真实月末生成入口：Owner 例落 canonical；坏形整批降级。

    改票真实入口（return_revise → prepare_rescript_prewrite）由
    tests/test_pihong_dossier_1490.py::test_657_revise_deliberate_strict_contracts_zero_write_on_bad_shape
    的 Owner 例路径覆盖，本测不另建平行夹具、不直调 helper 冒充入口。
    """
    import ming_sim.rescript_draft as rescript_mod

    del game
    owner_item = {
        "title": "陕西告饥",
        "context": "秦地赤旱，饥民待哺，急须责成赈济。",
        "options": [
            dict(_OWNER_OPTION),
            {
                **_OWNER_OPTION,
                "label": "缓征以苏民力",
                "hint": "先赈后征",
                "transaction_category": "钱粮",
            },
        ],
    }

    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"items": [owner_item]}, ensure_ascii=False),
    )
    drafts = rescript_mod.generate_rescript_draft(
        object(),
        {
            "active_issues": [],
            "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
            "army_targets": [],
        },
        1,
    )
    assert drafts is not None and len(drafts) == 1
    monthly = drafts[0]["options"][0]
    assert monthly["action_type"] == "assignment"
    assert monthly["target_kind"] == "region"
    assert monthly["target_id"] == "shaanxi"
    assert monthly["region_id"] == "shaanxi"
    assert monthly["locality_scope"] == "single"
    assert monthly["transaction_category"] == "督赈"
    assert not str(monthly.get("assignee_name") or "").strip()

    # 坏形 office+single：月末生成入口整批降级，不得静默改写后放行
    bad = dict(owner_item)
    bad["options"] = [
        {
            **_OWNER_OPTION,
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "region_id": "",
        },
        dict(_OWNER_OPTION),
    ]
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"items": [bad]}, ensure_ascii=False),
    )
    assert rescript_mod.generate_rescript_draft(
        object(),
        {
            "active_issues": [],
            "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
            "army_targets": [],
        },
        1,
    ) is None


def test_layer_a_helper_rejects_office_single_boundary():
    """层 A helper 最低层边界：office+single  typed 拒绝（非改票入口证明）。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    with pytest.raises(StructuredDecreeCombinationError):
        normalize_rescript_layer_a_option({
            **_OWNER_OPTION,
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "region_id": "",
        }, generation_admission=True)


def test_rescript_follow_draft_routes_hubu(game):
    """真实批红 follow_draft：Owner 例未点将 → 主办为户部在任。"""
    import ming_sim.rescript_actions as ra
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state, content = game
    _seed_hubu_in_shaanxi(db)

    opt = normalize_rescript_layer_a_option(dict(_OWNER_OPTION))
    alt = normalize_rescript_layer_a_option({
        **_OWNER_OPTION, "label": "缓征", "hint": "b", "transaction_category": "钱粮",
    })
    db.save_rescript_drafts(int(state.turn), [{
        "title": "陕西告饥",
        "context": "秦地赤旱",
        "options": [opt, alt],
        "actor_name": "杨嗣昌",
        "actor_office": "兵部尚书",
        "actor_faction": "东林",
    }])
    db.conn.commit()
    urgent = next(
        r for r in db.list_rescript_desk(int(state.turn))
        if r.get("kind") == "rescript_draft" and r.get("title") == "陕西告饥"
    )
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": urgent["decision_key"],
        "action": "follow_draft",
        "draft_capability": opt["draft_capability"],
        "label": opt["label"],
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.list_decree_dossiers()
    assert len(after) > before
    created = after[-1]
    payload = json.loads(created.get("payload_json") or "{}")
    assert payload.get("target_kind") == "region"
    assert payload.get("target_id") == "shaanxi"
    assert payload.get("region_id") == "shaanxi"
    assert payload.get("locality_scope") == "single"
    assert payload.get("transaction_category") == "督赈"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    _assert_hubu_duty_leads(db, created)


def test_manual_owner_example_seal_advances(tracer_client, monkeypatch):
    """真实 Web 手工拟诏：Owner 例 → 盖玺；持久化 canonical + 户部主办。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    _seed_hubu_in_shaanxi(game.db)

    def backend(*_a, **_k):
        return _owner_manual_backend_json(), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    response = tracer_client.post(
        "/api/directives",
        json={"text": "着户部继续核查陕西赈务，按月具报。", "notes": ""},
    )
    assert response.status_code == 200, response.text
    turn_before = game.state.turn
    _post_issue_stream(
        tracer_client, expected_turn=turn_before, step="#1624 owner seal",
    )
    assert game.state.turn == turn_before + 1
    dossiers = [dict(d) for d in game.db.list_decree_dossiers()]
    matched = [
        d for d in dossiers
        if str(json.loads(d.get("payload_json") or "{}").get("target_id") or "")
        == "shaanxi"
        and str(json.loads(d.get("payload_json") or "{}").get("transaction_category") or "")
        == "督赈"
    ]
    assert matched, f"expected shaanxi 督赈 dossier, got={dossiers!r}"
    payload = json.loads(matched[0]["payload_json"])
    assert payload.get("target_kind") == "region"
    assert payload.get("locality_scope") == "single"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    _assert_hubu_duty_leads(game.db, matched[0])


def test_fieldspec_categories_derive_from_duty_routes():
    """FieldSpec 事务类别闭集 = duty_routes 派生，无手抄第二份。"""
    from ming_sim.action_clusters import cluster_by_kind
    from ming_sim.executor_routing import duty_route_categories

    cats = duty_route_categories()
    assert "督赈" in cats
    for kind in ("assignment", "punishment", "military_order"):
        cluster = cluster_by_kind(kind)
        spec = next(f for f in cluster.fields if f.name == "transaction_category")
        assert frozenset(spec.allowed or ()) == cats
