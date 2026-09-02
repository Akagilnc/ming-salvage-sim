"""#1624 结构化旨意共同契约：三入口同一 canonical + 手工拟诏 Web tracer。"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.structured_decree import (
    assemble_structured_decree,
    validate_structured_decree_combination,
)
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client  # noqa: F401

# Owner 例句 canonical（issuecomment-5502331646）
_OWNER_CANONICAL = {
    "action_type": "assignment",
    "target_kind": "region",
    "target_id": "shaanxi",
    "region_id": "shaanxi",
    "locality_scope": "single",
    "transaction_category": "督赈",
}


def _assert_owner_shape(payload: dict) -> None:
    assert payload["target_kind"] == "region"
    assert payload["target_id"] == "shaanxi"
    assert payload["region_id"] == "shaanxi"
    assert payload["locality_scope"] == "single"
    assert payload["transaction_category"] == "督赈"
    action = str(
        payload.get("action_type") or payload.get("dossier_action_type") or ""
    )
    assert action == "assignment"
    # 不得写入人物 assignee；户部仅由职司路由
    for key in ("assignee", "assignee_id", "assignee_name"):
        assert not str(payload.get(key) or "").strip()


@pytest.mark.parametrize(
    "raw",
    [
        # 手工/召对中文运输键
        {
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "地区ID": "shaanxi",
            "施行范围": "单省",
            "事务类别": "督赈",
            "承办人": "",
        },
        # 月末票拟层 A 英键
        {
            "action_type": "assignment",
            "target_kind": "region",
            "target_id": "shaanxi",
            "region_id": "shaanxi",
            "locality_scope": "single",
            "transaction_category": "督赈",
            "assignee_name": "",
            "label": "着户部继续核查陕西赈务，按月具报。",
            "hint": "督赈",
        },
        # 已是 durable 形
        dict(_OWNER_CANONICAL),
    ],
    ids=["manual_zh", "rescript_layer_a", "durable_en"],
)
def test_shared_contract_owner_example_three_transports(raw):
    """三入口运输形 → 同一 canonical（最短 shared-contract 主干）。"""
    out = assemble_structured_decree(raw, validate=True)
    _assert_owner_shape(out)


def test_shared_contract_rejects_office_single_mask():
    """office+single 不得被覆盖成 office+none；须响亮拒绝。"""
    with pytest.raises(ValueError, match="locality_scope=single"):
        assemble_structured_decree({
            "action_type": "assignment",
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "transaction_category": "督赈",
        })


def test_layer_a_and_mapper_and_manual_same_canonical(game, monkeypatch):
    """薄入口适配：层 A / mapper / capture_manual 落同一 owner canonical。"""
    from ming_sim.rescript_actions import map_rescript_option_or_choice
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    layer = normalize_rescript_layer_a_option({
        "label": "着户部继续核查陕西赈务，按月具报。",
        "hint": "按月具报",
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "assignee_name": "",
        "transaction_category": "督赈",
    })
    _assert_owner_shape(layer)

    mapped = map_rescript_option_or_choice(layer)
    _assert_owner_shape(mapped)
    assert mapped["dossier_action_type"] == "assignment"

    def backend(*_a, **_k):
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
        }, ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    manual = cli_backend.capture_manual_directive_payload(
        "着户部继续核查陕西赈务，按月具报。",
        None,
        db=db,
        content=content,
    )
    _assert_owner_shape(manual)
    assert manual["dossier_action_type"] == "assignment"
    # 三入口核心字段一致
    for key in (
        "target_kind", "target_id", "region_id",
        "locality_scope", "transaction_category",
    ):
        assert layer[key] == mapped[key] == manual[key]


def test_manual_owner_example_seal_advances(tracer_client, monkeypatch):
    """真实 Web：手工拟诏 owner 例句 → 盖玺 → 月份推进。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None

    def backend(*_a, **_k):
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
        }, ensure_ascii=False), 1

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
    assert dossiers, "盖玺后须成案"
    # 陕西差务成案（payload 与行级 region_id 同源）
    matched = [
        d for d in dossiers
        if str(d.get("region_id") or "") == "shaanxi"
        or str(json.loads(d.get("payload_json") or "{}").get("target_id") or "") == "shaanxi"
    ]
    assert matched, f"expected shaanxi dossier, got={dossiers!r}"
    payload = json.loads(matched[0]["payload_json"])
    assert payload.get("locality_scope") == "single"
    assert payload.get("target_kind") == "region"
    assert payload.get("target_id") == "shaanxi"
    assert payload.get("transaction_category") == "督赈"
    # 户部职司路由：主办来自 duty_routes，非人物 assignee 字段
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
