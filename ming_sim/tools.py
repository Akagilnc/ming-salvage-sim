"""大臣 Agent 工具集：查询工具 + court tools（拟旨/退下/换人）。L5。"""

from __future__ import annotations

import difflib
import json
import re

from ming_sim.constants import TURN_UNIT
from ming_sim.context import _ctx as _content_ctx, state_context
from ming_sim.models import Character, CourtContext
from ming_sim.skills import available_skill_ids, skill_template

_STATUS_CN = {
    "active": "在朝",
    "dismissed": "已罢黜",
    "imprisoned": "下狱",
    "exiled": "流放",
    "retired": "致仕",
    "dead": "已故",
}


def _normalize_person_name(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _match_character_by_name(name: str) -> Character | None:
    key = _normalize_person_name(name)
    if not key:
        return None
    characters = [c for c in _content_ctx().characters.values() if c.office_type != "后宫"]
    for c in characters:
        names = [c.name, *(c.aliases or [])]
        if any(_normalize_person_name(n) == key for n in names):
            return c
    for c in characters:
        names = [c.name, *(c.aliases or [])]
        if any(key in _normalize_person_name(n) or _normalize_person_name(n) in key for n in names):
            return c
    choices = {c.name: c for c in characters}
    match = difflib.get_close_matches(key, list(choices.keys()), n=1, cutoff=0.6)
    return choices[match[0]] if match else None


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


def _assignment_hint(text: str) -> str:
    if not text:
        return ""
    places = [
        "山海关", "宁远", "辽东", "陕西", "延绥", "宣大", "登莱", "山东", "河南",
        "南直隶", "南京", "江南", "苏州", "松江", "湖广", "四川", "福建", "浙江",
        "广东", "广西", "京师",
    ]
    verbs = ("赴", "往", "至", "驻", "巡", "督押", "赍旨赴", "差往", "前往")
    if not any(v in text for v in verbs):
        return ""
    hits = [p for p in places if p in text]
    if not hits:
        return ""
    return "近来差遣：" + "、".join(hits[:4]) + "。"


def build_minister_tools(character: Character, context: CourtContext):
    skill_ids = set(available_skill_ids(character, context.db))

    def view_state() -> str:
        """查看当前大明核心国势数值（含派系/阶级/外部势力）。"""
        return (
            state_context(context.state)
            + "。派系：" + context.db.faction_report()
            + "。" + context.db.class_report()
            + "。外部：" + context.db.external_power_report()
        )

    def list_memorials() -> str:
        """查看当前在办的所有事项（issue）。"""
        rows = context.db.list_active_issues()
        if not rows:
            return f"本{TURN_UNIT}无在办事项。"
        lines = []
        for idx, row in enumerate(rows, 1):
            kind_tag = "系统" if row["kind"] == "situation" else "皇帝推动"
            lines.append(
                f"{idx}. #{row['id']}[{kind_tag}]{row['title']}"
                f"（bar {int(row['bar_value'])}/{row['bar_good_meaning']}，{row['stage_text']}）"
            )
        return "\n".join(lines)

    def inspect_memorial(slot: int) -> str:
        """查看某条在办事项的细节。slot 是事项编号（由 list_memorials 给出）。"""
        rows = context.db.list_active_issues()
        try:
            n = int(slot)
        except (ValueError, TypeError):
            return f"slot 必须是整数 1-{len(rows)}。"
        if n < 1 or n > len(rows):
            return f"slot 越界 {n}。本{TURN_UNIT}有 {len(rows)} 条在办事项。"
        row = rows[n - 1]
        return (
            f"#{row['id']} {row['title']}（bar {int(row['bar_value'])}，{row['bar_bad_meaning']}↔{row['bar_good_meaning']}）。"
            f"阶段：{row['stage_text']}。牵涉：{row['faction_hint'] or '—'}。"
            f"结案条件：{row['resolve_condition'] or '（未填）'}。失败条件：{row['fail_condition'] or '（未填）'}。"
        )

    def list_regions() -> str:
        f"""查看两京十三省最危险地区和账面{TURN_UNIT}税。"""
        return context.db.region_report(limit=6)

    def inspect_region(region_name: str) -> str:
        """查看某一地区人口、民心、动乱、天灾、人祸、田亩和税收。"""
        try:
            return context.db.region_detail(region_name)
        except ValueError as e:
            return f"未找到地区 '{region_name}'。可先调 list_regions 看地区 id/名称列表。错误：{e}"

    def list_armies() -> str:
        """查看大明主要军队的驻扎、维护费、补给、士气和欠饷警讯。"""
        return context.db.army_report(limit=6)

    def inspect_army(army_name: str) -> str:
        """查看某支军队驻扎地、兵种、人数、维护费、补给、士气、训练和欠饷。"""
        try:
            return context.db.army_detail(army_name)
        except ValueError as e:
            return f"未找到军队 '{army_name}'。可先调 list_armies 看军队 id/名称列表。错误：{e}"

    def list_external_powers() -> str:
        """查看后金、蒙古、朝鲜、流寇等外部势力状态。"""
        return context.db.external_power_report()

    def list_buildings() -> str:
        """查看全国在册建筑（火炮厂、矿厂、常平仓、边堡、织造局等）的等级、完好、维护费与产出。"""
        return context.db.buildings_report()

    def inspect_building(building_name: str) -> str:
        """查看某座建筑的类别、等级、完好、维护费、风险与产出。"""
        try:
            return context.db.building_detail(building_name)
        except ValueError as e:
            return f"未找到建筑 '{building_name}'。可先调 list_buildings 看建筑列表。错误：{e}"

    def list_court() -> str:
        """查在朝（及被罢/下狱/流放/致仕）官员名册：姓名、现职、派系、状态。"""
        lines = []
        for c in _content_ctx().characters.values():
            if c.office_type == "后宫":
                continue
            status, _ = context.db.get_character_status(c.name)
            if status == "offstage":
                continue  # 未登场者不泄露，防剧透
            tag = _STATUS_CN.get(status, status)
            suffix = "" if status == "active" else f"（{tag}）"
            lines.append(f"{c.name}：{c.office}，{c.faction}{suffix}")
        return "在朝官员名册：\n" + "\n".join(lines)

    def list_personnel() -> str:
        """查看当前人事总表：姓名、现职、派系、状态与任事处。"""
        lines = []
        for c in _content_ctx().characters.values():
            if c.office_type == "后宫":
                continue
            status, reason = context.db.get_character_status(c.name)
            if status == "offstage":
                continue
            tag = _STATUS_CN.get(status, status)
            location = _duty_location(c.office, c.office_type, status)
            suffix = f"；{reason}" if reason else ""
            lines.append(f"{c.name}：{c.office or '无现任官职'}，{c.faction}，{tag}，{location}{suffix}")
        return f"当前时点：{context.state.year}年{context.state.period}月。\n人事总表：\n" + "\n".join(lines)

    def inspect_minister(name: str) -> str:
        """查某位官员的现任官职、派系、当前状态、任事处和近来差遣。"""
        target = _match_character_by_name(name)
        if target is None:
            return f"名册中无『{name}』。可先调 list_personnel/list_court 看在朝官员名单。"
        status, reason = context.db.get_character_status(target.name)
        if status == "offstage":
            return f"『{target.name}』尚未起用入朝。"
        tag = _STATUS_CN.get(status, status)
        location = _duty_location(target.office, target.office_type, status)
        office_row = context.db.conn.execute(
            "SELECT office_title, office_type, source, updated_at FROM character_offices WHERE character_name=?",
            (target.name,),
        ).fetchone()
        office_source = ""
        if office_row:
            office_source = f"任职记录：{office_row['office_title']}（{office_row['office_type']}，来源：{office_row['source']}，更新时间：{office_row['updated_at']}）。"
        recent_directives = context.db.conn.execute(
            """
            SELECT turn, year, period, text, source, status, notes
            FROM turn_directives
            WHERE actor = ? OR text LIKE ?
            ORDER BY turn DESC, id DESC
            LIMIT 3
            """,
            (target.name, f"%{target.name}%"),
        ).fetchall()
        out = (
            f"当前时点：{context.state.year}年{context.state.period}月。"
            f"{target.name}：现职{target.office}，职位类型{target.office_type}，派系{target.faction}，状态{tag}。"
            f"任事处：{location}"
        )
        if reason:
            out += f"（{reason}）"
        if target.summary:
            out += f"简介：{target.summary}"
        if office_source:
            out += "\n" + office_source
        if recent_directives:
            lines = [
                f"{r['year']}年{r['period']}月：{r['source']}（{r['status']}）{str(r['text'])[:80]}"
                + (f"；{r['notes']}" if r["notes"] else "")
                for r in recent_directives
            ]
            assignment = next((_assignment_hint(str(r["text"] or "")) for r in recent_directives if _assignment_hint(str(r["text"] or ""))), "")
            if assignment:
                out += "\n" + assignment
            out += "\n近来牵涉诏令/草案：\n" + "\n".join(lines)
        return out

    def inspect_personnel_changes(name: str = "") -> str:
        """查某人或全朝最近人事变动（任命、调任、罢黜、下狱、致仕、死亡）。"""
        target = _match_character_by_name(name) if name else None
        where = ""
        params: list[object] = []
        if target is not None:
            where = "WHERE character_name = ?"
            params.append(target.name)
        office_rows = context.db.conn.execute(
            f"""
            SELECT character_name, office_title, office_type, source, updated_at
            FROM character_offices
            {where}
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
        status_rows = []
        if target is not None:
            status_rows = context.db.conn.execute(
                """
                SELECT name, status, status_reason, status_changed_turn
                FROM characters
                WHERE name = ? AND status_reason != ''
                """,
                (target.name,),
            ).fetchall()
        else:
            status_rows = context.db.conn.execute(
                """
                SELECT name, status, status_reason, status_changed_turn
                FROM characters
                WHERE status_reason != ''
                ORDER BY status_changed_turn DESC
                LIMIT 10
                """
            ).fetchall()
        if not office_rows and not status_rows:
            return "暂无可查的人事变动记录。"
        lines = [f"当前时点：{context.state.year}年{context.state.period}月。"]
        if office_rows:
            lines.append("任职记录：")
            for r in office_rows:
                lines.append(f"- {r['character_name']}：{r['office_title']}（{r['office_type']}），来源：{r['source']}，更新时间：{r['updated_at']}")
        if status_rows:
            lines.append("状态变更：")
            for r in status_rows:
                lines.append(f"- {r['name']}：{_STATUS_CN.get(r['status'], r['status'])}，第{r['status_changed_turn']}回合，{r['status_reason']}")
        return "\n".join(lines)

    def estimate_resistance(slot: int) -> str:
        """估算某条在办事项若下旨推动的主要阻力。slot 是事项编号（由 list_memorials 给出）。"""
        rows = context.db.list_active_issues()
        try:
            n = int(slot)
        except (ValueError, TypeError):
            return f"slot 必须是整数 1-{len(rows)}。"
        if n < 1 or n > len(rows):
            return f"slot 越界 {n}。本{TURN_UNIT}有 {len(rows)} 条在办事项。"
        row = rows[n - 1]
        db = context.db
        faction_lev_avg = db.conn.execute("SELECT AVG(leverage) AS v FROM factions").fetchone()["v"] or 50
        resistance = int(row["severity"]) // 4 + int(faction_lev_avg) // 6
        tags = row["faction_hint"] or ""
        if any(t in tags for t in ("边", "军")):
            arrears_avg = db.conn.execute("SELECT AVG(arrears) AS v FROM armies").fetchone()["v"] or 0
            resistance += int(arrears_avg) // 12
        if any(t in tags for t in ("百姓", "地方", "士绅")):
            unrest_avg = db.conn.execute("SELECT AVG(unrest) AS v FROM regions").fetchone()["v"] or 0
            resistance += int(unrest_avg) // 12
        if any(t in tags for t in ("户部", "财")):
            resistance += max(0, 500 - context.state.metrics["国库"]) // 50
        if resistance >= 28:
            level = "高"
        elif resistance >= 18:
            level = "中"
        else:
            level = "低"
        return f"{row['title']}阻力{level}，主要牵涉：{tags or '—'}。估算阻力值：{resistance}。"

    def read_past_report(year: int = 0, month: int = 0) -> str:
        """读某年某月邸报全文，了解此前朝局走向、地方动静、灾兵祸福，避免接旨时凭空臆议。
        参数：
        - year：年份（如 1628）。缺省（0）默认查上月。
        - month：月份（1-12）。缺省（0）配 year 缺省即上月；若给了 year 而 month=0，按 1 月算。
        所求年月未到、无邸报存档或在登基之前 → 提示『未见正式记录』。"""
        # 缺省：查上月（state.year/period - 1）
        if not year:
            target_year = context.state.year
            target_month = context.state.period - 1
            if target_month < 1:
                target_month = 12
                target_year -= 1
        else:
            target_year = int(year)
            target_month = int(month) if month else 1
            target_month = max(1, min(12, target_month))
        row = context.db.conn.execute(
            "SELECT turn, report FROM turn_reports WHERE year=? AND period=?",
            (target_year, target_month),
        ).fetchone()
        if not row or not row["report"]:
            return f"{target_year}年{target_month}月未见正式邸报记录。"
        return f"【{target_year}年{target_month}月邸报】\n{row['report']}"

    def recall_memory_detail(memory_id: int) -> str:
        """查某条旧事记忆的原始来源摘录。只有需要引用旧事细节、被皇帝追问经过、或准备据旧事拟旨时调用。"""
        try:
            mid = int(memory_id)
        except (TypeError, ValueError):
            return "memory_id 必须是旧事记忆编号。"
        return context.db.event_memory_detail(mid)

    def recall_memories_by_time(
        year: int,
        period: int,
        keywords: str = "",
    ) -> str:
        """按年月回忆历史旧事，可附加关键词辅助检索。
        皇帝问及某年某月旧事、或需追溯特定时期事件时调用。
        year: 年份（如1628）；period: 月份1-12；keywords: 逗号分隔的人名/地名/势力名（可为空）。
        时间查询绕过记忆衰减，能追溯已过期的历史记忆。
        """
        ref_turn = (int(year) - 1627) * 12 + (int(period) - 10) + 1
        kw_list = [k.strip() for k in str(keywords).split(",") if k.strip()] if keywords else []

        # 时间查：精确该月，ignore_expiry（历史档案，无视衰减）
        time_rows = context.db.conn.execute(
            """
            SELECT id, year, period, subject_id, title, cause, outcome, importance
            FROM event_memories
            WHERE turn = ?
            ORDER BY importance DESC
            LIMIT 10
            """,
            (ref_turn,),
        ).fetchall()

        # 关键词查：tags匹配，正常衰减过滤
        kw_rows = context.db.get_memories_by_keywords(
            kw_list, turn=context.state.turn, limit=10, ignore_expiry=False
        ) if kw_list else []

        # 合并去重，时间查优先
        seen: set = set()
        merged = []
        for r in list(time_rows) + list(kw_rows):
            rid = r["id"] if hasattr(r, "keys") else r[0]
            if rid not in seen:
                seen.add(rid)
                merged.append(r)

        if not merged:
            return f"{year}年{period}月前后未见相关旧事记忆。"
        lines = [f"【{year}年{period}月旧事】"]
        for r in merged:
            lines.append(
                f"- #{r['id']} {r['year']}年{r['period']}月 {r['subject_id']}："
                f"{r['title']}。起因：{r['cause']}。结果：{r['outcome']}。"
            )
        return "\n".join(lines)

    def check_treasury() -> str:
        """查国库、内库、收支和欠账。"""
        return skill_template("check_treasury_prefix") + context.db.treasury_report(context.state)

    def audit_tax_arrears(target: str = "各省积欠") -> str:
        """清查积欠、估算可追收入库。"""
        return skill_template("audit_tax_arrears", target=target)

    def allocate_payroll(target: str = f"本{TURN_UNIT}急需钱粮处") -> str:
        """核算军饷调度。"""
        return skill_template("allocate_payroll", target=target)

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

    def dismiss_minister() -> str:
        """结束本次召见。"""
        return "__dismiss__"

    def summon_minister(name: str) -> str:
        """传召另一位大臣。name 填大臣姓名。"""
        return f"__summon__{name}"

    tools = [
        view_state,
        list_memorials,
        inspect_memorial,
        list_regions,
        inspect_region,
        list_armies,
        inspect_army,
        list_external_powers,
        list_buildings,
        inspect_building,
        list_court,
        list_personnel,
        inspect_minister,
        inspect_personnel_changes,
        estimate_resistance,
        read_past_report,
        recall_memory_detail,
        recall_memories_by_time,
        propose_directive,
        dismiss_minister,
        summon_minister,
    ]
    # 吏部尚书专属：铨选任命，可把名册外的史实官员补入朝堂。
    if character.office_type == "吏部":
        tools.append(propose_appointment)
    if "check_treasury" in skill_ids:
        tools.append(check_treasury)
    if "allocate_payroll" in skill_ids:
        tools.extend([check_treasury, allocate_payroll])
    if "audit_tax_arrears" in skill_ids:
        tools.append(audit_tax_arrears)
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
        """查看当前大明核心国势数值（国库/内库/民心/皇威）及派系、阶级、外部势力总览。"""
        return (
            state_context(context.state)
            + "\n派系：" + context.db.faction_report()
            + "\n" + context.db.class_report()
            + "\n外部势力：" + context.db.external_power_report()
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
        """查看大明主要军队的驻扎、维护费、补给、士气和欠饷警讯。"""
        return context.db.army_report(limit=8)

    def inspect_army(army: str) -> str:
        """查某支军队详细数值：supply/morale/training/equipment/arrears/mobility/loyalty/
        manpower/maintenance_per_turn/station/commander/controller/troop_type/status。
        army 可传军队名（如"关宁军"）或 army_id（如"guanning"），两者均支持。"""
        try:
            return context.db.army_detail(army)
        except ValueError:
            row = context.db.conn.execute(
                "SELECT id,name,station,commander,controller,troop_type,manpower,"
                "maintenance_per_turn,supply,morale,training,equipment,arrears,mobility,loyalty,status "
                "FROM armies WHERE id=?", (army,)
            ).fetchone()
            if row is None:
                return f"未找到军队 {army!r}。可先调 list_armies 查名称/id 列表。"
            return str(dict(row))

    def list_external_powers() -> str:
        """查看后金、蒙古、朝鲜、流寇等外部势力当前态势（leverage/military_strength/stance/last_action）。"""
        return context.db.external_power_report()

    def inspect_external_power(power: str) -> str:
        """查某外部势力完整数值：leverage/satisfaction/military_strength/cohesion/supply/
        leader/stance/agenda/status/last_action。
        power 可传势力名（如"后金"）或 power_id（如"houjin"），两者均支持。"""
        row = context.db.conn.execute(
            "SELECT * FROM external_powers WHERE id=? OR name=?", (power, power)
        ).fetchone()
        if row is None:
            return f"未找到外部势力 {power!r}。可先调 list_external_powers 查名称/id 列表。"
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
        return (
            f"#{row['id']} {row['title']} bar={int(row['bar_value'])} "
            f"inertia={row['inertia']} kind={row['kind']} cancellable={row['cancellable']}\n"
            f"阶段：{row['stage_text']}。牵涉：{row['faction_hint'] or '—'}。\n"
            f"结案条件：{row['resolve_condition'] or '（未填）'}。"
            f"失败条件：{row['fail_condition'] or '（未填）'}。"
        )

    def get_active_ministers() -> str:
        """查当前在朝（active）官员名单：姓名、官职、派系。
        写 office_changes / character_status_changes 前必查，核实人物是否确实在朝。"""
        rows = context.db.conn.execute(
            "SELECT name,office,faction FROM characters WHERE status='active' ORDER BY rowid"
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
        list_external_powers,
        inspect_external_power,
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
          「陛下未知者」（本月发生但未上达/被压的事，1-3条，无则写"无可隐之事"）
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
          任官：旧职→新职 or 起用姓名为官职  → 档房抽office_changes
          去职：姓名+去职缘由（革/狱/流/仕/卒）  → 档房抽character_status_changes
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

        ══ 必须包含的 16 个顶层字段（无内容填 {} 或 []）══

        metric_delta        两量表增量 {"民心":N,"皇威":N}（增量非新值）
        economy_moves       浮动收支列表，每项 {account(国库/内库),delta,category,reason}
                            单位万两；fixed_flows已落账的固定项不重复写
                            account按钱出自哪个库定：内帑/内库拨出=内库，户部/太仓=国库
        faction_delta       派系满意度增量 {阉党/皇党/军队/东林/宗室/中立/西学: N}
        class_delta         阶级满意度/影响力增量
                            key="农民"(全国)或"农民@shaanxi"(省级切片)
                            value={"satisfaction":N,"leverage":N}（可只写一个）
        region_delta        地区数值变化 {region_id: {字段:增量}}
                            合法字段：public_support/unrest/grain_security/gentry_resistance/
                            military_pressure/corruption/population/registered_land/
                            hidden_land/tax_per_turn/natural_disaster/human_disaster/status
                            减人口写population，禁止写manpower（军队字段）
        army_delta          军队数值变化 {army_id: {字段:增量}}
                            合法字段：supply/morale/training/equipment/arrears/mobility/loyalty/
                            manpower/maintenance_quarter/station/commander/controller/troop_type/status
                            禁止写cohesion（外部势力字段）
        external_power_updates  外部势力变化 {power_id: {字段}}
                            数值字段填增量：leverage/satisfaction/military_strength/cohesion/supply
                            文字字段填新值：leader/stance/agenda/status/last_action
        world_advance       四方动向综述，后金/蒙古/朝鲜/流寇都必须有（无动作写"无新动"）
                            {"后金":{stance,action,impact,intent},"蒙古":{...},"朝鲜":{...},"流寇":{...},"summary":"..."}
        issue_advances      既有局势推进列表
                            每项：{issue_id(integer),delta_bar,stage_text,narrative,可选inertia_delta}
                            delta_bar=皇帝实旨推动量（不含自然漂移inertia，系统自动算）
                            档位：极端±40~50、重大±20~35、中等±8~15、轻度±1~5
                            本月未被实旨推动的填delta_bar:0（靠inertia自然漂）
        new_issues          本月新立局势
                            来源(a) origin_kind:"decree"——诏书明文长期工程/改革，需全字段：
                              kind(initiative/situation),title,origin_kind,bar_value(0-100),
                              expected_months(整数),stage_text,resolve_condition,fail_condition,
                              ongoing_effects,effect_on_resolve,effect_on_fail,
                              cancellable(decree/never/by_progress)
                              effect_on_resolve/fail 可含 metrics/economy/factions/buildings
                              buildings每项：{action:create/modify/remove,...}
                            来源(b) origin_kind:"event_pool"——只两字段：origin_kind+"id"(从candidate_events选)
                            一锤子事（当回合即办结）不立局势，直接落metric_delta等
        cancels             撤销局势 [{issue_id,applied_cost,narrative}]
        close_issues        结案/失败 [{issue_id,reason(resolved/failed),narrative}]
                            对照resolve_condition/fail_condition判，条件命中即报
                            不可崩坏局势（天灾/大旱等effect_on_fail为空）禁止reason=failed
        fiscal_changes      制度性财政系数变化 [{key,delta,reason}]
                            key只从财政系数表选：田赋_rate/辽饷_base/辽饷_rate/盐税_base/盐税_rate/
                            商税_base/商税_rate/皇庄_base/皇庄_rate/织造_base/织造_rate/矿税_base/矿税_rate/
                            宗室禄米_base/宗室禄米_rate/官俸_base/官俸_rate/工程_base/工程_rate/
                            赈灾_base/赈灾_rate/九边补给_base/九边补给_rate/宫廷_base/宫廷_rate/
                            内廷俸_base/内廷俸_rate/妃嫔_base/妃嫔_rate
        appointments        仅后宫纳妃 [{name,office,office_type:"后宫",reason,approved}]
                            decree_text明文"纳/册封/封/选 某某 为 位号"才立；朝臣一律不进此字段
        character_status_changes  大臣状态变更 [{name,status,reason}]
                            status∈dismissed/imprisoned/exiled/retired/dead/offstage
                            邸报明文写到此人此事才立；既已dismissed/dead的不重复
        office_changes      朝臣官职变更 [{name,new_office,reason,可选faction/new_office_type}]
                            任何人任某官（新进朝堂/调任/升迁）一律走此字段，不分新旧任
                            new_office必须是明制实官名；去职走character_status_changes

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
          "economy_moves": [{"account":"国库","delta":-15,"category":"赈灾","reason":"陕西赈粮"}],
          "faction_delta": {"阉党": -5, "东林": 4},
          "class_delta": {"农民@shaanxi": {"satisfaction": -6, "leverage": 5}},
          "region_delta": {"shaanxi": {"unrest": 5, "grain_security": -3}},
          "army_delta": {"guanning": {"morale": -3, "arrears": 5}},
          "external_power_updates": {"houjin": {"leverage": -4, "last_action": "退屯整兵"}},
          "world_advance": {"后金": {"stance":"敌对","action":"...","impact":"...","intent":"..."},"蒙古":{},"朝鲜":{},"流寇":{},"summary":"..."},
          "issue_advances": [{"issue_id":12,"delta_bar":15,"stage_text":"户部主事至苏州","narrative":"..."}],
          "new_issues": [{"kind":"initiative","title":"火器营试设","origin_kind":"decree","bar_value":20,"expected_months":10,"stage_text":"...","resolve_condition":"...","fail_condition":"...","ongoing_effects":{},"effect_on_resolve":{"metrics":{"皇威":3}},"effect_on_fail":{"metrics":{"皇威":-4}},"cancellable":"by_progress"}],
          "cancels": [],
          "close_issues": [{"issue_id":9,"reason":"resolved","narrative":"..."}],
          "fiscal_changes": [],
          "appointments": [],
          "character_status_changes": [{"name":"魏忠贤","status":"exiled","reason":"发配凤阳"}],
          "office_changes": [{"name":"孙传庭","new_office":"陕西总督","new_office_type":"督抚","reason":"永城知县擢用"}]
        }
        """
        _captured.append(json_str)
        return "__extraction_submitted__"

    return tools + [submit_extraction]
