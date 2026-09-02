"""#1624 结构化旨意共同契约：真实入口主干（禁 helper 直调冒充入口）。"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    assemble_structured_decree,
    structured_decree_guidance,
    structured_decree_rescript_option_lines,
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


def test_shared_contract_rejects_office_single_without_overwrite():
    """显式 office+single 不得被覆盖成 none；typed 拒绝。"""
    with pytest.raises(StructuredDecreeCombinationError, match="locality_scope=single"):
        assemble_structured_decree({
            "action_type": "assignment",
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "transaction_category": "督赈",
        })


def test_rescript_agents_inject_shared_contract(monkeypatch):
    """月末票拟/改票 agent 运行时注入共同契约，不靠静态 prompt 平行定义。"""
    import ming_sim.agents as agents_mod
    from ming_sim.models import LLMConfig

    captured: list[list] = []

    class _FakeAgent:
        def __init__(self, **kwargs):
            captured.append(list(kwargs.get("instructions") or []))

    monkeypatch.setattr(agents_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *a, **k: object())
    monkeypatch.setattr(
        agents_mod, "_ctx",
        lambda: type("C", (), {
            "game_world_prompt": "gw",
            "rescript_draft_prompt": "static-no-contract-copy",
        })(),
    )
    cfg = LLMConfig(model="test", api_key="k", base_url="http://x")
    agents_mod.create_rescript_draft_agent(cfg, object())
    agents_mod.create_rescript_revise_agent(cfg, object())
    assert len(captured) == 2
    guidance = structured_decree_guidance()
    option_lines = structured_decree_rescript_option_lines()
    for instructions in captured:
        blob = "\n".join(str(x) for x in instructions)
        assert guidance in blob
        assert option_lines in blob
        assert "督赈" in blob


def test_month_end_rescript_entry_owner_example(monkeypatch, game):
    """真实月末生成入口：LLM 产出 Owner 例 → validate 落 canonical，坏形不静默改写。"""
    import ming_sim.rescript_draft as rescript_mod

    db, _state, _content = game
    del db
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
    opt = drafts[0]["options"][0]
    assert opt["action_type"] == "assignment"
    assert opt["target_kind"] == "region"
    assert opt["target_id"] == "shaanxi"
    assert opt["region_id"] == "shaanxi"
    assert opt["locality_scope"] == "single"
    assert opt["transaction_category"] == "督赈"
    assert not str(opt.get("assignee_name") or "").strip()

    # 坏形 office+single：生成入口整批降级，不得静默改写后放行
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


def test_rescript_follow_draft_routes_hubu(game):
    """真实批红 follow_draft 入口：Owner 例未点将 → 职司路由户部（外部可见）。"""
    import ming_sim.rescript_actions as ra
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state, content = game
    # 省域 single 职司链需本省在任
    db.conn.execute(
        "UPDATE characters SET location='shaanxi' "
        "WHERE status='active' AND power_id='ming' AND office_type='户部'"
    )
    db.conn.commit()

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
    signal = created.get("execution_signal") or {}
    assert signal.get("chain") == "户部" or (
        (created.get("participant_roster") or [])
        and any(
            isinstance(e, dict)
            and str(e.get("tier") or "") == "主办"
            for e in (created.get("participant_roster") or [])
        )
    ), f"expected hubu duty route, signal={signal!r} roster={created.get('participant_roster')!r}"
    # chain 是职司路由的外部可见字段；若有则必须是户部
    if "chain" in signal:
        assert signal["chain"] == "户部"


def test_manual_owner_example_seal_advances(tracer_client, monkeypatch):
    """真实 Web 手工拟诏：Owner 例 → 盖玺推进；持久化 canonical + 户部路由。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    game.db.conn.execute(
        "UPDATE characters SET location='shaanxi' "
        "WHERE status='active' AND power_id='ming' AND office_type='户部'"
    )
    game.db.conn.commit()

    def backend(*_a, **_k):
        return _owner_manual_backend_json(), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    text = "着户部继续核查陕西赈务，按月具报。"
    response = tracer_client.post(
        "/api/directives", json={"text": text, "notes": ""},
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
        if str(d.get("region_id") or "") == "shaanxi"
        or str(json.loads(d.get("payload_json") or "{}").get("target_id") or "")
        == "shaanxi"
    ]
    assert matched, f"expected shaanxi dossier, got={dossiers!r}"
    payload = json.loads(matched[0]["payload_json"])
    assert payload.get("target_kind") == "region"
    assert payload.get("transaction_category") == "督赈"
    assert payload.get("locality_scope") == "single"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    signal = matched[0].get("execution_signal") or {}
    if "chain" in signal:
        assert signal["chain"] == "户部"


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
