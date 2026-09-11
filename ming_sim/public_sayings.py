"""公开说法：独立记录，进入 0034 角色见闻公开层。

说法可能符合实况，也可能是误传或掩饰。记录本身不改人物实况。
可注所涉人物 / 事务；事务引用可空（谣言无起头）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from ming_sim.applier import connection_owns_transaction

SOURCE_PREFIX = "public_saying:"
LAYER_TITLE = "有此说法"


def public_layer_prose(item: Mapping[str, object]) -> str:
    """公开层读到的是「有此说法」，不是实况。"""
    # #1812 P6：title/body 是自由正文，判空只用局部 stripped 副本，写出用原文。
    title = str(item.get("title") or LAYER_TITLE)
    if not title.strip():
        title = LAYER_TITLE
    body = str(item.get("body") or "")
    if body.strip():
        return f"{title}：{body}"
    return title


def _character_names(names: Iterable[str] | None) -> list[str]:
    return list(dict.fromkeys(str(name).strip() for name in (names or ()) if str(name).strip()))


def record_public_saying(
    db: Any,
    state: Any,
    body: str,
    *,
    involved_characters: Iterable[str] = (),
    affair_ref: str = "",
    excluded_names: Iterable[str] = (),
    excluded_targets: Mapping[str, Iterable[str]] | None = None,
    commit: bool = True,
) -> int:
    """记下一条公开说法，并写入公开层。不改人物实况。

    `excluded_names`/`excluded_targets`：密令『瞒某人』这类显式排除黑名单
    一票否决压过公开层——公开说法自己的 source（`public_saying:<id>`）复用
    既有 `knowledge_row_visible_to` 读口（它已经会回查
    `knowledge_exclusions_for_source`/`knowledge_exclusion_targets_for_source`），
    只是之前从未有写口往这个 source_id 上落过排除名单，闸有输入永远是空
    （#1829/#1832）。落库走既有 `register_character_knowledge_source`（同
    commissions 等其它 source 一样的持久黑名单表），不另建一套机制。"""
    if not isinstance(body, str) or not body.strip():
        raise ValueError("公开说法正文不能为空")
    if not isinstance(affair_ref, str):
        raise ValueError("事务引用必须为字符串")
    text = body
    affair = affair_ref
    people = _character_names(involved_characters)
    people_json = json.dumps(people, ensure_ascii=False)
    owns = bool(commit) and connection_owns_transaction(db.conn)
    cur = db.conn.execute(
        "INSERT INTO public_sayings "
        "(turn, year, period, body, involved_characters, affair_ref, source_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(state.turn),
            int(state.year),
            int(state.period),
            text,
            people_json,
            affair,
            f"{SOURCE_PREFIX}pending",
        ),
    )
    saying_id = int(cur.lastrowid)
    source_id = f"{SOURCE_PREFIX}{saying_id}"
    db.conn.execute(
        "UPDATE public_sayings SET source_id=? WHERE id=?",
        (source_id, saying_id),
    )
    names = _character_names(excluded_names)
    targets = {
        str(key): _character_names(values)
        for key, values in (excluded_targets or {}).items()
        if _character_names(values)
    }
    if (names or targets) and hasattr(db, "register_character_knowledge_source"):
        db.register_character_knowledge_source(
            state, (), kind="public", title=LAYER_TITLE, body=text,
            source_id=source_id, excluded_names=names, excluded_targets=targets,
            commit=False,
        )
    if owns:
        db.conn.commit()
    return saying_id


def public_layer_events(db: Any) -> list[dict[str, object]]:
    """投影进 0034 公开层的条目：人人读到「有此说法」，不是实况。"""
    return [
        {
            "turn": row["turn"],
            "year": row["year"],
            "period": row["period"],
            "kind": "public",
            "title": LAYER_TITLE,
            "body": row["body"],
            "source_id": row["source_id"],
        }
        for row in list_public_sayings(db)
        if row.get("source_id")
    ]


def _row_as_saying(row: Any) -> dict[str, object]:
    try:
        people = json.loads(row["involved_characters"] or "[]")
    except (TypeError, ValueError):
        people = []
    if not isinstance(people, list):
        people = []
    return {
        "id": int(row["id"]),
        "turn": int(row["turn"]),
        "year": int(row["year"]),
        "period": int(row["period"]),
        "body": str(row["body"] or ""),
        "involved_characters": [str(name) for name in people if str(name).strip()],
        "affair_ref": str(row["affair_ref"] or ""),
        "source_id": str(row["source_id"] or ""),
    }


def list_public_sayings(
    db: Any,
    *,
    involved_character: str | None = None,
    affair_ref: str | None = None,
) -> list[dict[str, object]]:
    rows = db.conn.execute(
        "SELECT id, turn, year, period, body, involved_characters, affair_ref, source_id "
        "FROM public_sayings ORDER BY id"
    ).fetchall()
    result = [_row_as_saying(row) for row in rows]
    if involved_character is not None:
        name = str(involved_character).strip()
        result = [row for row in result if name in row["involved_characters"]]
    if affair_ref is not None:
        result = [row for row in result if row["affair_ref"] == affair_ref]
    return result
