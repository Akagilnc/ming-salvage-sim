"""大臣 Agent 工具集：court 动作工具（拟旨/密令/退下/换人）。读取走材料目录。"""

from __future__ import annotations

import json
from typing import Dict, Optional

from ming_sim.constants import DOSSIER_LINK_TYPES
from ming_sim.models import FRONT_HALF_DONE_PHASES, Character, CourtContext
from ming_sim.issues import TravelTone, normalize_travel_tone
from ming_sim.strict_types import strict_int


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


def build_minister_tools(character: Character, context: CourtContext):
    def propose_directive(
        decree_text: str,
        punish_action: str = "",
        target_id: str = "",
        name: str = "",
        amount: int = 0,
        transaction_category: str = "",
        backing_dossier_id: Optional[int] = None,
        issue_id: Optional[int] = None,
        issue_disposition: str = "",
        mode: Optional[str] = None,
    ) -> str:
        """把已定处置方案拟成一道圣旨草稿呈给皇帝审阅。

        decree_text 为完整圣旨正文。若本件为惩处，须同时填 ACTION_CLUSTERS 同名
        结构化字段：punish_action、单一目标（target_id 或 name）、罚俸时正数 amount，
        以及来自 ACTION_CLUSTERS 的 transaction_category；若处置站台者，填
        backing_dossier_id 指向原廷议案卷；若处置弹劾潮，填 issue_id 与
        issue_disposition，并在办人时从该事项标靶中明确选择单一 target_id。
        仅在正文讨论廷杖/流放/昭雪等制度、未填结构化字段时，不得当作已决惩处。
        mode 是 LLM 对皇帝本意的新 typed 判定：确为中旨时填 midzhi，
        确为普通旨时填 ordinary；没有新判断时不填。
        """
        text = (decree_text or "").strip()
        if not text:
            return "拟旨失败：圣旨正文为空。"
        # punish_action/target_id|name/amount/backing_dossier_id：tool schema 显式字段，
        # 真源在 tool arguments，由 session/web 组装进候选 seam；标记串只带正文。
        # 返回草稿标记，由 minister_chat / GameSession.chat 截获展示给皇帝确认，不在此入库。
        return f"__pending_directive__{text}"

    def propose_appointment(
        name: str, office: str, faction: str = "中立", reason: str = "",
        replaces: str = "", mode: Optional[str] = None,
    ) -> str:
        """吏部铨选拟任。

        mode 是 LLM 对皇帝本意的新 typed 判定：确为中旨时填 midzhi，
        确为普通旨时填 ordinary；没有新判断时不填（#1731 None=沉默）。
        """
        nm = (name or "").strip()
        off = (office or "").strip()
        if not nm or not off:
            return "铨选失败：姓名或拟授官职为空。"
        import json as _json
        body = {
            "name": nm, "office": off,
            "faction": (faction or "中立").strip(),
            "reason": (reason or "").strip(),
            "replaces": (replaces or "").strip(),
        }
        raw_mode = str(mode or "").strip()
        if raw_mode:
            body["mode"] = "midzhi" if raw_mode == "midzhi" else "ordinary"
        payload = _json.dumps(body, ensure_ascii=False)
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
        kind: str = "",
        axes_json: str = "[]",
        direction: int = 1,
        delivery_unit: str = "",
        delivery_target_units: float = 0,
        purpose: str = "",
        category: str = "",
        account: str = "",
        target_kind: str = "",
        target_id: str = "",
        person_action: str = "",
        region: str = "",
        field: str = "",
        region_target: str = "",
        investigation_target: str = "",
        effect_sign: int = 0,
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
        issue 的 typed 合同：kind（差务名，如补发饷银/缉获人犯）、axes_json（价值轴闭集，
        六轴：礼法名节/既得利益/实务事功/皇权依附/华夷战和/民本恤民）、
        direction（1 或 -1）、effect_sign（生产者 +1 或 -1，不得从 direction 导出）。
        专题查核须填写非空 investigation_target，值为相关人员范围；同时填写正数
        delivery_target_units（须坐实的事实条数）和 effect_sign（+1 或 -1），delivery_unit 留空。
        普通交付差务须填写 canonical delivery_unit（万两/人犯/万亩）、正数 delivery_target_units
        及该单位既有 identity 字段；非调查留空 investigation_target。
        delivery_unit 决定还须填哪组 identity（缺则确认时响亮拒绝）：
        万两支出 → purpose（补饷须另填 target_kind=army 与 target_id；其余非空写成其它）、category、account；收入不填 purpose；
        人犯 → person_action（人物变更动作）；
        万亩 → region（地区 id）、field（落库字段）、region_target（落库后的目标值）。
        tags_json 只作检索关键词，不用于猜 kind。
        """
        # 恢复窗总闸（PR #90 R2 codex P2）：FRONT_HALF_DONE 时四个 action 都是
        # settle 重试事务边界外的直写，重放中止回滚不回滚它们——dispatcher 一处冻全部。
        if context.state.turn_phase in FRONT_HALF_DONE_PHASES:
            return "本月结算未完（恢复中），密令房暂不办事；请先续跑结算，再行降旨。"
        act = (action or "").strip().lower()
        if act == "issue":
            return _secret_order_issue(
                title, content, tags_json, assignee, deadline_months,
                excluded_names_json, excluded_offices_json, dossier_links_json,
                kind, axes_json, direction, delivery_unit, delivery_target_units,
                purpose, category, account, target_kind, target_id, person_action, region, field, region_target,
                investigation_target, effect_sign,
            )
        if act == "progress":
            return _secret_order_progress(order_id, progress)
        if act == "submit":
            return _secret_order_submit(order_id, claim)
        if act == "rush":
            return _secret_order_rush(order_id, deadline_months, reason)
        return f"未知 action={action!r}，可选：issue / progress / submit / rush。"

    def _secret_order_issue(
        title: str, content: str, tags_json: str = "[]", assignee: str = "", deadline_months: int = 0,
        excluded_names_json: str = "[]", excluded_offices_json: str = "[]", dossier_links_json: str = "[]",
        kind: str = "", axes_json: str = "[]", direction: int = 1, delivery_unit: str = "", delivery_target_units: float = 0,
        purpose: str = "", category: str = "", account: str = "",
        target_kind: str = "", target_id: str = "",
        person_action: str = "", region: str = "", field: str = "", region_target: str = "",
        investigation_target: str = "", effect_sign: int = 0,
    ) -> str:
        """接收已注册入口参数并构造待确认的密令 payload。"""
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
            raw_axes = json.loads(axes_json or "[]")
            if not isinstance(raw_axes, list):
                raw_axes = []
        except (ValueError, TypeError):
            raw_axes = []
        axes_clean = [str(k).strip() for k in raw_axes if str(k).strip()]
        try:
            dir_i = int(direction)
        except (TypeError, ValueError):
            dir_i = 1
        if dir_i not in (1, -1):
            dir_i = 1
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
                link_dossier_id = strict_int(raw_target_id)
            except (TypeError, ValueError, OverflowError):
                continue
            relation = str(link.get("relation_type") or "").strip()
            note = str(link.get("note") or "").strip()
            if link_dossier_id in visible_ids and relation in DOSSIER_LINK_TYPES and note:
                dossier_links.append({"target_dossier_id": link_dossier_id, "relation_type": relation, "note": note})
        try:
            deadline = max(0, min(int(deadline_months or 0), 36))
        except (TypeError, ValueError):
            deadline = 0
        from ming_sim.covert_progress import CovertContractError, build_covert_task_contract
        try:
            frozen = build_covert_task_contract(
                kind=kind,
                axes=axes_clean,
                direction=dir_i,
                delivery_unit=delivery_unit,
                delivery_target_units=delivery_target_units,
                purpose=purpose,
                category=category,
                account=account,
                target_kind=target_kind,
                target_id=target_id,
                person_action=person_action,
                region=region,
                field=field,
                region_target=region_target,
                investigation_target=investigation_target,
                effect_sign=effect_sign,
            )
        except CovertContractError as exc:
            return f"密令下达失败：{exc}"
        return f"__secret_order__{json.dumps({'title': t, 'content': c, 'tags': tags_clean, 'assignee': real_assignee, 'deadline_months': deadline, 'excluded_names': excluded, 'excluded_offices': excluded_offices, 'dossier_links': dossier_links, 'covert_task': frozen}, ensure_ascii=False)}"

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
            return f"密令 #{order['id']} 当前状态 {order['status']}，不可提交办结对账。"
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

    def rush_staged_commitment(
        issue_id: int,
        stage_idx: int = 0,
        deadline_months: int = 1,
        reason: str = "",
    ) -> str:
        """催办分段承诺（#624 / ADR 0078）。经确认闸门缩短 issues.stages_json[].due_turn。

        issue_id：承诺 issue 编号（须为 active 且含分段）。
        stage_idx：段序号（默认 0=首段）。
        deadline_months：1=下月核、3=三月内、0=本月即核。
        reason：催办缘由（简短）。
        """
        if context.state.turn_phase in FRONT_HALF_DONE_PHASES:
            return "本月结算未完（恢复中），暂不能催办承诺；请先续跑结算。"
        try:
            iid = int(issue_id)
        except (TypeError, ValueError):
            return "催办失败：issue_id 无效。"
        if iid <= 0:
            return "催办失败：issue_id 无效。"
        row = context.db.conn.execute(
            "SELECT id, status, stages_json FROM issues WHERE id=?",
            (iid,),
        ).fetchone()
        if row is None:
            return f"催办失败：查无承诺 issue#{iid}。"
        if str(row["status"] or "") != "active":
            return f"催办失败：承诺 issue#{iid} 状态 {row['status']}，不能催办。"
        from ming_sim.staged_commitment import normalize_commitment_stages
        stages = normalize_commitment_stages(row["stages_json"])
        if not stages:
            return f"催办失败：承诺 issue#{iid} 无分段，不能催办。"
        try:
            sidx = int(stage_idx if stage_idx is not None else 0)
        except (TypeError, ValueError):
            sidx = 0
        if not any(int(s["stage_idx"]) == sidx for s in stages):
            return f"催办失败：承诺 issue#{iid} 无 stage_idx={sidx}。"
        try:
            raw_deadline = 1 if deadline_months is None or deadline_months == "" else deadline_months
            deadline = max(0, min(int(raw_deadline), 36))
        except (TypeError, ValueError):
            deadline = 1
        payload = {
            "issue_id": iid,
            "stage_idx": sidx,
            "deadline_months": deadline,
            "reason": (reason or "").strip()[:120],
        }
        return "__commitment_rush__" + json.dumps(payload, ensure_ascii=False)

    def dismiss_minister() -> str:
        """结束本次召见，退朝。"""
        return "__dismiss__"

    def summon_minister(name: str, 行程语气: TravelTone = "常行") -> str:
        """传召另一位大臣入殿。行程语气取常行、加急或星夜兼程。"""
        normalize_travel_tone(行程语气)
        return f"__summon__{name}"

    # #635 荐人准入唯一所有者（庭裁 Y1/Y3）：reason 为工具契约必填参数，
    # 缺失/全空白在受理点响亮拒绝、绝不形成 __pending_recommendation__；
    # strip 仅作判空谓词，荐词原句逐字透传不裁剪（Y2）。
    def recommend_person(name: str, target_office: str, reason: str) -> str:
        """具名荐人并交给皇帝确认；只可荐本人的网络/见闻切片中已有的人。

        reason 是荐词原句（非空必填），逐字落库不作任何删改。"""
        target = str(name or "").strip()
        office = str(target_office or "").strip()
        row = next((item for item in context.db.list_recommendation_candidates(
            context.state, character.name) if item["name"] == target), None)
        if row is None:
            return "荐人失败：此人不在本大臣的派系/见闻可及切片内。"
        if not office:
            return "荐人失败：须说明拟授的目标差事。"
        recommendation_reason = "" if reason is None else str(reason)
        if not recommendation_reason.strip():
            return "荐人失败：须附非空荐词缘由（reason），缺失或全空白不予受理。"
        payload = json.dumps({
            "name": target, "office": office, "reason": recommendation_reason,
            "faction": row["faction"], "replaces": "",
            "recommendation": {
                "candidate_kind": row["candidate_kind"],
                "basis": row["basis"], "recommender": character.name,
                "candidate": row,
            },
        }, ensure_ascii=False)
        return f"__pending_recommendation__{payload}"

    action_tools = [
        propose_directive,
        secret_order,
        rush_staged_commitment,
        dismiss_minister,
        summon_minister,
        recommend_person,
        register_unlisted_person,
    ]
    if character.office_type == "吏部":
        action_tools.append(propose_appointment)
    unique_tools = []
    seen_tool_names: set = set()
    for tool in action_tools:
        name = getattr(tool, "__name__", str(tool))
        if name in seen_tool_names:
            continue
        seen_tool_names.add(name)
        unique_tools.append(tool)
    return unique_tools
