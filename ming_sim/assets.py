"""资源加载与 JSON 校验辅助。L0 叶子模块。

只读 content/ 下设定文件；不持有任何全局态。
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from typing import Dict, List

from ming_sim.constants import CONTENT_DIR, MONEY_UNIT, TURN_UNIT, WRAP


def wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=WRAP, replace_whitespace=False))


def load_text_asset(relative_path: str) -> str:
    path = os.path.join(CONTENT_DIR, relative_path)
    try:
        with open(path, "r", encoding="utf-8") as file:
            text = file.read().strip()
    except OSError as error:
        raise SystemExit(f"设定文件缺失或不可读：{path} ({error})") from error
    return text.replace("{{TURN_UNIT}}", TURN_UNIT)


def load_json_asset(relative_path: str) -> object:
    path = os.path.join(CONTENT_DIR, relative_path)
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except OSError as error:
        raise SystemExit(f"设定文件缺失或不可读：{path} ({error})") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"设定文件 JSON 格式错误：{path} ({error})") from error


def strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if match:
        return match.group(1).strip()
    return text.strip()


# #1473：气泡头已有 speaker；LLM 偶发自署「XX叩答：」+ 空首行叠床架屋。
# 投影缝（历史 build_chat_projection / 夜卷 read_night_scroll）共用，钉历史与实时同形。
_REDUNDANT_CHAT_SPEAKER_VERB = r"(?:叩答|谨奏|奏曰|顿首|回奏)?"
_REDUNDANT_CHAT_SPEAKER_TAIL = rf"{_REDUNDANT_CHAT_SPEAKER_VERB}[：:]\s*(?:\n[ \t]*)*"


def strip_redundant_chat_speaker_prefix(content: str, speaker: str) -> str:
    """去掉与气泡头重复的领头人名前缀及紧随空行；正文中途提及不动。"""
    text = str(content or "")
    name = str(speaker or "").strip()
    if not text or not name:
        return text
    # 人名必须与 speaker 全等锚定（re.escape），禁非贪婪吞掉「叩答」动词。
    pat = re.compile(rf"^{re.escape(name)}{_REDUNDANT_CHAT_SPEAKER_TAIL}")
    match = pat.match(text)
    if match is None:
        return text
    return text[match.end():]


def format_money(value: int) -> str:
    return f"{value}{MONEY_UNIT}"


def format_money_delta(value: int) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{format_money(value)}"


def format_wanliang_amount(value: object) -> str:
    """奏报口吻的万两数额：收整为整数或一位小数，杜绝 IEEE 浮点残渣。

    军饷 shortfall 等中间量常为 float；f-string 原始插值会把
    1.2000000000000002 写进 army_logs.reason → previous_summary。
    """
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    rounded = round(amount, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}"


def require_dict(data: object, path: str) -> Dict[str, object]:
    if not isinstance(data, dict):
        raise SystemExit(f"设定文件应为 JSON object：content/{path}")
    return data


def require_list(data: object, path: str) -> List[object]:
    if not isinstance(data, list):
        raise SystemExit(f"设定文件应为 JSON array：content/{path}")
    return data


def string_list(value: object, path: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"设定字段应为字符串数组：{path}")
    return [str(item) for item in value]


def int_field(data: Dict[str, object], key: str, path: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"设定字段应为整数：{path}.{key}") from error


def str_field(data: Dict[str, object], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"设定字段应为非空字符串：{path}.{key}")
    return value.strip()
