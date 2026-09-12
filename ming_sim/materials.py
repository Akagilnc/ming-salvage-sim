"""Character-call material directory (#1830 / ADR 0155).

The mediation layer writes human-readable files the model may open on demand.
Opening context stays the minimum set; the directory is the rest. CLI uses
this directory as cwd with read-only tools; API uses list/read on the same
tree. Rebuild from the world record + persisted night turns — never from a
live agent session.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_INDEX_NAME = "INDEX.txt"
_PERSON_DIR = "人物"
_AFFAIR_DIR = "事务"
_PUBLIC_DIR = "公开说法"
_REGION_DIR = "地区"
_ARMY_DIR = "军队"
_SECRET_DIR = "密令"
_RECOMMEND_DIR = "荐人"
_FACT_DIR = "事实"
_COURT_ROSTER_REL = f"{_PERSON_DIR}/朝臣名册.txt"


@dataclass(frozen=True)
class PreparedMaterials:
    root: Path
    opening: str
    index_lines: tuple[str, ...]


def _safe_segment(name: object) -> str:
    """Readable, path-safe text identity with a collision-resistant suffix."""
    text = str(name or "").strip() or "未名"
    clean = _UNSAFE.sub("_", text).strip()
    if clean in {"", ".", ".."}:
        clean = "未名"
    digest = hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"{clean[:48]}-{digest}"


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(body or "").rstrip() + "\n", encoding="utf-8")


def _resolve_inside(root: Path, rel: str) -> Path:
    root_r = root.resolve()
    raw = str(rel or "").strip()
    if not raw or raw in {".", "./"}:
        return root_r
    if Path(raw).is_absolute() or raw.startswith("~"):
        raise ValueError("材料路径越出目录")
    candidate = (root_r / raw).resolve()
    try:
        candidate.relative_to(root_r)
    except ValueError as exc:
        raise ValueError("材料路径越出目录") from exc
    return candidate


def character_materials_root(db: Any, state: Any, character: Any) -> Path:
    from ming_sim.audience_night import get_open_night

    parent = Path(str(getattr(db, "path", "") or ".")).resolve().parent
    night = get_open_night(db)
    key = f"night-{int(night['id'])}" if night else f"turn-{int(state.turn)}"
    return parent / "materials" / key / _safe_segment(getattr(character, "name", ""))


def list_materials(root: Path, path: str = "") -> List[str]:
    base = _resolve_inside(root, path)
    root_r = Path(root).resolve()
    if not base.exists():
        return []
    if base.is_file():
        return [str(base.relative_to(root_r)).replace("\\", "/")]
    out: List[str] = []
    for item in sorted(base.rglob("*")):
        if item.is_file():
            out.append(str(item.relative_to(root_r)).replace("\\", "/"))
    return out


def read_material(root: Path, path: str) -> str:
    target = _resolve_inside(root, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    return target.read_text(encoding="utf-8")


def material_tools(root: Path) -> list:
    """API-channel list/read tools bound to one prepared directory."""

    def list_materials_tool(path: str = "") -> str:
        """列出当前材料目录中可读的文件（相对路径，一行一项）。"""
        return "\n".join(list_materials(root, path))

    def read_material_tool(path: str) -> str:
        """读取材料目录中的一份人读文本。path 为相对路径，如 人物/某人/经历.txt。"""
        try:
            return read_material(root, path)
        except (ValueError, FileNotFoundError) as exc:
            return f"无法读取：{exc}"

    list_materials_tool.__name__ = "list_materials"
    read_material_tool.__name__ = "read_material"
    return [list_materials_tool, read_material_tool]


def _present_names(db: Any, character: Any) -> List[str]:
    from ming_sim.audience_night import get_open_night, present_names_at

    name = str(getattr(character, "name", "") or "")
    night = get_open_night(db)
    if night is None:
        return [name] if name else []
    names = sorted(present_names_at(db, int(night["id"])))
    return names or ([name] if name else [])


def _spoken_this_scene(db: Any, character: Any) -> str:
    from ming_sim.audience_night import audience_scene_recap

    return str(audience_scene_recap(db, getattr(character, "name", "")) or "").strip()


def _visible_affair_lines(knowledge: dict) -> list[dict[str, object]]:
    """Material matters are exactly the already-authorized knowledge projection."""
    lines: list[dict[str, object]] = []
    for issue in knowledge.get("issues") or []:
        issue_id = int(issue.get("id") or 0)
        title = str(issue.get("title") or "").strip()
        if issue_id <= 0 or not title:
            continue
        lines.append({
            "id": issue_id,
            "affair_id": int(issue.get("affair_id") or 0),
            "title": title,
            "situation": str(issue.get("stage_text") or "").strip() or "见目录。",
            "resolve_condition": str(issue.get("resolve_condition") or "").strip(),
            "fail_condition": str(issue.get("fail_condition") or "").strip(),
            "source_id": str(issue.get("source_id") or f"issue:{issue_id}"),
            "audience_names": tuple(issue.get("audience_names") or ()),
            "participant_roster": issue.get("participant_roster") or "[]",
        })
    return lines


def _handled_affair_lines(
    db: Any, state: Any, character_name: str, issue_materials: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Filter canonical visible issue materials to matters this character handles."""
    from ming_sim.participant_roster import participant_roster_names

    return [
        item for item in issue_materials
        if character_name in participant_roster_names(item.get("participant_roster"))
    ]


def _carryover_drafts(db: Any, state: Any) -> list[dict]:
    if not hasattr(db, "list_directives"):
        return []
    return [
        dict(row) for row in db.list_directives(state, statuses=("draft",))
        if int(row["turn"]) < int(state.turn)
        and (
            not hasattr(db, "get_dossier_for_directive")
            or db.get_dossier_for_directive(int(row["id"])) is None
        )
    ]


def minimal_opening_context(
    character: Any,
    state: Any,
    present: Sequence[str],
    affairs: Sequence[dict[str, object]],
    spoken: str,
) -> str:
    """Canonical minimal opening: identity/office, present, date, affairs, spoken."""
    name = str(getattr(character, "name", "") or "")
    office = str(getattr(character, "office", "") or "")
    parts = [
        f"身份：{name}，{office}",
        f"在场：{'、'.join(present) if present else name}",
        f"日期：{int(state.year)}年{int(state.period)}月",
    ]
    if affairs:
        parts.append("正经手事务：")
        parts.extend(
            f"- #{item['id']} {item['title']}：{item['situation']}"
            for item in affairs
        )
    else:
        parts.append("正经手事务：（无）")
    parts.append("本场已说的话：")
    parts.append(spoken if spoken else "（尚无）")
    parts.append("材料在当前目录。根目录 INDEX 一行一项。其余想读自己读。")
    return "\n".join(parts)


def _world_has_domain(knowledge: dict, domain: str) -> bool:
    world = knowledge.get("world") or {}
    return bool(str(world.get(domain) or "").strip())


def _write_secret_order_file(tmp: Path, db: Any, state: Any, character: Any) -> str | None:
    from ming_sim.models import CourtContext
    from ming_sim.registry import build_secret_order_brief

    brief = build_secret_order_brief(character, CourtContext(state=state, db=db))
    rel = f"{_SECRET_DIR}/进行中.txt"
    _write_text(tmp / rel, brief or "（无进行中密令）")
    return rel


def _write_recommendation_file(tmp: Path, db: Any, state: Any, character: Any) -> str | None:
    from ming_sim.recommendations import build_recommendation_brief

    brief = build_recommendation_brief(db, state, str(getattr(character, "name", "") or ""))
    rel = f"{_RECOMMEND_DIR}/可荐人切片.txt"
    _write_text(tmp / rel, brief or "【可荐人切片】本大臣眼下没有可据以具名荐人的人选。")
    return rel


def _write_textual_fact_files(
    tmp: Path, db: Any, character: Any, knowledge: dict,
    issue_materials: Sequence[dict[str, object]],
) -> list[str]:
    store = getattr(db, "textual_facts", None)
    readable = getattr(store, "readable_materials", None)
    if not callable(readable):
        return []
    subjects: list[tuple[str, str, str]] = []
    name = str(getattr(character, "name", "") or "")
    if name:
        subjects.append(("character", name, name))
    if _world_has_domain(knowledge, "regional") and hasattr(db, "region_rows"):
        for row in db.region_rows():
            rid = str(row["id"] or "")
            rname = str(row["name"] or rid)
            if rid:
                subjects.append(("region", rid, rname))
    if _world_has_domain(knowledge, "military") and hasattr(db, "army_rows"):
        for row in db.army_rows():
            aid = str(row["id"] or "")
            aname = str(row["name"] or aid)
            if aid:
                subjects.append(("army", aid, aname))
    for item in issue_materials:
        affair_id = int(item.get("affair_id") or 0)
        if affair_id > 0:
            subjects.append(("affair", str(affair_id), str(item.get("title") or affair_id)))
    index: list[str] = []
    seen: set[tuple[str, str]] = set()
    for kind, subject_id, label in subjects:
        key = (kind, subject_id)
        if key in seen:
            continue
        seen.add(key)
        facts = readable(subject_kind=kind, subject_id=subject_id)
        if not facts:
            continue
        body = "\n".join(str(fact.body or "").strip() for fact in facts if str(fact.body or "").strip())
        if not body:
            continue
        rel = f"{_FACT_DIR}/{kind}-{_safe_segment(label)}.txt"
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


def _write_region_detail_files(tmp: Path, db: Any, knowledge: dict) -> list[str]:
    if not _world_has_domain(knowledge, "regional") or not hasattr(db, "region_rows"):
        return []
    index: list[str] = []
    for row in db.region_rows():
        name = str(row["name"] or row["id"] or "")
        if not name:
            continue
        detail = db.region_detail(name, qualitative=True)
        rel = f"{_REGION_DIR}/{_safe_segment(name)}/详情.txt"
        _write_text(tmp / rel, detail)
        index.append(rel)
    return index


def _write_army_detail_files(tmp: Path, db: Any, knowledge: dict) -> list[str]:
    if not _world_has_domain(knowledge, "military") or not hasattr(db, "army_rows"):
        return []
    index: list[str] = []
    for row in db.army_rows():
        name = str(row["name"] or "")
        army_id = str(row["id"] or "")
        key = name or army_id
        if not key:
            continue
        # army_detail leaks raw firearm numbers; qualitative roster is the P4-safe renderer.
        detail = db.army_roster(
            filter_names=[name or army_id, army_id],
            qualitative_equipment=True,
        )
        rel = f"{_ARMY_DIR}/{_safe_segment(key)}/详情.txt"
        _write_text(tmp / rel, detail or str(row["status"] or ""))
        index.append(rel)
    return index


def _court_roster_text(db: Any, state: Any, character: Any, knowledge: dict) -> str:
    """Processed court roster for on-demand read (retired query_court_roster)."""
    from ming_sim.knowledge import project_court_roster_rows

    office_type = str(
        knowledge.get("office_type") or getattr(character, "office_type", "") or ""
    )
    rows: list[Any] = []
    if hasattr(db, "current_court_roster_rows"):
        rows = project_court_roster_rows(
            db.current_court_roster_rows(state),
            knowledge,
            office_type,
        )
    if not rows:
        return "见闻中未载所查人物。"
    return "【在朝人事索引】\n" + "\n".join(
        f"{row['name']}：{row['office'] or '无现任官职'}，{row['status']}"
        for row in rows
    )


def _write_tree(
    tmp: Path, db: Any, state: Any, character: Any, knowledge: dict,
    issue_materials: Sequence[dict[str, object]],
) -> list[str]:
    from ming_sim.decree_vocabulary import render_referenceable_dossier_brief
    from ming_sim.knowledge import render_character_knowledge

    name = str(getattr(character, "name", "") or "")
    index: list[str] = []

    _write_text(tmp / _COURT_ROSTER_REL, _court_roster_text(db, state, character, knowledge))
    index.append(_COURT_ROSTER_REL)

    person_dir = tmp / _PERSON_DIR / _safe_segment(name)
    private_events = knowledge.get("events") or []
    experience_lines = []
    for item in private_events:
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if title or body:
            experience_lines.append(f"{title}：{body}".strip("："))
    _write_text(person_dir / "经历.txt", "\n".join(experience_lines) or "（无）")
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/经历.txt")

    world = dict(knowledge.get("world") or {})
    world.pop("public", None)
    office_lines = [
        f"{key}：{value}"
        for key, value in world.items()
        if str(value or "").strip()
    ]
    if hasattr(db, "list_referenceable_dossiers"):
        brief = render_referenceable_dossier_brief(
            db.list_referenceable_dossiers(name, state.turn),
        )
        if brief:
            office_lines.append(brief)
    _write_text(person_dir / "公事档案.txt", "\n".join(office_lines) or "（无）")
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/公事档案.txt")

    # Keep a full processed projection in the directory for on-demand read;
    # this is mediation output, not a raw world-library dump.
    rendered = render_character_knowledge(
        knowledge, name, db=db, state=state,
    )
    if rendered:
        _write_text(person_dir / "见闻.txt", rendered)
        index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/见闻.txt")

    for item in issue_materials:
        segment = f"issue-{int(item['id'])}"
        affair_dir = tmp / _AFFAIR_DIR / segment
        details = [
            f"事项ID：{item['id']}",
            f"事务ID：{item['affair_id']}" if item["affair_id"] else "",
            f"标题：{item['title']}",
            f"当前情况：{item['situation']}",
            f"办结条件：{item['resolve_condition']}" if item["resolve_condition"] else "",
            f"失败条件：{item['fail_condition']}" if item["fail_condition"] else "",
        ]
        _write_text(affair_dir / "当前情况.txt", "\n".join(x for x in details if x))
        index.append(f"{_AFFAIR_DIR}/{segment}/当前情况.txt")

    for row in _carryover_drafts(db, state):
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row.get("text") or "").strip()
        _write_text(
            tmp / _AFFAIR_DIR / _safe_segment(title) / "当前情况.txt",
            f"{body}（尚未入档）" if body else "尚未入档",
        )
        index.append(f"{_AFFAIR_DIR}/{_safe_segment(title)}/当前情况.txt")

    public_by_month: dict[tuple[int, int], list[str]] = {}
    for item in knowledge.get("public_events") or []:
        year = int(item.get("year") or 0)
        period = int(item.get("period") or 0)
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not (title or body):
            continue
        public_by_month.setdefault((year, period), []).append(f"{title}：{body}".strip("："))
    for (year, period), lines in sorted(public_by_month.items()):
        fname = f"{year}年{period}月.txt" if year and period else "未标年月.txt"
        _write_text(tmp / _PUBLIC_DIR / fname, "\n".join(lines))
        index.append(f"{_PUBLIC_DIR}/{fname}")

    secret_rel = _write_secret_order_file(tmp, db, state, character)
    if secret_rel:
        index.append(secret_rel)
    recommend_rel = _write_recommendation_file(tmp, db, state, character)
    if recommend_rel:
        index.append(recommend_rel)
    index.extend(_write_textual_fact_files(tmp, db, character, knowledge, issue_materials))
    index.extend(_write_region_detail_files(tmp, db, knowledge))
    index.extend(_write_army_detail_files(tmp, db, knowledge))

    _write_text(tmp / _INDEX_NAME, "\n".join(index) if index else "")
    return index


def prepare_character_materials(
    db: Any,
    state: Any,
    character: Any,
    *,
    dest_root: Optional[Path] = None,
) -> PreparedMaterials:
    from ming_sim.knowledge import build_character_knowledge, project_issue_materials

    name = str(getattr(character, "name", "") or "")
    knowledge = {}
    if hasattr(db, "get_character_knowledge"):
        knowledge = db.get_character_knowledge(state, name)
    else:
        knowledge = build_character_knowledge(db, state, name)
    issue_materials = _visible_affair_lines({
        "issues": project_issue_materials(db, name, knowledge),
    })

    dest = Path(dest_root) if dest_root is not None else character_materials_root(db, state, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / (dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        index = _write_tree(tmp, db, state, character, knowledge, issue_materials)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    affairs = _handled_affair_lines(db, state, name, issue_materials)
    for row in _carryover_drafts(db, state):
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row.get("text") or "").strip()
        affairs.append({
            "id": f"draft-{int(row['id'])}", "title": title,
            "situation": f"{body}（尚未入档）" if body else "尚未入档",
        })
    opening = minimal_opening_context(
        character, state, _present_names(db, character), affairs, _spoken_this_scene(db, character),
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))
