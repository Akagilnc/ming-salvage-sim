"""结算中止错误包（ADR 0008 决定 6/7）。

代码异常 / extractor 失败中止结算时，自动落一份诊断包到 user-data 可写目录（frozen 下
`data/` 相对路径不可写，必走 paths.py 的 user-data helper），供试玩者手动发回作者。
包内四件：traceback / resolve_context / 存档副本(SQLite backup API) / manifest。

事务边界铁律：错误包**必须在回滚后、atomic 之外**写——db.backup_to 在 atomic 内会响亮拒绝
（备份走同连接 pager 会带未提交脏页；守卫在 db.backup_to，flag 由 applier.atomic 置）。

attempt 计数**从错误目录已有文件推导**（同 turn 既有目录数字后缀 max+1），不从 DB 取——DB
随回滚重置（决定 5）。建包目录 exist_ok=False：错误包是诊断孤本，任何路径都不许静默覆盖
既有包（非连续目录 / 并发双失败时 len+1 会撞名，cmr S6 r1）。写包本身要稳：目录创建 /
写文件失败不得吞掉原异常（链式 raise ... from，同 pre_settle reload 先例）。
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ming_sim.applier import safe_json_dumps
from ming_sim.paths import bundled_path, user_data_dir

logger = logging.getLogger(__name__)


_ERROR_PACKS_SUBDIR = "error_packs"


def error_packs_root() -> Path:
    """错误包根目录（user-data 下固定子目录）。"""
    return user_data_dir() / _ERROR_PACKS_SUBDIR


def rejections_jsonl_path() -> str:
    """拒收 jsonl 镜像路径（ADR 0008 决定 7：与错误包集中同一 user-data 目录，一次打包全带走）。

    RejectionCollector.mirror_to_jsonl 的目标路径约定 = user-data 错误目录下 `rejections.jsonl`。
    返回前确保父目录就位——mirror 是纯机械 append（open(path,"a") 不建父），开箱即写。
    commit 成功且最外层事务退出后 mirror。
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
    except OSError:
        logger.exception("error pack VERSION read failed path=%s", bundled_path("VERSION"))
        return "unknown"


def settlement_abort_message(pack_path: str, *, reason: str) -> str:
    """中止时透传故障原因及错误包路径（决定 7）。"""
    return (
        f"{reason}\n本月结算失败，进度已保存，可重试。\n"
        f"错误包已生成：{pack_path}\n"
        "请把该文件夹发给作者，以便排查。"
    )


def write_error_pack(
    db: Any,
    state: Any,
    *,
    exc: BaseException,
) -> str:
    """落一份错误包到 user-data 错误目录，返回包目录路径（绝对）。

    必须在回滚后、atomic 之外调用：内部 db.backup_to 走 conn.backup() API，在 atomic 内
    （_commit_suspended）会响亮 RuntimeError——这是设计约束（脏页备份），不在此处吞。

    内容：
      - traceback.txt        完整 traceback
      - resolve_context.json db.resolve_contexts.get(turn)（无则 null）
      - save_backup.db       SQLite 热备（conn.backup() API）
      - manifest.json        db 路径 / turn / 年月 / 版本 / attempt / 异常类型+消息 / 时间戳

    诊断包不参与恢复；恢复规则见 #1846。
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

    # resolve_context.json（无则 null）
    (pack_dir / "resolve_context.json").write_text(
        safe_json_dumps(db.resolve_contexts.get(turn), ensure_ascii=False, indent=2), encoding="utf-8"
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
        "exception_type": getattr(exc, "error_type", None) or type(exc).__name__,
        "exception_message": str(exc),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (pack_dir / "manifest.json").write_text(
        safe_json_dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return str(pack_dir)
