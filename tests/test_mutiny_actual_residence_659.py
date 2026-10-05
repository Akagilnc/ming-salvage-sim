"""#659：军队结构化实际驻地 → 财政事实属地 / S7 军镇 / 逃亡人口闭环。

票面根修：station_region=regions.id；station 只做人读细地点；欠饷事实 region
改取 station_region（饷源 pay_source_region 只服务分账）；逃亡落既有
population_transfers。禁止 station 文本解析、第二事实核、第二转移核。

本文件验证调防后的驻地与饷源分离、非法驻地拒收，以及新档驻地和人口切片。
"""

from __future__ import annotations

import os
import shutil

from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.models import Event

# content/classes.json 冻结字面（施工 oracle，非实现推导）
JUNHU_LIAODONG = 230000
JUNHU_DONGJIANG = 95000
LIUMIN_LIAODONG = 0
LIUMIN_DONGJIANG = 0



def _pseudo_event(title: str = "调防") -> Event:
    return Event(
        id="test_659", title=title, kind="圣旨", summary="",
        urgency=0, severity=0, credibility=100, interests=[], audiences=[],
    )







def test_station_region_rejects_unknown_region_id(game):
    """非空 station_region 必须是已入库 regions.id；不从 station 反推。"""
    db, state, _content = game
    changes = db.apply_army_deltas(
        state, _pseudo_event(), None, "test",
        {"dongjiang": {"station_region": "not_a_real_region", "reason": "坏 id"}},
    )
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected and rejected[0]["field"] == "station_region"
    row = db.conn.execute(
        "SELECT station_region FROM armies WHERE id='dongjiang'"
    ).fetchone()
    assert row["station_region"] == "dongjiang_area"
