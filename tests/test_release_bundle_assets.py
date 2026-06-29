import sqlite3
from types import SimpleNamespace

from ming_sim import paths
from ming_sim.db import GameDB


def test_pool_portrait_scan_falls_back_to_built_dist_when_public_absent(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    portraits = root / "web" / "dist" / "portraits"
    portraits.mkdir(parents=True)
    (portraits / "release_pool_3.png").write_bytes(b"png")

    monkeypatch.setattr(paths, "bundled_path", lambda *parts: str(root.joinpath(*parts)))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE characters (portrait_id TEXT)")
    db = SimpleNamespace(conn=conn)

    assert GameDB.next_pool_portrait_id(db, prefix="release_pool_") == "release_pool_3"


def test_pyinstaller_spec_does_not_duplicate_vite_public_assets():
    spec = open("Ming_LLM.spec", encoding="utf-8").read()

    assert 'tree_datas("web/dist", "web/dist"' in spec
    assert 'tree_datas("web/public", "web/public"' not in spec
