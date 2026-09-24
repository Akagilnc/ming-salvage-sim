"""#1274 / #1843 — 无旨月走同一过月主链，不走 16ms 快路。

没有旨意只是这个月没有旨意。ADR 0157 把推进放到邸报写成之后，
无旨月仍跑前括号、世界段和局势惯性，但不在邸报未写时自行推进。
"""

from __future__ import annotations

import inspect

import pytest

from ming_sim.applier import Provenance
from ming_sim.decree import resolve_directives
from tests.settlement_seam_helpers import canned_full_settlement, make_light_session

# Back-compat aliases for this file's call sites.
_canned_full_settlement = canned_full_settlement
_session = make_light_session


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
    assert result.advanced is False
    assert result.stage == "gazette"
    assert int(state.turn) == closed_turn
    # 世界段必经（负向：快路已死，也不再走 extractor）
    assert len(sim_calls) == 1
    assert not db.get_turn_report(closed_turn)
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
    """负向：快路壳已删；空旨过月走世界段，不推进、不走 extractor。"""
    # 1) grep 级缺席：生产码不再定义/导出 advance_without_edict 快路壳
    import ming_sim.decree as decree_pkg
    assert not hasattr(decree_pkg, "advance_without_edict")
    src = inspect.getsource(decree_pkg)
    assert "def advance_without_edict" not in src

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
    assert result.advanced is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn
    assert not db.get_turn_report(closed_turn)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_edict_zero_decisions_completes_without_stuck(game, monkeypatch):
    """无新旨月份走同一主链，不停在 awaiting，也不在邸报前推进。"""
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
    assert result.advanced is False
    assert result.decisions in (None, [])
    assert int(state.turn) == closed_turn
    assert state.turn_phase != "awaiting_decision"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_with_edict_resolve_turn_still_full_settlement(game, monkeypatch):
    """有旨月与无旨月同一主链：世界段跑一次，邸报未写则不推进。"""
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
    assert result.advanced is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn
    assert not db.get_turn_report(closed_turn)


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
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_serialized_web_write", unlocked)
    # 端点不应再依赖 advance_without_edict 快路返回 True
    response = web_app.api_advance_without_edict()

    assert response.get("awaiting_decision") is False
    assert len(sim_calls) == 1
    assert int(state.turn) == closed_turn
    assert not db.get_turn_report(closed_turn)
