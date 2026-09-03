"""发行包资产：portrait 扫 dist 回退 + spec 不重复打 public。

#1185：spec 侧用 tree_datas (source, destination) 参数对断言。
#1721：requirements.txt 须装入 bundled root（frozen ROOT_DIR），否则新开局先抛 FileNotFoundError。
"""

from pathlib import Path
import re
import sqlite3

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


def test_pyinstaller_spec_bundles_requirements_at_frozen_root():
    import ast
    spec = (Path(__file__).resolve().parents[1] / "Ming_LLM.spec").read_text(encoding="utf-8")
    tree = ast.parse(spec)
    bound_strings = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                bound_strings[node.targets[0].id] = node.value.value

    def resolve_str(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return bound_strings.get(node.id)
        return None

    pairs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 2:
            src = resolve_str(node.elts[0])
            dst = resolve_str(node.elts[1])
            if src is not None and dst is not None:
                pairs.add((src, dst))
    assert ("requirements.txt", ".") in pairs
