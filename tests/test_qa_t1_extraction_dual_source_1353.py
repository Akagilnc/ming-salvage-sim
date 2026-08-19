"""QA P0-A #1353+#1312：挡收夜判定与 pending 呈现必须同一真源。

成对一手（r6）：SSE error 报 chat_turn_ids=[N] 时 GET pending 不得 count=0。
本片钉：
1. drain 失败后 pending API 与 error.detail.chat_turn_ids 成对一致（仍待补时）
2. drain 失败清理不得把仍挡收夜的 turn 藏出 list_unextracted
3. drain 失败窗口内并发 heal → 不得留下「报未抽 + pending=0」双源；应续收或对齐
4. write_gate=None 卫兵不被 _gate_cm(nullcontext) 架空
5. r1：部分 heal 新旧 id 集不同 → converter 409 正文只含鲜集（禁 stale+fresh 拼串）
6. r1：session/对话口令收夜穿 runtime write_gate，与颁诏 auto_close 待补同行为
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import ming_sim.audience_extraction as ae
import web_app
from ming_sim import audience_night as an
from tests.conftest import active_ming_character
from tests.test_audience_extraction_501 import _BoomAgent, _minister, _open_night_with_persisted_reply


def _pending_api(db) -> dict:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db)
    return runtime.pending_story_extractions()


def test_drain_fail_closed_pending_api_pairs_with_error_ids(game, tmp_path, monkeypatch):
    """#1353：drain 仍挡收夜时，error.chat_turn_ids 与 pending API 成对非空且同集。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    err_ids = [int(x) for x in (ei.value.detail or {}).get("chat_turn_ids") or []]
    assert ctid in err_ids

    payload = _pending_api(db)
    assert int(payload["count"]) >= 1, (
        f"挡收夜时 pending 必非 0，got {payload!r} err_ids={err_ids}"
    )
    api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
    assert set(err_ids) <= api_ids
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_OPEN


def test_drain_fail_cleanup_does_not_hide_blocking_turn(game, tmp_path, monkeypatch):
    """#1353 负向：drain 失败清理（close scene abandon）不得 fail 掉挡夜的回话 turn。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    abandoned: list[int] = []
    joined: list[int] = []

    class _Reg:
        def start_close(self, *_a, **_k):
            return None

        def abandon(self, chat_turn_id: int):
            abandoned.append(int(chat_turn_id))

        def join(self, chat_turn_id: int):
            joined.append(int(chat_turn_id))
            return []

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db,
            state,
            night_id=nid,
            llm_config=object(),
            write_gate=threading.Lock(),
            beat_generator=object(),
            scene_registry=_Reg(),
        )
    assert ei.value.code == "pending_extraction"
    assert joined == [], "drain 失败路径不得 join 拉长窗口"
    assert abandoned, "drain 失败应 abandon close scaffold"
    assert ctid not in abandoned
    row = db.conn.execute(
        "SELECT status, extract_status, minister_message_id FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]
    assert str(row["extract_status"] or "") in ("", "pending")
    assert int(_pending_api(db)["count"]) >= 1


def test_drain_fail_concurrent_heal_does_not_leave_dual_source(
    game, tmp_path, monkeypatch,
):
    """#1353：drain 报未抽后清理窗口内 heal 不得留下 error 称未抽 + pending=0。

    允许：续收成功；或 error 与 pending 同时反映仍待补；禁双源。
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    def always_pending(**kwargs):
        cid = int(kwargs.get("chat_turn_id") or 0)
        with kwargs["write_gate"]:
            db.mark_story_extraction_pending(cid)
        return {"status": "pending", "chat_turn_id": cid}

    monkeypatch.setattr(ae, "run_extraction_for_turn", always_pending)

    # 在 reopen OPEN 的清理写口同步 heal——模拟 join 旧窗口内 trail 落账完成。
    real_set = an._set_night_fields

    def set_and_heal(db_, night_id, **fields):
        if fields.get("status") == an.NIGHT_STATUS_OPEN:
            db_.conn.execute(
                "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?",
                (ctid,),
            )
            db_.conn.commit()
        return real_set(db_, night_id, **fields)

    monkeypatch.setattr(an, "_set_night_fields", set_and_heal)

    raised: an.AudienceNightError | None = None
    closed = False
    try:
        result = an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
        closed = bool(result.get("closed"))
    except an.AudienceNightError as exc:
        raised = exc

    payload = _pending_api(db)
    if raised is not None and raised.code == "pending_extraction":
        err_ids = [int(x) for x in (raised.detail or {}).get("chat_turn_ids") or []]
        assert err_ids, "pending_extraction 必须带 chat_turn_ids"
        assert int(payload["count"]) >= 1, (
            f"双源禁：error 报未抽 {err_ids} 但 pending={payload!r}"
        )
        api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
        assert set(err_ids) <= api_ids
    else:
        # 清理窗口 heal 后应续收成功，或非 pending_extraction 的可重试中止
        assert closed or raised is None or getattr(raised, "code", None) != "pending_extraction"
        if closed:
            assert int(payload.get("count") or 0) == 0


def test_write_gate_none_not_defeated_by_nullcontext(game, tmp_path, monkeypatch):
    """嫌疑缝②：write_gate=None 时不得因 _gate_cm→nullcontext 绕过卫兵去假跑 drain。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    called = {"drain": 0}
    real_drain = ae.drain_pending_before_close

    def track_drain(*a, **k):
        called["drain"] += 1
        return real_drain(*a, **k)

    monkeypatch.setattr(ae, "drain_pending_before_close", track_drain)

    with pytest.raises(an.AudienceNightError) as ei:
        # llm_config 有值、write_gate 缺 —— 旧 bug 会把 nullcontext 当「有锁」去 drain
        an.close_night(db, state, night_id=nid, llm_config=object(), write_gate=None)
    assert ei.value.code == "pending_extraction"
    assert called["drain"] == 0
    assert ctid in [
        int(x) for x in (ei.value.detail or {}).get("chat_turn_ids") or []
    ]
    assert int(_pending_api(db)["count"]) >= 1


def test_issue_409_recovery_pending_pairs_for_retry_cta(game, tmp_path, monkeypatch):
    """#1312：颁诏/收夜 409 后 pending 非 0，retry 数源可喂拟诏台 CTA。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    payload = _pending_api(db)
    assert int(payload["count"]) >= 1
    assert any(int(p["chat_turn_id"]) == ctid for p in payload["pending"])
    # retry 入口读同一真源
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, llm_config=None)
    runtime._runtime_write_gate = lambda: threading.Lock()  # type: ignore[method-assign]
    runtime.pending_story_extractions = (  # type: ignore[method-assign]
        lambda: web_app.WebGame.pending_story_extractions(runtime)
    )
    # catch_up 仍 boom → pending 保持
    monkeypatch.setattr(
        web_app, "catch_up_pending_extractions",
        lambda **_k: {"extracted": 0, "pending": 1, "scanned": 1},
    )
    after = web_app.WebGame.retry_story_extractions(runtime)
    assert int(after["count"]) >= 1


def test_converter_409_body_only_fresh_ids_after_partial_heal(
    game, tmp_path, monkeypatch,
):
    """#1353 r1：部分 heal 后新旧 id 集不同 → converter 渲染正文只含鲜集。

    禁 `raise fresh from drain_exc` 把 stale chat_turn_ids 拼进 409 正文。
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid_stale, _ = _open_night_with_persisted_reply(db, state, minister, reply="甲。")
    # 同夜第二条待补回话——清理窗只愈其一，制造 stale⊃fresh。
    ctid_fresh = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), "乙。", ctid_fresh)

    real_set = an._set_night_fields

    def heal_stale_only(db_, night_id, **fields):
        if fields.get("status") == an.NIGHT_STATUS_OPEN:
            db_.conn.execute(
                "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?",
                (ctid_stale,),
            )
            db_.conn.commit()
        return real_set(db_, night_id, **fields)

    monkeypatch.setattr(an, "_set_night_fields", heal_stale_only)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    fresh_ids = [int(x) for x in (ei.value.detail or {}).get("chat_turn_ids") or []]
    assert fresh_ids == [ctid_fresh], fresh_ids
    assert ctid_stale not in fresh_ids

    http_exc = web_app._retryable_audience_close_http(ei.value)
    assert http_exc.status_code == 409
    body = str(http_exc.detail)
    assert f"chat_turn_ids=[{ctid_fresh}]" in body, body
    assert str(ctid_stale) not in body, (
        f"409 正文不得含已愈 stale id={ctid_stale}：{body!r}"
    )
    # cause 链不得再挂 pending_extraction stale 快照
    assert ei.value.__cause__ is None or getattr(
        ei.value.__cause__, "code", None
    ) != "pending_extraction"


def test_close_after_chat_passes_write_gate_like_auto_close(
    game, tmp_path, monkeypatch,
):
    """#1353 r1：口令收夜穿 runtime write_gate，与颁诏 auto_close 待补同形。

    禁因漏传 write_gate 误报「无 LLM/写锁」——卫兵仍在，只是真锁须穿到。
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _ = _open_night_with_persisted_reply(db, state, minister)

    from ming_sim.session import GameSession

    gate = threading.Lock()
    seen: dict = {}

    real_close = an.close_night

    def track_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return real_close(*a, **k)

    monkeypatch.setattr(an, "close_night", track_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._write_gate = gate

    with pytest.raises(an.AudienceNightError) as ei_cmd:
        # 显式穿锁（web epilogue 形）
        sess.close_night_after_chat_if_needed("court_break", write_gate=gate)
    assert ei_cmd.value.code == "pending_extraction"
    assert seen.get("write_gate") is gate
    msg_cmd = str(ei_cmd.value)
    assert "无 LLM/写锁" not in msg_cmd, msg_cmd
    assert ctid in [
        int(x) for x in (ei_cmd.value.detail or {}).get("chat_turn_ids") or []
    ]

    # 夜仍 open + 待补 —— 颁诏 auto_close 同 gate 同文案族
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_OPEN
    seen.clear()
    with pytest.raises(an.AudienceNightError) as ei_edict:
        an.auto_close_open_night(
            db, state, llm_config=object(), write_gate=gate,
        )
    assert ei_edict.value.code == "pending_extraction"
    assert seen.get("write_gate") is gate
    assert "无 LLM/写锁" not in str(ei_edict.value)
    # 两路 detail 同鲜集
    assert (ei_cmd.value.detail or {}).get("chat_turn_ids") == (
        ei_edict.value.detail or {}
    ).get("chat_turn_ids")


def test_close_after_chat_session_write_gate_fallback(game, tmp_path, monkeypatch):
    """session._write_gate 回落：未显式传 write_gate 时仍穿既有锁。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    _open_night_with_persisted_reply(db, state, minister)

    from ming_sim.session import GameSession

    gate = threading.Lock()
    seen: dict = {}
    real_close = an.close_night

    def track_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return real_close(*a, **k)

    monkeypatch.setattr(an, "close_night", track_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._write_gate = gate

    with pytest.raises(an.AudienceNightError) as ei:
        sess.close_night_after_chat_if_needed("court_break")
    assert ei.value.code == "pending_extraction"
    assert seen.get("write_gate") is gate
    assert "无 LLM/写锁" not in str(ei.value)
