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

    # PyInstaller 的 datas 契约是**扁平的 (source, destination) 配对列表**
    # （见 https://pyinstaller.org/en/stable/spec-files.html）：每一项直接是
    # 二元组，不接受嵌套子列表。故此处逐项断言二元组本身，嵌套即失败——
    # 不做递归摊平把非法形状洗成合法形状。
    root = str(tmp_path)
    return [
        (src.replace(root, "").replace("\\", "/"), str(dst).replace("\\", "/"))
        for src, dst in captured["datas"]
    ]


def test_spec_datas_ship_dist_assets_into_dist_and_never_repack_public(tmp_path, monkeypatch):
    """#1185：vite 已把 public 拷进 dist；spec 只打 dist 树，不得再单独打 public。

    断言落在 Analysis 实收的 (source, destination) 配对上：来源与**目标目录**
    都是契约——web_app 只从 bundled web/dist 提供前端，dist 装到别处就是坏包。
    """
    datas = _spec_datas(tmp_path, monkeypatch)
    assert datas

    shipped = {
        src: dst for src, dst in datas
        if src.endswith(("web/dist/index.html", "web/dist/assets/app.js"))
    }
    assert set(shipped) == {"web/dist/index.html", "web/dist/assets/app.js"}, datas
    # 目标目录须原样落在 web/dist 之下（index.html → web/dist，app.js → web/dist/assets）
    assert shipped["web/dist/index.html"] == "web/dist", shipped
    assert shipped["web/dist/assets/app.js"] == "web/dist/assets", shipped

    assert not any("web/public" in src for src, _dst in datas), datas


def test_spec_datas_puts_requirements_at_bundle_root(tmp_path, monkeypatch):
    """#1721：requirements.txt 装入 bundled root，否则新开局先抛 FileNotFoundError。"""
    datas = _spec_datas(tmp_path, monkeypatch)
    assert ("requirements.txt", ".") in datas