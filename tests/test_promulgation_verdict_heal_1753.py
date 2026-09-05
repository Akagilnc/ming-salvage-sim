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
    create_kwargs: list[dict] = []
    create_agents: list[object] = []

    def spy_create(*a, **k):
        # 记录会话生命周期接缝；返回轻量替身供 run 边界观察。
        create_kwargs.append({
            "args_len": len(a),
            "agno_db": a[1] if len(a) > 1 else k.get("agno_db"),
            "session_id": k.get("session_id"),
            "kwargs": dict(k),
        })
        agent = object()
        create_agents.append(agent)
        return agent

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", spy_create)

    # 真工厂配置核验（不跑模型）：db/session/history 三件必须齐。
    import tempfile
    from agno.db.sqlite import SqliteDb
    from ming_sim.agents import create_promulgation_judge_agent as real_create
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="test", base_url="http://example.invalid", model="m")
    with tempfile.TemporaryDirectory() as td:
        probe_db = SqliteDb(db_file=f"{td}/probe.db")
        probe = real_create(cfg, probe_db, session_id="promulgation-judge-turn-probe")
        assert getattr(probe, "db", None) is probe_db
        assert getattr(probe, "cache_session", None) is True
        assert getattr(probe, "add_history_to_context", None) is True
        assert getattr(probe, "session_id", None) == "promulgation-judge-turn-probe"

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

    # agno_db 非 None 才能走会话绑定；轻量 sqlite 占位。
    import tempfile as _tf
    from agno.db.sqlite import SqliteDb as _SqliteDb
    with _tf.TemporaryDirectory() as _td:
        agno_db = _SqliteDb(db_file=f"{_td}/agno.db")
        result = decree_mod.resolve_directives(
            state, db, agno_db, None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    # first attempt + exactly heal_budget heals until success on last
    assert len(run_calls) == heal_budget + 1
    assert len(create_agents) == 1  # same-session: one agent
    assert {c["agent_id"] for c in run_calls} == {id(create_agents[0])}
    # 工厂收到 turn 作用域 session_id 与 agno_db（会话生命周期真源）
    assert create_kwargs and create_kwargs[0]["agno_db"] is not None
    assert create_kwargs[0]["session_id"] == f"promulgation-judge-turn-{before_turn}"
    first_prompt = run_calls[0]["prompt"]
    assert str(first_id) in first_prompt and str(second_id) in first_prompt
    # 补交输入必须含：原始产出、失败原因、待判 id 全集、以及首抽快照（全案卷身份）
    for heal_call in run_calls[1:]:
        prompt = heal_call["prompt"]
        assert prompt, "heal must carry correction feedback"
        assert "校验失败原因" in prompt or "契约" in prompt
        assert "原始产出" in prompt
        # 首抽快照进入补交输入（draft 回喂形 / 会话续接可核）
        assert str(first_id) in prompt and str(second_id) in prompt
        assert "待判案卷 dossier_id 全集" in prompt
        if mode == "illegal_id":
            assert "not-int" in prompt
            assert "正整数" in prompt or "dossier_id" in prompt
        else:
            assert "覆盖" in prompt or "静默" in prompt or "proposed" in prompt
    # 判决按既有路径落账（pending 在 settle 尾会清；案卷不得仍全是 proposed）
    remaining_proposed = {
        int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in remaining_proposed
    assert second_id not in remaining_proposed


def _spy_create_agent(monkeypatch):
    agents: list[object] = []

    def spy_create(*a, **k):
        agent = object()
        agents.append(agent)
        return agent

    monkeypatch.setattr(decree_mod, "create_promulgation_judge_agent", spy_create)
    return agents


@pytest.mark.parametrize(
    "mode",
    ["illegal_id", "missing_coverage"],
    ids=["a-illegal-id", "b-missing-coverage"],
)
def test_promulgation_heal_exhausted_fail_closed_keeps_evidence(
    game, monkeypatch, mode,
):
    """补交 3 次仍不合规 → 整月可恢复失败；error pack 含 ≤4 份坏输出 + 已合规判决。

    走真实 llm_promulgation_verdicts + run_agent_text 边界（不整函数替身）。
    """
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    before_turn = int(state.turn)
    baseline = {
        first_id: db.get_decree_dossier(first_id),
        second_id: db.get_decree_dossier(second_id),
    }
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    agents = _spy_create_agent(monkeypatch)
    run_prompts: list[str] = []

    def always_bad_run(agent, prompt, tag=""):
        run_prompts.append(str(prompt))
        if mode == "illegal_id":
            payload = {
                "verdicts": [
                    {"dossier_id": "bad-id", "decision": "promulgated"},
                    {"dossier_id": second_id, "decision": "promulgated"},
                ],
            }
        else:
            # 漏盖：仅第一案合规
            payload = {
                "verdicts": [
                    {"dossier_id": first_id, "decision": "promulgated"},
                ],
            }
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(decree_mod, "run_agent_text", always_bad_run)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert ei.value.stage == "promulgation"
    assert int(state.turn) == before_turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.get_pending_promulgation_verdicts(before_turn) == []
    assert len(run_prompts) == heal_budget + 1
    assert len(agents) == 1
    # 补交 prompt 含原始产出与失败原因（真解析路径）
    assert any("校验失败原因" in p or "契约" in p for p in run_prompts[1:])
    for did, snap in baseline.items():
        assert db.get_decree_dossier(did) == snap
        assert db.list_decree_dossier_decisions(did) == []

    pack = Path(ei.value.error_pack_path)
    assert pack.is_dir()
    delta = json.loads((pack / "delta.json").read_text(encoding="utf-8"))
    bad_outputs = delta.get("promulgation_heal_bad_outputs")
    assert isinstance(bad_outputs, list)
    assert len(bad_outputs) == heal_budget + 1
    compliant = delta.get("promulgation_compliant_verdicts")
    assert isinstance(compliant, list)
    compliant_ids = {
        int(row["dossier_id"]) for row in compliant
        if isinstance(row, dict) and isinstance(row.get("dossier_id"), int)
    }
    if mode == "missing_coverage":
        assert first_id in compliant_ids
        assert second_id not in compliant_ids  # 不伪造缺判
    if mode == "illegal_id":
        assert second_id in compliant_ids
        assert first_id not in compliant_ids


def test_promulgation_heal_keeps_earlier_compliant_across_attempts(
    game, monkeypatch,
):
    """首抽含案卷 A 合规、后续补交仍失败且不含 A → error pack 仍保留 A。"""
    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    _spy_create_agent(monkeypatch)
    n = {"c": 0}

    def shifting_bad(agent, prompt, tag=""):
        n["c"] += 1
        if n["c"] == 1:
            # 首抽：A 合规 + 漏 B
            payload = {
                "verdicts": [
                    {"dossier_id": first_id, "decision": "promulgated"},
                ],
            }
        else:
            # 后续：完全空批，A 不再出现
            payload = {"verdicts": []}
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(decree_mod, "run_agent_text", shifting_bad)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert n["c"] == heal_budget + 1
    delta = json.loads(
        Path(ei.value.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    compliant = delta.get("promulgation_compliant_verdicts") or []
    compliant_ids = {
        int(row["dossier_id"]) for row in compliant
        if isinstance(row, dict) and isinstance(row.get("dossier_id"), int)
    }
    assert first_id in compliant_ids  # 前轮好不得被后轮冲掉
    assert second_id not in compliant_ids


def test_promulgation_heal_preserves_non_json_raw_in_correction_and_pack(
    game, monkeypatch,
):
    """非 JSON 原文须进入补交回喂与 error pack，不得落成空 list。"""
    db, state, content = game
    _stage_two_policy_dossiers(db, state)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    _spy_create_agent(monkeypatch)
    raw_text = "这不是 JSON，只是判官胡言。"
    prompts: list[str] = []

    def non_json_run(agent, prompt, tag=""):
        prompts.append(str(prompt))
        return raw_text

    monkeypatch.setattr(decree_mod, "run_agent_text", non_json_run)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )

    assert len(prompts) == heal_budget + 1
    # 补交须附原始非 JSON 文本
    assert any(raw_text in p for p in prompts[1:])
    delta = json.loads(
        Path(ei.value.error_pack_path, "delta.json").read_text(encoding="utf-8")
    )
    bad_outputs = delta.get("promulgation_heal_bad_outputs") or []
    assert len(bad_outputs) == heal_budget + 1
    assert any(raw_text in str(item) for item in bad_outputs)


def test_promulgation_heal_exhausted_recovery_via_resolve_turn(
    game, monkeypatch,
):
    """耗尽后从 GameSession.resolve_turn 真实恢复入口接续 → 月份只 +1、pre_settle 不重复。"""
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    first_id, second_id = _stage_two_policy_dossiers(db, state)
    # resolve_turn 需要 draft 指令才能过无旨门；案卷已有，再落一条 draft 关联即可。
    db.add_directive(
        state, None, "清核河工并整饬漕运", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": f"river-{state.turn}",
        },
    )
    before_turn = int(state.turn)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)

    real_llm = decree_mod.llm_promulgation_verdicts
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
        # 以当刻 proposed 为准（resolve_turn ensure 可能多落案卷）。
        proposed_ids = [
            int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
        ]
        if phase["n"] <= heal_budget + 1:
            # 漏盖：只判第一案
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

    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre_settle)
    monkeypatch.setattr(decree_mod, "run_agent_text", run_then_good)
    _spy_create_agent(monkeypatch)
    # 保留真 llm_promulgation；canned 只钉 sim/extract
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    monkeypatch.setattr(decree_mod, "pre_settle", spy_pre_settle)
    monkeypatch.setattr(decree_mod, "run_agent_text", run_then_good)

    monkeypatch.setattr(session_mod, "MinisterRegistry", lambda *a, **k: object())
    monkeypatch.setattr(
        session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *a, **k: "清核河工并整饬漕运",
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = None
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.last_decree = "清核河工并整饬漕运"
    sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = None
    sess._beat_generator = None
    sess._write_gate = None
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)
    monkeypatch.setattr(
        GameSession, "_write_gate_if_free", lambda self: None,
    )
    monkeypatch.setattr(
        GameSession, "_draft_fingerprint", lambda self, _dirs: (),
    )

    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn(decree="清核河工并整饬漕运")
    assert ei.value.stage == "promulgation"
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert pre_settle_calls == [before_turn]

    # 真实恢复入口：settling 无 ready → resolve_turn fallthrough
    result = sess.resolve_turn(decree="清核河工并整饬漕运")
    assert result.awaiting is False
    assert int(state.turn) == before_turn + 1
    assert pre_settle_calls == [before_turn]
    remaining_proposed = {
        int(row["id"]) for row in db.list_decree_dossiers(status="proposed")
    }
    assert first_id not in remaining_proposed
    assert second_id not in remaining_proposed


def test_promulgation_heal_retries_is_single_source(game, monkeypatch):
    """3 为单一真源：耗尽时真实 LLM 调用次数 = 1 + PROMULGATION_VERDICT_HEAL_RETRIES。"""
    db, state, content = game
    _stage_two_policy_dossiers(db, state)
    heal_budget = int(decree_mod.PROMULGATION_VERDICT_HEAL_RETRIES)
    assert heal_budget == 3

    real_llm = decree_mod.llm_promulgation_verdicts
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", real_llm)
    _spy_create_agent(monkeypatch)
    calls = {"n": 0}

    def bad_run(agent, prompt, tag=""):
        calls["n"] += 1
        return json.dumps({"verdicts": [{"dossier_id": "x", "decision": "promulgated"}]})

    monkeypatch.setattr(decree_mod, "run_agent_text", bad_run)

    with pytest.raises(SettlementAbort):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
        )
    assert calls["n"] == 1 + heal_budget
