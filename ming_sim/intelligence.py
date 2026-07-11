"""近臣回奏的确定性内容 seam（#492）。

官缺是静态职位定义上的读视图；在任者永远从 ``characters.office`` 读取。
回奏 payload 只携带叙事字符串和来源元数据，避免把引擎裸数值送进呈现层。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


# 督抚/总督级最小口径。职位定义是静态事实，当前谁在任不是这里的副本。
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
    normalized = str(query or "")
    rows = list(rows)
    exact_matches = [row for row in rows if str(row["office_title"]) in normalized]
    matches = exact_matches or [
        row
        for row in rows
        if any(
            part and part in normalized
            for part in str(row.get("jurisdiction") or "").split("、")
        )
        or str(row.get("region_id") or "") in normalized
    ]
    if not matches:
        return "近臣暂未查到与所问相符的督抚官缺。"
    statements = []
    for row in matches:
        holder = row.get("holder_name")
        if holder:
            statements.append(f"{row['office_title']}现由{holder}任事。")
        else:
            statements.append(f"{row['office_title']}当前虚悬。")
    return "".join(statements)


def build_return_report(
    db: Any,
    query: str,
    *,
    source_kind: str,
    source_ref: str,
) -> Dict[str, str]:
    """Build a traceable near-minister return without a minister reply input.

    ``source_kind`` is ``firsthand`` (near minister's own observation) or
    ``inquiry`` (delegated office investigation).  The query is answered only
    from the durable vacancy view; unknown questions are explicitly not made
    up.  All payload values are strings so the P4 boundary cannot leak raw
    engine values.
    """
    if source_kind not in {"firsthand", "inquiry"}:
        raise ValueError("回奏来源必须是 firsthand 或 inquiry")
    if not str(source_ref or "").strip():
        raise ValueError("回奏必须带可追溯来源")
    rows = db.list_office_vacancies()
    return {
        "source_kind": source_kind,
        "source_ref": str(source_ref).strip(),
        "subject": "官缺查访" if source_kind == "inquiry" else "近臣见闻",
        "statement": _vacancy_statement(rows, query),
    }


# P5：该 seam 的输入不含大臣回话，可与回话生成并行。
build_return_report.parallel_safe = True
build_return_report.dependencies = frozenset()
