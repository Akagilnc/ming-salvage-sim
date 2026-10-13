"""人物变更条目的姓名读取与名册对齐。"""

from __future__ import annotations

from typing import Dict, List, Optional

from ming_sim.content import GameContent
from ming_sim.db import GameDB


def _person_change_name(item: Dict[str, object]) -> str:
    return str(
        item.get("name")
        or item.get("姓名")
        or item.get("character")
        or item.get("person")
        or ""
    ).strip()


def _canonicalize_person_change_names(
    changes: List[Dict[str, object]],
    content: Optional[GameContent],
    db: GameDB,
) -> List[Dict[str, object]]:
    if content is None:
        return changes
    from ming_sim.session import _find_existing_minister

    canonicalized: List[Dict[str, object]] = []
    for item in changes:
        name = _person_change_name(item)
        canon = _find_existing_minister(content, name, db) if name else None
        if canon and canon != name:
            copied = dict(item)
            copied["name"] = canon
            canonicalized.append(copied)
        else:
            canonicalized.append(item)
    return canonicalized
