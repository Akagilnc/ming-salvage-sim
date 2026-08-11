"""大臣 Agent 工具集：查询工具 + court tools（拟旨/退下/换人）。L5。"""

from __future__ import annotations

import json
import re
from typing import Dict, List

from ming_sim.constants import DOSSIER_LINK_TYPES, TURN_UNIT
from ming_sim.context import _ctx as _content_ctx, state_context
from ming_sim.models import FRONT_HALF_DONE_PHASES, Character, CourtContext
from ming_sim.qualitative import qualitative_band
from ming_sim.strict_types import strict_int
from ming_sim.token_stats import tlog

_STATUS_CN = {
    "active": "在朝",
    "offstage": "赋闲",
    "candidate": "候选",
    "dismissed": "已罢黜",
    "imprisoned": "下狱",
    "exiled": "流放",
    "retired": "致仕",
    "dead": "已故",
}


def _duty_location(office: str, office_type: str, status: str) -> str:
    if status == "dead":
        return "已故，不在任事。"
    if status == "imprisoned":
        return "系狱待勘，具体羁押处以处置缘由为准。"
    if status in {"dismissed", "exiled", "retired", "offstage"}:
        return "不在朝任事。"
    text = office or office_type
    if not text:
        return "在朝但现职未明。"
    # 现职文本已写明在野（罢居/致仕/养病/丁忧某地）的，按文本说，不再脑补"在京师衙署任事"。
    if any(w in text for w in ("罢居", "罢闲", "赋闲", "养病", "丁忧", "致仕", "归籍", "在野")):
        return "现非实任，" + text + "。"
    region_markers = [
        "陕西", "辽东", "宁远", "关宁", "山西", "河南", "山东", "湖广", "四川", "福建",
        "广东", "广西", "浙江", "江西", "南直隶", "北直隶", "南京", "登莱", "宣大", "延绥",
    ]
    for marker in region_markers:
        if marker in text:
            return f"按现职在{marker}任事。"
    if office_type in {"内阁", "吏部", "户部", "礼部", "兵部", "工部", "都察院", "翰林院", "司礼监", "锦衣卫", "东厂", "内廷"}:
        return f"按现职在京师{office_type}衙署任事。"
    if office_type == "边镇":
        return "按现职在所辖边镇任事。"
    if office_type == "地方":
        return "按现职在地方任事。"
    return "按现职任事，具体地点需看官衔所辖。"


def _compact_json_text(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return "（未填）"
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return text


def _progress_band(value: object) -> str:
    return qualitative_band(value, ("未见起色", "略有起色", "进展过半", "进展顺利", "近于收束"))


_ABSTRACT_STOP_FIELDS = {
    "loyalty": "忠诚",
    "ability": "能力",
    "integrity": "操守",
    "courage": "胆略",
    "leverage": "朝势",
    "satisfaction": "态度",
    "public_support": "民心",
    "unrest": "动乱",
    "gentry_resistance": "士绅阻力",
    "military_pressure": "军事压力",
    "morale": "士气",
    "training": "训练",
    "equipment": "装备",
    "firearm_equipment": "火器",
    "corruption": "贪腐",
    "grain_security": "粮情",
    "city_level": "城防",
    "mobility": "机动",
    "cohesion": "凝聚",
    "supply": "补给",
    "bar_value": "进展",
    "progress": "进展",
    "皇威": "皇威",
    "民心": "民心",
    "动乱": "动乱",
    "满意度": "态度",
    "忠诚": "忠诚",
    "能力": "能力",
    "清廉": "操守",
    "胆略": "胆略",
    "进度": "进展",
}
_COUNTABLE_STOP_FIELDS = {
    "treasury", "国库", "内库", "arrears", "欠饷", "manpower", "兵额",
    "population", "registered_land", "hidden_land", "tax_per_turn", "grain",
    "army_needed", "cannon", "cannon_equipment",
}


def _qualitative_stop_field(key: str) -> str:
    parts = key.split(".")
    field = parts[-1]
    if field in _COUNTABLE_STOP_FIELDS:
        return ""
    label = _ABSTRACT_STOP_FIELDS.get(field)
    if label is None:
        label = next((value for name, value in _ABSTRACT_STOP_FIELDS.items() if name in key), "")
    if not label:
        return ""
    subject = parts[-2] if len(parts) > 1 else ""
    return f"{subject}{label}" if subject else label


def _qualitative_stop_condition(raw: object) -> str:
    """把承诺停止条件转成大臣可读的定性提示，保留钱粮条件的可数性。"""
    try:
        parsed = json.loads(str(raw or "")) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict):
        return "（条件已存档）"
    parts = []
    for key, condition in parsed.items():
        key_text = str(key)
        value_text = str(condition)
        qualitative_field = _qualitative_stop_field(key_text)
        if qualitative_field:
            suffix = "已达较高水准" if key_text.split(".")[-1] == "loyalty" else "达到所定档位"
            parts.append(f"{qualitative_field}{suffix}")
        elif any(name == key_text.split(".")[-1] for name in _COUNTABLE_STOP_FIELDS):
            parts.append(f"{key_text}{value_text}")
        else:
            # 只有明确可数物（如欠饷、银两、兵额）才把机器条件原样交给大臣。
            # 未知字段也不应成为抽象分数泄漏的后门：保留字段名，隐藏比较符和阈值。
            parts.append(f"{key_text}条件已存档")
    return "、".join(parts) or "（条件未详）"


def _qualitative_condition(raw: object) -> str:
    """Hide abstract thresholds in legacy resolve/fail condition strings."""
    text = str(raw or "").strip()
    match = re.fullmatch(r"([^<>=!]+?)\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)", text)
    if not match:
        return "（条件已存档）" if text else "（未填）"
    key = match.group(1).strip()
    field = key.rsplit(".", 1)[-1]
    if field in _COUNTABLE_STOP_FIELDS:
        return f"{key}{match.group(2)}{match.group(3)}"
    display_key = key
    parts = key.split(".")
    if len(parts) >= 2:
        subject = parts[-2]
        try:
            content = _content_ctx()
            for collection in (content.regions, content.armies, content.characters):
                match_subject = next(
                    (item.name for item in collection.values()
                     if getattr(item, "id", None) == subject),
                    None,
                )
                if match_subject:
                    subject = match_subject
                    break
        except (AttributeError, RuntimeError):
            pass
        display_key = f"{subject}{field}"
    label = _ABSTRACT_STOP_FIELDS.get(field, field)
    return f"{display_key.replace(field, label)}达到所定档位"


def _commitment_tool_fields(db, state, row) -> str:
    keys = row.keys() if hasattr(row, "keys") else []
    commitment_kind = str(row["commitment_kind"] if "commitment_kind" in keys else "").strip()
    if not commitment_kind:
        return ""
    from ming_sim.issues import commitment_display_text, commitment_progress_payload

    progress = commitment_progress_payload(db, state, row) or {}
    # Keep the durable elapsed-month marker in the tool contract; deadline
    # prose alone cannot tell a minister whether an undertaking has begun.
    try:
        origin = row["origin_turn"] if "origin_turn" in keys else state.turn
        elapsed = max(0, int(state.turn) - int(origin or state.turn))
    except (KeyError, TypeError, ValueError):
        elapsed = 0
    rendered_progress = commitment_display_text(progress, row).strip()
    progress_text = f"已履行{elapsed}月"
    if rendered_progress:
        progress_text = f"{progress_text}；{rendered_progress}"
    stop_condition = _qualitative_stop_condition(row["stop_condition"] if "stop_condition" in keys else "")
    try:
        end_turn = int(row["end_turn"] if "end_turn" in keys else 0)
    except (TypeError, ValueError):
        end_turn = 0
    return (
        f"commitment_kind={commitment_kind}；"
        f"stop_condition={stop_condition}；"
        f"end_turn={end_turn}；"
        f"progress={progress_text}"
    )


def build_minister_tools(character: Character, context: CourtContext,
                         use_roster_tool: bool = False, use_army_tool: bool = False):
    def projection() -> Dict[str, object]:
        from ming_sim.knowledge import build_character_knowledge
        return build_character_knowledge(context.db, context.state, character.name)

    def scoped_world(domain: str) -> str:
        """Read only the already-built character projection, never a global rail."""
        world = projection().get("world") or {}
        return str(world.get(domain) or "本职见闻未载此项。")

    def visible_issues() -> List[Dict[str, object]]:
        return list(projection().get("issues") or [])

    def filter_domain(domain: str, query: str = "") -> str:
        rendered = scoped_world(domain)
        needle = str(query or "").strip()
        if not needle:
            return rendered
        lines = [line for line in rendered.splitlines() if needle in line]
        return "\n".join(lines) if lines else f"见闻中未载{needle}。"

    def query_court_roster(names: List[str] = []) -> str:
        """按角色的本职、人事域与可见事件投影结构化在朝名册。"""
        from ming_sim.knowledge import project_court_roster_rows

        wanted = [str(name).strip() for name in (names or []) if str(name).strip()]
        rows = project_court_roster_rows(
            context.db.current_court_roster_rows(context.state, wanted),
            projection(),
            character.office_type,
        )
        if not rows:
            return "见闻中未载所查人物。"
        if not wanted:
            return "【在朝人事索引】\n" + "\n".join(
                f"{row['name']}：{row['office'] or '无现任官职'}，{row['status']}"
                for row in rows
            )
        return "【在朝人事详情】\n" + "\n".join(
            "|".join(str(value or "") for value in (
                row["name"], row["office"], row["office_type"], row["faction"],
                row["status_reason"] or row["status"],
            )) for row in rows
        )

    def query_army_roster(names: List[str] = []) -> str:
        """角色获准使用军籍工具后，空查完整索引、具名查完整记录。"""
        wanted = [str(name).strip() for name in (names or []) if str(name).strip()]
        if not wanted:
            return context.db.army_roster(qualitative_equipment=True)
        return context.db.army_roster(filter_names=wanted, qualitative_equipment=True) \
            or "见闻中未载所查军队。"

    def list_memorials() -> str:
        """查看当前在办的所有事项（issue）。"""
        rows = visible_issues()
        if not rows:
            return f"本{TURN_UNIT}无在办事项。"
        lines = []
        for idx, row in enumerate(rows, 1):
            kind_tag = "系统" if row["kind"] == "situation" else "皇帝推动"
            commitment_fields = _commitment_tool_fields(context.db, context.state, row)
            commitment_suffix = f"，{commitment_fields}" if commitment_fields else ""
            lines.append(
                f"{idx}. #{row['id']}[{kind_tag}]{row['title']}"
                f"（进展{_progress_band(row['bar_value'])}；向好端：{row['bar_good_meaning']}；"
                f"{row['stage_text']}{commitment_suffix}）"
            )
        return "\n".join(lines)

    def inspect_memorial(slot: int) -> str:
        """查看某条在办事项的细节。slot 是事项编号（由 list_memorials 给出）。"""
        rows = visible_issues()
        try:
            n = int(slot)
        except (ValueError, TypeError):
            return f"slot 必须是整数 1-{len(rows)}。"
        if n < 1 or n > len(rows):
            return f"slot 越界 {n}。本{TURN_UNIT}有 {len(rows)} 条在办事项。"
        row = rows[n - 1]
        commitment_fields = _commitment_tool_fields(context.db, context.state, row)
        commitment_text = f"承诺字段：{commitment_fields}。" if commitment_fields else ""
        return (
            f"#{row['id']} {row['title']}（进展{_progress_band(row['bar_value'])}，"
            f"{row['bar_bad_meaning']}↔{row['bar_good_meaning']}）。"
            f"阶段：{row['stage_text']}。牵涉：{row['faction_hint'] or '—'}。"
            f"结案条件：{_qualitative_condition(row['resolve_condition'])}。"
            f"失败条件：{_qualitative_condition(row['fail_condition'])}。"
            f"{commitment_text}"
        )

    def list_regions() -> str:
        f"""查看两京十三省最危险地区和账面{TURN_UNIT}税。"""
        return scoped_world("regional")

    def inspect_region(region_name: str) -> str:
        """查看某一地区人口、民心、动乱、天灾、人祸、田亩和税收。"""
        # The overview rail is intentionally capped for prompt size, but an
        # office already authorized for the regional domain may inspect a
        # named region.  Use the DB's qualitative presenter rather than its
        # raw detail path so this on-demand read keeps the P4 boundary.
        if not scoped_world("regional") or scoped_world("regional") == "本职见闻未载此项。":
            return "本职见闻未载此项。"
        try:
            return context.db.region_detail(region_name, qualitative=True)
        except ValueError:
            return f"见闻中未载{str(region_name or '').strip()}。"

    def list_buildings() -> str:
        """查看全国在册建筑（火炮厂、矿厂、常平仓、边堡、织造局等）的等级、完好、维护费与产出。"""
        return scoped_world("construction")

    def inspect_building(building_name: str) -> str:
        """查看某座建筑的类别、等级、完好、维护费、风险与产出。"""
        return filter_domain("construction", building_name)

    def estimate_resistance(slot: int) -> str:
        """估算某条在办事项若下旨推动的主要阻力。slot 是事项编号（由 list_memorials 给出）。"""
        rows = visible_issues()
        try:
            n = int(slot)
        except (ValueError, TypeError):
            return f"slot 必须是整数 1-{len(rows)}。"
        if n < 1 or n > len(rows):
            return f"slot 越界 {n}。本{TURN_UNIT}有 {len(rows)} 条在办事项。"
        row = rows[n - 1]
        # The tool may only estimate from the issue already present in the
        # character projection.  Do not rebuild a national resistance score
        # from global factions/regions/armies here: those are separate
        # perspectival rails and would bypass the read boundary.
        resistance = int(row["severity"]) // 4
        tags = row["faction_hint"] or ""
        if resistance >= 23:
            level = "高"
        elif resistance >= 18:
            level = "中"
        else:
            level = "低"
        return f"{row['title']}阻力{level}，主要牵涉：{tags or '—'}。"

    def read_past_report(year: int = 0, month: int = 0) -> str:
        """读某年某月邸报全文，了解此前朝局走向、地方动静、灾兵祸福，避免接旨时凭空臆议。
        **上月邸报已固定注入上下文（见 system 末尾【上回合邸报全文】），无须再调本工具查上月**；
        本工具用于查更早月份。
        参数：
        - year：年份（如 1628）。缺省（0）默认查上上月（上月已在上下文，故缺省往前再退一月）。
        - month：月份（1-12）。缺省（0）配 year 缺省即上上月；若给了 year 而 month=0，按 1 月算。
        所求年月未到、无邸报存档或在登基之前 → 提示『未见正式记录』。"""
        # 缺省：查上上月（state.year/period - 2）——上月邸报已固定在上下文，缺省再往前退一月。
        if not year:
            target_year = context.state.year
            target_month = context.state.period - 2
            while target_month < 1:
                target_month += 12
                target_year -= 1
        else:
            target_year = int(year)
            target_month = int(month) if month else 1
            target_month = max(1, min(12, target_month))
        knowledge = projection()
        rows = [
            item for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]
            if int(item.get("year") or 0) == target_year
            and int(item.get("period") or 0) == target_month
            and item.get("body")
        ]
        if not rows:
            return f"{target_year}年{target_month}月未见正式邸报记录。"
        lines = [f"【{target_year}年{target_month}月见闻】"]
        for item in rows:
            lines.append(f"{item.get('title') or '旧闻'}：{item['body']}")
        return "\n".join(lines)

    def search_memories(keywords: str = "", year: int = 0, period: int = 0) -> str:
        """检索起居注章节旧事。支持两种方式（可同时用）：
        - keywords: 逗号分隔关键词，如 "魏忠贤,下狱" 或 "山东,民变"；
        - year+period: 按年月检索，取前后2月窗口，如 year=1628, period=3。
        两种场景必须调用：1.皇帝问及某人/某地/某事；2.拟旨前涉及人事处置，先查旧况避免重复。
        """
        knowledge = projection()
        all_ch = [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]
        hits = []
        if year:
            ref_turn = (int(year) - 1627) * 12 + (int(period or 1) - 10) + 1
            hits = [c for c in all_ch if abs(int(c.get("turn") or 0) - ref_turn) <= 2]
        kw_list = [k.strip() for k in str(keywords or "").split(",") if k.strip()]
        if kw_list:
            kw_hits = [
                c for c in all_ch
                if any(kw in (c.get("body") or "") or kw in (c.get("title") or "") for kw in kw_list)
            ]
            seen = {c.get("source_id") for c in hits}
            hits += [c for c in kw_hits if c.get("source_id") not in seen]
        if not hits:
            desc = f"「{'、'.join(kw_list)}」" if kw_list else f"{year}年{period}月前后"
            return f"未找到与{desc}相关的起居注记载。"
        tlog(f"[search_memories] kw={kw_list} year={year} period={period} hit={len(hits)}")
        label = " ".join(kw_list) or f"{year}年{period}月"
        lines = [f"【起居注检索：{label}】"]
        for c in sorted(hits, key=lambda item: int(item.get("turn") or 0))[-8:]:
            body = str(c.get("body") or c.get("title") or "")
            if body:
                lines.append(f"- {c['year']}年{c['period']}月：{body}")
        if len(lines) == 1:
            return "未见正式邸报记录。"
        return "\n".join(lines)

    def check_treasury() -> str:
        """查国库、内库、收支和欠账。"""
        return scoped_world("treasury")

    def inspect_treasury_ledger(account: str = "内库", turns: int = 6) -> str:
        """查本职见闻中的国库或内库流水摘要。
        涉及内库/国库调动来源、历史拨款、查抄收益、赏赐开销时调用。
        account: "国库" 或 "内库"；turns: 查最近几回合（默认6）。
        """
        acc = (account or "内库").strip()
        if acc not in {"国库", "内库"}:
            return "account 须为「国库」或「内库」。"
        # The ledger read is owned by the role-scoped knowledge projection.
        # Never reopen economy_ledger here: doing so bypasses the office gate.
        from ming_sim.knowledge import build_character_treasury_ledger
        rendered = build_character_treasury_ledger(
            context.db, context.state, character.name, acc, turns,
        )
        if not rendered:
            return "本职见闻未载此项。"
        return rendered

    def audit_tax_arrears(target: str = "各省积欠") -> str:
        """清查积欠、估算可追收入库。"""
        needle = "" if target.strip() == "各省积欠" else target
        return filter_domain("regional", needle)

    def allocate_payroll(target: str = f"本{TURN_UNIT}急需钱粮处") -> str:
        """核算军饷调度。"""
        needle = "" if target.strip() == f"本{TURN_UNIT}急需钱粮处" else target
        return filter_domain("military", needle)

    def propose_directive(decree_text: str) -> str:
        """把已定处置方案拟成一道圣旨草稿呈给皇帝审阅。decree_text 为完整圣旨正文。"""
        text = (decree_text or "").strip()
        if not text:
            return "拟旨失败：圣旨正文为空。"
        # 返回草稿标记，由 minister_chat / GameSession.chat 截获展示给皇帝确认，不在此入库。
        return f"__pending_directive__{text}"

    def propose_appointment(name: str, office: str, faction: str = "中立", reason: str = "", replaces: str = "") -> str:
        """吏部铨选拟任。name 为拟任者，office 为拟授官职，replaces 为需腾缺的现任官员。"""
        nm = (name or "").strip()
        off = (office or "").strip()
        if not nm or not off:
            return "铨选失败：姓名或拟授官职为空。"
        import json as _json
        payload = _json.dumps(
            {
                "name": nm, "office": off,
                "faction": (faction or "中立").strip(),
                "reason": (reason or "").strip(),
                "replaces": (replaces or "").strip(),
            },
            ensure_ascii=False,
        )
        return f"__pending_appointment__{payload}"

    def register_unlisted_person(
        name: str,
        office: str,
        office_type: str,
        faction: str = "中立",
        aliases_json: str = "[]",
        summary: str = "",
        source: str = "historical",
        summon_after: bool = True,
    ) -> str:
        """登记名册外人物，使其进入本局可召见人物池。

        仅在两种情况下调用：
        1. source="historical"：名册无此人，但你高置信确认其为史实人物（含异体字、误写、近音、别名归一）。
        2. source="user_confirmed"：名册无此人且非明确史实，但皇帝已经说明其身份背景。

        不可用于正式升迁、外放或替换现任官缺；正式任官仍走吏部铨选或圣旨。
        aliases_json 填 JSON 数组字符串，如 ["李若璉","李若链","李若莲"]。
        """
        nm = (name or "").strip()
        off = (office or "").strip()
        kind = (office_type or "").strip()
        if not nm or not off or not kind:
            return "登记失败：姓名、职衔、官署类型不能为空。"
        try:
            aliases = json.loads(aliases_json or "[]")
        except (ValueError, TypeError):
            aliases = []
        if not isinstance(aliases, list):
            aliases = []
        payload = json.dumps(
            {
                "name": nm,
                "office": off,
                "office_type": kind,
                "faction": (faction or "中立").strip(),
                "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
                "summary": (summary or "").strip(),
                "source": (source or "historical").strip(),
                "summon_after": bool(summon_after),
            },
            ensure_ascii=False,
        )
        return f"__pending_unlisted_person__{payload}"

    def secret_order(
        action: str,
        title: str = "",
        content: str = "",
        tags_json: str = "[]",
        assignee: str = "",
        deadline_months: int = 0,
        order_id: int = 0,
        progress: str = "",
        claim: str = "",
        reason: str = "",
        excluded_names_json: str = "[]",
        excluded_offices_json: str = "[]",
        dossier_links_json: str = "[]",
    ) -> str:
        """密令统一入口。action 取值：
        - "issue"：下达新密令。需填 title、content；assignee 留空默认当前大臣；deadline_months=0 无硬限。
        - "progress"：汇报进展（兼查历史）。填 order_id；progress 非空且非建档当月则暂存落档，同月补充会修正本月行。
        - "submit"：提交结案。填 order_id、claim（办结陈词）。
        - "rush"：催办加急。填 order_id；deadline_months=1 下月核议，0=本月即核。

        issue 可用 dossier_links_json 关联当前提示中的旧案卷。它是 JSON 数组，每项必须含
        target_dossier_id（旧案卷整数 ID）、relation_type（护卫/稽核/接应之一）和 note
        （大臣已复述确认的说明）。示例：[{"target_dossier_id":12,"relation_type":"护卫",
        "note":"护送辽饷"}]。未明确确认则传 []。
        """
        # 恢复窗总闸（PR #90 R2 codex P2）：FRONT_HALF_DONE 时四个 action 都是
        # settle 重试事务边界外的直写，重放中止回滚不回滚它们——dispatcher 一处冻全部。
        if context.state.turn_phase in FRONT_HALF_DONE_PHASES:
            return "本月结算未完（恢复中），密令房暂不办事；请先续跑结算，再行降旨。"
        act = (action or "").strip().lower()
        if act == "issue":
            return _secret_order_issue(title, content, tags_json, assignee, deadline_months, excluded_names_json, excluded_offices_json, dossier_links_json)
        if act == "progress":
            return _secret_order_progress(order_id, progress)
        if act == "submit":
            return _secret_order_submit(order_id, claim)
        if act == "rush":
            return _secret_order_rush(order_id, deadline_months, reason)
        return f"未知 action={action!r}，可选：issue / progress / submit / rush。"

    def _secret_order_issue(title: str, content: str, tags_json: str = "[]", assignee: str = "", deadline_months: int = 0, excluded_names_json: str = "[]", excluded_offices_json: str = "[]", dossier_links_json: str = "[]") -> str:
        """皇帝下达密令，返回待确认密令 payload，由召对确认闸门决定是否正式落库。

        title：密令标题。
        content：密令详情，交代任务目标、保密要求、期限等。
        tags_json：JSON 数组，填相关人名/地区/事项关键词，用于日后检索，如 '["辽饷","兵部","密查"]'。
        assignee：实际承办人姓名。留空则默认为当前召见的大臣；若皇帝指名他人承办（如"命毕自严去查"），填该人全名。
        deadline_months：硬期限月数；0 表示无硬期限。若皇帝说"下月务必结案"填 1，说"三个月内结案"填 3。
        dossier_links_json：只填当前提示所列旧案卷，格式为 [{"target_dossier_id": 12,
        "relation_type": "护卫/稽核/接应", "note": "已复述确认的说明"}]。
        """
        t = (title or "").strip()
        c = (content or "").strip()
        if not t or not c:
            return "密令下达失败：标题或内容为空。"
        try:
            tags = json.loads(tags_json or "[]")
            if not isinstance(tags, list):
                tags = []
        except (ValueError, TypeError):
            tags = []
        tags_clean = [str(k).strip() for k in tags if str(k).strip()]
        try:
            excluded = json.loads(excluded_names_json or "[]")
            excluded = [str(k).strip() for k in excluded if str(k).strip()] if isinstance(excluded, list) else []
        except (ValueError, TypeError):
            excluded = []
        try:
            excluded_offices = json.loads(excluded_offices_json or "[]")
            excluded_offices = [str(k).strip() for k in excluded_offices if str(k).strip()] if isinstance(excluded_offices, list) else []
        except (ValueError, TypeError):
            excluded_offices = []
        # Stage the same canonical targets that the durable write boundary
        # enforces.  This keeps function-calling's optional fields from
        # producing a visibly unscoped candidate before confirmation.
        from ming_sim.db import canonical_secret_order_exclusions
        excluded, excluded_offices = canonical_secret_order_exclusions(
            context.db.content, excluded, excluded_offices, f"{t}\n{c}",
        )
        real_assignee = (assignee or "").strip() or character.name
        try:
            raw_links = json.loads(dossier_links_json or "[]")
        except (ValueError, TypeError):
            raw_links = []
        visible_ids = {
            int(row["id"]) for row in context.db.list_referenceable_dossiers(
                character.name, context.state.turn)
        }
        dossier_links = []
        for link in raw_links if isinstance(raw_links, list) else []:
            if not isinstance(link, dict):
                continue
            raw_target_id = link.get("target_dossier_id")
            if not (
                isinstance(raw_target_id, int) and not isinstance(raw_target_id, bool)
                or isinstance(raw_target_id, str) and raw_target_id.isdecimal()
            ):
                continue
            try:
                target_id = strict_int(raw_target_id)
            except (TypeError, ValueError, OverflowError):
                continue
            relation = str(link.get("relation_type") or "").strip()
            note = str(link.get("note") or "").strip()
            if target_id in visible_ids and relation in DOSSIER_LINK_TYPES and note:
                dossier_links.append({"target_dossier_id": target_id, "relation_type": relation, "note": note})
        try:
            deadline = max(0, min(int(deadline_months or 0), 36))
        except (TypeError, ValueError):
            deadline = 0
        return f"__secret_order__{json.dumps({'title': t, 'content': c, 'tags': tags_clean, 'assignee': real_assignee, 'deadline_months': deadline, 'excluded_names': excluded, 'excluded_offices': excluded_offices, 'dossier_links': dossier_links}, ensure_ascii=False)}"

    def _pending_secret_action(action_name: str, order_id: int, payload: Dict[str, object]) -> str:
        # Non-create tools (记进展/催办/提交核议) do **not** pin latest held.
        # Pure-public 问话 must not become secret-origin withheld (S3 参与即知).
        # New oral bloodline is production-pinned only on extract「更新」(new body).
        return "__secret_action__" + json.dumps(
            {"action": action_name, "order_id": int(order_id), "payload": dict(payload or {})},
            ensure_ascii=False,
        )

    def _own_secret_order(order_id: int):
        """取本承办人名下密令；非承办人或不存在返回 (None, 提示串)。"""
        oid = int(order_id) if str(order_id).isdigit() else 0
        if not oid:
            return None, "密令编号无效。"
        order = context.db.get_secret_order(oid)
        if order is None:
            return None, f"查无此密令（编号 #{oid}）。"
        if order["minister_name"] != character.name:
            return None, f"密令 #{oid} 由{order['minister_name']}承办，非你职掌，无从查问。"
        return order, ""

    def _secret_order_progress(order_id: int, progress: str = "") -> str:
        order, err = _own_secret_order(order_id)
        if order is None:
            return err
        if order["status"] != "active":
            return f"密令 #{order['id']} 已{order['status']}，不能再记进展。"
        is_issuing_turn = int(order.get("turn_issued") or 0) == int(context.state.turn)
        note = (progress or "").strip()
        if note and not is_issuing_turn:
            return _pending_secret_action("记进展", int(order["id"]), {"note": note})
        order = context.db.get_secret_order(order["id"]) or order
        parts = [f"密令 #{order['id']}「{order['title']}」状态：{order['status']}。"]
        parts.append(f"查办经过（按月，末行最新）：\n{order['result'] or '尚无进展记录。'}")
        if order.get("sim_note"):
            parts.append(f"外间动静（按月，末行最新）：\n{order['sim_note']}")
        if is_issuing_turn:
            parts.append("⚠️ 本月即建档当月，须待下月起才可查得头绪——本次未落档。")
        elif not note:
            parts.append("ℹ️ 未提供 progress，本月仍未推进。")
        return "\n".join(parts)

    def _secret_order_submit(order_id: int, claim: str) -> str:
        order, err = _own_secret_order(order_id)
        if order is None:
            return err
        if order["status"] != "active":
            return f"密令 #{order['id']} 当前状态 {order['status']}，不可重复提交核议。"
        text = (claim or "").strip()
        if not text:
            return "提交失败：claim 为空。"
        return _pending_secret_action("提交核议", int(order["id"]), {"claim": text})

    def _secret_order_rush(order_id: int, deadline_months: int = 1, reason: str = "") -> str:
        order, err = _own_secret_order(order_id)
        if order is None:
            return err
        if order["status"] != "active":
            return f"密令 #{order['id']} 当前状态 {order['status']}，不能再催办。"
        try:
            raw_deadline = 1 if deadline_months is None or deadline_months == "" else deadline_months
            deadline = max(0, min(int(raw_deadline), 36))
        except (TypeError, ValueError):
            deadline = 1
        return _pending_secret_action(
            "催办", int(order["id"]), {"deadline_months": deadline, "reason": (reason or "").strip()[:120]}
        )

    def dismiss_minister() -> str:
        """结束本次召见，退朝。"""
        return "__dismiss__"

    def summon_minister(name: str) -> str:
        """传召另一位大臣入殿。name 填大臣姓名。"""
        return f"__summon__{name}"

    def recommend_person(name: str, target_office: str, reason: str = "") -> str:
        """具名荐人并交给皇帝确认；只可荐本人的网络/见闻切片中已有的人。"""
        target = str(name or "").strip()
        office = str(target_office or "").strip()
        row = next((item for item in context.db.list_recommendation_candidates(
            context.state, character.name) if item["name"] == target), None)
        if row is None:
            return "荐人失败：此人不在本大臣的派系/见闻可及切片内。"
        if not office:
            return "荐人失败：须说明拟授的目标差事。"
        payload = json.dumps({
            "name": target, "office": office, "reason": str(reason or "").strip(),
            "faction": row["faction"], "replaces": "",
            "recommendation": {
                "candidate_kind": row["candidate_kind"],
                "basis": row["basis"], "recommender": character.name,
                "candidate": row,
            },
        }, ensure_ascii=False)
        return f"__pending_recommendation__{payload}"

    tools = [
        list_memorials,
        inspect_memorial,
        list_regions,
        inspect_region,
        list_buildings,
        inspect_building,
        estimate_resistance,
        read_past_report,
        search_memories,
        inspect_treasury_ledger,
        propose_directive,
        secret_order,
        dismiss_minister,
        summon_minister,
        recommend_person,
        register_unlisted_person,
    ]
    if use_roster_tool:
        tools.append(query_court_roster)
    # A scale threshold may switch an authorized projection from inline text
    # to a tool, but it must never grant a domain the role does not possess.
    if use_army_tool and "military" in (projection().get("world") or {}):
        tools.append(query_army_roster)
    if character.office_type == "吏部":
        tools.append(propose_appointment)
    if character.office_type in ("户部", "内阁", "司礼监"):
        tools.extend([check_treasury, allocate_payroll, audit_tax_arrears])
    unique_tools = []
    seen_tool_names: set = set()
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        if name in seen_tool_names:
            continue
        seen_tool_names.add(name)
        unique_tools.append(tool)
    return unique_tools



def build_board_query_tools(context: CourtContext):
    """推演官与档房书办共用的只读盘面查询工具集。

    支持按名称或 id 查询，两者均接受，自动 fallback。
    无 court tool，无 skill 闸，纯只读。
    """
    def view_state() -> str:
        """查看当前大明核心国势数值（国库/内库/民心/皇威）及派系、阶级、势力总览。"""
        return (
            state_context(context.state)
            + "\n派系：" + context.db.faction_report()
            + "\n" + context.db.class_report()
            + "\n势力：" + context.db.power_report(exclude_self=True)
        )

    def check_treasury() -> str:
        """查国库、内库、收支和欠账明细。"""
        return context.db.treasury_report(context.state)

    def list_regions() -> str:
        f"""查看两京十三省危情概览（动乱/民心/军压/欠饷等排序）。"""
        return context.db.region_report(limit=8)

    def inspect_region(region: str) -> str:
        """查某一地区详细数值：public_support/unrest/grain_security/gentry_resistance/
        military_pressure/corruption/population/registered_land/hidden_land/tax_per_turn/status。
        region 可传地区名（如"陕西"）或 region_id（如"shaanxi"），两者均支持。"""
        try:
            return context.db.region_detail(region)
        except ValueError:
            row = context.db.conn.execute(
                "SELECT id,name,public_support,unrest,grain_security,gentry_resistance,"
                "military_pressure,json_extract(fiscal,'$.corruption') as corruption,"
                "population,registered_land,hidden_land,tax_per_turn,status "
                "FROM regions WHERE id=?", (region,)
            ).fetchone()
            if row is None:
                return f"未找到地区 {region!r}。可先调 list_regions 查名称/id 列表。"
            return str(dict(row))

    def list_armies() -> str:
        """查看大明主要军队的驻扎、月应发军饷（引擎实扣 army_needed）、补给、士气、火器、随军大炮和欠饷警讯。"""
        return context.db.army_report(limit=8)

    def inspect_army(army: str) -> str:
        """查某支军队详细数值：supply/morale/training/equipment/firearm_equipment/cannon_equipment/
        arrears/mobility/loyalty/manpower/army_needed（月应发军饷=引擎实扣）/station/commander/controller/troop_type/status。
        army 可传军队名（如"关宁军"）或 army_id（如"guanning"），两者均支持；动态新建军同样可查。"""
        # army_detail 已统一按 DB id/name 直查 + 静态别名兜底 + SELECT* 渲染(含火器/随军大炮)，
        # 直接复用，不再各写一份窄 SELECT fallback（CMR codexB/C：army render 单一真源）。
        try:
            return context.db.army_detail(army)
        except ValueError:
            return f"未找到军队 {army!r}。可先调 list_armies 查名称/id 列表。"

    def list_powers() -> str:
        """查看后金、蒙古、朝鲜、日本、流寇等势力当前态势（leverage/military_strength/stance/last_action）。"""
        return context.db.power_report(exclude_self=True)

    def inspect_power(power: str) -> str:
        """查某势力完整数值：leverage/satisfaction/military_strength/cohesion/supply/
        leader/stance/agenda/status/last_action。
        power 可传势力名（如"后金"）或 power_id（如"houjin"），两者均支持。"""
        row = context.db.conn.execute(
            "SELECT * FROM powers WHERE id=? OR name=?", (power, power)
        ).fetchone()
        if row is None:
            return f"未找到势力 {power!r}。可先调 list_powers 查名称/id 列表。"
        return str(dict(row))

    def list_issues() -> str:
        """查看当前在办的所有事项（issue）清单及进度。"""
        rows = context.db.list_active_issues()
        if not rows:
            return f"本{TURN_UNIT}无在办事项。"
        lines = []
        for row in rows:
            kind_tag = "系统" if row["kind"] == "situation" else "皇帝推动"
            lines.append(
                f"#{row['id']}[{kind_tag}]{row['title']}"
                f"（bar {int(row['bar_value'])}/{row['bar_good_meaning']}，{row['stage_text']}）"
            )
        return "\n".join(lines)

    def inspect_issue(issue_id: int) -> str:
        """查某条在办事项完整详情：bar_value/inertia/kind/cancellable/stage/
        resolve_condition/fail_condition/faction_hint。issue_id 是数字编号（list_issues 里的 # 数字）。"""
        rows = context.db.list_active_issues()
        try:
            n = int(issue_id)
        except (ValueError, TypeError):
            return "issue_id 必须是整数。"
        row = next((r for r in rows if int(r["id"]) == n), None)
        if row is None:
            return f"未找到在办事项 #{n}。可先调 list_issues 看清单。"
        commitment_fields = _commitment_tool_fields(context.db, context.state, row)
        commitment_text = f"\n承诺字段：{commitment_fields}。" if commitment_fields else ""
        return (
            f"#{row['id']} {row['title']} bar={int(row['bar_value'])} "
            f"inertia={row['inertia']} kind={row['kind']} cancellable={row['cancellable']}\n"
            f"阶段：{row['stage_text']}。牵涉：{row['faction_hint'] or '—'}。\n"
            f"结案条件：{row['resolve_condition'] or '（未填）'}。"
            f"失败条件：{row['fail_condition'] or '（未填）'}。"
            f"{commitment_text}"
        )

    def get_active_ministers() -> str:
        """查当前在朝（active）官员名单：姓名、官职、派系。
        写 canonical 人物变更前必查，核实人物是否确实在朝。"""
        rows = context.db.conn.execute(
            # roster scope（同 court_roster / _talent_pool_rows）：大明、非后宫、非宗藩
            # （宗室就藩非朝堂命官，PR#121；写 canonical 人物变更前查此名单不应见宗藩，cmr R3 cross-section）。
            "SELECT name,office,faction FROM characters WHERE status='active' "
            "AND power_id='ming' AND office_type NOT IN ('后宫','宗藩') ORDER BY rowid"
        ).fetchall()
        return "\n".join(f"{r['name']}：{r['office']}，{r['faction']}" for r in rows)

    def get_faction_class_state() -> str:
        """查派系满意度与各阶级满意度/影响力（全国汇总）。
        写 faction_delta / class_delta 前查当前基准值。"""
        return context.db.faction_report() + "\n" + context.db.class_report()

    return [
        view_state,
        check_treasury,
        list_regions,
        inspect_region,
        list_armies,
        inspect_army,
        list_powers,
        inspect_power,
        list_issues,
        inspect_issue,
        get_active_ministers,
        get_faction_class_state,
    ]


def build_simulator_tools(context: CourtContext):
    """月末推演日讲官工具集：共用查询工具 + submit_report 提交工具。"""
    tools = build_board_query_tools(context)

    _captured_report: list[str] = []

    def submit_report(report_text: str) -> str:
        """提交本月末奏章全文。盘面查清、奏章写完后调用，调用后本月推演即结束。

        ══ 奏章结构 ══
        总标题一句诗（七言或五言），切本月最痛之事，不空泛。
        章节按「实际发生了什么」切，不要「诏书纪要/各方反应」机械分段。3-6章不等，
        每章一句标题+叙事150-300字，相关事可合并。末两章固定：
          「探子回报」（本月发生但未上达/被压的事，1-3条，无则写"无可隐之事"）
          「待办未解」（见下）

        ══ 笔法 ══
        历代邸报体：有时序、有人、有地、有冷暖、留钩子。
        具体数字鼓励写：拨银几万两、调兵几千、流民几万、屠某族几人、谷价几钱、
        灾区几县、限期几日、奏疏几道——越具体越好，给档房足够锚点判强度。
        禁用游戏机制token：bar、±N、N→N、「正向：重」「中度推进」之类强度标签。
        不写「激化/酝酿/阳阴违」抽象词，要写就写谁怎么拖（「巡按上疏推诿，称缇骑越权，留中」）。
        本朝文体：陛下、准奏、具题、留中、奉旨、塘报、是夜、漏二刻。不出戏。
        民生基调要诚实：盘面public_support低/satisfaction低时，写怨声载道铤而走险，不唱赞歌。

        ══ 局势推进 ══
        新局势只两个来源，不自创、不冠「新」字：
          - candidate_events里本月判定触发的——在章节写清来由，对上title，档房转局势
          - 玩家诏书明文强推的长期工程/改革——档房自己识别，邸报不代办
        地方衍生动静（土司争讼/兵丁鼓噪/饥民抢仓）只叙事，并入既有局势，不入库。
        一锤子事当月了结：拿人/罢官/查抄/申饬，本月写定局，不写「会审待覆」拖到下月。
        叙事把因果讲到位：手段+规模+波及面+对手反扑都从文字自现，不写强度词。
        candidate_events逐条判断是否浮现：is_historical=true则原则上必发生（结果受玩家影响）；
        is_historical=false则结合盘面/诏书/局势走向判断。触发的写进叙事，不触发的不写。
        止损原则：对症之策给正向advance，无作为才滑向fail_condition，不造死局。

        ══ 讣闻 ══
        deaths_this_turn里的人本月病逝：关键人物写派系动荡/官缺待补/政策中断；边缘人物一句。
        不为讣闻新立局势。

        ══ 任官与独缺顶替 ══
        诏书任命某官必须点名+写明新官职，在朝者写旧职→新职，新进者写所授官职。
        独占实职（总督/巡抚/总兵/某部尚书）任新人前，先查get_active_ministers有无现任者：
        有则写「原任X 去职/改调/夺职」再写「Y接任」，两人都进人事除目。
        debuts_this_turn是程序自动登场，不进人事除目，简短提一笔到任即可。

        ══ 末章固定 ══
        「人事除目」（有人事变动时必列，无则不列）：
          任官：旧职→新职 or 起用姓名为官职  → 档房抽「人物变更」任命/调任
          去职：姓名+去职缘由（革/狱/流/仕/卒）  → 档房抽「人物变更」罢黜/处置
        「待办未解」：只列active_issues在册局势，逐条状态短语（已具题待覆/已近结案/按其本然推移等），
        每条一句话点局势名与id，不写bar数字，不写from→to。
        「建筑只叙事」：不代标数值、不代立新建筑；新建/扩建走局势effect落地，不在邸报直造。

        ══ 输出格式 ══
        《诗题》
        {年}年{月}月 月末奏章

        一、（章节名）
        （叙事段）
        ...
        N、人事除目
        任官：孙传庭 由永城知县 擢 陕西总督
        去职：魏忠贤 革职拿问下诏狱
        N+1、待办未解
        1. #12 江南清查 — 户部主事至苏州，松江徐氏先具实田
        2. #15 陕西饥荒 — 赈粮未到，延安饥民结伙
        """
        _captured_report.append(report_text)
        return "__report_submitted__"

    context._simulator_report = _captured_report  # type: ignore[attr-defined]
    return tools + [submit_report]


def build_extractor_tools(context: CourtContext):
    """档房书办工具集：共用查询工具 + submit_extraction 提交工具。"""
    tools = build_board_query_tools(context)

    _captured: list[str] = []
    context._extractor_result = _captured  # type: ignore[attr-defined]

    def submit_extraction(json_str: str) -> str:
        """提交本月结算抽取结果。json_str 是严格 JSON 字符串（无 Markdown 包裹）。
        调用后本月 extractor 即结束；只能调用一次。

        ══ 必须包含的顶层字段（无内容填 {} 或 []）══

        metric_delta        两量表增量 {"民心":N,"皇威":N}（增量非新值）
        economy_moves       浮动收支列表，每项 {account(国库/内库),delta,category,reason,origin_ref}；
                            旨意驱动须从 extractor_context.decree_dossiers 选 dossier:<id>，
                            月末局势自然演化须显式填 origin_ref:"盘面自发"
                            单位万两；程序已落账的月度固定收支（税/军饷/建筑维护等）不重复写
                            account按钱出自哪个库定：内帑/内库拨出=内库，户部/太仓=国库
        faction_delta       派系满意度增量 {阉党/皇党/军队/东林/宗室/中立/西学: N}
        class_delta         阶级满意度/影响力增量
                            key="农民"(全国)或"农民@shaanxi"(省级切片)
                            value={"satisfaction":N,"leverage":N}（可只写一个）
        region_delta        地区数值变化 {region_id: {字段:增量,origin_ref}}
                            合法字段：public_support/unrest/grain_security/gentry_resistance/
                            military_pressure/corruption/population/registered_land/
                            hidden_land/tax_per_turn/natural_disaster/human_disaster/status
                            减人口写population，禁止写manpower（军队字段）
        army_delta          军队数值变化 {army_id: {字段:增量,origin_ref}}
                            合法字段：supply/morale/training/equipment/arrears/mobility/loyalty/
                            manpower/station/commander/controller/troop_type/status
                            禁止写cohesion（势力字段）。army_delta.arrears/欠饷只允许既有军
                            正值外生加欠，引擎按饷源比例拆入省/中央累加器；负值拒收。
                            补饷、减欠、核销必须走 economy_moves（purpose=补饷）或显式核销路径。
                            新军初始欠饷固定 0，不在 new_armies 写欠饷。
        new_armies          新建军队列表，每项含 id/name/owner_power/manpower/station/origin_ref/
                            commander/troop_type/status 等完整军队字段。
                            owner_power="ming" 且不是土司/自养军时，必须写饷源三字段：
                            pay_source_region/饷源省=明控省 region_id，
                            province_pay_share/省份额 与 central_pay_share/中央份额
                            为 0-1 小数且两者和为 1（纯省源 1.0/0.0，混合如 0.65/0.35）。
                            土司/自养明军才写 is_tusi/土司 或 self_funded_pay/自养军饷，
                            且饷源比例为 0/0；非明军不写明军饷源。
                            明军月饷总额由引擎按 manpower 派生，不写饷额。
        power_updates       别的势力三项简单属性 {power_id: {"威望":N,"实力":N,"经济":N,origin_ref}}
                            只写非大明势力；三项均为整数增量；不写立场/近动/状态
        world_advance       外交态度 KV；key 为势力名或 power_id，value 为简短态度字符串
                            如 {"后金":"敌对","蒙古":"摇摆","朝鲜":"倾明"}；无内容填 {}
        issue_advances      既有局势推进列表
                            每项：{issue_id(integer),delta_bar,stage_text,narrative,可选inertia_delta}
                            delta_bar=皇帝实旨推动量（不含自然漂移inertia，系统自动算）
                            档位：极端±40~50、重大±20~35、中等±8~15、轻度±1~5
                            本月未被实旨推动的填delta_bar:0（靠inertia自然漂）
        new_issues          本月新立局势/圣旨承诺
                            来源(a) origin_kind:"decree"——诏书明文长期工程/改革，需：
                              kind(initiative/situation),title,origin_kind,bar_value(0-100),
                              expected_months(整数),stage_text,resolve_condition,fail_condition,
                              ongoing_effects,effect_on_resolve,effect_on_fail,
                              cancellable(decree/never/by_progress)
                              effect_on_resolve/fail 可含 metrics/economy/factions/buildings
                              buildings每项：{action:create/modify/remove,origin_ref,...}；来源同样只能为已颁 dossier:<id> 或盘面自发
                            圣旨承诺(#136)固定 kind:"initiative" 且必须有
                              origin_ref(只能从 extractor_context.decree_dossiers 选择
                              dossier:<id>),commitment_kind:"until_stop"；
                              直到补齐/达标：ongoing_effects 语义非空 + stop_condition(dict)
                              人物安抚类 ongoing_effects 写 {"人物变更":[{"name":"毛文龙","动作":"评定","loyalty":2}]}
                              连续N月/半年为限：ongoing_effects 语义非空 + end_turn(turn+N，且必须大于当前turn)
                              未来一次性复试/复核：end_turn，ongoing_effects 可为空/语义空
                              stop_condition 只收 dict，如 {"army.guanning.arrears":"<=0"}；
                              承诺落库后自动 inertia=0,cancellable="decree"
                            来源(b) origin_kind:"event_pool"——只两字段：origin_kind+"id"(从candidate_events选)
                            一锤子事（当回合即办结）不立局势，直接落metric_delta等
        cancels             撤销局势 [{issue_id,applied_cost,narrative}]
        close_issues        结案/失败/到期待裁承诺ACK [{issue_id,reason(resolved/failed/acknowledged),narrative}]
                            对照resolve_condition/fail_condition判，条件命中即报
                            不可崩坏局势（天灾/大旱等effect_on_fail为空）禁止reason=failed
                            acknowledged仅用于无语义 ongoing 且已到期的圣旨承诺已由皇帝裁决确认
        fiscal_changes      制度性财政系数变化 [{key,delta,reason,origin_ref}]
                            origin_ref 必填：已颁 dossier:<id> 或精确 盘面自发
                            key只从财政系数表选：田赋_rate/辽饷_base/辽饷_rate/盐税_base/盐税_rate/
                            商税_base/商税_rate/皇庄_base/皇庄_rate/织造_base/织造_rate/矿税_base/矿税_rate/
                            宗室禄米_base/宗室禄米_rate/官俸_base/官俸_rate/工程_base/工程_rate/
                            赈灾_base/赈灾_rate/宫廷_base/宫廷_rate/
                            内廷俸_base/内廷俸_rate/妃嫔_base/妃嫔_rate
        人物变更            ADR0009 人事档案唯一生产入口；每项必须含 name、动作、origin_ref。
                            动作∈任命/罢黜/调任/处置/易主/册封/行止/评定；按动作补 office、
                            office_type、status、new_power、location、transit_to、loyalty、reason。

        ══ 档位判定标准 ══
        极端：屠戮全族/抄家灭门/决定性战胜败  bar±40~50  metric±20~30  faction±20~40
        重大：严旨+钱粮到位+硬办/抓多人/决定性战役/关键阁臣罢免  bar±20~35  metric±10~20  faction±10~20
        中等：遭抗争但在动/单人下狱/单地清丈到位/单战小胜败/单臣罢黜  bar±8~15  metric±3~10  faction±3~10
        轻度：只走流程/上疏留中/申饬/零星骚动/礼仪赏赐  bar±1~5  metric±1~3  faction±1~3

        民心严控：只有实打实惠民才正向（+1~3封顶）；横征暴敛/灾荒无救=-5~-15
        皇威严控：只有强势办成硬事才正向；例行推进0~+2；旨意被拖/战败=-3~-12
        禁止双重计账：issue effect_on_resolve已给过皇威，metric_delta不要再给

        ══ 输出 JSON 骨架示例 ══
        {
          "metric_delta": {"民心": -3, "皇威": 2},
          "economy_moves": [{"account":"国库","delta":-15,"category":"赈灾","reason":"陕西赈粮","origin_ref":"dossier:17"}],
          "faction_delta": {"阉党": -5, "东林": 4},
          "class_delta": {"农民@shaanxi": {"satisfaction": -6, "leverage": 5}},
          "region_delta": {"shaanxi": {"unrest": 5, "grain_security": -3, "origin_ref":"盘面自发"}},
          "army_delta": {"guanning": {"morale": -3, "arrears": 5, "origin_ref":"dossier:17"}},
          "new_armies": [{"id":"qin_army","name":"秦军新营","owner_power":"ming",
                          "manpower":8000,"station":"陕西/西安","commander":"孙传庭",
                          "troop_type":"募兵步骑","pay_source_region":"shaanxi",
                          "province_pay_share":0.65,"central_pay_share":0.35,
                          "status":"新募，亟待操练","origin_ref":"dossier:17"}],
          "power_updates": {"houjin": {"威望": -4, "实力": -3, "经济": -2, "origin_ref":"盘面自发"}},
          "world_advance": {"后金": "敌对", "蒙古": "摇摆", "朝鲜": "倾明"},
          "issue_advances": [{"issue_id":12,"delta_bar":15,"stage_text":"户部主事至苏州","narrative":"..."}],
          "new_issues": [{"kind":"initiative","title":"火器营试设","origin_kind":"decree","bar_value":20,"expected_months":10,"stage_text":"...","resolve_condition":"...","fail_condition":"...","ongoing_effects":{},"effect_on_resolve":{"metrics":{"皇威":3}},"effect_on_fail":{"metrics":{"皇威":-4}},"cancellable":"by_progress"},
                         {"kind":"initiative","title":"三月后复试孙承宗","origin_kind":"decree","origin_ref":"dossier:17","commitment_kind":"until_stop","end_turn":4,"ongoing_effects":{}}],
          "cancels": [],
          "close_issues": [{"issue_id":9,"reason":"resolved","narrative":"..."}],
          "fiscal_changes": [],
          "人物变更": [{"name":"魏忠贤","动作":"处置","status":"exiled","reason":"发配凤阳","origin_ref":"dossier:17"},
                       {"name":"孙传庭","动作":"任命","office":"陕西总督","office_type":"督抚","reason":"永城知县擢用","origin_ref":"dossier:17"}]
        }
        """
        _captured.append(json_str)
        return "__extraction_submitted__"

    return tools + [submit_extraction]
