"""#1783 真入口 tracer：一卷宗原句 → 一件事一案（钱+期限同案）。

后出为准替代 #1777 三候选并列形态：分类器按几件事拆，
「着户部尚书…拨银十五万两…十日内奏报…卿即拟旨呈览」是一道旨，
只出一个恩赏·拨帑候选，期限（十日＜一月→下一回合）挂同一案。
收夜后 economy_ledger 恰一条 −15、decree_dossiers 恰一份 grant_allocation，
无以召对记录为正文的平行交办案卷。stub 仅 LLM 边界。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.action_clusters import candidates_from_classifier_payload
from tests.test_army_pay_decree_1503 import _set_guanning_arrears

# #1783：同一事单候选——钱+下一回合期限挂本案（不再并列拟旨/拨帑/交办）。
_L13_ONE_MATTER = [
    {
        "动作类型": "恩赏·拨帑", "确认": "无", "新内容": "", "目标编号": "",
        "密令动作": "无", "目标密令编号": 0, "新标题": "", "期限月数": 0,
        "调教技能": "", "调教性格": "", "目标": "army.guanning",
        "颁布方式": "ordinary", "标题": "", "事务类别": "钱粮",
        "承诺类型": "无", "停止条件": "", "截止回合": 0,  # materialize 按 turn+1 覆写前由桩填
        "持续效果": "十日内奏报实发数目，不得加派于民", "分段里程碑": "",
        "目标候选": "", "恩赏拨帑": "协饷", "姓名": "", "目标类型": "army",
        "金额": 15, "账户": "国库", "用途": "补饷", "拨付节奏": "一次性",
        "执行面": "immediate", "权项": "无", "惩处动作": "无",
        "站台案卷": None, "事项标识": None, "事项处置": "无",
        "驻地": "", "驻地省": "", "官职": "", "授权编号": 0,
        "责任机关": "户部", "任免动作": "无", "任命后传召": "否", "任别": "真除",
    },
]

_EDICT = "着户部自国库拨银十五万两，专解关宁军前补发欠饷，不得加派于民。钦此。"
_UTTERANCE = (
    "着户部尚书郭允厚从国库拨银十五万两，解赴关宁军前专补欠饷，"
    "十日内奏报实发数目，不得加派于民。卿即拟旨呈览。"
)


def test_classify_prompt_splits_by_matters_not_verbs_1783(monkeypatch, game):
    """验收 4：说明书按几件事拆、一件事一案；旧「并存/省略/彼此独立/日级不填」句失效。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    captured = {}

    def _scripted(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        assert tag == "action_intent"
        return (json.dumps({"动作类型": "无"}, ensure_ascii=False), 0)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _scripted)
    cb.classify_cli_action_intent(
        _UTTERANCE,
        recent_context="",
        current_turn=int(state.turn),
    )
    prompt = captured["prompt"]
    assert "按几件事拆" in prompt
    assert "同一件事只出一条" in prompt
    turn_n = int(state.turn)
    assert f"日级期限不足一月则截止回合={turn_n + 1}" in prompt
    # 旧病根句不得再出现（同一事情形）
    assert "拟旨与其任免/拨帑等机械载荷候选可按既有契约并存" not in prompt
    assert "不得因拟旨前缀改判拟旨而省略拨款候选" not in prompt
    assert "交办·责成表达与拟旨彼此独立" not in prompt
    assert "日级期限无法换算为月数或回合，不填写期限月数或截止回合" not in prompt


def test_http_audience_one_matter_grant_with_deadline_1783(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """真 HTTP：一卷宗原句单候选 → 「准」 → issue/stream；
    恰一笔 −15、恰一份 grant 案卷、期限=下一回合；无平行交办案卷。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state,
        _post_issue_stream,
        _stub_outer_llm_seams,
        _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes

    class _HubuAgent:
        def run(self, *_a, **kwargs):
            from tests.test_audience_background import RunContent, RunOutput

            if kwargs.get("stream"):
                def chunks():
                    yield RunContent(_EDICT)
                    yield RunOutput([])
                return chunks()
            return SimpleNamespace(content=_EDICT, tools=[])

        def get_last_run_output(self):
            return None

    def fake_classify(text, *a, **k):
        if str(text or "").strip() == "准":
            return []
        # positional: active_orders, is_consort, has_pending_draft, summaries,
        # llm_config, recent_context, current_turn, backing…
        turn = int(k.get("current_turn") or 0)
        if not turn and len(a) >= 7:
            try:
                turn = int(a[6] or 0)
            except (TypeError, ValueError):
                turn = 0
        if not turn:
            turn = int(game.state.turn)
        raw = dict(_L13_ONE_MATTER[0])
        # 日级不足一月 → 下一回合（与说明书同口径）
        raw["截止回合"] = turn + 1
        scripted = candidates_from_classifier_payload([raw], soft=False)
        assert len(scripted) == 1, scripted
        return [dict(c) for c in scripted]

    def fake_confirm(player_message, *_a, **_k):
        if str(player_message or "").strip() == "准":
            return "应允"
        return "无"

    def fake_directive_confirmation(_msg, _reply, candidates, **_k):
        return {"decision": "应允", "target_ids": [int(c["id"]) for c in candidates]}

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(cb, "extract_confirmation_intent", fake_confirm)
    monkeypatch.setattr(cb, "extract_directive_confirmation", fake_directive_confirmation)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        game.session.registry.get = lambda _ch: _HubuAgent()
        if getattr(game.session, "llm_config", None) is not None:
            try:
                game.session.llm_config.channel = "cli"
            except Exception:
                pass

        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics["国库"]), 100)
        game.db.save_state(game.state)
        treasury_before = int(game.state.metrics["国库"])
        turn_before = int(game.state.turn)

        client = TestClient(web_app.app)
        petition = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": _UTTERANCE},
        )
        assert petition.status_code == 200, petition.text
        wait_pending_writes(game)
        assert int(game.state.metrics["国库"]) == treasury_before

        # 成案前：单候选、期限=下一回合；无 assignment 候选
        pending = [
            p for p in game.db.list_pending_actions(turn_before)
            if p.get("status") == "pending"
        ]
        assert len(pending) == 1, pending
        payload = json.loads(str(pending[0].get("payload_json") or "{}"))
        assert payload.get("dossier_action_type") == "grant_allocation"
        assert int(payload.get("due_turn") or 0) == turn_before + 1
        assert int(payload.get("amount") or 0) == 15
        assert not any(
            json.loads(str(p.get("payload_json") or "{}")).get("dossier_action_type")
            == "assignment"
            for p in pending
        )

        confirm = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert confirm.status_code == 200, confirm.text
        wait_pending_writes(game)

        body = _post_issue_stream(
            client, expected_turn=turn_before, step="1783 issue/stream",
        )
        assert not body.get("awaiting_decision"), body
        wait_pending_writes(game)

        after = _get_state(client)
        assert _turn_of(after) == turn_before + 1, after.get("turn")

        ledger = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT account, delta, purpose, target_id FROM economy_ledger
                WHERE purpose='补饷' AND target_id='guanning' AND account='国库'
                """
            ).fetchall()
        ]
        assert len(ledger) == 1, ledger
        assert int(ledger[0]["delta"]) == -15, ledger

        pay_dossiers = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
            and d["target_id"] == "guanning"
            and json.loads(game.db.conn.execute(
                "SELECT payload_json FROM decree_dossiers WHERE id=?", (d["id"],),
            ).fetchone()[0]).get("grant_action") == "协饷"
        ]
        assert len(pay_dossiers) == 1, pay_dossiers
        assert int(pay_dossiers[0].get("due_turn") or 0) == turn_before + 1, pay_dossiers[0]

        # 无以召对记录为正文的平行交办案卷
        assignment_dossiers = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "assignment"
        ]
        assert assignment_dossiers == [], assignment_dossiers

        pay_logs = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT delta FROM army_logs
                WHERE army_id='guanning' AND field='arrears' AND origin_ref=?
                """,
                (f"dossier:{pay_dossiers[0]['id']}",),
            ).fetchall()
        ]
        assert len(pay_logs) == 1, pay_logs
        assert float(pay_logs[0]["delta"]) == pytest.approx(-15)
    finally:
        try:
            game.db.close()
        except Exception:
            pass
