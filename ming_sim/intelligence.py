"""近臣回奏的确定性内容 seam（#492）。

回奏只从持久化盘面读取事实，并把来源限制为固定的查访/见闻 provider。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


OFFICE_SLOTS = (
    ("陕西巡抚", "督抚", "shaanxi", "陕西"),
    ("三边总督", "督抚", "shaanxi", "陕西、甘肃、宁夏"),
    ("蓟辽总督", "督抚", "liaodong", "蓟州、辽东"),
    ("宣大总督", "督抚", "shanxi", "宣府、大同"),
    ("山西巡抚", "督抚", "shanxi", "山西"),
    ("河南巡抚", "督抚", "henan", "河南"),
    ("山东巡抚", "督抚", "shandong", "山东"),
    ("登莱巡抚", "督抚", "deng_lai", "登莱"),
    ("湖广巡抚", "督抚", "huguang", "湖广"),
    ("四川巡抚", "督抚", "sichuan", "四川"),
    ("福建巡抚", "督抚", "fujian", "福建"),
    ("广东巡抚", "督抚", "guangdong", "广东"),
    ("两广总督", "督抚", "guangdong", "两广"),
)


def _vacancy_statement(rows: Iterable[Mapping[str, Any]], query: str) -> str:
    text = str(query or "")
    rows = list(rows)
    matches = [row for row in rows if str(row["office_title"]) in text]
    if not matches:
        matches = [row for row in rows if any(
            part and part in text for part in str(row.get("jurisdiction") or "").split("、")
        ) or str(row.get("region_id") or "") in text]
    if not matches:
        return "近臣暂未查到与所问相符的督抚官缺。"
    return "".join(
        f"{row['office_title']}{'现由' + str(row['holder_name']) + '任事。' if row.get('holder_name') else '当前虚悬。'}"
        for row in matches
    )


def _query_domain(query: str) -> str:
    text = str(query or "")
    if any(word in text for word in ("欠饷", "欠薪", "军饷", "饷银")):
        return "arrears"
    if any(word in text for word in ("流寇", "流贼", "贼情", "匪情", "贼势")):
        return "bandits"
    if any(word in text for word in ("军情", "敌情", "边情", "兵势", "战事")):
        return "military"
    return "office"


def _qualitative_domain_statement(db: Any, query: str) -> tuple[str, str]:
    """Read one existing substrate, keeping machine-valued fields out of payload."""
    domain = _query_domain(query)
    if domain == "office":
        return _vacancy_statement(db.list_office_vacancies(), query), "office_vacancies"
    if domain == "arrears":
        rows = db.conn.execute(
            "SELECT name, arrears FROM armies WHERE owner_power='ming' ORDER BY name"
        ).fetchall()
        owing = [str(row["name"]) for row in rows if float(row["arrears"] or 0) > 0]
        return (
            ("军籍所载仍有欠饷的军镇：" + "、".join(owing) + "。" if owing
             else "军籍所载各镇目前未见有欠饷记录。"),
            "armies",
        )
    rows = db.power_rows(exclude_self=True)
    if domain == "bandits":
        rows = [row for row in rows if any(word in (
            str(row["kind"] or "") + str(row["id"] or "") + str(row["name"] or "")
        ) for word in ("bandit", "贼", "流寇"))]
    if not rows:
        return "军情簿暂未载有与所问相符的势力。", "powers"
    return "".join(
        f"{row['name']}当前{row['stance']}，局面为{row['status']}；近况：{row['last_action'] or '尚无新动'}。"
        for row in rows
    ), "powers"


def _canonical_source_ref(source_kind: str, source_ref: Optional[str], domain_ref: str) -> str:
    """Canonicalize provider metadata; arbitrary caller text is never echoed."""
    if source_kind == "inquiry":
        # Keep the historical public label stable while deriving the actual
        # domain substrate independently of it.
        if source_ref == "吏部查访":
            return "吏部查访"
        provider = "查访"
    elif source_kind == "firsthand":
        provider = "见闻"
    else:
        raise ValueError("回奏来源必须是 firsthand 或 inquiry")
    return f"{provider}/{domain_ref}"


def build_return_report(
    db: Any,
    query: str,
    *,
    source_kind: str,
    source_ref: Optional[str] = None,
) -> Dict[str, str]:
    """Build a traceable report without a minister-reply dependency."""
    if source_kind not in {"firsthand", "inquiry"}:
        raise ValueError("回奏来源必须是 firsthand 或 inquiry")
    statement, domain_ref = _qualitative_domain_statement(db, query)
    return {
        "source_kind": source_kind,
        "source_ref": _canonical_source_ref(source_kind, source_ref, domain_ref),
        "subject": "查访" if source_kind == "inquiry" else "见闻",
        "statement": statement,
    }


build_return_report.parallel_safe = True
build_return_report.dependencies = frozenset()
