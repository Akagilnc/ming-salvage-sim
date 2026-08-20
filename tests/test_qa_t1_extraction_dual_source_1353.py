"""QA P0 #1353：欠账并入过月 + 单写者票据队列 + 删除面。

钉：
1. 竞态：owner 在跑时发起 close → 一次过（不 409、不假 pending）
2. 真欠账耗尽 → 失败单源（LLMUnavailable/通传未达）；诊断 pending API 非空
3. drain 失败清理不得藏挡夜 turn；write_gate=None 卫兵不被架空
4. 清理窗部分 heal → 失败单源 + pending 仅鲜集；全愈 → close_retry（无递归重入）
5. 口令收夜穿 runtime write_gate
6. 背书空文本独立 fail-closed + 409 重试形态（非欠账类）
7. 删除面：无 _healed_drain_retry / 玩家补写 CTA / 旧 drain 机构
8. fold-in r5：drain/catch_up 不推玩家可见补写 stage；签名无 on_event
9. 队列屏障：尾随票据未清时 barrier/close 等待；清后一次过
10. 闭环钉改走 play_turn 真 CLI 面——pending→一次 skip→turn+1 / 耗尽留回合
11. 撤回钉：cancel_key 空放行（见 test_session_write_queue_1353）
"""

from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import ming_sim.audience_extraction as ae
import ming_sim.cli.terminal as term
import ming_sim.issues as issues_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.exceptions import ExitGame, LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.session import GameSession, TurnPhase
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
    """#1353 竞态钉：尾随持票在跑时经屏障 close → 等票清后一次过（不 409 不假 pending）。"""
    from ming_sim.session_write_queue import SessionWriteQueue

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    q = SessionWriteQueue()
    gate = q.write_gate
    started = threading.Event()
    release_llm = threading.Event()
    owner_result: dict = {}
    ticket = q.claim(key=("turn", int(ctid)))
    assert ticket is not None

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
        try:
            write_gate = q.ticketed_gate(ticket)
            owner_result["out"] = ae.run_extraction_for_turn(
                db=db,
                minister_name=minister,
                reply="臣愿肩起此事。",
                chat_turn_id=ctid,
                night_id=nid,
                source_night_seq=seq,
                llm_config=object(),
                write_gate=write_gate,
                extractor_agent=_SlowAgent(),
                allow_closing=False,
            )
        finally:
            q.complete(ticket)

    owner_thread = threading.Thread(target=owner_worker, name="extract-owner-1353")
    owner_thread.start()
    assert started.wait(2), "owner must enter LLM before close"

    close_result: dict = {}

    def close_worker():
        close_result["r"] = q.barrier(
            lambda: an.close_night(
                db, state, night_id=nid, llm_config=object(), write_gate=gate,
            ),
                    )

    # 先起 close（阻塞在 barrier），再放 LLM——证明屏障等票而非旁路抢跑
    ct = threading.Thread(target=close_worker, name="close-barrier-1353", daemon=True)
    ct.start()
    # owner 仍持票时 close 不得完成
    assert ct.is_alive()
    assert "r" not in close_result
    release_llm.set()
    owner_thread.join(timeout=5)
    ct.join(timeout=5)
    assert not owner_thread.is_alive() and not ct.is_alive()

    result = close_result.get("r") or {}
    assert result.get("closed") is True, result
    assert owner_result.get("out", {}).get("status") == "done"
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
    """删除面 grep 钉：自愈 hint + 玩家补写 CTA/CLI 命令/旧 admission 舞步零残留。"""
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
    # #1353 队列：旧 drain/admission/旁路 wait 机构全灭
    web_src = (root / "web_app.py").read_text(encoding="utf-8")
    for retired in (
        "_drain_cond",
        "_draining",
        "_await_audience_inflight_clear",
        "_release_pending_write_admission_freeze",
        "_admission_drain_owners",
        "def _wait_open_night_chat_inflight",
    ):
        assert retired not in web_src, f"retired machinery still present: {retired}"
    prod = (root / "ming_sim/audience_extraction.py").read_text(encoding="utf-8")
    assert 'code="endorsement_batch_contended"' not in prod
    for retired_ae in (
        "join_pending_turn_extractions",
        "has_inflight_turn_extractions",
        "_join_single_flight",
        "DEFAULT_EXTRACT_JOIN_S",
    ):
        assert retired_ae not in prod, f"retired extraction join residue: {retired_ae}"
    night_src = (root / "ming_sim/audience_night.py").read_text(encoding="utf-8")
    # K10a：wait_in_flight 不按 elapsed 伪造失败；错误包 kind 仍可被 provider 终态路径使用
    assert "del timeout_s" in night_src or "timeout_s" in night_src
    swq = (root / "ming_sim/session_write_queue.py").read_text(encoding="utf-8")
    assert "TicketBarrierTimeout" not in swq
    assert "DEFAULT_TICKET_WAIT_S" not in swq
    # 无票裸回落已删
    assert "return self._runtime_write_gate()" not in (root / "web_app.py").read_text(encoding="utf-8")
    assert "TicketedWriteGate" in (root / "ming_sim/session_write_queue.py").read_text(
        encoding="utf-8"
    )
    # 生产写路径必须调用票据执行 seam（非仅单测）
    assert "ticketed_gate" in web_src or "_ticketed_write_gate" in web_src
    assert "TicketedWriteGate" in (root / "ming_sim/cli/terminal.py").read_text(
        encoding="utf-8"
    ) or "ticketed_gate" in (root / "ming_sim/cli/terminal.py").read_text(
        encoding="utf-8"
    )


def test_endorsement_single_flight_owner_binds_once(game, tmp_path, monkeypatch):
    """#1353：背书 single-flight 去重仍在；owner 绑定后二次调用幂等 already。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣愿作保。")
    assert ae.run_extraction_for_turn(
        db=db,
        minister_name=minister,
        reply="臣愿作保。",
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
            "minister_reply": "臣愿作保。",
            "ordinary_facts": [],
        }],
    }
    gate = threading.Lock()
    r1 = ae.run_endorsement_batch_for_night(
        db=db, night_id=nid, llm_config=object(), write_gate=gate,
        extractor_agent=SimpleNamespace(run=lambda _m: SimpleNamespace(content='{"endorsements":[]}')),
    )
    assert r1["status"] in {"done", "skipped"}
    r2 = ae.run_endorsement_batch_for_night(
        db=db, night_id=nid, llm_config=object(), write_gate=gate,
        extractor_agent=_BoomAgent(),
    )
    assert r2.get("already") is True or r2["status"] in {"done", "skipped"}
    assert ae._is_endorsement_bound(db, nid)


def test_drain_catch_up_silent_no_on_event_surface(game, tmp_path, monkeypatch):
    """#1353 fold-in r5：drain/catch_up 静默补跑——签名无 on_event，落账仍成功。"""
    import inspect

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)
    assert "on_event" not in inspect.signature(ae.drain_pending_before_close).parameters
    assert "on_event" not in inspect.signature(ae.catch_up_pending_extractions).parameters
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
    import pathlib

    prod = pathlib.Path(ae.__file__).read_text(encoding="utf-8")
    assert "补写召对账本" not in prod
    assert "过月时自动补跑" not in prod


def test_empty_startup_catchup_claims_zero_tickets(web_game):
    """#1353 r7：无待补时 startup catch-up 不领票——禁 residual pending 竞态。"""
    game = web_game
    q = game._runtime_write_queue()
    # fresh WebGame 无未抽回话；init 时 spawn 必须早退，队列空。
    assert q.inflight_count() == 0
    assert int(game._pending_writes_count) == 0
    # 显式再调仍不领票。
    game._spawn_startup_extraction_catch_up()
    assert q.inflight_count() == 0


def test_barrier_waits_trail_ticket_then_auto_close(web_game, monkeypatch):
    """#1353 生产接缝屏障钉：尾随领票未完成时 entry 不得抢跑；完成后一次过。"""
    game = web_game
    # 空库 startup 不得占票；本钉只见自领 1 票（全量 xdist 顺序依赖根因）。
    assert int(game._pending_writes_count) == 0
    ticket = game._mark_pending_write(key=("turn", 1))
    assert ticket is not None
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    trail_holding = threading.Event()
    release = threading.Event()
    entry_done = threading.Event()

    def trail_worker() -> None:
        trail_holding.set()
        assert release.wait(2.0), "barrier must block until trail ends"
        order.append("trail_end")
        game._complete_pending_write(ticket)

    t = threading.Thread(target=trail_worker, name="trail-barrier", daemon=True)
    t.start()
    assert trail_holding.wait(2.0)

    def track_auto_close(_g, **_k):
        assert ticket._done is True
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, name="settlement-entry", daemon=True)
    et.start()
    # 确定性：trail 未放行前 entry 不得完成（事件握手，不靠 sleep 判胜负）
    assert not entry_done.is_set()
    assert "auto_close" not in order
    assert "body" not in order

    order.append("release")
    release.set()
    assert entry_done.wait(2.0)
    t.join(timeout=2.0)
    et.join(timeout=2.0)
    assert not t.is_alive() and not et.is_alive()
    assert order == ["release", "trail_end", "auto_close", "body"], order
    assert int(game._pending_writes_count) == 0


def test_production_seam_cancel_blocks_trail_write(web_game):
    """生产接缝撤回钉：暂停腿 → cancel_key → 放行，TicketedWriteGate 零写。"""
    from ming_sim.session_write_queue import TicketCancelled

    game = web_game
    q = game._runtime_write_queue()
    ticket = game._mark_pending_write(key=("turn", 4242))
    assert ticket is not None

    entered = threading.Event()
    release = threading.Event()
    wrote = {"n": 0}
    outcome: dict = {}

    def paused_trail() -> None:
        entered.set()
        assert release.wait(2.0)
        gate = game._ticketed_write_gate(ticket)
        try:
            with gate:
                wrote["n"] += 1
            outcome["ok"] = True
        except TicketCancelled as exc:
            outcome["cancelled"] = type(exc).__name__
        finally:
            game._complete_pending_write(ticket)

    th = threading.Thread(target=paused_trail, daemon=True)
    th.start()
    assert entered.wait(2.0)
    n = q.cancel_key(("turn", 4242))
    assert n == 1
    release.set()
    th.join(timeout=2.0)
    assert not th.is_alive()
    assert wrote["n"] == 0
    assert outcome.get("cancelled") == "TicketCancelled"
    assert "ok" not in outcome


def test_production_seam_post_barrier_ticket_ordered(web_game, monkeypatch):
    """生产接缝：屏障已领后再领票，后票写不得越过屏障（经 ticketed gate）。"""
    game = web_game
    q = game._runtime_write_queue()
    order: list[str] = []
    barrier_in = threading.Event()
    release_barrier = threading.Event()
    late_claimed = threading.Event()
    late_done = threading.Event()

    def track_auto_close(_g, **_k):
        barrier_in.set()
        assert late_claimed.wait(2.0)
        order.append("barrier")
        assert release_barrier.wait(2.0)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    entry_done = threading.Event()

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, daemon=True)
    et.start()
    assert barrier_in.wait(2.0)

    late = game._mark_pending_write(key=("turn", 77))
    assert late is not None
    late_claimed.set()

    def late_write() -> None:
        gate = game._ticketed_write_gate(late)
        with gate:
            order.append("late")
        game._complete_pending_write(late)
        late_done.set()

    lt = threading.Thread(target=late_write, daemon=True)
    lt.start()
    assert "late" not in order
    assert not late_done.is_set()

    release_barrier.set()
    assert entry_done.wait(2.0)
    assert late_done.wait(2.0)
    et.join(timeout=2.0)
    lt.join(timeout=2.0)
    # barrier 写（auto_close）先于后票；body 在 barrier 返回后
    assert order.index("barrier") < order.index("late")
    assert order.index("barrier") < order.index("body")


def test_wait_in_flight_releases_on_worker_terminal(game, tmp_path, monkeypatch):
    """K10a：wait_in_flight 只依工人终态放行，不按 elapsed 伪造 409。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, _seq = _open_night_with_persisted_reply(db, state, minister)
    db.conn.execute(
        "UPDATE chat_turns SET status='generating' WHERE id=?", (ctid,)
    )
    db.conn.commit()
    monkeypatch.setattr(an, "DEFAULT_IN_FLIGHT_POLL_S", 0.01)

    # 确定性握手：主线程入轮询 → worker 发终态 → 主线程因终态返回
    # （禁 sleep 毫秒窗；禁把 SUT 包进 waiter 线程 try/finally 吞异常假绿）
    waiter_polling = threading.Event()
    worker_published = threading.Event()
    real_list = an.list_in_flight_chat_turns

    def _list_tracking(db_arg, night_id_arg):
        rows = real_list(db_arg, night_id_arg)
        waiter_polling.set()
        return rows

    monkeypatch.setattr(an, "list_in_flight_chat_turns", _list_tracking)

    def _worker_terminal() -> None:
        assert waiter_polling.wait(5.0), "waiter must enter poll before terminal"
        db.conn.execute(
            "UPDATE chat_turns SET status='active' WHERE id=?", (ctid,)
        )
        db.conn.commit()
        worker_published.set()

    wt = threading.Thread(
        target=_worker_terminal, name="worker-terminal-1353", daemon=True,
    )
    wt.start()
    # 主测试线程直调 SUT；pytest 原生捕获被测异常（禁 waiter 包装线程）
    # 不传短 timeout 墙钟；工人终态后必须返回（禁 elapsed 伪失败）
    an.wait_in_flight_clear(db, nid)
    assert worker_published.wait(5.0), "worker must publish terminal"
    wt.join(timeout=2.0)
    assert not wt.is_alive()
    assert an.list_in_flight_chat_turns(db, nid) == []


def test_seal_claim_rejects_three_trail_legs_zero_write(web_game, monkeypatch):
    """生产钉：seal 后三腿 claim 拒绝 → 零 LLM、零写。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    calls = {"hl": 0, "mind": 0, "ext": 0, "catch": 0}

    monkeypatch.setattr(
        web_app, "run_highlight_judge",
        lambda **_k: calls.__setitem__("hl", calls["hl"] + 1) or ["x"],
    )

    def boom_mind(**_k):
        calls["mind"] += 1
        return {"id": 1}

    monkeypatch.setattr(web_app, "run_mindreading_for_turn", boom_mind)
    monkeypatch.setattr(
        web_app, "trail_extraction_after_reply",
        lambda **_k: calls.__setitem__("ext", calls["ext"] + 1) or {"status": "done"},
    )
    monkeypatch.setattr(
        web_app, "catch_up_pending_extractions",
        lambda **_k: calls.__setitem__("catch", calls["catch"] + 1),
    )

    assert game._spawn_pending_write_thread(
        game._trail_mindreading_after_reply, ("m", "r", 1), "t",
        ticket_key=("turn", 1),
    ) is None
    assert game._spawn_extraction_trail("m", "r", 1) is None
    assert game._trail_highlight_judge_after_reply(
        "回话", message_id=1, chat_turn_id=1,
    ) == []
    assert game._trail_mindreading_after_reply("m", "r", 1) is None
    assert game._trail_extraction_after_reply("m", "r", 1) is None
    game._run_startup_extraction_catch_up(pending_ticket=None)
    assert calls == {"hl": 0, "mind": 0, "ext": 0, "catch": 0}
    assert q.inflight_count() == 0
    q.unseal()


def test_startup_catchup_uses_ticketed_gate_not_bare(web_game, monkeypatch):
    """startup catch-up 必须经 ticketed gate，不得传裸 write_gate。"""
    game = web_game
    seen = {}

    def fake_catch_up(*, write_gate=None, **_k):
        seen["gate_type"] = type(write_gate).__name__
        seen["is_ticketed"] = type(write_gate).__name__ == "TicketedWriteGate"

    monkeypatch.setattr(web_app, "catch_up_pending_extractions", fake_catch_up)
    ticket = game._mark_pending_write(key=("startup",))
    assert ticket is not None
    game._run_startup_extraction_catch_up(pending_ticket=ticket)
    assert seen.get("is_ticketed") is True
    assert ticket._done is True


def test_ticketed_write_gate_rejects_none(web_game):
    """无票不得回落裸 runtime write_gate。"""
    game = web_game
    with pytest.raises(RuntimeError, match="live WriteTicket"):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]


def test_catch_up_entry_list_under_gate_ticket_cancelled_empty():
    """#1353 r10 / 68Xp：catch-up 入口 list_unextracted 持闸；TicketCancelled → 空结果不抛。"""
    from ming_sim.audience_extraction import catch_up_pending_extractions
    from ming_sim.session_write_queue import SessionWriteQueue, TicketCancelled

    class _DB:
        def list_unextracted_replies(self, night_id=None):
            raise AssertionError("must not bare-read outside gate")

    q = SessionWriteQueue()
    ticket = q.claim(key=("startup",))
    assert ticket is not None
    q.cancel(ticket)
    gate = q.ticketed_gate(ticket)

    # 取消票进 gate → TicketCancelled；catch_up 必须吞成空结果
    out = catch_up_pending_extractions(
        db=_DB(), llm_config=object(), write_gate=gate,
    )
    assert out == {"extracted": 0, "pending": 0, "scanned": 0}


def test_stream_close_pending_extraction_emits_error_not_hang(web_game, monkeypatch):
    """#1353 r10 / 66nX：流式收夜欠账耗尽 LLMUnavailable 必须终态化（error），禁永阻。"""
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    game = web_game
    minister = next(iter(game.content.characters))
    # prologue 最小：持久大臣路径需要 chat turn；用 session stub 简化
    events: list[dict] = []

    class _Agent:
        def run(self, *_a, **_k):
            # 最小流：一个 content + RunOutput
            yield SimpleNamespace(event="RunContent", content="臣已知晓。")
            yield SimpleNamespace(
                event="RunCompletedEvent",
                content="臣已知晓。",
                tools=[],
                messages=[],
                status="COMPLETED",
            )

    game.session.registry.get = lambda _ch: _Agent()
    game.session._character = lambda name: SimpleNamespace(name=name)
    game.session.join_chat_turn_scene = lambda *_a, **_k: []
    game.session.persist_chat_turn_scene = lambda *_a, **_k: None
    game.session.abandon_chat_turn_scene = lambda *_a, **_k: None
    # 避免真实开夜/落库依赖：非持久路径（临时角色）或 stub 持久
    monkeypatch.setattr(game, "_persistent_chat_minister", lambda _n: False)
    monkeypatch.setattr(
        game, "_chat_stream_interpret_tools",
        lambda *a, **k: {
            "answer": "臣已知晓。",
            "court_action": "close_night",
            "next_minister": "",
            "proposed": None,
            "appointed": "",
            "registered": "",
            "displaced": "",
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
            "directive_ambiguous": None,
        },
    )
    monkeypatch.setattr(
        game, "_chat_payload",
        lambda *a, **k: {"answer": "臣已知晓。", "minister_message_id": 0},
    )

    def boom_close(_action="", *, write_gate=None):
        raise LLMUnavailable(
            CLI_RUNNER_PLAYER_MESSAGE,
            code="pending_extraction",
            provider_message="欠账耗尽",
        )

    game.session.close_night_after_chat_if_needed = boom_close

    gen = game.chat_stream(minister, "边饷如何？")
    # 有界消费：若未终态化，下一事件永不到 → 测试挂死；用线程+超时护栏
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in gen:
                events.append(item)
                if item.get("type") in {"end", "error"}:
                    break
            box["ok"] = True
        except Exception as exc:
            box["exc"] = exc
        finally:
            done.set()

    th = threading.Thread(target=consume, daemon=True)
    th.start()
    assert done.wait(5.0), "stream must terminalize (error/end); hung on ev_queue"
    th.join(timeout=1.0)
    assert box.get("ok") is True, box
    types = [e.get("type") for e in events]
    assert "error" in types, events
    assert types[-1] in {"error", "end"}
    # done 可先于 close 失败；error 必须到达
    err = next(e for e in events if e.get("type") == "error")
    assert "detail" in err or "message" in err


def test_chat_stream_prologue_uses_ticketed_not_bare_runtime(web_game, monkeypatch):
    """#1353 r10 / 66nR：流式 prologue 经 ticketed gate，不得裸 runtime write_gate 越屏障。"""
    from pathlib import Path

    # 源码钉：chat_stream 领票后绑定 _ticketed_write_gate，禁 prologue 直绑 _runtime_write_gate
    src = Path(web_app.__file__).read_text(encoding="utf-8")
    # 定位 chat_stream 函数体（下一 def 前）
    start = src.index("def chat_stream(")
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    assert "_ticketed_write_gate(pending_ticket)" in body
    assert "has_open_barrier()" in body
    # 禁 prologue 把业务闸直接绑成裸 runtime（bare_write_gate= 收夜收口除外）
    assert re.search(
        r"^\s*write_gate\s*=\s*self\._runtime_write_gate\(\)",
        body,
        flags=re.M,
    ) is None

    game = web_game
    minister = next(iter(game.content.characters))
    seen = {"ticketed_acquire": 0}
    real_tw = game._ticketed_write_gate

    def wrap_ticketed(ticket):
        gate = real_tw(ticket)
        real_acq = gate.acquire

        def acq(*a, **k):
            seen["ticketed_acquire"] += 1
            return real_acq(*a, **k)

        gate.acquire = acq  # type: ignore[method-assign]
        return gate

    monkeypatch.setattr(game, "_ticketed_write_gate", wrap_ticketed)

    class _Boom:
        def run(self, *_a, **_k):
            raise LLMUnavailable("boom")
            yield  # pragma: no cover

    game.session.registry.get = lambda _ch: _Boom()
    monkeypatch.setattr(game, "_persistent_chat_minister", lambda _n: False)

    events = list(game.chat_stream(minister, "边饷如何？"))
    assert seen["ticketed_acquire"] >= 1
    assert any(e.get("type") == "error" for e in events)


def test_seal_rejects_new_claim_after_lifecycle(web_game):
    """生命周期 seal 后新领票拒入（旧 _draining 语义）。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    assert game._mark_pending_write() is None
    q.unseal()
    t = game._mark_pending_write()
    assert t is not None
    game._complete_pending_write(t)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_cli_pending_one_op_closed_loop_turn_or_exhaust(
    game, tmp_path, monkeypatch, capsys,
):
    """#1353 fold-in r10：闭环钉改走 play_turn 真 CLI 面（禁直调 advance_without_decree）。

    A) 尾随失败留 pending → 一次 play_turn skip 自动清零且 turn == before+1
    B) 统一重试耗尽 → 玩家只见失败单源、turn 不进、play_turn 留回合可重按
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    monkeypatch.setattr(term, "_print_header", lambda _s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda _db: None)

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
        sess.previous_summary = ""
        sess.auto_save = lambda *a, **k: None  # type: ignore[method-assign]
        # play_turn 面：非 SUMMONING → 直入 review；begin/end 不落盘
        sess.begin_turn = (  # type: ignore[method-assign]
            lambda: SimpleNamespace(deaths_this_turn=[])
        )
        sess.current_phase = lambda: TurnPhase.REVIEWING  # type: ignore[method-assign]
        sess.end_turn = lambda: None  # type: ignore[method-assign]
        # CLI 唯一闸：与 resolve/advance 收夜 drain 同流
        term._cli_write_gate(sess)
        return sess

    # ── B) 耗尽：真欠账 + Boom → play_turn skip 失败单源、turn 不进、留回合 ─
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
    actions_b = iter(["skip"])

    def review_b(_s):
        try:
            return next(actions_b)
        except StopIteration:
            # 耗尽后 play_turn 须 continue 留在本回合——二次 review 用 ExitGame 收束测程
            raise ExitGame()

    monkeypatch.setattr(term, "review_directives", review_b)
    with pytest.raises(ExitGame):
        term.play_turn(sess_b)
    out_b = capsys.readouterr().out
    assert CLI_RUNNER_PLAYER_MESSAGE in out_b
    assert int(state.turn) == turn_before_b, "耗尽不得假推进 turn"
    assert int(_pending_api(db)["count"] or 0) >= 1
    assert an.get_night(db, nid_b)["status"] == an.NIGHT_STATUS_OPEN

    # ── A) 一次 play_turn skip：换成功抽取 + canned 结算 → 清零且 turn+1 ──
    # 复用同一开夜欠账（耗尽后仍 OPEN/pending）——重按真 CLI 路径。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(
            '{"facts":[{"person_names":["'
            + minister
            + '"],"audibility":"殿上公开","body":"r10闭环补清","tags":[],'
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
    monkeypatch.setattr(term, "review_directives", lambda _s: "skip")
    term.play_turn(sess_a)
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


def test_close_night_shared_conn_reads_short_hold_gate_source():
    """#1353 r7：close_night 共享 conn 读入闸——禁闸外 get_open/get_night/wait 裸读。"""
    import inspect
    from pathlib import Path

    import ming_sim.audience_night as an

    src = Path(an.__file__).read_text(encoding="utf-8")
    # wait_in_flight_clear 必接受 write_gate，且 sleep 在 with 外
    sig = inspect.signature(an.wait_in_flight_clear)
    assert "write_gate" in sig.parameters
    # close_night 调用 wait 时传 write_gate
    assert "wait_in_flight_clear(" in src
    assert "write_gate=write_gate" in src
    # 入场 get_open_night / get_night 在 with gate 内（源码形态）
    close_src = src.split("def close_night(", 1)[1].split("\ndef auto_close_open_night", 1)[0]
    assert "with gate:" in close_src
    # 禁「gate 赋值前」裸 get_open_night
    before_gate = close_src.split("gate = _gate_cm", 1)[0]
    assert "get_open_night" not in before_gate
    assert "get_night(" not in before_gate

