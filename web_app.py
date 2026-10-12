#!/usr/bin/env python3
"""FastAPI web entry for Ming Salvage Sim.

薄壳：路由调 ming_sim.session.GameSession（现役 Web 会话流转层）。
拟旨候选：召对转译交办 → pending_actions → 收夜成案 → 过月颁布关。
"""

from __future__ import annotations
from ming_sim.entities.issue.store import IssueStore
from ming_sim.session import AudienceChatTurn

import asyncio
import contextlib
import json
import logging
import os
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional

# 源码模式 `uvicorn web_app:app` 在 nohup/重定向（>> web_server.log）下 Python stdout 块缓冲，
# 日志滞后数分钟、结算中段 tail 看不见进度（#84）。强制行缓冲让 tlog + 各 print 近实时落盘；
# TTY 下本就行缓冲、无变化。frozen 打包路径已由 launcher.py 处理，此处覆盖源码 uvicorn 路径。
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(line_buffering=True)

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ming_sim.db import _load_durable_str_list
from ming_sim.applier import atomic, parse_engine_payload_json
from ming_sim.paths import (
    UnsafeSaveNameError,
    user_data_path,
    user_data_dir,
)
from ming_sim.save_slots import (
    SaveSlotCleanupError,
    copy_sqlite_file,
    delete_sqlite_db_files_or_raise,
)
from ming_sim.exceptions import DependencyMismatch, LLMUnavailable, SettlementAbort
from ming_sim.constants import GATE_METRIC_KEYS
from ming_sim.llm_config import (
    CLI_DEFAULT_TIMEOUT_SECONDS,
    VALID_CHANNELS,
    is_real_api_key,
    api_supports_reasoning_strength,
    cli_supports_reasoning_strength,
    REASONING_STRENGTH_CHOICES,
    real_api_key_or_empty,
    load_runtime_llm,
    normalize_openai_base_url,
    normalize_thinking_level,
    normalize_reasoning_strength,
    effective_reasoning_strengths,
    save_runtime_llm,
    _slot_header_table,
)
from ming_sim.llm_model import verify_llm_available
from ming_sim.entities.issue.commitment_display import (
    commitment_display_text,
    commitment_progress_payload,
    commitment_timed_bar_value,
)
from ming_sim.entities.issue.effects import format_issue_ongoing
from ming_sim.session import GameSession
from ming_sim.session import (
    AUTO_SAVE_PREFIX,
    _is_summonable_court_minister,
)
from ming_sim.highlight_judge import (
    DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
    run_highlight_judge,
)
from ming_sim.session_write_queue import (
    SessionWriteQueue,
    TicketCancelled,
    TicketedWriteGate,
    WriteTicket,
    get_session_write_queue,
)
from ming_sim.token_stats import tlog
from ming_sim.flows import compute_budget_lines
from ming_sim.models import (
    API_DEFAULT_BASE_URL,
    API_DEFAULT_MODEL,
    API_DEFAULT_TIMEOUT_SECONDS,
    Character,
    FRONT_HALF_DONE_PHASES,
    LLMConfig,
    TurnPhase,
    loads_effect_dict,
    reign_period_label,
)
logger = logging.getLogger(__name__)

_DEFAULT_FAVORITES = frozenset({"王承恩", "曹化淳", "李若琏", "魏忠贤", "田尔耕"})

# Formal character-condition value labels (used inside _humanize_condition_value only).
# Free resolve/fail_condition prose is transported unchanged; no catch-all replace.
_CONDITION_DISPLAY_REPLACEMENTS = [
    ("input.factions", "派系盘面"),
    ("input.classes", "阶级盘面"),
    ("input.regions", "地区盘面"),
    ("input.armies", "军队盘面"),
    ("input.current_state", "国势盘面"),
    ("region.", "地区："),
    ("army.", "军队："),
    ("faction.", "派系："),
    ("class.", "阶级："),
    ("power.", "势力："),
    ("registered_land", "已册田亩"),
    ("hidden_land", "隐田"),
    ("tax_per_turn", "月税"),
    ("public_support", "民心"),
    ("grain_security", "粮食"),
    ("unrest", "动乱"),
    ("gentry_resistance", "士绅阻力"),
    ("military_pressure", "边防压力"),
    ("supply", "补给"),
    ("morale", "士气"),
    ("training", "操练"),
    ("equipment", "军械"),
    ("arrears", "欠饷"),
    ("mobility", "机动"),
    ("loyalty", "忠诚"),
    ("controlled_by", "归属"),
    ("leverage", "影响力"),
    ("satisfaction", "满意度"),
    ("resolved", "达成"),
    ("failed", "失败"),
    ("region ", "地区 "),
    ("shenyang_liaoyang", "沈阳辽阳"),
    ("dongjiang_area", "东江海域"),
    ("mongol_chahar", "察哈尔蒙古"),
    ("beizhili", "北直隶"),
    ("nanzhili", "南直隶"),
    ("shandong", "山东"),
    ("shanxi", "山西"),
    ("henan", "河南"),
    ("shaanxi", "陕西"),
    ("zhejiang", "浙江"),
    ("jiangxi", "江西"),
    ("huguang", "湖广"),
    ("sichuan", "四川"),
    ("fujian", "福建"),
    ("guangdong", "广东"),
    ("guangxi", "广西"),
    ("yunnan", "云南"),
    ("guizhou", "贵州"),
    ("liaodong", "辽东"),
    ("dongjiang", "东江"),
    ("xuan_da", "宣大"),
    ("guanning", "关宁军"),
    ("jingying", "京营"),
    ("jizhen", "蓟镇"),
    ("houjin", "后金"),
    ("ming", "大明"),
    (".max", "最高值"),
    (".min", "最低值"),
    (".sum", "合计"),
    (".avg", "均值"),
    ("|", "、"),
    (".", "·"),
]


_CHARACTER_CONDITION_FIELD_LABELS = {
    "loyalty": "忠诚",
    "status": "状态",
    "location": "所在",
    "transit_to": "去向",
    "power_id": "归属",
    "office": "官职",
    "office_type": "职类",
    "faction": "派系",
    "reason_code": "缘由",
}
_CONDITION_OPERATOR_LABELS = {
    "==": "为",
    "!=": "不是",
    ">=": "至少",
    ">": "超过",
    "<=": "不高于",
    "<": "低于",
}


def _humanize_condition_value(field: str, value: str) -> str:
    if field == "status":
        return _STATUS_LABEL_WEB.get(value, value)
    for src, dst in _CONDITION_DISPLAY_REPLACEMENTS:
        value = value.replace(src, dst)
    return value


def _humanize_condition(text: str) -> str:
    """Formal character-condition DSL → display labels; free prose passes through unchanged."""
    if not text:
        return text
    character_condition = re.fullmatch(
        r"\s*character\.([^.]+)\.([A-Za-z_]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*",
        text,
    )
    if not character_condition:
        # N6: no vocabulary replace on free prose / non-formal condition text in transport.
        return text
    name, field, op, value = character_condition.groups()
    if field == "loyalty" and re.fullmatch(r"\d+", value):
        if op in {">=", ">"}:
            return f"{name}忠诚回稳"
        if op in {"<=", "<"}:
            return f"{name}忠诚未稳"
        return f"{name}忠诚非通常取值"
    label = _CHARACTER_CONDITION_FIELD_LABELS.get(field, field)
    op_label = _CONDITION_OPERATOR_LABELS.get(op, op)
    value_label = _humanize_condition_value(field, value)
    return f"{name}{label}{op_label}{value_label}"

_LEGACY_GATE_FIELD_LABELS = {
    "leverage": "影响力",
    "satisfaction": "满意度",
    "controlled_by": "归属",
    "hidden_land": "隐田",
    "gentry_resistance": "士绅阻力",
    "public_support": "民心",
    "unrest": "动乱",
    "military_pressure": "边防压力",
    "tax_per_turn": "税收",
    "morale": "士气",
    "training": "训练",
    "loyalty": "忠诚",
    "supply": "补给",
    "equipment": "装备",
}

_LEGACY_GATE_AGG_LABELS = {
    "max": "最高",
    "min": "最低",
    "sum": "合计",
    "avg": "平均",
}

_LEGACY_GATE_VALUE_LABELS = {
    "ming": "大明",
    "houjin": "后金",
    "bandits": "流寇",
}


def _legacy_gate_subject(raw_key: str, content: Any) -> str:
    parts = raw_key.split(".")
    if len(parts) < 3:
        return _humanize_condition(raw_key)
    scope, raw_ids, field = parts[0], parts[1], parts[2]
    agg = parts[3] if len(parts) > 3 else ""
    ids = [item for item in raw_ids.split("|") if item]
    if scope == "region":
        names = [getattr(content.regions.get(item), "name", item) for item in ids]
    elif scope == "faction":
        names = ids
    elif scope == "army":
        names = [getattr(content.armies.get(item), "name", item) for item in ids]
    else:
        names = ids
    entity = "、".join(str(name) for name in names)
    field_label = _LEGACY_GATE_FIELD_LABELS.get(field, _humanize_condition(field))
    agg_label = _LEGACY_GATE_AGG_LABELS.get(agg, "")
    return f"{entity}{field_label}{agg_label}"


def _humanize_legacy_gate(gate: Dict[str, str], content: Any) -> str:
    """把开局帝国修正的 clear_gate 转为中文展示文案。"""
    clauses: List[str] = []
    for raw_key, raw_expr in gate.items():
        subject = _legacy_gate_subject(str(raw_key), content)
        expr = str(raw_expr).strip()
        match = re.match(r"^(<=|>=|==|!=|<|>)\s*(.+)$", expr)
        if not match:
            clauses.append(f"{subject}达到 {expr}")
            continue
        op, value = match.groups()
        value = _LEGACY_GATE_VALUE_LABELS.get(value.strip(), value.strip())
        op_label = {
            "<=": "≤",
            ">=": "≥",
            "==": "为",
            "!=": "不为",
            "<": "<",
            ">": ">",
        }.get(op, op)
        clauses.append(f"{subject}{op_label}{value}")
    return "；".join(clauses)


def _legacy_effect_entity_name(scope: str, entity_id: str, content: Any) -> str:
    if scope == "regions":
        return str(getattr(content.regions.get(entity_id), "name", entity_id))
    if scope == "armies":
        return str(getattr(content.armies.get(entity_id), "name", entity_id))
    return entity_id


def _legacy_pct(value: int) -> str:
    return f"{'+' if value > 0 else ''}{value}%"


def _humanize_legacy_effect(modifiers: Dict[str, Any], content: Any) -> str:
    """把 legacy modifiers 转为中文展示，避免前端露出 nanzhili/guanning 等内部 id。"""
    parts: List[str] = []
    for account in GATE_METRIC_KEYS:  # #14 same source as db.legacy_modifiers
        value = modifiers.get(account)
        if isinstance(value, (int, float)):
            parts.append(f"{account}{_legacy_pct(int(value))}")
    for scope in ("regions", "armies"):
        block = modifiers.get(scope)
        if not isinstance(block, dict):
            continue
        for entity_id, fields in block.items():
            if not isinstance(fields, dict):
                continue
            entity_name = _legacy_effect_entity_name(scope, str(entity_id), content)
            for field, value in fields.items():
                if not isinstance(value, (int, float)):
                    continue
                field_label = _LEGACY_GATE_FIELD_LABELS.get(str(field), _humanize_condition(str(field)))
                parts.append(f"{entity_name}{field_label}{_legacy_pct(int(value))}")
    return "、".join(parts)


def _cleanup_failure_detail(err: SaveSlotCleanupError) -> str:
    """删主库失败的玩家指引文案（#1902：判定与归类在共享核，文案归 Web 入口）。

    文案与迁移前那份 web 私有实现逐句一致，只是失败原因改读核的 ``reason`` 归类，
    不再各自判一遍 ``isfile`` / ``PermissionError``。
    """
    target = err.target
    if err.reason == "not_a_file":
        return f"重开失败：无法清理主库文件 {target}，它不是普通文件。请检查该路径后再重试。"
    if err.reason == "permission":
        return (
            f"重开失败：权限不足，无法删除主库文件 {target}。"
            "请关闭占用该文件的程序，或用管理员权限运行游戏后重试。"
        )
    return (
        f"重开失败：无法删除主库文件 {target}。系统返回：{err.cause}。"
        "请确认没有其他游戏进程占用该文件；若是权限问题，请用管理员权限运行游戏后重试。"
    )


def _advanced_llm_config_for_verify(config: LLMConfig) -> LLMConfig:
    """主配置上的高级模型槽 → 单独烟测用的 LLMConfig。

    #1902 N2：不另造生效字段映射；复用共核 ``for_role(..., "simulator")`` 的 advanced 切片。
    """
    from ming_sim.llm_config import for_role

    return for_role(config, "simulator")


def _verify_smoke_leg(config: LLMConfig, *, stage: str, prefix: str) -> Optional[HTTPException]:
    """单条点火烟。失败返回已包好的 HTTPException，成功返回 None。"""
    try:
        verify_llm_available(config)
        return None
    except LLMUnavailable as exc:
        exc.stage = stage
        return HTTPException(status_code=400, detail=_exception_detail(exc, prefix))


def _is_deterministic_provider_4xx(err: Optional[HTTPException]) -> bool:
    """主腿提供方确定性 4xx（非 408/429）——可立刻上浮，不必等高级腿耗尽。"""
    if err is None:
        return False
    detail = err.detail
    if not isinstance(detail, dict):
        return False
    try:
        status = int(detail.get("status_code"))
    except (TypeError, ValueError):
        return False
    return 400 <= status < 500 and status not in (408, 429)


def _verify_llm_configs_or_raise(config: LLMConfig) -> None:
    """校验主模型；API 通道若配置了 advanced_model，与主模型并行烟测（#884 / P5）。

    CLI 通道只验当前 CLI 主槽；保留的 API advanced 槽不另起一腿、也不改槽字段。
    主腿确定性 4xx 已完成后立即上浮，不等高级腿耗尽。
    """
    legs: List[tuple[str, LLMConfig, str]] = [
        ("smoke-main", config, "主模型连通性检查失败："),
    ]
    channel = (config.channel or "").strip().lower()
    if channel != "cli" and (config.advanced_model or "").strip():
        legs.append(
            (
                "smoke-advanced",
                _advanced_llm_config_for_verify(config),
                "高级模型连通性检查失败：",
            )
        )
    for stage, _cfg, _prefix in legs:
        tlog(f"[llm:stage] {stage}")
    if len(legs) == 1:
        err = _verify_smoke_leg(legs[0][1], stage=legs[0][0], prefix=legs[0][2])
        if err is not None:
            raise err
        return
    pool = ThreadPoolExecutor(max_workers=len(legs), thread_name_prefix="llm-smoke")
    try:
        futures = [
            pool.submit(_verify_smoke_leg, cfg, stage=stage, prefix=prefix)
            for stage, cfg, prefix in legs
        ]
        main_fut = futures[0]
        pending = set(futures)
        errors_by_fut: Dict[Future, Optional[HTTPException]] = {}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                errors_by_fut[fut] = fut.result()
            if main_fut in errors_by_fut:
                main_err = errors_by_fut[main_fut]
                if _is_deterministic_provider_4xx(main_err):
                    raise main_err
        # 主腿优先 surface，避免并行把高级失败盖过主模型失败。
        for fut in futures:
            err = errors_by_fut.get(fut)
            if err is not None:
                raise err
    finally:
        # 主腿 4xx 快路径不 cancel 高级腿、也不等它耗尽；线程池自行收尾。
        pool.shutdown(wait=False)


def _exception_detail(exc: BaseException, prefix: str = "") -> Dict[str, Any]:
    """Project the actual failure; reuse existing diagnostic packs for HTTP and SSE."""
    detail = {"message": f"{prefix}{str(exc) or type(exc).__name__}"}
    if isinstance(exc, SettlementAbort):
        detail.update(stage=exc.stage, error_pack_path=exc.error_pack_path, turn=exc.turn)
    cause = exc
    while cause.__cause__ is not None and not isinstance(cause, LLMUnavailable):
        cause = cause.__cause__
    detail["error_type"] = getattr(cause, "error_type", None) or type(cause).__name__
    detail["reason"] = str(cause) or type(cause).__name__
    if isinstance(cause, BaseExceptionGroup):
        detail["reason"] = "；".join(str(sub) for sub in cause.exceptions)
    if isinstance(cause, subprocess.CalledProcessError):
        detail.update(
            reason=str(cause.stderr or cause),
            returncode=cause.returncode,
            stderr=str(cause.stderr or ""),
            stdout=str(cause.stdout or ""),
        )
    if isinstance(cause, LLMUnavailable):
        detail.update(
            reason=cause.provider_message or str(cause),
            code=cause.code,
            provider_message=cause.provider_message,
            status_code=cause.status_code,
        )
        if cause.transport_attempts is not None:
            detail["transport_attempts"] = cause.transport_attempts
        if cause.stage and "stage" not in detail:
            detail["stage"] = cause.stage
    if not detail.get("error_pack_path"):
        from ming_sim.audience_night import write_audience_error_pack

        detail["error_pack_path"] = write_audience_error_pack(
            kind="web", message=detail["message"], detail=detail, exc=exc,
        )
    return detail


# #1902：数值槽宽容取值与「是否真 key」判定都只在 llm_config 一处实现，
# web 侧这两个名字保留为薄转发（多处读档投影沿用），不再各写一份规则。

_has_real_api_key = is_real_api_key


# #1902：runtime json → LLMConfig 的投影下沉到 llm_config.llm_config_from_runtime
# （唯一真源）；此处只调用，不再在 web 侧留一份同名实现。
from ming_sim.llm_config import llm_config_from_runtime as _llm_config_from_runtime


def _api_reasoning_supported_for_effective_model(
    base_url: str,
    model: str,
    advanced_base_url: str = "",
    advanced_model: str = "",
) -> bool:
    adv_model = (advanced_model or "").strip()
    if adv_model:
        return api_supports_reasoning_strength((advanced_base_url or "").strip() or base_url, adv_model)
    return api_supports_reasoning_strength(base_url, model)


class ChatRequest(BaseModel):
    message: str


class AdvanceWithoutEdictRequest(BaseModel):
    """#1351 A1：可选回合令牌；缺省兼容无令牌旧客户端。"""
    expected_turn: Optional[int] = None


def _character_power_id(character: Character, db) -> str:
    """人物所属势力 id：DB 权威，回退内存 power_id，默认 ming。

    权威解析单一真源在 db.resolve_power_id（session.can_summon 等同源复用，见 #125），
    此处委托，朝堂可见性/召见两端口径一致、不各写一份。"""
    return db.resolve_power_id(character)


def visible_in_court(character: Character, db) -> bool:
    """朝堂大臣列表准入：在朝可召资格 + DB 权威状态非 offstage（离场/未登场不入列）。

    资格单真源 session._is_summonable_court_minister（#1317 r2：身份归一∧非宗藩∧非未仕）——
    与 can_summon/CLI/事实块同口径，禁另造过滤表。resolve 惰性入参，
    类型短路不得与谓词条件并存。
    状态与势力一律以 DB 为准（与 public_character 同源）——内存 c.status 在 auto-debut
    等路径（set_character_status 只写 DB、不回写内存）会 stale，不能用作过滤依据（见 #104）。

    宗藩/未仕不是可召见/可任免的朝堂官员，排除出朝堂+任免列表；藩王/诸生在册数据照旧
    留 DB，事件按名引用与铨选任命不受影响。
    """
    if not _is_summonable_court_minister(
        character,
        resolve_power_id=lambda c: _character_power_id(c, db),
    ):
        return False
    if db.characters.get_character_status(character.name)[0] == "offstage":
        return False
    return True


def in_talent_pool(character: Character, db, current_year: int, current_period: int) -> bool:
    """在野人才池准入（UI 端 offstage 子集）：可起复的前臣——DB 权威状态 offstage（不在朝）
    + ming 治下 + 非（后宫/宗藩/未仕）+ 非流寇（按 faction）+ 已历史登场（year+month）。

    解决「罢居前臣（孙承宗/韩爌/钱龙锡 等）被 #104 挡出朝堂列表后哪都看不见、无法起复」——
    他们 status=offstage、office_type=边镇/地方/礼部/内阁、debut_year=0（开局即在世，自请罢居）。
    排除：①未登场的未来人物（登场年月晚于当前，如左良玉 1630、吴三桂 1631——剧透）②未仕（史可法
    这类未入仕者）③流寇（李自成/张献忠 这类非起复对象）④宗藩（藩王不入仕）。设计依据
    docs/HISTORICAL_CASE_LIBRARY.md:41「人才池视图 + 起复派生」。

    流寇按 **faction** 排除而非 office_type：盘面无 office_type=流寇（实为 外臣/未仕），且招抚归明
    后 power_id 翻 ming（character_power_changes），仅靠 power_id 闸会把前流寇漏进起复池。

    登场判据对齐 db.apply_historical_debuts（year+month），否则同年但月份未到的人物会提前进池。

    范围说明：dismissed/retired/imprisoned 等在朝转出的非 active 已在朝堂「全部」栏可见
    （visible_in_court 只挡 offstage），故 UI 人才池只补 offstage 这一漏面。"""
    if character.office_type in ("后宫", "宗藩", "未仕"):
        return False
    if getattr(character, "faction", "") == "流寇":
        return False
    if db.characters.get_character_status(character.name)[0] != "offstage":
        return False
    debut_year = int(getattr(character, "debut_year", 0) or 0)
    debut_month = int(getattr(character, "debut_month", 0) or 0)
    if debut_year > current_year or (debut_year == current_year and debut_month > current_period):
        return False
    return _character_power_id(character, db) == "ming"


def _safe_save_name(name: str) -> str:
    """存档名清洗真源在 ``paths.safe_save_name``（#1902：菜单页 / WebGame / CLI 共用）。

    对外仍抛 HTTPException 400（Web 入口的形态）；非法名本身由共享核判定。
    """
    from ming_sim.paths import UnsafeSaveNameError, safe_save_name

    try:
        return safe_save_name(name)
    except UnsafeSaveNameError as err:
        raise HTTPException(status_code=400, detail=str(err))


class _WebSaveSlotHost:
    """#1902 F2：把 WebGame 的换库宿主能力适配给共享核 ``save_slots``。

    编排（备份/热替换/失败恢复）在共享核；此处只答「Web 侧怎么拿写队列、结算准入
    锁、在飞计数、怎么重建候选、怎么处置失败候选」，并把独占区里的结算在飞拒收
    翻成 Web 的 409（共享核抛 RuntimeError 带同一文案）。
    """

    def __init__(self, game: "WebGame") -> None:
        self.game = game

    def write_queue(self, runtime: Any):
        return get_session_write_queue(runtime)

    def entry_lock(self, runtime: Any):
        return runtime._settlement_entry_lock

    def settlement_inflight(self, runtime: Any) -> int:
        return int(runtime._settlement_entry_inflight or 0)

    def rebuild(self, runtime: Any, llm_config: LLMConfig) -> None:
        runtime._rebuild_session(llm_config)

    def dispose_residual(self, runtime: Any, residual: Any) -> bool:
        if residual is None:
            return True
        runtime._rebuild_residual_runtime = residual
        return runtime._dispose_rebuild_residual()

    def busy_detail(self) -> str:
        return "月末结算或上一步写入进行中，请稍候再操作。"


class WebGame:
    """Web 端会话包装：持一个 GameSession + 网页专属态（聊天历史、收藏）。"""

    def __init__(
        self,
        fresh: bool = False,
        on_stage: Optional[Callable[[str], None]] = None,
        db_path: Optional[str] = None,
    ) -> None:
        """实例化 = 真正进入游戏。无 API key 直接抛 LLMUnavailable。
        fresh=True：先清空主 DB（新游戏）再建 session。
        on_stage：#1195 可选阶段回调（仅推叙事文案，不改 GameSession 初始化序）。
        db_path：#1749 候选路径绑定——构造期不重读全局 _get_main_db_path，避免并发切换串库。
        """
        def _stage(label: str) -> None:
            if on_stage is not None:
                on_stage(label)

        if db_path:
            db_path = _normalize_db_path(db_path)
        else:
            db_path = _get_main_db_path()
        base_url = os.environ.get("OPENAI_BASE_URL", API_DEFAULT_BASE_URL)
        model = os.environ.get("OPENAI_MODEL", API_DEFAULT_MODEL)
        api_key = os.environ.get("OPENAI_API_KEY", "")
        advanced_model = os.environ.get("OPENAI_ADVANCED_MODEL", "")
        advanced_base_url = os.environ.get("OPENAI_ADVANCED_BASE_URL", "")
        advanced_api_key = os.environ.get("OPENAI_ADVANCED_API_KEY", "")
        # #1902 J3：思考档的 env 回落不再由本入口自读（落差已在
        # llm_config.llm_config_from_runtime 一处决定，CLI 入口同样传空串）。
        thinking_level = ""
        advanced_thinking_level = ""
        timeout_seconds = float(os.environ.get("OPENAI_TIMEOUT_SECONDS") or API_DEFAULT_TIMEOUT_SECONDS)
        # #1902 F1：「运行档优先、env/入参回落」的落差只在 llm_config_from_runtime
        # 一处决定——两端入口不再各自把运行档拼一遍（此前只有 Web 做，CLI 直接把
        # 入参当最终值，同一份档经两端建局得到不同执行事实）。
        runtime = load_runtime_llm()
        random.seed(int(os.environ.get("MING_SIM_SEED", "7")))
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        llm_config = _llm_config_from_runtime(
            runtime,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            thinking_level=thinking_level,
            advanced_model=advanced_model,
            advanced_base_url=advanced_base_url,
            advanced_api_key=advanced_api_key,
            advanced_thinking_level=advanced_thinking_level,
        )
        if llm_config.channel != "cli" and not llm_config.api_key:
            raise LLMUnavailable("未配 API key，请先到设置页填写。")
        # #1195：阶段标签紧贴既有分段（GameSession / begin_turn / 召对恢复）；
        # #1228：载入路径零 verify 调用——连通性 smoke 已拆除，报错落到玩家真实 LLM 动作。
        if fresh:
            # #1902：删库实现唯一在共享核 save_slots（此前 web_app 另有一份同构的
            # _delete_sqlite_db_files_or_raise，两份只差异常形态——那份已删）。
            # 此处只把核的归类翻成 Web 的 500 与玩家指引文案。
            try:
                delete_sqlite_db_files_or_raise(db_path)
            except SaveSlotCleanupError as err:
                raise HTTPException(
                    status_code=500,
                    detail=_cleanup_failure_detail(err),
                ) from err
        _stage("载入上次进度...")
        # #1749：GameSession 建立后任一后续步骤失败须 close，禁泄漏 db/agno 连接。
        self.session = None  # type: ignore[assignment]
        try:
            self.session = GameSession(db_path, llm_config)
            # #542：Web/CLI/收夜共用 session 持有的真实 scene LLM adapter；测试可在此 seam 注入 fake。
            # #1353：per-session 单写者票据队列 = 唯一写点；write_gate 并入队列执行器。
            self._write_queue: SessionWriteQueue = get_session_write_queue(self.session)
            self._write_gate = self._write_queue.write_gate
            self.session._write_gate = self._write_gate  # type: ignore[attr-defined]
            self.session._write_queue = self._write_queue  # type: ignore[attr-defined]
            # #1235 r4：点即入入口 in-flight 计数——accept 后 gate-free 窗锁闲≠孤儿；
            # 非创建者 exit 仅当无其他入口仍在办时才可清（见 _begin/_end_settlement_entry）。
            self._settlement_entry_lock = threading.Lock()
            self._settlement_entry_inflight = 0
            _stage("重整朝堂名册...")
            self.session.begin_turn()
            # #1234：唯一服务进程启动缝——孤儿月初快照清除（相位常态∧快照在→清+一行日志；
            # settling/awaiting 不清，交既有恢复）。与故障注入 oracle 同调具名函数。
            from ming_sim.month_open_snapshot import clear_orphan_month_open_snapshot
            clear_orphan_month_open_snapshot(self.db, self.state)
            # 召对记录持久化在 chat_messages 表，启动时恢复进内存缓存。
            _stage("恢复召对记录...")
            self.chat_history: Dict[str, List[Dict[str, str]]] = {
                name: [] for name in self.session.content.characters
            }
            for name, msgs in self.db.chat_messages.history_by_minister().items():
                self.chat_history.setdefault(name, []).extend(msgs)
            _fav_raw = self.db.reign.kv_get("favorites")
            self.favorites: set = (
                set(_load_durable_str_list(_fav_raw, surface="kv_store.favorites"))
                if _fav_raw is not None else set(_DEFAULT_FAVORITES)
            )
            if _fav_raw is None:
                self.db.reign.kv_set("favorites", json.dumps(sorted(self.favorites)))
            # #505／#1902 T4：启动恢复生命周期归会话共核；入口只调共核再启宿主后台补跑。
            self.session.reconcile_crashed_audience_turns()
            # #501：重开后补跑崩溃窗口里丢的叙事抽取账（后台、从不锁档）。
            self._spawn_startup_extraction_catch_up()
        except Exception as init_exc:
            # #1749 B：构造失败携回——残余 session 交同一 holder/CloseOp（失败 op），
            # 不得只 register close_op=None 的壳。
            session = getattr(self, "session", None)
            residual = getattr(init_exc, "residual_session", None)
            if session is None and residual is not None:
                self.session = residual
                _handback_failed_runtime(self, db_path)
            elif session is not None:
                try:
                    session.close()
                except Exception as _caught_failure:
                    logger.exception(
                        "WebGame init failed; session.close failed path=%s error=%s",
                        db_path,
                        _caught_failure,
                    )
                    _handback_failed_runtime(self, db_path)
            raise

    # ── 存档管理 ─────────────────────────────────────────────────────────
    def saves_dir(self) -> str:
        return user_data_path("saves")

    def list_saves(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        campaign_id = (self.db.reign.kv_get("campaign_id") or "").strip()
        for fname in sorted(os.listdir(self.saves_dir())):
            if not fname.endswith(".db"):
                continue
            if not _save_visible_for_campaign(fname, campaign_id):
                continue
            full = os.path.join(self.saves_dir(), fname)
            try:
                st = os.stat(full)
            except FileNotFoundError:
                continue
            out.append({
                "name": fname[:-3],
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
        out.sort(key=lambda x: x["mtime"], reverse=True)
        return out

    def _safe_save_name(self, name: str) -> str:
        # #1902：存档名校验唯一真源在模块级 _safe_save_name（菜单页无 WebGame 实例时同用）。
        return _safe_save_name(name)

    def save_to(self, name: str) -> Dict[str, Any]:
        # #1902 F2：存档真源在会话层（CLI 与 Web 同一条），此处只把 Web 的
        # 400 形态接上；名非法由共享核判。
        try:
            return dict(self.session.save_to(name))
        except UnsafeSaveNameError as err:
            raise HTTPException(status_code=400, detail=str(err))


    def _dispose_rebuild_residual(self) -> bool:
        """#1749 B：处置上一失败 rebuild 候选。成功关闭返回 True；仍活则 False 且保留引用。"""
        residual = getattr(self, "_rebuild_residual_runtime", None)
        if residual is None:
            return True
        path = _path_norm_of_game(residual, getattr(self, "db_path", "") or "")
        entry = _lookup_holder(path, residual) if path else None
        ok = False
        if entry is not None:
            role, op = _claim_close(entry, path)
            if role == "executor" and op is not None:
                try:
                    _drain_and_close_session(residual, entry=entry, close_op=op)
                except Exception as _caught_failure:
                    logger.exception(
                        "dispose rebuild residual drain failed path=%s error=%s",
                        path,
                        _caught_failure,
                    )
                ok = bool(op.done.is_set() and op.close_ok)
            elif role == "released_ok":
                ok = True
            elif op is not None:
                op.done.wait()
                ok = bool(op.close_ok)
        else:
            session = getattr(residual, "session", residual)
            close_fn = getattr(session, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                    ok = True
                except Exception as _caught_failure:
                    logger.exception(
                        "dispose rebuild residual close failed path=%s error=%s",
                        path,
                        _caught_failure,
                    )
                    _handback_failed_runtime(residual, path or self.db_path)
                    ok = False
            else:
                ok = True
        if ok:
            self._rebuild_residual_runtime = None
        return ok

    def _replace_database(self, destructive_replace: Callable[[], None]) -> None:
        """Drain admitted work, then replace the main DB under one exclusive barrier.

        #1902 F2：编排本身在共享核 ``ming_sim.save_slots.replace_database``（CLI 读档
        与新档走同一条），此处只提供 Web 侧宿主能力：写队列、结算准入锁与在飞计数、
        候选重建与失败候选处置。
        """
        from ming_sim.save_slots import SaveSlotBusyError, replace_database

        try:
            replace_database(self, _WebSaveSlotHost(self), destructive_replace)
        except SaveSlotBusyError as busy:
            # 独占区里的结算在飞拒收：对外仍是 Web 的 409（前端与 tracer 据此分流）。
            raise HTTPException(status_code=409, detail=busy.detail)

    def load_save(self, name: str) -> None:
        """从存档热替换主 DB；失败时恢复替换前的数据库与 runtime。"""
        safe = self._safe_save_name(name)
        source = os.path.join(self.saves_dir(), f"{safe}.db")
        if not os.path.isfile(source):
            raise HTTPException(status_code=404, detail="存档不存在。")

        # #1902：覆盖拷贝走共享核唯一实现（此前此处与 cli._cli_load 各带一份
        # 逐行相同的 sqlite backup 闭包——两份已删）。
        self._replace_database(
            lambda: copy_sqlite_file(source, self.db_path),
        )

    def _rebuild_session(self, llm_config: LLMConfig) -> None:
        """发布换库候选：共同生命周期在 save_slots；此处只映射呈现准备与发布。"""
        from ming_sim.save_slots import open_candidate_session

        # #1749：先处置上一失败候选；仍活则拒绝新候选，禁覆盖仍活资源。
        if not self._dispose_rebuild_residual():
            raise RuntimeError(
                f"previous rebuild residual still live path={self.db_path}"
            )

        def _prepare_web_presentation(candidate: GameSession):
            # 发布前准备：仍在共核失败关闭保护区内（读历史/收藏失败须关候选）。
            chat_history = {name: [] for name in candidate.content.characters}
            for name, msgs in candidate.db.chat_messages.history_by_minister().items():
                chat_history.setdefault(name, []).extend(msgs)
            fav_raw = candidate.db.reign.kv_get("favorites")
            favorites = (
                set(_load_durable_str_list(fav_raw, surface="kv.favorites"))
                if fav_raw is not None else set(_DEFAULT_FAVORITES)
            )
            if fav_raw is None:
                candidate.db.reign.kv_set("favorites", json.dumps(sorted(favorites)))
            return chat_history, favorites

        try:
            candidate, (chat_history, favorites) = open_candidate_session(
                self.db_path, llm_config, prepare=_prepare_web_presentation,
            )
        except Exception as rebuild_exc:
            # residual 挂在实际传出的异常上（含 close 失败那只）。
            residual = getattr(rebuild_exc, "residual_session", None)
            if residual is not None:
                wrapper = SimpleNamespace(
                    db_path=self.db_path,
                    session=residual,
                    _write_queue=getattr(residual, "_write_queue", None),
                    _write_gate=getattr(residual, "_write_gate", None),
                )
                _handback_failed_runtime(wrapper, self.db_path)
                self._rebuild_residual_runtime = wrapper
            raise

        # 发布：挂候选自有队列，不沿用已 seal 的旧队列。
        q = get_session_write_queue(candidate)
        self.session = candidate
        self._write_queue = q
        self._write_gate = q.write_gate
        self.chat_history = chat_history
        self.favorites = favorites

    # ── 便捷属性 ──────────────────────────────────────────────────────────
    @property
    def db(self):
        return self.session.db

    @property
    def state(self):
        return self.session.state

    @property
    def content(self):
        return self.session.content

    @property
    def previous_summary(self) -> str:
        return self.session.previous_summary

    @property
    def last_decree(self) -> str:
        return self.session.last_decree

    @property
    def last_report(self) -> str:
        """#1382：上一已完成月 turn_reports 原文；禁 session 瞬态缓存。"""
        previous_turn = int(self.state.turn) - 1
        if previous_turn < 0:
            return ""
        return self.db.turn_reports.report_text(previous_turn)

    def _runtime_write_queue(self) -> SessionWriteQueue:
        return get_session_write_queue(self)

    def _runtime_write_gate(self) -> threading.Lock:
        return self._runtime_write_queue().write_gate

    def _ticketed_write_gate(
        self, ticket: WriteTicket,
    ) -> TicketedWriteGate:
        """#1353：生产写 seam——必须持有效票，无裸 write_gate 回落。"""
        if ticket is None:
            raise RuntimeError("ticketed write requires a live WriteTicket")
        return self._runtime_write_queue().ticketed_gate(ticket)

    def _mark_pending_write(
        self, key: Optional[Any] = None,
    ) -> Optional[WriteTicket]:
        """#1353：起跑领票。返回票据；队列已 seal（生命周期 drain）→ None 拒入。

        队列长度即在途事实来源；领票方须在 finally 里 _complete_pending_write(ticket)。
        spawn 路由 `_spawn_pending_write_thread` 单真源 claim/try/finally 包任意 callee。
        key 用于撤回轮 cancel（ADR 0038）——尾随建议 key=("turn", chat_turn_id)。
        """
        return self._runtime_write_queue().claim(key=key if key is not None else ("pending",))

    def _complete_pending_write(self, ticket: Optional[WriteTicket] = None) -> None:
        """释放领票（成功/失败/空放行同形）。"""
        self._runtime_write_queue().complete(ticket)

    def refresh_turn(self) -> None:
        self.session.begin_turn()
        # #1343 孤儿快照清一处：受理样板成功支（_settlement_period_entry 持 write_cm）。
        # 生产四调用点皆在 entry 体内（inflight>0），此处再清恒不触发；禁第二清理点。

    # ── 序列化 ────────────────────────────────────────────────────────────
    def public_character(self, character: Character) -> Dict[str, Any]:
        status, status_reason = self.db.characters.get_character_status(character.name)
        # #1683：active=官印/在事态，不得单独译成物理「在朝」；去向另投影 location/transit。
        status_label = _STATUS_LABEL_WEB.get(status, status)
        office = character.office  # 去职者已被清空，可能为空串
        # summary 不含官职（卡片/详情已单独显 office），避免重复
        summary = f"{character.faction}一系，行事{character.style}。"
        power_id = self.db.resolve_power_id(character)  # 权威解析单一真源（#125）
        loc_row = self.db.characters.read_admit_audience((character.name,))
        location = str(loc_row["location"] or "") if loc_row is not None else ""
        transit_to = str(loc_row["transit_to"] or "") if loc_row is not None else ""
        regions = getattr(self.content, "regions", None) or {}

        def _region_label(region_id: str) -> str:
            if not region_id:
                return ""
            region = regions.get(region_id) if hasattr(regions, "get") else None
            name = getattr(region, "name", None) if region is not None else None
            return str(name or region_id)

        return {
            "name": character.name,
            "office": office,
            "office_type": character.office_type,
            "faction": character.faction,
            "style": character.style,
            "status": status,
            "status_reason": status_reason,
            "status_label": status_label,
            "location": location,
            "location_label": _region_label(location),
            "transit_to": transit_to,
            "transit_to_label": _region_label(transit_to),
            "summary": summary,
            "portrait_id": character.portrait_id,
            "power_id": power_id,
            "favorite": character.name in self.favorites,
        }

    def character_power_id(self, character: Character) -> str:
        return _character_power_id(character, self.db)

    def directive_payload(self, row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "event_id": row["event_id"] or "",
            "event_title": row["event_title"] or "",
            "actor": row["actor"] or "",
            "text": row["text"],
            "source": row["source"],
            "status": row["status"],
            "notes": row["notes"],
            # #1319(a)：authority 按真源投影；不得把 notes 备注别名为权威来源。
            "authority": (
                str(row["authority"] or "").strip()
                if hasattr(row, "keys") and "authority" in row.keys()
                else ""
            ),
        }

    def directive_rows(self):
        """Player desk projection shared with the CLI: undossiered candidates only."""
        visible_ids = {
            item.id for item in self.session.list_directives(include_pending=True)
        }
        return [
            row for row in self.db.issues.list_directives(self.state.turn, statuses=("pending", "draft"),
            )
            if int(row["id"]) in visible_ids
        ]

    def cased_directive_payloads(self) -> List[Dict[str, Any]]:
        """#1764 御案只读投影：已成案·待盖玺（0051 proposed）。

        读 issues.list_dossiered_draft_directives + dossier status；不改 list_directives 过滤，
        不另立事实源。上游 SELECT td.* + EXISTS 按主键逐行返回，无需 seen 去重。
        过月后 draft 迁出则桌空。
        """
        out: List[Dict[str, Any]] = []
        for row in self.db.issues.list_dossiered_draft_directives(self.state.turn):
            dir_id = int(row["id"])
            dossier = self.db.dossiers.get_for_directive(dir_id)
            if dossier is None:
                continue
            if str(dossier.get("status") or "") != "proposed":
                continue
            out.append({
                "id": dir_id,
                "dossier_id": int(dossier["id"]),
                "text": str(row["text"] or dossier.get("decree_text") or ""),
                "source": str(row["source"] or ""),
                "actor": str(row["actor"] or ""),
                "notes": str(row["notes"] or ""),
                "dossier_status": str(dossier["status"]),
            })
        return out

    def pending_directive_count(
        self, pending_actions: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """对话式拟旨暂存数（pending_actions kind=directive）唯一计数缝——state/chat done 共用。"""
        rows = pending_actions
        if rows is None:
            rows = self.db.dossiers.list_pending_actions(int(self.state.turn))
        return sum(1 for a in rows if a["kind"] == "directive")

    def map_nodes(self) -> List[Dict[str, Any]]:
        """地图节点投影。#1505：typed station_region 单归属；一军一挂；liaodong/dongjiang_area 同 id 合 theater+region。"""
        region_positions = {
            "beizhili": (55.5, 41.2), "nanzhili": (70, 41), "shandong": (56.8, 47.9),
            "shanxi": (48.8, 45.2), "henan": (58, 46), "shaanxi": (51, 38),
            "zhejiang": (73.7, 57.9), "jiangxi": (67, 55), "huguang": (59, 59),
            "sichuan": (57, 52), "fujian": (73.2, 65.1), "guangdong": (62.5, 73.6),
            "guangxi": (53.9, 69.6), "yunnan": (47, 69), "guizhou": (52, 56),
            # liaodong 与 theater 同 id 时走 theater_positions，此键仅兜底未合并路径
            "liaodong": (61.0, 37.6), "dongjiang_area": (68.9, 43.7),
            "shenyang_liaoyang": (61.3, 39.6), "jianzhou": (64.6, 31.0),
            "korea": (67.0, 44.8), "mongol_chahar": (47.0, 31.0), "nurgan": (58.2, 21.2),
            "outer_mongolia": (43.0, 24.0), "western_regions": (25.0, 40.0),
            "tibet": (31.0, 57.0), "amur_frontier": (70.0, 24.0),
            "japan": (83.0, 49.0), "southwest_frontier": (45.0, 75.0),
            "taiwan": (78, 67),
        }
        # 仅保留与 region 同 id 的合并 theater 针（辽东、东江）
        theater_positions = {
            "liaodong": (57.76, 42.21),
            "dongjiang_area": region_positions["dongjiang_area"],
        }
        armies = self.db.army_payload(danger_order=True)
        station_by_id = {
            str(row["id"]): str(row["station_region"] or "").strip()
            for row in self.db.army_rows(danger_order=True)
        }
        # #648：玩家面人口呈现走既批路径——simulator seam featured input +
        # LLM 长出叙事；web 直显模板已按 P7 删除，地图节点只回单一
        # db.region_payload()（机面 population），不再有第二套 UI 投影。
        regions = self.db.region_payload()
        # 一军一挂：按 typed station_region 单归属；空/未知不猜、不吊 any province 节点
        region_armies: Dict[str, List[Dict[str, Any]]] = {
            str(region["id"]): [] for region in regions
        }
        for army in armies:
            aid = str(army["id"])
            rid = station_by_id.get(aid, "")
            if not rid or rid not in region_armies:
                continue  # empty or unknown: no map hang, no text guess
            region_armies[rid].append(army)
        nodes: List[Dict[str, Any]] = []
        for region in regions:
            rid = str(region["id"])
            buildings = self.db.building_payload(rid)
            risk = int(region["unrest"]) + int(region["military_pressure"]) + (100 - int(region["public_support"]))
            stationed = list(region_armies.get(rid, []))
            if rid in theater_positions:
                # 与 theater 同 id：合并为带 region 的 theater 节点
                x, y = theater_positions[rid]
                nodes.append({
                    "id": rid,
                    "kind": "theater",
                    "x": x,
                    "y": y,
                    "label": self._theater_label(rid),
                    "region": region,
                    "armies": stationed,
                    "buildings": buildings,
                    "risk": risk,
                })
            else:
                x, y = region_positions.get(rid, (50, 50))
                node_kind = "region" if str(region.get("controlled_by") or "ming") == "ming" else "external"
                nodes.append({
                    "id": rid,
                    "kind": node_kind,
                    "x": x,
                    "y": y,
                    "region": region,
                    "armies": stationed,
                    "buildings": buildings,
                    "risk": risk,
                })
        return nodes

    def _theater_label(self, theater_id: str) -> str:
        return {
            "liaodong": "辽东 / 宁锦",
            "dongjiang_area": "东江 / 皮岛",
        }[theater_id]

    def closed_this_turn_payloads(self) -> List[Dict[str, Any]]:
        """上回合（resolve 后 state.turn 已 +1）关闭的 issue。"""
        target_turn = max(0, int(self.state.turn) - 1)
        out: List[Dict[str, Any]] = []
        for row in IssueStore(self.db.conn).read_list_closed_issues_at((target_turn,)):
            status = str(row["status"])
            effect_key = "effect_on_resolve" if status == "resolved" else "effect_on_fail"
            effect = loads_effect_dict(row[effect_key])  # 统一守门，绝不向前端吐非 dict（#117 R5）
            out.append({
                "id": int(row["id"]),
                "kind": row["kind"],
                "title": row["title"],
                "status": status,
                "bar_value": int(row["bar_value"]),
                "bar_good_meaning": row["bar_good_meaning"],
                "bar_bad_meaning": row["bar_bad_meaning"],
                "closed_turn": int(row["closed_turn"] or 0),
                "stage_text": row["stage_text"],
                "effect": effect,
            })
        return out

    def issue_payloads(self) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for row in self.db.issues.active_rows():
            commitment_progress = commitment_progress_payload(self.db, self.state, row)
            payload = {
                "id": int(row["id"]),
                "kind": row["kind"],
                "title": row["title"],
                "bar_value": int(row["bar_value"]),
                "bar_good_meaning": row["bar_good_meaning"],
                "bar_bad_meaning": row["bar_bad_meaning"],
                "phase": row["phase"],
                "stage_text": row["stage_text"],
                "severity": int(row["severity"]),
                "tags": _load_durable_str_list(row["tags"], surface="legacies.tags"),
                "inertia": int(row["inertia"] or 0),
                "resolve_condition": _humanize_condition(row["resolve_condition"] or ""),
                "fail_condition": _humanize_condition(row["fail_condition"] or ""),
                "ongoing_text": format_issue_ongoing(str(row["ongoing_effects"] or "{}")),
                "effect_on_resolve": loads_effect_dict(row["effect_on_resolve"]),
                "effect_on_fail": loads_effect_dict(row["effect_on_fail"]),
            }
            if commitment_progress is not None:
                timed_bar = commitment_timed_bar_value(commitment_progress, row)
                if timed_bar is not None:
                    payload["bar_value"] = timed_bar
                payload["commitment_progress"] = commitment_progress
                payload["commitment_progress_text"] = commitment_display_text(commitment_progress, row)
            payloads.append(payload)
        return payloads

    def memorial_payloads(self) -> List[Dict[str, Any]]:
        """#1726 奏疏收件箱投影：进度奏报 + 派系检举；正文原样，已读位随存档。"""
        return self.db.list_player_memorials()

    def mark_memorials_read(self, keys: List[str]) -> Dict[str, Any]:
        self.db.reign.mark_memorials_read(keys)
        memorials = self.memorial_payloads()
        return {
            "memorials": memorials,
            "unread_memorial_count": sum(1 for m in memorials if m.get("unread")),
        }

    def legacies_payload(self) -> List[Dict[str, Any]]:
        """现行帝国修正（长期百分比修正符），给状态栏小条用。"""
        out: List[Dict[str, Any]] = []
        opening_clear_text = {
            leg.key: leg.clear_narrative
            for leg in self.content.opening_legacies
            if leg.clear_narrative
        }
        for row in self.db.list_active_legacies(self.state):
            eff = parse_engine_payload_json(
                row["modifiers"],
            )
            clear_gate = parse_engine_payload_json(
                row["clear_gate"],
            )
            remaining_months = self.db.legacy_remaining_months(row, self.state)
            clear_condition = opening_clear_text.get(str(row["legacy_key"] or ""), "")
            if not clear_condition and clear_gate:
                clear_condition = _humanize_legacy_gate(clear_gate, self.content)
            elif clear_condition and clear_gate:
                clear_condition = f"{clear_condition}（{_humanize_legacy_gate(clear_gate, self.content)}）"
            if not clear_condition:
                clear_condition = "无固定消除条件" if remaining_months < 0 else f"再过 {remaining_months} 月自然消退"
            out.append({
                "id": int(row["id"]),
                "name": row["name"],
                "narrative_hint": row["narrative_hint"],
                "modifiers": eff,
                "effect_text": _humanize_legacy_effect(eff, self.content),
                "remaining_months": remaining_months,
                "clear_condition": clear_condition,
            })
        return out

    def _month_open_snapshot(self) -> Optional[Dict[str, int]]:
        """#1234 路③：当前回合未过期月初快照；无则 None（⇔ 非核账展示态）。"""
        return self.db.month_open_snapshots.get(int(self.state.turn))

    def _display_metrics(self) -> Dict[str, int]:
        """顶栏四键呈现缝：核账期读快照，否则读活值。"""
        metrics = dict(self.state.metrics)
        snap = self._month_open_snapshot()
        if snap is not None:
            metrics.update(snap)
        return metrics

    def budget_payload(self) -> Dict[str, Any]:
        # 唯一定额源：flows.compute_budget_lines（与实际落账 / 大臣 treasury_budget_summary 三处统一）。
        budget = compute_budget_lines(self.db, self.state)
        # #1234：户部余额与顶栏同缝——核账期读月初快照四键。
        display = self._display_metrics()
        budget["国库"]["balance"] = int(display["国库"])
        budget["内库"]["balance"] = int(display["内库"])
        for account in (budget["国库"], budget["内库"]):
            # #1471：玩家 HUD 定额精确投影 {name, amount}；flows/fiscal_config 工程 note·internal 留源侧。
            for direction in ("income", "expense"):
                account[direction] = [
                    {
                        "name": str(item["name"]),
                        "amount": int(item["amount"]),
                    }
                    for item in account[direction]
                ]
            income_total = sum(int(item["amount"]) for item in account["income"])
            expense_total = sum(int(item["amount"]) for item in account["expense"])
            account["income_total"] = income_total
            account["expense_total"] = expense_total
            account["net"] = income_total - expense_total
        # 本月入账（上月末结算）：上月末 LLM 推演 + 固定财政 tick 落的 ledger
        # 时序上 state.turn 在结算末尾 +1 进入新月，所以"本月可见的入账"是 cur_turn - 1 的 ledger。
        # 语义对齐玩家直觉："上月末抄家/清丈的钱，算这个月的收入"。
        # 过滤掉固定收支（已在上方"固定收入/固定支出"展示），只列一次性流水
        # （清丈追缴、抄家、赈济临支、亏空压力等 LLM 推演产物）。
        FIXED_CATEGORIES = {
            # 国库固定（category 以 ledger 实际写入值为准）
            "田赋辽饷盐商", "田赋", "辽饷", "盐税", "商税",
            "起运", "太仓亏空",
            "各军军饷", "中央军饷", "边饷hub", "宗室禄米", "百官俸禄", "工部", "赈灾备用",
            # 内库固定
            "皇庄", "织造", "矿税",
            "宫廷开支", "内廷俸禄", "妃嫔供奉",
            # 建筑（每月固定 tick）
            "建筑产出", "建筑维护",
            # 开局初始账册
            "期初",
        }
        cur_turn = int(self.state.turn)
        rows = self.db.reign.read_budget_ledger_rows((cur_turn - 1,))
        for name, account in budget.items():
            movements = [
                {
                    "delta": int(r["delta"]),
                    "balance_after": int(r["balance_after"]),
                    "category": str(r["category"] or ""),
                    "reason": str(r["reason"] or ""),
                }
                for r in rows
                if str(r["account"]) == name
                and str(r["category"] or "") not in FIXED_CATEGORIES
            ]
            account["movements"] = movements
            account["movements_total"] = sum(m["delta"] for m in movements)
        # #1366：结算前只呈现事实——全军名义应发合计，与 army_report 警讯文本共用同一计算，
        # 不与国库拟拨/结算结果混叫一个数字。
        budget["army_pay_due_total"] = self.db.army_pay_theoretical_total()
        # #1366：结算后的 typed 玩家结果；treasury_report 与 Web 共用同一 DB 投影。
        # 核账期（月初快照在场，settling/awaiting_decision）不下发——半程中间态不对皇帝
        # 可见（CONTEXT.md 核账期定义）；待 next_period 完成、快照过期后才见同 turn 结果，
        # 复用与顶栏/余额同一条 _month_open_snapshot 展示边界，不另造第二判定。
        budget["settled_army_pay"] = (
            None if self._month_open_snapshot() is not None
            else self.db.treasury_hub_result(self.state)
        )
        return budget

    def mechanical_tail_pending(self) -> bool:
        from ming_sim.mechanical_tail import _pending_mechanical_tails

        return bool(_pending_mechanical_tails(self.db))

    def mechanical_tail_failure(self) -> Optional[Dict[str, Any]]:
        from ming_sim.mechanical_tail import failed_mechanical_tail

        failure = failed_mechanical_tail(self.db)
        return {"error_pack_path": failure[1].get("error_pack_path"), "error": failure[1].get("error")} if failure else None

    def ending_payload(self) -> Optional[Dict[str, Any]]:
        """结局已触发时返回 {status,label,summary,timeline,summary_pending}，否则 None。

        总评在机械尾后台写完。空总评且尾仍 pending 时 summary_pending 为真，
        前台先开页，完成后重取才能看见；不把尚未写完说成没有总评。
        """
        if not self.state.ended:
            return None
        from ming_sim.context import ENDING_LABELS
        from ming_sim.mechanical_tail import ending_summary_pending
        # The tail saves the summary before marking done: sample pending first.
        summary_pending = ending_summary_pending(self.db, self.state)
        row = self.db.reign.get_ending_summary() or {}
        summary = row.get("summary", "") or ""
        return {
            "status": self.state.ending_status,
            "label": ENDING_LABELS.get(self.state.ending_status, "结局"),
            "summary": summary,
            "timeline": row.get("timeline", []),
            "summary_pending": summary_pending if not summary else False,
        }

    def state_payload(self) -> Dict[str, Any]:
        directives = [self.directive_payload(row) for row in self.directive_rows()]
        cased_directives = self.cased_directive_payloads()
        pending_actions = self.db.dossiers.list_pending_actions(int(self.state.turn))
        visible_non_directive_pending = [
            a for a in pending_actions
            if a["kind"] != "directive" and not (a["kind"] == "secret_order" and a["action"] == "新建")
        ]
        # #1234：快照在且回合匹配 ⇔ 核账展示态；四键经同一投影缝下发。
        snap = self._month_open_snapshot()
        settlement_display = snap is not None
        display_metrics = self._display_metrics()
        # #1625: phase/count/desk/resume form one recovery snapshot under the
        # existing settlement-entry lock. Holding the lock through the desk read
        # keeps a concurrent resolve begin from emptying the desk after this GET
        # already sampled inflight=false (false resume_phase2).
        with _settlement_entry_lock(self):
            turn_phase = self.state.turn_phase
            settlement_entry_inflight = (
                int(getattr(self, "_settlement_entry_inflight", 0) or 0) > 0
            )
            awaiting_decision = turn_phase == TurnPhase.AWAITING_DECISION.value
            pending_decisions = (
                self.session.pending_decisions() if awaiting_decision else []
            )
            deferred_rescripts = self.db.issues.list_rescript_drafts(status="revision_pending")
            durable_phase2_resume = (
                awaiting_decision
                and self.db.resolve_contexts.get(self.state.turn) is not None
                and not pending_decisions
            )
            # One failure projection for night forecasts, settlement and rescript continuation.
            settlement_recovery = None
            from ming_sim.month_chain import month_chain_call_failure
            month_failure = month_chain_call_failure(self.db, int(self.state.turn))
            if month_failure is not None and month_failure.get("step") == "edict_forecast":
                from ming_sim.decree_forecast import failed_decree_forecast
                month_failure = failed_decree_forecast(self.session)
            if turn_phase == TurnPhase.SETTLING.value or month_failure is not None:
                from ming_sim.error_pack import (
                    latest_error_pack_for_turn,
                    _read_complete_pack_manifest,
                    settlement_abort_message,
                )
                if month_failure is not None:
                    # 本次失败记录是诊断包真源；没有本次包就空着，不借同月旧包。
                    settlement_recovery = {
                        "retryable": True,
                        "error_pack_path": str(month_failure.get("error_pack_path") or ""),
                        "message": str(month_failure.get("message") or ""),
                        "stage": str(month_failure.get("step") or ""),
                    }
                else:
                    pack_path = latest_error_pack_for_turn(
                        self.db.path, int(self.state.turn),
                    )
                    manifest = (
                        _read_complete_pack_manifest(Path(pack_path)) if pack_path else None
                    )
                    settlement_recovery = {
                        "retryable": True,
                        "error_pack_path": pack_path or "",
                        "message": (
                            settlement_abort_message(
                                pack_path, reason=str(manifest["exception_message"]),
                            )
                            if manifest is not None
                            else "上月结算未完成（进度已保存）。"
                        ),
                    }
        # #1726：奏疏收件箱与未读数同份 list，禁每请求双跑 list_player_memorials。
        memorials = self.memorial_payloads()
        # #1855 / ADR 0158 决定 7：重开落点由账本状态投影；前端不猜。
        # 序：核账期（含停住，ADR 0149 点即入）→ settlement；夜未收 → audience；其余 → month。
        # 点退朝后收夜前并存窗：快照已立，开夜不得覆盖核账落点。
        reopen_landing = "month"
        from ming_sim.audience_night import get_open_night
        open_night = get_open_night(self.db)
        if settlement_display:
            reopen_landing = "settlement"
        elif open_night is not None:
            reopen_landing = "audience"
        return {
            "turn": {"year": self.state.year, "period": self.state.period,
                     "turn": self.state.turn, "phase": turn_phase,
                     "settlement_display": settlement_display,
                     # #1356：年号纪年投影单真源，前端报头直显，禁第二份 epoch 表
                     "reign_period_label": reign_period_label(
                         self.state.year, self.state.period)},
            "reopen_landing": reopen_landing,
            "metrics": display_metrics,
            "previous_summary": self.previous_summary,
            # #1356：邸报报头年月 ≡ 报文自身月（turn_reports 已存 year/period 投影）；
            # turn.reign_period_label 是当前回合标签，不得混充上月报头。
            "previous_reign_period_label": self.db.previous_turn_reign_period_label(self.state),
            # #1241 SP2：删 state_payload.treasury（零消费残口；判词 r1：treasury_report
            # 留 knowledge/simulation/tools 三缝，不动 settlement_display/budget 投影）。
            "issues": self.issue_payloads(),
            # #1726：奏疏收件箱（与局势 issues 脱钩）；未读数与面板同源。
            "memorials": memorials,
            "unread_memorial_count": sum(1 for m in memorials if m.get("unread")),
            "legacies": self.legacies_payload(),
            "closed_this_turn": self.closed_this_turn_payloads(),
            "budget": self.budget_payload(),
            "region_warning": self.db.region_report(limit=5),
            "army_warning": self.db.army_report(limit=5),
            "power_warning": self.db.power_report(exclude_self=True),
            "powers": self.db.power_payload(),
            "victory_status": self.session.victory(),
            # Sample pending before results, and failure after ending: the modal
            # needs summary_pending or a visible failure, not just global pending.
            "mechanical_tail_pending": self.mechanical_tail_pending(),
            "ending": self.ending_payload(),
            "mechanical_tail_failure": self.mechanical_tail_failure(),
            "events": [],
            "regions": self.db.region_payload(),
            "armies": self.db.army_payload(),
            "map_nodes": self.map_nodes(),
            "ministers": [
                self.public_character(c)
                for c in self.content.characters.values()
                if visible_in_court(c, self.db)
            ],
            "consorts": [
                self.public_character(c)
                for c in self.content.characters.values()
                if c.office_type == "后宫" and c.status == "active" and self.character_power_id(c) == "ming"
            ],
            "talent_pool": [
                # 角标覆盖成「罢居」：offstage 通用 label 是「尚未登场」，对在野前臣读着怪（韩爌曾是首辅）。
                {**self.public_character(c), "status_label": "罢居"}
                for c in self.content.characters.values()
                if in_talent_pool(c, self.db, self.state.year, self.state.period)
            ],
            "directives": directives,
            # #1764：已成案·待盖玺只读投影（0051）；不改 list_directives 过滤语义。
            "cased_directives": cased_directives,
            "pending_count": self.session.pending_count(),
            "pending_directive_count": self.pending_directive_count(pending_actions),
            # #1376：staged 密令候选如实入投影计数（可见性）。
            # #414 默认准行口径不变：确认闸门/落库时序仍走收夜·退朝 commit，
            # 本字段不把候选升成 player-facing secret_orders 行，禁静默漂成恒 0。
            "pending_secret_order_count": sum(
                1 for a in pending_actions
                if a["kind"] == "secret_order"),
            "pending_non_directive_action_count": len(visible_non_directive_pending),
            "pending_decisions": pending_decisions,
            "deferred_rescripts": deferred_rescripts,
            # #657：phase1 已落 decided、desk 只查 pending 为空时，投影 typed 续跑信号。
            # 不把 decided 塞回 pending 列表；前端空 POST 既有 resolve_decisions/stream。
            "resume_phase2": durable_phase2_resume and not settlement_entry_inflight,
            # #1625：只投影进程内既有入口计数；供刷新/重拉区分在飞与真暂停。
            "settlement_entry_inflight": settlement_entry_inflight,
            # #1846：settling 恢复面（message + error_pack_path）
            "settlement_recovery": settlement_recovery,
            "last_decree": self.last_decree,
            "last_report": self.last_report,
            # #671：上一已完成月王承恩独立递话（与 last_report 同级 typed 字段）
            "last_attendant_message": self.db.previous_turn_attendant_message(self.state),
        }

    # ── 聊天 ──────────────────────────────────────────────────────────────
    def chat_projection(self) -> List[Dict[str, Any]]:
        """当前召对夜的殿上投影。"""
        from ming_sim.audience_night import get_open_night, SCENE_CHAT_SPEAKER
        night = get_open_night(self.db)
        return self.db.build_chat_projection(
            SCENE_CHAT_SPEAKER, int(night["id"]) if night else 0,
        )

    def can_undo_last_chat(self, minister_name: str) -> bool:
        """#1902 J3：资格在会话共核；Web 只转发。"""
        return bool(self.session.can_undo_last_audience_chat(minister_name))

    def _start_chat_turn(
        self, minister_name: str, *, message: str = "",
    ) -> tuple[int, Dict[str, Any]]:
        """#1902：建轮与落问话已下沉会话层（与 CLI 共核），此处只回兼容二元组。

        走 ``GameSession.begin_audience_chat_turn`` 的未绑定真方法（而非
        ``self.session.begin_...``）：召对话轮生命周期是共核，测试壳只替 LLM 缝，
        不必各自再抄一份建轮（#13 禁测试自建被测行为）。
        模型会话身份／前像水位由会话核在真实夜确定后提供，入口不再拼名取水位。
        """
        del minister_name
        turn = GameSession.begin_audience_chat_turn(
            self.session, message,
        )
        return turn.chat_turn_id, turn.before_snapshot

    def _fail_chat_turn_and_reload(
        self, chat_turn_id: int, before_snapshot: Dict[str, Any],
        error: Optional[BaseException] = None,
    ) -> None:
        """召对中断/失败的统一善后：终态化本轮 + 重载召对历史缓存。

        所有「已建 chat_turn 但本轮未能正常完成」的路径都必须调用——否则留下 status=active 且
        minister_message_id 为空的孤儿轮，共核在飞资格会把本夜永久判为「上一轮
        仍在进行」而拒收后续问话（cmr Gate2 F-B）。chat_turn_id=0（无持久轮）时为 no-op。

        #1902：回滚与失败终态已下沉会话层（``GameSession.fail_audience_chat_turn``，
        与 CLI 共核）；此处只做 Web 呈现面的历史缓存重载。
        Scene abandon/drain 由调用方在 write_gate 外先完成（C9/T1/T10）。
        """
        if not chat_turn_id:
            return
        GameSession.fail_audience_chat_turn(
            self.session,
            AudienceChatTurn(
                chat_turn_id=int(chat_turn_id),
                accepted_turn=int(self.state.turn),
                night_id=0,
                before_snapshot=before_snapshot,
                user_message_id=0,
            ),
            error=error,
        )
        self.chat_history = {name: [] for name in self.session.content.characters}
        for name, msgs in self.db.chat_messages.history_by_minister().items():
            self.chat_history.setdefault(name, []).extend(msgs)

    def undo_last_chat(self, minister_name: str, *, gate_held: bool = False) -> Dict[str, Any]:
        """#1902 J3：撤回业务在会话共核；此处只映射 HTTP 与呈现。

        #1902 K1：不保留殿上→具名大臣转交的呈现分流；轮归属即请求名。
        """
        from ming_sim.session import AudienceChatUndoError

        try:
            core = self.session.undo_last_audience_chat(
                minister_name,
                gate_held=gate_held,
                write_queue=self._runtime_write_queue(),
            )
        except AudienceChatUndoError as exc:
            status = 404 if exc.code == "not_found" else 409
            raise HTTPException(status_code=status, detail=exc.detail) from None

        # Web 呈现缓存：历史投影依赖 chat_history。
        self.chat_history = {name: [] for name in self.session.content.characters}
        for name, msgs in self.db.chat_messages.history_by_minister().items():
            self.chat_history.setdefault(name, []).extend(msgs)
        present = core.minister_name
        return {
            "minister": present,
            "campaign_id": core.campaign_id,
            "night_id": int(core.night_id),
            "undone_chat_turn_id": int(core.undone_chat_turn_id),
            # #499 同一 turn-identified 投影：撤回后剩余轮的读心仍按轮归位
            "history": self.chat_projection(),
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "pending_directive_count": self.pending_directive_count(),
            "secret_orders": project_secret_orders_for_player(self.db.character_knowledge.list_secret_orders()),
            "can_undo_last_chat": self.can_undo_last_chat(present),
        }

    def _chat_payload(
        self,
        minister_name: str,
        answer: str,
        court_action: str = "",
        chat_turn_id: int = 0,
        accepted_turn: Optional[int] = None,
        before_snapshot: Optional[Dict[str, Any]] = None,
        persisted_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if minister_name != "殿上":
            self.session._character(minister_name)  # 未建档即响亮失败（LLMContractError）
        # Durable chat_turn message ids first, then memory history.  Publishing
        # history before append/update opens a race: observers see the minister
        # reply while can_undo_last_chat_turn is still false (#976 hold path
        # lengthens append_chat_message; background stream + early assert flaked
        # and tore down the shared DB under the worker → SIGSEGV).
        # #1902 F2／T4：落回话经会话层共核；retry 共核已落库时传 persisted_message_id，
        # 本入口只做呈现投影。转译由调用方在闸外安排。
        turn = int(self.state.turn if accepted_turn is None else accepted_turn)
        if persisted_message_id is not None:
            minister_message_id = int(persisted_message_id or 0)
        else:
            minister_message_id = GameSession.complete_audience_chat_turn(
                self.session,
                AudienceChatTurn(
                    chat_turn_id=int(chat_turn_id or 0),
                    accepted_turn=turn,
                    night_id=0,
                    before_snapshot=before_snapshot or {},
                    user_message_id=0,
                ),
                minister_name,
                answer,
            )
        self.chat_history.setdefault(minister_name, []).append({"role": "minister", "content": answer})
        from ming_sim.audience_night import get_open_night
        open_night = get_open_night(self.db)
        return {
            "minister": minister_name,
            "answer": answer,
            # Persisted identity travels with the real player response; the web client
            # never infers night ownership from cross-night personal chat history.
            "campaign_id": str(self.db.reign.kv_get("campaign_id") or ""),
            "night_id": int(open_night["id"]) if open_night else 0,
            # #499 单一投影：user/minister 带 chat_turn_id、既存读心记录按轮归位；
            # 前端 setChat 不再抹掉历史读心记录。
            "history": self.chat_projection(),
            "chat_turn_id": int(chat_turn_id or 0),
            # #544：供高亮判官落库锚定（非流式折窗 / 流式补挂）
            "minister_message_id": int(minister_message_id or 0),
            "court_action": court_action,
            # #1902 T6：旧 result 投影字段无场景产者，已随死契约清退。
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            # #1716：done 载荷同步 pending_directive_count——onDone 直接落 UI，不单靠 refresh 竞态。
            "pending_directive_count": self.pending_directive_count(),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
        }


    def reply_retries(self, minister_name: str) -> List[Dict[str, Any]]:
        """#1902 L1：中断 + 尾随失败取数在会话共核；入口只转发。

        请求名仅供 HTTP 面；殿上夜筛与相位选择不在 Web 自办。
        """
        del minister_name
        return self.session.pending_audience_recovery_retries()

    def _resume_post_reply(self, minister_name: str, target: Dict[str, Any]) -> Dict[str, Any]:
        """#1902 L1：尾随恢复编排在会话共核；此处只映射 HTTP／呈现／高亮钩。"""
        from ming_sim.session import PostReplyRecoveryError

        try:
            core = self.session.resume_post_reply_recovery(
                target,
                write_gate=self._runtime_write_gate(),
                after_reply=lambda item: self._trail_highlight_judge_after_reply(
                    str(item.get("answer") or ""),
                    message_id=int(item.get("minister_message_id") or 0),
                    chat_turn_id=int(item.get("chat_turn_id") or 0),
                ),
            )
        except PostReplyRecoveryError as exc:
            status = 404 if exc.code == "not_found" else 409
            raise HTTPException(status_code=status, detail=exc.detail) from None
        return {
            "answer": str(core["answer"]), "chat_turn_id": int(core["chat_turn_id"]),
            "history": self.chat_projection(),
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "pending_directive_count": self.pending_directive_count(),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
        }

    def retry_interrupted_reply(self, minister_name: str, target_chat_turn_id: Optional[int] = None) -> Dict[str, Any]:
        """恢复指定中断轮，或续接已落回话的尾随阶段；旧调用默认最新中断轮。

        复用既有 chat_turn 与已持久问话——**绝不再落问话**（对话记录无重复句，AC3）。成功即回话
        落库、轮 generating→active；重试再失败则翻回 interrupted 保持可再重试。无待重试轮 → 响亮 404。"""
        retries = self.reply_retries(minister_name)
        if not retries:
            raise HTTPException(status_code=404, detail=f"{minister_name}没有待重试的回话。")
        target = (next((r for r in retries if int(r["chat_turn_id"]) == target_chat_turn_id), None)
                  if target_chat_turn_id else next((r for r in reversed(retries) if not r.get("recovery_phase")), None))
        if target is None:
            raise HTTPException(status_code=404, detail=f"{minister_name}没有该轮待重试回话。")
        if target["minister_name"] != minister_name:
            result = self.retry_interrupted_reply(str(target["minister_name"]), int(target["chat_turn_id"]))
            result["history"] = self.chat_projection()
            result["can_undo_last_chat"] = self.can_undo_last_chat(minister_name)
            return result
        if target.get("recovery_phase"):
            return self._resume_post_reply(minister_name, target)
        chat_turn_id = int(target["chat_turn_id"])
        question = str(target["question"])
        accepted_turn = int(target["turn"])
        # 与非流式 chat 同形：整轮票据覆盖 LLM 无锁窗 + epilogue，防 barrier/drain 当空闲关连接。
        pending_ticket = self._mark_pending_write()
        if pending_ticket is None:
            raise HTTPException(
                status_code=503,
                detail="当前会话正在关闭，请回菜单重新进入。",
            )
        # #1353 r10：屏障已受理则拒重试召对；否则整轮 DB 缝经 ticketed gate。
        # 失败清理在票可能已 complete 后走裸 runtime gate。宿主屏障资源留入口。
        if self._runtime_write_queue().has_open_barrier():
            self._complete_pending_write(pending_ticket)
            raise HTTPException(
                status_code=409,
                detail="本夜收夜中，暂不能召对。",
            )
        gate = self._ticketed_write_gate(pending_ticket)
        # 票可能已 complete 后的失败收口必须走裸 runtime gate（与旧 cleanup_gate 同缝）。
        cleanup_gate = self._runtime_write_gate()
        # #1902 T4：reopen→快照→生成→落回话／失败收口走会话共核；此处只做票据、写闸、投影。
        # 收夜须在放行 pending write 之后，成功后再调共核调度。
        # #1902：相位／收夜／在飞业务资格在 execute_interrupted_reply_retry 共核，入口不持副本。
        from ming_sim.session import AudienceChatAdmissionError
        turn = None
        result = None
        translation_scheduled = False
        try:
            try:
                retry_outcome = self.session.execute_interrupted_reply_retry(
                    chat_turn_id=chat_turn_id,
                    question=question,
                    message_speaker=minister_name,
                    accepted_turn=accepted_turn,
                    user_message_id=int(target.get("user_message_id") or 0),
                    stream_emit=lambda _delta, **_kwargs: None,
                    write_gate=gate,
                )
            except AudienceChatAdmissionError as exc:
                raise HTTPException(status_code=409, detail=exc.detail) from None
            if retry_outcome is None:
                raise HTTPException(
                    status_code=409, detail=f"{minister_name}上一轮回奏仍在进行，请稍候再问。",
                )
            turn, result, minister_message_id = retry_outcome
            try:
                payload = self._chat_payload(
                    minister_name, result.answer,
                    court_action=result.court_action,
                    chat_turn_id=chat_turn_id,
                    accepted_turn=accepted_turn,
                    before_snapshot=turn.before_snapshot,
                    persisted_message_id=minister_message_id,
                )
                # #1842：回话落定后起后台转译（ADR 0155 / 0036）。
                result._admitted_write_ticket = pending_ticket
                self.session.schedule_pending_scene_translation(result)
                translation_scheduled = True
                answer_text = str(getattr(result, "answer", "") or "")
                message_id = int(payload.get("minister_message_id") or 0)
                # #1842：旧读心/抽取/判官退役；放行整轮票后高亮仍可跑。
                if chat_turn_id and answer_text:
                    self._complete_pending_write(pending_ticket)
                    pending_ticket = None
                if message_id and answer_text:
                    # #544：重试非流式同折窗封顶（自领 turn 票，无裸写）
                    self._trail_highlight_judge_after_reply(
                        answer_text,
                        message_id=message_id,
                        chat_turn_id=chat_turn_id,
                    )
                    payload["history"] = self.chat_projection()
                # #1353：若无尾随仍须放行整轮票后再收夜。
                if pending_ticket is not None:
                    self._complete_pending_write(pending_ticket)
                    pending_ticket = None
                court_action = getattr(result, "court_action", "") or ""
                # 宿主票已放行：收夜走共核调度 + runtime gate（非 ticketed）。
                self.session.schedule_close_night_after_chat_if_needed(
                    court_action, write_gate=cleanup_gate,
                )
                return payload
            except Exception as error:
                # 投影／转译调度失败：共核已落回话时仍须 fail 收口；票可能已 complete，
                # 故用 runtime gate，不得再持 ticketed gate。
                try:
                    with cleanup_gate:
                        GameSession.fail_audience_chat_turn(
                            self.session,
                            turn if turn is not None else AudienceChatTurn(
                                chat_turn_id=chat_turn_id,
                                accepted_turn=accepted_turn,
                                night_id=0,
                                before_snapshot={},
                                user_message_id=int(target.get("user_message_id") or 0),
                            ),
                            replied=result is not None,
                            error=error,
                            translation_dispatched=translation_scheduled,
                            court_action=str(getattr(result, "court_action", "") or ""),
                        )
                except Exception as _caught_failure:
                    logger.exception(
                        "retry adapter cleanup: fail_audience_chat_turn failed chat_turn_id=%s error=%s",
                        chat_turn_id,
                        _caught_failure,
                    )
                raise
        finally:
            self._complete_pending_write(pending_ticket)

    def _scene_chat_stream_payload(
        self,
        minister_name: str,
        text: str,
        chat_turn_id: int,
        before_snapshot: Dict[str, Any],
        accepted_turn: int,
        emit_delta,
        write_gate: Optional[threading.Lock] = None,
        admitted_ticket: Optional[WriteTicket] = None,
        on_protagonist_changed=None,
    ) -> Dict[str, Any]:
        """#1842：流式殿上入口——scene_chat + transport 流式，保 SSE/重试/失败路径。

        不跑旧分类器 / 故事抽取 / 边事件判官 / 代码触发读心；转译由 scene_chat 后台承接。
        """
        emitted = {"n": 0}

        def _emit(delta: str, replace: bool = False) -> None:
            if delta:
                emitted["n"] += 1
            # 生产 emit_delta 契约含 replace；夹具须同形，禁签名探测降级。
            emit_delta(delta, replace=replace)

        result = self.session.scene_chat(
            text,
            chat_turn_id=int(chat_turn_id or 0),
            stream_emit=_emit,
            on_protagonist_changed=on_protagonist_changed,
        )
        answer = str(getattr(result, "answer", "") or "")
        # 非流式 agent 回整段时 transport 可能未分片 emit——补一次 delta 保 SSE 契约。
        if answer and emitted["n"] == 0:
            _emit(answer)
        cm = write_gate if write_gate is not None else contextlib.nullcontext()
        with cm:
            with atomic(self.db):
                payload = self._chat_payload(
                    minister_name,
                    answer,
                    court_action=getattr(result, "court_action", "") or "",
                    chat_turn_id=chat_turn_id,
                    accepted_turn=accepted_turn,
                    # #1902 F2：回滚差异由共核方法随落回话一起记，调用方不再另记一份。
                    before_snapshot=before_snapshot,
                )
        # #1842：回话落定后起后台转译（ADR 0155 / 0036）。
        result._admitted_write_ticket = admitted_ticket
        self.session.schedule_pending_scene_translation(result)
        attempts = getattr(result, "transport_attempts", None)
        if attempts:
            payload["transport_attempts"] = attempts
        return payload


    def _trail_highlight_judge_after_reply(
        self,
        minister_reply: str,
        *,
        message_id: int,
        chat_turn_id: int = 0,
        timeout_s: float = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
        pending_ticket: Optional[WriteTicket] = None,
    ) -> List[str]:
        """#544 / ADR 0045：回话完成后同通道高亮判官。超时/坏输出 → []，落库短语。

        判官实际调用故障原样上抛（不在此转空成功）；写库经票据 seam。
        匹配/剥离在前端，此处只存短语。无票且 seal → 零 LLM 零写。
        #1353：spawn 路票据由 spawner finally 归还；本腿只消费交接票。直接调用无票时自领自还。
        """
        own_ticket = False
        mid = int(message_id or 0)
        reply = str(minister_reply or "")
        if mid <= 0 or not reply.strip():
            return []
        # 未由调用方领票 → 本腿自领 turn key 票（生产写必经 seam）。
        if pending_ticket is None and int(chat_turn_id or 0) > 0:
            pending_ticket = self._mark_pending_write(
                key=("turn", int(chat_turn_id)),
            )
            own_ticket = pending_ticket is not None
        if pending_ticket is None:
            # seal/拒票：禁无票裸写/裸跑 LLM
            return []
        try:
            if pending_ticket is not None and (
                pending_ticket.cancelled or pending_ticket._done
            ):
                return []
            phrases = list(run_highlight_judge(
                minister_reply=reply,
                llm_config=getattr(self.session, "llm_config", None),
                timeout_s=timeout_s,
            ) or [])
            try:
                with self._ticketed_write_gate(pending_ticket):
                    self.db.chat_messages.set_highlights(mid, phrases)
            except TicketCancelled:
                return []
            return phrases
        finally:
            # 仅自领票由本腿收口；spawn 交接票由 spawner 归还。
            if own_ticket:
                self._complete_pending_write(pending_ticket)

    def _spawn_pending_write_thread(
        self, target: Any, args: tuple, name: str,
        *,
        ticket_key: Optional[Any] = None,
    ) -> Optional[threading.Thread]:
        """起跑领票 → try 调任意 callee → finally 归还（#1353：生命周期单真源在 spawner）。

        包住 stub/异常/早退——callee 不得再负责交接票归还（腿内归还副本已删）。
        `Thread.start()` 抛异常时补偿 complete 再上抛，绝不泄漏票据致 barrier/drain 永阻。
        队列 seal 则不起、返 None（调用方不得另开无票旁路）。
        返回 Thread 供 stream join 收 SSE；非 stream 可忽略。
        """
        ticket = self._mark_pending_write(key=ticket_key)
        if ticket is None:
            return None

        def _runner() -> None:
            try:
                target(*args, pending_ticket=ticket)
            finally:
                self._complete_pending_write(ticket)

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=name,
        )
        try:
            thread.start()
        except Exception:
            self._complete_pending_write(ticket)
            raise
        return thread

    def _run_startup_extraction_catch_up(
        self,
        *,
        pending_ticket: Optional[WriteTicket] = None,
    ) -> None:
        """Web 宿主适配：持票据闸调用会话共核启动补跑（#1902 T4）。

        生命周期真源 ``GameSession.run_startup_translation_catch_up``；本方法只办
        票据写闸。spawn 路票据由 ``_spawn_pending_write_thread`` finally 归还，
        callee 不重复收口。
        """
        if pending_ticket is None:
            return
        if pending_ticket.cancelled or pending_ticket._done:
            return
        try:
            self.session.run_startup_translation_catch_up(
                write_gate=self._ticketed_write_gate(pending_ticket),
                write_queue=self._runtime_write_queue(),
            )
        except TicketCancelled:
            return

    def _spawn_startup_extraction_catch_up(self) -> None:
        """Web 宿主适配：后台线程发起启动补跑（不阻塞存档加载）。

        待补判定走会话共核 ``list_startup_translation_catch_up``；有待补才领票 spawn。
        #1353：空 catch-up 不占票；预检短持 runtime gate（共享 conn 禁裸读）。

        """
        with self._runtime_write_gate():
            pending = self.session.list_startup_translation_catch_up()
        if not pending:
            return
        self._spawn_pending_write_thread(
            self._run_startup_extraction_catch_up,
            (),
            "audience-startup-extraction-catchup",
            ticket_key=("startup",),
        )


    def pending_translation_retries(
        self, *, night_id: Optional[int] = None, chat_turn_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """#1842：转译待补投影；会话共核持真源，入口只注入写队列。"""
        return self.session.list_pending_translation_retries(
            night_id=night_id, chat_turn_id=chat_turn_id,
            write_queue=self._runtime_write_queue(),
        )

    def retry_pending_translation(self, chat_turn_id: int) -> Dict[str, Any]:
        """#1842/#1902 M1：指定源轮转译恢复；业务在会话共核，此处只映射 HTTP。"""
        from ming_sim.session import TranslationRetryError

        try:
            return self.session.retry_pending_translation(
                int(chat_turn_id),
                write_gate=self._runtime_write_gate(),
                write_queue=self._runtime_write_queue(),
            )
        except TranslationRetryError as exc:
            status = {"invalid": 400, "not_found": 404, "settling": 409}.get(
                exc.code, 409,
            )
            raise HTTPException(status_code=status, detail=exc.detail) from None

    def chat_stream(self, minister_name: str, message: str) -> Iterator[Dict[str, Any]]:
        # #1849 reopen：召对只剩殿上一个入口；按大臣/密令/场外路由整条删除。
        from ming_sim.audience_night import SCENE_CHAT_SPEAKER
        if minister_name != SCENE_CHAT_SPEAKER:
            yield {"type": "error", "message": "召对只从殿上入口进行。"}
            return
        # Free emperor prose: empty-check without mutating carried body (P6).
        text = str(message or "")
        if not text.strip():
            yield {"type": "error", "message": "问话不能为空。"}
            return
        # 整轮（含转译与高亮尾随）共用一次队列票据——关闭/fixture 必须等其完成。
        pending_ticket = self._mark_pending_write()
        if pending_ticket is None:
            yield {"type": "error", "message": "当前会话正在关闭，请回菜单重新进入。"}
            return
        # #1353 r10：屏障已受理则拒后序流式聊天（与 seal 合流）；否则 prologue/epilogue
        # 经 ticketed gate（写段序）。LLM 仍在无锁窗（AC10）。宿主屏障资源留入口。
        if self._runtime_write_queue().has_open_barrier():
            self._complete_pending_write(pending_ticket)
            yield {
                "type": "error",
                "message": "本夜收夜中，暂不能召对。",
                "code": "night_closing",
            }
            return
        write_gate = self._ticketed_write_gate(pending_ticket)
        bare_write_gate = self._runtime_write_gate()
        chat_turn_id = 0
        before_snapshot: Dict[str, Any] = {}
        accepted_turn = 0
        # #498 AC10：prologue 持锁写库后立刻释放，LLM 不持 write_gate——
        # 颁诏入口可并发观测 generating 并有界超时 fail-closed，不被挂起回话永久挡死。
        # #542 r6g：Lock.locked() 不记 owner——本路径自记是否仍持 gate，只放自己的锁。
        gate_held = True
        try:
            write_gate.acquire()
        except TicketCancelled:
            self._complete_pending_write(pending_ticket)
            yield {"type": "error", "message": "当前会话正在关闭，请回菜单重新进入。"}
            return
        from ming_sim.session import AudienceChatAdmissionError
        try:
            accepted_turn = int(self.state.turn)
            # #1902：建轮（含相位／收夜／在飞业务资格）与问话落库同走会话层共核；
            # 入口只更呈现缓存，不持业务权威副本。
            chat_turn_id, before_snapshot = self._start_chat_turn(
                minister_name, message=text,
            )
            self.chat_history.setdefault(minister_name, []).append({"role": "user", "content": text})
        except AudienceChatAdmissionError as err:
            if gate_held:
                try:
                    write_gate.release()
                except RuntimeError:
                    pass
                gate_held = False
            self._complete_pending_write(pending_ticket)
            out: Dict[str, Any] = {"type": "error", "message": err.detail}
            if err.code == "night_closing":
                out["code"] = "night_closing"
            yield out
            return
        except Exception as error:
            # Release gate before scene drain — prologue may have already started futures.
            if gate_held:
                try:
                    write_gate.release()
                except RuntimeError as release_error:
                    logger.exception(
                        "stream prologue gate release failed error=%s",
                        release_error,
                    )
                gate_held = False
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；abandon / 终态写分 try，
            # 清理异常不覆盖原始错误、不阻断终态上抛。
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot, error)
            except Exception as _caught_failure:
                logger.exception(
                    "stream prologue cleanup: fail_chat_turn/reload failed chat_turn_id=%s error=%s",
                    chat_turn_id,
                    _caught_failure,
                )
            self._complete_pending_write(pending_ticket)
            raise
        finally:
            if gate_held:
                write_gate.release()

        ev_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        identity = {
            "campaign_id": "",
            "night_id": 0,
            "chat_turn_id": int(chat_turn_id or 0),
        }
        # Identity setup is still between durable prologue and worker ownership. Any failure
        # must close the durable turn and pending owner through the same terminal path as a
        # worker failure, rather than escaping this SSE generator.
        try:
            identity["campaign_id"] = str(self.db.reign.kv_get("campaign_id") or "")
            if chat_turn_id:
                from ming_sim.audience_night import get_open_night
                open_night = get_open_night(self.db)
                identity["night_id"] = int(open_night["id"]) if open_night else 0
                ev_queue.put({"type": "accepted", **identity})
        except Exception as error:  # noqa: BLE001
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；原始 error 仍下发。
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot, error)
            except Exception as _caught_failure:
                logger.exception(
                    "stream identity cleanup: fail_chat_turn/reload failed chat_turn_id=%s error=%s",
                    chat_turn_id,
                    _caught_failure,
                )
            self._complete_pending_write(pending_ticket)
            yield {"type": "error", **_exception_detail(error), **identity}
            return

        def emit_delta(delta: str, *, replace: bool = False) -> None:
            # replace=True：复用既有 delta 事件形态，令客户端重置本轮临时正文后再接
            item: Dict[str, Any] = {"type": "delta", "content": delta}
            if replace:
                item["replace"] = True
            ev_queue.put(item)

        def worker() -> None:
            nonlocal pending_ticket
            payload: Optional[Dict[str, Any]] = None
            court_action = ""
            # #1727：court_break 预领屏障；异常出口也须 complete，禁 has_open_barrier 永真。
            close_barrier_ticket: Optional[WriteTicket] = None
            # #1353 r12：payload 已成 ⇒ done 必先于 error（后处理失败回话已可见）。
            # #1727 把尾随 spawn/屏障领票挪到 done 前，spawn 抛错时须由出口补 done。
            reply_done_emitted = False
            try:
                try:
                    # #1849 reopen：殿上唯一入口 → scene_chat transport。
                    # SSE 契约保持 accepted/delta/done/end。
                    payload = self._scene_chat_stream_payload(
                        minister_name, text, chat_turn_id, before_snapshot,
                        accepted_turn, emit_delta,
                        write_gate=write_gate,
                        admitted_ticket=pending_ticket,
                        on_protagonist_changed=lambda: ev_queue.put({"type": "protagonist_changed"}),
                    )

                    answer = str((payload or {}).get("answer") or "")
                    message_id = int((payload or {}).get("minister_message_id") or 0)
                    court_action = str((payload or {}).get("court_action") or "")
                    # #1353：高亮仍经 _spawn_pending_write_thread；旧抽取/读心退役。
                    turn_key = ("turn", int(chat_turn_id)) if chat_turn_id else None
                    highlight_thread: Optional[threading.Thread] = None
                    highlight_box: List[str] = []
                    # 仅高亮 join 路收故障；共享 spawner 不吞，startup 等无 join 仍走线程未捕获出口。
                    highlight_errors: List[BaseException] = []
                    # #1727：court_break 预领屏障票——须在尾随领票之后、done 之前。

                    if chat_turn_id and answer:
                        if message_id and answer:
                            def _highlight_worker(
                                reply: str,
                                mid: int,
                                ctid: int,
                                *,
                                pending_ticket: Optional[WriteTicket] = None,
                            ) -> None:
                                try:
                                    highlight_box.extend(
                                        self._trail_highlight_judge_after_reply(
                                            reply,
                                            message_id=mid,
                                            chat_turn_id=ctid,
                                            pending_ticket=pending_ticket,
                                        ) or []
                                    )
                                except BaseException as exc:
                                    highlight_errors.append(exc)

                            highlight_thread = self._spawn_pending_write_thread(
                                _highlight_worker,
                                (answer, message_id, chat_turn_id),
                                "audience-p5-highlight",
                                ticket_key=turn_key,
                            )
                        # 整轮票在尾随已领票后放行——屏障盯尾随票。
                        self._complete_pending_write(pending_ticket)
                        pending_ticket = None

                    if court_action == "court_break":
                        # 无尾随时也须放行整轮票，再领屏障（禁自等待）。
                        if pending_ticket is not None:
                            self._complete_pending_write(pending_ticket)
                            pending_ticket = None
                        close_barrier_ticket = self._runtime_write_queue().claim_barrier()

                    # P5：先 done（回话可见），再 join 尾随 / 收夜 / end。
                    # #1727：court_break 时 done 前已领屏障，召对写入口不再全活。
                    ev_queue.put({"type": "done", "payload": payload or {}})
                    reply_done_emitted = True

                    # #544：流式不挡流——done 后补挂高亮（超时封顶）；有清单才发事件。
                    # 高亮实际异常交还本 worker 统一失败出口（error→end），不洗成成功。
                    if highlight_thread is not None:
                        highlight_thread.join()
                    if highlight_box:
                        ev_queue.put({
                            "type": "highlights",
                            "highlights": list(highlight_box),
                            "chat_turn_id": chat_turn_id,
                            "message_id": message_id,
                        })

                    # #526/#1353：尾随票已清后收夜。整轮票已 complete 时 ticketed gate 会
                    # TicketCancelled——收夜短写改走裸 runtime write_gate（腿已终态，无越屏障窗）。
                    # #1727：预领屏障票交给 close 复用（barrier），禁再领第二张。
                    # 交接后归还真源在 close／barrier；本 worker 仅未交接早退才 complete。
                    # #1902 N4：GameSession 恒有 close_night_after_chat_if_needed；删 getattr 降级。
                    handed_barrier = close_barrier_ticket
                    close_barrier_ticket = None
                    self.session.close_night_after_chat_if_needed(
                        court_action,
                        write_gate=bare_write_gate,
                        barrier_ticket=handed_barrier,
                        night_id=identity["night_id"],
                    )
                    if highlight_errors:
                        raise highlight_errors[0]

                    ev_queue.put({"type": "end"})
                except Exception as error:  # noqa: BLE001
                    # #1353 r12/r13：worker 单一异常出口——payload / 后处理 / 收夜任一失败
                    # 皆 error→end；禁逐点补丁，禁只走 finally 致消费者永阻。
                    # 回话是否已落以持久轮为准；payload 仍可能在落库后的调度窗为空。
                    # #1727：done 前尾随/屏障步失败时，此处补 done，保「回话已可见」再 error。
                    # ADR 0005 / #1408：清理二次失败 logger.exception 记 traceback 不宽吞；
                    # abandon / 终态写分 try；清理异常不覆盖原始 error、不阻断 error→end。
                    # Scene drain stays outside write_gate (C9/T1/T10).
                    if payload is not None and not reply_done_emitted:
                        ev_queue.put({"type": "done", "payload": payload or {}})
                        reply_done_emitted = True
                    reply_persisted = False
                    try:
                        if chat_turn_id:
                            with bare_write_gate:
                                reply_persisted = GameSession.fail_audience_chat_turn(
                                    self.session,
                                    AudienceChatTurn(
                                        chat_turn_id=int(chat_turn_id),
                                        accepted_turn=int(accepted_turn or self.state.turn),
                                        night_id=0,
                                        before_snapshot=before_snapshot,
                                        user_message_id=0,
                                    ),
                                    replied=payload is not None or reply_done_emitted,
                                    error=error,
                                    translation_dispatched=payload is not None,
                                    court_action=court_action,
                                )
                    except Exception as _caught_failure:
                        logger.exception(
                            "stream worker cleanup: fail_chat_turn/reload failed chat_turn_id=%s error=%s",
                            chat_turn_id,
                            _caught_failure,
                        )
                        # 收口自身失败：不删问话/回话（无法证明未落），但本轮没有可交付的 payload。
                        reply_persisted = True
                        if payload is None:
                            emit_delta("", replace=True)
                    if payload is None and not reply_persisted:
                        try:
                            with write_gate:
                                self.chat_history = {
                                    name: [] for name in self.session.content.characters
                                }
                                for name, msgs in self.db.chat_messages.history_by_minister().items():
                                    self.chat_history.setdefault(name, []).extend(msgs)
                        except Exception as _caught_failure:
                            logger.exception(
                                "stream worker cleanup: fail_chat_turn/reload failed chat_turn_id=%s error=%s",
                                chat_turn_id,
                                _caught_failure,
                            )
                        # #1465 ④：回话未成终失败 — 与重试起手同形无条件 replace，再 error
                        # （禁「只 put error 不 replace」；客户端已处理空 replace）
                        emit_delta("", replace=True)
                    if isinstance(error, LLMUnavailable):
                        ev_queue.put({
                            "type": "error",
                            "detail": _exception_detail(error),
                            **identity,
                        })
                    else:
                        ev_queue.put({
                            "type": "error",
                            **_exception_detail(error),
                            **identity,
                        })
                    ev_queue.put({"type": "end"})
            finally:
                if close_barrier_ticket is not None:
                    self._runtime_write_queue().complete(close_barrier_ticket)
                    close_barrier_ticket = None
                self._complete_pending_write(pending_ticket)

        thread = threading.Thread(target=worker, daemon=True)
        try:
            thread.start()
        except Exception as error:
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；原始异常仍上抛。
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot, error)
            except Exception as _caught_failure:
                logger.exception(
                    "stream start cleanup: fail_chat_turn/reload failed chat_turn_id=%s error=%s",
                    chat_turn_id,
                    _caught_failure,
                )
            self._complete_pending_write(pending_ticket)
            raise
        while True:
            item = ev_queue.get()
            yield item
            # #1353 r11：只以 end 收束——失败路径先 error 再 end，禁 error 单终态截断。
            if item.get("type") == "end":
                break


def sse_event(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _settlement_player_payload(
    *,
    decree: str = "",
    report: str = "",
    decisions: Optional[List[Dict[str, Any]]] = None,
    advanced: Optional[bool] = None,
) -> Dict[str, Any]:
    """One player-facing seam for every settlement SSE terminal event."""
    payload: Dict[str, Any] = {
        "decree": decree,
        "report": report,
    }
    if decisions is not None:
        payload["decisions"] = decisions
    if advanced is not None:
        payload["advanced"] = advanced
    return payload


def _next_or_none(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _retryable_audience_close_http(exc: BaseException) -> HTTPException:
    """Keep close failures retryable without dropping their cause or diagnostic pointer."""
    from ming_sim.audience_night import AudienceNightError

    if not isinstance(exc, (AudienceNightError, ExceptionGroup)):
        raise TypeError(f"not a retryable audience/close error: {type(exc)!r}")
    return HTTPException(status_code=409, detail=_exception_detail(exc))


def _accept_settlement_period(game) -> bool:
    """#1235 / ADR 0149 点即入：颁布/退朝受理即 capture 月初快照（先于 await/close）。

    无真实 db 的测试替身直接跳过。幂等；FRONT_HALF_DONE 不重写。
    返回 True 仅当本请求真新建快照——调用方失败 exit 时作 gate 阻塞信号
    （创建者 blocking 必清；非创建者 non-blocking + in-flight 归零才可清）。"""
    db = getattr(game, "db", None)
    state = getattr(game, "state", None)
    if db is None or state is None:
        return False
    from ming_sim.month_open_snapshot import accept_settlement_period
    return accept_settlement_period(db, state)


def _settlement_entry_lock(game) -> threading.Lock:
    """#1235 r4：入口 in-flight 计数锁（与 write_gate 分立；gate-free 窗仍计在办）。"""
    lock = getattr(game, "_settlement_entry_lock", None)
    if lock is None:
        lock = threading.Lock()
        setattr(game, "_settlement_entry_lock", lock)
    return lock


def _begin_settlement_entry(game) -> None:
    """#1235 r4：颁布/退朝入口 try 起点登记在办（先于 accept，使并发 B 可见 A）。"""
    lock = _settlement_entry_lock(game)
    with lock:
        n = int(getattr(game, "_settlement_entry_inflight", 0) or 0)
        setattr(game, "_settlement_entry_inflight", n + 1)


def _end_settlement_entry(game) -> None:
    """#1235 r4：入口 finally 销账在办（须在失败 exit 之后，使 exit 仍计本请求）。"""
    lock = _settlement_entry_lock(game)
    with lock:
        n = int(getattr(game, "_settlement_entry_inflight", 0) or 0)
        setattr(game, "_settlement_entry_inflight", max(0, n - 1))


def _settlement_entry_inflight(game) -> int:
    """当前点即入入口在办数（含调用方自身，若已 begin 未 end）。"""
    lock = _settlement_entry_lock(game)
    with lock:
        return int(getattr(game, "_settlement_entry_inflight", 0) or 0)


def _exit_settlement_display_on_failure(game, *, blocking: bool = False) -> None:
    """#1235 / ADR 0149 真失败另形：前半段未提交时清快照，出核账展示态。

    settling/awaiting 保留交恢复（AC3）。无真实 db 替身跳过。
    清快照写必须经 `_write_gate`，禁无门直写共享连接。
    blocking=True（web 创建者）：阻塞 acquire 后必清（r1 D）。
    blocking=False（非创建者/默认）：
      - 其他入口仍在办（in-flight > 1）→ 立即返回（r4：gate-free 窗锁闲≠孤儿，禁代清）；
      - 仅本请求在办且 non-blocking 抢到锁 → 可清 session 再创建孤儿（r3 C）；
      - 撞锁立即返回（r2 持锁防代清）。
    已 begin（in-flight 已登记）后的失败路径须尝试本函数；未 begin 者无快照可退且会破 in-flight 算术，不得调用；created_display 只控 blocking，不再门控是否调用。
    清快照期间持 entry_lock，使并发 begin 不得插在「见 in-flight==1」与 clear 之间。"""
    db = getattr(game, "db", None)
    state = getattr(game, "state", None)
    if db is None or state is None:
        return
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    gate = _game_write_gate(game)
    entry_lock = _settlement_entry_lock(game)
    if blocking:
        gate.acquire()
    elif not gate.acquire(blocking=False):
        return
    try:
        with entry_lock:
            if not blocking and int(getattr(game, "_settlement_entry_inflight", 0) or 0) > 1:
                return
            exit_settlement_display_on_failure(db, state)
    finally:
        gate.release()


def _auto_close_open_night_gate_free(
    game, *, write_gate: Any = None,
) -> None:
    """Close the open audience night outside any outer runtime write gate.

    close_night holds the real runtime lock only for short prepare/finalize writes;
    pending turn translations run with the gate released. Web issue / stream /
    no-edict share this single orchestration (no duplicated close flow).

    #1353：过月屏障票据排在已领票之后——调用方经 queue.barrier 入此函数时，
    前序尾随已空放行/落库；close 内 wait_in_flight 只消费工人终态（K10a）。
    无真实 game.db.conn 的 legacy 替身跳过。
    #1353 fold-in r5：欠账补跑内部静默，不并入过月 SSE。
    #1353 r12：write_gate 可由调用方注入（advance 注入非阻塞短持适配；默认 runtime 闸）。
    # #1902：无 conn legacy 替身跳过已清退；WebGame 恒持真实 GameDB。
    """
    from ming_sim.audience_night import auto_close_open_night

    session = getattr(game, "session", None)
    auto_close_open_night(
        game.db,
        game.state,
        content=getattr(game, "content", None),
        llm_config=getattr(session, "llm_config", None) if session is not None else None,
        write_gate=_game_write_gate(game) if write_gate is None else write_gate,
    )


def _game_write_gate(game) -> threading.Lock:
    if hasattr(game, "_runtime_write_gate"):
        return game._runtime_write_gate()
    return game._write_gate


def _refuse_settling_or_busy_write_phase(game) -> None:
    """#393 Gate2 相位拒——与 `_serialized_web_write` 同文案单源。"""
    state = getattr(game, "state", None)
    phase = getattr(state, "turn_phase", None)
    if phase in FRONT_HALF_DONE_PHASES:
        # #1306：分相位文案——awaiting_decision 是等批红（结算未在跑），settling 才是月末结算中。
        if phase == TurnPhase.AWAITING_DECISION.value:
            raise HTTPException(status_code=409, detail="等待批红，请待批红完成后再操作。")
        raise HTTPException(status_code=409, detail="月末结算进行中，请待结算完成后再操作。")


def _refuse_if_open_night_barrier(game) -> None:
    """#1727：court_break 预领屏障开启期间拒玩家召对写入口。

    复用 #1353 has_open_barrier 唯一真源（经 get_session_write_queue）；
    只挂在召对写入口，不改 `_serialized_web_write` 本体（favorites 等非召对写不属本拒）。
    #1740：禁 hasattr 缺方法早退——真实 WebGame 必有队列；缺接线不得当放行。
    """
    if get_session_write_queue(game).has_open_barrier():
        raise HTTPException(
            status_code=409,
            detail="本夜收夜中，暂不能召对。",
        )


def _acquire_web_write_gate_or_409(gate) -> None:
    """抢会话 write_gate：空闲即持；本闸转译短持则等其释放后再非阻塞重试；否则 409。

    #1842：后台转译只在读写临界短持同一闸；LLM 段不持闸。前台拟旨等入口不得
    因本闸转译短临界随机 409，也不得在结算长写或其它会话转译上挂死——仅当
    holder kind 为转译时等待该闸释放并重试；结算/其它写 → 立即 409。
    holder kind 与 gate 所有权同临界（ClassifiedWriteGate），无旁路入账窗。
    """
    from ming_sim.audience_translation import (
        translation_holding_write_gate,
        wait_translation_write_gate_released,
    )

    while True:
        if gate.acquire(blocking=False):
            return
        if not translation_holding_write_gate(gate):
            raise HTTPException(
                status_code=409,
                detail="月末结算或上一步写入进行中，请稍候再操作。",
            )
        wait_translation_write_gate_released(gate)


def _try_acquire_serialized_web_write_gate(game):
    """非阻塞抢 write_gate；抢不到立即 409（转译短持除外，见上）。返回已持锁的 gate。"""
    gate = _game_write_gate(game)
    _acquire_web_write_gate_or_409(gate)
    return gate


class _NonBlockingWebWriteGate:
    """#1353 r12：同一把 runtime write_gate 的非阻塞短持适配（不是平行闸）。

    advance 路径注入 auto_close/get_open_night 真实 with 接缝：占用即 409，
    禁阻塞等闸（#1842：转译短持与 ``_try_acquire`` 同缝等待后重试）。
    issue/stream 仍传裸 Lock（阻塞 acquire）。
    """

    __slots__ = ("_lock",)

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        del blocking, timeout  # 契约：短持处不挂死在结算长写上
        _acquire_web_write_gate_or_409(self._lock)
        return True

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self) -> "_NonBlockingWebWriteGate":
        self.acquire()
        return self

    def __exit__(self, *args: object) -> bool:
        self.release()
        return False


@contextlib.contextmanager
def _serialized_web_write(game):
    """串行化「绕过会话层、直写 game.db」的 web 端点写入，杜绝它与月末结算原子块 / 后台召对
    worker 在同一无锁连接（check_same_thread=False，db.py:317「单写者、无并发写」）上重叠。

    cmr Gate2 F-A：仅查 turn_phase 不够——pre_settle 在 `atomic_and_reload` 原子块内
    （`_commit_suspended=True`）跑财政 tick/硬立项，**到块尾才落 `turn_phase=SETTLING`**
    （decree.py:942）。相位落定前那段窗口里 phase 检查会放行，写入便骑进结算原子事务，随
    SettlementAbort 回滚（端点返 200 却丢数据，破 ADR0008 全有或全无 + P1）。结算 worker 全程
    持 `_write_gate`，故以「非阻塞抢同一把锁」为权威信号：
      ① 相位拒——AWAITING_DECISION 暂停期 worker 已释放锁、但前半段已落，不许再直写改盘面
         （与 session._refuse_if_settling 同口径）。
      ② 非阻塞抢 `_write_gate`——抢不到=结算 worker 或后台召对 worker 正持锁（含上述 pre_settle
         窗口）→ 立即 409，不在事件循环上阻塞等结算（F1 同因）；抢到则持锁到写完再释放。
    直写 game.db 的端点、以及绕过 _write_gate 的会话写端点（诏稿/拟旨/撤回召对——它们各自的
    session._refuse_if_settling/相位门只查相位、守不住 pre_settle 窗口）都经本 CM 串行；结算入口
    （resolve_turn/submit_decisions）走阻塞版 _game_write_gate（在自己的 worker 线程里持锁）。"""
    _refuse_settling_or_busy_write_phase(game)
    gate = _try_acquire_serialized_web_write_gate(game)
    try:
        yield
    finally:
        gate.release()


@contextlib.contextmanager
def _settlement_period_entry(
    game,
    *,
    write_cm: Callable[[Any], Any],
    hold_write_for_body: bool = True,
):
    """#1241 S1：颁布/退朝/stream 三入口受理样板（begin→accept→await→close→gate）。

    行为零变化硬约束：write_cm **必须**参数化锁获取语义分叉——
      · advance → `_serialized_web_write`（非阻塞抢锁，撞锁/相位拒 409）
      · issue / stream → `_game_write_gate`（阻塞 acquire）
    统一获取语义即破 T2 行为零变化（r2-r7 不变式）。

    #657 resolve/stream：hold_write_for_body=False——展示态仍走本样板，但 body 内
    submit_hitl_choices 自管 ①/③ 短持同一 write_cm（② 无锁 join）；禁整段 gate 盖 join。
    hold_write_for_body=True（默认）= issue/advance 旧形：body 全程持 write_cm。

    #1353 fold-in r5：收夜欠账补跑内部静默；过月 SSE 只由 resolve 本体推正常进度。

    成功路径（with 体正常结束/return）保留展示态；异常路径先 exit 再 end
    （exit 先于 end；created_display 只控 blocking，不门控是否调用 exit）。
    """
    settled_ok = False
    created_display = False
    entered = False
    try:
        # #1235 r4：先登记在办，再 capture——并发 B 在 A gate-free 窗可见 A 仍在办。
        _begin_settlement_entry(game)
        entered = True
        # #1235 / ADR 0149：点即入——先 capture 入核账展示态，再等在飞/收夜/结算续跑。
        created_display = _accept_settlement_period(game)
        # #1353 r12：advance 非阻塞下沉到 auto_close 真实短持接缝（占用即 409）；
        # 删预探即释——探后至 get_open_night 短持之间 TOCTOU 可再阻塞。
        # 相位拒仍在进 barrier 前（避免 settling 窗误收夜）；issue/stream 阻塞等闸。
        if write_cm is _serialized_web_write:
            _refuse_settling_or_busy_write_phase(game)
            close_gate: Any = _NonBlockingWebWriteGate(_game_write_gate(game))
        else:
            close_gate = _game_write_gate(game)

        # #1353：过月=屏障票据（队列内任务）。整轮 chat 票 + 尾随 turn 票清零后
        # 才 gate-free 收夜；屏障只等工人终态/空放行（K10a：无 elapsed 熔断）。
        # #1842：排空、欠账补跑与收夜共用一张 SessionWriteQueue
        # 屏障票；既不在 callback 内再领票自等，也不在收夜前归还留窗。
        sess = getattr(game, "session", None)
        if sess is None:
            raise RuntimeError("settlement entry 缺 session")

        def _close_open_night() -> None:
            _auto_close_open_night_gate_free(
                game, write_gate=close_gate,
            )

        sess.await_translations_before_month(after_drain=_close_open_night)

        def _clear_orphan_success() -> None:
            # #1343/#1378/#1379/#1388：成功回常态后兜底清残留快照。
            # 持 write_cm 同门（与失败支 _game_write_gate 同形）——禁无门直写共享连接。
            db = getattr(game, "db", None)
            state = getattr(game, "state", None)
            if db is not None and state is not None:
                from ming_sim.month_open_snapshot import clear_orphan_month_open_snapshot
                clear_orphan_month_open_snapshot(db, state)

        if hold_write_for_body:
            with write_cm(game):
                yield
                _clear_orphan_success()
                # with 体无异常结束且 clear 已完成（或无需 clear）→ 成功。
                settled_ok = True
        else:
            # #657：body 自管 write_cm 分段；成功后短持 clear。
            yield
            with write_cm(game):
                _clear_orphan_success()
            settled_ok = True
    finally:
        # 嵌套 try/finally：exit/clear 抛错仍须销账 inflight（验收：clear 抛 → inflight 归零）。
        try:
            if entered and not settled_ok:
                # 含 gate/HTTPException 拒收与未映射异常；blocking 由 web 创建位决定。
                # exit 须在 end 之前：非创建者凭 in-flight>1 识别他者仍在办（r4）。
                # advance 走 _serialized_web_write（非阻塞 409 契约）：失败清快照也不得
                # 阻塞等闸——否则「他方持闸 → 本路 409 → exit blocking 等同一闸」自锁死。
                exit_blocking = bool(
                    created_display and write_cm is not _serialized_web_write
                )
                _exit_settlement_display_on_failure(game, blocking=exit_blocking)
        finally:
            if entered:
                _end_settlement_entry(game)


def _active_db_path_file() -> str:
    """主库路径的真源文件（#396 new_game 切换主库路径用）。"""
    return user_data_path("active_db.txt")


def _read_active_db_path() -> str:
    """读 active_db.txt。文件不存在 → 空串；读失败响亮上抛（ADR 0005），禁静默退 env/default。"""
    active_file = _active_db_path_file()
    if not os.path.exists(active_file):
        return ""
    try:
        with open(active_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as _caught_failure:
        logger.exception(
            "read active_db path failed path=%s error=%s",
            active_file,
            _caught_failure,
        )
        raise


def _atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_file = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_file, path)
    finally:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception as _caught_failure:
                logger.exception(
                    "cleanup atomic write tmp failed path=%s error=%s",
                    tmp_file,
                    _caught_failure,
                )


def _write_active_db_path(db_path: str) -> None:
    _atomic_write_text(_active_db_path_file(), db_path)


def _snapshot_main_db_path_config() -> tuple[bool, str, bool, str]:
    """快照主库路径配置。active 文件存在则必读成功——读失败上抛，禁空值冒充快照（ADR 0005）。"""
    active_file = _active_db_path_file()
    active_exists = os.path.exists(active_file)
    active_value = ""
    if active_exists:
        try:
            with open(active_file, "r", encoding="utf-8") as f:
                active_value = f.read()
        except Exception as _caught_failure:
            logger.exception(
                "snapshot active_db read failed path=%s error=%s",
                active_file,
                _caught_failure,
            )
            raise
    return (
        "MING_SIM_DB" in os.environ,
        os.environ.get("MING_SIM_DB", ""),
        active_exists,
        active_value,
    )


def _restore_main_db_path_config(snapshot: tuple[bool, str, bool, str]) -> None:
    """按快照恢复主库路径。删/写失败上抛——禁静默改写成 env/default 另一身份（ADR 0005）。"""
    env_exists, env_value, active_exists, active_value = snapshot
    if env_exists:
        os.environ["MING_SIM_DB"] = env_value
    else:
        os.environ.pop("MING_SIM_DB", None)
    active_file = _active_db_path_file()
    if active_exists:
        _atomic_write_text(active_file, active_value)
    elif os.path.exists(active_file):
        try:
            os.remove(active_file)
        except Exception as _caught_failure:
            logger.exception(
                "restore: remove stale active_db failed path=%s error=%s",
                active_file,
                _caught_failure,
            )
            raise


def _set_main_db_path(db_path: str) -> None:
    os.environ["MING_SIM_DB"] = db_path
    _write_active_db_path(db_path)


def _normalize_db_path(path: str) -> str:
    """#1749 / #14：路径身份唯一真源。

    相对路径按 user_data_dir 解析（与 WebGame.__init__ 同），再 abspath。
    abspath 失败直接上抛——禁静默退回另一套身份语义（ADR 0005）。
    """
    if not path:
        return ""
    if not os.path.isabs(path):
        path = str(user_data_dir() / path)
    return os.path.abspath(path)


def _get_main_db_path() -> str:
    """解析当前主库路径：active_db.txt > env > 默认 ming_sim.db。

    #396：new_game 不删旧库文件（旧后台 worker 仍写，删了会触发 SQLite readonly database），
    而是把主库路径切到新文件，旧连接排空关闭后旧库归档为存档。active_db.txt 持久化该切换，
    使重启后仍能加载新库。
    返回值经 _normalize_db_path——与 WebGame 打开、归档比较同一身份。
    """
    active_path = _read_active_db_path()
    if active_path:
        return _normalize_db_path(active_path)
    db_path = os.environ.get("MING_SIM_DB", "")
    if db_path:
        return _normalize_db_path(db_path)
    return _normalize_db_path(user_data_path("ming_sim.db"))


def _same_db_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return _normalize_db_path(left) == _normalize_db_path(right)


class _CloseOp:
    """单次关闭结果唯一通道（per-holder CloseOp；#1749 r7）。"""

    __slots__ = ("done", "close_ok", "db_path", "archive_settled")

    def __init__(self, db_path: str = "") -> None:
        self.done = threading.Event()
        self.close_ok = False
        self.db_path = db_path  # normalized；空=无路径身份
        # AS：当次 close executor finally 置位（失败亦空完成，不冒归档成功）。
        self.archive_settled = threading.Event()


class _HolderEntry:
    """路径持有者强引用；close_op 为关闭结果唯一通道。"""

    __slots__ = ("runtime", "close_op")

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.close_op: Optional[_CloseOp] = None


class _MenuPathLease:
    """一 norm 一租约：单槽 opening + holders 强引用 + 归档请求真源。

    关闭结果只走 entry.close_op；归档请求只走 archive_pending；执行只走 C7。
    无 lease.completion 单槽。
    """

    __slots__ = ("opening", "holders", "archive_pending")

    def __init__(self) -> None:
        self.opening: int = 0  # ∈ {0, 1}
        self.holders: dict[int, _HolderEntry] = {}  # id(runtime) → entry
        self.archive_pending: bool = False


# 路径 → 租约。C7 谓词：opening==0 ∧ holders 空 ∧ archive_pending。
_menu_path_leases: dict[str, _MenuPathLease] = {}
_menu_path_lock = threading.Lock()


def _path_lease_gc_locked(norm: str, lease: _MenuPathLease) -> None:
    if lease.opening <= 0 and not lease.holders and not lease.archive_pending:
        _menu_path_leases.pop(norm, None)


def _path_norm_of_game(game: Any, path: str = "") -> str:
    raw = path or (getattr(game, "db_path", "") or "")
    return _normalize_db_path(raw) if raw else ""


def _claim_opening(path: str) -> str:
    """C1 单槽：opening 0→1 成功返回 norm；已占用或空路径返回 ""。"""
    norm = _normalize_db_path(path) if path else ""
    if not norm:
        return ""
    with _menu_path_lock:
        lease = _menu_path_leases.setdefault(norm, _MenuPathLease())
        if lease.opening != 0:
            return ""
        lease.opening = 1
    return norm


def _c7_ready_locked(lease: _MenuPathLease) -> bool:
    """C7 唯一资格谓词（path 锁内）。"""
    return lease.opening <= 0 and not lease.holders and lease.archive_pending


def _release_opening(path: str) -> None:
    """释放本次 opening；有 pending 时走 C7-release（资格只在 C7 判定）。"""
    norm = _normalize_db_path(path) if path else ""
    if not norm:
        return
    has_pending = False
    with _menu_path_lock:
        lease = _menu_path_leases.get(norm)
        if lease is None:
            return
        if lease.opening > 0:
            lease.opening = 0
        has_pending = bool(lease.archive_pending)
        if not has_pending:
            _path_lease_gc_locked(norm, lease)
    if has_pending:
        _c7_try_fulfill_archive(norm)


def _register_holder(path: str, runtime: Any) -> Optional[_HolderEntry]:
    """P1：登记 holder 强引用；同 id 幂等返回原 entry。claim 永不经此补登。"""
    norm = _path_norm_of_game(runtime, path)
    if not norm or runtime is None:
        return None
    gid = id(runtime)
    with _menu_path_lock:
        lease = _menu_path_leases.setdefault(norm, _MenuPathLease())
        existing = lease.holders.get(gid)
        if existing is not None:
            return existing
        entry = _HolderEntry(runtime)
        lease.holders[gid] = entry
        return entry


def _lookup_holder(path: str, runtime: Any) -> Optional[_HolderEntry]:
    """定点查 entry；不扫全表、不补登。"""
    norm = _path_norm_of_game(runtime, path)
    if not norm or runtime is None:
        return None
    gid = id(runtime)
    with _menu_path_lock:
        lease = _menu_path_leases.get(norm)
        if lease is None:
            return None
        return lease.holders.get(gid)


def _handback_failed_runtime(runtime: Any, path: str = "") -> Optional[_HolderEntry]:
    """#1749 B：构造/清理 close 失败携回——同一 holder + 失败 CloseOp（A5）。

    只装配 entry/op，落结果走唯一 ``_settle_close_result``，不另开置位。
    """
    norm = _path_norm_of_game(runtime, path)
    if not norm or runtime is None:
        return None
    entry = _register_holder(norm, runtime)
    if entry is None:
        return None
    op = entry.close_op
    if op is None or (op.done.is_set() and not op.close_ok):
        op = _CloseOp(db_path=norm)
        entry.close_op = op
    if not op.db_path:
        op.db_path = norm
    _settle_close_result(op=op, close_ok=False, entry=entry, path=norm)
    return entry


def _claim_close(
    entry: _HolderEntry,
    path: str = "",
) -> tuple[str, Optional[_CloseOp]]:
    """领关闭 op。返回 (role, op)：

    - executor：新领 op，调用方必须 drain
    - waiter：已有 op（进行中或成功完成），只等
    - orphan：entry 已不在 holders 且无 op → 禁冒成功
    - released_ok / released_failed：entry 已删但调用方持有已完成 op 的引用
    - A8：在册且 done∧¬ok → 允许方获新 op 重试
    """
    if entry is None:
        return ("orphan", None)
    runtime = entry.runtime
    norm = _path_norm_of_game(runtime, path)
    gid = id(runtime) if runtime is not None else 0
    with _menu_path_lock:
        lease = _menu_path_leases.get(norm) if norm else None
        current = lease.holders.get(gid) if lease is not None else None
        if current is not entry:
            # 已删或非本 entry
            op = entry.close_op
            if op is None:
                return ("orphan", None)
            if op.done.is_set():
                return (
                    "released_ok" if op.close_ok else "released_failed",
                    op,
                )
            return ("waiter", op)
        op = entry.close_op
        if op is None:
            op = _CloseOp(db_path=norm)
            entry.close_op = op
            return ("executor", op)
        # A8：失败已完成 op → 允许方重试（新 op）；进行中或成功完成仍 waiter/released。
        if op.done.is_set() and not op.close_ok:
            op = _CloseOp(db_path=norm)
            entry.close_op = op
            return ("executor", op)
        return ("waiter", op)


def _note_close_result(
    entry: _HolderEntry,
    close_ok: bool,
    path: str = "",
) -> None:
    """A4/A5：executor 关闭结果入账。成功删 entry 并 C7-note；失败留 entry。

    资格谓词只在 C7；此处不重复实现搬库条件。
    """
    runtime = entry.runtime
    norm = _path_norm_of_game(runtime, path)
    if not norm:
        return
    gid = id(runtime) if runtime is not None else 0
    has_pending = False
    with _menu_path_lock:
        lease = _menu_path_leases.setdefault(norm, _MenuPathLease())
        current = lease.holders.get(gid)
        op = entry.close_op
        if op is not None:
            op.close_ok = close_ok
            if not op.db_path:
                op.db_path = norm
        if close_ok:
            if current is entry:
                del lease.holders[gid]
            has_pending = bool(lease.archive_pending)
            if not has_pending:
                _path_lease_gc_locked(norm, lease)
        else:
            # 失败：entry 必须仍在；若竞态被删则补回，不升成功态（A5）。
            if current is None:
                lease.holders[gid] = entry
    if close_ok and has_pending:
        _c7_try_fulfill_archive(norm)


def _path_request_archive(path: str) -> None:
    """AR-req：归档请求唯一写入入口（成功发布的 new_game）。C7-fulfill 边沿。"""
    norm = _normalize_db_path(path) if path else ""
    if not norm:
        return
    with _menu_path_lock:
        lease = _menu_path_leases.setdefault(norm, _MenuPathLease())
        lease.archive_pending = True
    _c7_try_fulfill_archive(norm)


def _c7_try_fulfill_archive(path: str) -> bool:
    """C7 唯一执行接缝：opening==0 ∧ holders 空 ∧ pending → 搬库。

    资格判定与搬库均在 path 锁内一次完成（r5①C / r7 C7）；失败保持 pending、留真因，
    不在 GC 后把异常当成功清空职责。禁止 claimed→锁外 move→再取锁回写。
    """
    norm = _normalize_db_path(path) if path else ""
    if not norm:
        return False
    with _menu_path_lock:
        lease = _menu_path_leases.get(norm)
        if lease is None or not _c7_ready_locked(lease):
            return False
        moved_ok = False
        try:
            if not os.path.exists(norm):
                moved_ok = True
            else:
                moved_ok = _archive_move_db_files(norm)
        except Exception as _caught_failure:
            logger.exception(
                "C7 archive execute failed path=%s error=%s",
                norm,
                _caught_failure,
            )
            moved_ok = False
        if not moved_ok:
            # pending 保持 True；holders/opening 未变，不 GC。
            return False
        lease.archive_pending = False
        _path_lease_gc_locked(norm, lease)
        return True


def _snap_holders(path: str) -> list[_HolderEntry]:
    """opening 持有者扫表：快照当前 holders（仅调用方已持 opening 时合法）。"""
    norm = _normalize_db_path(path) if path else ""
    if not norm:
        return []
    with _menu_path_lock:
        lease = _menu_path_leases.get(norm)
        if lease is None:
            return []
        return list(lease.holders.values())


def _drain_path_holders(path: str) -> bool:
    """K2/L3：对 path 上所有 holder 定点 claim/wait/drain。

    任一 close_ok is False → False（保留失败 entry，开库前取消）。
    orphan / released_failed 必须失败投影（A0″）；不得跳过当成功。
    调用方必须已持 opening。
    """
    entries = _snap_holders(path)
    all_ok = True
    for entry in entries:
        role, op = _claim_close(entry, path)
        if role == "orphan":
            all_ok = False
            continue
        if role == "executor" and op is not None:
            _spawn_drain_close(entry.runtime, entry=entry, close_op=op)
        if op is not None:
            op.done.wait()
            if not op.close_ok:
                all_ok = False
        elif role == "released_failed":
            all_ok = False
    return all_ok


def _point_retire_close(game: Any, path: str = "") -> Optional[_CloseOp]:
    """E2/E3 / X2：定点退休。E2_absent → 不 drain、不伪造 op。"""
    norm = _path_norm_of_game(game, path)
    entry = _lookup_holder(norm, game)
    if entry is None:
        return None  # E2_absent
    role, op = _claim_close(entry, norm)
    if role == "executor" and op is not None:
        _spawn_drain_close(game, entry=entry, close_op=op)
    return op


def _settle_close_result(
    *,
    op: Optional[_CloseOp],
    close_ok: bool,
    entry: Optional[_HolderEntry] = None,
    game: Any = None,
    path: str = "",
) -> None:
    """#1749 C7/完成者：同步/异步/私有关闭唯一落结果。

    note/归档异常不得跳过 done/archive_settled；waiter/调用方不补置位。
    close 成功不因后续 note 异常倒写 close_ok。
    """
    try:
        if entry is not None:
            _note_close_result(entry, close_ok, path)
        elif not close_ok and game is not None:
            norm = path or _path_norm_of_game(game)
            if norm:
                registered = _register_holder(norm, game)
                if registered is not None:
                    if registered.close_op is None and op is not None:
                        registered.close_op = op
                    elif (
                        op is not None
                        and registered.close_op is not None
                        and registered.close_op.done.is_set()
                        and not registered.close_op.close_ok
                    ):
                        registered.close_op = op
                    _note_close_result(registered, False, norm)
    except Exception as _caught_failure:
        logger.exception(
            "settle close note failed path=%s error=%s",
            path,
            _caught_failure,
        )
    finally:
        if op is not None:
            op.close_ok = close_ok
            op.done.set()
            op.archive_settled.set()


def _close_unregistered(
    game: Any,
    path: str = "",
) -> Optional[_CloseOp]:
    """构造失败/取消且未 P1：私有 close；失败则补登 holder 保所有权。"""
    norm = _path_norm_of_game(game, path)
    op = _CloseOp(db_path=norm)
    close_ok = False
    try:
        _drain_close_body(game)
        close_ok = True
    except Exception as _caught_failure:
        logger.exception(
            "private close failed path=%s error=%s",
            norm,
            _caught_failure,
        )
        close_ok = False
    finally:
        _settle_close_result(
            op=op, close_ok=close_ok, entry=None, game=game, path=norm,
        )
    return op


class _MenuCandidateCancelled(Exception):
    """菜单候选代际取消：经统一未发布收口后，投影为入口既有取消身份（非 worker 崩）。"""


def _discard_unpublished_candidate(
    runtime: Any,
    entry: Optional[_HolderEntry],
    path: str = "",
) -> None:
    """未发布候选的取消/准备失败收口：经 holder/CloseOp/drain 唯一接缝关闭。

    已登记走 claim_close→drain；未登记走 _close_unregistered。
    close 失败由 settle 留存失败 holder/op 供重试，不删活引用、不冒成功。
    次生异常只 logger.exception 留痕，不上改调用方主异常身份。
    """
    if runtime is None:
        return
    try:
        if entry is not None:
            role, op = _claim_close(entry, path)
            if role == "executor" and op is not None:
                try:
                    _drain_and_close_session(
                        runtime, entry=entry, close_op=op,
                    )
                except Exception as _caught_failure:
                    logger.exception(
                        "discard unpublished candidate drain failed path=%s error=%s",
                        path,
                        _caught_failure,
                    )
        else:
            _close_unregistered(runtime, path)
    except Exception as _caught_failure:
        logger.exception(
            "discard unpublished candidate failed path=%s error=%s",
            path,
            _caught_failure,
        )


def _drop_live_pointer_if_unrecoverable(
    expected: Any,
    *,
    exclude: Any = None,
) -> None:
    """菜单失败出口：仅当活指针仍是本请求启动时的 expected 且已不可恢复时摘掉。

    身份匹配 + restorable 谓词：不碰后继已发布对象，不碰 exclude（本请求候选）。
    指针交换在 lifecycle 锁内；restorable 探测在锁外（可触 DB，不扩大锁窗）。
    """
    global web_game
    if expected is None:
        return
    if exclude is not None and expected is exclude:
        return
    cur = web_game
    if cur is not expected:
        return
    if _runtime_restorable(cur):
        return
    with _menu_lifecycle_lock:
        if web_game is expected:
            web_game = None


def _runtime_restorable(game: Any) -> bool:
    """#1749：失败 close 后可否恢复为活局——db 与 agno 都必须仍可用，且未进入 close 半态。

    判定真源在共享核 ``save_slots.runtime_restorable``（#1902 F2：CLI 读档失败恢复
    走同一条判据）；此处只做 Web 侧转发，探测异常的真因日志也归共享核（ADR 0005）。
    """
    from ming_sim.save_slots import runtime_restorable

    return runtime_restorable(game)


def _archive_move_db_files(old_db_path: str) -> bool:
    """纯文件搬库（#396 / #1732 唯一实现）。成功 True；失败 False 并 log。

    不在此做 live/资格判断——资格只由 C7 谓词承担。
    目录准备/move/WAL/SHM/回滚异常一律捕获留真因，返回 False（不抛穿 C7）。
    """
    if not old_db_path or not os.path.exists(old_db_path):
        return True
    saves_dir = user_data_path("saves")
    try:
        os.makedirs(saves_dir, exist_ok=True)
    except Exception as _caught_failure:
        logger.exception(
            "archive prep makedirs failed dir=%s error=%s",
            saves_dir,
            _caught_failure,
        )
        return False
    target = os.path.join(saves_dir, f"drained_{time.time_ns()}.db")
    try:
        shutil.move(old_db_path, target)
    except Exception as _caught_failure:
        logger.exception(
            "archive move failed path=%s → %s error=%s",
            old_db_path,
            target,
            _caught_failure,
        )
        return False
    wal_path = old_db_path + "-wal"
    if os.path.exists(wal_path):
        try:
            shutil.move(wal_path, target + "-wal")
        except Exception as _caught_failure:
            logger.exception(
                "archive wal move failed path=%s error=%s",
                wal_path,
                _caught_failure,
            )
            try:
                shutil.move(target, old_db_path)
            except Exception as _caught_failure:
                logger.exception(
                    "archive rollback failed path=%s error=%s",
                    old_db_path,
                    _caught_failure,
                )
            return False
    shm_path = old_db_path + "-shm"
    if os.path.exists(shm_path):
        try:
            shutil.move(shm_path, target + "-shm")
        except Exception as _caught_failure:
            logger.exception(
                "archive shm move failed path=%s error=%s",
                shm_path,
                _caught_failure,
            )
            # shm 失败不回滚主库（与既有行为一致：仅 log）；主库已进 saves。
    return True


def _drain_close_body(game: Any) -> None:
    """委托共享 drain 核心；失败上抛，可写时 unseal（Web 保留可写探测）。

    权威逻辑在 ``ming_sim.session_write_queue.drain_and_close_session``——
    CLI/Web 同核；本函数只保留 Web 侧日志与 ``_runtime_restorable`` 门。
    """
    from ming_sim.session_write_queue import drain_and_close_session as _shared_drain

    q = get_session_write_queue(game)
    try:
        _shared_drain(game)
    except Exception as _caught_failure:
        # #1740 / ADR 0005：排空关库失败不得无痕 return——保留原异常上抛。
        logger.exception(
            "drain/close session failed error=%s",
            _caught_failure,
        )
        if _runtime_restorable(game):
            try:
                q.unseal()
            except Exception as _caught_failure:
                logger.exception(
                    "unseal after drain/close failure failed error=%s",
                    _caught_failure,
                )
        raise


def _drain_and_close_session(
    game: Any,
    *,
    entry: Optional[_HolderEntry] = None,
    close_op: Optional[_CloseOp] = None,
) -> None:
    """等在途后台写入排空后再关连接；结果经 entry/close_op 入账。

    #396：菜单生命周期不在 write_gate 被持时直接 session.close()。
    #1353：seal + barrier + 持 write_gate 关连接。
    #1749 r7：不在此写 archive_pending——归档请求只经 AR-req。
    同步 executor 与 spawn 共用 ``_settle_close_result``（note 异常亦必达 done/AS）。
    失败由 ``_drain_close_body`` 原样上抛（ADR 0005）。
    """
    op = close_op
    if op is None and entry is not None:
        op = entry.close_op
    path = _path_norm_of_game(game)
    close_ok = False
    try:
        _drain_close_body(game)
        close_ok = True
    finally:
        _settle_close_result(
            op=op,
            close_ok=close_ok,
            entry=entry,
            game=game if entry is None else None,
            path=path,
        )


def _spawn_drain_close(
    game: Any,
    *,
    entry: Optional[_HolderEntry] = None,
    close_op: Optional[_CloseOp] = None,
) -> _CloseOp:
    """后台 drain/close；返回 CloseOp（executor 通道）。不写 archive_pending。"""
    path = _path_norm_of_game(game)
    op = close_op
    if op is None:
        if entry is not None and entry.close_op is not None:
            op = entry.close_op
        else:
            op = _CloseOp(db_path=path)
            if entry is not None and entry.close_op is None:
                entry.close_op = op
    elif not op.db_path and path:
        op.db_path = path

    def _run() -> None:
        close_ok = False
        try:
            _drain_close_body(game)
            close_ok = True
        except Exception as _caught_failure:
            logger.exception(
                "drain/close worker failed path=%s error=%s",
                path,
                _caught_failure,
            )
            close_ok = False
        finally:
            _settle_close_result(
                op=op,
                close_ok=close_ok,
                entry=entry,
                game=game if entry is None else None,
                path=path,
            )

    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception as _caught_failure:
        logger.exception(
            "spawn drain/close thread failed error=%s",
            _caught_failure,
        )
        _settle_close_result(
            op=op, close_ok=False, entry=entry,
            game=game if entry is None else None, path=path,
        )
        raise
    return op


web_game: Optional[WebGame] = None  # 懒加载：菜单页点「新游戏/继续/加载存档」才实例化
# #1195：菜单生命周期世代。continue worker 发布 web_game 前对号；失配则丢弃白建局。
_menu_generation: int = 0
# #1749：new_game/exit 互斥——禁止 web_game=None 窗口内二次 new_game 把
# 仍在构造的新库路径当 prev 归档（活连接钉 drained_*.db → readonly）。
_menu_lifecycle_lock = threading.Lock()


app = FastAPI(title="Ming Salvage MVP Web")


def _dependency_mismatch_detail(exc: DependencyMismatch) -> Dict[str, Any]:
    """#1721：DependencyMismatch 的唯一 typed 投影（HTTP detail 与 SSE error 共用）。"""
    return {
        "code": "dependency_mismatch",
        "package": exc.package,
        "requirement": exc.requirement,
        "message": exc.message,
    }


@app.exception_handler(Exception)
async def runtime_failure_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": _exception_detail(exc)})


@app.exception_handler(DependencyMismatch)
async def dependency_mismatch_handler(_request: Request, exc: DependencyMismatch) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": _dependency_mismatch_detail(exc)})


def get_game() -> WebGame:
    """游戏路由统一入口。未开局 → 409 让前端跳回菜单页。"""
    if web_game is None:
        raise HTTPException(status_code=409, detail="尚未开局，请回菜单选择新游戏/继续/加载存档。")
    return web_game


def _save_visible_for_campaign(fname: str, campaign_id: str) -> bool:
    if not fname.startswith(AUTO_SAVE_PREFIX):
        return True
    campaign_id = (campaign_id or "").strip()
    return bool(campaign_id and fname.startswith(f"{AUTO_SAVE_PREFIX}{campaign_id}_"))


# 自动存档文件名：auto_<campaign_id>_<year>_<period>_t<turn>_<tag>.db
_AUTO_SAVE_RE = re.compile(
    rf"^{re.escape(AUTO_SAVE_PREFIX)}(?P<cid>[0-9a-f]+)_"
    r"(?P<year>\d{4})_(?P<period>\d{2})_t(?P<turn>\d{4})_(?P<tag>\w+)$"
)

_AUTO_TAG_LABEL = {"begin": "月初", "preresolve": "结算前"}


def _parse_save_name(name: str) -> Dict[str, Any]:
    """把存档名解析成元信息。自动档归到对应 campaign，手动档 campaign_id 留空。"""
    m = _AUTO_SAVE_RE.match(name)
    if not m:
        return {"campaign_id": "", "kind": "manual", "label": name}
    year = int(m.group("year"))
    period = int(m.group("period"))
    turn = int(m.group("turn"))
    tag = m.group("tag")
    tag_label = _AUTO_TAG_LABEL.get(tag, tag)
    return {
        "campaign_id": m.group("cid"),
        "kind": "auto",
        "year": year,
        "period": period,
        "turn": turn,
        "tag": tag,
        "label": f"{year}年{period}月 · 第{turn}回合 · {tag_label}",
    }


def _main_db_campaign_id() -> str:
    """Read the main campaign identity; an absent file is not a corrupt database."""
    db_path = _get_main_db_path()
    if not os.path.isfile(db_path):
        return ""
    conn = sqlite3.connect(db_path)
    try:
        from ming_sim.entities.reign_state.store import ReignStateStore

        value = ReignStateStore(conn).kv_get("campaign_id")
        return str(value).strip() if value else ""
    finally:
        conn.close()


def _scan_saves() -> List[Dict[str, Any]]:
    """扫存档目录，独立于 WebGame 实例（菜单页无 game 也要能列）。
    不再按 campaign 过滤——所有局的存档都列出，由前端按局分组。"""
    saves_dir = user_data_path("saves")
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(saves_dir):
        return out
    for fname in sorted(os.listdir(saves_dir)):
        if not fname.endswith(".db"):
            continue
        name = fname[:-3]
        full = os.path.join(saves_dir, fname)
        try:
            st = os.stat(full)
        except FileNotFoundError:
            continue
        meta = _parse_save_name(name)
        out.append({
            "name": name,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            **meta,
        })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _scan_campaigns() -> List[Dict[str, Any]]:
    """把存档按局（campaign_id）分组，当前主 DB 的局标 current=True。
    手动存档（无 campaign_id）归到一个 manual 组。每组按 mtime 倒序，组也按最新档倒序。"""
    saves = _scan_saves()
    cur_campaign = _main_db_campaign_id()
    groups: Dict[str, Dict[str, Any]] = {}
    for s in saves:
        cid = s.get("campaign_id") or ""
        key = cid or "__manual__"
        group = groups.get(key)
        if group is None:
            group = {
                "campaign_id": cid,
                "kind": "manual" if not cid else "auto",
                "current": bool(cid) and cid == cur_campaign,
                "saves": [],
                "latest_mtime": 0,
            }
            groups[key] = group
        group["saves"].append(s)
        group["latest_mtime"] = max(group["latest_mtime"], s["mtime"])
    out = list(groups.values())
    # 当前局置顶，其余按最新档时间倒序；手动组排最后。
    out.sort(key=lambda g: (
        0 if g["current"] else (2 if g["kind"] == "manual" else 1),
        -g["latest_mtime"],
    ))
    return out


def _has_main_db() -> bool:
    """主 DB 文件是否存在 → 决定「继续」按钮可不可点。"""
    return os.path.isfile(_get_main_db_path())


@app.get("/api/menu/status")
async def api_menu_status() -> Dict[str, Any]:
    """菜单页状态：API key 是否配好、上次主 DB 是否存在、存档列表。"""
    runtime = load_runtime_llm()
    from ming_sim.cli_backend import (
        CLI_REASONING_FLOOR_RUNNERS,
        CLI_REASONING_STRENGTH_RUNNERS,
        cli_model_choices,
        cli_runner_choices,
        is_supported_cli_runner,
    )
    from ming_sim.llm_config import llm_config_from_runtime
    # #1902 F2：有效配置只认共核 llm_config_from_runtime；入口只保留原样存盘值供表单。
    cfg = llm_config_from_runtime(
        runtime,
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        model=os.environ.get("OPENAI_MODEL", ""),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        timeout_seconds=float(os.environ.get("OPENAI_TIMEOUT_SECONDS") or API_DEFAULT_TIMEOUT_SECONDS),
        thinking_level="",
        advanced_model=os.environ.get("OPENAI_ADVANCED_MODEL", ""),
        advanced_base_url=os.environ.get("OPENAI_ADVANCED_BASE_URL", ""),
        advanced_api_key=os.environ.get("OPENAI_ADVANCED_API_KEY", ""),
        advanced_thinking_level="",
    )
    cli_slot = runtime.get("cli") if isinstance(runtime.get("cli"), dict) else {}
    api_slot = runtime.get("api") if isinstance(runtime.get("api"), dict) else {}
    # cli_model_saved = 原样存盘值（空=用户选「默认」档）；cli_model = 共核 resolved。
    # 表单（CliModelField 下拉）须读 raw，否则空保存被 resolved 成默认名 → 下拉误判「其他(手填)」
    # 并把字面量钉死（CMR R1 Claude+Gemini concur）。
    cli_model_saved = str(cli_slot.get("model") or "").strip()
    has_api_key = _has_real_api_key(cfg.api_key) or _has_real_api_key(os.environ.get("OPENAI_API_KEY"))
    reasoning_supported = (
        cli_supports_reasoning_strength(cfg.cli_runner)
        if cfg.channel == "cli"
        else _api_reasoning_supported_for_effective_model(
            str(cfg.base_url),
            str(cfg.model),
            str(cfg.advanced_base_url),
            str(cfg.advanced_model),
        )
    )
    # readiness 按 active channel 判：API 通道看真实 key，CLI 通道看 runner 是否受支持。
    # 不能因 inactive API 槽（ADR 0001 保留）里有 key 就把不可用的 CLI runner 误报成 ready。
    llm_ready = has_api_key if cfg.channel == "api" else is_supported_cli_runner(cfg.cli_runner)
    return {
        "has_api_key": has_api_key,
        "llm_ready": llm_ready,
        "has_running_game": web_game is not None,
        "has_main_db": _has_main_db(),
        "saves": _scan_saves(),
        "campaigns": _scan_campaigns(),
        "current_campaign": _main_db_campaign_id(),
        "llm": {
            "channel": cfg.channel,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "has_api_key": has_api_key,
            "cli_runner": cfg.cli_runner,
            "cli_model": cfg.cli_model,
            "cli_model_saved": cli_model_saved,
            "cli_model_choices": cli_model_choices(),
            # #1274 W1：CLI Runner 下拉单源（= _CLI_BACKENDS 有序），menuPage/gameMenu 共吃。
            "cli_runners": cli_runner_choices(),
            "cli_timeout_seconds": cfg.cli_timeout_seconds,
            "reasoning_strength": cfg.reasoning_strength,
            "api_reasoning_strength": api_slot.get("reasoning_strength"),
            "cli_reasoning_strength": cli_slot.get("reasoning_strength"),
            "effective_reasoning_strengths": effective_reasoning_strengths(runtime),
            "reasoning_supported": reasoning_supported,
            "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
            # #1271：能力名单自 cli_backend 单源导出，供前端 fallback 消费（禁前端硬编码）。
            "cli_reasoning_runners": sorted(CLI_REASONING_STRENGTH_RUNNERS),
            "cli_reasoning_floor_runners": sorted(CLI_REASONING_FLOOR_RUNNERS),
            "timeout_seconds": cfg.timeout_seconds,
            "thinking_level": cfg.thinking_level,
            "advanced_model": cfg.advanced_model,
            "advanced_base_url": cfg.advanced_base_url,
            "has_advanced_api_key": _has_real_api_key(cfg.advanced_api_key) or _has_real_api_key(os.environ.get("OPENAI_ADVANCED_API_KEY")),
            "advanced_thinking_level": "",
            # #1794：设置页读回附加请求头表（API 槽）。
            "default_headers": dict(cfg.default_headers or {}),
        },
    }


@app.post("/api/menu/new_game")
async def api_menu_new_game() -> Dict[str, Any]:
    """开始新游戏：切主库路径 → 新建 WebGame → 发布时再退休旧 runtime。

    #396/#1732/#1749 r7：
    N1a lifecycle bump+set main；N1b claim_opening(new)；N2 构造；
    P1 register → P2 代际发布；AR-req(prev) 与定点退休正交；N5 release_opening。
    构造期不 detach 旧 web_game；失配不复活旧局。
    """
    global web_game, _menu_generation
    loop = asyncio.get_running_loop()

    def _new_game_work() -> Dict[str, Any]:
        global web_game, _menu_generation
        opening_path = ""
        token = 0
        snapshot: Optional[tuple[bool, str, bool, str]] = None
        prev_db_path = ""
        new_db_path = ""
        candidate_entry: Optional[_HolderEntry] = None
        with _menu_lifecycle_lock:
            # N1a
            _menu_generation += 1
            token = _menu_generation
            snapshot = _snapshot_main_db_path_config()
            prev_db_path = _get_main_db_path()
            new_db_path = user_data_path(f"ming_sim_{time.time_ns()}.db")
            try:
                _set_main_db_path(new_db_path)
            except Exception:
                _restore_main_db_path_config(snapshot)
                raise
        # N1b 仅 path
        opening_path = _claim_opening(new_db_path)

        def _rollback_path_if_ours() -> None:
            """归属检查+配置恢复在 lifecycle 锁内一次完成；不覆盖后继已切走的主路径。"""
            assert snapshot is not None
            with _menu_lifecycle_lock:
                if _same_db_path(_get_main_db_path(), new_db_path):
                    _restore_main_db_path_config(snapshot)

        if not opening_path:
            _rollback_path_if_ours()
            raise HTTPException(status_code=409, detail="新游戏路径忙，请稍后重试。")

        try:
            try:
                # N2 无锁构造
                new_game = WebGame(fresh=True, db_path=new_db_path)
            except LLMUnavailable as exc:
                _rollback_path_if_ours()
                raise HTTPException(status_code=412, detail=_exception_detail(exc))
            except Exception:
                _rollback_path_if_ours()
                raise

            # P1 path register（发布前入册）
            candidate_entry = _register_holder(new_db_path, new_game)
            # #1749：响应快照须在发布前物化——持 opening + 未入 web_game 时独占活连接；
            # 发布后 exit/new_game 可经 web_game 定点退休关库，锁外 state_payload 会读已关连接。
            # 准备失败（含快照）与代际取消共用未发布收口，不另造清理分支。
            retire = None
            published = False
            try:
                state_snapshot = new_game.state_payload()
                prev_norm = _normalize_db_path(prev_db_path) if prev_db_path else ""
                with _menu_lifecycle_lock:
                    # P2 仅代际+指针——发布决定在锁内落定，禁锁外再读 token 改判。
                    if token == _menu_generation:
                        retire = web_game
                        web_game = new_game
                        published = True

                if not published:
                    raise HTTPException(
                        status_code=409, detail="新游戏已取消（菜单状态已变更）。",
                    )

                # ★ AR-req：已发布操作仍承担——对 prev 写 pending（与 close executor 正交）
                if prev_norm and not _same_db_path(prev_norm, new_db_path):
                    _path_request_archive(prev_norm)

                # 定点退休 old（不依赖 drain 写 pending）；已发布后 token 再 bump 不撤销此责
                if retire is not None and retire is not new_game:
                    _point_retire_close(retire)

                # 响应用发布前快照；payload 未知代码错必须响亮失败（ADR 0005），
                # 不得宽捕获后返回 ok=True 洗白成功。finally 仍 release_opening。
                return {"state": state_snapshot}
            except Exception:
                if not published:
                    _discard_unpublished_candidate(
                        new_game, candidate_entry, new_db_path,
                    )
                    _rollback_path_if_ours()
                raise
        finally:
            # N5：release_opening（含 C7-release；new 侧通常无 pending）
            _release_opening(opening_path)

    return await loop.run_in_executor(None, _new_game_work)


@app.post("/api/menu/continue")
async def api_menu_continue() -> StreamingResponse:
    """继续：用上次主 DB 启动 WebGame。

    #1195：SSE stage → done/error。
    #1749 r7：K1 bump → K3 claim_opening → K2 排空 holders → K3t 代际核验
    → K4 构造 → P1/P2/P3 → K5out 退休 old（不 AR）→ K6 release_opening。
    """
    global _menu_generation
    if not _has_main_db():
        raise HTTPException(status_code=404, detail="无上次进度可继续，请先新游戏或加载存档。")

    with _menu_lifecycle_lock:
        # K1
        _menu_generation += 1
        token = _menu_generation
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def on_stage(label: str) -> None:
        ev_queue.put(("stage", label))

    def worker() -> None:
        global web_game
        opening_path = ""
        candidate_entry: Optional[_HolderEntry] = None
        # 记录本 worker 启动时的活指针身份：失败收口只摘「仍是该旧对象且已不可恢复」的指针，
        # 不得清掉代际间已被 new_game/load 发布的新局。
        initial_web_game = web_game
        # 排空一旦开扫，旧 holder 可能已半关/全关——此后任一失败/取消出口统一履行死指针处置。
        drain_attempted = False
        published = False
        game = None
        try:
            on_stage("准备载入上次进度...")
            main_for_open = _get_main_db_path()
            # K3 仅 path：消费准入
            opening_path = _claim_opening(main_for_open)
            if not opening_path:
                ev_queue.put((
                    "__error__",
                    {"message": "有菜单操作进行中，请稍后重试。"},
                ))
                return
            # K2：排空本路径 holders（仅 opening 持有者可扫）
            drain_attempted = True
            if not _drain_path_holders(opening_path):
                ev_queue.put((
                    "__error__",
                    {"message": "上一局尚未关闭完成，请稍后重试。"},
                ))
                return
            # K3t：排空后、构造前强制代际核验
            if token != _menu_generation:
                ev_queue.put(("__error__", {"message": "继续已取消（菜单状态已变更）。"}))
                return
            # K4 无锁构造
            game = WebGame(fresh=False, on_stage=on_stage, db_path=opening_path)
            # P1
            candidate_entry = _register_holder(opening_path, game)
            # #1749：发布前快照——持 opening + 未入 web_game 时独占；发布后可被定点退休关库。
            # 准备失败（含快照）与代际取消共用未发布收口；死指针在 finally 统一摘。
            old_runtime = None
            try:
                state_snapshot = game.state_payload()
                with _menu_lifecycle_lock:
                    # P2
                    if token == _menu_generation:
                        old_runtime = web_game
                        web_game = game
                        published = True
                if not published:
                    raise _MenuCandidateCancelled(
                        "继续已取消（菜单状态已变更）。",
                    )
                # K5out：退休 old，不 AR-req（#1732 续玩）
                if old_runtime is not None and old_runtime is not game:
                    _point_retire_close(old_runtime)
                ev_queue.put(("__done__", {"state": state_snapshot}))
            except Exception:
                if not published:
                    _discard_unpublished_candidate(
                        game, candidate_entry, opening_path,
                    )
                raise
        except _MenuCandidateCancelled as exc:
            ev_queue.put(("__error__", _exception_detail(exc)))
        except LLMUnavailable as exc:
            ev_queue.put(("__error__", _exception_detail(exc)))
        except DependencyMismatch as exc:
            ev_queue.put(("__error__", _dependency_mismatch_detail(exc)))
        except Exception as exc:  # noqa: BLE001 — SSE 终态收束，不让线程死掉
            logger.exception('continue worker failed')
            ev_queue.put(("__error__", _exception_detail(exc)))
        finally:
            # 排空后任一失败/取消出口：仅摘本请求启动时已不可恢复的旧指针。
            if drain_attempted and not published:
                _drop_live_pointer_if_unrecoverable(
                    initial_web_game, exclude=game,
                )
            # K6：必达 release（含 C7-release）
            _release_opening(opening_path)

    async def generate() -> AsyncIterator[str]:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        loop = asyncio.get_running_loop()
        while True:
            kind, data = await loop.run_in_executor(None, ev_queue.get)
            if kind == "__done__":
                yield sse_event("done", data)
                break
            if kind == "__error__":
                yield sse_event("error", data if isinstance(data, dict) else {"message": data})
                break
            yield sse_event(kind, {"content": data})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/menu/load_save/{name}")
async def api_menu_load_save(name: str) -> Dict[str, Any]:
    """从存档启动：先启动空 WebGame（fresh=False）→ 调 load_save 热替换主 DB。

    #1749 r7：L1 bump+摘 old → L2 claim_opening → L3/L3c 排空 → L3t 代际
    → L4/L5 构造/replace → P1/P2/P3 → L7 release_opening。
    锁序禁 lifecycle→path；发布后只用本地 published 引用。
    """
    global web_game, _menu_generation
    loop = asyncio.get_running_loop()

    def _load_work() -> Any:
        global web_game, _menu_generation
        opening_path = ""
        token = 0
        old_game = None
        # L1 lifecycle：bump + 摘指针
        with _menu_lifecycle_lock:
            _menu_generation += 1
            token = _menu_generation
            main_before = _get_main_db_path()
            old_game = web_game
            web_game = None

        def _restore_old_if_current_generation() -> None:
            """失败恢复：仅当本代仍有效且无更新发布时恢复；禁只凭 web_game is None。"""
            global web_game
            if old_game is None or not _runtime_restorable(old_game):
                return
            with _menu_lifecycle_lock:
                if token == _menu_generation and web_game is None:
                    web_game = old_game

        try:
            # L2 仅 path
            opening_path = _claim_opening(main_before) if main_before else ""
            if main_before and not opening_path:
                _restore_old_if_current_generation()
                raise HTTPException(
                    status_code=409,
                    detail="有菜单操作进行中，请稍后重试。",
                )

            # L3：定点关 old + L3c 扫剩余 holders
            if old_game is not None:
                op = _point_retire_close(old_game, main_before or "")
                if op is not None:
                    op.done.wait()
                    if not op.close_ok:
                        _restore_old_if_current_generation()
                        logger.exception(
                            "load_save close failed for previous runtime"
                        )
                        raise HTTPException(
                            status_code=409, detail="无法关闭当前局，请稍后重试。",
                        )
            if opening_path and not _drain_path_holders(opening_path):
                _restore_old_if_current_generation()
                raise HTTPException(
                    status_code=409,
                    detail="上一局尚未关闭完成，请稍后重试。",
                )

            # L3t
            if token != _menu_generation:
                _restore_old_if_current_generation()
                raise HTTPException(
                    status_code=409, detail="加载已取消（菜单状态已变更）。",
                )

            # L4–L5 构造 / 热替换：必须绑定已领取 opening 路径，禁重读可变全局路径。
            bound_path = opening_path or main_before or ""
            candidate = None
            candidate_entry: Optional[_HolderEntry] = None
            try:
                candidate = WebGame(fresh=False, db_path=bound_path or None)
                candidate.load_save(name)
            except LLMUnavailable as exc:
                if candidate is not None:
                    _close_unregistered(
                        candidate, getattr(candidate, "db_path", "") or bound_path,
                    )
                raise HTTPException(status_code=412, detail=_exception_detail(exc))
            except Exception:
                if candidate is not None:
                    _close_unregistered(
                        candidate, getattr(candidate, "db_path", "") or bound_path,
                    )
                raise

            cand_path = (
                getattr(candidate, "db_path", "") or bound_path
            )
            candidate_entry = _register_holder(cand_path, candidate)
            # #1749：发布前快照——opening 释放后 / 发布后 exit 可关库；响应不得再读活连接。
            # 准备失败（含快照）与代际取消共用未发布收口。
            published = False
            try:
                state_snapshot = candidate.state_payload()
                with _menu_lifecycle_lock:
                    if token == _menu_generation:
                        web_game = candidate
                        published = True
                if not published:
                    raise HTTPException(
                        status_code=409, detail="加载已取消（菜单状态已变更）。",
                    )
                return candidate, state_snapshot
            except Exception:
                if not published:
                    _discard_unpublished_candidate(
                        candidate, candidate_entry, cand_path,
                    )
                raise
        finally:
            _release_opening(opening_path)

    published_game, state_snapshot = await loop.run_in_executor(None, _load_work)
    # 与建局／换库同形：启动补跑预检故障上抛，不另包非致命策略。
    published_game._spawn_startup_extraction_catch_up()
    return {"state": state_snapshot}


@app.delete("/api/menu/saves/{name}")
async def api_menu_delete_save(name: str) -> Dict[str, Any]:
    """菜单页删存档：不依赖 WebGame 实例，直接删文件系统里的 <name>.db。
    与 WebGame.delete_save 共用模块级 _safe_save_name（#1902 单一真源），返回刷新后的 campaigns。"""
    cleaned = _safe_save_name(name)
    target = os.path.join(user_data_path("saves"), f"{cleaned}.db")
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="存档不存在。")
    os.remove(target)
    return {"saves": _scan_saves(), "campaigns": _scan_campaigns()}


@app.post("/api/menu/exit_to_menu")
async def api_menu_exit() -> Dict[str, Any]:
    """退回菜单：关 session 但不删 DB。

    #396：界面立刻退（web_game=None + 响应返回），后台 detach 关连接。
    #1732 T1：不搬主库；归档由后续 new_game AR-req 承接。
    #1749 r7：X1 lifecycle 摘指针；X2 定点 claim|E2_absent；X3 后台 E3；不 AR、无单槽 completion。
    """
    global web_game, _menu_generation
    loop = asyncio.get_running_loop()

    def _exit_work() -> Dict[str, Any]:
        global web_game, _menu_generation
        old_game = None
        with _menu_lifecycle_lock:
            # X1：解绑指针；旧局拒绝新操作靠 web_game=None + 定点退休。
            # seal 只在既有 drain（_drain_close_body）内做——#1842 禁正常退出另增 seal。
            _menu_generation += 1
            if web_game is not None:
                old_game = web_game
                web_game = None
        if old_game is not None:
            # X2/X3：定点退休，HTTP 不等待。E2_absent → 零新 drain（已由他方 A4 删除）。
            _point_retire_close(old_game)
        return {"ok": True}

    return await loop.run_in_executor(None, _exit_work)


@app.post("/api/menu/shutdown")
async def api_menu_shutdown() -> Dict[str, Any]:
    """退出整个游戏：关 session + 终止服务进程。前端收响应后自行关页面。

    #396：关进程前等队列把最后一句写完（owner decision：可能等一两秒，可接受），
    不在 worker 写时关连接。"""
    import os as _os
    import signal as _signal
    import threading as _threading
    global web_game
    if web_game is not None:
        old_game = web_game
        web_game = None
        # 关进程前等队列排空（#396 owner decision）。#1740：drain 失败已 logger 留痕，
        # 此处仍继续杀进程——关进程通道不得因关库失败而卡死。
        # #1749 r7：S1 同步通道；拆锁，不嵌套 lifecycle→path。
        def _shutdown_close() -> None:
            entry = _lookup_holder(_path_norm_of_game(old_game), old_game)
            if entry is not None:
                role, op = _claim_close(entry)
                if role == "executor" and op is not None:
                    _drain_and_close_session(
                        old_game, entry=entry, close_op=op,
                    )
                elif op is not None:
                    op.done.wait()
            else:
                _drain_and_close_session(old_game)

        try:
            await asyncio.get_running_loop().run_in_executor(None, _shutdown_close)
        except Exception as _caught_failure:
            logger.exception(
                "shutdown drain/close failed; continuing process exit error=%s",
                _caught_failure,
            )
    # 先返回响应，再异步终止进程。SIGTERM 在 *nix 走优雅退出；
    # Windows 无完整 SIGTERM 语义（pywebview 主线程也不收信号），直接 os._exit 兜底。
    def _kill_later() -> None:
        import sys as _sys
        import time as _time
        _time.sleep(0.3)
        if _sys.platform == "win32":
            _os._exit(0)
        else:
            _os.kill(_os.getpid(), _signal.SIGTERM)
    _threading.Thread(target=_kill_later, daemon=True).start()
    return {"ok": True}


class LlmSetupRequest(BaseModel):
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = API_DEFAULT_TIMEOUT_SECONDS
    thinking_level: str = ""
    advanced_model: str = ""
    advanced_base_url: str = ""
    advanced_api_key: str = ""
    advanced_thinking_level: str = ""
    reasoning_strength: str = ""
    channel: str = "api"
    cli_runner: str = ""
    cli_model: str = ""
    # 静默判死阈值（秒）：距上次新内容这么久没动静就判该次调用已死并重试（#1465 切片③）。
    cli_timeout_seconds: float = 0
    # #1794：设置页附加请求头表；None=保留档内，{}=清空。
    default_headers: Optional[Dict[str, str]] = None


async def _menu_save_cli_llm(request: LlmSetupRequest) -> Dict[str, Any]:
    """保存 CLI 通道：选 runner/model，不要求真实 api_key，保留 API 槽。"""
    cli_runner = (request.cli_runner or "").strip().lower()
    cli_model = (request.cli_model or "").strip()
    reasoning_strength = normalize_reasoning_strength(request.reasoning_strength)
    cli_timeout = request.cli_timeout_seconds if request.cli_timeout_seconds and request.cli_timeout_seconds > 0 else CLI_DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = request.timeout_seconds if request.timeout_seconds > 0 else API_DEFAULT_TIMEOUT_SECONDS
    if not cli_runner:
        raise HTTPException(status_code=400, detail="cli_runner 不能为空。")
    # #1902 N2：入口把表单映射成 channel/cli 槽，生效配置只走共核投影。
    config = _llm_config_from_runtime(
        {
            "channel": "cli",
            "cli": {
                "runner": cli_runner,
                "model": cli_model,
                "timeout_seconds": cli_timeout,
                "reasoning_strength": reasoning_strength,
            },
        },
        base_url="",
        model=cli_model,
        api_key="",
        timeout_seconds=timeout_seconds,
        thinking_level="",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )
    try:
        # CLI/API smoke 是阻塞子进程/网络调用(只要还在出字就一直跑,静默超 cli_timeout_seconds
        # 才判死重试),不能跑在 asyncio event loop 上卡死并发请求 → offload 到线程池(P1/P2)。
        # verify 只读不改盘面。
        await asyncio.get_running_loop().run_in_executor(
            None, _verify_llm_configs_or_raise, config
        )
    except HTTPException:
        raise
    except LLMUnavailable as exc:
        raise HTTPException(status_code=400, detail=_exception_detail(exc)) from exc
    # 空 API 输入 → save_runtime_llm 保留已存 API 槽（ADR 0001）。
    save_runtime_llm(
        "",
        "",
        "",
        timeout_seconds,
        "",
        "",
        "",
        "",
        "",
        channel="cli",
        cli_runner=cli_runner,
        cli_model=cli_model,
        cli_timeout_seconds=cli_timeout,
        reasoning_strength=reasoning_strength,
    )
    return {
        "ok": True,
        "llm": {
            "channel": "cli",
            "cli_runner": cli_runner,
            "cli_model": cli_model,
            "cli_timeout_seconds": cli_timeout,
            "reasoning_strength": reasoning_strength,
            "has_api_key": _has_real_api_key(config.api_key),
        },
    }


@app.post("/api/menu/llm")
async def api_menu_save_llm(request: LlmSetupRequest) -> Dict[str, Any]:
    """菜单页保存 LLM 配置：先发起轻量聊天校验，通过后才落盘。"""
    channel = (request.channel or "api").strip().lower()
    if channel not in VALID_CHANNELS:
        channel = "api"
    if channel == "cli":
        return await _menu_save_cli_llm(request)
    base_url = (request.base_url or "").strip()
    model = (request.model or "").strip()
    api_key = real_api_key_or_empty(request.api_key)  # 请求里的占位符不当真 key
    advanced_model = (request.advanced_model or "").strip()
    adv_base_in = (request.advanced_base_url or "").strip()
    advanced_base_url = normalize_openai_base_url(adv_base_in) if adv_base_in else ""
    advanced_api_key = (request.advanced_api_key or "").strip()
    timeout_seconds = request.timeout_seconds if request.timeout_seconds > 0 else API_DEFAULT_TIMEOUT_SECONDS
    thinking_level = normalize_thinking_level(request.thinking_level)
    advanced_thinking_level = ""
    reasoning_strength = normalize_reasoning_strength(request.reasoning_strength)
    if not (base_url and model):
        raise HTTPException(status_code=400, detail="base_url / model 不能为空。")
    existing = load_runtime_llm()
    existing_api = existing.get("api") if isinstance(existing.get("api"), dict) else {}
    if not api_key:
        for candidate in (existing_api.get("api_key"), os.environ.get("OPENAI_API_KEY", "")):
            if _has_real_api_key(candidate):
                api_key = str(candidate).strip()
                break
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key 未配置，请填写。")
    # advanced_api_key 留空：复用已存的（避免覆盖成空）。
    if advanced_model and not advanced_api_key:
        advanced_api_key = real_api_key_or_empty(existing_api.get("advanced_api_key")) or real_api_key_or_empty(os.environ.get("OPENAI_ADVANCED_API_KEY"))
    # #1794：请求体显式带头表则用之（含空表清空）；省略则装入档内头表。
    if request.default_headers is not None:
        default_headers = _slot_header_table(request.default_headers)
    else:
        default_headers = _slot_header_table(existing_api.get("default_headers"))
    normalized_base_url = normalize_openai_base_url(base_url)
    # #1902 N2：入口把表单/已存回落映射成 api 槽，生效配置只走共核投影。
    config = _llm_config_from_runtime(
        {
            "channel": "api",
            "api": {
                "base_url": normalized_base_url,
                "model": model,
                "api_key": api_key,
                "timeout_seconds": timeout_seconds,
                "thinking_level": thinking_level,
                "advanced_model": advanced_model,
                "advanced_base_url": advanced_base_url,
                "advanced_api_key": advanced_api_key,
                "advanced_thinking_level": advanced_thinking_level,
                "reasoning_strength": reasoning_strength,
                "default_headers": default_headers,
            },
        },
        base_url="",
        model="",
        api_key="",
        timeout_seconds=timeout_seconds,
        thinking_level=thinking_level,
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )
    try:
        # CLI/API smoke 是阻塞子进程/网络调用(只要还在出字就一直跑,静默超 cli_timeout_seconds
        # 才判死重试),不能跑在 asyncio event loop 上卡死并发请求 → offload 到线程池(P1/P2)。
        # verify 只读不改盘面。
        await asyncio.get_running_loop().run_in_executor(
            None, _verify_llm_configs_or_raise, config
        )
    except HTTPException:
        raise
    except LLMUnavailable as exc:
        raise HTTPException(status_code=400, detail=_exception_detail(exc)) from exc
    save_runtime_llm(
        normalized_base_url,
        model,
        api_key,
        timeout_seconds,
        thinking_level,
        advanced_model,
        advanced_base_url,
        advanced_api_key,
        advanced_thinking_level,
        channel="api",
        reasoning_strength=reasoning_strength,
        default_headers=default_headers,
    )
    return {
        "ok": True,
        "llm": {
            "base_url": normalized_base_url,
            "model": model,
            "has_api_key": _has_real_api_key(api_key),
            "timeout_seconds": timeout_seconds,
            "thinking_level": thinking_level,
            "advanced_model": advanced_model,
            "advanced_base_url": advanced_base_url,
            "has_advanced_api_key": _has_real_api_key(advanced_api_key),
            "advanced_thinking_level": "",
            "reasoning_strength": reasoning_strength,
            "default_headers": default_headers,
        },
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/game/state")
async def api_state() -> Dict[str, Any]:
    try:
        return get_game().state_payload()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_exception_detail(exc)) from exc


@app.post("/api/game/mechanical_tail/retry")
async def api_retry_mechanical_tail() -> Dict[str, Any]:
    from ming_sim.mechanical_tail import retry_failed_mechanical_tail

    game = get_game()
    with _serialized_web_write(game):
        if not retry_failed_mechanical_tail(game.session):
            raise HTTPException(status_code=409, detail="没有可重试的机械尾失败")
    return game.state_payload()


@app.post("/api/memorials/read")
async def api_memorials_read(body: Dict[str, Any]) -> Dict[str, Any]:
    """#1726：点开奏疏即已读；键绑具体奏报行，随存档持久化。"""
    keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(keys, list):
        keys = []
    clean = [str(k).strip() for k in keys if str(k or "").strip()]
    game = get_game()
    with _serialized_web_write(game):
        return game.mark_memorials_read(clean)


_PLAYER_CLOSED_SECRET_ORDER_STATUSES = frozenset({"done", "failed"})


def project_secret_orders_for_player(
    orders: List[Dict[str, Any]], status: str = "",
) -> List[Dict[str, Any]]:
    """玩家投影：结案成败收成同一档。账本 status 不动，奏报原文不动。

    先投影再过滤。按 done 或 failed 查询得到的是同一份已结案清单，
    不能凭「问 failed 有没有行」读出实际成败。
    """
    want = str(status or "").strip()
    if want in _PLAYER_CLOSED_SECRET_ORDER_STATUSES:
        want = "closed"
    projected: List[Dict[str, Any]] = []
    for order in orders:
        item = dict(order)
        if item.get("status") in _PLAYER_CLOSED_SECRET_ORDER_STATUSES:
            item["status"] = "closed"
        if want and item.get("status") != want:
            continue
        projected.append(item)
    return projected


@app.get("/api/secret_orders")
async def api_secret_orders(status: str = "") -> Dict[str, Any]:
    """列出密令的玩家投影。status 为空返回全部，否则按投影后的状态过滤。"""
    game = get_game()
    orders = project_secret_orders_for_player(
        game.db.character_knowledge.list_secret_orders(), status=status,
    )
    return {"orders": orders}


@app.get("/api/history/turns")
def api_history_turns() -> Dict[str, Any]:
    """场级归档列表；同步 handler 由 FastAPI 在线程池中执行 SQLite 投影。"""
    turns = get_game().db.list_archived_turns()
    return {"turns": turns}


@app.get("/api/history/turn/{turn}")
async def api_history_turn(turn: int) -> Dict[str, Any]:
    """某回合玩家历史：只交付邸报、诏书、已颁草案与独立递话原文。"""
    db = get_game().db
    archive = db.turn_reports.archive(turn)
    report = str((archive or {}).get("report") or "")
    attendant_message = str((archive or {}).get("attendant_message") or "")
    # #1843 reopen：本月诏书改读月链常驻的 pending_resolve_context.decree_text
    resolve_ctx = db.resolve_contexts.get(turn) or {}
    decree_text = str(resolve_ctx.get("decree_text") or "")
    directives = db.issues.list_directives_by_turn(turn)
    # exists：report/递话纯空白与空串同属缺席（临时 strip）；payload 仍回原文
    if (
        not str(report or "").strip()
        and not str(attendant_message or "").strip()
        and not str(decree_text or "").strip()
        and not directives
    ):
        return {"turn": turn, "exists": False}
    if directives:
        year = directives[0]["year"]
        period = directives[0]["period"]
    elif archive is not None:
        year = archive["year"]
        period = archive["period"]
    else:
        year = 0
        period = 0
    return {
        "turn": turn,
        "exists": True,
        "year": year,
        "period": period,
        "report": report,
        "attendant_message": attendant_message,
        "decree_text": decree_text,
        "directives": directives,
    }


# #1902：GET /api/map 与 GET /api/buildings 退役——前端零调用；地图节点随
# state_payload.map_nodes 下发（1851），省份建筑随 state_payload.buildings（1489）。


@app.post("/api/favorites/{minister_name}")
async def api_add_favorite(minister_name: str) -> Dict[str, Any]:
    game = get_game()
    if minister_name not in game.content.characters:
        raise HTTPException(status_code=404, detail=f"未找到：{minister_name}")
    with _serialized_web_write(game):
        game.favorites.add(minister_name)
        game.db.reign.kv_set("favorites", json.dumps(sorted(game.favorites)))
    return {"favorites": sorted(game.favorites)}


@app.delete("/api/favorites/{minister_name}")
async def api_remove_favorite(minister_name: str) -> Dict[str, Any]:
    game = get_game()
    with _serialized_web_write(game):
        game.favorites.discard(minister_name)
        game.db.reign.kv_set("favorites", json.dumps(sorted(game.favorites)))
    return {"favorites": sorted(game.favorites)}


_STATUS_LABEL_WEB = {
    # #1683：active 是广义在事/官印态（ADR 0009），不是物理「在朝」
    "active": "在事", "offstage": "尚未登场", "dead": "已殁", "dismissed": "已罢黜",
    "imprisoned": "下狱", "exiled": "流放", "retired": "致仕",
}


@app.get("/api/audience/scroll")
def api_audience_scroll(night_id: int = 0) -> Dict[str, Any]:
    """Shared live/read-only projection of one persisted audience scroll."""
    from ming_sim.audience_night import get_night, get_open_night, presence_roster, read_night_scroll, night_scroll_container, list_ledger, list_chat_turns_for_night
    game = get_game()
    night = get_night(game.db, night_id) if night_id else get_open_night(game.db)
    if night is None:
        return {
            "night_id": 0, "status": "", "messages": [], "protagonist": "",
            "roster": [], "translation_pending": False, "translation_retries": [],
            "pending_translation_turn_ids": [], "reply_retries": [],
        }
    roster = presence_roster(game.db, int(night["id"]))
    protagonist = str(night.get("protagonist_name") or "")
    messages = read_night_scroll(game.db, int(night["id"]))
    container = night_scroll_container(night, list_ledger(game.db, int(night["id"])), list_chat_turns_for_night(game.db, int(night["id"])))
    names = list(dict.fromkeys(
        [entry["name"] for entry in roster]
        + ([protagonist] if protagonist else [])
        + [message["speaker"] for message in messages if message["role"] in {"minister", "attendant"} and message["speaker"]]
    ))
    characters = getattr(getattr(game, "content", None), "characters", {})
    pending_replies = game.db.reign.list_unextracted_replies(night_id=int(night["id"]))

    return {
        "night_id": int(night["id"]),
        "status": night["status"],
        "messages": messages,
        "container": container,
        "protagonist": protagonist,
        "roster": roster,
        "characters": [game.public_character(characters[name]) for name in names if name in characters],
        "translation_pending": bool(pending_replies),
        "pending_translation_turn_ids": [int(row["chat_turn_id"]) for row in pending_replies],
        "translation_retries": game.pending_translation_retries(night_id=int(night["id"])),
        "reply_retries": game.session.pending_audience_recovery_retries(night_id=int(night["id"])),
    }


@app.get("/api/audience/chat")
async def api_audience_chat_history() -> Dict[str, Any]:
    """Live audience state belongs to the open scene, never to a roster member."""
    game = get_game()
    from ming_sim.audience_night import SCENE_CHAT_SPEAKER, get_open_night
    open_night = get_open_night(game.db)
    return {
        "minister": {
            "name": SCENE_CHAT_SPEAKER, "office": "一夜一卷", "office_type": "scene",
            "faction": "", "style": "", "status": "active", "status_label": "在殿",
            "summary": "", "favorite": False,
        },
        "campaign_id": str(game.db.reign.kv_get("campaign_id") or ""),
        "night_id": int(open_night["id"]) if open_night else 0,
        "history": game.chat_projection(),
        "can_undo_last_chat": game.can_undo_last_chat(SCENE_CHAT_SPEAKER),
        "reply_retries": game.reply_retries(SCENE_CHAT_SPEAKER),
        "generating_turn_ids": [int(r["id"]) for r in game.db.reign.list_in_flight_chat_turns(
            night_id=int(open_night["id"]) if open_night else None,
            minister_name=SCENE_CHAT_SPEAKER,
        )],
        "translation_retries": game.pending_translation_retries(
            night_id=int(open_night["id"]) if open_night else None,
        ),
    }


# #1902：非流式 POST /api/audience/chat 退役——说话只有流式一条入口（/api/audience/chat/stream）；前端自 #1842 起零调用此路，两条同源入口会把同一编排复制两份。GET /api/audience/chat（召对历史读面）不受影响。

@app.post("/api/audience/reply/retry")
async def api_retry_audience_reply(chat_turn_id: int = Body(0, embed=True)) -> Dict[str, Any]:
    from ming_sim.audience_night import AudienceNightError, SCENE_CHAT_SPEAKER
    try:
        return await run_in_threadpool(get_game().retry_interrupted_reply, SCENE_CHAT_SPEAKER, chat_turn_id or None)
    except AudienceNightError as exc:
        raise _retryable_audience_close_http(exc) from exc


@app.post("/api/audience/chat/undo")
async def api_undo_audience_chat() -> Dict[str, Any]:
    from ming_sim.audience_night import SCENE_CHAT_SPEAKER
    game = get_game()
    _refuse_if_open_night_barrier(game)
    with _serialized_web_write(game):
        return game.undo_last_chat(SCENE_CHAT_SPEAKER, gate_held=True)


class TranslationRetryRequest(BaseModel):
    chat_turn_id: int


@app.post("/api/audience/translation/retry")
async def api_retry_pending_translation(
    request: TranslationRetryRequest,
) -> Dict[str, Any]:
    """#1842：只补对应源轮的转译重试（catch_up 按轮收窄；不做页面）。"""
    game = get_game()
    return await run_in_threadpool(
        game.retry_pending_translation, int(request.chat_turn_id),
    )


def _chat_stream_response(minister_name: str, request: ChatRequest) -> StreamingResponse:
    iterator = iter(get_game().chat_stream(minister_name, request.message))

    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, _next_or_none, iterator)
            except Exception as exc:
                yield sse_event("error", _exception_detail(exc))
                return
            if item is None:
                break
            item_type = str(item.get("type", "message"))
            if item_type == "accepted":
                yield sse_event("accepted", {
                    "campaign_id": item.get("campaign_id", ""),
                    "night_id": item.get("night_id", 0),
                    "chat_turn_id": item.get("chat_turn_id", 0),
                })
            elif item_type == "protagonist_changed":
                yield sse_event("protagonist_changed", {})
            elif item_type == "delta":
                delta_payload: Dict[str, Any] = {"content": item.get("content", "")}
                if item.get("replace"):
                    delta_payload["replace"] = True
                yield sse_event("delta", delta_payload)
            elif item_type == "done":
                yield sse_event("done", item.get("payload", {}))
            elif item_type == "highlights":
                # #544：流完补挂高亮清单
                yield sse_event("highlights", {
                    "highlights": item.get("highlights") or [],
                    "chat_turn_id": item.get("chat_turn_id") or 0,
                    "message_id": item.get("message_id") or 0,
                })
            elif item_type == "end":
                yield sse_event("end", {})
                break
            elif item_type == "error":
                detail = item.get("detail") or item
                payload = dict(detail) if isinstance(detail, dict) else {"message": str(detail)}
                # #1902：结构化拒收的 code 必须过 SSE 终态（前端 normalizeApiError 与
                # 测试都按它分流；旧非流式路由把它放在 HTTP detail 里，迁流式不得丢）。
                if item.get("code") and not payload.get("code"):
                    payload["code"] = str(item.get("code"))
                payload.update({
                    "campaign_id": item.get("campaign_id", ""),
                    "night_id": item.get("night_id", 0),
                    "chat_turn_id": item.get("chat_turn_id", 0),
                })
                yield sse_event("error", payload)
                break

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/audience/chat/stream")
async def api_audience_chat_stream(request: ChatRequest) -> StreamingResponse:
    """Scene-level live transport; the scene LLM chooses who answers."""
    from ming_sim.audience_night import SCENE_CHAT_SPEAKER
    return _chat_stream_response(SCENE_CHAT_SPEAKER, request)


# #1902 / #1812 待拍第 6 项：拟诏台手写入口全退——POST|PATCH /api/directives 不再注册。
# 旨意只从召对来（#1772）；草稿可见、已发追溯与删旧草稿（DELETE）保留，旧草稿去向
# 由 #1826 的草稿与已发记录承接。共享抽取核未删：成案准入补交
# （session._resubmit_draft_admission_failures）仍是它的现役消费者。


@app.delete("/api/directives/{directive_id}")
async def api_delete_directive(directive_id: int) -> Dict[str, Any]:
    game = get_game()
    try:
        # #1749：同 create/update——删除后列表投影在 gate 内完成。
        with _serialized_web_write(game):
            game.session.delete_directive(directive_id)
            return {
                "directives": [
                    game.directive_payload(item) for item in game.directive_rows()
                ],
            }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=_exception_detail(e)) from e


@app.post("/api/decree/advance_without_edict")
def api_advance_without_edict(
    body: AdvanceWithoutEdictRequest = AdvanceWithoutEdictRequest(),
) -> Dict[str, Any]:
    # #498 AC10 / #1353：内部屏障票据同步等在飞尾随终态。
    game = get_game()
    from ming_sim.audience_night import AudienceNightError
    try:
        with _settlement_period_entry(game, write_cm=_serialized_web_write):
            _reject_stale_month_token(game, body.expected_turn, token_label="退朝")
            settlement_result = game.session.advance_without_decree(
                write_gate_already_held=True,
            )
            awaiting = bool(
                settlement_result is not None and settlement_result.awaiting
            )
            advanced = bool(
                settlement_result is not None
                and not awaiting
                and settlement_result.advanced
            )
            if advanced:
                game.session.end_turn()
                game.refresh_turn()
            return {
                "state": game.state_payload(),
                "awaiting_decision": awaiting,
                "advanced": advanced,
                "decisions": (
                    settlement_result.decisions
                    if settlement_result is not None and settlement_result.awaiting
                    else []
                ),
            }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_exception_detail(e)) from e
    except SettlementAbort as e:
        raise HTTPException(
            status_code=409,
            detail=_exception_detail(e),
        ) from e
    except (AudienceNightError, ExceptionGroup) as e:
        raise _retryable_audience_close_http(e) from e
    except LLMUnavailable as e:
        raise HTTPException(status_code=412, detail=_exception_detail(e)) from e


# #1341/#1338：PATCH /api/decree 已删（web/src 零真实调用方；裸设总诏绕过 directives
# 结构化违 P1）。OpenAPI 随路由消失。改稿只走 PATCH /api/directives/{id}。


class IssueDecreeRequest(BaseModel):
    # 作弊控制台（Ctrl+~）下的强制结算项；一次性，颁诏即用。普通颁诏留空。
    cheat: str = ""
    # #1277/#1351：可选回合令牌；缺省兼容无令牌旧客户端。与 advance_without_edict 同口径。
    expected_turn: Optional[int] = None


def _reject_stale_month_token(game, expected_turn: Optional[int], *, token_label: str) -> None:
    """获锁后、resolve_turn 前：expected_turn 与当前月份不一致 → 人话 409（含当前 turn）。

    #1351 advance / #1277 issue 主路共用；缺省令牌=不比对（兼容旧客户端）。
    """
    if expected_turn is None:
        return
    current_turn = int(getattr(game.state, "turn", 0) or 0)
    if current_turn != int(expected_turn):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"月份已变更（当前第 {current_turn} 月），"
                    f"与{token_label}令牌不符，请刷新后再试。"
                ),
                "turn": current_turn,
            },
        )


# #1902：非流式 POST /api/decree/issue 退役——颁布只有流式一条入口
# （/api/decree/issue/stream），两条同源入口把同一编排复制一份。此路由曾独有
# 的 typed 失败面已补进 SSE 终态：SettlementAbort 带 status_code=409 + stage +
# error_pack_path 与真实 LLM 原因统一经 _exception_detail。

@app.post("/api/decree/issue/stream")
async def api_issue_decree_stream(body: IssueDecreeRequest = IssueDecreeRequest()) -> StreamingResponse:
    """流式颁诏：终态（done / decisions / error）经 SSE 推给前端。

    #1852：worker 只投终态。#1853 J5：不附 failed 密令专属载荷。
    """
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def worker() -> None:
        try:
            game = get_game()
            terminal: Optional[tuple[str, Any]] = None
            with _settlement_period_entry(game, write_cm=_game_write_gate):
                _reject_stale_month_token(game, body.expected_turn, token_label="颁诏")
                result = game.session.resolve_turn(
                    cheat_directive=body.cheat,
                    write_gate_already_held=True,
                )
                decree = game.session.last_decree
                if result.awaiting:
                    terminal = ("__decisions__", _settlement_player_payload(
                        decree=decree,
                        decisions=result.decisions,
                    ))
                else:
                    report = result.report
                    advanced = bool(getattr(result, "advanced", True))
                    if advanced:
                        game.session.end_turn()
                        game.refresh_turn()
                    terminal = ("__done__", _settlement_player_payload(
                        decree=decree,
                        report=report,
                        advanced=advanced,
                    ))
            if terminal is not None:
                ev_queue.put(terminal)
        except ValueError as e:
            # exit/end 已由 _settlement_period_entry 在异常路径完成（若已 begin）。
            ev_queue.put(("__error__", _exception_detail(e)))
        except HTTPException as e:
            detail = e.detail
            if isinstance(detail, dict):
                payload = dict(detail)
                payload.setdefault("status_code", e.status_code)
                ev_queue.put(("__error__", payload))
            else:
                ev_queue.put((
                    "__error__",
                    {"message": str(detail), "status_code": e.status_code},
                ))
        except Exception as e:  # noqa: BLE001
            # #1235：真失败另形——helper 已 exit（含 AudienceNightError / SettlementAbort）。
            # #1465 ②：message 标量 + typed 键外层；与 resolve_decisions/stream 同真源。
            # #1853 J5：真异常经本口上抛；不以 failed 行另造 pending_action_failures。
            ev_queue.put(("__error__", _exception_detail(e)))

    async def generate() -> AsyncIterator[str]:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        loop = asyncio.get_running_loop()
        while True:
            kind, data = await loop.run_in_executor(None, ev_queue.get)
            if kind == "__done__":
                yield sse_event("done", data)
                break
            if kind == "__decisions__":
                yield sse_event("decisions", data)
                break
            if kind == "__error__":
                yield sse_event("error", data if isinstance(data, dict) else {"message": data})
                break

    return StreamingResponse(generate(), media_type="text/event-stream")


class ResolveDecisionsRequest(BaseModel):
    # #1589：皇帝亲裁结果，每项须显式携带 decision_key（{decision_key, label, hint?, note?}）；
    # 缺键/重复键/desk 外键整批拒绝，不落任何领域写。dossier 批红另须带
    # dossier_id/dossier_decision（#1490，非法不落 decided）。
    choices: List[Dict[str, Any]] = []
    cheat: str = ""


@app.post("/api/decree/resolve_decisions/stream")
async def api_resolve_decisions_stream(body: ResolveDecisionsRequest) -> StreamingResponse:
    """皇帝亲裁完决策点，流式跑 phase2 结算。#1853 J5：不附 failed 密令专属载荷。"""
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def worker() -> None:
        try:
            game = get_game()
            turn_before = int(game.state.turn)
            if game.session.current_phase() != TurnPhase.AWAITING_DECISION:
                raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")
            terminal: Optional[tuple[str, Any]] = None
            with _settlement_period_entry(
                game, write_cm=_game_write_gate, hold_write_for_body=False,
            ):
                report = game.session.submit_hitl_choices(
                    body.choices,
                    write_gate=_game_write_gate(game),
                    cheat_directive=body.cheat,
                )
                decree = game.session.last_decree
                with _game_write_gate(game):
                    advanced = int(game.state.turn) != turn_before
                    if advanced:
                        game.session.end_turn()
                        game.refresh_turn()
                terminal = ("__done__", _settlement_player_payload(
                    decree=decree,
                    report=report,
                    advanced=advanced,
                ))
            if terminal is not None:
                ev_queue.put(terminal)
        except ValueError as e:
            # exit/end 已由 _settlement_period_entry 在异常路径完成（若已 begin）。
            ev_queue.put(("__error__", _exception_detail(e)))
        except Exception as e:  # noqa: BLE001
            # §5.4：无独立 HTTP/AudienceNight 分表；与 issue/stream 同真源。
            # #1465 ②：SettlementAbort.__cause__ LLMUnavailable 亦外层保真 typed 键。
            # #1853 J5：真异常经本口上抛；不以 failed 行另造 pending_action_failures。
            ev_queue.put(("__error__", _exception_detail(e)))

    async def generate() -> AsyncIterator[str]:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        loop = asyncio.get_running_loop()
        while True:
            kind, data = await loop.run_in_executor(None, ev_queue.get)
            if kind == "__done__":
                yield sse_event("done", data)
                break
            if kind == "__error__":
                yield sse_event("error", data if isinstance(data, dict) else {"message": data})
                break

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/saves")
async def api_list_saves() -> Dict[str, Any]:
    return {"saves": get_game().list_saves()}
