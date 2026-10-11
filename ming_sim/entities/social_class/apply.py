"""实体记账原语。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB
from ming_sim.applier import RejectedItem, Provenance
from ming_sim.strict_types import strict_int as _strict_int


def _apply_class_dict(
    db: GameDB,
    class_delta: Dict[str, object],
    *,
    source: Provenance,
) -> Tuple[Dict[str, object], List[RejectedItem]]:
    """class_delta 结构：{ '农民@shaanxi': {'satisfaction': -5, 'leverage': +3}, '士绅': {...} }
    key 不带 @ 默认全国汇总。字段只接 satisfaction / leverage 增量。

    逐项拒收契约（ADR 0008 决定 1，#14/#63）：字段值非整数（含 bool/float）→
    invalid_enum 逐项拒收；查无此阶级名由 db.adjust_classes 返 missing_ref。
    #649 §1.4 升格：value 内出现 population 键 → 该 item 整项以 invalid_enum 拒收
    留痕（原为静默忽略；合法转移入口开通后，静默通道不得存活），其余 sat/lev 合法
    item 不受累——一切人口变化走 population_transfers 守恒原语。二级真值非 dict
    （如 {"农民": 0}）同样逐项拒收。
    返回 (已落 delta dict, 拒收项列表)：前者供 web 「阶级变化」面板，后者为
    canonical RejectedItem，由段适配器并入 SectionResult.rejected。
    """
    # #649 C3/C4：字段名先经 ITEM_FIELD_ALIASES 单一真源 canonical 化（满意→satisfaction、
    # 人口→population），使 population guard 对中英文拼写统一整项拒收，不在本层手抄别名分支。
    from ming_sim.simulation import _canonical_item_fields

    cleaned: Dict[str, Dict[str, int]] = {}
    rejected: List[RejectedItem] = []
    class_delta = class_delta if isinstance(class_delta, dict) else {}  # #117 同类：真值非 dict 守卫
    for key, fields in class_delta.items():
        if isinstance(fields, dict):
            fields = _canonical_item_fields(fields)
        if not isinstance(fields, dict):
            rejected.append(RejectedItem(item={str(key): fields}, reason=f"「{key}」阶级变化须为对象：{fields!r}", category="invalid_enum", source=source))
            continue
        if "population" in fields:
            rejected.append(RejectedItem(item={str(key): fields}, reason=f"「{key}」class_delta 无 population 更新面：写 population 整项拒收，"
                    "人口只经 population_transfers 守恒转移变动（#649/0087，单记录双写）", category="invalid_enum", source=source))
            continue
        entry: Dict[str, int] = {}
        for fname in ("satisfaction", "leverage"):
            raw = fields.get(fname)
            if raw is None:
                continue
            try:
                d = _strict_int(raw)
            except (TypeError, ValueError):
                rejected.append(RejectedItem(item={str(key): fields}, reason=f"「{key}」{fname} 值非整数：{raw!r}", category="invalid_enum", source=source))
                continue
            if d == 0:
                continue
            entry[fname] = d
        if entry:
            cleaned[str(key)] = entry
    if cleaned:
        # 同 faction：db 层未知名 missing_ref 拒收未写库，从 cleaned 剔除防面板误显（cmr r3 codex）。
        for _rej in db.adjust_classes(cleaned, commit=False, source=source):
            cleaned.pop(next(iter(_rej.item)), None)
            rejected.append(_rej)
    return cleaned, rejected
