"""#1620：手动旨稿协饷 target 在承重落库前 canonicalize（关宁军→guanning）。

真实 HTTP 入口 POST /api/directives；LLM 边界返回冻结 typed 协饷 intent
（target_id=关宁军）；断言 turn_directives 首次承重 payload 与 dossier 均为
guanning，再经真实 verdict/apply 销欠恰好一次并 turn+1。
不得从 dossier 下游手工注入 guanning。
"""

from __future__ import annotations

import json

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client


_XIEXANG_TEXT = "着户部准拨关宁军饷十五万两，以清积欠。"


def _extracted_xiexang_display_name():
    """冻结 typed 协饷 intent：target 用展示名，admission 须 canonicalize。"""
    return {
        "拟旨意图": "拟旨",
        "动作类型": "grant_allocation",
        "恩赏拨帑": "协饷",
        "用途": "补饷",
        "目标类型": "army",
        "目标": "关宁军",
        "金额": 15,
        "账户": "国库",
        "颁布方式": "普通",
    }


def test_manual_directive_xiexang_canonicalizes_army_id_and_settles(
    tracer_client, monkeypatch,
):
    """#1620 主干：关宁军→guanning 入卷；真实过月扣库/销欠一次。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None

    # 种子欠饷，供补饷销欠可观察
    game.db.conn.execute(
        "UPDATE armies SET arrears=80, province_pay_arrears=0, "
        "central_pay_arrears=80 WHERE id='guanning'"
    )
    game.db.conn.commit()
    before_arrears = float(
        game.db.conn.execute(
            "SELECT arrears FROM armies WHERE id='guanning'"
        ).fetchone()["arrears"]
    )

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)

    def backend(prompt, *_args, tag="", **_kwargs):
        if "请据此拟旨" not in str(prompt) and _XIEXANG_TEXT not in str(prompt):
            return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)
        return (json.dumps(_extracted_xiexang_display_name(), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)

    response = tracer_client.post(
        "/api/directives", json={"text": _XIEXANG_TEXT, "notes": ""},
    )
    assert response.status_code == 200, response.text

    # 首次承重：turn_directives.dossier_payload_json 已是 canonical guanning
    row = game.db.conn.execute(
        "SELECT id, dossier_payload_json, text, source FROM turn_directives "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    payload = json.loads(str(row["dossier_payload_json"] or "{}"))
    assert payload.get("grant_action") == "协饷"
    assert payload.get("target_kind") == "army"
    assert payload.get("target_id") == "guanning", (
        f"admission 须 canonicalize，拒展示名残留：{payload.get('target_id')!r}"
    )
    assert int(payload.get("amount") or 0) == 15
    assert str(payload.get("account") or "") == "国库"

    turn_before = game.state.turn
    _post_issue_stream(
        tracer_client, expected_turn=turn_before, step="#1620 xiexang issue/stream",
    )
    assert game.state.turn == turn_before + 1

    dossiers = game.db.list_decree_dossiers()
    xiexang = [
        d for d in dossiers
        if str(d.get("action_type") or "") == "grant_allocation"
        and str(d.get("target_id") or "") == "guanning"
    ]
    assert len(xiexang) == 1, f"dossier 须唯一 guanning 协饷案：{dossiers!r}"
    d_payload = json.loads(str(xiexang[0].get("payload_json") or "{}"))
    assert d_payload.get("target_id") == "guanning"
    assert d_payload.get("grant_action") == "协饷"

    # 扣库/销欠恰好一次（补饷 economy_ledger）
    moves = game.db.conn.execute(
        "SELECT delta, purpose, target_id FROM economy_ledger "
        "WHERE purpose='补饷' AND target_kind='army' AND target_id='guanning'"
    ).fetchall()
    assert len(moves) == 1, f"补饷流水须恰好一次：{moves!r}"
    assert int(moves[0]["delta"]) == -15

    after_arrears = float(
        game.db.conn.execute(
            "SELECT arrears FROM armies WHERE id='guanning'"
        ).fetchone()["arrears"]
    )
    # 销欠生效：欠饷下降。月度 tick 可能另增欠，不锁绝对差额。
    assert after_arrears < before_arrears


def test_capture_xiexang_without_db_keeps_explicit_fields(monkeypatch):
    """无 db 时仍走 explicit 验形（兼容旧调用）；不静默升格 army id。"""
    import ming_sim.cli_backend as cli_backend

    monkeypatch.setattr(
        cli_backend,
        "_run_backend_for_config",
        lambda *_a, **_k: (
            json.dumps(_extracted_xiexang_display_name(), ensure_ascii=False), 1,
        ),
    )
    payload = cli_backend.capture_manual_directive_payload(_XIEXANG_TEXT, None)
    assert payload.get("grant_action") == "协饷"
    assert payload.get("target_id") == "关宁军"
    assert int(payload.get("amount") or 0) == 15
