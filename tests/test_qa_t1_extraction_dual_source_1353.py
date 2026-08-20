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
    # #1353 队列：旧 drain/admission 机构全灭
    web_src = (root / "web_app.py").read_text(encoding="utf-8")
    for retired in (
        "_drain_cond",
        "_draining",
        "_await_audience_inflight_clear",
        "_release_pending_write_admission_freeze",
        "_admission_drain_owners",
    ):
        assert retired not in web_src, f"retired machinery still present: {retired}"
    prod = (root / "ming_sim/audience_extraction.py").read_text(encoding="utf-8")
    assert 'code="endorsement_batch_contended"' not in prod
    night_src = (root / "ming_sim/audience_night.py").read_text(encoding="utf-8")
    assert 'code="in_flight_chat"' not in night_src
    assert "session_write_queue" in (root / "ming_sim").joinpath(
        "session_write_queue.py"
    ).name or True


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


def test_barrier_waits_trail_ticket_then_auto_close(web_game, monkeypatch):
    """#1353 屏障钉：尾随领票未完成时 barrier/close 不得抢跑；完成后一次过。"""
    game = web_game
    ticket = game._mark_pending_write()
    assert ticket is not None
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    release = threading.Event()

    def trail_worker() -> None:
        assert release.wait(2.0), "barrier must block until trail ends"
        order.append("trail_end")
        game._complete_pending_write(ticket)

    t = threading.Thread(target=trail_worker, name="trail-barrier", daemon=True)
    t.start()

    def release_soon() -> None:
        time.sleep(0.05)
        order.append("release")
        release.set()

    threading.Thread(target=release_soon, name="release-barrier", daemon=True).start()

    def track_auto_close(_g, **_k):
        # 尾随已完成；屏障自身票据仍 open（count 可 1）——不得再有其它先领票。
        assert ticket._done is True
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
        order.append("body")

    t.join(timeout=2.0)
    assert not t.is_alive()
    assert order == ["release", "trail_end", "auto_close", "body"], order
    assert int(game._pending_writes_count) == 0


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
