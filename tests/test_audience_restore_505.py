"""#505 [S4] 续夜 restore：重开回到最后一条持久化对话轮续夜（ADR 0036）。

一条贯穿真实入口→DB 末态的 tracer：用生产 seam（open_night / attach_chat_turn_to_night /
append_chat_message）造出「回话生成半途被 kill」的真实崩溃态（generating 轮、问话已落、
回话未落），再用**重开真路径**（同库新建 GameDB + reconcile_interrupted_chat_turns）断言：

- AC1/AC4：账本逐条一致、恢复路径未删任何账（重开前后 list_ledger 相等）。
- AC2：纯奏对零账目段寸步不丢（完成轮无账目，重开后逐字稿仍在）。
- AC3：半途回话丢弃（问话保留、不删）、最后一句带重试；重试后记录无重复句。

负向：reconcile 不动完成的活跃轮（不误标 interrupted）；无待重试轮时 retry 响亮拒绝；
reconcile 保留问话消息行（区别于 fail_chat_turn 的删问话善后）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import ming_sim.issues as issues_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.audience_night import attach_chat_turn_to_night
from ming_sim.db import GameDB
from ming_sim.session import ChatTurnResult
from web_app import FRONT_HALF_DONE_PHASES


# ── 真实开局 / 重开 helpers ──────────────────────────────────────────


def _active_minister(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _open_db(path, content, *, first: bool):
    db = GameDB(path, content)
    if first:
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)
    else:
        state = db.load_state()
    return db, state


@pytest.fixture
def restore_env(content, tmp_path):
    # 用例自管句柄开合（重开=同库新建 GameDB）；tmp_path 由 pytest 清理，teardown 不再 close
    # （避免对已在用例内 close 的句柄二次 close）。
    path = str(tmp_path / "restore.db")
    db, state = _open_db(path, content, first=True)
    yield SimpleNamespace(path=path, db=db, state=state, content=content)


def _start_generating_turn(db, state, minister, question):
    """生产 seam 造在飞 generating 轮：问话已落库并链接，回话未落（= 生成半途被 kill）。"""
    _night_id, ct = attach_chat_turn_to_night(
        db, state, minister, agno_session_id="sess", agno_runs_before=0,
    )
    mid = db.append_chat_message(minister, state.turn, "user", question)
    db.update_chat_turn_messages(ct, user_message_id=mid)
    return ct


def _land_full_turn(db, state, minister, question, answer):
    """生产 seam 造完成轮：问话 + 回话都落库、链接（generating→active）。"""
    _night_id, ct = attach_chat_turn_to_night(
        db, state, minister, agno_session_id="sess", agno_runs_before=0,
    )
    uid = db.append_chat_message(minister, state.turn, "user", question)
    db.update_chat_turn_messages(ct, user_message_id=uid)
    mid = db.append_chat_message(minister, state.turn, "minister", answer)
    db.update_chat_turn_messages(ct, minister_message_id=mid)
    db.conn.execute("UPDATE chat_turns SET extract_status='done' WHERE id=?", (ct,))
    db.conn.commit()
    return ct


def _reopen(path, content):
    return _open_db(path, content, first=False)


# ── AC1/AC4 账本逐条一致、恢复路径未删任何账 ──────────────────────────


def test_reopen_reconcile_preserves_ledger_exactly(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    an.summon_enter(db, night["id"], minister, method=an.METHOD_XUANRU)
    # 回话生成半途 kill：问话已落、回话未落。
    _start_generating_turn(db, state, minister, "剿抚孰先？")
    ledger_before = an.list_ledger(db, night["id"])
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        db2.reconcile_interrupted_chat_turns()
        ledger_after = an.list_ledger(db2, night["id"])
        # 恢复路径未删任何账，且逐条一致（AC1/AC4）。
        assert ledger_after == ledger_before
    finally:
        db2.close()
    # keep db handle count sane for fixture teardown


# ── AC3 半途回话丢弃 + 问话保留、不阻塞、可重试 ──────────────────────


def test_reopen_reconcile_unblocks_and_keeps_question(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="文华殿", time_of_day="午时")
    ct = _start_generating_turn(db, state, minister, "杨卿何以教朕？")
    # kill 前：该轮为在飞、大臣被判「仍在进行」。
    assert an.list_in_flight_chat_turns(db, night["id"])
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        interrupted = db2.reconcile_interrupted_chat_turns()
        # 该轮被标为可重试的 interrupted（不再在飞、不阻塞续问/收夜）。
        assert an.list_in_flight_chat_turns(db2, night["id"]) == []
        assert any(int(r["chat_turn_id"]) == ct for r in interrupted)
        # 问话原句保留（不删）——恢复路径永不删记录。
        proj = db2.build_chat_projection(minister)
        assert [m["content"] for m in proj if m["role"] == "user"] == ["杨卿何以教朕？"]
        # 待重试面板取数：带问话原文。
        retries = db2.get_interrupted_reply_retries(minister)
        assert [r["question"] for r in retries] == ["杨卿何以教朕？"]
    finally:
        db2.close()


def test_reconcile_leaves_completed_turn_untouched(restore_env):
    """负向：完成的活跃轮不得被 reconcile 误标 interrupted。"""
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    ct = _land_full_turn(db, state, minister, "问", "臣对。")
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        interrupted = db2.reconcile_interrupted_chat_turns()
        assert all(int(r["chat_turn_id"]) != ct for r in interrupted)
        status = db2.conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (ct,)
        ).fetchone()["status"]
        assert status == "active"
    finally:
        db2.close()


def test_reconcile_does_not_delete_question_row(restore_env):
    """负向对照：reconcile 保留问话消息行（区别于 fail_chat_turn 的删问话善后）。"""
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    _start_generating_turn(db, state, minister, "此问不可蒸发")
    before = db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE role='user'"
    ).fetchone()["c"]
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        db2.reconcile_interrupted_chat_turns()
        after = db2.conn.execute(
            "SELECT COUNT(*) c FROM chat_messages WHERE role='user'"
        ).fetchone()["c"]
        assert after == before  # 一条问话都不删
    finally:
        db2.close()


# ── AC2 纯奏对零账目段寸步不丢 ───────────────────────────────────────


def test_pure_audience_zero_ledger_turn_survives_reopen(restore_env):
    """完成轮不产任何账目（纯奏对），重开后逐字稿仍在——锚点=最后持久化对话轮，非最后账。"""
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    ledger_marker = len(an.list_ledger(db, night["id"]))
    _land_full_turn(db, state, minister, "四轮问对之一", "臣愚见如此。")
    # 纯奏对：该轮不产任何叙事抽取账（source_chat_turn_id>0 的账为 0 条）——锚点非「最后一笔账」。
    _ = ledger_marker
    extracted = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE source_chat_turn_id>0"
    ).fetchone()["c"]
    assert extracted == 0
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        db2.reconcile_interrupted_chat_turns()
        proj = db2.build_chat_projection(minister)
        assert "四轮问对之一" in [m["content"] for m in proj if m["role"] == "user"]
        assert "臣愚见如此。" in [m["content"] for m in proj if m["role"] == "minister"]
    finally:
        db2.close()


# ── AC3 重试重新生成回话、记录无重复句 ───────────────────────────────


class _RetrySession:
    """最小真路径替身：chat 复用被指定 chat_turn，落回话由 WebGame._chat_payload 走真实 db。"""

    temporary_characters: set = set()

    def __init__(self, db, state, minister):
        self.db = db
        self.state = state
        self._minister = minister
        self.content = SimpleNamespace(characters={minister: SimpleNamespace(name=minister)})

    def _character(self, name):
        return self.content.characters[name]

    def pending_count(self):
        return 0

    def chat(self, minister_name, message, *, chat_turn_id=0):
        # 关键：retry 复用既有 chat_turn，绝不再落问话——只产回话。
        assert chat_turn_id != 0
        return ChatTurnResult(answer="臣重奏：剿为先。")

    # #542 scene lifecycle seams：retry 入口会 start/join/persist/abandon；替身 no-op。
    def start_chat_turn_scene(self, *_a, **_k):
        return None

    def start_chat_turn_exit_scene(self, *_a, **_k):
        return None

    def join_chat_turn_scene(self, *_a, **_k):
        return []

    def persist_chat_turn_scene(self, *_a, **_k):
        return None

    def abandon_chat_turn_scene(self, *_a, **_k):
        return None


def _retry_runtime(db, state, minister):
    rt = object.__new__(web_app.WebGame)
    # WebGame.db/state 均为只读 property（读 session.db / session.state）——经 session 供给。
    rt.session = _RetrySession(db, state, minister)
    rt.chat_history = {minister: []}
    rt._write_gate = __import__("threading").Lock()
    rt._runtime_write_gate = lambda: rt._write_gate
    rt.directive_rows = lambda: []
    rt.directive_payload = lambda row: row
    rt.suggestions_for = lambda character: []
    rt.can_undo_last_chat = lambda name: False
    rt.pending_action_failures_for = lambda name: []
    rt._audience_turn_in_flight = lambda name: False
    # 整轮 pending 由 retry 本体持有；尾随（读心/抽取）在本单元测试外——不起后台线程。
    from ming_sim.session_write_queue import SessionWriteQueue
    rt._write_queue = SessionWriteQueue()
    rt._write_gate = rt._write_queue.write_gate
    rt._runtime_write_queue = lambda: rt._write_queue  # type: ignore
    rt._mark_pending_write = lambda key=None: rt._write_queue.claim(key=key or ("pending",))  # type: ignore
    rt._complete_pending_write = lambda ticket=None: rt._write_queue.complete(ticket)  # type: ignore
    rt._spawn_pending_write_thread = lambda *a, **k: False
    rt._spawn_extraction_trail = lambda *a, **k: None
    return rt


def test_retry_regenerates_reply_without_duplicate_question(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    ct = _start_generating_turn(db, state, minister, "剿抚孰先？")
    db.reconcile_interrupted_chat_turns()

    rt = _retry_runtime(db, state, minister)
    payload = rt.retry_interrupted_reply(minister)

    assert payload["answer"] == "臣重奏：剿为先。"
    # 记录无重复句：问话仍只一条，回话新落一条。
    users = db.conn.execute(
        "SELECT content FROM chat_messages WHERE role='user'"
    ).fetchall()
    assert [r["content"] for r in users] == ["剿抚孰先？"]
    replies = db.conn.execute(
        "SELECT content FROM chat_messages WHERE role='minister'"
    ).fetchall()
    assert [r["content"] for r in replies] == ["臣重奏：剿为先。"]
    # 轮完成：generating/interrupted → active，回话已链接。
    row = db.conn.execute(
        "SELECT status, minister_message_id FROM chat_turns WHERE id=?", (ct,)
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]
    # 重试后该轮不再挂在待重试面板。
    assert db.get_interrupted_reply_retries(minister) == []


def test_retry_without_interrupted_turn_is_rejected(restore_env):
    """负向：无待重试轮时重试响亮拒绝，不静默造轮。"""
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    rt = _retry_runtime(db, state, minister)
    with pytest.raises(HTTPException):
        rt.retry_interrupted_reply(minister)


# ── finding1：重试失败尾声——副作用回滚、问话保留、可再重试（与 chat 失败尾声同缝）────


class _FailingRetrySession(_RetrySession):
    """session.chat 在返回前 durable 落副作用（改 characters.loyalty）随后失败——
    测重试失败尾声：本次落下的副作用回滚、问话不删、翻回 interrupted 保持可再重试。"""

    def chat(self, minister_name, message, *, chat_turn_id=0):
        assert chat_turn_id != 0
        self.db.conn.execute(
            "UPDATE characters SET loyalty = loyalty + 40 WHERE name = ?", (self._minister,)
        )
        self.db.conn.commit()
        raise RuntimeError("重试 LLM 失败")


def test_failed_retry_rolls_back_side_effects_and_keeps_question(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    ct = _start_generating_turn(db, state, minister, "剿抚孰先？")
    db.reconcile_interrupted_chat_turns()
    loyalty0 = db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (minister,)
    ).fetchone()["loyalty"]

    rt = _retry_runtime(db, state, minister)
    rt.session = _FailingRetrySession(db, state, minister)
    with pytest.raises(RuntimeError):
        rt.retry_interrupted_reply(minister)

    # 本次重试落下的副作用回滚（loyalty 复原）——不留双 stage / 粘滞。
    assert db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (minister,)
    ).fetchone()["loyalty"] == loyalty0
    # 问话保留、无回话、翻回 interrupted 保持可再重试（恢复路径永不删账）。
    row = db.conn.execute(
        "SELECT status, minister_message_id FROM chat_turns WHERE id=?", (ct,)
    ).fetchone()
    assert row["status"] == "interrupted"
    assert not row["minister_message_id"]
    assert [r["question"] for r in db.get_interrupted_reply_retries(minister)] == ["剿抚孰先？"]
    assert [
        r["content"] for r in db.conn.execute(
            "SELECT content FROM chat_messages WHERE role='user'"
        ).fetchall()
    ] == ["剿抚孰先？"]
    # 消费后无残留 rollback_items（否则将来重试成功→撤回会双还原）。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_turn_rollback_items WHERE chat_turn_id=?", (ct,)
    ).fetchone()["c"] == 0

    # 再重试成功：问话仍只一条、回话新落一条（记录无重复句）。
    rt.session = _RetrySession(db, state, minister)
    payload = rt.retry_interrupted_reply(minister)
    assert payload["answer"] == "臣重奏：剿为先。"
    assert [
        r["content"] for r in db.conn.execute(
            "SELECT content FROM chat_messages WHERE role='user'"
        ).fetchall()
    ] == ["剿抚孰先？"]


# ── finding3：reopen CAS——未赢的并发/双击重试不落第二条大臣回话 ─────────────


def test_lost_reopen_cas_rejects_without_second_reply(restore_env, monkeypatch):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    _start_generating_turn(db, state, minister, "剿抚孰先？")
    db.reconcile_interrupted_chat_turns()
    rt = _retry_runtime(db, state, minister)
    # 模拟并发重试抢先翻走 CAS：本次 reopen 未赢（rowcount=0 → False）。
    monkeypatch.setattr(db, "reopen_interrupted_chat_turn_for_retry", lambda cid: False)
    with pytest.raises(HTTPException):
        rt.retry_interrupted_reply(minister)
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE role='minister'"
    ).fetchone()["c"] == 0


# ── finding4：结算/亲裁相位不得重试召对（夜不跨月）─────────────────────────


def test_retry_rejected_in_settlement_phase(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    _start_generating_turn(db, state, minister, "剿抚孰先？")
    db.reconcile_interrupted_chat_turns()
    rt = _retry_runtime(db, state, minister)
    rt.session.state.turn_phase = next(iter(FRONT_HALF_DONE_PHASES))
    with pytest.raises(HTTPException):
        rt.retry_interrupted_reply(minister)
    # 相位门先于生成/落库：无回话落下。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE role='minister'"
    ).fetchone()["c"] == 0


# ── finding5：reconcile 截断在飞轮的 Agno runs 到本轮起点（retry 上下文不双倍）──


def test_reconcile_truncates_agno_runs_to_turn_start(restore_env):
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    # 本轮起点 agno_runs_before=1；崩溃时 runs 已长到 2（半途生成写入未随回话回滚）。
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS agno_sessions "
        "(session_id TEXT PRIMARY KEY, runs TEXT, updated_at INTEGER)"
    )
    db.conn.execute(
        "INSERT INTO agno_sessions (session_id, runs, updated_at) VALUES (?, ?, 0)",
        ("sess", '[{"r": 1}, {"r": 2}]'),
    )
    db.conn.commit()
    _nid, ct = attach_chat_turn_to_night(
        db, state, minister, agno_session_id="sess", agno_runs_before=1,
    )
    mid = db.append_chat_message(minister, state.turn, "user", "剿抚孰先？")
    db.update_chat_turn_messages(ct, user_message_id=mid)
    assert db.agno_runs_length("sess") == 2

    db.reconcile_interrupted_chat_turns()
    # 截回起点，只丢没落完那半句的 LLM 工作态——问话/账未删。
    assert db.agno_runs_length("sess") == 1
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ct,)
    ).fetchone()["status"] == "interrupted"


def test_reconcile_marks_questionless_orphan_failed(restore_env):
    """负向：连问话都没落的极窄崩溃孤儿 → 'failed'（无可保留/重试），只解阻塞、不入待重试。"""
    env = restore_env
    db, state, content = env.db, env.state, env.content
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    _nid, ct = attach_chat_turn_to_night(
        db, state, minister, agno_session_id="sess", agno_runs_before=0,
    )
    # 不 append 问话、不 link user_message_id：generating 且无 user_message。
    db.close()

    db2, _state2 = _reopen(env.path, content)
    try:
        interrupted = db2.reconcile_interrupted_chat_turns()
        assert all(int(r["chat_turn_id"]) != ct for r in interrupted)
        assert an.list_in_flight_chat_turns(db2, night["id"]) == []
        assert db2.conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (ct,)
        ).fetchone()["status"] == "failed"
        assert db2.get_interrupted_reply_retries(minister) == []
    finally:
        db2.close()


# ── finding2：load_save / 换档重建走 __init__ 同序重开对账 ───────────────────


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（新档、temp DB/saves）；构造即不连 LLM，仅 runtime 配置中和。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    game = web_app.WebGame(fresh=False)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def test_load_save_reconciles_interrupted_orphan(web_game):
    """换档重建（load_save）与 __init__ 同序重开对账：存档里的在飞孤儿轮终态化、
    不再永挡续问/收夜（finding2）。"""
    game = web_game
    minister = _active_minister(game.db, game.content)
    an.open_night(game.db, game.state, location="乾清宫", time_of_day="戌时")
    ct = _start_generating_turn(game.db, game.state, minister, "剿抚孰先？")
    assert game.db.list_in_flight_chat_turns()  # 存档前：在飞
    game.save_to("orphan_save")

    game.load_save("orphan_save")
    # 换档重建后重开对账：孤儿轮 → interrupted，在飞判定解除、问话保留。
    assert game.db.list_in_flight_chat_turns() == []
    assert game.db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ct,)
    ).fetchone()["status"] == "interrupted"
    assert [r["question"] for r in game.db.get_interrupted_reply_retries(minister)] == ["剿抚孰先？"]
