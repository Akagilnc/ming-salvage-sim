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
    assert m in an.present_names_at(db, night_id)

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
    assert m not in an.present_names_at(db, night_id)
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


