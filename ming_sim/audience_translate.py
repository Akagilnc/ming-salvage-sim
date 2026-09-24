"""召对转译：每轮一次完整声明（C1a/C1b/C2；后台化归 T2 #1842）。

每轮回话落定后起一次转译 LLM，读本轮（皇帝原话 + 回话 + 本场已说的话 +
本夜暂存清单），一次声明本轮全部记录——交办载荷与应允、当场实况（生死 /
下狱 / 革职）、文字事实、公开说法、在场进出、说话人分段、边事件、御前主角、
入册；代码只把声明交给 :func:`ming_sim.audience_translation.apply_audience_round_translation`
（经 C0 分派器）落账（ADR 0155 场中承接）。

生产上转译是后台任务（#1842）：按轮串行、前台不等；封夜提交 join 最后一轮；
耗尽 = 该轮待补，不挡下一句。场景 LLM 零动作工具、零格式约束；两通道同形。
承接不了的交办由分派器逐项拒收当事实回场，代码不做「所指未明 → 强制追问」闸。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ming_sim.applier import Provenance
from ming_sim.declaration_dispatch import DeclarationDispatchResult
from ming_sim.decree_vocabulary import TARGET_KINDS

TranslateFn = Callable[[str, Any], Mapping[str, object]]

# C0 全 section + 主角；normalize 补齐这些键，未知顶层键原样保留给分派器。
_DECLARATION_KEYS: tuple[str, ...] = (
    "commissions",
    "promises",
    "textual_facts",
    "public_sayings",
    "on_scene_facts",
    "presence",
    "scene_facts",
    "edge_events",
    "protagonist",
    "registrations",
    "effects",
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
    if not hasattr(db, "conn"):
        return []
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
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        text = str(payload.get("text") or row["action"] or "").strip()
        brief = text[:60] if text else str(row["kind"] or "")
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
    if int(night_id or 0) <= 0 or not hasattr(db, "conn"):
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
            lines.append(f"{role_label}：{body}")
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


def build_translation_target_grounding(db: Any) -> str:
    """权威目标目录：dispatcher 可校验的 region/army/character/issue 投影。

    只读 DB 真源；查询失败按 ADR 0005 上抛，不得静默退化为空目录。
    不猜、不从正文匹配改写模型输出。
    """
    if not hasattr(db, "conn"):
        return ""
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
    if hasattr(db, "list_active_issues"):
        for row in db.list_active_issues():
            lines.append(
                f"issue\t{int(row['id'])}\t{str(row['title'] or '')}"
            )
    else:
        for row in db.conn.execute(
            "SELECT id, title FROM issues WHERE status='active' ORDER BY id"
        ).fetchall():
            lines.append(
                f"issue\t{int(row['id'])}\t{str(row['title'] or '')}"
            )
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "【权威目标目录】\n"
        "grant.target_id / appointment.region_id 必须是下列目录中的精确 id，禁止编造。\n"
        f"{body}\n"
    )


def build_c0_declaration_shape() -> str:
    """C0 唯一输出形状，召对与过月转译共用。"""
    # 效果 delta 的唯一形状真源沿用旧结算入口的 EMPTY_EXTRACTION，避免声明层
    # 另手维护一份平行字段表。
    from ming_sim.simulation import EMPTY_EXTRACTION

    # target_kind 表面唯一真源 = decree_vocabulary.TARGET_KINDS，禁手抄分叉。
    target_kind_hint = "|".join(sorted(TARGET_KINDS))
    effect_shape = "\n".join(
        f"    {line}" for line in json.dumps(
            EMPTY_EXTRACTION, ensure_ascii=False, indent=2,
        ).splitlines()
    )
    return (
        "{\n"
        '  "commissions": [\n'
        "    {\n"
        '      "text": "交办正文（原样，不删改）",\n'
        '      "appointment": {\n'
        '        "name": "人名", "office": "官职", "appoint_action": "任命|罢免",\n'
        '        "region_id": "任所 region id（地方/督抚/边镇任命必填；中央可空）"\n'
        "      },\n"
        '      "grant": {\n'
        '        "grant_action": "赈灾|协饷|赏赉|发内帑|项目经费|…",\n'
        '        "amount": 正整数万两, "account": "国库|内库",\n'
        '        "purpose": "补饷（仅协饷）",\n'
        f'        "target_kind": "{target_kind_hint}",\n'
        '        "target_id": "目标 id", "cadence": "一次性|每月"\n'
        "      }\n"
        "    }\n"
        "  ],\n"
        '  "promises": [{"action_id": 正整数, "decision": "应允|拒绝"}],\n'
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
        '  "effects": ' + effect_shape + "\n"
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
        "- 皇帝对已暂存交办说「准」「照办」等应允语义 → promises 里 decision=应允；"
        "「不准」「作罢」→ 拒绝。皇帝本轮未表态 → promises 为空（默认不应允）。\n"
        "- 当场已发生（斩杀/拿下/伤臂/告退等）走 on_scene_facts / textual_facts / "
        "presence / public_sayings / edge_events，不要写成交办。\n"
        "- effects 是过月才核算的旨意办理效果；召对夜本轮留空，不得将尚未发生的效果写成当场实况。\n"
        "- public_sayings 的 excluded_names / excluded_offices：皇帝明示排除的读者"
        "保持不知情；无排除则给空数组。\n"
        "- 无对应事实的 section 输出空数组（protagonist 无则省略或 null），不要编造。\n"
        "- 承接不了的交办仍写入 commissions（由代码拒收），不要改写皇帝原话去猜。\n"
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
        return {}
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


def apply_audience_turn_translation(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    night_id: int,
    chat_turn_id: int = 0,
    minister_name: str = "",
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把转译声明交给场中承接落账核（C0 分派 + 源轮/水位）。

    ``chat_turn_id`` 是当场实况源轮；落账核经统一分派器自记撤回前像。
    """
    from ming_sim.audience_translation import apply_audience_round_translation

    return apply_audience_round_translation(
        db,
        state,
        declaration,
        night_id=int(night_id or 0),
        chat_turn_id=int(chat_turn_id or 0),
        minister_name=minister_name,
        source=source,
    )


def run_audience_turn_translation(
    db: Any,
    state: Any,
    *,
    emperor_message: str,
    reply: str,
    night_id: int,
    chat_turn_id: int = 0,
    minister_name: str = "",
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """组装本轮上下文 → 转译 → 落账。scene_chat 同步路径与后台 worker 共用。

    转译调用失败抛 :class:`AudienceTranslateError`，不进入落账核
    （失败≠成功空声明）。

    ``chat_turn_id`` 原样下传（不另造平行快照）；过月/无源轮传 0。
    """
    ctid = int(chat_turn_id or 0)
    night_said = build_night_said_so_far(
        db, int(night_id or 0), until_chat_turn_id=ctid,
    )
    pending = build_pending_summaries(db, int(state.turn), night_id=int(night_id or 0))
    target_grounding = build_translation_target_grounding(db)
    declaration = translate_audience_turn(
        emperor_message=emperor_message,
        reply=reply,
        night_said=night_said,
        pending_summaries=pending,
        target_grounding=target_grounding,
        llm_config=llm_config,
        translate_fn=translate_fn,
    )
    return apply_audience_turn_translation(
        db,
        state,
        declaration,
        night_id=int(night_id or 0),
        chat_turn_id=ctid,
        minister_name=minister_name,
        source=source,
    )
