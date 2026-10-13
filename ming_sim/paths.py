"""路径解析：分离只读资源（bundled）与用户数据（可写）。L0。

打包发布模式（PyInstaller --onefile）：
  - bundled_path("content/foo.json") → sys._MEIPASS/content/foo.json（只读，临时解压目录）
  - user_data_dir() → ~/.ming_sim/（跨进程持久，user 可写）

源码开发模式：
  - bundled_path("content/foo.json") → <repo>/content/foo.json
  - user_data_dir() → <repo>/data/（沿用旧布局）

判依据：sys.frozen 由 PyInstaller 注入。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否在 PyInstaller 打包产物里跑。"""
    return getattr(sys, "frozen", False)


def bundled_root() -> Path:
    """只读资源根目录。
    frozen：PyInstaller 解压临时目录 _MEIPASS。
    源码：仓库根（ming_sim/ 父目录）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).resolve().parent.parent


def bundled_path(*parts: str) -> str:
    """拼 bundled 资源路径。例：bundled_path('content', 'events.json')。"""
    return str(bundled_root().joinpath(*parts))


def user_data_dir() -> Path:
    """用户可写数据目录。
    frozen：~/.ming_sim/（首次自动建）。
    源码：<repo>/data/（沿用旧布局，便于开发期切换存档）。"""
    override = os.environ.get("MING_SIM_USER_DATA_DIR", "").strip()
    if override:
        d = Path(override).expanduser()
    elif is_frozen():
        d = Path.home() / ".ming_sim"
    else:
        d = Path(__file__).resolve().parent.parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_data_path(*parts: str) -> str:
    """拼 user data 路径，自动建父目录。例：user_data_path('saves', 'auto.db')。"""
    p = user_data_dir().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


class UnsafeSaveNameError(ValueError):
    """存档名非法（#1902：清洗真源，两端共用一份）。"""


def safe_save_name(name: str) -> str:
    """存档名清洗唯一真源（#1902）：Web 菜单、CLI 入口与会话层同用这一份。

    只留字母/数字/``._-``；清洗后为空或以 ``.`` 开头（``.`` / 隐藏名 / 纯 ``..``）
    一律拒——防目录穿越与隐藏文件。
    """
    cleaned = "".join(c for c in str(name or "").strip() if c.isalnum() or c in "._-")
    if not cleaned or cleaned.startswith("."):
        raise UnsafeSaveNameError("存档名非法。仅允许字母/数字/._- ")
    return cleaned


def save_slot_path(name: str) -> str:
    """存档名 → ``<user_data>/saves/<name>.db`` 绝对路径（校验同一份真源）。"""
    return user_data_path("saves", f"{safe_save_name(name)}.db")
