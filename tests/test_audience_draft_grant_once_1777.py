"""#1777 真入口 tracer：一句「拟旨 + 协饷 + 交办」只扣一次国库。

原轨（真实对局 L13）分类器把「着户部尚书郭允厚从国库拨银十五万两，解赴关宁
军前专补欠饷……卿即拟旨呈览」判成三条并列动作：拟旨 / 恩赏·拨帑(协饷 15 国库
army.guanning) / 交办。批写遍逐候选各自从 baseline 复制 out，两条候选都落了同
一笔协饷案卷 → 收夜颁诏后国库被扣两次。

本条只钉外部可见结果：这句话对应的协饷 economy_ledger 恰一条 −15、
decree_dossiers 恰一份 grant_allocation 协饷案卷。stub 仅 LLM 边界。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.action_clusters import candidates_from_classifier_payload
from tests.test_army_pay_decree_1503 import _army_row, _set_guanning_arrears

# 真实对局 trace L13：分类器对同一句话回的三元数组（原样，未删字段）。
_L13_THREE_ACTIONS = [
    {"动作类型": "拟旨", "确认": "无", "新内容": "", "目标编号": "", "密令动作": "无",
     "目标密令编号": 0, "新标题": "", "期限月数": 0, "调教技能": "", "调教性格": "",
     "目标": "", "颁布方式": "ordinary", "标题": "", "事务类别": "钱粮",
     "承诺类型": "无", "停止条件": "", "截止回合": 0, "持续效果": "", "分段里程碑": "",
     "目标候选": "", "恩赏拨帑": "无", "姓名": "", "目标类型": "dossier", "金额": None,
     "账户": "国库", "用途": "", "拨付节奏": "一次性", "执行面": "in_transit",
     "权项": "无", "惩处动作": "无", "站台案卷": None, "事项标识": None,
     "事项处置": "无", "驻地": "", "驻地省": "", "官职": "", "授权编号": 0,
     "责任机关": "", "任免动作": "无", "任命后传召": "否", "任别": "真除"},
    {"动作类型": "恩赏·拨帑", "确认": "无", "新内容": "", "目标编号": "", "密令动作": "无",
     "目标密令编号": 0, "新标题": "", "期限月数": 0, "调教技能": "", "调教性格": "",
     "目标": "army.guanning", "颁布方式": "", "标题": "", "事务类别": "钱粮",
     "承诺类型": "无", "停止条件": "", "截止回合": 0,
     "持续效果": "专补欠饷，不得加派于民", "分段里程碑": "", "目标候选": "",
     "恩赏拨帑": "协饷", "姓名": "", "目标类型": "army", "金额": 15, "账户": "国库",
     "用途": "补饷", "拨付节奏": "一次性", "执行面": "in_transit", "权项": "无",
     "惩处动作": "无", "站台案卷": None, "事项标识": None, "事项处置": "无",
     "驻地": "", "驻地省": "", "官职": "", "授权编号": 0, "责任机关": "户部",
     "任免动作": "无", "任命后传召": "否", "任别": "真除"},
    {"动作类型": "交办·责成", "确认": "无", "新内容": "", "目标编号": "", "密令动作": "无",
     "目标密令编号": 0, "新标题": "", "期限月数": 0, "调教技能": "", "调教性格": "",
     "目标": "郭允厚", "颁布方式": "", "标题": "", "事务类别": "钱粮",
     "承诺类型": "无", "停止条件": "", "截止回合": 0,
     "持续效果": "十日内奏报实发数目，不得加派于民", "分段里程碑": "", "目标候选": "",
     "恩赏拨帑": "无", "姓名": "郭允厚", "目标类型": "character", "金额": None,
     "账户": "国库", "用途": "", "拨付节奏": "一次性", "执行面": "immediate",
     "权项": "无", "惩处动作": "无", "站台案卷": None, "事项标识": None,
     "事项处置": "无", "驻地": "", "驻地省": "", "官职": "户部尚书", "授权编号": 0,
     "责任机关": "户部", "任免动作": "无", "任命后传召": "否", "任别": "真除"},
]

_EDICT = "着户部自国库拨银十五万两，专解关宁军前补发欠饷，不得加派于民。钦此。"


def test_http_audience_draft_plus_grant_debits_treasury_once_1777(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """真 HTTP：一句三动作 → 「准」 → issue/stream；协饷恰一笔 −15、恰一份案卷。"""
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
        """户部两轮回话：请拨 → 遵旨拟出的诏书正文。"""

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

    scripted = candidates_from_classifier_payload(_L13_THREE_ACTIONS, soft=False)
    assert len(scripted) == 3, scripted

    def fake_classify(text, *_a, **_k):
        if str(text or "").strip() == "准":
            return []
        return [dict(c) for c in scripted]

    def fake_confirm(player_message, *_a, **_k):
        if str(player_message or "").strip() == "准":
            return "应允"
        return "无"

    def fake_directive_confirmation(_msg, _reply, candidates, **_k):
        # 皇帝一句「准」准的是这道旨；多道并存时点名全部候选。
        return {"decision": "应允", "target_ids": [int(c["id"]) for c in candidates]}

    # 拟旨抽取器把诏书正文回填成 grant 载荷 —— 真实对局正是这一步造出第二份案卷。
    def fake_draft_extract(**_kwargs):
        return {
            "draft_action": "拟旨",
            "draft_text": _EDICT,
            "target_candidate": "",
            "dossier_action_type": "grant_allocation",
            "grant_action": "协饷",
            "target_kind": "army",
            "target_id": "guanning",
            "amount": 15,
            "account": "国库",
            "purpose": "补饷",
            "cadence": "一次性",
            "mode": "ordinary",
        }

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(cb, "extract_confirmation_intent", fake_confirm)
    monkeypatch.setattr(cb, "extract_directive_confirmation", fake_directive_confirmation)
    monkeypatch.setattr(cb, "extract_draft_intent_with_roster_heal", fake_draft_extract)

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
            json={"message": (
                "着户部尚书郭允厚从国库拨银十五万两，解赴关宁军前专补欠饷，"
                "不得加派于民；卿即拟旨呈览。"
            )},
        )
        assert petition.status_code == 200, petition.text
        wait_pending_writes(game)
        assert int(game.state.metrics["国库"]) == treasury_before

        confirm = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert confirm.status_code == 200, confirm.text
        wait_pending_writes(game)

        body = _post_issue_stream(
            client, expected_turn=turn_before, step="1777 issue/stream",
        )
        assert not body.get("awaiting_decision"), body
        wait_pending_writes(game)

        after = _get_state(client)
        assert _turn_of(after) == turn_before + 1, after.get("turn")

        # 这句话的协饷：恰一笔 −15、恰一份案卷、军欠恰减 15。
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

        # 军欠销 15 恰记一笔（月度财政 tick 另有流水，故只钉本案卷的 origin_ref）。
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
