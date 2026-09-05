"""#1749 新局写路径：真实 HTTP 入口 tracer。

不 mock WebGame/session/归档链。断言落在 typed campaign / 独立 DB 读 / drain completion。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web_app
from ming_sim.session import GameSession
from tests.test_month_loop_tracer_1468 import (
    _assert_not_bare_500,
    _parse_sse,
    _pick_active_minister,
    tracer_client,
)
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


def _campaign(game) -> str:
    return str(game.db.kv_get("campaign_id") or "").strip()


def _counts(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        camp = conn.execute(
            "SELECT value FROM kv_store WHERE key='campaign_id'"
        ).fetchone()
        dirs = conn.execute("SELECT COUNT(*) FROM turn_directives").fetchone()
        nights = conn.execute("SELECT COUNT(*) FROM audience_nights").fetchone()
        return {
            "campaign_id": str(camp[0]) if camp and camp[0] else "",
            "directives": int(dirs[0] if dirs else 0),
            "nights": int(nights[0] if nights else 0),
        }
    finally:
        conn.close()


def _drained(root: Path) -> list[Path]:
    saves = root / "saves"
    return sorted(saves.glob("drained_*.db")) if saves.is_dir() else []


def _capture_spawns(monkeypatch) -> list:
    out: list = []
    real = web_app._spawn_drain_close

    def wrap(game, archive_db: bool = False, completion=None):
        c = real(game, archive_db=archive_db, completion=completion)
        out.append(c)
        return c

    monkeypatch.setattr(web_app, "_spawn_drain_close", wrap)
    return out


def _wait_spawns(spawns: list, start: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    fresh = spawns[start:]
    assert fresh, "expected drain spawn"
    for c in fresh:
        assert c.done.wait(timeout=max(0.01, deadline - time.monotonic()))
        assert c.close_ok is True


def _canned_minister(game) -> None:
    class _A:
        def run(self, *_a, **_k):
            t = "臣已知悉，边饷当速清。"
            yield SimpleNamespace(content=t, event="RunContent", tool=None, tools=[])
            yield SimpleNamespace(
                content=t, event="RunCompleted", tool=None, tools=[], status=None, messages=[],
            )

    game.session.registry.get = lambda _ch: _A()


def _directive(client: TestClient, text: str) -> None:
    r = client.post("/api/directives", json={"text": text, "notes": ""})
    _assert_not_bare_500(r, step="directives")
    assert r.status_code == 200, r.text


def _chat_stream(client: TestClient, minister: str, msg: str) -> dict:
    r = client.post(
        f"/api/ministers/{minister}/chat/stream", json={"message": msg},
    )
    _assert_not_bare_500(r, step="chat/stream")
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert not any(e.get("event") == "error" for e in events), r.text
    acc = next(e for e in events if e.get("event") == "accepted")
    data = json.loads(acc["data"])
    assert data.get("campaign_id") and int(data.get("night_id") or 0) >= 1
    assert int(data.get("chat_turn_id") or 0) >= 1
    return data


def test_drain_skips_archive_when_agno_close_fails(tmp_path, monkeypatch):
    """真实 _drain_and_close_session：agno close 失败上抛且不搬库。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "web_game", None)
    import ming_sim.beat_orchestration as bo
    from ming_sim.models import LLMConfig
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    dbp = str(tmp_path / "ud" / "old.db")
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    sess = GameSession(
        db_path=dbp,
        llm_config=LLMConfig(api_key="sk-test", base_url="http://x", model="m"),
    )
    engine = sess.agno_db.db_engine
    game = SimpleNamespace(
        session=sess, db_path=dbp,
        _write_queue=sess._write_queue, _write_gate=sess._write_gate,
    )
    sess.agno_db.close = lambda: (_ for _ in ()).throw(RuntimeError("agno close failed"))  # type: ignore
    with pytest.raises(RuntimeError, match="agno close failed"):
        web_app._drain_and_close_session(game, archive_db=True)
    assert os.path.isfile(dbp)
    assert _drained(tmp_path / "ud") == []
    # agno 失败路径未 dispose：engine 仍可 connect（证明失败发生在 close 调用中）
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def test_new_game_write_path_and_continue_restore(tracer_client, monkeypatch):
    """主干：seed 写 → 直接 new_game 写只落新库 → drain 完成后旧归档 → continue 恢复新局。"""
    client = tracer_client
    spawns = _capture_spawns(monkeypatch)

    seed = client.post("/api/menu/new_game")
    _assert_not_bare_500(seed, step="seed")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    p0, c0 = g0.db_path, _campaign(g0)
    _directive(client, "着户部清核辽饷（seed）。")
    _wait_pending_writes(g0)
    d0 = _counts(p0)["directives"]
    assert d0 >= 1

    n0 = len(spawns)
    ng = client.post("/api/menu/new_game")
    _assert_not_bare_500(ng, step="new_game")
    assert ng.status_code == 200
    g1 = web_app.web_game
    assert g1 is not None and g1 is not g0
    c1 = _campaign(g1)
    assert c1 and c1 != c0
    p1 = g1.db_path
    assert p1 != p0

    _directive(client, "着户部清核辽饷（新局）。")
    _wait_pending_writes(g1)
    st = client.get("/api/game/state")
    minister = _pick_active_minister(st.json())
    _canned_minister(g1)
    acc = _chat_stream(client, minister, "边饷如何？新局")
    assert acc["campaign_id"] == c1
    _wait_pending_writes(g1)

    _wait_spawns(spawns, n0)
    assert not os.path.exists(p0)
    drained = _drained(Path(web_app.user_data_path()))
    assert drained
    old_hit = next(
        c for c in (_counts(str(p)) for p in drained) if c["campaign_id"] == c0
    )
    assert old_hit["directives"] == d0
    live = _counts(p1)
    assert live["campaign_id"] == c1 and live["directives"] >= 1 and live["nights"] >= 1
    main = str(list(g1.db.conn.execute("PRAGMA database_list"))[0][2])
    assert os.path.abspath(main) == os.path.abspath(p1)
    for p in drained:
        assert os.path.abspath(main) != os.path.abspath(str(p))
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        g0.db.conn.execute("SELECT 1")

    # 真实 exit → continue：退休 g1（含 agno close）后再续当前主库
    agno_closed: list[int] = []
    real_agno_close = g1.session.agno_db.close

    def _track_agno_close() -> None:
        agno_closed.append(1)
        real_agno_close()

    g1.session.agno_db.close = _track_agno_close  # type: ignore[method-assign]
    n_ex = len(spawns)
    assert client.post("/api/menu/exit_to_menu").status_code == 200
    assert web_app.web_game is None
    _wait_spawns(spawns, n_ex)
    assert agno_closed == [1], "exit drain must close agno_db"
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        g1.db.conn.execute("SELECT 1")

    cont = client.post("/api/menu/continue")
    _assert_not_bare_500(cont, step="continue")
    assert cont.status_code == 200
    events = _parse_sse(cont.text)
    terminal = events[-1] if events else {}
    assert terminal.get("event") == "done", cont.text
    done = json.loads(terminal["data"])
    assert isinstance(done.get("state"), dict)
    g2 = web_app.web_game
    assert g2 is not None and g2 is not g1
    assert _campaign(g2) == c1
    assert os.path.abspath(g2.db_path) == os.path.abspath(p1)
    _directive(client, "着再拨饷银（续）。")
    _wait_pending_writes(g2)
    assert _counts(p1)["campaign_id"] == c1
    assert _counts(p1)["directives"] >= 2


def test_exit_new_game_keeps_late_writes_on_old_archive(tracer_client, monkeypatch):
    """exit→new_game：completion 后归档；gate 内迟到写留旧 campaign。"""
    client = tracer_client
    spawns = _capture_spawns(monkeypatch)

    seed = client.post("/api/menu/new_game")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    p0, c0 = g0.db_path, _campaign(g0)
    _directive(client, "着户部清核辽饷（pre-exit）。")
    _wait_pending_writes(g0)

    gate = g0._write_gate
    gate.acquire()
    n_exit = len(spawns)
    try:
        assert client.post("/api/menu/exit_to_menu").status_code == 200
        assert web_app.web_game is None
        g0.db.kv_set("_late", "1")
        g0.db.add_directive(
            g0.state, None, "迟到旨意留旧局", "手动新增",
            dossier_payload={
                "dossier_action_type": "policy",
                "target_kind": "issue",
                "target_id": "late",
                "mode": "ordinary",
            },
        )
    finally:
        if gate.locked():
            gate.release()
    _wait_spawns(spawns, n_exit)
    assert os.path.exists(p0)  # exit 不搬库

    archived = threading.Event()
    seen: list[str] = []
    real = web_app._archive_drained_db_file

    def _arch(path: str) -> None:
        real(path)
        seen.append(path)
        archived.set()

    monkeypatch.setattr(web_app, "_archive_drained_db_file", _arch)

    ng = client.post("/api/menu/new_game")
    assert ng.status_code == 200
    g1 = web_app.web_game
    assert g1 is not None and _campaign(g1) != c0
    _directive(client, "着户部清核辽饷（exit-new）。")
    _wait_pending_writes(g1)
    assert archived.wait(5.0), f"archive not signaled; seen={seen}"
    assert not os.path.exists(p0)

    found = False
    for path in _drained(Path(web_app.user_data_path())):
        if _counts(str(path))["campaign_id"] != c0:
            continue
        conn = sqlite3.connect(str(path))
        try:
            if conn.execute(
                "SELECT value FROM kv_store WHERE key='_late'"
            ).fetchone() == ("1",) and conn.execute(
                "SELECT COUNT(*) FROM turn_directives WHERE text LIKE '%迟到%'"
            ).fetchone()[0] >= 1:
                found = True
                break
        finally:
            conn.close()
    assert found
    assert _counts(g1.db_path)["campaign_id"] == _campaign(g1)
    assert _counts(g1.db_path)["directives"] >= 1
