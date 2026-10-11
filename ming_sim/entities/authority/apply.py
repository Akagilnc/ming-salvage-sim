"""委任授权落库核。

段适配器只编排；校验与写入住在本模块。数据失败抛 AuthorityDataError，
读库与写库故障原样上抛，由外层事务回滚。
"""

from __future__ import annotations

from typing import Dict, Optional

from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.db import GameDB
from ming_sim.decree_vocabulary import dossier_action_policy
from ming_sim.strict_types import _parse_sqlite_id
from ming_sim.models import GameState


class AuthorityDataError(ValueError):
    """授权项本身不成立。不是读库或写库故障。"""

    def __init__(self, message: str, *, category: Optional[str] = None) -> None:
        super().__init__(message)
        self.category = category


_AUTHORITY_GRANT_OPS = frozenset({"授予", "grant"})
_AUTHORITY_REVOKE_OPS = frozenset({"收回", "revoke"})


def _prepare_authority_change_item(
    db: GameDB, state: GameState, item: Dict[str, object],
) -> Dict[str, object]:
    """校验一条授权变更。不写库。幂等重放放在 applied 里返回。"""
    if "dossier_id" not in item or item.get("dossier_id") in (None, ""):
        raise AuthorityDataError("missing_dossier_source")
    try:
        dossier_id = _parse_sqlite_id(item.get("dossier_id"))
    except (TypeError, ValueError) as exc:
        raise AuthorityDataError(str(exc), category="missing_dossier_source") from exc
    if dossier_id <= 0 or db.get_decree_dossier(dossier_id) is None:
        raise AuthorityDataError("missing_dossier_source")
    if not db.dossier_authorizes_effects(dossier_id):
        raise AuthorityDataError("dossier_not_effect_eligible")
    op = str(item.get("动作") or item.get("op") or "").strip()
    if op not in _AUTHORITY_GRANT_OPS | _AUTHORITY_REVOKE_OPS:
        raise AuthorityDataError("授权变更动作只收授予/收回")

    if op in _AUTHORITY_GRANT_OPS:
        holder_id = str(item.get("holder_id") or "").strip()
        privilege = str(item.get("privilege") or item.get("权项") or "").strip()
        scope = str(item.get("scope") or item.get("事域") or "").strip()
        if not holder_id or not privilege or not scope:
            raise AuthorityDataError("授予项必须含 holder_id/privilege/scope")
        if privilege not in AUTHORITY_PRIVILEGE_SET:
            raise AuthorityDataError("授权权项不在首批枚举")
        kind, separator, target_id = scope.partition(":")
        if not separator or not kind or not target_id:
            raise AuthorityDataError("invalid_authority_scope")
        if not db.conn.execute(
            "SELECT 1 FROM characters WHERE name=?", (holder_id,)
        ).fetchone():
            raise AuthorityDataError("授权对象不在人物档")
        origin = db.find_authority_by_origin(
            dossier_id, holder_id=holder_id, privilege=privilege, scope=scope,
        )
        if origin is not None:
            return {"applied": {
                "动作": "授予",
                "authority_id": int(origin["id"]),
                "dossier_id": dossier_id,
                "holder_id": holder_id,
                "privilege": privilege,
                "scope": scope,
                "reason": "same_dossier_replay",
            }}
        effective_raw = item.get("effective_turn", item.get("生效回合"))
        expires_raw = item.get("expires_turn", item.get("失效回合"))
        try:
            effective_turn = (
                int(state.turn) if effective_raw in (None, "")
                else _parse_sqlite_id(effective_raw)
            )
            expires_turn = (
                None if expires_raw in (None, "")
                else _parse_sqlite_id(expires_raw)
            )
        except (TypeError, ValueError):
            raise AuthorityDataError("授权回合非法") from None
        if expires_turn is not None and expires_turn < effective_turn:
            raise AuthorityDataError("授权失效回合不得早于生效回合")
        existing = db.find_active_authority(
            state.turn, holder_id=holder_id, privilege=privilege, scope=scope,
        )
        if existing is not None:
            raise AuthorityDataError("duplicate_active_authority")
        return {
            "op": "grant",
            "holder_id": holder_id,
            "privilege": privilege,
            "scope": scope,
            "effective_turn": effective_turn,
            "expires_turn": expires_turn,
            "dossier_id": dossier_id,
        }

    try:
        authority_id = _parse_sqlite_id(item.get("authority_id"))
    except (TypeError, ValueError) as exc:
        raise AuthorityDataError(str(exc), category="unknown_authority_id") from exc
    if authority_id <= 0:
        raise AuthorityDataError("unknown_authority_id")
    record = db.get_authority(authority_id)
    if record is None:
        raise AuthorityDataError("unknown_authority_id")
    if bool(record.get("revoked")):
        return {"applied": {
            "动作": "收回",
            "authority_id": authority_id,
            "dossier_id": dossier_id,
            "reason": "already_revoked",
        }}
    return {
        "op": "revoke",
        "authority_id": authority_id,
        "dossier_id": dossier_id,
        "record": record,
    }


def _write_authority_change_item(
    db: GameDB, state: GameState, prepared: Dict[str, object],
) -> Dict[str, object]:
    """落一条已校验的授权变更。写后故障原样上抛。"""
    if prepared["op"] == "grant":
        cursor = db.conn.execute(
            "INSERT INTO authority_records "
            "(holder_id,privilege,scope,effective_turn,expires_turn,dossier_id) "
            "VALUES (?,?,?,?,?,?)",
            (
                prepared["holder_id"], prepared["privilege"], prepared["scope"],
                prepared["effective_turn"], prepared["expires_turn"],
                prepared["dossier_id"],
            ),
        )
        return {
            "动作": "授予",
            "authority_id": int(cursor.lastrowid),
            "dossier_id": prepared["dossier_id"],
            "holder_id": prepared["holder_id"],
            "privilege": prepared["privilege"],
            "scope": prepared["scope"],
        }
    authority_id = int(prepared["authority_id"])
    record = prepared["record"]
    revoked = db.conn.execute(
        "UPDATE authority_records SET revoked=1,revoked_turn=? "
        "WHERE id=? AND revoked=0", (int(state.turn), authority_id),
    )
    if revoked.rowcount <= 0:
        raise ValueError("unknown_authority_id")
    # #1895 / #1835 J19：首次收回只记授权事实；holder 是否结怨由既有人物 run
    # 经 relation 声明口承接，代码不自动写 holder→皇帝结怨。
    privilege = str(record.get("privilege") or "")
    scope = str(record.get("scope") or "")
    holder_id = str(record.get("holder_id") or "")
    return {
        "动作": "收回",
        "authority_id": authority_id,
        "dossier_id": prepared["dossier_id"],
        "holder_id": holder_id,
        "privilege": privilege,
        "scope": scope,
    }


def _payload_owned_dossier_for_origin(db: GameDB, origin_ref: object) -> Optional[Dict[str, object]]:
    """Resolve an authorized dossier through the canonical ownership policy."""
    text = str(origin_ref or "").strip()
    if not text.startswith("dossier:"):
        return None
    try:
        dossier_id = _parse_sqlite_id(text.split(":", 1)[1])
    except ValueError:
        return None
    row = db.get_decree_dossier(dossier_id)
    if row is None or not db.dossier_authorizes_effects(dossier_id):
        return None
    payload = row["payload"]  # GameDB.get_decree_dossier 已校验持久 JSON。
    if dossier_action_policy(row.get("action_type"), payload)["effect_owner"] != "payload":
        return None
    return row
