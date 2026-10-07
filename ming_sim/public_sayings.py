"""公开说法：独立记录，进入 0034 角色见闻公开层。

说法可能符合实况，也可能是误传或掩饰。记录本身不改人物实况。
可注所涉人物 / 事务；事务引用可空（谣言无起头）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from ming_sim.applier import connection_owns_transaction, sanitize_sqlite_text

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
    一票否决压过公开层。正文与排除名单只存在公开说法记录一处（#1829 reopen）；
    读口经 `public_saying:<id>` 回查本表，不另抄见闻来源、不月末物化。"""
    if not isinstance(body, str) or not body.strip():
        raise ValueError("公开说法正文不能为空")
    if not isinstance(affair_ref, str):
        raise ValueError("事务引用必须为字符串")
    text = sanitize_sqlite_text(body)
    affair = sanitize_sqlite_text(affair_ref.strip())
    people = _character_names(involved_characters)
    people_json = json.dumps(people, ensure_ascii=False)
    names = _character_names(excluded_names)
    targets = {
        str(key): _character_names(values)
        for key, values in (excluded_targets or {}).items()
        if _character_names(values)
    }
    owns = bool(commit) and connection_owns_transaction(db.conn)
    cur = db.conn.execute(
        "INSERT INTO public_sayings "
        "(turn, year, period, body, involved_characters, affair_ref, source_id, "
        "excluded_names, excluded_targets) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            int(state.turn),
            int(state.year),
            int(state.period),
            text,
            people_json,
            affair,
            f"{SOURCE_PREFIX}pending",
            json.dumps(names, ensure_ascii=False),
            json.dumps(targets, ensure_ascii=False),
        ),
    )
    saying_id = int(cur.lastrowid)
    source_id = f"{SOURCE_PREFIX}{saying_id}"
    db.conn.execute(
        "UPDATE public_sayings SET source_id=? WHERE id=?",
        (source_id, saying_id),
    )
    if owns:
        db.conn.commit()
    return saying_id


def public_layer_events(db: Any, *, for_public_feed: bool = False) -> list[dict[str, object]]:
    """投影进 0034 公开层的条目：人人读到「有此说法」，不是实况。

    `for_public_feed=True` 只由公共供料方（公共邸报作者）使用：带显式排除
    名单的说法不是「人人可读」，公共供料没有可被排除的具体读者，故不投影，
    否则公共供料会把受排除材料重新公开（#1829 C1）。其余读者（人物、全量
    推演者）走 `knowledge_row_visible_to` 的按人边界：推演者按 ADR 0155 三层
    全看，无读者不代表公共（#1829 F1）。
    """
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
        and not (
            for_public_feed
            and (row["excluded_names"] or row["excluded_targets"])
        )
    ]


def _json_name_list(raw: object) -> list[str]:
    from ming_sim.db import GameDB

    values = GameDB._loads_stored_json_list(raw, surface="public_sayings.excluded_names")
    return [str(name) for name in values if str(name).strip()]


def _json_target_map(raw: object) -> dict[str, list[str]]:
    from ming_sim.db import GameDB

    payload = GameDB.parse_engine_payload_json(
        raw, surface="public_sayings.excluded_targets",
    )
    result: dict[str, list[str]] = {}
    for key, values in payload.items():
        names = (
            [str(name) for name in values if str(name).strip()]
            if isinstance(values, list)
            else []
        )
        if names:
            result[str(key)] = names
    return result


def _row_as_saying(row: Any) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "turn": int(row["turn"]),
        "year": int(row["year"]),
        "period": int(row["period"]),
        "body": str(row["body"] or ""),
        "involved_characters": _json_name_list(row["involved_characters"]),
        "affair_ref": str(row["affair_ref"] or ""),
        "source_id": str(row["source_id"] or ""),
        "excluded_names": _json_name_list(row["excluded_names"]),
        "excluded_targets": _json_target_map(row["excluded_targets"]),
    }


def list_public_sayings(
    db: Any,
    *,
    involved_character: str | None = None,
    affair_ref: str | None = None,
) -> list[dict[str, object]]:
    rows = db.conn.execute(
        "SELECT id, turn, year, period, body, involved_characters, affair_ref, source_id, "
        "excluded_names, excluded_targets "
        "FROM public_sayings ORDER BY id"
    ).fetchall()
    result = [_row_as_saying(row) for row in rows]
    if involved_character is not None:
        name = str(involved_character).strip()
        result = [row for row in result if name in row["involved_characters"]]
    if affair_ref is not None:
        result = [row for row in result if row["affair_ref"] == affair_ref]
    return result
