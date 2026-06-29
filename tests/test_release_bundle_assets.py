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

    monkeypatch.setattr(paths, "bundled_path", lambda *parts: str(root.joinpath(*parts)))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE characters (portrait_id TEXT)")
    db = MinimalGameDB(conn)

    assert db.next_pool_portrait_id(prefix="release_pool_") == "release_pool_3"


def test_pyinstaller_spec_does_not_duplicate_vite_public_assets():
    spec_path = Path(__file__).resolve().parents[1] / "Ming_LLM.spec"
    spec = spec_path.read_text(encoding="utf-8")

    assert 'tree_datas("web/dist", "web/dist"' in spec
    assert 'tree_datas("web/public", "web/public"' not in spec
