"""召对转译：交办载荷与应允（C1a，#1837）。

每轮回话落定后起一次转译 LLM，读本轮（皇帝原话 + 回话 + 本场已说的话 +
本夜暂存清单），一次声明新交办及其载荷、哪条暂存已应允或被拒；代码只把声明
交给既有 :func:`ming_sim.declaration_dispatch.dispatch_declaration` 分派到
暂存与收夜成案链（ADR 0155 场中承接；ADR 0028 后出注记）。

本票只接交办（commissions）与应允/拒绝（promises）；分段 / 在场 / 边事件等
归 C1b，当场实况归 C2，后台化与封夜 join 归 T2。场景 LLM 零动作工具、零格式
约束（生成链不声明）；两通道（CLI / API）共用本入口同一形状，退役与回话并行
的意图分类器与应允判读。承接不了的交办由分派器逐项拒收当事实回场，代码不做
「所指未明 → 强制追问」闸。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ming_sim.applier import Provenance
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    dispatch_declaration,
)

TranslateFn = Callable[[str, Any], Mapping[str, object]]


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


def build_night_said_so_far(db: Any, night_id: int) -> List[str]:
    """本场已说的话：按夜持久化对话轮 + 故事账，正文从 chat_messages 取。

    chat_turns 只有 user_message_id / minister_message_id，没有 user_text 列；
    与 materials._scene_spoken_text / read_night_scroll 同口径，不另造假键。
    """
    if int(night_id or 0) <= 0 or not hasattr(db, "conn"):
        return []
    from ming_sim.audience_night import list_chat_turns_for_night, list_ledger

    lines: List[str] = []
    # 故事账（入殿等）按夜序；对话轮按 night_seq。两者分列后按既有材料口径
    # 先对话再穿插非必要——转译只要「已说」全集，顺序以对话轮为主、账文附后。
    for turn in list_chat_turns_for_night(db, int(night_id)):
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
        body = str(entry.get("body") or "")
        if body.strip():
            lines.append(body)
    return lines


def build_audience_translate_prompt(
    *,
    emperor_message: str,
    reply: str,
    night_said: Sequence[str],
    pending_summaries: Sequence[str],
) -> str:
    """转译输入：本轮皇帝原话 + 回话 + 本场已说 + 本夜暂存清单。

    产出契约只声明 commissions / promises（C1a）；其余 section 留给后续票。
    不解析自由散文——模型直接给结构化声明。
    """
    said_block = "\n".join(str(s) for s in night_said if str(s).strip()) or "（无）"
    pending_block = "；".join(str(s) for s in pending_summaries if str(s).strip()) or "（无）"
    return (
        "你是召对转译器。读本轮皇帝原话、回话、本场已说的话与本夜暂存清单，"
        "一次声明本轮全部交办与应允/拒绝。只输出一个 JSON 对象，无代码围栏、无多余字。\n"
        "形状：\n"
        "{\n"
        '  "commissions": [\n'
        "    {\n"
        '      "text": "交办正文（原样，不删改）",\n'
        '      "appointment": {"name": "人名", "office": "官职", "appoint_action": "任命|罢免"},\n'
        '      "grant": {\n'
        '        "grant_action": "赈灾|协饷|赏赉|发内帑|项目经费|…",\n'
        '        "amount": 正整数万两, "account": "国库|内库",\n'
        '        "purpose": "补饷（仅协饷）",\n'
        '        "target_kind": "region|army|character|issue|…",\n'
        '        "target_id": "目标 id", "cadence": "一次性|每月"\n'
        "      }\n"
        "    }\n"
        "  ],\n"
        '  "promises": [\n'
        '    {"action_id": 正整数, "decision": "应允|拒绝"}\n'
        "  ]\n"
        "}\n"
        "规则：\n"
        "- 一句话同时含拟旨 + 拨帑 + 任免时，只出一条 commission，载荷挂在同一条上；"
        "不要拆成拟旨 / 拨帑 / 交办三道。\n"
        "- 皇帝对已暂存交办说「准」「照办」等应允语义 → promises 里 decision=应允；"
        "「不准」「作罢」→ 拒绝。皇帝本轮未表态 → promises 为空（默认不应允）。\n"
        "- 无新交办、无应允/拒绝时输出空数组，不要编造。\n"
        "- 承接不了的交办仍写入 commissions（由代码拒收），不要改写皇帝原话去猜。\n"
        f"【本场已说的话】\n{said_block}\n"
        f"【本夜暂存清单】{pending_block}\n"
        f"【本轮皇帝】{emperor_message or '（无）'}\n"
        f"【本轮回话】{reply or '（无）'}\n"
    )


def _default_translate_runner(prompt: str, llm_config: Any) -> Mapping[str, object]:
    from ming_sim.cli_backend import _loads_lenient, _run_json_extractor_for_config

    raw, _ = _run_json_extractor_for_config(prompt, llm_config, tag="audience_translate")
    obj = _loads_lenient(raw, accepted_types=(dict,))
    if not isinstance(obj, dict):
        return {}
    return obj


def normalize_audience_declaration(raw: object) -> Dict[str, object]:
    """转译 JSON → 只保留 C1a 两个 section；其它键原样忽略（C1b/C2 另票）。"""
    if not isinstance(raw, Mapping):
        return {"commissions": [], "promises": []}
    declaration: Dict[str, object] = {}
    for key in ("commissions", "promises"):
        value = raw.get(key)
        if value is None:
            declaration[key] = []
        else:
            declaration[key] = value
    return declaration


def translate_audience_turn(
    *,
    emperor_message: str,
    reply: str,
    night_said: Sequence[str] = (),
    pending_summaries: Sequence[str] = (),
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
) -> Dict[str, object]:
    """一次转译 → commissions/promises 声明。

    调用失败抛 :class:`AudienceTranslateError`（与成功空声明可区分）；
    不挡回话、不洗成「本轮无动作」。后台待补/重试归 T2。
    """
    prompt = build_audience_translate_prompt(
        emperor_message=emperor_message,
        reply=reply,
        night_said=night_said,
        pending_summaries=pending_summaries,
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
    minister_name: str = "",
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把转译声明交给 C0 统一分派器；召对与过月同入口。"""
    return dispatch_declaration(
        db,
        state,
        declaration,
        minister_name=minister_name,
        night_id=int(night_id or 0),
        source=source,
    )


def run_audience_turn_translation(
    db: Any,
    state: Any,
    *,
    emperor_message: str,
    reply: str,
    night_id: int,
    minister_name: str = "",
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """组装本轮上下文 → 转译 → 分派。scene_chat 与其它通道共用。

    转译调用失败抛 :class:`AudienceTranslateError`，不进入
    :func:`dispatch_declaration`（失败≠成功空声明）。
    """
    night_said = build_night_said_so_far(db, int(night_id or 0))
    pending = build_pending_summaries(db, int(state.turn), night_id=int(night_id or 0))
    declaration = translate_audience_turn(
        emperor_message=emperor_message,
        reply=reply,
        night_said=night_said,
        pending_summaries=pending,
        llm_config=llm_config,
        translate_fn=translate_fn,
    )
    return apply_audience_turn_translation(
        db,
        state,
        declaration,
        night_id=int(night_id or 0),
        minister_name=minister_name,
        source=source,
    )
