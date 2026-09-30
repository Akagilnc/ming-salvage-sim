"""发行包资产：portrait 扫 dist 回退 + spec 装配结果（不重复打 public）。

#1185：不变式落在 spec 真实执行出的 datas 结构化装配结果上，不扫源码写法。
#1721：requirements.txt 须装入 bundled root（frozen ROOT_DIR），否则新开局先抛 FileNotFoundError。
"""

from pathlib import Path
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


def _spec_datas(tmp_path, monkeypatch) -> list:
    """真实执行 Ming_LLM.spec 的装配语句，返回 Analysis 收到的 datas。

    跳过 _release_guard（它要真 web/dist 构建产物与 git 干净态，与装配无关）；
    其余装配语句（含 tree_datas 定义与 datas 拼接）全部真实执行，因此断言落在
    实际打包的文件对，而非 spec 源码的引号/写法。
    """
    import ast
    import sys
    import types
    from types import SimpleNamespace

    repo = Path(__file__).resolve().parents[1]
    # 在沙箱根下造出 dist 与 public 两棵树：spec 若把 public 也打进来，
    # 装配结果里就会出现 public 的源路径（vite 已把它拷进 dist，重复打是坏包）。
    (tmp_path / "web" / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "web" / "dist" / "index.html").write_text("<html>", encoding="utf-8")
    (tmp_path / "web" / "dist" / "assets" / "app.js").write_text("js", encoding="utf-8")
    (tmp_path / "web" / "public" / "portraits").mkdir(parents=True)
    (tmp_path / "web" / "public" / "portraits" / "release_pool_3.png").write_bytes(b"png")

    tree = ast.parse((repo / "Ming_LLM.spec").read_text(encoding="utf-8"))
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
    monkeypatch.chdir(tmp_path)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(repo / "Ming_LLM.spec"), "exec"), namespace)

    # datas 里 tree_datas 的返回值是「一批 (source, destination)」的列表，
    # 故先摊平再统一成 (source, destination) 字符串对。
    pairs: list[tuple[str, str]] = []
    pending = list(captured["datas"])
    while pending:
        item = pending.pop()
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
            pairs.append((item[0], item[1]))
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        else:  # pragma: no cover - spec 装配形状外的项
            raise AssertionError(f"unexpected datas entry: {item!r}")
    root = str(tmp_path)
    return [(src.replace(root, "").replace("\\", "/"), str(dst)) for src, dst in pairs]


def test_spec_datas_ship_dist_assets_once_and_never_repack_public(tmp_path, monkeypatch):
    """#1185：vite 已把 public 拷进 dist；spec 只打 dist 树，不得再单独打 public。"""
    datas = _spec_datas(tmp_path, monkeypatch)

    sources = [src for src, _dst in datas]
    assert any(s.endswith("web/dist/index.html") for s in sources), sources
    assert any(s.endswith("web/dist/assets/app.js") for s in sources), sources
    assert not any("web/public" in s for s in sources), sources


def test_spec_datas_puts_requirements_at_bundle_root(tmp_path, monkeypatch):
    """#1721：requirements.txt 装入 bundled root，否则新开局先抛 FileNotFoundError。"""
    datas = _spec_datas(tmp_path, monkeypatch)
    assert ("requirements.txt", ".") in datas