#!/usr/bin/env python3
"""FastAPI web entry for Ming Salvage Sim.

薄壳：路由调 ming_sim.session.GameSession（与 CLI 共用同一流转层）。
拟旨候选：大臣 propose_directive/前缀/自然语言 → pending_actions 闸门 → 对话确认或颁诏默认同意。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import queue
import random
import re
import shutil
import sys
import time
import threading
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

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
    load_runtime_game,
    load_runtime_llm,
    normalize_openai_base_url,
    normalize_thinking_level,
    normalize_reasoning_strength,
    legacy_reasoning_strength,
    save_runtime_game,
    save_runtime_llm,
)
from ming_sim.agents import _dump_llm_messages
from ming_sim.llm_model import extract_agent_text, verify_llm_available
from ming_sim.llm_contract import fail_if_llm_error
from ming_sim.issues import _format_issue_ongoing, commitment_display_text, commitment_progress_payload, commitment_timed_bar_value
from ming_sim.memories import effect_brief
from ming_sim.session import GameSession
from ming_sim.session import AUTO_SAVE_PREFIX
from ming_sim.skills import available_skill_ids, skill_display_name, skill_source_labels
from ming_sim.context import match_minister_from_text
from ming_sim.flows import compute_budget_lines
from ming_sim.exceptions import LLMContractError  # noqa: F401  (保留：供错误处理)
from ming_sim.models import (
    API_DEFAULT_MAX_TOKENS,
    API_DEFAULT_TIMEOUT_SECONDS,
    Character,
    FRONT_HALF_DONE_PHASES,
    LLMConfig,
    TurnPhase,
    is_vassal_prince,
    loads_effect_dict,
)
from ming_sim import steam_events

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


def _turn_account_report(db, turn: int) -> str:
    extraction = db.get_turn_extraction(turn)
    if not extraction:
        return ""
    applied = extraction.get("extractor_output")
    if isinstance(applied, dict) and applied.get("mode") == "modular" and isinstance(applied.get("merged"), dict):
        applied = applied["merged"]
    lines: List[str] = ["本月实账："]
    if isinstance(applied, dict):
        brief = effect_brief(applied)
        lines.append(brief or "无显著落账。")
    elif applied:
        lines.append(str(applied))
    else:
        lines.append("无显著落账。")

    try:
        # 旧存档的 rejection_reports 可能没有 resimulation_invalidated 列：COALESCE 不能挡
        # 「列不存在」（SQLite 会直接 OperationalError），broad except 会把整段「窒碍未行」吞掉。
        # 先查列是否存在（同 decree._has_durable_player_visible_rejection 的 PRAGMA 守法），
        # 有才加该过滤，无则退化为不过滤（codex correctness）。
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(rejection_reports)").fetchall()}
        invalidated_clause = (
            "AND COALESCE(resimulation_invalidated, 0) = 0"
            if "resimulation_invalidated" in cols else ""
        )
        rows = db.conn.execute(
            f"""
            SELECT section, reason FROM rejection_reports
            WHERE turn = ?
              AND source IN ('player_decree', 'hitl_decision')
              {invalidated_clause}
            ORDER BY id
            """,
            (int(turn),),
        ).fetchall()
    except Exception:
        rows = []
    if rows:
        lines.append("")
        lines.append("窒碍未行：")
        for row in rows[:8]:
            section = str(row["section"] or "所拟事项")
            reason = str(row["reason"] or "有司未能照办")
            lines.append(f"- {section}：{reason}")
    return "\n".join(lines)


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
        max_tokens=config.max_tokens,
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
    max_tokens: int,
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
        max_tokens=max_tokens,
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


def _character_power_id(character: Character, db) -> str:
    """人物所属势力 id：DB 权威，回退内存 power_id，默认 ming。

    权威解析单一真源在 db.resolve_power_id（session.can_summon 等同源复用，见 #125），
    此处委托，朝堂可见性/召见两端口径一致、不各写一份。"""
    return db.resolve_power_id(character)


def visible_in_court(character: Character, db) -> bool:
    """朝堂大臣列表准入：ming 治下、非后宫、非宗藩，且 DB 权威状态非 offstage（离场/未登场不入列）。

    状态与势力一律以 DB 为准（与 public_character 同源）——内存 c.status 在 auto-debut
    等路径（set_character_status 只写 DB、不回写内存）会 stale，不能用作过滤依据（见 #104）。

    宗藩（就藩藩王，office_type=宗藩）不是可召见/可任免的朝堂官员，排除出朝堂+任免列表
    （用户 2026-06-14 拍）。藩王在册数据照旧留 DB，事件按名引用不受影响；office_type 由
    seed 走 use_llm=False 信 content 既定值=宗藩（PR#118 后确定可靠）。
    """
    if character.office_type in ("后宫", "宗藩"):
        return False
    if db.get_character_status(character.name)[0] == "offstage":
        return False
    return _character_power_id(character, db) == "ming"


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


class WebGame:
    """Web 端会话包装：持一个 GameSession + 网页专属态（聊天历史、收藏）。"""

    def __init__(self, fresh: bool = False) -> None:
        """实例化 = 真正进入游戏。无 API key 直接抛 LLMUnavailable。
        fresh=True：先清空主 DB（新游戏）再建 session。"""
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
        max_tokens = int(runtime.get("max_tokens") or API_DEFAULT_MAX_TOKENS)
        timeout_seconds = float(runtime.get("timeout_seconds") or timeout_seconds)
        random.seed(int(os.environ.get("MING_SIM_SEED", "7")))
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        llm_config = _llm_config_from_runtime(
            runtime,
            base_url=base_url,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            thinking_level=thinking_level,
            advanced_model=advanced_model,
            advanced_base_url=advanced_base_url,
            advanced_api_key=advanced_api_key,
            advanced_thinking_level=advanced_thinking_level,
        )
        if llm_config.channel != "cli" and not llm_config.api_key:
            raise LLMUnavailable("未配 API key，请先到设置页填写。")
        if fresh:
            verify_llm_available(llm_config)
            _delete_sqlite_db_files_or_raise(db_path)
        self.session = GameSession(db_path, llm_config, verify_llm=not fresh)
        self._write_gate = threading.Lock()
        # #396 Gap B: 排队等 gate 的旧召对 worker 计数 + 条件变量。
        # drain 须等计数归零（所有排队 worker 跑完）再关连接——否则只等当前持锁者，
        # drain 抢下一轮 acquire 后关 session，排队 worker 永不跑或写 closed DB。
        self._drain_cond = threading.Condition()
        self._pending_writes_count = 0
        self._draining = False
        self.session.begin_turn()
        # 召对记录持久化在 chat_messages 表，启动时恢复进内存缓存。
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

    def reset_game(self) -> None:
        """全清主 DB：关连接 → 删 sqlite 主/wal/shm → 重建空 session。
        存档目录不动。"""
        llm_config = self.session.llm_config
        verify_llm_available(llm_config)
        try:
            self.session.close()
        except Exception:
            pass
        _delete_sqlite_db_files_or_raise(self.db_path)
        self._rebuild_session(llm_config, verify_llm=False)

    def load_save(self, name: str) -> None:
        """从存档热替换主 DB：备份当前 → 拷源到主 DB → 重建 session。"""
        safe = self._safe_save_name(name)
        source = os.path.join(self.saves_dir(), f"{safe}.db")
        if not os.path.isfile(source):
            raise HTTPException(status_code=404, detail="存档不存在。")
        # 先关闭当前 session 的 DB 连接，避免 Windows/某些平台上的 file lock。
        try:
            self.session.close()
        except Exception:
            pass
        # 用 sqlite backup 把存档拷回主路径
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(source)
        dst_conn = _sqlite3.connect(self.db_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            src_conn.close()
            dst_conn.close()
        self._rebuild_session(self.session.llm_config)

    def _rebuild_session(self, llm_config: LLMConfig, verify_llm: bool = True) -> None:
        """用新 llm_config（或换完 DB 后）重建 GameSession + 内存缓存。"""
        if verify_llm:
            verify_llm_available(llm_config)
        self.session = GameSession(self.db_path, llm_config, verify_llm=False)
        self.session.begin_turn()
        self.chat_history = {name: [] for name in self.session.content.characters}
        for name, msgs in self.db.load_all_chat_history().items():
            self.chat_history.setdefault(name, []).extend(msgs)
        _DEFAULT_FAVORITES = {"王承恩", "曹化淳", "李若琏", "魏忠贤", "田尔耕"}
        _fav_raw = self.db.kv_get("favorites")
        self.favorites = set(json.loads(_fav_raw)) if _fav_raw else set(_DEFAULT_FAVORITES)
        if not _fav_raw:
            self.db.kv_set("favorites", json.dumps(sorted(self.favorites)))

    def build_llm_config(
        self,
        base_url: str,
        model: str,
        api_key: str,
        max_tokens: int = 0,
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
        new_max = max_tokens if max_tokens > 0 else cur.max_tokens
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
            max_tokens=new_max,
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
                    prev.max_tokens,
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
                new_config.max_tokens,
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
        return self.session.last_report

    def _runtime_write_gate(self) -> threading.Lock:
        gate = getattr(self, "_write_gate", None)
        if gate is None:
            gate = threading.Lock()
            self._write_gate = gate
        return gate

    def _mark_pending_write(self) -> bool:
        """#396 Gap B: 标记一个即将抢 write_gate 的流式召对 worker。
        drain 须等所有已标记 worker 完成才关连接——否则排队等 gate 的 worker
        会被 drain 抢下一轮 acquire 后关连接饿死。"""
        cond = getattr(self, "_drain_cond", None)
        if cond is None:
            return True
        with cond:
            if getattr(self, "_draining", False):
                return False
            self._pending_writes_count = getattr(self, "_pending_writes_count", 0) + 1
            return True

    def _complete_pending_write(self) -> None:
        cond = getattr(self, "_drain_cond", None)
        if cond is None:
            return
        with cond:
            count = getattr(self, "_pending_writes_count", 0)
            if count > 0:
                self._pending_writes_count = count - 1
            if self._pending_writes_count == 0:
                cond.notify_all()

    def refresh_turn(self) -> None:
        self.session.begin_turn()

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
        status_label = _STATUS_LABEL_WEB.get(status, "在朝" if status == "active" else status)
        office = character.office  # 去职者已被清空，可能为空串
        # summary 不含官职（卡片/详情已单独显 office），避免重复
        summary = f"{character.faction}一系，行事{character.style}。"
        power_id = self.db.resolve_power_id(character)  # 权威解析单一真源（#125）
        return {
            "name": character.name,
            "office": office,
            "office_type": character.office_type,
            "faction": character.faction,
            "style": character.style,
            "status": status,
            "status_reason": status_reason,
            "status_label": status_label,
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
            "authority": row["notes"] or "",
        }

    def directive_rows(self):
        # 颁诏候选 = draft；UI 列表含 pending
        return self.db.list_directives(self.state, statuses=("pending", "draft"))

    def map_nodes(self) -> List[Dict[str, Any]]:
        region_positions = {
            "beizhili": (55.5, 41.2), "nanzhili": (70, 41), "shandong": (56.8, 47.9),
            "shanxi": (48.8, 45.2), "henan": (58, 46), "shaanxi": (51, 38),
            "zhejiang": (73.7, 57.9), "jiangxi": (67, 55), "huguang": (59, 59),
            "sichuan": (57, 52), "fujian": (73.2, 65.1), "guangdong": (62.5, 73.6),
            "guangxi": (53.9, 69.6), "yunnan": (47, 69), "guizhou": (52, 56),
            "liaodong": (61.0, 37.6), "dongjiang_area": (68.9, 43.7),
            "shenyang_liaoyang": (61.3, 39.6), "jianzhou": (64.6, 31.0),
            "korea": (67.0, 44.8), "mongol_chahar": (47.0, 31.0), "nurgan": (58.2, 21.2),
            "outer_mongolia": (43.0, 24.0), "western_regions": (25.0, 40.0),
            "tibet": (31.0, 57.0), "amur_frontier": (70.0, 24.0),
            "japan": (83.0, 49.0), "southwest_frontier": (45.0, 75.0),
            "taiwan": (78, 67),
        }
        theater_positions = {
            "liaodong": (57.76, 42.21), "dongjiang": (63.95, 42.39),
            "xuan_da": (50.49, 40.08), "shanhaiguan": (55.52, 42.84),
        }
        armies = self.db.army_payload(danger_order=True)
        nodes: List[Dict[str, Any]] = []
        for region in self.db.region_payload():
            x, y = region_positions.get(str(region["id"]), (50, 50))
            stationed = [a for a in armies if self._army_belongs_to_region(a, region)]
            buildings = self.db.building_payload(str(region["id"]))
            risk = int(region["unrest"]) + int(region["military_pressure"]) + (100 - int(region["public_support"]))
            node_kind = "region" if str(region.get("controlled_by") or "ming") == "ming" else "external"
            nodes.append({"id": region["id"], "kind": node_kind, "x": x, "y": y, "region": region, "armies": stationed, "buildings": buildings, "risk": risk})
        for node_id, (x, y) in theater_positions.items():
            stationed = [a for a in armies if self._army_belongs_to_theater(a, node_id)]
            if stationed:
                nodes.append({"id": node_id, "kind": "theater", "x": x, "y": y, "label": self._theater_label(node_id), "armies": stationed, "risk": 120})
        return nodes

    def _army_belongs_to_region(self, army: Dict[str, Any], region: Dict[str, Any]) -> bool:
        station = str(army["station"])
        region_name = str(region["name"])
        return (
            str(region["id"]) in station
            or region_name in station
            or station in region_name
            or any(part.strip() and part.strip() in station for part in region_name.replace("／", "/").split("/"))
        )

    def _army_belongs_to_theater(self, army: Dict[str, Any], theater_id: str) -> bool:
        text = f"{army['id']} {army['name']} {army['station']} {army['theater']}"
        mapping = {
            "liaodong": ("辽东", "宁锦", "关宁"),
            "dongjiang": ("东江", "皮岛"),
            "xuan_da": ("宣大", "宣府", "大同"),
            "shanhaiguan": ("山海关",),
        }
        return any(word in text for word in mapping.get(theater_id, ()))

    def _theater_label(self, theater_id: str) -> str:
        return {
            "liaodong": "辽东 / 宁锦",
            "dongjiang": "东江镇",
            "xuan_da": "宣大",
            "shanhaiguan": "山海关",
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

    def budget_payload(self) -> Dict[str, Any]:
        # 唯一定额源：flows.compute_budget_lines（与实际落账 / 大臣 treasury_budget_summary 三处统一）。
        budget = compute_budget_lines(self.db, self.state)
        budget["国库"]["balance"] = int(self.state.metrics["国库"])
        budget["内库"]["balance"] = int(self.state.metrics["内库"])
        for account in (budget["国库"], budget["内库"]):
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
            "各军军饷", "宗室禄米", "百官俸禄", "工部", "赈灾备用",
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
        previous_turn = max(0, int(self.state.turn) - 1)
        return {
            "turn": {"year": self.state.year, "period": self.state.period,
                     "turn": self.state.turn, "phase": self.state.turn_phase},
            "metrics": self.state.metrics,
            "previous_summary": self.previous_summary,
            "previous_account_summary": _turn_account_report(self.db, previous_turn),
            "treasury": self.db.treasury_report(self.state),
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
                1 for a in self.db.list_pending_actions(int(self.state.turn))
                if a["kind"] == "directive"),
            "pending_decisions": (
                self.session.pending_decisions()
                if self.state.turn_phase == TurnPhase.AWAITING_DECISION.value else []
            ),
            "last_decree": self.last_decree,
            "last_report": self.last_report,
        }

    # ── 聊天 ──────────────────────────────────────────────────────────────
    def _persistent_chat_minister(self, minister_name: str) -> bool:
        return minister_name not in self.session.temporary_characters

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

    def _audience_turn_in_flight(self, minister_name: str) -> bool:
        """#383 背景召对契约：同一大臣已有「已受理、尚未完成回奏」的 turn 时，不得再开新轮。

        in-flight = `status='active'` 且 `minister_message_id` 仍空；已完成的可撤回 turn 其
        `minister_message_id` 已写、不算 in-flight，不挡新问。#383 把召对回合改成后台 worker
        续跑后，「离开实时流（前端 busy 已清）→ 重开同大臣 → 再问」会并发开两轮，两个后台
        worker 竞写同一 SQLite 连接（ADR0008 单写者不变式）并让历史错序——#383 Out of Scope
        明令「不允许同大臣并发未答 turn」。本守卫在两个召对入口（流式 chat_stream + 非流式
        chat）创建新 turn 前拒掉这种并发（integrated cmr Gate2，三模型一致 P1）。"""
        if not self._persistent_chat_minister(minister_name):
            return False
        existing = self.db.get_last_active_chat_turn(minister_name, self.state.turn)
        return existing is not None and not existing.get("minister_message_id")

    def _start_chat_turn(self, minister_name: str) -> tuple[int, Dict[str, Any]]:
        agno_session_id = self._minister_agno_session_id(minister_name)
        runs_before = self.db.agno_runs_length(agno_session_id)
        snapshot = self.db.capture_chat_rollback_snapshot()
        chat_turn_id = self.db.create_chat_turn(
            self.state,
            minister_name,
            agno_session_id,
            runs_before,
        )
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
        仍在进行」而拒收后续问话（cmr Gate2 F-B）。chat_turn_id=0（无持久轮）时为 no-op。"""
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
        try:
            undone = self.db.undo_chat_turn(int(row["id"]))
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
            "undone_chat_turn_id": int(undone["id"]),
            "history": self.chat_history.get(minister_name, []),
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "secret_orders": self.db.list_secret_orders(),
            "suggestions": self.suggestions_for(character),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
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
        chat_turn_id: int = 0,
        accepted_turn: Optional[int] = None,
    ) -> Dict[str, Any]:
        character = self.session._character(minister_name)
        self.chat_history[minister_name].append({"role": "minister", "content": answer})
        if minister_name not in self.session.temporary_characters:
            turn = int(self.state.turn if accepted_turn is None else accepted_turn)
            message_id = self.db.append_chat_message(minister_name, turn, "minister", answer)
            if chat_turn_id:
                self.db.update_chat_turn_messages(chat_turn_id, minister_message_id=message_id)
        return {
            "minister": minister_name,
            "answer": answer,
            "history": self.chat_history[minister_name],
            "court_action": court_action,
            "next_minister": next_minister,
            "proposed_directive": proposed_directive,
            "appointed_minister": appointed_minister,
            "registered_minister": registered_minister,
            "displaced_minister": displaced_minister,
            "secret_order_id": secret_order_id or 0,
            "pending_action_id": pending_action_id or 0,
            "directives": [self.directive_payload(row) for row in self.directive_rows()],
            "pending_count": self.session.pending_count(),
            "suggestions": self.suggestions_for(character),
            "can_undo_last_chat": self.can_undo_last_chat(minister_name),
        }

    def chat(self, minister_name: str, message: str) -> Dict[str, Any]:
        if minister_name not in self.content.characters and minister_name not in self.session.temporary_characters:
            raise HTTPException(status_code=404, detail=f"未找到大臣：{minister_name}")
        text = message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="问话不能为空。")
        with self._runtime_write_gate():
            if self._audience_turn_in_flight(minister_name):
                raise HTTPException(status_code=409, detail=f"{minister_name}上一轮回奏仍在进行，请稍候再问。")
            accepted_turn = int(self.state.turn)
            chat_turn_id = 0
            before_snapshot: Dict[str, Any] = {}
            if self._persistent_chat_minister(minister_name):
                chat_turn_id, before_snapshot = self._start_chat_turn(minister_name)
            self.chat_history.setdefault(minister_name, []).append({"role": "user", "content": text})
            if minister_name not in self.session.temporary_characters:
                message_id = self.db.append_chat_message(minister_name, accepted_turn, "user", text)
                if chat_turn_id:
                    self.db.update_chat_turn_messages(chat_turn_id, user_message_id=message_id)
            try:
                result = self.session.chat(minister_name, text)
                proposed = None
                if result.proposed_directive is not None:
                    d = result.proposed_directive
                    proposed = {"id": d.id, "text": d.text, "status": d.status, "notes": d.notes}
                # _chat_payload 持久化 minister 消息 + 更新 chat_turn——纳入失败 guard 覆盖范围，
                # 若它失败也干净回滚，不留孤儿轮（#399 cmr R1 coderabbit Major）。
                payload = self._chat_payload(
                    minister_name, result.answer,
                    court_action=result.court_action, next_minister=result.next_minister,
                    proposed_directive=proposed, appointed_minister=result.appointed_minister,
                    registered_minister=result.registered_minister,
                    displaced_minister=result.displaced_minister,
                    secret_order_id=result.secret_order_id,
                    pending_action_id=getattr(result, "pending_action_id", 0),
                    chat_turn_id=chat_turn_id,
                    accepted_turn=accepted_turn,
                )
                self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                return payload
            except Exception:
                if chat_turn_id:
                    self._record_chat_rollback_items(chat_turn_id, before_snapshot)
                    self.db.fail_chat_turn(chat_turn_id)
                    self.chat_history = {name: [] for name in self.session.content.characters}
                    for name, msgs in self.db.load_all_chat_history().items():
                        self.chat_history.setdefault(name, []).extend(msgs)
                raise

    def _chat_stream_payload(
        self,
        minister_name: str,
        text: str,
        chat_turn_id: int,
        before_snapshot: Dict[str, Any],
        accepted_turn: int,
        emit_delta,
    ) -> Dict[str, Any]:
        character = self.session._character(minister_name)
        chunks: List[str] = []
        agent = self.session.registry.get(character)
        action_intent_future = self.session._start_cli_action_intent(character, text)
        run_output = None
        stream = agent.run(text, stream=True, stream_events=True, yield_run_output=True)
        for event in stream:
            content = getattr(event, "content", None)
            event_name = getattr(event, "event", "")
            if event_name == "RunContent" and content:
                delta = str(content)
                chunks.append(delta)
                emit_delta(delta)
            if type(event).__name__ in ("RunOutput", "RunCompletedEvent"):
                run_output = event
        # 流式跑完补 dump：流式 run_output(RunCompletedEvent)常无 .messages，
        # 传 agent= 让 _dump_llm_messages 走 agent.get_last_run_output() fallback 取 system/user。
        _dump_llm_messages(run_output, f"大臣对话/{minister_name}", agent=agent)
        answer = "".join(chunks).strip()
        fail_if_llm_error(answer, "LLM 调用")
        if not answer and run_output is not None:
            answer = extract_agent_text(run_output)
        if not answer:
            raise LLMUnavailable("LLM 调用失败：流式回复为空。")
        # 截 propose_directive：入 pending_actions；截 propose_appointment：吏部铨选建档
        proposed = None
        appointed = ""
        registered = ""
        court_action = ""
        next_minister = ""
        displaced = ""
        secret_order_id = 0
        pending_action_id = 0
        if run_output is not None:
            for tool_exec in getattr(run_output, "tools", None) or []:
                res = str(getattr(tool_exec, "result", "") or "")
                tool_name = getattr(tool_exec, "tool_name", "")
                if tool_name == "propose_directive" or res.startswith("__pending_directive__"):
                    draft_text = res.removeprefix("__pending_directive__").strip()
                    if not draft_text:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        draft_text = (args.get("decree_text") or "").strip()
                    if draft_text and GameSession._proposal_blocked(self.state):
                        draft_text = ""  # 恢复窗婉拒（ship-pre r2 软死锁环源头，同 session 路）
                    if draft_text:
                        pending_action_id = self.db.upsert_pending_directive(
                            self.state.turn, character.name,
                            payload={"text": draft_text, "actor": character.name},
                        )
                elif tool_name == "propose_appointment" or res.startswith("__pending_appointment__"):
                    payload_json = res.removeprefix("__pending_appointment__").strip()
                    if not payload_json:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        payload_json = json.dumps(args, ensure_ascii=False)
                    appointed, displaced = self.session._apply_appointment(payload_json, character)
                elif tool_name == "register_unlisted_person" or res.startswith("__pending_unlisted_person__"):
                    payload_json = res.removeprefix("__pending_unlisted_person__").strip()
                    if not payload_json:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        payload_json = json.dumps(args, ensure_ascii=False)
                    registered, summon_after = self.session._apply_unlisted_person_registration(payload_json)
                    if registered and summon_after:
                        court_action = "summon"
                        next_minister = registered
                elif tool_name == "summon_minister" or res.startswith("__summon__"):
                    target_name = res.removeprefix("__summon__").strip()
                    if not target_name:
                        args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                        target_name = args.get("name", "")
                    if target_name:
                        try:
                            target, _is_temporary = self.session.summon_character(
                                target_name, character, allow_temporary=False
                            )
                        except ValueError:
                            target = None
                        if target is not None:
                            ok, _reason = self.session.can_summon(target)
                            if ok:
                                court_action = "summon"
                                next_minister = target.name
                elif tool_name == "dismiss_minister" or res == "__dismiss__":
                    court_action = "dismiss"
                elif tool_name == "issue_secret_order" or res.startswith("__secret_order_registered__") or res.startswith("__secret_order__"):
                    if res.startswith("__secret_order_registered__"):
                        try:
                            registered_id = int(res.split("__")[3])
                        except Exception:
                            registered_id = 0
                        if registered_id:
                            pending_action_id = self.session._stage_legacy_registered_secret_order(
                                registered_id, character.name)
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
                            pending_action_id = self.db.stage_pending_action(
                                self.state.turn, kind="secret_order", action="新建",
                                minister_name=character.name, target_id=None,
                                payload={
                                    "title": str(payload.get("title") or "").strip(),
                                    "content": str(payload.get("content") or "").strip(),
                                    "assignee": str(payload.get("assignee") or character.name).strip(),
                                    "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
                                    "deadline_months": payload.get("deadline_months") or 0,
                                },
                            )
                # 密令结案不再走大臣工具，由月末推演 + extractor 写入
        # CLI 后端（agy/codex）：玩家用拟旨/密令按钮（消息带前缀）时，把大臣这句回话原文入档。
        # CLI 后端会话落地走共享真源 session.apply_cli_conversation_actions(同 session.chat 非流式路径)，
        # 杜绝 web/CLI 两边逻辑漂移（CMR F3 / codexC-1）。
        res = self.session.apply_cli_conversation_actions(
            character, text, answer,
            has_directive=proposed is not None or bool(pending_action_id),
            secret_order_id=secret_order_id,
            preclassified_intent=self.session._finish_cli_action_intent(action_intent_future),
        )
        if proposed is None and res["directive"]:
            proposed = res["directive"]
        if res["secret_order_id"]:
            secret_order_id = res["secret_order_id"]
        pending_action_id = pending_action_id or int(res.get("pending_action_id") or 0)
        self._record_chat_rollback_items(chat_turn_id, before_snapshot)
        return self._chat_payload(
            minister_name, answer, court_action=court_action, next_minister=next_minister,
            proposed_directive=proposed, appointed_minister=appointed,
            registered_minister=registered,
            displaced_minister=displaced,
            secret_order_id=secret_order_id,
            pending_action_id=pending_action_id,
            chat_turn_id=chat_turn_id,
            accepted_turn=accepted_turn,
        )

    def chat_stream(self, minister_name: str, message: str) -> Iterator[Dict[str, Any]]:
        if minister_name not in self.content.characters and minister_name not in self.session.temporary_characters:
            yield {"type": "error", "message": f"未找到大臣：{minister_name}"}
            return
        text = message.strip()
        if not text:
            yield {"type": "error", "message": "问话不能为空。"}
            return
        if not self._mark_pending_write():
            yield {"type": "error", "message": "当前会话正在关闭，请回菜单重新进入。"}
            return
        write_gate = self._runtime_write_gate()
        write_gate.acquire()
        gate_released = False
        chat_turn_id = 0
        before_snapshot: Dict[str, Any] = {}
        try:
            if self._audience_turn_in_flight(minister_name):
                write_gate.release()
                gate_released = True
                self._complete_pending_write()
                yield {"type": "error", "message": f"{minister_name}上一轮回奏仍在进行，请稍候再问。"}
                return
            accepted_turn = int(self.state.turn)
            if self._persistent_chat_minister(minister_name):
                chat_turn_id, before_snapshot = self._start_chat_turn(minister_name)
            self.chat_history.setdefault(minister_name, []).append({"role": "user", "content": text})
            if minister_name not in self.session.temporary_characters:
                message_id = self.db.append_chat_message(minister_name, accepted_turn, "user", text)
                if chat_turn_id:
                    self.db.update_chat_turn_messages(chat_turn_id, user_message_id=message_id)
        except Exception:
            # 已建 chat_turn 但 prologue 写途中崩 → 必须失败该轮，否则留下 active 且无大臣回复的
            # 孤儿轮，_audience_turn_in_flight 会永久挡住该大臣（cmr Gate2 F-B）。
            # R3 self-check: _fail_chat_turn_and_reload 自身可能再抛（DB 已坏）——必须吞掉，
            # 否则 write_gate 与 _pending_writes_count 泄漏，drain 永久挂起、所有写入被永久挡。
            try:
                self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
            except Exception:
                pass
            if not gate_released:
                write_gate.release()
                gate_released = True
            self._complete_pending_write()
            raise

        ev_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

        def emit_delta(delta: str) -> None:
            ev_queue.put({"type": "delta", "content": delta})

        def worker() -> None:
            nonlocal gate_released
            try:
                payload = self._chat_stream_payload(
                    minister_name, text, chat_turn_id, before_snapshot, accepted_turn, emit_delta)
                ev_queue.put({"type": "done", "payload": payload})
            except Exception as error:  # noqa: BLE001
                # R3 self-check: _fail_chat_turn_and_reload 自身可能再抛（DB 已坏）——必须吞掉，
                # 否则 error 事件不会被投进 queue、消费者永久挂死（finally 只保 gate/counter 释放）。
                try:
                    self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
                except Exception:
                    pass
                if isinstance(error, LLMUnavailable):
                    ev_queue.put({"type": "error", "detail": _llm_error_detail(error)})
                else:
                    ev_queue.put({"type": "error", "message": str(error)})
            finally:
                if not gate_released:
                    write_gate.release()
                    gate_released = True
                self._complete_pending_write()

        thread = threading.Thread(target=worker, daemon=True)
        try:
            thread.start()
        except Exception:
            # worker 没起来 → prologue 已建的 chat_turn 不会有 worker 去失败它，须就地善后，
            # 否则同样留下孤儿轮永久挡该大臣（cmr Gate2 F-B）。
            # R3 self-check: 同 prologue except——_fail_chat_turn_and_reload 自身再抛时也须释放锁与计数。
            try:
                self._fail_chat_turn_and_reload(chat_turn_id, before_snapshot)
            except Exception:
                pass
            if not gate_released:
                write_gate.release()
                gate_released = True
            self._complete_pending_write()
            raise
        while True:
            item = ev_queue.get()
            yield item
            if item.get("type") in {"done", "error"}:
                break

    def suggestions_for(self, character: Character) -> List[Dict[str, str]]:
        suggestions = [
            {"label": "问在办事项", "text": "当前在办的事项里，哪几件轻重缓急最该先理？"},
            {"label": "问阻力", "text": "眼下推进朝政，最大的阻力来自哪一方？"},
            {"label": "拟旨", "text": "拟旨如下：", "prefix": True},
            {"label": "下密令", "text": "密令如下：", "prefix": True},
        ]
        skill_ids = set(available_skill_ids(character, self.db))
        if "check_treasury" in skill_ids:
            suggestions.insert(1, {"label": "查钱粮", "text": "太仓和内库实数如何？本月哪些钱最急？"})
        if "check_military" in skill_ids or "front_line_plan" in skill_ids or "strategic_review" in skill_ids:
            suggestions.insert(1, {"label": "查驻军", "text": "查一下关宁军、京营和陕西边军的士气、欠饷与补给。"})
        if "secret_investigation" in skill_ids:
            suggestions.insert(1, {"label": "密查", "text": "哪些账册和人物最该先密查？"})
        return suggestions[:6]


def sse_event(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _next_or_none(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _game_write_gate(game) -> threading.Lock:
    if hasattr(game, "_runtime_write_gate"):
        return game._runtime_write_gate()
    gate = getattr(game, "_write_gate", None)
    if gate is None:
        gate = threading.Lock()
        setattr(game, "_write_gate", gate)
    return gate


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
    state = getattr(game, "state", None)
    if getattr(state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
        raise HTTPException(status_code=409, detail="月末结算进行中，请待结算完成后再操作。")
    gate = _game_write_gate(game)
    if not gate.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="月末结算或上一步写入进行中，请稍候再操作。")
    try:
        yield
    finally:
        gate.release()


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
    """等在途后台写入（召对 worker / 结算 worker）排空 write_gate 后再关连接。

    #396：菜单生命周期端点（exit_to_menu / new_game / shutdown）不再在 write_gate 被
    持时直接 session.close()——否则后台 worker 崩在 closed database（#382 连接级并发）。
    exit_to_menu 立刻清 web_game 并返回，连接在后台 daemon 线程延后关（detach）；
    new_game 先把旧库 park 旁路、再立刻建新局（零等待）；排空后关连接并把旁路库归档为存档；
    shutdown await 排空后再杀进程。不挂 #382 大设计，仅用现有 write_gate 队列续跑再关。
    """
    # #396 Gap B: 先等所有排队等 gate 的旧召对 worker 跑完（counter→0）再抢 gate——
    # 否则只等当前持锁者，drain 抢下一轮 acquire 后关 session，排队的 worker 永不跑或写 closed DB。
    cond = getattr(game, "_drain_cond", None)
    if cond is not None:
        with cond:
            setattr(game, "_draining", True)
            while getattr(game, "_pending_writes_count", 0) > 0:
                cond.wait()
    gate = _game_write_gate(game)
    gate.acquire()  # 阻塞——等最后一个 worker 释放
    close_failed = False
    try:
        session = getattr(game, "session", None)
        if session is not None:
            session.close()
    except Exception:
        close_failed = True
    finally:
        gate.release()
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
    from ming_sim.cli_backend import cli_backend_from_env, cli_model_choices, is_supported_cli_runner
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
        "game_settings": load_runtime_game(),
        "llm": {
            "channel": channel,
            "base_url": base_url,
            "model": model,
            "has_api_key": has_api_key,
            "cli_runner": cli_runner,
            "cli_model": cli_model,
            "cli_model_saved": cli_model_saved,
            "cli_model_choices": cli_model_choices(),
            "cli_timeout_seconds": cli_timeout,
            "reasoning_strength": reasoning_strength,
            "api_reasoning_strength": api_reasoning_strength,
            "cli_reasoning_strength": cli_reasoning_strength,
            "reasoning_supported": reasoning_supported,
            "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
            "max_tokens": int(runtime.get("max_tokens") or API_DEFAULT_MAX_TOKENS),
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
    global web_game
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
async def api_menu_continue() -> Dict[str, Any]:
    """继续：用上次主 DB 启动 WebGame。"""
    global web_game
    if not _has_main_db():
        raise HTTPException(status_code=404, detail="无上次进度可继续，请先新游戏或加载存档。")
    try:
        web_game = WebGame(fresh=False)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=412, detail=_llm_error_detail(exc))
    return {"state": web_game.state_payload()}


@app.post("/api/menu/load_save/{name}")
async def api_menu_load_save(name: str) -> Dict[str, Any]:
    """从存档启动：先启动空 WebGame（fresh）→ 调 load_save 热替换主 DB。"""
    global web_game
    try:
        web_game = WebGame(fresh=False)  # 先有 session 才能 load_save
    except LLMUnavailable as exc:
        raise HTTPException(status_code=412, detail=_llm_error_detail(exc))
    web_game.load_save(name)
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
    global web_game
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
    max_tokens: int = API_DEFAULT_MAX_TOKENS
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
    max_tokens = request.max_tokens if request.max_tokens > 0 else API_DEFAULT_MAX_TOKENS
    timeout_seconds = request.timeout_seconds if request.timeout_seconds > 0 else API_DEFAULT_TIMEOUT_SECONDS
    if not cli_runner:
        raise HTTPException(status_code=400, detail="cli_runner 不能为空。")
    config = LLMConfig(
        api_key="",  # CLI 通道不要 API key；占位符在 create_chat_model 构造 CliChat 时注入
        base_url="",
        model=cli_model,
        max_tokens=max_tokens,
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
        max_tokens,
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
    max_tokens = request.max_tokens if request.max_tokens > 0 else API_DEFAULT_MAX_TOKENS
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
        max_tokens=max_tokens,
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
        max_tokens,
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
            "max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "thinking_level": thinking_level,
            "advanced_model": advanced_model,
            "advanced_base_url": advanced_base_url,
            "has_advanced_api_key": _has_real_api_key(advanced_api_key),
            "advanced_thinking_level": "",
            "reasoning_strength": reasoning_strength,
        },
    }


class GameSettingsRequest(BaseModel):
    # HITL 每回合最少决策点数，0-5。0=不强制（宁缺毋滥）。
    hitl_min_decisions: int = 1


@app.get("/api/menu/game_settings")
async def api_menu_game_settings() -> Dict[str, Any]:
    """读全局玩法设置。"""
    return {"game_settings": load_runtime_game()}


@app.post("/api/menu/game_settings")
async def api_menu_save_game_settings(request: GameSettingsRequest) -> Dict[str, Any]:
    """保存全局玩法设置（runtime_game.json）。立即对下一回合推演生效。"""
    saved = save_runtime_game(request.hitl_min_decisions)
    return {"ok": True, "game_settings": saved}


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
    """列出密令。status 为空返回全部，否则按 active/done/failed 过滤。"""
    orders = get_game().db.list_secret_orders(status=status or None)
    return {"orders": orders}


@app.get("/api/pending_actions")
async def api_pending_actions() -> Dict[str, Any]:
    """列出本回合待确认动作(动作闸门 ADR 0006):皇帝复核区,颁诏批量落库前可见可撤。"""
    game = get_game()
    return {"actions": game.db.list_pending_actions(int(game.state.turn))}


@app.post("/api/pending_actions/{action_id}/withdraw")
async def api_withdraw_pending_action(action_id: int) -> Dict[str, Any]:
    """皇帝撤回一条尚未颁诏落库的暂存动作。不存在→404;存在但已落库/非本回合→409。
    先原子条件 DELETE(以删成功为真源,免 check-then-act 竞态,pr-loop sourcery),
    失败再查行分流 404/409。"""
    game = get_game()
    with _serialized_web_write(game):
        if game.db.withdraw_pending_action(int(action_id), int(game.state.turn)):
            return {"withdrawn": action_id, "actions": game.db.list_pending_actions(int(game.state.turn))}
    # 删不动:查清是不存在还是已落库/非本回合
    row = game.db.conn.execute(
        "SELECT turn, status FROM pending_actions WHERE id=?", (int(action_id),)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="该待确认动作不存在。")
    raise HTTPException(status_code=409, detail="该动作已落库或非本回合，无法撤回。")


@app.get("/api/turn_extraction")
async def api_turn_extraction(turn: int = -1) -> Dict[str, Any]:
    """读 turn_extractions：默认上一回合（state.turn-1，因 resolve 已 next_period）。"""
    if turn < 0:
        turn = max(1, int(get_game().state.turn) - 1)
    data = get_game().db.get_turn_extraction(turn)
    if data is None:
        return {"turn": turn, "exists": False}
    data["exists"] = True
    return data


@app.get("/api/history/turns")
async def api_history_turns() -> Dict[str, Any]:
    """已存档回合列表（turn_reports / turn_extractions / 已颁诏 turn_directives 并集）。"""
    return {"turns": get_game().db.list_archived_turns()}


@app.get("/api/history/turn/{turn}")
async def api_history_turn(turn: int) -> Dict[str, Any]:
    """某回合历史聚合：邸报奏报 + 诏书 + 已颁草案 + extractor 输入/输出。"""
    db = get_game().db
    report = db.get_turn_report(turn)
    extraction = db.get_turn_extraction(turn)
    directives = db.list_directives_by_turn(turn)
    if not report and extraction is None and not directives:
        return {"turn": turn, "exists": False}
    decree_text = ""
    if extraction is not None:
        decree_text = str(extraction.get("decree_text") or "")
        extraction["exists"] = True
    return {
        "turn": turn,
        "exists": True,
        "year": extraction["year"] if extraction else (directives[0]["year"] if directives else 0),
        "period": extraction["period"] if extraction else (directives[0]["period"] if directives else 0),
        "report": report,
        "decree_text": decree_text,
        "directives": directives,
        "extraction": extraction,
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
    "active": "在朝", "offstage": "尚未登场", "dead": "已殁", "dismissed": "已罢黜",
    "imprisoned": "下狱", "exiled": "流放", "retired": "致仕",
}


def _require_active_minister(minister_name: str) -> None:
    if minister_name in get_game().session.temporary_characters:
        return
    if minister_name not in get_game().content.characters:
        raise HTTPException(status_code=404, detail=f"未找到人物：{minister_name}")
    character = get_game().content.characters[minister_name]
    # 宗藩（就藩藩王）已被 visible_in_court 挡出朝堂/任免列表，但 /chat 端点须同步拒绝，
    # 否则可绕列表直接按名经 API 召对（用户 2026-06-14 拍：宗室不可召见）。后宫不在此拒——
    # 嫔妃 chat 复用本端点，加 后宫 会误伤选妃后的召对路径。
    if is_vassal_prince(character):
        raise HTTPException(status_code=409, detail=f"{minister_name}为就藩宗室，非朝廷命官，无法召见。")
    if get_game().character_power_id(character) != "ming":
        raise HTTPException(status_code=409, detail=f"{minister_name}不属大明朝廷，无法召见。")
    status, reason = get_game().db.get_character_status(minister_name)
    if status != "active":
        label = _STATUS_LABEL_WEB.get(status, status)
        detail = f"{minister_name}已{label}，无法召见。" + (reason or "")
        raise HTTPException(status_code=409, detail=detail.strip())


@app.get("/api/ministers/{minister_name}/chat")
async def api_chat_history(minister_name: str) -> Dict[str, Any]:
    _require_active_minister(minister_name)
    character = get_game().session._character(minister_name)
    return {
        "minister": get_game().public_character(character),
        "history": get_game().chat_history.get(minister_name, []),
        "suggestions": get_game().suggestions_for(character),
        "can_undo_last_chat": get_game().can_undo_last_chat(minister_name),
    }


@app.post("/api/ministers/{minister_name}/secret_order")
async def api_create_secret_order(minister_name: str, request: SecretOrderRequest) -> Dict[str, Any]:
    """皇帝直接下达密令，不经 LLM，直接落库。"""
    game = get_game()
    character = game.session.content.characters.get(minister_name)
    if not character:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"未找到大臣：{minister_name}")
    if is_vassal_prince(character):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=f"{minister_name}为就藩宗室，非朝廷命官，无法下达密令。")
    if game.character_power_id(character) != "ming":
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=f"{minister_name}不属大明朝廷，无法下达密令。")
    title = request.title.strip()[:20]
    content = request.content.strip()
    if not title or not content:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="title 和 content 不能为空")
    # 直接下达=显式新建一道密令（create，非 upsert）：皇帝点「下密令」按钮给确切 title+content
    # 就是要一道新令，同大臣可有多条 active；upsert 会静默覆盖最新 active 那条（codexC-2）。
    # 「更新已有密令」走会话路径(LLM 判意图 → update_secret_order_by_id 精确改)，不在此端点。
    with _serialized_web_write(game):
        order_id = game.db.create_secret_order(
            game.session.state, minister_name, title, content, request.tags, deadline_months=request.deadline_months
        )
        # registry.refresh 也留在门内：否则提前释放锁后留下 DB 已建密令、内存 agent 上下文仍旧
        # 的撕裂窗口（cmr Gate2 r3 Finding2，同 consort/admin 那类 DB/内存撕裂）。
        if game.session.registry is not None:
            game.session.registry.refresh(minister_name)  # 上下文带上最新密令
    print(f"[secret_order/api] 新建 minister={minister_name} title={title!r} id={order_id}")
    return {"order_id": order_id, "minister_name": minister_name, "title": title, "status": "active"}


@app.post("/api/ministers/{minister_name}/chat")
async def api_chat(minister_name: str, request: ChatRequest) -> Dict[str, Any]:
    _require_active_minister(minister_name)
    return get_game().chat(minister_name, request.message)


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
        iterator = iter(get_game().chat_stream(minister_name, request.message))
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, _next_or_none, iterator)
            if item is None:
                break
            item_type = str(item.get("type", "message"))
            if item_type == "delta":
                yield sse_event("delta", {"content": item.get("content", "")})
            elif item_type == "done":
                yield sse_event("done", item.get("payload", {}))
                break
            elif item_type == "error":
                yield sse_event("error", item.get("detail") or {"message": item.get("message", "流式回复失败。")})
                break

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/directives")
async def api_create_directive(request: DirectiveRequest) -> Dict[str, Any]:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="指令内容不能为空。")
    game = get_game()
    try:
        # 会话层 _refuse_if_settling 仅查相位，守不住 pre_settle 原子块在 settling 落定前的窗口；
        # 与直写端点同走 _serialized_web_write 抢 _write_gate（cmr Gate2 F-A 残面：会话写也要串行）。
        with _serialized_web_write(game):
            dv = game.session.add_directive(request.text.strip(), notes=request.notes)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None  # 恢复窗冻结指引
    return {
        "directive": {"id": dv.id, "text": dv.text, "status": dv.status},
        "directives": [game.directive_payload(item) for item in game.directive_rows()],
    }


@app.patch("/api/directives/{directive_id}")
async def api_update_directive(directive_id: int, request: DirectivePatch) -> Dict[str, Any]:
    rows = get_game().directive_rows()
    row = next((item for item in rows if int(item["id"]) == directive_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到草案。")
    text = request.text if request.text is not None else str(row["text"])
    if not text.strip():
        raise HTTPException(status_code=400, detail="指令内容不能为空。")
    game = get_game()
    try:
        with _serialized_web_write(game):
            game.session.update_directive(directive_id, text.strip())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
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


@app.post("/api/directives/{directive_id}/confirm")
async def api_confirm_directive(directive_id: int) -> Dict[str, Any]:
    """大臣拟旨经皇帝核定：pending → draft。"""
    game = get_game()
    try:
        with _serialized_web_write(game):
            game.session.confirm_directive(directive_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {
        "directives": [game.directive_payload(item) for item in game.directive_rows()],
        "pending_count": game.session.pending_count(),
    }


@app.post("/api/directives/{directive_id}/reject")
async def api_reject_directive(directive_id: int) -> Dict[str, Any]:
    """皇帝驳回大臣拟旨：pending → rejected。"""
    game = get_game()
    try:
        with _serialized_web_write(game):
            game.session.reject_directive(directive_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {
        "directives": [game.directive_payload(item) for item in game.directive_rows()],
        "pending_count": game.session.pending_count(),
    }


@app.post("/api/decree/write")
async def api_write_decree() -> Dict[str, Any]:
    game = get_game()
    try:
        # write_decree 先 commit_pending_actions（真 DB 写）再润色——DB 写同样不能骑进结算
        # pre_settle 原子窗口；走 _serialized_web_write 抢 _write_gate（cmr Gate2 F-A 残面）。
        with _serialized_web_write(game):
            decree = game.session.write_decree()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {"decree": decree}


class EditDecreeRequest(BaseModel):
    decree: str


@app.patch("/api/decree")
async def api_edit_decree(body: EditDecreeRequest) -> Dict[str, Any]:
    """皇帝手动改定诏书正文（拟诏后、颁诏前）。"""
    game = get_game()
    try:
        # set_decree 改 in-memory last_decree（结算读它）；与会话写同走串行门，避免在结算冻结
        # 窗口里改诏书正文（cmr Gate2 F-A 残面 / Finding2 冻结窗一致性）。
        with _serialized_web_write(game):
            decree = game.session.set_decree(body.decree)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {"decree": decree}


class IssueDecreeRequest(BaseModel):
    # 作弊控制台（Ctrl+~）下的强制结算项；一次性，颁诏即用。普通颁诏留空。
    cheat: str = ""


@app.post("/api/decree/issue")
async def api_issue_decree(body: IssueDecreeRequest = IssueDecreeRequest()) -> Dict[str, Any]:
    """非流式颁诏（保留兼容）。前端默认走 /api/decree/issue/stream。"""
    game = get_game()
    was_ended = bool(game.state.ended)
    try:
        with _game_write_gate(game):
            result = game.session.resolve_turn(cheat_directive=body.cheat)
            decree = game.session.last_decree
            if result.awaiting:
                # 决策点暂停：回合未结算，返回决策点让前端弹窗；不刷新、不计 steam。
                return {"decree": decree, "awaiting_decision": True,
                        "decisions": result.decisions, "state": game.state_payload()}
            report = result.report
            game.refresh_turn()
            events = [
                steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                steam_events.set_stat(steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn)),
            ]
            if not was_ended and game.state.ended:
                events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
            return steam_events.with_events({"decree": decree, "report": report, "state": game.state_payload()}, events)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except SettlementAbort as e:
        # 结算中止（ADR 0008 决定 6/7）：进度已保存可重试，detail 即玩家指引
        # （含错误包路径+「请发给作者」）。非 500——这是已处理的可重试态，不是服务器 bug。
        raise HTTPException(status_code=409, detail=str(e)) from None


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
        try:
            game = get_game()
            was_ended = bool(game.state.ended)
            with _game_write_gate(game):
                result = game.session.resolve_turn(on_event=on_event, cheat_directive=body.cheat)
                decree = game.session.last_decree
                if result.awaiting:
                    # 决策点暂停：邸报已流式推完，再推 decisions 让前端弹窗；本回合未结算、不刷新、不计 steam。
                    ev_queue.put(("__decisions__", {
                        "decree": decree,
                        "decisions": result.decisions,
                        "state": game.state_payload(),
                    }))
                    return
                report = result.report
                game.refresh_turn()
                events = [
                    steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                    steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                    steam_events.set_stat(steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn)),
                ]
                if not was_ended and game.state.ended:
                    events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
                ev_queue.put(("__done__", {
                    "decree": decree,
                    "report": report,
                    "state": game.state_payload(),
                    "steam_events": events,
                }))
        except ValueError as e:
            ev_queue.put(("__error__", str(e)))
        except Exception as e:  # noqa: BLE001
            ev_queue.put(("__error__", _llm_error_detail(e) if isinstance(e, LLMUnavailable) else str(e)))

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
    # 皇帝亲裁结果：按决策点 idx 顺序，每项 {label, hint?, note?}。
    choices: List[Dict[str, Any]] = []
    cheat: str = ""


@app.post("/api/decree/resolve_decisions/stream")
async def api_resolve_decisions_stream(body: ResolveDecisionsRequest) -> StreamingResponse:
    """皇帝亲裁完决策点，流式跑 phase2 结算（extractor→落库→结局）。
    与 issue/stream 同结构：worker 跑 submit_decisions，SSE 推 stage/text + done。"""
    ev_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()

    def on_event(kind: str, data: str) -> None:
        ev_queue.put((kind, data))

    def worker() -> None:
        try:
            game = get_game()
            was_ended = bool(game.state.ended)
            with _game_write_gate(game):
                report = game.session.submit_decisions(
                    body.choices, on_event=on_event, cheat_directive=body.cheat
                )
                decree = game.session.last_decree
                game.refresh_turn()
                events = [
                    steam_events.add_stat(steam_events.STAT_DECREES_ISSUED),
                    steam_events.add_stat(steam_events.STAT_TURNS_PLAYED),
                    steam_events.set_stat(steam_events.STAT_MAX_TURN_REACHED, int(game.state.turn)),
                ]
                if not was_ended and game.state.ended:
                    events.append(steam_events.add_stat(steam_events.STAT_ENDINGS_REACHED))
                ev_queue.put(("__done__", {
                    "decree": decree,
                    "report": report,
                    "state": game.state_payload(),
                    "steam_events": events,
                }))
        except ValueError as e:
            ev_queue.put(("__error__", str(e)))
        except Exception as e:  # noqa: BLE001
            ev_queue.put(("__error__", _llm_error_detail(e) if isinstance(e, LLMUnavailable) else str(e)))

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
    max_tokens: int = 0
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
    with _serialized_web_write(game):
        game.load_save(name)
    return {"state": get_game().state_payload()}


@app.post("/api/game/reset")
async def api_reset_game() -> Dict[str, Any]:
    """清空主 DB 重开新局。存档目录保留。"""
    # reset_game 关连接 + 删 sqlite 文件 + 重建——同 load_save，正持锁的 worker 会崩在关连接上。
    # 非阻塞抢 _write_gate：忙时 409（cmr Gate2 r5；强制中断在途属 #382）。
    game = get_game()
    with _serialized_web_write(game):
        game.reset_game()
    return steam_events.with_events(
        {"state": get_game().state_payload()},
        [steam_events.add_stat(steam_events.STAT_RUNS_STARTED)],
    )


@app.get("/api/llm/config")
async def api_get_llm_config() -> Dict[str, Any]:
    """读当前生效的 LLM 配置。api_key 不回传明文，只回是否已设置。"""
    from ming_sim.cli_backend import cli_model_choices
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
        "max_tokens": cfg.max_tokens,
        "timeout_seconds": cfg.timeout_seconds,
        "thinking_level": cfg.thinking_level,
        "reasoning_strength": cfg.reasoning_strength,
        "reasoning_supported": reasoning_supported,
        "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
        "advanced_model": cfg.advanced_model,
        "advanced_base_url": cfg.advanced_base_url,
        "has_advanced_api_key": _has_real_api_key(cfg.advanced_api_key),
        "advanced_thinking_level": "",
        "has_api_key": _has_real_api_key(cfg.api_key),
        "cli_runner": cfg.cli_runner,
        "cli_model": cfg.cli_model,
        "cli_model_choices": cli_model_choices(),
        "cli_timeout_seconds": cfg.cli_timeout_seconds,
        "persisted": {
            "channel": saved.get("channel", ""),
            "base_url": saved.get("base_url", ""),
            "model": saved.get("model", ""),
            "has_api_key": _has_real_api_key(saved.get("api_key", "")),
            "max_tokens": int(saved.get("max_tokens") or API_DEFAULT_MAX_TOKENS),
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
            request.max_tokens,
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
        "max_tokens": cfg.max_tokens,
        "timeout_seconds": cfg.timeout_seconds,
        "thinking_level": cfg.thinking_level,
        "reasoning_strength": cfg.reasoning_strength,
        "reasoning_supported": reasoning_supported,
        "reasoning_strengths": list(REASONING_STRENGTH_CHOICES),
        "advanced_model": cfg.advanced_model,
        "advanced_base_url": cfg.advanced_base_url,
        "has_advanced_api_key": _has_real_api_key(cfg.advanced_api_key),
        "advanced_thinking_level": "",
        "has_api_key": _has_real_api_key(cfg.api_key),
        "channel": cfg.channel,
        "cli_runner": cfg.cli_runner,
        "cli_model": cfg.cli_model,
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
