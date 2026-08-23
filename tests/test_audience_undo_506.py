"""#506 撤回本轮效果逆转（轮级撤销日志 / 白名单审计，ADR 0038 cmr R1 修订版）。

一条贯穿真实入口：召对夜里一「轮」= 一次玩家发话到下一次发话的完整交换，落为一条
`chat_turns` 行。生产走 `capture_chat_rollback_snapshot`（轮前）→ 该轮全部写入 →
`record_chat_turn_rollback_diffs`（轮后，前像撤销日志）→ `undo_chat_turn`（逆转）。
本文件按同一 seam 驱动、断 DB/账本/在场末态，覆盖 AC1–AC12。

不锁 LLM 叙事正文；不接受 failed 当成功。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_night import AudienceNightError
from ming_sim.db import GameDB


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


def _night_seq_of(db, chat_id: int) -> int:
    row = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id = ?", (int(chat_id),)
    ).fetchone()
    return int(row["night_seq"] or 0)


def _run_round(
    db: GameDB,
    state,
    minister: str,
    *,
    writes: Optional[Callable[[int, int], None]] = None,
    facts: Optional[Sequence[Dict[str, Any]]] = None,
    reply: str = "臣遵旨。",
) -> tuple[int, int]:
    """跑一「轮」——严格复刻 web_app 的轮窗口 seam。

    `writes(night_id, chat_id)` 在轮窗口内做该轮的结构化写（暂存/密令落地/入册等）；
    `facts` 若给出则经抽取唯一入口 `settle_story_extraction` 落抽取账（source_chat_turn_id=轮）。
    """
    before = db.capture_chat_rollback_snapshot()
    night_id, chat_id = an.attach_chat_turn_to_night(db, state, minister)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (minister, state.turn, "卿以为如何？"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, reply),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid)
    )
    if writes is not None:
        writes(int(night_id), int(chat_id))
    if facts is not None:
        db.settle_story_extraction(
            int(chat_id), int(night_id), facts, source_night_seq=_night_seq_of(db, chat_id)
        )
    else:
        db.conn.execute(
            "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?", (int(chat_id),)
        )
        db.conn.commit()
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(chat_id), before, after)
    return int(night_id), int(chat_id)


def _reopen(db: GameDB, content) -> GameDB:
    """kill+重开：关旧句柄、按同 path 重开（撤销日志持久化真源，AC6/AC7）。"""
    path = db.path
    db.close()
    return GameDB(path, content)


# ── AC1 / AC2：撤回后按夜取数与「该轮未发生」等价；该轮抽取账/入殿账消失 ──────────


def test_undo_erases_round_from_night_ledger_and_presence(game):
    db, state, content = game
    m = _active_minister(db, content)
    night_id, chat_id = _run_round(
        db, state, m,
        facts=[{"person_names": [m], "presence_effect": "enter",
                "body": "臣入殿奏对辽饷。", "tags": ["军务"]}],
    )
    # 轮内：该轮抽取账在册、入殿账使其在场
    assert any(e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db, night_id))
    assert m in an.persons_present_tonight(db, night_id)

    ledger_before = [e for e in an.list_ledger(db, night_id)
                     if e["source_chat_turn_id"] != chat_id and m not in e["person_names"]]

    db.undo_chat_turn(chat_id)

    ledger_after = an.list_ledger(db, night_id)
    # 该轮抽取账 + 该轮入殿账全消失
    assert not any(e["source_chat_turn_id"] == chat_id for e in ledger_after)
    assert not any(m in e["person_names"] for e in ledger_after)
    # 与「该轮未发生」等价：夜内其余账（开夜/员额框架）一字不动
    assert [e["id"] for e in ledger_after] == [e["id"] for e in ledger_before]
    # 在场推导：该轮入殿的人像没登场过
    assert m not in an.persons_present_tonight(db, night_id)
    # 对话轮不再计入夜（undone 不返回给「按夜取数」）
    assert chat_id not in {int(t["id"]) for t in an.list_chat_turns_for_night(db, night_id)}


# ── AC5：撤回只够到最近一轮；收夜/颁诏封窗后撤回被拒 ────────────────────────────


def test_undo_rejected_after_night_closed(game):
    db, state, content = game
    m = _active_minister(db, content)
    night_id, chat_id = _run_round(
        db, state, m,
        facts=[{"person_names": [m], "presence_effect": "enter", "body": "奏对。"}],
    )
    an.close_night(db, state, night_id=night_id)
    assert an.get_night(db, night_id)["status"] == "closed"
    with pytest.raises(ValueError):
        db.undo_chat_turn(chat_id)
    # 封窗后账仍在（未被误撤）
    assert any(e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db, night_id))


# ── AC8：撤回终结异步残余——后台写入前校验目标轮存活，不写已撤/失败轮 ────────────


def test_settle_extraction_skips_dead_round_but_writes_live_round(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 活轮：抽取正常落账（正向）
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    live_id = db.create_chat_turn(state, m, "", 0, night_id=int(night["id"]))
    db.settle_story_extraction(
        int(live_id), int(night["id"]),
        [{"person_names": [m], "presence_effect": "enter", "body": "臣在。"}],
        source_night_seq=_night_seq_of(db, live_id),
    )
    assert any(e["source_chat_turn_id"] == live_id for e in an.list_ledger(db, int(night["id"])))

    # 死轮：目标轮 undone → 后台抽取写入被拦，零孤儿账（负向）
    dead_id = db.create_chat_turn(state, m, "", 0, night_id=int(night["id"]))
    db.conn.execute("UPDATE chat_turns SET status = 'undone' WHERE id = ?", (int(dead_id),))
    db.conn.commit()
    written = db.settle_story_extraction(
        int(dead_id), int(night["id"]),
        [{"person_names": [m], "presence_effect": "enter", "body": "不该落。"}],
        source_night_seq=_night_seq_of(db, dead_id),
    )
    assert written == []
    assert not any(e["source_chat_turn_id"] == dead_id for e in an.list_ledger(db, int(night["id"])))


# ── AC3：夜内真实盘面直写走可枚举白名单；越权直写被审计咬住 ──────────────────────


def test_night_direct_write_whitelist_enumerates_three_items():
    wl = an.NIGHT_DIRECT_WRITE_WHITELIST
    # 白名单恰三项（#634 落地 ADR 0038 白名单③「召对口关系边事件」）——
    # 新增夜内直写仍须过设计审、显式扩表。
    assert set(wl) == {"密令落地", "未在册人物入册", "召对口关系边事件"}
    assert wl["密令落地"] == frozenset({"secret_orders", "secret_order_briefs"})
    assert wl["未在册人物入册"] == frozenset({"characters", "character_offices"})
    assert wl["召对口关系边事件"] == frozenset({"relation_edge_events"})


def test_audit_passes_whitelisted_and_catches_unwhitelisted_night_write(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 合法夜：仅「密令落地」直写真实盘面 → 审计通过，报出观测到的白名单操作
    def _land_secret(night_id: int, chat_id: int) -> None:
        db.create_secret_order(
            state, m, "密查盐引", "密查两淮盐引亏空", ["盐政"], importance=4,
        )
    legal_night, _ = _run_round(
        db, state, m, writes=_land_secret,
        facts=[{"person_names": [m], "presence_effect": "enter", "body": "领旨。"}],
    )
    assert "密令落地" in an.audit_night_direct_writes(db, legal_night)
    an.close_night(db, state, night_id=legal_night)

    # 越权夜：夜内直写 factions（真实盘面、非白名单——本应走待确认暂存）→ 审计咬住
    def _rogue_direct_write(night_id: int, chat_id: int) -> None:
        fac = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()["name"]
        db.conn.execute(
            "UPDATE factions SET leverage = leverage + 1 WHERE name = ?", (fac,)
        )
        db.conn.commit()
    rogue_night, _ = _run_round(db, state, m, writes=_rogue_direct_write)
    with pytest.raises(AudienceNightError) as ei:
        an.audit_night_direct_writes(db, rogue_night)
    assert ei.value.code == "unwhitelisted_night_write"
    assert "factions" in ei.value.detail.get("tables", [])


# ── AC4：撤回删除该轮新入册人物——档案+入殿账一并消失，像没登场过 ────────────────


def test_undo_removes_unlisted_person_registration(game):
    db, state, content = game
    from ming_sim.models import Character

    caller = _active_minister(db, content)
    newcomer = "临时借调_算学郎中"  # 未在册者

    def _register(night_id: int, chat_id: int) -> None:
        # 白名单②「未在册人物入册」：被宣召的未在册者须即时建档才能开口。
        db.add_character(state, Character(
            name=newcomer, office="翰林院侍读", office_type="翰林院", faction="",
            aliases=[], personal_skills=[], loyalty=60, ability=70,
            integrity=60, courage=50, style="谨饬", power_id="ming",
        ), source="宣召入册")
        an.ensure_summon_enter(db, night_id, newcomer, origin_chat_turn_id=chat_id)

    night_id, chat_id = _run_round(db, state, caller, writes=_register)

    assert db.get_character_status(newcomer)[0] == "active"
    assert newcomer in an.persons_present_tonight(db, night_id)

    db.undo_chat_turn(chat_id)

    # 档案（characters/character_offices）消失
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name = ?", (newcomer,)
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM character_offices WHERE character_name = ?", (newcomer,)
    ).fetchone() is None
    # 入殿账消失 → 在场推导里像没登场过
    assert newcomer not in an.persons_present_tonight(db, night_id)


# ── AC6：kill+重开后撤回最近一轮仍完整逆转（撤销日志持久化）────────────────────


def test_undo_full_reversal_survives_kill_and_reopen(game):
    db, state, content = game
    m = _active_minister(db, content)

    def _land_secret(night_id: int, chat_id: int) -> None:
        db.create_secret_order(state, m, "密查军资", "密查蓟镇军资挪用", ["军务"])
    night_id, chat_id = _run_round(
        db, state, m, writes=_land_secret,
        facts=[{"person_names": [m], "presence_effect": "enter", "body": "领旨。"}],
    )
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 1

    db2 = _reopen(db, content)
    try:
        # 重开后撤销日志仍在 → 撤回照样完整逆转
        db2.undo_chat_turn(chat_id)
        assert db2.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 0
        assert not any(
            e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db2, night_id)
        )
        assert m not in an.persons_present_tonight(db2, night_id)
    finally:
        db2.close()


# ── AC7：撤回×待补——不重新生成该轮账、无孤儿重试入口 ─────────────────────────


def test_undo_pending_extraction_leaves_no_orphan_retry(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 垃圾 shape → 待补（extract_status='pending'），轮未抽落账
    def _mark_pending(night_id: int, chat_id: int) -> None:
        db.mark_story_extraction_pending(int(chat_id))
    night_id, chat_id = _run_round(db, state, m, writes=_mark_pending)
    # 注意 _run_round 无 facts 分支会把水位推到 done——此处显式改回 pending 建待补态
    db.conn.execute("UPDATE chat_turns SET extract_status = 'pending' WHERE id = ?", (chat_id,))
    db.conn.commit()
    assert db.count_pending_story_extractions(night_id=night_id) == 1

    db.undo_chat_turn(chat_id)

    # 撤回后：该轮不再是待补重试真源（无孤儿重试入口），补跑不复活该轮账
    assert db.count_pending_story_extractions(night_id=night_id) == 0
    assert db.list_unextracted_replies(night_id=night_id) == []
    # kill+重开后仍无重试入口（撤销持久）
    db2 = _reopen(db, content)
    try:
        assert db2.count_pending_story_extractions(night_id=night_id) == 0
    finally:
        db2.close()


# ── AC9：撤回整套逆转事务原子——中途崩溃则原样未撤（无半撤回脏档）──────────────


def test_undo_reversal_is_atomic_on_midway_crash(game, monkeypatch):
    db, state, content = game
    m = _active_minister(db, content)

    def _land_secret(night_id: int, chat_id: int) -> None:
        db.create_secret_order(state, m, "密查漕运", "密查漕运折耗", ["漕运"])
    night_id, chat_id = _run_round(
        db, state, m, writes=_land_secret,
        facts=[{"person_names": [m], "presence_effect": "enter", "body": "领旨。"}],
    )

    # 注入撤回逆转事务内的崩溃（末步 agno 截断处）
    def _boom(*_a, **_k):
        raise RuntimeError("注入：撤回中途崩溃")
    monkeypatch.setattr(db, "_truncate_agno_runs_in_tx", _boom)

    with pytest.raises(RuntimeError):
        db.undo_chat_turn(chat_id)

    # 全有或全无：崩溃 → 原样未撤（账/密令/轮状态一律不变，无半撤回脏档）
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 1
    assert any(e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db, night_id))
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id = ?", (chat_id,)
    ).fetchone()["status"] == "active"


# ── AC10：确认轮撤回——被该轮确认的暂存回到待确认（不再随颁诏提交）──────────────


def test_undo_confirm_round_reverts_pending_to_unapproved(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 轮1：暂存一条任免动作（night_approved=0，待确认）
    staged: Dict[str, int] = {}

    def _stage(night_id: int, chat_id: int) -> None:
        staged["id"] = db.stage_pending_action(
            int(state.turn), "office", "任命", m, {"office": "兵部尚书"},
        )
    _run_round(db, state, m, writes=_stage)
    action_id = staged["id"]
    assert db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id = ?", (action_id,)
    ).fetchone()["night_approved"] == 0

    # 轮2：确认该暂存（应允 → night_approved=1，收夜将提交）
    def _confirm(night_id: int, chat_id: int) -> None:
        db.mark_pending_night_approved([action_id], night_id=night_id)
    _, confirm_chat = _run_round(db, state, m, writes=_confirm)
    assert db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id = ?", (action_id,)
    ).fetchone()["night_approved"] == 1

    # 撤回确认轮 → 暂存回到待确认（night_approved=0，不再随颁诏提交），暂存行本身仍在
    db.undo_chat_turn(confirm_chat)
    row = db.conn.execute(
        "SELECT status, night_approved FROM pending_actions WHERE id = ?", (action_id,)
    ).fetchone()
    assert row is not None and row["status"] == "pending" and row["night_approved"] == 0


# ── AC11：被该轮口头拒绝而删除的暂存行复原（回滚该轮对先前对象的变更）──────────────


def test_undo_restores_staging_row_deleted_by_verbal_reject(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 轮1：暂存一条动作
    staged: Dict[str, int] = {}

    def _stage(night_id: int, chat_id: int) -> None:
        staged["id"] = db.stage_pending_action(
            int(state.turn), "office", "任命", m, {"office": "蓟辽总督"},
        )
    _run_round(db, state, m, writes=_stage)
    action_id = staged["id"]

    # 轮2：口头拒绝 → 删该暂存行
    def _reject(night_id: int, chat_id: int) -> None:
        assert db.withdraw_pending_action(action_id, int(state.turn)) is True
    _, reject_chat = _run_round(db, state, m, writes=_reject)
    assert db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id = ?", (action_id,)
    ).fetchone() is None

    # 撤回拒绝轮 → 前像日志据 restore_deleted_row 复原该暂存行（含原 payload）
    db.undo_chat_turn(reject_chat)
    row = db.conn.execute(
        "SELECT status, payload_json FROM pending_actions WHERE id = ?", (action_id,)
    ).fetchone()
    assert row is not None and row["status"] == "pending"
    assert "蓟辽总督" in row["payload_json"]


# ── AC12：已落地密令撤回后其全部结构化字段记录一并消失（无幽灵排除）──────────────


def test_undo_landed_secret_decree_removes_all_structured_records(game):
    db, state, content = game
    m = _active_minister(db, content)

    def _land(night_id: int, chat_id: int) -> None:
        db.create_secret_order(
            state, m, "密核盐课", "密核长芦盐课隐没", ["盐政", "稽核"],
            importance=5, deadline_months=6,
            excluded_names=[_active_minister(db, content, exclude={m})],
            excluded_offices=["户部"],
        )
    night_id, chat_id = _run_round(
        db, state, m, writes=_land,
        facts=[{"person_names": [m], "presence_effect": "enter", "body": "领旨。"}],
    )
    order_id = int(db.conn.execute("SELECT id FROM secret_orders").fetchone()["id"])
    # 落地时结构化字段（标题/期限/标签/排除名单/机构级映射）+ 简报（承办人/知情圈）齐备
    row = db.conn.execute(
        "SELECT title, due_turn, tags, excluded_names, excluded_targets "
        "FROM secret_orders WHERE id = ?", (order_id,)
    ).fetchone()
    assert row["title"] and row["excluded_names"] != "[]" and row["excluded_targets"] != "{}"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id = ?", (order_id,)
    ).fetchone()[0] == 1

    db.undo_chat_turn(chat_id)

    # 密令行 + 全部结构化字段随行消失；简报（承办人/知情圈 payload）一并消失——无幽灵排除
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE id = ?", (order_id,)
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id = ?", (order_id,)
    ).fetchone()[0] == 0


# ── L1（judge R1 S-exit-origin-unbound）：令退轮撤回 → 告退账消失 + 在场复原 ──────
# 病根：dismiss_from_audience 落告退账时不绑本轮，undo 删不掉 → 按夜取数 ≠ 未发生，
# 且被令退者永久差出（双轮场景在场不复原）。


def test_undo_dismiss_round_removes_exit_ledger_and_restores_presence(game):
    """round1 入殿 → round2 令退（绑本轮）→ undo round2 → 告退账消失且该人复在场。"""
    db, state, content = game
    m = _active_minister(db, content)
    # round1：入殿（无结构化写）
    n1, _c1 = _run_round(db, state, m)
    assert m in an.present_names_at(db, n1)
    # round2：令退，告退账绑本轮 chat_id
    n2, c2 = _run_round(
        db, state, m,
        writes=lambda night_id, chat_id: an.dismiss_from_audience(
            db, m, origin_chat_turn_id=chat_id
        ),
    )
    assert n2 == n1
    # 令退落地：不在场（present_names_at 消费口令 TAG_EXIT）+ 告退账在册
    assert m not in an.present_names_at(db, n1)
    assert any(an.TAG_EXIT in (e["tags"] or []) and m in e["person_names"]
               for e in an.list_ledger(db, n1))

    db.undo_chat_turn(c2)

    # 告退账消失（origin 绑本轮，随撤回删）
    assert not any(an.TAG_EXIT in (e["tags"] or []) and m in e["person_names"]
                   for e in an.list_ledger(db, n1))
    # 在场复原（round1 入殿仍在）——被令退者不再永久差出
    assert m in an.present_names_at(db, n1)


def test_undo_single_round_enter_and_dismiss_equals_not_happened(game):
    """单轮内入殿+令退，undo 后账与在场均 ≡ 该轮未发生（入殿账 origin 也绑本轮）。"""
    db, state, content = game
    m = _active_minister(db, content)
    n1, c1 = _run_round(
        db, state, m,
        writes=lambda night_id, chat_id: an.dismiss_from_audience(
            db, m, origin_chat_turn_id=chat_id
        ),
    )
    # 本轮产了入殿账（attach）+ 告退账（dismiss），二者皆绑本轮
    round_entries = [e for e in an.list_ledger(db, n1)
                     if e["origin_chat_turn_id"] == c1 and m in e["person_names"]]
    assert any(an.TAG_ENTER in (e["tags"] or []) for e in round_entries)
    assert any(an.TAG_EXIT in (e["tags"] or []) for e in round_entries)

    db.undo_chat_turn(c1)

    # 该轮所产入殿/告退账全消失；在场无该人——像本轮从未发生
    assert not any(m in e["person_names"] for e in an.list_ledger(db, n1))
    assert m not in an.present_names_at(db, n1)


# ── L2（judge R1 S-origin-bind-non-atomic）：入殿账 origin 绑定须原子 ──────────────
# 病根：入殿账 commit → 建轮 commit → 单独 UPDATE origin，中途崩溃留 origin=0 孤儿入殿账，
# 后续撤回删不掉（与 L1 同形脏账）。修法：enter+建轮+回绑 origin 整段原子。


def test_attach_origin_bind_atomic_no_orphan_enter_on_midway_crash(game):
    """注入建轮崩溃（enter 已落、origin 未绑）→ atomic 回滚 → 无 origin=0 孤儿入殿账。"""
    db, state, content = game
    m = _active_minister(db, content)
    an.open_night(db, state)
    night_id = int(an.get_open_night(db)["id"])
    assert m not in an.persons_present_tonight(db, night_id)  # m 非常在员额
    ledger_ids_before = {e["id"] for e in an.list_ledger(db, night_id)}

    orig_create = db.create_chat_turn

    def _boom(*a, **k):
        raise RuntimeError("inject crash: enter 已落、origin 未绑")

    db.create_chat_turn = _boom
    try:
        with pytest.raises(RuntimeError):
            an.attach_chat_turn_to_night(db, state, m)
    finally:
        db.create_chat_turn = orig_create

    # atomic 回滚：账本零净增，无孤儿入殿账，在场未变
    assert {e["id"] for e in an.list_ledger(db, night_id)} == ledger_ids_before
    assert m not in an.persons_present_tonight(db, night_id)


def test_attach_origin_bind_atomic_normal_path_binds_and_undo_deletes(game):
    """正常路径：入殿账 origin 绑本轮（非 0），undo 仍删该入殿账。"""
    db, state, content = game
    m = _active_minister(db, content)
    # _run_round 内经 attach 入殿 + 落回话（轮转 active，可撤回）
    night_id, chat_id = _run_round(db, state, m)
    enter = [e for e in an.list_ledger(db, night_id)
             if an.TAG_ENTER in (e["tags"] or []) and m in e["person_names"]]
    assert enter and all(e["origin_chat_turn_id"] == chat_id for e in enter)

    db.undo_chat_turn(chat_id)

    assert not any(an.TAG_ENTER in (e["tags"] or []) and m in e["person_names"]
                   for e in an.list_ledger(db, night_id))


# ── 旧档升级路径：chat_turns.undone_at 缺列 → open 补列 → undo 逆转 ─────────────
# undone_at 进 CREATE TABLE 晚于该表初版；缺 ensure_column 时旧档 undo 的
# UPDATE ... SET undone_at 会 OperationalError（no such column）→ 整撤回回滚。


def test_undo_survives_db_created_before_undone_at_column(game):
    db, state, content = game
    m = _active_minister(db, content)
    night_id, chat_id = _run_round(db, state, m)

    # 模拟旧档：chat_turns 建于 undone_at 进 CREATE 之前（列不存在）。
    db.conn.execute("ALTER TABLE chat_turns DROP COLUMN undone_at")
    db.conn.commit()
    assert "undone_at" not in {
        r["name"] for r in db.conn.execute("PRAGMA table_info(chat_turns)").fetchall()
    }

    # 重开 → GameDB 升级迁移必须补回该列（ensure_column），而非留待 undo 时炸。
    db2 = _reopen(db, content)
    try:
        assert "undone_at" in {
            r["name"] for r in db2.conn.execute("PRAGMA table_info(chat_turns)").fetchall()
        }
        db2.undo_chat_turn(chat_id)
        row = db2.conn.execute(
            "SELECT status, undone_at FROM chat_turns WHERE id = ?", (int(chat_id),)
        ).fetchone()
        assert row["status"] == "undone"
        assert row["undone_at"]
    finally:
        db2.close()
