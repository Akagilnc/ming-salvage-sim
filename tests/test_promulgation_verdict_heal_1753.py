"""#1753 / #1757 — 颁布判决有界补交，耗尽 fail-closed 可恢复。

decision key: promulgation-verdict-heal-by-resume-then-fail-closed
复用 settlement_seam_helpers 与既有 run_agent_text / web abort 通道。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import web_app
from ming_sim.exceptions import LLMContractError, SettlementAbort
from ming_sim.models import LLMConfig, TurnPhase
from tests.settlement_seam_helpers import canned_full_settlement, make_light_session


def _two_dossiers(db, state):
    a = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    )
    b = db.create_decree_dossier(
        state, action_type="policy", decree_text="整饬漕运",
        target_kind="issue", target_id=f"canal-{state.turn}",
    )
    return a, b


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


def _patch_heal_boundary(monkeypatch, run_fn):
    """canned sim/extract；保留真实 llm_promulgation_verdicts + run 边界。"""
    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    agents: list[object] = []
    create_kwargs: list[dict] = []

    def spy_create(*a, **k):
        create_kwargs.append({
            "agno_db": a[1] if len(a) > 1 else k.get("agno_db"),
            "session_id": k.get("session_id"),
            "num_history_runs": k.get("num_history_runs"),
        })
        agent = object()
        agents.append(agent)
        return agent

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", spy_create)
    monkeypatch.setattr(decree_mod, "run_agent_text", run_fn)
    return agents, create_kwargs


def _validator_reason(db, state, mode, first_id, second_id) -> str:
    """从现行 validator 取该形态失败原因原文（非测试内锁措辞）。"""
    dossiers = db.list_decree_dossiers(status="proposed")
    ctx = decree_mod.build_promulgation_judge_context(db, state, dossiers)
    bad = _bad_verdicts(mode, first_id, second_id)
    with pytest.raises(LLMContractError) as ei:
        decree_mod.validate_promulgation_verdicts(
            bad, dossiers, db, prepared_context=ctx,
        )
    return str(ei.value)


def _assert_pack_bad_outputs(pack_path, expected_raw, *, n):
    delta = json.loads(Path(pack_path, "delta.json").read_text(encoding="utf-8"))
    bad = delta["promulgation_heal_bad_outputs"]
    assert len(bad) == n
    for batch in bad:
        assert json.dumps(batch, ensure_ascii=False, sort_keys=True) == expected_raw
    return delta


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_heal_within_bound_then_settles(game, monkeypatch, mode):
    """两形态：有界补交末次合规 → 月+1；回喂含原始坏批 + 现行 validator 原因。"""
    db, state, content = game
    first_id, second_id = _two_dossiers(db, state)
    before = int(state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    agno = object()
    calls: list[dict] = []
    reason = _validator_reason(db, state, mode, first_id, second_id)
    expected_raw = json.dumps(
        _bad_verdicts(mode, first_id, second_id), ensure_ascii=False, sort_keys=True,
    )

    def run(agent, prompt, tag=""):
        calls.append({"id": id(agent), "prompt": str(prompt)})
        payload = (
            _bad_verdicts(mode, first_id, second_id)
            if len(calls) <= budget
            else _good_verdicts(first_id, second_id)
        )
        return json.dumps({"verdicts": payload}, ensure_ascii=False)

    agents, kwargs = _patch_heal_boundary(monkeypatch, run)
    result = decree_mod.resolve_directives(
        state, db, agno, None, [object()], "两旨", content=content,
    )

    assert result.awaiting is False
    assert int(state.turn) == before + 1
    assert len(calls) == budget + 1
    assert len(agents) == 1 and {c["id"] for c in calls} == {id(agents[0])}
    assert kwargs[0]["agno_db"] is agno
    assert kwargs[0]["session_id"] == f"promulgation-judge-turn-{before}"
    assert kwargs[0]["num_history_runs"] == budget + 1
    for c in calls[1:]:
        assert expected_raw in c["prompt"]
        assert reason in c["prompt"]
        assert str(first_id) in c["prompt"] and str(second_id) in c["prompt"]
    proposed = {int(r["id"]) for r in db.list_decree_dossiers(status="proposed")}
    assert first_id not in proposed and second_id not in proposed


@pytest.mark.parametrize(
    "mode", ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_heal_exhaust_via_resolve_turn_pack_and_http_channel(
    game, monkeypatch, tmp_path, mode,
):
    """盖玺入口 resolve_turn 耗尽 → pack 留每轮坏批；HTTP issue 通道 409 含 pack 路径。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_id, second_id = _two_dossiers(db, state)
    db.add_directive(
        state, None, "两旨", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    before = int(state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    baseline = {
        first_id: db.get_decree_dossier(first_id),
        second_id: db.get_decree_dossier(second_id),
    }
    reason = _validator_reason(db, state, mode, first_id, second_id)
    expected_raw = json.dumps(
        _bad_verdicts(mode, first_id, second_id), ensure_ascii=False, sort_keys=True,
    )
    prompts: list[str] = []

    def always_bad(agent, prompt, tag=""):
        prompts.append(str(prompt))
        return json.dumps(
            {"verdicts": _bad_verdicts(mode, first_id, second_id)},
            ensure_ascii=False,
        )

    agents, _ = _patch_heal_boundary(monkeypatch, always_bad)
    sess = make_light_session(
        db, state, content, monkeypatch, decree="两旨", agno_db=object(),
    )

    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn(decree="两旨")
    abort = ei.value

    assert abort.stage == "promulgation"
    assert int(state.turn) == before
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.get_pending_promulgation_verdicts(before) == []
    assert len(prompts) == budget + 1 and len(agents) == 1
    assert any(expected_raw in p and reason in p for p in prompts[1:])
    for did, snap in baseline.items():
        assert db.get_decree_dossier(did) == snap
        assert db.list_decree_dossier_decisions(did) == []

    pack = Path(abort.error_pack_path)
    assert pack.is_dir()
    delta = _assert_pack_bad_outputs(pack, expected_raw, n=budget + 1)
    compliant = {
        int(r["dossier_id"]) for r in delta["promulgation_compliant_verdicts"]
    }
    if mode == "missing_coverage":
        assert first_id in compliant and second_id not in compliant
    else:
        assert second_id in compliant and first_id not in compliant

    # 既有 web 失败呈现通道：409 + detail 携带 pack 路径（结构化身份，不锁人话）
    import contextlib

    class _Game:
        session = type("S", (), {
            "resolve_turn": lambda self, *a, **k: (_ for _ in ()).throw(
                SettlementAbort(
                    str(abort), turn=abort.turn, stage=abort.stage,
                    error_pack_path=abort.error_pack_path,
                )
            ),
        })()
        class state:
            ended = False
            turn = abort.turn

    @contextlib.contextmanager
    def _entry(game, *, write_cm, hold_write_for_body=True):
        del game, write_cm, hold_write_for_body
        yield

    monkeypatch.setattr(web_app, "get_game", lambda: _Game())
    monkeypatch.setattr(web_app, "_settlement_period_entry", _entry)
    with pytest.raises(HTTPException) as http_ei:
        web_app.api_issue_decree()
    assert http_ei.value.status_code == 409
    detail = http_ei.value.detail
    text = detail.get("message", detail) if isinstance(detail, dict) else str(detail)
    assert str(abort.error_pack_path) in text


def test_heal_keeps_earlier_compliant_and_non_json_raw(game, monkeypatch, tmp_path):
    """跨轮好判保留；非 JSON 原文进入回喂与 pack（两行为共一案）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_id, second_id = _two_dossiers(db, state)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    n = {"c": 0}
    raw_text = "not-json-promulgation-output"
    prompts: list[str] = []

    def shifting(agent, prompt, tag=""):
        n["c"] += 1
        prompts.append(str(prompt))
        if n["c"] == 1:
            return json.dumps({
                "verdicts": [{"dossier_id": first_id, "decision": "promulgated"}],
            })
        if n["c"] == 2:
            return raw_text
        return json.dumps({"verdicts": []})

    _patch_heal_boundary(monkeypatch, shifting)
    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, object(), None, [object()], "两旨", content=content,
        )
    assert n["c"] == budget + 1
    assert any(raw_text in p for p in prompts[1:])
    delta = json.loads(
        Path(ei.value.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    assert first_id in {
        int(r["dossier_id"]) for r in delta["promulgation_compliant_verdicts"]
    }
    assert second_id not in {
        int(r["dossier_id"]) for r in delta["promulgation_compliant_verdicts"]
    }
    assert any(raw_text in str(item) for item in delta["promulgation_heal_bad_outputs"])


def test_heal_exhaust_recovery_month_plus_one_pre_settle_once(game, monkeypatch):
    """耗尽后 resolve_turn 恢复：月份只 +1，pre_settle 不重复。"""
    db, state, content = game
    first_id, second_id = _two_dossiers(db, state)
    db.add_directive(
        state, None, "两旨", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    before = int(state.turn)
    budget = decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES
    phase = {"n": 0}
    pre_calls: list[int] = []
    real_pre = decree_mod.pre_settle

    def spy_pre(*a, **k):
        pre_calls.append(int(getattr(a[0], "turn", state.turn) if a else state.turn))
        return real_pre(*a, **k)

    def run_then_good(agent, prompt, tag=""):
        phase["n"] += 1
        ids = [int(r["id"]) for r in db.list_decree_dossiers(status="proposed")]
        if phase["n"] <= budget + 1:
            only = ids[:1] or [first_id]
            return json.dumps({
                "verdicts": [{"dossier_id": only[0], "decision": "promulgated"}],
            })
        return json.dumps({
            "verdicts": [{"dossier_id": i, "decision": "promulgated"} for i in ids],
        })

    _patch_heal_boundary(monkeypatch, run_then_good)
    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre)
    sess = make_light_session(
        db, state, content, monkeypatch, decree="两旨", agno_db=object(),
    )

    with pytest.raises(SettlementAbort):
        sess.resolve_turn(decree="两旨")
    assert pre_calls == [before]
    result = sess.resolve_turn(decree="两旨")
    assert result.awaiting is False
    assert int(state.turn) == before + 1
    assert pre_calls == [before]
    proposed = {int(r["id"]) for r in db.list_decree_dossiers(status="proposed")}
    assert first_id not in proposed and second_id not in proposed


def test_promulgation_judge_binds_real_agno_session(tmp_path, monkeypatch):
    """真工厂 + 真 SqliteDb：db/session_id/history 接缝绑定（无网络 LLM）。"""
    from agno.db.sqlite import SqliteDb

    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *a, **k: object())
    monkeypatch.setattr(agents_mod, "Agent", lambda **kwargs: kwargs)
    cfg = LLMConfig(api_key="t", base_url="http://invalid.example", model="m")
    agno_db = SqliteDb(db_file=str(tmp_path / "promulgation-judge.db"))
    sid = "promulgation-judge-turn-7"
    bound = agents_mod.create_promulgation_judge_agent(
        cfg, agno_db, session_id=sid,
        num_history_runs=decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES + 1,
    )
    assert bound["db"] is agno_db
    assert bound["session_id"] == sid
    assert bound["cache_session"] is True
    assert bound["add_history_to_context"] is True
    assert bound["num_history_runs"] == decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES + 1
