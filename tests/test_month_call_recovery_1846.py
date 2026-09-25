"""#1846：过月模型调用统一重试、停住、逃生口与恢复真源（ADR 0157）。

接缝：audience_transport_policy + run_with_transport；run_player_month_chain /
resolve_turn 停住与续跑；state_payload.settlement_recovery 投影。
不覆盖 #1853/#1854 界面，不覆盖 #1847 批红续推，不另起并行恢复机制。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from openai import APIStatusError, APITimeoutError

from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.llm_transport import (
    TRANSPORT_DEFAULT_MAX_ATTEMPTS,
    TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS,
    audience_transport_policy,
    run_with_transport,
)
from ming_sim.models import TurnPhase
from tests.settlement_seam_helpers import make_light_session


def _forbid_extractor(monkeypatch):
    import ming_sim.decree as decree_mod
    import ming_sim.simulation as simulation

    assert not hasattr(decree_mod, "extract_scores_by_modules_with_agno")
    assert not hasattr(simulation, "extract_scores_by_modules_with_agno")
    monkeypatch.setattr(
        "ming_sim.session.write_decree_with_agno", lambda *_a, **_k: "诏",
    )


def _stage_settled_ready_edict(db, state, minister, *, delta=-3):
    from ming_sim.declaration_dispatch import pending_action_decree_ref

    affair = db.affairs.open(
        name="已落旨", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-recovery", "actor": minister, "mode": "ordinary",
            "text": "宁远补饷",
        },
    )
    ref = pending_action_decree_ref(pending_id, 1)
    db.staged_declarations.stage(
        decree_ref=ref,
        declaration={"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": delta,
            "category": "宁远补饷", "reason": "宁远补饷",
        }]}},
        turn=int(state.turn),
        verdict={"decision": "promulgated"},
        forecast_text="预推文",
        visible_refs={"affairs": [affair.id], "issues": [], "secret_orders": []},
    )
    return ref


def _ningyuan_ledger_rows(db):
    return list(db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE category='宁远补饷' ORDER BY id",
    ))


def _http_status_error(status: int) -> APIStatusError:
    response = SimpleNamespace(status_code=status, headers={}, request=None)
    return APIStatusError(
        message=f"http {status}",
        response=response,
        body={"error": {"message": f"http {status}"}},
    )


def test_month_call_policy_stops_on_429_without_auto_retry(monkeypatch):
    """ADR 0157：过月/召对共用策略——429 一次终止，不自动重试。"""
    sleeps: list[float] = []
    monkeypatch.setattr(
        "ming_sim.llm_transport._sleep_retry_interval",
        lambda seconds: sleeps.append(float(seconds)),
    )
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise _http_status_error(429)

    with pytest.raises(LLMUnavailable) as caught:
        run_with_transport(boom, policy=audience_transport_policy())

    assert calls["n"] == 1
    assert sleeps == []
    assert caught.value.status_code == 429
    assert (caught.value.transport_attempts or [])[0]["outcome"] == "terminal_fail"


def test_month_call_policy_retries_5xx_and_timeout_up_to_three_with_five_second_gap(
    monkeypatch,
):
    """本身 + 两次重试共三次；5xx / 超时隔五秒再试。"""
    sleeps: list[float] = []
    monkeypatch.setattr(
        "ming_sim.llm_transport._sleep_retry_interval",
        lambda seconds: sleeps.append(float(seconds)),
    )
    sequence = [
        _http_status_error(500),
        APITimeoutError(request=None),
        _http_status_error(503),
    ]
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise sequence[calls["n"] - 1]

    with pytest.raises(LLMUnavailable):
        run_with_transport(boom, policy=audience_transport_policy())

    assert calls["n"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert sleeps == [TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS] * (
        TRANSPORT_DEFAULT_MAX_ATTEMPTS - 1
    )


def test_forecast_exhaustion_does_not_overwrite_prior_ending(game, monkeypatch, tmp_path):
    """补跑用尽只写失败标记，不得覆盖先前已提交的结局事实。"""
    import ming_sim.decree_forecast as decree_forecast

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    from ming_sim.declaration_dispatch import pending_action_decree_ref

    first_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "ending", "actor": minister, "mode": "ordinary",
                 "text": "退位"},
    )
    first_ref = pending_action_decree_ref(first_id, 1)
    db.staged_declarations.stage(
        decree_ref=first_ref,
        declaration={"effects": {"emperor_fate": "abdicate"}},
        turn=int(state.turn), verdict={"decision": "promulgated"},
    )
    second_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "needs-forecast", "actor": minister, "mode": "ordinary",
                 "text": "补跑失败"},
    )
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    failed = {"once": True}

    def produce(*_a, **_k):
        if failed["once"]:
            failed["once"] = False
            raise LLMUnavailable("catch-up exhausted")
        return {
            "verdict": {"decision": "promulgated"},
            "declaration": {"effects": {}},
            "questions": None,
            "forecast_text": "补跑完成",
        }

    monkeypatch.setattr(decree_forecast, "produce_forecast_product", produce)
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *_a, **_k: "")
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert db.staged_declarations.is_settled(first_ref)
    assert (chain.get("declaration_outcome") or {}).get("status") == "emperor_abdicate"
    assert (chain.get("call_failure") or {}).get("kind") == "model_exhausted"
    assert db.get_decree_dossier(second_id) is not None

    db.save_turn_report(state, "邸报已成")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert db.staged_declarations.is_settled(first_ref)


def test_world_text_exhaustion_stops_month_keeps_settled_edicts(game, monkeypatch, tmp_path):
    """步骤 3 世界推演用尽：停住当前过月 run，已落旨不动，留错误包与可续相位。"""
    import ming_sim.month_chain as month_chain

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    state.metrics["国库"] = 500_000
    db.save_state(state)
    ref = _stage_settled_ready_edict(db, state, minister, delta=-7)
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)

    def exhaust(*_a, **_k):
        raise LLMUnavailable(
            "world push exhausted", code="llm_http_500", status_code=500,
            provider_message="upstream 500",
        )

    monkeypatch.setattr(month_chain, "run_world_segment_text", exhaust)
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)

    assert int(state.turn) == turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.staged_declarations.is_settled(ref)
    rows = _ningyuan_ledger_rows(db)
    assert len(rows) == 1 and int(rows[0]["delta"]) == -7
    abort = caught.value
    assert abort.error_pack_path
    assert abort.stage in {"world_text", "world-segment", "world_segment"}
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    failure = chain.get("call_failure") or {}
    assert failure.get("kind") == "model_exhausted"
    assert failure.get("error_pack_path") == abort.error_pack_path
    assert "world" in str(failure.get("step") or abort.stage)
    assert not chain.get("world_text_ready")
    assert not chain.get("world_committed")


def test_world_translate_exhaustion_keeps_text_resume_retries_translate_only(
    game, monkeypatch, tmp_path,
):
    """段文已存、转译用尽：重开只续转译，不重推世界段文；已落不动。"""
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    state.metrics["国库"] = 500_000
    db.save_state(state)
    ref = _stage_settled_ready_edict(db, state, minister, delta=-5)
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)

    world_calls = []
    translate_calls = []

    def world(*_a, **_k):
        world_calls.append(1)
        return "世界段已成文。"

    def translate_fail(*_a, **_k):
        translate_calls.append("fail")
        raise LLMUnavailable(
            "translate exhausted", code="llm_timeout", provider_message="timeout",
        )

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_translate, "translate_month_segment", translate_fail)
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert chain.get("world_text_ready") is True
    assert chain.get("world_text") == "世界段已成文。"
    assert not chain.get("world_committed")
    assert db.staged_declarations.is_settled(ref)
    rows_after_fail = _ningyuan_ledger_rows(db)
    assert len(rows_after_fail) == 1 and int(rows_after_fail[0]["delta"]) == -5
    assert world_calls == [1]
    assert translate_calls == ["fail"]

    def translate_ok(*_a, **_k):
        translate_calls.append("ok")
        return {"effects": {}}

    monkeypatch.setattr(month_translate, "translate_month_segment", translate_ok)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not repush world")),
    )
    db.save_turn_report(state, "邸报已成")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert world_calls == [1]
    assert translate_calls == ["fail", "ok"]
    assert len(_ningyuan_ledger_rows(db)) == 1
    assert int(_ningyuan_ledger_rows(db)[0]["delta"]) == -5


def test_escape_hatch_discards_world_segment_only_on_second_player_retry(
    game, monkeypatch, tmp_path,
):
    """转译再点重试仍用尽 → 继续停；再点同一钮才丢段重推，已落不动。"""
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    state.metrics["国库"] = 400_000
    db.save_state(state)
    ref = _stage_settled_ready_edict(db, state, minister, delta=-2)
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)

    world_texts = ["第一段文", "逃生口重推段文"]
    world_calls = {"n": 0}

    def world(*_a, **_k):
        text = world_texts[min(world_calls["n"], len(world_texts) - 1)]
        world_calls["n"] += 1
        return text

    translate_results = [
        LLMUnavailable("t1", code="llm_timeout"),
        LLMUnavailable("t2", code="llm_timeout"),
        {"effects": {}},
    ]
    translate_calls = {"n": 0}

    def translate(*_a, **_k):
        item = translate_results[translate_calls["n"]]
        translate_calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert chain.get("world_text") == "第一段文"
    assert (chain.get("call_failure") or {}).get("escape_armed") is False
    assert len(_ningyuan_ledger_rows(db)) == 1

    # 第一次玩家重试：仍只续转译，不丢段；再次用尽后武装逃生口
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert chain.get("world_text") == "第一段文"
    assert world_calls["n"] == 1
    assert (chain.get("call_failure") or {}).get("escape_armed") is True
    assert len(_ningyuan_ledger_rows(db)) == 1

    # 第二次玩家重试：丢段重推
    db.save_turn_report(state, "邸报已成")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert world_calls["n"] == 2
    assert translate_calls["n"] == 3
    assert db.staged_declarations.is_settled(ref)
    assert len(_ningyuan_ledger_rows(db)) == 1
    assert int(_ningyuan_ledger_rows(db)[0]["delta"]) == -2


def test_settlement_recovery_projects_month_call_failure(
    game, monkeypatch, tmp_path, _offline_scene_beat_generator,
):
    """核账期投影交出错误原文、错误包路径与可重试（#1854 只承接呈现）。"""
    import ming_sim.month_chain as month_chain
    import web_app

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    web_game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", web_game)
    db, state = web_game.db, web_game.state
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)

    def exhaust(*_a, **_k):
        raise LLMUnavailable(
            "核账期可见原文", code="llm_http_502", status_code=502,
            provider_message="bad gateway",
        )

    monkeypatch.setattr(month_chain, "run_world_segment_text", exhaust)
    session = web_game.session
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    assert state.turn_phase == TurnPhase.SETTLING.value
    recovery = web_game.state_payload().get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery.get("retryable") is True
    assert recovery.get("ready_replay") is False
    assert recovery.get("error_pack_path")
    assert "核账期可见原文" in str(recovery.get("message") or "")
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert (chain.get("call_failure") or {}).get("error_pack_path") == recovery[
        "error_pack_path"
    ]
    web_game.session.close()


def test_code_exception_during_world_commit_keeps_phase_and_settled_edicts(
    game, monkeypatch, tmp_path,
):
    """代码异常响亮中止+错误包；已落旨与已存段文保留，按相位续而非强行重调模型。"""
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    state.metrics["国库"] = 300_000
    db.save_state(state)
    ref = _stage_settled_ready_edict(db, state, minister, delta=-4)
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)

    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *_a, **_k: "段文已存",
    )

    def boom_commit(*_a, **_k):
        raise RuntimeError("injected commit bug")

    monkeypatch.setattr(month_translate, "dispatch_month_segment", boom_commit)
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)

    assert caught.value.error_pack_path
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert int(state.turn) == turn
    assert db.staged_declarations.is_settled(ref)
    assert len(_ningyuan_ledger_rows(db)) == 1
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    failure = chain.get("call_failure") or {}
    assert failure.get("kind") == "code_exception"
    assert chain.get("world_text_ready") is True
    assert chain.get("world_text") == "段文已存"
    assert not chain.get("world_committed")
