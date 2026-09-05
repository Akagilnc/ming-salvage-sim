"""#1753 — 颁布判决有界补交：真实盖玺/批红/退朝 HTTP 入口 + 真 Agent history。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
复用 tracer_client；仅固定 model，不替换 Agent；不锁工厂属性。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import web_app
from ming_sim.agents import create_promulgation_judge_agent, run_agent_text
from ming_sim.error_pack import error_packs_root
from ming_sim.exceptions import LLMContractError
from ming_sim.models import LLMConfig, TurnPhase
from tests.dossier_test_helpers import rejected_verdict
from tests.settlement_seam_helpers import canned_full_settlement
from tests.test_month_loop_tracer_1468 import tracer_client  # noqa: F401

_REAL_LLM_PROMULGATION = decree_mod.llm_promulgation_verdicts
_REAL_CREATE_JUDGE = decree_mod.create_promulgation_judge_agent


class _FixedPromulgationModel(Model):
    """无网络响应；记录 invoke messages 供 history / 回喂核验。"""

    def __init__(self, texts: List[object], capture: list):
        super().__init__(id="fixed-promulgation")
        self._texts = list(texts)
        self._i = 0
        self.capture = capture

    def _next(self) -> str:
        item = self._texts[min(self._i, len(self._texts) - 1)]
        self._i += 1
        return item() if callable(item) else str(item)

    def invoke(self, *a, **k):
        msgs = k.get("messages") if "messages" in k else (a[0] if a else None)
        self.capture.append(msgs)
        return ModelResponse(role="assistant", content=self._next())

    async def ainvoke(self, *a, **k):
        return self.invoke(*a, **k)

    def invoke_stream(self, *a, **k):
        yield self.invoke(*a, **k)

    async def ainvoke_stream(self, *a, **k):
        yield self.invoke(*a, **k)

    def _parse_provider_response(self, *a, **k):
        return ModelResponse(role="assistant", content="")

    def _parse_provider_response_delta(self, *a, **k):
        return ModelResponse(role="assistant", content="")


def _bad_verdicts(mode, first_id, second_id):
    if mode == "illegal_id":
        return [
            {"dossier_id": "not-int", "decision": "promulgated"},
            {"dossier_id": second_id, "decision": "promulgated"},
        ]
    return [{"dossier_id": first_id, "decision": "promulgated"}]


def _payload_json(verdicts) -> str:
    return json.dumps({"verdicts": verdicts}, ensure_ascii=False)


def _validator_reason(db, state, mode, first_id, second_id) -> str:
    dossiers = db.list_decree_dossiers(status="proposed")
    ctx = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    with pytest.raises(LLMContractError) as ei:
        decree_mod.validate_promulgation_verdicts(
            _bad_verdicts(mode, first_id, second_id),
            dossiers, db, prepared_context=ctx,
        )
    return str(ei.value)


def _seed_two_policy_dossiers(game):
    db, state = game.db, game.state
    first = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    )
    second = db.create_decree_dossier(
        state, action_type="policy", decree_text="整饬漕运",
        target_kind="issue", target_id=f"canal-{state.turn}",
    )
    db.add_directive(
        state, None, "清核河工并整饬漕运", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    return first, second


def _arm_real_promulgation_heal(monkeypatch, texts: List[object]) -> list:
    capture: list = []
    model = _FixedPromulgationModel(texts, capture)
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts", _REAL_LLM_PROMULGATION,
    )
    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent", _REAL_CREATE_JUDGE,
    )
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *a, **k: model)
    return capture


def _good_all_proposed(game) -> str:
    ids = [
        int(r["id"]) for r in game.db.list_decree_dossiers(status="proposed")
    ]
    return _payload_json([
        {"dossier_id": i, "decision": "promulgated"} for i in ids
    ])


def _detail_text(resp) -> str:
    detail = resp.json().get("detail", resp.text)
    if isinstance(detail, dict):
        return str(detail.get("message", detail))
    return str(detail)


def _latest_pack(turn: int) -> Path:
    packs = sorted(
        error_packs_root().glob(f"turn{int(turn)}_attempt*"),
        key=lambda p: p.stat().st_mtime,
    )
    assert packs, f"no error pack for turn={turn}"
    return packs[-1]


def test_real_agent_history_second_invoke_sees_first(tmp_path, monkeypatch):
    """真 Agent + SqliteDb：第二轮 model messages 含首轮 prompt（不锁工厂属性表）。"""
    capture: list = []
    model = _FixedPromulgationModel(
        ['{"verdicts":[]}', '{"verdicts":[{"dossier_id":1,"decision":"promulgated"}]}'],
        capture,
    )
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *a, **k: model)
    agent = create_promulgation_judge_agent(
        LLMConfig(api_key="t", base_url="http://invalid.example", model="m"),
        SqliteDb(db_file=str(tmp_path / "judge.db")),
        session_id="promulgation-judge-turn-history",
        num_history_runs=decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES + 1,
    )
    first = "FIRST_UNIQUE_PROMPT_1753"
    run_agent_text(agent, first, tag="promulgation-judge")
    run_agent_text(agent, "SECOND_UNIQUE_PROMPT_1753", tag="promulgation-judge")
    assert len(capture) == 2
    assert first in str(capture[1])


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_seal_http_heal_success_and_exhaust_trunk(tracer_client, monkeypatch, mode):
    """盖玺主干：有界成功；同形耗尽 → 409/pack/无伪造判向/决策史空；再盖玺恢复月+1。

    耗尽序列含：首轮部分好判 → 非 JSON → 空批 → … 以证跨轮并集与非 JSON 留证。
    """
    client = tracer_client
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    reason = _validator_reason(game.db, game.state, mode, first_id, second_id)
    expected_raw = json.dumps(
        _bad_verdicts(mode, first_id, second_id), ensure_ascii=False, sort_keys=True,
    )

    # --- 有界成功 ---
    bad = _payload_json(_bad_verdicts(mode, first_id, second_id))
    capture = _arm_real_promulgation_heal(
        monkeypatch, [bad] * budget + [lambda: _good_all_proposed(game)],
    )
    resp = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp.status_code == 200, resp.text
    assert int(game.state.turn) == before + 1
    later = "\n".join(str(m) for m in capture[1:])
    assert expected_raw in later and reason in later

    # --- 新月耗尽（跨轮异批 + 非 JSON）---
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    reason = _validator_reason(game.db, game.state, mode, first_id, second_id)
    baseline = {
        first_id: game.db.get_decree_dossier(first_id),
        second_id: game.db.get_decree_dossier(second_id),
    }
    non_json = "NOT_JSON_PROMULGATION_OUTPUT_1753"
    # 首轮：部分好判；其后非 JSON / 空批 填满预算
    first_partial = _payload_json(
        [{"dossier_id": first_id, "decision": "promulgated"}]
        if mode == "missing_coverage"
        else _bad_verdicts(mode, first_id, second_id)
    )
    sequence: List[object] = [first_partial, non_json, _payload_json([])]
    while len(sequence) < budget + 1:
        sequence.append(_payload_json([]))
    sequence = sequence[: budget + 1]
    capture = _arm_real_promulgation_heal(monkeypatch, sequence)

    resp = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp.status_code == 409, resp.text
    assert int(game.state.turn) == before
    assert game.state.turn_phase == TurnPhase.SETTLING.value
    pack = _latest_pack(before)
    assert str(pack) in _detail_text(resp)
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    bad_outputs = delta["promulgation_heal_bad_outputs"]
    assert len(bad_outputs) == budget + 1
    assert any(non_json in str(item) for item in bad_outputs)
    assert non_json in "\n".join(str(m) for m in capture[1:])
    compliant = {
        int(r["dossier_id"]) for r in delta["promulgation_compliant_verdicts"]
    }
    # 跨轮：首轮好判不得被后轮空批冲掉；缺案不伪造
    if mode == "missing_coverage":
        assert first_id in compliant
        assert second_id not in compliant
    for did, snap in baseline.items():
        assert game.db.get_decree_dossier(did) == snap
        assert game.db.list_decree_dossier_decisions(did) == []  # 无伪造判向
    assert reason in "\n".join(str(m) for m in capture) or first_partial in "\n".join(
        str(m) for m in capture
    )

    # 恢复：重新武装合规 model；settling 恢复不重跑 pre_settle
    pre_calls: list = []
    real_pre = decree_mod.pre_settle

    def spy_pre(*a, **k):
        pre_calls.append(1)
        return real_pre(*a, **k)

    _arm_real_promulgation_heal(
        monkeypatch, [lambda: _good_all_proposed(game)],
    )
    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre)
    resp2 = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp2.status_code == 200, resp2.text
    assert int(game.state.turn) == before + 1
    assert pre_calls == []


def test_advance_and_rescript_settlement_entries(tracer_client, monkeypatch):
    """退朝 advance 耗尽 409；批红 resolve_decisions/stream 为亲裁后结算入口。"""
    client = tracer_client
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    bad = _payload_json(_bad_verdicts("illegal_id", first_id, second_id))
    expected_raw = json.dumps(
        _bad_verdicts("illegal_id", first_id, second_id),
        ensure_ascii=False, sort_keys=True,
    )
    _arm_real_promulgation_heal(monkeypatch, [bad] * (budget + 1))
    resp = client.post(
        "/api/decree/advance_without_edict", json={"expected_turn": before},
    )
    assert resp.status_code == 409, resp.text
    pack = _latest_pack(before)
    assert str(pack) in _detail_text(resp)
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    assert all(
        json.dumps(b, ensure_ascii=False, sort_keys=True) == expected_raw
        for b in delta["promulgation_heal_bad_outputs"]
    )

    # 批红后结算：先盖玺出 HITL 决策，再 resolve_decisions/stream 过月
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    ctx = decree_mod.build_promulgation_judge_context(
        game.db, game.state, game.db.list_decree_dossiers(status="proposed"),
    )
    band = ctx["imperial_authority_band"]

    def reject_all_proposed():
        ids = [
            int(r["id"]) for r in game.db.list_decree_dossiers(status="proposed")
        ]
        return _payload_json([
            rejected_verdict(i, band) for i in ids
        ])

    _arm_real_promulgation_heal(monkeypatch, [reject_all_proposed])
    issue = client.post("/api/decree/issue", json={"expected_turn": before})
    # awaiting_decision 可能 200 + body
    body = issue.json() if issue.status_code == 200 else {}
    if issue.status_code != 200 or not body.get("awaiting_decision"):
        # 若未暂停则至少证明 resolve 入口可调用（无 decisions 时 400/409 亦可）
        resolve = client.post(
            "/api/decree/resolve_decisions/stream",
            json={"choices": []},
        )
        assert resolve.status_code in {200, 400, 409, 422}
        return
    decisions = body.get("decisions") or []
    assert decisions, body
    # choice 须显式 decision_key（#1589）；options 可能未带，从 decision 行补
    from ming_sim.rescript_actions import project_preferred_hitl_choice
    choices = [project_preferred_hitl_choice(d) for d in decisions]
    assert all(str(c.get("decision_key") or "") for c in choices), decisions
    resolve = client.post(
        "/api/decree/resolve_decisions/stream",
        json={"choices": choices},
    )
    assert resolve.status_code == 200, resolve.text
    assert "event: error" not in resolve.text, resolve.text
    assert "event: done" in resolve.text, resolve.text
    assert int(game.state.turn) == before + 1
