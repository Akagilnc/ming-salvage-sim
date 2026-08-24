"""#318 — 第3振转流寇 + owner_power 唯一写口 + 空来源受限（ADR 0025 D5/D7）。

seam = 月末确定性结算 tick（apply_fixed_period_flows）
     + apply_army_deltas / transition_army_owner_power 唯一 adapter。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.db import GameDB
from ming_sim.flows import apply_fixed_period_flows, derive_army_mutiny_state
from ming_sim.simulation import build_simulator_payload

ARMY = "guanning"
PATHS = ("legacy", "substrate_hub")
BANDIT_POWERS = frozenset({"bandits", "bandit_li_zicheng"})


def _configure(db, fiscal_path: str) -> None:
    value = 0 if fiscal_path == "legacy" else 1
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,?,'meta','test') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1,
           pay_source_region='liaodong', province_pay_arrears=0, central_pay_arrears=0
           WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()


def _set(
    db,
    fiscal_path: str,
    *,
    loyalty: int,
    arrears: float,
    latched: int,
    mutiny_count: int | None = None,
    mutiny_probation: int | None = None,
    manpower: int | None = None,
) -> None:
    central = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
        (loyalty, arrears, latched, central, ARMY),
    )
    if mutiny_count is not None:
        db.conn.execute(
            "UPDATE armies SET mutiny_count=? WHERE id=?", (mutiny_count, ARMY)
        )
    if mutiny_probation is not None:
        db.conn.execute(
            "UPDATE armies SET mutiny_probation=? WHERE id=?", (mutiny_probation, ARMY)
        )
    if manpower is not None:
        db.conn.execute(
            "UPDATE armies SET manpower=? WHERE id=?", (manpower, ARMY)
        )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    return db.conn.execute(
        """SELECT loyalty,is_mutinied,mutiny_count,mutiny_probation,owner_power,
                  arrears,province_pay_arrears,central_pay_arrears,
                  pay_source_region,province_pay_share,central_pay_share
           FROM armies WHERE id=?""",
        (ARMY,),
    ).fetchone()


def _logs(db, fields: tuple[str, ...]):
    placeholders = ",".join("?" * len(fields))
    return db.conn.execute(
        f"""SELECT id, field, old_value, new_value, delta, reason
            FROM army_logs
            WHERE army_id=? AND field IN ({placeholders})
            ORDER BY id""",
        (ARMY, *fields),
    ).fetchall()


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_third_strike_transfers_to_bandit_via_adapter(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    # count 已 2：再 0→1 进闩即第 3 振
    _set(
        db, fiscal_path, loyalty=19, arrears=5, latched=0,
        mutiny_count=2, mutiny_probation=0,
    )
    before_arrears = float(
        db.conn.execute("SELECT arrears FROM armies WHERE id=?", (ARMY,)).fetchone()[
            "arrears"
        ]
    )
    assert before_arrears > 0

    row = _tick(db, state)

    assert row["mutiny_count"] == 3
    assert row["is_mutinied"] == 0  # 清 latch 先于/同于改 owner
    assert row["mutiny_probation"] == 0
    assert row["owner_power"] in BANDIT_POWERS
    assert float(row["arrears"]) == pytest.approx(0)
    assert float(row["province_pay_arrears"]) == pytest.approx(0)
    assert float(row["central_pay_arrears"]) == pytest.approx(0)
    assert row["pay_source_region"] in ("", None)
    assert float(row["province_pay_share"] or 0) == pytest.approx(0)
    assert float(row["central_pay_share"] or 0) == pytest.approx(0)

    logs = _logs(db, ("arrears", "is_mutinied", "owner_power", "mutiny_count"))
    writeoff = next(
        (
            log
            for log in logs
            if log["field"] == "arrears" and "核销" in str(log["reason"])
        ),
        None,
    )
    latch_clear = next(
        (
            log
            for log in logs
            if log["field"] == "is_mutinied"
            and str(log["old_value"]) in {"1", "True"}
            and str(log["new_value"]) in {"0", "False"}
        ),
        None,
    )
    # 第三振：可能从未把 latch 写成 1 即清；允许「清 latch」日志缺省，但 owner 必有
    owner_log = next((log for log in logs if log["field"] == "owner_power"), None)
    count_log = next(
        (
            log
            for log in logs
            if log["field"] == "mutiny_count" and int(float(log["new_value"])) == 3
        ),
        None,
    )
    assert writeoff is not None
    assert owner_log is not None
    assert count_log is not None
    assert owner_log["new_value"] in BANDIT_POWERS
    # 核销 → owner（清 latch 若有则夹在中间或与 owner 同序前）
    assert writeoff["id"] < owner_log["id"]
    if latch_clear is not None:
        assert writeoff["id"] < latch_clear["id"] <= owner_log["id"] or (
            latch_clear["id"] < owner_log["id"]
        )


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_third_strike_does_not_repeat_while_already_bandit(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(
        db, fiscal_path, loyalty=19, arrears=5, latched=0,
        mutiny_count=2, mutiny_probation=0,
    )
    first = _tick(db, state)
    assert first["owner_power"] in BANDIT_POWERS
    owner_after = first["owner_power"]

    # 再 tick：非明军不走军心/哗变，不得重复转移或回 ming
    second = _tick(db, state)
    assert second["owner_power"] == owner_after
    assert second["mutiny_count"] == 3
    owner_logs = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs) == 1


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_zero_manpower_latched_clears_before_continue_no_third_strike(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(
        db, fiscal_path, loyalty=10, arrears=9, latched=1,
        mutiny_count=2, mutiny_probation=3, manpower=0,
    )

    row = _tick(db, state)

    assert row["is_mutinied"] == 0
    assert row["mutiny_count"] == 2  # 不误触第三振
    assert row["owner_power"] == "ming"
    assert row["mutiny_probation"] == 3  # 只清 latch
    logs = [
        log
        for log in _logs(db, ("is_mutinied",))
        if str(log["new_value"]) in {"0", "False"}
    ]
    assert logs, "零兵清闩须写 army_logs 审计"


@pytest.mark.parametrize("fiscal_path", PATHS)
@pytest.mark.parametrize("cutover", (0, 1))
def test_empty_source_delta_cannot_defect_latched_first_or_second_strike(
    game, fiscal_path, cutover
):
    db, state, _ = game
    _configure(db, fiscal_path)
    # cutover 开/关都必须经同一 adapter，禁止 text 直写旁路
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',?,'meta','test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (cutover,),
    )
    for count in (1, 2):
        _set(
            db, fiscal_path, loyalty=15, arrears=6, latched=1,
            mutiny_count=count, mutiny_probation=0 if count == 1 else 3,
        )
        db.conn.execute(
            "UPDATE armies SET owner_power='ming', pay_source_region='liaodong',"
            " province_pay_share=0, central_pay_share=1 WHERE id=?",
            (ARMY,),
        )
        db.conn.commit()
        before = db.conn.execute(
            "SELECT owner_power,is_mutinied,arrears,mutiny_count FROM armies WHERE id=?",
            (ARMY,),
        ).fetchone()

        changes = db.apply_army_deltas(
            state,
            SimpleNamespace(id="season", title="空来源归属"),
            None,
            "测试",
            {ARMY: {"owner_power": "houjin", "reason": "投敌"}},
            commit=False,
        )

        after = db.conn.execute(
            "SELECT owner_power,is_mutinied,arrears,mutiny_count FROM armies WHERE id=?",
            (ARMY,),
        ).fetchone()
        assert dict(after) == dict(before)
        assert after["owner_power"] == "ming"
        assert after["is_mutinied"] == 1
        # 拒收或 no-op：不得出现成功的 owner 变更
        assert not any(
            c.get("field") == "owner_power" and not c.get("rejected") for c in changes
        )


def test_non_latched_generic_owner_change_still_works_via_adapter(game):
    db, state, _ = game
    _configure(db, "substrate_hub")
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',1,'meta','test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    _set(db, "substrate_hub", loyalty=70, arrears=3, latched=0, mutiny_count=0)
    db.conn.execute(
        """UPDATE armies SET pay_source_region='liaodong',
           province_pay_share=0, central_pay_share=1,
           province_pay_arrears=0, central_pay_arrears=3, arrears=3 WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()

    changes = db.apply_army_deltas(
        state,
        SimpleNamespace(id="season", title="陷没"),
        None,
        "测试",
        {ARMY: {"owner_power": "houjin", "reason": "城破易主"}},
        commit=False,
    )

    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert row["owner_power"] == "houjin"
    assert row["is_mutinied"] == 0
    assert float(row["arrears"]) == pytest.approx(0)
    logs = _logs(db, ("arrears", "owner_power"))
    writeoff = next(
        (log for log in logs if log["field"] == "arrears" and "核销" in str(log["reason"])),
        None,
    )
    owner_log = next((log for log in logs if log["field"] == "owner_power"), None)
    assert writeoff is not None and owner_log is not None
    assert writeoff["id"] < owner_log["id"]


@pytest.mark.parametrize("cutover", (0, 1))
def test_transfer_to_ming_rejects_mutiny_count_ge_3(game, cutover):
    db, state, _ = game
    _configure(db, "substrate_hub")
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',?,'meta','test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (cutover,),
    )
    db.conn.execute(
        """UPDATE armies SET owner_power='bandits', mutiny_count=3, is_mutinied=0,
           pay_source_region='', province_pay_share=0, central_pay_share=0,
           province_pay_arrears=0, central_pay_arrears=0, arrears=0 WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()

    changes = db.apply_army_deltas(
        state,
        SimpleNamespace(id="season", title="招安"),
        None,
        "测试",
        {
            ARMY: {
                "owner_power": "ming",
                "pay_source_region": "liaodong",
                "province_pay_share": 0.0,
                "central_pay_share": 1.0,
                "reason": "招安回明",
            }
        },
        commit=False,
    )

    row = db.conn.execute(
        "SELECT owner_power,mutiny_count FROM armies WHERE id=?", (ARMY,)
    ).fetchone()
    assert row["owner_power"] == "bandits"
    assert row["mutiny_count"] == 3
    assert any(c.get("rejected") for c in changes)


@pytest.mark.parametrize("cutover", (0, 1))
def test_transfer_to_ming_requires_d6_pay_source(game, cutover):
    """外军 mutiny<3 同条合法 D6 → ming：cutover 开/关均原子成功；缺饷源均拒。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES "
        "('__army_pay_source_cutover',?,'meta','test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (cutover,),
    )
    db.conn.execute(
        """UPDATE armies SET owner_power='houjin', mutiny_count=0, is_mutinied=0,
           pay_source_region='', province_pay_share=0, central_pay_share=0,
           arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()

    rejected = db.apply_army_deltas(
        state,
        SimpleNamespace(id="season", title="招安缺饷源"),
        None,
        "测试",
        {ARMY: {"owner_power": "ming", "reason": "招安"}},
        commit=False,
    )
    assert any(c.get("rejected") for c in rejected)
    assert (
        db.conn.execute(
            "SELECT owner_power FROM armies WHERE id=?", (ARMY,)
        ).fetchone()["owner_power"]
        == "houjin"
    )

    ok = db.apply_army_deltas(
        state,
        SimpleNamespace(id="season", title="招安"),
        None,
        "测试",
        {
            ARMY: {
                "owner_power": "ming",
                "pay_source_region": "liaodong",
                "province_pay_share": 0.0,
                "central_pay_share": 1.0,
                "reason": "招安",
            }
        },
        commit=False,
    )
    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    assert not any(c.get("rejected") for c in ok)
    assert row["owner_power"] == "ming"
    assert row["pay_source_region"] == "liaodong"
    assert float(row["province_pay_share"] or 0) == pytest.approx(0.0)
    assert float(row["central_pay_share"] or 0) == pytest.approx(1.0)


def test_simulator_payload_derives_zero_combat_from_mutiny_latch(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(db, "legacy", loyalty=10, arrears=5, latched=1, mutiny_count=1)

    def _army_dicts(payload_armies):
        if isinstance(payload_armies, dict) and "rows" in payload_armies:
            cols = payload_armies.get("cols") or payload_armies.get("columns") or []
            return [dict(zip(cols, row)) for row in payload_armies["rows"]]
        return list(payload_armies)

    def _find_guanning(rows):
        return next(
            r
            for r in rows
            if "关宁" in str(r.get("name", "")) or str(r.get("id", "")) == ARMY
        )

    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    by_name = _find_guanning(_army_dicts(payload["armies"]))
    assert by_name.get("zero_combat") is True
    assert "is_mutinied" not in by_name  # 机读派生 flag，不抛裸 latch 列
    # 非闩军
    db.conn.execute(
        "UPDATE armies SET is_mutinied=0, loyalty=80 WHERE id=?", (ARMY,)
    )
    db.conn.commit()
    payload2 = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    by_name2 = _find_guanning(_army_dicts(payload2["armies"]))
    assert by_name2.get("zero_combat") is False


def test_season_simulator_prompt_defines_zero_combat_noncombat():
    """ADR 0025 D8：zero_combat 须在军事软判规则有正向明文（不可投入战斗/非战斗）。"""
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[1] / "content/prompts/season_simulator.md").read_text(
        encoding="utf-8"
    )
    assert "zero_combat" in prompt
    assert "不可投入战斗" in prompt or "非战斗" in prompt


@pytest.mark.parametrize("fiscal_path", PATHS)
@pytest.mark.parametrize(
    "identity",
    (
        {"is_tusi": 1, "self_funded_pay": 0},
        {"is_tusi": 0, "self_funded_pay": 1},
    ),
    ids=("tusi", "self_funded"),
)
def test_hub_excluded_zero_manpower_latched_clears_once(game, fiscal_path, identity):
    """hub 资格外（土司/自养）零兵旧闩：分叉前全军归一仍清闩，且仅一条清闩审计。"""
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(
        db, fiscal_path, loyalty=10, arrears=0, latched=1,
        mutiny_count=2, mutiny_probation=3, manpower=0,
    )
    # 豁免军双累加器/份额须为 0（cutover 守恒）；本测只钉清闩，不测发饷
    db.conn.execute(
        """UPDATE armies SET is_tusi=?, self_funded_pay=?,
           pay_source_region='', province_pay_share=0, central_pay_share=0,
           province_pay_arrears=0, central_pay_arrears=0, arrears=0
           WHERE id=?""",
        (identity["is_tusi"], identity["self_funded_pay"], ARMY),
    )
    db.conn.commit()

    row = _tick(db, state)

    assert row["is_mutinied"] == 0
    assert row["mutiny_count"] == 2
    assert row["owner_power"] == "ming"
    clear_logs = [
        log
        for log in _logs(db, ("is_mutinied",))
        if str(log["old_value"]) in {"1", "True"}
        and str(log["new_value"]) in {"0", "False"}
        and "零兵" in str(log["reason"])
    ]
    assert len(clear_logs) == 1


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_persisted_third_strike_defects_next_tick_once(game, fiscal_path):
    """父版可持久 (latched=1,count=3,ming)：下一 tick 恰好一次核销→清闩→bandits。"""
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(
        db, fiscal_path, loyalty=10, arrears=5, latched=1,
        mutiny_count=3, mutiny_probation=0, manpower=10000,
    )

    first = _tick(db, state)
    assert first["owner_power"] in BANDIT_POWERS
    assert first["is_mutinied"] == 0
    assert first["mutiny_count"] == 3
    assert float(first["arrears"]) == pytest.approx(0)
    owner_logs = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs) == 1
    owner_after = first["owner_power"]

    second = _tick(db, state)
    assert second["owner_power"] == owner_after
    assert second["mutiny_count"] == 3
    owner_logs2 = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs2) == 1


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_persisted_third_strike_defects_on_recovery_boundary(game, fiscal_path):
    """恢复边界：loyalty=35+满饷会解闩，须在 advance 前转出，不得逃过第三振。"""
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(
        db, fiscal_path, loyalty=35, arrears=0, latched=1,
        mutiny_count=3, mutiny_probation=0, manpower=10000,
    )

    first = _tick(db, state)
    assert first["owner_power"] in BANDIT_POWERS
    assert first["is_mutinied"] == 0
    assert first["mutiny_count"] == 3
    owner_logs = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs) == 1
    owner_after = first["owner_power"]

    second = _tick(db, state)
    assert second["owner_power"] == owner_after
    assert second["mutiny_count"] == 3
    owner_logs2 = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs2) == 1


@pytest.mark.parametrize(
    "identity",
    (
        {"is_tusi": 1, "self_funded_pay": 0},
        {"is_tusi": 0, "self_funded_pay": 1},
    ),
    ids=("tusi", "self_funded"),
)
def test_hub_excluded_persisted_third_strike_defects_once(game, identity):
    """hub 资格外脏第三振正兵力：分叉前全军缝仍一次转出（不受 WHERE 子集过滤）。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    _set(
        db, "substrate_hub", loyalty=35, arrears=0, latched=1,
        mutiny_count=3, mutiny_probation=0, manpower=10000,
    )
    db.conn.execute(
        """UPDATE armies SET is_tusi=?, self_funded_pay=?,
           pay_source_region='', province_pay_share=0, central_pay_share=0,
           province_pay_arrears=0, central_pay_arrears=0, arrears=0
           WHERE id=?""",
        (identity["is_tusi"], identity["self_funded_pay"], ARMY),
    )
    db.conn.commit()

    first = _tick(db, state)
    assert first["owner_power"] in BANDIT_POWERS
    assert first["is_mutinied"] == 0
    assert first["mutiny_count"] == 3
    owner_logs = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs) == 1

    second = _tick(db, state)
    assert second["owner_power"] == first["owner_power"]
    owner_logs2 = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs2) == 1


def test_single_production_zero_manpower_clear_callsite():
    """生产清闩 helper 仅分叉前一处调用（两 branch-local 已删）。"""
    import inspect
    import re

    import ming_sim.flows as flows_mod

    src = inspect.getsource(flows_mod.apply_fixed_period_flows)
    calls = re.findall(r"_clear_zero_manpower_mutiny_latch\(", src)
    assert len(calls) == 1
    # 旧态第三振与零兵清闩同缝：pre-fork 循环内调用 helper，非 branch-local 复制 gate
    assert "_maybe_third_strike_defect(" in src
    pre_fork = src.split("if db.fiscal_engine() == \"legacy\":", 1)[0]
    assert "_clear_zero_manpower_mutiny_latch(" in pre_fork
    assert "_maybe_third_strike_defect(" in pre_fork


def test_single_production_owner_power_updater_exists():
    """仓内生产 UPDATE owner_power 只经 transition_army_owner_power 一处。"""
    import inspect
    import ming_sim.db as db_mod
    import ming_sim.flows as flows_mod

    src_db = inspect.getsource(db_mod.GameDB)
    # 生产方法体之外不应再手写 SET owner_power（seed/migration 除外，它们在其他方法）
    assert "def transition_army_owner_power" in src_db
    # flows 第三振必须调用 adapter，不直写 owner
    src_flows = inspect.getsource(flows_mod)
    assert "transition_army_owner_power" in src_flows
    assert "SET owner_power" not in src_flows
