"""QA P0 #1353：OPEN 期汇合普通抽取 + 欠账并入过月 + 删除面。

钉：
1. 竞态：owner 在跑时发起 close → 有限 join 后一次过（不 409、不假 pending）
1b. 竞态：join 已返回、freeze 前才 admission 的 owner（确定性调度钉，不靠 sleep）
2. 真欠账耗尽 → 失败单源（LLMUnavailable/通传未达）；诊断 pending API 非空
3. drain 失败清理不得藏挡夜 turn；write_gate=None 卫兵不被架空
4. 清理窗部分 heal → 失败单源 + pending 仅鲜集；全愈 → close_retry（无递归重入）
5. 口令收夜穿 runtime write_gate
6. 背书空文本独立 fail-closed + 409 重试形态（非欠账类）
7. 删除面：无 _healed_drain_retry / closing+zero player_hint / 玩家补写 CTA
8. fold-in r2 K10a：wait_in_flight 不按 elapsed 造 409
9. fold-in r2/r3 K10c：背书争用一次有界 join + 重读 DB（禁 while/二次 LLM/contended 409）
   9a. owner 挂过预算 → contender 有限 fail-closed
   9b. owner 真失败 → contender 不调 extractor、夜未绑定
10. fold-in r5：drain/catch_up 不推玩家可见补写 stage；签名无 on_event
11. fold-in r9：整轮 worker 真终态后才 gate-free close（尾随 pending-write）
12. fold-in r9：CLI 真实闭环钉——pending→一次 advance→turn+1 / 耗尽留回合
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import ming_sim.audience_extraction as ae
import ming_sim.cli.terminal as term
import web_app
from ming_sim import audience_night as an
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.session import GameSession
from tests.test_audience_extraction_501 import (
    _BoomAgent,
    _FactsAgent,
    _minister,
    _open_night_with_persisted_reply,
)
from tests.test_no_edict_full_settlement_1274 import _canned_full_settlement


def _pending_api(db) -> dict:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db)
    return runtime.pending_story_extractions()


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（temp DB）；r9 工人终态钉用。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    return web_app.WebGame(fresh=False)


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
    """#1353 fold-in：真欠账耗尽 → 失败单源；诊断 pending API 含本轮 debt。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert "待补" not in ei.value.message
    assert "chat_turn" not in ei.value.message

    payload = _pending_api(db)
    assert int(payload["count"]) >= 1, (
        f"挡收夜时 pending 必非 0，got {payload!r}"
    )
    api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
    assert ctid in api_ids
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

    with pytest.raises(LLMUnavailable) as ei:
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
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
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

    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(db, state, night_id=nid, llm_config=object(), write_gate=None)
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert called["drain"] == 0
    payload = _pending_api(db)
    assert int(payload["count"]) >= 1
    assert ctid in {int(p["chat_turn_id"]) for p in payload.get("pending") or []}


def test_debt_exhausted_single_source_no_player_cta(game, tmp_path, monkeypatch):
    """#1353 fold-in：欠账耗尽 → 失败单源；诊断 pending 可查；无玩家补写 CTA 面。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent()
    )
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    payload = _pending_api(db)
    assert int(payload["count"]) >= 1
    assert any(int(p["chat_turn_id"]) == ctid for p in payload["pending"])
    # 删除面：玩家 message 不得再带待补/chat_turn CTA 语义
    assert "待补" not in ei.value.message
    assert "补写" not in ei.value.message
    assert "chat_turn" not in ei.value.message


def test_partial_heal_single_source_pending_only_fresh(
    game, tmp_path, monkeypatch,
):
    """部分 heal 后新旧 id 集不同 → 失败单源；诊断 pending 只含鲜集。"""
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

    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    # 玩家面无 id；诊断 pending 仅鲜集
    assert "chat_turn" not in ei.value.message
    payload = _pending_api(db)
    api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
    assert api_ids == {ctid_fresh}, api_ids
    assert ctid_stale not in api_ids
    assert str(ctid_fresh) in str(ei.value.provider_message)
    assert str(ctid_stale) not in str(ei.value.provider_message)


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

    with pytest.raises(LLMUnavailable) as ei_cmd:
        sess.close_night_after_chat_if_needed("court_break", write_gate=gate)
    assert ei_cmd.value.code == "pending_extraction"
    assert ei_cmd.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert seen.get("write_gate") is gate
    msg_cmd = str(ei_cmd.value)
    assert "无 LLM/写锁" not in msg_cmd, msg_cmd
    assert ctid in {int(p["chat_turn_id"]) for p in _pending_api(db).get("pending") or []}

    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_OPEN
    seen.clear()
    with pytest.raises(LLMUnavailable) as ei_edict:
        an.auto_close_open_night(
            db, state, llm_config=object(), write_gate=gate,
        )
    assert ei_edict.value.code == "pending_extraction"
    assert ei_edict.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert seen.get("write_gate") is gate
    assert "无 LLM/写锁" not in str(ei_edict.value)
    assert ei_cmd.value.message == ei_edict.value.message


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

    with pytest.raises(LLMUnavailable) as ei:
        sess.close_night_after_chat_if_needed("court_break")
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
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
    """删除面 grep 钉：自愈 hint + 玩家补写 CTA/CLI 命令/Web retry 入口零残留。"""
    import inspect
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for rel in (
        "ming_sim/audience_night.py",
        "ming_sim/audience_extraction.py",
        "ming_sim/cli/terminal.py",
        "web_app.py",
        "web/src/useChatActions.ts",
        "web/src/useSettlementFlow.ts",
        "web/src/components/chatModal.tsx",
        "web/src/components/edictModal.tsx",
        "web/src/main.tsx",
        "web/src/types.ts",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        if "_healed_drain_retry" in text:
            hits.append(rel)
        if "player_hint" in text and "自愈" in text:
            hits.append(f"{rel}:player_hint自愈")
        if "extractionHealedHint" in text:
            hits.append(f"{rel}:extractionHealedHint")
        # #1353 fold-in：玩家可见补写 CTA / CLI 命令 / Web retry 包装
        for needle in (
            "data-testid=\"extraction-pending\"",
            "data-testid=\"edict-extraction-pending\"",
            "召对账待补写",
            "重试补写",
            "retry extraction",
            "retry_extraction",
            "onRetryExtraction",
            "extractionPendingCount",
            "retryStoryExtraction",
            "retryAudienceStoryExtraction",
            "retry_story_extractions",
            "/api/audience/extraction/retry",
            "_retry_story_extraction_cli",
            "_print_extraction_pending_hint",
            # #1353 fold-in r5：欠账技术进度/CLI 提示不得穿透玩家面
            "补写召对账本",
            "【账本抽取】",
            "过月时自动补跑",
        ):
            if needle in text:
                hits.append(f"{rel}:{needle}")
    # extractionRetry 模块整链删除
    if (root / "web/src/extractionRetry.ts").exists():
        hits.append("web/src/extractionRetry.ts:exists")
    assert hits == [], hits
    assert "_healed_drain_retry" not in inspect.signature(an.close_night).parameters
    # fold-in r2/r3：禁 elapsed 伪造 in_flight / 背书争用 409 / while 回环二次 LLM
    prod = (root / "ming_sim/audience_extraction.py").read_text(encoding="utf-8")
    assert 'code="endorsement_batch_contended"' not in prod
    # run_endorsement_batch_for_night 体：一次 claim+join，禁 while True 无界重试
    fn_start = prod.index("def run_endorsement_batch_for_night")
    fn_end = prod.index("\ndef ", fn_start + 1)
    assert "while True" not in prod[fn_start:fn_end], (
        "K10c forbids unbounded while-retry in endorsement contention"
    )
    night_src = (root / "ming_sim/audience_night.py").read_text(encoding="utf-8")
    assert 'code="in_flight_chat"' not in night_src


def test_wait_in_flight_clear_consumes_terminal_no_elapsed_409(game):
    """#1353 K10a：在飞 hang 时 wait 不按 elapsed 抛；工人终态后返回。"""
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.summon_enter(db, nid, minister, method=an.METHOD_XUANRU)
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="sess-k10a", agno_runs_before=0,
    )
    mid = db.append_chat_message(minister, state.turn, "user", "边饷如何？")
    db.update_chat_turn_messages(ctid, user_message_id=mid)
    assert an.list_in_flight_chat_turns(db, nid)

    done = threading.Event()
    raised: list = []

    def waiter():
        try:
            an.wait_in_flight_clear(db, nid, timeout_s=0.0, poll_s=0.01)
        except BaseException as exc:  # noqa: BLE001 — 采集任何伪造失败
            raised.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=waiter, name="wait-inflight-k10a")
    t.start()
    # 给 waiter 时间进入轮询；timeout_s=0 旧路径会立即 409
    time.sleep(0.05)
    assert t.is_alive(), "must keep waiting for worker terminal, not forge elapsed failure"
    # 工人终态：fail 清在飞
    db.fail_chat_turn(int(ctid))
    assert done.wait(2.0), "waiter did not observe terminal"
    t.join(timeout=1.0)
    assert raised == [], f"K10a forbids elapsed-forged failure: {raised!r}"
    assert an.list_in_flight_chat_turns(db, nid) == []


def _prep_endorsement_contention(game, tmp_path, monkeypatch, *, reply="臣愿作保。"):
    """K10c 并发夹具：普通抽取 done + 背书批输入桩。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply=reply)
    assert ae.run_extraction_for_turn(
        db=db,
        minister_name=minister,
        reply=reply,
        chat_turn_id=ctid,
        night_id=nid,
        source_night_seq=seq,
        llm_config=object(),
        write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(
            '{"facts":[{"person_names":["'
            + minister
            + '"],"audibility":"殿上公开","body":"站台","tags":[],'
            '"presence_effect":""}]}'
        ),
    )["status"] == "done"
    db.list_endorsement_batch_inputs = lambda _nid: {  # type: ignore[method-assign]
        "candidates": [{
            "ref": {"dossier_id": 1, "kind": "directive"},
            "decree_text": "清核辽饷",
        }],
        "turns": [{
            "source_chat_turn_id": ctid,
            "minister_name": minister,
            "emperor_text": "准。",
            "minister_reply": reply,
            "ordinary_facts": [],
        }],
    }
    return db, nid


def test_endorsement_contention_joins_owner_then_continues(game, tmp_path, monkeypatch):
    """#1353 K10c：owner 成功绑定 → contender 一次有界 join 后重读 bound 续跑。"""
    db, nid = _prep_endorsement_contention(game, tmp_path, monkeypatch)

    started = threading.Event()
    release_llm = threading.Event()
    gate = threading.Lock()
    owner_out: dict = {}
    contender_out: dict = {}

    class _SlowEndorsement:
        def run(self, _materials):
            started.set()
            assert release_llm.wait(5), "release endorsement owner"
            return SimpleNamespace(content='{"endorsements":[]}')

    def owner_worker():
        try:
            owner_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_SlowEndorsement(),
            )
        except BaseException as exc:  # noqa: BLE001
            owner_out["exc"] = exc

    ot = threading.Thread(target=owner_worker, name="endorsement-owner-k10c")
    ot.start()
    assert started.wait(5), "owner LLM must start"

    def contender_worker():
        try:
            contender_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_BoomAgent(),  # 成功路径 contender 只重读 bound，禁二次 LLM
                join_timeout_s=5.0,  # 覆盖 owner 成功绑定窗口；禁短预算误杀
            )
        except BaseException as exc:  # noqa: BLE001
            contender_out["exc"] = exc

    ct = threading.Thread(target=contender_worker, name="endorsement-contender-k10c")
    ct.start()
    # contender 进入 join，不得立即 contended 抛出
    time.sleep(0.05)
    assert ct.is_alive(), "contender must be joining owner, not returning contended 409"
    release_llm.set()
    ot.join(timeout=5)
    ct.join(timeout=5)
    assert not ot.is_alive() and not ct.is_alive()

    assert "exc" not in owner_out, owner_out
    assert "exc" not in contender_out, contender_out
    assert owner_out["r"]["status"] in {"done", "skipped"}
    assert contender_out["r"]["status"] in {"done", "skipped"}
    assert ae._is_endorsement_bound(db, nid)
    assert getattr(contender_out.get("exc"), "code", None) != "endorsement_batch_contended"


def test_endorsement_contender_join_timeout_fail_closed_no_second_budget(
    game, tmp_path, monkeypatch,
):
    """#1353 K10c r3：(a) owner 挂过总预算 → contender 一次 join 后有限 fail-closed。"""
    db, nid = _prep_endorsement_contention(game, tmp_path, monkeypatch)

    started = threading.Event()
    release_llm = threading.Event()
    gate = threading.Lock()
    owner_out: dict = {}
    contender_out: dict = {}
    contender_calls = {"n": 0}

    class _HangEndorsement:
        def run(self, _materials):
            started.set()
            assert release_llm.wait(5), "release hang owner"
            return SimpleNamespace(content='{"endorsements":[]}')

    class _CountEndorsement:
        def run(self, _materials):
            contender_calls["n"] += 1
            raise AssertionError("contender must not start second endorsement LLM")

    def owner_worker():
        try:
            owner_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_HangEndorsement(),
            )
        except BaseException as exc:  # noqa: BLE001
            owner_out["exc"] = exc

    ot = threading.Thread(target=owner_worker, name="endorsement-owner-hang-k10c")
    ot.start()
    assert started.wait(5), "owner LLM must start"

    t0 = time.monotonic()

    def contender_worker():
        try:
            contender_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_CountEndorsement(),
                join_timeout_s=0.05,
            )
        except BaseException as exc:  # noqa: BLE001
            contender_out["exc"] = exc

    ct = threading.Thread(target=contender_worker, name="endorsement-contender-timeout-k10c")
    ct.start()
    ct.join(timeout=2.0)
    elapsed = time.monotonic() - t0
    assert not ct.is_alive(), "contender must finite-return after one join budget"
    assert elapsed < 1.0, f"unbounded while-retry suspected: elapsed={elapsed:.3f}s"
    assert "exc" in contender_out, contender_out
    assert getattr(contender_out["exc"], "code", None) == "endorsement_not_bound"
    assert getattr(contender_out["exc"], "code", None) != "endorsement_batch_contended"
    assert contender_calls["n"] == 0
    # owner 仍在飞：夜不得被 contender 绑定
    assert not ae._is_endorsement_bound(db, nid)

    release_llm.set()
    ot.join(timeout=5)
    assert not ot.is_alive()
    # owner 最终可绑定；contender 不得在超时路径抢成第二 owner
    assert "exc" not in owner_out, owner_out
    assert ae._is_endorsement_bound(db, nid)


def test_endorsement_owner_fail_contender_no_second_llm(game, tmp_path, monkeypatch):
    """#1353 K10c r3：(b) owner 真失败 → contender 不调 extractor、夜未绑定 fail-closed。"""
    db, nid = _prep_endorsement_contention(game, tmp_path, monkeypatch)

    started = threading.Event()
    release_fail = threading.Event()
    gate = threading.Lock()
    owner_out: dict = {}
    contender_out: dict = {}
    contender_calls = {"n": 0}

    class _FailEndorsement:
        def run(self, _materials):
            started.set()
            assert release_fail.wait(5), "release fail owner"
            raise RuntimeError("owner endorsement true failure")

    class _CountEndorsement:
        def run(self, _materials):
            contender_calls["n"] += 1
            return SimpleNamespace(content='{"endorsements":[]}')

    def owner_worker():
        try:
            owner_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_FailEndorsement(),
            )
        except BaseException as exc:  # noqa: BLE001
            owner_out["exc"] = exc

    ot = threading.Thread(target=owner_worker, name="endorsement-owner-fail-k10c")
    ot.start()
    assert started.wait(5), "owner LLM must start"

    def contender_worker():
        try:
            contender_out["r"] = ae.run_endorsement_batch_for_night(
                db=db,
                night_id=nid,
                llm_config=object(),
                write_gate=gate,
                extractor_agent=_CountEndorsement(),
                join_timeout_s=5.0,
            )
        except BaseException as exc:  # noqa: BLE001
            contender_out["exc"] = exc

    ct = threading.Thread(target=contender_worker, name="endorsement-contender-fail-k10c")
    ct.start()
    time.sleep(0.05)
    assert ct.is_alive(), "contender must join, not contend-409"
    release_fail.set()
    ot.join(timeout=5)
    ct.join(timeout=5)
    assert not ot.is_alive() and not ct.is_alive()

    assert "exc" in owner_out, owner_out
    assert getattr(owner_out["exc"], "code", None) == "endorsement_extract_failed"
    assert "exc" in contender_out, contender_out
    assert getattr(contender_out["exc"], "code", None) == "endorsement_not_bound"
    assert getattr(contender_out["exc"], "code", None) != "endorsement_batch_contended"
    assert contender_calls["n"] == 0, "K10b: contender must not start second LLM"
    assert not ae._is_endorsement_bound(db, nid)


def test_drain_catch_up_silent_no_on_event_surface(game, tmp_path, monkeypatch):
    """#1353 fold-in r5：drain/catch_up 静默补跑——签名无 on_event，落账仍成功。"""
    import inspect

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)

    assert "on_event" not in inspect.signature(ae.catch_up_pending_extractions).parameters
    assert "on_event" not in inspect.signature(ae.drain_pending_before_close).parameters
    assert "on_event" not in inspect.signature(an.close_night).parameters
    assert "on_event" not in inspect.signature(an.auto_close_open_night).parameters

    ae.drain_pending_before_close(
        db=db,
        llm_config=object(),
        write_gate=threading.Lock(),
        night_id=nid,
        extractor_agent=_FactsAgent(
            '{"facts":[{"person_names":["'
            + minister
            + '"],"audibility":"殿上公开","body":"静默落","tags":[],'
            '"presence_effect":""}]}'
        ),
    )
    assert db.get_story_extract_status(ctid) == "done"
    # 生产源码无欠账技术进度文案
    import pathlib

    prod = pathlib.Path(ae.__file__).read_text(encoding="utf-8")
    assert "补写召对账本" not in prod
    assert "过月时自动补跑" not in prod


def test_await_inflight_blocks_until_trail_worker_end(web_game):
    """#1353 fold-in r9 最小诊断钉：chat_turn 已 done 但尾随仍持 pending-write 时，
    gate-free close 前门必须等整轮 worker 真终态（_complete_pending_write）才返回。

    旧缝只等 list_in_flight_chat_turns（minister_message 已落即放行）→ 尾随与
    auto_close 并发打同一 SQLite 连接随机 500。禁新锁：复用既有 _drain_cond。
    """
    game = web_game
    # 无开夜时 wait_in_flight 早退；本钉只证 pending-write ownership 接缝。
    assert game._mark_pending_write()
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    release = threading.Event()

    def trail_worker() -> None:
        assert release.wait(2.0), "await must block until trail ends"
        order.append("trail_end")
        game._complete_pending_write()

    t = threading.Thread(target=trail_worker, name="trail-pending-r9", daemon=True)
    t.start()

    def release_soon() -> None:
        time.sleep(0.05)
        order.append("release")
        release.set()

    threading.Thread(target=release_soon, name="release-trail-r9", daemon=True).start()

    started = time.perf_counter()
    web_app._await_audience_inflight_clear(game)
    elapsed = time.perf_counter() - started
    t.join(timeout=2.0)
    assert not t.is_alive()

    assert order == ["release", "trail_end"], order
    assert int(getattr(game, "_pending_writes_count", 0) or 0) == 0
    assert elapsed >= 0.04, f"await returned too early ({elapsed:.4f}s); did not wait trail"


def test_settlement_entry_gate_free_close_after_worker_end(web_game, monkeypatch):
    """#1353 fold-in r9：受理样板 gate-free close 只在整轮 worker 终态后进入。"""
    game = web_game
    assert game._mark_pending_write()

    order: list[str] = []
    release = threading.Event()

    def trail_worker() -> None:
        assert release.wait(2.0)
        order.append("trail_end")
        game._complete_pending_write()

    t = threading.Thread(target=trail_worker, name="trail-entry-r9", daemon=True)
    t.start()

    def release_soon() -> None:
        time.sleep(0.05)
        release.set()

    threading.Thread(target=release_soon, daemon=True).start()

    def track_auto_close(_g, **_k):
        # close 入缝时尾随必须已放 ownership——否则即并发窗。
        assert int(getattr(game, "_pending_writes_count", 0) or 0) == 0
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
        order.append("body")

    t.join(timeout=2.0)
    assert not t.is_alive()
    assert order == ["trail_end", "auto_close", "body"], order


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_cli_pending_one_op_closed_loop_turn_or_exhaust(game, tmp_path, monkeypatch):
    """#1353 fold-in r9：真实 DB/GameSession + 唯一 _write_gate 闭环钉（替假半钉）。

    A) 尾随失败留 pending → 一次 skip/advance 自动清零且 turn == before+1
    B) 统一重试耗尽 → 玩家只见失败单源、turn 不进；清源后可重按推进
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)

    def _mk_session() -> GameSession:
        sess = object.__new__(GameSession)
        sess.db = db
        sess.state = state
        sess.content = content
        sess.registry = None
        sess.llm_config = object()
        sess._scene_registry = None
        sess._beat_generator = None
        sess.agno_db = None
        sess.last_decree = ""
        sess.last_report = ""
        sess._decree_draft_fingerprint = ()
        sess.deaths_this_turn = []
        sess.debuts_this_turn = []
        sess.auto_save = lambda *a, **k: None  # type: ignore[method-assign]
        # CLI 唯一闸：与 resolve/advance 收夜 drain 同流
        term._cli_write_gate(sess)
        return sess

    # ── B) 耗尽：真欠账 + Boom → 失败单源、turn 不进、可重按 ─────────────
    nid_b, ctid_b, _ = _open_night_with_persisted_reply(
        db, state, minister, reply="耗尽轮回话。",
    )
    assert db.get_story_extract_status(ctid_b) != "done"
    turn_before_b = int(state.turn)
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _BoomAgent(),
    )
    sess_b = _mk_session()
    with pytest.raises(LLMUnavailable) as ei_b:
        sess_b.advance_without_decree()
    assert ei_b.value.code == "pending_extraction"
    assert CLI_RUNNER_PLAYER_MESSAGE in str(ei_b.value)
    assert int(state.turn) == turn_before_b, "耗尽不得假推进 turn"
    assert int(_pending_api(db)["count"] or 0) >= 1
    assert an.get_night(db, nid_b)["status"] == an.NIGHT_STATUS_OPEN

    # ── A) 一次 skip：换成功抽取 + canned 结算 → 清零且 turn+1 ───────────
    # 复用同一开夜欠账（耗尽后仍 OPEN/pending）——重按真路径。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(
            '{"facts":[{"person_names":["'
            + minister
            + '"],"audibility":"殿上公开","body":"r9闭环补清","tags":[],'
            '"presence_effect":""}]}'
        ),
    )
    _canned_full_settlement(
        monkeypatch,
        narrative="本月邸报：欠账一次清后过月。",
    )

    turn_before_a = int(state.turn)
    assert turn_before_a == turn_before_b
    sess_a = _mk_session()
    result = sess_a.advance_without_decree()
    assert result is not None
    assert result.awaiting is False
    assert int(state.turn) == turn_before_a + 1
    assert db.get_story_extract_status(ctid_b) == "done"
    assert int(_pending_api(db)["count"] or 0) == 0
    assert an.get_night(db, nid_b)["status"] == an.NIGHT_STATUS_CLOSED
    # 闸仍是 session 唯一 _write_gate（禁第二锁名）
    assert getattr(sess_a, "_write_gate", None) is not None


def test_resolve_turn_write_gate_held_by_caller_no_reenter(game, tmp_path, monkeypatch):
    """#1353 fold-in r8：外层已持闸时 resolve 不得再传入同一把锁（禁自锁）。"""
    from ming_sim.session import GameSession, TurnPhase

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # 夜已关：auto_close 早退；本钉只证 held → write_gate 参数为 None
    state.turn_phase = TurnPhase.REVIEWING.value

    gate = threading.Lock()
    assert gate.acquire(blocking=False)
    seen: dict = {}

    def track_auto_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return None  # 无开夜

    monkeypatch.setattr(an, "auto_close_open_night", track_auto_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._beat_generator = None
    sess._write_gate = gate
    sess.agno_db = None
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []

    try:
        with pytest.raises(ValueError, match="草案"):
            sess.resolve_turn()
        assert seen.get("write_gate") is None, (
            f"held outer gate must not re-enter; got {seen.get('write_gate')!r}"
        )
    finally:
        gate.release()
