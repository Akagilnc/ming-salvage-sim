"""#654 差务属地 fan-out oracle + 带宽/阻力两轴清单（纯机面）。

- locality：闭合结构化 oracle，禁散文。
- distance_semantic_band：0094 矩阵 × 0097/ r4-A 四档措辞。
- build_execution_two_axis_surface：给定 DB → 确定性清单，零 LLM。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ming_sim.decree_vocabulary import NATIONAL_FANOUT_ACTION_TYPES, TARGET_KINDS
from ming_sim.distance import DistanceMatrix
from ming_sim.matching import match_region_id_from_text
from ming_sim.paths import bundled_path

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
PROVINCE_KINDS = frozenset({"两京", "布政司"})
DISASTER_KINDS = frozenset({"天灾", "灾情", "饥荒"})  # issues.py 灾情族同源
ABSENT = "不参与"
NO_RECORD = "无记录"
VACANT = "出缺"
NO_BANDIT = "无"

# r4-A 四档完整字符串（接口层语义量，纯机面合法）
BAND_LOCAL = "本省当地，全程旬月可至"
BAND_NEAR = "邻近之地，全程约一月量级"
BAND_MID = "中途之程，全程约二三月量级"
BAND_FAR = "边远之途，全程约三月以上量级"


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
        raise ValueError(f"locality_scope 非法：{raw!r}")
    return scope


def _load_distance_matrix() -> DistanceMatrix:
    """每次调用装载；禁止模块级可变缓存（r3-A.1 / r4-A）。"""
    return DistanceMatrix.from_file(
        bundled_path("content", "distance_matrix.json"),
    )


def fold_distance_band(travel_months: float) -> str:
    """0094 耗时（常速月）→ r4-A 四档完整措辞。阈值首版随 playtest。"""
    t = float(travel_months)
    if t <= 0.0 or math.isclose(t, 0.0, abs_tol=1e-9):
        return BAND_LOCAL
    if t <= 1.0 or math.isclose(t, 1.0, abs_tol=1e-9):
        return BAND_NEAR
    if t <= 3.0 or math.isclose(t, 3.0, abs_tol=1e-9):
        return BAND_MID
    return BAND_FAR


def distance_semantic_band(
    *,
    owner_location: str,
    region_id: str,
    transit_to: str = "",
    matrix: Optional[DistanceMatrix] = None,
) -> str:
    """D1–D6 退化树。缺矩阵项原样 KeyError（D6 fail-loud）。"""
    rid = str(region_id or "").strip()
    if not rid:
        return ABSENT  # D1
    loc = str(owner_location or "").strip()
    if not loc:
        return ABSENT  # D2
    if str(transit_to or "").strip():
        return ABSENT  # D3
    if loc == rid:
        return BAND_LOCAL  # D4
    # 未传入 matrix 时函数内局部装载，不写模块全局
    m = matrix if matrix is not None else _load_distance_matrix()
    return fold_distance_band(m.travel_time(loc, rid))  # D5 / D6


def ming_province_ids(conn) -> List[str]:
    rows = conn.execute(
        "SELECT id FROM regions "
        "WHERE kind IN ('两京','布政司') AND controlled_by='ming' "
        "ORDER BY id",
    ).fetchall()
    return [str(r["id"]) for r in rows]


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


def resolve_dossier_region_ids(
    conn,
    *,
    action_type: str,
    payload: Mapping[str, object],
    regions_content: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """属地三分 oracle → 本案应落的 region_id 列表（确定序）。

    组合校验先于 region 解析（r4-B）。返回 [''] 表示非属地单行。
    region 缺省 / none / national 一律 fail-loud（无兼容暗升或空串降级）。
    """
    action = str(action_type or "").strip()
    target_kind = str(payload.get("target_kind") or "").strip()
    raw_scope = payload.get("locality_scope")
    scope = normalize_locality_scope(raw_scope)
    target_id = str(payload.get("target_id") or "").strip()

    # 八值成员校验先于 8×3 矩阵分派（owner A：无成员校验前旁路）
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind 非法：{target_kind!r}")

    # r4-B / owner A 8×3：R1 = region ∧ single；dossier 仅 none → 单行 ''
    if target_kind == "region":
        if scope != "single":
            raise ValueError(
                f"region 目标与 locality_scope={scope!r} 矛盾（须 single）"
            )
        return [_resolve_single_region_id(
            conn, target_id, regions_content=regions_content,
        )]

    if target_kind == "dossier":
        if scope != "none":
            raise ValueError(
                f"target_kind=dossier 与 locality_scope={scope!r} 矛盾（须 none）"
            )
        return [""]

    if scope == "single":
        raise ValueError(
            f"locality_scope=single 只配 region 目标，得 target_kind={target_kind!r}"
        )

    if scope == "national":
        if target_kind in {"character", "office", "army", "dossier"}:
            raise ValueError(
                f"target_kind={target_kind!r} 不得 national fan-out"
            )
        # policy / issue / account
        if action not in NATIONAL_FANOUT_ACTION_TYPES:
            raise ValueError(
                f"national fan-out 动作不在白名单：{action!r}"
            )
        provinces = ming_province_ids(conn)
        if not provinces:
            raise ValueError("全国 fan-out 省集合为空")
        return provinces

    # scope == none：policy/issue/account/character/office/army → 单行 ''
    return [""]


def _class_slice(conn, name: str, region_id: str) -> object:
    row = conn.execute(
        "SELECT population, satisfaction, leverage FROM classes "
        "WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    if row is None:
        return NO_RECORD
    return {
        "population": int(row["population"]),
        "satisfaction": int(row["satisfaction"]),
        "leverage": int(row["leverage"]),
    }


def _format_class_slice(value: object) -> str:
    """TSV 运输：有记录 → pop/sat/lev；哨兵原样。"""
    if isinstance(value, Mapping):
        return (
            f"{int(value.get('population', 0))}/"
            f"{int(value.get('satisfaction', 0))}/"
            f"{int(value.get('leverage', 0))}"
        )
    return str(value)


def _dutang_fields(conn, region_id: str) -> Tuple[object, object]:
    """督抚三态：无 slot=无记录；有 slot 无 holder=出缺；有 holder 读人物。"""
    row = conn.execute(
        "SELECT holder_name FROM office_vacancies "
        "WHERE region_id=? AND office_type='督抚' "
        "ORDER BY sort_order ASC, office_title ASC LIMIT 1",
        (region_id,),
    ).fetchone()
    if row is None:
        return NO_RECORD, NO_RECORD
    if not str(row["holder_name"] or "").strip():
        return VACANT, VACANT
    holder = str(row["holder_name"])
    ch = conn.execute(
        "SELECT faction, integrity FROM characters WHERE name=?", (holder,),
    ).fetchone()
    if ch is None:
        return VACANT, VACANT
    return str(ch["faction"] or ""), int(ch["integrity"] or 0)


def _bandit_strength(conn, region_id: str) -> object:
    row = conn.execute(
        """
        SELECT MAX(p.military_strength) AS ms
        FROM powers p
        JOIN armies a ON a.controller = p.id
        WHERE p.kind = '内乱' AND a.station = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None or row["ms"] is None:
        return NO_BANDIT
    return int(row["ms"])


def _disaster_rows(conn, region_id: str) -> List[Dict[str, object]]:
    """D1：灾种真源＝tags ∩ DISASTER_KINDS；durable kind 固定 situation。"""
    import json

    rows = conn.execute(
        """
        SELECT id, title, kind, severity, region_hint, tags
        FROM issues
        WHERE status='active' AND kind='situation' AND region_hint=?
        ORDER BY severity DESC, id ASC
        """,
        (region_id,),
    ).fetchall()
    stable = tuple(sorted(DISASTER_KINDS))
    out: List[Dict[str, object]] = []
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except (TypeError, ValueError):
            tags = []
        if not isinstance(tags, list):
            tags = []
        tag_set = {str(t).strip() for t in tags if str(t).strip()}
        hit = [k for k in stable if k in tag_set]
        if not hit:
            continue
        out.append({
            "id": int(r["id"]),
            "title": str(r["title"] or ""),
            "kind": hit[0],
            "severity": int(r["severity"] or 0),
        })
    return out


def _host_leads_from_roster(raw: object) -> List[str]:
    """participant_roster → 主办 character_id 列表（保序去重；解码失败→[]）。"""
    import json
    try:
        roster = json.loads(raw or "[]") if not isinstance(raw, list) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(roster, list):
        return []
    leads: List[str] = []
    seen: set = set()
    for item in roster:
        if not isinstance(item, dict):
            continue
        if str(item.get("tier") or "").strip() != "主办":
            continue
        name = str(item.get("character_id") or "").strip()
        if name and name not in seen:
            seen.add(name)
            leads.append(name)
    return leads


def _load_executing_host_leads(conn) -> List[Tuple[str, List[str]]]:
    """一次装载 executing 案卷的 (region_id, 主办 leads)。"""
    rows = conn.execute(
        "SELECT region_id, participant_roster FROM decree_dossiers "
        "WHERE status='executing' ORDER BY region_id, id",
    ).fetchall()
    return [
        (str(row["region_id"] or ""), _host_leads_from_roster(row["participant_roster"]))
        for row in rows
    ]


def _province_open_counts(conn) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT region_id, COUNT(*) AS n FROM decree_dossiers "
        "WHERE status='executing' GROUP BY region_id",
    ).fetchall()
    return {str(r["region_id"] or ""): int(r["n"]) for r in rows}


def _in_transit_name_index(transit_semantics: Sequence[object]) -> set:
    """派生 name 成员索引（查找结构，非第二真源 collection）。"""
    return {str(item["name"]).strip() for item in transit_semantics}


def _duty_arrival_status(
    *,
    owner_name: str,
    location: str,
    duty_region_id: str,
    in_transit_names: set,
) -> Optional[str]:
    """#673 r3 B：在途 / 已到差 / 尚未到差；空端省略（返回 None）。"""
    if owner_name in in_transit_names:
        return "在途"
    loc = str(location or "").strip()
    rid = str(duty_region_id or "").strip()
    if not loc or not rid:
        return None
    if loc == rid:
        return "已到差"
    return "尚未到差"


def _project_owner_arrival_for_region(
    *,
    rid: str,
    owner_names: Sequence[str],
    char_rows: Mapping[str, object],
    owner_counts: Mapping[str, int],
    matrix: DistanceMatrix,
    in_transit_names: set,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """一省主办行 + 到差态行投影（builder 局部职责）。"""
    owner_rows: List[Dict[str, object]] = []
    arrival_rows: List[Dict[str, object]] = []
    for name in owner_names:
        ch = char_rows.get(name)
        ability = int(ch["ability"]) if ch is not None else 0
        open_count = int(owner_counts.get(name, 0))
        loc = str(ch["location"] or "") if ch is not None else ""
        transit = str(ch["transit_to"] or "") if ch is not None else ""
        if rid == "":
            dist = ABSENT
        else:
            dist = distance_semantic_band(
                owner_location=loc,
                region_id=rid,
                transit_to=transit,
                matrix=matrix,
            )
        owner_rows.append({
            "owner_name": name,
            "owner_open_count": open_count,
            "owner_ability": ability,
            "owner_load": open_count * ability,
            "distance_semantic_band": dist,
        })
        status = _duty_arrival_status(
            owner_name=name,
            location=loc,
            duty_region_id=rid,
            in_transit_names=in_transit_names,
        )
        if status is not None:
            arrival_rows.append({
                "owner_name": name,
                "duty_region_id": rid,
                "duty_arrival_status": status,
            })
    return owner_rows, arrival_rows


def _assemble_province_block(
    conn,
    rid: str,
    owner_rows: Sequence[Mapping[str, object]],
    arrival_rows: Sequence[Mapping[str, object]],
    province_counts: Mapping[str, int],
) -> Dict[str, object]:
    """单省 block 装配（哨兵块 vs 读 regions / 切片 / 督抚 / 贼 / 灾）。"""
    if rid == "":
        return {
            "region_id": "",
            "province_open_count": ABSENT,
            "gentry_resistance": ABSENT,
            "gentry_slice": ABSENT,
            "officials_slice": ABSENT,
            "dutang_faction": ABSENT,
            "dutang_integrity": ABSENT,
            "bandit_pressure": ABSENT,
            "bandit_strength": ABSENT,
            "disaster_rows": [],
            "owners": list(owner_rows),
            "arrival_rows": list(arrival_rows),
        }

    reg = conn.execute(
        "SELECT gentry_resistance, military_pressure FROM regions WHERE id=?",
        (rid,),
    ).fetchone()
    gentry_res = int(reg["gentry_resistance"]) if reg is not None else 0
    bandit_pressure = int(reg["military_pressure"]) if reg is not None else 0
    dutang_faction, dutang_integrity = _dutang_fields(conn, rid)
    return {
        "region_id": rid,
        "province_open_count": int(province_counts.get(rid, 0)),
        "gentry_resistance": gentry_res,
        "gentry_slice": _class_slice(conn, "士绅", rid),
        "officials_slice": _class_slice(conn, "官僚", rid),
        "dutang_faction": dutang_faction,
        "dutang_integrity": dutang_integrity,
        "bandit_pressure": bandit_pressure,
        "bandit_strength": _bandit_strength(conn, rid),
        "disaster_rows": _disaster_rows(conn, rid),
        "owners": list(owner_rows),
        "arrival_rows": list(arrival_rows),
    }


def build_execution_two_axis_surface(
    db,
    turn: int = 0,
    *,
    transit_semantics: Sequence[object],
) -> Dict[str, object]:
    """接口层纯函数：DB 状态 → 两轴清单（结构化 + TSV 文本）。

    只读；零 LLM / 零时钟 / 零随机。turn 保留签名位（调用方对齐），不参与计算。
    builder 内一次装载距离矩阵并经参下传（r3-A.1）。
    transit_semantics：phase1 既成 collection 引用（#669）；必需形参，无默认回落。
    """
    del turn  # 清单只读当前 executing 态，不按 turn 过滤
    conn = db.conn
    matrix = _load_distance_matrix()
    province_counts = _province_open_counts(conn)
    in_transit_names = _in_transit_name_index(transit_semantics)

    # executing roster 一次装载 → owner 负荷 + 按省主办两路派生
    executing_leads = _load_executing_host_leads(conn)
    owner_counts: Dict[str, int] = {}
    owners_by_region: Dict[str, List[str]] = {}
    for rid, leads in executing_leads:
        for name in leads:
            owner_counts[name] = owner_counts.get(name, 0) + 1
        bucket = owners_by_region.setdefault(rid, [])
        seen = set(bucket)
        for name in leads:
            if name not in seen:
                seen.add(name)
                bucket.append(name)

    # 角色能力/位置一次拉取
    char_rows = {
        str(r["name"]): r
        for r in conn.execute(
            "SELECT name, ability, location, transit_to, faction, integrity "
            "FROM characters",
        ).fetchall()
    }

    # 所有 executing 差务涉及的省（含 ''）
    region_ids = [
        str(r["region_id"] or "")
        for r in conn.execute(
            "SELECT DISTINCT region_id FROM decree_dossiers "
            "WHERE status='executing' ORDER BY region_id",
        ).fetchall()
    ]

    provinces: List[Dict[str, object]] = []
    for rid in region_ids:
        owner_rows, arrival_rows = _project_owner_arrival_for_region(
            rid=rid,
            owner_names=owners_by_region.get(rid, []),
            char_rows=char_rows,
            owner_counts=owner_counts,
            matrix=matrix,
            in_transit_names=in_transit_names,
        )
        provinces.append(
            _assemble_province_block(
                conn, rid, owner_rows, arrival_rows, province_counts,
            ),
        )

    tsv = _render_two_axis_tsv(provinces)
    return {
        "provinces": provinces,
        "tsv": tsv,
    }


def _escape_tsv_cell(value: object) -> str:
    """TSV transport only: reversible encode of field/record separators."""
    s = str(value)
    return (
        s.replace("\\", "\\\\")
         .replace("\t", "\\t")
         .replace("\n", "\\n")
         .replace("\r", "\\r")
    )


def _tsv_data_row(cells: Sequence[object]) -> str:
    """Join one 20-cell data row with per-cell transport escaping."""
    return "\t".join(_escape_tsv_cell(c) for c in cells)


def _render_two_axis_tsv(provinces: Sequence[Mapping[str, object]]) -> str:
    """一省一块投影：灾情行 → 省盘 → 主办行 → 到差态行；无全局重排。20 列 ABI。"""
    header = (
        "行类\t省\t省在办数\t士绅阻力\t流寇压力\t贼强度\t督抚派系\t督抚操守"
        "\t士绅盘\t官僚盘\t主办\t在办数\t能力\t负荷\t距离档"
        "\t灾情id\t灾种\t严重度\t标题\t到差态"
    )
    lines: List[str] = [
        "## 差务两轴清单（TSV；带宽=忙→拖磨，阻力=顶→变形）",
        header,
    ]
    for block in provinces:
        rid = str(block.get("region_id") or "") or "（非属地）"
        # ① 本省灾情行（builder 已 severity DESC, id ASC）
        for dis in block.get("disaster_rows") or []:
            if not isinstance(dis, Mapping):
                continue
            lines.append(
                _tsv_data_row([
                    "灾情",
                    rid,
                    "", "", "", "", "", "",
                    "", "",
                    "", "", "", "", "",
                    str(dis.get("id")),
                    str(dis.get("kind") or ""),
                    str(dis.get("severity")),
                    str(dis.get("title") or ""),
                    "",  # 到差态
                ])
            )
        # ② 省摘要行（含 gentry_slice / officials_slice）
        lines.append(
            _tsv_data_row([
                "省盘",
                rid,
                str(block.get("province_open_count")),
                str(block.get("gentry_resistance")),
                str(block.get("bandit_pressure")),
                str(block.get("bandit_strength")),
                str(block.get("dutang_faction")),
                str(block.get("dutang_integrity")),
                _format_class_slice(block.get("gentry_slice")),
                _format_class_slice(block.get("officials_slice")),
                "", "", "", "", "",
                "", "", "", "",
                "",  # 到差态
            ])
        )
        # ③ 主办行
        for own in block.get("owners") or []:
            if not isinstance(own, Mapping):
                continue
            lines.append(
                _tsv_data_row([
                    "主办",
                    rid,
                    "", "", "", "", "", "",
                    "", "",
                    str(own.get("owner_name") or ""),
                    str(own.get("owner_open_count")),
                    str(own.get("owner_ability")),
                    str(own.get("owner_load")),
                    str(own.get("distance_semantic_band") or ""),
                    "", "", "", "",
                    "",  # 到差态
                ])
            )
        # ④ 到差态行（与 arrival_rows 1:1；仅填 省/主办/到差态）
        for arr in block.get("arrival_rows") or []:
            lines.append(
                _tsv_data_row([
                    "到差态",
                    rid,
                    "", "", "", "", "", "",
                    "", "",
                    str(arr.get("owner_name") or ""),
                    "", "", "", "",
                    "", "", "", "",
                    str(arr.get("duty_arrival_status") or ""),
                ])
            )
    return "\n".join(lines)
