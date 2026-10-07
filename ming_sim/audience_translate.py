"""召对转译：每轮一次完整声明（C1a/C1b/C2；后台化归 T2 #1842）。

每轮回话落定后起一次转译 LLM，读本轮（皇帝原话 + 回话 + 本场已说的话 +
本夜暂存清单），一次声明本轮全部记录——交办载荷与应允、对暂存交办的背书
（会签/当面站台/御笔手敕）、当场实况（生死 / 下狱 / 革职）、文字事实、
公开说法、在场进出、说话人分段、边事件、御前主角、入册；代码只把声明交给
:func:`ming_sim.audience_translation.apply_audience_round_translation`
（经 C0 分派器）落账（ADR 0155 场中承接）。

生产上转译是后台任务（#1842）：按轮串行、前台不等；收夜先补跑再提交成案；
耗尽 = 该轮待补，不挡下一句与退朝，过月前 join 补齐。场景 LLM 零动作工具、
零格式约束。承接不了的交办由分派器逐项拒收当事实回场，代码不做
「所指未明 → 强制追问」闸。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.applier import Provenance

TranslateFn = Callable[[str, Any], Mapping[str, object]]

# C0 全 section + 主角；normalize 补齐这些键，未知顶层键原样保留给分派器。
_DECLARATION_KEYS: tuple[str, ...] = (
    "commissions",
    "promises",
    "endorsements",
    "textual_facts",
    "public_sayings",
    "on_scene_facts",
    "presence",
    "scene_facts",
    "edge_events",
    "protagonist",
    "registrations",
    "effects",
    # #1837 reopen：旧 agent 工具退役后的转译承接节。
    "inquiries",
    "rushes",
    "travel_tones",
)
_ARRAY_SECTIONS = frozenset(
    k for k in _DECLARATION_KEYS if k not in {"protagonist", "effects"}
)


class AudienceTranslateError(RuntimeError):
    """转译 LLM 调用失败（与成功空声明可区分；不得洗成无动作）。"""


def build_pending_summaries(db: Any, turn: int, *, night_id: int = 0) -> List[str]:
    """本夜（或本回合）暂存清单摘要，供转译读。

    直接读表：``list_pending_actions`` 投影不含 night_id / night_approved，
    转译必须看见本夜归属与应允态，不能靠那条呈现投影。
    """
    params: list[Any] = [int(turn)]
    sql = (
        "SELECT id, kind, action, payload_json, night_id, night_approved "
        "FROM pending_actions WHERE turn=? AND status='pending'"
    )
    if int(night_id or 0) > 0:
        sql += " AND night_id=?"
        params.append(int(night_id))
    sql += " ORDER BY id"
    rows = db.conn.execute(sql, tuple(params)).fetchall()
    out: List[str] = []
    for row in rows:
        from ming_sim.db import GameDB

        payload = GameDB.parse_engine_payload_json(
            row["payload_json"], surface="pending_actions.payload_json",
        )
        # Free prose pending text → translation supply: preserve full bytes (#1834 F16).
        text = str(payload.get("text") or row["action"] or "")
        brief = text if text.strip() else str(row["kind"] or "")
        approved = "已应允" if int(row["night_approved"] or 0) else "待应允"
        out.append(
            f"#{int(row['id'])} [{row['kind']}/{row['action']}] {approved} {brief}"
        )
    return out


def build_night_said_so_far(
    db: Any, night_id: int, *, until_chat_turn_id: int = 0,
) -> List[str]:
    """本场已说的话：按夜持久化对话轮 + 故事账，正文从 chat_messages 取。

    chat_turns 只有 user_message_id / minister_message_id，没有 user_text 列；
    与 materials._scene_spoken_text / read_night_scroll 同口径，不另造假键。

    ``until_chat_turn_id``（ADR 0155）：按源轮 night_seq/id 截止——只含严格早于
    该轮的已说；本轮正文只走【本轮皇帝】【本轮回话】，不在此重复；亦不读后续
    已持久化轮（下一句不等转译时可能已落库）。
    """
    if int(night_id or 0) <= 0:
        return []
    from ming_sim.audience_night import list_chat_turns_for_night, list_ledger

    cutoff_id = int(until_chat_turn_id or 0)
    cutoff_seq: Optional[int] = None
    if cutoff_id > 0:
        crow = db.conn.execute(
            "SELECT night_seq FROM chat_turns WHERE id=?", (cutoff_id,),
        ).fetchone()
        if crow is not None:
            cutoff_seq = int(crow["night_seq"] or 0)

    def _before_cutoff(seq: int, turn_id: int) -> bool:
        if cutoff_id <= 0 or cutoff_seq is None:
            return True
        if int(seq) < int(cutoff_seq):
            return True
        if int(seq) > int(cutoff_seq):
            return False
        return int(turn_id) < int(cutoff_id)

    lines: List[str] = []
    # 故事账（入殿等）按夜序；对话轮按 night_seq。两者分列后按既有材料口径
    # 先对话再穿插非必要——转译只要「已说」截止集，顺序以对话轮为主、账文附后。
    prior_turn_ids: set[int] = set()
    for turn in list_chat_turns_for_night(db, int(night_id)):
        tid = int(turn.get("id") or 0)
        tseq = int(turn.get("night_seq") or 0)
        if not _before_cutoff(tseq, tid):
            continue
        if tid > 0:
            prior_turn_ids.add(tid)
        minister = str(turn.get("minister_name") or "").strip() or "殿上"
        for mid, role_label in (
            (turn.get("user_message_id"), "皇帝"),
            (turn.get("minister_message_id"), minister),
        ):
            if not mid:
                continue
            row = db.conn.execute(
                "SELECT content FROM chat_messages WHERE id=?", (int(mid),),
            ).fetchone()
            if row is None:
                continue
            body = str(row["content"] or "")
            if not body.strip():
                continue
            lines.append(f"[chat_turn_id={tid}] {role_label}：{body}")
    for entry in list_ledger(db, int(night_id)):
        src = int(entry.get("source_chat_turn_id") or 0)
        origin = int(entry.get("origin_chat_turn_id") or 0)
        if cutoff_id > 0 and cutoff_seq is not None:
            # 本轮/后续轮声明账不入；框架账（双 0）按 seq 截止到本轮之前。
            if src == cutoff_id or origin == cutoff_id:
                continue
            if src > 0 and src not in prior_turn_ids:
                continue
            if src <= 0 and origin > 0 and origin not in prior_turn_ids:
                continue
            if src <= 0 and origin <= 0:
                entry_seq = entry.get("order_key")
                if entry_seq is None:
                    entry_seq = entry.get("seq") or 0
                if float(entry_seq) >= float(cutoff_seq):
                    continue
        body = str(entry.get("body") or "")
        if body.strip():
            lines.append(body)
    return lines


def _person_candidate_grounding(db: Any, state: Any) -> str:
    """把人物候选的权威身份和 event_pool 声明契约交给既有转译调用。"""
    if state is None:
        return ""
    from ming_sim.materials import _world_candidate_events

    roster = [
        {
            "id": item["id"],
            "title": item["title"],
            "terminal_reason_labels": list(item.get("terminal_reason_labels") or []),
        }
        for item in _world_candidate_events(db, state)
    ]
    if not roster:
        return ""
    return (
        "【合资格人物事件候选】\n"
        "身份只认下列 id。段文写明其中一件由人物选择发生时，effects 声明 "
        "new_issues，origin_kind 为 event_pool，id 为该候选 id。"
        "该候选列出封闭结局标签时，同一信封顶层 event_id 写该 id，"
        "事件结局只用其中一枚标签。未发生的候选不声明。\n"
        + json.dumps(roster, ensure_ascii=False)
    )


def build_translation_target_grounding(db: Any, state: Any = None) -> str:
    """权威目标目录：dispatcher 可校验的目标与当前场面投影。

    只读 DB 真源；查询失败按 ADR 0005 上抛，不得静默退化为空目录。
    不猜、不从正文匹配改写模型输出。
    """
    lines: List[str] = []
    for row in db.conn.execute(
        "SELECT id, name FROM regions ORDER BY id"
    ).fetchall():
        lines.append(f"region\t{row['id']}\t{row['name']}")
    for row in db.conn.execute(
        "SELECT id, name FROM armies ORDER BY id"
    ).fetchall():
        lines.append(f"army\t{row['id']}\t{row['name']}")
    for row in db.conn.execute(
        "SELECT name, office FROM characters WHERE status='active' "
        "ORDER BY name"
    ).fetchall():
        lines.append(
            f"character\t{row['name']}\t{str(row['office'] or row['name'])}"
        )
    from ming_sim.staged_commitment import normalize_commitment_stages
    for row in db.conn.execute(
        "SELECT id, title, stages_json FROM issues WHERE status='active' ORDER BY id"
    ).fetchall():
        stages = normalize_commitment_stages(row['stages_json'])
        lines.append(f"issue\t{int(row['id'])}\t{str(row['title'] or '')}")
        for stage in stages:
            lines.append(f"stage\t{int(row['id'])}\t{stage['stage_idx']}\t{stage}")
    for row in db.conn.execute(
        "SELECT id, title FROM secret_orders WHERE status='active' ORDER BY id"
    ).fetchall():
        lines.append(f"secret_order\t{int(row['id'])}\t{str(row['title'] or '')}")
    # 在途拨帑与自带押解标记（普通押解随拨银旨）；专用护送目录/实况行已退役。
    for row in db.conn.execute(
        "SELECT id, action_type, target_kind, target_id FROM decree_dossiers "
        "WHERE status='executing' AND action_type='grant_allocation' ORDER BY id"
    ).fetchall():
        declared = db.dossier_declares_escort(int(row["id"]))
        lines.append(
            f"dossier\t{int(row['id'])}\t{str(row['target_kind'] or '')}:{str(row['target_id'] or '')}"
            + ("\t自带押解" if declared else "")
        )
    if state is not None:
        from ming_sim.due_review import list_due_review_scenes
        for scene in list_due_review_scenes(db, state):
            if scene.get("kind") == "covert_levy_exposure" and not scene.get("decision"):
                lines.append("scene\t" + json.dumps(scene, ensure_ascii=False, sort_keys=True))
    candidate_block = _person_candidate_grounding(db, state)
    if not lines and not candidate_block:
        return ""
    parts: List[str] = []
    if lines:
        body = "\n".join(lines)
        parts.append(
            "【权威目标目录】\n"
            "grant.target_id / appointment.region_id / rushes.target_id / 禁摊派案卷 id 必须取对应目录中的精确 id，禁止编造。\n"
            f"{body}"
        )
    if candidate_block:
        parts.append(candidate_block)
    return "\n".join(parts) + "\n"


def build_c0_declaration_shape() -> str:
    """C0 唯一输出形状，召对与过月转译共用。"""
    # 效果 delta 的形状真源是 simulation.EMPTY_EXTRACTION；声明层不另维护字段表。
    from ming_sim.simulation import EMPTY_EXTRACTION

    # target_kind 表面唯一真源 = decree_vocabulary.TARGET_KINDS，禁手抄分叉。
    target_kind_hint = "|".join(sorted(TARGET_KINDS))
    effect_shape = "\n".join(
        f"    {line}" for line in json.dumps(
            {"event_id": "仅属某事件战果时填事件 id；未填即独立", **EMPTY_EXTRACTION},
            ensure_ascii=False, indent=2,
        ).splitlines()
    )
    return (
        "{\n"
        '  "commissions": [\n'
        "    {\n"
        '      "text": "交办正文（原样，不删改）", "mode": "ordinary|midzhi（中旨明示才填 midzhi）",\n'
        '      "target_dossier_id": "御笔强推已有案卷 id（不与 grant/appointment 同填）",\n'
        '      "appointment": {\n'
        '        "name": "人名", "office": "官职", "appoint_action": "任命|罢免",\n'
        '        "region_id": "任所 region id（地方/督抚/边镇任命必填；中央可空）"\n'
        "      },\n"
        '      "grant": {\n'
        '        "grant_action": "赈灾|协饷|赏赉|发内帑|项目经费|…",\n'
        '        "amount": 正整数万两, "account": "国库|内库",\n'
        '        "purpose": "补饷（仅协饷）",\n'
        f'        "target_kind": "{target_kind_hint}",\n'
        '        "target_id": "目标 id", "cadence": "一次性|每月",\n'
        '        "escort": {"escortees": [{"character_id": "押解人名", '
        '"tier": "主办|协办|知情", "role": "职分文字", '
        '"delegator_id": "委派人名或空"}], "note": "押解护送缘由原句"}\n'
        "      },\n"
        '      "punishment": {"target_id": "处置人名（压下时可空）", '
        '"punish_action": "惩处动作（压下时为无）", "issue_id": "弹劾事项 id（有则填）", '
        '"issue_disposition": "办人|压下（弹劾事项有则填）", '
        '"transaction_category": "事务类别（有则填）", "amount": "罚俸金额（罚俸时填）", '
        '"backing_dossier_id": "所援案卷 id（有则填）"},\n'
        '      "pacification": {"target_id": "自新内乱首领的具名 id", "mode": "ordinary|midzhi"},\n'
        '      "revoke": {"target_kind": "dossier|issue（不填按 dossier）", '
        '"target_id": "所撤那道已发旨的案卷 id 或 issue id", '
        '"target_candidate": "续办所指候选 id（撤令一般留空）"},\n'
        '      "secret_order": {"title": "密令标题", "content": "密令正文", '
        '"assignee": "承办人 id", "tags": [], "deadline_months": 0, '
        '"covert_task": {}},\n'
        '      "secret_order_progress": {"order_id": "往期有效密令 id", "note": "本轮具名进展"},\n'
        '      "strategy_selection": {"target_id": "已选方案的政策目标 id", '
        '"source_chat_turn_id": "本场已说的大臣陈策轮 chat_turn_id（不能填本轮）"},\n'
        '      "secret_order_update": {"order_id": "承办人现役密令 id", '
        '"title": "新标题（有则填）", "content": "完整新正文（必填）", '
        '"deadline_months": "期限月数（有则填）"},\n'
        '      "assignment": {"title": "独立事项名", "target_id": "事项 id", '        '"assignee": "承办人 id", "participant_roster": [], '
        '"target_candidate": "续办所指候选 id（新案留空）", '
        '"commitment_kind": "承诺类别（无承诺填无）", '
        '"deadline_months": 0, "stop_condition": {}},\n'
        '      "recommendation": {\n'
        '        "recommender": "荐者人名", "reason": "荐词原句（非空，逐字）"\n'
        "      },\n"
        '      "dossier_action_type": "prohibit_covert_levy（禁摊派时填）",\n'
        '      "target_id": "本场暗渠案卷事实中的 dossier_id（禁摊派时填）"\n'
        "    }\n"
        "  ],\n"
        '  "promises": [{"action_id": 正整数, "decision": "应允|拒绝|修改|留中", '
        '"mode": "ordinary|midzhi（有则填）", "new_content": "仅修改新建密令时填完整正文"}],\n'
        '  "endorsements": [\n'
        '    {"action_id": 正整数, "form": "会签|当面站台|御笔手敕", '
        '"endorser_id": "人名（御笔手敕为空）"}\n'
        '  ],\n'
        '  "inquiries": [{"attendant": "受命近侍", "query": "所查之事"}],\n'
        '  "rushes": [{"target_kind": "commitment|secret_order", "target_id": 正整数, '
        '"stage_idx": 0, "deadline_months": 1, "reason": "催办缘由"}],\n'
        '  "travel_tones": [{"person_name": "人名", "tone": "常行|加急|星夜兼程"}],\n'
        '  "on_scene_facts": [\n'
        "    {\n"
        '      "name": "人名",\n'
        '      "动作": "处置|罢黜|…（人物变更闭集）",\n'
        '      "status": "dead|imprisoned|active|…",\n'
        '      "reason": "当场原因原文"\n'
        "    }\n"
        "  ],\n"
        '  "textual_facts": [\n'
        '    {"subject_kind": "character|army|region", "subject_id": "id", "body": "文字事实"}\n'
        "  ],\n"
        '  "public_sayings": [\n'
        "    {\n"
        '      "body": "公开说法",\n'
        '      "involved_characters": ["人名"],\n'
        '      "excluded_names": ["明示排除、不得知情的人名"],\n'
        '      "excluded_offices": ["明示排除、不得知情的官职"]\n'
        "    }\n"
        "  ],\n"
        '  "presence": [\n'
        '    {"person_name": "人名", "effect": "enter|exit", "body": "入见/告退正文"}\n'
        "  ],\n"
        '  "scene_facts": [\n'
        "    {\n"
        '      "body": "本段戏文原样",\n'
        '      "role": "user|minister|attendant|scene",\n'
        '      "audibility": "殿上公开|御前低语",\n'
        '      "person_names": ["说话/涉及人名"],\n'
        '      "tags": []\n'
        "    }\n"
        "  ],\n"
        '  "edge_events": [\n'
        '    {"source": "人名", "target": "人名", "event_kind": "结怨|撑腰|…", "context": "缘由"}\n'
        "  ],\n"
        '  "protagonist": {"person_name": "本轮御前主角"},\n'
        '  "registrations": [\n'
        '    {"name": "新人名", "office": "官职", "office_type": "文|武|…"}\n'
        "  ],\n"
        '  "effects": [' + effect_shape + "]\n"
        "}\n"
    )


def build_audience_translate_prompt(
    *,
    emperor_message: str,
    reply: str,
    night_said: Sequence[str],
    pending_summaries: Sequence[str],
    target_grounding: str = "",
) -> str:
    """转译输入：本轮皇帝原话 + 回话 + 本场已说 + 本夜暂存清单。

    产出契约 = C0 全 section（交办/应允/当场实况/文字事实/公开说法/在场/
    分段/边事件/主角/入册）。不解析自由散文——模型直接给结构化声明。
    """
    said_block = "\n".join(str(s) for s in night_said if str(s).strip()) or "（无）"
    pending_block = "；".join(str(s) for s in pending_summaries if str(s).strip()) or "（无）"
    grounding = str(target_grounding or "").strip()
    grounding_block = f"{grounding}\n" if grounding else ""
    return (
        "你是召对转译器。读本轮皇帝原话、回话、本场已说的话与本夜暂存清单，"
        "一次声明本轮全部记录。只输出一个 JSON 对象，无代码围栏、无多余字。\n"
        f"形状：\n{build_c0_declaration_shape()}"
        "规则：\n"
        "- scene_facts 按原顺序完整分段覆盖本轮回话；各 body 直接拼接须与回话逐字相同（含空白、标点与 Markdown），不得概括、补字或漏字；role 是该段的说话人类别，大臣/近臣的 person_names 首位是说话人（user/scene 可为空）。\n"
        "- 一句话同时含拟旨 + 拨帑 + 任免时，只出一条 commission，载荷挂在同一条上；"
        "不要拆成拟旨 / 拨帑 / 交办三道。\n"
        "- 离殿后独立责成的事项逐件给 commission.assignment；title/target_id 是事项锚，"
        "assignee/participant_roster 来自已明确的承办人；续办只在能指向既有候选时填 target_candidate。"
        "不从当场问答推造独立差事。\n"
        "- 皇帝从本场大臣陈策中点选方案时，交办正文由转译明确给出，"
        "commission.strategy_selection 指向【本场已说的话】中对应陈策轮 chat_turn_id；"
        "无该源轮不得猜造。\n"
        "- 具名秘密差事的新建走 commission.secret_order；必须含 title、content、"
        "承办人与已确定的 covert_task 冻结任务契约；无契约不得编造。"
        "covert_task 的字段随差务类型而异，按该类契约给全（含交付单位与对应身份字段）。"
        "查案类另可在 covert_task 里给 investigation_fact：本道密令的来源明确指向"
        "哪一条罪证就填那一条的标识，没指明就留空——留空不是错，引擎不会替来源挑一条。\n"
        "往期密令具名进展走 commission.secret_order_progress；不凭空记进展。\n"
        "- 皇帝明确撤回一道**已发出**的旨（撤回成命）走 commission.revoke，"
        "target_id 取那道旨的案卷 id；「撤回本场刚才的话」「撤回上一轮召对」"
        "不是撤令，不填 revoke（由既有撤回机制处理）。\n"
        "- 皇帝对已暂存交办说「准」「照办」等应允语义 → promises 里 decision=应允；"
        "「不准」「作罢」→ 拒绝；修改已有新建密令 → 修改并给完整 typed new_content，"
        "不从原话截断猜正文。皇帝本轮未表态 → promises 为空（默认不应允）。\n"
        "- 本轮有人当面说出担名（会签/当面站台）或皇帝说要亲笔担某旨 → endorsements "
        "指向暂存清单里那件（action_id）；御笔手敕的 endorser_id 为空。\n"
        "- 当场已发生（斩杀/拿下/伤臂/告退等）走 on_scene_facts / textual_facts / "
        "presence / public_sayings / edge_events，不要写成交办。\n"
        "- effects 是过月才核算的旨意办理效果；召对夜本轮留空，不得将尚未发生的效果写成当场实况。\n"
        "- public_sayings 的 excluded_names / excluded_offices：皇帝明示排除的读者"
        "保持不知情；无排除则给空数组。\n"
        "- 无对应事实的 section 输出空数组（protagonist 无则省略或 null），不要编造。\n"
        "- 承接不了的交办仍写入 commissions（由代码拒收），不要改写皇帝原话去猜。\n"
        "- 暗渠揭破场面呈上后皇帝禁摊派 → commissions 一项 dossier_action_type=prohibit_covert_levy，target_id 填当前场面案卷 dossier_id。\n"
        "- 大臣具名举荐某人任某差并附荐词 → commissions 任命 + recommendation（荐者/荐词原句）。\n"
        "- 皇帝交代近侍查某事 → inquiries；催某件分段事或密令 → rushes；传召说明缓急 → travel_tones。\n"
        "- **本场新交办的拨银自带押解**（「着某人押解护送」）→ 不另立密令，"
        "在该 commissions 项的 grant.escort.escortees 按 ADR 0053 参与人条目写押解人"
        "（character_id／tier 机械档／role 职分／delegator_id 委派人，无委派留空），"
        "此人即进本案参与人名单。\n"
        f"{grounding_block}"
        f"【本场已说的话】\n{said_block}\n"
        f"【本夜暂存清单】{pending_block}\n"
        f"【本轮皇帝】{emperor_message or '（无）'}\n"
        f"【本轮回话】{reply or '（无）'}\n"
    )


def run_declaration_translate_prompt(
    prompt: str, llm_config: Any = None, *, tag: str, policy: Any = None,
) -> Mapping[str, object]:
    """共用声明转译 runner：沿现有宿主 extractor 与 JSON 解析接缝。"""
    from ming_sim.cli_backend import _loads_lenient, _run_json_extractor_for_config

    raw, _ = _run_json_extractor_for_config(prompt, llm_config, tag=tag, policy=policy)
    obj = _loads_lenient(raw, accepted_types=(dict,))
    if not isinstance(obj, dict):
        raise AudienceTranslateError("转译输出无法解析为 JSON 对象")
    return obj


def _default_translate_runner(prompt: str, llm_config: Any) -> Mapping[str, object]:
    from ming_sim.llm_transport import audience_transport_policy

    return run_declaration_translate_prompt(
        prompt, llm_config, tag="audience_translate",
        policy=audience_transport_policy(),
    )


def normalize_audience_declaration(raw: object) -> Dict[str, object]:
    """转译 JSON → C0 声明形状；未知顶层键原样保留，交既有分派器 durable 拒收。

    不得在 normalize 静默删键——未知 section 的 ``invalid_shape`` 留痕是
    ``declaration_dispatch._record_unknown_sections`` 的唯一职责（ADR 0015）。
    """
    empty: Dict[str, object] = {k: [] for k in _ARRAY_SECTIONS}
    if not isinstance(raw, Mapping):
        return empty
    declaration: Dict[str, object] = {}
    for key in _DECLARATION_KEYS:
        if key not in raw:
            if key in _ARRAY_SECTIONS:
                declaration[key] = []
            elif key == "effects":
                declaration[key] = {}
            continue
        value = raw.get(key)
        if key == "effects":
            declaration[key] = {} if value is None else value
            continue
        if key == "protagonist":
            if value is None:
                continue
            declaration[key] = value
            continue
        if value is None:
            declaration[key] = []
        else:
            declaration[key] = value
    # 未知顶层键原样过手，供分派器逐项 invalid_shape；不在此过滤。
    for key, value in raw.items():
        sk = str(key)
        if sk in _DECLARATION_KEYS:
            continue
        declaration[sk] = value
    return declaration


def translate_audience_turn(
    *,
    emperor_message: str,
    reply: str,
    night_said: Sequence[str] = (),
    pending_summaries: Sequence[str] = (),
    target_grounding: str = "",
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
) -> Dict[str, object]:
    """一次转译 → 完整声明（C0 全 section）。

    调用失败抛 :class:`AudienceTranslateError`（与成功空声明可区分）；
    不挡回话、不洗成「本轮无动作」。后台待补/重试见 schedule 入口。
    """
    prompt = build_audience_translate_prompt(
        emperor_message=emperor_message,
        reply=reply,
        night_said=night_said,
        pending_summaries=pending_summaries,
        target_grounding=target_grounding,
    )
    runner = translate_fn or _default_translate_runner
    try:
        raw = runner(prompt, llm_config)
    except AudienceTranslateError:
        raise
    except Exception as exc:
        raise AudienceTranslateError(str(exc) or exc.__class__.__name__) from exc
    return normalize_audience_declaration(raw)
