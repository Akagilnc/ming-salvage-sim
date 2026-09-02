"""#1624 结构化旨意共同契约：最短 shared-seam + 真实 Web 主干。"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.structured_decree import assemble_structured_decree
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client  # noqa: F401


@pytest.mark.parametrize(
    "raw,expect_action_key",
    [
        (
            {
                "动作类型": "assignment",
                "目标类型": "region",
                "目标ID": "shaanxi",
                "地区ID": "shaanxi",
                "施行范围": "单省",
                "事务类别": "督赈",
                "承办人": "",
            },
            "action_type",
        ),
        (
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
            "action_type",
        ),
    ],
    ids=["manual_zh_transport", "rescript_layer_a_transport"],
)
def test_shared_contract_owner_example_transports(raw, expect_action_key):
    """共同接缝：两种入口运输形 → Owner canonical（一条主干）。"""
    out = assemble_structured_decree(raw, validate=True)
    assert out[expect_action_key] == "assignment"
    assert out["dossier_action_type"] == "assignment"
    assert out["target_kind"] == "region"
    assert out["target_id"] == "shaanxi"
    assert out["region_id"] == "shaanxi"
    assert out["locality_scope"] == "single"
    assert out["transaction_category"] == "督赈"
    assert not str(out.get("assignee_name") or out.get("assignee") or "").strip()


def test_shared_contract_rejects_office_single_without_overwrite():
    """显式 office+single 不得被覆盖成 none；响亮拒绝。"""
    with pytest.raises(ValueError, match="locality_scope=single"):
        assemble_structured_decree({
            "action_type": "assignment",
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "transaction_category": "督赈",
        })


def test_manual_entry_consumes_shared_assemble(game, monkeypatch):
    """手工入口独有：capture 走共同 assemble，不平行重锁全套字段。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game

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
    # 入口边界：draft 载荷键 + 无人物 assignee（承办归职司路由）
    assert manual["dossier_action_type"] == "assignment"
    assert manual["target_kind"] == "region"
    assert not str(manual.get("assignee") or "").strip()


def test_manual_owner_example_seal_advances(tracer_client, monkeypatch):
    """真实 Web：手工拟诏 owner 例句 → 盖玺 → 月份推进（外部可见结果）。"""
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
