"""开局帝国修正（legacy）清算与落库：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations
from ming_sim.applier import parse_engine_payload_json

import ming_sim.issues as issues

from typing import List

from ming_sim.db import (
    GameDB,
)
from ming_sim.models import GameState


def clear_gated_legacies(db: GameDB, state: GameState) -> List[str]:
    """每月调一次：取所有 active 且带 clear_gate 的 legacy，gate 达标即置 'cleared'。
    返回被消除的 legacy 名称列表（供叙事/提示用，不强制使用）。"""
    rows = db.conn.execute(
        'SELECT id, name, clear_gate, narrative_hint FROM legacies WHERE '
        "status='active' AND clear_gate != '' AND clear_gate != '{}'",
        (),
    ).fetchall()
    cleared: List[str] = []
    for row in rows:
        gate = parse_engine_payload_json(
            row["clear_gate"],
        )
        if not gate:
            continue
        if issues._gate_passed(gate, state.metrics, db):
            db.reign.set_legacy_statuses([("cleared", int(row["id"]))])
            cleared.append(str(row["name"]))
    if cleared:
        db._legacy_mod_cache = None  # active 集变了，修正符缓存失效
    return cleared


def sync_opening_legacies(db: GameDB, state: GameState) -> None:
    """开局负面帝国修正落库/校准。新档与读档都调（在 session.__init__ load_state 之后）：
    - 已达 clear_gate：不补；若残留 active 则置 cleared。
    - 未达标：该 legacy_key 不存在 active 行则 insert（永久 duration=-1，仅靠 gate 消除）。
    一个函数覆盖新档（全补）/旧档（补缺）/达标档（不补/清残）。"""
    for leg in issues._ctx().opening_legacies:
        passed = issues._gate_passed(leg.clear_gate, state.metrics, db)
        if db.reign.sync_opening_legacy(
            legacy_key=leg.key, name=leg.name, modifiers=leg.modifiers,
            narrative_hint=leg.narrative_hint, clear_gate=leg.clear_gate,
            passed=passed, start_month=int(state.year) * 12 + int(state.period),
        ):
            db._legacy_mod_cache = None
