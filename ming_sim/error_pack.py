"""结算中止错误包（ADR 0008 决定 6/7）。

代码异常 / extractor 失败中止结算时，自动落一份诊断包到 user-data 可写目录（frozen 下
`data/` 相对路径不可写，必走 paths.py 的 user-data helper），供试玩者手动发回作者。
包内五件：traceback / delta / resolve_context / 存档副本(SQLite backup API) / manifest。

事务边界铁律：错误包**必须在回滚后、atomic 之外**写——db.backup_to 在 atomic 内会响亮拒绝
（备份走同连接 pager 会带未提交脏页；守卫在 db.backup_to，flag 由 applier.atomic 置）。

attempt 计数**从错误目录已有文件推导**（同 turn 既有目录数字后缀 max+1），不从 DB 取——DB
随回滚重置（决定 5）。建包目录 exist_ok=False：错误包是诊断孤本，任何路径都不许静默覆盖
既有包（非连续目录 / 并发双失败时 len+1 会撞名，cmr S6 r1）。写包本身要稳：目录创建 /
写文件失败不得吞掉原异常（链式 raise ... from，同 pre_settle reload 先例）。
"""

from __future__ import annotations

import hashlib
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ming_sim.applier import atomic, safe_json_dumps
from ming_sim.paths import bundled_path, user_data_dir


_ERROR_PACKS_SUBDIR = "error_packs"


def error_packs_root() -> Path:
    """错误包根目录（user-data 下固定子目录）。"""
    return user_data_dir() / _ERROR_PACKS_SUBDIR


def rejections_jsonl_path() -> str:
    """拒收 jsonl 镜像路径（ADR 0008 决定 7：与错误包集中同一 user-data 目录，一次打包全带走）。

    RejectionCollector.mirror_to_jsonl 的目标路径约定 = user-data 错误目录下 `rejections.jsonl`。
    返回前确保父目录就位——mirror 是纯机械 append（open(path,"a") 不建父），开箱即写。
    接线于 settle_with_delta（PR2-S0）：commit 成功且最外层事务退出后 mirror。
    """
    root = error_packs_root()
    root.mkdir(parents=True, exist_ok=True)
    return str(root / "rejections.jsonl")


def _next_attempt(turn: int) -> int:
    """同 turn 的下一个 attempt 序号：既有目录数字后缀 max+1（决定 5，不从 DB 取）。

    len+1 在非连续目录（玩家发包后删过早期 attempt）下会撞既有名而静默覆盖诊断孤本；
    不可解析的后缀忽略。
    """
    root = error_packs_root()
    if not root.exists():
        return 1
    prefix = f"turn{int(turn)}_attempt"
    highest = 0
    for p in root.iterdir():
        if not (p.is_dir() and p.name.startswith(prefix)):
            continue
        try:
            highest = max(highest, int(p.name[len(prefix):]))
        except ValueError:
            continue
    return highest + 1


def _read_version() -> str:
    """读 VERSION 文件（bundled）；缺失 / 读失败回 'unknown'，绝不让写包失败。"""
    try:
        return Path(bundled_path("VERSION")).read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def ready_payload_digest(payload: object) -> str:
    """Stable identity for an ADR0008 persisted ready payload."""
    canonical = safe_json_dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_COMPLETE_PACK_FILES = frozenset({
    "traceback.txt", "delta.json", "resolve_context.json",
    "save_backup.db", "manifest.json",
})


def _read_complete_pack_manifest(path: Path) -> Optional[Dict[str, object]]:
    """完整五件包的 manifest 身份；残缺/坏 JSON → None。complete/latest 共用。"""
    if not path.is_dir() or not all((path / name).is_file() for name in _COMPLETE_PACK_FILES):
        return None
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def complete_error_packs_for_ready(db_path: object, turn: int, payload: object) -> list[Path]:
    """Return complete packs for this database, turn, and exact ready payload."""
    expected = ready_payload_digest(payload)
    expected_db_path = str(db_path)
    root = error_packs_root()
    if not root.exists():
        return []
    matches: list[Path] = []
    for path in root.glob(f"turn{int(turn)}_attempt*"):
        manifest = _read_complete_pack_manifest(path)
        if manifest is None:
            continue
        if (
            str(manifest.get("db_path")) == expected_db_path
            and manifest.get("turn") == int(turn)
            and manifest.get("ready_payload_digest") == expected
        ):
            matches.append(path)
    return matches


def settlement_abort_message(pack_path: str) -> str:
    """中止时的玩家可见提示（决定 7：自带路径指引）。"""
    return (
        "本月结算失败，进度已保存，可重试。\n"
        f"错误包已生成：{pack_path}\n"
        "请把该文件夹发给作者，以便排查。"
    )


def latest_error_pack_for_turn(db_path: object, turn: int) -> Optional[str]:
    """同 DB + turn 最新完整错误包绝对路径；无则 None（ADR 0008 决定 7 恢复面）。

    身份与 complete_error_packs_for_ready 同缝：manifest.db_path + turn，
    禁跨存档串包（同 user-data 下另一 DB 的更高 attempt 不得入选）。
    """
    root = error_packs_root()
    if not root.exists():
        return None
    expected_db_path = str(db_path)
    prefix = f"turn{int(turn)}_attempt"
    best: Optional[Path] = None
    best_n = -1
    for path in root.iterdir():
        if not (path.is_dir() and path.name.startswith(prefix)):
            continue
        try:
            n = int(path.name[len(prefix):])
        except ValueError:
            continue
        manifest = _read_complete_pack_manifest(path)
        if manifest is None:
            continue
        if (
            str(manifest.get("db_path")) != expected_db_path
            or manifest.get("turn") != int(turn)
        ):
            continue
        if n > best_n:
            best_n = n
            best = path
    return str(best.resolve()) if best is not None else None


def write_error_pack(
    db: Any,
    state: Any,
    *,
    exc: BaseException,
    extracted: Optional[Dict[str, object]] = None,
    resolve_ctx: Optional[Dict[str, object]] = None,
) -> str:
    """落一份错误包到 user-data 错误目录，返回包目录路径（绝对）。

    必须在回滚后、atomic 之外调用：内部 db.backup_to 走 conn.backup() API，在 atomic 内
    （_commit_suspended）会响亮 RuntimeError——这是设计约束（脏页备份），不在此处吞。

    内容：
      - traceback.txt        完整 traceback
      - delta.json           当回合 delta（无则 {} + 说明）
      - resolve_context.json db.get_resolve_context(turn)（无则 null）
      - save_backup.db       SQLite 热备（conn.backup() API）
      - manifest.json        db 路径 / turn / 年月 / 版本 / attempt / 异常类型+消息 / 时间戳

    extractor 失败（LLM 失败）也写包：delta 为空，但 traceback+manifest 有诊断价值；重试本就
    要重跑贵调用，不存 delta 不损失什么（决定 6）。
    """
    turn = int(getattr(state, "turn", 0))
    # exist_ok=False + 撞名重试：诊断孤本绝不静默覆盖（并发双失败 / 非连续目录撞名时
    # 升号再试，cmr S6 r1）。
    attempt = _next_attempt(turn)
    while True:
        pack_dir = error_packs_root() / f"turn{turn}_attempt{attempt}"
        try:
            pack_dir.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            attempt += 1

    # traceback.txt
    tb_text = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    (pack_dir / "traceback.txt").write_text(tb_text, encoding="utf-8")

    # delta.json（extractor 失败时 extracted=None → {} + 说明）
    if extracted is None:
        delta_payload: Dict[str, object] = {
            "_note": "extractor 失败 / 无 delta；本回合无可落库产物（重试将重跑 simulator/extractor）。",
        }
    else:
        delta_payload = extracted
    (pack_dir / "delta.json").write_text(
        safe_json_dumps(delta_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # resolve_context.json（无则 null）
    (pack_dir / "resolve_context.json").write_text(
        safe_json_dumps(resolve_ctx, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # save_backup.db（仅 conn.backup() API；atomic 内会被 backup_to 拒绝）
    db.backup_to(str(pack_dir / "save_backup.db"))

    # manifest.json
    manifest = {
        "db_path": getattr(db, "path", None),
        "turn": turn,
        "year": getattr(state, "year", None),
        "period": getattr(state, "period", None),
        "version": _read_version(),
        "attempt": attempt,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ready_payload_digest": ready_payload_digest(extracted) if extracted is not None else None,
    }
    (pack_dir / "manifest.json").write_text(
        safe_json_dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return str(pack_dir)


# #671：sim 真成功后、companion join 前的 durable 完成态标记（∈ simulator_payload）。
# 唯一命中条件：payload.get(KEY) is True。clear_for_resimulation 必剥，避免撞 ADR 0008 重推演。
ARRIVAL_COMPANION_SIM_DONE_KEY = "arrival_companion_sim_done"


def clear_for_resimulation(db: Any, turn: int) -> None:
    """「重新推演」逃生口（ADR 0008 决定 6）：把 resolve_context 降级为非 ready，
    让重试重跑 simulator/extractor。

    **降级而非删行**（cmr S7 r3，2/2）：决定 6 的「清」指清 LLM 段产出（extracted），
    phase1 字段（叙事/诏书/payload/亲裁上下文）是 HITL 重抽的数据依赖、且是唯一持久副本
    ——整行删除会把 HITL 叉钉进「awaiting+决策在+context 没了 → phase2 永远拒收」的新
    软死锁。降级后：settling 叉重试 extracted=None → 恢复分流不命中 → fallthrough 重新
    推演；HITL 叉重试走 phase2 非 ready 分支用存的叙事+亲裁指令重抽。

    **settling 相位不清**：pre_settle 前半段确实提交了（固定财政 + 暂存动作），重推演
    只重跑 LLM 段，前半段不可重跑（否则二次 tick）。

    **单事务原子性**（#656 A2-r4）：rejection 作废标记、该 turn 陈旧票拟行删除、
    ready context 降级同处一个 `applier.atomic(db)`——中途任何一步失败（如降级写
    异常）整体回滚，不留「票拟已删、ready 真源仍在」的半作废状态。atomic 内
    commit 全部暂停，由最外层统一落定。
    """
    ctx = db.get_resolve_context(int(turn))
    with atomic(db):
        db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rejection_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                section TEXT NOT NULL,
                item_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1,
                resimulation_invalidated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cols = {str(row[1]) for row in db.conn.execute("PRAGMA table_info(rejection_reports)").fetchall()}
        if "resimulation_invalidated" not in cols:
            db.conn.execute(
                "ALTER TABLE rejection_reports ADD COLUMN resimulation_invalidated INTEGER NOT NULL DEFAULT 0"
            )
        db.conn.execute(
            "UPDATE rejection_reports SET resimulation_invalidated=1 WHERE turn=?",
            (int(turn),),
        )
        # #656 A2：重模拟作废与陈旧票拟同生死——ready context 降级的同一作废动作里，
        # 清掉该 turn 已持久化的 kind='rescript_draft' 行（ADR 0008 决定 6「清 LLM 段
        # 产出」：票拟行是 LLM 段产出）。否则重跑若抽取为空／降级／分拣人缺位，旧票拟
        # 会残留并冒充本月头版。phase1 context 与 decision 行不动；复用现表，不建 tombstone。
        db.conn.execute(
            "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'rescript_draft'",
            (int(turn),),
        )
        if ctx is None:
            return
        # #671：剥 companion 完成态标记——降级后 ready=0 且 narrative/attendant 可非空，
        # 但不得命中标记，SETTLING fallthrough 仍按 ADR 0008 重跑 simulator。
        payload = (
            dict(ctx["simulator_payload"])
            if isinstance(ctx.get("simulator_payload"), dict)
            else {}
        )
        payload.pop(ARRIVAL_COMPANION_SIM_DONE_KEY, None)
        db.save_resolve_context(
            int(turn),
            str(ctx.get("decree_text") or ""),
            str(ctx.get("narrative") or ""),
            payload,
            # 分组承载是 dict（#48）；兼容在途旧 list 形状的 ctx，二者都透传。
            secret_orders=ctx.get("secret_orders") if isinstance(ctx.get("secret_orders"), (list, dict)) else {},
            relevant_memories=ctx.get("relevant_memories") if isinstance(ctx.get("relevant_memories"), list) else [],
            # 拒收来源随降级保留（#144 cmr r1）：source 是 phase1 持久字段，重抽后
            # 恢复重放仍需原始 provenance 判玩家可见性；不回传会被默认 system_simulation
            # 盖掉原 player_decree/hitl_decision，使降级路径静默吞掉玩家可见提示。
            source=str(ctx.get("source") or "system_simulation"),
            # #671：王承恩递话随 phase1 字段保留，不得因重模拟降级清空。
            attendant_message=str(ctx.get("attendant_message") or ""),
            # 不传 extracted → upsert ready=0：LLM 段产出清除，phase1 字段保留。
        )
