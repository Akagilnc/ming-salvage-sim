"""Character-call material directory (#1830 / ADR 0155).

The mediation layer writes human-readable files the model may open on demand.
Opening context stays the minimum set; the directory is the rest. CLI uses
this directory as cwd with read-only tools; API uses list/read on the same
tree. Rebuild from the world record + persisted night turns — never from a
live agent session.
"""

from __future__ import annotations

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
_GAZETTE_DIR = f"{_PUBLIC_DIR}/邸报"
_COURT_ROSTER_REL = f"{_PERSON_DIR}/朝臣名册.txt"


@dataclass(frozen=True)
class PreparedMaterials:
    root: Path
    opening: str
    index_lines: tuple[str, ...]


def _safe_segment(name: object) -> str:
    text = str(name or "").strip() or "未名"
    return _UNSAFE.sub("_", text)[:80]


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


def _visible_affair_lines(knowledge: dict) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    seen: set[str] = set()
    for issue in knowledge.get("issues") or []:
        title = str(issue.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        situation = str(issue.get("stage_text") or "").strip() or "见目录。"
        lines.append((title, situation))
    return lines


def _handled_affair_lines(db: Any, state: Any, character_name: str, knowledge: dict) -> list[tuple[str, str]]:
    from ming_sim.knowledge import _issue_audience_case_events
    from ming_sim.participant_roster import participant_roster_names

    seen: set[str] = set()
    lines: list[tuple[str, str]] = []
    active = db.list_active_issues() if hasattr(db, "list_active_issues") else []
    for issue in active:
        try:
            title = str(issue["title"] or "").strip()
        except (KeyError, IndexError, TypeError):
            continue
        if not title or title in seen:
            continue
        try:
            roster = issue["participant_roster"]
        except (KeyError, IndexError, TypeError):
            roster = []
        try:
            participants = participant_roster_names(roster)
        except (KeyError, IndexError, TypeError):
            participants = set()
        if character_name not in participants:
            continue
        seen.add(title)
        try:
            situation = str(issue["stage_text"] or "").strip() or "见目录。"
        except (KeyError, IndexError, TypeError):
            situation = "见目录。"
        lines.append((title, situation))
    known_ids = {
        str(item.get("source_id") or "")
        for item in [*(knowledge.get("events") or []), *(knowledge.get("public_events") or [])]
        if item.get("source_id")
    }
    for item in _issue_audience_case_events(
        db, state, character_name, known_source_ids=known_ids,
    ):
        title = str(item.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        situation = str(item.get("body") or "").strip() or "见目录。"
        lines.append((title, situation))
    return lines


def _carryover_drafts(db: Any, state: Any) -> list[dict]:
    if not hasattr(db, "list_directives"):
        return []
    return [
        row for row in db.list_directives(state, statuses=("draft",))
        if int(row["turn"]) < int(state.turn)
        and (
            not hasattr(db, "get_dossier_for_directive")
            or db.get_dossier_for_directive(int(row["id"])) is None
        )
    ]


def _opening_text(
    character: Any,
    state: Any,
    present: Sequence[str],
    affairs: Sequence[tuple[str, str]],
    spoken: str,
) -> str:
    name = str(getattr(character, "name", "") or "")
    office = str(getattr(character, "office", "") or "")
    parts = [
        f"身份：{name}，{office}",
        f"在场：{'、'.join(present) if present else name}",
        f"日期：{int(state.year)}年{int(state.period)}月",
    ]
    if affairs:
        parts.append("正经手事务：")
        parts.extend(f"- {title}：{situation}" for title, situation in affairs)
    else:
        parts.append("正经手事务：（无）")
    parts.append("本场已说的话：")
    parts.append(spoken if spoken else "（尚无）")
    parts.append("材料在当前目录。根目录 INDEX 一行一项。其余想读自己读。")
    return "\n".join(parts)


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


def _write_tree(tmp: Path, db: Any, state: Any, character: Any, knowledge: dict) -> list[str]:
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

    visible_affairs = _visible_affair_lines(knowledge)
    visible_titles = {title for title, _ in visible_affairs}
    for title, situation in visible_affairs:
        affair_dir = tmp / _AFFAIR_DIR / _safe_segment(title)
        _write_text(affair_dir / "当前情况.txt", situation)
        index.append(f"{_AFFAIR_DIR}/{_safe_segment(title)}/当前情况.txt")
    for title, situation in _handled_affair_lines(db, state, name, knowledge):
        if title in visible_titles:
            continue
        affair_dir = tmp / _AFFAIR_DIR / _safe_segment(title)
        _write_text(affair_dir / "当前情况.txt", situation)
        index.append(f"{_AFFAIR_DIR}/{_safe_segment(title)}/当前情况.txt")

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

    for report in db.list_turn_reports():
        if int(report["turn"]) <= 0:
            continue
        body = str(report.get("report") or "").strip()
        if not body:
            continue
        year = int(report.get("year") or 0)
        period = int(report.get("period") or 0)
        fname = (
            f"{year}年{period}月.txt"
            if year and period
            else f"turn-{int(report['turn'])}.txt"
        )
        rel = f"{_GAZETTE_DIR}/{fname}"
        _write_text(tmp / rel, body)
        index.append(rel)

    _write_text(tmp / _INDEX_NAME, "\n".join(index) if index else "")
    return index


def prepare_character_materials(
    db: Any,
    state: Any,
    character: Any,
    *,
    dest_root: Optional[Path] = None,
) -> PreparedMaterials:
    from ming_sim.knowledge import build_character_knowledge

    name = str(getattr(character, "name", "") or "")
    knowledge = {}
    if hasattr(db, "get_character_knowledge"):
        knowledge = db.get_character_knowledge(state, name)
    else:
        knowledge = build_character_knowledge(db, state, name)

    dest = Path(dest_root) if dest_root is not None else character_materials_root(db, state, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / (dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        index = _write_tree(tmp, db, state, character, knowledge)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    affairs = _handled_affair_lines(db, state, name, knowledge)
    for row in _carryover_drafts(db, state):
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row.get("text") or "").strip()
        affairs.append((title, f"{body}（尚未入档）" if body else "尚未入档"))
    opening = _opening_text(
        character, state, _present_names(db, character), affairs, _spoken_this_scene(db, character),
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))


def directory_has_raw_world_copy(root: Path, db: Any) -> bool:
    """True when the tree contains a raw world-library replica (db/json dump)."""
    root_r = Path(root).resolve()
    forbidden_suffixes = {".db", ".sqlite", ".sqlite3", ".json"}
    for item in root_r.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix.lower() in forbidden_suffixes:
            return True
        if item.name == Path(str(getattr(db, "path", "") or "")).name:
            return True
    return False
