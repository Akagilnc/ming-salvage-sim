"""近臣回奏的确定性内容 seam（#492）。

回奏只从持久化盘面读取事实，并把来源限制为固定的查访/见闻 provider。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, Mapping, Optional

OFFICE_SLOTS = (
    ("陕西巡抚", "督抚", "shaanxi", "陕西"),
    ("三边总督", "督抚", "shaanxi", "陕西、甘肃、宁夏"),
)


def _vacancy_statement(rows: Iterable[Mapping[str, Any]], query: str) -> tuple[str, str]:
    """Return (statement, result_kind) for an office-domain inquiry.

    result_kind is the report-export discriminator: ``known`` when at least one
    authorized office/jurisdiction matched, else ``unknown``. Callers must not
    treat an empty or unrelated statement as unknown without this flag.
    """
    text = str(query or "")
    rows = list(rows)
    matches = [row for row in rows if str(row["office_title"]) in text]
    if not matches:
        matches = [row for row in rows if any(
            part and part in text for part in str(row.get("jurisdiction") or "").split("、")
        ) or str(row.get("region_id") or "") in text]
    if not matches:
        if any(word in text for word in ("督抚", "官缺")):
            vacancies = [row for row in rows if not row.get("holder_name")]
            matches = vacancies or rows
    if not matches:
        return "近臣暂未查到与所问相符的督抚官缺。", "unknown"
    return "".join(
        f"{row['office_title']}{'现由' + str(row['holder_name']) + '任事。' if row.get('holder_name') else '当前虚悬。'}"
        for row in matches
    ), "known"


def _query_domain(query: str) -> str:
    text = str(query or "")
    if any(word in text for word in ("欠饷", "欠薪", "军饷", "饷银")):
        return "arrears"
    if any(word in text for word in ("流寇", "流贼", "贼情", "匪情", "贼势")):
        return "bandits"
    if any(word in text for word in ("军情", "敌情", "边情", "兵势", "战事")):
        return "military"
    if any(word in text for word in ("巡抚", "总督", "督抚", "官缺", "虚悬", "在任")):
        return "office"
    return ""


def source_kind_for_query(query: str) -> str:
    """Classify the durable channel implied by the emperor's wording."""
    text = str(query or "")
    return "inquiry" if any(word in text for word in ("查访", "密查", "查问", "访查")) else "firsthand"


def _report_text(text: object) -> str:
    """Carry report prose; structured readers own qualitative projection."""
    return str(text or "")


def _qualitative_domain_statement(db: Any, query: str) -> tuple[str, str, str]:
    """Read existing domain seams.

    Returns ``(statement, domain_ref, result_kind)``. ``result_kind`` is the
    public report-export discriminator (known / unknown / unsupported).
    """
    domain = _query_domain(query)
    if not domain:
        return "近臣暂不能据现有册档查明所问。", "unsupported", "unsupported"
    if domain == "office":
        statement, result_kind = _vacancy_statement(db.list_office_vacancies(), query)
        return statement, "office_vacancies", result_kind
    if domain == "arrears":
        return _report_text(db.army_report(limit=10)), "armies", "known"
    if domain == "bandits":
        # power_report is the existing qualitative military-intelligence seam;
        # use its domain filter so a bandit question cannot receive every
        # foreign power's report.
        return _report_text(db.power_report(
            # Content identifies the three rebel powers by id while their
            # display kind is "内乱".  power_report accepts either form.
            exclude_self=True, kinds={"bandit", "bandits", "内乱"}, audience=True,
        )), "powers", "known"
    return _report_text(db.power_report(exclude_self=True, audience=True)), "powers", "known"


def _character_domain_statement(db: Any, state: Any, character_name: str, query: str) -> tuple[str, str]:
    """Read a firsthand report from the character's durable knowledge rail.

    A near-minister report must not turn the global engine readers into an
    audience bypass.  Inquiry reports use the independent provider below;
    firsthand reports are limited to the role projection already granted to
    this character.
    """
    record = _matching_firsthand_record(db, state, character_name, query)
    if record is None:
        return "近臣未从自身见闻掌握所问一事。", f"knowledge_denied:{_query_domain(query)}"
    # The durable source id remains in the knowledge ledger.  The audience
    # payload gets only a qualitative label, so its provenance can be
    # explained without exposing an internal key (which may contain digits).
    return _report_text(record.get("body")), "持久见闻"


def _canonical_source_ref(source_kind: str, source_ref: Optional[str], domain_ref: str) -> str:
    """Canonicalize provider metadata; arbitrary caller text is never echoed."""
    if source_kind == "inquiry":
        # The office channel has a stable historical provider label, but it is
        # selected from the queried substrate rather than trusted caller text.
        if domain_ref == "office_vacancies":
            return "吏部查访"
        provider = "查访"
    elif source_kind == "firsthand":
        return "见闻/持久见闻"
    else:
        raise ValueError("回奏来源必须是 firsthand 或 inquiry")
    return f"{provider}/{domain_ref}"


def _domain_terms(domain: str) -> tuple[str, ...]:
    return {
        "arrears": ("欠饷", "欠薪", "军饷", "饷银"),
        "bandits": ("流寇", "流贼", "贼情", "匪情", "贼势"),
        "military": ("军情", "敌情", "边情", "兵势", "战事", "边地"),
        "office": ("官缺", "巡抚", "总督", "督抚"),
    }.get(domain, ())


def _matching_firsthand_record(
    db: Any, state: Any, character_name: str, query: str,
) -> Optional[Mapping[str, Any]]:
    """Return whether this character has a durable witness for this domain.

    A witness in another domain cannot be promoted to a source for an
    unrelated question.  The ledger predates a dedicated domain column, so
    the durable title/body vocabulary is the compatibility discriminator.
    """
    terms = _domain_terms(_query_domain(query))
    knowledge = db.get_character_knowledge(state, character_name)
    matches = [
        item for item in [*(knowledge.get("events") or []), *(knowledge.get("public_events") or [])]
        if str(item.get("kind") or "") in {"witness", "scout", "firsthand"}
        and any(term in f"{item.get('title') or ''}{item.get('body') or ''}" for term in terms)
        and str(item.get("body") or "").strip()
    ]
    # Knowledge readers are chronological, so next() selected the oldest
    # witness after an update.  Turn plus ledger order is the durable recency
    # contract; enumeration makes equal-turn records deterministic.
    return max(enumerate(matches), key=lambda pair: (int(pair[1].get("turn") or 0), pair[0]))[1] if matches else None


def build_return_report(
    db: Any,
    query: str,
    *,
    source_kind: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> Dict[str, str]:
    """Build a traceable report without a minister-reply dependency."""
    requested_kind = source_kind or source_kind_for_query(query)
    if requested_kind not in {"firsthand", "inquiry"}:
        raise ValueError("回奏来源必须是 firsthand 或 inquiry")
    # This seam has no character/state argument, so it cannot verify a
    # minister's durable witness.  Never let wording or a caller label mint
    # a firsthand report; the production, role-scoped seam below performs the
    # witness check before selecting firsthand.
    source_kind = "inquiry"
    statement, domain_ref, result_kind = _qualitative_domain_statement(db, query)
    return {
        "source_kind": source_kind,
        "source_ref": _canonical_source_ref(source_kind, source_ref, domain_ref),
        "subject": "查访" if source_kind == "inquiry" else "见闻",
        "statement": statement,
        # Report-export discriminator: office hit vs office miss vs unsupported.
        # Empty/unrelated statements must not satisfy an unknown contract alone.
        "result_kind": result_kind,
    }


def persist_return_report(
    db: Any, state: Any, character_name: str, query: str, *, chat_turn_id: int = 0,
) -> Dict[str, str]:
    """Persist one scoped near-minister report and return its canonical payload.

    The audience source is the durable knowledge-source row, not a caller
    supplied label.  The stable key makes repeated prompt construction
    idempotent while keeping one minister's report out of another minister's
    projection.
    """
    # An emperor's question opens the inquiry channel by default.  Firsthand
    # is allowed only when a durable witness/scout record for this domain
    # already exists; wording alone may not manufacture provenance.
    domain = _query_domain(query)
    if not domain:
        return {
            "source_kind": "unsupported", "source_ref": "unsupported",
            "subject": "未成报", "statement": "近臣暂不能据现有册档查明所问。",
            "result_kind": "unsupported",
        }
    firsthand_record = _matching_firsthand_record(db, state, character_name, query)
    requested_kind = source_kind_for_query(query)
    source_kind = (
        "firsthand"
        if requested_kind != "inquiry" and firsthand_record is not None
        else "inquiry"
    )
    if source_kind == "firsthand":
        statement, domain_ref = _character_domain_statement(db, state, character_name, query)
        result_kind = "known"
    else:
        # Keep the existing DB seam as the single deterministic inquiry
        # provider; it derives the source from the queried substrate.
        report = db.build_return_report(query, source_kind="inquiry", source_ref="")
        statement = report["statement"]
        source_ref = report["source_ref"]
        result_kind = str(report.get("result_kind") or "known")
    if source_kind == "firsthand":
        source_ref = _canonical_source_ref(source_kind, None, domain_ref)
    digest = hashlib.sha256(f"{state.turn}|{character_name}|{query}".encode()).hexdigest()[:16]
    stable_source_id = f"near_minister:{state.turn}:{digest}"
    source_id = stable_source_id
    exists = None
    if chat_turn_id:
        exists = db.conn.execute(
            "SELECT 1 FROM character_knowledge_sources WHERE source_id=?", (stable_source_id,)
        ).fetchone()
        if exists is None:
            source_id = f"{stable_source_id}:chat_turn:{int(chat_turn_id)}"
    report = {
        "source_kind": source_kind,
        "source_ref": source_ref,
        "subject": "查访" if source_kind == "inquiry" else "见闻",
        "statement": statement,
        "result_kind": result_kind,
    }
    if not chat_turn_id or source_id != stable_source_id or exists is None:
        db.register_character_knowledge_source(
            state, [{"character_id": character_name}], "return_report",
            f"近臣{report['subject']}（{source_ref}）", statement, source_id=source_id,
        )
    return report


build_return_report.parallel_safe = True
build_return_report.dependencies = frozenset()
