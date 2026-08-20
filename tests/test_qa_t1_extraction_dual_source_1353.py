"""QA P0 #1353：OPEN 期汇合普通抽取 + 闸/账一致 + 删除面。

钉：
1. 竞态：owner 在跑时发起 close → 有限 join 后一次过（不 409、不假 pending）
1b. 竞态：join 已返回、freeze 前才 admission 的 owner（确定性调度钉，不靠 sleep）
2. 真欠账时 pending 必非空可重试（error.ids 与 pending API 同集）
3. drain 失败清理不得藏挡夜 turn；write_gate=None 卫兵不被架空
4. 清理窗部分 heal → 409 正文只含鲜集；全愈 → close_retry（无递归重入）
5. 口令收夜穿 runtime write_gate
6. 背书空文本独立 fail-closed + 409 重试形态
7. 删除面：无 _healed_drain_retry / closing+zero player_hint
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import ming_sim.audience_extraction as ae
import web_app
from ming_sim import audience_night as an
from tests.test_audience_extraction_501 import (
    _BoomAgent,
    _FactsAgent,
    _minister,
    _open_night_with_persisted_reply,
)


def _pending_api(db) -> dict:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db)
    return runtime.pending_story_extractions()


def test_close_joins_in_flight_owner_while_open_one_shot(game, tmp_path, monkeypatch):
    """#1353 竞态钉：owner 在跑时 close → OPEN 期 join 后一次过（不 409 不假 pending）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    started = threading.Event()
    release_llm = threading.Event()
    gate = threading.Lock()
    owner_result: dict = {}

    class _SlowAgent:
        def run(self, _material):
            started.set()
            assert release_llm.wait(5), "test release signal"
            return SimpleNamespace(
                content=(
                    '{"facts":[{"person_names":["'
                    + minister
                    + '"],"audibility":"殿上公开","body":"慢抽取落账","tags":[],'
                    '"presence_effect":""}]}'
                )
            )

    def owner_worker():
        owner_result["out"] = ae.run_extraction_for_turn(
            db=db,
            minister_name=minister,
            reply="臣愿肩起此事。",
            chat_turn_id=ctid,
            night_id=nid,
            source_night_seq=seq,
            llm_config=object(),
            write_gate=gate,
            extractor_agent=_SlowAgent(),
            allow_closing=False,  # 后台 trail 形：CLOSING 后 settle 必败（旧竞态根）
        )

    owner_thread = threading.Thread(target=owner_worker, name="extract-owner-1353")
    owner_thread.start()
    assert started.wait(2), "owner must enter LLM before close"

    # 放行 owner LLM，同时发起 close——join 须等 owner settle（仍 OPEN）后冻结
    def release_soon():
        time.sleep(0.05)
        release_llm.set()

    threading.Thread(target=release_soon, name="release-llm-1353", daemon=True).start()

    result = an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=gate,
    )
    owner_thread.join(timeout=5)
    assert not owner_thread.is_alive()

    assert result.get("closed") is True, result
    assert owner_result.get("out", {}).get("status") == "done"
    assert db.get_story_extract_status(ctid) == "done"
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert int(_pending_api(db)["count"]) == 0


def test_close_joins_owner_admitted_after_join_before_freeze(
    game, tmp_path, monkeypatch,
):
    """#1353 r2：join 已返回、freeze 尚未发生时 owner 才启动 → 仍一次过（不假 pending）。

    确定性调度钉（不靠 sleep 竞猜）：
    - 第 1 次 join 返回后同步 admission owner，并等到其进入 LLM；
    - 第 2 次 join（gate 内 inflight 复查看见后的再汇合）才放行 owner settle。
    旧实现只 join 一次即 freeze → owner allow_closing=False settle 必败 → 假 pending。
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    started_llm = threading.Event()
    release_llm = threading.Event()
    gate = threading.Lock()
    owner_result: dict = {}
    join_calls = {"n": 0}
    owner_thread_box: list[threading.Thread] = []

    class _SlowAgent:
        def run(self, _material):
            started_llm.set()
            assert release_llm.wait(5), "second join must release owner"
            return SimpleNamespace(
                content=(
                    '{"facts":[{"person_names":["'
                    + minister
                    + '"],"audibility":"殿上公开","body":"窗内启动落账","tags":[],'
                    '"presence_effect":""}]}'
                )
            )

    def owner_worker():
        owner_result["out"] = ae.run_extraction_for_turn(
            db=db,
            minister_name=minister,
            reply="臣愿肩起此事。",
            chat_turn_id=ctid,
            night_id=nid,
            source_night_seq=seq,
            llm_config=object(),
            write_gate=gate,
            extractor_agent=_SlowAgent(),
            allow_closing=False,  # 后台 trail 形
        )

    real_join = ae.join_pending_turn_extractions

    def join_schedule_hook(db_, *, night_id, timeout_s=None):
        join_calls["n"] += 1
        if join_calls["n"] == 1:
            # 先跑真 join（此时尚无 owner），返回后才 admission——钉住 join→freeze 窗。
            real_join(db_, night_id=night_id, timeout_s=timeout_s)
            t = threading.Thread(
                target=owner_worker, name="extract-owner-after-join-1353",
            )
            owner_thread_box.append(t)
            t.start()
            assert started_llm.wait(2), (
                "owner must enter LLM inside join→freeze window"
            )
            return None
        # 第 2+ 次：close 在 gate 内看见 inflight 后的再汇合——此刻放行 owner。
        release_llm.set()
        return real_join(db_, night_id=night_id, timeout_s=timeout_s)

    monkeypatch.setattr(ae, "join_pending_turn_extractions", join_schedule_hook)

    result = an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=gate,
    )
    assert owner_thread_box, "owner must have been admitted after first join"
    owner_thread_box[0].join(timeout=5)
    assert not owner_thread_box[0].is_alive()

    assert join_calls["n"] >= 2, (
        f"inflight recheck must re-join after window admission, got {join_calls['n']}"
    )
    assert result.get("closed") is True, result
    assert owner_result.get("out", {}).get("status") == "done", owner_result
    assert db.get_story_extract_status(ctid) == "done"
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert int(_pending_api(db)["count"]) == 0


def test_drain_fail_closed_pending_api_pairs_with_error_ids(game, tmp_path, monkeypatch):
    """#1353：真欠账时 error.chat_turn_ids 与 pending API 成对非空且同集。"""
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
    # 删除面：closing+zero 自愈 hint 不得再发
    assert not payload.get("player_hint")


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


def test_drain_fail_concurrent_heal_asks_retry_no_dual_source(
    game, tmp_path, monkeypatch,
):
    """#1353：drain 报未抽后清理窗 heal → close_retry（无递归）；禁 error 未抽 + pending=0。"""
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

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "close_retry"
    assert int(_pending_api(db)["count"]) == 0
    # 无递归：signature 不得再收 _healed_drain_retry
    import inspect
    assert "_healed_drain_retry" not in inspect.signature(an.close_night).parameters


def test_write_gate_none_not_defeated_by_nullcontext(game, tmp_path, monkeypatch):
    """write_gate=None 时不得因 _gate_cm→nullcontext 绕过卫兵去假跑 drain。"""
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
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, llm_config=None)
    runtime._runtime_write_gate = lambda: threading.Lock()  # type: ignore[method-assign]
    runtime.pending_story_extractions = (  # type: ignore[method-assign]
        lambda: web_app.WebGame.pending_story_extractions(runtime)
    )
    monkeypatch.setattr(
        web_app, "catch_up_pending_extractions",
        lambda **_k: {"extracted": 0, "pending": 1, "scanned": 1},
    )
    after = web_app.WebGame.retry_story_extractions(runtime)
    assert int(after["count"]) >= 1


def test_converter_409_body_only_fresh_ids_after_partial_heal(
    game, tmp_path, monkeypatch,
):
    """部分 heal 后新旧 id 集不同 → converter 409 正文只含鲜集。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid_stale, _ = _open_night_with_persisted_reply(db, state, minister, reply="甲。")
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
    assert ei.value.__cause__ is None or getattr(
        ei.value.__cause__, "code", None
    ) != "pending_extraction"


def test_close_retry_on_healed_cleanup_no_stale_ids(game, tmp_path, monkeypatch):
    """清理窗全愈 → close_retry（无 _healed_drain_retry 递归）；409 无 stale ids。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid_stale, _ = _open_night_with_persisted_reply(db, state, minister)

    real_set = an._set_night_fields

    def heal_all_on_open(db_, night_id, **fields):
        if fields.get("status") == an.NIGHT_STATUS_OPEN:
            db_.conn.execute(
                "UPDATE chat_turns SET extract_status = 'done' "
                "WHERE night_id = ? AND minister_message_id IS NOT NULL",
                (int(night_id),),
            )
            db_.conn.commit()
        return real_set(db_, night_id, **fields)

    monkeypatch.setattr(an, "_set_night_fields", heal_all_on_open)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "close_retry", (
        f"expected close_retry, got {ei.value.code}: {ei.value}"
    )
    assert ei.value.__cause__ is None or getattr(
        ei.value.__cause__, "code", None
    ) != "pending_extraction"

    http_exc = web_app._retryable_audience_close_http(ei.value)
    assert http_exc.status_code == 409
    body = str(http_exc.detail)
    assert str(ctid_stale) not in body, (
        f"close_retry 409 正文不得含已愈 stale id={ctid_stale}：{body!r}"
    )
    assert "chat_turn_ids=" not in body, body
    assert int(_pending_api(db)["count"]) == 0


def test_close_after_chat_passes_write_gate_like_auto_close(
    game, tmp_path, monkeypatch,
):
    """口令收夜穿 runtime write_gate，与颁诏 auto_close 待补同形。"""
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
        sess.close_night_after_chat_if_needed("court_break", write_gate=gate)
    assert ei_cmd.value.code == "pending_extraction"
    assert seen.get("write_gate") is gate
    msg_cmd = str(ei_cmd.value)
    assert "无 LLM/写锁" not in msg_cmd, msg_cmd
    assert ctid in [
        int(x) for x in (ei_cmd.value.detail or {}).get("chat_turn_ids") or []
    ]

    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_OPEN
    seen.clear()
    with pytest.raises(an.AudienceNightError) as ei_edict:
        an.auto_close_open_night(
            db, state, llm_config=object(), write_gate=gate,
        )
    assert ei_edict.value.code == "pending_extraction"
    assert seen.get("write_gate") is gate
    assert "无 LLM/写锁" not in str(ei_edict.value)
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


def test_empty_endorsement_text_fail_closed_retryable_409(game, tmp_path, monkeypatch):
    """#1353 Class2：背书空文本独立 fail-closed；409 走既有重试形态（可重试颁诏/收夜）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣愿作保。")

    # 普通抽取先落 done，使失败面只剩 endorsement
    fact_agent = _FactsAgent(
        '{"facts":[{"person_names":["'
        + minister
        + '"],"audibility":"殿上公开","body":"站台","tags":["站台"],'
        '"presence_effect":""}]}'
    )
    assert ae.run_extraction_for_turn(
        db=db,
        minister_name=minister,
        reply="臣愿作保。",
        chat_turn_id=ctid,
        night_id=nid,
        source_night_seq=seq,
        llm_config=object(),
        write_gate=threading.Lock(),
        extractor_agent=fact_agent,
    )["status"] == "done"

    # stub 候选 + 空文本 agent，迫使 endorsement LLM 被调用
    db.list_endorsement_batch_inputs = lambda _nid: {  # type: ignore[method-assign]
        "candidates": [{
            "ref": {"dossier_id": 1, "kind": "directive"},
            "decree_text": "清核辽饷",
        }],
        "turns": [{
            "source_chat_turn_id": ctid,
            "minister_name": minister,
            "emperor_text": "准。",
            "minister_reply": "臣愿作保。",
            "ordinary_facts": [],
        }],
    }

    class _EmptyEndorsement:
        def run(self, _materials):
            return SimpleNamespace(content="   ")

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda cfg: _EmptyEndorsement(),
    )

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, content=content,
            llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "endorsement_extract_failed"
    assert "空文本" in str(ei.value)
    night = an.get_night(db, nid)
    assert night["status"] == an.NIGHT_STATUS_OPEN
    assert int(night["close_commit_cursor"] or 0) == 0

    http_exc = web_app._retryable_audience_close_http(ei.value)
    assert http_exc.status_code == 409
    body = str(http_exc.detail)
    assert "空文本" in body or "背书" in body
    # 既有失败单源：409 即重试 CTA（玩家重点颁诏/收夜）；无新 endpoint/文案模板
    assert "chat_turn_ids=" not in body  # 不与 pending_extraction 混面


def test_deleted_surface_no_healed_drain_retry_residue():
    """删除面 grep 钉：_healed_drain_retry 零残留。"""
    import inspect
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for rel in (
        "ming_sim/audience_night.py",
        "ming_sim/audience_extraction.py",
        "web_app.py",
        "web/src/useChatActions.ts",
        "web/src/components/chatModal.tsx",
        "web/src/types.ts",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        if "_healed_drain_retry" in text:
            hits.append(rel)
        if "player_hint" in text and "自愈" in text:
            hits.append(f"{rel}:player_hint自愈")
        if "extractionHealedHint" in text:
            hits.append(f"{rel}:extractionHealedHint")
    assert hits == [], hits
    assert "_healed_drain_retry" not in inspect.signature(an.close_night).parameters
