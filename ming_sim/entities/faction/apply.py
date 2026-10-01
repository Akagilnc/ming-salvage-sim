"""实体记账原语。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB
from ming_sim.applier import RejectedItem, Provenance
from ming_sim.strict_types import strict_int as _strict_int


def _apply_faction_dict(
    db: GameDB,
    faction_delta: Dict[str, object],
    *,
    source: Provenance,
) -> Tuple[Dict[str, object], List[RejectedItem]]:
    """支持两种格式：
    - 旧格式：{"阉党": -10}  → 仅 satisfaction 增量
    - 新格式：{"阉党": {"satisfaction": -10, "leverage": -15}}

    逐项拒收契约（ADR 0008 决定 1，#14/#63）：satisfaction/leverage 值非整数（含
    bool/float，cmr r1 codex）→ invalid_enum 逐项拒收留痕（#14 模式 A，原 `continue`
    静默跳）；查无此派系名由 db.adjust_factions 返 missing_ref。
    返回 (已落 delta dict, 拒收项列表)：前者供 web 「派系变化」面板（形状不变），
    后者由落库编排器置于派系段的 RejectedItem 流，自动收进拒收报告。
    """
    cleaned: Dict[str, object] = {}
    rejected: List[RejectedItem] = []
    if not isinstance(faction_delta, dict):
        return {}, [RejectedItem(item={"raw_value": faction_delta}, reason="派系效果须为对象", category="invalid_shape", source=source)]
    for key, val in faction_delta.items():
        if isinstance(val, dict):
            for field in val.keys() - {"satisfaction", "leverage"}:
                rejected.append(RejectedItem(item={"entity_id": str(key), "field": field, "raw_value": val[field]}, reason="派系效果字段不可执行", category="invalid_enum", source=source))
            entry: Dict[str, int] = {}
            for fname in ("satisfaction", "leverage"):
                raw = val.get(fname)
                if raw is None:
                    continue
                try:
                    d = _strict_int(raw)
                except (TypeError, ValueError):
                    rejected.append(RejectedItem(item={str(key): val}, reason=f"「{key}」{fname} 值非整数：{raw!r}", category="invalid_enum", source=source))
                    continue
                if d != 0:
                    entry[fname] = d
            if entry:
                cleaned[str(key)] = entry
        else:
            try:
                d = _strict_int(val)
            except (TypeError, ValueError):
                rejected.append(RejectedItem(item={str(key): val}, reason=f"「{key}」值非整数：{val!r}", category="invalid_enum", source=source))
                continue
            if d != 0:
                cleaned[str(key)] = d
    if cleaned:
        # db 层未知名 → missing_ref 拒收：未写库，须从 cleaned 剔除，否则未落库的未知派系
        # 会进 faction_delta 段被 web 面板当「已落」误显（cmr r3 codex，DB↔呈现漂移=#14 本症）。
        for _rej in db.adjust_factions(cleaned, commit=False, source=source):
            cleaned.pop(next(iter(_rej.item)), None)
            rejected.append(_rej)
    return cleaned, rejected

