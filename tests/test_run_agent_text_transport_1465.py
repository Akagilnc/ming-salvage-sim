"""#1465 ② 缝级：run_agent_text 终文取 SDK 终包，非 chunk 拼接。

结算入口空转/跨墙/自愈/耗尽见 test_settlement_extractor_transport_1750（可观察流替身）。
本文件：chunk 畸形 vs 终包；history-backed 空终包重试截 run。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.agents as agents_mod
from ming_sim.db import GameDB
from ming_sim.llm_model import create_agno_db


class RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:
    def __init__(self, content=None):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


class RunOutput:
    def __init__(self, content: str):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


def test_run_agent_text_final_text_from_terminal_not_chunk_join(monkeypatch):
    """chunk 含畸形片段时，终文仍取 SDK 终包完整 content（严格 JSON 真源）。"""
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    good = '{"国势变化": {"民心": -1}, "钱粮收支": []}'

    class _ChunkGarbageTerminalGood:
        def run(self, *_a, **_k):
            yield RunContent('{"partial":')
            yield RunContent(" NOT_JSON_GARBAGE ")
            yield RunCompletedEvent(content=None)
            yield RunOutput(good)

    text = agents_mod.run_agent_text(
        _ChunkGarbageTerminalGood(), "payload", tag="extractor/internal",
    )
    assert text == good
    assert json.loads(text)["国势变化"]["民心"] == -1


def _ensure_agno_run_store(game_db: GameDB, agno_db) -> None:
    """Agno 3 表由 SqliteDb 懒建；与 audience_restore 同形强制建齐。"""
    agno_db._create_all_tables()


def _insert_completed_run(
    game_db: GameDB, session_id: str, run_id: str, *,
    run_index: int, content: str,
) -> None:
    game_db.conn.execute(
        "INSERT INTO agno_runs "
        "(run_id, session_id, run_type, status, run_index, run_data, created_at) "
        "VALUES (?, ?, 'agent', 'COMPLETED', ?, ?, ?)",
        (
            run_id,
            session_id,
            run_index,
            json.dumps(
                {"run_id": run_id, "status": "COMPLETED", "content": content},
                ensure_ascii=False,
            ),
            run_index + 1,
        ),
    )
    game_db.conn.commit()


def test_run_agent_text_history_backed_drops_empty_completed_before_retry(
    tmp_path, content, monkeypatch,
):
    """history-backed agent：空终包 completed run 落库后，transport 再试前截掉。

    真实入口 = run_agent_text；命中面 = 颁布判官同款 flags（db+cache_session+
    add_history_to_context）。替身 run 模拟 agno cleanup_and_store 落空 run。
    截缝 = GameDB.truncate_agno_session_runs（与召对同 _truncate_agno_runs_in_tx）。
    """
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    path = str(tmp_path / "hist.db")
    game_db = GameDB(path, content)
    game_db.seed_static_data()
    agno_db = create_agno_db(path)
    _ensure_agno_run_store(game_db, agno_db)
    session_id = "promulgation-judge-test-empty-retry"
    good = '{"verdicts": []}'

    # 预置 session + 既有 history run（heal 前轮），keep_count 应保留它
    prior_id = "run-prior-ok"
    game_db.conn.execute(
        "INSERT INTO agno_sessions "
        "(session_id, session_type, created_at, updated_at) VALUES (?, 'agent', 1, 1)",
        (session_id,),
    )
    game_db.conn.commit()
    _insert_completed_run(
        game_db, session_id, prior_id, run_index=0, content='{"verdicts": [1]}',
    )
    assert game_db.agno_runs_length(session_id) == 1

    class _HistoryBackedEmptyThenGood:
        """颁布判官同 flags；首 attempt 落空 completed run 再吐空终包。"""

        add_history_to_context = True
        cache_session = True
        calls = 0

        def __init__(self) -> None:
            self.session_id = session_id
            self.db = agno_db
            self._ming_game_db = game_db
            self._cached_session = SimpleNamespace(
                session_id=session_id,
                runs=[SimpleNamespace(run_id=prior_id, status="COMPLETED")],
            )
            self._cached_session_db = agno_db

        def run(self, *_a, **_k):
            self.calls += 1
            n = self.calls
            if n == 1:
                empty_id = "run-empty-completed"
                # 模拟 agno cleanup_and_store：空终包以 completed 落库
                _insert_completed_run(
                    game_db, session_id, empty_id, run_index=1, content="",
                )
                self._cached_session.runs.append(
                    SimpleNamespace(run_id=empty_id, status="COMPLETED"),
                )
                assert game_db.agno_runs_length(session_id) == 2
                yield RunContent("…")
                yield RunOutput("")
                return
            # 再试前须已截回 keep_count=1；否则空 run 仍在 history
            assert game_db.agno_runs_length(session_id) == 1, (
                f"empty completed run must be truncated before retry; "
                f"len={game_db.agno_runs_length(session_id)}"
            )
            assert self._cached_session is None, "cache_session must invalidate on truncate"
            ok_id = "run-ok"
            _insert_completed_run(
                game_db, session_id, ok_id, run_index=1, content=good,
            )
            yield RunContent("…")
            yield RunOutput(good)

    agent = _HistoryBackedEmptyThenGood()
    text = agents_mod.run_agent_text(agent, "payload", tag="promulgation-judge")
    assert text == good
    assert agent.calls >= 2
    # 终态：prior + 成功 = 2；空 completed 不得残留
    assert game_db.agno_runs_length(session_id) == 2
    rows = game_db.conn.execute(
        "SELECT run_id FROM agno_runs WHERE session_id = ? ORDER BY run_index",
        (session_id,),
    ).fetchall()
    ids = [r[0] for r in rows]
    assert prior_id in ids
    assert "run-empty-completed" not in ids
    assert "run-ok" in ids
    game_db.conn.close()
    agno_db.close()
