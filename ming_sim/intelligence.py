"""近臣回奏的确定性内容 seam（#492）。

回奏只从持久化盘面读取事实，并把来源限制为固定的查访/见闻 provider。
"""

from __future__ import annotations

import re
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


def source_kind_for_query(query: str) -> str:
    """Classify the durable channel implied by the emperor's wording."""
    text = str(query or "")
    return "inquiry" if any(word in text for word in ("查访", "密查", "查问", "访查")) else "firsthand"


def _safe_report_text(text: object) -> str:
    """Keep reusable report prose qualitative at the audience boundary."""
    return re.sub(r"[-+]?\d+(?:\.\d+)?%?", "若干", str(text or ""))


def _qualitative_domain_statement(db: Any, query: str) -> tuple[str, str]:
    """Read the existing domain presentation seams, keeping values out of payload."""
    domain = _query_domain(query)
    if domain == "office":
        return _vacancy_statement(db.list_office_vacancies(), query), "office_vacancies"
    if domain == "arrears":
        return _safe_report_text(db.army_report(limit=10)), "armies"
    if domain == "bandits":
        # power_report is the existing qualitative military-intelligence seam;
        # use its domain filter so a bandit question cannot receive every
        # foreign power's report.
        return _safe_report_text(db.power_report(exclude_self=True, kinds={"bandit", "bandits"})), "powers"
    return _safe_report_text(db.power_report(exclude_self=True)), "powers"


def _canonical_source_ref(source_kind: str, source_ref: Optional[str], domain_ref: str) -> str:
    """Canonicalize provider metadata; arbitrary caller text is never echoed."""
    if source_kind == "inquiry":
        # The office channel has a stable historical provider label, but it is
        # selected from the queried substrate rather than trusted caller text.
        if domain_ref == "office_vacancies":
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
    source_kind: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> Dict[str, str]:
    """Build a traceable report without a minister-reply dependency."""
    source_kind = source_kind or source_kind_for_query(query)
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
