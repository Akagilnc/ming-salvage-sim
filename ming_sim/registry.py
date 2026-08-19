"""大臣 Agent 创建与注册表，朝会动态上下文 court_brief。L6。

通过 bind_content() 注入 GameContent。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills
from agno.skills.loaders.local import LocalSkills

from ming_sim.constants import TURN_UNIT
from ming_sim.content import GameContent
from ming_sim.context import character_context_with_db, faction_context_with_db
from ming_sim.models import Character, CourtContext, LLMConfig, MINISTER_CHAT_CLI_TIMEOUT_SECONDS
from ming_sim.recommendations import build_recommendation_brief
from ming_sim.llm_model import create_chat_model
from ming_sim.knowledge import project_court_roster_rows, render_character_knowledge
from ming_sim.qualitative import (
    building_output_effect,
    building_qualitative_fields,
    power_band,
)
from ming_sim.token_stats import tlog
from ming_sim.tools import _duty_location, build_minister_tools

_content: Optional[GameContent] = None
_skills_cache: Dict[str, Skills] = {}

# 各 office_type 对应的 skill 子集。只给该类大臣实际需要的 skill，
# 避免把 simulator/extractor 专用 skill 注入大臣 system prompt 浪费 token。
_OFFICE_SKILLS: Dict[str, List[str]] = {
    # 所有大臣共有：记忆检索、拟旨入档、密令、召见传人
    # 人物>100 或军队>30 时改为动态 tool 查询（当前 40人/17军，暂全量注入 system）
    "_base": ["memory-recall", "decree-drafting", "secret-order", "summon"],
    # 礼部：额外选妃
    "礼部":   ["consort-selection"],
    # 司礼监：选妃
    "司礼监": ["consort-selection"],
}


def _skills_for(office_type: str, extra: List[str] = []) -> Skills:
    """按 office_type 返回精简 skill 集。extra 为运行时动态追加（不缓存）。"""
    cache_key = office_type if not extra else f"{office_type}+{','.join(sorted(extra))}"
    if cache_key not in _skills_cache:
        names = list(_OFFICE_SKILLS["_base"])
        names += _OFFICE_SKILLS.get(office_type, [])
        names += [n for n in extra if n not in names]
        loaders = [LocalSkills(f".agno_skills/{n}", validate=False) for n in names]
        _skills_cache[cache_key] = Skills(loaders)
    return _skills_cache[cache_key]


def bind_content(content: GameContent) -> None:
    global _content
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("registry.bind_content() 未调用：GameContent 未注入。")
    return _content


def build_court_brief(context: CourtContext, character: Optional[Character] = None) -> str:
    """每回合精简上下文：仅含回合 + 核心数值 + 在办事项 + 钱粮一句话。
    地区/军队/派系/事项详情靠大臣按需调 tool 查（list_regions, inspect_memorial 等）。
    """
    metrics = context.state.metrics
    money_line = (
        f"国库{metrics.get('国库', 0)}万两，内库{metrics.get('内库', 0)}万两。"
    )
    score_line = "民情与君威见于各地奏报和行事反应。"
    if character:
        # Characterized callers must use the same perspectival issue rail as
        # the agent prompt; the uncharacterized board brief remains an engine
        # overview for non-minister callers.
        issues = context.db.get_character_knowledge(context.state, character.name).get("issues", [])
    else:
        issues = context.db.list_active_issues()
    issue_lines: List[str] = []
    for row in issues[:10]:
        kind_tag = "系统" if row["kind"] == "situation" else "玩家"
        issue_lines.append(
            f"#{row['id']}[{kind_tag}]{row['title']}"
            f"（局势未决；向好端：{row['bar_good_meaning']}；向坏端：{row['bar_bad_meaning']}）"
        )
    issues_brief = "；".join(issue_lines) if issue_lines else "无"
    identity_brief = faction_context_with_db(character, context.db) if character else ""
    return (
        f"本{TURN_UNIT}：{context.state.year}年{context.state.period}月（第{context.state.turn}回合）。"
        f"钱粮：{money_line}国势：{score_line}。"
        f"在办事项：{issues_brief}。"
        f"{identity_brief}"
        f"势力档料：{_power_brief(context)}。"
        f"地区/奏报/钱粮详情按需调工具查（list_regions/inspect_region/inspect_memorial/check_treasury 等）；人事与军队详情见下方固定名册。"
    )


def _minister_game_world_prompt(prompt: str) -> str:
    """给大臣的世界观说明只保留呈现口径，不把引擎量表喂给角色。"""
    lines = []
    for line in prompt.splitlines():
        if "国势核心数值四个：" in line:
            line = "- 国势以奏报呈现：国库、内库保留钱粮口径；民心、皇威只作定性描述。"
        elif "地区盘面使用两京十三省的核心字段：" in line:
            line = "- 地区盘面中人口、粮食、田亩、隐田、每回合税收等可数物照实呈报；民心、动乱、士绅阻力、军事压力以定性描述呈报。"
        elif "军队盘面使用主要军队核心字段：" in line:
            line = "- 军队盘面中驻地、统帅、兵种、人数、月饷与欠饷等可数物照实呈报；补给、士气、训练、装备、火器、机动、忠诚以定性描述呈报；随军大炮照门数呈报。"
        lines.append(line)
    return "\n".join(lines)


def _power_brief(context: CourtContext) -> str:
    """势力的抽象轴也只以定性档料进入扮演 prompt。"""
    rows = context.db.power_rows(exclude_self=True)
    if not rows:
        return "势力未建档。"

    return "；".join(
        f"{row['name']}（{row['leader']}）：{row['stance']}，朝势{power_band(row['leverage'])}、"
        f"军力{power_band(row['military_strength'])}、财力{power_band(row['supply'])}，"
        f"{row['status']}；近动：{row['last_action'] or '尚无新动'}"
        for row in rows
    )


def build_court_roster(context: CourtContext) -> str:
    """全体在朝大臣名册——表格（| 分隔）压 token，固定喂进大臣 system。
    去掉了 inspect_minister/list_court/list_personnel 后，大臣据此知道"别人"现状，不再调工具查。
    含被罢/下狱/流放/致仕者（标状态），不含后宫、宗藩（就藩宗室非朝堂命官）、非大明势力、未登场者（防剧透）。
    """
    db = context.db
    lines: List[str] = []
    for c in _ctx().characters.values():
        # roster scope：非后宫、非宗藩（宗室就藩非朝堂命官，PR#121；大臣据此名册知他人现状，
        # 宗藩不入此册，与 web visible_in_court 同步，cmr R3 cross-section）。
        if c.office_type in ("后宫", "宗藩"):
            continue
        status, reason = db.get_character_status(c.name)
        if status == "offstage":  # offstage 多，先短路省一次 resolve_power_id DB 查询（gemini PR#130 R1）
            continue
        if db.resolve_power_id(c) != "ming":  # DB 权威：招抚归明者(DB翻ming/content仍旧势力)入册
            continue
        # 直接按字段吐原值，不脑补、不翻译。状态原值 + 缘由（如有）。
        state_cell = f"{status}（{reason}）" if reason else status
        lines.append(
            "|".join((c.name, c.office or "无现任官职", c.office_type, c.faction, state_cell))
        )
    if not lines:
        return ""
    return (
        "【在朝人事名册（现状以此为准，提及他人官职/状态直接据此作答，不要凭历史印象）】\n"
        "（| 分隔，列序＝姓名|现职|官署|派系|状态）：\n"
        + "\n".join(lines)
    )


def build_court_roster_index(context: CourtContext) -> str:
    """人物数超 100 时用索引替代完整名册：仅姓名+官署+状态，完整信息由 query_court_roster tool 提供。"""
    db = context.db
    lines: List[str] = []
    for c in _ctx().characters.values():
        # roster scope：非后宫、非宗藩（同 build_court_roster，cmr R3 cross-section）。
        if c.office_type in ("后宫", "宗藩"):
            continue
        status, reason = db.get_character_status(c.name)
        if status == "offstage":  # offstage 多，先短路省一次 resolve_power_id DB 查询（gemini PR#130 R1）
            continue
        if db.resolve_power_id(c) != "ming":  # DB 权威：招抚归明者(DB翻ming/content仍旧势力)入册
            continue
        state_cell = f"{status}（{reason}）" if reason else status
        lines.append(f"{c.name}：{c.office or '无现任官职'}，{state_cell}")
    if not lines:
        return ""
    return (
        "【在朝人事索引（涉及人物官职/状态时先调 query_court_roster 查完整信息）】\n"
        + "\n".join(lines)
    )


def build_last_gazette_brief(context: CourtContext) -> str:
    """上回合（上月）邸报全文，固定喂进大臣 system。
    去掉了"上月须调 read_past_report"的依赖，大臣首轮即知上月朝局/地方/灾兵祸福。
    更早月份的邸报仍由 read_past_report 工具按需查。无上月邸报（开局首回合）返回空。"""
    prev_turn = int(context.state.turn) - 1
    if prev_turn < 0:
        return ""
    report = context.db.get_turn_report(prev_turn)
    if not report or not report.strip():
        return ""
    safe_report = str(report or "")
    return "【上回合邸报全文（上月朝局实录，作答涉及上月动静以此为准；更早月份调 read_past_report 查）】\n" + safe_report


def build_memory_brief(character: Character, context: CourtContext) -> str:
    """从人物见闻投影渲染更早朝局；章节表不是人物读取端。"""
    prev_turn = int(context.state.turn) - 1
    knowledge = context.db.get_character_knowledge(context.state, character.name)
    chapters = [c for c in knowledge.get("public_events", [])
                if (c.get("kind") == "chapter_summary" or str(c.get("source_id") or "").startswith("chapter_source:"))
                and int(c.get("turn") or 0) != prev_turn]
    lines = ["【更早朝局（起居注章节，上月详情见上方邸报）】"]
    for c in chapters:
        body = str(c.get("body") or c.get("title") or "")
        if body:
            lines.append(f"- {c['year']}年{c['period']}月：{body}")
    if len(lines) == 1:
        return ""
    brief = "\n".join(lines)
    chap_list = "、".join(f"{c['year']}年{c['period']}月" for c in chapters)
    tlog(
        f"[装填大臣记忆] 建「{character.name}」对话Agent时，把更早朝局的起居注章节"
        f"（每月一段朝局叙事，取 turn-2 及更早4月内）塞进其system上下文，"
        f"让他作答能记得这几月发生过什么。本次装 {len(chapters)} 章：{chap_list}，共 {len(brief)} 字"
    )
    return brief


def build_character_knowledge_brief(character: Character, context: CourtContext) -> str:
    """Render the minister's perspectival world slice for the audience prompt.

    ``get_character_knowledge`` is the sole read boundary here: unlike the
    legacy registry builders it applies office scoping and source exclusions
    before anything reaches the model.  Keep this as one block so a future
    prompt assembly change cannot accidentally reintroduce a global rail.
    """
    knowledge = context.db.get_character_knowledge(context.state, character.name)
    return render_character_knowledge(
        knowledge, character.name, db=context.db, state=context.state,
    )


def build_secret_order_brief(character: Character, context: CourtContext) -> str:
    """本大臣名下进行中密令的提醒——只列编号+标题+本月推进了没，不泄具体进展。
    详情由大臣自己调 report_secret_order_progress 查（同时可写进展）。非承办人不提示。"""
    try:
        orders = context.db.get_active_secret_orders_for_minister(character.name)
    except Exception:
        return ""
    if not orders:
        return ""
    lines = [
        "【你身上还在办的密令】",
        "★ 皇帝问进度时调 `report_secret_order_progress(order_id, progress=本月新一步进展)`：有 progress 时先暂存待确认，确认后落档；若只想查看历史则留空 progress；同月补充会修正本月行。",
        "★ 皇帝催办/加急时调 `rush_secret_order(order_id, deadline_months=1/3/0, reason=催办缘由)`：1=下月核议，3=三月内核议，0=本月即核。",
        "★ 自认任务办到位时调 `submit_secret_order_for_review(order_id, claim=自述办结陈词)`：转入待核议状态，等推演月末判 done/failed。",
        "★ progress / claim 写具体事实：派谁去、查到什么、摸到哪一层、下一步指向谁。空话「待实据到手」不算。",
        "★ 大臣无权直接判 done/failed——结案权全归推演。提交后该月不再可推进。",
        "在册密令：",
    ]
    for o in orders:
        status = o.get("status", "active")
        if status == "pending_review":
            tag = "⏳ 已提交待核议（本月不再可动，等推演月末定夺）"
        else:
            advanced = context.db._has_secret_order_period_line(
                int(o["id"]), "result", context.state.year, context.state.period
            )
            tag = "✅ 本月已推进" if advanced else "⚠️ 本月尚未推进"
        due_turn = int(o.get("due_turn") or 0)
        due_text = f"；御限剩 {max(0, due_turn - int(context.state.turn))} 月" if due_turn else ""
        lines.append(f"  - #{o['id']}「{o['title']}」 {tag}{due_text}")
        content_brief = (o.get("content") or "")[:80].replace("\n", " ")
        if content_brief:
            lines.append(f"    （任务摘要：{content_brief}…）")
    return "\n".join(lines)


def build_region_brief(context: CourtContext) -> str:
    """两京十三省危情概览注入大臣 system —— CLI 后端无 list_regions 工具，
    靠此让大臣知地方民心/动乱/边压，谈政略不抓瞎。"""
    try:
        return context.db.region_report(limit=8)
    except Exception:
        return ""


def build_building_brief(context: CourtContext) -> str:
    """现有建筑紧凑表（名·类·省 规模/完好/产出）——省去叙述控 token。
    CLI 后端无 list_buildings 工具，靠此让大臣知国家有哪些厂局仓坞。"""
    try:
        # 用中文地区名（LEFT JOIN regions），不漏拼音 region_id（beizhili 等英文进 system
        # 会诱发模型 code-switch 蹦英文；地区无名时退回 region_id）。
        rows = context.db.conn.execute(
            "SELECT b.name AS name, b.category AS category, "
            "COALESCE(r.name, b.region_id) AS region_name, "
            "b.level AS level, b.condition AS condition, "
            "b.risk AS risk, "
            "b.output_metric AS output_metric, b.output_amount AS output_amount "
            "FROM buildings b LEFT JOIN regions r ON r.id = b.region_id "
            "ORDER BY b.region_id, b.category"
        ).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""

    lines = []
    for r in rows:
        metric = str(r["output_metric"] or "")
        out = building_output_effect(metric, r["output_amount"], prefix="·")
        level, condition, _risk = building_qualitative_fields(r)
        lines.append(
            f"{r['name']}（{r['category']}·{r['region_name']}）"
            f"Lv档{level}，完好{condition}{out}"
        )
    return "【现有建筑（名·类别·地区 规模/完好/产出；问营建/厂局/仓坞据此）】\n" + "；".join(lines)


def _make_cultivate_tool(character: Character, context: CourtContext):
    """生成后宫调教 tool，绑定到当前妃嫔。"""
    name = character.name

    def cultivate_consort(skill: str = "", trait: str = "") -> str:
        """皇帝调教妃嫔，为其新增技能或改变性格。skill：新增技能名（如"书法精通"），可为空；trait：新增性格词（如"更加温婉"），可为空。效果永久生效，下次召见时体现在人物描述中。"""
        context.db.cultivate_consort(
            name, context.state.turn, skill=skill.strip(), trait=trait.strip()
        )
        parts = []
        if skill.strip():
            parts.append(f"习得技能「{skill.strip()}」")
        if trait.strip():
            parts.append(f"性情添了「{trait.strip()}」")
        if not parts:
            return "未指定技能或性格，调教无效。"
        return "已记录：" + "、".join(parts) + "。下次召见时将体现。"

    return cultivate_consort


# 后宫预设立绘池：编号 → 该图的人物身份/气质（LLM 据此为秀女配图，确保人图一致）。
# 与 web/public/portraits/consort_pool_<N>.png 及 docs/portrait-prompts.md 文末清单对应。
CONSORT_POOL_IDENTITIES: Dict[int, str] = {
    1: "满洲格格——英武明艳，关外贵女，骑射出身",
    2: "江湖卖艺女——活泼灵动，杂耍歌舞，市井出身",
    3: "女侠——飒爽英姿，习武佩剑，江湖出身",
    4: "江南名妓——才情风流，诗词歌赋，秦淮出身",
    5: "才女画师——洒脱灵动，丹青妙笔，书香出身",
    6: "棋待诏——冷静知性，精于围棋，弈林出身",
    7: "道姑——仙气飘逸，修道清修，方外出身",
    8: "忧郁美人——秋色清愁，沉静寡言，文士门第",
    9: "波斯商女——异域浓彩，丝路而来，西域胡商之女",
    10: "琴师——清雅文艺，善抚瑶琴，乐坊出身",
    11: "娇艳贵女——明丽妩媚，雍容华贵，勋贵门第",
    12: "女医——温柔聪慧，通晓医药，杏林出身",
    13: "东厂女探——暗黑魅惑，身手不凡，厂卫出身",
    14: "端庄贵妇——母仪雍容，知书达礼，名门嫡女",
    15: "茶道名媛——温润恬静，精于茶艺，士绅之家",
    16: "南洋舶来——海岛风情，远渡而来，南洋舶商之女",
}


def _make_select_consort_tool(context: CourtContext):
    """生成选妃呈名单 tool，挂在司礼监/礼部大臣上。
    秀女由 LLM 据预设立绘池的身份现场拟就，tool 落库为待选采女（status=candidate），
    人设与所选立绘一致。只立候选不册封——皇帝看中后另下诏册封，走 candidate 升格路径。"""

    def _pool_used() -> set:
        rows = context.db.conn.execute(
            "SELECT portrait_id FROM characters WHERE portrait_id LIKE 'consort_pool_%'"
        ).fetchall()
        used = set()
        for r in rows:
            try:
                used.add(int(str(r["portrait_id"]).replace("consort_pool_", "")))
            except ValueError:
                pass
        return used

    def present_consort_candidates(consorts_json: str = "") -> str:
        """呈上待选秀女名单。

        可用立绘身份（portrait 编号→身份；已被占用的编号不要再选，先以空参调用可查当前可用编号）：
        {POOL_TABLE}

        consorts_json：JSON 数组字符串，3-5 人。每名秀女对象：
          {{"portrait": 4, "name": "柳如烟", "style": "才情风流",
            "skills": ["诗词","琵琶"], "summary": "秦淮名妓，色艺双绝", "faction": "中宫"}}
        """
        content = _ctx()
        try:
            raw = json.loads(consorts_json) if isinstance(consorts_json, str) and consorts_json.strip() else consorts_json
        except (json.JSONDecodeError, TypeError):
            return "（拟选名单格式有误，请以 JSON 数组重拟，每名含 portrait/name/style/skills/summary。）"
        if isinstance(raw, dict):
            raw = raw.get("consorts") or raw.get("candidates") or [raw]
        if not isinstance(raw, list) or not raw:
            free = sorted(set(CONSORT_POOL_IDENTITIES) - _pool_used())
            table = "\n".join(f"  {i}：{CONSORT_POOL_IDENTITIES[i]}" for i in free)
            return ("（尚未拟出秀女。请按下列可用立绘配人，回传 JSON 数组：\n"
                    + table + "\n每名含 portrait/name/style/skills/summary。）")

        existing_names = set(content.characters.keys())
        used = _pool_used()
        chosen: List[tuple[Character, int]] = []
        for item in raw[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in existing_names:
                continue
            try:
                pid = int(item.get("portrait"))
            except (TypeError, ValueError):
                continue
            if pid not in CONSORT_POOL_IDENTITIES or pid in used:
                continue  # 编号非法或已占用，跳过
            skills = item.get("skills") or []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.replace("、", ",").split(",") if s.strip()]
            consort = Character(
                name=name,
                office="采女（待选）",
                office_type="后宫",
                faction=str(item.get("faction") or "中宫"),
                aliases=[],
                personal_skills=[str(s).strip() for s in skills if str(s).strip()],
                loyalty=int(item.get("loyalty") or 60),
                ability=int(item.get("ability") or 55),
                integrity=int(item.get("integrity") or 60),
                courage=int(item.get("courage") or 50),
                style=str(item.get("style") or "温婉"),
                power_id="ming",
                status="candidate",
                summary=str(item.get("summary") or "").strip(),
                portrait_id=f"consort_pool_{pid}",  # 显式指定，add_character 不再自动分配
            )
            context.db.add_character(context.state, consort)
            content.characters[name] = consort
            existing_names.add(name)
            used.add(pid)
            chosen.append((consort, pid))

        if not chosen:
            free = sorted(set(CONSORT_POOL_IDENTITIES) - _pool_used())
            return ("（拟选的秀女或重名、或立绘编号非法/已占用，未能立为候选。"
                    f"当前可用立绘编号：{free}，请重拟。）")

        lines = ["臣等已为陛下物色数名待选采女，恭呈御览："]
        for idx, (c, _pid) in enumerate(chosen, 1):
            tags = "、".join(c.personal_skills) if c.personal_skills else "—"
            summary = (c.summary or "").strip()
            if len(summary) > 50:
                summary = summary[:50] + "…"
            lines.append(
                f"{idx}. {c.name}　性情：{c.style or '—'}　特质：{tags}"
                + (f"　{summary}" if summary else "")
            )
        lines.append("陛下若有中意者，可降诏册封其位份，即可入宫。")
        return "\n".join(lines)

    # 池身份表烤进 docstring（全 16 槽静态，不含动态 free 列表 → 工具 schema 跨回合不变，保缓存）。
    pool_table = "\n".join(f"  {i}：{CONSORT_POOL_IDENTITIES[i]}" for i in sorted(CONSORT_POOL_IDENTITIES))
    present_consort_candidates.__doc__ = present_consort_candidates.__doc__.replace("{POOL_TABLE}", pool_table)
    return present_consort_candidates


def create_minister_agent(
    character: Character,
    llm_config: LLMConfig,
    context: CourtContext,
    agno_db: SqliteDb,
    session_id: Optional[str] = None,
) -> Agent:
    # 实时召对用短超时（#353）：大臣回话 ≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS，
    # 与月末结算的 300 s 解耦；用 dataclasses.replace 不改原配置对象。
    chat_llm_config = replace(
        llm_config,
        cli_timeout_seconds=min(llm_config.cli_timeout_seconds, MINISTER_CHAT_CLI_TIMEOUT_SECONDS)
        if llm_config.cli_timeout_seconds is not None
        else MINISTER_CHAT_CLI_TIMEOUT_SECONDS,
        timeout_seconds=min(llm_config.timeout_seconds, MINISTER_CHAT_CLI_TIMEOUT_SECONDS)
        if llm_config.timeout_seconds is not None
        else MINISTER_CHAT_CLI_TIMEOUT_SECONDS,
    )
    # temperature 0.6：保留人物个性，但收敛发挥——少在拟旨里夹带题外私货。
    model = create_chat_model(chat_llm_config, temperature=0.6, top_p=0.9)
    # 缓存策略：instructions 全部静态化（仅依赖 character，不依赖每月 state/events）。
    # game_world / minister_agent prompt、character 档案 跨月完全相同 → DeepSeek 前缀缓存命中。
    # 每月动态上下文（钱粮、奏报、地区、军队、派系）由 MinisterRegistry 在 agent 创建后通过首轮
    # user message 喂入，不污染 system prompt。
    # The caller owns the live content/state pair.  Requiring the module-level
    # registry binding here makes this public construction seam fail in fresh
    # sessions (and lets a stale binding win over a restored context).
    c = context.db.content or _ctx()
    is_consort = character.office_type == "后宫"
    if is_consort:
        # 从 DB 取调教记录
        cultivated = context.db.get_consort_traits(character.name)
        extra_skills_str = ("、".join(cultivated["extra_skills"])) if cultivated["extra_skills"] else ""
        extra_traits_str = ("、".join(cultivated["extra_traits"])) if cultivated["extra_traits"] else ""
        cultivate_desc = ""
        if extra_skills_str:
            cultivate_desc += f"经皇帝调教后习得：{extra_skills_str}。"
        if extra_traits_str:
            cultivate_desc += f"性情逐渐变化：{extra_traits_str}。"
        instructions = [
            _minister_game_world_prompt(c.game_world_prompt),
            c.consort_agent_prompt,
            f"你当前扮演：{character.name}，{character.office}，性格{character.style}，"
            f"人物特质：{'、'.join(character.personal_skills)}。个人简介：{character.summary}"
            + (f"\n{cultivate_desc}" if cultivate_desc else ""),
            f"你与皇帝的对话在后宫寝殿；同一回合复召时接续此前对话，不要重置记忆。",
            f"当前为 {context.state.year} 年 {context.state.period} 月。",
        ]
        tools = [_make_cultivate_tool(character, context)]
    else:
        # 月度动态上下文全挂 system 末尾——见闻投影是唯一世界输入；前面 game_world /
        # minister_agent / character 静态段仍命中前缀缓存。旧 registry 全知 builders
        # 保留给其他调用方，但不能从此处绕过角色见闻边界。
        complete_roster = context.db.current_court_roster_rows(context.state)
        army_count = context.db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]
        projected_world = context.db.get_character_knowledge(
            context.state, character.name,
        )
        projected_roster = project_court_roster_rows(
            complete_roster, projected_world, character.office_type,
        )
        # Scale thresholds operate on the authorized slice, never on the global
        # backing set: a large court cannot manufacture a personnel capability.
        use_roster_tool = len(projected_roster) > 100
        projected_world = projected_world.get("world") or {}
        # The threshold may alter delivery, never authorization: a role without
        # the military domain must not receive either the roster tool or skill.
        use_army_tool = army_count > 30 and "military" in projected_world
        knowledge_brief = build_character_knowledge_brief(character, context)
        secret_brief = build_secret_order_brief(character, context)
        recommendation_brief = build_recommendation_brief(context.db, context.state, character.name)
        monthly_block_parts = [
            f"当前为 {context.state.year} 年 {context.state.period} 月（第 {context.state.turn} 回合）。"
            "作答涉及时序（某事多久前、某人是否已亡、某限期是否到）时以此为准。",
        ]
        if knowledge_brief:
            monthly_block_parts.append(knowledge_brief)
        if secret_brief:
            monthly_block_parts.append(secret_brief)
        monthly_block_parts.append(recommendation_brief)
        if projected_roster and not use_roster_tool:
            monthly_block_parts.append(
                "【已授权在朝名册】\n" + "\n".join(
                    f"{row['name']}：{row['office'] or '无现任官职'}，{row['status']}"
                    for row in projected_roster
                )
            )
        instructions = [
            _minister_game_world_prompt(c.game_world_prompt),
            c.minister_agent_prompt,
            f"你当前扮演：{character_context_with_db(character, context.db)}，"
            f"任事处：{_duty_location(character.office, character.office_type, 'active')}。",
            f"你与皇帝的多轮对话会持续到本{TURN_UNIT}退朝；同一{TURN_UNIT}复召时要接续此前奏对，不要重置记忆。",
            "\n\n".join(monthly_block_parts),
        ]
        tools = build_minister_tools(character, context,
                                     use_roster_tool=use_roster_tool,
                                     use_army_tool=use_army_tool)
        # 司礼监（内官管后宫）与礼部（议礼册封）可奉旨选妃：现场拟就秀女名单呈御览。
        if character.office_type in ("司礼监", "礼部"):
            tools.append(_make_select_consort_tool(context))
        extra_skills = []
        if use_roster_tool:
            extra_skills.append("court-roster")
        if use_army_tool:
            extra_skills.append("army-roster")
        minister_skills = _skills_for(character.office_type, extra=extra_skills)
    return Agent(
        name=character.name,
        id=f"minister-{character.name}",
        session_id=session_id or f"minister-{character.name}-turn-{context.state.turn}",
        db=agno_db,
        model=model,
        instructions=instructions,
        tools=tools,
        skills=minister_skills if not is_consort else None,
        add_history_to_context=True,
        num_history_runs=6,
        tool_call_limit=5,
        markdown=False,
    )


class MinisterRegistry:
    def __init__(
        self,
        llm_config: LLMConfig,
        agno_db: SqliteDb,
        context: CourtContext,
    ) -> None:
        self.llm_config = llm_config
        self.agno_db = agno_db
        self.context = context
        self.agents: Dict[str, Agent] = {}
        # The CourtContext owns the live content/state pair.  Do not depend on
        # a module-global binding here: fresh sessions and registry refreshes
        # must build from the same restored content that supplied the context.
        self.content = context.db.content or _ctx()
        characters = self.content.characters
        self.session_ids: Dict[str, str] = {
            name: f"minister-{name}-turn-{context.state.turn}"
            for name in characters
        }
        # 懒加载：不在构造时预建全人物 agent（一整月通常只召见两三人，预建 50+ 个
        # 都要查 DB 拼 memory_brief，纯浪费）。改由 get() 首次取用时按需建并缓存。

    def _create(self, character: Character) -> Agent:
        return create_minister_agent(
            character,
            self.llm_config,
            self.context,
            self.agno_db,
            session_id=self.session_ids[character.name],
        )

    def build_draft_line(self) -> str:
        """实时查本回合已核定草案，供需要展示草案列表的调用方使用。"""
        draft_rows = [
            row for row in self.context.db.list_directives(
                self.context.state, statuses=("draft",),
            )
            if self.context.db.get_dossier_for_directive(int(row["id"])) is None
        ]
        if not draft_rows:
            return "无"
        return "；".join(
            f"#{r['id']} {r['text'][:40]}{'…' if len(r['text']) > 40 else ''}"
            for r in draft_rows
        )

    def get(self, character: Character) -> Agent:
        """懒加载：首次召见某大臣才建其 Agent（含查 DB 拼 memory_brief），之后本回合复用缓存。"""
        agent = self.agents.get(character.name)
        if agent is None:
            agent = self._create(character)
            self.agents[character.name] = agent
        return agent

    def refresh(self, character_name: str) -> None:
        character = self.content.characters.get(character_name)
        if character is None:
            return
        self.agents[character.name] = self._create(character)

    def register(self, character: Character) -> None:
        """运行时新建人物（吏部铨选任命）后注册其 Agent，使本回合即可召见。"""
        self.session_ids[character.name] = (
            f"minister-{character.name}-turn-{self.context.state.turn}"
        )
        self.agents[character.name] = self._create(character)

    def register_runtime(self, character: Character) -> None:
        """注册不入正式名册的临时召见人物。"""
        self.session_ids[character.name] = (
            f"temporary-{character.name}-turn-{self.context.state.turn}"
        )
        self.agents[character.name] = self._create(character)
