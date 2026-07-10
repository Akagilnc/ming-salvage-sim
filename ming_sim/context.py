"""上下文生成与文本匹配：历史锚点、胜负判定、地区/军队/事件模糊匹配、
人物/事件上下文串、给 LLM 的 state_context。L4。

通过 bind_content() 注入 GameContent（过渡期）。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from ming_sim.constants import ECONOMY_ACCOUNTS, TURN_UNIT
from ming_sim.assets import format_money, format_money_delta
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.exceptions import LLMContractError
from ming_sim.models import Army, Character, Event, GameState, Region
from ming_sim.qualitative import qualitative_band, qualitative_bucket
from ming_sim.skills import available_skill_names

_content: Optional[GameContent] = None


def bind_content(content: GameContent) -> None:
    global _content
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("context.bind_content() 未调用：GameContent 未注入。")
    return _content


def historical_anchor_for_month(year: int, month: int) -> Dict[str, object]:
    """给 LLM 的历史护栏：关键历史事变必须出现，但玩家可改变走向和结果。"""
    anchors = {
        (1626, 9): "努尔哈赤已死于宁远败后不久，后金内部围绕汗位重排，皇太极取得主动。",
        (1626, 10): "皇太极继后金汗位，改元天聪；此事在游戏开局前已成定局，不可改写为尚未登基。",
        (1627, 1): "丁卯之役：后金攻朝鲜，朝鲜被迫与后金缔结兄弟之盟，但仍暗中倾明。",
        (1629, 10): "己巳之变历史窗口开启：皇太极可能绕道蒙古、蓟镇入塞，威胁遵化、京师。",
        (1629, 11): "己巳之变最危险阶段：若蓟镇、宣大、京营、关宁勤王失措，后金兵锋可逼近北京城下。",
        (1630, 1): "己巳之变余波：辽东督师、京畿防务与勤王军功过会引发朝廷追责。",
        (1632, 5): "皇太极西征林丹汗及察哈尔体系的历史压力上升，蒙古各部可能倒向后金。",
        (1635, 4): "察哈尔衰败后，后金收编蒙古部众、获得传国玉玺一类政治资源的窗口临近。",
        (1636, 4): "皇太极历史上会改国号为大清、称帝；若后金仍强盛且未被明军压制，应发生称帝建制。",
        (1637, 1): "丙子之役后朝鲜可能彻底臣服清；若明朝未能牵制辽东，朝鲜倾明空间会急剧缩小。",
        (1642, 3): "松锦决战历史压力：若关宁、锦州、宁远供给和士气长期恶化，辽东主力可能遭毁灭性打击。",
    }
    note = anchors.get((year, month), "")
    return {
        "date": f"{year}年{month}月",
        "note": note or f"本{TURN_UNIT}无硬性历史锚点，但势力仍需按其利益自行推进。",
        "must_respect": bool(note),
    }


# 结局类型枚举（CLI/Web/总结 agent 共用）。
# - ongoing：未决
# - capital_fallen：京师失守（beizhili 易主非 ming）——数值型，本函数判
# - emperor_abdicate / emperor_suicide：崇祯退位/自尽——叙事型，由 extractor 抽 emperor_fate 后
#   写入 applied["victory_status"]，不在本函数判
# - timeout：20 年到期（turn>=240）强制收尾——由 decree 结局收口判，不在本函数判
ENDING_ONGOING = "ongoing"
ENDING_CAPITAL_FALLEN = "capital_fallen"
ENDING_EMPEROR_ABDICATE = "emperor_abdicate"
ENDING_EMPEROR_SUICIDE = "emperor_suicide"
ENDING_TIMEOUT = "timeout"

# 五态结局的定调文案（前端弹窗标题/CLI 打印用）。ongoing 不入此表。
ENDING_LABELS: Dict[str, str] = {
    ENDING_CAPITAL_FALLEN: "京师陷落",
    ENDING_EMPEROR_ABDICATE: "崇祯逊位",
    ENDING_EMPEROR_SUICIDE: "崇祯殉国",
    ENDING_TIMEOUT: "二十载尘埃落定",
}


def victory_status(db: GameDB, state: GameState) -> Dict[str, object]:
    """结局判定（数值型部分）：本函数只判「京师失守」。

    退位/自尽走 extractor 的 emperor_fate（叙事型，见 issues.apply_score_extraction），
    20 年到期走 decree 结局收口（turn>=240），均不在此判。其余一律 ongoing。
    京畿 = beizhili，控制权字段 controlled_by（FK powers）；非 'ming' 即京师失守。
    """
    beizhili = db.conn.execute("SELECT * FROM regions WHERE id = 'beizhili'").fetchone()
    if beizhili is not None and str(beizhili["controlled_by"]) != "ming":
        holder_id = str(beizhili["controlled_by"])
        holder = db.conn.execute(
            "SELECT name FROM powers WHERE id = ?", (holder_id,)
        ).fetchone()
        holder_name = str(holder["name"]) if holder else holder_id
        return {
            "status": ENDING_CAPITAL_FALLEN,
            "summary": f"京师失守，{holder_name}入主北京，社稷倾覆，大明失其神器。",
        }
    return {"status": ENDING_ONGOING, "summary": "局势未决，社稷尚在崇祯一念之间。"}


# 地区/军队名称匹配实现在 matching.py；此处提供绑定 GameContent 的便捷封装。
from ming_sim.matching import army_aliases, compact_name, region_aliases  # noqa: E402,F401
from ming_sim.matching import match_army_id_from_text as _match_army
from ming_sim.matching import match_region_id_from_text as _match_region


def match_region_id_from_text(text: str) -> Optional[str]:
    return _match_region(text, _ctx().regions)


def match_army_id_from_text(text: str) -> Optional[str]:
    return _match_army(text, _ctx().armies)


def state_context(state: GameState) -> str:
    parts = []
    for key, value in state.metrics.items():
        if key in ECONOMY_ACCOUNTS:
            parts.append(f"{key}{format_money(value)}")
        else:
            parts.append(f"{key}{value}")
    return "，".join(parts)


def parse_json_dict(raw: str) -> Dict[str, int]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LLMContractError(f"数据库中的数值变化 JSON 已损坏：{raw[:200]}") from error
    if not isinstance(data, dict):
        raise LLMContractError(f"数据库中的数值变化不是 object：{raw[:200]}")
    parsed: Dict[str, int] = {}
    for key, value in data.items():
        try:
            parsed[str(key)] = int(value)
        except (TypeError, ValueError) as error:
            raise LLMContractError(f"数据库中的数值变化字段不是整数：{key}={value}") from error
    return parsed


def format_metric_delta(delta: Dict[str, int]) -> str:
    if not delta:
        return "核心数值无明显变化"
    parts = []
    for key, value in delta.items():
        if key in ECONOMY_ACCOUNTS:
            parts.append(f"{key}{format_money_delta(value)}")
        else:
            sign = "+" if value > 0 else ""
            parts.append(f"{key}{sign}{value}")
    return "数值变化：" + "；".join(parts)


_CHARACTER_BANDS = {
    "loyalty": ("离心已显", "心志浮动", "大体守中", "颇知向背", "可托腹心"),
    "ability": ("才具浅薄", "才具有限", "堪当常务", "才具出众", "足任大事"),
    "integrity": ("操守多亏", "操守未稳", "操守平常", "操守清正", "清介可称"),
    "courage": ("临事易退", "多有顾忌", "进退审慎", "敢任其事", "临难不屈"),
}

_INTRIGUE_PLACEHOLDER = "阴谋能力未详，暂以查案行事表现推知"


def _character_band(field: str, value: object) -> str:
    return qualitative_band(value, _CHARACTER_BANDS[field])


def _identity_band(value: object) -> str:
    return qualitative_band(value, ("几乎不染党色", "党色较淡", "党色不显", "党色较深", "党色极深"), default=50)


def _identity_bucket(value: object) -> str:
    return ("low", "middle", "high")[qualitative_bucket(value, (40, 80), default=50)]


def _faction_band(field: str, value: object) -> str:
    words = {
        "satisfaction": ("怨气深重", "颇多不满", "态度平常", "颇为顺应", "乐于奉行"),
        "leverage": ("人马凋零", "朝中孤弱", "根基平常", "颇有根基", "势重可动员"),
    }[field]
    return qualitative_band(value, words, default=50)


def character_context(character: Character) -> str:
    skills = "、".join(character.personal_skills) or "未留专长档案"
    summary = (character.summary or "").strip() or "未有专门 dossier，以官职、性情和任事处作通用特征化。"
    style = (character.style or "").strip() or "未详，以官职与任事处推知其处世分寸。"
    return (
        f"【人物档料】{character.name}，{character.office}，职位类型：{character.office_type}；"
        f"身份简介：{summary}；性情：{style}；专长：{skills}。"
        f"人物行事可见为：忠诚{_character_band('loyalty', character.loyalty)}、"
        f"能力{_character_band('ability', character.ability)}、"
        f"清廉{_character_band('integrity', character.integrity)}、"
        f"胆略{_character_band('courage', character.courage)}、"
        f"党派认同{_identity_band(character.identity)}、"
        f"阴谋{_INTRIGUE_PLACEHOLDER}。"
    )


def character_context_with_db(character: Character, db: GameDB) -> str:
    return (
        character_context(character)
        + faction_context_with_db(character, db)
        + f"当前可用技能：{available_skill_names(character, db)}"
    )


def faction_context_with_db(character: Character, db: GameDB) -> str:
    """只组装当前人物认同度允许知道的本派档料；不提供全局派系表。"""
    faction = db.conn.execute(
        "SELECT agenda, satisfaction, leverage FROM factions WHERE name = ?",
        (character.faction,),
    ).fetchone()
    bucket = _identity_bucket(character.identity)
    if bucket == "low":
        faction_text = "与该派仅有名义关联，未提供该派内情；人物立场由自身经历与当下处境呈现。"
    elif faction is None:
        faction_text = "该派尚无完整档料，以人物所处官职和已知行动推知其所求。"
    elif bucket == "middle":
        faction_text = (
            f"所求：{faction['agenda']}；当前朝势："
            f"{_faction_band('leverage', faction['leverage'])}。"
        )
    else:
        faction_text = (
            f"所求：{faction['agenda']}；当前朝势："
            f"{_faction_band('leverage', faction['leverage'])}，"
            f"对政局态度{_faction_band('satisfaction', faction['satisfaction'])}。"
        )
    return (
        f"【派系档料】{character.faction}：{faction_text}"
        f"【党派认同】此人对本派的认同为{_identity_band(character.identity)}。"
    )


def event_context(event: Event) -> str:
    return (
        f"{event.title}。类型：{event.kind}。奏报：{event.summary} "
        f"紧急{event.urgency}，严重{event.severity}，可信{event.credibility}。"
        f"牵涉利益：{', '.join(event.interests)}。"
    )


def first_character() -> Character:
    try:
        return next(iter(_ctx().characters.values()))
    except StopIteration as error:
        raise SystemExit("characters.json 至少需要一个人物。") from error


def first_character_name() -> str:
    return first_character().name


def character_from_name(name: object) -> Character:
    value = str(name or "")
    character = _ctx().characters.get(value)
    if character is None:
        raise LLMContractError(f"人物未建档：{value}")
    return character


def match_minister_from_text(text: str, current: Optional[Character] = None) -> Optional[Character]:
    cleaned = text.strip()
    if not cleaned:
        return None
    matches = []
    for character in _ctx().characters.values():
        if current is not None and character.name == current.name:
            continue
        if (
            character.name in cleaned
            or character.office in cleaned
            or character.office_type in cleaned
            or character.faction in cleaned
            or any(alias in cleaned for alias in character.aliases)
        ):
            matches.append(character)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact = [character for character in matches if character.name in cleaned]
        if len(exact) == 1:
            return exact[0]
    return None
