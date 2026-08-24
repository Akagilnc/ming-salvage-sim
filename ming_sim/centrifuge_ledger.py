"""#690 / ADR 0011-2 — 血债棘轮 substrate（离心账本）。

公开入口：
  - accrue_blood_debt：惩处
  - accrue_detection_wariness：侦测薄 wrapper（#699 只调此口）
  - rebuild_centrifuge_cache：唯一维护例外（只重建派生 cache/overdraw，不改 log）

唯一正常 accrue/append 写核自持 applier.atomic，核内精确解析 canonical target，
公式 → 幂等三态 → 直写 log/cache/overdraw。无 caller faction/identity/planned_* 通道。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

from ming_sim.applier import atomic
from ming_sim.exceptions import SettlementAbort
from ming_sim.person_archive_contract import normalize_reason_code

SEVERITY_BASE: Dict[str, int] = {
    "申饬": 3,
    "罢黜": 10,
    "廷杖": 40,
    "抄家": 70,
    "诛": 100,
}

CENTRIFUGE_AXES: frozenset[str] = frozenset(
    {
        "礼法名节",
        "既得利益",
        "实务事功",
        "皇权依附",
        "华夷战和",
        "民本恤民",
    }
)

LEGAL_KINDS: frozenset[str] = frozenset({"direct", "kinship", "overdraw"})

# D2-5：STIGMA 独立常量，不进 0009 PERSON_REASON_CODES。
# crime_weight=1 由调用方/#692 传入；本片不查表、不因 STIGMA 自动改 cw。
STIGMA_REASON_CODES: frozenset[str] = frozenset({"中旨除授", "非正途", "罗织"})

_MODE_PUNISHMENT = "punishment"
_MODE_DETECTION = "detection"


def _abort(turn: int, message: str) -> SettlementAbort:
    return SettlementAbort(message, turn=int(turn), stage="centrifuge")


def _require_target(target: object, *, turn: int) -> str:
    if not isinstance(target, str) or target == "":
        raise _abort(turn, "target 必须为非空 str（名册原始全名）")
    # 不 strip：前后空白 ≠ 精确全名
    return target


def _require_axis(axis: object, *, turn: int) -> str:
    if not isinstance(axis, str) or axis not in CENTRIFUGE_AXES:
        raise _abort(turn, f"axis 必须为六轴之一，得 {axis!r}")
    return axis


def _require_idem_base(idem_base: object, *, turn: int) -> str:
    if not isinstance(idem_base, str) or idem_base == "":
        raise _abort(turn, "idem_base 必须为非空 str")
    return idem_base


def _require_turn(turn: object) -> int:
    if isinstance(turn, bool) or not isinstance(turn, int):
        raise SettlementAbort("turn 必须为 int", turn=0, stage="centrifuge")
    if turn < 0:
        raise SettlementAbort("turn 不可为负", turn=0, stage="centrifuge")
    return turn


def _require_int_in_range(
    value: object, *, label: str, lo: int, hi: int, turn: int
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _abort(turn, f"{label} 必须为 int")
    if value < lo or value > hi:
        raise _abort(turn, f"{label} 超出范围 [{lo},{hi}]")
    return value


def _require_positive_int(value: object, *, label: str, turn: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _abort(turn, f"{label} 必须为正 int")
    return value


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _null_safe_eq(left: object, right: object) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return left == right


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def accrue_blood_debt(
    *,
    db: Any,
    turn: int,
    target: str,
    axis: str,
    penalty_type: str,
    crime_weight: int,
    idem_base: str,
    reason_code: str | None = None,
    source: str | None = None,
) -> None:
    """惩处入口：只做与 DB 无关的表面校验，转交唯一写核。"""
    turn_i = _require_turn(turn)
    target_s = _require_target(target, turn=turn_i)
    axis_s = _require_axis(axis, turn=turn_i)
    if not isinstance(penalty_type, str) or penalty_type not in SEVERITY_BASE:
        raise _abort(turn_i, f"penalty_type 必须为 SEVERITY_BASE 五枚举之一，得 {penalty_type!r}")
    cw = _require_int_in_range(
        crime_weight, label="crime_weight", lo=1, hi=100, turn=turn_i
    )
    idem = _require_idem_base(idem_base, turn=turn_i)
    rc_raw = _optional_text(reason_code)
    if rc_raw is not None:
        normalized = normalize_reason_code(rc_raw)
        if normalized == "未识别":
            raise _abort(turn_i, f"reason_code 未识别：{rc_raw!r}")
        rc = normalized
    else:
        rc = None
    src = _optional_text(source)
    _accrue_centrifuge(
        db=db,
        turn=turn_i,
        target=target_s,
        axis=axis_s,
        mode=_MODE_PUNISHMENT,
        idem_base=idem,
        penalty_type=penalty_type,
        crime_weight=cw,
        alert_severity=None,
        reason_code=rc,
        source=src,
    )


def accrue_detection_wariness(
    *,
    db: Any,
    turn: int,
    target: str,
    axis: str,
    alert_severity: int,
    idem_base: str,
    source: str | None = None,
) -> None:
    """侦测薄 wrapper：leg=100 写死于核内；只 kinship；不收 penalty/cw/amount/faction/identity。"""
    turn_i = _require_turn(turn)
    target_s = _require_target(target, turn=turn_i)
    axis_s = _require_axis(axis, turn=turn_i)
    alert = _require_positive_int(alert_severity, label="alert_severity", turn=turn_i)
    idem = _require_idem_base(idem_base, turn=turn_i)
    src = _optional_text(source)
    _accrue_centrifuge(
        db=db,
        turn=turn_i,
        target=target_s,
        axis=axis_s,
        mode=_MODE_DETECTION,
        idem_base=idem,
        penalty_type=None,
        crime_weight=None,
        alert_severity=alert,
        reason_code=None,
        source=src,
    )


def rebuild_centrifuge_cache(db: Any) -> None:
    """唯一维护例外：同一 atomic 内先清派生 cache/overdraw，再仅由 log 回填。绝不改 log。"""
    with atomic(db):
        conn = db.conn
        conn.execute("DELETE FROM faction_axis_debt")
        conn.execute("UPDATE factions SET edict_overdraw = 0")
        # blood_debt from direct
        blood_rows = conn.execute(
            """
            SELECT faction, axis, COALESCE(SUM(amount), 0) AS total
            FROM centrifuge_log
            WHERE kind = 'direct'
            GROUP BY faction, axis
            """
        ).fetchall()
        wary_rows = conn.execute(
            """
            SELECT faction, axis, COALESCE(SUM(amount), 0) AS total
            FROM centrifuge_log
            WHERE kind = 'kinship'
            GROUP BY faction, axis
            """
        ).fetchall()
        totals: Dict[Tuple[str, str], Dict[str, int]] = {}
        for row in blood_rows:
            key = (str(row["faction"]), str(row["axis"]))
            totals.setdefault(key, {"blood_debt": 0, "wariness": 0})
            totals[key]["blood_debt"] = int(row["total"])
        for row in wary_rows:
            key = (str(row["faction"]), str(row["axis"]))
            totals.setdefault(key, {"blood_debt": 0, "wariness": 0})
            totals[key]["wariness"] = int(row["total"])
        for (faction, axis), vals in totals.items():
            if vals["blood_debt"] > 0 or vals["wariness"] > 0:
                conn.execute(
                    """
                    INSERT INTO faction_axis_debt(faction, axis, blood_debt, wariness)
                    VALUES (?, ?, ?, ?)
                    """,
                    (faction, axis, vals["blood_debt"], vals["wariness"]),
                )
        od_rows = conn.execute(
            """
            SELECT faction, COALESCE(SUM(amount), 0) AS total
            FROM centrifuge_log
            WHERE kind = 'overdraw'
            GROUP BY faction
            """
        ).fetchall()
        for row in od_rows:
            total = int(row["total"])
            if total > 0:
                conn.execute(
                    "UPDATE factions SET edict_overdraw = ? WHERE name = ?",
                    (total, str(row["faction"])),
                )


def _resolve_target_faction_identity(
    conn: Any, target: str, *, turn: int
) -> Tuple[str, int]:
    rows = conn.execute(
        "SELECT faction, identity FROM characters WHERE name = ?",
        (target,),
    ).fetchall()
    if len(rows) != 1:
        raise _abort(turn, f"target 精确命中必须恰好 1 行，得 {len(rows)}：{target!r}")
    row = rows[0]
    faction = row["faction"]
    if not isinstance(faction, str) or not faction.strip():
        raise _abort(turn, f"派生 faction 非法：{faction!r}")
    faction = str(faction)
    fac_row = conn.execute(
        "SELECT 1 FROM factions WHERE name = ?", (faction,)
    ).fetchone()
    if fac_row is None:
        raise _abort(turn, f"派生 faction 不在 factions 表：{faction!r}")
    identity = row["identity"]
    # 仅 strict int（排除 bool）；禁止 int() 静默截断 REAL/TEXT
    if not isinstance(identity, int) or isinstance(identity, bool):
        raise _abort(turn, f"派生 identity 非 int：{identity!r}")
    if identity < 0 or identity > 100:
        raise _abort(turn, f"派生 identity 越界：{identity}")
    return faction, identity


def _compute_punishment_deltas(
    *,
    turn: int,
    axis: str,
    penalty_type: str,
    crime_weight: int,
    identity: int,
    reason_code: Optional[str],
    source: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """栈内算 Δ；不接收/回传派生 faction，不组装可外传写载荷。"""
    severity = SEVERITY_BASE[penalty_type]
    mismatch = max(0, severity - crime_weight)
    # D2-4：金额用 raw 失称度；整数 legitimacy_pct 仅审计落库
    leg_raw = _clamp(10.0 + 90.0 * mismatch / severity, 10.0, 100.0)
    legitimacy_pct = int(round(leg_raw))
    k_id = _clamp(identity / 100.0, 0.0, 1.0)
    direct = int(round(severity * leg_raw / 100.0))
    # ADR 原式：禁止先 round(direct) 再乘
    kinship = int(round(severity * leg_raw / 100.0 * 0.3 * k_id))
    planned: Dict[str, Dict[str, Any]] = {}
    common = {
        "turn": turn,
        "reason_code": reason_code,
        "source": source,
    }
    if direct > 0:
        planned["direct"] = {
            **common,
            "axis": axis,
            "base": severity,
            "legitimacy_pct": legitimacy_pct,
            "amount": direct,
        }
    if kinship > 0:
        planned["kinship"] = {
            **common,
            "axis": axis,
            "base": severity,
            "legitimacy_pct": legitimacy_pct,
            "amount": kinship,
        }
    if penalty_type == "廷杖":
        planned["overdraw"] = {
            **common,
            "axis": None,
            "base": None,
            "legitimacy_pct": None,
            "amount": 1,
        }
    return planned


def _compute_detection_deltas(
    *,
    turn: int,
    axis: str,
    alert_severity: int,
    identity: int,
    source: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """栈内算 Δ；leg=100 写死；不接收/回传派生 faction。"""
    legitimacy_pct = 100
    k_id = _clamp(identity / 100.0, 0.0, 1.0)
    kinship = int(round(alert_severity * 0.3 * k_id))
    planned: Dict[str, Dict[str, Any]] = {}
    if kinship > 0:
        planned["kinship"] = {
            "turn": turn,
            "reason_code": None,
            "source": source,
            "axis": axis,
            "base": int(alert_severity),
            "legitimacy_pct": legitimacy_pct,
            "amount": kinship,
        }
    return planned


def _load_namespace(conn: Any, idem_base: str) -> Dict[str, Any]:
    keys = [f"{idem_base}|{k}" for k in sorted(LEGAL_KINDS)]
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        SELECT turn, faction, axis, kind, base, legitimacy_pct, amount,
               source_name, reason_code, source, idem_key
        FROM centrifuge_log
        WHERE idem_key IN ({placeholders})
        """,
        keys,
    ).fetchall()
    by_kind: Dict[str, Any] = {}
    for row in rows:
        kind = str(row["kind"])
        if kind not in LEGAL_KINDS:
            continue
        by_kind[kind] = row
    return by_kind


def _payloads_match(durable_row: Any, payload: Dict[str, Any], *, kind: str) -> bool:
    checks = [
        ("turn", durable_row["turn"], payload["turn"]),
        ("faction", durable_row["faction"], payload["faction"]),
        ("source_name", durable_row["source_name"], payload["source_name"]),
        ("amount", durable_row["amount"], payload["amount"]),
        ("reason_code", durable_row["reason_code"], payload["reason_code"]),
        ("source", durable_row["source"], payload["source"]),
    ]
    for _label, left, right in checks:
        if not _null_safe_eq(left, right):
            return False
    if kind in ("direct", "kinship"):
        for field in ("axis", "base", "legitimacy_pct"):
            if not _null_safe_eq(durable_row[field], payload[field]):
                return False
    elif kind == "overdraw":
        for field in ("axis", "base", "legitimacy_pct"):
            if durable_row[field] is not None:
                return False
            if payload[field] is not None:
                return False
    else:
        return False
    return True


def _accrue_centrifuge(
    *,
    db: Any,
    turn: int,
    target: str,
    axis: str,
    mode: str,
    idem_base: str,
    penalty_type: Optional[str],
    crime_weight: Optional[int],
    alert_severity: Optional[int],
    reason_code: Optional[str],
    source: Optional[str],
) -> None:
    """唯一正常 accrue/append 写核。形参不含 faction/identity/planned_*。

    同一 atomic 内：精确解析 target → 栈内算 Δ → 幂等三态 → 直写 log/cache/overdraw。
    无第二 planned 写缝；写时用核内已解析 faction/identity。
    """
    with atomic(db):
        conn = db.conn
        faction, identity = _resolve_target_faction_identity(conn, target, turn=turn)
        if mode == _MODE_PUNISHMENT:
            assert penalty_type is not None and crime_weight is not None
            deltas = _compute_punishment_deltas(
                turn=turn,
                axis=axis,
                penalty_type=penalty_type,
                crime_weight=crime_weight,
                identity=identity,
                reason_code=reason_code,
                source=source,
            )
        elif mode == _MODE_DETECTION:
            assert alert_severity is not None
            deltas = _compute_detection_deltas(
                turn=turn,
                axis=axis,
                alert_severity=alert_severity,
                identity=identity,
                source=source,
            )
        else:
            raise _abort(turn, f"unknown centrifuge mode: {mode!r}")

        # 核内已解析值并入比对/落库行（compute 不组装 faction/source_name）
        planned: Dict[str, Dict[str, Any]] = {
            kind: {**delta, "faction": faction, "source_name": target}
            for kind, delta in deltas.items()
        }

        planned_kinds: Set[str] = set(planned)
        existing = _load_namespace(conn, idem_base)
        durable_kinds: Set[str] = set(existing)

        if durable_kinds == set() and planned_kinds == set():
            return
        if durable_kinds == planned_kinds:
            for kind in planned_kinds:
                if not _payloads_match(existing[kind], planned[kind], kind=kind):
                    raise _abort(
                        turn,
                        f"centrifuge idem payload mismatch under {idem_base!r} kind={kind}",
                    )
            return
        if durable_kinds != set():
            raise _abort(
                turn,
                f"centrifuge idem kind-set mismatch under {idem_base!r}: "
                f"durable={sorted(durable_kinds)} planned={sorted(planned_kinds)}",
            )

        # durable 空且 planned 非空：直写三账（唯一写缝）
        for kind, payload in planned.items():
            idem_key = f"{idem_base}|{kind}"
            conn.execute(
                """
                INSERT INTO centrifuge_log(
                    turn, faction, axis, kind, base, legitimacy_pct, amount,
                    source_name, reason_code, source, idem_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["turn"],
                    faction,
                    payload["axis"],
                    kind,
                    payload["base"],
                    payload["legitimacy_pct"],
                    payload["amount"],
                    target,
                    payload["reason_code"],
                    payload["source"],
                    idem_key,
                ),
            )
            if kind == "direct":
                conn.execute(
                    """
                    INSERT INTO faction_axis_debt(faction, axis, blood_debt, wariness)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(faction, axis) DO UPDATE SET
                        blood_debt = blood_debt + excluded.blood_debt
                    """,
                    (faction, payload["axis"], int(payload["amount"])),
                )
            elif kind == "kinship":
                conn.execute(
                    """
                    INSERT INTO faction_axis_debt(faction, axis, blood_debt, wariness)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(faction, axis) DO UPDATE SET
                        wariness = wariness + excluded.wariness
                    """,
                    (faction, payload["axis"], int(payload["amount"])),
                )
            elif kind == "overdraw":
                conn.execute(
                    """
                    UPDATE factions
                    SET edict_overdraw = edict_overdraw + ?
                    WHERE name = ?
                    """,
                    (int(payload["amount"]), faction),
                )
