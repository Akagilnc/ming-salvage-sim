"""#1753 / #1757 — 颁布判决 LLM 契约错有界补交，耗尽 fail-closed 可恢复。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
两形态：(a) 非法 dossier_id；(b) 漏盖 proposed 案卷。
复用 test_promulgation_judge_561 的 run_agent_text 边界与既有结算 tracer。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
from ming_sim.error_pack import settlement_abort_message
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import TurnPhase
from ming_sim.session import GameSession
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


def _patch_real_llm_boundary(monkeypatch, run_fn, *, spy_create=True):
    """钉 sim/extract，保留真实 llm_promulgation_verdicts + run_agent_text 边界。"""
    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    agents: list[object] = []
    create_kwargs: list[dict] = []
    if spy_create:
        def _spy(*a, **k):
            create_kwargs.append({
                "agno_db": a[1] if len(a) > 1 else k.get("agno_db"),
                "session_id": k.get("session_id"),
                "num_history_runs": k.get("num_history_runs"),
            })
            agent = object()
            agents.append(agent)
            return agent
        monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", _spy)
    monkeypatch.setattr(decree_mod, "run_agent_text", run_fn)
    return agents, create_kwargs


def _bad_payload(mode, first_id, second_id):
    if mode == "illegal_id":
        return {
            "verdicts": [
                {"dossier_id": "not-int", "decision": "promulgated"},
                {"dossier_id": second_id, "decision": "promulgated"},
            ],
        }
    return {
        "verdicts": [
            {"dossier_id": first_id, "decision": "promulgated"},
        ],
    }


def _good_payload(first_id, second_id):
    return {
        "verdicts": [
            {"dossier_id": first_id, "decision": "promulgated"},
            {"dossier_id": second_id, "decision": "promulgated"},
        ],
    }


def _light_session(db, state, content, monkeypatch, *, decree="清核河工并整饬漕运"):
    """盖玺/退朝结算入口用的最小 GameSession（生产 resolve_turn 真缝）。"""
    monkeypatch.setattr(session_mod, "MinisterRegistry", lambda *a, **k: object())
    monkeypatch.setattr(
        session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno", lambda *a, **k: decree,
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = object()
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.last_decree = decree
    sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = None
    sess._beat_generator = None
    sess._write_gate = None
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)
    monkeypatch.setattr(GameSession, "_write_gate_if_free", lambda self: None)
    monkeypatch.setattr(GameSession, "_draft_fingerprint", lambda self, _dirs: ())
    return sess


@pytest.mark.parametrize(
    "mode",
    ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_promulgation_contract_error_heals_within_bound_then_settles(
    game, monkeypatch, mode,
):
    """(a)/(b) 首抽违契约 → 同会话补交 ≤3；末次合规 → 月份 +1、判决落账。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    run_calls: list[dict] = []

    def fake_run(agent, prompt, tag=""):
        run_calls.append({"agent_id": id(agent), "prompt": str(prompt), "tag": tag})
        if len(run_calls) <= heal_budget:
            payload = _bad_payload(mode, first_id, second_id)
        else:
            payload = _good_payload(first_id, second_id)
        return json.dumps(payload, ensure_ascii=False)

    agents, create_kwargs = _patch_real_llm_boundary(monkeypatch, fake_run)

    result = decree_mod.resolve_directives(
        state, db, object(), None, [object()], "清核河工并整饬漕运",
        content=content,
    )

    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    assert len(run_calls) == heal_budget + 1
    assert len(agents) == 1
    assert len({c["agent_id"] for c in run_calls}) == 1
    assert create_kwargs and create_kwargs[0]["agno_db"] is not None
    assert create_kwargs[0]["session_id"] == f"promulgation-judge-turn-{before_turn}"
    assert create_kwargs[0]["num_history_runs"] == heal_budget + 1
    for heal_call in run_calls[1:]:
        prompt = heal_call["prompt"]
        assert str(first_id) in prompt and str(second_id) in prompt
        if mode == "illegal_id":
            assert "not-int" in prompt
            assert "SQLite" in prompt or "正整数" in prompt
        else:
            assert "proposed" in prompt or "覆盖" in prompt
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
    """补交耗尽 → 整月可恢复失败；error pack 含 ≤4 份坏输出 + 已合规判决。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    baseline = {
        first_id: db.get_decree_dossier(first_id),
        second_id: db.get_decree_dossier(second_id),
    }
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    run_prompts: list[str] = []

    def always_bad(agent, prompt, tag=""):
        run_prompts.append(str(prompt))
        return json.dumps(
            _bad_payload(mode, first_id, second_id), ensure_ascii=False,
        )

    agents, _ = _patch_real_llm_boundary(monkeypatch, always_bad)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, object(), None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    abort = ei.value
    assert abort.stage == "promulgation"
    assert int(state.turn) == before_turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.get_pending_promulgation_verdicts(before_turn) == []
    assert len(run_prompts) == heal_budget + 1
    assert len(agents) == 1
    assert any(
        ("not-int" in p if mode == "illegal_id" else str(first_id) in p)
        and ("正整数" in p or "SQLite" in p or "proposed" in p or "覆盖" in p)
        for p in run_prompts[1:]
    )
    for did, snap in baseline.items():
        assert db.get_decree_dossier(did) == snap
        assert db.list_decree_dossier_decisions(did) == []

    pack = Path(abort.error_pack_path)
    assert pack.is_dir()
    assert str(abort) == settlement_abort_message(str(pack))
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    bad_outputs = delta["promulgation_heal_bad_outputs"]
    assert len(bad_outputs) == heal_budget + 1
    compliant_ids = {
        int(row["dossier_id"]) for row in delta["promulgation_compliant_verdicts"]
    }
    if mode == "missing_coverage":
        assert first_id in compliant_ids
        assert second_id not in compliant_ids
    if mode == "illegal_id":
        assert second_id in compliant_ids
        assert first_id not in compliant_ids


def test_promulgation_heal_keeps_earlier_compliant_across_attempts(
    game, monkeypatch,
):
    """首抽含案卷 A 合规、后续补交仍失败且不含 A → error pack 仍保留 A。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    n = {"c": 0}

    def shifting_bad(agent, prompt, tag=""):
        n["c"] += 1
        if n["c"] == 1:
            payload = {
                "verdicts": [
                    {"dossier_id": first_id, "decision": "promulgated"},
                ],
            }
        else:
            payload = {"verdicts": []}
        return json.dumps(payload, ensure_ascii=False)

    _patch_real_llm_boundary(monkeypatch, shifting_bad)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, object(), None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert n["c"] == heal_budget + 1
    delta = json.loads(
        Path(ei.value.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    compliant_ids = {
        int(row["dossier_id"])
        for row in delta["promulgation_compliant_verdicts"]
    }
    assert first_id in compliant_ids
    assert second_id not in compliant_ids


def test_promulgation_heal_preserves_non_json_raw_in_correction_and_pack(
    game, monkeypatch,
):
    """非 JSON 原文须进入补交回喂与 error pack。"""
    db, state, content = game
    _stage_two_policy_dossiers(db, state)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    raw_text = "这不是 JSON，只是判官胡言。"
    prompts: list[str] = []

    def non_json_run(agent, prompt, tag=""):
        prompts.append(str(prompt))
        return raw_text

    _patch_real_llm_boundary(monkeypatch, non_json_run)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, object(), None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert len(prompts) == heal_budget + 1
    assert any(raw_text in p for p in prompts[1:])
    delta = json.loads(
        Path(ei.value.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    bad_outputs = delta["promulgation_heal_bad_outputs"]
    assert len(bad_outputs) == heal_budget + 1
    assert any(raw_text in str(item) for item in bad_outputs)


def test_promulgation_heal_exhausted_via_seal_resolve_turn_entry(
    game, monkeypatch, tmp_path,
):
    """盖玺后结算入口 GameSession.resolve_turn：LLM 边界注入 → 真实 SettlementAbort 传播。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    db.add_directive(
        state, None, "清核河工并整饬漕运", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    before_turn = int(state.turn)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    run_prompts: list[str] = []

    def always_bad(agent, prompt, tag=""):
        run_prompts.append(str(prompt))
        return json.dumps(
            _bad_payload("illegal_id", first_id, second_id), ensure_ascii=False,
        )

    agents, _ = _patch_real_llm_boundary(monkeypatch, always_bad)
    sess = _light_session(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn(decree="清核河工并整饬漕运")

    abort = ei.value
    assert abort.stage == "promulgation"
    assert int(state.turn) == before_turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert len(run_prompts) == heal_budget + 1
    assert len(agents) == 1
    assert any("not-int" in p for p in run_prompts[1:])
    assert str(abort) == settlement_abort_message(str(abort.error_pack_path))
    delta = json.loads(
        Path(abort.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    assert len(delta["promulgation_heal_bad_outputs"]) == heal_budget + 1


def test_promulgation_heal_exhausted_via_advance_without_decree_entry(
    game, monkeypatch, tmp_path,
):
    """退朝/无旨结算入口 advance_without_decree：同颁布 LLM 边界注入 → SettlementAbort。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES

    def always_bad(agent, prompt, tag=""):
        return json.dumps(
            _bad_payload("missing_coverage", first_id, second_id),
            ensure_ascii=False,
        )

    agents, _ = _patch_real_llm_boundary(monkeypatch, always_bad)
    sess = _light_session(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort) as ei:
        sess.advance_without_decree()

    abort = ei.value
    assert abort.stage == "promulgation"
    assert int(state.turn) == before_turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert len(agents) == 1
    assert str(abort) == settlement_abort_message(str(abort.error_pack_path))
    delta = json.loads(
        Path(abort.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    assert len(delta["promulgation_heal_bad_outputs"]) == heal_budget + 1
    compliant_ids = {
        int(row["dossier_id"]) for row in delta["promulgation_compliant_verdicts"]
    }
    assert first_id in compliant_ids
    assert second_id not in compliant_ids


def test_promulgation_heal_exhausted_recovery_via_resolve_turn(
    game, monkeypatch,
):
    """耗尽后从 GameSession.resolve_turn 恢复 → 月份只 +1、pre_settle 不重复。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    db.add_directive(
        state, None, "清核河工并整饬漕运", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    before_turn = int(state.turn)
    heal_budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    phase = {"n": 0}
    pre_settle_calls: list[int] = []
    real_pre_settle = decree_mod.pre_settle

    def spy_pre_settle(*a, **k):
        pre_settle_calls.append(
            int(getattr(a[0], "turn", state.turn) if a else state.turn)
        )
        return real_pre_settle(*a, **k)

    def run_then_good(agent, prompt, tag=""):
        phase["n"] += 1
        proposed_ids = [
            int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
        ]
        if phase["n"] <= heal_budget + 1:
            only = proposed_ids[:1] or [first_id]
            return json.dumps({
                "verdicts": [
                    {"dossier_id": only[0], "decision": "promulgated"},
                ],
            }, ensure_ascii=False)
        return json.dumps({
            "verdicts": [
                {"dossier_id": did, "decision": "promulgated"}
                for did in proposed_ids
            ],
        }, ensure_ascii=False)

    _patch_real_llm_boundary(monkeypatch, run_then_good)
    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre_settle)
    sess = _light_session(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn(decree="清核河工并整饬漕运")
    assert ei.value.stage == "promulgation"
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert pre_settle_calls == [before_turn]

    result = sess.resolve_turn(decree="清核河工并整饬漕运")
    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    assert pre_settle_calls == [before_turn]
    remaining_proposed = {
        int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in remaining_proposed
    assert second_id not in remaining_proposed
