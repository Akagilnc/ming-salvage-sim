#!/usr/bin/env python3
"""FastAPI web entry for Ming Salvage Sim.

薄壳：路由调 ming_sim.session.GameSession（与 CLI 共用同一流转层）。
拟旨候选：大臣 propose_directive/前缀/自然语言 → pending_actions 闸门 → 对话确认或颁诏默认同意。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import queue
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import threading
from concurrent.futures import Future
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Literal, Optional

# 源码模式 `uvicorn web_app:app` 在 nohup/重定向（>> web_server.log）下 Python stdout 块缓冲，
# 日志滞后数分钟、结算中段 tail 看不见进度（#84）。强制行缓冲让 tlog + 各 print 近实时落盘；
# TTY 下本就行缓冲、无变化。frozen 打包路径已由 launcher.py 处理，此处覆盖源码 uvicorn 路径。
try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    if sys.stderr is not None:
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 — 缓冲设置失败不该阻断 web 启动
    pass

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ming_sim.applier import atomic
from ming_sim.constants import ROOT_DIR
from ming_sim.paths import bundled_path, user_data_path, user_data_dir
from ming_sim.exceptions import ExitGame, LLMUnavailable, SettlementAbort
from ming_sim.llm_config import (
    CLI_DEFAULT_TIMEOUT_SECONDS,
    VALID_CHANNELS,
    cli_model_from_env,
    is_real_api_key,
    api_supports_reasoning_strength,
    cli_supports_reasoning_strength,
    REASONING_STRENGTH_CHOICES,
    real_api_key_or_empty,
    load_llm_config,
    load_runtime_llm,
    normalize_openai_base_url,
    normalize_thinking_level,
    normalize_reasoning_strength,
    legacy_reasoning_strength,
    save_runtime_llm,
)
from ming_sim.agents import _dump_llm_messages
from ming_sim.llm_model import extract_agent_text, llm_stream_unavailable, verify_llm_available
from ming_sim.llm_contract import fail_if_llm_error
from ming_sim.issues import _format_issue_ongoing, commitment_display_text, commitment_progress_payload, commitment_timed_bar_value
from ming_sim.session import GameSession
from ming_sim.session import (
    AUTO_SAVE_PREFIX,
    AudienceAdmission,
    _is_summonable_court_minister,
    _pending_action_failure_payload,
    coalesce_pending_action_id,
)
from ming_sim.audience_pipeline import run_mindreading_for_turn
from ming_sim.relation_judge import run_summon_relation_judge
from ming_sim.highlight_judge import (
    DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
    run_highlight_judge,
)
from ming_sim.audience_extraction import (
    catch_up_pending_extractions,
    trail_extraction_after_reply,
)
from ming_sim.session_write_queue import (
    SessionWriteQueue,
    TicketCancelled,
    TicketedWriteGate,
    WriteTicket,
    get_session_write_queue,
)
from ming_sim.token_stats import tlog
from ming_sim.skills import available_skill_ids, skill_display_name, skill_source_labels
from ming_sim.context import match_minister_from_text
from ming_sim.flows import compute_budget_lines
from ming_sim.exceptions import LLMContractError  # noqa: F401  (保留：供错误处理)
from ming_sim.models import (
    API_DEFAULT_TIMEOUT_SECONDS,
    Character,
    FRONT_HALF_DONE_PHASES,
    LLMConfig,
    TurnPhase,
    loads_effect_dict,
    reign_period_label,
)
from ming_sim import steam_events

logger = logging.getLogger(__name__)

WEB_DIST = bundled_path("web", "dist")
# 用户上传的自定义立绘存档级目录（不随 build 清空，git 可忽略）。
# frozen 模式落 ~/.ming_sim/uploads/portraits/，源码模式落 <repo>/data/uploads/portraits/。
UPLOAD_PORTRAIT_DIR = user_data_path("uploads", "portraits")
# 自定义立绘 portrait_id 前缀；前端据此解析到 /portraits/custom/<name>.png。
CUSTOM_PORTRAIT_PREFIX = "custom:"
ALLOWED_PORTRAIT_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_PORTRAIT_BYTES = 8 * 1024 * 1024  # 8MB 上限

# resolve/fail_condition 同时喂 extractor（需 input.factions/leverage 等技术 key）与展示给玩家。
# 展示前把技术词替换成中文，原文不动（LLM 仍读原文判定）。按长键先替，避免子串误伤。
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
    """把结案/失败条件里的技术 key 替换成玩家可读中文（仅用于展示）。"""
    if not text:
        return text
    character_condition = re.fullmatch(
        r"\s*character\.([^.]+)\.([A-Za-z_]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*",
        text,
    )
    if character_condition:
        name, field, op, value = character_condition.groups()
        if field == "loyalty" and re.fullmatch(r"\d+", value):
            if op in {">=", ">"}:
                return f"{name}忠诚回稳"
            if op in {"<=", "<"}:
                return f"{name}忠诚未稳"
            return f"{name}忠诚非通常阈值"
        label = _CHARACTER_CONDITION_FIELD_LABELS.get(field, field)
        op_label = _CONDITION_OPERATOR_LABELS.get(op, op)
        value_label = _humanize_condition_value(field, value)
        return f"{name}{label}{op_label}{value_label}"
    for src, dst in _CONDITION_DISPLAY_REPLACEMENTS:
        text = text.replace(src, dst)
    return text


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
    for account in ("国库", "内库", "民心", "皇威"):
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


def _delete_sqlite_db_files_or_raise(db_path: str) -> None:
    """删除 SQLite 主库及 WAL/SHM；失败时阻断重开，避免误读旧档。"""
    for suffix in ("", "-wal", "-shm"):
        target = db_path + suffix
        if not os.path.exists(target):
            continue
        if not os.path.isfile(target):
            raise HTTPException(
                status_code=500,
                detail=f"重开失败：无法清理主库文件 {target}，它不是普通文件。请检查该路径后再重试。",
            )
        try:
            os.remove(target)
        except PermissionError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"重开失败：权限不足，无法删除主库文件 {target}。"
                    "请关闭占用该文件的程序，或用管理员权限运行游戏后重试。"
                ),
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"重开失败：无法删除主库文件 {target}。系统返回：{exc}。"
                    "请确认没有其他游戏进程占用该文件；若是权限问题，请用管理员权限运行游戏后重试。"
                ),
            ) from exc


def _verify_llm_configs_or_raise(config: LLMConfig) -> None:
    """校验主模型；若配置了 advanced_model，也用其实际 base/key 单独校验。"""
    try:
        verify_llm_available(config)
    except LLMUnavailable as e:
        raise HTTPException(status_code=400, detail=_llm_error_detail(e, "主模型连通性检查失败：")) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_llm_error_detail(e, "主模型连通性检查失败：")) from None

    advanced_model = (config.advanced_model or "").strip()
    if not advanced_model:
        return
    advanced_config = LLMConfig(
        api_key=real_api_key_or_empty(config.advanced_api_key) or real_api_key_or_empty(config.api_key),
        base_url=(config.advanced_base_url or "").strip() or config.base_url,
        model=advanced_model,
        timeout_seconds=config.timeout_seconds,
        thinking_level="",
        advanced_model=config.advanced_model,
        advanced_base_url=config.advanced_base_url,
        advanced_api_key=config.advanced_api_key,
        advanced_thinking_level="",
        reasoning_strength=config.reasoning_strength,
        channel=config.channel,
        cli_runner=config.cli_runner,
        cli_model=config.cli_model,
        cli_timeout_seconds=config.cli_timeout_seconds,
    )
    try:
        verify_llm_available(advanced_config)
    except LLMUnavailable as e:
        raise HTTPException(status_code=400, detail=_llm_error_detail(e, "高级模型连通性检查失败：")) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_llm_error_detail(e, "高级模型连通性检查失败：")) from None


def _llm_error_detail(exc: Exception, prefix: str = "") -> Dict[str, Any]:
    message = f"{prefix}{exc.message if hasattr(exc, 'message') else str(exc)}"
    return {
        "code": getattr(exc, "code", "llm_error"),
        "message": message,
        "provider_message": getattr(exc, "provider_message", str(exc)),
        "status_code": getattr(exc, "status_code", None),
    }


def _runtime_float(value: object, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _has_real_api_key(value: object) -> bool:
    # 单一真源在 llm_config.is_real_api_key；此处只做 web 层薄包装。
    return is_real_api_key(value)


def _llm_config_from_runtime(
    runtime: Dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float,
    thinking_level: str,
    advanced_model: str,
    advanced_base_url: str,
    advanced_api_key: str,
    advanced_thinking_level: str,
) -> LLMConfig:
    from ming_sim.cli_backend import cli_backend_from_env

    channel = str(runtime.get("channel") or "").strip().lower()
    env_runner = cli_backend_from_env()
    if channel not in VALID_CHANNELS:
        channel = "cli" if env_runner else "api"
    cli_slot = runtime.get("cli") if isinstance(runtime.get("cli"), dict) else {}
    cli_runner = str(cli_slot.get("runner") or env_runner or ("agy" if channel == "cli" else "")).strip().lower()
    cli_model = str(cli_slot.get("model") or cli_model_from_env(cli_runner, model)).strip()
    legacy_reasoning = (
        legacy_reasoning_strength({
            "advanced_model": advanced_model,
            "advanced_thinking_level": advanced_thinking_level,
            "thinking_level": thinking_level,
        })
        if channel != "cli"
        else ""
    )
    reasoning_strength = normalize_reasoning_strength(
        (cli_slot.get("reasoning_strength") if channel == "cli" else runtime.get("reasoning_strength"))
        or runtime.get("reasoning_strength", "")
    ) or legacy_reasoning
    # 无 saved CLI timeout 时回落 CLI 默认（300），不回落 API request timeout（codex R1 #3）。
    cli_timeout = _runtime_float(cli_slot.get("timeout_seconds"), CLI_DEFAULT_TIMEOUT_SECONDS)
    if channel == "cli":
        api_key = ""  # CLI 通道不要 API key；占位符在 create_chat_model 构造 CliChat 时注入
    elif not is_real_api_key(api_key):
        # 占位符不当真 key：清空让下游空检查报「未配 API key」，
        # 而不是拿假 key 去探 OpenAI（误导性 412）。
        api_key = ""
    return LLMConfig(
        api_key=api_key,
        base_url=normalize_openai_base_url(base_url),
        model=model,
        timeout_seconds=timeout_seconds,
        thinking_level=normalize_thinking_level(thinking_level),
        advanced_model=(advanced_model or "").strip(),
        advanced_base_url=normalize_openai_base_url(advanced_base_url) if advanced_base_url else "",
        advanced_api_key=real_api_key_or_empty(advanced_api_key),
        advanced_thinking_level="",
        reasoning_strength=reasoning_strength,
        channel=channel,
        cli_runner=cli_runner,
        cli_model=cli_model,
        cli_timeout_seconds=cli_timeout,
    )


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
    intent: Optional[Literal["secret_order"]] = None


class DirectiveRequest(BaseModel):
    text: str
    notes: str = ""


class SecretOrderRequest(BaseModel):
    title: str
    content: str
    tags: List[str] = []
    deadline_months: int = 0


class DirectivePatch(BaseModel):
    text: Optional[str] = None
    notes: Optional[str] = None


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
    与 list_ministers/can_summon/CLI/事实块同口径，禁另造过滤表。resolve 惰性入参，
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
    if db.get_character_status(character.name)[0] == "offstage":
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

    范围说明：此函数是 ADR 0009 域内人才池 simulation._talent_pool_rows 的 **UI 子集**——后者覆盖
    offstage/retired/dismissed/听用候铨被顶替全部可起复者，而 dismissed/retired/imprisoned 等在朝
    转出的非 active 已在朝堂「全部」栏可见（visible_in_court 只挡 offstage），故 UI 人才池只补
    offstage 这一漏面，两者口径不同、勿等同。"""
    if character.office_type in ("后宫", "宗藩", "未仕"):
        return False
    if getattr(character, "faction", "") == "流寇":
        return False
    if db.get_character_status(character.name)[0] != "offstage":
        return False
    debut_year = int(getattr(character, "debut_year", 0) or 0)
    debut_month = int(getattr(character, "debut_month", 0) or 0)
    if debut_year > current_year or (debut_year == current_year and debut_month > current_period):
        return False
    return _character_power_id(character, db) == "ming"


def _audience_prompt_for_web_chat(session: Any, text: str, character: Character, chat_turn_id: int) -> str:
    """Build a minister prompt without mistaking production failures for legacy APIs.

    Lightweight test doubles may still expose the old one-argument builder.
    Choose that compatibility path by binding its signature *before* invoking
    it, so a TypeError raised inside the real per-character builder propagates
    to the normal chat-turn rollback path instead of causing an unscoped retry.
    """
    prompt_builder = getattr(session, "_audience_prompt_for_message", None)
    if prompt_builder is None:
        return text
    signature = inspect.signature(prompt_builder)
    try:
        signature.bind(text, character, chat_turn_id=chat_turn_id)
    except TypeError:
        signature.bind(text)
        return prompt_builder(text)
    return prompt_builder(text, character, chat_turn_id=chat_turn_id)


class WebGame:
    """Web 端会话包装：持一个 GameSession + 网页专属态（聊天历史、收藏）。"""

    def __init__(self, fresh: bool = False, on_stage: Optional[Callable[[str], None]] = None) -> None:
        """实例化 = 真正进入游戏。无 API key 直接抛 LLMUnavailable。
        fresh=True：先清空主 DB（新游戏）再建 session。
        on_stage：#1195 可选阶段回调（仅推叙事文案，不改 GameSession 初始化序）。"""
        def _stage(label: str) -> None:
            if on_stage is not None:
                on_stage(label)

        db_path = _get_main_db_path()
        if not os.path.isabs(db_path):
            db_path = str(user_data_dir() / db_path)
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        advanced_model = os.environ.get("OPENAI_ADVANCED_MODEL", "")
        advanced_base_url = os.environ.get("OPENAI_ADVANCED_BASE_URL", "")
        advanced_api_key = os.environ.get("OPENAI_ADVANCED_API_KEY", "")
        thinking_level = os.environ.get("OPENAI_THINKING_LEVEL", "")
        advanced_thinking_level = os.environ.get("OPENAI_ADVANCED_THINKING_LEVEL", "")
        timeout_seconds = float(os.environ.get("OPENAI_TIMEOUT_SECONDS") or API_DEFAULT_TIMEOUT_SECONDS)
        # 菜单写的 runtime_llm.json 优先于 env，让"在网页里改的配置"重启后仍生效。
        runtime = load_runtime_llm()
        base_url = runtime.get("base_url") or base_url
        model = runtime.get("model") or model
        # 占位符不当真 key：stale cli-backend 不该覆盖真实 env key（否则 api 通道
        # 启动被清空报「未配 API key」，而 menu 用 env key 判 ready，二者矛盾）。
        _rt_api_key = runtime.get("api_key")
        api_key = _rt_api_key if is_real_api_key(_rt_api_key) else api_key
        thinking_level = runtime.get("thinking_level") or thinking_level
        advanced_model = runtime.get("advanced_model") or advanced_model
        advanced_base_url = runtime.get("advanced_base_url") or advanced_base_url
        advanced_api_key = real_api_key_or_empty(runtime.get("advanced_api_key")) or advanced_api_key
        advanced_thinking_level = runtime.get("advanced_thinking_level") or advanced_thinking_level
        timeout_seconds = float(runtime.get("timeout_seconds") or timeout_seconds)
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
            _delete_sqlite_db_files_or_raise(db_path)
        _stage("载入上次进度...")
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
        for name, msgs in self.db.load_all_chat_history().items():
            self.chat_history.setdefault(name, []).extend(msgs)
        _DEFAULT_FAVORITES = {"王承恩", "曹化淳", "李若琏", "魏忠贤", "田尔耕"}
        _fav_raw = self.db.kv_get("favorites")
        self.favorites: set = set(json.loads(_fav_raw)) if _fav_raw else set(_DEFAULT_FAVORITES)
        if not _fav_raw:
            self.db.kv_set("favorites", json.dumps(sorted(self.favorites)))
        # #505：重开对账——上一进程崩溃遗留的在飞回话轮终态化（问话保留 + 可重试，永不删账）。
        # 解除在飞判定，使续问/收夜不被崩溃孤儿轮永久挡死（ADR 0036）。同步、先于后台补跑。
        if hasattr(self.db, "conn"):
            self.db.reconcile_interrupted_chat_turns()
        # #501：重开后补跑崩溃窗口里丢的叙事抽取账（后台、从不锁档）。
        self._spawn_startup_extraction_catch_up()

    # ── 存档管理 ─────────────────────────────────────────────────────────
    def saves_dir(self) -> str:
        return user_data_path("saves")

    def list_saves(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        campaign_id = (self.db.kv_get("campaign_id") or "").strip()
        for fname in sorted(os.listdir(self.saves_dir())):
            if not fname.endswith(".db"):
                continue
            if not _save_visible_for_campaign(fname, campaign_id):
                continue
            full = os.path.join(self.saves_dir(), fname)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append({
                "name": fname[:-3],
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
        out.sort(key=lambda x: x["mtime"], reverse=True)
        return out

    def _safe_save_name(self, name: str) -> str:
        cleaned = "".join(c for c in name.strip() if c.isalnum() or c in "._-")
        if not cleaned or cleaned.startswith("."):
            raise HTTPException(status_code=400, detail="存档名非法。仅允许字母/数字/._- ")
        return cleaned

    def save_to(self, name: str) -> Dict[str, Any]:
        safe = self._safe_save_name(name)
        target = os.path.join(self.saves_dir(), f"{safe}.db")
        self.db.backup_to(target)
        return {"name": safe, "path": target}

    def delete_save(self, name: str) -> None:
        safe = self._safe_save_name(name)
        target = os.path.join(self.saves_dir(), f"{safe}.db")
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="存档不存在。")
        os.remove(target)

    def _replace_database(self, destructive_replace: Callable[[], None]) -> None:
        """Replace the main DB transactionally, preserving the live runtime on prepare failure."""
        backup_fd, backup_path = tempfile.mkstemp(prefix="ming-hot-replace-", suffix=".db")
        os.close(backup_fd)
        old_session = self.session
        old_config = old_session.llm_config
        backup_complete = False
        try:
            # Prepare is deliberately non-destructive: a failed backup leaves the old runtime intact.
            self.db.backup_to(backup_path)
            backup_complete = True
            old_session.close()
            destructive_replace()
            self._rebuild_session(old_config)
        except Exception as replace_exc:
            if not backup_complete:
                raise
            try:
                _delete_sqlite_db_files_or_raise(self.db_path)
                shutil.copy2(backup_path, self.db_path)
                self._rebuild_session(old_config)
            except Exception as recovery_exc:
                logger.exception("hot replace recovery failed")
                raise replace_exc from recovery_exc
            raise
        finally:
            try:
                os.remove(backup_path)
            except OSError:
                logger.exception("failed to remove hot replace backup %s", backup_path)

    def reset_game(self) -> None:
        """全清主 DB；失败时恢复替换前的数据库与 runtime。"""
        self._replace_database(lambda: _delete_sqlite_db_files_or_raise(self.db_path))

    def load_save(self, name: str) -> None:
        """从存档热替换主 DB；失败时恢复替换前的数据库与 runtime。"""
        safe = self._safe_save_name(name)
        source = os.path.join(self.saves_dir(), f"{safe}.db")
        if not os.path.isfile(source):
            raise HTTPException(status_code=404, detail="存档不存在。")

        def replace_from_save() -> None:
            src_conn = sqlite3.connect(source)
            dst_conn = sqlite3.connect(self.db_path)
            try:
                src_conn.backup(dst_conn)
            finally:
                src_conn.close()
                dst_conn.close()

        self._replace_database(replace_from_save)

    def _rebuild_session(self, llm_config: LLMConfig) -> None:
        """Fully initialize a candidate before publishing it as the active session."""
        candidate = GameSession(self.db_path, llm_config)
        q = getattr(self, "_write_queue", None)
        if not isinstance(q, SessionWriteQueue):
            q = get_session_write_queue(candidate)
        else:
            candidate._write_queue = q  # type: ignore[attr-defined]
            candidate._write_gate = q.write_gate  # type: ignore[attr-defined]
        try:
            candidate.begin_turn()
            chat_history = {name: [] for name in candidate.content.characters}
            for name, msgs in candidate.db.load_all_chat_history().items():
                chat_history.setdefault(name, []).extend(msgs)
            default_favorites = {"王承恩", "曹化淳", "李若琏", "魏忠贤", "田尔耕"}
            fav_raw = candidate.db.kv_get("favorites")
            favorites = set(json.loads(fav_raw)) if fav_raw else set(default_favorites)
            if not fav_raw:
                candidate.db.kv_set("favorites", json.dumps(sorted(favorites)))
            if hasattr(candidate.db, "conn"):
                candidate.db.reconcile_interrupted_chat_turns()
        except Exception:
            try:
                candidate.close()
            except Exception:
                logger.exception("failed to close rejected replacement session")
            raise

        self.session = candidate
        self._write_queue = q
        self._write_gate = q.write_gate
        self.chat_history = chat_history
        self.favorites = favorites

    def build_llm_config(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 0,
        thinking_level: Optional[str] = None,
        reasoning_strength: Optional[str] = None,
        advanced_model: Optional[str] = None,
        advanced_base_url: Optional[str] = None,
        advanced_api_key: Optional[str] = None,
        advanced_thinking_level: Optional[str] = None,
        channel: Optional[str] = None,
        cli_runner: Optional[str] = None,
        cli_model: Optional[str] = None,
        cli_timeout_seconds: float = 0,
    ) -> LLMConfig:
        """从 in-game 输入派生新 LLMConfig（纯函数,不 verify/不落盘/不改 session）。
        通道感知（#51）：显式 channel 优先;否则填了真实 API key=切 api;都没有=保留当前通道
        （CLI 局开 in-game 设置不再被强制降级到 api + 空 key 误报）。"""
        cur = self.session.llm_config
        # 通道解析（#51）
        explicit = (channel or "").strip().lower() if channel is not None else ""
        if explicit in VALID_CHANNELS:
            new_channel = explicit
        elif real_api_key_or_empty(api_key):
            new_channel = "api"   # 用户填了真实 API key = 显式切到 API
        else:
            new_channel = (cur.channel or "api")   # 没填 = 保留当前通道,不强制降级
        # CLI 槽位：未传则保留当前
        new_cli_runner = (cli_runner if cli_runner is not None else cur.cli_runner)
        new_cli_model = (cli_model if cli_model is not None else cur.cli_model)
        new_cli_timeout = (
            cli_timeout_seconds if cli_timeout_seconds and cli_timeout_seconds > 0
            else cur.cli_timeout_seconds
        )
        base = normalize_openai_base_url(base_url.strip() or cur.base_url)
        new_model = model.strip() or cur.model
        # CLI 通道不要 API key（占位符在 create_chat_model 构造 CliChat 时注入）；
        # API 通道：请求 key 与已存 key 回落都过占位符过滤。
        if new_channel == "cli":
            new_key = ""
        else:
            new_key = real_api_key_or_empty(api_key) or real_api_key_or_empty(cur.api_key)
            if not new_key:
                # 从 cli 切回 api：cur.api_key 在 cli 模式已归一为空,但真实 key 仍存在
                # runtime_llm.json 的 api 槽——回收它,免得切回 api 还要重输 key(Gemini R1)。
                saved = load_runtime_llm()
                saved_api = saved.get("api") if isinstance(saved.get("api"), dict) else {}
                new_key = real_api_key_or_empty(saved_api.get("api_key"))
        new_timeout = timeout_seconds if timeout_seconds > 0 else cur.timeout_seconds
        if thinking_level is None:
            new_thinking_level = cur.thinking_level
        else:
            new_thinking_level = normalize_thinking_level(thinking_level)
        if reasoning_strength is None:
            new_reasoning_strength = cur.reasoning_strength
        else:
            new_reasoning_strength = normalize_reasoning_strength(reasoning_strength)
        # advanced_* = None 表示不动；传空串表示显式清空。
        if advanced_model is None:
            new_advanced = cur.advanced_model
        else:
            new_advanced = advanced_model.strip()
        if advanced_base_url is None:
            new_adv_base = cur.advanced_base_url
        else:
            adv_base_in = advanced_base_url.strip()
            new_adv_base = normalize_openai_base_url(adv_base_in) if adv_base_in else ""
        if advanced_api_key is None:
            new_adv_key = cur.advanced_api_key
        else:
            new_adv_key = advanced_api_key.strip()
        new_adv_thinking_level = ""
        return LLMConfig(
            api_key=new_key,
            base_url=base,
            model=new_model,
            timeout_seconds=new_timeout,
            thinking_level=new_thinking_level,
            advanced_model=new_advanced,
            advanced_base_url=new_adv_base,
            advanced_api_key=new_adv_key,
            advanced_thinking_level=new_adv_thinking_level,
            reasoning_strength=new_reasoning_strength,
            channel=new_channel,
            cli_runner=new_cli_runner,
            cli_model=new_cli_model,
            cli_timeout_seconds=new_cli_timeout,
        )

    def commit_llm_config(self, new_config: LLMConfig) -> LLMConfig:
        """落盘 + 切 session + 重建 registry（快;verify 由调用方先做,可 offload）。"""
        if new_config.channel == "cli":
            # CLI 通道:保住 api 槽的真实配置,切回 api 才找得回(CMR R1/R2 codex)。
            #  1) 已存 api 槽有真实 key → 传空 api 输入触发 save_runtime_llm 的 preserve_api,原样留。
            #  2) 槽无真实 key,但当前(切换前)session 是带真实 key 的 api 配置(可能来自 OPENAI_API_KEY
            #     env,尚未落 runtime_llm.json 槽)→ 把它显式写进 api 槽,否则 env-only key 在
            #     api→cli→api 往返中丢失。
            #  3) 哪都没有真实 key → 传空(无可丢)。
            saved = load_runtime_llm()
            saved_api = saved.get("api") if isinstance(saved.get("api"), dict) else {}
            prev = self.session.llm_config
            if real_api_key_or_empty(saved_api.get("api_key")) or not real_api_key_or_empty(prev.api_key):
                save_runtime_llm(
                    "", "", "",
                    channel="cli",
                    cli_runner=new_config.cli_runner,
                    cli_model=new_config.cli_model,
                    cli_timeout_seconds=new_config.cli_timeout_seconds,
                    reasoning_strength=new_config.reasoning_strength,
                )
            else:
                save_runtime_llm(
                    prev.base_url,
                    prev.model,
                    real_api_key_or_empty(prev.api_key),
                    prev.timeout_seconds,
                    prev.thinking_level,
                    prev.advanced_model,
                    prev.advanced_base_url,
                    prev.advanced_api_key,
                    "",
                    channel="cli",
                    cli_runner=new_config.cli_runner,
                    cli_model=new_config.cli_model,
                    cli_timeout_seconds=new_config.cli_timeout_seconds,
                    reasoning_strength=new_config.reasoning_strength,
                    api_reasoning_strength=prev.reasoning_strength,
                )
        else:
            save_runtime_llm(
                new_config.base_url,
                new_config.model,
                new_config.api_key,
                new_config.timeout_seconds,
                new_config.thinking_level,
                new_config.advanced_model,
                new_config.advanced_base_url,
                new_config.advanced_api_key,
                "",
                channel="api",
                cli_runner=new_config.cli_runner,
                cli_model=new_config.cli_model,
                cli_timeout_seconds=new_config.cli_timeout_seconds,
                reasoning_strength=new_config.reasoning_strength,
            )
        self.session.llm_config = new_config
        # 重建 registry 让大臣 Agent 用新配置
        self.session.begin_turn()
        return new_config

    def apply_llm_config(self, *args, **kwargs) -> LLMConfig:
        """同步:build → verify → commit。异步端点 api_set_llm_config 改为分步以 offload verify。"""
        new_config = self.build_llm_config(*args, **kwargs)
        _verify_llm_configs_or_raise(new_config)
        return self.commit_llm_config(new_config)

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
        return self.db.get_turn_report(previous_turn)

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

    @property
    def _pending_writes_count(self) -> int:
        """兼容只读：队列在途票据数（旧 counter 名，事实来源=队列）。"""
        return int(self._runtime_write_queue().inflight_count())

    def refresh_turn(self) -> None:
        self.session.begin_turn()
        # #1343 孤儿快照清一处：受理样板成功支（_settlement_period_entry 持 write_cm）。
        # 生产四调用点皆在 entry 体内（inflight>0），此处再清恒不触发；禁第二清理点。

    # ── 自定义立绘 ────────────────────────────────────────────────────────
    def find_character(self, name: str) -> Optional[Character]:
        return self.content.characters.get(name)

    def set_custom_portrait(self, name: str, portrait_id: str) -> None:
        """落库并回写内存：把某人物 portrait_id 指向自定义立绘。"""
        self.db.set_portrait_id(name, portrait_id)
        character = self.content.characters.get(name)
        if character is not None:
            character.portrait_id = portrait_id

    # ── 序列化 ────────────────────────────────────────────────────────────
    def public_character(self, character: Character) -> Dict[str, Any]:
        status, status_reason = self.db.get_character_status(character.name)
        # #1683：active=官印/在事态，不得单独译成物理「在朝」；去向另投影 location/transit。
        status_label = _STATUS_LABEL_WEB.get(status, status)
        office = character.office  # 去职者已被清空，可能为空串
        # summary 不含官职（卡片/详情已单独显 office），避免重复
        summary = f"{character.faction}一系，行事{character.style}。"
        power_id = self.db.resolve_power_id(character)  # 权威解析单一真源（#125）
        loc_row = self.db.conn.execute(
            "SELECT location, transit_to "
            "FROM characters WHERE name=?",
            (character.name,),
        ).fetchone()
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
            "skills": [
                {
                    "id": skill_id,
                    "name": skill_display_name(skill_id),
                    "sources": skill_source_labels(character, skill_id, self.db),
                    "description": self.content.skill_descriptions.get(skill_id, ""),
                }
                for skill_id in available_skill_ids(character, self.db)
            ],
            "favorite": character.name in self.favorites,
        }

    def character_power_id(self, character: Character) -> str:
        return _character_power_id(character, self.db)

    def directive_payload(self, row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "event_id": row["event_id"] or "",
            "event_title": (row["event_title"] if "event_title" in row.keys() else "") or "",
            "actor": row["actor"] or "",
            "skill_id": row["skill_id"] or "",
            "skill_name": skill_display_name(str(row["skill_id"] or "")),
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
            row for row in self.db.list_directives(
                self.state, statuses=("pending", "draft"),
            )
            if int(row["id"]) in visible_ids
        ]

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
        for row in self.db.list_closed_issues_at(target_turn):
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
        for row in self.db.list_active_issues():
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
                "tags": list(json.loads(str(row["tags"] or "[]"))),
                "inertia": int(row["inertia"] or 0),
                "resolve_condition": _humanize_condition(row["resolve_condition"] or ""),
                "fail_condition": _humanize_condition(row["fail_condition"] or ""),
                "ongoing_text": _format_issue_ongoing(str(row["ongoing_effects"] or "{}")),
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

    def legacies_payload(self) -> List[Dict[str, Any]]:
        """现行帝国修正（长期百分比修正符），给状态栏小条用。"""
        out: List[Dict[str, Any]] = []
        opening_clear_text = {
            leg.key: leg.clear_narrative
            for leg in self.content.opening_legacies
            if leg.clear_narrative
        }
        for row in self.db.list_active_legacies(self.state):
            try:
                eff = json.loads(str(row["modifiers"] or "{}"))
            except Exception:
                eff = {}
            try:
                clear_gate = json.loads(str(row["clear_gate"] or "{}"))
            except Exception:
                clear_gate = {}
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
        return self.db.get_month_open_snapshot(int(self.state.turn))

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
        rows = self.db.conn.execute(
            "SELECT id, account, delta, balance_after, category, reason "
            "FROM economy_ledger WHERE turn = ? ORDER BY id",
            (cur_turn - 1,),
        ).fetchall()
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

    def ending_payload(self) -> Optional[Dict[str, Any]]:
        """结局已触发时返回 {status,label,summary,timeline}，否则 None。"""
        if not self.state.ended:
            return None
        from ming_sim.context import ENDING_LABELS
        row = self.db.get_ending_summary() or {}
        return {
            "status": self.state.ending_status,
            "label": ENDING_LABELS.get(self.state.ending_status, "结局"),
            "summary": row.get("summary", ""),
            "timeline": row.get("timeline", []),
        }

    def state_payload(self) -> Dict[str, Any]:
        directives = [self.directive_payload(row) for row in self.directive_rows()]
        pending_actions = self.db.list_pending_actions(int(self.state.turn))
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
            durable_phase2_resume = (
                awaiting_decision
                and self.db.get_resolve_context(self.state.turn) is not None
                and not pending_decisions
            )
            # #1620 / ADR 0008 决定 6/7：settling 恢复面投影既有 abort message + ready 判别。
            # ready_replay=True → 续跑结算（重放 apply）；False → 重新推演（fallthrough）。
            settlement_recovery = None
            if turn_phase == TurnPhase.SETTLING.value:
                from ming_sim.error_pack import (
                    latest_error_pack_for_turn,
                    settlement_abort_message,
                )
                ctx = self.db.get_resolve_context(self.state.turn)
                ready_replay = ctx is not None and ctx.get("extracted") is not None
                pack_path = latest_error_pack_for_turn(int(self.state.turn))
                settlement_recovery = {
                    "ready_replay": bool(ready_replay),
                    "error_pack_path": pack_path or "",
                    "message": (
                        settlement_abort_message(pack_path)
                        if pack_path
                        else "上月结算未完成（进度已保存）。"
                    ),
                }
        return {
            "turn": {"year": self.state.year, "period": self.state.period,
                     "turn": self.state.turn, "phase": turn_phase,
                     "settlement_display": settlement_display,
                     # #1356：年号纪年投影单真源，前端报头直显，禁第二份 epoch 表
                     "reign_period_label": reign_period_label(
                         self.state.year, self.state.period)},
            "metrics": display_metrics,
            "previous_summary": self.previous_summary,
            # #1356：邸报报头年月 ≡ 报文自身月（turn_reports 已存 year/period 投影）；
            # turn.reign_period_label 是当前回合标签，不得混充上月报头。
            "previous_reign_period_label": self.db.previous_turn_reign_period_label(self.state),
            # #1241 SP2：删 state_payload.treasury（零消费残口；判词 r1：treasury_report
            # 留 knowledge/simulation/tools 三缝，不动 settlement_display/budget 投影）。
            "issues": self.issue_payloads(),
            "legacies": self.legacies_payload(),
            "closed_this_turn": self.closed_this_turn_payloads(),
            "budget": self.budget_payload(),
            "region_warning": self.db.region_report(limit=5),
            "army_warning": self.db.army_report(limit=5),
            "power_warning": self.db.power_report(exclude_self=True),
            "powers": self.db.power_payload(),
            "victory_status": self.session.victory(),
            "ending": self.ending_payload(),
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
            "pending_count": self.session.pending_count(),
            "pending_directive_count": sum(
                1 for a in pending_actions
                if a["kind"] == "directive"),
            # #1376：staged 密令候选如实入投影计数（可见性）。
            # #414 默认准行口径不变：确认闸门/落库时序仍走收夜·退朝 commit，
            # 本字段不把候选升成 player-facing secret_orders 行，禁静默漂成恒 0。
            "pending_secret_order_count": sum(
                1 for a in pending_actions
                if a["kind"] == "secret_order"),
            "pending_non_directive_action_count": len(visible_non_directive_pending),
            "failed_secret_order_count": sum(
                1 for _a in self.db.list_failed_secret_order_actions()),
            "pending_decisions": pending_decisions,
            # #657：phase1 已落 decided、desk 只查 pending 为空时，投影 typed 续跑信号。
            # 不把 decided 塞回 pending 列表；前端空 POST 既有 resolve_decisions/stream。
            "resume_phase2": durable_phase2_resume and not settlement_entry_inflight,
            # #1625：只投影进程内既有入口计数；供刷新/重拉区分在飞与真暂停。
            "settlement_entry_inflight": settlement_entry_inflight,
            # #1620：settling 恢复面（ADR 0008 决定 6/7 message + ready_replay）
            "settlement_recovery": settlement_recovery,
            "last_decree": self.last_decree,
            "last_report": self.last_report,
            # #671：上一已完成月王承恩独立递话（与 last_report 同级 typed 字段）
            "last_attendant_message": self.db.previous_turn_attendant_message(self.state),
        }

    # ── 聊天 ──────────────────────────────────────────────────────────────
    def _persistent_chat_minister(self, minister_name: str) -> bool:
        return minister_name not in self.session.temporary_characters

    def chat_projection(self, minister_name: str) -> List[Dict[str, Any]]:
        """召对显示投影（#499 单一真源）：持久大臣 → DB turn-identified 投影（含读心
        递话按轮归位）；临时召见 → 内存历史（无 chat_turn/无读心）。三处出口（历史
        入口 / 回话 done / 撤回）共用它，杜绝 setChat(history) 抹掉读心的覆盖竞争。"""
        if self._persistent_chat_minister(minister_name):
            # Lightweight stream seams intentionally expose neither a durable connection nor
            # the night-aware projection signature. Production DBs always use the night owner.
            if not hasattr(self.db, "conn"):
                return self.db.build_chat_projection(minister_name)
            from ming_sim.audience_night import get_open_night
            night = get_open_night(self.db)
            return self.db.build_chat_projection(minister_name, int(night["id"]) if night else 0)
        return [
            {"role": m["role"], "content": m["content"], "chat_turn_id": 0}
            for m in self.chat_history.get(minister_name, [])
        ]

    def _minister_agno_session_id(self, minister_name: str) -> str:
        registry = self.session.registry
        if registry is None:
            return f"minister-{minister_name}-turn-{self.state.turn}"
        return registry.session_ids.get(minister_name, f"minister-{minister_name}-turn-{self.state.turn}")

    def can_undo_last_chat(self, minister_name: str) -> bool:
        if not self._persistent_chat_minister(minister_name):
            return False
        if self.state.turn_phase not in (TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value):
            return False
        return self.db.can_undo_last_chat_turn(minister_name, self.state.turn)

    def pending_action_failures_for(self, minister_name: str) -> List[Dict[str, Any]]:
        """该召对对象仍可由玩家处理的失败密令动作。"""
        return [
            _pending_action_failure_payload(action, getattr(self, "state", None))
            for action in self.db.list_failed_secret_order_actions(minister_name)
        ]

    def pending_action_failures(self) -> List[Dict[str, Any]]:
        """所有仍可由玩家处理的失败密令动作，不依赖承办人当前是否可召见。"""
        return [
            _pending_action_failure_payload(action, getattr(self, "state", None))
            for action in self.db.list_failed_secret_order_actions()
        ]

    def _audience_turn_in_flight(self, minister_name: str) -> bool:
        """#383 背景召对契约：同一大臣已有「已受理、尚未完成回奏」的 turn 时，不得再开新轮。

        in-flight = `status='generating'`，或 `status='active'` 且 `minister_message_id` 仍空
        （#498 挂夜轮以 generating 起笔，回话入档后升 active）。走 GameDB 查询 seam，
        不直摸 db.conn（测试替身可 stub list_in_flight_chat_turns）。"""
        if not self._persistent_chat_minister(minister_name):
            return False
        if hasattr(self.db, "list_in_flight_chat_turns"):
            rows = self.db.list_in_flight_chat_turns(
                minister_name=minister_name, turn=int(self.state.turn),
            )
            return bool(rows)
        # 极薄兜底：旧替身无接口时不挡（与 get_last_active 语义接近）
        existing = self.db.get_last_active_chat_turn(minister_name, self.state.turn)
        return existing is not None and not existing.get("minister_message_id")

    def _start_chat_turn(
        self, minister_name: str, *, attach_to_hall: bool = True, route: str = "",
    ) -> tuple[int, Dict[str, Any]]:
        agno_session_id = self._minister_agno_session_id(minister_name)
        runs_before = self.db.agno_runs_length(agno_session_id)
        snapshot = self.db.capture_chat_rollback_snapshot()
        # #498：进入召对即开夜；对话轮挂 night_id，status=generating 至回话入档。
        # 测试替身无 conn/夜表时回退 create_chat_turn（lifecycle 双接口仍可测）。
        # #1566：场外密疏只挂当前夜，不入殿、不启殿上 scene；route 落 chat_turns。
        if hasattr(self.db, "conn"):
            from ming_sim.audience_night import (
                attach_chat_turn_to_night,
                ensure_open_night_for_audience,
                get_open_night,
            )
            if attach_to_hall:
                _night_id, chat_turn_id = attach_chat_turn_to_night(
                    self.db,
                    self.state,
                    minister_name,
                    agno_session_id=agno_session_id,
                    agno_runs_before=runs_before,
                    beat_generator=None,
                    route=route,
                )
                if chat_turn_id:
                    self.session.start_chat_turn_scene(minister_name, chat_turn_id)
            else:
                night = get_open_night(self.db) or ensure_open_night_for_audience(
                    self.db, self.state,
                )
                chat_turn_id = self.db.create_chat_turn(
                    self.state,
                    minister_name,
                    agno_session_id,
                    runs_before,
                    night_id=int(night["id"]),
                    status="generating",
                    route=route,
                )
        else:
            chat_turn_id = self.db.create_chat_turn(
                self.state,
                minister_name,
                agno_session_id,
                runs_before,
                route=route,
            )
            if attach_to_hall and chat_turn_id:
                self.session.start_chat_turn_scene(minister_name, chat_turn_id)
        return chat_turn_id, snapshot

    def _record_chat_rollback_items(
        self,
        chat_turn_id: int,
        before_snapshot: Dict[str, Any],
    ) -> None:
        if not chat_turn_id:
            return
        after_snapshot = self.db.capture_chat_rollback_snapshot()
        self.db.record_chat_turn_rollback_diffs(chat_turn_id, before_snapshot, after_snapshot)

    def _fail_chat_turn_and_reload(self, chat_turn_id: int, before_snapshot: Dict[str, Any]) -> None:
        """召对中断/失败的统一善后：记 rollback 项、标 chat_turn=failed、从 DB 重载聊天缓存。
        所有「已建 chat_turn 但本轮未能正常完成」的路径都必须调用——否则留下 status=active 且
        minister_message_id 为空的孤儿轮，`_audience_turn_in_flight` 会把该大臣永久判为「上一轮
        仍在进行」而拒收后续问话（cmr Gate2 F-B）。chat_turn_id=0（无持久轮）时为 no-op。

        Scene abandon/drain 由调用方在 write_gate 外先完成（C9/T1/T10）；本方法只做短事务写。
        """
        if not chat_turn_id:
            return
        self._record_chat_rollback_items(chat_turn_id, before_snapshot)
        self.db.fail_chat_turn(chat_turn_id)
        self.chat_history = {name: [] for name in self.session.content.characters}
        for name, msgs in self.db.load_all_chat_history().items():
            self.chat_history.setdefault(name, []).extend(msgs)

    def undo_last_chat(self, minister_name: str) -> Dict[str, Any]:
        if self.state.turn_phase not in (TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value):
            raise HTTPException(status_code=409, detail="本回合已经进入颁诏结算，不能撤回召对。")
        if not self._persistent_chat_minister(minister_name):
            raise HTTPException(status_code=409, detail="临时召见人物暂不支持撤回。")
        row = self.db.get_last_active_chat_turn(minister_name, self.state.turn)
        if row is None:
            raise HTTPException(status_code=404, detail="本回合没有可撤回的召对。")
        if not self.db.is_global_last_active_chat_turn(int(row["id"])):
            raise HTTPException(status_code=409, detail="只能撤回全局最后一轮召对。")
        if not row.get("user_message_id") or not row.get("minister_message_id"):
            raise HTTPException(status_code=409, detail="该召对尚未完整完成，不能撤回。")
        # #1353 / ADR 0038：撤回轮取消其在飞票据（空放行、不复活写库）。
        turn_id = int(row["id"])
        try:
            self._runtime_write_queue().cancel_key(("turn", turn_id))
        except Exception:
            pass
        try:
            undone = self.db.undo_chat_turn(turn_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        # P1-2：撤回若删了已 commit 的对话草案，作废已生成的诏书正文（last_decree），
        # 不让玩家原样颁出含被撤回指令的陈旧诏书。
        self.session.note_chat_rollback(
            deleted_committed_draft_ids=undone.get("deleted_committed_draft_ids"))
        self.session.refresh_runtime_after_chat_rollback()
        self.chat_history = {name: [] for name in self.session.content.characters}
        for name, msgs in self.db.load_all_chat_history().items():
            self.chat_history.setdefault(name, []).extend(msgs)
        character = self.session._character(minister_name)
        return {
            "minister": minister_name,
            "campaign_id": str(self.db.kv_get("campaign_id") or ""),
            "night_id": int(row.get("night_id") or 0),
            "undone_chat_turn_id": int(undone["id"]),
            # #499 同一 turn-identified 投影：撤回后剩余轮的读心仍按轮归位
            "history": self.chat_projection(minister_name),
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "secret_orders": self.db.list_secret_orders(),
            "suggestions": self.suggestions_for(character),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
            "pending_action_failures": self.pending_action_failures_for(minister_name),
        }

    def _chat_payload(
        self,
        minister_name: str,
        answer: str,
        court_action: str = "",
        next_minister: str = "",
        proposed_directive: Optional[Dict[str, Any]] = None,
        appointed_minister: str = "",
        registered_minister: str = "",
        displaced_minister: str = "",
        secret_order_id: int = 0,
        pending_action_id: int = 0,
        pending_action_failures: Optional[List[Dict[str, Any]]] = None,
        chat_turn_id: int = 0,
        accepted_turn: Optional[int] = None,
        directive_confirmation_ambiguous: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        character = self.session._character(minister_name)
        # Durable chat_turn message ids first, then memory history.  Publishing
        # history before append/update opens a race: observers see the minister
        # reply while can_undo_last_chat_turn is still false (#976 hold path
        # lengthens append_chat_message; background stream + early assert flaked
        # and tore down the shared DB under the worker → SIGSEGV).
        minister_message_id = 0
        if minister_name not in self.session.temporary_characters:
            turn = int(self.state.turn if accepted_turn is None else accepted_turn)
            if chat_turn_id:
                # #499 单一事务：插入回话 → 链接 turn → 接受读心任务（''→'running'）→ 一次提交。
                # 杜绝「回话已 commit 却未链接」孤儿（否则可见回话 chat_turn_id 0、空任务态、
                # 无对账、无 pending、in-flight 守卫永挡召见）。worker 崩溃遗留的 running 由启动
                # 对账终态化，不永挂 pending。
                minister_message_id = int(
                    self.db.persist_minister_reply(minister_name, turn, answer, chat_turn_id)
                )
            else:
                # 无持久 chat_turn（如临时召见路径异常）：仅落消息，无可链接的任务。
                minister_message_id = int(
                    self.db.append_chat_message(minister_name, turn, "minister", answer)
                )
        self.chat_history[minister_name].append({"role": "minister", "content": answer})
        open_night = None
        if hasattr(self.db, "conn"):
            from ming_sim.audience_night import get_open_night
            open_night = get_open_night(self.db)
        return {
            "minister": minister_name,
            "answer": answer,
            # Persisted identity travels with the real player response; the web client
            # never infers night ownership from cross-night personal chat history.
            "campaign_id": str(self.db.kv_get("campaign_id") or "") if hasattr(self.db, "kv_get") else "",
            "night_id": int(open_night["id"]) if open_night else 0,
            # #499 单一投影：user/minister 带 chat_turn_id、既有读心按轮归位；
            # 前端 setChat 不再抹掉先前浮现的读心递话。
            "history": self.chat_projection(minister_name),
            "chat_turn_id": int(chat_turn_id or 0),
            # #544：供高亮判官落库锚定（非流式折窗 / 流式补挂）
            "minister_message_id": int(minister_message_id or 0),
            "court_action": court_action,
            "next_minister": next_minister,
            "proposed_directive": proposed_directive,
            "appointed_minister": appointed_minister,
            "registered_minister": registered_minister,
            "displaced_minister": displaced_minister,
            "secret_order_id": secret_order_id or 0,
            "pending_action_id": pending_action_id or 0,
            "pending_action_failures": pending_action_failures or [],
            # #502 AC5：多道准驳含糊态（候选 id/摘要）供前端展示大臣追问；无则 None。
            "directive_confirmation_ambiguous": directive_confirmation_ambiguous or None,
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "suggestions": self.suggestions_for(character),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
        }

    def _reject_if_settlement_phase(self) -> None:
        """#498/#505：结算/亲裁相位不得召对（含续问与重试召对）——否则开/续的夜会随
        submit_decisions 跨月推进而不收（夜不跨月）。raise 版召对入口共用此单缝，
        新入口（如 #505 重试）不再另抄一份 if（stream 入口走 yield-error 控制流，自持一份）。"""
        if getattr(self.state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
            raise HTTPException(status_code=409, detail="月末结算/亲裁进行中，暂不能召对。")

    @staticmethod
    def _message_is_formal_secret_order(message: str) -> bool:
        """#1566：正式密令前缀入口（复用既有 _SECRET_PREFIXES，不另造分类器）。

        ADR 0096：密疏不受 location 分流；公开 chat/stream 须在 admission 前识别。
        """
        from ming_sim.cli_backend import _SECRET_PREFIXES
        return (message or "").strip().startswith(_SECRET_PREFIXES)

    def _finish_offsite_summon_scene(
        self, *, origin_id: str, minister_name: str, gate_cm: Any,
    ) -> None:
        """#1566：gate 内组装 DB 输入、gate 外生成、gate 内短写。无专用 Future。"""
        from ming_sim.beat_orchestration import (
            assemble_offsite_summon_inputs,
            persist_chat_turn_scene,
            run_beat_generator,
        )

        with gate_cm:
            assembled = assemble_offsite_summon_inputs(
                self.db, self.state, origin_id=origin_id, person_name=minister_name,
            )
        if assembled is None:
            return
        entry_id, inputs = assembled
        body = run_beat_generator(
            getattr(self.session, "_beat_generator", None), inputs,
        )
        with gate_cm:
            with atomic(self.db):
                persist_chat_turn_scene(self.db, [(entry_id, body)])

    def _summon_admission_success_payload(
        self, minister_name: str, admission_result: str,
    ) -> Dict[str, Any]:
        """#670：成功记召静默载荷——不建轮、不落消息、不调回话/LLM。

        admission 为机面控制码，客户端不得写入玩家错误区。
        #1566：canonical scroll 承接可见 scene；本载荷仍空 answer。
        """
        character = self.session._character(minister_name)
        open_night = None
        if hasattr(self.db, "conn"):
            from ming_sim.audience_night import get_open_night
            open_night = get_open_night(self.db)
        return {
            "minister": minister_name,
            "answer": "",
            "campaign_id": (
                str(self.db.kv_get("campaign_id") or "")
                if hasattr(self.db, "kv_get") else ""
            ),
            "night_id": int(open_night["id"]) if open_night else 0,
            "history": self.chat_projection(minister_name),
            "chat_turn_id": 0,
            "minister_message_id": 0,
            "court_action": "",
            "next_minister": "",
            "proposed_directive": None,
            "appointed_minister": "",
            "registered_minister": "",
            "displaced_minister": "",
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
            "directive_confirmation_ambiguous": None,
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "suggestions": self.suggestions_for(character),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
            # 机面字段：不渲染；前端 refresh 故事账/卷轴即可。
            "admission": str(admission_result or ""),
        }

    def chat(self, minister_name: str, message: str, intent: Optional[str] = None) -> Dict[str, Any]:
        # #498 AC10：LLM 生成不持 write_gate，使颁诏入口可观测 in-flight 并有界超时；
        # 仅 prologue/epilogue 写库持锁。
        # #670 / ADR 0096：殿上入口——自持闸 prologue 内消费 admission（与 chat_stream 同口径）。
        return self._chat_core(minister_name, message, gate_already_held=False, intent=intent)

    def _chat_with_write_gate_held(self, minister_name: str, message: str) -> Dict[str, Any]:
        """#1357：兼容密令按钮端点已由 `_serialized_web_write` 持 write_gate。

        与 `chat()` 同语义，但不得再 acquire 非可重入 Lock（会死锁）。
        此兼容路径在外层闸内跑完整轮（含 LLM）；公开 chat/chat_stream 仍按 AC10
        在生成期放闸。
        #670：密疏只受 _require_active_minister/can_summon，不走殿上 admission。
        """
        return self._chat_core(minister_name, message, gate_already_held=True)

    def _chat_core(
        self,
        minister_name: str,
        message: str,
        *,
        gate_already_held: bool,
        intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        if minister_name not in self.content.characters and minister_name not in self.session.temporary_characters:
            raise HTTPException(status_code=404, detail=f"未找到大臣：{minister_name}")
        text = message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="问话不能为空。")
        # #498：结算/亲裁相位不得召对——否则开的夜会随 submit_decisions 跨月推进而不收（夜不跨月）。
        # 锁前查仅为快速失败；权威判定须在持 gate 后、建任何 chat turn/开夜/写库之前复查——
        # 否则 SUMMONING 通过后等 gate 时被结算 worker 改成 AWAITING_DECISION/SETTLING，仍会开夜（TOCTOU）。
        self._reject_if_settlement_phase()
        # 整轮（含 LLM 无锁窗 + epilogue）共用一次队列票据——对齐 chat_stream。
        # #1291 卸到 threadpool 后事件循环可与回菜单/新局重叠；不领票则 barrier/drain
        # 当空闲关连接，epilogue 落库打到已关连接。公开 chat 与持闸密令路共用 claim→finally complete。
        pending_ticket = self._mark_pending_write()
        if pending_ticket is None:
            raise HTTPException(
                status_code=503,
                detail="当前会话正在关闭，请回菜单重新进入。",
            )
        # #1353 r10：删简优先——屏障已受理则拒后序聊天（与 seal 合流），禁排队等屏障后
        # 再写旧 night；公开路径 DB 缝另经 ticketed gate。持闸兼容路外层已持裸锁。
        # 失败清理在票可能已 complete 后走裸 runtime gate（ticketed 见 _done 会 TicketCancelled）。
        if (
            not gate_already_held
            and self._runtime_write_queue().has_open_barrier()
        ):
            self._complete_pending_write(pending_ticket)
            raise HTTPException(
                status_code=409,
                detail="本夜收夜中，暂不能召对。",
            )
        if gate_already_held:
            gate_cm: Any = contextlib.nullcontext()
            cleanup_gate: Any = contextlib.nullcontext()
        else:
            gate_cm = self._ticketed_write_gate(pending_ticket)
            cleanup_gate = self._runtime_write_gate()
        chat_turn_id = 0
        before_snapshot: Dict[str, Any] = {}
        accepted_turn = 0
        # #1566：场外记召成功后在 gate 外物化 scene；（minister, admission_result, origin_id）
        offsite_summon: Optional[tuple[str, str, str]] = None
        # #542 r6e：prologue（_start_chat_turn / append）纳入既有 try/except；
        # 与流式 L2414-2428 同缝——drain 在 write_gate 外，再 abandon + fail。
        try:
            try:
                with gate_cm:
                    self._reject_if_settlement_phase()
                    # #612：CLOSING 冻结新对话——与 stream 共用唯一玩家输入准入真源，无平行 status 判断。
                    if hasattr(self.db, "conn"):
                        from ming_sim.audience_night import assert_night_accepts_player_input
                        assert_night_accepts_player_input(self.db, what="召对")
                    if self._audience_turn_in_flight(minister_name):
                        raise HTTPException(status_code=409, detail=f"{minister_name}上一轮回奏仍在进行，请稍候再问。")
                    accepted_turn = int(self.state.turn)
                    # #670：殿上 chat 自持闸时消费 admission；密疏兼容路（gate_already_held）不消费。
                    # 闸只管殿上召对——书信/密疏只受基础资格（_require_active_minister/can_summon）。
                    # #1566：正式密令前缀须先入密令管线，不得被 location admission 抢先截获。
                    explicit_secret_order = intent == "secret_order" or self._message_is_formal_secret_order(text)
                    secret_order_bypass = gate_already_held or explicit_secret_order
                    offsite_secret_order = False
                    if not secret_order_bypass:
                        origin_id = f"web:chat:{accepted_turn}:{minister_name}"
                        admission = self.session.consume_audience_admission(
                            self.session._character(minister_name),
                            origin_id=origin_id,
                        )
                        if not admission.allowed:
                            # 资格失败：非空 reason → 409 错误通道。
                            # 成功记召（SUMMON_* + 空 reason）：静默 200，退出玩家错误通道。
                            if admission.reason:
                                raise HTTPException(
                                    status_code=409, detail=admission.reason,
                                )
                            if admission.result in (
                                AudienceAdmission.SUMMON_FRESH,
                                AudienceAdmission.SUMMON_IN_TRANSIT,
                            ):
                                # 记召已落账；scene 在 gate 外生成（见 with 后）。
                                offsite_summon = (
                                    minister_name,
                                    admission.result.value,
                                    origin_id,
                                )
                            else:
                                raise HTTPException(
                                    status_code=409,
                                    detail=(
                                        admission.result.value
                                        if admission.result is not None else ""
                                    ),
                                )
                    elif (
                        not gate_already_held
                        and explicit_secret_order
                    ):
                        decision = self.session.admit_audience(
                            self.session._character(minister_name),
                        )
                        if decision.reason:
                            raise HTTPException(
                                status_code=409, detail=decision.reason,
                            )
                        offsite_secret_order = decision.result in (
                            AudienceAdmission.SUMMON_FRESH,
                            AudienceAdmission.SUMMON_IN_TRANSIT,
                        )
                    if offsite_summon is None:
                        if self._persistent_chat_minister(minister_name):
                            from ming_sim.audience_night import encode_chat_turn_route
                            chat_turn_id, before_snapshot = self._start_chat_turn(
                                minister_name,
                                attach_to_hall=not offsite_secret_order,
                                route=encode_chat_turn_route(
                                    explicit_secret_order=explicit_secret_order,
                                    offsite=offsite_secret_order,
                                ),
                            )
                        self.chat_history.setdefault(minister_name, []).append({"role": "user", "content": text})
                        if minister_name not in self.session.temporary_characters:
                            message_id = self.db.append_chat_message(minister_name, accepted_turn, "user", text)
                            if chat_turn_id:
                                self.db.update_chat_turn_messages(chat_turn_id, user_message_id=message_id)
                if offsite_summon is not None:
                    summon_name, summon_result, summon_origin = offsite_summon
                    self._finish_offsite_summon_scene(
                        origin_id=summon_origin, minister_name=summon_name,
                        gate_cm=gate_cm,
                    )
                    # #1566：成功载荷的同连接 DB 投影读须纳入 ticketed gate 短临界段，
                    # 与并发同源请求的读/写在同一 sqlite connection 上互斥；LLM 早已在
                    # write_back 内结清，此处只剩纯读。
                    with gate_cm:
                        return self._summon_admission_success_payload(
                            summon_name, summon_result,
                        )
                # #634 P5：判官拍与回话并行发出（先于回话生成，TD-9 零额外等待）。
                self._dispatch_relation_judge(chat_turn_id)
                # #1566：生产契约直调（chat_turn_id + explicit_secret_order）；禁签名探测降级。
                result = self.session.chat(
                    minister_name, text,
                    chat_turn_id=chat_turn_id,
                    explicit_secret_order=explicit_secret_order,
                )
                proposed = None
                if result.proposed_directive is not None:
                    d = result.proposed_directive
                    proposed = {"id": d.id, "text": d.text, "status": d.status, "notes": d.notes}
                scene_generated = self.session.join_chat_turn_scene(chat_turn_id)
                with gate_cm:
                    # 慢 scene 等待在 gate 外；短事务内与回话全有或全无。
                    with atomic(self.db):
                        self.session.persist_chat_turn_scene(scene_generated)
                        # _chat_payload 持久化 minister 消息 + 更新 chat_turn。
                        payload = self._chat_payload(
                        minister_name, result.answer,
                        court_action=result.court_action, next_minister=result.next_minister,
                        proposed_directive=proposed, appointed_minister=result.appointed_minister,
                        registered_minister=result.registered_minister,
                        displaced_minister=result.displaced_minister,
                        secret_order_id=result.secret_order_id,
                        pending_action_id=getattr(result, "pending_action_id", 0),
                        pending_action_failures=getattr(result, "pending_action_failures", []),
                        chat_turn_id=chat_turn_id,
                        accepted_turn=accepted_turn,
                        # #502 R1：非流式路径同 surface 结构化含糊态（与 stream 同真源，禁双路径漂移）。
                        directive_confirmation_ambiguous=getattr(
                            result, "directive_confirmation_ambiguous", None),
                    )
                    self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                answer_text = str(getattr(result, "answer", "") or "")
                message_id = int(payload.get("minister_message_id") or 0)
                # P5：先 spawn 读心/抽取，再折进判官等待窗——折窗期内后处理已在跑。
                # #1353：非持闸路尾随领 turn 票后立刻放行整轮票——否则 ticketed write 等整轮票
                # 而主线程持整轮票等尾随 = 自锁。持闸兼容路整轮票覆盖高亮写（禁无票裸写）。
                if chat_turn_id and answer_text:
                    self._spawn_pending_write_thread(
                        self._trail_mindreading_after_reply,
                        (minister_name, answer_text, chat_turn_id),
                        "audience-p5-mindreading",
                        ticket_key=("turn", int(chat_turn_id)),
                    )
                    # #501：叙事抽取落账与读心并行尾随（各自队列票据，P5）。
                    self._spawn_extraction_trail(minister_name, answer_text, chat_turn_id)
                    if not gate_already_held:
                        self._complete_pending_write(pending_ticket)
                        pending_ticket = None
                # #544：非流式折进等待窗——判官以超时封顶后与回话同到；超时则空清单先行。
                # 持闸路须把已持闸态传到判官写库缝，禁同线程二次 acquire 非可重入 Lock。
                if message_id and answer_text:
                    held_ticket = pending_ticket if gate_already_held else None
                    self._trail_highlight_judge_after_reply(
                        answer_text,
                        message_id=message_id,
                        chat_turn_id=chat_turn_id,
                        gate_already_held=gate_already_held,
                        pending_ticket=held_ticket,
                    )
                    if held_ticket is not None:
                        # 持闸兼容：整轮票覆盖高亮写；trail 不二次 acquire，由调用方收口。
                        self._complete_pending_write(held_ticket)
                        pending_ticket = None
                    payload["history"] = self.chat_projection(minister_name)
            except Exception:
                # drain 在 write_gate 外（与 stream / retry 同序），再短写 fail。
                # 内层守护对齐流式：二次失败记日志不吞原错；abandon / 终态写分 try，
                # 终态写尽力而为——abandon 崩不得跳过 fail，否则 turn 卡 generating。
                try:
                    self.session.abandon_chat_turn_scene(chat_turn_id)
                except Exception:
                    logger.exception(
                        "nonstream chat cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                        chat_turn_id,
                    )
                try:
                    with cleanup_gate:
                        if chat_turn_id:
                            self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                            self.db.fail_chat_turn(chat_turn_id)
                            self.chat_history = {name: [] for name in self.session.content.characters}
                            for name, msgs in self.db.load_all_chat_history().items():
                                self.chat_history.setdefault(name, []).extend(msgs)
                except Exception:
                    logger.exception(
                        "nonstream chat cleanup: fail_chat_turn/reload failed chat_turn_id=%s",
                        chat_turn_id,
                    )
                raise
            # #1353：若无尾随（无 turn/answer）仍须放行整轮票后再收夜。
            if pending_ticket is not None:
                self._complete_pending_write(pending_ticket)
                pending_ticket = None
            # #526：回话已落库后收夜。失败响亮上抛，不得回滚已成回话；夜可恢复。
            # #1353：close 经队列屏障；穿既有 runtime write_gate（禁第二锁）。
            close_after = getattr(self.session, "close_night_after_chat_if_needed", None)
            if close_after is not None:
                close_after(
                    getattr(result, "court_action", "") or "",
                    write_gate=self._runtime_write_gate(),
                )
            return payload
        finally:
            self._complete_pending_write(pending_ticket)

    def interrupted_reply_retries(self, minister_name: str) -> List[Dict[str, Any]]:
        """#505：某大臣重开后待重试的中断回话轮（问话已落、回话未落）——恢复提示取数。
        测试替身无 conn/该接口时返回空（无中断可重试）。"""
        if not hasattr(self.db, "get_interrupted_reply_retries"):
            return []
        return self.db.get_interrupted_reply_retries(minister_name)

    def retry_interrupted_reply(self, minister_name: str) -> Dict[str, Any]:
        """#505 恢复动作：重开后为最后一条中断轮**重新生成回话**（系统层重试，非内容选项按钮）。

        复用既有 chat_turn 与已持久问话——**绝不再落问话**（对话记录无重复句，AC3）。成功即回话
        落库、轮 generating→active；重试再失败则翻回 interrupted 保持可再重试。无待重试轮 → 响亮 404。"""
        retries = self.interrupted_reply_retries(minister_name)
        if not retries:
            raise HTTPException(status_code=404, detail=f"{minister_name}没有待重试的中断回话。")
        target = retries[-1]  # 最后一条中断轮
        chat_turn_id = int(target["chat_turn_id"])
        question = str(target["question"])
        accepted_turn = int(target["turn"])
        # #505 finding4：结算/亲裁相位不得重试召对（与 chat 同相位门，夜不跨月）。锁前快速失败。
        self._reject_if_settlement_phase()
        # 与非流式 chat 同形：整轮票据覆盖 LLM 无锁窗 + epilogue，防 barrier/drain 当空闲关连接。
        pending_ticket = self._mark_pending_write()
        if pending_ticket is None:
            raise HTTPException(
                status_code=503,
                detail="当前会话正在关闭，请回菜单重新进入。",
            )
        # #1353 r10：屏障已受理则拒重试召对；否则整轮 DB 缝经 ticketed gate。
        # 失败清理在票可能已 complete 后走裸 runtime gate。
        if self._runtime_write_queue().has_open_barrier():
            self._complete_pending_write(pending_ticket)
            raise HTTPException(
                status_code=409,
                detail="本夜收夜中，暂不能召对。",
            )
        gate = self._ticketed_write_gate(pending_ticket)
        cleanup_gate = self._runtime_write_gate()
        before_snapshot: Dict[str, Any] = {}
        # #1566：route 权威解码——场外密令不启殿上 scene；密令重试保 explicit_secret_order。
        from ming_sim.audience_night import decode_chat_turn_route
        retry_route = decode_chat_turn_route(target.get("route"))
        # #542 r6e：reopen + start_chat_turn_scene 纳入既有 try/except；
        # 失败复用 abandon + restore interrupted；drain 在 write_gate 外。
        try:
            try:
                with gate:
                    self._reject_if_settlement_phase()
                    # #612：CLOSING 冻结重试召对——与 chat 共用唯一玩家输入准入真源，CAS reopen 前拒绝。
                    if hasattr(self.db, "conn"):
                        from ming_sim.audience_night import assert_night_accepts_player_input
                        assert_night_accepts_player_input(self.db, what="召对")
                    if self._audience_turn_in_flight(minister_name):
                        raise HTTPException(
                            status_code=409, detail=f"{minister_name}上一轮回奏仍在进行，请稍候再问。")
                    # #505 finding3：reopen 是 CAS（interrupted→generating）。未赢（并发/双击重试
                    # 已被别的调用翻走）→ 响亮 409，绝不 generate/persist 出第二条大臣回话。
                    if not self.db.reopen_interrupted_chat_turn_for_retry(chat_turn_id):
                        raise HTTPException(
                            status_code=409, detail=f"{minister_name}上一轮回奏仍在进行，请稍候再问。")
                    # #505 finding1：与 chat 同 snapshot→record rollback 缝——session.chat 在返回前
                    # 即可 durable 落副作用（dismiss 账/拟旨/任免候选等，session.py tool 环）。捕于
                    # reopen 后、session.chat 前，成功后记 diff 供撤回、失败时回滚，杜绝双 stage/粘滞。
                    before_snapshot = self.db.capture_chat_rollback_snapshot()
                    if retry_route["start_hall_scene"]:
                        self.session.start_chat_turn_scene(minister_name, chat_turn_id)
                # #634 P5：重试同形——判官拍与回话并行发出（不依赖本轮回话）。
                self._dispatch_relation_judge(chat_turn_id)
                # #1566：生产契约直调（chat_turn_id + explicit_secret_order）；禁签名探测降级。
                result = self.session.chat(
                    minister_name, question,
                    chat_turn_id=chat_turn_id,
                    explicit_secret_order=retry_route["explicit_secret_order"],
                )
                proposed = None
                if result.proposed_directive is not None:
                    d = result.proposed_directive
                    proposed = {"id": d.id, "text": d.text, "status": d.status, "notes": d.notes}
                scene_generated = self.session.join_chat_turn_scene(chat_turn_id)
                with gate:
                    with atomic(self.db):
                        self.session.persist_chat_turn_scene(scene_generated)
                        payload = self._chat_payload(
                        minister_name, result.answer,
                        court_action=result.court_action, next_minister=result.next_minister,
                        proposed_directive=proposed, appointed_minister=result.appointed_minister,
                        registered_minister=result.registered_minister,
                        displaced_minister=result.displaced_minister,
                        secret_order_id=result.secret_order_id,
                        pending_action_id=getattr(result, "pending_action_id", 0),
                        pending_action_failures=getattr(result, "pending_action_failures", []),
                        chat_turn_id=chat_turn_id,
                        accepted_turn=accepted_turn,
                        directive_confirmation_ambiguous=getattr(
                            result, "directive_confirmation_ambiguous", None),
                    )
                    # #505 finding1：与 chat 成功尾声同缝，记本次重试落下的副作用 diff，供日后撤回还原。
                    self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                answer_text = str(getattr(result, "answer", "") or "")
                message_id = int(payload.get("minister_message_id") or 0)
                # P5：重试同形——先 spawn 读心/抽取，再折判官窗。
                # #1353：尾随领票后立刻放行整轮票，禁 ticketed write 与主线程互相等待。
                if chat_turn_id and answer_text:
                    self._spawn_pending_write_thread(
                        self._trail_mindreading_after_reply,
                        (minister_name, answer_text, chat_turn_id),
                        "audience-p5-mindreading",
                        ticket_key=("turn", int(chat_turn_id)),
                    )
                    self._spawn_extraction_trail(minister_name, answer_text, chat_turn_id)
                    self._complete_pending_write(pending_ticket)
                    pending_ticket = None
                if message_id and answer_text:
                    # #544：重试非流式同折窗封顶（自领 turn 票，无裸写）
                    self._trail_highlight_judge_after_reply(
                        answer_text,
                        message_id=message_id,
                        chat_turn_id=chat_turn_id,
                    )
                    payload["history"] = self.chat_projection(minister_name)
            except Exception:
                # #505 finding1：重试再失败——先记本次 session.chat 落下的副作用 diff，再回滚它们
                # （与 chat 失败尾声同缝），并截断本轮 agno、翻回 interrupted 保持可再重试；
                # 但**绝不删问话/回话**（AC3/AC4 恢复路径永不删账），不静默 fail 掉最后一句。
                # #542：running Future 的 cancel/join 必须在 write gate 外；锁内仅 rollback 短写。
                # 内层守护对齐流式/非流 chat：二次失败记日志不吞原错；abandon / 终态写分 try，
                # 终态写尽力而为——abandon 崩不得跳过 restore，否则 turn 卡 generating。
                try:
                    self.session.abandon_chat_turn_scene(chat_turn_id)
                except Exception:
                    logger.exception(
                        "retry cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                        chat_turn_id,
                    )
                try:
                    with cleanup_gate:
                        self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                        self.db.restore_interrupted_after_failed_retry(chat_turn_id)
                except Exception:
                    logger.exception(
                        "retry cleanup: restore_interrupted failed chat_turn_id=%s",
                        chat_turn_id,
                    )
                raise
            # #1353：若无尾随仍须放行整轮票后再收夜。
            if pending_ticket is not None:
                self._complete_pending_write(pending_ticket)
                pending_ticket = None
            # #526：回话已落库后收夜。失败响亮上抛，不得回滚已成回话；夜可恢复。
            close_after = getattr(self.session, "close_night_after_chat_if_needed", None)
            if close_after is not None:
                close_after(
                    getattr(result, "court_action", "") or "",
                    write_gate=self._runtime_write_gate(),
                )
            return payload
        finally:
            self._complete_pending_write(pending_ticket)

    def mindreading_for_minister(
        self, minister_name: str, chat_turn_id: int = 0,
    ) -> Dict[str, Any]:
        """轮询/恢复读取路径：某一轮召对的读心记录（#499 就绪即浮现）。

        `chat_turn_id>0` 时锁定该指定轮（取消/早重开的前端固定 expected 轮轮询，
        不受新一轮成为 latest 影响、旧轮读心不丢失/不错归）；为 0 时取最近活跃轮
        （历史入口首拉）。记录带持久 `id`，前端按 (chat_turn_id, id) 去重/归位。

        `pending`/`pending_turn_ids` 只读**持久 per-turn 任务态**（记录 + 终态标 failed/skip），
        不重算当前资格：读心任务在回话完成时被 worker 接受，接受后近臣关系变化不改其归属——
        「接受但未落库、未达终态」即 pending，直到 worker 写出记录或落 failed/skip 终态。
        （不因当前近臣关系变了就报 terminal-false，误停仍在跑的已接受任务。）
        `pending_turn_ids`=本大臣本回合所有待读心轮（不只最新），供重开路径对每一轮各自轮询、
        随新一轮发出仍存活（前端按面板/poll-batch 归属维持，不按发送作废）。
        """
        records: List[Dict[str, Any]] = []
        pending = False
        pending_turn_ids: List[int] = []
        if self._persistent_chat_minister(minister_name):
            target_turn = int(chat_turn_id)
            if target_turn <= 0:
                row = self.db.get_last_active_chat_turn(minister_name, self.state.turn)
                target_turn = int(row["id"]) if row is not None else 0
            chat_turn_id = target_turn
            if chat_turn_id > 0:
                records = list(self.db.list_mindreading_records(chat_turn_id))
                if not records:
                    # 单轮 pending：已接受在办（'running'）且未落库——显式任务态，'' 不算 accepted。
                    pending = self.db.get_mindreading_status(chat_turn_id) == "running"
            pending_turn_ids = self.db.list_pending_mindreading_turns(
                minister_name, self.state.turn,
            )
        return {
            "minister": minister_name,
            "chat_turn_id": chat_turn_id,
            "mindreading": records,
            "mindreading_pending": pending,
            "pending_turn_ids": pending_turn_ids,
        }

    def _chat_stream_payload(
        self,
        minister_name: str,
        text: str,
        chat_turn_id: int,
        before_snapshot: Dict[str, Any],
        accepted_turn: int,
        emit_delta,
        write_gate: Optional[threading.Lock] = None,
        action_intent_future: Optional[Future] = None,
        explicit_secret_order: bool = False,
    ) -> Dict[str, Any]:
        character = self.session._character(minister_name)
        chunks: List[str] = []
        agent = self.session.registry.get(character)
        # 动作意图分类只读皇帝消息，是唯一可与回话重叠的独立调用：由 worker 先于回话
        # 发出（跨越回话流式在飞），此处消费一次；不再在本轮内二次发起。
        run_output = None
        # The session audience seam is per-character: passing only the message
        # makes a web-streamed question bypass that perspective.
        agent_prompt = _audience_prompt_for_web_chat(
            self.session, text, character, chat_turn_id,
        )
        # LLM 流在无锁窗口跑（#498 AC10 可达熔断）
        stream = agent.run(agent_prompt, stream=True, stream_events=True, yield_run_output=True)
        # #542：dismiss tool 事件一出现就 start_exit，与尚未结束的回话流重叠。
        # #1566：密令 route 跳过流中 early-exit（与 interpret/session.chat 同门）。
        from ming_sim.cli_backend import _SECRET_PREFIXES as _STREAM_SECRET_PREFIXES
        stream_secret_route = bool(explicit_secret_order) or (text or "").strip().startswith(
            _STREAM_SECRET_PREFIXES
        )
        exit_started_during_stream = False
        for event in stream:
            content = getattr(event, "content", None)
            event_name = getattr(event, "event", "")
            # #1452：provider 失败时 agno 发 RunErrorEvent（如 Unknown model error）；
            # 不得静默吞成「流式回复为空」，与 agents.run_agent_stream_text 同闸。
            if type(event).__name__ == "RunErrorEvent":
                raise llm_stream_unavailable(content)
            if event_name == "RunContent" and content:
                delta = str(content)
                chunks.append(delta)
                emit_delta(delta)
            if not exit_started_during_stream and not stream_secret_route:
                # agno ToolCallCompletedEvent.tool；终事件 RunOutput.tools 作兜底。
                # 轻量 session 替身可能无此方法——缺则留给 interpret 旧缝/跳过。
                start_exit = getattr(
                    self.session, "start_exit_scene_from_dismiss_tools", None,
                )
                tool = getattr(event, "tool", None)
                tools_now: List[Any] = [tool] if tool is not None else []
                if not tools_now and type(event).__name__ in ("RunOutput", "RunCompletedEvent"):
                    tools_now = list(getattr(event, "tools", None) or [])
                if (
                    tools_now
                    and start_exit is not None
                    and start_exit(character.name, int(chat_turn_id or 0), tools_now)
                ):
                    exit_started_during_stream = True
            if type(event).__name__ in ("RunOutput", "RunCompletedEvent"):
                run_output = event
        # 流式跑完补 dump：流式 run_output(RunCompletedEvent)常无 .messages，
        # 传 agent= 让 _dump_llm_messages 走 agent.get_last_run_output() fallback 取 system/user。
        _dump_llm_messages(run_output, f"大臣对话/{minister_name}", agent=agent)
        answer = "".join(chunks).strip()
        # #1299/#1310：run_output.status=ERROR 时 extract 翻 typed（禁横幅当台词）；
        # 有 chunks 也必须过 status 闸，不能只在空 answer 时才 extract。
        if run_output is not None:
            extracted = extract_agent_text(run_output)
            if not answer:
                answer = extracted
        else:
            fail_if_llm_error(answer, "LLM 调用")
        if not answer:
            raise LLMUnavailable("LLM 调用失败：流式回复为空。")

        # #542：action/tool 解释（exit 若流中未启则幂等补登），write_gate 外统一 join，
        # 短事务原子持久化 reply + 本轮全部 scene。join 不得早于 start_exit。
        interpreted = self._chat_stream_interpret_tools(
            minister_name, text, character, answer, run_output,
            action_intent_future, chat_turn_id, explicit_secret_order,
        )
        scene_generated = self.session.join_chat_turn_scene(chat_turn_id)
        cm = write_gate if write_gate is not None else contextlib.nullcontext()
        with cm:
            with atomic(self.db):
                self.session.persist_chat_turn_scene(scene_generated or [])
                payload = self._chat_payload(
                    minister_name,
                    interpreted["answer"],
                    court_action=interpreted["court_action"],
                    next_minister=interpreted["next_minister"],
                    proposed_directive=interpreted["proposed"],
                    appointed_minister=interpreted["appointed"],
                    registered_minister=interpreted["registered"],
                    displaced_minister=interpreted["displaced"],
                    secret_order_id=interpreted["secret_order_id"],
                    pending_action_id=interpreted["pending_action_id"],
                    pending_action_failures=interpreted["pending_action_failures"],
                    chat_turn_id=chat_turn_id,
                    accepted_turn=accepted_turn,
                    directive_confirmation_ambiguous=interpreted["directive_ambiguous"],
                )
                self._record_chat_rollback_items(chat_turn_id, before_snapshot)
        return payload

    def _chat_stream_interpret_tools(
        self,
        minister_name: str,
        text: str,
        character: Any,
        answer: str,
        run_output: Any,
        action_intent_future: Any,
        chat_turn_id: int,
        explicit_secret_order: bool = False,
    ) -> Dict[str, Any]:
        # 截 propose_directive：入 pending_actions；截 propose_appointment：吏部铨选建档
        proposed = None
        appointed = ""
        registered = ""
        court_action = ""
        next_minister = ""
        displaced = ""
        secret_order_id = 0
        pending_action_id = 0
        tool_pending_action_id = 0
        tool_stage_failures: List[Dict[str, Any]] = []
        # #1566：密令 route 须在 command-verdict / exit / summon·dismiss 之前成立。
        message_text = (text or "").strip()
        from ming_sim.cli_backend import _DRAFT_PREFIXES, _SECRET_PREFIXES
        from ming_sim.action_clusters import is_confirmation_decision, resolve_primary_intent
        explicit_draft_prefix = message_text.startswith(_DRAFT_PREFIXES)
        explicit_secret_prefix = message_text.startswith(_SECRET_PREFIXES)
        explicit_secret_route = explicit_secret_order or explicit_secret_prefix
        # #526：口令判词与 session.chat 同缝（流式不经 session.chat；同步封闭集，无 Future）。
        # #1566：密令 route 跳过 command-verdict。
        apply_cmd = getattr(self.session, "_apply_audience_command_verdict", None)
        recognize_cmd = getattr(self.session, "_recognize_audience_command_verdict", None)
        if (
            not explicit_secret_route
            and apply_cmd is not None
            and recognize_cmd is not None
        ):
            from ming_sim.session import ChatTurnResult
            cmd_result = ChatTurnResult(answer=answer)
            apply_cmd(
                cmd_result, character, text,
                verdict=recognize_cmd(text),
                chat_turn_id=int(chat_turn_id or 0),
            )
            answer = cmd_result.answer
            if cmd_result.court_action:
                court_action = cmd_result.court_action
        if hasattr(self.db, "list_pending_actions"):
            preexisting_pending_action_ids = {
                int(p["id"]) for p in self.db.list_pending_actions(self.state.turn, minister_name=character.name)
            }
        else:
            preexisting_pending_action_ids = set()
        preclassified_intent = self.session._finish_cli_action_intent(action_intent_future)
        confirmation_intent_for_pending = getattr(
            self.session, "_confirmation_intent_for_preexisting_pending", None)
        if confirmation_intent_for_pending is not None and not explicit_secret_order:
            preclassified_intent = confirmation_intent_for_pending(
                character.name, text, answer, preclassified_intent, preexisting_pending_action_ids)
        confirmation_turn = is_confirmation_decision(
            resolve_primary_intent(preclassified_intent))
        if run_output is not None:
            for tool_exec in getattr(run_output, "tools", None) or []:
                res = str(getattr(tool_exec, "result", "") or "")
                tool_name = getattr(tool_exec, "tool_name", "")
                if tool_name == "propose_directive" or res.startswith("__pending_directive__"):
                    # confirmation / secret 前缀仍整枚跳过；孪生抑制在
                    # _stage_directive_tool_candidate generic 尾路按 kind 分派。
                    if confirmation_turn or explicit_secret_route:
                        continue
                    args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                    if not isinstance(args, dict):
                        args = {}
                    draft_text = res.removeprefix("__pending_directive__").strip()
                    if not draft_text:
                        draft_text = (args.get("decree_text") or "").strip()
                    if draft_text and GameSession._proposal_blocked(self.state):
                        draft_text = ""  # 恢复窗婉拒（ship-pre r2 软死锁环源头，同 session 路）
                    if draft_text:
                        # #502 L2 / #522 / #517：与 session 非流式同真源；
                        # 惩处结构化字段只从 tool arguments 交付。
                        stage_failures: List[Dict[str, Any]] = []
                        pending_action_id = coalesce_pending_action_id(
                            pending_action_id,
                            self.session._stage_directive_tool_candidate(
                                draft_text, character.name, message_text,
                                failures_out=stage_failures,
                                punish_action=args.get("punish_action"),
                                target_id=args.get("target_id"),
                                name=args.get("name"),
                                amount=args.get("amount"),
                                transaction_category=args.get("transaction_category"),
                                backing_dossier_id=args.get("backing_dossier_id"),
                                issue_id=args.get("issue_id"),
                                issue_disposition=args.get("issue_disposition"),
                                intent_candidates=preclassified_intent,
                            ),
                        )
                        if stage_failures:
                            # Merge into method-local channel; confirmation-path
                            # pending_action_failures are appended below.
                            tool_stage_failures.extend(stage_failures)
                elif (
                    tool_name == "propose_appointment"
                    or res.startswith("__pending_appointment__")
                    or res.startswith("__pending_recommendation__")
                ):
                    if confirmation_turn or explicit_draft_prefix or explicit_secret_route:
                        continue
                    payload_json = res.removeprefix("__pending_recommendation__")
                    payload_json = payload_json.removeprefix("__pending_appointment__").strip()
                    if not payload_json:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        payload_json = json.dumps(args, ensure_ascii=False)
                    pending_action_id = coalesce_pending_action_id(
                        pending_action_id,
                        self.session._stage_appointment_candidate(
                            payload_json, character, message_text,
                        ),
                    )
                elif tool_name == "register_unlisted_person" or res.startswith("__pending_unlisted_person__"):
                    if confirmation_turn or explicit_draft_prefix or explicit_secret_route:
                        continue
                    payload_json = res.removeprefix("__pending_unlisted_person__").strip()
                    if not payload_json:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        payload_json = json.dumps(args, ensure_ascii=False)
                    registered, summon_after = self.session._apply_unlisted_person_registration(payload_json)
                    # #670 / ADR 0038+0096：补档已落 DB 后须走共享 admission；仅 allowed 换人。
                    if registered and summon_after:
                        target = self.session.content.characters.get(registered)
                        if target is not None:
                            decision = self.session.consume_audience_admission(
                                target,
                                origin_id=f"web:tool:{int(chat_turn_id or 0)}:{target.name}",
                                origin_chat_turn_id=int(chat_turn_id or 0),
                            )
                            if decision.allowed:
                                court_action = "summon"
                                next_minister = target.name
                elif tool_name == "summon_minister" or res.startswith("__summon__"):
                    # #1566：密令 route 跳过 summon / 换人。
                    if explicit_secret_route:
                        continue
                    args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                    target_name = res.removeprefix("__summon__").strip() or args.get("name", "")
                    if target_name:
                        try:
                            target, _is_temporary = self.session.summon_character(
                                target_name, character, allow_temporary=False
                            )
                        except ValueError:
                            target = None
                        if target is not None:
                            decision = self.session.consume_audience_admission(
                                target,
                                origin_id=f"web:tool:{int(chat_turn_id or 0)}:{target.name}",
                                origin_chat_turn_id=int(chat_turn_id or 0),
                                travel_tone=args.get("行程语气"),
                            )
                            if decision.allowed:
                                court_action = "summon"
                                next_minister = target.name
                            # #670 P6'/P7：拒入殿只不设 court_action/next_minister；闸文不进 LLM answer。
                elif tool_name == "dismiss_minister" or res == "__dismiss__":
                    # #1566：密令 route 跳过 dismiss / exit。
                    if explicit_secret_route:
                        continue
                    court_action = "dismiss"
                    # AC1（#500）/#506 L1：令退同源落账绑本轮。#542：流中已 start_exit
                    # 时此处幂等 no-op；未启则补登（仅 tools 终事件路径）。
                    start_exit = getattr(
                        self.session, "start_exit_scene_from_dismiss_tools", None,
                    )
                    if start_exit is not None:
                        start_exit(
                            character.name, int(chat_turn_id or 0), [tool_exec],
                        )
                    elif hasattr(self.db, "conn"):
                        from ming_sim.audience_night import dismiss_from_audience
                        entry_id = dismiss_from_audience(
                            self.db, character.name,
                            origin_chat_turn_id=chat_turn_id, state=self.state,
                        )
                        if entry_id and chat_turn_id and hasattr(
                            self.session, "start_chat_turn_exit_scene",
                        ):
                            self.session.start_chat_turn_exit_scene(
                                character.name, int(chat_turn_id), int(entry_id),
                            )
                elif res.startswith("__commitment_rush__"):
                    if confirmation_turn or explicit_draft_prefix or explicit_secret_route:
                        continue
                    if GameSession._proposal_blocked(self.state):
                        continue
                    payload_json = res.removeprefix("__commitment_rush__").strip()
                    try:
                        payload = json.loads(payload_json) if payload_json else {}
                    except (ValueError, TypeError):
                        payload = {}
                    if isinstance(payload, dict):
                        try:
                            issue_id = int(payload.get("issue_id") or 0)
                        except (TypeError, ValueError):
                            issue_id = 0
                        if issue_id > 0:
                            staged_id = self.db.stage_pending_action(
                                self.state.turn,
                                kind="commitment",
                                action="催办",
                                minister_name=character.name,
                                target_id=issue_id,
                                payload={
                                    "stage_idx": int(payload.get("stage_idx") or 0),
                                    "deadline_months": payload.get("deadline_months", 1),
                                    "reason": str(payload.get("reason") or "")[:120],
                                },
                            )
                            pending_action_id = coalesce_pending_action_id(
                                pending_action_id, staged_id,
                            )
                            tool_pending_action_id = coalesce_pending_action_id(
                                tool_pending_action_id, staged_id,
                            )
                elif (
                    res.startswith("__secret_order_registered__")
                    or res.startswith("__secret_order__")
                    or res.startswith("__secret_action__")
                ):
                    if confirmation_turn or explicit_draft_prefix:
                        continue
                    if GameSession._proposal_blocked(self.state):
                        continue
                    if res.startswith("__secret_action__"):
                        payload_json = res.removeprefix("__secret_action__").strip()
                        try:
                            data = json.loads(payload_json) if payload_json else {}
                        except (ValueError, TypeError):
                            data = {}
                        if isinstance(data, dict):
                            action = str(data.get("action") or "").strip()
                            try:
                                order_id = int(data.get("order_id") or 0)
                            except (TypeError, ValueError):
                                order_id = 0
                            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                            if action and order_id:
                                if action == "更新":
                                    payload = self.db.attach_secret_oral_pin(
                                        character.name, int(self.state.turn), payload,
                                    )
                                staged_id = self.db.stage_pending_action(
                                    self.state.turn, kind="secret_order", action=action,
                                    minister_name=character.name, target_id=order_id,
                                    payload=payload,
                                )
                                pending_action_id = coalesce_pending_action_id(
                                    pending_action_id, staged_id,
                                )
                                tool_pending_action_id = coalesce_pending_action_id(
                                    tool_pending_action_id, staged_id,
                                )
                    elif res.startswith("__secret_order_registered__"):
                        try:
                            registered_id = int(
                                res.removeprefix("__secret_order_registered__").split("__", 1)[0]
                            )
                        except Exception:
                            registered_id = 0
                        if registered_id:
                            staged_id = self.session._stage_legacy_registered_secret_order(
                                registered_id, character.name)
                            pending_action_id = coalesce_pending_action_id(
                                pending_action_id, staged_id,
                            )
                            tool_pending_action_id = coalesce_pending_action_id(
                                tool_pending_action_id, staged_id,
                            )
                    else:
                        payload_json = res.removeprefix("__secret_order__").strip()
                        if not payload_json:
                            args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                            payload_json = json.dumps(args, ensure_ascii=False)
                        try:
                            payload = json.loads(payload_json) if payload_json else {}
                        except (ValueError, TypeError):
                            payload = {}
                        if isinstance(payload, dict):
                            from ming_sim.cli_backend import confirm_dossier_links
                            dossier_links = confirm_dossier_links(
                                answer,
                                self.db.list_referenceable_dossiers(
                                    character.name, self.state.turn),
                                payload.get("dossier_links"),
                                llm_config=getattr(self.session, "llm_config", None),
                            )
                            staged_id = self.db.stage_pending_action(
                                self.state.turn, kind="secret_order", action="新建",
                                minister_name=character.name, target_id=None,
                                payload={
                                    "title": str(payload.get("title") or "").strip(),
                                    "content": str(payload.get("content") or "").strip(),
                                    "assignee": str(payload.get("assignee") or character.name).strip(),
                                    "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
                                    "deadline_months": payload.get("deadline_months") or 0,
                                    "excluded_names": payload.get("excluded_names") if isinstance(payload.get("excluded_names"), list) else [],
                                    "excluded_offices": payload.get("excluded_offices") if isinstance(payload.get("excluded_offices"), list) else [],
                                    "dossier_links": dossier_links,
                                    "covert_task": payload.get("covert_task") if isinstance(payload.get("covert_task"), dict) else None,
                                },
                            )
                            pending_action_id = coalesce_pending_action_id(
                                pending_action_id, staged_id,
                            )
                            tool_pending_action_id = coalesce_pending_action_id(
                                tool_pending_action_id, staged_id,
                            )
                # 密令结案不再走大臣工具：月末 settle 按实进度对账派生 done/failed（#1504）
        # CLI 后端（agy/codex）：玩家用拟旨/密令按钮（消息带前缀）时，把大臣这句回话原文入档。
        # CLI 后端会话落地走共享真源 session.apply_cli_conversation_actions(同 session.chat 非流式路径)，
        # 杜绝 web/CLI 两边逻辑漂移（CMR F3 / codexC-1）。
        # #568：chat_turn_id 经 session 作用域透传（apply 签名不动），供点策 origin 结构化排除本轮。
        prev_turn = getattr(self.session, "_active_chat_turn_id", 0)
        self.session._active_chat_turn_id = int(chat_turn_id or 0)
        try:
            res = self.session.apply_cli_conversation_actions(
                character, text, answer,
                has_directive=proposed is not None or bool(pending_action_id),
                secret_order_id=secret_order_id,
                preclassified_intent=preclassified_intent,
                confirm_target_ids=preexisting_pending_action_ids,
                explicit_secret_order=explicit_secret_order,
            )
        finally:
            self.session._active_chat_turn_id = prev_turn
        if proposed is None and res["directive"]:
            proposed = res["directive"]
        if res["secret_order_id"]:
            secret_order_id = res["secret_order_id"]
        pending_action_id = pending_action_id or int(res.get("pending_action_id") or 0)
        if pending_action_id:
            if tool_pending_action_id:
                self.session._merge_staged_new_secret_order_content(
                    tool_pending_action_id,
                    character.name,
                    text,
                )
        # #502 AC5：多道准驳含糊 → 结构化含糊态透进 chat payload + 大臣当场追问哪一道（表面契约可达）。
        directive_ambiguous = res.get("directive_confirmation_ambiguous")
        if directive_ambiguous:
            answer = GameSession._ensure_clarification_cue(answer, directive_ambiguous)
        # #1274 V-1：查无此人 → 戏内回禀附于回话；不落草案、不回滚整轮。
        esc = res.get("unknown_participant_escalate") or {}
        report = str(esc.get("report") or "").strip()
        if report:
            answer = GameSession._ensure_unknown_participant_report_cue(answer, report)
        pending_action_failures = list(res.get("pending_action_failures") or [])
        if tool_stage_failures:
            pending_action_failures = pending_action_failures + list(tool_stage_failures)
        # 仅解释/登记；join + 短事务落账由 _chat_stream_payload 在 gate 外/内分阶完成。
        return {
            "answer": answer,
            "court_action": court_action,
            "next_minister": next_minister,
            "proposed": proposed,
            "appointed": appointed,
            "registered": registered,
            "displaced": displaced,
            "secret_order_id": secret_order_id,
            "pending_action_id": pending_action_id,
            "pending_action_failures": pending_action_failures,
            "directive_ambiguous": directive_ambiguous,
        }

    def _dispatch_relation_judge(self, chat_turn_id: Any) -> Optional[threading.Thread]:
        """启动关系判官旁路；基础设施失败只响亮降级，不得阻塞回话主链。"""
        if not chat_turn_id:
            return None
        try:
            return self._spawn_pending_write_thread(
                self._trail_relation_judge_beat,
                (),
                "audience-p5-relation-judge",
                ticket_key=("turn", int(chat_turn_id)),
            )
        except Exception:
            logger.exception(
                "relation judge dispatch degraded chat_turn_id=%s", chat_turn_id,
            )
            return None

    def _trail_relation_judge_beat(
        self, *, pending_ticket: Optional[WriteTicket] = None,
    ) -> Optional[Dict[str, Any]]:
        """#634 / ADR 0082：召对判官拍——P5 并行记账腿。

        派发先于回话生成（不依赖本轮回话输出，TD-9 零额外等待）；判读窗口＝已判
        水位后的已完成轮。LLM 失败降级留痕不抛（漏判不阻塞召对主链）；写库经票据
        执行 seam。#1353：spawn 路票据由 spawner finally 归还；直接调用无票时自领自还。
        """
        own_ticket = False
        try:
            if pending_ticket is None:
                pending_ticket = self._mark_pending_write()
                own_ticket = pending_ticket is not None
            if pending_ticket is None:
                return None
            if pending_ticket.cancelled or pending_ticket._done:
                return None
            return run_summon_relation_judge(
                self.db, self.state,
                llm_config=getattr(self.session, "llm_config", None),
                write_gate=self._ticketed_write_gate(pending_ticket),
            )
        except TicketCancelled:
            return None
        except Exception:
            logger.exception("relation judge worker degraded")
            return None
        finally:
            if own_ticket:
                self._complete_pending_write(pending_ticket)

    def _trail_mindreading_after_reply(
        self,
        minister_name: str,
        minister_reply: str,
        chat_turn_id: int,
        *,
        pending_ticket: Optional[WriteTicket] = None,
        owns_pending: bool = False,  # 旧形兼容；新路传 pending_ticket
    ) -> Optional[Dict[str, Any]]:
        """P5（#499）：回话 done 后在本 worker 内直接尾随读心（依赖回话、必串于其后）。

        读心是单一依赖任务、调用方随即等其结果——无需另起 executor/Future。回话已完成并
        落库（读心闸门=非空完整回话，喂真实 reply 而非问句）；写库经票据执行 seam。
        #1353：spawn 路票据生命周期在 spawner finally；本腿只消费票、不归还交接票。
        直接调用无票时自领并自还。失败不回滚回话。无票且 seal → 零 LLM 零写。
        """
        del owns_pending  # 票据路径取代布尔 ownership
        own_ticket = False
        try:
            reply = str(minister_reply or "")
            if not chat_turn_id or not reply.strip():
                return None
            if pending_ticket is None:
                pending_ticket = self._mark_pending_write(
                    key=("turn", int(chat_turn_id)),
                )
                own_ticket = pending_ticket is not None
            if pending_ticket is None:
                return None  # seal/拒票：无第二入口
            # 撤回后 ticket 已 cancel：禁复活写（ADR 0038）。
            if pending_ticket.cancelled or pending_ticket._done:
                return None
            write_gate = self._ticketed_write_gate(pending_ticket)
            # 资格判定唯一入口在 run_mindreading_for_turn 内（不在此重复查询）
            terminal_status = ""
            try:
                result = run_mindreading_for_turn(
                    db=self.db,
                    state=self.state,
                    content_characters=self.content.characters,
                    minister_name=minister_name,
                    minister_reply=reply,
                    llm_config=getattr(self.session, "llm_config", None),
                    chat_turn_id=chat_turn_id,
                    write_gate=write_gate,
                )
            except TicketCancelled:
                return None
            except Exception:
                # 读心失败：回话已 done，不回滚。落终态 failed 让重开轮询能终止。
                result = None
                terminal_status = "failed"
            else:
                # 返回非记录（不适用/目标已失效）→ 终态 skip，同样让轮询终止。
                if not isinstance(result, dict):
                    terminal_status = "skip"
            if terminal_status:
                # 终态落库经同一票据 seam；已 ready 的轮不打标。
                try:
                    with write_gate:
                        self.db.set_mindreading_status(chat_turn_id, terminal_status)
                except TicketCancelled:
                    return None
                except Exception:
                    pass
            return result if isinstance(result, dict) else None
        finally:
            # 仅自领票由本腿收口；spawn 交接票由 spawner finally 归还（stub 安全）。
            if own_ticket:
                self._complete_pending_write(pending_ticket)

    def _trail_highlight_judge_after_reply(
        self,
        minister_reply: str,
        *,
        message_id: int,
        chat_turn_id: int = 0,
        timeout_s: float = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
        gate_already_held: bool = False,
        pending_ticket: Optional[WriteTicket] = None,
    ) -> List[str]:
        """#544 / ADR 0045：回话完成后同通道高亮判官。超时/坏输出 → []，落库短语。

        判官失败边界在 run_highlight_judge（带日志）；此处只收窄写库 sqlite 异常并 warning。
        写库经票据执行 seam；调用方已持闸时传 gate_already_held=True，禁同线程二次 acquire。
        匹配/剥离在前端，此处只存短语。无票且 seal → 零 LLM 零写。
        #1353：spawn 路票据由 spawner finally 归还；本腿只消费交接票。直接调用无票时自领自还。
        """
        own_ticket = False
        mid = int(message_id or 0)
        reply = str(minister_reply or "")
        if mid <= 0 or not reply.strip():
            return []
        # 未由调用方领票且非持闸兼容路 → 本腿自领 turn key 票（生产写必经 seam）。
        if pending_ticket is None and not gate_already_held and int(chat_turn_id or 0) > 0:
            pending_ticket = self._mark_pending_write(
                key=("turn", int(chat_turn_id)),
            )
            own_ticket = pending_ticket is not None
        if pending_ticket is None and not gate_already_held:
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
            # 持闸态是 _chat_core span 一等参数：密令兼容路外层已持非可重入 Lock，
            # 此处再 with write_gate 会永久挂死（外层 finally 永不 release）。
            # 已持闸时票仍覆盖本写（调用方收口 complete）；只做取消检查，不二次 acquire。
            if gate_already_held:
                if pending_ticket is not None and (
                    pending_ticket.cancelled or pending_ticket._done
                ):
                    return []
                gate_cm: Any = contextlib.nullcontext()
            else:
                gate_cm = self._ticketed_write_gate(pending_ticket)
            try:
                with gate_cm:
                    self.db.set_message_highlights(mid, phrases)
            except TicketCancelled:
                return []
            except sqlite3.Error as exc:
                logger.warning(
                    "highlight judge persist failed message_id=%s: %s",
                    mid, exc, exc_info=True,
                )
                return []
            return phrases
        finally:
            # 仅自领票由本腿收口；spawn 交接/持闸兼容票由 spawner 或调用方归还。
            if own_ticket:
                self._complete_pending_write(pending_ticket)

    def _trail_extraction_after_reply(
        self,
        minister_name: str,
        minister_reply: str,
        chat_turn_id: int,
        *,
        pending_ticket: Optional[WriteTicket] = None,
        owns_pending: bool = False,  # 旧形兼容
    ) -> Optional[Dict[str, Any]]:
        """#501：回话 done 后尾随叙事抽取落账（与读心并行——二者皆只依赖已完成回话，P5）。

        核在 `audience_extraction.trail_extraction_after_reply`（Web/CLI 共用）；本方法只
        包票据执行 seam。#1353：spawn 路票据由 spawner finally 归还；本腿只消费交接票。
        直接调用无票时自领自还；seal 拒票 → 零写（禁裸 gate）。
        """
        del owns_pending
        own_ticket = False
        try:
            if pending_ticket is None and int(chat_turn_id or 0) > 0:
                pending_ticket = self._mark_pending_write(
                    key=("turn", int(chat_turn_id)),
                )
                own_ticket = pending_ticket is not None
            if pending_ticket is None:
                return None
            if pending_ticket.cancelled or pending_ticket._done:
                return None
            return trail_extraction_after_reply(
                db=self.db,
                minister_name=minister_name,
                minister_reply=minister_reply,
                chat_turn_id=int(chat_turn_id),
                llm_config=getattr(self.session, "llm_config", None),
                write_gate=self._ticketed_write_gate(pending_ticket),
            )
        except TicketCancelled:
            return None
        finally:
            # 仅自领票由本腿收口；spawn 交接票由 spawner finally 归还（stub 安全）。
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

    def _spawn_extraction_trail(
        self, minister_name: str, minister_reply: str, chat_turn_id: int,
    ) -> Optional[threading.Thread]:
        """在独立后台线程发起抽取落账尾随（与读心并行）。原子交接 pending ownership：
        任何 DB 访问前先登记，关闭须等其完成。非召对夜轮 / 空白回话由尾随函数内自决
        （空白 → 标 done，不占永久待补；与 run 入口一致）。seal → None。"""
        if not chat_turn_id:
            return None
        return self._spawn_pending_write_thread(
            self._trail_extraction_after_reply,
            (minister_name, str(minister_reply or ""), chat_turn_id),
            "audience-p5-extraction",
            ticket_key=("turn", int(chat_turn_id)),
        )

    def _run_startup_extraction_catch_up(
        self,
        *,
        pending_ticket: Optional[WriteTicket] = None,
        owns_pending: bool = False,
    ) -> None:
        """重开补跑（ADR 0036）：已持久化回话但账未抽 → 补跑抽取，不回滚对话。

        `catch_up_pending_extractions` 从不抛——补跑失败标待补、不锁档，**永不进启动致命路径**。
        在后台线程跑，不阻塞存档加载。写经已领票据 seam（禁裸 gate）。
        #1353：spawn 路票据由 spawner finally 归还；本函数不归还交接票（complete 幂等保直接调用钉）。
        """
        del owns_pending
        try:
            if pending_ticket is None:
                return
            if pending_ticket.cancelled or pending_ticket._done:
                return
            catch_up_pending_extractions(
                db=self.db,
                llm_config=getattr(self.session, "llm_config", None),
                write_gate=self._ticketed_write_gate(pending_ticket),
            )
        except TicketCancelled:
            return
        except Exception as exc:
            # catch_up 契约从不抛；到此=意外故障。铁律：不锁档、不进启动致命路径——
            # 但**留痕不静默**（窄捕 + log，账仍待补候下轮 drain/重试）。
            tlog(f"[audience-extraction] 启动补跑意外故障（不锁档、已忽略）：{exc}")
        finally:
            # 直接调用钉（test_startup_catchup_uses_ticketed_gate_not_bare）仍依赖此处收口；
            # spawn 路 spawner 也会 complete——complete 幂等，双路径皆安全。
            if pending_ticket is not None:
                self._complete_pending_write(pending_ticket)

    def _spawn_startup_extraction_catch_up(self) -> None:
        """存档（重）加载后在后台发起一次抽取补跑（重开崩溃窗口丢的站台/进出账补落）。

        #1353 r7：无待补时不领票——空 catch-up 占票会与同 session 的 barrier/
        `_pending_writes_count` 钉竞态（全量 xdist 下 residual ticket）。有待补才
        claim+spawn；key=("startup",) 与 turn/pending 区分。
        #1353 r10：预检 list_unextracted 短持 runtime gate（共享 conn 禁裸读）。
        """
        if not hasattr(self.db, "conn"):
            return
        if not hasattr(self.db, "list_unextracted_replies"):
            return
        with self._runtime_write_gate():
            pending = self.db.list_unextracted_replies() or []
        if not pending:
            return
        self._spawn_pending_write_thread(
            self._run_startup_extraction_catch_up,
            (),
            "audience-startup-extraction-catchup",
            ticket_key=("startup",),
        )

    def pending_story_extractions(self) -> Dict[str, Any]:
        """#501/#1353：待补抽取只读诊断（本开夜 turn ids + 大臣名 + 计数）。

        与 close_night drain 挡收夜判定同一真源（list_unextracted via helper）。
        欠账唯一处理路=过月/收夜内部 drain；本接口不承载玩家手动补写 CTA。
        无开夜则回全库待补。测试替身无 conn 时空。
        """
        if not hasattr(self.db, "conn"):
            return {"night_id": 0, "count": 0, "pending": []}
        from ming_sim.audience_night import (
            _pending_extraction_rows,
            get_open_night,
        )

        open_n = get_open_night(self.db)
        nid = int(open_n["id"]) if open_n else None
        night_status = str((open_n or {}).get("status") or "")
        if nid is not None and int(nid) > 0:
            rows = _pending_extraction_rows(self.db, int(nid))
        else:
            rows = self.db.list_unextracted_replies(night_id=nid)
        pending = [
            {
                "chat_turn_id": int(r.get("chat_turn_id") or 0),
                "minister_name": str(r.get("minister_name") or ""),
                "night_id": int(r.get("night_id") or 0),
            }
            for r in rows
        ]
        out: Dict[str, Any] = {
            "night_id": int(nid or 0),
            "count": len(pending),
            "pending": pending,
        }
        if night_status:
            out["night_status"] = night_status
        return out

    def chat_stream(self, minister_name: str, message: str, intent: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        if minister_name not in self.content.characters and minister_name not in self.session.temporary_characters:
            yield {"type": "error", "message": f"未找到大臣：{minister_name}"}
            return
        text = message.strip()
        if not text:
            yield {"type": "error", "message": "问话不能为空。"}
            return
        # #498：结算/亲裁相位不得召对（夜不跨月）。锁前查仅快速失败；权威判定在持 gate 后复查
        # （见下），防 TOCTOU——SUMMONING 通过后等 gate 时被结算改相位仍会开夜。
        if getattr(self.state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
            yield {"type": "error", "message": "月末结算/亲裁进行中，暂不能召对。"}
            return
        # 整轮（含读心尾随）共用一次队列票据——关闭/fixture 必须等其完成。
        pending_ticket = self._mark_pending_write()
        if pending_ticket is None:
            yield {"type": "error", "message": "当前会话正在关闭，请回菜单重新进入。"}
            return
        # #1353 r10：屏障已受理则拒后序流式聊天（与 seal 合流）；否则 prologue/epilogue
        # 经 ticketed gate（写段序）。LLM 仍在无锁窗（AC10）。
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
        # #1566：场外记召成功后在 gate 外物化 scene；（minister, admission_result, origin_id）
        offsite_summon: Optional[tuple[str, str, str]] = None
        try:
            write_gate.acquire()
        except TicketCancelled:
            self._complete_pending_write(pending_ticket)
            yield {"type": "error", "message": "当前会话正在关闭，请回菜单重新进入。"}
            return
        try:
            # 权威相位复查（持 gate 内，建 chat turn/开夜/写库之前）：等锁期间若被结算改相位则拒。
            if getattr(self.state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
                self._complete_pending_write(pending_ticket)
                yield {"type": "error", "message": "月末结算/亲裁进行中，暂不能召对。"}
                return
            # #612：CLOSING 冻结新对话——唯一玩家输入准入真源，无平行 status 判断。
            if hasattr(self.db, "conn"):
                from ming_sim.audience_night import (
                    AudienceNightError,
                    assert_night_accepts_player_input,
                )
                try:
                    assert_night_accepts_player_input(self.db, what="召对")
                except AudienceNightError as err:
                    if getattr(err, "code", "") == "night_closing":
                        self._complete_pending_write(pending_ticket)
                        yield {
                            "type": "error",
                            "message": str(err) or "本夜收夜中，暂不能召对。",
                            "code": "night_closing",
                        }
                        return
                    raise
            if self._audience_turn_in_flight(minister_name):
                self._complete_pending_write(pending_ticket)
                yield {"type": "error", "message": f"{minister_name}上一轮回奏仍在进行，请稍候再问。"}
                return
            accepted_turn = int(self.state.turn)
            # #1566：正式密令前缀先入密令管线；场外记召成功后在 gate 外物化 scene。
            offsite_secret_order = False
            explicit_secret_order = intent == "secret_order" or self._message_is_formal_secret_order(text)
            if not explicit_secret_order:
                stream_origin = f"web:stream:{accepted_turn}:{minister_name}"
                admission = self.session.consume_audience_admission(
                    self.session._character(minister_name),
                    origin_id=stream_origin,
                )
                if not admission.allowed:
                    # 资格失败：非空 reason → SSE error，当场结清 ticket。
                    # 成功记召：ticket 须覆盖后续 scene LLM/持久化，禁止提前 complete。
                    if admission.reason:
                        self._complete_pending_write(pending_ticket)
                        pending_ticket = None
                        yield {"type": "error", "message": admission.reason}
                        return
                    if admission.result in (
                        AudienceAdmission.SUMMON_FRESH,
                        AudienceAdmission.SUMMON_IN_TRANSIT,
                    ):
                        offsite_summon = (
                            minister_name,
                            admission.result.value,
                            stream_origin,
                        )
                    else:
                        self._complete_pending_write(pending_ticket)
                        pending_ticket = None
                        yield {
                            "type": "error",
                            "message": (
                                admission.result.value
                                if admission.result is not None else ""
                            ),
                        }
                        return
            else:
                decision = self.session.admit_audience(
                    self.session._character(minister_name),
                )
                if decision.reason:
                    self._complete_pending_write(pending_ticket)
                    pending_ticket = None
                    yield {"type": "error", "message": decision.reason}
                    return
                offsite_secret_order = decision.result in (
                    AudienceAdmission.SUMMON_FRESH,
                    AudienceAdmission.SUMMON_IN_TRANSIT,
                )
            if offsite_summon is None:
                if self._persistent_chat_minister(minister_name):
                    from ming_sim.audience_night import encode_chat_turn_route
                    chat_turn_id, before_snapshot = self._start_chat_turn(
                        minister_name,
                        attach_to_hall=not offsite_secret_order,
                        route=encode_chat_turn_route(
                            explicit_secret_order=explicit_secret_order,
                            offsite=offsite_secret_order,
                        ),
                    )
                self.chat_history.setdefault(minister_name, []).append({"role": "user", "content": text})
                if minister_name not in self.session.temporary_characters:
                    message_id = self.db.append_chat_message(minister_name, accepted_turn, "user", text)
                    if chat_turn_id:
                        self.db.update_chat_turn_messages(chat_turn_id, user_message_id=message_id)
        except Exception:
            # Release gate before scene drain — prologue may have already started futures.
            if gate_held:
                try:
                    write_gate.release()
                except RuntimeError:
                    pass
                gate_held = False
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；abandon / 终态写分 try，
            # 清理异常不覆盖原始错误、不阻断终态上抛。
            try:
                if chat_turn_id:
                    self.session.abandon_chat_turn_scene(chat_turn_id)
            except Exception:
                logger.exception(
                    "stream prologue cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                    chat_turn_id,
                )
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
            except Exception:
                logger.exception(
                    "stream prologue cleanup: fail_chat_turn/reload failed chat_turn_id=%s",
                    chat_turn_id,
                )
            self._complete_pending_write(pending_ticket)
            raise
        finally:
            if gate_held:
                write_gate.release()

        if offsite_summon is not None:
            try:
                summon_name, summon_result, summon_origin = offsite_summon
                self._finish_offsite_summon_scene(
                    origin_id=summon_origin, minister_name=summon_name,
                    gate_cm=write_gate,
                )
                # #1566：成功载荷的同连接 DB 投影读须纳入 ticketed gate 短临界段，
                # 与并发同源请求的读/写在同一 sqlite connection 上互斥；LLM 早已在
                # write_back 内结清，此处只剩纯读。
                with write_gate:
                    payload = self._summon_admission_success_payload(
                        summon_name, summon_result,
                    )
                yield {"type": "done", "payload": payload}
                yield {"type": "end"}
            finally:
                self._complete_pending_write(pending_ticket)
            return

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
            if hasattr(self.db, "kv_get"):
                identity["campaign_id"] = str(self.db.kv_get("campaign_id") or "")
            if chat_turn_id and hasattr(self.db, "conn"):
                from ming_sim.audience_night import get_open_night
                open_night = get_open_night(self.db)
                identity["night_id"] = int(open_night["id"]) if open_night else 0
                ev_queue.put({"type": "accepted", **identity})
        except Exception as error:  # noqa: BLE001
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；原始 error 仍下发。
            try:
                if chat_turn_id:
                    self.session.abandon_chat_turn_scene(chat_turn_id)
            except Exception:
                logger.exception(
                    "stream identity cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                    chat_turn_id,
                )
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
            except Exception:
                logger.exception(
                    "stream identity cleanup: fail_chat_turn/reload failed chat_turn_id=%s",
                    chat_turn_id,
                )
            self._complete_pending_write(pending_ticket)
            yield {"type": "error", "message": str(error), **identity}
            return

        def emit_delta(delta: str) -> None:
            ev_queue.put({"type": "delta", "content": delta})

        def worker() -> None:
            nonlocal pending_ticket
            payload: Optional[Dict[str, Any]] = None
            try:
                try:
                    # P5：唯一不依赖回话输出的独立调用 = CLI 动作意图分类（只读皇帝消息）。
                    # 先于回话在其自有 executor 上发出，跨越回话流式在飞，回话后消费一次。
                    # 回奏（return_report）须先写见闻再组回话 prompt，是回话前置依赖、非并行调用，
                    # 由 _audience_prompt_for_message 单次落地，不在此重复发起。
                    character = self.session._character(minister_name)
                    action_intent_future = (
                        None if explicit_secret_order
                        else self.session._start_cli_action_intent(character, text)
                    )

                    # #634 P5：召对判官拍——唯一不依赖本轮回话输出的记账腿，与回话
                    # 生成并行发出（TD-9 零额外等待）；写库经自有票据，join 于收夜前。
                    self._dispatch_relation_judge(chat_turn_id)

                    # LLM 在无锁窗口跑；落库/会话动作再抢 write_gate（#498 AC10）
                    payload = self._chat_stream_payload(
                        minister_name, text, chat_turn_id, before_snapshot,
                        accepted_turn, emit_delta,
                        write_gate=write_gate,
                        action_intent_future=action_intent_future,
                        explicit_secret_order=explicit_secret_order,
                    )

                    # P5：先 done（回话可见），再读心∥高亮∥抽取补挂，最后 end——玩家无「为后处理黑屏」。
                    ev_queue.put({"type": "done", "payload": payload or {}})
                    answer = str((payload or {}).get("answer") or "")
                    message_id = int((payload or {}).get("minister_message_id") or 0)
                    # #1353：三腿统一经 _spawn_pending_write_thread（claim→try callee→finally 归还）；
                    # seal/claim 拒绝 → 不起线程、零 LLM 零写。整轮票在 spawn 后空放行。
                    turn_key = ("turn", int(chat_turn_id)) if chat_turn_id else None
                    extraction_thread: Optional[threading.Thread] = None
                    highlight_thread: Optional[threading.Thread] = None
                    mind_thread: Optional[threading.Thread] = None
                    highlight_box: List[str] = []
                    mind_box: List[Optional[Dict[str, Any]]] = []

                    if chat_turn_id and answer:
                        extraction_thread = self._spawn_extraction_trail(
                            minister_name, answer, chat_turn_id,
                        )

                        if message_id and answer:
                            def _highlight_worker(
                                reply: str,
                                mid: int,
                                ctid: int,
                                *,
                                pending_ticket: Optional[WriteTicket] = None,
                            ) -> None:
                                highlight_box.extend(
                                    self._trail_highlight_judge_after_reply(
                                        reply,
                                        message_id=mid,
                                        chat_turn_id=ctid,
                                        pending_ticket=pending_ticket,
                                    ) or []
                                )

                            highlight_thread = self._spawn_pending_write_thread(
                                _highlight_worker,
                                (answer, message_id, chat_turn_id),
                                "audience-p5-highlight",
                                ticket_key=turn_key,
                            )

                        def _mind_worker(
                            mname: str,
                            reply: str,
                            ctid: int,
                            *,
                            pending_ticket: Optional[WriteTicket] = None,
                        ) -> None:
                            try:
                                mind_box.append(
                                    self._trail_mindreading_after_reply(
                                        mname, reply, ctid,
                                        pending_ticket=pending_ticket,
                                    )
                                )
                            except Exception:
                                mind_box.append(None)

                        mind_thread = self._spawn_pending_write_thread(
                            _mind_worker,
                            (minister_name, answer, chat_turn_id),
                            "audience-p5-mindreading",
                            ticket_key=turn_key,
                        )
                        # 整轮票在尾随已领票后放行——屏障盯尾随票。
                        self._complete_pending_write(pending_ticket)
                        pending_ticket = None

                    if mind_thread is not None:
                        mind_thread.join()
                    mind_payload = mind_box[0] if mind_box else None
                    if mind_payload:
                        ev_queue.put({
                            "type": "mindreading",
                            "payload": mind_payload,
                            "chat_turn_id": chat_turn_id,
                        })
                    # #544：流式不挡流——done 后补挂高亮（超时封顶）；有清单才发事件。
                    if highlight_thread is not None:
                        highlight_thread.join()
                    if highlight_box:
                        ev_queue.put({
                            "type": "highlights",
                            "highlights": list(highlight_box),
                            "chat_turn_id": chat_turn_id,
                            "message_id": message_id,
                        })
                    if extraction_thread is not None:
                        extraction_thread.join()

                    # #526/#1353：尾随票已清后收夜。整轮票已 complete 时 ticketed gate 会
                    # TicketCancelled——收夜短写改走裸 runtime write_gate（腿已终态，无越屏障窗）。
                    close_after = getattr(self.session, "close_night_after_chat_if_needed", None)
                    if close_after is not None:
                        close_after(
                            (payload or {}).get("court_action") or "",
                            write_gate=bare_write_gate,
                        )

                    ev_queue.put({"type": "end"})
                except Exception as error:  # noqa: BLE001
                    # #1353 r12/r13：worker 单一异常出口——payload / 后处理 / 收夜任一失败
                    # 皆 error→end；禁逐点补丁，禁只走 finally 致消费者永阻。
                    # payload 未成（回话失败）才 fail 本轮；后处理失败回话已可见。
                    # ADR 0005 / #1408：清理二次失败 logger.exception 记 traceback 不宽吞；
                    # abandon / 终态写分 try；清理异常不覆盖原始 error、不阻断 error→end。
                    # Scene drain stays outside write_gate (C9/T1/T10).
                    if payload is None:
                        try:
                            if chat_turn_id:
                                self.session.abandon_chat_turn_scene(chat_turn_id)
                        except Exception:
                            logger.exception(
                                "stream worker cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                                chat_turn_id,
                            )
                        try:
                            with write_gate:
                                self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
                        except Exception:
                            logger.exception(
                                "stream worker cleanup: fail_chat_turn/reload failed chat_turn_id=%s",
                                chat_turn_id,
                            )
                    if isinstance(error, LLMUnavailable):
                        ev_queue.put({
                            "type": "error",
                            "detail": _llm_error_detail(error),
                            **identity,
                        })
                    else:
                        ev_queue.put({
                            "type": "error",
                            "message": str(error),
                            **identity,
                        })
                    ev_queue.put({"type": "end"})
            finally:
                self._complete_pending_write(pending_ticket)

        thread = threading.Thread(target=worker, daemon=True)
        try:
            thread.start()
        except Exception:
            # ADR 0005 / #1408：清理二次失败记日志不宽吞；原始异常仍上抛。
            try:
                if chat_turn_id:
                    self.session.abandon_chat_turn_scene(chat_turn_id)
            except Exception:
                logger.exception(
                    "stream start cleanup: abandon_chat_turn_scene failed chat_turn_id=%s",
                    chat_turn_id,
                )
            try:
                with write_gate:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
            except Exception:
                logger.exception(
                    "stream start cleanup: fail_chat_turn/reload failed chat_turn_id=%s",
                    chat_turn_id,
                )
            self._complete_pending_write(pending_ticket)
            raise
        while True:
            item = ev_queue.get()
            yield item
            # #1353 r11：只以 end 收束——失败路径先 error 再 end，禁 error 单终态截断。
            if item.get("type") == "end":
                break

    def suggestions_for(self, character: Character) -> List[Dict[str, Any]]:
        """召对快捷钮：仅保留意图声明前缀（拟旨/下密令）。

        ADR 0042 / #527：旧询问 chips（问在办事项/问阻力/查钱粮/查驻军/密查）已砍；
        问事走直接开口 + 角色见闻。character 保留在签名上以兼容三处 payload 调用点。
        """
        return [
            {"label": "拟旨", "text": "拟旨如下：", "prefix": True},
            {"label": "下密令", "text": "密令如下：", "prefix": True, "intent": "secret_order"},
        ]


def sse_event(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _settlement_player_payload(
    *,
    decree: str = "",
    report: str = "",
    decisions: Optional[List[Dict[str, Any]]] = None,
    pending_action_failures: Optional[List[Dict[str, Any]]] = None,
    steam_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """One player-facing seam for every settlement SSE terminal event."""
    payload: Dict[str, Any] = {
        "decree": decree,
        "report": report,
    }
    if decisions is not None:
        payload["decisions"] = decisions
    if pending_action_failures is not None:
        payload["pending_action_failures"] = pending_action_failures
    if steam_events is not None:
        payload["steam_events"] = steam_events
    return payload


def _next_or_none(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _retryable_audience_close_http(exc: BaseException) -> HTTPException:
    """Map audience-night / close dual-failure errors to retryable HTTP 409.

    Shared converter for player-input boundaries (chat / reply-retry) and sync
    decree endpoints (issue / advance_without_edict). AudienceNightError keeps
    ``detail=str(exc)`` and walks ``__cause__`` so endorsement∥close-scene dual
    failures still surface both nested diagnostics (CI5 dropped ExceptionGroup
    bus; chain is primary from join). Legacy ExceptionGroup still flattened.
    No new exception protocol — existing 409 only.
    """
    from ming_sim.audience_night import AudienceNightError
    if isinstance(exc, AudienceNightError):
        parts: list[str] = []
        cur: BaseException | None = exc
        seen: set[int] = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            text = str(cur).strip()
            if text and text not in parts:
                parts.append(text)
            cur = cur.__cause__  # type: ignore[assignment]
        return HTTPException(
            status_code=409,
            detail="；".join(parts) if parts else str(exc),
        )
    if isinstance(exc, ExceptionGroup):
        parts = [str(sub) for sub in exc.exceptions]
        return HTTPException(
            status_code=409,
            detail="；".join(parts) if parts else str(exc),
        )
    raise TypeError(f"not a retryable audience/close error: {type(exc)!r}")


def _accept_settlement_period(game) -> bool:
    """#1235 / ADR 0149 点即入：颁布/退朝受理即 capture 月初快照（先于 await/close）。

    无真实 db 的测试替身直接跳过。幂等；FRONT_HALF_DONE 不重写。
    返回 True 仅当本请求真新建快照——调用方失败 exit 时作 gate 阻塞信号
    （创建者 blocking 必清；非创建者 non-blocking + in-flight 归零才可清）。"""
    db = getattr(game, "db", None)
    state = getattr(game, "state", None)
    if db is None or state is None or not hasattr(db, "capture_month_open_snapshot"):
        return False
    from ming_sim.month_open_snapshot import accept_settlement_period
    return bool(accept_settlement_period(db, state))


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
    if db is None or state is None or not hasattr(db, "clear_month_open_snapshot"):
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
    game, *, inflight_wait_s: float = 0.0, write_gate: Any = None,
) -> None:
    """Close the open audience night outside any outer runtime write gate.

    close_night holds the real runtime lock only for short prepare/finalize writes;
    the night-level endorsement-only LLM runs with the gate released. Web issue /
    stream / no-edict share this single orchestration (no duplicated close flow).

    #1353：过月屏障票据排在已领票之后——调用方经 queue.barrier 入此函数时，
    前序尾随已空放行/落库；close 内 wait_in_flight 只消费工人终态（K10a）。
    无真实 game.db.conn 的 legacy 替身跳过。
    #1353 fold-in r5：欠账补跑内部静默，不并入过月 SSE。
    #1353 r12：write_gate 可由调用方注入（advance 注入非阻塞短持适配；默认 runtime 闸）。
    """
    db = getattr(game, "db", None)
    if db is None or not hasattr(db, "conn"):
        return
    from ming_sim.audience_night import auto_close_open_night

    session = getattr(game, "session", None)
    auto_close_open_night(
        db,
        game.state,
        content=getattr(game, "content", None),
        registry=getattr(session, "registry", None) if session is not None else None,
        wait_timeout_s=float(inflight_wait_s),
        beat_generator=getattr(session, "_beat_generator", None) if session is not None else None,
        llm_config=getattr(session, "llm_config", None) if session is not None else None,
        write_gate=_game_write_gate(game) if write_gate is None else write_gate,
        scene_registry=getattr(session, "_scene_registry", None) if session is not None else None,
    )


def _game_write_gate(game) -> threading.Lock:
    if hasattr(game, "_runtime_write_gate"):
        return game._runtime_write_gate()
    gate = getattr(game, "_write_gate", None)
    if gate is None:
        gate = threading.Lock()
        setattr(game, "_write_gate", gate)
    return gate


def _refuse_settling_or_busy_write_phase(game) -> None:
    """#393 Gate2 相位拒——与 `_serialized_web_write` 同文案单源。"""
    state = getattr(game, "state", None)
    phase = getattr(state, "turn_phase", None)
    if phase in FRONT_HALF_DONE_PHASES:
        # #1306：分相位文案——awaiting_decision 是等批红（结算未在跑），settling 才是月末结算中。
        if phase == TurnPhase.AWAITING_DECISION.value:
            raise HTTPException(status_code=409, detail="等待批红，请待批红完成后再操作。")
        raise HTTPException(status_code=409, detail="月末结算进行中，请待结算完成后再操作。")


def _try_acquire_serialized_web_write_gate(game):
    """非阻塞抢 write_gate；抢不到立即 409（不挂死）。返回已持锁的 gate。"""
    gate = _game_write_gate(game)
    if not gate.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="月末结算或上一步写入进行中，请稍候再操作。")
    return gate


class _NonBlockingWebWriteGate:
    """#1353 r12：同一把 runtime write_gate 的非阻塞短持适配（不是平行闸）。

    advance 路径注入 auto_close/get_open_night 真实 with 接缝：占用即 409，
    禁阻塞等闸。issue/stream 仍传裸 Lock（阻塞 acquire）。
    """

    __slots__ = ("_lock",)

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        del blocking, timeout  # 契约：短持处永不阻塞等闸
        if not self._lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="月末结算或上一步写入进行中，请稍候再操作。",
            )
        return True

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return bool(self._lock.locked())

    def __enter__(self) -> "_NonBlockingWebWriteGate":
        self.acquire()
        return self

    def __exit__(self, *args: object) -> bool:
        self.release()
        return False


@contextlib.contextmanager
def _hot_replace_when_idle(game):
    """load/reset 热替换：非阻塞抢 gate + entry_lock 后 seal queue；在办 entry/ticket 立即 409。

    #1702：与 settlement entry 共用临界区——锁序先 write_gate 后 entry_lock
    （同 `_exit_settlement_display_on_failure`），持锁全程覆盖 inflight 检与 replace，
    杜绝 gate-free 窗（HITL 尾/join）下 TOCTOU 热替换。
    """
    _refuse_settling_or_busy_write_phase(game)
    gate = _try_acquire_serialized_web_write_gate(game)
    entry_lock = _settlement_entry_lock(game)
    entry_lock.acquire()
    q = get_session_write_queue(game)
    q.seal()
    try:
        # 直接读计数；禁止调 `_settlement_entry_inflight()`（会二次抢同一 entry_lock）。
        if int(getattr(game, "_settlement_entry_inflight", 0) or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="月末结算或上一步写入进行中，请稍候再操作。",
            )
        if q.inflight_count() > 0:
            raise HTTPException(
                status_code=409,
                detail="月末结算或上一步写入进行中，请稍候再操作。",
            )
        yield
    finally:
        q.unseal()
        entry_lock.release()
        gate.release()


def _spawn_startup_catch_up_nonfatal(game) -> None:
    """Start post-replacement catch-up without turning a successful replacement into failure."""
    try:
        game._spawn_startup_extraction_catch_up()
    except Exception:
        logger.exception("startup extraction catch-up scheduling failed")


def _run_hot_replace(game, replace: Callable[[], None], *, failure_label: str) -> None:
    """独占热替换核心；释放旧 gate 后才让新 session 的补跑领票。"""
    try:
        with _hot_replace_when_idle(game):
            replace()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("%s", failure_label)
        raise HTTPException(status_code=500, detail=f"{failure_label}：{exc}") from exc
    _spawn_startup_catch_up_nonfatal(game)


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
        # 欠账抽取并入同一次过月动作（内部静默），不再 409 打回玩家补写。
        # 在途事实唯一来源=队列票据（旁路 wait 已删）。
        get_session_write_queue(game).barrier(
            lambda: _auto_close_open_night_gate_free(
                game, inflight_wait_s=0.0, write_gate=close_gate,
            ),
        )

        def _clear_orphan_success() -> None:
            # #1343/#1378/#1379/#1388：成功回常态后兜底清残留快照。
            # 持 write_cm 同门（与失败支 _game_write_gate 同形）——禁无门直写共享连接。
            db = getattr(game, "db", None)
            state = getattr(game, "state", None)
            if db is not None and state is not None and hasattr(db, "clear_month_open_snapshot"):
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
                _exit_settlement_display_on_failure(game, blocking=created_display)
        finally:
            if entered:
                _end_settlement_entry(game)


def _active_db_path_file() -> str:
    """主库路径的真源文件（#396 new_game 切换主库路径用）。"""
    return user_data_path("active_db.txt")


def _read_active_db_path() -> str:
    active_file = _active_db_path_file()
    if not os.path.exists(active_file):
        return ""
    try:
        with open(active_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


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
            except Exception:
                pass


def _write_active_db_path(db_path: str) -> None:
    _atomic_write_text(_active_db_path_file(), db_path)


def _snapshot_main_db_path_config() -> tuple[bool, str, bool, str]:
    active_file = _active_db_path_file()
    active_exists = os.path.exists(active_file)
    active_value = ""
    if active_exists:
        try:
            with open(active_file, "r", encoding="utf-8") as f:
                active_value = f.read()
        except Exception:
            active_value = ""
    return (
        "MING_SIM_DB" in os.environ,
        os.environ.get("MING_SIM_DB", ""),
        active_exists,
        active_value,
    )


def _restore_main_db_path_config(snapshot: tuple[bool, str, bool, str]) -> None:
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
        except Exception:
            fallback_path = env_value if env_exists and env_value else user_data_path("ming_sim.db")
            try:
                _atomic_write_text(active_file, fallback_path)
            except Exception:
                pass


def _set_main_db_path(db_path: str) -> None:
    os.environ["MING_SIM_DB"] = db_path
    _write_active_db_path(db_path)


def _get_main_db_path() -> str:
    """解析当前主库路径：active_db.txt > env > 默认 ming_sim.db。

    #396：new_game 不删旧库文件（旧后台 worker 仍写，删了会触发 SQLite readonly database），
    而是把主库路径切到新文件，旧连接排空关闭后旧库归档为存档。active_db.txt 持久化该切换，
    使重启后仍能加载新库。"""
    active_path = _read_active_db_path()
    if active_path:
        return active_path
    db_path = os.environ.get("MING_SIM_DB", "")
    if db_path:
        return db_path
    return user_data_path("ming_sim.db")


def _drain_and_close_session(game, archive_db: bool = False) -> None:
    """等在途后台写入（召对 worker / 结算 worker）排空后再关连接。

    #396：菜单生命周期端点（exit_to_menu / new_game / shutdown）不再在 write_gate 被
    持时直接 session.close()——否则后台 worker 崩在 closed database（#382 连接级并发）。
    exit_to_menu 立刻清 web_game 并返回，连接在后台 daemon 线程延后关（detach）；
    new_game 先把旧库 park 旁路、再立刻建新局（零等待）；排空后关连接并把旁路库归档为存档；
    shutdown await 排空后再杀进程。

    #1353：seal 拒新领票 + barrier 等既有票据清 + 持 write_gate 关连接。
    """
    q = get_session_write_queue(game)
    q.seal()

    def _close_under_gate() -> None:
        gate = _game_write_gate(game)
        gate.acquire()
        try:
            session = getattr(game, "session", None)
            if session is not None:
                session.close()
        finally:
            gate.release()

    close_failed = False
    try:
        q.barrier(_close_under_gate)
    except Exception:
        close_failed = True
    if close_failed:
        return
    if archive_db:
        old_db_path = getattr(game, "db_path", "")
        if old_db_path and os.path.exists(old_db_path):
            saves_dir = user_data_path("saves")
            os.makedirs(saves_dir, exist_ok=True)
            target = os.path.join(saves_dir, f"drained_{time.time_ns()}.db")
            moved = False
            try:
                shutil.move(old_db_path, target)
                moved = True
            except Exception:
                pass
            if moved:
                wal_path = old_db_path + "-wal"
                if os.path.exists(wal_path):
                    try:
                        shutil.move(wal_path, target + "-wal")
                    except Exception:
                        try:
                            shutil.move(target, old_db_path)
                        except Exception:
                            pass
                        return
                shm_path = old_db_path + "-shm"
                if os.path.exists(shm_path):
                    try:
                        shutil.move(shm_path, target + "-shm")
                    except Exception:
                        pass


web_game: Optional[WebGame] = None  # 懒加载：菜单页点「新游戏/继续/加载存档」才实例化
# #1195：菜单生命周期世代。continue worker 发布 web_game 前对号；失配则丢弃白建局。
_menu_generation: int = 0


app = FastAPI(title="Ming Salvage MVP Web")


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
    db_path = _get_main_db_path()
    if not os.path.isabs(db_path):
        db_path = str(user_data_dir() / db_path)
    if not os.path.isfile(db_path):
        return ""
    try:
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM kv_store WHERE key='campaign_id'").fetchone()
            return str(row[0]).strip() if row and row[0] else ""
        finally:
            conn.close()
    except Exception:
        return ""


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
        except OSError:
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
    db_path = _get_main_db_path()
    if not os.path.isabs(db_path):
        db_path = str(user_data_dir() / db_path)
    return os.path.isfile(db_path)


@app.get("/api/menu/status")
async def api_menu_status() -> Dict[str, Any]:
    """菜单页状态：API key 是否配好、上次主 DB 是否存在、存档列表。"""
    runtime = load_runtime_llm()
    from ming_sim.cli_backend import (
        CLI_REASONING_STRENGTH_RUNNERS,
        cli_backend_from_env,
        cli_model_choices,
        cli_runner_choices,
        is_supported_cli_runner,
    )
    env_runner = cli_backend_from_env()
    channel = str(runtime.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        channel = "cli" if env_runner else "api"
    cli_slot = runtime.get("cli") if isinstance(runtime.get("cli"), dict) else {}
    api_slot = runtime.get("api") if isinstance(runtime.get("api"), dict) else {}
    cli_runner = str(cli_slot.get("runner") or env_runner or ("agy" if channel == "cli" else "")).strip().lower()
    # cli_model_saved = 原样存盘值（空=用户选「默认」档）；cli_model = 兜底成默认名的 resolved 值。
    # 表单（CliModelField 下拉）须读 raw，否则空保存被 resolved 成默认名 → 下拉误判「其他(手填)」
    # 并把字面量钉死（CMR R1 Claude+Gemini concur）。resolved 仅供「当前后端」展示行。
    cli_model_saved = str(cli_slot.get("model") or "").strip()
    cli_model = cli_model_saved or str(cli_model_from_env(cli_runner, "")).strip()
    cli_timeout = _runtime_float(cli_slot.get("timeout_seconds"), CLI_DEFAULT_TIMEOUT_SECONDS)
    has_api_key = _has_real_api_key(runtime.get("api_key")) or _has_real_api_key(os.environ.get("OPENAI_API_KEY"))
    base_url = runtime.get("base_url") or os.environ.get("OPENAI_BASE_URL", "")
    model = runtime.get("model") or os.environ.get("OPENAI_MODEL", "")
    reasoning_strength = normalize_reasoning_strength(
        (cli_slot.get("reasoning_strength") if channel == "cli" else runtime.get("reasoning_strength"))
        or runtime.get("reasoning_strength", "")
    )
    cli_reasoning_strength = normalize_reasoning_strength(cli_slot.get("reasoning_strength"))
    api_reasoning_strength = normalize_reasoning_strength(api_slot.get("reasoning_strength"))
    reasoning_supported = (
        cli_supports_reasoning_strength(cli_runner)
        if channel == "cli"
        else _api_reasoning_supported_for_effective_model(
            str(base_url),
            str(model),
            str(runtime.get("advanced_base_url") or os.environ.get("OPENAI_ADVANCED_BASE_URL", "")),
            str(runtime.get("advanced_model") or os.environ.get("OPENAI_ADVANCED_MODEL", "")),
        )
    )
    # readiness 按 active channel 判：API 通道看真实 key，CLI 通道看 runner 是否受支持。
    # 不能因 inactive API 槽（ADR 0001 保留）里有 key 就把不可用的 CLI runner 误报成 ready。
    llm_ready = has_api_key if channel == "api" else is_supported_cli_runner(cli_runner)
    return {
        "has_api_key": has_api_key,
        "llm_ready": llm_ready,
        "has_running_game": web_game is not None,
        "has_main_db": _has_main_db(),
        "saves": _scan_saves(),
        "campaigns": _scan_campaigns(),
        "current_campaign": _main_db_campaign_id(),
        "llm": {
            "channel": channel,
            "base_url": base_url,
            "model": model,
            "has_api_key": has_api_key,
            "cli_runner": cli_runner,
            "cli_model": cli_model,
            "cli_model_saved": cli_model_saved,
            "cli_model_choices": cli_model_choices(),
            # #1274 W1：CLI Runner 下拉单源（= _CLI_BACKENDS 有序），menuPage/gameMenu 共吃。
            "cli_runners": cli_runner_choices(),
            "cli_timeout_seconds": cli_timeout,
            "reasoning_strength": reasoning_strength,
            "api_reasoning_strength": api_reasoning_strength,
            "cli_reasoning_strength": cli_reasoning_strength,
            "reasoning_supported": reasoning_supported,
            "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
            # #1271：能力名单自 cli_backend 单源导出，供前端 fallback 消费（禁前端硬编码）。
            "cli_reasoning_runners": sorted(CLI_REASONING_STRENGTH_RUNNERS),
            "timeout_seconds": float(runtime.get("timeout_seconds") or os.environ.get("OPENAI_TIMEOUT_SECONDS") or API_DEFAULT_TIMEOUT_SECONDS),
            "thinking_level": runtime.get("thinking_level") or os.environ.get("OPENAI_THINKING_LEVEL", ""),
            "advanced_model": runtime.get("advanced_model") or os.environ.get("OPENAI_ADVANCED_MODEL", ""),
            "advanced_base_url": runtime.get("advanced_base_url") or os.environ.get("OPENAI_ADVANCED_BASE_URL", ""),
            "has_advanced_api_key": _has_real_api_key(runtime.get("advanced_api_key")) or _has_real_api_key(os.environ.get("OPENAI_ADVANCED_API_KEY")),
            "advanced_thinking_level": "",
        },
    }


@app.post("/api/menu/new_game")
async def api_menu_new_game() -> Dict[str, Any]:
    """开始新游戏：清主 DB → 新建 WebGame。

    #396：与 exit_to_menu 同构——界面立刻退（web_game=None + 构建新局），
    旧 session 的后台召对队列在 daemon 线程里续跑写入、排空 write_gate 后再关连接（detach）。
    先把旧库 park 旁路再 fresh=True 建新库——不在旧 worker 仍写旧连接时 os.remove 底层文件；
    排空后关旧连接并把旁路库归档为存档，玩家可再次进入看到迟到的后台回奏；
    #382 通用并发模型（Windows file-lock 等）不在本轮 scope。"""
    global web_game, _menu_generation
    _menu_generation += 1
    old_game = web_game
    # #396 Step5 R4: 无论 web_game 是否为 None（退菜单后 / 服务端首次 new_game），
    # fresh=True 前都必须切换主库路径到新文件——否则 WebGame 会解析到旧配置库（env /
    # active_db.txt）并在 fresh=True 时删/覆盖旧库，而旧 detach worker 可能仍写旧库。
    # #396: 不能在旧后台 worker 仍写旧库时删/重命名旧库文件（SQLite 会报 readonly database）。
    # 改为把主库路径切换到新文件，旧 worker 安全续写旧库；排空关连接后旧库归档为存档。
    snapshot = _snapshot_main_db_path_config()
    new_db_path = user_data_path(f"ming_sim_{time.time_ns()}.db")
    try:
        # 同步覆写 env + active_db.txt → 新局落新路径，重启也继续新路径。
        _set_main_db_path(new_db_path)
        web_game = None
        new_game = WebGame(fresh=True)
    except LLMUnavailable as exc:
        _restore_main_db_path_config(snapshot)
        web_game = old_game
        raise HTTPException(status_code=412, detail=_llm_error_detail(exc))
    except Exception:
        _restore_main_db_path_config(snapshot)
        web_game = old_game
        raise
    web_game = new_game
    if old_game is not None:
        # detach：新局已确认可用后，才退休旧连接 + 归档旧库（#396）。
        threading.Thread(
            target=_drain_and_close_session,
            args=(old_game, True),
            daemon=True,
        ).start()
    return steam_events.with_events(
        {"state": web_game.state_payload()},
        [steam_events.add_stat(steam_events.STAT_RUNS_STARTED)],
    )


@app.post("/api/menu/continue")
async def api_menu_continue() -> StreamingResponse:
    """继续：用上次主 DB 启动 WebGame。

    #1195：与颁诏 settle 同构 SSE——stage 逐段推文案，done 带 state，
    error 带 message。首条 stage 在重活前即发（目标 ≤5s 首见）。
    """
    global _menu_generation
    if not _has_main_db():
        raise HTTPException(status_code=404, detail="无上次进度可继续，请先新游戏或加载存档。")

    _menu_generation += 1
    token = _menu_generation
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def on_stage(label: str) -> None:
        ev_queue.put(("stage", label))

    def worker() -> None:
        global web_game
        try:
            # 首条阶段立即入队：生成器可在 WebGame 构造重活前就 yield（#1195 ≤5s 首见）
            # #1228：构造不再做连通 smoke，文案须诚实反映载入准备（非「检查模型后端」）。
            on_stage("准备载入上次进度...")
            game = WebGame(fresh=False, on_stage=on_stage)
            # #1195：发布前对世代号——exit/new_game/load_save/新 continue 已 bump 则丢弃白建局
            if token != _menu_generation:
                _drain_and_close_session(game)
                ev_queue.put(("__error__", {"message": "继续已取消（菜单状态已变更）。"}))
                return
            web_game = game
            ev_queue.put(("__done__", {"state": game.state_payload()}))
        except LLMUnavailable as exc:
            ev_queue.put(("__error__", _llm_error_detail(exc)))
        except Exception as exc:  # noqa: BLE001 — SSE 终态收束，不让线程死掉
            ev_queue.put(("__error__", {"message": str(exc)}))

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
    """从存档启动：先启动空 WebGame（fresh）→ 调 load_save 热替换主 DB。"""
    global web_game, _menu_generation
    _menu_generation += 1
    try:
        web_game = WebGame(fresh=False)  # 先有 session 才能 load_save
    except LLMUnavailable as exc:
        raise HTTPException(status_code=412, detail=_llm_error_detail(exc))
    web_game.load_save(name)
    _spawn_startup_catch_up_nonfatal(web_game)
    return {"state": web_game.state_payload()}


@app.delete("/api/menu/saves/{name}")
async def api_menu_delete_save(name: str) -> Dict[str, Any]:
    """菜单页删存档：不依赖 WebGame 实例，直接删文件系统里的 <name>.db。
    与 WebGame.delete_save 同名校验，返回刷新后的 campaigns。"""
    cleaned = "".join(c for c in name.strip() if c.isalnum() or c in "._-")
    if not cleaned or cleaned.startswith("."):
        raise HTTPException(status_code=400, detail="存档名非法。仅允许字母/数字/._- ")
    target = os.path.join(user_data_path("saves"), f"{cleaned}.db")
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="存档不存在。")
    os.remove(target)
    return {"saves": _scan_saves(), "campaigns": _scan_campaigns()}


@app.post("/api/menu/exit_to_menu")
async def api_menu_exit() -> Dict[str, Any]:
    """退回菜单：关 session 但不删 DB。

    #396：界面立刻退（web_game=None + 响应返回），后台召对 worker 继续跑完、写进档；
    session.close() 推迟到 write_gate 排空后再执行（detach），不在 worker 写时关。"""
    global web_game, _menu_generation
    _menu_generation += 1
    if web_game is not None:
        old_game = web_game
        web_game = None  # 界面立刻退
        # detach：等 write_gate 排空后再关连接（#396）
        threading.Thread(target=_drain_and_close_session, args=(old_game,), daemon=True).start()
    return {"ok": True}


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
        # 关进程前等队列排空（#396 owner decision）
        await asyncio.get_running_loop().run_in_executor(None, _drain_and_close_session, old_game)
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
    cli_timeout_seconds: float = 0


async def _menu_save_cli_llm(request: LlmSetupRequest) -> Dict[str, Any]:
    """保存 CLI 通道：选 runner/model，不要求真实 api_key，保留 API 槽。"""
    cli_runner = (request.cli_runner or "").strip().lower()
    cli_model = (request.cli_model or "").strip()
    reasoning_strength = normalize_reasoning_strength(request.reasoning_strength)
    cli_timeout = request.cli_timeout_seconds if request.cli_timeout_seconds and request.cli_timeout_seconds > 0 else CLI_DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = request.timeout_seconds if request.timeout_seconds > 0 else API_DEFAULT_TIMEOUT_SECONDS
    if not cli_runner:
        raise HTTPException(status_code=400, detail="cli_runner 不能为空。")
    config = LLMConfig(
        api_key="",  # CLI 通道不要 API key；占位符在 create_chat_model 构造 CliChat 时注入
        base_url="",
        model=cli_model,
        timeout_seconds=timeout_seconds,
        reasoning_strength=reasoning_strength,
        channel="cli",
        cli_runner=cli_runner,
        cli_model=cli_model,
        cli_timeout_seconds=cli_timeout,
    )
    try:
        # CLI/API smoke 是阻塞子进程/网络调用(CLI 最长 cli_timeout_seconds),不能跑在
        # asyncio event loop 上卡死并发请求 → offload 到线程池(P1/P2)。verify 只读不改盘面。
        await asyncio.get_running_loop().run_in_executor(
            None, _verify_llm_configs_or_raise, config
        )
    except HTTPException:
        raise
    except LLMUnavailable as exc:
        raise HTTPException(status_code=400, detail=_llm_error_detail(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "llm_validation_failed", "message": str(exc)}) from None
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
    if not api_key:
        existing = load_runtime_llm()
        for candidate in (existing.get("api_key"), os.environ.get("OPENAI_API_KEY", "")):
            if _has_real_api_key(candidate):
                api_key = str(candidate).strip()
                break
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key 未配置，请填写。")
    # advanced_api_key 留空：复用已存的（避免覆盖成空）。
    if advanced_model and not advanced_api_key:
        existing = load_runtime_llm()
        advanced_api_key = real_api_key_or_empty(existing.get("advanced_api_key")) or real_api_key_or_empty(os.environ.get("OPENAI_ADVANCED_API_KEY"))
    normalized_base_url = normalize_openai_base_url(base_url)
    config = LLMConfig(
        api_key=api_key,
        base_url=normalized_base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        thinking_level=thinking_level,
        advanced_model=advanced_model,
        advanced_base_url=advanced_base_url,
        advanced_api_key=advanced_api_key,
        advanced_thinking_level=advanced_thinking_level,
        reasoning_strength=reasoning_strength,
        channel="api",
    )
    try:
        # CLI/API smoke 是阻塞子进程/网络调用(CLI 最长 cli_timeout_seconds),不能跑在
        # asyncio event loop 上卡死并发请求 → offload 到线程池(P1/P2)。verify 只读不改盘面。
        await asyncio.get_running_loop().run_in_executor(
            None, _verify_llm_configs_or_raise, config
        )
    except HTTPException:
        raise
    except LLMUnavailable as exc:
        raise HTTPException(status_code=400, detail=_llm_error_detail(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "llm_validation_failed", "message": str(exc)}) from None
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
    return get_game().state_payload()


@app.get("/api/secret_orders")
async def api_secret_orders(status: str = "") -> Dict[str, Any]:
    """列出密令。status 为空返回全部，否则按 active/done/failed 过滤。

    failed_secret_order_count 真源在 state_payload（~1405）；前端 useDurableProjection
    只读 state，本端点不重复暴露。
    """
    game = get_game()
    orders = game.db.list_secret_orders(status=status or None)
    return {"orders": orders}


def _player_visible_pending_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        action for action in actions
        if not (action.get("kind") == "secret_order" and action.get("action") == "新建")
    ]


def _failed_secret_order_ids_for_turn(game: WebGame, turn: int) -> set[int]:
    db = getattr(game, "db", None)
    if db is None or not hasattr(db, "list_pending_actions"):
        return set()
    return {
        int(action.get("id") or 0)
        for action in db.list_pending_actions(int(turn), status="failed")
        if action.get("kind") == "secret_order"
    }


def _new_secret_order_failure_payloads_for_turn(
    game: WebGame, turn: int, before_ids: set[int],
) -> List[Dict[str, Any]]:
    db = getattr(game, "db", None)
    if db is None or not hasattr(db, "list_pending_actions"):
        return []
    return [
        _pending_action_failure_payload(action, game.state)
        for action in db.list_pending_actions(int(turn), status="failed")
        if action.get("kind") == "secret_order" and int(action.get("id") or 0) not in before_ids
    ]


@app.get("/api/pending_actions")
async def api_pending_actions() -> Dict[str, Any]:
    """列出本回合待确认动作(动作闸门 ADR 0006):皇帝复核区,颁诏批量落库前可见可撤。"""
    game = get_game()
    return {"actions": _player_visible_pending_actions(
        game.db.list_pending_actions(int(game.state.turn)))}


@app.get("/api/pending_actions/failures")
async def api_pending_action_failures() -> Dict[str, Any]:
    game = get_game()
    return {"pending_action_failures": game.pending_action_failures()}


@app.post("/api/pending_actions/{action_id}/withdraw")
async def api_withdraw_pending_action(action_id: int) -> Dict[str, Any]:
    """皇帝撤回一条尚未颁诏落库的暂存动作。不存在→404;存在但已落库/非本回合→409。
    先原子条件 DELETE(以删成功为真源,免 check-then-act 竞态,pr-loop sourcery),
    失败再查行分流 404/409。"""
    game = get_game()
    with _serialized_web_write(game):
        if game.db.withdraw_pending_action(int(action_id), int(game.state.turn)):
            return {"withdrawn": action_id, "actions": _player_visible_pending_actions(
                game.db.list_pending_actions(int(game.state.turn)))}
    # 删不动:查清是不存在还是已落库/非本回合
    row = game.db.conn.execute(
        "SELECT turn, status FROM pending_actions WHERE id=?", (int(action_id),)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="该待确认动作不存在。")
    raise HTTPException(status_code=409, detail="该动作已落库或非本回合，无法撤回。")


@app.post("/api/pending_actions/{action_id}/retry")
async def api_retry_pending_action(action_id: int) -> Dict[str, Any]:
    """重试本回合失败的密令下达，用已存 pending_actions payload 重新落库。"""
    game = get_game()
    minister_name = ""
    with _serialized_web_write(game):
        try:
            row = game.db.conn.execute(
                "SELECT minister_name FROM pending_actions WHERE id=?",
                (int(action_id),),
            ).fetchone()
            if row is not None:
                minister_name = str(row["minister_name"] or "")
            with atomic(game.db):
                result = game.db.retry_failed_pending_action(
                    game.state, int(action_id),
                    content=getattr(game.session, "content", None),
                    registry=getattr(game.session, "registry", None),
                )
                if result.get("committed"):
                    game.db.retire_chat_turn_for_pending_action_retry(int(action_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "retry": result,
        "actions": _player_visible_pending_actions(
            game.db.list_pending_actions(int(game.state.turn))),
        "secret_orders": game.db.list_secret_orders(),
        "can_undo_last_chat": game.can_undo_last_chat(minister_name) if minister_name else False,
        "pending_action_failures": game.pending_action_failures_for(minister_name) if minister_name else [],
    }


@app.get("/api/history/turns")
def api_history_turns() -> Dict[str, Any]:
    """场级归档列表；同步 handler 由 FastAPI 在线程池中执行 SQLite 投影。"""
    turns = get_game().db.list_archived_turns()
    return {"turns": [
        {k: v for k, v in item.items() if k != "has_extraction"}
        for item in turns
    ]}


@app.get("/api/history/turn/{turn}")
async def api_history_turn(turn: int) -> Dict[str, Any]:
    """某回合玩家历史：只交付邸报、诏书、已颁草案与独立递话原文。"""
    db = get_game().db
    # #671：一次读 turn_reports；year/period 在 extraction/directives 皆无时回落存档行
    archive = db.get_turn_report_archive(turn)
    report = str((archive or {}).get("report") or "")
    attendant_message = str((archive or {}).get("attendant_message") or "")
    extraction = db.get_turn_extraction(turn)
    directives = db.list_directives_by_turn(turn)
    # exists：report/递话纯空白与空串同属缺席（临时 strip）；payload 仍回原文
    if (
        not str(report or "").strip()
        and not str(attendant_message or "").strip()
        and extraction is None
        and not directives
    ):
        return {"turn": turn, "exists": False}
    decree_text = ""
    if extraction is not None:
        decree_text = str(extraction.get("decree_text") or "")
    if extraction is not None:
        year = extraction["year"]
        period = extraction["period"]
    elif directives:
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


@app.get("/api/map")
async def api_map() -> Dict[str, Any]:
    return {"nodes": get_game().map_nodes()}


@app.get("/api/buildings")
async def api_buildings(region_id: str = "") -> Dict[str, Any]:
    return {"buildings": get_game().db.building_payload(region_id)}


@app.post("/api/favorites/{minister_name}")
async def api_add_favorite(minister_name: str) -> Dict[str, Any]:
    game = get_game()
    if minister_name not in game.content.characters:
        raise HTTPException(status_code=404, detail=f"未找到：{minister_name}")
    with _serialized_web_write(game):
        game.favorites.add(minister_name)
        game.db.kv_set("favorites", json.dumps(sorted(game.favorites)))
    return {"favorites": sorted(game.favorites)}


@app.delete("/api/favorites/{minister_name}")
async def api_remove_favorite(minister_name: str) -> Dict[str, Any]:
    game = get_game()
    with _serialized_web_write(game):
        game.favorites.discard(minister_name)
        game.db.kv_set("favorites", json.dumps(sorted(game.favorites)))
    return {"favorites": sorted(game.favorites)}


_STATUS_LABEL_WEB = {
    # #1683：active 是广义在事/官印态（ADR 0009），不是物理「在朝」
    "active": "在事", "offstage": "尚未登场", "dead": "已殁", "dismissed": "已罢黜",
    "imprisoned": "下狱", "exiled": "流放", "retired": "致仕",
}


def _require_active_minister(minister_name: str) -> None:
    if minister_name in get_game().session.temporary_characters:
        return
    if minister_name not in get_game().content.characters:
        raise HTTPException(status_code=404, detail=f"未找到人物：{minister_name}")
    character = get_game().content.characters[minister_name]
    # #1402：召见闸文案单一真源 = session.can_summon（含宗藩/非大明/非 active）。
    # 旧副本多一个「已」字，offstage 产「已尚未登场」；后宫仍由 can_summon 放行
    # （不拒 office_type=后宫，嫔妃 chat 复用本端点）。
    ok, reason = get_game().session.can_summon(character)
    if not ok:
        raise HTTPException(status_code=409, detail=(reason or "").strip())


@app.get("/api/audience/scroll")
def api_audience_scroll(night_id: int = 0) -> Dict[str, Any]:
    """Shared live/read-only projection of one persisted audience scroll."""
    from ming_sim.audience_night import get_night, get_open_night, read_night_scroll

    game = get_game()
    night = get_night(game.db, night_id) if night_id else get_open_night(game.db)
    if night is None:
        return {"night_id": 0, "status": "", "messages": []}
    return {
        "night_id": int(night["id"]),
        "status": night["status"],
        "messages": read_night_scroll(game.db, int(night["id"])),
    }


@app.get("/api/ministers/{minister_name}/chat")
async def api_chat_history(minister_name: str) -> Dict[str, Any]:
    _require_active_minister(minister_name)
    game = get_game()
    character = game.session._character(minister_name)
    mind = game.mindreading_for_minister(minister_name)
    from ming_sim.audience_night import get_open_night
    open_night = get_open_night(game.db) if hasattr(game.db, "conn") else None
    return {
        "minister": game.public_character(character),
        "campaign_id": str(game.db.kv_get("campaign_id") or ""),
        "night_id": int(open_night["id"]) if open_night else 0,
        # #499：turn-identified 单一投影，读心递话（role=attendant）已按轮归位于其中
        "history": game.chat_projection(minister_name),
        "suggestions": game.suggestions_for(character),
        "can_undo_last_chat": game.can_undo_last_chat(minister_name),
        "pending_action_failures": game.pending_action_failures_for(minister_name),
        # 最新活跃轮 + 所有待读心轮 → 前端对每一待读心轮各自固定轮有界轮询（随新一轮发出仍存活）
        "chat_turn_id": mind["chat_turn_id"],
        "mindreading_pending": mind["mindreading_pending"],
        "pending_turn_ids": mind["pending_turn_ids"],
        # #505：重开后崩溃遗留的中断轮 → 最后一句上给「重新生成回话」重试（系统层恢复动作）。
        "reply_retry": (game.interrupted_reply_retries(minister_name) or [None])[-1],
    }


@app.post("/api/ministers/{minister_name}/reply/retry")
async def api_retry_interrupted_reply(minister_name: str) -> Dict[str, Any]:
    """#505：重开后为中断轮重新生成回话（复用已持久问话，对话记录无重复句）。"""
    _require_active_minister(minister_name)
    from ming_sim.audience_night import AudienceNightError
    try:
        return await run_in_threadpool(get_game().retry_interrupted_reply, minister_name)
    except AudienceNightError as e:
        # CLOSING / night admission → 409 (retryable); reuse shared converter, no status fork.
        raise _retryable_audience_close_http(e) from None


@app.get("/api/ministers/{minister_name}/chat/mindreading")
async def api_chat_mindreading(minister_name: str, chat_turn_id: int = 0) -> Dict[str, Any]:
    """#499 读心轮询入口：回话 done 后后台生成，就绪即可拉取。

    `chat_turn_id` 固定 expected 轮：取消/早重开的前端锁定首拉那一轮轮询，
    新一轮成为 latest 也不截断旧轮读心。
    """
    _require_active_minister(minister_name)
    return get_game().mindreading_for_minister(minister_name, chat_turn_id)


@app.get("/api/audience/extraction/pending")
async def api_pending_story_extractions() -> Dict[str, Any]:
    """#501/#1353：本开夜待补叙事抽取只读诊断（无玩家手动补写入口）。"""
    return get_game().pending_story_extractions()


@app.post("/api/ministers/{minister_name}/secret_order")
async def api_create_secret_order(minister_name: str, request: SecretOrderRequest) -> Dict[str, Any]:
    """兼容旧按钮端点：转成召对前缀消息，走同一大臣回话/确认闸门。"""
    game = get_game()
    _require_active_minister(minister_name)
    title = request.title.strip()
    content = request.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title 和 content 不能为空")
    lines = [f"密令如下：{title}", content]
    tags_raw = request.tags if isinstance(request.tags, list) else []
    tags = [str(tag).strip() for tag in tags_raw if str(tag).strip()]
    if tags:
        lines.append("标签：" + "、".join(tags))
    provided_fields = (
        getattr(request, "model_fields_set", None)
        or getattr(request, "__fields_set__", set())
    )
    if "deadline_months" in provided_fields and request.deadline_months is not None:
        lines.append(f"期限：{int(request.deadline_months)}月")

    def _create_with_gate() -> Dict[str, Any]:
        with _serialized_web_write(game):
            return game._chat_with_write_gate_held(minister_name, "\n".join(lines))

    return await run_in_threadpool(_create_with_gate)


@app.post("/api/ministers/{minister_name}/chat")
async def api_chat(minister_name: str, request: ChatRequest) -> Dict[str, Any]:
    _require_active_minister(minister_name)
    from ming_sim.audience_night import AudienceNightError
    try:
        # #1291+#1322: 全同步 chat（→ session → cli subprocess.run）须卸出事件循环，
        # 与 retry_interrupted_reply / secret_order 同构 run_in_threadpool；
        # 流式路走 run_in_executor，directives 走 to_thread——禁在 async handler 内直调。
        return await run_in_threadpool(get_game().chat, minister_name, request.message, request.intent)
    except AudienceNightError as e:
        # CLOSING / night admission → 409 (retryable); same family as stream path.
        raise _retryable_audience_close_http(e) from None
    except LLMUnavailable as e:
        # #1452：非流式召对 LLM 死 → 结构化错误，禁裸 500。
        raise HTTPException(status_code=400, detail=_llm_error_detail(e)) from None


@app.post("/api/ministers/{minister_name}/chat/undo")
async def api_undo_chat(minister_name: str) -> Dict[str, Any]:
    # undo_last_chat 自带产品相位门（只许 SUMMONING/REVIEWING 撤回），但那是 phase-only、守不住
    # pre_settle 原子窗口，且 undo_chat_turn 直写共享连接 → 与其它写端点一致走 _write_gate
    # （cmr Gate2 r3 Finding1）。门内若相位门拒，HTTPException 经 finally 释放锁后正常上抛。
    game = get_game()
    with _serialized_web_write(game):
        return game.undo_last_chat(minister_name)


@app.post("/api/ministers/{minister_name}/chat/stream")
async def api_chat_stream(minister_name: str, request: ChatRequest) -> StreamingResponse:
    _require_active_minister(minister_name)
    async def generate() -> AsyncIterator[str]:
        iterator = iter(get_game().chat_stream(minister_name, request.message, request.intent))
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, _next_or_none, iterator)
            if item is None:
                break
            item_type = str(item.get("type", "message"))
            if item_type == "accepted":
                yield sse_event("accepted", {
                    "campaign_id": item.get("campaign_id", ""),
                    "night_id": item.get("night_id", 0),
                    "chat_turn_id": item.get("chat_turn_id", 0),
                })
            elif item_type == "delta":
                yield sse_event("delta", {"content": item.get("content", "")})
            elif item_type == "done":
                # 回话先可见；流继续至 end，以便读心就绪后浮现（#499 / ADR 0046 递话）
                yield sse_event("done", item.get("payload", {}))
            elif item_type == "mindreading":
                yield sse_event("mindreading", {
                    "mindreading": item.get("payload"),
                    "chat_turn_id": item.get("chat_turn_id") or 0,
                })
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
                detail = item.get("detail") or {"message": item.get("message", "流式回复失败。")}
                payload = dict(detail) if isinstance(detail, dict) else {"message": str(detail)}
                payload.update({
                    "campaign_id": item.get("campaign_id", ""),
                    "night_id": item.get("night_id", 0),
                    "chat_turn_id": item.get("chat_turn_id", 0),
                })
                yield sse_event("error", payload)
                break

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/directives")
async def api_create_directive(request: DirectiveRequest) -> Dict[str, Any]:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="指令内容不能为空。")
    game = get_game()
    try:
        with _serialized_web_write(game):
            capture_turn = int(game.state.turn)
        from ming_sim.cli_backend import capture_manual_directive_payload
        dossier_payload = await asyncio.to_thread(
            capture_manual_directive_payload,
            request.text.strip(),
            game.session.llm_config,
            **({"db": game.db, "content": game.content}
               if getattr(game, "content", None) is not None else {}),
        )
        # 会话层 _refuse_if_settling 仅查相位，守不住 pre_settle 原子块在 settling 落定前的窗口；
        # 与直写端点同走 _serialized_web_write 抢 _write_gate（cmr Gate2 F-A 残面：会话写也要串行）。
        with _serialized_web_write(game):
            if int(game.state.turn) != capture_turn:
                raise ValueError("旨意抽取期间回合已推进，请在当前回合重新提交。")
            dv = game.session.add_directive(
                request.text.strip(), notes=request.notes,
                dossier_payload=dossier_payload,
            )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None  # 恢复窗冻结指引
    except LLMUnavailable as e:
        # #1274 V-1 r6 / #1452：回禀产文失败 → 结构化 400，禁裸 500 / 固定戏内模板。
        raise HTTPException(status_code=400, detail=_llm_error_detail(e)) from None
    return {
        "directive": {"id": dv.id, "text": dv.text, "status": dv.status},
        "directives": [game.directive_payload(item) for item in game.directive_rows()],
    }


@app.patch("/api/directives/{directive_id}")
async def api_update_directive(directive_id: int, request: DirectivePatch) -> Dict[str, Any]:
    game = get_game()
    try:
        with _serialized_web_write(game):
            row = next(
                (item for item in game.directive_rows() if int(item["id"]) == directive_id),
                None,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="未找到草案。")
            text = request.text if request.text is not None else str(row["text"])
            if not text.strip():
                raise HTTPException(status_code=400, detail="指令内容不能为空。")
            capture_turn = int(game.state.turn)
            existing_mode = game.db.read_directive_dossier_payload(row).get("mode")
        from ming_sim.cli_backend import capture_manual_directive_payload
        dossier_payload = await asyncio.to_thread(
            capture_manual_directive_payload,
            text.strip(),
            game.session.llm_config,
            existing_mode=existing_mode,
            **({"db": game.db, "content": game.content}
               if getattr(game, "content", None) is not None else {}),
        )
        with _serialized_web_write(game):
            if int(game.state.turn) != capture_turn:
                raise ValueError("旨意抽取期间回合已推进，请在当前回合重新提交。")
            game.session.update_directive(
                directive_id, text.strip(), dossier_payload=dossier_payload,
            )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except LLMUnavailable as e:
        # #1274 V-1 r6 / #1452：回禀产文失败 → 结构化 400，禁裸 500 / 固定戏内模板。
        raise HTTPException(status_code=400, detail=_llm_error_detail(e)) from None
    return {"directives": [game.directive_payload(item) for item in game.directive_rows()]}


@app.delete("/api/directives/{directive_id}")
async def api_delete_directive(directive_id: int) -> Dict[str, Any]:
    game = get_game()
    try:
        with _serialized_web_write(game):
            game.session.delete_directive(directive_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {"directives": [game.directive_payload(item) for item in game.directive_rows()]}


@app.post("/api/decree/advance_without_edict")
def api_advance_without_edict(
    body: AdvanceWithoutEdictRequest = AdvanceWithoutEdictRequest(),
) -> Dict[str, Any]:
    # #498 AC10 / #1353：内部屏障票据同步等在飞尾随终态
    # （消费工人终态，不按 elapsed 伪造 409）。用同步 def 交给 FastAPI threadpool，
    # 绝不在 async event loop 上跑同步 sleep（会冻结全服务）。
    game = get_game()
    turn_before = int(getattr(game.state, "turn", 0) or 0)
    failed_before = _failed_secret_order_ids_for_turn(game, turn_before)
    from ming_sim.audience_night import AudienceNightError
    settlement_result = None
    try:
        # #1241 S1：受理样板收 helper；advance 锁语义 = 非阻塞抢锁 409（禁改用阻塞 gate）。
        with _settlement_period_entry(game, write_cm=_serialized_web_write):
            # #1351 A1：获锁后、推进副作用前比对令牌；不匹配 → 409（样板 finally 清展示态）。
            _reject_stale_month_token(game, body.expected_turn, token_label="退朝")
            # #1274 QA J-1：无旨月与有旨月同走完整结算链（session.advance_without_decree
            # → resolve_turn(allow_empty_decree) → pre_settle+simulator+settle）。
            # 16ms 快路已废；decree.advance_without_edict 空壳已删；有草案时 advance 内转 resolve_turn。
            settlement_result = game.session.advance_without_decree(inflight_wait_s=0.0)
            if settlement_result is None or not settlement_result.awaiting:
                game.session.end_turn()
                game.refresh_turn()
    except HTTPException:
        # 令牌/相位/锁门 409 等既有 HTTP 面原样上抛，禁被下方 Exception 改包。
        raise
    except ValueError as e:
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        detail: Any = {"message": str(e), "pending_action_failures": failures} if failures else str(e)
        raise HTTPException(status_code=400, detail=detail) from None
    except SettlementAbort as e:
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        detail = {"message": str(e), "pending_action_failures": failures} if failures else str(e)
        raise HTTPException(status_code=409, detail=detail) from None
    except (AudienceNightError, ExceptionGroup) as e:
        # #498 AC10 / #612：在飞超时或 close 双支 → 夜保持开、409 可原地重试。
        raise _retryable_audience_close_http(e) from None
    except Exception as e:  # noqa: BLE001
        # #1433：同流式颁诏 4616-4623——LLMUnavailable→可读 _llm_error_detail；其余 Exception→str。
        # HTTP 面 LLM 死走 412（菜单/连通先例）；禁裸 500 无 detail。
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        if isinstance(e, LLMUnavailable):
            detail = _llm_error_detail(e)
            if failures:
                detail = {**detail, "pending_action_failures": failures}
            raise HTTPException(status_code=412, detail=detail) from None
        message = str(e) or "退朝结算失败，请重试。"
        detail = (
            {"message": message, "pending_action_failures": failures}
            if failures else {"message": message}
        )
        raise HTTPException(status_code=500, detail=detail) from None
    return {
        "state": game.state_payload(),
        "awaiting_decision": bool(
            settlement_result is not None and settlement_result.awaiting
        ),
        "decisions": (
            settlement_result.decisions
            if settlement_result is not None and settlement_result.awaiting else []
        ),
        "pending_action_failures": _new_secret_order_failure_payloads_for_turn(
            game, turn_before, failed_before),
    }


# #1341/#1338：PATCH /api/decree 已删（web/src 零真实调用方；裸设总诏绕过 directives
# 结构化违 P1）。OpenAPI 随路由消失。拟诏/改稿只走 POST|PATCH /api/directives。


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


@app.post("/api/decree/issue")
def api_issue_decree(body: IssueDecreeRequest = IssueDecreeRequest()) -> Dict[str, Any]:
    """非流式颁诏（保留兼容）。前端默认走 /api/decree/issue/stream。

    同步 def：内部队列屏障 + resolve_turn 是阻塞同步调用
    （等在飞回话工人终态；#1353 K10a 不按 elapsed 造 409），交给 FastAPI threadpool，
    不冻结 async event loop。"""
    game = get_game()
    was_ended = bool(game.state.ended)
    turn_before = int(getattr(game.state, "turn", 0) or 0)
    failed_before = _failed_secret_order_ids_for_turn(game, turn_before)
    from ming_sim.audience_night import AudienceNightError
    try:
        # #1241 S1：受理样板收 helper；issue 锁语义 = 阻塞 _game_write_gate（禁改非阻塞）。
        with _settlement_period_entry(game, write_cm=_game_write_gate):
            # #1277/#1351：获锁后、resolve_turn 前比对令牌；不匹配 → 409（样板 finally 清展示态）。
            _reject_stale_month_token(game, body.expected_turn, token_label="颁诏")
            result = game.session.resolve_turn(cheat_directive=body.cheat, inflight_wait_s=0.0)
            decree = game.session.last_decree
            failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
            if result.awaiting:
                # 决策点暂停：回合未结算，返回决策点让前端弹窗；不刷新、不计 steam。
                return {
                    **_settlement_player_payload(
                        decree=decree,
                        decisions=result.decisions,
                        pending_action_failures=failures,
                    ),
                    "awaiting_decision": True,
                }
            report = result.report
            game.session.end_turn()
            game.refresh_turn()
            events = [
                steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                steam_events.set_stat(steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn)),
            ]
            if not was_ended and game.state.ended:
                events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
            return steam_events.with_events(_settlement_player_payload(
                decree=decree,
                report=report,
                pending_action_failures=failures,
            ), events)
    except ValueError as e:
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        detail = {"message": str(e), "pending_action_failures": failures} if failures else str(e)
        raise HTTPException(status_code=400, detail=detail) from None
    except SettlementAbort as e:
        # 结算中止（ADR 0008 决定 6/7）：进度已保存可重试，detail 即玩家指引
        # （含错误包路径+「请发给作者」）。非 500——这是已处理的可重试态，不是服务器 bug。
        # settling 已落则 helper 保留交恢复。
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        detail = {"message": str(e), "pending_action_failures": failures} if failures else str(e)
        raise HTTPException(status_code=409, detail=detail) from None
    except LLMUnavailable as e:
        # #1452：非流式颁诏 LLM 死 → 结构化错误，禁裸 500（对齐 _llm_error_detail）。
        failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
        detail = _llm_error_detail(e)
        if failures:
            detail = {**detail, "pending_action_failures": failures}
        raise HTTPException(status_code=400, detail=detail) from None
    except (AudienceNightError, ExceptionGroup) as e:
        # #498 AC10 / #612：在飞超时或 close 双支 → 夜保持开、409 可原地重试。
        raise _retryable_audience_close_http(e) from None


@app.post("/api/decree/issue/stream")
async def api_issue_decree_stream(body: IssueDecreeRequest = IssueDecreeRequest()) -> StreamingResponse:
    """流式颁诏：推演过程（阶段/思考/正文）实时 SSE 推给前端。

    resolve_turn 是阻塞的同步调用，且 on_event 是 push 式回调。
    用 worker 线程跑 resolve_turn，回调把事件投进 Queue；
    async generator 从 Queue 拉事件转成 SSE。
    """
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def on_event(kind: str, data: str) -> None:
        ev_queue.put((kind, data))

    def worker() -> None:
        game = None
        turn_before = 0
        failed_before: set[int] = set()
        try:
            game = get_game()
            was_ended = bool(game.state.ended)
            turn_before = int(game.state.turn)
            failed_before = _failed_secret_order_ids_for_turn(game, turn_before)
            # #1241 S1：受理样板收 helper；stream 锁语义 = 阻塞 _game_write_gate（与 issue 同）。
            # 终态 __done__/__decisions__ 须在 entry（含 clear）成功后才入队——
            # 与 settled_ok 同核：clear 抛错走 __error__，禁先推成功终态。
            terminal: Optional[tuple[str, Any]] = None
            with _settlement_period_entry(game, write_cm=_game_write_gate):
                # #1277/#1351：获锁后、resolve_turn 前比对令牌；不匹配 → 409（样板 finally 清展示态）。
                _reject_stale_month_token(game, body.expected_turn, token_label="颁诏")
                result = game.session.resolve_turn(
                    on_event=on_event, cheat_directive=body.cheat, inflight_wait_s=0.0)
                decree = game.session.last_decree
                failures = _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if result.awaiting:
                    # 决策点暂停：邸报已流式推完，再推 decisions 让前端弹窗；本回合未结算、不刷新、不计 steam。
                    terminal = ("__decisions__", _settlement_player_payload(
                        decree=decree,
                        decisions=result.decisions,
                        pending_action_failures=failures,
                    ))
                else:
                    report = result.report
                    game.session.end_turn()
                    game.refresh_turn()
                    events = [
                        steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                        steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                        steam_events.set_stat(steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn)),
                    ]
                    if not was_ended and game.state.ended:
                        events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
                    terminal = ("__done__", _settlement_player_payload(
                        decree=decree,
                        report=report,
                        steam_events=events,
                        pending_action_failures=failures,
                    ))
            if terminal is not None:
                ev_queue.put(terminal)
        except ValueError as e:
            # exit/end 已由 _settlement_period_entry 在异常路径完成（若已 begin）。
            failures = (
                _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if game is not None else []
            )
            ev_queue.put(("__error__", {"message": str(e), "pending_action_failures": failures} if failures else str(e)))
        except HTTPException as e:
            # #1277：令牌 409 等须保留 detail.turn / status_code，供 FE 复用 advance 的
            # 「serverTurn>expected → reload 不报错」；禁 str(HTTPException) 丢结构。
            failures = (
                _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if game is not None else []
            )
            detail = e.detail
            if isinstance(detail, dict):
                payload = dict(detail)
                payload.setdefault("status_code", e.status_code)
                if failures and "pending_action_failures" not in payload:
                    payload["pending_action_failures"] = failures
                ev_queue.put(("__error__", payload))
            else:
                payload = {"message": str(detail), "status_code": e.status_code}
                if failures:
                    payload["pending_action_failures"] = failures
                ev_queue.put(("__error__", payload))
        except Exception as e:  # noqa: BLE001
            # #1235：真失败另形——helper 已 exit（含 AudienceNightError / SettlementAbort）。
            failures = (
                _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if game is not None else []
            )
            message = _llm_error_detail(e) if isinstance(e, LLMUnavailable) else str(e)
            ev_queue.put(("__error__", {"message": message, "pending_action_failures": failures} if failures else message))

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
            # stage / thinking / text
            yield sse_event(kind, {"content": data})

    return StreamingResponse(generate(), media_type="text/event-stream")


class ResolveDecisionsRequest(BaseModel):
    # #1589：皇帝亲裁结果，每项须显式携带 decision_key（{decision_key, label, hint?, note?}）；
    # 缺键/重复键/desk 外键整批拒绝，不落任何领域写。dossier 批红另须带
    # dossier_id/dossier_decision（#1490，非法不落 decided）。
    choices: List[Dict[str, Any]] = []
    cheat: str = ""


@app.post("/api/decree/resolve_decisions/stream")
async def api_resolve_decisions_stream(body: ResolveDecisionsRequest) -> StreamingResponse:
    """皇帝亲裁完决策点，流式跑 phase2 结算（extractor→落库→结局）。
    与 issue/stream 同结构：worker 跑 session.submit_hitl_choices（唯一 HITL 编排入口，
    keyed 权威由 validate_all 整批拒），SSE 推 stage/text + done。"""
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def on_event(kind: str, data: str) -> None:
        ev_queue.put((kind, data))

    def worker() -> None:
        game = None
        turn_before = 0
        failed_before: set[int] = set()
        try:
            game = get_game()
            was_ended = bool(game.state.ended)
            turn_before = int(game.state.turn)
            failed_before = _failed_secret_order_ids_for_turn(game, turn_before)
            # #1322：相位快速预检前移到受理/抢锁前（假 200/锁排队拖成数十秒）；
            # 锁内 submit_decisions 仍做权威复查——与既有 TOCTOU 双查同款。
            if game.session.current_phase() != TurnPhase.AWAITING_DECISION:
                raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")
            # #657 / ADR 0149：展示态走 _settlement_period_entry；hold_write_for_body=False
            # 使 PREWRITE/② join 在 write_gate 外，①/③ 由 submit_hitl_choices 短持同一 gate。
            # 终态 __done__ 须在 entry（含 clear）成功后才入队——与 settled_ok 同核。
            # 唯一 HITL 编排：session.submit_hitl_choices；禁 submit_decisions 生产旁路。
            terminal: Optional[tuple[str, Any]] = None
            with _settlement_period_entry(
                game, write_cm=_game_write_gate, hold_write_for_body=False,
            ):
                report = game.session.submit_hitl_choices(
                    body.choices,
                    write_gate=_game_write_gate(game),
                    on_event=on_event,
                    cheat_directive=body.cheat,
                )
                decree = game.session.last_decree
                failures = _new_secret_order_failure_payloads_for_turn(
                    game, turn_before, failed_before,
                )
                # #1702 A2：尾写短持既有 write_gate，与热替换/其它持闸写者单写；
                # 不整段 body 持锁（join 仍在 gate 外）；成功 clear 仍走样板 False 支短持。
                with _game_write_gate(game):
                    game.session.end_turn()
                    game.refresh_turn()
                events = [
                    steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                    steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                    steam_events.set_stat(
                        steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn),
                    ),
                ]
                if not was_ended and game.state.ended:
                    events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
                terminal = ("__done__", _settlement_player_payload(
                    decree=decree,
                    report=report,
                    steam_events=events,
                    pending_action_failures=failures,
                ))
            if terminal is not None:
                ev_queue.put(terminal)
        except ValueError as e:
            # exit/end 已由 _settlement_period_entry 在异常路径完成（若已 begin）。
            failures = (
                _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if game is not None else []
            )
            ev_queue.put(("__error__", {"message": str(e), "pending_action_failures": failures} if failures else str(e)))
        except Exception as e:  # noqa: BLE001
            failures = (
                _new_secret_order_failure_payloads_for_turn(game, turn_before, failed_before)
                if game is not None else []
            )
            message = _llm_error_detail(e) if isinstance(e, LLMUnavailable) else str(e)
            ev_queue.put(("__error__", {"message": message, "pending_action_failures": failures} if failures else message))

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


class SaveCreateRequest(BaseModel):
    name: str


class LLMConfigRequest(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout_seconds: float = 0
    thinking_level: str = "__keep__"
    reasoning_strength: str = "__keep__"
    # None=不动，""=显式清空，其他=覆写。pydantic v1 默认 None 走不进来；用 sentinel "__keep__"
    advanced_model: str = "__keep__"
    advanced_base_url: str = "__keep__"
    advanced_api_key: str = "__keep__"
    advanced_thinking_level: str = "__keep__"
    # 通道感知（#51）：channel/cli_runner/cli_model 用 "__keep__" sentinel 表示「保留当前」;
    # cli_timeout_seconds 是数值,沿用数值 sentinel 0（=不改,build 回落当前值），不走 "__keep__"。
    channel: str = "__keep__"
    cli_runner: str = "__keep__"
    cli_model: str = "__keep__"
    cli_timeout_seconds: float = 0


@app.get("/api/consorts/candidates")
async def api_consort_candidates() -> Dict[str, Any]:
    """返回 status=candidate 的待选秀女，供选妃事件展示。"""
    candidates = [
        get_game().public_character(c)
        for c in get_game().content.characters.values()
        if c.office_type == "后宫" and c.status == "candidate" and get_game().character_power_id(c) == "ming"
    ]
    return {"candidates": candidates}


@app.post("/api/consorts/{name}/select")
async def api_select_consort(name: str) -> Dict[str, Any]:
    """皇帝选中某秀女，转 active 并赋予初始位份。"""
    game = get_game()
    consort = game.content.characters.get(name)
    if consort is None or consort.office_type != "后宫":
        raise HTTPException(status_code=404, detail=f"未找到候选秀女：{name}")
    if consort.status != "candidate":
        raise HTTPException(status_code=409, detail=f"{name} 当前状态为 {consort.status}，不可再选。")
    # 整段逻辑写（DB + in-memory state/content/registry）都在门内，避免提前释放锁后留下
    # DB 已改、内存未改的窗口被结算/召对观察到（cmr Gate2 Finding2 DB/内存撕裂）。
    with _serialized_web_write(game):
        game.db.set_character_office(name, "嫔", "后宫", source="皇帝选妃")
        game.db.set_character_status(game.state, name, "active", "皇帝选中入宫")
        consort.office = "嫔"
        consort.office_type = "后宫"
        consort.status = "active"
        # 同步进 registry（新增 agent）
        game.session.registry.register(consort)
    game.chat_history.setdefault(name, [])
    return {"selected": game.public_character(consort)}


@app.get("/api/saves")
async def api_list_saves() -> Dict[str, Any]:
    return {"saves": get_game().list_saves()}


@app.post("/api/saves")
async def api_create_save(request: SaveCreateRequest) -> Dict[str, Any]:
    # save_to → db.backup_to（commit + sqlite backup）：结算/后台召对 worker 持锁期间不能并发
    # 走同一无锁连接（否则撞 _commit_suspended 守卫成 500）。走 _write_gate → 忙时干净 409
    # （cmr Gate2 r5）。生命周期写也纳入串行门，完整收口（连接级 close 竞态的通用解仍属 #382）。
    game = get_game()
    with _serialized_web_write(game):
        info = game.save_to(request.name)
    return steam_events.with_events(
        {"save": info, "saves": game.list_saves()},
        [steam_events.add_stat(steam_events.STAT_SAVES_CREATED)],
    )


@app.delete("/api/saves/{name}")
async def api_delete_save(name: str) -> Dict[str, Any]:
    get_game().delete_save(name)
    return {"saves": get_game().list_saves()}


@app.post("/api/saves/{name}/load")
async def api_load_save(name: str) -> Dict[str, Any]:
    # load_save 会 session.close() 热替换主 DB——若结算/后台召对 worker 正持锁写旧连接，关连接
    # 会让 worker 崩在「closed database」。非阻塞抢 _write_gate：忙时 409，让玩家待 worker 落定
    # 再载（cmr Gate2 r5；强制中断在途 worker 的取消语义属 #382 通用并发模型，本轮不做）。
    game = get_game()
    _run_hot_replace(game, lambda: game.load_save(name), failure_label="载入存档失败")
    return {"state": get_game().state_payload()}


@app.post("/api/game/reset")
async def api_reset_game() -> Dict[str, Any]:
    """清空主 DB 重开新局。存档目录保留。"""
    # reset_game 关连接 + 删 sqlite 文件 + 重建——同 load_save，正持锁的 worker 会崩在关连接上。
    # 非阻塞抢 _write_gate：忙时 409（cmr Gate2 r5；强制中断在途属 #382）。
    game = get_game()
    _run_hot_replace(game, lambda: game.reset_game(), failure_label="重开新局失败")
    return steam_events.with_events(
        {"state": get_game().state_payload()},
        [steam_events.add_stat(steam_events.STAT_RUNS_STARTED)],
    )


@app.get("/api/llm/config")
async def api_get_llm_config() -> Dict[str, Any]:
    """读当前生效的 LLM 配置。api_key 不回传明文，只回是否已设置。"""
    from ming_sim.cli_backend import CLI_REASONING_STRENGTH_RUNNERS, cli_model_choices, cli_runner_choices
    cfg = get_game().session.llm_config
    saved = load_runtime_llm()
    saved_cli = saved.get("cli") if isinstance(saved.get("cli"), dict) else {}
    saved_api = saved.get("api") if isinstance(saved.get("api"), dict) else {}
    saved_api_reasoning_strength = normalize_reasoning_strength(saved_api.get("reasoning_strength"))
    saved_cli_reasoning_strength = normalize_reasoning_strength(saved_cli.get("reasoning_strength"))
    reasoning_supported = (
        cli_supports_reasoning_strength(cfg.cli_runner)
        if cfg.channel == "cli"
        else _api_reasoning_supported_for_effective_model(
            cfg.base_url, cfg.model, cfg.advanced_base_url, cfg.advanced_model
        )
    )
    return {
        "channel": cfg.channel,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "timeout_seconds": cfg.timeout_seconds,
        "thinking_level": cfg.thinking_level,
        "reasoning_strength": cfg.reasoning_strength,
        "reasoning_supported": reasoning_supported,
        "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
        # #1271：能力名单自 cli_backend 单源导出。
        "cli_reasoning_runners": sorted(CLI_REASONING_STRENGTH_RUNNERS),
        "advanced_model": cfg.advanced_model,
        "advanced_base_url": cfg.advanced_base_url,
        "has_advanced_api_key": _has_real_api_key(cfg.advanced_api_key),
        "advanced_thinking_level": "",
        "has_api_key": _has_real_api_key(cfg.api_key),
        "cli_runner": cfg.cli_runner,
        "cli_model": cfg.cli_model,
        "cli_model_choices": cli_model_choices(),
        # #1274 W1：CLI Runner 下拉单源（= _CLI_BACKENDS 有序），menuPage/gameMenu 共吃。
        "cli_runners": cli_runner_choices(),
        "cli_timeout_seconds": cfg.cli_timeout_seconds,
        "persisted": {
            "channel": saved.get("channel", ""),
            "base_url": saved.get("base_url", ""),
            "model": saved.get("model", ""),
            "has_api_key": _has_real_api_key(saved.get("api_key", "")),
            "timeout_seconds": float(saved.get("timeout_seconds") or API_DEFAULT_TIMEOUT_SECONDS),
            "thinking_level": saved.get("thinking_level", ""),
            "reasoning_strength": saved.get("reasoning_strength", ""),
            "api_reasoning_strength": saved_api_reasoning_strength,
            "cli_reasoning_strength": saved_cli_reasoning_strength,
            "advanced_model": saved.get("advanced_model", ""),
            "advanced_base_url": saved.get("advanced_base_url", ""),
            "has_advanced_api_key": _has_real_api_key(saved.get("advanced_api_key", "")),
            "advanced_thinking_level": "",
            "cli_runner": str(saved_cli.get("runner") or ""),
            "cli_model": str(saved_cli.get("model") or ""),
            "cli_timeout_seconds": _runtime_float(saved_cli.get("timeout_seconds"), CLI_DEFAULT_TIMEOUT_SECONDS),
        },
    }


@app.post("/api/llm/config")
async def api_set_llm_config(request: LLMConfigRequest) -> Dict[str, Any]:
    thinking_level = None if request.thinking_level == "__keep__" else request.thinking_level
    reasoning_strength = None if request.reasoning_strength == "__keep__" else request.reasoning_strength
    advanced = None if request.advanced_model == "__keep__" else request.advanced_model
    adv_base = None if request.advanced_base_url == "__keep__" else request.advanced_base_url
    adv_key = None if request.advanced_api_key == "__keep__" else request.advanced_api_key
    adv_thinking = None if request.advanced_thinking_level == "__keep__" else request.advanced_thinking_level
    channel = None if request.channel == "__keep__" else request.channel
    cli_runner = None if request.cli_runner == "__keep__" else request.cli_runner
    cli_model = None if request.cli_model == "__keep__" else request.cli_model
    try:
        # 通道感知 build（#51）。verify(CLI smoke ~12s,只读)offload 出 event loop 不卡 UI;
        # commit(落盘+begin_turn 改 session 态)**留在 loop 上同步跑**——单人 CLI 串行探针下它原子、
        # 无并发 race,无需全局锁(CMR R3-R5:把 commit offload 到线程引入 session race / 断连
        # cancel 下 worker-join 不可靠的一连串并发边缘,对单人场景得不偿失,故回退到 on-loop)。
        game = get_game()
        cfg = game.build_llm_config(
            request.base_url,
            request.model,
            request.api_key,
            request.timeout_seconds,
            thinking_level=thinking_level,
            reasoning_strength=reasoning_strength,
            advanced_model=advanced,
            advanced_base_url=adv_base,
            advanced_api_key=adv_key,
            advanced_thinking_level=adv_thinking,
            channel=channel,
            cli_runner=cli_runner,
            cli_model=cli_model,
            cli_timeout_seconds=request.cli_timeout_seconds,
        )
        await asyncio.get_running_loop().run_in_executor(None, _verify_llm_configs_or_raise, cfg)
        # commit 仍同步 on-loop（上方注释的刻意决定不变），但须走 _write_gate：commit_llm_config
        # 末尾 begin_turn 会 save_state/apply_historical_* 直写共享连接，#383 后台召对 worker /
        # #393 线程化结算引入了真并发——那条「单人无并发 race、无需锁」的前提已被推翻，结算/召对
        # worker 持锁期间 commit 会撞同一无锁连接（cmr Gate2 r4 Finding1）。非阻塞抢锁、保持 on-loop。
        with _serialized_web_write(game):
            game.commit_llm_config(cfg)
    except HTTPException:
        # _verify_llm_configs_or_raise 已把校验失败包成带干净 detail 的 HTTPException;
        # 经 run_in_executor 透传上来后原样抛,别被下面 except Exception 二次包裹 mangle 掉(Gemini R2)。
        raise
    except LLMUnavailable as e:
        raise HTTPException(status_code=400, detail=_llm_error_detail(e)) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_llm_error_detail(e)) from None
    from ming_sim.cli_backend import CLI_REASONING_STRENGTH_RUNNERS, cli_runner_choices
    reasoning_supported = (
        cli_supports_reasoning_strength(cfg.cli_runner)
        if cfg.channel == "cli"
        else _api_reasoning_supported_for_effective_model(
            cfg.base_url, cfg.model, cfg.advanced_base_url, cfg.advanced_model
        )
    )
    return {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "timeout_seconds": cfg.timeout_seconds,
        "thinking_level": cfg.thinking_level,
        "reasoning_strength": cfg.reasoning_strength,
        "reasoning_supported": reasoning_supported,
        "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
        # #1271：能力名单自 cli_backend 单源导出。
        "cli_reasoning_runners": sorted(CLI_REASONING_STRENGTH_RUNNERS),
        "advanced_model": cfg.advanced_model,
        "advanced_base_url": cfg.advanced_base_url,
        "has_advanced_api_key": _has_real_api_key(cfg.advanced_api_key),
        "advanced_thinking_level": "",
        "has_api_key": _has_real_api_key(cfg.api_key),
        "channel": cfg.channel,
        "cli_runner": cfg.cli_runner,
        "cli_model": cfg.cli_model,
        # #1274 W1：CLI Runner 下拉单源。
        "cli_runners": cli_runner_choices(),
        "cli_timeout_seconds": cfg.cli_timeout_seconds,
    }


# ── 自定义立绘上传/读取 ──────────────────────────────────────────────────────
# content_type → 存盘扩展名。一人一图，上传新图会顶掉旧扩展名的文件。
_PORTRAIT_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _find_portrait_file(name: str) -> Optional[str]:
    """找该人物已存在的自定义立绘文件（任一扩展名），无则 None。"""
    for ext in _PORTRAIT_EXT.values():
        path = os.path.join(UPLOAD_PORTRAIT_DIR, f"{name}.{ext}")
        if os.path.exists(path):
            return path
    return None


@app.post("/api/consorts/{name}/portrait")
async def api_upload_portrait(name: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    # 只接受已存在的人物名 → 集合固定，杜绝路径穿越/任意写。
    game = get_game()
    character = game.find_character(name)
    if character is None:
        raise HTTPException(status_code=404, detail="未找到该人物")
    ext = _PORTRAIT_EXT.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPEG/WebP 图片")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_PORTRAIT_BYTES:
        raise HTTPException(status_code=400, detail="图片过大（上限 8MB）")
    with _serialized_web_write(game):
        os.makedirs(UPLOAD_PORTRAIT_DIR, exist_ok=True)
        # 先清掉该人物的旧图（可能扩展名不同），再写新图。
        old = _find_portrait_file(name)
        if old is not None:
            os.remove(old)
        with open(os.path.join(UPLOAD_PORTRAIT_DIR, f"{name}.{ext}"), "wb") as fh:
            fh.write(data)
        game.set_custom_portrait(name, f"{CUSTOM_PORTRAIT_PREFIX}{name}")
    return {"name": name, "portrait_id": f"{CUSTOM_PORTRAIT_PREFIX}{name}"}


@app.delete("/api/consorts/{name}/portrait")
async def api_delete_portrait(name: str) -> Dict[str, Any]:
    game = get_game()
    character = game.find_character(name)
    if character is None:
        raise HTTPException(status_code=404, detail="未找到该人物")
    with _serialized_web_write(game):
        old = _find_portrait_file(name)
        if old is not None:
            os.remove(old)
        # 复位 portrait_id：清空 → 前端回落到池图（add/seed 时会按 office_type 再分配）。
        game.set_custom_portrait(name, "")
    return {"name": name, "portrait_id": ""}


@app.get("/api/court_layout")
async def api_get_court_layout() -> Dict[str, Any]:
    val = get_game().db.kv_get("court_layout")
    return {"layout": val or "{}"}


@app.post("/api/court_layout")
async def api_set_court_layout(body: Dict[str, Any]) -> Dict[str, Any]:
    game = get_game()
    with _serialized_web_write(game):
        game.db.kv_set("court_layout", body.get("layout", "{}"))
    return {"ok": True}


@app.get("/portraits/custom/{name}")
async def api_get_portrait(name: str):
    path = _find_portrait_file(name)
    if path is None:
        raise HTTPException(status_code=404, detail="无自定义立绘")
    return FileResponse(path)


# ── 调试台：直接读写核心表 ─────────────────────────────────────
@app.get("/api/admin/tables")
async def api_admin_tables() -> Dict[str, Any]:
    return {"tables": list(get_game().db.ADMIN_TABLES.keys())}


@app.get("/api/admin/table/{table}")
async def api_admin_table(table: str) -> Dict[str, Any]:
    db = get_game().db
    try:
        return {
            "table": table,
            "pk": db.admin_check_table(table),
            "columns": db.admin_columns(table),
            "rows": db.admin_rows(table),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/table/{table}/upsert")
async def api_admin_upsert(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    game = get_game()
    try:
        with _serialized_web_write(game):
            row = game.db.admin_upsert(table, payload)
            # 内存 state 同步留在门内：否则提前释放锁后留下 DB 已改、内存未改的撕裂窗口被
            # 结算/召对（读 game.state）观察到（cmr Gate2 Finding2）。
            st = game.state
            if table == "metrics" and row.get("key") in st.metrics:
                st.metrics[row["key"]] = int(row["value"])
            elif table == "game_state":
                st.year, st.period, st.turn = int(row["year"]), int(row["period"]), int(row["turn"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"row": row}


@app.post("/api/admin/table/{table}/delete")
async def api_admin_delete(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    game = get_game()
    pk_value = payload.get("pk_value")
    if pk_value in (None, ""):
        raise HTTPException(status_code=400, detail="缺 pk_value")
    try:
        with _serialized_web_write(game):
            return {"deleted": game.db.admin_delete(table, pk_value)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin")
async def admin_page():
    return HTMLResponse(_ADMIN_HTML)


if os.path.isdir(WEB_DIST):
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


_ADMIN_HTML = """<!doctype html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>调试台 · 核心表增删改查</title>
<style>
  :root{--bg:#1b1712;--panel:#26211a;--line:#3a3228;--txt:#e8dcc6;--accent:#c8a35a;--danger:#b5503f;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,"PingFang SC",monospace}
  header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  header h1{font-size:16px;margin:0 12px 0 0;color:var(--accent)}
  .tab{padding:5px 12px;border:1px solid var(--line);background:var(--panel);color:var(--txt);border-radius:4px;cursor:pointer}
  .tab.active{background:var(--accent);color:#1b1712;font-weight:600}
  #bar{padding:8px 16px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center}
  button.act{padding:5px 12px;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer}
  button.act:hover{background:var(--accent);color:#1b1712}
  #wrap{overflow:auto;height:calc(100vh - 110px)}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{border:1px solid var(--line);padding:4px 6px;text-align:left;white-space:nowrap}
  th{position:sticky;top:0;background:var(--panel);color:var(--accent);z-index:1}
  th.pk{color:#e8c87a}
  td input{width:100%;min-width:90px;background:#15110c;border:1px solid var(--line);color:var(--txt);padding:3px 5px;border-radius:3px;font:13px monospace}
  td input:focus{border-color:var(--accent);outline:none}
  tr.dirty td{background:#2e2718}
  td.ops{white-space:nowrap}
  .sm{padding:3px 8px;font-size:12px;border-radius:3px;cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--txt)}
  .sm.save{border-color:var(--accent);color:var(--accent)}
  .sm.del{border-color:var(--danger);color:var(--danger)}
  #msg{margin-left:auto;color:#9c8c6a;font-size:12px}
  .hint{color:#6f6552;font-size:12px}
</style></head><body>
<header><h1>调试台 · 直改核心表</h1><span id="tabs"></span></header>
<div id="bar">
  <button class="act" id="addBtn">+ 新增行</button>
  <button class="act" id="reload">↻ 重载</button>
  <span class="hint">改格变黄→点行尾「存」。新增行须填主键才能存。删除不可撤销。</span>
  <span id="msg"></span>
</div>
<div id="wrap"><table id="grid"></table></div>
<script>
let cur=null, cols=[], pk=null, rows=[];
const $=s=>document.querySelector(s), msg=t=>{$("#msg").textContent=t;};
async function jget(u){const r=await fetch(u);if(!r.ok)throw new Error((await r.json()).detail||r.status);return r.json();}
async function jpost(u,b){const r=await fetch(u,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(b)});if(!r.ok)throw new Error((await r.json()).detail||r.status);return r.json();}
async function init(){
  const tabs=(await jget("/api/admin/tables")).tables;
  $("#tabs").innerHTML=tabs.map(t=>`<span class="tab" data-t="${t}">${t}</span>`).join("");
  document.querySelectorAll(".tab").forEach(e=>e.onclick=()=>load(e.dataset.t));
  load(tabs[0]);
}
async function load(t){
  cur=t; msg("加载…");
  document.querySelectorAll(".tab").forEach(e=>e.classList.toggle("active",e.dataset.t===t));
  const d=await jget("/api/admin/table/"+t);
  cols=d.columns; pk=d.pk; rows=d.rows; render(); msg(rows.length+" 行");
}
function render(){
  const g=$("#grid");
  const head="<tr>"+cols.map(c=>`<th class="${c.pk?'pk':''}">${c.name}${c.pk?' 🔑':''}<br><span class="hint">${c.type}</span></th>`).join("")+"<th>操作</th></tr>";
  g.innerHTML=head+rows.map((r,i)=>rowHtml(r,i)).join("");
  g.querySelectorAll("input").forEach(inp=>inp.oninput=()=>inp.closest("tr").classList.add("dirty"));
  g.querySelectorAll(".save").forEach(b=>b.onclick=()=>saveRow(+b.dataset.i));
  g.querySelectorAll(".del").forEach(b=>b.onclick=()=>delRow(+b.dataset.i));
}
function rowHtml(r,i){
  const tds=cols.map(c=>{
    const v=r[c.name]==null?"":r[c.name];
    return `<td><input data-c="${c.name}" value="${String(v).replace(/"/g,'&quot;')}"></td>`;
  }).join("");
  return `<tr data-i="${i}">${tds}<td class="ops"><button class="sm save" data-i="${i}">存</button> <button class="sm del" data-i="${i}">删</button></td></tr>`;
}
function readRow(i){
  const tr=document.querySelector(`tr[data-i="${i}"]`), o={};
  tr.querySelectorAll("input").forEach(inp=>{
    const c=cols.find(x=>x.name===inp.dataset.c); let v=inp.value;
    if(v===""){o[inp.dataset.c]=null;return;}
    if(c && /INT/i.test(c.type)) v=parseInt(v,10);
    o[inp.dataset.c]=v;
  });
  return o;
}
async function saveRow(i){
  try{
    const body=readRow(i);
    if(body[pk]==null||body[pk]===""){msg("⚠ 主键 "+pk+" 不能空");return;}
    const d=await jpost(`/api/admin/table/${cur}/upsert`,body);
    rows[i]=d.row; render(); msg("✓ 已存 "+body[pk]);
  }catch(e){msg("✗ "+e.message);}
}
async function delRow(i){
  const key=rows[i][pk];
  if(key!=null&&key!==""&&!confirm(`删除 ${cur} 行：${pk}=${key} ？不可撤销`))return;
  try{
    if(key==null||key===""){rows.splice(i,1);render();msg("已移除未存行");return;}
    const d=await jpost(`/api/admin/table/${cur}/delete`,{pk_value:key});
    rows.splice(i,1); render(); msg("✓ 删 "+d.deleted+" 行");
  }catch(e){msg("✗ "+e.message);}
}
$("#addBtn").onclick=()=>{const o={};cols.forEach(c=>o[c.name]=null);rows.unshift(o);render();msg("新增空行，填主键后点存");};
$("#reload").onclick=()=>load(cur);
init().catch(e=>msg("初始化失败:"+e.message));
</script></body></html>"""
