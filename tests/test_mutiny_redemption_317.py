"""#317 — 连续满饷兑换军心上限，且进度跨存档持久。"""
from __future__ import annotations

import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.flows import apply_fixed_period_flows

ARMY = "guanning"


def _configure(db) -> None:
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1
           WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()

