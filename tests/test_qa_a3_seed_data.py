"""#1274 QA A-3/A-3b：seed 数据残余（#1283/#1289 + #1284/#1308 史实尾单）。

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

    # #1406：正则 [\u4e00-\u9fff]{2,4} 会把「赵率教交章」切成「赵率教交」，
    # 使赵率教缺席 named 仍绿。显式钉两位请饷人在 stage 且 active。
    petitioners = {"祖大寿", "赵率教"}
    assert petitioners <= set(characters), "辽东索饷请饷人须存在于 seed 名册"
    assert all(name in stage for name in petitioners), (
        f"stage_text 须点名 {sorted(petitioners)}: {stage!r}"
    )
    assert all(characters[name].status == "active" for name in petitioners), (
        "辽东索饷请饷人须为 active seed 人物"
    )
    # 若点到名册人物，每人须非罢居串；允许匿名将领/边情质感
    named = {name for name in characters if name in stage}
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


def test_lai_zongdao_remains_opening_libu_shangshu():
    """#1284：1627.10 史实礼部尚书=来宗道（兼东阁），保留不改。"""
    _, characters = load_character_content()
    lai = characters["来宗道"]
    assert "礼部尚书" in (lai.office or ""), lai.office
    assert "东阁大学士" in (lai.office or ""), lai.office


def test_wen_tiren_opening_office_is_libu_you_shilang():
    """#1284：1627.10 温体仁史实=礼部右侍郎（崇祯元年方迁尚书；升迁走游戏内任免，无 timeline）。"""
    _, characters = load_character_content()
    wen = characters["温体仁"]
    assert (wen.office or "") == "礼部右侍郎", wen.office


def test_seed_has_exactly_one_active_libu_shangshu():
    """#1284 不变式：active seed 精确分项「礼部尚书」恰一人（来宗道），无双尚书叠座。

    「前礼部尚书」等前衔/罢居串不算当期占缺（normalize 分项精确等值）。
    """
    _, characters = load_character_content()
    holders = [
        name
        for name, ch in characters.items()
        if (ch.status or "") == "active"
        and "礼部尚书"
        in [p.strip() for p in normalize_office(ch.office or "").split(",") if p.strip()]
    ]
    assert holders == ["来宗道"], f"开局礼部尚书 holders={holders!r}（须唯一来宗道）"


def test_zhang_fengyi_office_strips_future_title():
    """#1308 残余：张凤翼 office 不得含「后…」未来官职；只留当期名分。

仓内 raw/portrait 仅有「总督」+生涯「后兵部尚书」旁注，无 1627 地望实据，
故清成光秃「总督」，禁臆补宣大/保定等（同李待问不臆补地望）。
"""
    _, characters = load_character_content()
    ch = characters["张凤翼"]
    office = ch.office or ""
    assert "后" not in office, f"仍含未来官职旁注: {office!r}"
    assert "兵部尚书" not in office, f"未来兵书不得入当期 office: {office!r}"
    assert office == "总督", f"当期名分偏离仓内可核口径: {office!r}"


def test_qian_qianyi_seed_office_records_bajiu_dismissal():
    """#1308 残余：钱谦益 seed office 须记削籍罢居（非空）；运行时空 office 是 ADR 0009 清洗。

仓内 raw/minister/portrait 一致：前礼部右侍郎，罢居常熟（天启科场案削籍在野）。
"""
    _, characters = load_character_content()
    ch = characters["钱谦益"]
    office = ch.office or ""
    assert office.strip(), "seed office 不得空——运行时 dismissed 清空是 migration，不是 seed 缺史实"
    assert "罢居" in office, office
    assert "礼部" in office and "侍郎" in office, office
