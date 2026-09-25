"""#1845：机械尾后台化、章节记忆退役、历月邸报索引。

Seams:
- month_chain / resolve_turn 推进后启动机械尾（关系酿制 + 结局总评）
- SessionWriteQueue 票键 (\"mechanical-tail\", closed_turn)：不挡新月前台；下次过月 barrier join
- 未完尾按 month_chain 持久状态重开续接；耗尽降级后终结，不永久卡住
- 章节记忆三读者（大臣知识面 / 结局时间线 / 材料目录）不再读 chapter_summary
- 召对高亮不在本票机械尾（沿 ADR 0045）
"""

from __future__ import annotations

import threading
import time

import pytest

import ming_sim.month_chain as month_chain
import ming_sim.decree as decree_mod
from ming_sim.applier import Provenance
from ming_sim.session_write_queue import get_session_write_queue
from tests.settlement_seam_helpers import make_light_session


def _forbid_extractor(monkeypatch):
    assert not hasattr(decree_mod, "extract_scores_by_modules_with_agno")
    monkeypatch.setattr(
        "ming_sim.session.write_decree_with_agno", lambda *_a, **_k: "诏",
    )


def _archive_and_stub_world(db, state, monkeypatch):
    db.save_turn_report(state, "本月邸报正文·公开")
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment",
        lambda *a, **k: {"effects": {}},
    )


def test_advance_starts_mechanical_tail_without_blocking_new_month(game, monkeypatch):
    """推进后机械尾后台跑；前台立刻进入新月，不等酿制结束。"""
    db, state, content = game
    closed_turn = int(state.turn)
    closed_year, closed_period = int(state.year), int(state.period)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    brew_started = threading.Event()
    brew_release = threading.Event()
    brew_calls = []

    def slow_brew(db_, state_, brew_fn, **kwargs):
        brew_started.set()
        assert brew_release.wait(timeout=5)
        brew_calls.append({
            "year": kwargs.get("settled_year"),
            "period": kwargs.get("settled_period"),
            "turn": kwargs.get("settled_turn"),
        })
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew", slow_brew,
    )

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert int(state.turn) == closed_turn + 1
    assert brew_started.wait(timeout=2), "机械尾应在推进后立即启动"
    # 前台已在新月；酿制仍可被拦住 → 证明不等待
    assert not brew_calls
    brew_release.set()
    queue = get_session_write_queue(session)
    assert queue.wait_idle(timeout_s=5)
    assert brew_calls == [{
        "year": closed_year, "period": closed_period, "turn": closed_turn,
    }]
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("mechanical_tail", {}).get("status") == "done"


def test_next_month_waits_for_prior_mechanical_tail(game, monkeypatch):
    """下次过月在主链前 join 上月尾；未终结则等待，不跳过。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    brew_started = threading.Event()
    brew_release = threading.Event()
    order = []

    def slow_brew(*_a, **_k):
        order.append("brew-start")
        brew_started.set()
        assert brew_release.wait(timeout=5)
        order.append("brew-done")
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew", slow_brew,
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert brew_started.wait(timeout=2), "上月机械尾应已启动"
    assert "brew-done" not in order

    # 新月再过月：须等上月尾结束
    db.save_turn_report(state, "新月邸报")
    next_started = threading.Event()

    def mark_world(*_a, **_k):
        next_started.set()
        return ""

    monkeypatch.setattr(month_chain, "run_world_segment_text", mark_world)

    def finish_later():
        time.sleep(0.05)
        brew_release.set()

    threading.Thread(target=finish_later).start()
    result = session.resolve_turn(allow_empty_decree=True)
    assert "brew-done" in order
    assert next_started.is_set()
    assert result.stage in {"gazette", "advanced", "rescript"}


def test_reopen_resumes_incomplete_mechanical_tail(game, monkeypatch):
    """崩溃后只留 DB 未完标记时，同过月入口续接，不因重开跳过或重复执行。"""
    db, state, content = game
    closed_turn = int(state.turn)
    closed_year, closed_period = int(state.year), int(state.period)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    from ming_sim.mechanical_tail import ensure_mechanical_tails

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    calls = []

    def recording_brew(*_a, **kwargs):
        calls.append(kwargs.get("settled_turn"))
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew", recording_brew,
    )
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert calls == [closed_turn]

    # 模拟进程退出后只剩 DB pending、写队列票已失
    chain = month_chain._load_chain(db, closed_turn)
    chain["mechanical_tail"] = {
        "status": "pending",
        "settled_year": closed_year,
        "settled_period": closed_period,
        "ending_outcome": None,
    }
    month_chain._save_chain(db, closed_turn, chain, source=Provenance.system_simulation)
    calls.clear()
    ensure_mechanical_tails(session)
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert calls == [closed_turn]
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"


def test_exhausted_mechanical_tail_degrades_and_unblocks_next_month(game, monkeypatch):
    """模型耗尽按既有降级留痕终结，下次过月不永久卡住。"""
    from ming_sim.exceptions import LLMUnavailable

    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    def boom(*_a, **_k):
        raise LLMUnavailable("酿制耗尽", stage="relation-brew")

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew", boom,
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    status = month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"]
    assert status == "degraded"

    db.save_turn_report(state, "下月邸报")
    # 不得因上月尾永久阻塞
    assert session.resolve_turn(allow_empty_decree=True).stage in {
        "gazette", "advanced", "rescript",
    }


def test_ending_summary_runs_in_mechanical_tail_after_advance(game, monkeypatch):
    """结局判定在推进前；结局总评属推进后机械尾。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew",
        lambda *a, **k: {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0},
    )
    summary_turns = []

    def fake_summary(db_, state_, outcome, **_k):
        summary_turns.append(int(state_.turn))
        db_.save_ending_summary(state_, str(outcome.get("status") or ""), "史评", [])
        return "史评"

    monkeypatch.setattr(
        "ming_sim.mechanical_tail.generate_ending_summary_for_tail", fake_summary,
    )
    monkeypatch.setattr(
        "ming_sim.context.victory_status",
        lambda *_a, **_k: {"status": "emperor_abdicate", "summary": "退位"},
    )

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert state.ended is True
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    assert summary_turns == [closed_turn]
    ending = db.get_ending_summary()
    assert ending is not None
    assert ending["summary"] == "史评"


def test_chapter_memory_retired_from_three_readers(game):
    """大臣知识面 / 结局时间线 / 材料目录均不再吃章节记忆。"""
    from ming_sim.knowledge import build_character_knowledge
    from ming_sim.memories import build_timeline
    from ming_sim.materials import prepare_world_materials, list_materials, release_material_tree

    db, state, content = game
    marker = "章节记忆退役哨兵-不得出现"
    db.save_chapter_memory(state, "朝局", marker)
    db.save_turn_report(state, "历月邸报正文可供自读")

    # 大臣知识面
    name = next(iter(content.characters))
    knowledge = build_character_knowledge(db, state, name)
    blob = str(knowledge)
    assert marker not in blob
    public = knowledge.get("public_events") or []
    assert all(row.get("kind") != "chapter_summary" for row in public)
    assert any("历月邸报正文" in str(row.get("body") or "") for row in public)

    # 结局时间线：改读邸报，不再灌章节正文
    timeline = build_timeline(db, upto_turn=state.turn)
    assert all(marker not in str(row.get("chapter") or "") for row in timeline)
    assert any("历月邸报正文" in str(row.get("gazette") or "") for row in timeline)

    # 材料目录：有邸报索引，无章节记忆路径
    prepared = prepare_world_materials(db, state)
    try:
        names = list_materials(prepared.root)
        assert any(n.startswith("邸报/") for n in names)
        assert not any("章节" in n or "chapter" in n.lower() for n in names)
    finally:
        release_material_tree(prepared.root)


def test_mechanical_tail_does_not_schedule_audience_highlight(game, monkeypatch):
    """高亮不属机械尾：推进后不得补跑召对高亮。"""
    db, state, content = game
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)
    monkeypatch.setattr(
        "ming_sim.mechanical_tail.run_month_end_relation_brew",
        lambda *a, **k: {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0},
    )
    highlight_calls = []

    def spy_highlight(*_a, **_k):
        highlight_calls.append(1)

    for target in (
        "ming_sim.agents.create_highlight_agent",
        "ming_sim.audience_extraction.schedule_highlight",
    ):
        try:
            monkeypatch.setattr(target, spy_highlight)
        except Exception:
            pass

    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert highlight_calls == []
