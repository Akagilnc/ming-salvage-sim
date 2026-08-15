"""地区城市等级/城防大炮 在 region_report 与 region_detail 里要显示。

同军表漏火器一类病：字段加进了 regions 表 + simulator payload，但大臣/玩家用的
region_report(危情概览) / region_detail(inspect) 没带 → 看不见城防。

#1185：断言绑 region_public_payload（report/detail 唯一结构消费面）的
city_level / cannon / cannon_cap 与 0–5 离散等级边界；不锁中文展示串。
真实出口须经 tracer 证明调用并消费同一投影（旁路投影不可绿）。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List

import pytest


def _city_region(db):
    return db.conn.execute(
        "SELECT id, name, city_level, cannon FROM regions WHERE city_level>0 LIMIT 1"
    ).fetchone()


def _trace_region_public(db, monkeypatch) -> List[Dict[str, Any]]:
    """Minimal tracer: record each region_public_payload call + returned structure."""
    calls: List[Dict[str, Any]] = []
    original: Callable[..., Dict[str, object]] = db.region_public_payload

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        # Deep-copy so later sentinel mutation is isolated per call record.
        calls.append(
            {
                "args": args,
                "kwargs": dict(kwargs),
                "result": copy.deepcopy(result),
            }
        )
        return result

    monkeypatch.setattr(db, "region_public_payload", wrapper)
    return calls


def _with_sentinel_region(
    db, monkeypatch, region_id: str, *, cannon: int | None = None, name_prefix: str = "ZTRACE_"
) -> List[Dict[str, Any]]:
    """Trace + mutate projection entry so exit consumption is mechanically observable."""
    calls: List[Dict[str, Any]] = []
    original: Callable[..., Dict[str, object]] = db.region_public_payload

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        out = {
            "regions": [dict(e) for e in result["regions"]],  # type: ignore[index]
            "tax_total": result.get("tax_total", 0),
        }
        for entry in out["regions"]:
            if entry["id"] == region_id:
                if cannon is not None:
                    entry["cannon"] = cannon
                entry["name"] = f"{name_prefix}{entry['name']}"
        calls.append({"args": args, "kwargs": dict(kwargs), "result": out})
        return out

    monkeypatch.setattr(db, "region_public_payload", wrapper)
    return calls


def test_region_report_shows_city_defense(game, monkeypatch):
    """region_report 必须调用并消费 region_public_payload 的 cannon 可数事实。"""
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=5 WHERE id=?", (r["id"],))
    db.conn.commit()

    # Independent structural expectations on the sole public projection.
    baseline = db.region_public_payload(limit=20, danger_order=True)
    entry0 = next(e for e in baseline["regions"] if e["id"] == r["id"])
    assert int(entry0["city_level"]) > 0
    assert int(entry0["cannon"]) == 5
    assert int(entry0["cannon_cap"]) == int(entry0["city_level"]) * 8

    # Mechanical proof: real exit invokes the same projection and consumes its values.
    calls = _with_sentinel_region(db, monkeypatch, r["id"], cannon=918273)
    rep = db.region_report(limit=20)
    assert len(calls) == 1, "region_report must call region_public_payload exactly once"
    traced = next(e for e in calls[0]["result"]["regions"] if e["id"] == r["id"])
    assert int(traced["cannon"]) == 918273
    assert int(traced["city_level"]) == int(entry0["city_level"])
    assert int(traced["cannon_cap"]) == int(entry0["cannon_cap"])
    # Exit string reflects projection sentinels (not a bypass that only hits DB).
    assert traced["name"] in rep
    assert "918273" in rep


def test_region_detail_shows_city_level_and_cannon(game, monkeypatch):
    """region_detail 必须调用并消费 region_public_payload 的 city_level/cannon/cap。"""
    db, _, _ = game
    r = _city_region(db)
    db.conn.execute("UPDATE regions SET cannon=6 WHERE id=?", (r["id"],))
    db.conn.commit()

    stored_level = int(
        db.conn.execute(
            "SELECT city_level FROM regions WHERE id=?", (r["id"],)
        ).fetchone()["city_level"]
    )
    # Independent structural expectations (pre-trace, faithful read).
    row = db._resolve_region_row(r["name"])
    entry0 = db.region_public_payload(rows=[row])["regions"][0]
    assert int(entry0["cannon"]) == 6
    assert int(entry0["city_level"]) == stored_level
    assert int(entry0["cannon_cap"]) == stored_level * 8

    calls = _with_sentinel_region(db, monkeypatch, r["id"], cannon=817263)
    det = db.region_detail(r["name"])
    assert len(calls) == 1, "region_detail must call region_public_payload"
    assert calls[0]["kwargs"].get("rows") is not None, "detail must use rows= slice"
    traced = calls[0]["result"]["regions"][0]
    assert traced["id"] == r["id"]
    assert int(traced["cannon"]) == 817263
    assert int(traced["city_level"]) == stored_level
    assert int(traced["cannon_cap"]) == stored_level * 8
    assert traced["name"] in det
    assert "817263" in det


@pytest.mark.parametrize("level", (1, 3, 5))
def test_region_detail_uses_the_discrete_city_defense_scale(game, monkeypatch, level):
    """离散 0–5 城防等级边界：投影 city_level 即结构枚举，detail 消费同一投影。"""
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute(
        "UPDATE regions SET city_level=? WHERE id=?", (level, region["id"])
    )
    db.conn.commit()

    # Independent explicit level/cap expectations.
    row = db._resolve_region_row(region["name"])
    entry0 = db.region_public_payload(rows=[row])["regions"][0]
    assert int(entry0["city_level"]) == level
    assert 0 <= int(entry0["city_level"]) <= 5
    assert int(entry0["cannon_cap"]) == level * 8

    calls = _trace_region_public(db, monkeypatch)
    detail = db.region_detail(region["name"], qualitative=True)
    assert len(calls) == 1
    traced = calls[0]["result"]["regions"][0]
    assert int(traced["city_level"]) == level
    assert int(traced["cannon_cap"]) == level * 8
    assert isinstance(detail, str) and traced["name"] in detail


def test_region_public_payload_does_not_clamp_out_of_range_city_level(game):
    """越界存量 city_level 读回不被投影静默截断（清单边界断言≠授权改写）。"""
    db, _, _ = game
    region = _city_region(db)
    db.conn.execute(
        "UPDATE regions SET city_level=9 WHERE id=?", (region["id"],)
    )
    db.conn.commit()
    row = db._resolve_region_row(region["name"])
    entry = db.region_public_payload(rows=[row])["regions"][0]
    assert int(entry["city_level"]) == 9
    assert int(entry["cannon_cap"]) == 72
