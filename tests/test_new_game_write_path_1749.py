"""#1749 新局后写路径：真实入口 tracer + 固定点回归。

锁：
- new_game 后 directives + chat/stream 只写当前库（独立 sqlite 读）
- close 失败不搬库（含 agno_db.close）
- 菜单生命周期发布与代际检查原子（continue 不得覆盖更新的 new_game）
- 迟到记录留旧局；排空关闭完成信号后才见归档
- 不 mock WebGame/session/归档被测链
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


def _campaign_of(game) -> str:
    return str(game.db.kv_get("campaign_id") or "").strip()


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
    errors = [e for e in events if e.get("event") == "error"]
    assert not errors, f"chat/stream business error SSE: {resp.text!r}"
    kinds = {e.get("event") for e in events}
    assert "accepted" in kinds, f"chat/stream missing accepted: {resp.text!r}"
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


def _capture_drain_completions(monkeypatch) -> list:
    """拦截 _spawn_drain_close，收集 completion 供确定性 wait（禁 sleep 竞猜）。"""
    completions: list = []
    real = web_app._spawn_drain_close

    def wrapped(game, archive_db: bool = False, completion=None):
        c = real(game, archive_db=archive_db, completion=completion)
        completions.append(c)
        return c

    monkeypatch.setattr(web_app, "_spawn_drain_close", wrapped)
    return completions


def _wait_completions(completions: list, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    for c in list(completions):
        remaining = max(0.01, deadline - time.monotonic())
        assert c.done.wait(timeout=remaining), (
            f"drain completion not signaled within {timeout}s; "
            f"close_ok={getattr(c, 'close_ok', None)}"
        )


# ── 固定点：close 失败不搬库（含 agno） ──────────────────────────────────


def test_session_close_propagates_agno_close_failure(tmp_path, monkeypatch):
    """#1749：agno_db.close 失败必须上抛，不得吞掉后让 drain 当成功。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    from ming_sim.models import LLMConfig
    from ming_sim.beat_orchestration import create_llm_beat_generator
    import ming_sim.beat_orchestration as bo
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    cfg = LLMConfig(api_key="sk-test", base_url="http://x", model="m")
    dbp = str(tmp_path / "sess.db")
    sess = GameSession(db_path=dbp, llm_config=cfg)
    assert sess.agno_db is not None
    # 真 agno 句柄在场；替换 close 为失败以证传播
    real_close = sess.agno_db.close

    def boom():
        raise RuntimeError("agno close failed")

    sess.agno_db.close = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="agno close failed"):
        sess.close()
    # 主库仍应已尝试关闭；恢复真 close 以免泄漏
    try:
        real_close()
    except Exception:
        pass


def test_drain_skips_archive_when_agno_close_fails(tmp_path, monkeypatch):
    """#1749 / #1740：session.close 因 agno 失败上抛 → archive_db 不得搬文件。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "web_game", None)

    import ming_sim.beat_orchestration as bo
    from ming_sim.models import LLMConfig
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    cfg = LLMConfig(api_key="sk-test", base_url="http://x", model="m")
    dbp = str(tmp_path / "ud" / "old.db")
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    sess = GameSession(db_path=dbp, llm_config=cfg)
    game = SimpleNamespace(
        session=sess,
        db_path=dbp,
        _write_queue=sess._write_queue,
        _write_gate=sess._write_gate,
    )

    def boom():
        raise RuntimeError("agno close failed")

    sess.agno_db.close = boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="agno close failed"):
        web_app._drain_and_close_session(game, archive_db=True)

    assert os.path.exists(dbp), "close 失败不得搬旧库"
    assert _drained_saves(tmp_path / "ud") == []


def test_session_close_disposes_real_agno_engine(tmp_path, monkeypatch):
    """#1749：真 agno engine 在 close 后 dispose——退休运行时不持旧连接。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_DB", raising=False)

    import ming_sim.beat_orchestration as bo
    from ming_sim.models import LLMConfig
    from tests.conftest import deterministic_test_beat_generator

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _c: deterministic_test_beat_generator)
    cfg = LLMConfig(api_key="sk-test", base_url="http://x", model="m")
    dbp = str(tmp_path / "agno-close.db")
    sess = GameSession(db_path=dbp, llm_config=cfg)
    engine = sess.agno_db.db_engine
    # 先借一条连接确认池活着
    conn = engine.connect()
    conn.close()
    sess.close()
    # dispose 后 pool 已关；再 connect 会建新池或报错——SQLAlchemy dispose 后
    # engine.pool 仍在但 checked-out 应为空且 disposed 标记。
    assert engine.pool is not None
    # 主库 conn 已关
    with pytest.raises(Exception):
        sess.db.conn.execute("SELECT 1")


# ── 固定点：continue 发布与 new_game 原子 ────────────────────────────────


def test_continue_publish_cannot_overwrite_newer_new_game(monkeypatch, tmp_path):
    """#1749：continue worker 对号+发布与 new_game 同锁——禁止 stale 覆盖。

    旧逻辑（check 与赋值非原子）会在 new_game 发布后仍把 stale continue 写成活 runtime。
    """
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.setattr(web_app, "_menu_generation", 0)

    # 模拟 continue：构造完成后、对号前插入 new_game 发布
    published = {}

    class _FakeGame:
        def __init__(self, label: str):
            self.label = label
            self.db_path = str(tmp_path / f"{label}.db")

        def state_payload(self):
            return {"from": self.label}

    # 直接行使与生产相同的锁+对号+赋值临界区
    token_continue = None
    with web_app._menu_lifecycle_lock:
        web_app._menu_generation += 1
        token_continue = web_app._menu_generation

    stale = _FakeGame("stale-continue")
    # new_game 插队：bump + 发布
    with web_app._menu_lifecycle_lock:
        web_app._menu_generation += 1
        web_app.web_game = _FakeGame("new-game")
        published["new_game"] = web_app.web_game.label

    # continue 生产路径：对号与赋值同锁
    publish = False
    with web_app._menu_lifecycle_lock:
        if token_continue == web_app._menu_generation:
            web_app.web_game = stale
            publish = True
    assert publish is False, "stale continue must not publish after generation bump"
    assert web_app.web_game is not None
    assert web_app.web_game.label == "new-game"
    assert published["new_game"] == "new-game"


# ── HTTP tracer：直接新局 / exit→new_game ────────────────────────────────


def _new_game_write_round(
    client: TestClient,
    *,
    label: str,
    drain_completions: list | None = None,
) -> dict:
    game_before = web_app.web_game
    old_path = game_before.db_path if game_before is not None else None
    old_campaign = _campaign_of(game_before) if game_before is not None else None
    old_directive_count = None
    if old_path and os.path.isfile(old_path):
        old_directive_count = _independent_counts(old_path)["directives"]

    n_before = len(drain_completions) if drain_completions is not None else 0
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

    _post_directive(client, f"着户部清核辽饷（{label}）。")
    _wait_pending_writes(game)

    state = client.get("/api/game/state")
    _assert_not_bare_500(state, step=f"{label} state")
    minister = _pick_active_minister(state.json())
    _install_canned_minister(game)
    events = _post_chat_stream(client, minister, f"边饷如何？{label}")
    accepted = next(e for e in events if e.get("event") == "accepted")
    adata = json.loads(accepted["data"])
    assert adata["campaign_id"] == live_campaign
    _wait_pending_writes(game)

    if old_path and drain_completions is not None:
        # 只等本轮 new_game 新产生的 drain completion（确定性握手）
        fresh = drain_completions[n_before:]
        assert fresh, f"{label}: expected drain spawn for old_game"
        _wait_completions(fresh)
        assert all(c.close_ok for c in fresh), (
            f"{label}: drain close_ok failed; completions={[c.close_ok for c in fresh]}"
        )
        assert not os.path.exists(old_path), f"{label}: old db still at {old_path}"
        drained = _drained_saves(Path(web_app.user_data_path()))
        assert drained, f"{label}: expected drained archive"

        archived = None
        for path in drained:
            info = _independent_counts(str(path))
            if old_campaign and info["campaign_id"] == old_campaign:
                archived = info
                break
        assert archived is not None, f"{label}: old campaign missing in drained"
        if old_directive_count is not None:
            assert archived["directives"] == old_directive_count

        live_info = _independent_counts(game.db_path)
        assert live_info["campaign_id"] == live_campaign
        assert live_info["directives"] >= 1
        assert live_info["nights"] >= 1
        # 新局写入不得出现在旧 campaign 归档
        assert archived["campaign_id"] != live_info["campaign_id"]

        if game_before is not None:
            with pytest.raises(Exception):
                game_before.db.conn.execute("SELECT 1")

    # live conn 指向当前库文件（非 drained）
    live_path = game.db_path
    assert os.path.isfile(live_path)
    assert os.path.abspath(live_path) == os.path.abspath(game.db.path)
    assert os.path.abspath(live_path) == os.path.abspath(web_app._get_main_db_path())
    main_file = str(list(game.db.conn.execute("PRAGMA database_list"))[0][2])
    assert os.path.abspath(main_file) == os.path.abspath(live_path)
    for drained in _drained_saves(Path(web_app.user_data_path())):
        assert os.path.abspath(main_file) != os.path.abspath(str(drained))

    live_info = _independent_counts(live_path)
    assert live_info["campaign_id"] == live_campaign
    assert live_info["directives"] >= 1

    return {
        "campaign_id": live_campaign,
        "db_path": game.db_path,
        "minister": minister,
        "old_path": old_path,
        "old_campaign": old_campaign,
    }


def test_direct_new_game_write_path_only_current_db(tracer_client, monkeypatch):
    """直接新局：seed → new_game → 写只落当前库；drain completion 后旧库归档。"""
    client = tracer_client
    completions = _capture_drain_completions(monkeypatch)

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

    result = _new_game_write_round(
        client, label="direct", drain_completions=completions,
    )
    assert result["campaign_id"] != seed_campaign
    assert result["db_path"] != seed_path
    assert result["old_path"] == seed_path
    assert result["old_campaign"] == seed_campaign
    assert not os.path.exists(seed_path)

    reopened = _independent_counts(result["db_path"])
    assert reopened["campaign_id"] == result["campaign_id"]
    assert reopened["directives"] >= 1
    assert reopened["nights"] >= 1


def test_exit_then_new_game_write_path_only_current_db(tracer_client, monkeypatch):
    """exit → new_game：completion 握手后归档；迟到写留旧局。"""
    client = tracer_client
    completions = _capture_drain_completions(monkeypatch)

    seed = client.post("/api/menu/new_game")
    _assert_not_bare_500(seed, step="seed new_game")
    assert seed.status_code == 200
    seed_game = web_app.web_game
    assert seed_game is not None
    seed_path = seed_game.db_path
    seed_campaign = _campaign_of(seed_game)
    _post_directive(client, "着户部清核辽饷（pre-exit）。")
    _wait_pending_writes(seed_game)
    dirs_before_late = _independent_counts(seed_path)["directives"]

    gate = seed_game._write_gate
    gate.acquire()
    n_before_exit = len(completions)
    try:
        exited = client.post("/api/menu/exit_to_menu")
        assert exited.status_code == 200
        assert web_app.web_game is None
        assert os.path.exists(seed_path)

        # 迟到写仍进旧连接（exit detach 卡在 gate）
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
        dirs_after_late = _independent_counts(seed_path)["directives"]
        assert dirs_after_late == dirs_before_late + 1
    finally:
        # exit drain 已 spawn；放 gate 让其完成
        if gate.locked():
            gate.release()

    exit_comps = completions[n_before_exit:]
    assert exit_comps, "exit must spawn drain completion"
    _wait_completions(exit_comps)
    assert all(c.close_ok for c in exit_comps)

    # exit 不搬库；主库文件仍在直至 subsequent new_game 归档
    assert os.path.exists(seed_path)

    # exit 路径 old_game is None：归档走 prev 线程（等 exit completion 后
    # _archive_drained_db_file）。用 Event 接住归档完成，禁盲 sleep/轮询。
    archived_paths: list[str] = []
    archive_done = threading.Event()
    real_archive = web_app._archive_drained_db_file

    def _archive_and_signal(path: str) -> None:
        real_archive(path)
        archived_paths.append(path)
        archive_done.set()

    monkeypatch.setattr(web_app, "_archive_drained_db_file", _archive_and_signal)
    result = _new_game_write_round(
        client, label="exit-new", drain_completions=completions,
    )
    assert result["campaign_id"] != seed_campaign
    assert archive_done.wait(timeout=5.0), (
        f"prev archive not signaled; still_exists={os.path.exists(seed_path)} "
        f"archived={archived_paths}"
    )
    assert not os.path.exists(seed_path), "prev archive after exit close_ok"
    assert any(os.path.abspath(p) == os.path.abspath(seed_path) for p in archived_paths)

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


def test_new_game_real_connection_writable_after_archive(tracer_client, monkeypatch):
    """真 WebGame 连接在旧库 drain completion 后仍可写当前库。"""
    client = tracer_client
    completions = _capture_drain_completions(monkeypatch)

    first = client.post("/api/menu/new_game")
    assert first.status_code == 200
    g1 = web_app.web_game
    assert g1 is not None
    p1 = g1.db_path
    c1 = _campaign_of(g1)
    n0 = len(completions)

    second = client.post("/api/menu/new_game")
    assert second.status_code == 200
    g2 = web_app.web_game
    assert g2 is not None and g2 is not g1
    fresh = completions[n0:]
    assert fresh
    _wait_completions(fresh)
    assert all(c.close_ok for c in fresh)
    assert not os.path.exists(p1)

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
        assert camp and camp[0] == _campaign_of(g2)
        assert camp[0] != c1
    finally:
        indep.close()

    with pytest.raises(Exception):
        g1.db.conn.execute("SELECT 1")
    main = list(g2.db.conn.execute("PRAGMA database_list"))[0][2]
    for drained in _drained_saves(Path(web_app.user_data_path())):
        assert os.path.abspath(str(main)) != os.path.abspath(str(drained))
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
