"""#1685 manual directive region locality via assembly write + real HTTP tracer.

#1849：独立手拟新增 Web 入口（POST /api/directives）已随拟诏台「御笔自拟」控件退役；
草稿改经现行 capture 核 + session 落桌（召对拟旨同一写入），下游封存/案卷断言不变。
"""

from __future__ import annotations

import json

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client


def _extracted(scope, person="毕自严"):
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "地区ID": "shaanxi",
        "颁布方式": "普通",
        "施行范围": scope,
        "承办人": person,
        "参与人": [{"character_id": person, "tier": "主办"}],
    }


def test_manual_directive_region_assembly_writes_single_and_advances(
    tracer_client, monkeypatch,
):
    """#1624/#1685 主干：LLM 抽 region+单省 → 共同契约落 single → 封存推进。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    calls = []

    def backend(*_args, **_kwargs):
        calls.append(1)
        return json.dumps(_extracted("单省"), ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    # #1849：独立手拟新增 Web 口已退役；经现行 capture 核 + session 落草案
    # （召对拟旨同一条 turn_directives 写入）。
    from tests.directive_seed_helpers import seed_manual_draft

    assert seed_manual_draft(game.session, "着依旨施行。") > 0
    assert len(calls) == 1
    turn_before = game.state.turn
    _post_issue_stream(
        tracer_client, expected_turn=turn_before, step="#1685 locality issue/stream",
    )
    assert game.state.turn == turn_before + 1
    dossiers = game.db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["region_id"] == "shaanxi"
    payload = json.loads(dossiers[0]["payload_json"])
    assert payload["locality_scope"] == "single"
    assert [p["character_id"] for p in payload["participant_roster"]] == ["毕自严"]
