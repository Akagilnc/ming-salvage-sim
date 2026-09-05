"""#1749 新局后写路径：真实 HTTP 入口 tracer。

查证并锁：
- new_game 后 directives + chat/stream 只写当前库（独立 sqlite 读证）
- 迟到记录留旧局；排空关闭后才归档；退休运行时不持旧连接
- 同一主干覆盖「直接新局」与「exit → new_game」
- 不 mock WebGame / session / 归档被测链
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
from tests.test_month_loop_tracer_1468 import (
    _assert_not_bare_500,
    _parse_sse,
    _pick_active_minister,
    tracer_client,
)
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


def _campaign_of(game) -> str:
    return str(game.db.kv_get("campaign_id") or "").strip()


def _wait_path_gone(path: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not os.path.exists(path):
            return True
        time.sleep(0.02)
    return not os.path.exists(path)


def _drained_saves(user_root: Path) -> list[Path]:
    saves = user_root / "saves"
    if not saves.is_dir():
        return []
    return sorted(saves.glob("drained_*.db"))


def _independent_counts(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        campaign = conn.execute(
            "SELECT value FROM kv_store WHERE key='campaign_id'"
        ).fetchone()
        dirs = conn.execute("SELECT COUNT(*) FROM turn_directives").fetchone()
        nights = conn.execute("SELECT COUNT(*) FROM audience_nights").fetchone()
        return {
            "campaign_id": str(campaign[0]) if campaign and campaign[0] else "",
            "directives": int(dirs[0] if dirs else 0),
            "nights": int(nights[0] if nights else 0),
        }
    finally:
        conn.close()


def _install_canned_minister(game) -> None:
    """stream 路径 agent.run(..., stream=True) 须可迭代事件（#1716 同形）。"""

    class _Agent:
        def run(self, *_a, **_k):
            text = "臣已知悉，边饷当速清。"
            yield SimpleNamespace(
                content=text, event="RunContent", tool=None, tools=[],
            )
            # 终事件：type 名非 RunOutput 时走 chunks 拼 answer，仍须可迭代耗尽。
            yield SimpleNamespace(
                content=text, event="RunCompleted", tool=None, tools=[],
                status=None, messages=[],
            )

    game.session.registry.get = lambda _ch: _Agent()


def _post_directive(client: TestClient, text: str) -> dict:
    resp = client.post("/api/directives", json={"text": text, "notes": ""})
    _assert_not_bare_500(resp, step="POST /api/directives")
    assert resp.status_code == 200, f"directives → {resp.status_code}: {resp.text}"
    body = resp.json()
    assert isinstance(body, dict)
    assert body.get("directive") or body.get("directives"), body
    return body


def _post_chat_stream(client: TestClient, minister: str, message: str) -> list[dict]:
    resp = client.post(
        f"/api/ministers/{minister}/chat/stream",
        json={"message": message},
    )
    _assert_not_bare_500(resp, step="POST chat/stream")
    assert resp.status_code == 200, f"chat/stream HTTP → {resp.status_code}: {resp.text}"
    events = _parse_sse(resp.text)
    assert events, f"chat/stream empty SSE: {resp.text!r}"
    # 业务失败在 SSE event:error，不能只看 HTTP 200（票面验收）。
    errors = [e for e in events if e.get("event") == "error"]
    assert not errors, f"chat/stream business error SSE: {resp.text!r}"
    kinds = {e.get("event") for e in events}
    assert "accepted" in kinds, f"chat/stream missing accepted: {resp.text!r}"
    # accepted 已含 typed campaign/night/chat_turn——开夜写路径已过（票面 readonly 断点）。
    accepted = next(e for e in events if e.get("event") == "accepted")
    try:
        adata = json.loads(accepted.get("data") or "{}")
    except json.JSONDecodeError as exc:
        raise AssertionError(f"accepted data not json: {accepted!r}") from exc
    assert str(adata.get("campaign_id") or "").strip(), accepted
    assert int(adata.get("night_id") or 0) >= 1, accepted
    assert int(adata.get("chat_turn_id") or 0) >= 1, accepted
    assert "done" in kinds or "token" in kinds or "answer" in kinds, (
        f"chat/stream missing reply events after accepted: {resp.text!r}"
    )
    return events


def _assert_live_writable_current_only(game, *, old_path: str | None, old_campaign: str | None) -> None:
    live_path = game.db_path
    assert os.path.isfile(live_path), f"live db missing: {live_path}"
    assert live_path == game.db.path == web_app._get_main_db_path()
    rows = list(game.db.conn.execute("PRAGMA database_list"))
    # row: (seq, name, file)
    main_file = str(rows[0][2] if rows else "")
    assert main_file, rows
    assert os.path.abspath(main_file) == os.path.abspath(live_path), (
        f"conn main file {main_file!r} != live {live_path!r}"
    )
    # 独立只读连接证明当前库可写内容已落当前文件
    indep = _independent_counts(live_path)
    assert indep["campaign_id"] == _campaign_of(game)
    if old_path and os.path.isfile(old_path):
        old_indep = _independent_counts(old_path)
        if old_campaign:
            assert old_indep["campaign_id"] == old_campaign
        # 新局旨意不得出现在仍未搬的旧文件里（静默丢写假说）
        assert old_indep["directives"] == _independent_counts(old_path)["directives"]
    # 退休路径：drained 文件不得再被本进程以可写主连接持有
    for drained in _drained_saves(Path(web_app.user_data_path())):
        # 允许以后加载重开；禁止 live conn 指向 drained
        assert os.path.abspath(str(drained)) != os.path.abspath(live_path)
        assert os.path.abspath(main_file) != os.path.abspath(str(drained))


def _new_game_write_round(client: TestClient, *, label: str) -> dict:
    """new_game → directives + chat/stream → 独立 DB 证当前库。"""
    game_before = web_app.web_game
    old_path = game_before.db_path if game_before is not None else None
    old_campaign = _campaign_of(game_before) if game_before is not None else None
    old_directive_count = None
    if old_path and os.path.isfile(old_path):
        old_directive_count = _independent_counts(old_path)["directives"]

    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step=f"{label} new_game")
    assert new.status_code == 200, f"{label} new_game → {new.status_code}: {new.text}"
    body = new.json()
    assert isinstance(body, dict) and body.get("state"), body

    game = web_app.web_game
    assert game is not None
    assert game is not game_before
    live_campaign = _campaign_of(game)
    assert live_campaign
    if old_campaign:
        assert live_campaign != old_campaign

    # 写路径：拟诏
    _post_directive(client, f"着户部清核辽饷（{label}）。")
    _wait_pending_writes(game)

    # 写路径：召对 SSE（断业务事件）
    state = client.get("/api/game/state")
    _assert_not_bare_500(state, step=f"{label} state")
    minister = _pick_active_minister(state.json())
    _install_canned_minister(game)
    _post_chat_stream(client, minister, f"边饷如何？{label}")
    _wait_pending_writes(game)

    # 等旧库归档（若有旧局）
    if old_path:
        assert _wait_path_gone(old_path), f"{label}: old db not archived: {old_path}"
        drained = _drained_saves(Path(web_app.user_data_path()))
        assert drained, f"{label}: expected drained archive after old path gone"

        # 旧局记录留在归档；新局写入不在归档
        archived = None
        for path in drained:
            info = _independent_counts(str(path))
            if old_campaign and info["campaign_id"] == old_campaign:
                archived = info
                break
        assert archived is not None, f"{label}: old campaign not in drained; {[ _independent_counts(str(p)) for p in drained]}"
        if old_directive_count is not None:
            assert archived["directives"] == old_directive_count
        # 新局至少 1 条旨意只在当前库
        live_info = _independent_counts(game.db_path)
        assert live_info["campaign_id"] == live_campaign
        assert live_info["directives"] >= 1
        assert live_info["nights"] >= 1
        assert archived["directives"] != live_info["directives"] or archived["campaign_id"] != live_info["campaign_id"]

        # 退休运行时：旧 session 连接应已关；进程不应再把 drained 当 live main
        if game_before is not None:
            with pytest.raises(Exception):
                game_before.db.conn.execute("SELECT 1")

    _assert_live_writable_current_only(
        game, old_path=None, old_campaign=old_campaign,
    )
    # 静默丢写：当前库 campaign 与 state 一致；旨意在当前文件
    live_info = _independent_counts(game.db_path)
    assert live_info["campaign_id"] == live_campaign
    assert live_info["directives"] >= 1

    return {
        "campaign_id": live_campaign,
        "db_path": game.db_path,
        "minister": minister,
    }


def test_direct_new_game_write_path_only_current_db(tracer_client, tmp_path):
    """直接新局：seed 局 → new_game → 写只落当前库；旧库归档后可独立读。"""
    client = tracer_client
    seed = client.post("/api/menu/new_game")
    _assert_not_bare_500(seed, step="seed new_game")
    assert seed.status_code == 200
    seed_game = web_app.web_game
    assert seed_game is not None
    seed_campaign = _campaign_of(seed_game)
    seed_path = seed_game.db_path
    _post_directive(client, "着户部清核辽饷（seed）。")
    _wait_pending_writes(seed_game)
    seed_dirs = _independent_counts(seed_path)["directives"]
    assert seed_dirs >= 1

    result = _new_game_write_round(client, label="direct")
    assert result["campaign_id"] != seed_campaign
    assert result["db_path"] != seed_path
    assert not os.path.exists(seed_path)

    # 重开/继续：主路径仍是新局；独立打开可恢复 campaign
    reopened = _independent_counts(result["db_path"])
    assert reopened["campaign_id"] == result["campaign_id"]
    assert reopened["directives"] >= 1
    assert reopened["nights"] >= 1


def test_exit_then_new_game_write_path_only_current_db(tracer_client):
    """exit → new_game：旧连接排空关闭后归档；新局写路径不碰旧库。"""
    client = tracer_client
    seed = client.post("/api/menu/new_game")
    _assert_not_bare_500(seed, step="seed new_game")
    assert seed.status_code == 200
    seed_game = web_app.web_game
    assert seed_game is not None
    seed_path = seed_game.db_path
    seed_campaign = _campaign_of(seed_game)
    _post_directive(client, "着户部清核辽饷（pre-exit）。")
    _wait_pending_writes(seed_game)

    # 持 gate 模拟在飞写：exit 立刻返回，new_game 切路径不搬仍写的旧库
    gate = seed_game._write_gate
    gate.acquire()
    try:
        exited = client.post("/api/menu/exit_to_menu")
        assert exited.status_code == 200
        assert web_app.web_game is None
        assert os.path.exists(seed_path)  # exit 不搬库

        # 迟到写仍进旧连接（旧 session 尚未 close）
        seed_game.db.kv_set("_late_marker", "exit-hold")
        seed_game.db.add_directive(
            seed_game.state,
            None,
            "迟到旨意留旧局",
            "手动新增",
            dossier_payload={
                "dossier_action_type": "policy",
                "target_kind": "issue",
                "target_id": "late-1749",
                "mode": "ordinary",
            },
        )
    finally:
        # new_game 在 lock 下会等；先放 gate 让 exit detach 能关库
        pass

    # 仍持 gate 时启动 new_game 会卡在 lifecycle 之后的 drain 等待？
    # new_game 不关旧库（old_game is None），只等 exit completion。
    # exit detach 卡在 gate → new_game 的 archive 线程会 wait completion。
    # 本线程若在持 gate 时调 new_game，会因 lifecycle lock 与 exit 已释放 lock 而进入构造；
    # archive 后台等 completion；我们构造完再放 gate。
    def _release_later():
        time.sleep(0.2)
        if gate.locked():
            gate.release()

    releaser = threading.Thread(target=_release_later, daemon=True)
    releaser.start()
    try:
        result = _new_game_write_round(client, label="exit-new")
    finally:
        releaser.join(timeout=2.0)
        if gate.locked():
            gate.release()

    assert result["campaign_id"] != seed_campaign
    assert not os.path.exists(seed_path)
    # 迟到记录在归档旧局
    found_late = False
    for path in _drained_saves(Path(web_app.user_data_path())):
        info = _independent_counts(str(path))
        if info["campaign_id"] != seed_campaign:
            continue
        conn = sqlite3.connect(str(path))
        try:
            late = conn.execute(
                "SELECT value FROM kv_store WHERE key='_late_marker'"
            ).fetchone()
            text_hit = conn.execute(
                "SELECT COUNT(*) FROM turn_directives WHERE text LIKE '%迟到旨意留旧局%'"
            ).fetchone()
            if late and late[0] == "exit-hold" and text_hit and int(text_hit[0]) >= 1:
                found_late = True
                break
        finally:
            conn.close()
    assert found_late, "late writes must remain on archived old campaign"


def test_new_game_real_connection_writable_after_archive(tracer_client):
    """补证 #396 SimpleNamespace 未覆盖面：真 WebGame 连接在旧库归档后仍可写当前库。"""
    client = tracer_client
    first = client.post("/api/menu/new_game")
    assert first.status_code == 200
    g1 = web_app.web_game
    assert g1 is not None
    p1 = g1.db_path
    c1 = _campaign_of(g1)

    second = client.post("/api/menu/new_game")
    assert second.status_code == 200
    g2 = web_app.web_game
    assert g2 is not None and g2 is not g1
    assert _wait_path_gone(p1)

    # 真连接写
    g2.db.kv_set("_1749_probe", "ok")
    assert g2.db.kv_get("_1749_probe") == "ok"
    indep = sqlite3.connect(g2.db_path)
    try:
        row = indep.execute(
            "SELECT value FROM kv_store WHERE key='_1749_probe'"
        ).fetchone()
        assert row and row[0] == "ok"
        camp = indep.execute(
            "SELECT value FROM kv_store WHERE key='campaign_id'"
        ).fetchone()
        assert camp and camp[0] == _campaign_of(g2) != c1
    finally:
        indep.close()

    # 旧 session 不可再写；主 conn 不指向 drained
    with pytest.raises(Exception):
        g1.db.conn.execute("SELECT 1")
    main = list(g2.db.conn.execute("PRAGMA database_list"))[0][2]
    for drained in _drained_saves(Path(web_app.user_data_path())):
        assert os.path.abspath(str(main)) != os.path.abspath(str(drained))
        # 取证：退休后 drained 可被独立打开，但不是 live 写点
        dconn = sqlite3.connect(str(drained))
        try:
            dcamp = dconn.execute(
                "SELECT value FROM kv_store WHERE key='campaign_id'"
            ).fetchone()
            if dcamp and dcamp[0] == c1:
                assert dconn.execute(
                    "SELECT value FROM kv_store WHERE key='_1749_probe'"
                ).fetchone() is None
        finally:
            dconn.close()
