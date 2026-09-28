"""#1774 军饷目标：场景声明与手拟各走现役写口的可物化准入。

场景转译输出 typed 军队 ID；不可解析的声明不得暂存或成案。
现役 Web 召对／确认／收夜与手拟端点分别验证可见的军饷案卷。
"""

from __future__ import annotations

import json

import ming_sim.cli_backend as cli_backend
from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent

AUDIENCE_MESSAGE = (
    "着户部从国库拨银十五万两，解赴关宁军前专补欠饷。卿即拟旨呈览。"
)
MANUAL_TEXT = "命户部从国库核拨欠饷十五万两，解赴关宁军前，不得加派于民。"


def _canned_draft(target: str) -> dict:
    """真实局同形 draft_intent 返回（附件 1772 trace）。"""
    return {
        "拟旨意图": "拟旨",
        "动作类型": "grant_allocation",
        "entries": [],
        "恩赏拨帑": "协饷",
        "姓名": "郭允厚",
        "目标": target,
        "目标类型": "army",
        "金额": 15,
        "账户": "国库",
        "用途": "补饷",
        "拨付节奏": "一次性",
        "颁布方式": "ordinary",
        "执行面": "in_transit",
        "目标候选": target,
        "目标ID": "",
        "地区ID": "",
        "施行范围": "",
        "事务类别": "",
        "承办人": "郭允厚",
        "参与人": [],
        "期限月数": None,
        "目标案卷ID": None,
    }


def _active_ming_minister(db, content, *, office: str | None = None):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and (office is None or getattr(ch, "office_type", "") == office)
        and db.get_character_status(ch.name)[0] == "active"
    )


# ── 验收 2：召对应允收夜 ──────────────────────────────────────────────


def test_audience_grounded_army_pay_lands_through_close_night(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """拟旨 → 皇帝应允 → 收夜 → GET state；目标/金额正确、无重复。"""
    from fastapi.testclient import TestClient

    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state, _post_issue_stream, _resolve_decisions_via_stream, _stub_outer_llm_seams,
        _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes
    from tests.test_audience_background import RunContent, RunOutput

    class _Agent:
        def __init__(self):
            self._n = 0

        def run(self, *_a, **_k):
            self._n += 1
            text = "臣领旨，谨拟敕谕。" if self._n == 1 else "臣遵旨，即刻解发。"
            return iter((RunContent(text), RunOutput([])))

        def get_last_run_output(self):
            return None

    monkeypatch.setattr(cli_backend, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = _active_ming_minister(game.db, game.content, office="户部").name
        agent = _Agent()
        stub_scene_agent(monkeypatch, agent)

        translate_calls = 0

        def _translate(prompt, _cfg):
            nonlocal translate_calls
            translate_calls += 1
            scene = offline_empty_audience_translate(prompt, _cfg)
            if translate_calls == 2:
                rows = [
                    r for r in game.db.list_pending_actions(game.state.turn)
                    if r.get("kind") == "directive" and r.get("status") == "pending"
                ]
                if not rows:
                    return scene
                return {
                    **scene,
                    "promises": [{"action_id": int(rows[0]["id"]), "decision": "应允"}],
                }
            return {
                **scene,
                "commissions": [{
                    "text": AUDIENCE_MESSAGE,
                    "grant": {
                        "grant_action": "协饷",
                        "amount": 15,
                        "account": "国库",
                        "purpose": "补饷",
                        "target_kind": "army",
                        "target_id": "guanning",
                    },
                }],
            }

        stub_audience_translate(monkeypatch, _translate)
        client = TestClient(web_app.app)
        turn_before = int(game.state.turn)

        draft = client.post(
            f"/api/ministers/{name}/chat/stream", json={"message": AUDIENCE_MESSAGE},
        )
        assert draft.status_code == 200, draft.text
        game._runtime_write_queue().barrier(lambda: None)
        wait_pending_writes(game)
        pend = [
            json.loads(r["payload_json"])
            for r in game.db.list_pending_actions(game.state.turn)
            if r["kind"] == "directive" and r.get("status") == "pending"
        ]
        assert [p.get("target_id") for p in pend] == ["guanning"]

        approve = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert approve.status_code == 200, approve.text
        game._runtime_write_queue().barrier(lambda: None)
        wait_pending_writes(game)

        body = _post_issue_stream(client, expected_turn=turn_before, step="#1774 收夜")
        if body.get("awaiting_decision"):
            _resolve_decisions_via_stream(
                client, body.get("decisions") or [], step="#1774 亲裁",
            )
        wait_pending_writes(game)

        assert _turn_of(_get_state(client)) == turn_before + 1
        pay = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation" and d["target_id"] == "guanning"
        ]
        assert len(pay) == 1, pay
        payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (pay[0]["id"],),
        ).fetchone()[0])
        assert payload["grant_action"] == "协饷"
        assert int(payload["amount"]) == 15
        assert payload["account"] == "国库"
    finally:
        wait_pending_writes(game)
        if game.session:
            game.session.close()


def test_declared_unresolvable_army_target_forms_no_case(game):
    """场景声明须给可核的军队 ID；虚构目标不暂存也不成案。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, _content = game
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": AUDIENCE_MESSAGE,
        "grant": {"grant_action": "协饷", "amount": 15, "account": "国库",
                  "purpose": "补饷", "target_kind": "army", "target_id": "平辽大军"},
    }]}, minister_name="毕自严")
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert db.list_pending_actions(state.turn) == []
    assert db.ensure_dossiers_for_draft_directives(state) == []
    assert db.list_decree_dossiers() == []


# ── 验收 3：手拟可见结果 + 成案边界 ────────────────────────────────────


def test_manual_grounded_army_pay_directive_forms_case(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """POST /api/directives 可见结果；ensure_dossiers 真实成案。"""
    from fastapi.testclient import TestClient

    import web_app
    from tests.test_month_loop_tracer_1468 import _stub_outer_llm_seams
    from tests.test_session_write_queue_1353 import wait_pending_writes

    monkeypatch.setattr(cli_backend, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(_canned_draft("@guanning"), ensure_ascii=False), 1),
    )

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        if game.session.llm_config is not None:
            game.session.llm_config.channel = "cli"
        client = TestClient(web_app.app)
        resp = client.post("/api/directives", json={"text": MANUAL_TEXT, "notes": ""})
        assert resp.status_code == 200, resp.text
        wait_pending_writes(game)
        body = resp.json()
        assert body["directive"]["status"] == "draft"
        assert body["directive"]["text"] == MANUAL_TEXT
        drafts = game.db.list_directives(game.state, statuses=("draft",))
        assert len(drafts) == 1
        payload = game.db.read_directive_dossier_payload(drafts[0])
        assert payload.get("target_id") == "guanning"

        assert game.db.ensure_dossiers_for_draft_directives(game.state) == []
        cases = game.db.list_decree_dossiers()
        assert len(cases) == 1
        assert cases[0]["action_type"] == "grant_allocation"
        assert cases[0]["target_id"] == "guanning"
        case_payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (cases[0]["id"],),
        ).fetchone()[0])
        assert int(case_payload["amount"]) == 15
        assert case_payload["grant_action"] == "协饷"
    finally:
        wait_pending_writes(game)
        if game.session:
            game.session.close()
