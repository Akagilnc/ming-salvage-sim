"""#654 差务属地 oracle：闭合结构化组合，不解析散文。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.matching import match_region_id_from_text

# TARGET_KINDS：八值真源在 decree_vocabulary；此处 re-export 保兼容。
# 归一后合法 locality_scope 闭集
LOCALITY_SCOPES = frozenset({"national", "single", "none"})
_SCOPE_ALIASES = {
    "全国": "national",
    "单省": "single",
    "无": "none",
    "national": "national",
    "single": "single",
    "none": "none",
}

# #654 r4-B / #1624：target_kind → 可接受 locality_scope 闭集（8×3 scope 轴唯一 typed 真源）。
# assert_target_locality_matrix 与 prompt 投影共引（#1778：national 无动作白名单）。
# 禁 prompt/入口手抄第二份可接受面。
TARGET_KIND_LOCALITY_SCOPES: Dict[str, frozenset[str]] = {
    "region": frozenset({"single"}),
    "dossier": frozenset({"none"}),
    "character": frozenset({"none"}),
    "office": frozenset({"none"}),
    "army": frozenset({"none"}),
    "policy": frozenset({"none", "national"}),
    "issue": frozenset({"none", "national"}),
    "account": frozenset({"none", "national"}),
}
assert frozenset(TARGET_KIND_LOCALITY_SCOPES) == TARGET_KINDS
PROVINCE_KINDS = frozenset({"两京", "布政司"})


def write_locality_scope_for_target_kind(target_kind: object) -> str:
    """缺省 locality 补全（仅输入未给 scope 时）。region→single，其余→none。

    #1624：禁止用本函数覆盖 LLM/层 A 已给的 locality 来掩盖错误目标；
    显式组合校验见 structured_decree.validate_structured_decree_combination。
    """
    return "single" if str(target_kind or "").strip() == "region" else "none"


def normalize_locality_scope(raw: object) -> str:
    """{'全国'/'单省'/'无'/缺省 → national/single/none}；枚举外 fail-loud。"""
    if raw is None:
        return "none"
    text = str(raw).strip()
    if not text:
        return "none"
    if text in _SCOPE_ALIASES:
        scope = _SCOPE_ALIASES[text]
    else:
        scope = text
    if scope not in LOCALITY_SCOPES:
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            f"locality_scope 非法：{raw!r}",
            failed_fields=("locality_scope",),
        )
    return scope


def _resolve_single_region_id(
    conn,
    target_id: str,
    *,
    regions_content: Optional[Mapping[str, Any]] = None,
) -> str:
    """R1 解析链：id 精确 → name 精确 → match_region_id_from_text；歧义/零命中 fail-loud。"""
    tid = str(target_id or "").strip()
    if not tid:
        raise ValueError("单省目标 target_id 为空")
    by_id = conn.execute(
        "SELECT id, kind, controlled_by FROM regions WHERE id=?", (tid,),
    ).fetchone()
    if by_id is not None:
        return _region_row_to_locality(by_id)
    by_name = conn.execute(
        "SELECT id, kind, controlled_by FROM regions WHERE name=?", (tid,),
    ).fetchall()
    if len(by_name) == 1:
        return _region_row_to_locality(by_name[0])
    if len(by_name) > 1:
        raise ValueError(f"单省目标歧义（多省同名）：{tid!r}")
    # ③ matching 链：需 content.regions；无 content 时仅 DB 已判零命中
    if regions_content is None:
        raise ValueError(f"单省目标零命中：{tid!r}")
    matched = match_region_id_from_text(tid, regions_content)
    if matched is None:
        raise ValueError(f"单省目标零命中或歧义：{tid!r}")
    row = conn.execute(
        "SELECT id, kind, controlled_by FROM regions WHERE id=?", (matched,),
    ).fetchone()
    if row is None:
        raise ValueError(f"单省目标零命中：{tid!r}")
    return _region_row_to_locality(row)


def _region_row_to_locality(row) -> str:
    kind = str(row["kind"] or "")
    controlled = str(row["controlled_by"] or "")
    rid = str(row["id"])
    if kind in PROVINCE_KINDS and controlled == "ming":
        return rid
    # 省集合外（边镇/外域等）→ 不入属地浓度账
    return ""


class TargetLocalityMatrixError(ValueError):
    """属地矩阵不变式失败；failed_fields 为可修字段边界（禁异常文本识别）。

    field_failures：权威结构化失败事实（field/current/expected）；运输层只携带。
    """

    def __init__(
        self,
        message: object,
        *,
        field_failures: tuple[dict[str, object], ...] = (),
    ) -> None:
        super().__init__(message)
        # failed_fields 只从权威事实派生，不双持独立输入
        self.field_failures = tuple(dict(f) for f in field_failures)
        self.failed_fields = frozenset(
            str(f["field"]) for f in self.field_failures
        )


def project_target_locality_matrix_prompt() -> str:
    """由 TARGET_KIND_LOCALITY_SCOPES 投影可接受面（供共同 prompt 消费；禁手抄）。"""
    groups: Dict[frozenset[str], list[str]] = {}
    for kind, scopes in TARGET_KIND_LOCALITY_SCOPES.items():
        groups.setdefault(scopes, []).append(kind)
    parts: list[str] = []
    for scopes in sorted(groups, key=lambda s: (sorted(s), len(s))):
        kinds = "|".join(sorted(groups[scopes]))
        if len(scopes) == 1:
            only = next(iter(scopes))
            parts.append(f"{kinds}仅{only}")
        else:
            parts.append(f"{kinds}∈{'|'.join(sorted(scopes))}")
    return (
        "target_kind×locality_scope 可接受面（" + "；".join(parts) + "）"
    )


def assert_target_locality_matrix(
    *,
    target_kind: object,
    locality_scope: object,
) -> str:
    """#654 / #1624：target_kind × locality_scope 8×3 矩阵唯一实现（无 DB）。

    可接受面真源 = TARGET_KIND_LOCALITY_SCOPES（#1778：national 不再另咬动作白名单）。
    resolve_dossier_region_ids 与 structured_decree 组合闸共引本函数——禁止平行第二份矩阵。
    失败带 TargetLocalityMatrixError.failed_fields（逐不变式可修边界）。
    """
    kind = str(target_kind or "").strip()
    kinds_expected = sorted(TARGET_KINDS)

    def _fact(
        field: str,
        *,
        current: object,
        expected: object,
    ) -> dict[str, object]:
        return {"field": field, "current": current, "expected": expected}

    def _matrix_fail(
        message: str,
        *,
        field_failures: tuple[dict[str, object], ...],
    ) -> None:
        raise TargetLocalityMatrixError(
            message,
            field_failures=field_failures,
        )

    try:
        scope = normalize_locality_scope(locality_scope)
    except ValueError as exc:
        _matrix_fail(
            str(exc),
            field_failures=(
                _fact(
                    "locality_scope",
                    current=locality_scope,
                    expected=sorted(LOCALITY_SCOPES),
                ),
            ),
        )

    allowed = TARGET_KIND_LOCALITY_SCOPES.get(kind)

    if allowed is None or kind not in TARGET_KINDS:
        _matrix_fail(
            f"target_kind 非法：{kind!r}",
            field_failures=(
                _fact("target_kind", current=kind, expected=kinds_expected),
            ),
        )

    scope_allowed = sorted(allowed)
    if scope not in allowed:
        # 保留历史失败措辞（下游测试/诊断认语义，不锁字符串为闸）
        kind_fact = _fact("target_kind", current=kind, expected=kinds_expected)
        scope_fact = _fact(
            "locality_scope", current=scope, expected=scope_allowed,
        )
        if kind == "region":
            _matrix_fail(
                f"region 目标与 locality_scope={scope!r} 矛盾（须 single）",
                field_failures=(scope_fact,),
            )
        if kind == "dossier":
            _matrix_fail(
                f"target_kind=dossier 与 locality_scope={scope!r} 矛盾（须 none）",
                field_failures=(scope_fact,),
            )
        if scope == "single":
            _matrix_fail(
                f"locality_scope=single 只配 region 目标，得 target_kind={kind!r}",
                field_failures=(scope_fact, kind_fact),
            )
        if scope == "national":
            _matrix_fail(
                f"target_kind={kind!r} 不得 national fan-out",
                field_failures=(scope_fact, kind_fact),
            )
        _matrix_fail(
            f"target_kind={kind!r} 与 locality_scope={scope!r} 矛盾"
            f"（允许 {'|'.join(scope_allowed)}）",
            field_failures=(scope_fact, kind_fact),
        )

    return scope


def resolve_dossier_region_ids(
    conn,
    *,
    payload: Mapping[str, object],
    regions_content: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """属地三分 oracle → 本案应落的 region_id 列表（确定序）。

    组合校验先于 region 解析（r4-B）。返回 [''] 表示非属地单行。
    #1778 决定 4：全国政令也是一份案卷、一张名单——national 与 none 同为单行 ''，
    不按省拆；各省忙闲/阻力只作执行判官的事实输入（0092 两轴）。
    """
    target_kind = str(payload.get("target_kind") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    assert_target_locality_matrix(
        target_kind=target_kind,
        locality_scope=payload.get("locality_scope"),
    )

    if target_kind == "region":
        return [_resolve_single_region_id(
            conn, target_id, regions_content=regions_content,
        )]

    # national / none：单行 ''（region 目标以外一律不落属地行）
    return [""]
