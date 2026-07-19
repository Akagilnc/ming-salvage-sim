"""#498 召对夜容器与故事账本地基——真实入口→DB 末态 tracer。

一条贯穿：web/CLI 会话 seam 与 GameSession 公开颁诏/过回合入口，断言 DB 可观察
结果。覆盖 AC1–10 核心：账本骨架、多夜隔离、完成态与 night_seq 对齐、死账、
员额、AC8 顺势收夜顺序、AC9 崩溃续跑真实任免/候选、AC10 完成等待与超时、旧档迁移。

不锁 LLM 叙事正文；不接受 failed 当成功。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    CLOSE_STEP_COMMIT_OFFICE,
    METHOD_XUANRU,
    METHOD_YUECI,
    TAG_AUTO_CLOSE,
    TAG_CLOSE_NIGHT,
    TAG_ENTER,
    TAG_OPEN_NIGHT,
    TAG_STANDING_ROSTER,
    AudienceNightError,
)
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.decree import advance_without_edict, pre_settle
from ming_sim.session import TurnPhase


def _active_minister(db, content, *, exclude: set[str] | None = None) -> str:
    skip = exclude or set()
    for name, ch in content.characters.items():
        if name in skip:
            continue
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _find_entries(entries, *required_tags):
    need = set(required_tags)
    return [e for e in entries if need.issubset(set(e["tags"]))]


def _partial_session(db, state, content):
    """真实 GameSession 公开颁诏入口（resolve_turn / await_audience_inflight_clear），
    绕开 LLM 构造：无草案时 auto_close 先收夜、再以 ValueError 停在拟诏前，够断言收夜副作用。"""
    from ming_sim.session import GameSession
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = None
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.pending_count = lambda: 0  # type: ignore
    return sess


def _land_reply(db, state, minister: str, chat_id: int, text: str = "臣遵旨。") -> None:
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, text),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_id, minister_message_id=int(mid))


# ── AC1/2/5 开夜→宣人→收夜 ──────────────────────────────────────────


def test_open_summon_close_chain_readable_by_night(game):
    db, state, content = game
    minister = _active_minister(db, content)

    night = an.open_night(
        db, state, time_of_day="戌时", location="乾清宫",
        body="乾清宫灯火初上。",
    )
    an.summon_enter(db, night["id"], minister, method=METHOD_XUANRU)
    an.close_night(db, state, night_id=night["id"], body="秋深夜寒，退朝。")

    loaded = an.get_night(db, night["id"])
    assert loaded["status"] == "closed"
    assert loaded["time_of_day"] == "戌时"
    assert loaded["location"] == "乾清宫"

    entries = an.list_ledger(db, night["id"])
    for e in entries:
        assert isinstance(e["seq"], int)
        assert isinstance(e["person_names"], list)
        assert e["audibility"] in {AUDIBILITY_PUBLIC, an.AUDIBILITY_PRIVATE}
        assert isinstance(e["body"], str)
        assert isinstance(e["tags"], list)
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs)

    assert len(_find_entries(entries, TAG_OPEN_NIGHT)) == 1
    enter_e = _find_entries(entries, TAG_ENTER, METHOD_XUANRU)
    assert any(minister in e["person_names"] for e in enter_e)
    assert len(_find_entries(entries, TAG_CLOSE_NIGHT)) == 1


def test_summon_method_and_bad_method(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="文华殿", time_of_day="午时")
    an.summon_enter(db, night["id"], minister, method=METHOD_YUECI)
    hit = _find_entries(an.list_ledger(db, night["id"]), TAG_ENTER, METHOD_YUECI)
    assert hit and minister in hit[0]["person_names"]
    with pytest.raises(AudienceNightError) as ei:
        an.summon_enter(db, night["id"], minister, method="密召")
    assert ei.value.code == "bad_summon_method"


# ── AC3 多夜隔离 + AC4 timeline ──────────────────────────────────────


def test_two_nights_isolated_and_timeline_alignable(game):
    db, state, content = game
    a = _active_minister(db, content)
    b = _active_minister(db, content, exclude={a})

    n1 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    an.summon_enter(db, n1["id"], a, method=METHOD_XUANRU)
    tid1 = db.create_chat_turn(state, a, "sess-a", 0, night_id=n1["id"])
    _land_reply(db, state, a, tid1)
    an.close_night(db, state, night_id=n1["id"])

    n2 = an.open_night(db, state, location="文华殿", time_of_day="日")
    an.summon_enter(db, n2["id"], b, method=METHOD_XUANRU)
    tid2 = db.create_chat_turn(state, b, "sess-b", 0, night_id=n2["id"])
    _land_reply(db, state, b, tid2)
    an.close_night(db, state, night_id=n2["id"])

    assert n1["id"] != n2["id"]
    n1_persons = {p for e in an.list_ledger(db, n1["id"]) for p in e["person_names"]}
    n2_persons = {p for e in an.list_ledger(db, n2["id"]) for p in e["person_names"]}
    assert a in n1_persons and a not in n2_persons
    assert b in n2_persons and b not in n1_persons
    assert [int(x["id"]) for x in an.list_chat_turns_for_night(db, n1["id"])] == [tid1]
    assert [int(x["id"]) for x in an.list_chat_turns_for_night(db, n2["id"])] == [tid2]

    # AC4：合流 timeline 按 night_seq 单调，chat 与 ledger 同桶
    tl = an.list_night_timeline(db, n1["id"])
    seqs = [int(ev["seq"]) for ev in tl]
    assert seqs == sorted(seqs)
    assert any(ev["kind"] == "chat_turn" for ev in tl)
    assert any(ev["kind"] == "ledger" for ev in tl)
    chat_ev = next(ev for ev in tl if ev["kind"] == "chat_turn")
    assert int(chat_ev["payload"]["night_seq"]) == int(chat_ev["seq"]) > 0

    state.turn_phase = TurnPhase.SUMMONING.value
    pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value


def test_chat_completion_via_attach(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s1", agno_runs_before=0,
        location="便殿", time_of_day="申时",
    )
    row = db.conn.execute("SELECT * FROM chat_turns WHERE id=?", (chat_id,)).fetchone()
    assert int(row["night_id"]) == night_id
    assert row["status"] == "generating"
    assert int(row["night_seq"]) > 0
    _land_reply(db, state, minister, chat_id)
    done = db.conn.execute("SELECT status FROM chat_turns WHERE id=?", (chat_id,)).fetchone()
    assert done["status"] == "active"


# ── AC6/7 死账与员额 ────────────────────────────────────────────────


def test_dead_person_enter_rejected_with_error_pack(game):
    db, state, content = game
    minister = _active_minister(db, content)
    db.set_character_status(state, minister, "dead", reason="测试身故")
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.summon_enter(db, night["id"], minister, method=METHOD_XUANRU)
    assert ei.value.code == "dead_present"
    assert ei.value.error_pack_path
    assert Path(ei.value.error_pack_path).is_dir()


def test_standing_roster_skips_dead(game):
    db, state, content = game
    roster_before = an.resolve_standing_roster(db)
    assert roster_before
    victim = roster_before[0]
    db.set_character_status(state, victim, "dead", reason="测试")
    night = an.open_night(db, state, location="乾清宫")
    names = {
        p
        for e in _find_entries(an.list_ledger(db, night["id"]), TAG_ENTER, TAG_STANDING_ROSTER)
        for p in e["person_names"]
    }
    assert victim not in names


# ── AC8：公开入口顺势收夜（GameSession.resolve_turn / advance）────────


def test_resolve_turn_auto_closes_before_settlement(game, monkeypatch):
    """AC8：GameSession.resolve_turn 公开入口最前收夜，再进结算候选。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    an.summon_enter(db, night["id"], minister)

    order: list[str] = []
    real_auto = an.auto_close_open_night

    def tracing_auto(db_, state_, **kw):
        order.append("auto_close")
        return real_auto(db_, state_, **kw)

    # resolve_turn imports auto_close from audience_night at call time
    monkeypatch.setattr(
        "ming_sim.audience_night.auto_close_open_night", tracing_auto,
    )

    # 阻止真 LLM：pending 大门拒 + 无 draft 会 ValueError；我们只断言收夜先发生
    sess = _partial_session(db, state, content)

    # list_directives empty → ValueError after auto_close
    with pytest.raises(ValueError, match="草案|颁诏"):
        sess.resolve_turn(decree="")
    assert "auto_close" in order
    assert an.get_night(db, night["id"])["status"] == "closed"
    close_e = _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)
    assert close_e and TAG_AUTO_CLOSE in close_e[0]["tags"]


def test_advance_without_edict_auto_closes(game):
    db, state, content = game
    night = an.open_night(db, state, location="便殿")
    state.turn_phase = TurnPhase.SUMMONING.value
    before = state.turn
    advance_without_edict(state, db, content=content)
    assert an.get_night(db, night["id"])["status"] == "closed"
    assert state.turn == before + 1


def test_write_decree_does_not_close_night(game, monkeypatch):
    """AC8：拟诏（write_decree）不是收夜触发器——夜内可拟旨并继续斟酌，夜保持开。
    只有 resolve_turn / advance 才收夜。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫")
    # 一条对话式拟旨暂存 → write_decree 会提交为 draft 并生成诏书
    db.upsert_pending_directive(state.turn, minister, payload={"text": "着户部核边饷", "actor": minister})
    monkeypatch.setattr("ming_sim.session.write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")

    sess = _partial_session(db, state, content)
    decree = sess.write_decree()
    assert "诏" in decree
    # 拟诏后夜仍开着（可继续拟旨/斟酌）
    assert an.get_night(db, night["id"])["status"] == "open"
    assert not _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)


def test_cross_night_directive_reassigned_to_second_night(game):
    """同臣跨两夜拟旨：第一夜未应允 directive 留 pending；第二夜复用更新时归属原子迁到第二夜，
    第二夜应允 → 只在第二夜收夜提交，不被旧夜漏挂。"""
    db, state, content = game
    minister = _active_minister(db, content)

    n1 = an.open_night(db, state, location="乾清宫")
    d_id = db.upsert_pending_directive(state.turn, minister, payload={"text": "初稿：缓征辽饷", "actor": minister})
    # 第一夜不应允 → 留 pending；收夜不提交
    an.close_night(db, state, night_id=n1["id"], content=content)
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (d_id,)).fetchone()["status"] == "pending"

    n2 = an.open_night(db, state, location="文华殿")
    # 同臣同回合复用更新（last-write-wins）→ 归属须迁到第二夜、清 approval
    same_id = db.upsert_pending_directive(state.turn, minister, payload={"text": "定稿：改折色", "actor": minister})
    assert same_id == d_id
    row = db.conn.execute("SELECT night_id, night_approved FROM pending_actions WHERE id=?", (d_id,)).fetchone()
    assert int(row["night_id"]) == n2["id"]
    assert int(row["night_approved"]) == 0
    # 第二夜应允 + 收夜 → 提交
    assert db.mark_pending_night_approved([d_id], night_id=n2["id"]) == 1
    an.close_night(db, state, night_id=n2["id"], content=content)
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (d_id,)).fetchone()["status"] == "committed"
    drafts = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=? AND status='draft'", (state.turn,)).fetchall()
    assert any("改折色" in (r["text"] or "") for r in drafts)


# ── AC9：真实任免 + 候选转档 + 崩溃续跑 ──────────────────────────────


def test_close_night_crash_then_reopen_db_resumes_idempotent(content):
    """AC9：合法任免已 commit、候选转档前 crash → 关 GameDB、重开续跑收齐；
    真实任免落盘、候选真实转档、单条收夜账、幂等无重复、无半提交终态。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        state = db.load_state()
        minister = _active_minister(db, content)
        night = an.open_night(db, state)

        new_office = "兵部郎中"
        pa_id = db.stage_pending_action(
            state.turn, kind="office", action="任命",
            minister_name=minister,
            payload={
                "name": minister, "office": new_office, "office_type": "六部",
                "faction": "中立", "reason": "测试任免",
            },
        )
        db.mark_pending_night_approved([pa_id], night_id=night["id"])
        dir_id = db.upsert_pending_directive(
            state.turn, minister, payload={"text": "着户部清查边饷", "actor": minister},
        )
        db.mark_pending_night_approved([dir_id], night_id=night["id"])

        # crash：任免已 commit（step1）、候选转档（step2）前崩
        with pytest.raises(AudienceNightError) as ei:
            an.close_night(
                db, state, night_id=night["id"], content=content,
                crash_after_step=CLOSE_STEP_COMMIT_OFFICE,
            )
        assert ei.value.code == "close_crash"
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"] == new_office
        db.close()  # 进程崩溃：关库

        # 重开 GameDB / state，从游标续跑（跨进程恢复）
        db2 = GameDB(path, content)
        state2 = db2.load_state()
        mid = an.get_night(db2, night["id"])
        assert mid["status"] == "closing"
        assert int(mid["close_commit_cursor"]) == CLOSE_STEP_COMMIT_OFFICE

        result = an.close_night(db2, state2, night_id=night["id"], content=content)
        assert result["closed"] is True
        final = an.get_night(db2, night["id"])
        assert final["status"] == "closed"
        assert int(final["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE
        # 任免仍在（不因重开丢失）+ 候选真实转档
        assert db2.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"] == new_office
        assert db2.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (dir_id,),
        ).fetchone()["status"] == "committed"
        drafts = db2.conn.execute(
            "SELECT text FROM turn_directives WHERE turn=? AND status='draft'",
            (state2.turn,),
        ).fetchall()
        assert any("清查边饷" in (r["text"] or "") for r in drafts)
        # 单条收夜账，再收幂等无重复
        assert len(_find_entries(an.list_ledger(db2, night["id"]), TAG_CLOSE_NIGHT)) == 1
        again = an.close_night(db2, state2, night_id=night["id"], content=content)
        assert again.get("already") is True
        assert len(_find_entries(an.list_ledger(db2, night["id"]), TAG_CLOSE_NIGHT)) == 1
        db2.close()
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def test_close_night_only_commits_this_night_approved(game):
    """收夜只交本夜已应允白名单；他夜/未应允项不被串走。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state)
    approved = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister,
        payload={"name": minister, "office": "兵部郎中", "office_type": "六部",
                 "faction": "中立", "reason": "测试"},
    )
    db.mark_pending_night_approved([approved], night_id=night["id"])
    # 未应允项（同回合、另一夜语义）
    unapproved = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister,
        payload={"name": minister, "office": "不该落的官", "office_type": "六部"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET night_id=0, night_approved=0 WHERE id=?", (unapproved,))
    db.conn.commit()

    an.close_night(db, state, night_id=night["id"], content=content)
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (approved,)).fetchone()["status"] == "committed"
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (unapproved,)).fetchone()["status"] == "pending"


# ── AC10 在飞：完成可收 / 超时 fail-closed ───────────────────────────


def test_close_inflight_timeout_then_retry_after_land(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly", agno_runs_before=0,
    )
    with pytest.raises(AudienceNightError) as ei:
        an.close_night(db, state, night_id=night_id, wait_timeout_s=0.0)
    assert ei.value.code == "in_flight_chat"
    assert ei.value.error_pack_path
    assert an.get_night(db, night_id)["status"] == "open"

    _land_reply(db, state, minister, chat_id)
    result = an.close_night(db, state, night_id=night_id, wait_timeout_s=0.0)
    assert result["closed"] is True
    assert an.get_night(db, night_id)["status"] == "closed"


def test_resolve_turn_blocked_by_inflight_stays_open(game, monkeypatch):
    """挂起/超时 → resolve_turn fail-closed，夜保持 open、相位不进。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly2", agno_runs_before=0,
    )
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.0)

    sess = _partial_session(db, state, content)
    with pytest.raises(AudienceNightError) as ei:
        sess.resolve_turn(decree="")
    assert ei.value.code == "in_flight_chat"
    assert an.get_night(db, night_id)["status"] == "open"
    assert state.turn_phase == TurnPhase.SUMMONING.value


def test_resolve_turn_gate_held_close_is_instant_failclosed(game):
    """AC10 反自锁：web 入口持 gate 传 inflight_wait_s=0.0，在飞时即时 fail-closed，
    绝不持 gate 空转 30 秒（否则回话 epilogue 抢不到 gate 落档）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly3", agno_runs_before=0,
    )
    sess = _partial_session(db, state, content)
    t0 = time.monotonic()
    with pytest.raises(AudienceNightError) as ei:
        sess.resolve_turn(decree="", inflight_wait_s=0.0)
    assert ei.value.code == "in_flight_chat"
    assert time.monotonic() - t0 < 5.0  # 即时返回，非默认 30s 自锁
    assert an.get_night(db, night_id)["status"] == "open"


def test_inflight_reply_lands_before_decree_closes(game):
    """AC10 顺序：web 颁诏入口在抢 write_gate 前先 gate-free 等在飞回话落档
    （_await_audience_inflight_clear 不持 gate），回话 epilogue 抢得 gate 入档后，
    再持 gate 收夜——回话先入档→收夜。"""
    import web_app
    from types import SimpleNamespace

    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly4", agno_runs_before=0,
    )
    web_gate = threading.Lock()  # 代 web write_gate：回话 epilogue 落档须持它
    go = threading.Event()

    def reply_epilogue():
        go.wait(2.0)
        with web_gate:  # 回话生成完，抢 gate 落档
            _land_reply(db, state, minister, chat_id)

    worker = threading.Thread(target=reply_epilogue)
    worker.start()

    sess = _partial_session(db, state, content)
    go.set()
    # web 入口真实前置步：gate 外等在飞落档（不持 web_gate，故 reply_epilogue 能抢锁入档、返回）
    web_app._await_audience_inflight_clear(SimpleNamespace(db=db))
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (chat_id,)).fetchone()["status"] == "active"
    # 落档后持 gate 收夜即时复查
    with web_gate:
        with pytest.raises(ValueError, match="草案|颁诏"):
            sess.resolve_turn(decree="", inflight_wait_s=0.0)
    worker.join(2.0)
    assert not worker.is_alive()
    assert an.get_night(db, night_id)["status"] == "closed"


# ── 开夜原子 + 旧档迁移 ──────────────────────────────────────────────


def test_open_night_atomic_on_dead_roster_injection(game, monkeypatch):
    """开夜原子：落账失败时不留缺账 open 夜。"""
    db, state, content = game
    real_append = an.append_ledger_entry
    calls = {"n": 0}

    def flaky_append(*args, **kwargs):
        calls["n"] += 1
        # 开夜账成功后，第一条员额账炸掉
        if calls["n"] >= 2 and kwargs.get("tags") and an.TAG_STANDING_ROSTER in kwargs["tags"]:
            raise RuntimeError("inject roster fail")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(an, "append_ledger_entry", flaky_append)
    # 确保有员额可触发
    assert an.resolve_standing_roster(db)
    with pytest.raises(RuntimeError, match="inject roster fail"):
        an.open_night(db, state, location="乾清宫")
    open_n = an.get_open_night(db)
    assert open_n is None
    n_nights = db.conn.execute("SELECT COUNT(*) AS c FROM audience_nights").fetchone()["c"]
    assert int(n_nights) == 0


def test_old_save_migration_night_id_index_order(content):
    """旧档无 night_id 列：ensure_column 后再建索引，重开不炸。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minister_name TEXT NOT NULL,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                user_message_id INTEGER,
                minister_message_id INTEGER,
                agno_session_id TEXT NOT NULL DEFAULT '',
                agno_runs_before INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                undone_at TEXT
            );
            CREATE TABLE game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                turn_phase TEXT NOT NULL DEFAULT 'summoning'
            );
            INSERT INTO game_state (id, year, period, turn) VALUES (1, 1628, 1, 1);
            """
        )
        conn.commit()
        conn.close()
        # 完整 GameDB 初始化会 ensure 列 + 建索引
        db = GameDB(path, content)
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(chat_turns)").fetchall()}
        assert "night_id" in cols
        assert "night_seq" in cols
        # 索引存在
        idxs = {
            r["name"]
            for r in db.conn.execute("PRAGMA index_list(chat_turns)").fetchall()
        }
        assert "idx_chat_turns_night" in idxs
        # 可写挂夜轮
        state = db.load_state()
        minister = _active_minister(db, content)
        night = an.open_night(db, state)
        cid = db.create_chat_turn(state, minister, "migrate", 0, night_id=night["id"])
        row = db.conn.execute(
            "SELECT night_id, night_seq, status FROM chat_turns WHERE id=?", (cid,),
        ).fetchone()
        assert int(row["night_id"]) == night["id"]
        assert row["status"] == "generating"
        db.close()
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


# ── 负向 ─────────────────────────────────────────────────────────────


def test_bad_audibility_and_append_after_close(game):
    db, state, content = game
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.append_ledger_entry(
            db, night["id"], person_names=[], audibility="全知", body="x", tags=["试"],
        )
    assert ei.value.code == "bad_audibility"
    an.close_night(db, state, night_id=night["id"])
    with pytest.raises(AudienceNightError) as ei2:
        an.append_ledger_entry(db, night["id"], body="不该", tags=["试"])
    assert ei2.value.code == "night_closed"


def test_cli_minister_chat_anchors_turn_to_night(game, monkeypatch):
    """CLI 真实输入入口 terminal.minister_chat 起聊 → 对话轮挂夜（非 night_id=0 旁路）。"""
    import ming_sim.cli.terminal as term
    from types import SimpleNamespace

    db, state, content = game
    character = next(c for c in content.characters.values()
                     if db.get_character_status(c.name)[0] == "active"
                     and getattr(c, "power_id", "ming") == "ming"
                     and getattr(c, "office_type", "") != "后宫")

    def chat(_name, _question, chat_turn_id=0):
        assert chat_turn_id > 0  # 挂夜轮以 generating 起笔，回话须带 chat_turn_id
        return SimpleNamespace(
            answer="臣有本奏。", proposed_directive=None, appointed_minister="",
            registered_minister="", displaced_minister="", court_action="",
            next_minister="", secret_order_id=0, pending_action_id=0,
            pending_action_failures=[],
        )

    session = SimpleNamespace(
        db=db, state=state, content=content, temporary_characters=set(), chat=chat,
    )
    answers = iter(["朕问卿边事如何？", "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(session, character) == "dismiss"

    open_n = an.get_open_night(db)
    assert open_n is not None
    turns = an.list_chat_turns_for_night(db, int(open_n["id"]))
    assert turns and turns[-1]["minister_name"] == character.name
    assert int(turns[-1]["night_id"]) == int(open_n["id"]) > 0
