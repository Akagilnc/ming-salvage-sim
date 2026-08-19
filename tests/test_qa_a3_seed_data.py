"""#1274 QA A-3：seed 数据残余（#1283 stage_text + #1289 巡抚实名）。

只钉 content 静态口径；seed 仅对新档生效，不碰 DB/引擎。
"""

from __future__ import annotations

import re
from pathlib import Path

from ming_sim.content import load_character_content, load_event_content
from ming_sim.db import normalize_office
from ming_sim.intelligence import OFFICE_SLOTS

ROOT = Path(__file__).resolve().parents[1]


def _liaodong_seed():
    events = load_event_content("seed_events.json")
    by_id = {ev.id: ev for ev in events}
    assert "liaodong" in by_id, "seed_events 须含辽东索饷 id=liaodong"
    return by_id["liaodong"]


def _opening_gazette_text() -> str:
    return (ROOT / "content" / "opening_gazette.md").read_text(encoding="utf-8")


def _arrears_month_tokens(text: str) -> set[str]:
    """Extract 欠饷…N月 month tokens; consistency-only, no gazette wording pin."""
    return set(re.findall(r"欠饷[^\n。；]{0,12}?([元正一二三四五六七八九十两]+)月", text))


def test_liaodong_stage_text_does_not_name_bajiu_offstage_as_active_petitioners():
    """#1283 残余：stage_text 不得写罢居者作在任请饷人；点名须落在任名册。"""
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

    # 若点到名册人物，每人须非罢居串；允许匿名将领/边情质感
    candidates = set(re.findall(r"[\u4e00-\u9fff]{2,4}", stage))
    named = candidates & set(characters)
    assert named or ("将" in stage or "边" in stage), (
        "stage_text 既未点名册人物，也未保留将领/边情叙事质感"
    )
    for name in named:
        office = characters[name].office or ""
        assert "罢居" not in office, f"点名 {name} 仍是罢居串: {office!r}"


def test_liaodong_stage_text_arrears_months_match_opening_gazette():
    """#1283 残余：欠饷月数只钉 stage↔gazette 口径一致（不钉邸报原句）。"""
    gazette = _opening_gazette_text()
    stage = _liaodong_seed().stage_text
    gazette_months = _arrears_month_tokens(gazette)
    stage_months = _arrears_month_tokens(stage)
    assert gazette_months, "opening_gazette 须含欠饷月数以便对照"
    assert stage_months, f"stage_text 须含欠饷月数: {stage!r}"
    assert stage_months <= gazette_months, (
        f"stage 欠饷月数 {stage_months} 与 gazette {gazette_months} 口径不一致"
    )


def test_active_seed_characters_do_not_occupy_office_slots():
    """不变式：active seed 人物 normalize_office 不得等于 OFFICE_SLOTS 任一 title。

    office_vacancies 以精确等值匹配 holder；未票面任命不得字面占虚悬缺。
    """
    slot_titles = {slot[0] for slot in OFFICE_SLOTS}
    assert slot_titles, "OFFICE_SLOTS 不得为空"
    _, characters = load_character_content()
    offenders: list[str] = []
    for name, ch in characters.items():
        if (ch.status or "") != "active":
            continue
        office_n = normalize_office(ch.office or "")
        parts = [p.strip() for p in office_n.split(",") if p.strip()]
        hit = [p for p in parts if p in slot_titles]
        if hit:
            offenders.append(f"{name}: office={ch.office!r} occupies {hit}")
    assert not offenders, (
        "active seed 字面占用 OFFICE_SLOTS（须票面任命或退回非 slot 衔）:\n"
        + "\n".join(offenders)
    )


def test_settled_located_xunfu_offices_carry_province_or_zhen_title():
    """#1289：已结清的二人 office 不得光秃「巡抚」（练国事陕抚时序 defer owner）。"""
    _, characters = load_character_content()
    expected = {
        "邹维琏": ("fujian", ("福建",)),
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


def test_li_daiwen_office_forbids_unproven_province_tokens():
    """#1289：李待问 office 禁臆补应天/南直隶/松江/江南（省份待 owner，不钉 location 永约）。"""
    _, characters = load_character_content()
    ch = characters["李待问"]
    for banned in ("应天", "南直隶", "松江", "江南"):
        assert banned not in (ch.office or ""), (
            f"李待问 office 臆补了未核地望 {banned!r}: {ch.office!r}"
        )
