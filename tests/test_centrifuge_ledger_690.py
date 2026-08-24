"""#690 / ADR 0011-2 — 血债棘轮 substrate 公开行为钉。

公开面：accrue_blood_debt / accrue_detection_wariness / rebuild_centrifuge_cache。
只观察 DB 与异常；不 spy 私有核、不 inspect.signature、不断言宽返回 DTO。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from ming_sim.agents import build_simulator_context
from ming_sim.context import character_context, character_context_with_db
from ming_sim.exceptions import SettlementAbort
from ming_sim.person_archive_contract import PERSON_REASON_CODES, normalize_reason_code
from ming_sim.simulation import build_simulator_payload

# ---------------------------------------------------------------------------
# helpers（只读观察；不构成第二写缝）
# ---------------------------------------------------------------------------

_AXIS = "礼法名节"
_TARGET_EUNUCH = "崔呈秀"  # 阉党 · identity=98
_TARGET_ARMY = "袁崇焕"  # 军队 · identity=80
_FIELD_NAMES = (
    "blood_debt",
    "wariness",
    "edict_overdraw",
    "legitimacy_pct",
    "amount",
    "base",
)
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


def _set_identity(db, name: str, identity: int) -> None:
    db.conn.execute(
        "UPDATE characters SET identity=? WHERE name=?", (int(identity), name)
    )
    db.conn.commit()


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
    assert int(rows["kinship"]["amount"]) != 0


# ---------------------------------------------------------------------------
# T3 — Δ=0 且命名空间无 durable → 合法零写
# ---------------------------------------------------------------------------


def test_t3_zero_delta_empty_namespace_is_legal_noop(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=3,
        idem_base="t3|zero",
    )
    assert _snapshot(db) == before


# ---------------------------------------------------------------------------
# T4 — 快乐路径 + 禁参 TypeError
# ---------------------------------------------------------------------------


def test_t4_happy_path_and_forbidden_kwargs(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t4|happy",
        reason_code="依律",
        source="test",
    )
    faction = _faction_of(db, _TARGET_EUNUCH)
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t4|happy|")]
    kinds = {r["kind"] for r in rows}
    assert "direct" in kinds
    assert "kinship" in kinds
    for r in rows:
        assert r["source_name"] == _TARGET_EUNUCH
        assert r["faction"] == faction
    cache = [
        r
        for r in _cache_rows(db)
        if r["faction"] == faction and r["axis"] == _AXIS
    ]
    assert cache and int(cache[0]["blood_debt"]) > 0

    for kwargs in (
        {"faction": faction},
        {"identity": 50},
        {"amount": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_blood_debt(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                penalty_type="抄家",
                crime_weight=70,
                idem_base="t4|forbidden",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert before != _snapshot(db)


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
    assert rows[0]["kind"] != "direct"
    assert all(r["kind"] != "overdraw" for r in rows)
    assert all(r["kind"] != "direct" for r in rows)

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


def test_t9_idempotency_namespace_and_empty_planned(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game

    # ① replay：同参两次，第二次零增
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    mid = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    assert _snapshot(db) == mid

    # ② 同 idem_base 异载荷（换 target）且 kinds 仍能凑集合相等 → Abort
    # 先用另一 base 写军队目标，确保军队可被写；此处专门：已有 t9|payload 写阉党后换军队
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|payload",
    )
    before_payload = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=1,
            idem_base="t9|payload",
        )
    assert _snapshot(db) == before_payload

    # ③ 旧批多 kind / 当前真子集：identity→0 去掉 kinship
    _set_identity(db, _TARGET_ARMY, 80)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_ARMY,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|subset",
    )
    kinds_first = {
        r["kind"]
        for r in _log_rows(db)
        if str(r["idem_key"]).startswith("t9|subset|")
    }
    assert kinds_first == {"direct", "kinship"}
    _set_identity(db, _TARGET_ARMY, 0)
    before_subset = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=1,
            idem_base="t9|subset",
        )
    assert _snapshot(db) == before_subset

    # ④ 旧批非空 / 当前 planned 空：申饬 cw1→cw3，同 target/axis/idem_base
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|empty_planned",
    )
    first_rows = [
        r
        for r in _log_rows(db)
        if str(r["idem_key"]).startswith("t9|empty_planned|")
    ]
    assert any(r["kind"] == "direct" and int(r["amount"]) == 2 for r in first_rows)
    before_empty = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=3,
            idem_base="t9|empty_planned",
        )
    assert _snapshot(db) == before_empty


# ---------------------------------------------------------------------------
# T10 — 半套 key 预插
# ---------------------------------------------------------------------------


def test_t10_partial_preinserted_key_aborts(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    # 只预插 direct，公开调用会计划 multi-kind → 集合不等
    db.conn.execute(
        "INSERT INTO centrifuge_log("
        "turn, faction, axis, kind, base, legitimacy_pct, amount, "
        "source_name, reason_code, source, idem_key"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            state.turn,
            faction,
            _AXIS,
            "direct",
            70,
            10,
            7,
            _TARGET_EUNUCH,
            None,
            None,
            "t10|partial|direct",
        ),
    )
    db.conn.commit()
    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t10|partial",
        )
    assert _snapshot(db) == before


# ---------------------------------------------------------------------------
# T11 — rebuild + 写途回滚
# ---------------------------------------------------------------------------


def test_t11_rebuild_clears_dirty_and_write_path_rolls_back(game, monkeypatch):
    from ming_sim.centrifuge_ledger import (
        accrue_blood_debt,
        rebuild_centrifuge_cache,
    )

    db, state, _content = game
    # 先落一笔真账
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t11|seed",
    )
    log_before = [dict(r) for r in _log_rows(db)]
    faction = _faction_of(db, _TARGET_EUNUCH)
    other = "东林"
    assert other != faction

    # 脏 cache 行（无对应 log group）+ 脏 overdraw
    db.conn.execute(
        "INSERT INTO faction_axis_debt(faction, axis, blood_debt, wariness) "
        "VALUES (?,?,?,?)",
        (other, "民本恤民", 99, 88),
    )
    db.conn.execute(
        "UPDATE factions SET edict_overdraw = 7 WHERE name=?", (other,)
    )
    db.conn.commit()
    assert any(r["faction"] == other for r in _cache_rows(db))
    assert _overdraw_map(db)[other] == 7

    rebuild_centrifuge_cache(db)
    assert not any(r["faction"] == other for r in _cache_rows(db))
    assert _overdraw_map(db)[other] == 0
    assert [dict(r) for r in _log_rows(db)] == log_before
    # 真账 cache 仍在
    eunuch_cache = [
        r for r in _cache_rows(db) if r["faction"] == faction and r["axis"] == _AXIS
    ]
    assert eunuch_cache and int(eunuch_cache[0]["blood_debt"]) > 0

    # 写途 monkeypatch：INSERT centrifuge_log 时抛错 → 全快照回滚
    before_fail = _snapshot(db)
    real_execute = db.conn.execute

    def boom_on_log(sql, parameters=()):
        text = sql if isinstance(sql, str) else str(sql)
        if "INSERT INTO centrifuge_log" in text.replace("\n", " "):
            raise sqlite3.OperationalError("simulated write failure")
        return real_execute(sql, parameters)

    monkeypatch.setattr(db.conn, "execute", boom_on_log)
    with pytest.raises(sqlite3.OperationalError, match="simulated write failure"):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t11|boom",
        )
    monkeypatch.setattr(db.conn, "execute", real_execute)
    assert _snapshot(db) == before_fail

    # rebuild 中途失败亦整原子回滚
    real_execute2 = db.conn.execute
    calls = {"n": 0}

    def boom_on_rebuild(sql, parameters=()):
        text = sql if isinstance(sql, str) else str(sql)
        if "DELETE FROM faction_axis_debt" in text:
            calls["n"] += 1
            if calls["n"] >= 1:
                # let delete happen then fail on next write
                pass
        if "UPDATE factions SET edict_overdraw" in text.replace("\n", " "):
            raise sqlite3.OperationalError("simulated rebuild failure")
        return real_execute2(sql, parameters)

    before_rebuild = _snapshot(db)
    monkeypatch.setattr(db.conn, "execute", boom_on_rebuild)
    with pytest.raises(sqlite3.OperationalError, match="simulated rebuild failure"):
        rebuild_centrifuge_cache(db)
    monkeypatch.setattr(db.conn, "execute", real_execute2)
    assert _snapshot(db) == before_rebuild


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


def test_t13_p4_surfaces_do_not_feed_new_fields(game):
    db, state, content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    # 植入 sentinel 到派生表/列与 log
    db.conn.execute(
        "INSERT INTO faction_axis_debt(faction, axis, blood_debt, wariness) "
        "VALUES (?,?,?,?)",
        (faction, _AXIS, _SENTINEL_DEBT, _SENTINEL_WARINESS),
    )
    db.conn.execute(
        "UPDATE factions SET edict_overdraw=? WHERE name=?",
        (_SENTINEL_OVERDRAW, faction),
    )
    db.conn.execute(
        "INSERT INTO centrifuge_log("
        "turn, faction, axis, kind, base, legitimacy_pct, amount, "
        "source_name, reason_code, source, idem_key"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            state.turn,
            faction,
            _AXIS,
            "direct",
            _SENTINEL_BASE,
            _SENTINEL_LEG,
            _SENTINEL_AMOUNT,
            _TARGET_EUNUCH,
            None,
            None,
            "t13|sentinel|direct",
        ),
    )
    db.conn.commit()

    character = content.characters[_TARGET_EUNUCH]
    surfaces: list[str] = [
        character_context(character),
        character_context_with_db(character, db, turn=state.turn),
    ]
    payload = build_simulator_payload(state, db, "", "")
    brief = str(payload["factions_brief"])
    ctx = build_simulator_context(payload)
    report = db.faction_report()
    surfaces.extend([brief, ctx, report])

    sentinels = (
        _SENTINEL_DEBT,
        _SENTINEL_WARINESS,
        _SENTINEL_OVERDRAW,
        _SENTINEL_LEG,
        _SENTINEL_AMOUNT,
        _SENTINEL_BASE,
    )
    unique_names = (
        "blood_debt",
        "wariness",
        "edict_overdraw",
        "legitimacy_pct",
    )
    for text in surfaces:
        for name in unique_names:
            assert name not in text
        for value in sentinels:
            assert str(value) not in text

    # factions_brief / character / faction_report 无 amount/base 子串；
    # 全量 ctx 预存 output_amount 列名，只禁独立字段形态与 sentinel。
    for text in (surfaces[0], surfaces[1], brief, report):
        assert "amount" not in text
        assert "base" not in text
    assert "blood_debt" not in ctx
    assert "edict_overdraw" not in ctx


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
