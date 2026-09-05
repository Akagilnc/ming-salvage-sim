"""#1753 — 颁布判决有界补交：盖玺/批红/退朝 HTTP 入口。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
复用 settlement_seam_helpers + tracer_client；固定 model 注入边界。
同会话 history 续接以一次真跑留证，不造永久 Agent+SqliteDb 自动测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
from agno.models.base import Model
from agno.models.response import ModelResponse

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import web_app
from ming_sim.error_pack import error_packs_root
from ming_sim.exceptions import LLMContractError
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import rejected_verdict
from tests.settlement_seam_helpers import canned_full_settlement
from tests.test_month_loop_tracer_1468 import tracer_client  # noqa: F401

_REAL_LLM_PROMULGATION = decree_mod.llm_promulgation_verdicts


class _FixedPromulgationModel(Model):
    """无网络响应；逐轮记录 invoke messages，供回喂逐轮对应核验。"""

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


def _feedback_raw_from_model_text(text: str) -> str:
    """生产回喂 raw_output：可解析 verdicts 批 → dumps(list)；否则原文本。"""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(text)
    if isinstance(parsed, dict) and "verdicts" in parsed:
        return json.dumps(parsed["verdicts"], ensure_ascii=False, sort_keys=True)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _validator_reason_for_batch(db, state, batch) -> str:
    dossiers = db.list_decree_dossiers(status="proposed")
    ctx = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    with pytest.raises(LLMContractError) as ei:
        decree_mod.validate_promulgation_verdicts(
            batch, dossiers, db, prepared_context=ctx,
        )
    return str(ei.value)


def _validator_reason(db, state, mode, first_id, second_id) -> str:
    return _validator_reason_for_batch(
        db, state, _bad_verdicts(mode, first_id, second_id),
    )


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
    """钉 sim/extract，恢复真实 llm_promulgation_verdicts，固定 chat model。"""
    capture: list = []
    model = _FixedPromulgationModel(texts, capture)
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts", _REAL_LLM_PROMULGATION,
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


def _assert_promulgated_verdicts_landed(db, dossier_ids) -> None:
    """成功/恢复后：真实案卷判决史落账（结构化，不锁呈现措辞）。"""
    for did in dossier_ids:
        decisions = db.list_decree_dossier_decisions(did)
        assert decisions, f"dossier {did} missing decision history"
        assert any(
            str(row.get("decision") or "") == "promulgated" for row in decisions
        ), decisions
        row = db.get_decree_dossier(did)
        assert row is not None
        assert str(row.get("promulgation_decision") or "") == "promulgated"
        assert str(row.get("status") or "") != "proposed"


def _invoke_messages_text(messages) -> str:
    """从 model invoke messages 抽 content 正文（不依赖 Message repr 转义）。"""
    if messages is None:
        return ""
    parts: List[str] = []
    for message in messages:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
        else:
            parts.append(str(content))
    return "\n".join(parts)


def _assert_round_feedback_correspondence(
    capture: list, model_texts: List[str], reasons: List[str],
) -> None:
    """逐轮：第 k 次补交 invoke 含第 k-1 次原产出与对应失败原因；不拼全量、不二选一。"""
    assert len(capture) >= 2
    assert len(reasons) == len(model_texts)
    heal_rounds = min(len(capture) - 1, len(model_texts))
    for i in range(heal_rounds):
        round_text = _invoke_messages_text(capture[i + 1])
        expected_raw = _feedback_raw_from_model_text(model_texts[i])
        assert expected_raw in round_text, (
            f"heal round {i + 1} missing prior raw output"
        )
        assert reasons[i] in round_text, (
            f"heal round {i + 1} missing prior failure reason"
        )


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_seal_http_heal_success_and_exhaust_trunk(tracer_client, monkeypatch, mode):
    """盖玺主干：有界成功落账；耗尽 409/pack/好判保留/无伪造；恢复月+1 且判决落账。"""
    client = tracer_client
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    reason = _validator_reason(game.db, game.state, mode, first_id, second_id)
    bad = _payload_json(_bad_verdicts(mode, first_id, second_id))
    bad_model_texts = [bad] * budget
    success_texts: List[object] = list(bad_model_texts) + [
        lambda: _good_all_proposed(game),
    ]

    # --- 有界成功 ---
    capture = _arm_real_promulgation_heal(monkeypatch, success_texts)
    resp = client.post("/api/decree/issue", json={"expected_turn": before})
    assert resp.status_code == 200, resp.text
    assert int(game.state.turn) == before + 1
    _assert_promulgated_verdicts_landed(game.db, (first_id, second_id))
    _assert_round_feedback_correspondence(
        capture, bad_model_texts, [reason] * budget,
    )

    # --- 新月耗尽（跨轮异批 + 非 JSON）---
    assert client.post("/api/menu/new_game").status_code == 200
    game = web_app.web_game
    first_id, second_id = _seed_two_policy_dossiers(game)
    before = int(game.state.turn)
    baseline = {
        first_id: game.db.get_decree_dossier(first_id),
        second_id: game.db.get_decree_dossier(second_id),
    }
    non_json = "NOT_JSON_PROMULGATION_OUTPUT_1753"
    first_partial_verdicts = (
        [{"dossier_id": first_id, "decision": "promulgated"}]
        if mode == "missing_coverage"
        else _bad_verdicts(mode, first_id, second_id)
    )
    first_partial = _payload_json(first_partial_verdicts)
    sequence_texts = [first_partial, non_json, _payload_json([])]
    while len(sequence_texts) < budget + 1:
        sequence_texts.append(_payload_json([]))
    sequence_texts = sequence_texts[: budget + 1]

    # 各轮失败原因：可解析批走 validator；非 JSON 走 parse 契约错原文
    round_reasons: List[str] = []
    for text in sequence_texts:
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            with pytest.raises(LLMContractError) as ei:
                decree_mod.parse_agent_json(text, "颁布判官")
            round_reasons.append(str(ei.value))
            continue
        batch = parsed.get("verdicts") if isinstance(parsed, dict) else parsed
        if not isinstance(batch, list):
            with pytest.raises(LLMContractError) as ei:
                decree_mod._require_promulgation_verdict_list(
                    batch, raw_value=parsed,
                )
            round_reasons.append(str(ei.value))
            continue
        round_reasons.append(
            _validator_reason_for_batch(game.db, game.state, batch),
        )

    capture = _arm_real_promulgation_heal(monkeypatch, list(sequence_texts))

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
    compliant_rows = list(delta["promulgation_compliant_verdicts"])
    compliant_ids = {int(r["dossier_id"]) for r in compliant_rows}
    # 两形态均核好判内容不丢：illegal_id 保留 second；missing_coverage 保留 first
    if mode == "missing_coverage":
        assert first_id in compliant_ids
        assert second_id not in compliant_ids
        assert any(
            int(r["dossier_id"]) == first_id
            and str(r.get("decision") or "") == "promulgated"
            for r in compliant_rows
        )
    else:
        assert second_id in compliant_ids
        assert first_id not in compliant_ids
        assert any(
            int(r["dossier_id"]) == second_id
            and str(r.get("decision") or "") == "promulgated"
            for r in compliant_rows
        )
    for did, snap in baseline.items():
        assert game.db.get_decree_dossier(did) == snap
        assert game.db.list_decree_dossier_decisions(did) == []
    # 逐轮对应：不拼所有 messages、不 reason∨raw 二选一
    _assert_round_feedback_correspondence(
        capture, sequence_texts[:-1], round_reasons[:-1],
    )

    # 恢复：合规 model；settling 不重跑 pre_settle；判决落账
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
    _assert_promulgated_verdicts_landed(game.db, (first_id, second_id))


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
    assert issue.status_code == 200, issue.text
    body = issue.json()
    assert body.get("awaiting_decision") is True, body
    decisions = body.get("decisions") or []
    assert decisions, body
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
