"""#1749 新局写路径：真实 HTTP 入口 tracer。

不 mock WebGame/session/归档链。断言落在 typed campaign / 独立 DB 读 / drain completion。
用户提交旨意文本作保真核验；LLM 生成正文只观察，不作相等/非空契约。
"""
from __future__ import annotations

import json
import os
import sqlite3
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
    """独立只读连接：campaign + 旨意/夜/回话终态身份，不经活 session。

    chat_turns 带 minister_message_id；join chat_messages 只取结构化身份
    （id/role 存在），不把生成正文当契约。
    """
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
            "SELECT id, night_id, minister_message_id, status FROM chat_turns ORDER BY id"
        ).fetchall()
        chat_rows = []
        for tid, nid, mid, status in turns:
            msg = None
            if mid:
                msg = conn.execute(
                    "SELECT id, role FROM chat_messages WHERE id=?",
                    (int(mid),),
                ).fetchone()
            chat_rows.append({
                "chat_turn_id": int(tid),
                "night_id": int(nid or 0),
                "minister_message_id": int(mid or 0),
                "status": str(status or ""),
                "message": (
                    {
                        "id": int(msg[0]),
                        "role": str(msg[1]),
                    }
                    if msg
                    else None
                ),
            })
        return {
            "campaign_id": str(camp[0]) if camp and camp[0] else "",
            "directive_ids": [int(r[0]) for r in dirs],
            "directive_texts": [str(r[1]) for r in dirs],
            "night_ids": [int(r[0]) for r in nights],
            "chat_turns": chat_rows,
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
            t = "canned-minister-reply"
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
    """真实 chat/stream：须 SSE accepted + done；done 带 typed minister_message_id。

    生成 answer 正文只观察（带回），不作非空/相等契约。
    """
    r = client.post(
        f"/api/ministers/{minister}/chat/stream", json={"message": msg},
    )
    _assert_not_bare_500(r, step="chat/stream")
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert not any(e.get("event") == "error" for e in events), r.text
    acc = next(e for e in events if e.get("event") == "accepted")
    acc_data = json.loads(acc["data"])
    assert acc_data.get("campaign_id") and int(acc_data.get("night_id") or 0) >= 1
    assert int(acc_data.get("chat_turn_id") or 0) >= 1
    done = next((e for e in events if e.get("event") == "done"), None)
    assert done is not None, f"chat/stream missing done; events={events!r}"
    done_data = json.loads(done["data"]) if isinstance(done.get("data"), str) else done.get("data")
    assert isinstance(done_data, dict), done_data
    mid = int(done_data.get("minister_message_id") or 0)
    assert mid >= 1, f"done missing minister_message_id: {done_data!r}"
    return {
        "campaign_id": acc_data["campaign_id"],
        "night_id": int(acc_data["night_id"]),
        "chat_turn_id": int(acc_data["chat_turn_id"]),
        "minister_message_id": mid,
        # 观察位：不参与 assert 契约
        "answer_observed": str(done_data.get("answer") or ""),
    }


def _assert_chat_persisted(snap: dict, *, chat_turn_id: int, night_id: int,
                           minister_message_id: int) -> None:
    """独立 DB：chat_turns.minister_message_id 链接 chat_messages 身份（非正文）。"""
    row = next(
        (t for t in snap["chat_turns"] if t["chat_turn_id"] == chat_turn_id),
        None,
    )
    assert row is not None, snap["chat_turns"]
    assert row["night_id"] == night_id
    assert row["minister_message_id"] == minister_message_id
    assert row["minister_message_id"] >= 1
    assert row["message"] is not None, row
    assert row["message"]["id"] == minister_message_id
    assert row["message"]["role"] == "minister"
    assert night_id in snap["night_ids"]


def _write_and_verify_live(client: TestClient, game, *, label: str) -> dict:
    """经真实 directives + chat/stream 写入，独立 DB 核对 campaign/回话终态。"""
    d_text = f"着户部清核辽饷（{label}）。"
    _directive(client, d_text)
    _wait_pending_writes(game)
    st = client.get("/api/game/state")
    minister = _pick_active_minister(st.json())
    chat = _chat_stream(client, minister, f"边饷如何？{label}")
    camp = _campaign(game)
    assert chat["campaign_id"] == camp
    _wait_pending_writes(game)
    snap = _db_snapshot(game.db_path)
    assert snap["campaign_id"] == camp
    assert d_text in snap["directive_texts"]
    _assert_chat_persisted(
        snap,
        chat_turn_id=chat["chat_turn_id"],
        night_id=chat["night_id"],
        minister_message_id=chat["minister_message_id"],
    )
    return {
        "campaign_id": camp,
        "chat_turn_id": chat["chat_turn_id"],
        "night_id": chat["night_id"],
        "minister_message_id": chat["minister_message_id"],
        "d_text": d_text,
    }


def _old_handle_commit(game, marker: str) -> None:
    """旧 runtime 句柄仍可提交：经同一连接写入 kv 标记（证明非只读探测）。"""
    game.db.conn.execute(
        "INSERT OR REPLACE INTO kv_store(key, value) VALUES (?, ?)",
        (f"late_write:{marker}", marker),
    )
    game.db.conn.commit()


def _kv_has(db_path: str, marker: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key=?",
            (f"late_write:{marker}",),
        ).fetchone()
        return bool(row and str(row[0]) == marker)
    finally:
        conn.close()


def test_new_game_write_path_direct_and_via_exit(tracer_client, monkeypatch):
    """主干：直接 new_game 与 exit→new_game；迟到写；旧档 load_save 恢复。"""
    client = tracer_client
    _install_canned_minister_factory(monkeypatch)
    spawns = _capture_spawns(monkeypatch)
    ud = Path(web_app.user_data_path())

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
    late_direct = "着户部清核辽饷（late-direct-old-handle）。"
    try:
        ng = client.post("/api/menu/new_game")
        _assert_not_bare_500(ng, step="new_game-direct")
        assert ng.status_code == 200
        g1 = web_app.web_game
        assert g1 is not None and g1 is not g0
        p1 = g1.db_path
        assert p1 != p0
        # 旧句柄仍可真实提交（非只 SELECT 1）
        _old_handle_commit(g0, late_direct)
        assert _kv_has(p0, late_direct)
        assert not _kv_has(p1, late_direct)
        rec1 = _write_and_verify_live(client, g1, label="direct-new")
        c1 = rec1["campaign_id"]
        assert c1 and c1 != c0
        old_snap = _db_snapshot(p0)
        new_snap = _db_snapshot(p1)
        assert rec1["d_text"] in new_snap["directive_texts"]
        assert rec1["d_text"] not in old_snap["directive_texts"]
        assert old_snap["campaign_id"] == c0
        assert new_snap["campaign_id"] == c1
    finally:
        if old_gate.locked():
            old_gate.release()

    _wait_spawns(spawns, n0)
    assert not os.path.exists(p0)
    drained = _drained(ud)
    assert drained
    old_hit = next(
        s for s in (_db_snapshot(str(p)) for p in drained) if s["campaign_id"] == c0
    )
    assert old_hit["directives"] >= d0_count
    assert seed_rec["d_text"] in old_hit["directive_texts"]
    c0_archive = next(p for p in drained if _db_snapshot(str(p))["campaign_id"] == c0)
    assert _kv_has(str(c0_archive), late_direct)
    live = _db_snapshot(p1)
    assert live["campaign_id"] == c1
    assert rec1["d_text"] in live["directive_texts"]
    _assert_chat_persisted(
        live,
        chat_turn_id=rec1["chat_turn_id"],
        night_id=rec1["night_id"],
        minister_message_id=rec1["minister_message_id"],
    )
    main = str(list(g1.db.conn.execute("PRAGMA database_list"))[0][2])
    assert web_app._same_db_path(main, p1)
    for p in drained:
        assert not web_app._same_db_path(main, str(p))
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        g0.db.conn.execute("SELECT 1")

    # ── 路二：exit → new_game（确定性；真实 exit 并发交错留临时真跑，不进永久案）──
    pre_exit = "着户部清核辽饷（pre-exit）。"
    _directive(client, pre_exit)
    _wait_pending_writes(g1)
    n_exit = len(spawns)
    assert client.post("/api/menu/exit_to_menu").status_code == 200
    assert web_app.web_game is None
    _wait_spawns(spawns, n_exit)
    assert os.path.exists(p1)  # exit 不搬库

    ng2 = client.post("/api/menu/new_game")
    _assert_not_bare_500(ng2, step="new_game-after-exit")
    assert ng2.status_code == 200
    g2 = web_app.web_game
    assert g2 is not None and g2 is not g1
    rec2 = _write_and_verify_live(client, g2, label="exit-new")
    c2 = rec2["campaign_id"]
    assert c2 != c1

    wait_until(lambda: not os.path.exists(p1))
    old_arch = next(
        s for s in (_db_snapshot(str(p)) for p in _drained(ud))
        if s["campaign_id"] == c1
    )
    assert pre_exit in old_arch["directive_texts"]
    assert rec1["d_text"] in old_arch["directive_texts"]
    _assert_chat_persisted(
        old_arch,
        chat_turn_id=rec1["chat_turn_id"],
        night_id=rec1["night_id"],
        minister_message_id=rec1["minister_message_id"],
    )
    c1_archive = next(
        p for p in _drained(ud) if _db_snapshot(str(p))["campaign_id"] == c1
    )
    live2 = _db_snapshot(g2.db_path)
    assert live2["campaign_id"] == c2
    assert rec2["d_text"] in live2["directive_texts"]
    assert rec2["d_text"] not in old_arch["directive_texts"]

    # ── continue 恢复最新主库 ──
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
    _assert_chat_persisted(
        restored,
        chat_turn_id=rec2["chat_turn_id"],
        night_id=rec2["night_id"],
        minister_message_id=rec2["minister_message_id"],
    )
    cont_more = "着再拨饷银（续）。"
    _directive(client, cont_more)
    _wait_pending_writes(g3)
    assert cont_more in _db_snapshot(g3.db_path)["directive_texts"]

    # ── 旧档 c0/c1 经真实 load_save 恢复同条旨意与召对轮 ──
    for arch, camp, rec in (
        (c0_archive, c0, seed_rec),
        (c1_archive, c1, rec1),
    ):
        name = arch.stem
        r = client.post(f"/api/menu/load_save/{name}")
        _assert_not_bare_500(r, step=f"load_save-{name}")
        assert r.status_code == 200, r.text
        g = web_app.web_game
        assert g is not None
        snap = _db_snapshot(g.db_path)
        assert snap["campaign_id"] == camp
        assert rec["d_text"] in snap["directive_texts"]
        _assert_chat_persisted(
            snap,
            chat_turn_id=rec["chat_turn_id"],
            night_id=rec["night_id"],
            minister_message_id=rec["minister_message_id"],
        )


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
    after = "着户部清核辽饷（after-fail）。"
    _directive(client, after)
    _wait_pending_writes(g0)
    snap = _db_snapshot(p0)
    assert snap["campaign_id"] == c0
    assert after in snap["directive_texts"]


def test_gamesession_load_state_failure_closes_partial_resources(tmp_path, monkeypatch):
    """GameSession 构造中 load_state 失败 → db 与 agno.close 均执行，禁部分资源泄漏。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import ming_sim.beat_orchestration as bo
    import ming_sim.session as session_mod
    from ming_sim.db import GameDB
    from ming_sim.models import LLMConfig
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    dbp = str(tmp_path / "ud" / "partial-gs.db")
    os.makedirs(os.path.dirname(dbp), exist_ok=True)

    opened: list = []
    agno_close_calls: list = []

    def boom_load(self, *a, **k):
        opened.append(self)
        raise RuntimeError("load_state boom")

    real_create_agno = session_mod.create_agno_db

    def tracking_create_agno(path):
        agno = real_create_agno(path)
        real_close = agno.close

        def _close() -> None:
            agno_close_calls.append(1)
            return real_close()

        agno.close = _close  # type: ignore[method-assign]
        return agno

    monkeypatch.setattr(GameDB, "load_state", boom_load)
    monkeypatch.setattr(session_mod, "create_agno_db", tracking_create_agno)
    with pytest.raises(RuntimeError, match="load_state boom"):
        GameSession(
            db_path=dbp,
            llm_config=LLMConfig(api_key="sk-test", base_url="http://x", model="m"),
        )
    assert opened
    db = opened[0]
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
        db.conn.execute("SELECT 1")
    assert agno_close_calls == [1], "agno.close must run on partial init failure"


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

    def boom_close() -> None:
        raise RuntimeError("close boom")

    g0.session.close = boom_close  # type: ignore[method-assign]
    try:
        r = client.post("/api/menu/load_save/snap1749")
        assert r.status_code == 409, r.text
        assert web_app.web_game is g0
        assert web_app._runtime_restorable(g0)
        assert not g0._write_queue.is_sealed(), "drain failure must unseal restored runtime"
        assert os.path.isfile(old_path)
        web_app._archive_drained_db_file(old_path)
        assert os.path.isfile(old_path)
        assert _drained(Path(web_app.user_data_path())) == []
        marker = "着户部清核辽饷（load-save-close-fail）。"
        _directive(client, marker)
        _wait_pending_writes(g0)
        snap = _db_snapshot(old_path)
        assert snap["campaign_id"] == c0
        assert marker in snap["directive_texts"]
    finally:
        g0.session.close = real_close  # type: ignore[method-assign]


def test_exit_close_fail_blocks_archive_on_real_new_game(tracer_client, monkeypatch):
    """真实 exit→new_game：detach close 失败保留回执，旧主库不被归档。"""
    client = tracer_client
    _install_canned_minister_factory(monkeypatch)
    seed = client.post("/api/menu/new_game")
    assert seed.status_code == 200
    g0 = web_app.web_game
    assert g0 is not None
    old_path = g0.db_path
    c0 = _campaign(g0)
    marker = "着户部清核辽饷（exit-close-fail）。"
    _directive(client, marker)
    _wait_pending_writes(g0)

    real_close = g0.session.close

    def boom_close() -> None:
        raise RuntimeError("exit close boom")

    g0.session.close = boom_close  # type: ignore[method-assign]
    try:
        assert client.post("/api/menu/exit_to_menu").status_code == 200
        assert web_app.web_game is None
        completion = web_app._peek_exit_detach_completion()
        assert completion is not None
        assert completion.db_path
        assert web_app._same_db_path(completion.db_path, old_path)
        completion.done.wait()
        assert completion.close_ok is False
        # 失败回执不得被提前清除
        assert web_app._peek_exit_detach_completion() is completion
        assert os.path.isfile(old_path)

        ng = client.post("/api/menu/new_game")
        _assert_not_bare_500(ng, step="new_game-after-failed-exit")
        assert ng.status_code == 200
        g1 = web_app.web_game
        assert g1 is not None
        # 等归档消费者终态（非主路径已切换的早采样）
        completion.archive_settled.wait()
        assert os.path.isfile(old_path)
        assert all(
            _db_snapshot(str(p))["campaign_id"] != c0
            for p in _drained(Path(web_app.user_data_path()))
        ) or _drained(Path(web_app.user_data_path())) == []
        # 旧文件内容仍在
        assert marker in _db_snapshot(old_path)["directive_texts"]
        # 失败回执仍在（成功才清）；路径身份仍绑定旧库
        assert web_app._peek_exit_detach_completion() is completion
        assert web_app._same_db_path(completion.db_path, old_path)
    finally:
        g0.session.close = real_close  # type: ignore[method-assign]
        # 故障注入遗留的旧 runtime 已脱离 web_game，须真实关闭，禁只恢复方法。
        try:
            web_app._drain_and_close_session(g0, archive_db=False)
        except Exception:
            pass
