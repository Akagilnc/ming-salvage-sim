"""发行包资产：portrait 扫 dist 回退 + spec 不重复打 public。

#1185：spec 侧用 tree_datas (source, destination) 参数对断言。
#1721：requirements.txt 须装入 bundled root（frozen ROOT_DIR），否则新开局先抛 FileNotFoundError。
"""

from pathlib import Path
import re
import sqlite3

import pytest

from ming_sim import paths
from ming_sim.db import GameDB


class MinimalGameDB(GameDB):
    def __init__(self, conn):
        self.conn = conn


def test_pool_portrait_scan_falls_back_to_built_dist_when_public_absent(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    portraits = root / "web" / "dist" / "portraits"
    portraits.mkdir(parents=True)
    (portraits / "release_pool_3.png").write_bytes(b"png")
    assert not (root / "web" / "public" / "portraits").exists()

    monkeypatch.setattr(paths, "bundled_path", lambda *parts: str(root.joinpath(*parts)))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE characters (portrait_id TEXT)")
    db = MinimalGameDB(conn)

    assert db.next_pool_portrait_id(prefix="release_pool_") == "release_pool_3"


def test_pyinstaller_spec_does_not_duplicate_vite_public_assets():
    spec = (Path(__file__).resolve().parents[1] / "Ming_LLM.spec").read_text(encoding="utf-8")
    # 不变式由 (source, destination) 参数对共同拥有，不得只查 source 集合。
    tree_pairs = re.findall(r'tree_datas\(\s*"([^"]+)"\s*,\s*"([^"]+)"', spec)
    assert ("web/dist", "web/dist") in tree_pairs
    assert all(src != "web/public" for src, _dst in tree_pairs)
    assert ("web/public", "web/public") not in tree_pairs
    assert not re.search(r'[\("]web/public[\)"]', spec)


def test_spec_datas_puts_requirements_at_bundle_root(monkeypatch):
    import ast
    import sys
    import types
    from types import SimpleNamespace

    repo = Path(__file__).resolve().parents[1]
    tree = ast.parse((repo / "Ming_LLM.spec").read_text(encoding="utf-8"))
    # 仅跳过发行门卫调用（它要 web/dist 构建产物与 git 干净态，与 datas 装配无关）；
    # 其余装配语句（含 tree_datas 定义与 datas 拼接）全部真实执行。
    body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_release_guard"
        )
    ]

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda name: ([], [], [])
    hooks.collect_submodules = lambda name: []
    monkeypatch.setitem(sys.modules, "PyInstaller", types.ModuleType("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", types.ModuleType("PyInstaller.utils"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)

    captured = {}

    def _analysis(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], zipped_data=[], scripts=[], binaries=[], zipfiles=[], datas=kwargs.get("datas", []))

    namespace = {
        "__name__": "__ming_spec__",
        "__file__": str(repo / "Ming_LLM.spec"),
        "Analysis": _analysis,
        "PYZ": lambda *args, **kwargs: SimpleNamespace(),
        "EXE": lambda *args, **kwargs: SimpleNamespace(),
        "COLLECT": lambda *args, **kwargs: None,
        "BUNDLE": lambda *args, **kwargs: None,
    }
    monkeypatch.chdir(repo)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(repo / "Ming_LLM.spec"), "exec"), namespace)
    assert ("requirements.txt", ".") in captured["datas"]
