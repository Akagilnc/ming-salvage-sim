"""#1783 真入口 tracer：一卷宗原句 → 一件事一案（钱+期限同案）。

#1842：殿上 scene_chat 转译双桩产出 grant commission（含 #1778 承办/
#1783 期限既有 staging 字段）→ pending；「准」→ promises 应允。
收夜后 economy_ledger 恰一条 −15、decree_dossiers 恰一份 grant_allocation，
无以召对记录为正文的平行交办案卷。stub 仅 LLM 边界。

#1778 并存：承办人来自声明名单（郭允厚），不是当前召对大臣；
本票不回写配人。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.test_army_pay_decree_1503 import _set_guanning_arrears

_EDICT = "着户部自国库拨银十五万两，专解关宁军前补发欠饷，不得加派于民。钦此。"
_UTTERANCE = (
    "着户部尚书郭允厚从国库拨银十五万两，解赴关宁军前专补欠饷，"
    "十日内奏报实发数目，不得加派于民。卿即拟旨呈览。"
)


def test_http_audience_one_matter_grant_with_deadline_1783(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """真 HTTP：一卷宗原句单候选 → 「准」 → issue/stream；
    恰一笔 −15、恰一份 grant 案卷、期限=下一回合；无平行交办案卷；
    主办＝郭允厚（非召对大臣）；到期走 0076 执行格。
    """
    from fastapi.testclient import TestClient

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

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        from ming_sim.audience_translation import join_all_translations

        # 召对大臣刻意避开抽取所得承办人，钉「名单≠当前说话大臣」。
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
            and getattr(ch, "name", key) != "郭允厚"
        )
        agent = _HubuAgent()
        game.session.registry.get = lambda _ch, **_kw: agent
        game.session._scene_agent_double = agent
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

        # #1842：殿上 scene_chat 双桩——交办 grant+承办/期限 → pending；「准」→ promises。
        def _translate(prompt, _cfg):
            text = str(prompt or "")
            if "【本轮皇帝】准" in text:
                rows = [
                    r for r in game.db.list_pending_actions(game.state.turn)
                    if r.get("kind") == "directive" and r.get("status") == "pending"
                ]
                if not rows:
                    return {"commissions": [], "promises": []}
                return {
                    "commissions": [],
                    "promises": [{"action_id": int(rows[0]["id"]), "decision": "应允"}],
                }
            return {
                "commissions": [{
                    "text": _UTTERANCE,
                    "grant": {
                        "grant_action": "协饷",
                        "amount": 15,
                        "account": "国库",
                        "purpose": "补饷",
                        "target_kind": "army",
                        "target_id": "guanning",
                    },
                    # #1778/#1783 既有 staging 字段（非 #1815）
                    "assignee": "郭允厚",
                    "participant_roster": [{
                        "character_id": "郭允厚", "tier": "主办",
                        "role": "户部尚书承办", "delegator_id": None,
                    }],
                    "due_turn": turn_before + 1,
                }],
                "promises": [],
            }

        game.session._audience_translate_fn = _translate

        client = TestClient(web_app.app)
        petition = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": _UTTERANCE},
        )
        assert petition.status_code == 200, petition.text
        assert join_all_translations(timeout_s=5.0)
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
        # 承办人挂本案 pending（#1778 并存；非当前召对大臣）
        assert str(payload.get("assignee") or payload.get("assignee_id") or "") == "郭允厚", payload
        assert not any(
            json.loads(str(p.get("payload_json") or "{}")).get("dossier_action_type")
            == "assignment"
            for p in pending
        )

        confirm = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert confirm.status_code == 200, confirm.text
        assert join_all_translations(timeout_s=5.0)
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
        dossier_id = int(pay_dossiers[0]["id"])
        assert int(pay_dossiers[0].get("due_turn") or 0) == turn_before + 1, pay_dossiers[0]
        # 期限未到：钱已落、案卷保持 executing（不当夜终裁）
        assert pay_dossiers[0]["status"] == "executing", pay_dossiers[0]
        assert not str(pay_dossiers[0].get("execution_outcome") or "").strip()

        # 无以召对记录为正文的平行交办案卷
        assignment_dossiers = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "assignment"
        ]
        assert assignment_dossiers == [], assignment_dossiers

        # #1778 并存：一件事一案的主办＝郭允厚，不是当前召对大臣
        leads = [
            e["character_id"]
            for e in (pay_dossiers[0].get("participant_roster") or [])
            if e.get("tier") == "主办"
        ]
        assert leads == ["郭允厚"], leads
        assert name != "郭允厚" and name not in leads

        # 期限不另立承诺事项、不占在办名额
        origin_issues = game.db.conn.execute(
            "SELECT id, kind, status FROM issues WHERE origin_ref=?",
            (f"dossier:{dossier_id}",),
        ).fetchall()
        assert origin_issues == [], origin_issues

        pay_logs = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT delta FROM army_logs
                WHERE army_id='guanning' AND field='arrears' AND origin_ref=?
                """,
                (f"dossier:{dossier_id}",),
            ).fetchall()
        ]
        assert len(pay_logs) == 1, pay_logs
        assert float(pay_logs[0]["delta"]) == pytest.approx(-15)

        # 验收 3：受控推进 → 0076 到期复核 → 执行格（钱已落＝fulfilled，0076 既有映射）
        from ming_sim.decree import settle_with_delta
        from ming_sim.due_review import list_due_review_scenes
        from ming_sim.staged_commitment import TODO_STATUS_PENDING

        settle_with_delta(
            game.state, game.db, {}, before_turn=int(game.state.turn),
            content=game.content,
        )
        assert game.db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        scenes = list_due_review_scenes(game.db, game.state)
        # 验收 3：场面属本案到期复核，不得冒出断供哭谏
        due_scenes = [
            s for s in scenes
            if s.get("kind") == "due_review"
            and int(s.get("dossier_id") or 0) == dossier_id
        ]
        assert due_scenes, scenes
        assert not any(s.get("kind") == "breach_plea" for s in scenes), scenes

        settle_with_delta(
            game.state, game.db, {}, before_turn=int(game.state.turn),
            content=game.content,
        )
        after_due = game.db.get_decree_dossier(dossier_id)
        assert after_due is not None
        # 本路 economy 实况已落、无表报 → 0076 decide 唯一终值 fulfilled
        assert after_due["execution_outcome"] == "fulfilled", after_due
        assert after_due["status"] == "closed"
    finally:
        try:
            game.db.close()
        except Exception:
            pass
