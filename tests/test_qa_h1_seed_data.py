"""#1274 QA 包辛 H-1：seed 扩修钉测（#1359/#1360/#1365/#1361）。

只钉 content/seed 静态口径 + 开局贯通；禁臆写史实、禁动引擎。
与 #1404（关宁 commander 同域 backlog）关系：本片按 opening_gazette 落地分统口径，
#1404 若另定单名主官须对照本钉与 gazette 再开。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ming_sim.content import load_character_content, load_event_content
from ming_sim.db import GameDB
from ming_sim.models import GameState

ROOT = Path(__file__).resolve().parents[1]


def _armies_seed() -> list[dict]:
    data = json.loads((ROOT / "content" / "armies.json").read_text(encoding="utf-8"))
    return list(data["armies"])


def _army_by_id(aid: str) -> dict:
    for item in _armies_seed():
        if item["id"] == aid:
            return item
    raise AssertionError(f"armies.json 缺 id={aid}")


def _bajiu_names(characters: dict) -> set[str]:
    return {
        name
        for name, ch in characters.items()
        if "罢居" in (ch.office or "")
    }


def _deficit_seed():
    events = load_event_content("seed_events.json")
    by_id = {ev.id: ev for ev in events}
    assert "deficit" in by_id
    return by_id["deficit"]


def test_guanning_commander_not_bajiu_offstage_yuan():
    """#1359：关宁 commander 不得是罢居袁崇焕；须与 opening_gazette 分统口径一致。

    gazette：「关外无主帅。关宁军由祖大寿、何可纲、赵率教分统」。
    controller（A-3 已改）与 commander 同落分统名，禁再写袁崇焕。
    """
    _, characters = load_character_content()
    assert "罢居" in (characters["袁崇焕"].office or "")
    army = _army_by_id("guanning")
    commander = army["commander"]
    controller = army["controller"]
    assert commander != "袁崇焕", commander
    assert "袁崇焕" not in commander
    # 分统三人须同时出现在 commander（与 gazette / controller 同口径）
    for name in ("祖大寿", "何可纲", "赵率教"):
        assert name in commander, f"commander 缺分统 {name}: {commander!r}"
        assert name in controller, f"controller 缺分统 {name}: {controller!r}"
    # 若 commander 点到名册人物，不得是罢居串
    named = set(re.findall(r"[\u4e00-\u9fff]{2,4}", commander)) & set(characters)
    for name in named:
        assert "罢居" not in (characters[name].office or ""), (
            f"关宁 commander 点名罢居者 {name}"
        )


def test_dongjiang_commander_is_active_mao_wenlong():
    """#1360：1627.10 毛文龙仍在镇；commander 须为毛文龙，禁「毛文龙旧部」。"""
    _, characters = load_character_content()
    mao = characters["毛文龙"]
    assert "东江" in (mao.office or "") and "总兵" in (mao.office or ""), mao.office
    assert (mao.status or "active") == "active"
    army = _army_by_id("dongjiang")
    assert army["commander"] == "毛文龙", army["commander"]
    assert "旧部" not in army["commander"]


def test_seed_army_firearms_differentiated_within_p2_caps():
    """#1365：seed 军火器/随军炮须差异化，且落在 P2 上限内（火器 0-100、炮 0-12）。

    关宁含炮兵须有随军炮；禁全军同一 firearm/cannon 拍数。
    """
    armies = _armies_seed()
    assert len(armies) >= 10
    firearms = []
    cannons = []
    for item in armies:
        fe = int(item.get("firearm_equipment", -1))
        ce = int(item.get("cannon_equipment", -1))
        assert 0 <= fe <= 100, f"{item['id']} firearm_equipment={fe} 越 P2"
        assert 0 <= ce <= 12, f"{item['id']} cannon_equipment={ce} 越 P2 cap12"
        firearms.append(fe)
        cannons.append(ce)
    assert len(set(firearms)) >= 4, f"火器未差异化: {firearms}"
    assert any(c > 0 for c in cannons), "全军炮=0，含炮兵军未配随军炮"
    guanning = _army_by_id("guanning")
    assert "炮兵" in guanning["troop_type"]
    assert int(guanning["firearm_equipment"]) >= 55
    assert int(guanning["cannon_equipment"]) >= 4
    # 内地卫所/土司弱于边镇炮兵
    nanjing = _army_by_id("nanjing_garrison")
    tusi = _army_by_id("southwest_tusi")
    assert int(nanjing["firearm_equipment"]) < int(guanning["firearm_equipment"])
    assert int(tusi["firearm_equipment"]) < int(guanning["firearm_equipment"])
    assert int(nanjing["cannon_equipment"]) < int(guanning["cannon_equipment"])


def test_fresh_seed_army_equipment_and_commanders_wire_through(content):
    """开局贯通：DB 军队火器/炮与统帅名分与 seed 一致；统帅人物卡状态不自相矛盾。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        rows = {
            r["id"]: dict(r)
            for r in db.conn.execute(
                "SELECT id, commander, controller, firearm_equipment, cannon_equipment "
                "FROM armies"
            ).fetchall()
        }
        g = rows["guanning"]
        assert "袁崇焕" not in g["commander"]
        assert int(g["cannon_equipment"]) >= 4
        assert int(g["firearm_equipment"]) >= 55
        d = rows["dongjiang"]
        assert d["commander"] == "毛文龙"
        # 人物卡：毛文龙 active；袁崇焕不得仍是 commander
        mao = db.conn.execute(
            "SELECT status, office FROM characters WHERE name='毛文龙'"
        ).fetchone()
        assert mao["status"] == "active"
        yuan = db.conn.execute(
            "SELECT status FROM characters WHERE name='袁崇焕'"
        ).fetchone()
        assert yuan["status"] == "offstage"
        # P2 上限贯通
        for r in rows.values():
            assert 0 <= int(r["firearm_equipment"]) <= 100
            assert 0 <= int(r["cannon_equipment"]) <= 12
        # 非全军同一数
        assert len({int(r["firearm_equipment"]) for r in rows.values()}) >= 4
        assert any(int(r["cannon_equipment"]) > 0 for r in rows.values())
    finally:
        if db is not None:
            db.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def test_deficit_stage_text_aligns_with_opening_treasury_and_hubu():
    """#1361：户部亏空 stage_text 不得与开局国库实数/户部尚书名分恒冲突。

    诊断：seed 静态「不足三百万」vs 开局 metrics 国库=320；毕自严=南京户部，
    户部尚书=郭允厚。修法=定性奏报口吻 + 具题人对齐在任户部尚书。
    """
    _, characters = load_character_content()
    guo = characters["郭允厚"]
    bi = characters["毕自严"]
    assert "户部尚书" in (guo.office or "") and "南京" not in (guo.office or ""), guo.office
    assert "南京" in (bi.office or ""), bi.office

    ev = _deficit_seed()
    stage = ev.stage_text or ""
    assert "毕自严" not in stage, f"具题人仍是南京户书: {stage!r}"
    assert "郭允厚" in stage, stage
    # 禁与开局国库 320 恒冲突的「不足三百万」硬数；允许定性或对齐实数
    assert "不足三百万" not in stage, stage
    # 若仍写具体「百万」量级，不得宣称低于开局国库
    m = re.search(r"不足\s*([一二三四五六七八九十百千万0-9]+)\s*万", stage)
    assert m is None, f"仍用不足X万硬数易与账本漂移冲突: {stage!r}"

    # audiences 须含在任户部尚书，召对注入才对口
    audiences = list(ev.audiences or [])
    assert "郭允厚" in audiences, audiences

    # 开局国库硬锚（models.GameState 默认 = seed 贯通）
    assert GameState().metrics["国库"] == 320
