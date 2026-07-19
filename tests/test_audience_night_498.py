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
from ming_sim.session import GameSession, TurnPhase


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

    monkeypatch.setattr(an, "auto_close_open_night", tracing_auto)
    # resolve_turn imports auto_close from audience_night at call time
    import ming_sim.session as sess_mod
    monkeypatch.setattr(
        "ming_sim.audience_night.auto_close_open_night", tracing_auto,
    )

    # 阻止真 LLM：pending 大门拒 + 无 draft 会 ValueError；我们只断言收夜先发生
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

    # list_directives empty → ValueError after auto_close
    with pytest.raises(ValueError, match="草案|颁诏"):
        GameSession.resolve_turn(sess, decree="")
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


# ── AC9：真实任免 + 候选转档 + 崩溃续跑 ──────────────────────────────


def test_close_night_crash_resume_real_appointment_and_directive(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state)

    # 在册大臣改任新职（真实可 commit 的 office 形状）
    new_office = "兵部郎中"
    pa_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister,
        payload={
            "name": minister,
            "office": new_office,
            "office_type": "六部",
            "faction": "中立",
            "reason": "测试任免",
        },
    )
    db.mark_pending_night_approved([pa_id], night_id=night["id"])

    dir_id = db.upsert_pending_directive(
        state.turn, minister,
        payload={"text": "着户部清查边饷", "actor": minister},
    )
    db.mark_pending_night_approved([dir_id], night_id=night["id"])

    # 同回合另一夜未应允项不得被本夜收走
    other_pending = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister,
        payload={"name": minister, "office": "不该落的官", "office_type": "六部"},
    )
    # 强制挂到「别的夜」语义：清 night_approved 并改 night_id=0
    db.conn.execute(
        "UPDATE pending_actions SET night_id=0, night_approved=0 WHERE id=?",
        (other_pending,),
    )
    db.conn.commit()

    with pytest.raises(AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night["id"],
            content=content,
            crash_after_step=CLOSE_STEP_COMMIT_OFFICE,
        )
    assert ei.value.code == "close_crash"
    mid = an.get_night(db, night["id"])
    assert mid["status"] == "closing"
    assert int(mid["close_commit_cursor"]) == CLOSE_STEP_COMMIT_OFFICE

    # 任免真实落盘
    office_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (minister,),
    ).fetchone()
    assert office_row["office"] == new_office
    pa = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pa_id,),
    ).fetchone()
    assert pa["status"] == "committed"

    # 未应允项仍 pending
    other = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (other_pending,),
    ).fetchone()
    assert other["status"] == "pending"

    # 续跑：候选转档 + 收夜
    result = an.close_night(db, state, night_id=night["id"], content=content)
    assert result["closed"] is True
    final = an.get_night(db, night["id"])
    assert final["status"] == "closed"
    assert int(final["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE

    dir_row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (dir_id,),
    ).fetchone()
    assert dir_row["status"] == "committed"
    drafts = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,),
    ).fetchall()
    assert any("清查边饷" in (r["text"] or "") for r in drafts)

    close_e = _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)
    assert len(close_e) == 1
    again = an.close_night(db, state, night_id=night["id"], content=content)
    assert again.get("already") is True
    assert len(_find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)) == 1


def test_close_submit_failure_does_not_seal_night(game):
    """提交失败不得推进 cursor 封夜。"""
    db, state, content = game
    night = an.open_night(db, state)
    # 坏 payload 任免 → apply 返 False → failed
    pa_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name="不存在的人",
        payload={"name": "", "office": "空"},
    )
    db.mark_pending_night_approved([pa_id], night_id=night["id"])
    with pytest.raises(AudienceNightError) as ei:
        an.close_night(db, state, night_id=night["id"], content=content)
    assert ei.value.code == "close_submit_failed"
    loaded = an.get_night(db, night["id"])
    assert loaded["status"] == "closing"
    assert int(loaded["close_commit_cursor"]) == 0


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


def test_resolve_turn_blocked_by_inflight(game, monkeypatch):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly2", agno_runs_before=0,
    )
    monkeypatch.setattr(an, "DEFAULT_IN_FLIGHT_WAIT_S", 0.0)
    monkeypatch.setattr(
        "ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.0,
    )

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

    with pytest.raises(AudienceNightError) as ei:
        GameSession.resolve_turn(sess, decree="")
    assert ei.value.code == "in_flight_chat"
    assert an.get_night(db, night_id)["status"] == "open"
    assert state.turn_phase == TurnPhase.SUMMONING.value


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


def test_cli_attach_path_sets_night_id(game):
    """CLI 起聊走 attach_chat_turn_to_night（非 night_id=0 旁路）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    from ming_sim.audience_night import attach_chat_turn_to_night
    night_id, cid = attach_chat_turn_to_night(
        db, state, minister, agno_session_id=f"cli:{minister}", agno_runs_before=0,
    )
    row = db.conn.execute(
        "SELECT night_id, status FROM chat_turns WHERE id=?", (cid,),
    ).fetchone()
    assert int(row["night_id"]) == night_id > 0
    assert row["status"] == "generating"
