"""#1274 QA J-1 — 无旨月完整结算（删 16ms 快路）。

Owner 拍板：没有旨意只是这个月没有旨意；之前下的旨、在做的事、局势惯性
都要继续跑。无旨月 = decrees=[] 的正常月，走 pre_settle + simulator +
settle_with_delta 全链（ADR 0004），禁止跳过 simulator 的快跳分支。

钉测：
1. 退朝无旨 → turn+1 且邸报叙事落库 + 局势惯性推进
2. 负向：不存在跳过 simulator 的路径（快路分支已死）
3. 有旨月回归：resolve_turn 有草案仍走完整结算
4. simulator 真零决策 → 按既有空批链路走通，不卡死
"""

from __future__ import annotations

import inspect

import pytest

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.applier import Provenance
from ming_sim.decree import advance_without_edict, resolve_directives
from ming_sim.session import GameSession


def _canned_full_settlement(monkeypatch, *, narrative="本月边情邸报：辽饷催征，流寇未息。",
                            decisions=None, simulator_calls=None, source_spy=None):
    """Replace only external LLM seams; keep production settlement spine."""
    simulator_calls = simulator_calls if simulator_calls is not None else []
    decisions = list(decisions or [])

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _sim(*a, **k):
        simulator_calls.append({
            "decree_text": a[3] if len(a) > 3 else k.get("decree_text", ""),
            "payload": k.get("simulator_payload") or (a[10] if len(a) > 10 else None),
        })
        text = narrative
        if decisions:
            # parse_decision_blocks 认 <<DECISION>> 块
            blocks = []
            for i, d in enumerate(decisions):
                title = d.get("title") or f"决策{i}"
                opts = d.get("options") or ["准", "不准"]
                opt_lines = "\n".join(f"- {o}" for o in opts)
                blocks.append(f"<<DECISION title=\"{title}\">>\n{opt_lines}\n<</DECISION>>")
            text = narrative + "\n" + "\n".join(blocks)
        return text, k.get("simulator_payload") or {}

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _sim)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')

    if source_spy is not None:
        real_settle = decree_mod.settle_with_delta

        def _spy_settle(*a, **k):
            source_spy.append(k.get("source"))
            return real_settle(*a, **k)

        monkeypatch.setattr(decree_mod, "settle_with_delta", _spy_settle)

    return simulator_calls


def _session(db, state, content):
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.content = content
    session.registry = None
    session.llm_config = None
    session.agno_db = None
    session.deaths_this_turn = []
    session.debuts_this_turn = []
    session.last_decree = ""
    session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *a, **k: None
    return session


def _issue_bars(db):
    rows = db.conn.execute(
        "SELECT id, title, bar_value FROM issues WHERE status='active' ORDER BY id"
    ).fetchall()
    return {str(r["id"]): int(r["bar_value"] or 0) for r in rows}


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_advance_runs_full_settlement_chain(game, monkeypatch):
    """无旨退朝：turn+1 + 邸报落库 + simulator 被调用 + 局势惯性有机会推进。"""
    db, state, content = game
    closed_turn = int(state.turn)
    bars_before = _issue_bars(db)
    # 至少保证有一条带非零惯性的 active issue，便于观察惯性推进
    if not bars_before:
        db.insert_issue(
            state, kind="situation", title="辽东索饷",
            bar_value=25, inertia=1,
        )
        bars_before = _issue_bars(db)

    sim_calls = []
    sources = []
    _canned_full_settlement(
        monkeypatch,
        narrative="本月邸报：无新旨，边事自演。辽饷催征未绝，流寇窥陕。",
        simulator_calls=sim_calls,
        source_spy=sources,
    )

    result = _session(db, state, content).advance_without_decree()

    assert result is not None
    assert result.awaiting is False
    assert int(state.turn) == closed_turn + 1
    # simulator 必经（负向：快路已死）
    assert len(sim_calls) == 1
    # 邸报叙事落库（正常链 save_turn_report，非快路固定套话）
    report = db.get_turn_report(closed_turn)
    assert report is not None
    assert "边事自演" in report or "邸报" in report
    # 禁快路固定套话独占月档（若 simulator 叙事在，正常链已接管）
    assert "诸事仍待来月处置" not in (report or "")
    # 来源 = system_simulation（无旨/世界自演变）
    assert any(s == Provenance.system_simulation or s == Provenance.system_simulation.value
               or s is Provenance.system_simulation for s in sources) or sources == []
    # 局势 bar：惯性推进后至少有一条变化，或 inertia 路径已跑过（空盘面也允许全不变）
    bars_after = _issue_bars(db)
    # 有 inertia≠0 的 issue 时 bar 应动；无则仅要求链跑通（上面 turn/report/sim 已锁）
    moving = [
        iid for iid, before in bars_before.items()
        if iid in bars_after and bars_after[iid] != before
    ]
    # seed 开局通常有 inertia；若本夹具全零惯性则跳过 bar 断言
    has_inertia = db.conn.execute(
        "SELECT COUNT(*) AS n FROM issues WHERE status='active' AND inertia != 0"
    ).fetchone()["n"]
    if has_inertia:
        assert moving, f"expected inertia movement; before={bars_before} after={bars_after}"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_fast_path_branch_is_dead(game, monkeypatch):
    """负向：advance_without_edict / resolve_directives 不再提供跳过 simulator 的快路。"""
    # 1) 源码层：快路推进体已死（恒 return False；无 next_period / 无 _NeedsFullSettlement）
    src = inspect.getsource(advance_without_edict)
    assert "return False" in src
    assert "return True" not in src
    assert "state.next_period" not in src
    assert "_NeedsFullSettlement" not in src
    assert "apply_fixed_period_flows" not in src

    # 2) 行为层：空旨 resolve_directives 必调 simulator
    db, state, content = game
    closed_turn = int(state.turn)
    sim_calls = []
    _canned_full_settlement(
        monkeypatch,
        narrative="世界自演变邸报。",
        simulator_calls=sim_calls,
    )
    result = resolve_directives(
        state, db, None, None, [], "",
        content=content, registry=None,
        source=Provenance.system_simulation,
    )
    assert result.awaiting is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn + 1
    assert db.get_turn_report(closed_turn)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_zero_decisions_completes_without_stuck(game, monkeypatch):
    """simulator 真零决策 → 既有空批/all-decided 链路走通，不卡在 awaiting。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _canned_full_settlement(
        monkeypatch,
        narrative="本月无重大抉择，朝局按惯性推移。",
        decisions=[],  # 零决策
    )
    result = _session(db, state, content).advance_without_decree()
    assert result is not None
    assert result.awaiting is False
    assert result.decisions in (None, [])
    assert int(state.turn) == closed_turn + 1
    # 相位不停在 awaiting_decision
    assert state.turn_phase != "awaiting_decision"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_with_edict_resolve_turn_still_full_settlement(game, monkeypatch):
    """有旨月回归：带草案 resolve_turn 仍走 simulator 全链，行为不退化。"""
    db, state, content = game
    closed_turn = int(state.turn)
    db.add_directive(
        state, None, "着户部清核辽饷。", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "liao-pay-audit-1274",
        },
    )

    sim_calls = []
    _canned_full_settlement(
        monkeypatch,
        narrative="奉诏清核辽饷。户部议覆如左。",
        simulator_calls=sim_calls,
    )
    # 免 LLM 拟诏
    monkeypatch.setattr(
        "ming_sim.session.write_decree_with_agno",
        lambda *a, **k: "着户部清核辽饷。",
    )

    result = _session(db, state, content).resolve_turn()
    assert result.awaiting is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn + 1
    report = db.get_turn_report(closed_turn)
    assert report is not None
    assert "辽饷" in report or "邸报" in report or "奉诏" in report


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_web_no_edict_endpoint_routes_to_full_settlement(game, monkeypatch):
    """Web 退朝端点：无草案时不再走 16ms 快路，必经 simulator。"""
    from contextlib import contextmanager
    from types import SimpleNamespace

    import web_app

    db, state, content = game
    closed_turn = int(state.turn)
    sim_calls = []
    _canned_full_settlement(
        monkeypatch,
        narrative="Web 无旨月邸报。",
        simulator_calls=sim_calls,
    )
    session = _session(db, state, content)
    web_game = SimpleNamespace(
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: [],
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": int(state.turn)}},
    )

    @contextmanager
    def unlocked(_game):
        yield

    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", unlocked)
    # 端点不应再依赖 advance_without_edict 快路返回 True
    response = web_app.api_advance_without_edict()

    assert response.get("awaiting_decision") is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn + 1
    assert db.get_turn_report(closed_turn)
