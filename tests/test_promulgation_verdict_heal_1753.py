"""#1753 — 颁布判决有界补交：真实盖玺/退朝 HTTP 入口 + 真 Agent 会话续接。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
复用 tracer_client（#1468）真实 FastAPI 入口；仅固定 model 响应，不替换 Agent。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
from agno.agent import Agent
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
from tests.settlement_seam_helpers import canned_full_settlement
from tests.test_month_loop_tracer_1468 import tracer_client  # noqa: F401

# tracer/canned 会替身颁布缝；import 时留下真函数引用。
_REAL_LLM_PROMULGATION = decree_mod.llm_promulgation_verdicts
_REAL_CREATE_JUDGE = decree_mod.create_promulgation_judge_agent


class _FixedPromulgationModel(Model):
    """无网络固定/回调响应；记录每次 invoke 的 messages 供 history 核验。"""

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


def _good_verdicts(first_id, second_id):
    return [
        {"dossier_id": first_id, "decision": "promulgated"},
        {"dossier_id": second_id, "decision": "promulgated"},
    ]


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
    """canned 其它结算缝；颁布走真工厂/真 llm 路径 + 真 Agent + 固定 model。"""
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
    """按当刻 proposed 全集生成合规批（ensure 可能多落案卷）。"""
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
    assert packs, f"no error pack for turn={turn} under {error_packs_root()}"
    return packs[-1]


# ── 真 Agent 会话 history（不替换 Agent）────────────────────────────────


def test_real_agent_session_history_across_two_runs(tmp_path, monkeypatch):
    """真 Agent + 真 SqliteDb + 固定 model：第二次 invoke messages 含首轮。"""
    capture: list = []
    model = _FixedPromulgationModel(
        [
            '{"verdicts":[]}',
            '{"verdicts":[{"dossier_id":1,"decision":"promulgated"}]}',
        ],
        capture,
    )
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *a, **k: model)
    cfg = LLMConfig(api_key="t", base_url="http://invalid.example", model="m")
    agno_db = SqliteDb(db_file=str(tmp_path / "judge.db"))
    sid = "promulgation-judge-turn-history"
    agent = create_promulgation_judge_agent(
        cfg, agno_db, session_id=sid,
        num_history_runs=decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES + 1,
    )
    assert isinstance(agent, Agent)
    assert agent.db is agno_db
    assert agent.session_id == sid
    assert agent.add_history_to_context is True
    assert agent.cache_session is True

    first = "FIRST_UNIQUE_PROMPT_1753"
    second = "SECOND_UNIQUE_PROMPT_1753"
    out1 = run_agent_text(agent, first, tag="promulgation-judge")
    out2 = run_agent_text(agent, second, tag="promulgation-judge")
    assert "verdicts" in out1 and "verdicts" in out2
    assert len(capture) == 2
    assert first in str(capture[1])


# ── 盖玺 / 退朝真实 HTTP 入口 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_seal_http_heals_within_bound(tracer_client, monkeypatch, mode):
    """盖玺 POST /api/decree/issue：违契约 → 真 Agent 有界补交 → 月+1。"""
    client = tracer_client
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    assert game is not None
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    reason = _validator_reason(game.db, game.state, mode, first_id, second_id)
    expected_raw = json.dumps(
        _bad_verdicts(mode, first_id, second_id), ensure_ascii=False, sort_keys=True,
    )
    bad = _payload_json(_bad_verdicts(mode, first_id, second_id))
    texts: List[object] = [bad] * budget + [lambda: _good_all_proposed(game)]
    capture = _arm_real_promulgation_heal(monkeypatch, texts)

    resp = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp.status_code == 200, resp.text
    assert int(game.state.turn) == before + 1
    assert len(capture) == budget + 1
    # 同会话：后续轮 messages 含校验失败原因与原始坏批
    later = "\n".join(str(m) for m in capture[1:])
    assert expected_raw in later
    assert reason in later
    proposed = {
        int(r["id"]) for r in game.db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in proposed and second_id not in proposed


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_seal_http_exhaust_fail_closed_then_recover(tracer_client, monkeypatch, mode):
    """盖玺耗尽 → 409 + pack 坏批；再盖玺合规 → 月只 +1、pre_settle 一次。"""
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
    baseline = {
        first_id: game.db.get_decree_dossier(first_id),
        second_id: game.db.get_decree_dossier(second_id),
    }
    bad = _payload_json(_bad_verdicts(mode, first_id, second_id))
    capture = _arm_real_promulgation_heal(
        monkeypatch,
        [bad] * (budget + 1) + [lambda: _good_all_proposed(game)],
    )

    resp = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp.status_code == 409, resp.text
    assert int(game.state.turn) == before
    assert game.state.turn_phase == TurnPhase.SETTLING.value
    pack = _latest_pack(before)
    assert str(pack) in _detail_text(resp)
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    bad_outputs = delta["promulgation_heal_bad_outputs"]
    assert len(bad_outputs) == budget + 1
    assert all(
        json.dumps(b, ensure_ascii=False, sort_keys=True) == expected_raw
        for b in bad_outputs
    )
    compliant = {
        int(r["dossier_id"]) for r in delta["promulgation_compliant_verdicts"]
    }
    if mode == "missing_coverage":
        assert first_id in compliant and second_id not in compliant
    else:
        assert second_id in compliant and first_id not in compliant
    for did, snap in baseline.items():
        assert game.db.get_decree_dossier(did) == snap
    assert reason in "\n".join(str(m) for m in capture)

    pre_calls: list[int] = []
    real_pre = decree_mod.pre_settle

    def spy_pre(*a, **k):
        pre_calls.append(int(getattr(a[0], "turn", before)))
        return real_pre(*a, **k)

    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre)
    resp2 = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp2.status_code == 200, resp2.text
    assert int(game.state.turn) == before + 1
    # ADR0008 决定3：settling 恢复不重跑已执行的 pre_settle
    assert pre_calls == []
    proposed = {
        int(r["id"]) for r in game.db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in proposed and second_id not in proposed


def test_advance_http_exhaust_fail_closed(tracer_client, monkeypatch):
    """退朝 POST /api/decree/advance_without_edict：颁布 heal 耗尽 → 409 + pack。"""
    client = tracer_client
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    expected_raw = json.dumps(
        _bad_verdicts("illegal_id", first_id, second_id),
        ensure_ascii=False, sort_keys=True,
    )
    bad = _payload_json(_bad_verdicts("illegal_id", first_id, second_id))
    _arm_real_promulgation_heal(monkeypatch, [bad] * (budget + 1))

    resp = client.post(
        "/api/decree/advance_without_edict",
        json={"expected_turn": before},
    )
    assert resp.status_code == 409, resp.text
    pack = _latest_pack(before)
    assert str(pack) in _detail_text(resp)
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    assert len(delta["promulgation_heal_bad_outputs"]) == budget + 1
    assert all(
        json.dumps(b, ensure_ascii=False, sort_keys=True) == expected_raw
        for b in delta["promulgation_heal_bad_outputs"]
    )
