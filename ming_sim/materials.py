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
from typing import Any, Callable, List, Mapping, Optional, Sequence

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
_CANDIDATE_DIR = "候选事件"
_PETITION_DIR = "请旨事项"
_WORLD_GAZETTE_DIR = "邸报"
_CHARACTER_GAZETTE_DIR = f"{_PUBLIC_DIR}/邸报"
_COURT_ROSTER_REL = f"{_PERSON_DIR}/朝臣名册.txt"
# #1893：本月候选事实（人物事件 + 弹劾潮）单一真源路径，目录与 opening 共用。
_CANDIDATE_REL = f"{_BOARD_DIR}/候选事件与弹劾潮.txt"


@dataclass(frozen=True)
class PreparedMaterials:
    root: Path
    opening: str
    index_lines: tuple[str, ...]


def identity_material_rel(name: object) -> str:
    """4a 本人可及材料的人读索引；正文在其子目录按既定载体分列。"""
    return f"{_PERSON_DIR}/{_safe_segment(name)}/可及材料/{_INDEX_NAME}"


def write_identity_materials(
    prepared: Any, db: Any, state: Any, names: Sequence[object],
) -> List[str]:
    """复用人物材料写手，向本次调用树写入各自可及子目录，返回索引路径。

    调用方备什么树就写什么树（4a 密令供料传自己的 ``prepared``）。实情须说明白：
    4a 目前用的是 ``prepare_world_materials(db, state)`` 的默认根
    （``…/turn-N/世界推演``），与世界段同一路径——**不外泄靠的是生命周期而非路径**：
    4a 调完即 ``release_material_tree`` 整树释放，邸报作者用前会重新 prepare，
    故读不到上一场留在树里的东西（#1862 用例正守「密报不入邸报」这条界）。

    ⚠️ 故本函数**不得**在别的调用还持有一棵未释放的树时被调进去：身份投影含
    本人私务（含其在办密报正文），并进一棵**别人正在读**的树等于把密报内容
    抬进其读取范围。同场不等于人物全知，读取范围也不该因共用一棵树而互相放宽。
    """
    from types import SimpleNamespace

    root = Path(prepared.root)
    index = list(getattr(prepared, "index_lines", ()) or ())
    written: List[str] = []
    for raw in names:
        name = str(raw or "").strip()
        row = db.conn.execute(
            "SELECT name,office,office_type FROM characters WHERE name=?", (name,),
        ).fetchone() if name else None
        if row is None:
            continue  # 不是真人物（如「某类人」式题名）：没有身份材料，不编
        character = SimpleNamespace(**dict(row))
        knowledge, issue_materials = _character_material_projection(db, state, character)
        rel = identity_material_rel(name)
        _write_tree((root / rel).parent, db, state, character, knowledge, issue_materials)
        index.append(rel)
        written.append(rel)
    if written:
        index_path = root / _INDEX_NAME
        # Append paths without re-reading or normalizing the existing free text.
        with index_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write("\n" + "\n".join(written) + "\n")
        object.__setattr__(prepared, "index_lines", tuple(index))
    return written


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
    db_path = Path(str(db.path)).resolve()
    stem = _safe_segment(db_path.stem if db_path.suffix else db_path.name)
    return db_path.parent / "materials" / stem


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # #1812 P6：raw body 是材料自由正文，不得 rstrip——只补齐末尾换行，不削内容。
    text = str(body or "")
    # newline="": 自由正文里的 CR/CRLF 原样落盘，不换成系统换行。
    path.write_text(
        text if text.endswith("\n") else text + "\n",
        encoding="utf-8",
        newline="",
    )


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
    """按材料目录内的相对路径读文件。索引展示行不是路径。"""
    target = _resolve_inside(root, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    # newline="": 与磁盘原文一致。默认文本读会把 CR/CRLF 换成 LF。
    with target.open(encoding="utf-8", newline="") as stream:
        return stream.read()


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
    try:
        return int(db.affairs.affair_id_for_issue(int(issue_id)))
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
    from ming_sim.knowledge import _issue_audience_case_events, _reader_in_issue_audience, origin_visible_to
    from ming_sim.participant_roster import participant_roster_names

    store = db.affairs

    dossier_participant_ids: set[int] = set()
    for row in db.conn.execute(
        "SELECT id, affair_id, secret_order_id, participant_roster "
        "FROM decree_dossiers WHERE affair_id != 0",
    ).fetchall():
        if (
            row["secret_order_id"] is not None
            and origin_visible_to(db, f"dossier:{row['id']}", character_name)
        ) or (
            row["secret_order_id"] is None
            and character_name in participant_roster_names(row["participant_roster"])
        ):
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
    for issue in db.list_active_issues():
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
        if character_name in roster or _reader_in_issue_audience(db, issue, character_name):
            handling_ids.add(linked_affair_id)

    candidate_ids = dossier_participant_ids | set(linked_material) | handling_ids
    textual_facts = db.textual_facts
    lines: list[tuple[str, str, str, str, bool]] = []
    for affair_id in candidate_ids:
        try:
            affair = store.get(affair_id)
        except KeyError:
            continue
        facts = tuple(fact for fact in store.current_situation(textual_facts, affair_id)
                      if origin_visible_to(db, fact.origin_ref, character_name))
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
        title = str(issue.get("title") or "")
        if issue_id <= 0 or not title.strip():
            continue
        stage = str(issue.get("stage_text") or "")
        resolve = str(issue.get("resolve_condition") or "")
        fail = str(issue.get("fail_condition") or "")
        lines.append({
            "id": issue_id,
            "affair_id": int(issue.get("affair_id") or 0),
            "title": title,
            "situation": stage if stage else "见目录。",
            "resolve_condition": resolve,
            "fail_condition": fail,
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
    from ming_sim.knowledge import _reader_in_issue_audience
    from ming_sim.participant_roster import participant_roster_names

    visible = {
        dir_key: (title, opening_text, is_handling)
        for dir_key, title, _directory_text, opening_text, is_handling
        in matter_lines
    }
    handled: list[tuple[str, str]] = []
    seen: set[str] = set()
    active = db.list_active_issues()
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
        if character_name not in roster and not _reader_in_issue_audience(db, issue, character_name):
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
    # #1853 J8-R：必备 list_directives / get_dossier_for_directive 直调。
    return [
        dict(row) for row in db.list_directives(state, statuses=("draft",))
        if int(row["turn"]) < int(state.turn)
        and db.get_dossier_for_directive(int(row["id"])) is None
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


def _secret_order_memorials(order: Any) -> list[str]:
    """承办人自己的月度奏报。月份与进展取记录字段，正文原样。

    催办/核议不是月报，实况单位不进这份材料。不从正文日期或排列序号推定月份。
    """
    from ming_sim.db import GameDB
    from ming_sim.supervision import report_origin_base

    monthly = GameDB.DOSSIER_REPORT_ORIGIN_MONTHLY
    texts: list[str] = []
    for item in order.get("dossier_progress") or []:
        if not isinstance(item, Mapping) or item.get("is_terminal"):
            continue
        if report_origin_base(item.get("origin")) != monthly:
            continue
        text = str(item.get("memorial_text") or "")
        if not text.strip():
            continue
        turn = int(item.get("turn") or 0)
        band = str(item.get("progress_band") or "")
        texts.append(f"回合：{turn}\n进展：{band}\n{text}")
    return texts


def _write_secret_order_file(tmp: Path, db: Any, state: Any, character: Any, *, rel: str | None = None) -> str | None:
    """Directory copy of the minister's active secret-order reminder.

    Logic lives here after #1833 retired the registry brief builder. Full task
    text is kept for on-demand read — no replacement length cap (#1833 AC).
    DB/read failures raise; they are not washed into an empty-business result.
    """
    from ming_sim.db import GameDB
    from ming_sim.supervision import report_origin_base

    name = str(getattr(character, "name", "") or "")
    orders = db.get_active_secret_orders_for_minister(name) if name else []
    if orders:
        monthly = GameDB.DOSSIER_REPORT_ORIGIN_MONTHLY
        lines = [
            "【你身上还在办的密令】",
            "在册密令：",
        ]
        for o in orders:
            turn = int(state.turn)
            advanced = any(
                not item.get("is_terminal")
                and int(item.get("turn") or 0) == turn
                and report_origin_base(item.get("origin")) == monthly
                for item in (o.get("dossier_progress") or [])
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
            lines.extend(_secret_order_memorials(o))
        brief = "\n".join(lines)
    else:
        brief = ""
    rel = rel or f"{_SECRET_DIR}/进行中.txt"
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
    from ming_sim.knowledge import origin_visible_to

    store = db.textual_facts
    subjects: list[tuple[str, str, str]] = []
    name = str(getattr(character, "name", "") or "")
    if name:
        subjects.append(("character", name, name))
    region_ids = set((knowledge.get("scope") or {}).get("region_ids") or ())
    if region_ids:
        for row in db.region_rows():
            if str(row["id"] or "") not in region_ids:
                continue
            rid = str(row["id"] or "")
            rname = str(row["name"] or rid)
            if rid:
                subjects.append(("region", rid, rname))
    army_ids = set((knowledge.get("scope") or {}).get("army_ids") or ())
    if army_ids:
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
        facts = tuple(fact for fact in store.readable_materials(subject_kind=kind, subject_id=subject_id)
                      if origin_visible_to(db, fact.origin_ref, name))
        if not facts:
            continue
        body = "\n".join(
            raw for fact in facts
            if (raw := str(fact.body or "")).strip()
        )
        if not body:
            continue
        rel = f"{_FACT_DIR}/{kind}-{_safe_segment(label)}.txt"
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


def _write_region_detail_files(tmp: Path, db: Any, knowledge: dict) -> list[str]:
    region_ids = set((knowledge.get("scope") or {}).get("region_ids") or ())
    if not region_ids:
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
    if not army_ids:
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
    brief = render_referenceable_dossier_brief(
        db.list_referenceable_dossiers(name, state.turn),
    )
    if brief:
        office_lines.append(brief)
    return "\n".join(office_lines) or "（无）"


def _court_roster_text(db: Any, state: Any, character: Any, knowledge: dict) -> str:
    """Processed court roster for on-demand read."""
    from ming_sim.knowledge import project_court_roster_rows

    office_type = str(
        knowledge.get("office_type") or getattr(character, "office_type", "") or ""
    )
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
    name = str(getattr(character, "name", "") or "")
    index: list[str] = []

    _write_text(tmp / _COURT_ROSTER_REL, _court_roster_text(db, state, character, knowledge))
    index.append(_COURT_ROSTER_REL)

    person_dir = tmp / _PERSON_DIR / _safe_segment(name)
    _write_text(person_dir / "经历.txt", _experience_text(knowledge, _person_audience_experience(db, name)))
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/经历.txt")

    _write_text(
        person_dir / "公事档案.txt",
        character_office_archive_text(db, state, character, knowledge),
    )
    index.append(f"{_PERSON_DIR}/{_safe_segment(name)}/公事档案.txt")

    # #1830：不再另写一份综合见闻。角色知识此前在这里被 render_character_knowledge
    # 整体重渲成 人物/<名>/见闻.txt，于是同一条公开记录同时存在于按月公开说法与
    # 邸报载体（world.public 把公开层正文再拼一遍，public_events/events 又逐条重
    # 述），邸报因而不止一处可读。每一段都已有既定载体：公开层走
    # _write_character_public_layer（公开说法/ 与 公开说法/邸报/），亲历走 经历.txt，
    # 职门底账走 公事档案.txt，人事走 _court_roster_text。删掉重复投影，不另造新载体。

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
    index.extend(_write_character_public_layer(tmp, public_events, db))

    secret_rel = _write_secret_order_file(tmp, db, state, character)
    if secret_rel:
        index.append(secret_rel)
    index.extend(_inquiry_monthly_report_rels(tmp, db, character, knowledge))
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
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if not title.strip() and not body.strip():
            continue
        lines.append(f"{title}：{body}" if title and body else (title or body))
    lines.extend(str(item["body"]) for item in audible_entries if item.get("body"))
    return "\n".join(lines) or "（无）"


def _person_audience_experience(db: Any, name: str) -> list[dict]:
    """Surviving audience nights, projected through the existing audibility rule.

    #1853 J8-R：必备 GameDB.conn 直调。
    """
    from ming_sim.audience_night import person_night_experience

    nights = db.conn.execute("SELECT id FROM audience_nights ORDER BY id").fetchall()
    return [entry for night in nights
            for entry in person_night_experience(db, int(night["id"]), name)]


def _secret_order_chat_turn_ids(db: Any) -> set[int]:
    """Use durable oral pins, including later approvals and updates, not only issuance."""
    message_ids = list(db._secret_origin_message_protection())
    if not message_ids:
        return set()
    placeholders = ",".join("?" for _ in message_ids)
    return {
        int(row["id"])
        for row in db.conn.execute(
            f"SELECT id FROM chat_turns WHERE user_message_id IN ({placeholders}) "
            f"OR minister_message_id IN ({placeholders})",
            [*message_ids, *message_ids],
        )
    }


def _omit_secret_order_audience(entries: Sequence[dict], secret_turn_ids: set[int]) -> list[dict]:
    """作者经历只去掉 source_chat_turn_id 落在密令轮上的条目。"""
    if not secret_turn_ids:
        return list(entries)
    return [
        entry for entry in entries
        if int(entry.get("source_chat_turn_id") or 0) not in secret_turn_ids
    ]


def _write_public_by_month(
    tmp: Path, public_events: list, *, base: str = _PUBLIC_DIR,
) -> list[str]:
    """公开说法按月分文件（#1830 既有形态，人物目录／场景人物子树／推演者目录共用）。

    邸报直接读归档表，使用独立目录载体。``base`` 是目录内
    相对前缀——场景人物私有子树把同一份材料写在自己名下，准入与人读呈现
    仍走这一个函数（#1830 共用读侧契约）。
    """
    index: list[str] = []
    public_by_month: dict[tuple[int, int], list[str]] = {}
    for item in public_events or []:
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
        rel = f"{base}/{fname}" if base else fname
        _write_text(tmp / rel, "\n".join(lines))
        index.append(rel)
    return index


def _write_character_public_layer(
    tmp: Path, public_events: Sequence[dict], db: Any, *, base: str = "",
) -> list[str]:
    """一份人物可读公开层：按月公开说法 + 本人有权读取的历月邸报载体。

    人物目录、场景人物私有子树共用——同一公开记录的准入与人读呈现不因走哪条
    目录而分叉（#1830 共用读侧契约 / ADR 0155）。
    """
    index = _write_public_by_month(
        tmp, list(public_events), base=f"{base}/{_PUBLIC_DIR}" if base else _PUBLIC_DIR,
    )
    index.extend(_write_gazette_index(
        tmp,
        db.list_turn_reports(),
        prefix=f"{base}/{_CHARACTER_GAZETTE_DIR}" if base else _CHARACTER_GAZETTE_DIR,
    ))
    return index


def _character_material_projection(db: Any, state: Any, character: Any) -> tuple[dict, list]:
    from ming_sim.knowledge import project_issue_materials

    name = str(getattr(character, "name", "") or "")
    knowledge = db.get_character_knowledge(state, name)
    issues = _visible_affair_lines({"issues": project_issue_materials(db, name, knowledge)})
    return knowledge, issues


def prepare_character_materials(
    db: Any,
    state: Any,
    character: Any,
    *,
    dest_root: Optional[Path] = None,
) -> PreparedMaterials:
    name = str(getattr(character, "name", "") or "")
    knowledge, issue_materials = _character_material_projection(db, state, character)

    dest, index = _publish_material_tree(
        dest_root,
        character_materials_root(db, state, character),
        lambda tmp: _write_tree(tmp, db, state, character, knowledge, issue_materials),
    )

    affairs = _handled_affair_lines(db, state, name, issue_materials)
    for row in _carryover_drafts(db, state):
        title = f"尚未入档旨稿#{int(row['id'])}"
        body = str(row["text"] if hasattr(row, "keys") and "text" in row.keys() else (row.get("text") if hasattr(row, "get") else ""))
        affairs.append({
            "id": f"draft-{int(row['id'])}", "title": title,
            "situation": f"{body}（尚未入档）" if body.strip() else "尚未入档",
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


def _gazette_index_line(rel: str, year: int, period: int, title: str) -> str:
    """一行 = 路径、年月、已入档标题。无标题时只留路径，不另造标题。"""
    shown = str(title or "")
    if not shown.strip():
        return rel
    from ming_sim.models import reign_period_label

    label = reign_period_label(year, period) if year and 1 <= period <= 12 else ""
    return f"{rel} {label} {shown}" if label else f"{rel} {shown}"


def _write_gazette_index(
    tmp: Path, rows: Sequence[dict[str, object]], *, prefix: str,
) -> list[str]:
    """历月邸报一行索引入目录（#1845：年月 + #1862 已入档标题）。

    全文仍是 ``{年}年{月}月.txt``。索引行不解析正文。
    ``prefix``：人物用 ``公开说法/邸报``，推演者用顶层 ``邸报``。
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
        index.append(_gazette_index_line(rel, year, period, str(row.get("title") or "")))
    return index


def _write_world_textual_fact_files(
    tmp: Path, db: Any, include_fact: Any = None,
) -> list[str]:
    """World directory: character/army/region textual facts once from store.

    affair facts already ride 事务/*/当前情况.txt — do not mint a second carrier.
    """
    store = db.textual_facts
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
            raw for fact in facts
            if _keep_fact(fact, include_fact) and (raw := str(fact.body or "")).strip()
        )
        if not body:
            continue
        label = subject_id
        if kind == "region":
            for region in db.region_rows():
                if str(region["id"] or "") == subject_id:
                    label = str(region["name"] or subject_id)
                    break
        elif kind == "army":
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


def secret_order_dossier_ids(db: Any) -> set[int]:
    """案卷关联：secret_order_id 有值的案卷。沿 list_decree_dossiers，不另查一套。"""
    return {
        int(row["id"])
        for row in db.list_decree_dossiers()
        if row.get("secret_order_id")
    }


# 密令来源 origin / source_id 唯一前缀（#1862 reopen）。拼接与判定都走这里。
SECRET_ORDER_ORIGIN_PREFIX = "secret_order:"


def is_secret_order_origin(origin: object) -> bool:
    """是否密令来源：origin/source_id 以 SECRET_ORDER_ORIGIN_PREFIX 开头。"""
    return str(origin or "").startswith(SECRET_ORDER_ORIGIN_PREFIX)


def secret_order_origin(order_id: object) -> str:
    """密令来源字符串：前缀 + 密令 id。"""
    return f"{SECRET_ORDER_ORIGIN_PREFIX}{int(order_id)}"


def dossier_id_in_origin(origin: object) -> Optional[int]:
    match = re.match(r"(?:decree_)?dossier:(\d+)(?:[:/]|$)", str(origin or ""))
    return int(match.group(1)) if match else None


def _candidate_event_fact(ev: Any) -> dict[str, object]:
    """一个候选事件的结构化事实（ADR 0014 触发门已由 gather 判过，这里只转述事实）。

    战果软判需要的「历史结果 + 历史成因」锚 = summary / precondition /
    resolve_condition / fail_condition；不给 effect 载荷，代码不代模型算软判。
    结局标签只对 strategic_foreign 的 node/ending 战事给，取既有写口的同一份
    白名单（issues.strategic_event_outcome_labels），空集即该事件不收结局标签。
    """
    from ming_sim.issues import strategic_event_outcome_labels

    return {
        "id": str(ev.id),
        "title": str(ev.title),
        "kind": str(ev.kind),
        "interests": list(ev.interests),
        "trigger_gate": dict(ev.trigger_gate),
        "terminal_reason_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
        "summary": str(ev.summary),
        "event_type": str(ev.event_type),
        "trigger_class": str(getattr(ev, "trigger_class", "") or ""),
        "category": str(getattr(ev, "category", "") or ""),
        "urgency": int(getattr(ev, "urgency", 0) or 0),
        "severity": int(getattr(ev, "severity", 0) or 0),
        "person_core_subjects": list(getattr(ev, "person_core_subjects", []) or []),
        "precondition": str(getattr(ev, "precondition", "") or ""),
        "resolve_condition": str(getattr(ev, "resolve_condition", "") or ""),
        "fail_condition": str(getattr(ev, "fail_condition", "") or ""),
        "outcome_labels": sorted(strategic_event_outcome_labels(str(ev.id))),
        "region_hint": str(getattr(ev, "region_hint", "") or ""),
    }


def candidate_supply(
    db: Any, state: Any, *, exclude_dossier_ids: Optional[set[int]] = None,
) -> dict[str, list]:
    """#1893：本月可供模型挑选的人物事件与弹劾潮候选（只供事实，不代选）。

    人物事件候选走既有 ``gather_candidate_events`` 硬门（时间窗 / 状态门 /
    已发·避过·过期终态 / auto_trigger 均已在读侧排除），弹劾潮候选走既有
    ``gather_impeachment_surge_candidates`` 硬门（旨外变形暴露 × 派系 leverage）。
    两条门只给资格与结构化事实；选不选、发不发难仍由同一次月末世界段里的
    模型决定（ADR 0014 / 0091 / P6）。
    """
    from ming_sim.issues import (
        gather_candidate_events,
        gather_impeachment_surge_candidates,
    )

    events = [_candidate_event_fact(ev) for ev in gather_candidate_events(state, db)]
    excluded = set(exclude_dossier_ids or ())
    surge = [
        dict(item)
        for item in gather_impeachment_surge_candidates(state, db)
        if int(item.get("dossier_id") or 0) not in excluded  # type: ignore[arg-type]
    ]
    return {"events": events, "impeachment_surge": surge}


def _world_board_text(
    db: Any, state: Any, *,
    public_only: bool = False,
) -> str:
    """盘面全量：未按职位裁切的实况账本（0034 后出注记：仅人物按职位读衙门底账，
    推演者不受此限）。各段落直取账本读方法，不经任何奏报/邸报文本中转——满足
    「推演者读到的是实况数不是奏报数」。"""
    # limit=None：与 region_rows/army_rows/treasury_report 的既有「None=不截断」
    # 约定一致，真正的全量——不是拿一个更大的数顶替旧上限（#1834 大理寺 bounce）。
    sections = (
        ("国库", db.treasury_report(
            state, limit=None, public_only=public_only,
        )),
        ("军务", db.army_report(limit=None)),
        ("地方", db.region_report(limit=None)),
        ("营建", db.buildings_report(qualitative=True)),
        ("边防", db.power_report(exclude_self=True)),
        ("阶级", db.class_report(audience=True)),
    )
    parts = [f"{title}：\n{body}" for title, body in sections if str(body or "").strip()]
    return "\n\n".join(parts) or "（无）"


def _world_roster_text(db: Any, state: Any) -> str:
    rows = db.current_court_roster_rows(state)
    if not rows:
        return "在朝名册：暂无。"
    return "在朝名册：\n" + "\n".join(
        f"{row['name']}：{row['office'] or '无现任官职'}，{row['office_type']}，{row['status']}"
        for row in rows
    )


def _keep_fact(fact: Any, include_fact: Any) -> bool:
    if include_fact is None:
        return True
    return bool(include_fact(fact))


def _knowledge_for_experience(knowledge: dict, include_event: Any) -> dict:
    """经历投影的可选事件筛。缺省原样；筛过的调用方拿到一份不改原知识的副本。"""
    if include_event is None:
        return knowledge
    events = list(knowledge.get("events") or [])
    kept = [item for item in events if include_event(item)]
    if len(kept) == len(events):
        return knowledge
    projected = dict(knowledge)
    projected["events"] = kept
    return projected


def _world_affair_lines(db: Any, include_fact: Any = None) -> list[tuple[str, str, str, str]]:
    """全部开着的事务及其当前情况（不按人物过滤——推演者看全量，非某人经手）。

    Each line is (dir_key, title, directory_text, opening_text): directory_text
    carries every dated textual fact (ADR 0156 全部提供), opening_text is only
    the latest one-liner (0155 开场最小集只放一句)."""
    store = db.affairs
    textual_facts = db.textual_facts
    lines: list[tuple[str, str, str, str]] = []
    for affair in store.list_open():
        facts = store.current_situation(textual_facts, affair.id)
        facts = tuple(fact for fact in facts if _keep_fact(fact, include_fact))
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
    return [
        str(row["name"] or "").strip()
        for row in db.conn.execute("SELECT name FROM characters ORDER BY name").fetchall()
        if str(row["name"] or "").strip()
    ]


def _world_subject_ids(db: Any, table: str) -> list[str]:
    """`armies`/`regions` 全量 id（TEXT 主键），世界目录按对象枚举文字事实用。"""
    return [
        str(row["id"] or "").strip()
        for row in db.conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        if str(row["id"] or "").strip()
    ]


def _textual_facts_text(
    textual_facts: Any, *, subject_kind: str, subject_id: str, include_fact: Any = None,
) -> str:
    """这个对象名下全部文字事实（ADR 0156），按月连写、最新的在最后；无记录
    给占位——世界目录按 character/army/region/affair 四类对象统一走这一条投影
    （#1812/#1828/#1834：写口早接好，之前没有任何读口，人物伤势等只能落库、
    过后无法再被推演读到；只在世界目录接，不注入人物私有全知目录）。"""
    if textual_facts is None:
        return "（无）"
    facts = textual_facts.readable_materials(subject_kind=subject_kind, subject_id=subject_id)
    facts = tuple(fact for fact in facts if _keep_fact(fact, include_fact))
    if not facts:
        return "（无）"
    return "\n".join(f"{fact.occurred_month}：{fact.body}" for fact in facts)


def _world_candidate_events(db: Any, state: Any) -> list:
    """#1892：合资格且尚无终态的人物事件候选，连同结构化事实交世界段模型自读。

    候选资格与结构化事实由 gather_candidate_events 单一真源判（窗口/前提门/已发
    终态/三饷亲裁排除）；本函数只把该结果写成材料，不另设判门、不替模型选。
    """
    from ming_sim.issues import gather_candidate_events

    return [_candidate_event_fact(ev) for ev in gather_candidate_events(state, db)]


def _world_fiscal_levy_petitions(db: Any, state: Any) -> list:
    """#1892：三饷到点请旨事项——交世界段成陈情与拟旨，皇帝亲裁，不由模型代批。

    资格单一真源＝issues.gather_fiscal_levy_petitions；本函数只投影事件自身既有
    字段（不另设判门、不写终态）。军费实况仍走盘面既有段落，本目录不重造。

    另投影**已呈未决**事项的既有事实（#1891 后续世界段供料契约）：该事项此前已上疏
    皇帝、皇帝已批「留中」或尚未答复。推演者据此可另上疏续请，也可不再上疏；引擎
    不新增自动重呈机制，也不改判门（资格仍由 gather_fiscal_levy_petitions 判）。
    """
    from ming_sim.issues import gather_fiscal_levy_petitions

    presented = {}
    for row in db.list_event_petition_records():
        event_id = str(row.get("event_id") or "")
        record = row.get("petition")
        if not event_id or not isinstance(record, dict):
            continue
        # 答案字段（label/hint/note）与呈疏字段同在 choice_json 顶层，petition 段
        # 只放「何时呈、呈的什么」——两处都读，别只读一层。
        presented[event_id] = {
            **record,
            "emperor_label": str(row.get("label") or ""),
            "emperor_hint": str(row.get("hint") or ""),
            "emperor_note": str(row.get("note") or ""),
            # 留中＝已有请旨答复且终态仍空。不另记标记、不解析批语用词。
            "held": not str(row.get("terminal_state") or "").strip(),
        }
    items = []
    for ev in gather_fiscal_levy_petitions(state, db):
        record = presented.get(ev.id)
        item: dict = {
            "id": ev.id,
            "title": ev.title,
            "summary": ev.summary,
            # 封闭结局标签＝玩家批红可落的白名单；模型只可在此集内给选项标签，
            # 否则语义写口的归一器会 fail-loud。
            "verdict_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
        }
        if record is not None:
            # 逐字供给已呈奏疏原文与皇帝原批语（ADR 0142：不删改、不摘要成模板）。
            item["presented"] = {
                "presented_title": str(record.get("title") or ""),
                "presented_context": str(record.get("context") or ""),
                "emperor_label": record["emperor_label"],
                "emperor_hint": record["emperor_hint"],
                "emperor_note": record["emperor_note"],
                "held": record["held"],
                "presented_turn": record.get("presented_turn"),
                "presented_year": record.get("presented_year"),
                "presented_period": record.get("presented_period"),
                "held_turn": record.get("held_turn"),
            }
        items.append(item)
    return items


def _write_candidate_event_files(tmp: Path, db: Any, state: Any) -> list[str]:
    index: list[str] = []
    candidates = _world_candidate_events(db, state)
    index_rel = f"{_CANDIDATE_DIR}/INDEX.txt"
    # 索引与文件名同一真源：写盘用 _safe_segment，索引也必须用它拼，否则目录里
    # 每一条索引都指向不存在的文件（按原始 id 拼时两者不一致）。
    entries = [f"{_safe_segment(item['id'])}.txt" for item in candidates]
    _write_text(tmp / index_rel, "\n".join(entries))
    index.append(index_rel)
    for item, entry in zip(candidates, entries):
        rel = f"{_CANDIDATE_DIR}/{entry}"
        rows = [
            ("id", item["id"]),
            ("标题", item["title"]),
            ("类别", item["kind"]),
            ("事件类型", item["event_type"]),
            ("事由", item["summary"]),
            ("相关", "、".join(item["interests"])),
            ("前提门", json.dumps(item["trigger_gate"], ensure_ascii=False)),
            ("可解条件", item["resolve_condition"]),
            ("崩坏条件", item["fail_condition"]),
            ("历史前情与结果", item["precondition"]),
        ]
        if item.get("terminal_reason_labels"):
            rows.append(("封闭结局", "、".join(item["terminal_reason_labels"])))
        body = "\n".join(f"{label}：{value}" for label, value in rows)
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


def _write_fiscal_levy_petition_files(tmp: Path, db: Any, state: Any) -> list[str]:
    """#1892 J5：到点三饷写成「请旨事项」目录，供世界段据以上疏请旨（皇帝亲裁）。

    与「候选事件」分开：那里是交模型代选是否发生的人物事件；这里的事件发生权在
    皇帝，模型只负责陈情与拟旨，批红后才落终态。
    """
    index: list[str] = []
    petitions = _world_fiscal_levy_petitions(db, state)
    index_rel = f"{_PETITION_DIR}/INDEX.txt"
    entries = [f"{_safe_segment(item['id'])}.txt" for item in petitions]
    _write_text(tmp / index_rel, "\n".join(entries))
    index.append(index_rel)
    for item, entry in zip(petitions, entries):
        rel = f"{_PETITION_DIR}/{entry}"
        presented = item.get("presented")
        prior_lines = ""
        if isinstance(presented, dict):
            # 已呈未决的既有事实逐字供给（ADR 0142）：旧疏原文与皇帝原批语都原样写出，
            # 由推演者自行决定是否另上疏；引擎不加自动重呈。
            prior_lines = "\n".join((
                "",
                f"此前已呈：{presented.get('presented_title') or ''}",
                f"呈疏年份：{presented.get('presented_year')}",
                f"呈疏期：{presented.get('presented_period')}",
                f"已呈奏疏原文：{presented.get('presented_context') or ''}",
                f"皇帝原批语标签：{presented.get('emperor_label') or ''}",
                f"皇帝原批语提示：{presented.get('emperor_hint') or ''}",
                f"皇帝原批语：{presented.get('emperor_note') or ''}",
            ))
        body = "\n".join(
            f"{label}：{value}"
            for label, value in (
                ("id", item["id"]),
                ("事项", item["title"]),
                ("事由", item["summary"]),
                ("可批结局标签", "、".join(item["verdict_labels"])),
            )
        ) + prior_lines
        _write_text(tmp / rel, body)
        index.append(rel)
    return index


def _write_world_tree(
    tmp: Path,
    db: Any,
    state: Any,
    public_events: list,
    affair_lines: list[tuple[str, str, str, str]],
    board_text: str,
    denunciation_facts: dict[str, object],
    candidates: dict[str, list],
    include_fact: Any = None,
    include_event: Any = None,
    secret_turn_ids: set[int] | None = None,
    *,
    exclude_secret_order_dossiers: bool = False,
) -> list[str]:
    index: list[str] = []
    textual_facts = db.textual_facts

    board_rel = f"{_BOARD_DIR}/全局.txt"
    _write_text(tmp / board_rel, board_text)
    index.append(board_rel)

    denunciation_rel = f"{_BOARD_DIR}/派系检举事实.txt"
    _write_text(tmp / denunciation_rel, json.dumps(denunciation_facts, ensure_ascii=False))
    index.append(denunciation_rel)

    # #1893：人物事件与弹劾潮候选进同一份世界目录（硬门已在读侧判过），
    # 供同一次月末世界段里的模型自读挑选；不在此代选、不代发难。
    _write_text(tmp / _CANDIDATE_REL, json.dumps(candidates, ensure_ascii=False))
    index.append(_CANDIDATE_REL)

    _write_text(tmp / _COURT_ROSTER_REL, _world_roster_text(db, state))
    index.append(_COURT_ROSTER_REL)

    for name in _world_roster_names(db):
        knowledge = db.get_character_knowledge(state, name)
        person_dir = f"{_PERSON_DIR}/{_safe_segment(name)}"
        rel = f"{person_dir}/经历.txt"
        audience = _omit_secret_order_audience(_person_audience_experience(db, name), secret_turn_ids or set())
        _write_text(tmp / rel, _experience_text(
            _knowledge_for_experience(knowledge, include_event),
            audience,
        ))
        index.append(rel)
        # #1828/#1834：人物名下按月文字事实（负伤/患病等）单独一份，世界目录
        # 才有；人物私有经历目录（_write_tree）不注入，仍只按其知识见闻投影。
        facts_rel = f"{person_dir}/按月实况.txt"
        _write_text(tmp / facts_rel, _textual_facts_text(
            textual_facts, subject_kind="character", subject_id=name,
            include_fact=include_fact,
        ))
        index.append(facts_rel)

    for army_id in _world_subject_ids(db, "armies"):
        rel = f"{_ARMY_DIR}/{army_id}/按月实况.txt"
        _write_text(tmp / rel, _textual_facts_text(
            textual_facts, subject_kind="army", subject_id=army_id,
            include_fact=include_fact,
        ))
        index.append(rel)

    for region_id in _world_subject_ids(db, "regions"):
        rel = f"{_REGION_DIR}/{region_id}/按月实况.txt"
        _write_text(tmp / rel, _textual_facts_text(
            textual_facts, subject_kind="region", subject_id=region_id,
            include_fact=include_fact,
        ))
        index.append(rel)

    for dir_key, title, directory_text, _opening_text in affair_lines:
        seg = _safe_segment(dir_key)
        body = f"{title}\n{directory_text}" if title else directory_text
        rel = f"{_AFFAIR_DIR}/{seg}/当前情况.txt"
        _write_text(tmp / rel, body)
        index.append(rel)

    # 公共邸报供料已排除密令案卷时，实况旁路不得再无条件写入（#1897 F1）。
    if not exclude_secret_order_dossiers:
        index.extend(_write_secret_actual_note_files(tmp, db))
    index.extend(_write_candidate_event_files(tmp, db, state))
    index.extend(_write_fiscal_levy_petition_files(tmp, db, state))
    index.extend(_write_world_textual_fact_files(tmp, db, include_fact=include_fact))
    index.extend(_write_public_by_month(tmp, public_events))
    index.extend(_write_gazette_index(
        tmp,
        db.list_turn_reports(),
        prefix=_WORLD_GAZETTE_DIR,
    ))

    _write_text(tmp / _INDEX_NAME, "\n".join(index) if index else "")
    return index


def dossier_paid_amount(db: Any, dossier_id: object) -> int:
    """案卷已从账本实付总额（economy moves 负向 delta 之和）。

    世界段在途案卷与逐旨预推「本旨」事实共用；无案卷行或尚无动账时为 0。
    """
    try:
        oid = int(dossier_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if oid <= 0:
        return 0
    return sum(
        max(0, -int(move.get("delta") or 0))
        for move in db.list_economy_moves_for_dossier(oid)
    )


def revoke_target_facts(db: Any, payload: object, row: object = None) -> dict[str, object]:
    """#1894：撤令所指那道**原旨**的事实（原旨、已投入、办理进度、参与者）。

    供料接缝，不新增模型调用：撤令案卷的颁布判官（0055）与逐旨推演都据这份
    事实判断准行/劝回/拖延，以及准行后原案卷的办理结果怎么落。只读 DB 真源；
    目标身份解析复用 ``db.resolve_revoke_decree_target_ids``（判后物化同一实现，
    禁平行口径），身份取自载荷与案卷行（与判后物化同一读口，缺行即漏回退）；
    查无此事时返回空 dict（调用方按「无原旨可读」处理，不猜）。
    """
    if not isinstance(payload, Mapping) and not isinstance(row, Mapping):
        return {}
    # #1853 J8-R2：resolve_revoke_decree_target_ids 为 GameDB 必备接口；
    # 只捕获业务拒收（ValueError/TypeError→无原旨可读），禁 AttributeError 缺方法软空。
    try:
        target_dossier_id, target_issue_id = db.resolve_revoke_decree_target_ids(payload, row)
    except (TypeError, ValueError):
        return {}
    dossier = db.get_decree_dossier(int(target_dossier_id))
    if dossier is None:
        return {}
    roster = [
        {
            "character_id": str(item.get("character_id") or ""),
            "tier": str(item.get("tier") or ""),
            "role": str(item.get("role") or ""),
        }
        for item in (dossier.get("participant_roster") or [])
        if isinstance(item, dict)
    ]
    progress = [
        {
            "turn": int(row.get("turn") or 0),
            "progress_band": str(row.get("progress_band") or ""),
            "narrative": str(row.get("narrative") or ""),
            "is_terminal": bool(row.get("is_terminal")),
        }
        for row in db.list_dossier_progress(int(target_dossier_id))
    ]
    return {
        "dossier_id": int(target_dossier_id),
        "issue_id": int(target_issue_id),
        "status": str(dossier.get("status") or ""),
        "action_type": str(dossier.get("action_type") or ""),
        "decree_text": str(dossier.get("decree_text") or ""),
        "promulgated_turn": int(dossier.get("promulgated_turn") or 0),
        "executor_id": str(dossier.get("executor_id") or ""),
        "paid": dossier_paid_amount(db, int(target_dossier_id)),
        "participant_roster": roster,
        "progress": progress,
    }


def continuing_dossier_facts(db: Any, turn: int) -> list[dict[str, object]]:
    """本月世界段要接着办的案卷：模拟清单里仍在执行的。

    真实强颁在同一次颁布里会把在途案卷转入 executing，或把终局载荷结案，
    不会带着 promulgated 进入次月。
    """
    rows = db.list_decree_dossiers_for_simulation(int(turn))
    facts: list[dict[str, object]] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status != "executing":
            continue
        dossier_id = int(row["id"])
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        facts.append({
            "id": dossier_id,
            "status": status,
            "decree_text": str(row.get("decree_text") or ""),
            "action_type": str(row.get("action_type") or ""),
            "target_kind": str(row.get("target_kind") or ""),
            "target_id": str(row.get("target_id") or ""),
            "grant_action": str(payload.get("grant_action") or ""),
            "paid": dossier_paid_amount(db, dossier_id),
        })
    return facts


def _world_opening_text(
    state: Any,
    board_text: str,
    affair_lines: list[tuple[str, str, str, str]],
    dossier_facts: list[dict[str, object]],
    *,
    events: int = 0,
    surges: int = 0,
) -> str:
    from ming_sim.models import reign_period_label

    parts = [
        f"日期：{reign_period_label(int(state.year), int(state.period))}",
        "盘面：",
        board_text,
        "开着的事务：" if affair_lines else "开着的事务：（无）",
    ]
    parts.extend(f"- {title}：{opening_text}" for _key, title, _directory_text, opening_text in affair_lines)
    parts.append("在途办理案卷：" if dossier_facts else "在途办理案卷：（无）")
    for fact in dossier_facts:
        parts.append(
            f"- dossier:{fact['id']} {fact['decree_text']}；"
            f"办理动作：{fact['action_type']}；"
            f"目标：{fact['target_kind']}:{fact['target_id']}；"
            f"拨款：{fact['grant_action']}；实付：{fact['paid']}万两"
        )
    # #1893：候选事实在目录里（硬门已判过），本段自行读、自行挑；开场只报条数。
    parts.append(
        f"本月候选：人物事件 {events} 项，弹劾潮 {surges} 项，"
        f"在 {_CANDIDATE_REL}，按需自读。"
    )
    parts.append(
        "到点须皇帝亲裁的事项在「请旨事项」目录（按 INDEX 自读）：这些不由你决定成败，"
        "你只据盘面与军费实况上疏陈情、拟出请旨，请旨块的 event_id 写该事项 id，"
        "选项标签只取该事项列出的可批结局标签；皇帝批红后结局才落账。"
    )
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
        row = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (name,),
        ).fetchone()
        if row is not None:
            office = str(row["office"] or "")
        rows.append((name, office))
    return rows


def _json_list_field(raw: object) -> list[str]:
    """DB 人物 aliases/personal_skills：腐坏响亮，不 catch-to-[]（#1897 E1）。"""
    from ming_sim.db import _load_durable_str_list
    return _load_durable_str_list(raw, surface="characters.json_list_field")


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
        intrigue=_int("intrigue", 50),
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
    row = db.conn.execute(
        """
        SELECT name, office, office_type, faction, aliases, personal_skills,
               loyalty, ability, integrity, courage, style, identity, intrigue,
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
    if night is None:
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


def _scene_pending_audience_facts(db: Any, state: Any) -> list[str]:
    """#1838 reopen：待裁场面原样事实（到期复命 / 暗渠摊派暴露与缺口重开 / 谏催）。

    原喂开夜旁白；现并入场景开场最小集。结构化事实原样，不加措辞模板。
    """
    from ming_sim.audience_night import list_unsettled_summons
    from ming_sim.due_review import list_due_review_scenes
    from ming_sim.urge_lever import list_urge_audience_scenes

    lines: list[str] = []
    for scene in list(list_due_review_scenes(db, state)) + list(
        list_urge_audience_scenes(db, state)
    ):
        if not isinstance(scene, dict):
            continue
        lines.append(json.dumps(scene, ensure_ascii=False, sort_keys=True))
    for summon in list_unsettled_summons(db):
        facts = {key: summon[key] for key in ("person_name", "kind", "travel_tone") if key in summon}
        lines.append(json.dumps(facts, ensure_ascii=False, sort_keys=True))
    return lines


def _scene_opening_text(
    state: Any,
    present_rows: Sequence[tuple[str, str]],
    spoken: str,
    handling_by_person: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    pending_audience_facts: Sequence[str] = (),
) -> str:
    """场景 LLM 开场最小集（ADR 0155）：在场、日期、正经手、本场已说、当前待裁场面。"""
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
    # #1838 reopen / ADR 0155：当前待裁场面（到期复命、暗渠摊派暴露/缺口重开）
    parts.append("当前待裁场面：")
    if pending_audience_facts:
        parts.extend(str(line) for line in pending_audience_facts)
    else:
        parts.append("（无）")
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
    audible = _person_audience_experience(db, name)
    _write_text(tmp / exp_rel, _experience_text(knowledge, audible))
    index.append(exp_rel)

    from ming_sim.knowledge import origin_visible_to

    # #1839 / ADR 0156：文字事实当场落账后须进本夜场景目录（下一句可见）。
    # 与世界目录同形（按月实况），投影复用 _textual_facts_text，不另造读口。
    facts_rel = f"{base}/按月实况.txt"
    _write_text(
        tmp / facts_rel,
        _textual_facts_text(
            db.textual_facts,
            subject_kind="character", subject_id=name,
            include_fact=lambda fact: origin_visible_to(db, fact.origin_ref, name),
        ),
    )
    index.append(facts_rel)

    from ming_sim.recommendations import build_recommendation_brief
    recommend_rel = f"{base}/{_RECOMMEND_DIR}/可荐人切片.txt"
    _write_text(tmp / recommend_rel, build_recommendation_brief(db, state, name))
    index.append(recommend_rel)

    office_rel = f"{base}/公事档案.txt"
    _write_text(
        tmp / office_rel,
        character_office_archive_text(db, state, character, knowledge),
    )
    index.append(office_rel)

    secret_rel = _write_secret_order_file(
        tmp, db, state, character, rel=f"{base}/{_SECRET_DIR}/进行中.txt",
    )
    if secret_rel:
        index.append(secret_rel)
    index.extend(_inquiry_monthly_report_rels(
        tmp, db, character, knowledge, prefix=f"{base}/",
    ))

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

    # 公开层与单人目录同形：按月公开说法 + 本人有权读取的历月邸报载体，各写在自己
    # 名下私有子树。#1830：准入与人读呈现走 _write_character_public_layer 这一个
    # 入口，不在此另写一份逐条循环（原先此处无邸报门，邸报会混进公开说法）。
    index.extend(_write_character_public_layer(
        tmp, knowledge.get("public_events") or [], db, base=base,
    ))

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
    from ming_sim.audience_night import get_open_night

    present_rows = _scene_present_rows(db, state)
    night = get_open_night(db)
    night_id = int(night["id"]) if night is not None else 0
    spoken = _scene_spoken_text(db)
    content = db.content
    characters = getattr(content, "characters", None) or {}

    # 一次 prepare 冻结每人 knowledge + matter_lines，目录与 opening 共用。
    person_payloads: list[tuple[Any, dict, list]] = []
    handling_by_person: list[tuple[str, list[tuple[str, str]]]] = []
    for name, office in present_rows:
        character = _resolve_present_character(db, name, office, characters)
        knowledge = db.get_character_knowledge(state, name)
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
    pending_facts = _scene_pending_audience_facts(db, state)
    opening = _scene_opening_text(
        state, present_rows, spoken, handling_by_person, pending_facts,
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))


def actual_progress_notes(db: Any, dossier_id: int) -> list[dict[str, object]]:
    """实况轨原文读投影。未提供正文的空串不算一行；显式正文（含空白）原样。"""
    if not hasattr(db, "list_dossier_actual_progress"):
        return []
    notes: list[dict[str, object]] = []
    for row in db.list_dossier_actual_progress(int(dossier_id)):
        note = str(row.get("note") or "")
        # 仅缺省空串视为无正文；不以 strip 丢弃显式空白（P6 / #1897 N2）。
        if note == "":
            continue
        notes.append({"turn": int(row.get("turn") or 0), "note": note})
    return notes


def _write_secret_actual_note_files(tmp: Path, db: Any) -> list[str]:
    """推演目录里的实况原文。人物目录与滤掉密令案卷的邸报目录不写。"""
    if not hasattr(db, "list_secret_orders") or not hasattr(db, "get_dossier_for_secret_order"):
        return []
    written: list[str] = []
    for order in db.list_secret_orders():
        dossier = db.get_dossier_for_secret_order(int(order["id"]))
        if dossier is None:
            continue
        notes = actual_progress_notes(db, int(dossier["id"]))
        if not notes:
            continue
        body = "\n".join(f"回合：{item['turn']}\n{item['note']}" for item in notes)
        rel = f"{_SECRET_DIR}/实况/{int(order['id'])}.txt"
        _write_text(tmp / rel, body)
        written.append(rel)
    return written


def prepare_world_materials(
    db: Any,
    state: Any,
    *,
    dest_root: Optional[Path] = None,
    include_fact: Any = None,
    include_event: Any = None,
    exclude_secret_order_dossiers: bool = False,
    exclude_secret_order_audience: bool = False,
    public_feed: bool = False,
) -> PreparedMaterials:
    """过月推演者材料目录：盘面全量 + 开着的事务清单进开场最小集；人物经历、
    公开说法、历月邸报按需自读（#1834）。写入（拒收/实况回目录、下月材料）不
    在本函数职责内——本函数只组装可读材料，不提供任何写入口。

    `public_feed=True` selects the public author; world simulation and private
    reports retain the full read surface.
    """
    from ming_sim.knowledge import build_character_knowledge

    # Reuse the public-version read projection. Full world facts and each
    # person's own experiences are read independently below.
    knowledge = build_character_knowledge(db, state, "")
    public_events = knowledge.get("public_events") or []
    affair_lines = _world_affair_lines(db, include_fact)
    dossier_facts = continuing_dossier_facts(db, int(state.turn))
    # #1834 大理寺 bounce 3：与人物经历同一纪律——本次 prepare 只算一次盘面全量
    # 投影，目录写入与 opening 共用同一份冻结结果，不重复查两遍账本。
    secret_dossiers = secret_order_dossier_ids(db) if exclude_secret_order_dossiers else set()
    if secret_dossiers:
        dossier_facts = [
            fact for fact in dossier_facts
            if int(fact["id"]) not in secret_dossiers
        ]
    board_text = _world_board_text(
        db, state, public_only=public_feed,
    )
    denunciation_facts = db.build_faction_denunciation_facts(
        exclude_dossier_ids=secret_dossiers,
    )
    # #1893：候选只在世界段起调时取一次，目录写入与 opening 共用同一份冻结结果。
    candidates = candidate_supply(db, state, exclude_dossier_ids=secret_dossiers or None)

    dest, index = _publish_material_tree(
        dest_root,
        world_materials_root(db, state),
        lambda tmp: _write_world_tree(
            tmp, db, state, public_events, affair_lines, board_text,
            denunciation_facts, candidates, include_fact, include_event,
            _secret_order_chat_turn_ids(db) if exclude_secret_order_audience else None,
            exclude_secret_order_dossiers=exclude_secret_order_dossiers,
        ),
    )

    opening = _world_opening_text(
        state, board_text, affair_lines, dossier_facts,
        events=len(candidates["events"]),
        surges=len(candidates["impeachment_surge"]),
    )
    return PreparedMaterials(root=dest, opening=opening, index_lines=tuple(index))

def _inquiry_monthly_report_rels(
    tmp: Path,
    db: Any,
    character: Any,
    knowledge: dict,
    *,
    prefix: str = "",
) -> list[str]:
    """查访声明点名的密令，只拉该令当前月度非终值奏报。

    见闻里没有 order 标记的委派不打开任何密令。承办人自己的在办令已在进行中.txt。
    委派是经手授权，与官职无关。没有月报正文就不写文件。
    """
    from ming_sim.knowledge import knowledge_row_visible_to

    name = str(getattr(character, "name", "") or "")
    if not name or not hasattr(db, "list_secret_orders"):
        return []
    own_active: set[int] = set()
    if hasattr(db, "get_active_secret_orders_for_minister"):
        own_active = {
            int(order["id"])
            for order in db.get_active_secret_orders_for_minister(name)
        }
    by_id = {int(order["id"]): order for order in db.list_secret_orders()}
    written: list[str] = []
    seen: set[int] = set()
    for event in knowledge.get("events") or []:
        if str(event.get("kind") or "") != "inquiry_assignment":
            continue
        order_id = inquiry_source_order_id(event.get("source_id"))
        if order_id is None or order_id in seen or order_id in own_active:
            continue
        seen.add(order_id)
        order = by_id.get(order_id)
        if order is None:
            continue
        if not knowledge_row_visible_to(db, {"source_id": f"secret_order:{order_id}"}, name):
            continue
        texts = _secret_order_memorials(order)
        if not texts:
            continue
        rel = f"{prefix}{_SECRET_DIR}/查访月报/{order_id}.txt"
        _write_text(tmp / rel, "\n".join(texts))
        written.append(rel)
    return written


def inquiry_source_order_id(source_id: object) -> Optional[int]:
    """从见闻 source_id 取出已声明的密令 id。无标记或非十进制则不是查访读轨。"""
    text = str(source_id or "")
    if not text.startswith("inquiry:"):
        return None
    _, separator, tail = text.partition(":order:")
    token = tail.partition(":")[0]
    if not separator or not token.isascii() or not token.isdecimal():
        return None
    return int(token)


def inquiry_order_source_suffix(order_id: int) -> str:
    """查访见闻指向一条密令的结构化后缀。不用 secret_order: 前缀。"""
    return f":order:{int(order_id)}"
