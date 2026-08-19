"""#1274 QA A-3：seed 数据残余（#1283 stage_text + #1289 巡抚实名）。

只钉 content 静态口径；seed 仅对新档生效，不碰 DB/引擎。
"""

from __future__ import annotations

import re
from pathlib import Path

from ming_sim.content import load_character_content, load_event_content

ROOT = Path(__file__).resolve().parents[1]


def _liaodong_seed():
    events = load_event_content("seed_events.json")
    by_id = {ev.id: ev for ev in events}
    assert "liaodong" in by_id, "seed_events 须含辽东索饷 id=liaodong"
    return by_id["liaodong"]


def _opening_gazette_text() -> str:
    return (ROOT / "content" / "opening_gazette.md").read_text(encoding="utf-8")


def test_liaodong_stage_text_does_not_name_bajiu_offstage_as_active_petitioners():
    """#1283 残余：stage_text 不得写罢居者「连章告急」（与名册 offstage 清洗矛盾）。"""
    _, characters = load_character_content()
    bajiu_names = {
        name
        for name, ch in characters.items()
        if "罢居" in (ch.office or "")
    }
    # 开局清洗后进人才池的两位，必须在 seed office 串里带罢居标记
    assert {"袁崇焕", "孙承宗"} <= bajiu_names

    stage = _liaodong_seed().stage_text
    for name in ("袁崇焕", "孙承宗"):
        assert name not in stage, f"辽东索饷 stage_text 仍点名罢居者 {name!r}: {stage!r}"


def test_liaodong_stage_text_arrears_months_match_opening_gazette():
    """#1283 残余：欠饷月数与 opening_gazette「逾五月」统一（以邸报为准）。"""
    gazette = _opening_gazette_text()
    assert "欠饷已逾五月" in gazette
    assert re.search(r"欠饷五月", gazette), "opening_gazette 待办条亦写欠饷五月"

    stage = _liaodong_seed().stage_text
    assert "三月" not in stage, f"stage_text 仍写三月，未与邸报统一: {stage!r}"
    assert "五月" in stage, f"stage_text 须与邸报同口径含五月: {stage!r}"


def test_liaodong_stage_text_names_roster_active_or_is_anonymous():
    """叙事可点在任名册人物，或去点名；若点名则每人须在 characters 且非罢居串。"""
    _, characters = load_character_content()
    stage = _liaodong_seed().stage_text
    # 粗抓连续中文人名（2–4 字），再与名册求交——只约束点到名册的名字
    candidates = set(re.findall(r"[\u4e00-\u9fff]{2,4}", stage))
    named = candidates & set(characters)
    assert named or ("将" in stage or "边" in stage), (
        "stage_text 既未点名册人物，也未保留将领/边情叙事质感"
    )
    for name in named:
        office = characters[name].office or ""
        assert "罢居" not in office, f"点名 {name} 仍是罢居串: {office!r}"


def test_three_located_xunfu_offices_carry_province_or_zhen_title():
    """#1289：location 已有的三人 office 不得光秃「巡抚」。"""
    _, characters = load_character_content()
    expected = {
        "邹维琏": ("fujian", ("福建",)),
        "练国事": ("shaanxi", ("陕西",)),
        # 焦源溥 summary/portrait 锚定大同巡抚；location=shanxi 表示任事山西边地
        "焦源溥": ("shanxi", ("大同", "山西")),
    }
    for name, (loc, tokens) in expected.items():
        ch = characters[name]
        assert ch.location == loc, f"{name} location 漂移: {ch.location!r}"
        assert ch.office != "巡抚", f"{name} office 仍光秃巡抚"
        assert any(t in ch.office for t in tokens), (
            f"{name} office={ch.office!r} 未含 {tokens}"
        )


def test_li_daiwen_province_left_open_when_unproven():
    """#1289：李待问 location 空；仓内 portrait 作松江殉难中书舍人，1627 应天巡抚无实据——禁臆补。"""
    _, characters = load_character_content()
    ch = characters["李待问"]
    assert (ch.location or "") == ""
    # 不得臆写应天/南直隶等未核省份
    for banned in ("应天", "南直隶", "松江", "江南"):
        assert banned not in (ch.office or ""), (
            f"李待问 office 臆补了未核地望 {banned!r}: {ch.office!r}"
        )
