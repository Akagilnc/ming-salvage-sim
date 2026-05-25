"""大臣 Agent 工具集：查询工具 + court tools（拟旨/退下/换人）。L5。"""

from __future__ import annotations

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
        """查在朝（及被罢/下狱/流放/致仕）官员名册：姓名、现职、派系、状态。
        被问及某官现任何职、是否在朝时，必须先查此工具，不得凭记忆臆断。"""
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

    def inspect_minister(name: str) -> str:
        """查某位官员的现任官职、派系与当前状态（在朝/罢黜/下狱/流放/致仕/已故）。
        被问及某人职位、近况、是否当差时，必须调此工具核实，禁止凭训练记忆编造史实职位。"""
        target = None
        key = (name or "").strip()
        for c in _content_ctx().characters.values():
            if c.name == key or key in (c.aliases or []):
                target = c
                break
        if target is None:
            return f"名册中无『{name}』。可先调 list_court 看在朝官员名单。"
        status, reason = context.db.get_character_status(target.name)
        if status == "offstage":
            return f"『{target.name}』尚未起用入朝。"
        tag = _STATUS_CN.get(status, status)
        out = f"{target.name}：现职{target.office}，职位类型{target.office_type}，派系{target.faction}，状态{tag}。"
        if reason:
            out += f"（{reason}）"
        if target.summary:
            out += f"简介：{target.summary}"
        return out

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
        """当皇帝态度强硬、已经定夺并命你拟旨/草诏/下旨/写旨时，调用此工具，
        把已定处置方案拟成一道圣旨草稿呈给皇帝审阅。皇帝确认后才正式入档。

        重要：普通文本回复不会入草案。皇帝只是询问、试探或方案未定时，不要调用；可先奏明利害。
        若皇帝已强命拟旨，必须调用此工具，不能只在回复中写圣旨正文。

        参数：
        - decree_text：完整圣旨正文，明确执行者、关键动作、期限、回奏要求。不带 Markdown。

        皇帝若仅在咨询、未示采纳，不要调此 tool。"""
        text = (decree_text or "").strip()
        if not text:
            return "拟旨失败：圣旨正文为空。"
        # 返回草稿标记，由 minister_chat / GameSession.chat 截获展示给皇帝确认，不在此入库。
        return f"__pending_directive__{text}"

    def propose_appointment(name: str, office: str, faction: str = "中立", reason: str = "", replaces: str = "") -> str:
        """【吏部专属】皇帝点名起用某位尚未在朝臣名单上的官员（如把当时还是底层小官的史可法
        擢为浙江巡抚），由吏部尚书铨选拟任。**只要任命说得通**（资历、官职合理）即可调此 tool
        把人补入名册——史有其人按其史实资历判，杜撰名按诏书自陈/常识推定的资历判，无须强求
        史有其人。当前游戏年月按回合推进（本游戏从 1627.10 崇祯即位开局，已到崇祯七年就按 1634 算）。

        判断规则——你（吏部尚书）凭常识自行裁断：
        - 资历悬殊得离谱（白身直拜内阁首辅、童生直授尚书）→ 不要调，劝谏皇帝。
        - 官职非明制（「军师」「军长」之类）→ 不要调，提醒皇帝改正。
        - 资历相称、官职合法 → 调此 tool。是否史有其人不作硬性要求。

        **职位替换**：明制一缺一人。若拟授官职是个独缺实职（如某省巡抚、某镇总兵、某部尚书），
        且现朝堂上已有人正任此职，须把现任者姓名填进 replaces，由代码端把原任者罢黜（dismissed）
        腾缺。你凭朝臣名册判断谁正占此缺——拿不准（如泛称「内阁大学士」可并存多员、或现无人任此职）
        就留空，不要乱填。replaces 填的人必须是当前在朝（active）的大臣姓名。

        参数：
        - name：拟任者姓名。
        - office：拟授官职（如「浙江巡抚」「登莱巡抚」）。
        - faction：派系，取值须是现有派系之一（东林/阉党/皇党/军队/宗室/中立/西学），拿不准填「中立」。
        - reason：铨选理由一句话，写明此人资历与任命依据。
        - replaces：被此任命腾缺的现任官员姓名；无人占缺或不确定则留空。
        """
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
        """皇帝示意退下（如"退下""好，去办吧""朕知道了"等），调此 tool 结束本次召见。"""
        return "__dismiss__"

    def summon_minister(name: str) -> str:
        """皇帝要召见另一位大臣（如"传袁崇焕来""叫毕自严进来"），调此 tool 换人。name 填大臣姓名。"""
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
        inspect_minister,
        estimate_resistance,
        read_past_report,
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


def build_simulator_tools(context: CourtContext):
    """月末推演日讲官的只读查询工具。

    与大臣 tool 的差异：纯只读、无 court tool（拟旨/退下/换人）、无 skill 闸。
    推演官借这些 tool 按需查实时盘面，让月末邸报有据，不靠 payload 静态快照瞎编。
    """
    def view_state() -> str:
        """查看当前大明核心国势数值（含派系/阶级/外部势力）。"""
        return (
            state_context(context.state)
            + "。派系：" + context.db.faction_report()
            + "。" + context.db.class_report()
            + "。外部：" + context.db.external_power_report()
        )

    def list_issues() -> str:
        """查看当前在办的所有事项（issue）及进度。"""
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
        """查看某条在办事项细节。issue_id 是事项编号（由 list_issues 给出，带 # 的数字）。"""
        rows = context.db.list_active_issues()
        try:
            n = int(issue_id)
        except (ValueError, TypeError):
            return "issue_id 必须是整数。"
        row = next((r for r in rows if int(r["id"]) == n), None)
        if row is None:
            return f"未找到在办事项 #{n}。可先调 list_issues 看清单。"
        return (
            f"#{row['id']} {row['title']}（bar {int(row['bar_value'])}，"
            f"{row['bar_bad_meaning']}↔{row['bar_good_meaning']}）。"
            f"阶段：{row['stage_text']}。牵涉：{row['faction_hint'] or '—'}。"
            f"结案条件：{row['resolve_condition'] or '（未填）'}。失败条件：{row['fail_condition'] or '（未填）'}。"
        )

    def list_regions() -> str:
        f"""查看两京十三省最危险地区和账面{TURN_UNIT}税。"""
        return context.db.region_report(limit=8)

    def inspect_region(region_name: str) -> str:
        """查看某一地区人口、民心、动乱、天灾、人祸、田亩和税收。"""
        try:
            return context.db.region_detail(region_name)
        except ValueError as e:
            return f"未找到地区 '{region_name}'。可先调 list_regions 看地区列表。错误：{e}"

    def list_armies() -> str:
        """查看大明主要军队的驻扎、维护费、补给、士气和欠饷警讯。"""
        return context.db.army_report(limit=8)

    def inspect_army(army_name: str) -> str:
        """查看某支军队驻扎地、兵种、人数、维护费、补给、士气、训练和欠饷。"""
        try:
            return context.db.army_detail(army_name)
        except ValueError as e:
            return f"未找到军队 '{army_name}'。可先调 list_armies 看军队列表。错误：{e}"

    def list_external_powers() -> str:
        """查看后金、蒙古、朝鲜、流寇等外部势力状态。"""
        return context.db.external_power_report()

    def check_treasury() -> str:
        """查国库、内库、收支和欠账明细。"""
        return context.db.treasury_report(context.state)

    return [
        view_state,
        list_issues,
        inspect_issue,
        list_regions,
        inspect_region,
        list_armies,
        inspect_army,
        list_external_powers,
        check_treasury,
    ]
