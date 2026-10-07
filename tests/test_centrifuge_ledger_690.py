"""#690 / ADR 0011-2 — 血债棘轮 substrate 公开行为钉。

公开面：accrue_blood_debt / accrue_detection_wariness / rebuild_centrifuge_cache。
只观察 DB 与异常；不 spy 私有核、不 inspect.signature、不断言宽返回 DTO。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from ming_sim.context import character_context, character_context_with_db
from ming_sim.exceptions import SettlementAbort
from ming_sim.person_archive_contract import PERSON_REASON_CODES, normalize_reason_code

# ---------------------------------------------------------------------------
# helpers（只读观察；不构成第二写缝）
# ---------------------------------------------------------------------------

_AXIS = "礼法名节"
_TARGET_EUNUCH = "崔呈秀"  # 阉党 · identity=98
_TARGET_ARMY = "袁崇焕"  # 军队 · identity=80
_SENTINEL_DEBT = 424242
_SENTINEL_WARINESS = 434343
_SENTINEL_OVERDRAW = 444444
_SENTINEL_LEG = 454545
_SENTINEL_AMOUNT = 464646
_SENTINEL_BASE = 474747


def _log_rows(db) -> list[sqlite3.Row]:
    return list(
        db.conn.execute(
            "SELECT turn, faction, axis, kind, base, legitimacy_pct, amount, "
            "source_name, reason_code, source, idem_key "
            "FROM centrifuge_log ORDER BY id"
        ).fetchall()
    )


def _cache_rows(db) -> list[sqlite3.Row]:
    return list(
        db.conn.execute(
            "SELECT faction, axis, blood_debt, wariness "
            "FROM faction_axis_debt ORDER BY faction, axis"
        ).fetchall()
    )


def _overdraw_map(db) -> dict[str, int]:
    rows = db.conn.execute(
        "SELECT name, edict_overdraw FROM factions ORDER BY name"
    ).fetchall()
    return {str(r["name"]): int(r["edict_overdraw"]) for r in rows}


def _snapshot(db) -> dict[str, Any]:
    return {
        "log": [dict(r) for r in _log_rows(db)],
        "cache": [dict(r) for r in _cache_rows(db)],
        "overdraw": _overdraw_map(db),
    }


def _faction_of(db, name: str) -> str:
    row = db.conn.execute(
        "SELECT faction FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row is not None
    return str(row["faction"])



def _direct_rows(db, *, idem_base: str | None = None) -> list[sqlite3.Row]:
    if idem_base is None:
        return [
            r
            for r in _log_rows(db)
            if r["kind"] == "direct"
        ]
    key = f"{idem_base}|direct"
    return [r for r in _log_rows(db) if r["idem_key"] == key]


# ---------------------------------------------------------------------------
# T1 — D2-4 三锚 +7/+61/+69
# ---------------------------------------------------------------------------


def test_t1_confiscation_direct_anchors_via_public_api(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    cases = (
        (70, 7, 10),
        (10, 61, 87),
        (1, 69, 99),
    )
    for cw, expect_amount, expect_leg in cases:
        idem = f"t1|抄家|cw{cw}"
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=cw,
            idem_base=idem,
        )
        rows = _direct_rows(db, idem_base=idem)
        assert len(rows) == 1
        assert int(rows[0]["amount"]) == expect_amount
        assert int(rows[0]["legitimacy_pct"]) == expect_leg
        assert int(rows[0]["base"]) == 70


# ---------------------------------------------------------------------------
# T2 — kinship ADR 原式（杀 round(direct)×0.3×k）
# ---------------------------------------------------------------------------


def test_t2_kinship_uses_unrounded_formula(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    # 袁崇焕 identity=80；申饬+cw1 → direct=2, kinship=1（错式得 0）
    assert (
        db.conn.execute(
            "SELECT identity FROM characters WHERE name=?", (_TARGET_ARMY,)
        ).fetchone()["identity"]
        == 80
    )
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_ARMY,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t2|kinship",
    )
    rows = {r["kind"]: r for r in _log_rows(db) if r["idem_key"].startswith("t2|kinship|")}
    assert int(rows["direct"]["amount"]) == 2
    assert int(rows["kinship"]["amount"]) == 1


def test_t2b_legitimacy_uses_raw_for_amounts(game):
    """D2-4：leg_raw 算金额；整数 legitimacy_pct 仅审计。

    廷杖40/cw6 → leg_raw=86.5 → pct=86，direct=round(34.6)=35（错式用 86 得 34）。
    廷杖40/cw1/id98 → kinship=round(11.466…)=11（错式用 98 整数 leg 得 12）。
    """
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_ARMY,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=6,
        idem_base="t2b|direct35",
    )
    direct_rows = _direct_rows(db, idem_base="t2b|direct35")
    assert len(direct_rows) == 1
    assert int(direct_rows[0]["legitimacy_pct"]) == 86
    assert int(direct_rows[0]["amount"]) == 35

    # 崔呈秀 identity=98
    assert (
        db.conn.execute(
            "SELECT identity FROM characters WHERE name=?", (_TARGET_EUNUCH,)
        ).fetchone()["identity"]
        == 98
    )
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=1,
        idem_base="t2b|kinship11",
    )
    kin = next(
        r
        for r in _log_rows(db)
        if r["idem_key"] == "t2b|kinship11|kinship"
    )
    assert int(kin["legitimacy_pct"]) == 98
    assert int(kin["amount"]) == 11


# ---------------------------------------------------------------------------
# T3 — Δ=0 且命名空间无 durable → 合法零写
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T4 — 快乐路径 + 禁参 TypeError
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T5 — 廷杖 overdraw 同批；非廷杖无 overdraw
# ---------------------------------------------------------------------------


def test_t5_bastinado_overdraw_batch_and_non_bastinado(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    before_od = _overdraw_map(db)[faction]

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=1,
        idem_base="t5|廷杖",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|廷杖|")]
    kinds = {r["kind"] for r in rows}
    assert "overdraw" in kinds
    od = next(r for r in rows if r["kind"] == "overdraw")
    assert od["axis"] is None and od["base"] is None and od["legitimacy_pct"] is None
    assert int(od["amount"]) == 1
    assert _overdraw_map(db)[faction] == before_od + 1

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="罢黜",
        crime_weight=1,
        idem_base="t5|罢黜",
    )
    non = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|罢黜|")]
    assert all(r["kind"] != "overdraw" for r in non)


# ---------------------------------------------------------------------------
# T6 — 错误 target 零写
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_target",
    ["", "崔", "崔尚书", "不存在之人甲乙丙"],
)
def test_t6_bad_target_aborts_with_zero_write(game, bad_target):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=bad_target,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base=f"t6|{bad_target!r}",
        )
    assert _snapshot(db) == before


@pytest.mark.parametrize(
    "raw_identity,expected_typeof",
    [
        (80.5, "real"),  # 旧 int(80.5)==80 静默截断
        ("8_0", "text"),  # 旧 int("8_0")==80；ASCII '80' 会被 affinity 吞成 integer，禁用
    ],
)
def test_t6b_non_int_identity_aborts_with_zero_write(
    game, raw_identity, expected_typeof
):
    """strict-int：可达 REAL/TEXT 先 typeof，再公开 API Abort + 三账零写。

    不可达（不伪测）：NULL 被 NOT NULL 阻断；bool 经 ? 绑定读回 int；
    ASCII '80' 被 INTEGER affinity 存成 integer。
    """
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    # 绕过 _set_identity 的 int() 强制，直写 characters.identity
    db.conn.execute(
        "UPDATE characters SET identity=? WHERE name=?",
        (raw_identity, _TARGET_ARMY),
    )
    db.conn.commit()
    stored = db.conn.execute(
        "SELECT typeof(identity) AS t FROM characters WHERE name=?",
        (_TARGET_ARMY,),
    ).fetchone()
    assert str(stored["t"]) == expected_typeof

    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base=f"t6b|{expected_typeof}",
        )
    assert _snapshot(db) == before


# ---------------------------------------------------------------------------
# T7 — 跨派隔离
# ---------------------------------------------------------------------------


def test_t7_cross_faction_isolation(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    army = _faction_of(db, _TARGET_ARMY)
    eunuch = _faction_of(db, _TARGET_EUNUCH)
    assert army != eunuch
    before_army_cache = [
        dict(r) for r in _cache_rows(db) if r["faction"] == army
    ]
    before_army_log = [
        dict(r) for r in _log_rows(db) if r["faction"] == army
    ]
    before_army_od = _overdraw_map(db)[army]

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t7|eunuch",
    )
    assert [dict(r) for r in _cache_rows(db) if r["faction"] == army] == before_army_cache
    assert [dict(r) for r in _log_rows(db) if r["faction"] == army] == before_army_log
    assert _overdraw_map(db)[army] == before_army_od
    written = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t7|eunuch|")]
    assert written and all(r["faction"] == eunuch for r in written)


# ---------------------------------------------------------------------------
# T8 — detection wrapper
# ---------------------------------------------------------------------------


def test_t8_detection_wariness_only_kinship(game):
    from ming_sim.centrifuge_ledger import accrue_detection_wariness

    db, state, _content = game
    before = _snapshot(db)
    accrue_detection_wariness(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        alert_severity=10,
        idem_base="t8|det",
        source="alert",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t8|det|")]
    assert len(rows) == 1
    assert rows[0]["kind"] == "kinship"
    assert int(rows[0]["legitimacy_pct"]) == 100

    for kwargs in (
        {"penalty_type": "抄家"},
        {"crime_weight": 1},
        {"amount": 1},
        {"faction": "阉党"},
        {"identity": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_detection_wariness(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                alert_severity=10,
                idem_base="t8|bad",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert _snapshot(db) != before


# ---------------------------------------------------------------------------
# T9 — 幂等三态
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T10 — 半套 key 预插
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T11 — rebuild + 写途回滚
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T12 — restore：关库重开
# ---------------------------------------------------------------------------


def test_t12_restore_preserves_tables_and_rebuild(tmp_path, content):
    from ming_sim.centrifuge_ledger import (
        accrue_blood_debt,
        rebuild_centrifuge_cache,
    )
    from ming_sim.db import GameDB

    path = tmp_path / "centrifuge-690.db"
    first = GameDB(str(path), content)
    first.seed_static_data()
    state = first.load_state()
    accrue_blood_debt(
        db=first,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=1,
        idem_base="t12|persist",
    )
    snap = _snapshot(first)
    first.close()

    second = GameDB(str(path), content)
    # 表/列/值仍在
    assert _snapshot(second) == snap
    cols = {
        r["name"]
        for r in second.conn.execute("PRAGMA table_info(factions)").fetchall()
    }
    assert "edict_overdraw" in cols
    tables = {
        r["name"]
        for r in second.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "faction_axis_debt" in tables
    assert "centrifuge_log" in tables
    rebuild_centrifuge_cache(second)
    # cache≡log：blood/wariness/overdraw 与 log 聚合一致
    log = _log_rows(second)
    from collections import defaultdict

    blood: dict[tuple[str, str], int] = defaultdict(int)
    wary: dict[tuple[str, str], int] = defaultdict(int)
    od: dict[str, int] = defaultdict(int)
    for r in log:
        if r["kind"] == "direct":
            blood[(r["faction"], r["axis"])] += int(r["amount"])
        elif r["kind"] == "kinship":
            wary[(r["faction"], r["axis"])] += int(r["amount"])
        elif r["kind"] == "overdraw":
            od[r["faction"]] += int(r["amount"])
    cache = {(r["faction"], r["axis"]): r for r in _cache_rows(second)}
    keys = set(blood) | set(wary)
    assert set(cache) == keys
    for key in keys:
        row = cache[key]
        assert int(row["blood_debt"]) == blood.get(key, 0)
        assert int(row["wariness"]) == wary.get(key, 0)
    omap = _overdraw_map(second)
    for fac, val in od.items():
        assert omap[fac] == val
    second.close()


# ---------------------------------------------------------------------------
# T13 — P4 输入侧不喂
# ---------------------------------------------------------------------------


def _collect_typed_keys(obj: Any, *, _out: set[str] | None = None) -> set[str]:
    """递归收集真实 payload 的 typed dict keys；不解析自由文本。"""
    if _out is None:
        _out = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            _out.add(str(key))
            _collect_typed_keys(value, _out=_out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_typed_keys(item, _out=_out)
    return _out




# ---------------------------------------------------------------------------
# T14 — 码集二分
# ---------------------------------------------------------------------------


def test_t14_reason_code_sets_and_reject_unrecognized(game):
    from ming_sim.centrifuge_ledger import STIGMA_REASON_CODES, accrue_blood_debt

    db, state, _content = game
    for code in ("依律", "谋逆坐实", "贪墨坐实"):
        assert code in PERSON_REASON_CODES
        assert normalize_reason_code(code) == code

    for code in ("中旨除授", "非正途", "罗织"):
        assert code in STIGMA_REASON_CODES
        assert code not in PERSON_REASON_CODES

    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t14|bad_reason",
            reason_code="完全不是码",
        )
    assert _snapshot(db) == before
