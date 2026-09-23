"""Character-call material directory (#1830 / ADR 0155).

The mediation layer writes human-readable files the model may open on demand.
Opening context stays the minimum set; the directory is the rest. CLI uses
this directory as cwd with read-only tools; API uses list/read on the same
tree. Rebuild from the world record + persisted night turns — never from a
live agent session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

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
_BOARD_DIR = "盘面"
_WORLD_GAZETTE_DIR = "邸报"
_CHARACTER_GAZETTE_DIR = f"{_PUBLIC_DIR}/邸报"
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


def _materials_campaign_dir(db: Any) -> Path:
    """每档 DB 一份材料树根，避免同父目录多 .db 互踩。

    测试 `mkstemp` 与生产 `saves/*.db` 都把多档放在同一 parent；若材料只按
    night-/turn- 键挂在 parent/materials/ 下，并行 prepare 会抢同一 scene.tmp
    （Errno 2/17/66）。按 db stem 再隔一层后，各档原子重建互不影响。
    """
    db_path = Path(str(getattr(db, "path", "") or ".")).resolve()
    stem = _safe_segment(db_path.stem if db_path.suffix else db_path.name)
    return db_path.parent / "materials" / stem


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # #1812 P6：raw body 是材料自由正文，不得 rstrip——只补齐末尾换行，不削内容。
    text = str(body or "")
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


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


def _materials_invocation_dir(db: Any, state: Any) -> Path:
    from ming_sim.audience_night import get_open_night


    db_path = Path(str(getattr(db, "path", "") or ".")).resolve()
    night = get_open_night(db)
    key = f"night-{int(night['id'])}" if night else f"turn-{int(state.turn)}"
    return (
        _materials_campaign_dir(db) / key / uuid.uuid4().hex
    )


class MaterialsRoot:
    """Mutable live materials root shared by API tools and optional CLI cwd.

    Independent of whether the concrete model declares ``materials_dir``.
    """

    __slots__ = ("_root",)

    def __init__(self, root: Optional[Path | str] = "") -> None:
        self._root = str(root or "")

    @property
    def root(self) -> str:
        return self._root

    def set(self, root: Optional[Path | str]) -> str:
        previous = self._root
        self._root = str(root or "")
        return previous

    def clear(self) -> str:
        return self.set("")

    def __call__(self) -> str:
        return self._root


def _empty_uuid_invocation_parent(path: Path) -> Optional[Path]:
    parent = path.parent
    name = parent.name
    if (
        parent.exists()
        and parent.is_dir()
        and len(name) == 32
        and all(ch in "0123456789abcdef" for ch in name)
        and not any(parent.iterdir())
    ):
        return parent
    return None


def release_material_tree(root: Optional[Path | str]) -> None:
    """Release one prepared materials root and empty UUID invocation parents.

    Fail-loud on cleanup errors (ADR 0005) — callers that must continue other
    resource teardown catch and surface, never ignore_errors whitewash.
    Primary cleanup error is preserved if a secondary parent rmdir also fails.
    """
    if root is None:
        return
    path = Path(root)
    primary: BaseException | None = None
    try:
        if path.exists():
            shutil.rmtree(path)
    except BaseException as exc:
        primary = exc
    parent = _empty_uuid_invocation_parent(path)
    if parent is not None:
        try:
            parent.rmdir()
        except BaseException as exc:
            if primary is None:
                primary = exc
    if primary is not None:
        raise primary


def release_previous_material_tree(
    old_root: Optional[Path | str],
    new_root: Optional[Path | str],
) -> None:
    """After a live root handoff: best-effort release of the previous tree.

    The new root is already installed. Cleanup failure is logged with the real
    exception and must not revoke the new root or interrupt the caller
    (audience handoff). close/teardown paths call :func:`release_material_tree`
    directly and re-raise after other resources are released.
    """
    import logging

    if old_root is None:
        return
    old = str(old_root or "").strip()
    new = str(new_root or "").strip()
    if not old or old == new:
        return
    try:
        release_material_tree(old)
    except BaseException:
        logging.getLogger(__name__).exception(
            "previous materials tree cleanup failed; live root retained: %s",
            new or "(none)",
        )


def _publish_material_tree(
    dest_root: Optional[Path],
    default_root: Path,
    write_tree,
) -> tuple[Path, list[str]]:
    dest = Path(dest_root) / uuid.uuid4().hex if dest_root is not None else Path(default_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f"{dest.name}.{uuid.uuid4().hex}.tmp"
    tmp.mkdir(parents=True)
    try:
        index = write_tree(tmp)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception as original:
        # write_tree / rename primary must stay the outward exception; cleanup
        # failures only trail (ADR 0005 / materials ownership).
        cleanup_err: BaseException | None = None
        try:
            if tmp.exists():
                shutil.rmtree(tmp)
        except BaseException as exc:
            cleanup_err = exc
        parent = _empty_uuid_invocation_parent(dest)
        if parent is not None:
            try:
                parent.rmdir()
            except BaseException as exc:
                if cleanup_err is None:
                    cleanup_err = exc
        if cleanup_err is not None:
            raise original from cleanup_err
        raise original
    return dest, index


def character_materials_root(db: Any, state: Any, character: Any) -> Path:
    return _materials_invocation_dir(db, state) / _safe_segment(
        getattr(character, "name", "")
    )


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


def material_tools(root: Any) -> list:
    """API-channel list/read tools bound to the live materials root.

    ``root`` may be a Path/str or a zero-arg callable returning the current
    path so refresh can point CLI cwd and API tools at the same latest tree.
    """

    def current_root() -> Path:
        value = root() if callable(root) else root
        text = str(value or "").strip()
        if not text:
            # Empty/cleared MaterialsRoot must not resolve Path("") → CWD.
            raise ValueError("材料目录未就绪")
        return Path(text)

    def project_error(operation: str, call: Any, *args: object) -> str:
        try:
            return call(*args)
        except (ValueError, FileNotFoundError) as exc:
            return f"无法{operation}：{exc}"

    def list_materials_tool(path: str = "") -> str:
        """列出当前材料目录中可读的文件（相对路径，一行一项）。"""
        # current_root() must run inside project_error so empty-root ValueError
        # projects as structured text (never Path("") → CWD).
        return project_error(
            "读取",
            lambda value: "\n".join(list_materials(current_root(), value)),
            path,
        )

    def read_material_tool(path: str) -> str:
        """读取材料目录中的一份人读文本。path 为相对路径，如 人物/某人/经历.txt。"""
        return project_error(
            "读取",
            lambda value: read_material(current_root(), value),
            path,
        )

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

    # #1812 P6：本场对话记录是自由正文，不得 strip；判空留给调用方按需处理。
    return str(audience_scene_recap(db, getattr(character, "name", "")) or "")


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
    issue points here — the #1830 opening min-set's established criterion,
    unchanged by this fix. `AffairStore.declare_closed` (ADR 0154 decision
    key `affair-close-requires-no-active-linked-issues`) rejects closing an
    affair that still has an active linked issue, so "closed affair with a
    still-active linked issue" cannot occur — this function does not need to
    special-case it.
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
        # #1812 P6：title/body 是自由正文，判空只用局部 stripped 副本，写出用原文。
        linked_affair_id = _issue_linked_affair_id(db, issue_id)
        if not linked_affair_id:
            return
        if not (title.strip() or body.strip()):
            return
        text = f"{title}：{body}" if title and body else (title or body)
        linked_material.setdefault(linked_affair_id, []).append(text)

    for issue in knowledge.get("issues") or []:
        try:
            issue_id = int(issue.get("id"))
        except (TypeError, ValueError):
            continue
        _collect_linked(
            issue_id, str(issue.get("title") or ""),
            str(issue.get("stage_text") or ""),
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
            int(match.group(1)), str(item.get("title") or ""),
            str(item.get("body") or ""),
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
            # #1812 P6：raw body 是文字事实自由正文，不得 strip。
            raw_latest = str(facts[-1].body or "")
            opening_text = raw_latest if raw_latest.strip() else "见目录。"
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
        # #1812 P6：title/stage_text 是自由正文，判空只用局部 stripped 副本。
        title = str(issue.get("title") or "")
        dir_key = f"issue-{issue_id}"
        if not title.strip() or dir_key in seen:
            continue
        seen.add(dir_key)
        raw_situation = str(issue.get("stage_text") or "")
        situation = raw_situation if raw_situation.strip() else "见目录。"
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
        # #1812 P6：title/body 是自由正文，判空只用局部 stripped 副本。
        title = str(item.get("title") or "")
        dir_key = f"issue-{match.group(1)}"
        if not title.strip() or dir_key in seen:
            continue
        seen.add(dir_key)
        raw_situation = str(item.get("body") or "")
        situation = raw_situation if raw_situation.strip() else "见目录。"
        lines.append((dir_key, title, situation, situation, False))
    for row in _carryover_drafts(db, state):
        dir_key = f"draft-{int(row['id'])}"
        if dir_key in seen:
            continue
        seen.add(dir_key)
        title = f"尚未入档旨稿#{int(row['id'])}"
        # #1812 P6：raw body 是草稿自由正文，判空只用局部 stripped 副本。
        # sqlite3.Row / dict 同形：下标读取，禁 .get（Row 无此方法）。
        body = str(row["text"] if "text" in row.keys() else "")
        text = f"{body}（尚未入档）" if body.strip() else "尚未入档"
        lines.append((dir_key, title, text, text, True))
    for dir_key, title, directory_text, opening_text, is_handling in _own_affair_lines(
        db, state, character_name, knowledge,
    ):
        if dir_key in seen or not title:
            continue
        seen.add(dir_key)
        lines.append((dir_key, title, directory_text, opening_text, is_handling))
    return lines


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


def _opening_affair_lines(
    db: Any,
    character_name: str,
    matter_lines: list[tuple[str, str, str, str, bool]],
) -> list[tuple[str, str]]:
    """Opening min-set: 正经手事务 ⊂ unique visible matter projection.

    `matter_lines` is the one frozen `_character_affair_lines` projection
    `prepare_character_materials` already computed for this call — the
    directory tree is built from the same object (#1812: one projection per
    prepare, not a second independent recompute here). Each affair's single
    identity and `is_handling` verdict (dossier participant, or a linked
    issue that passes the existing participant/audience gate) is already
    resolved there. This function only consumes that verdict for "affair-"
    entries — it does not re-derive or change the gate itself.
    """
    from ming_sim.knowledge import _issue_audience_names
    from ming_sim.participant_roster import participant_roster_names

    visible = {
        dir_key: (title, opening_text, is_handling)
        for dir_key, title, _directory_text, opening_text, is_handling
        in matter_lines
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
    # #1812 P6：spoken 是自由正文，判空只用局部 stripped 副本，写出用原文。
    parts.append(spoken if spoken.strip() else "（尚无）")
    parts.append("材料在当前目录。根目录 INDEX 一行一项。其余想读自己读。")
    return "\n".join(parts)


def _write_secret_order_file(tmp: Path, db: Any, state: Any, character: Any) -> str | None:
    """Directory copy of the minister's active secret-order reminder.

    Logic lives here after #1833 retired the registry brief builder. Full task
    text is kept for on-demand read — no replacement length cap (#1833 AC).
    DB/read failures raise; they are not washed into an empty-business result.
    """
    name = str(getattr(character, "name", "") or "")
    orders = db.get_active_secret_orders_for_minister(name) if name else []
    if orders:
        lines = [
            "【你身上还在办的密令】",
            "★ 皇帝问进度时调 `report_secret_order_progress(order_id, progress=本月新一步进展)`：有 progress 时先暂存待确认，确认后落档；若只想查看历史则留空 progress；同月补充会修正本月行。",
            "★ 皇帝催办/加急时调 `rush_secret_order(order_id, deadline_months=1/3/0, reason=催办缘由)`：1=下月到期，3=三月内到期，0=本月到期对账。",
            "★ 自认任务办到位时调 `submit_secret_order_for_review(order_id, claim=自述办结陈词)`：缩期限至本月，月末按实进度对账。",
            "★ progress / claim 写具体事实：派谁去、查到什么、摸到哪一层、下一步指向谁。空话「待实据到手」不算。",
            "★ 大臣无权直接判 done/failed——结案由月末实进度对账派生。",
            "在册密令：",
        ]
        for o in orders:
            advanced = db._has_secret_order_period_line(
                int(o["id"]), "result", state.year, state.period,
            )
            tag = "✅ 本月已推进" if advanced else "⚠️ 本月尚未推进"
            due_turn = int(o.get("due_turn") or 0)
            due_text = (
                f"；御限剩 {max(0, due_turn - int(state.turn))} 月" if due_turn else ""
            )
            lines.append(f"  - #{o['id']}「{o['title']}」 {tag}{due_text}")
            content = str(o.get("content") or "")
            if content:
                lines.append(content)
        brief = "\n".join(lines)
    else:
        brief = ""
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
    region_ids = set((knowledge.get("scope") or {}).get("region_ids") or ())
    if region_ids and hasattr(db, "region_rows"):
        for row in db.region_rows():
            if str(row["id"] or "") not in region_ids:
                continue
            rid = str(row["id"] or "")
            rname = str(row["name"] or rid)
            if rid:
                subjects.append(("region", rid, rname))
    army_ids = set((knowledge.get("scope") or {}).get("army_ids") or ())
    if army_ids and hasattr(db, "army_rows"):
        for row in db.army_rows():
            if str(row["id"] or "") not in army_ids:
                continue
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
    region_ids = set((knowledge.get("scope") or {}).get("region_ids") or ())
    if not region_ids or not hasattr(db, "region_rows"):
        return []
    index: list[str] = []
    for row in db.region_rows():
        if str(row["id"] or "") not in region_ids:
            continue
        name = str(row["name"] or row["id"] or "")
        if not name:
            continue
        detail = db.region_detail(name, qualitative=True)
        rel = f"{_REGION_DIR}/{_safe_segment(name)}/详情.txt"
        _write_text(tmp / rel, detail)
        index.append(rel)
    return index


def _write_army_detail_files(tmp: Path, db: Any, knowledge: dict) -> list[str]:
    army_ids = set((knowledge.get("scope") or {}).get("army_ids") or ())
    if not army_ids or not hasattr(db, "army_rows"):
        return []
    index: list[str] = []
    for row in db.army_rows():
        if str(row["id"] or "") not in army_ids:
            continue
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


_LEDGER_KEYS = (
    "treasury", "military", "personnel", "construction", "regional", "command",
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


def _write_tree(
    tmp: Path, db: Any, state: Any, character: Any, knowledge: dict,
    issue_materials: Sequence[dict[str, object]],
) -> list[str]:
    from ming_sim.knowledge import render_character_knowledge

    name = str(getattr(character, "name", "") or "")
    index: list[str] = []

    _write_text(tmp / _COURT_ROSTER_REL, _court_roster_text(db, state, character, knowledge))
    index.append(_COURT_ROSTER_REL)

    person_dir = tmp / _PERSON_DIR / _safe_segment(name)
    _write_text(person_dir / "经历.txt", _experience_text(knowledge))
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/经历.txt")

    _write_text(
        person_dir / "公事档案.txt",
        character_office_archive_text(db, state, character, knowledge),
    )
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

    public_events = knowledge.get("public_events") or []
    index.extend(_write_public_by_month(tmp, public_events))
    index.extend(_write_gazette_index(
        tmp, _character_gazette_rows(public_events), prefix=_CHARACTER_GAZETTE_DIR,
    ))

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


def _experience_text(knowledge: dict, audible_entries: Sequence[dict] = ()) -> str:
    """人物经历投影：知识见闻里本人经历事件，逐条『标题：正文』连写。

    Shared by the per-character directory's own 经历.txt (#1830) and the
    world materials directory's per-character 经历.txt (#1834) — one
    projection, not two independently maintained renderings.
    """
    lines: list[str] = []
    for item in knowledge.get("events") or []:
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if title or body:
            lines.append(f"{title}：{body}".strip("："))
    lines.extend(str(item["body"]) for item in audible_entries if item.get("body"))
    return "\n".join(lines) or "（无）"


def _is_gazette_public_event(item: dict) -> bool:
    """Turn-report gazette rows have their own directory carrier; exclude from 公开说法."""
    source_id = str(item.get("source_id") or "")
    return (
        source_id.startswith("projection:turn_report:")
        or (source_id.startswith("turn_report:") and source_id.endswith(":public"))
        or (source_id.startswith("turn_report:") and not source_id.endswith(":public"))
    )


def _write_public_by_month(tmp: Path, public_events: list) -> list[str]:
    """公开说法按月分文件（#1830 既有形态，供人物目录与推演者目录共用）。

    邸报有独立目录载体，不在此再复制同一份 turn_report。
    """
    index: list[str] = []
    public_by_month: dict[tuple[int, int], list[str]] = {}
    for item in public_events or []:
        if _is_gazette_public_event(item):
            continue
        year = int(item.get("year") or 0)
        period = int(item.get("period") or 0)
        # #1812 P6：title/body 是自由正文，判空只用局部 stripped 副本，写出用原文。
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if not (title.strip() or body.strip()):
            continue
        line = f"{title}：{body}" if title and body else (title or body)
        public_by_month.setdefault((year, period), []).append(line)
    for (year, period), lines in sorted(public_by_month.items()):
        fname = f"{year}年{period}月.txt" if year and period else "未标年月.txt"
        _write_text(tmp / _PUBLIC_DIR / fname, "\n".join(lines))
        index.append(f"{_PUBLIC_DIR}/{fname}")
    return index


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

    dest, index = _publish_material_tree(
        dest_root,
        character_materials_root(db, state, character),
        lambda tmp: _write_tree(tmp, db, state, character, knowledge, issue_materials),
    )

    affairs = _handled_affair_lines(db, state, name, issue_materials)
    for row in _carryover_drafts(db, state):
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row.get("text") or "").strip()
        affairs.append({
            "id": f"draft-{int(row['id'])}", "title": title,
            "situation": f"{body}（尚未入档）" if body else "尚未入档",
        })
    from types import SimpleNamespace
    from ming_sim.knowledge import current_character_office

    office, office_type = current_character_office(db, character, name)
    current_character = SimpleNamespace(name=name, office=office, office_type=office_type)
    opening = minimal_opening_context(
        current_character, state, _present_names(db, character), affairs,
        _spoken_this_scene(db, character),
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))


def _character_gazette_rows(public_events: Sequence[dict]) -> list[dict[str, object]]:
    """Person gazette rows come only from that person's typed public projection.

    Raw ``turn_reports`` aggregates are not an authorization boundary (#883 / #1832).
    """
    rows: list[dict[str, object]] = []
    for item in public_events or []:
        source_id = str(item.get("source_id") or "")
        if not (
            source_id.startswith("projection:turn_report:")
            or (source_id.startswith("turn_report:") and source_id.endswith(":public"))
        ):
            continue
        body = str(item.get("body") or "")
        if not body.strip():
            continue
        rows.append({
            "year": int(item.get("year") or 0),
            "period": int(item.get("period") or 0),
            "turn": int(item.get("turn") or 0),
            "body": body,
        })
    return rows


def _write_gazette_index(
    tmp: Path, rows: Sequence[dict[str, object]], *, prefix: str,
) -> list[str]:
    """历月邸报一行索引入目录（章节记忆退役，M3；0155/0157 后出注记）：每回合一份
    全文文件，根 INDEX 里天然是一行一项——不再压缩/摘要成第二套机制。

    ``prefix`` differs by reader: characters use ``公开说法/邸报``; world simulation
    keeps top-level ``邸报`` (#1833 docs / #1834 world directory).
    """
    index: list[str] = []
    for row in rows:
        year = int(row.get("year") or 0)
        period = int(row.get("period") or 0)
        turn = int(row.get("turn") or 0)
        fname = f"{year}年{period}月.txt" if year and period else f"turn-{turn}.txt"
        body = str(row.get("body") or row.get("report") or "")
        if not body.strip():
            continue
        rel = f"{prefix}/{fname}"
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


def _write_world_textual_fact_files(tmp: Path, db: Any) -> list[str]:
    """World directory: character/army/region textual facts once from store.

    affair facts already ride 事务/*/当前情况.txt — do not mint a second carrier.
    """
    store = getattr(db, "textual_facts", None)
    if store is None or not hasattr(db, "conn"):
        return []
    rows = db.conn.execute(
        "SELECT DISTINCT subject_kind, subject_id FROM textual_facts "
        "WHERE subject_kind IN ('character', 'army', 'region') "
        "ORDER BY subject_kind, subject_id"
    ).fetchall()
    index: list[str] = []
    for row in rows:
        kind = str(row["subject_kind"] or "").strip()
        subject_id = str(row["subject_id"] or "").strip()
        if not kind or not subject_id:
            continue
        facts = store.readable_materials(subject_kind=kind, subject_id=subject_id)
        body = "\n".join(
            str(fact.body or "").strip() for fact in facts if str(fact.body or "").strip()
        )
        if not body:
            continue
        label = subject_id
        if kind == "region" and hasattr(db, "region_rows"):
            for region in db.region_rows():
                if str(region["id"] or "") == subject_id:
                    label = str(region["name"] or subject_id)
                    break
        elif kind == "army" and hasattr(db, "army_rows"):
            for army in db.army_rows():
                if str(army["id"] or "") == subject_id:
                    label = str(army["name"] or subject_id)
                    break
        rel = f"{_FACT_DIR}/{kind}-{_safe_segment(label)}.txt"
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


# ── 过月推演者材料目录（#1834 / ADR 0153 / 0155 / 0157）──
#
# 推演者三层全看（实况 + 人物经历 + 公开说法），另有盘面（0155 读取形态段）。
# 开场最小集 = 当前盘面全量 + 开着的事务清单；其余（各人经历、公开说法、历月
# 邸报）按需自读。夜里预推段与过月世界段读同一目录（同 night/turn key，与
# character_materials_root 同构）；预推产物本身不进目录（0157 原则）——本模块
# 只备读，不提供任何暂存写入口，天然不会把预推产物写进来。


def world_materials_root(db: Any, state: Any) -> Path:
    from ming_sim.audience_night import get_open_night

    night = get_open_night(db)
    key = f"night-{int(night['id'])}" if night else f"turn-{int(state.turn)}"
    return _materials_campaign_dir(db) / key / "世界推演"


def _world_board_text(db: Any, state: Any) -> str:
    """盘面全量：未按职位裁切的实况账本（0034 后出注记：仅人物按职位读衙门底账，
    推演者不受此限）。各段落直取账本读方法，不经任何奏报/邸报文本中转——满足
    「推演者读到的是实况数不是奏报数」。"""
    # limit=None：与 region_rows/army_rows/treasury_report 的既有「None=不截断」
    # 约定一致，真正的全量——不是拿一个更大的数顶替旧上限（#1834 大理寺 bounce）。
    sections = (
        ("国库", db.treasury_report(state, limit=None)),
        ("军务", db.army_report(limit=None)),
        ("地方", db.region_report(limit=None)),
        ("营建", db.buildings_report(qualitative=True)),
        ("边防", db.power_report(exclude_self=True)),
        ("阶级", db.class_report(audience=True)),
    )
    parts = [f"{title}：\n{body}" for title, body in sections if str(body or "").strip()]
    return "\n\n".join(parts) or "（无）"


def _world_roster_text(db: Any, state: Any) -> str:
    if not hasattr(db, "current_court_roster_rows"):
        return "在朝名册：暂无。"
    rows = db.current_court_roster_rows(state)
    if not rows:
        return "在朝名册：暂无。"
    return "在朝名册：\n" + "\n".join(
        f"{row['name']}：{row['office'] or '无现任官职'}，{row['office_type']}，{row['status']}"
        for row in rows
    )


def _world_affair_lines(db: Any) -> list[tuple[str, str, str, str]]:
    """全部开着的事务及其当前情况（不按人物过滤——推演者看全量，非某人经手）。

    Each line is (dir_key, title, directory_text, opening_text): directory_text
    carries every dated textual fact (ADR 0156 全部提供), opening_text is only
    the latest one-liner (0155 开场最小集只放一句)."""
    store = getattr(db, "affairs", None)
    if store is None or not hasattr(store, "list_open"):
        return []
    textual_facts = getattr(db, "textual_facts", None)
    lines: list[tuple[str, str, str, str]] = []
    for affair in store.list_open():
        facts = (
            store.current_situation(textual_facts, affair.id)
            if textual_facts is not None else ()
        )
        fact_lines = [f"{fact.occurred_month}：{fact.body}" for fact in facts]
        directory_text = "\n".join(fact_lines) if fact_lines else "见目录。"
        # #1812 P6：raw body 是文字事实自由正文，不得 strip。
        opening_text = str(facts[-1].body or "") if facts else "见目录。"
        lines.append((f"affair-{affair.id}", str(affair.name or ""), directory_text, opening_text))
    return lines


def _world_roster_names(db: Any) -> list[str]:
    """全部人物经历真源：持久 characters 表，不以当前在朝名册为白名单

    (#1834 大理寺 bounce：已离朝/下狱/致仕/死亡等不在当前朝臣名册的人物仍须
    可读——#1819 Resolution 决定 1「各人物经历……三层全可读」不按当前在朝
    状态收窄）。「盘面」里的在朝名册（_world_roster_text）另有独立投影，与此
    处经历目录的人物枚举各司其职，互不作为对方的过滤条件。"""
    if not hasattr(db, "conn"):
        return []
    return [
        str(row["name"] or "").strip()
        for row in db.conn.execute("SELECT name FROM characters ORDER BY name").fetchall()
        if str(row["name"] or "").strip()
    ]


def _world_subject_ids(db: Any, table: str) -> list[str]:
    """`armies`/`regions` 全量 id（TEXT 主键），世界目录按对象枚举文字事实用。"""
    if not hasattr(db, "conn"):
        return []
    return [
        str(row["id"] or "").strip()
        for row in db.conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        if str(row["id"] or "").strip()
    ]


def _textual_facts_text(textual_facts: Any, *, subject_kind: str, subject_id: str) -> str:
    """这个对象名下全部文字事实（ADR 0156），按月连写、最新的在最后；无记录
    给占位——世界目录按 character/army/region/affair 四类对象统一走这一条投影
    （#1812/#1828/#1834：写口早接好，之前没有任何读口，人物伤势等只能落库、
    过后无法再被推演读到；只在世界目录接，不注入人物私有全知目录）。"""
    if textual_facts is None:
        return "（无）"
    facts = textual_facts.readable_materials(subject_kind=subject_kind, subject_id=subject_id)
    if not facts:
        return "（无）"
    return "\n".join(f"{fact.occurred_month}：{fact.body}" for fact in facts)


def _write_world_tree(
    tmp: Path,
    db: Any,
    state: Any,
    public_events: list,
    affair_lines: list[tuple[str, str, str, str]],
    board_text: str,
) -> list[str]:
    from ming_sim.knowledge import build_character_knowledge

    index: list[str] = []
    textual_facts = getattr(db, "textual_facts", None)

    board_rel = f"{_BOARD_DIR}/全局.txt"
    _write_text(tmp / board_rel, board_text)
    index.append(board_rel)

    _write_text(tmp / _COURT_ROSTER_REL, _world_roster_text(db, state))
    index.append(_COURT_ROSTER_REL)

    for name in _world_roster_names(db):
        knowledge = (
            db.get_character_knowledge(state, name) if hasattr(db, "get_character_knowledge")
            else build_character_knowledge(db, state, name)
        )
        person_dir = f"{_PERSON_DIR}/{_safe_segment(name)}"
        rel = f"{person_dir}/经历.txt"
        _write_text(tmp / rel, _experience_text(knowledge))
        index.append(rel)
        # #1828/#1834：人物名下按月文字事实（负伤/患病等）单独一份，世界目录
        # 才有；人物私有经历目录（_write_tree）不注入，仍只按其知识见闻投影。
        facts_rel = f"{person_dir}/按月实况.txt"
        _write_text(tmp / facts_rel, _textual_facts_text(
            textual_facts, subject_kind="character", subject_id=name,
        ))
        index.append(facts_rel)

    for army_id in _world_subject_ids(db, "armies"):
        rel = f"{_ARMY_DIR}/{army_id}/按月实况.txt"
        _write_text(tmp / rel, _textual_facts_text(
            textual_facts, subject_kind="army", subject_id=army_id,
        ))
        index.append(rel)

    for region_id in _world_subject_ids(db, "regions"):
        rel = f"{_REGION_DIR}/{region_id}/按月实况.txt"
        _write_text(tmp / rel, _textual_facts_text(
            textual_facts, subject_kind="region", subject_id=region_id,
        ))
        index.append(rel)

    for dir_key, title, directory_text, _opening_text in affair_lines:
        seg = _safe_segment(dir_key)
        body = f"{title}\n{directory_text}" if title else directory_text
        rel = f"{_AFFAIR_DIR}/{seg}/当前情况.txt"
        _write_text(tmp / rel, body)
        index.append(rel)

    index.extend(_write_world_textual_fact_files(tmp, db))
    index.extend(_write_public_by_month(tmp, public_events))
    index.extend(_write_gazette_index(
        tmp, db.list_turn_reports() if hasattr(db, "list_turn_reports") else (),
        prefix=_WORLD_GAZETTE_DIR,
    ))

    _write_text(tmp / _INDEX_NAME, "\n".join(index) if index else "")
    return index


def _world_opening_text(state: Any, board_text: str, affair_lines: list[tuple[str, str, str, str]]) -> str:
    parts = [
        f"日期：{int(state.year)}年{int(state.period)}月",
        "盘面：",
        board_text,
        "开着的事务：" if affair_lines else "开着的事务：（无）",
    ]
    parts.extend(f"- {title}：{opening_text}" for _key, title, _directory_text, opening_text in affair_lines)
    parts.append("人物经历、公开说法、历月邸报在当前目录，按需自读。根目录 INDEX 一行一项。")
    return "\n".join(parts)


def scene_materials_root(db: Any, state: Any) -> Path:
    """#1836：整场场景 LLM 的材料目录根（一夜一份，不按单人拆）。"""
    from ming_sim.audience_night import get_open_night

    night = get_open_night(db)
    key = f"night-{int(night['id'])}" if night else f"turn-{int(state.turn)}"
    return _materials_campaign_dir(db) / key / "scene"


def _scene_present_rows(db: Any, state: Any) -> list[tuple[str, str]]:
    """在场诸人（含常在员额）→ (name, office) 列表，按姓名排序。"""
    from ming_sim.audience_night import get_open_night, present_names_at, resolve_standing_roster

    night = get_open_night(db)
    if night is not None:
        names = sorted(present_names_at(db, int(night["id"])))
    else:
        names = sorted(resolve_standing_roster(db))
    rows: list[tuple[str, str]] = []
    for name in names:
        office = ""
        if hasattr(db, "conn"):
            row = db.conn.execute(
                "SELECT office FROM characters WHERE name=?", (name,),
            ).fetchone()
            if row is not None:
                office = str(row["office"] or "")
        rows.append((name, office))
    return rows


def _json_list_field(raw: object) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _character_projection_from_db_row(row: Any) -> Any:
    """DB characters 行 → 档料投影用 Character（字段齐整，供 character_context_with_db）。"""
    from ming_sim.models import Character

    def _int(key: str, default: int = 0) -> int:
        try:
            return int(row[key])
        except (KeyError, TypeError, ValueError):
            return default

    def _str(key: str, default: str = "") -> str:
        try:
            value = row[key]
        except (KeyError, IndexError, TypeError):
            return default
        return default if value is None else str(value)

    return Character(
        name=_str("name"),
        office=_str("office"),
        office_type=_str("office_type"),
        faction=_str("faction"),
        aliases=_json_list_field(row["aliases"]),
        personal_skills=_json_list_field(row["personal_skills"]),
        loyalty=_int("loyalty"),
        ability=_int("ability"),
        integrity=_int("integrity"),
        courage=_int("courage"),
        style=_str("style"),
        power_id=_str("power_id", "ming") or "ming",
        summary=_str("summary"),
        identity=_int("identity", 50),
    )


def _resolve_present_character(
    db: Any,
    name: str,
    office: str,
    characters: dict,
) -> Any:
    """在场者 → 档料投影：content 优先，否则 DB 行，再否则空字段 Character（既有缺省语义）。

    不得回退成缺 personal_skills/faction 的残壳——character_context_with_db 会崩
    （#1836 返修）。不合成占位文案（P7）。
    """
    hit = characters.get(name)
    if hit is not None:
        return hit
    if hasattr(db, "conn"):
        row = db.conn.execute(
            """
            SELECT name, office, office_type, faction, aliases, personal_skills,
                   loyalty, ability, integrity, courage, style, identity,
                   summary, power_id
            FROM characters WHERE name=?
            """,
            (name,),
        ).fetchone()
        if row is not None:
            return _character_projection_from_db_row(row)
    from ming_sim.models import Character

    return Character(
        name=name,
        office=office or "",
        office_type="",
        faction="",
        aliases=[],
        personal_skills=[],
        loyalty=0,
        ability=0,
        integrity=0,
        courage=0,
        style="",
        power_id="ming",
    )


def _scene_spoken_text(db: Any) -> str:
    """本场已说的话：按夜持久化对话轮（皇帝原话 + 场景戏文）重建。"""
    from ming_sim.audience_night import get_open_night, list_chat_turns_for_night

    night = get_open_night(db)
    if night is None or not hasattr(db, "conn"):
        return ""
    lines: list[str] = []
    for turn in list_chat_turns_for_night(db, int(night["id"])):
        for mid, role_label in (
            (turn.get("user_message_id"), "朕"),
            (turn.get("minister_message_id"), "殿上"),
        ):
            if not mid:
                continue
            row = db.conn.execute(
                "SELECT content FROM chat_messages WHERE id=?", (int(mid),),
            ).fetchone()
            if row is None:
                continue
            # #1812 P6：对话正文是自由文本，判空用局部 stripped 副本，写出用原文。
            body = str(row["content"] or "")
            if not body.strip():
                continue
            lines.append(f"{role_label}：{body}")
    return "\n".join(lines)


def _scene_opening_text(
    state: Any,
    present_rows: Sequence[tuple[str, str]],
    spoken: str,
    handling_by_person: Sequence[tuple[str, Sequence[tuple[str, str]]]],
) -> str:
    """场景 LLM 开场最小集（ADR 0155）：在场诸人身份职位、日期、各人正经手事务一句、本场已说的话。"""
    if present_rows:
        present_line = "、".join(
            f"{name}（{office}）" if office else name for name, office in present_rows
        )
    else:
        present_line = "（尚无）"
    parts = [
        f"在场：{present_line}",
        f"日期：{int(state.year)}年{int(state.period)}月",
    ]
    # 各在场人正经手事务（名字 + 当前情况一句）；无人经手则标（无）。
    parts.append("正经手事务：")
    any_handling = False
    for name, affairs in handling_by_person:
        if not affairs:
            continue
        any_handling = True
        parts.append(f"{name}：")
        parts.extend(f"- {title}：{situation}" for title, situation in affairs)
    if not any_handling:
        parts.append("（无）")
    parts.append("本场已说的话：")
    parts.append(spoken if spoken.strip() else "（尚无）")
    parts.append(
        "在场诸人各自材料在 人物/<名>/ 下（人物档料、经历、公事档案、朝臣名册、事务、公开说法）。"
        "根目录 INDEX 一行一项。其余想读自己读。"
    )
    return "\n".join(parts)


def _write_one_present_person(
    tmp: Path,
    db: Any,
    state: Any,
    character: Any,
    knowledge: dict,
    matter_lines: list[tuple[str, str, str, str, bool]],
    night_id: int = 0,
) -> list[str]:
    """把一人的可读材料全部写在 人物/<名>/ 之下，不与他人共享路径。

    #1830 _write_tree 会把朝臣名册 / 事务 / 公开说法写到 scene 根下共享位置，
    多人叠写会后写覆盖先写（#1836 审回）。场景目录改为每人一棵私有子树。
    """
    name = str(getattr(character, "name", "") or "")
    # 场景人物路径是玩家可见索引；名称仍保持可读，只替换路径非法字符。
    seg = _UNSAFE.sub("_", name).strip() or "未名"
    base = f"{_PERSON_DIR}/{seg}"
    index: list[str] = []

    # ADR 0033 / 0155：人物+派系+认同度客观特征化；单一真源 character_context_with_db
    # （单人链 registry 已用同一投影）。不另造第二套描述规则。
    # #1839：当场实况（生死/下狱/革职）已落 characters.status 时，档料附当前状态一行，
    # 下一句场景目录可见——不另造第二套状态投影，只读 DB 真源。
    from ming_sim.context import character_context_with_db

    dossier_body = character_context_with_db(character, db, turn=int(state.turn))
    if hasattr(db, "get_character_status"):
        status, reason = db.get_character_status(name)
        status_text = str(status or "").strip()
        reason_text = str(reason or "")
        if status_text and status_text != "active":
            line = f"当前状态：{status_text}"
            if reason_text.strip():
                line = f"{line}（{reason_text}）"
            dossier_body = f"{dossier_body}\n{line}"
    dossier_rel = f"{base}/人物档料.txt"
    _write_text(tmp / dossier_rel, dossier_body)
    index.append(dossier_rel)

    roster_rel = f"{base}/朝臣名册.txt"
    _write_text(tmp / roster_rel, _court_roster_text(db, state, character, knowledge))
    index.append(roster_rel)

    exp_rel = f"{base}/经历.txt"
    if night_id:
        from ming_sim.audience_night import person_night_experience
        audible = person_night_experience(db, night_id, name)
    else:
        audible = []
    _write_text(tmp / exp_rel, _experience_text(knowledge, audible))
    index.append(exp_rel)

    # #1839 / ADR 0156：文字事实当场落账后须进本夜场景目录（下一句可见）。
    # 与世界目录同形（按月实况），投影复用 _textual_facts_text，不另造读口。
    facts_rel = f"{base}/按月实况.txt"
    _write_text(
        tmp / facts_rel,
        _textual_facts_text(
            getattr(db, "textual_facts", None),
            subject_kind="character", subject_id=name,
        ),
    )
    index.append(facts_rel)

    office_rel = f"{base}/公事档案.txt"
    _write_text(
        tmp / office_rel,
        character_office_archive_text(db, state, character, knowledge),
    )
    index.append(office_rel)

    for dir_key, title, directory_text, _opening_text, _is_handling in matter_lines:
        matter_seg = _safe_segment(dir_key)
        if title and "\n" in directory_text:
            body = f"{title}\n{directory_text}"
        elif title and directory_text:
            body = f"{title}：{directory_text}"
        else:
            body = title or directory_text
        rel = f"{base}/事务/{matter_seg}/当前情况.txt"
        _write_text(tmp / rel, body)
        index.append(rel)

    public_events = knowledge.get("public_events") or []
    public_by_month: dict[tuple[int, int], list[str]] = {}
    for item in public_events:
        year = int(item.get("year") or 0)
        period = int(item.get("period") or 0)
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if not (title.strip() or body.strip()):
            continue
        line = f"{title}：{body}" if title and body else (title or body)
        public_by_month.setdefault((year, period), []).append(line)
    for (year, period), lines in sorted(public_by_month.items()):
        fname = f"{year}年{period}月.txt" if year and period else "未标年月.txt"
        rel = f"{base}/公开说法/{fname}"
        _write_text(tmp / rel, "\n".join(lines))
        index.append(rel)

    return index


def _write_scene_tree(
    tmp: Path,
    db: Any,
    state: Any,
    present_rows: Sequence[tuple[str, str]],
    person_payloads: Sequence[tuple[Any, dict, list]],
    night_id: int = 0,
) -> list[str]:
    """为每位在场人物写入互不覆盖的私有材料子树，合并 INDEX。"""
    index: list[str] = []
    seen_rel: set[str] = set()

    def _add(rel: str) -> None:
        if rel and rel not in seen_rel:
            seen_rel.add(rel)
            index.append(rel)

    for character, knowledge, matter_lines in person_payloads:
        for rel in _write_one_present_person(
            tmp, db, state, character, knowledge, matter_lines,
            night_id,
        ):
            _add(rel)

    _write_text(tmp / _INDEX_NAME, "\n".join(index) if index else "")
    return index


def prepare_scene_materials(
    db: Any,
    state: Any,
    *,
    dest_root: Optional[Path] = None,
) -> PreparedMaterials:
    """#1836 / ADR 0155：整场场景 LLM 材料目录。

    在场诸人（含递话人）各有自己的人物档料/事务/公开说法材料（每人一棵
    人物/<名>/ 子树，互不覆盖；人物档料复用 character_context_with_db）；
    开场最小集 = 在场身份职位、日期、各人正经手事务一句、本场已说的话。
    CLI cwd / API list-read 同树。
    """
    from ming_sim.knowledge import build_character_knowledge
    from ming_sim.audience_night import get_open_night

    present_rows = _scene_present_rows(db, state)
    night = get_open_night(db)
    night_id = int(night["id"]) if night is not None else 0
    spoken = _scene_spoken_text(db)
    content = getattr(db, "content", None)
    characters = getattr(content, "characters", None) or {}

    # 一次 prepare 冻结每人 knowledge + matter_lines，目录与 opening 共用。
    person_payloads: list[tuple[Any, dict, list]] = []
    handling_by_person: list[tuple[str, list[tuple[str, str]]]] = []
    for name, office in present_rows:
        character = _resolve_present_character(db, name, office, characters)
        if hasattr(db, "get_character_knowledge"):
            knowledge = db.get_character_knowledge(state, name)
        else:
            knowledge = build_character_knowledge(db, state, name)
        matter_lines = _character_affair_lines(db, state, name, knowledge)
        person_payloads.append((character, knowledge, matter_lines))
        handling_by_person.append(
            (name, _opening_affair_lines(db, name, matter_lines)),
        )

    dest, index = _publish_material_tree(
        dest_root,
        scene_materials_root(db, state),
        lambda tmp: _write_scene_tree(tmp, db, state, present_rows, person_payloads, night_id),
    )
    opening = _scene_opening_text(state, present_rows, spoken, handling_by_person)
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))


def prepare_world_materials(
    db: Any,
    state: Any,
    *,
    dest_root: Optional[Path] = None,
) -> PreparedMaterials:
    """过月推演者材料目录：盘面全量 + 开着的事务清单进开场最小集；人物经历、
    公开说法、历月邸报按需自读（#1834）。写入（拒收/实况回目录、下月材料）不
    在本函数职责内——本函数只组装可读材料，不提供任何写入口。"""
    from ming_sim.knowledge import build_character_knowledge

    # public_events 的既有投影与具体 character_name 无关（build_character_knowledge
    # 里 public_events 恒取 `_character_knowledge_events("", ...)`）——借用同一投影，
    # 不另建一套「世界公开说法」查询。
    knowledge = build_character_knowledge(db, state, "")
    public_events = knowledge.get("public_events") or []
    affair_lines = _world_affair_lines(db)
    # #1834 大理寺 bounce 3：与人物经历同一纪律——本次 prepare 只算一次盘面全量
    # 投影，目录写入与 opening 共用同一份冻结结果，不重复查两遍账本。
    board_text = _world_board_text(db, state)

    dest, index = _publish_material_tree(
        dest_root,
        world_materials_root(db, state),
        lambda tmp: _write_world_tree(tmp, db, state, public_events, affair_lines, board_text),
    )

    opening = _world_opening_text(state, board_text, affair_lines)
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))
