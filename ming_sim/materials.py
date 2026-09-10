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


def _issue_linked_affair_id(db: Any, issue_id: object) -> int:
    """ADR 0154：issue 若已指向某 affair，返回该 affair id；未挂靠返 0。"""
    store = getattr(db, "affairs", None)
    if store is None or not hasattr(store, "affair_id_for_issue"):
        return 0
    try:
        return int(store.affair_id_for_issue(int(issue_id)))
    except (KeyError, TypeError, ValueError):
        return 0


def _own_affair_lines(
    db: Any, state: Any, character_name: str, knowledge: dict,
) -> list[tuple[str, str, str, str, bool]]:
    """One durable projection per affair (#1812) — no open/closed gate, no
    separate issue-N identity for a linked issue, whatever the affair's
    status. Each line is (dir_key, title, directory_text, opening_text,
    is_handling).

    Candidate affairs = this character's dossier participation (any status —
    #1819 Resolution 3/7: an affair's full history stays queryable in its own
    directory entry after it closes) ∪ affairs whose linked issue this
    character can see (existing knowledge/audience visibility). A visible
    linked issue's own stage text is ADR 0154's "mechanical carrier" material
    for that affair — it is folded into the affair's directory_text, never
    dropped and never a second standalone identity.

    is_handling is True unconditionally for a dossier participant. Otherwise
    it mirrors the existing participant/audience "handling" gate already
    applied to ordinary (non-linked) issues, checked against whichever linked
    issue points here — this is the #1830 opening min-set's established
    criterion, unchanged by this fix; whether a closed affair with an active
    handled linked issue should count is an open product question this
    function does not decide, it only reports the gate's verdict.
    """
    from ming_sim.knowledge import _issue_audience_case_events, _issue_audience_names
    from ming_sim.participant_roster import participant_roster_names

    store = getattr(db, "affairs", None)
    if store is None or not hasattr(store, "get"):
        return []

    dossier_participant_ids: set[int] = set()
    for row in db.conn.execute(
        "SELECT affair_id, participant_roster FROM decree_dossiers WHERE affair_id != 0",
    ).fetchall():
        if character_name in participant_roster_names(row["participant_roster"]):
            dossier_participant_ids.add(int(row["affair_id"]))

    linked_material: dict[int, list[str]] = {}

    def _collect_linked(issue_id: int, title: str, body: str) -> None:
        linked_affair_id = _issue_linked_affair_id(db, issue_id)
        if not linked_affair_id:
            return
        text = f"{title}：{body}".strip("：") if (title or body) else ""
        if text:
            linked_material.setdefault(linked_affair_id, []).append(text)

    for issue in knowledge.get("issues") or []:
        try:
            issue_id = int(issue.get("id"))
        except (TypeError, ValueError):
            continue
        _collect_linked(
            issue_id, str(issue.get("title") or "").strip(),
            str(issue.get("stage_text") or "").strip(),
        )
    known_ids = {
        str(item.get("source_id") or "")
        for item in [
            *(knowledge.get("events") or []),
            *(knowledge.get("public_events") or []),
            *(knowledge.get("issues") or []),
        ]
        if item.get("source_id")
    }
    for item in _issue_audience_case_events(
        db, state, character_name, known_source_ids=known_ids,
    ):
        match = re.match(r"issue:(\d+)$", str(item.get("source_id") or ""))
        if not match:
            continue
        _collect_linked(
            int(match.group(1)), str(item.get("title") or "").strip(),
            str(item.get("body") or "").strip(),
        )

    handling_ids: set[int] = set()
    for issue in (db.list_active_issues() if hasattr(db, "list_active_issues") else []):
        try:
            issue_id = int(issue["id"])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        linked_affair_id = _issue_linked_affair_id(db, issue_id)
        if not linked_affair_id:
            continue
        try:
            roster = participant_roster_names(issue["participant_roster"])
        except (KeyError, IndexError, TypeError):
            roster = set()
        if character_name in roster or character_name in _issue_audience_names(db, issue):
            handling_ids.add(linked_affair_id)

    candidate_ids = dossier_participant_ids | set(linked_material) | handling_ids
    textual_facts = getattr(db, "textual_facts", None)
    lines: list[tuple[str, str, str, str, bool]] = []
    for affair_id in candidate_ids:
        try:
            affair = store.get(affair_id)
        except KeyError:
            continue
        facts = (
            store.current_situation(textual_facts, affair_id)
            if textual_facts is not None else ()
        )
        fact_lines = [f"{fact.occurred_month}：{fact.body}" for fact in facts]
        extra_lines = linked_material.get(affair_id) or []
        directory_lines = [*fact_lines, *extra_lines]
        directory_text = "\n".join(directory_lines) if directory_lines else "见目录。"
        if facts:
            opening_text = str(facts[-1].body or "").strip() or "见目录。"
        elif extra_lines:
            opening_text = extra_lines[0]
        else:
            opening_text = "见目录。"
        is_handling = affair_id in dossier_participant_ids or affair_id in handling_ids
        lines.append((
            f"affair-{affair_id}", str(affair.name or ""), directory_text, opening_text,
            is_handling,
        ))
    return lines


def _character_affair_lines(
    db: Any, state: Any, character_name: str, knowledge: dict,
) -> list[tuple[str, str, str, str, bool]]:
    """Matter lines for opening and the directory tree.

    Each line is (durable_dir_key, display_title, directory_text,
    opening_text, is_handling). The directory key must be collision-free
    across distinct matters — the title is display-only and never used to
    derive a path (#1812: titles differing only by an unsafe character both
    normalized to the same segment). directory_text and opening_text differ
    only for durable affairs (full dated history + folded linked-issue
    material vs latest one-liner); every other matter kind uses the same
    text for both, and carries `is_handling=False`/`True` as a fixed
    placeholder unused by callers for that kind.

    An issue already pointed at a durable affair is that affair's mechanical
    carrier (ADR 0154) — it never surfaces as a second standalone identity,
    whether the affair is open or closed (`_own_affair_lines` folds it in).
    """
    from ming_sim.knowledge import _issue_audience_case_events

    lines: list[tuple[str, str, str, str, bool]] = []
    seen: set[str] = set()
    for issue in knowledge.get("issues") or []:
        try:
            issue_id = int(issue.get("id"))
        except (TypeError, ValueError):
            continue
        if _issue_linked_affair_id(db, issue_id):
            continue
        title = str(issue.get("title") or "").strip()
        dir_key = f"issue-{issue_id}"
        if not title or dir_key in seen:
            continue
        seen.add(dir_key)
        situation = str(issue.get("stage_text") or "").strip() or "见目录。"
        lines.append((dir_key, title, situation, situation, False))
    known_ids = {
        str(item.get("source_id") or "")
        for item in [
            *(knowledge.get("events") or []),
            *(knowledge.get("public_events") or []),
            *(knowledge.get("issues") or []),
        ]
        if item.get("source_id")
    }
    for item in _issue_audience_case_events(
        db, state, character_name, known_source_ids=known_ids,
    ):
        match = re.match(r"issue:(\d+)$", str(item.get("source_id") or ""))
        if not match or _issue_linked_affair_id(db, match.group(1)):
            continue
        title = str(item.get("title") or "").strip()
        dir_key = f"issue-{match.group(1)}"
        if not title or dir_key in seen:
            continue
        seen.add(dir_key)
        situation = str(item.get("body") or "").strip() or "见目录。"
        lines.append((dir_key, title, situation, situation, False))
    for row in _carryover_drafts(db, state):
        dir_key = f"draft-{int(row['id'])}"
        if dir_key in seen:
            continue
        seen.add(dir_key)
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row.get("text") or "").strip()
        text = f"{body}（尚未入档）" if body else "尚未入档"
        lines.append((dir_key, title, text, text, True))
    for dir_key, title, directory_text, opening_text, is_handling in _own_affair_lines(
        db, state, character_name, knowledge,
    ):
        if dir_key in seen or not title:
            continue
        seen.add(dir_key)
        lines.append((dir_key, title, directory_text, opening_text, is_handling))
    return lines


def _opening_affair_lines(
    db: Any, state: Any, character_name: str, knowledge: dict,
) -> list[tuple[str, str]]:
    """Opening min-set: 正经手事务 ⊂ unique visible matter projection.

    `_character_affair_lines` already resolved each affair's single identity
    and its `is_handling` verdict (dossier participant, or a linked issue
    that passes the existing participant/audience gate). This function only
    consumes that verdict for "affair-" entries — it does not re-derive or
    change the gate itself (#1812: whether a closed affair with a still
    active, still-handled linked issue counts as opening 正经手 is an open
    product question, decided upstream/elsewhere, not here).
    """
    from ming_sim.knowledge import _issue_audience_names
    from ming_sim.participant_roster import participant_roster_names

    visible = {
        dir_key: (title, opening_text, is_handling)
        for dir_key, title, _directory_text, opening_text, is_handling
        in _character_affair_lines(db, state, character_name, knowledge)
    }
    handled: list[tuple[str, str]] = []
    seen: set[str] = set()
    active = db.list_active_issues() if hasattr(db, "list_active_issues") else []
    for issue in active:
        try:
            issue_id = int(issue["id"])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if _issue_linked_affair_id(db, issue_id):
            continue  # represented via its affair's own entry, if any.
        dir_key = f"issue-{issue_id}"
        if dir_key not in visible or dir_key in seen:
            continue
        try:
            roster = participant_roster_names(issue["participant_roster"])
        except (KeyError, IndexError, TypeError):
            roster = set()
        if character_name not in roster and character_name not in _issue_audience_names(db, issue):
            continue
        seen.add(dir_key)
        handled.append(visible[dir_key][:2])
    # Unfiled drafts are by construction things this character is handling.
    # An "affair-" entry joins only when `_character_affair_lines` already
    # marked it is_handling (dossier participant, or a linked issue's own
    # gate pass) — a merely-visible affair stays directory-only.
    for dir_key, (title, situation, is_handling) in visible.items():
        if dir_key in seen:
            continue
        if dir_key.startswith("draft-") or (dir_key.startswith("affair-") and is_handling):
            seen.add(dir_key)
            handled.append((title, situation))
    return handled


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


_LEDGER_KEYS = (
    "treasury", "military", "personnel", "construction",
    "security", "regional",
)


def character_hearing_records(knowledge: dict) -> list[dict[str, str]]:
    """可见经历与公开说法的同一批投影，不裁条数。"""
    records: list[dict[str, str]] = []
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if title or body:
            records.append({"title": title, "body": body})
    return records


def character_office_archive_text(db: Any, state: Any, character: Any, knowledge: dict) -> str:
    """本衙门公事档案：职位底账 + 可见案卷。与目录 公事档案.txt 同一份。"""
    from ming_sim.decree_vocabulary import render_referenceable_dossier_brief

    name = str(getattr(character, "name", "") or "")
    world = dict(knowledge.get("world") or {})
    office_lines = [
        f"{key}：{value}"
        for key, value in world.items()
        if key in _LEDGER_KEYS and str(value or "").strip()
    ]
    if hasattr(db, "list_referenceable_dossiers"):
        brief = render_referenceable_dossier_brief(
            db.list_referenceable_dossiers(name, state.turn),
        )
        if brief:
            office_lines.append(brief)
    return "\n".join(office_lines) or "（无）"


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
    name = str(getattr(character, "name", "") or "")
    index: list[str] = []

    _write_text(tmp / _COURT_ROSTER_REL, _court_roster_text(db, state, character, knowledge))
    index.append(_COURT_ROSTER_REL)

    person_dir = tmp / _PERSON_DIR / _safe_segment(name)
    experience_lines = []
    for item in knowledge.get("events") or []:
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if title or body:
            experience_lines.append(f"{title}：{body}".strip("："))
    _write_text(person_dir / "经历.txt", "\n".join(experience_lines) or "（无）")
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/经历.txt")

    _write_text(
        person_dir / "公事档案.txt",
        character_office_archive_text(db, state, character, knowledge),
    )
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/公事档案.txt")

    for dir_key, title, directory_text, _opening_text, _is_participant in _character_affair_lines(
        db, state, name, knowledge,
    ):
        # #1812：目录段用不碰撞的 durable id；标题只作展示，写进正文。多行的
        # （事务全部按月文字事实，ADR 0156）另起一行，单行的沿用冒号连写。
        seg = _safe_segment(dir_key)
        affair_dir = tmp / _AFFAIR_DIR / seg
        if title and "\n" in directory_text:
            body = f"{title}\n{directory_text}"
        else:
            body = f"{title}：{directory_text}".strip("：")
        _write_text(affair_dir / "当前情况.txt", body)
        index.append(f"{_AFFAIR_DIR}/{seg}/当前情况.txt")

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

    affairs = _opening_affair_lines(db, state, name, knowledge)
    opening = _opening_text(
        character, state, _present_names(db, character), affairs, _spoken_this_scene(db, character),
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))
