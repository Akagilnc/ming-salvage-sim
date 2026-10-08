"""#506 撤回本轮效果逆转（轮级撤销日志 / 白名单审计，ADR 0038 cmr R1 修订版）。

一条贯穿真实入口：召对夜里一「轮」= 一次玩家发话到下一次发话的完整交换，落为一条
`chat_turns` 行。生产走 `capture_chat_rollback_snapshot`（轮前）→ 该轮全部写入 →
`record_chat_turn_rollback_diffs`（轮后，前像撤销日志）→ `undo_chat_turn`（逆转）。
本文件按同一 seam 驱动、断 DB/账本/在场末态，覆盖 AC1–AC12。

不锁 LLM 叙事正文；不接受 failed 当成功。
"""

from __future__ import annotations
from tests.conftest import open_hall_turn

import json
from typing import Callable, Dict, Mapping, Optional

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_night import AudienceNightError
from ming_sim.audience_translation import apply_audience_round_translation, mark_turn_translation_done
from ming_sim.db import GameDB
from tests.dossier_test_helpers import create_test_secret_order


from tests.test_audience_night_498 import _active_minister

def _run_round(
    db: GameDB,
    state,
    minister: str,
    *,
    writes: Optional[Callable[[int, int], None]] = None,
    declaration: Optional[Mapping[str, object]] = None,
    reply: str = "臣遵旨。",
) -> tuple[int, int]:
    """跑一「轮」——严格复刻 web_app 的轮窗口 seam。

    `writes(night_id, chat_id)` 在轮窗口内做该轮的结构化写（暂存/密令落地/入册等）；
    `declaration` 若给出则经现役转译入口落账；否则只推进空轮水位。
    """
    before = db.capture_chat_rollback_snapshot()
    night_id, chat_id = open_hall_turn(db, state, minister)
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
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(chat_id), before, after)
    if declaration is not None:
        apply_audience_round_translation(
            db, state, declaration, night_id=int(night_id),
            chat_turn_id=int(chat_id), minister_name=minister,
        )
    else:
        mark_turn_translation_done(db, int(chat_id))
    return int(night_id), int(chat_id)


def _minister_declaration(minister: str, presence_body: str) -> dict[str, object]:
    return {
        "presence": [{"person_name": minister, "effect": "enter", "body": presence_body}],
        "scene_facts": [{
            "body": "臣遵旨。", "role": "minister", "audibility": "殿上公开",
            "person_names": [minister], "tags": ["scroll_role:minister"],
        }],
    }


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
        declaration=_minister_declaration(m, "臣入殿奏对辽饷。"),
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
        declaration=_minister_declaration(m, "奏对。"),
    )
    an.close_night(db, state, night_id=night_id)
    assert an.get_night(db, night_id)["status"] == "closed"
    with pytest.raises(ValueError):
        db.undo_chat_turn(chat_id)
    # 封窗后账仍在（未被误撤）
    assert any(e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db, night_id))


# ── AC8：撤回终结异步残余——后台写入前校验目标轮存活，不写已撤/失败轮 ────────────


# ── AC3：夜内真实盘面直写走可枚举白名单；越权直写被审计咬住 ──────────────────────


def test_night_direct_write_whitelist_enumerates_authorized_items():
    wl = an.NIGHT_DIRECT_WRITE_WHITELIST
    # ADR 0038：①密令落地；②转译声明的当场实况（#1839 第四类，原入册/边事件并入）。
    # 新增夜内直写仍须过设计审、显式扩表。
    assert set(wl) == {"密令落地", "转译声明的当场实况"}
    assert wl["密令落地"] == frozenset({"secret_orders", "secret_order_briefs"})
    fourth = wl["转译声明的当场实况"]
    assert {"characters", "character_offices", "relation_edge_events"} <= set(fourth)
    assert {"textual_facts", "public_sayings", "story_ledger_entries"} <= set(fourth)
def test_audit_passes_whitelisted_and_catches_unwhitelisted_night_write(game):
    db, state, content = game
    m = _active_minister(db, content)

    # 合法夜：仅「密令落地」直写真实盘面 → 审计通过，报出观测到的白名单操作
    def _land_secret(night_id: int, chat_id: int) -> None:
        create_test_secret_order(db,
            state, m, "密查盐引", "密查两淮盐引亏空", ["盐政"], importance=4,
        )
    legal_night, _ = _run_round(
        db, state, m, writes=_land_secret,
        declaration=_minister_declaration(m, "领旨。"),
    )
    assert "密令落地" in an.audit_night_direct_writes(db, legal_night)
    an.close_night(db, state, night_id=legal_night)

    # 越权夜：不经结算直写案卷月度进展，仍须被审计咬住。
    def _rogue_direct_write(night_id: int, chat_id: int) -> None:
        dossier = db.conn.execute("SELECT id FROM decree_dossiers LIMIT 1").fetchone()
        assert dossier is not None
        db.conn.execute(
            "INSERT INTO dossier_reported_progress "
            "(dossier_id, turn, progress_band, memorial_text, origin) "
            "VALUES (?, ?, '进行中', '越权记录', 'night')",
            (int(dossier["id"]), int(state.turn)),
        )
        db.conn.commit()
    rogue_night, _ = _run_round(db, state, m, writes=_rogue_direct_write)
    with pytest.raises(AudienceNightError) as ei:
        an.audit_night_direct_writes(db, rogue_night)
    assert ei.value.code == "unwhitelisted_night_write"
    assert "dossier_reported_progress" in ei.value.detail.get("tables", [])
