"""召对转译场中承接（C1b，#1838）。

每轮回话落定后，中间层把转译 LLM 的一份声明接到既有分派器：说话人分段与
可闻性、在场进出、本轮御前主角、边事件、公开说法（及 C0 已铺的其余 section）。
语义理解归转译；本模块只做源轮绑定、主角持久化、抽取/判官水位推进——故事抽取、
边事件判官、代码触发读心不再另起（ADR 0155 场中承接段）。

生产上转译是后台任务（T2 #1842）；本入口是「声明已到手」后的同步落账核，
可被后台 worker 或受控桩直接调用。交办载荷与应允（C1a #1837）走同一
:func:`~ming_sim.declaration_dispatch.dispatch_declaration` 分派体，不另造一份。
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import set_night_protagonist
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    dispatch_declaration,
)


def apply_audience_round_translation(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    night_id: int,
    chat_turn_id: int = 0,
    minister_name: str = "",
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把本轮转译声明落到召对夜账本与世界记录，并按源轮绑主角 / 水位。

    - ``night_id``：本轮所属召对夜（在场进出、说话人分段挂此夜）
    - ``chat_turn_id``：源对话轮；>0 时 ledger 写 ``source_chat_turn_id``、主角
      写到该轮与夜当前值，并把 ``extract_status`` / ``relation_judge_status``
      标 ``done``（转译已承接，收夜不再跑故事抽取 / 边事件判官）

    第四类落账委托公开入口 :func:`dispatch_declaration`——入口自记撤回前像，
    后台 worker 直接调用本函数时 undo 亦可逆转，不另造第二份 capture/record。
    主角 / 水位写仍由本入口在分派后执行（chat_turns 不在前像表，属 #1838 语义）。
    """
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    # 复用公开入口的前像自足机制；不直调私有执行体绕过 capture/record。
    result = dispatch_declaration(
        db, state, declaration,
        minister_name=minister_name,
        night_id=nid,
        chat_turn_id=ctid,
        source=source,
    )
    # 主角持久化 + 抽取/判官水位：chat_turns 不在前像表，undo 走重投影。
    with atomic(db):
        _bind_round_after_dispatch(db, nid, ctid, result)
    return result


def _bind_round_after_dispatch(
    db: Any,
    night_id: int,
    chat_turn_id: int,
    result: DeclarationDispatchResult,
) -> None:
    """主角持久化 + 本轮抽取/判官水位。须在调用方 atomic 内。"""
    validated = result.protagonist.validated
    name = ""
    if isinstance(validated, Mapping):
        name = str(validated.get("person_name") or "").strip()
    if name and night_id > 0:
        set_night_protagonist(db, night_id, name, reason="translation", commit=False)
    if chat_turn_id <= 0:
        return
    if name:
        db.conn.execute(
            "UPDATE chat_turns SET protagonist_name=? WHERE id=?",
            (name, int(chat_turn_id)),
        )
    # 转译已声明本轮记录 → 故事抽取与边事件判官退役于本轮（水位 done，收夜 drain 跳过）
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done', relation_judge_status='done' "
        "WHERE id=? AND status NOT IN ('failed','undone')",
        (int(chat_turn_id),),
    )
