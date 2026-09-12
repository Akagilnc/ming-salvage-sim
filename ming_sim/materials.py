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
import uuid
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
_BOARD_DIR = "盘面"
_GAZETTE_DIR = "邸报"
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


def _materials_invocation_dir(db: Any, state: Any) -> Path:
    from ming_sim.audience_night import get_open_night

    db_path = Path(str(getattr(db, "path", "") or ".")).resolve()
    night = get_open_night(db)
    key = f"night-{int(night['id'])}" if night else f"turn-{int(state.turn)}"
    return (
        db_path.parent / "materials" / _safe_segment(db_path.name) / key / uuid.uuid4().hex
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
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise
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


def material_tools(root: Path) -> list:
    """API-channel list/read tools bound to one prepared directory."""

    def project_error(operation: str, call: Any, *args: object) -> str:
        try:
            return call(*args)
        except (ValueError, FileNotFoundError) as exc:
            return f"无法{operation}：{exc}"

    def list_materials_tool(path: str = "") -> str:
        """列出当前材料目录中可读的文件（相对路径，一行一项）。"""
        return project_error("读取", lambda value: "\n".join(list_materials(root, value)), path)

    def read_material_tool(path: str) -> str:
        """读取材料目录中的一份人读文本。path 为相对路径，如 人物/某人/经历.txt。"""
        return project_error("读取", read_material, root, path)

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


def _write_secret_order_file(tmp: Path, db: Any, state: Any, character: Any) -> str | None:
    """Directory copy of the minister's active secret-order reminder.

    Logic lives here after #1833 retired the registry brief builder; content
    matches the former ``build_secret_order_brief`` projection.
    """
    name = str(getattr(character, "name", "") or "")
    try:
        orders = db.get_active_secret_orders_for_minister(name) if name else []
    except Exception:
        orders = []
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
            content_brief = (o.get("content") or "")[:80].replace("\n", " ")
            if content_brief:
                lines.append(f"    （任务摘要：{content_brief}…）")
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

    index.extend(_write_public_by_month(tmp, knowledge.get("public_events") or []))
    index.extend(_write_gazette_index(tmp, db))

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


def _experience_text(knowledge: dict) -> str:
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
    return "\n".join(lines) or "（无）"


def _write_public_by_month(tmp: Path, public_events: list) -> list[str]:
    """公开说法按月分文件（#1830 既有形态，供人物目录与推演者目录共用）。"""
    index: list[str] = []
    public_by_month: dict[tuple[int, int], list[str]] = {}
    for item in public_events or []:
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


# ── 过月推演者材料目录（#1834 / ADR 0153 / 0155 / 0157）──
#
# 推演者三层全看（实况 + 人物经历 + 公开说法），另有盘面（0155 读取形态段）。
# 开场最小集 = 当前盘面全量 + 开着的事务清单；其余（各人经历、公开说法、历月
# 邸报）按需自读。夜里预推段与过月世界段读同一目录（同 night/turn key，与
# character_materials_root 同构）；预推产物本身不进目录（0157 原则）——本模块
# 只备读，不提供任何暂存写入口，天然不会把预推产物写进来。


def world_materials_root(db: Any, state: Any) -> Path:
    return _materials_invocation_dir(db, state) / "世界推演"


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
        opening_text = str(facts[-1].body or "").strip() if facts else "见目录。"
        lines.append((f"affair-{affair.id}", str(affair.name or ""), directory_text, opening_text))
    return lines


def _write_gazette_index(tmp: Path, db: Any) -> list[str]:
    """历月邸报一行索引入目录（章节记忆退役，M3；0155/0157 后出注记）：每回合一份
    全文文件，根 INDEX 里天然是一行一项——不再压缩/摘要成第二套机制。"""
    index: list[str] = []
    for row in db.list_turn_reports():
        year = int(row.get("year") or 0)
        period = int(row.get("period") or 0)
        turn = int(row.get("turn") or 0)
        fname = f"{year}年{period}月.txt" if year and period else f"turn-{turn}.txt"
        rel = f"{_GAZETTE_DIR}/{fname}"
        _write_text(tmp / rel, str(row.get("report") or ""))
        index.append(rel)
    return index


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
        rel = f"{_PERSON_DIR}/{_safe_segment(name)}/经历.txt"
        _write_text(tmp / rel, _experience_text(knowledge))
        index.append(rel)

    for dir_key, title, directory_text, _opening_text in affair_lines:
        seg = _safe_segment(dir_key)
        body = f"{title}\n{directory_text}" if title else directory_text
        rel = f"{_AFFAIR_DIR}/{seg}/当前情况.txt"
        _write_text(tmp / rel, body)
        index.append(rel)

    index.extend(_write_public_by_month(tmp, public_events))
    index.extend(_write_gazette_index(tmp, db))

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
