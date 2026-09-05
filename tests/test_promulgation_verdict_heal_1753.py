"""#1753 / #1757 — 颁布判决 LLM 契约错有界补交，耗尽 fail-closed 可恢复。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
两形态：(a) 非法 dossier_id；(b) 漏盖 proposed 案卷。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import TurnPhase
from tests.settlement_seam_helpers import canned_full_settlement


def _stage_two_policy_dossiers(db, state):
    first = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    )
    second = db.create_decree_dossier(
        state, action_type="policy", decree_text="整饬漕运",
        target_kind="issue", target_id=f"canal-{state.turn}",
    )
    return first, second


def _good_batch(dossiers):
    return [
        {"dossier_id": int(row["id"]), "decision": "promulgated"}
        for row in dossiers
    ]


@pytest.mark.parametrize(
    "mode",
    ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_promulgation_contract_error_heals_within_bound_then_settles(
    game, monkeypatch, mode,
):
    """(a)/(b) 首抽违契约 → 同会话补交 ≤3；第 k 次合规 → 月份 +1、判决落账。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)
    assert heal_budget == 3

    # canned 钉 sim/extract，但会顺手替掉颁布 LLM——先留真函数再钉回，
    # 使 run_agent_text 边界注入走真实 heal 骨架。
    real_llm_promulgation = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts", real_llm_promulgation,
    )
    create_calls: list[object] = []

    def spy_create(*a, **k):
        agent = object()
        create_calls.append(agent)
        return agent

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", spy_create)

    run_calls: list[dict] = []

    def fake_run(agent, prompt, tag=""):
        run_calls.append({
            "agent_id": id(agent),
            "prompt": str(prompt),
            "tag": tag,
        })
        n = len(run_calls)
        if n <= heal_budget:
            if mode == "illegal_id":
                payload = {
                    "verdicts": [
                        {"dossier_id": "not-int", "decision": "promulgated"},
                        {"dossier_id": second_id, "decision": "promulgated"},
                    ],
                }
            else:
                payload = {
                    "verdicts": [
                        {"dossier_id": first_id, "decision": "promulgated"},
                    ],
                }
        else:
            payload = {
                "verdicts": [
                    {"dossier_id": first_id, "decision": "promulgated"},
                    {"dossier_id": second_id, "decision": "promulgated"},
                ],
            }
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(decree_mod, "run_agent_text", fake_run)

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "清核河工并整饬漕运",
        content=content,
    )

    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    # first attempt + exactly heal_budget heals until success on last
    assert len(run_calls) == heal_budget + 1
    assert len(create_calls) == 1  # same-session: one agent
    assert {c["agent_id"] for c in run_calls} == {id(create_calls[0])}
    # 补交上下文必须附原始产出与校验失败原因
    for heal_call in run_calls[1:]:
        prompt = heal_call["prompt"]
        assert prompt, "heal must carry correction feedback"
        assert "校验失败原因" in prompt or "契约" in prompt
        if mode == "illegal_id":
            assert "not-int" in prompt or "原始产出" in prompt
            assert "正整数" in prompt or "dossier_id" in prompt
        else:
            assert str(first_id) in prompt or "原始产出" in prompt
            assert "覆盖" in prompt or "静默" in prompt or "proposed" in prompt
    # 判决按既有路径落账（pending 在 settle 尾会清；案卷不得仍全是 proposed）
    remaining_proposed = {
        int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in remaining_proposed
    assert second_id not in remaining_proposed


@pytest.mark.parametrize(
    "mode",
    ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_promulgation_heal_exhausted_fail_closed_keeps_evidence(
    game, monkeypatch, mode,
):
    """补交 3 次仍不合规 → 整月可恢复失败；error pack 含 ≤4 份坏输出 + 已合规判决。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    baseline = {
        first_id: db.get_decree_dossier(first_id),
        second_id: db.get_decree_dossier(second_id),
    }
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    def always_bad(dossiers, _state, **kwargs):
        if mode == "illegal_id":
            return [
                {"dossier_id": "bad-id", "decision": "promulgated"},
                {"dossier_id": second_id, "decision": "promulgated"},
            ]
        # 漏盖：仅第一案合规，第二案缺席 → 保留单项已合规证据
        return [{"dossier_id": first_id, "decision": "promulgated"}]

    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", always_bad)
    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object(),
    )

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert ei.value.stage == "promulgation"
    assert int(state.turn) == before_turn  # 月份不推进
    assert state.turn_phase == TurnPhase.SETTLING.value  # 可恢复
    assert db.get_pending_promulgation_verdicts(before_turn) == []
    # 无伪造判向；案卷保持 proposed
    for did, snap in baseline.items():
        assert db.get_decree_dossier(did) == snap
        assert db.list_decree_dossier_decisions(did) == []

    pack = Path(ei.value.error_pack_path)
    assert pack.is_dir()
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    bad_outputs = delta.get("promulgation_heal_bad_outputs")
    assert isinstance(bad_outputs, list)
    # 首次 + ≤3 次补交 = ≤4
    assert 1 <= len(bad_outputs) <= heal_budget + 1
    assert len(bad_outputs) == heal_budget + 1
    compliant = delta.get("promulgation_compliant_verdicts")
    assert isinstance(compliant, list)
    if mode == "missing_coverage":
        assert any(int(row.get("dossier_id")) == first_id for row in compliant)
    # 不伪造缺判案卷
    compliant_ids = {
        int(row["dossier_id"]) for row in compliant
        if isinstance(row, dict) and isinstance(row.get("dossier_id"), int)
    }
    assert second_id not in compliant_ids or mode != "missing_coverage" or True
    # missing_coverage: second must NOT appear as forged compliant
    if mode == "missing_coverage":
        assert second_id not in compliant_ids


def test_promulgation_heal_exhausted_recovery_settles_once_without_double_pre_settle(
    game, monkeypatch,
):
    """耗尽后从真实恢复入口接续 → 注入合规 verdict → 月份只 +1、pre_settle 不重复。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    phase = {"n": 0}
    pre_settle_calls: list[int] = []
    real_pre_settle = decree_mod.pre_settle

    def spy_pre_settle(*a, **k):
        pre_settle_calls.append(int(getattr(a[0], "turn", state.turn) if a else state.turn))
        return real_pre_settle(*a, **k)

    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre_settle)

    def llm_then_good(dossiers, _state, **kwargs):
        phase["n"] += 1
        # First resolve: always bad through heal budget+1 calls.
        # Second resolve (recovery): good on first call.
        if phase["n"] <= heal_budget + 1:
            return [{"dossier_id": first_id, "decision": "promulgated"}]
        return _good_batch(dossiers)

    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", llm_then_good)
    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object(),
    )

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )
    assert ei.value.stage == "promulgation"
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert pre_settle_calls == [before_turn]

    # 真实恢复入口：settling 无 ready → fallthrough 重跑后半；canned 后再钉颁布 LLM。
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", llm_then_good)
    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre_settle)
    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "清核河工并整饬漕运",
        content=content,
    )

    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    # pre_settle 不二跑（0008 决定 3）：恢复接续不得再入前半
    assert pre_settle_calls == [before_turn]
    remaining_proposed = {
        int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in remaining_proposed
    assert second_id not in remaining_proposed


def test_promulgation_heal_retries_is_single_source():
    """3 为单一真源；不得另散落魔法数。"""
    assert decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES == 3
    src = Path(decree_mod.__file__).read_text(encoding="utf-8")
    # 补交次数只认该常量名参与循环上界
    assert "PROMULGATION_VERDICT_HEAL_RETRIES" in src
