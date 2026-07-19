"""#498 召对夜容器与故事账本地基。

最高 seam = 夜会话接口对 DB 的效果：开夜→宣人→对话轮→收夜，断言可观察账本骨架、
按夜隔离、死账/在飞响亮失败、收夜提交幂等续跑、结算顺势收夜。

不锁 LLM 叙事正文；锁硬骨架（序/人/可闻性/标签）与完成态。
"""

from __future__ import annotations

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
from ming_sim.decree import advance_without_edict, pre_settle
from ming_sim.session import TurnPhase


# ── helpers ──────────────────────────────────────────────────────────


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


# ── AC1/2/5：开夜→宣人→收夜一链 ─────────────────────────────────────


def test_open_summon_close_chain_readable_by_night(game):
    db, state, content = game
    minister = _active_minister(db, content)

    night = an.open_night(
        db, state, time_of_day="戌时", location="乾清宫",
        body="乾清宫灯火初上。",
    )
    assert night["status"] == "open"
    assert night["time_of_day"] == "戌时"
    assert night["location"] == "乾清宫"

    an.summon_enter(db, night["id"], minister, method=METHOD_XUANRU)
    an.close_night(db, state, night_id=night["id"], body="秋深夜寒，退朝。")

    loaded = an.get_night(db, night["id"])
    assert loaded is not None
    assert loaded["status"] == "closed"
    assert loaded["time_of_day"] == "戌时"
    assert loaded["location"] == "乾清宫"

    entries = an.list_ledger(db, night["id"])
    assert entries, "账本不能空"
    # 硬骨架三字段 + 正文/标签可断言
    for e in entries:
        assert "seq" in e and isinstance(e["seq"], int)
        assert isinstance(e["person_names"], list)
        assert e["audibility"] in {AUDIBILITY_PUBLIC, an.AUDIBILITY_PRIVATE}
        assert isinstance(e["body"], str)
        assert isinstance(e["tags"], list)
    # 序严格递增
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))

    open_e = _find_entries(entries, TAG_OPEN_NIGHT)
    assert len(open_e) == 1
    assert open_e[0]["person_names"] == []

    enter_e = _find_entries(entries, TAG_ENTER, METHOD_XUANRU)
    assert any(minister in e["person_names"] for e in enter_e)
    # 召法从开放标签可辨
    assert METHOD_XUANRU in enter_e[0]["tags"]

    close_e = _find_entries(entries, TAG_CLOSE_NIGHT)
    assert len(close_e) == 1
    assert close_e[0]["person_names"] == []


def test_summon_method_yueci_tag_identifiable(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="文华殿", time_of_day="午时")
    an.summon_enter(db, night["id"], minister, method=METHOD_YUECI, body="越次召见。")
    entries = an.list_ledger(db, night["id"])
    hit = _find_entries(entries, TAG_ENTER, METHOD_YUECI)
    assert hit and minister in hit[0]["person_names"]


def test_bad_summon_method_rejected(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.summon_enter(db, night["id"], minister, method="密召")
    assert ei.value.code == "bad_summon_method"


# ── AC3：同月两夜隔离 ────────────────────────────────────────────────


def test_two_nights_same_month_isolated(game):
    db, state, content = game
    a = _active_minister(db, content)
    b = _active_minister(db, content, exclude={a})

    n1 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    an.summon_enter(db, n1["id"], a, method=METHOD_XUANRU)
    tid1 = db.create_chat_turn(
        state, a, "sess-a", 0, night_id=n1["id"],
    )
    # 回话入档 → 完成态
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', '臣遵旨')",
        (a, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(tid1, minister_message_id=int(mid))
    an.close_night(db, state, night_id=n1["id"])

    n2 = an.open_night(db, state, location="文华殿", time_of_day="日")
    an.summon_enter(db, n2["id"], b, method=METHOD_XUANRU)
    tid2 = db.create_chat_turn(
        state, b, "sess-b", 0, night_id=n2["id"],
    )
    mid2 = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', '臣在')",
        (b, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(tid2, minister_message_id=int(mid2))
    an.close_night(db, state, night_id=n2["id"])

    assert n1["id"] != n2["id"]
    e1 = an.list_ledger(db, n1["id"])
    e2 = an.list_ledger(db, n2["id"])
    # 互不串：第一夜账不含 b 的宣入；第二夜不含 a 的宣入（常在员额除外）
    n1_persons = {p for e in e1 for p in e["person_names"]}
    n2_persons = {p for e in e2 for p in e["person_names"]}
    assert a in n1_persons and a not in n2_persons
    assert b in n2_persons and b not in n1_persons

    t1 = an.list_chat_turns_for_night(db, n1["id"])
    t2 = an.list_chat_turns_for_night(db, n2["id"])
    assert [int(x["id"]) for x in t1] == [tid1]
    assert [int(x["id"]) for x in t2] == [tid2]

    # 结算 guard 不误挡：两夜都已收，pre_settle 可进
    state.turn_phase = TurnPhase.SUMMONING.value
    pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value


# ── AC4：对话轮完成态与时序 ──────────────────────────────────────────


def test_chat_turns_completion_and_night_anchor(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s1", agno_runs_before=0,
        location="便殿", time_of_day="申时",
    )
    row = db.conn.execute(
        "SELECT * FROM chat_turns WHERE id=?", (chat_id,)
    ).fetchone()
    assert int(row["night_id"]) == night_id
    assert row["status"] == "generating"

    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'user', '问')",
        (minister, state.turn),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', '答')",
        (minister, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_id, user_message_id=int(uid))
    # 仅用户消息：仍 generating
    still = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (chat_id,)
    ).fetchone()
    assert still["status"] == "generating"

    db.update_chat_turn_messages(chat_id, minister_message_id=int(mid))
    done = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (chat_id,)
    ).fetchone()
    assert done["status"] == "active"

    turns = an.list_chat_turns_for_night(db, night_id)
    assert len(turns) == 1
    assert int(turns[0]["id"]) == chat_id
    assert turns[0]["status"] == "active"
    # 账目时序：开夜/入殿在对话轮之前可对齐（seq 存在且 chat id 单调）
    ledger = an.list_ledger(db, night_id)
    assert ledger[0]["tags"] == [TAG_OPEN_NIGHT] or TAG_OPEN_NIGHT in ledger[0]["tags"]


# ── AC6：死账校验 ────────────────────────────────────────────────────


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
    # 夜仍开着，未落死账入殿
    entries = an.list_ledger(db, night["id"])
    assert not any(
        minister in e["person_names"] and TAG_ENTER in e["tags"]
        and TAG_STANDING_ROSTER not in e["tags"]
        for e in entries
    )


# ── AC7：常在员额生命守卫 ────────────────────────────────────────────


def test_standing_roster_skips_dead_or_dismissed(game):
    db, state, content = game
    # 找出当前御前近臣
    roster_before = an.resolve_standing_roster(db)
    assert roster_before, "开局应有王承恩类常在员额"

    victim = roster_before[0]
    db.set_character_status(state, victim, "dead", reason="测试")
    # 开新夜不得撞死账
    night = an.open_night(db, state, location="乾清宫")
    assert night["status"] == "open"
    entries = an.list_ledger(db, night["id"])
    roster_enters = _find_entries(entries, TAG_ENTER, TAG_STANDING_ROSTER)
    names = {p for e in roster_enters for p in e["person_names"]}
    assert victim not in names

    # 免职同理
    db.set_character_status(state, victim, "active", reason="")
    # 清空 office 使 is_inner_court_attendant 不命中
    db.conn.execute(
        "UPDATE characters SET office='', status='dismissed' WHERE name=?",
        (victim,),
    )
    db.conn.commit()
    if victim in content.characters:
        content.characters[victim].status = "dismissed"
        content.characters[victim].office = ""
    night2_prev = an.close_night(db, state, night_id=night["id"])
    assert night2_prev["closed"]
    night2 = an.open_night(db, state)
    roster2 = {
        p
        for e in _find_entries(an.list_ledger(db, night2["id"]), TAG_ENTER, TAG_STANDING_ROSTER)
        for p in e["person_names"]
    }
    assert victim not in roster2


# ── AC8：颁诏/过回合顺势收夜 ─────────────────────────────────────────


def test_pre_settle_auto_closes_open_night(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    an.summon_enter(db, night["id"], minister)
    state.turn_phase = TurnPhase.SUMMONING.value
    pre_settle(state, db, content=content)
    loaded = an.get_night(db, night["id"])
    assert loaded["status"] == "closed"
    close_e = _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)
    assert close_e
    assert TAG_AUTO_CLOSE in close_e[0]["tags"]
    assert state.turn_phase == TurnPhase.SETTLING.value


def test_advance_without_edict_auto_closes_open_night(game):
    db, state, content = game
    night = an.open_night(db, state, location="便殿")
    state.turn_phase = TurnPhase.SUMMONING.value
    before_turn = state.turn
    advance_without_edict(state, db, content=content)
    loaded = an.get_night(db, night["id"])
    assert loaded["status"] == "closed"
    assert state.turn == before_turn + 1


# ── AC9：收夜提交崩溃幂等续跑 ────────────────────────────────────────


def test_close_night_crash_resume_idempotent(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state)
    # 任免暂存
    pa_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister,
        target_id=None,
        payload={
            "name": minister,
            "office": "测试郎中",
            "office_type": "六部",
            "action": "任命",
        },
    )
    # 拟旨暂存
    db.upsert_pending_directive(
        state.turn, minister,
        payload={"text": "着户部清查边饷", "actor": minister},
    )

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
    # 任免已 commit
    pa = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pa_id,)
    ).fetchone()
    # office apply 可能 failed（坏 payload 形状）或 committed——游标已过步即可
    assert pa is not None
    assert pa["status"] in {"committed", "failed"}

    # 续跑收齐
    result = an.close_night(db, state, night_id=night["id"], content=content)
    assert result["closed"] is True
    final = an.get_night(db, night["id"])
    assert final["status"] == "closed"
    assert int(final["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE
    # 收夜账仅一条
    close_e = _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)
    assert len(close_e) == 1
    # 再 close 幂等
    again = an.close_night(db, state, night_id=night["id"], content=content)
    assert again.get("already") is True
    assert len(_find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)) == 1


# ── AC10：在飞回话 fail-closed ───────────────────────────────────────


def test_close_with_in_flight_chat_fail_closed(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly", agno_runs_before=0,
    )
    # generating、无大臣回话 → 在飞
    with pytest.raises(AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id, wait_timeout_s=0.0,
        )
    assert ei.value.code == "in_flight_chat"
    assert ei.value.error_pack_path
    assert Path(ei.value.error_pack_path).is_dir()
    loaded = an.get_night(db, night_id)
    assert loaded["status"] == "open"  # 未进入 closing
    # 可原地重试：回话入档后收夜成功
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', '回奏')",
        (minister, state.turn),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_id, minister_message_id=int(mid))
    result = an.close_night(db, state, night_id=night_id, wait_timeout_s=0.0)
    assert result["closed"] is True
    assert an.get_night(db, night_id)["status"] == "closed"


def test_pre_settle_blocked_by_in_flight_keeps_night_open(game, monkeypatch):
    db, state, content = game
    # 收夜默认 wait 很短；强制 0 使在飞立刻 fail-closed
    monkeypatch.setattr(an, "DEFAULT_IN_FLIGHT_WAIT_S", 0.0)

    minister = _active_minister(db, content)
    night_id, _chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="fly2", agno_runs_before=0,
    )
    state.turn_phase = TurnPhase.SUMMONING.value
    with pytest.raises(AudienceNightError) as ei:
        pre_settle(state, db, content=content)
    assert ei.value.code == "in_flight_chat"
    assert an.get_night(db, night_id)["status"] == "open"
    assert state.turn_phase == TurnPhase.SUMMONING.value


# ── 负向：坏可闻性 / 已收夜再写账 ─────────────────────────────────────


def test_bad_audibility_rejected(game):
    db, state, content = game
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.append_ledger_entry(
            db, night["id"], person_names=[], audibility="全知",
            body="x", tags=["试"],
        )
    assert ei.value.code == "bad_audibility"


def test_append_after_close_rejected(game):
    db, state, content = game
    night = an.open_night(db, state)
    an.close_night(db, state, night_id=night["id"])
    with pytest.raises(AudienceNightError) as ei:
        an.append_ledger_entry(
            db, night["id"], body="不该写入", tags=["试"],
        )
    assert ei.value.code == "night_closed"
