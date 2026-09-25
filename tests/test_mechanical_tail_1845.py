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
from concurrent.futures import Future

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


def test_advance_schedules_mechanical_tail_after_front_month_advance(game, monkeypatch):
    """提交到受管后台票；无需线程即可核实尾工作不在前台调用栈执行。"""
    db, state, content = game
    closed_turn = int(state.turn)
    closed_year, closed_period = int(state.year), int(state.period)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)
    brew_calls = []

    def recording_brew(_session, **kwargs):
        brew_calls.append({
            "year": kwargs.get("settled_year"),
            "period": kwargs.get("settled_period"),
            "turn": kwargs.get("closed_turn"),
        })
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", recording_brew)
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()

    class DeferredExecutor:
        def submit(self, fn):
            self.fn = fn
            self.future = Future()
            return self.future

    executor = DeferredExecutor()
    monkeypatch.setattr("ming_sim.audience_translation._executor", executor)
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert int(state.turn) == closed_turn + 1
    assert not brew_calls
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "pending"

    executor.fn()
    executor.future.set_result(None)
    assert get_session_write_queue(session).wait_idle(timeout_s=1)
    assert brew_calls == [{
        "year": closed_year, "period": closed_period, "turn": closed_turn,
    }]
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"


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

    def recording_brew(_session, **kwargs):
        calls.append(kwargs.get("closed_turn"))
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", recording_brew,
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
        "ming_sim.mechanical_tail._run_relation_brew", boom,
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


def test_web_barrier_resumes_pending_tail_before_join(game, monkeypatch):
    """Web 共用过月 barrier 入口先恢复 pending 尾，再等待队列。"""
    import ming_sim.audience_translation as audience_translation
    from ming_sim.mechanical_tail import mark_mechanical_tail_pending

    db, state, content = game
    closed_turn = max(0, int(state.turn) - 1)
    mark_mechanical_tail_pending(
        db, closed_turn, settled_year=state.year, settled_period=state.period,
    )
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()
    queue = get_session_write_queue(session)
    order = []

    class InlineExecutor:
        def submit(self, fn):
            future = Future()
            try:
                future.set_result(fn())
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(audience_translation, "_executor", InlineExecutor())
    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew",
        lambda *_a, **_k: order.append("tail-done"),
    )
    monkeypatch.setattr(
        "ming_sim.audience_translation.catch_up_pending_translations",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "ming_sim.audience_translation.list_pending_translations", lambda *_a: [],
    )
    monkeypatch.setattr(
        "ming_sim.audience_night.commit_late_night_approved", lambda *_a, **_k: None,
    )
    original_barrier = queue.barrier

    def barrier(fn):
        order.append("barrier")
        assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
        return original_barrier(fn)

    monkeypatch.setattr(queue, "barrier", barrier)
    session.await_translations_before_month()
    assert order == ["tail-done", "barrier"]


def test_non_exhausted_tail_failure_stays_pending_and_retries(game, monkeypatch):
    """后台程序异常须传播至 Future 观察面并保留 pending，后续入口能重提。"""
    import ming_sim.audience_translation as audience_translation

    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)
    session = make_light_session(db, state, content)
    session._write_gate = threading.Lock()
    session.llm_config = object()
    session.agno_db = object()
    calls = []

    class InlineExecutor:
        def submit(self, fn):
            future = Future()
            try:
                future.set_result(fn())
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(audience_translation, "_executor", InlineExecutor())

    def fail(*_a, **_k):
        calls.append(1)
        raise RuntimeError("internal failure")

    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", fail)
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "pending"
    from ming_sim.mechanical_tail import ensure_mechanical_tails
    ensure_mechanical_tails(session)
    assert len(calls) == 2
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "pending"


def test_ending_summary_runs_in_mechanical_tail_after_advance(game, monkeypatch):
    """结局判定在推进前；结局总评属推进后机械尾。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", lambda *a, **k: None,
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
    db.conn.execute(
        """
        INSERT INTO event_memories (
            subject_type, subject_id, turn, year, period, event_type, title,
            outcome, sentiment, importance, tags, source_kind, source_id, body
        ) VALUES (
            'court', 'chapter', ?, ?, ?, 'chapter_summary', '朝局',
            '旧', 'neutral', 5, '[]', 'turn_report', ?, ?
        )
        """,
        (state.turn, state.year, state.period, str(state.turn), "旧档章节内容"),
    )
    db.conn.commit()
    db.save_turn_report(state, "历月邸报正文")

    # 大臣知识面
    name = next(iter(content.characters))
    knowledge = build_character_knowledge(db, state, name)
    public = knowledge.get("public_events") or []
    assert all(row.get("kind") != "chapter_summary" for row in public)
    assert any(str(row.get("source_id") or "").startswith("projection:turn_report:") for row in public)

    # 结局时间线：改读邸报，不再灌章节正文
    timeline = build_timeline(db, upto_turn=state.turn)
    assert all("chapter" not in row for row in timeline)
    assert all("gazette" in row for row in timeline)

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
        "ming_sim.mechanical_tail._run_relation_brew", lambda *a, **k: None,
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


def test_ending_summary_keeps_llm_text_and_drops_empty(game, monkeypatch):
    """空输出与调用失败都不落固定年月句式。失败原样抛出。"""
    from ming_sim.mechanical_tail import generate_ending_summary_for_tail

    db, state, _content = game
    db.save_turn_report(state, "邸报原文")
    outcome = {"status": "emperor_abdicate", "summary": "退位"}
    monkeypatch.setattr(
        "ming_sim.agents.create_ending_summary_agent", lambda *_a, **_k: object(),
    )

    monkeypatch.setattr("ming_sim.agents.run_agent_text", lambda *_a, **_k: "  ")
    assert generate_ending_summary_for_tail(
        db, state, outcome, llm_config=object(),
    ) == ""
    assert db.get_ending_summary() is None

    def explode(*_a, **_k):
        raise RuntimeError("model down")

    monkeypatch.setattr("ming_sim.agents.run_agent_text", explode)
    with pytest.raises(RuntimeError, match="model down"):
        generate_ending_summary_for_tail(db, state, outcome, llm_config=object())
    assert db.get_ending_summary() is None

    monkeypatch.setattr("ming_sim.agents.run_agent_text", lambda *_a, **_k: "史评正文")
    assert generate_ending_summary_for_tail(
        db, state, outcome, llm_config=object(),
    ) == "史评正文"
    saved = db.get_ending_summary()
    assert saved is not None
    assert saved["summary"] == "史评正文"


def test_cli_ending_reads_summary_after_open_tail_ticket(game, monkeypatch):
    """CLI 终局先等写队列里的尾票，再读总评。"""
    from ming_sim.cli.terminal import _printed_ending_summary
    from ming_sim.session_write_queue import SessionWriteQueue, get_session_write_queue

    db, state, content = game
    session = make_light_session(db, state, content)
    queue = get_session_write_queue(session)
    ticket = queue.claim(key=("mechanical-tail", int(state.turn)))
    original = SessionWriteQueue.wait_idle

    def land_then_wait(self, **kwargs):
        db.save_ending_summary(state, "emperor_abdicate", "史评正文", [])
        self.complete(ticket)
        return original(self, **kwargs)

    monkeypatch.setattr(SessionWriteQueue, "wait_idle", land_then_wait)
    assert _printed_ending_summary(session) == "史评正文"
