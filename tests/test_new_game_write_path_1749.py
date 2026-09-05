"""#1749 新局写路径：真实 HTTP 入口 tracer。

不 mock WebGame/session/归档链。断言落在 typed campaign / 独立 DB 读 / drain completion。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
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
from tests.wait_utils import wait_until


def _campaign(game) -> str:
    return str(game.db.kv_get("campaign_id") or "").strip()


def _db_snapshot(db_path: str) -> dict:
    """独立只读连接：campaign + 旨意/夜/回话身份，不经活 session。"""
    conn = sqlite3.connect(db_path)
    try:
        camp = conn.execute(
            "SELECT value FROM kv_store WHERE key='campaign_id'"
        ).fetchone()
        dirs = conn.execute(
            "SELECT id, text FROM turn_directives ORDER BY id"
        ).fetchall()
        nights = conn.execute(
            "SELECT id FROM audience_nights ORDER BY id"
        ).fetchall()
        turns = conn.execute(
            "SELECT id, night_id FROM chat_turns ORDER BY id"
        ).fetchall()
        return {
            "campaign_id": str(camp[0]) if camp and camp[0] else "",
            "directive_ids": [int(r[0]) for r in dirs],
            "directive_texts": [str(r[1]) for r in dirs],
            "night_ids": [int(r[0]) for r in nights],
            "chat_turns": [(int(r[0]), int(r[1] or 0)) for r in turns],
            "directives": len(dirs),
            "nights": len(nights),
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


def _wait_spawns(spawns: list, start: int) -> None:
    wait_until(lambda: len(spawns) > start)
    for c in spawns[start:]:
        c.done.wait()
        assert c.close_ok is True


def _install_canned_minister_factory(monkeypatch) -> None:
    """外层模型工厂缝：create_minister_agent → canned；保留真实 registry/session。"""
    import ming_sim.registry as reg

    class _A:
        def run(self, *_a, **_k):
            t = "臣已知悉，边饷当速清。"
            yield SimpleNamespace(content=t, event="RunContent", tool=None, tools=[])
            yield SimpleNamespace(
                content=t, event="RunCompleted", tool=None, tools=[],
                status=None, messages=[],
            )

    monkeypatch.setattr(reg, "create_minister_agent", lambda *a, **k: _A())


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


def _write_and_verify_live(client: TestClient, game, *, label: str) -> dict:
    """经真实 directives + chat/stream 写入，独立 DB 核对 campaign/记录身份。"""
    d_text = f"着户部清核辽饷（{label}）。"
    _directive(client, d_text)
    _wait_pending_writes(game)
    st = client.get("/api/game/state")
    minister = _pick_active_minister(st.json())
    acc = _chat_stream(client, minister, f"边饷如何？{label}")
    camp = _campaign(game)
    assert acc["campaign_id"] == camp
    _wait_pending_writes(game)
    snap = _db_snapshot(game.db_path)
    assert snap["campaign_id"] == camp
    assert d_text in snap["directive_texts"]
    turn_id = int(acc["chat_turn_id"])
    night_id = int(acc["night_id"])
    assert any(t[0] == turn_id and t[1] == night_id for t in snap["chat_turns"]), snap
    assert night_id in snap["night_ids"]
    return {"campaign_id": camp, "chat_turn_id": turn_id, "night_id": night_id, "d_text": d_text}


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
    game = SimpleNamespace(
        session=sess, db_path=dbp,
        _write_queue=sess._write_queue, _write_gate=sess._write_gate,
    )
    real_agno_close = sess.agno_db.close
    sess.agno_db.close = lambda: (_ for _ in ()).throw(RuntimeError("agno close failed"))  # type: ignore
    try:
        with pytest.raises(RuntimeError, match="agno close failed"):
            web_app._drain_and_close_session(game, archive_db=True)
        assert os.path.isfile(dbp)
        assert _drained(tmp_path / "ud") == []
        # db 侧已关；证明失败发生在 agno close，且未搬库
        with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
            sess.db.conn.execute("SELECT 1")
    finally:
        sess.agno_db.close = real_agno_close  # type: ignore[method-assign]
        try:
            sess.close()
        except Exception:
            # 部分资源可能已关；尽力收束，禁泄漏到进程外
            try:
                real_agno_close()
            except Exception:
                pass


def test_new_game_write_path_direct_and_via_exit(tracer_client, monkeypatch):
    """主干：直接 new_game 与 exit→new_game 两路均经 directives+chat；独立 DB 身份；恢复。"""
    client = tracer_client
    _install_canned_minister_factory(monkeypatch)
    spawns = _capture_spawns(monkeypatch)

    seed = client.post("/api/menu/new_game")
    _assert_not_bare_500(seed, step="seed")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    p0 = g0.db_path
    seed_rec = _write_and_verify_live(client, g0, label="seed")
    c0 = seed_rec["campaign_id"]
    d0_count = _db_snapshot(p0)["directives"]

    # ── 路一：直接 new_game（持旧 gate 保持双句柄可写窗）──
    n0 = len(spawns)
    old_gate = g0._write_gate
    old_gate.acquire()
    try:
        ng = client.post("/api/menu/new_game")
        _assert_not_bare_500(ng, step="new_game-direct")
        assert ng.status_code == 200
        g1 = web_app.web_game
        assert g1 is not None and g1 is not g0
        p1 = g1.db_path
        assert p1 != p0
        # 旧 drain 被 gate 挡住：两句柄同时可提交
        g0.db.conn.execute("SELECT 1")
        rec1 = _write_and_verify_live(client, g1, label="direct-new")
        c1 = rec1["campaign_id"]
        assert c1 and c1 != c0
        # 静默丢写假说：新旨意只落新库；旧句柄直写只留旧库
        g0.db.kv_set("_old_handle_mark", "1")
        old_snap = _db_snapshot(p0)
        new_snap = _db_snapshot(p1)
        assert rec1["d_text"] in new_snap["directive_texts"]
        assert rec1["d_text"] not in old_snap["directive_texts"]
        assert old_snap["campaign_id"] == c0
        conn = sqlite3.connect(p0)
        try:
            assert conn.execute(
                "SELECT value FROM kv_store WHERE key='_old_handle_mark'"
            ).fetchone() == ("1",)
        finally:
            conn.close()
        conn = sqlite3.connect(p1)
        try:
            assert conn.execute(
                "SELECT value FROM kv_store WHERE key='_old_handle_mark'"
            ).fetchone() is None
        finally:
            conn.close()
    finally:
        if old_gate.locked():
            old_gate.release()

    _wait_spawns(spawns, n0)
    assert not os.path.exists(p0)
    drained = _drained(Path(web_app.user_data_path()))
    assert drained
    old_hit = next(
        s for s in (_db_snapshot(str(p)) for p in drained) if s["campaign_id"] == c0
    )
    assert old_hit["directives"] == d0_count
    assert seed_rec["d_text"] in old_hit["directive_texts"]
    live = _db_snapshot(p1)
    assert live["campaign_id"] == c1
    assert rec1["d_text"] in live["directive_texts"]
    assert any(t[0] == rec1["chat_turn_id"] for t in live["chat_turns"])
    main = str(list(g1.db.conn.execute("PRAGMA database_list"))[0][2])
    assert web_app._same_db_path(main, p1)
    for p in drained:
        assert not web_app._same_db_path(main, str(p))
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        g0.db.conn.execute("SELECT 1")

    # ── 路二：exit → 迟到写 → new_game ──
    gate = g1._write_gate
    gate.acquire()
    n_exit = len(spawns)
    late_key = "_late_exit_new"
    try:
        assert client.post("/api/menu/exit_to_menu").status_code == 200
        assert web_app.web_game is None
        g1.db.kv_set(late_key, "1")
        g1.db.add_directive(
            g1.state, None, "迟到旨意留旧局", "手动新增",
            dossier_payload={
                "dossier_action_type": "policy",
                "target_kind": "issue",
                "target_id": "late-exit-new",
                "mode": "ordinary",
            },
        )
    finally:
        if gate.locked():
            gate.release()
    _wait_spawns(spawns, n_exit)
    assert os.path.exists(p1)  # exit 不搬库

    archived = threading.Event()
    seen: list[str] = []
    real_arch = web_app._archive_drained_db_file

    def _arch(path: str) -> None:
        real_arch(path)
        seen.append(path)
        archived.set()

    monkeypatch.setattr(web_app, "_archive_drained_db_file", _arch)

    ng2 = client.post("/api/menu/new_game")
    _assert_not_bare_500(ng2, step="new_game-after-exit")
    assert ng2.status_code == 200
    g2 = web_app.web_game
    assert g2 is not None and g2 is not g1
    rec2 = _write_and_verify_live(client, g2, label="exit-new")
    c2 = rec2["campaign_id"]
    assert c2 != c1

    wait_until(archived.is_set)
    assert not os.path.exists(p1)
    found_late = False
    for path in _drained(Path(web_app.user_data_path())):
        snap = _db_snapshot(str(path))
        if snap["campaign_id"] != c1:
            continue
        conn = sqlite3.connect(str(path))
        try:
            late = conn.execute(
                "SELECT value FROM kv_store WHERE key=?", (late_key,)
            ).fetchone()
            late_dir = conn.execute(
                "SELECT id FROM turn_directives WHERE text=?",
                ("迟到旨意留旧局",),
            ).fetchone()
        finally:
            conn.close()
        if late == ("1",) and late_dir is not None:
            found_late = True
            break
    assert found_late
    live2 = _db_snapshot(g2.db_path)
    assert live2["campaign_id"] == c2
    assert rec2["d_text"] in live2["directive_texts"]
    assert rec2["d_text"] not in _db_snapshot(
        next(str(p) for p in _drained(Path(web_app.user_data_path()))
             if _db_snapshot(str(p))["campaign_id"] == c1)
    )["directive_texts"]

    # ── continue 恢复最新主库旨意与回话 ──
    n_ex2 = len(spawns)
    assert client.post("/api/menu/exit_to_menu").status_code == 200
    _wait_spawns(spawns, n_ex2)

    cont = client.post("/api/menu/continue")
    _assert_not_bare_500(cont, step="continue")
    assert cont.status_code == 200
    events = _parse_sse(cont.text)
    terminal = events[-1] if events else {}
    assert terminal.get("event") == "done", cont.text
    g3 = web_app.web_game
    assert g3 is not None and g3 is not g2
    assert _campaign(g3) == c2
    assert web_app._same_db_path(g3.db_path, g2.db_path)
    restored = _db_snapshot(g3.db_path)
    assert restored["campaign_id"] == c2
    assert rec2["d_text"] in restored["directive_texts"]
    assert any(t[0] == rec2["chat_turn_id"] and t[1] == rec2["night_id"]
               for t in restored["chat_turns"])
    _directive(client, "着再拨饷银（续）。")
    _wait_pending_writes(g3)
    assert "着再拨饷银（续）。" in _db_snapshot(g3.db_path)["directive_texts"]


def test_new_game_construct_failure_keeps_old_writable(tracer_client, monkeypatch):
    """真实 new_game 入口：构造失败恢复旧指针与主库路径，旧局仍可写。"""
    client = tracer_client
    _install_canned_minister_factory(monkeypatch)

    seed = client.post("/api/menu/new_game")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    p0 = g0.db_path
    c0 = _campaign(g0)
    _directive(client, "着户部清核辽饷（pre-fail）。")
    _wait_pending_writes(g0)
    main_before = web_app._get_main_db_path()

    real_begin = GameSession.begin_turn
    boom_on = {"armed": True}

    def _boom_begin(self, *a, **k):
        if boom_on["armed"]:
            boom_on["armed"] = False
            raise RuntimeError("begin_turn boom")
        return real_begin(self, *a, **k)

    monkeypatch.setattr(GameSession, "begin_turn", _boom_begin)
    # TestClient 默认 raise_server_exceptions：构造失败原样上抛，仍须恢复旧局。
    with pytest.raises(RuntimeError, match="begin_turn boom"):
        client.post("/api/menu/new_game")
    assert web_app.web_game is g0
    assert web_app._same_db_path(web_app._get_main_db_path(), main_before)
    assert web_app._same_db_path(g0.db_path, p0)
    assert _campaign(g0) == c0
    # 旧局仍可写
    _directive(client, "着户部清核辽饷（after-fail）。")
    _wait_pending_writes(g0)
    snap = _db_snapshot(p0)
    assert snap["campaign_id"] == c0
    assert "着户部清核辽饷（after-fail）。" in snap["directive_texts"]


def test_gamesession_load_state_failure_closes_partial_resources(tmp_path, monkeypatch):
    """GameSession 构造中 load_state 失败 → db/agno 均关，禁部分资源泄漏。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import ming_sim.beat_orchestration as bo
    from ming_sim.db import GameDB
    from ming_sim.models import LLMConfig
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    dbp = str(tmp_path / "ud" / "partial-gs.db")
    os.makedirs(os.path.dirname(dbp), exist_ok=True)

    opened: list = []
    real_load = GameDB.load_state

    def boom_load(self, *a, **k):
        opened.append(self)
        raise RuntimeError("load_state boom")

    monkeypatch.setattr(GameDB, "load_state", boom_load)
    with pytest.raises(RuntimeError, match="load_state boom"):
        GameSession(
            db_path=dbp,
            llm_config=LLMConfig(api_key="sk-test", base_url="http://x", model="m"),
        )
    assert opened
    db = opened[0]
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        db.conn.execute("SELECT 1")


def test_webgame_begin_turn_failure_closes_session(tmp_path, monkeypatch):
    """GameSession 已建、begin_turn 失败 → session.close，禁泄漏 db/agno。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    import ming_sim.beat_orchestration as bo
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    dbp = str(tmp_path / "ud" / "partial.db")
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    monkeypatch.setenv("MING_SIM_DB", dbp)
    web_app._write_active_db_path(dbp)

    held: list = []

    def boom_begin(self, *a, **k):
        held.append(self)
        raise RuntimeError("begin_turn boom")

    monkeypatch.setattr(GameSession, "begin_turn", boom_begin)
    with pytest.raises(RuntimeError, match="begin_turn boom"):
        web_app.WebGame(fresh=True)
    assert len(held) == 1
    sess = held[0]
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        sess.db.conn.execute("SELECT 1")


def test_load_save_close_fail_restores_writable_old_game(tracer_client, monkeypatch):
    """真实 load_save 入口：关旧局失败 → 409、恢复指针且 /api/directives 仍可写；不搬活库。"""
    client = tracer_client
    _install_canned_minister_factory(monkeypatch)
    seed = client.post("/api/menu/new_game")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    old_path = g0.db_path
    c0 = _campaign(g0)
    g0.save_to("snap1749")

    real_close = g0.session.close
    g0.session.close = lambda: (_ for _ in ()).throw(RuntimeError("close boom"))  # type: ignore
    try:
        r = client.post("/api/menu/load_save/snap1749")
        assert r.status_code == 409, r.text
        assert web_app.web_game is g0
        assert not g0._write_queue.is_sealed(), "drain failure must unseal restored runtime"
        assert os.path.isfile(old_path)
        web_app._archive_drained_db_file(old_path)
        assert os.path.isfile(old_path)
        assert _drained(Path(web_app.user_data_path())) == []
        # 外部行为：409 后经真实 directives 入口旧局仍可写
        _directive(client, "着户部清核辽饷（load-save-close-fail）。")
        _wait_pending_writes(g0)
        snap = _db_snapshot(old_path)
        assert snap["campaign_id"] == c0
        assert "着户部清核辽饷（load-save-close-fail）。" in snap["directive_texts"]
    finally:
        g0.session.close = real_close  # type: ignore[method-assign]


