"""测试侧只读回读的单一副本：多文件共用的 SELECT 读口只在此定义一次（#1834 JA-2）。"""
from __future__ import annotations


def active_character_name(db) -> str:
    """按名排序的首个在任人物名（不分势力）。"""
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def ming_character_name(db) -> str:
    """按名排序的首个明廷在任人物名。"""
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def class_population(db, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def global_population(db) -> int:
    return int(db.conn.execute("SELECT COALESCE(SUM(population),0) FROM classes").fetchone()[0])


def economy_ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def faction_satisfaction(db, name: str) -> int:
    row = db.conn.execute("SELECT satisfaction FROM factions WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["satisfaction"])


def class_satisfaction(db, name: str, region_id: str = "") -> int:
    row = db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    assert row is not None
    return int(row["satisfaction"])


def army_loyalty(db, army_id: str) -> int:
    return int(db.conn.execute(
        "SELECT loyalty FROM armies WHERE id=?", (army_id,)).fetchone()["loyalty"])


def non_ming_power_id(db) -> str:
    """取一个非 ming 的合法 power id。"""
    row = db.conn.execute("SELECT id FROM powers WHERE id != 'ming' LIMIT 1").fetchone()
    assert row is not None
    return row[0]
