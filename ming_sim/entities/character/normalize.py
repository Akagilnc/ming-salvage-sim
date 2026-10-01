"""人物变更流的单一规范化口（#1835 F1：旧四键兼容层随声明契约收敛退出）。

ADR 0009 决定 11 保留的旧键翻译层（appointments / character_status_changes /
character_power_changes / office_changes → 人物变更）曾只为「历史 delta 与
ready=1 重试真源」服务；#1846 起不再持久化 ready=1 extractor delta、恢复真源是
暂存声明与落账相位，那层兼容失去存在理由，已随 C0 声明契约退役：声明层与领域
核算层都只认 ``人物变更`` 一条流，旧键由 ``sanitize_delta_shape`` 按 ADR 0015
逐段拒收留痕，不再静默翻译。
"""

from __future__ import annotations

from typing import List, Mapping


PERSON_CHANGE_KEY = "人物变更"
ACTION_KEY = "动作"


def normalize_person_changes(extracted: Mapping[str, object]) -> List[dict]:
    """把声明/载荷里的 ``人物变更`` 归一成 ADR 0009 的人物变更项。

    - ``action`` 是 ``动作`` 的输入侧别名，同一项内二者同时在场时以显式
      ``动作`` 为准（不新增能力，只是同一闭集的两种写法归一）。
    - 非 Mapping 项不静默丢形状：调用方各自的 ADR 0015 逐项拒收口径负责留痕，
      本函数只负责「能进核算核的项」。
    """
    raw_items = extracted.get(PERSON_CHANGE_KEY)
    if not isinstance(raw_items, list) or not raw_items:
        return []
    normalized: List[dict] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        if "action" in entry and ACTION_KEY not in entry:
            entry[ACTION_KEY] = entry.pop("action")
        normalized.append(entry)
    return normalized
