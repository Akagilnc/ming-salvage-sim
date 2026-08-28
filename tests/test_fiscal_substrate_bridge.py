"""#66/#266：regions.fiscal 省级 settle_tick 基座 + DB↔settle_tick 桥。

两件事：
1. 种子——已 seed 的明控省 fiscal JSON 内嵌 settle 基座（开账 st + 月参 p），必须能被
   settle_tick 接受（=有效基座）；陕西作为 #266 史实量级 shadow seed 的基线样例。
2. 桥——`GameDB.settle_province_tick(region_id, actions)` 读 settle.st/p → 跑 settle_tick →
   写回 new_st。**港口锁**：坏输入/守恒破 raise 时 FAIL tick 绝不落库（毒态不钉存档）。

陕西种子 = 低省库 + 正赋5.0563/月 + 辽饷2.1969011325/月 + 逋赋0.45 + 边镇 Due；
空 action 跑一 tick 应进入欠账螺旋。月末 shadow spine 按 controlled_by==ming 且有 settle
动态推进，失地/无基座省自然出列。
"""
import json
import math
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import ming_sim.content as content_mod
from ming_sim.applier import atomic
from ming_sim.constants import ARMY_FIELD_LABELS
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.exceptions import SettlementAbort
from ming_sim.fiscal_tick import settle_tick
from ming_sim.flows import army_needed
from ming_sim.issues import sync_opening_legacies
from tests.fiscal_test_utils import zero_non_meta_fiscal_config


@pytest.fixture
def fresh_db(tmp_path):
    """全新空库 + 从当前 content 种子（含本 slice 新增的 settle 基座）。
    不能用 conftest 的 game fixture——它拷贝 data/probe.db 旧档，INSERT OR IGNORE 不会带出
    content 新增字段（同「金手指只对新档生效」）。"""
    content = GameContent.load()
    bind_content(content)
    db = GameDB(str(tmp_path / "fresh.db"), content)
    db.seed_static_data()
    try:
        yield db
    finally:
        db.conn.close()


def _read_settle(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}")).get("settle")


def _read_fiscal(db, region_id):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))


def _content_settle(region_id):
    return content_mod.load_region_content()[region_id].fiscal["settle"]


def _raw_settle_meta_defaults_by_region():
    data = content_mod.load_json_asset("regions.json")
    out = {}
    for item in data.get("regions", []):
        fiscal = item.get("fiscal") or {}
        settle = fiscal.get("settle") or {}
        out[str(item.get("id"))] = settle.get("_meta_defaults")
    return out


def _write_settle(db, region_id, settle):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}"))
    fiscal["settle"] = settle
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), region_id),
    )
    db.conn.commit()


def test_seed_royal_stipends_use_wanli_accounting_by_province(fresh_db):
    """#584: 卷三十二宗藩禄粮按藩府驻地映射为省级 Due.宗禄。"""
    expected_due = {
        "shanxi": 10.99,
        "henan": 9.15,
        "shaanxi": 4.07,
        "huguang": 2.63,
        "shandong": 1.19,
        "sichuan": 0.8,
        "guangxi": 0.72,
        "jiangxi": 0.79,
        "nanzhili": 0.0,
        "zhejiang": 0.0,
        "fujian": 0.0,
        "guangdong": 0.0,
        "yunnan": 0.0,
        "guizhou": 0.0,
        "beizhili": 0.0,
        "liaodong": 0.0,
        "dongjiang_area": 0.0,
    }

    for region_id, expected in expected_due.items():
        settle = _read_settle(fresh_db, region_id)
        assert settle["p"]["Due"]["宗禄"] == pytest.approx(expected, abs=0.01)
        provisional = settle.get("_meta", {}).get("provisional", [])
        assert "宗禄" not in provisional

    henan_source = _read_fiscal(fresh_db, "henan")["settle"]["_meta"]["royal_stipends_source"]
    assert henan_source["source"] == "《万历会计录》卷三十二「宗藩禄粮」"
    assert henan_source["conversion"]["liang_per_shi"] == 0.5
    assert sum(item["annual_shi"] for item in henan_source["items"]) == pytest.approx(
        2196300.19,
        abs=0.01,
    )
    assert {"周府", "唐府", "赵府", "郑府", "崇府"} <= {
        item["house"] for item in henan_source["items"]
    }

    huguang_houses = {
        item["house"]
        for item in _read_fiscal(fresh_db, "huguang")["settle"]["_meta"]["royal_stipends_source"]["items"]
    }
    assert {"楚府", "岷府", "襄府", "荆府", "吉府", "荣府", "太和王府", "药阳王府"} <= huguang_houses

    due = {
        region_id: _read_settle(fresh_db, region_id)["p"]["Due"]["宗禄"]
        for region_id in expected_due
    }
    assert due["shanxi"] > due["henan"] > due["shaanxi"] > due["huguang"]
    assert due["huguang"] > due["shandong"] > due["sichuan"]


def _set_all_settle_grants(db, amount):
    for row in db.conn.execute("SELECT id, fiscal FROM regions").fetchall():
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError):
            continue
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if not isinstance(settle, dict):
            continue
        p = settle.get("p")
        if not isinstance(p, dict):
            continue
        p["拨付gross"] = amount
        db.conn.execute(
            "UPDATE regions SET fiscal = ? WHERE id = ?",
            (json.dumps(fiscal, ensure_ascii=False), str(row["id"])),
        )
    db.conn.commit()


def _set_fiscal_config_value(db, key, value):
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES (?, ?, 'rate', 'test override')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """,
        (key, value),
    )
    db.conn.commit()


def _zero_non_meta_fiscal_config(db):
    zero_non_meta_fiscal_config(db)


def _hub_ledger_snapshot(db, *, turn=None):
    query = """
        SELECT category, COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库'
          AND category IN ('起运', '盐税', '商税', '太仓亏空', '边饷hub')
    """
    params = []
    if turn is not None:
        query += " AND turn = ?"
        params.append(int(turn))
    query += """
        GROUP BY category
    """
    rows = db.conn.execute(query, params).fetchall()
    return {str(row["category"]): float(row["delta"] or 0) for row in rows}


def _hub_container_snapshot(db):
    keys = (
        "hub_省级起运到京", "hub_盐税解京", "hub_商税解京",
        "hub_太仓亏空", "hub_京运损耗",
        "C_太仓挪用", "C_太仓纯亏空", "C_京运克扣", "C_京运运损",
    )
    rows = db.conn.execute(
        f"SELECT key, value FROM fiscal_containers WHERE key IN ({','.join('?' for _ in keys)})",
        keys,
    ).fetchall()
    values = {key: 0.0 for key in keys}
    values.update({str(row["key"]): float(row["value"] or 0) for row in rows})
    return values


def _assert_hub_conservation_oracle(
    ledger,
    containers,
    *,
    outbound=None,
    expected_taicang_losses=None,
    expected_jingyun_losses=None,
):
    """Independent hub oracle over persisted ledger/container values.

    The test reconstructs the two #261 hub identities from externally visible
    stores only: economy_ledger and fiscal_containers. Mutating any side of the
    equation must fail this helper.
    """
    inbound_gross = (
        containers["hub_省级起运到京"]
        + containers["hub_盐税解京"]
        + containers["hub_商税解京"]
    )
    taicang_human = containers["C_太仓挪用"]
    taicang_sink = containers["C_太仓纯亏空"]
    taicang_loss = containers["hub_太仓亏空"]
    inbound_booked_net = (
        ledger.get("起运", 0.0)
        + ledger.get("盐税", 0.0)
        + ledger.get("商税", 0.0)
        + ledger.get("太仓亏空", 0.0)
    )
    assert inbound_gross == pytest.approx(inbound_booked_net + taicang_loss)
    if expected_taicang_losses is not None:
        expected_human, expected_sink = expected_taicang_losses
        assert taicang_human == pytest.approx(expected_human)
        assert taicang_sink == pytest.approx(expected_sink)
        assert taicang_loss == pytest.approx(expected_human + expected_sink)

    if outbound is not None:
        jingyun_human = containers["C_京运克扣"]
        jingyun_sink = containers["C_京运运损"]
        jingyun_loss = containers["hub_京运损耗"]
        outbound_debit = -ledger.get("边饷hub", 0.0)
        assert outbound_debit == pytest.approx(
            outbound["jingyun_paid"] + outbound["central_paid"] + jingyun_loss
        )
        assert jingyun_loss == pytest.approx(outbound["transport_loss"])
        if expected_jingyun_losses is not None:
            expected_human, expected_sink = expected_jingyun_losses
            assert jingyun_human == pytest.approx(expected_human)
            assert jingyun_sink == pytest.approx(expected_sink)
            assert outbound["transport_loss"] == pytest.approx(
                expected_human + expected_sink
            )


def _assert_hub_oracle_mutation_fails(
    ledger,
    containers,
    *,
    outbound=None,
    expected_taicang_losses=None,
    expected_jingyun_losses=None,
    mutate,
):
    mutated_ledger = dict(ledger)
    mutated_containers = dict(containers)
    mutated_outbound = dict(outbound) if outbound is not None else None
    mutate(mutated_ledger, mutated_containers, mutated_outbound)
    with pytest.raises(AssertionError):
        _assert_hub_conservation_oracle(
            mutated_ledger,
            mutated_containers,
            outbound=mutated_outbound,
            expected_taicang_losses=expected_taicang_losses,
            expected_jingyun_losses=expected_jingyun_losses,
        )


def _disable_army_pay_source_cutover(db):
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__army_pay_source_cutover', 0, 'meta', 'test legacy shadow mode')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__fiscal_engine', 0, 'meta', 'test legacy engine')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    db.conn.commit()


def _province_pay_due(db, region_id):
    rows = db.conn.execute(
        """
        SELECT * FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND pay_source_region = ?
        """,
        (region_id,),
    ).fetchall()
    return sum(army_needed(row) * float(row["province_pay_share"] or 0) for row in rows)


def _province_pay_arrears(db, region_id):
    return float(db.conn.execute(
        """
        SELECT COALESCE(SUM(province_pay_arrears), 0) AS total
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND pay_source_region = ?
        """,
        (region_id,),
    ).fetchone()["total"] or 0)


def _non_self_funded_pay_arrears(db):
    row = db.conn.execute(
        """
        SELECT
          COALESCE(SUM(province_pay_arrears), 0) AS province_total,
          COALESCE(SUM(central_pay_arrears), 0) AS central_total,
          COALESCE(SUM(arrears), 0) AS army_total
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
        """
    ).fetchone()
    return (
        float(row["province_total"] or 0),
        float(row["central_total"] or 0),
        float(row["army_total"] or 0),
    )


def _province_container_total(db):
    total = 0.0
    for row in db.conn.execute(
        "SELECT fiscal FROM regions WHERE controlled_by = 'ming'"
    ).fetchall():
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError):
            continue
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if isinstance(settle, dict) and isinstance(settle.get("st"), dict):
            total += float(settle["st"].get("军饷欠", 0) or 0)
    return total


def _standalone_region_pay_arrears(db, region_id):
    settle = _read_settle(db, region_id)
    if not isinstance(settle, dict):
        return 0.0
    if (
        db._primary_source_army_pay_due(settle) is None
        and not db._is_seeded_military_pay_funnel(settle)
    ):
        return 0.0
    if db._army_pay_source_rows_for_region(region_id):
        return 0.0
    return float(settle["st"].get("军饷欠", 0) or 0.0)


def _region_pay_arrears_container_basis(db, region_id):
    return _province_pay_arrears(db, region_id) + _standalone_region_pay_arrears(db, region_id)


def _region_with_settle(settle):
    return {
        "id": "test_province",
        "name": "测试省",
        "kind": "布政司",
        "population": 1,
        "public_support": 50,
        "unrest": 0,
        "natural_disaster": "无",
        "human_disaster": "无",
        "registered_land": 1,
        "hidden_land": 1,
        "tax_per_turn": 1,
        "grain_security": 1,
        "gentry_resistance": 0,
        "military_pressure": 0,
        "status": "测试",
        "controlled_by": "ming",
        "fiscal": {"settle": settle},
    }


def test_region_loader_expands_shared_settle_meta_defaults(monkeypatch):
    region = _region_with_settle({
        "_meta_defaults": "ming_province",
        "_meta": {
            "postures": ["江南财赋核心"],
            "notes": {"漕粮": "保留省份专属说明"},
        },
        "st": {},
        "p": {},
    })
    fake_regions = {
        "settle_meta_defaults": {
            "ming_province": {
                "provisional": ["宗禄", "起运定额", "官民田", "隐田"],
                "levies": {"seeded": ["辽饷"], "not_seeded": ["剿饷", "练饷"]},
                "notes": {"起运定额": "#259 后由饷率通道动态接管、此值届时失效"},
            }
        },
        "regions": [region],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    # before-image：须在 loader 可能共享/改写同一可变对象之前捕获 expected override
    expected_province_note = region["fiscal"]["settle"]["_meta"]["notes"]["漕粮"]
    loaded = content_mod.load_region_content()["test_province"].fiscal["settle"]

    assert "_meta_defaults" not in loaded
    assert loaded["_meta"]["provisional"] == ["宗禄", "起运定额", "官民田", "隐田"]
    assert loaded["_meta"]["levies"]["seeded"] == ["辽饷"]
    assert loaded["_meta"]["levies"]["not_seeded"] == ["剿饷", "练饷"]
    assert loaded["_meta"]["postures"] == ["江南财赋核心"]
    assert loaded["_meta"]["notes"]["起运定额"].startswith("#259")
    # 省份专属 notes 键保留并覆盖默认；与输入 before-image 同值，不另钉自由说明正文。
    assert loaded["_meta"]["notes"]["漕粮"] == expected_province_note
    assert "漕粮" not in fake_regions["settle_meta_defaults"]["ming_province"]["notes"]


def test_army_pay_source_spine_seed_splits_arrears_and_reconciles_tusi(fresh_db):
    assert fresh_db.is_army_pay_source_cutover_enabled()

    row = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               pay_source_region, province_pay_share, central_pay_share,
               is_tusi, self_funded_pay
        FROM armies WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert row["pay_source_region"] == "shaanxi"
    assert row["province_pay_share"] == pytest.approx(0.65)
    assert row["central_pay_share"] == pytest.approx(0.35)
    assert row["province_pay_arrears"] == pytest.approx(16.25)
    assert row["central_pay_arrears"] == pytest.approx(8.75)
    assert row["arrears"] == pytest.approx(
        row["province_pay_arrears"] + row["central_pay_arrears"]
    )

    pure = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               pay_source_region, province_pay_share, central_pay_share
        FROM armies WHERE id = 'fujian_navy'
        """
    ).fetchone()
    assert pure["pay_source_region"] == "fujian"
    assert pure["province_pay_share"] == pytest.approx(1.0)
    assert pure["central_pay_share"] == pytest.approx(0.0)
    assert pure["province_pay_arrears"] == pytest.approx(pure["arrears"])
    assert pure["central_pay_arrears"] == pytest.approx(0.0)

    tusi = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               province_pay_share, central_pay_share, is_tusi, self_funded_pay
        FROM armies WHERE id = 'southwest_tusi'
        """
    ).fetchone()
    assert tusi["is_tusi"] == 1
    assert tusi["self_funded_pay"] == 1
    assert tusi["province_pay_share"] == pytest.approx(0.0)
    assert tusi["central_pay_share"] == pytest.approx(0.0)
    assert tusi["province_pay_arrears"] == pytest.approx(0.0)
    assert tusi["central_pay_arrears"] == pytest.approx(0.0)
    assert tusi["arrears"] == pytest.approx(0.0)
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )

    log = fresh_db.conn.execute(
        """
        SELECT turn, year, period, army_id, field, old_value, new_value, delta, reason,
               event_id, edict_id, actor
        FROM army_logs
        WHERE army_id = 'southwest_tusi' AND field = 'arrears'
        """
    ).fetchone()
    assert log is not None
    assert log["turn"] == 1
    assert log["year"] == 1627
    assert log["period"] == 10
    assert log["old_value"] == "4.0"
    assert log["new_value"] == "0.0"
    assert log["delta"] == -4
    assert isinstance(log["reason"], str) and log["reason"].strip()
    assert log["event_id"] is None
    assert log["edict_id"] is None
    assert log["actor"] == "system"


def test_self_funded_seed_arrears_log_preserves_fractional_delta(tmp_path):
    content = GameContent.load()
    content.armies["southwest_tusi"] = replace(
        content.armies["southwest_tusi"],
        arrears=4.5,
    )
    bind_content(content)
    db = GameDB(str(tmp_path / "fractional-tusi.db"), content)
    db.seed_static_data()
    try:
        log = db.conn.execute(
            """
            SELECT old_value, new_value, delta
            FROM army_logs
            WHERE army_id = 'southwest_tusi' AND field = 'arrears'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert log is not None
        assert log["old_value"] == "4.5"
        assert log["new_value"] == "0.0"
        assert log["delta"] == pytest.approx(-4.5)
    finally:
        db.conn.close()
        bind_content(GameContent.load())


def test_fresh_save_pay_source_prefers_content_army_fields(tmp_path):
    content = GameContent.load()
    content.armies["xuan_da"] = replace(
        content.armies["xuan_da"],
        pay_source_region="shandong",
        province_pay_share=0.25,
        central_pay_share=0.75,
        is_tusi=0,
        self_funded_pay=0,
    )
    db = GameDB(str(tmp_path / "pay-source-content.db"), content)
    try:
        db.seed_static_data()
        row = db.conn.execute(
            """
            SELECT pay_source_region, province_pay_share, central_pay_share
            FROM armies WHERE id = 'xuan_da'
            """
        ).fetchone()
        assert row["pay_source_region"] == "shandong"
        assert row["province_pay_share"] == pytest.approx(0.25)
        assert row["central_pay_share"] == pytest.approx(0.75)
    finally:
        db.close()


def test_province_tick_derives_due_and_allocates_province_arrears_by_pay_source(fresh_db):
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 1.0,
            central_pay_share = 0.0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            station = '福建', manpower = 10000, salary_rate = 5
        WHERE id = 'fujian_navy'
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 6.5,
            central_pay_arrears = 3.5, arrears = 10,
            station = '北直隶 / 客防', manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    _write_settle(
        fresh_db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 999,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 8,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )

    result = fresh_db.settle_province_tick("shaanxi")

    mixed = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    pure = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'fujian_navy'"
    ).fetchone()
    mixed_due = army_needed(mixed) * 0.65
    pure_due = army_needed(pure)
    total_due = mixed_due + pure_due
    assert result.breakdown["NewDebt"]["军饷欠"] == pytest.approx(total_due - 8)

    expected_mixed = 6.5 + (total_due - 8) * mixed_due / total_due
    expected_pure = (total_due - 8) * pure_due / total_due
    assert mixed["province_pay_arrears"] == pytest.approx(expected_mixed)
    assert pure["province_pay_arrears"] == pytest.approx(expected_pure)
    assert mixed["central_pay_arrears"] == pytest.approx(3.5)
    assert mixed["arrears"] == pytest.approx(
        mixed["province_pay_arrears"] + mixed["central_pay_arrears"]
    )

    settle = _read_settle(fresh_db, "shaanxi")
    assert settle["p"]["Due"]["军饷"] == pytest.approx(total_due)
    assert settle["st"]["军饷欠"] == pytest.approx(
        mixed["province_pay_arrears"] + pure["province_pay_arrears"]
    )
    log_rows = fresh_db.conn.execute(
        """
        SELECT army_id, field, old_value, new_value, delta, reason, actor
        FROM army_logs
        WHERE army_id IN ('shaanxi_army', 'fujian_navy')
          AND field = 'province_pay_arrears'
        ORDER BY army_id
        """
    ).fetchall()
    assert {row["army_id"] for row in log_rows} == {"shaanxi_army", "fujian_navy"}
    assert all(isinstance(row["reason"], str) and row["reason"].strip() for row in log_rows)
    assert all(row["actor"] == "户部" for row in log_rows)
    assert all(float(row["delta"] or 0) != 0 for row in log_rows)


def test_conservation_rejects_excluded_army_with_pay_source_debt(fresh_db):
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET owner_power = 'houjin',
            province_pay_share = 0,
            central_pay_share = 0,
            province_pay_arrears = 2,
            central_pay_arrears = 3,
            arrears = 5
        WHERE id = 'guanning'
        """
    )
    fresh_db._reconcile_army_pay_source_region_container("liaodong")
    fresh_db._reconcile_central_army_pay_arrears_container()

    with pytest.raises(ValueError, match="自养/非明军双累加器必须为 0"):
        fresh_db.assert_army_pay_source_container_conservation()


def test_conservation_rejects_province_source_army_without_settle_base(fresh_db):
    fresh_db.conn.execute(
        "UPDATE regions SET controlled_by = 'ming', fiscal = '{}' WHERE id = 'taiwan'"
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET owner_power = 'ming',
            is_tusi = 0,
            self_funded_pay = 0,
            pay_source_region = 'taiwan',
            province_pay_share = 1,
            central_pay_share = 0,
            province_pay_arrears = 1,
            central_pay_arrears = 0,
            arrears = 1
        WHERE id = 'fujian_navy'
        """
    )
    fresh_db._reconcile_central_army_pay_arrears_container()

    with pytest.raises(ValueError, match="pay_source_region 无 settle st/p 基座"):
        fresh_db.assert_army_pay_source_container_conservation()


def test_fixed_flows_substrate_hub_retires_global_central_pay_route(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 0
    db.save_state(state)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    row = db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert not any(
        flow.get("account") == "国库" and flow.get("category") == "各军军饷"
        for flow in flow_rows
    )
    assert row["central_pay_arrears"] == pytest.approx(3.5)
    assert row["arrears"] == pytest.approx(
        row["province_pay_arrears"] + row["central_pay_arrears"]
    )
    assert db.get_central_army_pay_arrears_container() == pytest.approx(3.5)
    _province_total, central_total, army_total = _non_self_funded_pay_arrears(db)
    assert db.get_central_army_pay_arrears_container() == pytest.approx(central_total)
    assert _province_container_total(db) + db.get_central_army_pay_arrears_container() == pytest.approx(
        army_total + db._standalone_army_pay_container_total()
    )


def test_fixed_flows_legacy_engine_keeps_global_army_pay_route(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    state.metrics["国库"] = 0
    db.save_state(state)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET owner_power = ?, self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """,
        (db.conn.execute("SELECT id FROM powers WHERE id <> 'ming' LIMIT 1").fetchone()[0],),
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    db.conn.commit()

    flows_mod.apply_fixed_period_flows(db, state)

    row = db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert row["arrears"] == pytest.approx(10)
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)



def test_substrate_hub_dual_track_sanity_keeps_legacy_calc_as_reference(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    legacy_treasury, legacy_inner, legacy_lines = flows_mod.calc_province_fiscal(state, db)

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(legacy_treasury, int)
    assert isinstance(legacy_inner, int)
    assert isinstance(legacy_lines, list)
    assert any(flow.get("category") == "边饷hub" for flow in flow_rows)
    assert any(flow.get("category") == "中央军饷" for flow in flow_rows)
    db.assert_army_pay_source_container_conservation()


def test_substrate_hub_cutover_runs_multi_tick_treasury_trajectory(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    db.conn.commit()

    balances = []
    taicang_loss_months = []
    taicang_loss_stocks = []
    for _ in range(3):
        turn = state.turn
        flow_rows = flows_mod.apply_fixed_period_flows(db, state)
        balances.append(state.metrics["国库"])
        container_snapshot = _hub_container_snapshot(db)
        taicang_loss_months.append(container_snapshot["hub_太仓亏空"])
        taicang_loss_stocks.append(
            container_snapshot["C_太仓挪用"] + container_snapshot["C_太仓纯亏空"]
        )

        assert any(row.get("category") == "起运" for row in flow_rows)
        _assert_hub_conservation_oracle(
            _hub_ledger_snapshot(db, turn=turn),
            container_snapshot,
        )

        state.turn += 1
        db.save_state(state)

    assert len(set(balances)) > 1
    assert balances[-1] == db.load_state().metrics["国库"]
    assert taicang_loss_stocks[-1] == pytest.approx(sum(taicang_loss_months))
    assert taicang_loss_stocks[-1] > taicang_loss_months[-1]


def test_ready_context_retry_does_not_recompute_substrate_hub_pre_settle(fresh_game):
    from ming_sim.decree import persist_resolve_context, pre_settle

    db, state = fresh_game
    turn = state.turn

    pre_settle(state, db)
    before_ledger = _hub_ledger_snapshot(db, turn=turn)
    before_containers = _hub_container_snapshot(db)
    before_balance = state.metrics["国库"]

    persist_resolve_context(
        db,
        turn,
        {},
        decree_text="测试诏",
        narrative="测试邸报",
        simulator_payload={},
        secret_orders=[],
        relevant_memories=[],
    )
    assert db.get_resolve_context(turn)["extracted"] == {}

    pre_settle(state, db)

    assert _hub_ledger_snapshot(db, turn=turn) == before_ledger
    assert _hub_container_snapshot(db) == before_containers
    assert state.metrics["国库"] == before_balance
    _assert_hub_conservation_oracle(before_ledger, before_containers)


def test_fixed_flows_substrate_hub_central_capacity_reduces_current_central_arrears(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 10
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    for army_id in ("guanning", "shaanxi_army"):
        db.conn.execute(
            """
            UPDATE armies
            SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
                pay_source_region = 'shaanxi', province_pay_share = 0,
                central_pay_share = 1, province_pay_arrears = 0,
                central_pay_arrears = 0, arrears = 0,
                manpower = 10000, salary_rate = 10
            WHERE id = ?
            """,
            (army_id,),
        )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    rows = {
        row["id"]: row
        for row in db.conn.execute(
            """
            SELECT id, central_pay_arrears, arrears
            FROM armies
            WHERE id IN ('guanning', 'shaanxi_army')
            """
        ).fetchall()
    }
    assert not any(
        flow.get("account") == "国库" and flow.get("category") == "各军军饷"
        for flow in flow_rows
    )
    assert rows["guanning"]["central_pay_arrears"] == pytest.approx(5)
    assert rows["shaanxi_army"]["central_pay_arrears"] == pytest.approx(5)
    assert rows["guanning"]["arrears"] == pytest.approx(5)
    assert rows["shaanxi_army"]["arrears"] == pytest.approx(5)
    assert db.get_central_army_pay_arrears_container() == pytest.approx(10)


def test_fixed_flows_substrate_hub_central_pay_shares_hub_tier_with_jingyun_grants(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 15
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 10,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 0, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    _set_fiscal_config_value(db, "central_jingyun_human_loss_rate", 20)
    _set_fiscal_config_value(db, "central_jingyun_sink_loss_rate", 10)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    for army_id in ("guanning", "shaanxi_army"):
        db.conn.execute(
            """
            UPDATE armies
            SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
                pay_source_region = 'shaanxi', province_pay_share = 0,
                central_pay_share = 1, province_pay_arrears = 0,
                central_pay_arrears = 0, arrears = 0,
                manpower = 10000, salary_rate = 10
            WHERE id = ?
            """,
            (army_id,),
        )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    rows = {
        row["id"]: row
        for row in db.conn.execute(
            """
            SELECT id, central_pay_arrears, arrears
            FROM armies
            WHERE id IN ('guanning', 'shaanxi_army')
            """
        ).fetchall()
    }
    expense_row = next(flow for flow in flow_rows if flow.get("category") == "边饷hub")
    hub_row = next(flow for flow in flow_rows if flow.get("category") == "中央军饷")
    assert hub_row["jingyun_due"] == pytest.approx(10)
    assert hub_row["needed"] == pytest.approx(20)
    assert hub_row["k"] == pytest.approx(0.5)
    assert hub_row["paid"] == pytest.approx(6)
    assert expense_row["paid"] == pytest.approx(15)
    assert expense_row["jingyun_paid"] == pytest.approx(4)
    assert expense_row["central_paid"] == pytest.approx(6)
    assert expense_row["transport_loss"] == pytest.approx(5)
    loss_rows = {
        row["key"]: row["value"]
        for row in db.conn.execute(
            "SELECT key, value FROM fiscal_containers WHERE key IN ('C_京运克扣', 'C_京运运损')"
        ).fetchall()
    }
    assert loss_rows["C_京运克扣"] == pytest.approx(3)
    assert loss_rows["C_京运运损"] == pytest.approx(2)
    ledger = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库' AND category = '边饷hub'
        """
    ).fetchone()
    assert ledger["delta"] == pytest.approx(-15)
    assert rows["guanning"]["central_pay_arrears"] == pytest.approx(7)
    assert rows["shaanxi_army"]["central_pay_arrears"] == pytest.approx(7)
    assert rows["guanning"]["arrears"] == pytest.approx(7)
    assert rows["shaanxi_army"]["arrears"] == pytest.approx(7)
    assert db.get_central_army_pay_arrears_container() == pytest.approx(14)
    ledger_snapshot = _hub_ledger_snapshot(db, turn=state.turn)
    container_snapshot = _hub_container_snapshot(db)
    outbound = {
        "jingyun_paid": expense_row["jingyun_paid"],
        "central_paid": expense_row["central_paid"],
        "transport_loss": expense_row["transport_loss"],
    }
    expected_jingyun_losses = (3, 2)
    _assert_hub_conservation_oracle(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=expected_jingyun_losses,
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=expected_jingyun_losses,
        mutate=lambda ledger, containers, out: ledger.__setitem__(
            "边饷hub", ledger["边饷hub"] + 1
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=expected_jingyun_losses,
        mutate=lambda ledger, containers, out: containers.__setitem__(
            "C_京运克扣", containers["C_京运克扣"] + 1
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=expected_jingyun_losses,
        mutate=lambda ledger, containers, out: (
            containers.__setitem__("C_京运克扣", 2),
            containers.__setitem__("C_京运运损", 0),
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=expected_jingyun_losses,
        mutate=lambda ledger, containers, out: out.__setitem__(
            "transport_loss", out["transport_loss"] + 1
        ),
    )


def test_fixed_flows_substrate_hub_central_pay_carries_transport_loss_without_jingyun(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 10
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    _set_fiscal_config_value(db, "central_jingyun_human_loss_rate", 20)
    _set_fiscal_config_value(db, "central_jingyun_sink_loss_rate", 10)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0,
            central_pay_share = 1, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 10000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    expense_row = next(flow for flow in flow_rows if flow.get("category") == "边饷hub")
    central_row = next(flow for flow in flow_rows if flow.get("category") == "中央军饷")
    army = db.conn.execute(
        "SELECT central_pay_arrears, arrears FROM armies WHERE id = 'guanning'"
    ).fetchone()
    loss_rows = {
        row["key"]: row["value"]
        for row in db.conn.execute(
            "SELECT key, value FROM fiscal_containers WHERE key IN ('C_京运克扣', 'C_京运运损')"
        ).fetchall()
    }
    persisted = {
        row["key"]: row["value"]
        for row in db.conn.execute(
            "SELECT key, value FROM fiscal_containers WHERE key IN ('hub_京运实拨', 'hub_中央军饷实拨', 'hub_京运损耗')"
        ).fetchall()
    }
    ledger = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库' AND category = '边饷hub'
        """
    ).fetchone()

    assert central_row["jingyun_due"] == pytest.approx(0)
    assert central_row["needed"] == pytest.approx(10)
    assert central_row["k"] == pytest.approx(1)
    assert central_row["paid"] == pytest.approx(7)
    assert central_row["shortfall"] == pytest.approx(3)
    assert central_row["transport_loss"] == pytest.approx(3)
    assert expense_row["paid"] == pytest.approx(10)
    assert expense_row["jingyun_paid"] == pytest.approx(0)
    assert expense_row["central_paid"] == pytest.approx(7)
    assert expense_row["transport_loss"] == pytest.approx(3)
    assert loss_rows["C_京运克扣"] == pytest.approx(2)
    assert loss_rows["C_京运运损"] == pytest.approx(1)
    assert persisted["hub_京运实拨"] == pytest.approx(0)
    assert persisted["hub_中央军饷实拨"] == pytest.approx(7)
    assert persisted["hub_京运损耗"] == pytest.approx(3)
    assert ledger["delta"] == pytest.approx(-10)
    assert army["central_pay_arrears"] == pytest.approx(3)
    assert army["arrears"] == pytest.approx(3)

    # #1366：从玩家可达 treasury_report 真入口接线；机器断言落结构化结果，
    # 不锁生成文本措辞。
    assert db.treasury_report(state)
    assert db.treasury_hub_result(state) == {
        "treasury_disbursed": 10,
        "actual_arrived": 7,
        "transit_loss": 3,
    }

    ledger_snapshot = _hub_ledger_snapshot(db, turn=state.turn)
    container_snapshot = _hub_container_snapshot(db)
    outbound = {
        "jingyun_paid": expense_row["jingyun_paid"],
        "central_paid": expense_row["central_paid"],
        "transport_loss": expense_row["transport_loss"],
    }
    _assert_hub_conservation_oracle(
        ledger_snapshot,
        container_snapshot,
        outbound=outbound,
        expected_jingyun_losses=(2, 1),
    )


def test_fixed_flows_substrate_hub_books_split_treasury_income_and_central_losses(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 0
    db.save_state(state)
    sync_opening_legacies(db, state)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    _set_fiscal_config_value(db, "central_taicang_human_loss_rate", 10)
    _set_fiscal_config_value(db, "central_taicang_sink_loss_rate", 5)
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute("UPDATE regions SET controlled_by = 'houjin', tax_per_turn = 999")
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 20,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 12,
                "拨付gross": 0,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 0, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute(
        """
        UPDATE regions
        SET controlled_by = 'ming',
            fiscal = json_set(fiscal, '$.salt_tax', 3, '$.commerce_tax', 4)
        WHERE id = 'shaanxi'
        """
    )
    db.conn.commit()

    net_pct = int(db.legacy_modifiers(state).get("国库", 0) or 0)
    assert net_pct < 0
    expected_remittance = db.apply_legacy_pct(12, net_pct)
    expected_salt = db.apply_legacy_pct(3, net_pct)
    expected_commerce = db.apply_legacy_pct(4, net_pct)

    pre_budget = flows_mod.compute_budget_lines(db, state)
    pre_income = {
        row["name"]: row["amount"]
        for row in pre_budget["国库"]["income"]
        if row["name"] in {"起运", "盐税", "商税"}
    }
    pre_expense = {
        row["name"]: row["amount"]
        for row in pre_budget["国库"]["expense"]
        if row["name"] == "太仓亏空"
    }
    assert pre_income == {
        "起运": expected_remittance,
        "盐税": expected_salt,
        "商税": expected_commerce,
    }
    assert pre_expense == {"太仓亏空": 3}

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert state.metrics["国库"] == expected_remittance + expected_salt + expected_commerce - 3
    flow_by_category = {flow.get("category"): flow for flow in flow_rows}
    assert flow_by_category["起运"]["amount"] == expected_remittance
    assert flow_by_category["盐税"]["amount"] == expected_salt
    assert flow_by_category["商税"]["amount"] == expected_commerce
    assert flow_by_category["太仓亏空"]["amount"] == 3
    ledger = {
        row["category"]: row["delta"]
        for row in db.conn.execute(
            """
            SELECT category, delta
            FROM economy_ledger
            WHERE account = '国库' AND category IN ('起运', '盐税', '商税', '太仓亏空')
            """
        ).fetchall()
    }
    assert ledger == {
        "起运": expected_remittance,
        "盐税": expected_salt,
        "商税": expected_commerce,
        "太仓亏空": -3,
    }
    containers = {
        row["key"]: row["value"]
        for row in db.conn.execute(
            """
            SELECT key, value
            FROM fiscal_containers
            WHERE key IN (
                'hub_省级起运到京', 'hub_盐税解京', 'hub_商税解京',
                'C_太仓挪用', 'C_太仓纯亏空'
            )
            """
        ).fetchall()
    }
    assert containers["hub_省级起运到京"] == pytest.approx(expected_remittance)
    assert containers["hub_盐税解京"] == pytest.approx(expected_salt)
    assert containers["hub_商税解京"] == pytest.approx(expected_commerce)
    assert containers["C_太仓挪用"] == pytest.approx(2)
    assert containers["C_太仓纯亏空"] == pytest.approx(1)
    ledger_snapshot = _hub_ledger_snapshot(db, turn=state.turn)
    container_snapshot = _hub_container_snapshot(db)
    expected_taicang_losses = (2, 1)
    _assert_hub_conservation_oracle(
        ledger_snapshot,
        container_snapshot,
        expected_taicang_losses=expected_taicang_losses,
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        expected_taicang_losses=expected_taicang_losses,
        mutate=lambda ledger, containers, out: containers.__setitem__(
            "hub_省级起运到京", containers["hub_省级起运到京"] + 1
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        expected_taicang_losses=expected_taicang_losses,
        mutate=lambda ledger, containers, out: ledger.__setitem__(
            "太仓亏空", ledger["太仓亏空"] - 1
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        expected_taicang_losses=expected_taicang_losses,
        mutate=lambda ledger, containers, out: containers.__setitem__(
            "C_太仓挪用", containers["C_太仓挪用"] + 1
        ),
    )
    _assert_hub_oracle_mutation_fails(
        ledger_snapshot,
        container_snapshot,
        expected_taicang_losses=expected_taicang_losses,
        mutate=lambda ledger, containers, out: (
            containers.__setitem__("C_太仓挪用", 3),
            containers.__setitem__("C_太仓纯亏空", 0),
        ),
    )


def test_budget_projection_passes_copied_settle_snapshots_to_fiscal_tick(fresh_game, monkeypatch):
    import ming_sim.fiscal_tick as fiscal_tick_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    original_json_loads = flows_mod.json.loads
    original_settle_tick = fiscal_tick_mod.settle_tick
    original_st_objects = []
    original_p_objects = []
    seen_tick_args = []

    def tracking_json_loads(raw):
        parsed = original_json_loads(raw)
        settle = parsed.get("settle") if isinstance(parsed, dict) else None
        if isinstance(settle, dict):
            st = settle.get("st")
            p = settle.get("p")
            if isinstance(st, dict):
                original_st_objects.append(st)
            if isinstance(p, dict):
                original_p_objects.append(p)
        return parsed

    def spy_settle_tick(st, p, actions):
        # 委派 spy：真调用真返回；只记录 identity，证明 projection 传入的是拷贝。
        seen_tick_args.append((st, p))
        return original_settle_tick(st, p, actions)

    monkeypatch.setattr(flows_mod.json, "loads", tracking_json_loads)
    monkeypatch.setattr(fiscal_tick_mod, "settle_tick", spy_settle_tick)

    budget = flows_mod.compute_budget_lines(db, state)

    assert seen_tick_args, "substrate hub budget projection should call settle_tick"
    assert isinstance(budget, dict) and "国库" in budget
    assert all(
        tick_st is not original_st
        for tick_st, _ in seen_tick_args
        for original_st in original_st_objects
    )
    assert all(
        tick_p is not original_p
        for _, tick_p in seen_tick_args
        for original_p in original_p_objects
    )


def test_budget_lines_read_persisted_substrate_hub_income_source(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    db.conn.executemany(
        """
        INSERT INTO fiscal_containers (key, value, note)
        VALUES (?, ?, 'test persisted hub source')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """,
        [
            ("hub_省级起运到京", 11),
            ("hub_盐税解京", 3),
            ("hub_商税解京", 4),
            ("hub_太仓亏空", 3),
            ("C_太仓挪用", 2),
            ("C_太仓纯亏空", 1),
        ],
    )
    db.conn.execute(
        """
        UPDATE regions
        SET fiscal = json_set(
            fiscal,
            '$.settle.p.正赋应征', 999,
            '$.settle.p.起运定额', 999,
            '$.salt_tax', 999,
            '$.commerce_tax', 999
        )
        """
    )
    db.conn.commit()

    budget = flows_mod.compute_budget_lines(db, state)

    income = {row["name"]: row["amount"] for row in budget["国库"]["income"]}
    expenses = {row["name"]: row["amount"] for row in budget["国库"]["expense"]}
    assert income["起运"] == 11
    assert income["盐税"] == 3
    assert income["商税"] == 4
    assert "田赋辽饷盐商" not in income
    assert expenses["太仓亏空"] == 3


def test_substrate_hub_skip_uses_internal_marker_not_user_fixed_display(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE regions
        SET controlled_by = 'houjin',
            fiscal = json_set(fiscal, '$.salt_tax', 0, '$.commerce_tax', 0)
        """
    )
    db.create_fiscal_item(
        "巡盐加派_base",
        "国库",
        "income",
        "盐税",
        7,
        note="display intentionally collides with substrate hub salt tax",
        commit=False,
    )
    db.conn.commit()

    budget = flows_mod.compute_budget_lines(db, state)
    salt_lines = [row for row in budget["国库"]["income"] if row["name"] == "盐税"]
    assert any(row.get("internal") == "substrate_hub" for row in salt_lines)
    assert any(row.get("internal") != "substrate_hub" for row in salt_lines)

    flows_mod.apply_fixed_period_flows(db, state)

    net_pct = int(db.legacy_modifiers(state).get("国库", 0) or 0)
    expected = db.apply_legacy_pct(7, net_pct) if net_pct else 7
    rows = db.conn.execute(
        """
        SELECT delta, reason
        FROM economy_ledger
        WHERE account = '国库' AND category = '盐税'
        ORDER BY id
        """
    ).fetchall()
    assert [int(row["delta"]) for row in rows] == [expected]
    assert all(str(row["reason"] or "").strip() for row in rows)


def test_substrate_hub_uses_month_opening_treasury_before_lower_priority_expenses(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 15
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 10,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 0, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute("UPDATE fiscal_config SET value = 10 WHERE key = '官俸_base'")
    db.conn.execute("UPDATE fiscal_config SET value = 100 WHERE key = '官俸_rate'")
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    for army_id in ("guanning", "shaanxi_army"):
        db.conn.execute(
            """
            UPDATE armies
            SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
                pay_source_region = 'shaanxi', province_pay_share = 0,
                central_pay_share = 1, province_pay_arrears = 0,
                central_pay_arrears = 0, arrears = 0,
                manpower = 10000, salary_rate = 10
            WHERE id = ?
            """,
            (army_id,),
        )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    hub_row = next(flow for flow in flow_rows if flow.get("category") == "边饷hub")
    central_row = next(flow for flow in flow_rows if flow.get("category") == "中央军饷")
    low_priority = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库' AND category = '百官俸禄'
        """
    ).fetchone()
    assert hub_row["needed"] == pytest.approx(30)
    assert hub_row["paid"] == pytest.approx(15)
    assert central_row["paid"] == pytest.approx(10)
    assert low_priority["delta"] == 0
    split_income = sum(
        flow["amount"]
        for flow in flow_rows
        if flow.get("category") in {"起运", "盐税", "商税"}
    )
    taicang_loss = sum(
        flow["amount"]
        for flow in flow_rows
        if flow.get("category") == "太仓亏空"
    )
    assert state.metrics["国库"] == pytest.approx(split_income - taicang_loss)


def test_fixed_flows_substrate_hub_integer_allocation_drives_all_consumers(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 5
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 3,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 3, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.5,
            central_pay_share = 0.5, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 6000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    ledger = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库' AND category = '边饷hub'
        """
    ).fetchone()
    hub_row = next(flow for flow in flow_rows if flow.get("category") == "边饷hub")
    central_row = next(flow for flow in flow_rows if flow.get("category") == "中央军饷")
    army = db.conn.execute(
        "SELECT central_pay_arrears FROM armies WHERE id = 'guanning'"
    ).fetchone()
    settle = _read_settle(db, "shaanxi")

    assert ledger["delta"] == -5
    assert hub_row["paid"] == 5
    assert hub_row["jingyun_paid"] + hub_row["central_paid"] == 5
    assert central_row["paid"] == pytest.approx(hub_row["central_paid"])
    assert settle["p"]["拨付gross"] == pytest.approx(3)
    province_paid = 3 - settle["st"]["军饷欠"]
    central_paid = 3 - army["central_pay_arrears"]
    assert province_paid + central_paid == pytest.approx(5)


def test_substrate_hub_debit_fails_loud_when_required_debit_not_booked(fresh_db, monkeypatch):
    # #287 PR R2：hub allocation 已决定要扣国库时，ledger 写入失败不能静默当 0。
    from ming_sim.flows import _HubOutboundResult, _debit_substrate_hub_outbound

    hub_outbound = _HubOutboundResult(
        k=1.0,
        jingyun_due_total=0.0,
        jingyun_paid_by_region={},
        jingyun_paid_total=0.0,
        central_due_total=5.0,
        central_paid_by_army={"guanning": 5.0},
        central_paid_total=5.0,
        central_transport_loss=0.0,
        central_transport_human_loss=0.0,
        central_transport_sink_loss=0.0,
    )
    monkeypatch.setattr(
        fresh_db, "record_issue_economy_move",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="边饷hub"):
        _debit_substrate_hub_outbound(fresh_db, SimpleNamespace(), hub_outbound)


def test_fixed_flows_substrate_hub_fractional_due_caps_integer_debit(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 10
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 3.5,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 0.4, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.4,
            central_pay_share = 0.6, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 1000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    ledger = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE account = '国库' AND category = '边饷hub'
        """
    ).fetchone()
    hub_row = next(flow for flow in flow_rows if flow.get("category") == "边饷hub")
    central_row = next(flow for flow in flow_rows if flow.get("category") == "中央军饷")
    army = db.conn.execute(
        "SELECT arrears, central_pay_arrears FROM armies WHERE id = 'guanning'"
    ).fetchone()
    settle = _read_settle(db, "shaanxi")

    assert ledger["delta"] == -3
    assert hub_row["paid"] == 3
    assert hub_row["jingyun_paid"] == 3
    assert hub_row["central_paid"] == 0
    assert central_row["paid"] == 0
    assert central_row["shortfall"] == pytest.approx(0.6)
    assert army["central_pay_arrears"] == pytest.approx(0.6)
    assert army["arrears"] == pytest.approx(0.6)
    assert settle["p"]["拨付gross"] == pytest.approx(3.5)
    assert settle["st"]["军饷欠"] == pytest.approx(0)


def test_region_army_pay_tick_treats_missing_breakdown_as_no_delta(fresh_db):
    # #287 PR R2：settle result breakdown 缺失时按无本月军饷 delta 处理，不因 None 崩 tick。
    pay_rows = fresh_db._army_pay_source_rows_for_region("shaanxi")
    assert pay_rows, "陕西应有省源军饷行，保证测试命中实际 tick seam"
    pay_row = dict(pay_rows[0])
    army_id = str(pay_row["id"])
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET province_pay_arrears = 1, central_pay_arrears = 0, arrears = 1
        WHERE id = ?
        """,
        (army_id,),
    )
    fresh_db.conn.commit()
    pay_row["province_pay_arrears"] = 1.0
    pay_row["central_pay_arrears"] = 0.0
    before = fresh_db.conn.execute(
        "SELECT province_pay_arrears, arrears, morale FROM armies WHERE id = ?",
        (army_id,),
    ).fetchone()

    fresh_db._apply_region_army_pay_tick([pay_row], SimpleNamespace(breakdown=None))

    after = fresh_db.conn.execute(
        "SELECT province_pay_arrears, arrears, morale FROM armies WHERE id = ?",
        (army_id,),
    ).fetchone()
    assert after["province_pay_arrears"] == pytest.approx(before["province_pay_arrears"])
    assert after["arrears"] == pytest.approx(before["arrears"])
    assert after["morale"] == before["morale"]


def test_region_army_morale_haircut_denominator_includes_standalone_funnel(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 2
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    _write_settle(
        db, "liaodong", {
            "_meta": {
                "postures": ["纯军饷漏斗"],
                "standalone_military_pay_due": 10,
            },
            "st": {
                "省库库银": 0, "C_地方截留": 0, "C_中饱": 0,
                "C_漂没": 0, "C_eff损耗": 0, "民欠旧赋": 0,
                "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
                "官民田": 0, "隐田": 0,
            },
            "p": {
                "正赋应征": 0, "三饷应征": 0, "火耗率": 0,
                "逋赋率": 0, "起运定额": 0, "拨付gross": 0,
                "中饱率": 0, "漂没率": 0,
                "Due": {"军饷": 14, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute("UPDATE buildings SET output_amount=0, maintenance=0")
    _zero_non_meta_fiscal_config(db)
    _set_fiscal_config_value(db, "due_haircut_bp_军饷@liaodong#province", 5000)
    _set_fiscal_config_value(db, "due_haircut_bp_军饷@liaodong#central", 5000)
    db.conn.execute(
        "UPDATE regions SET tax_per_turn=0, fiscal=json_set(fiscal, "
        "'$.huang_tian',0,'$.liao_xiang',0,'$.salt_tax',0,'$.commerce_tax',0)"
    )
    db.conn.execute(
        "UPDATE armies SET self_funded_pay=1, is_tusi=1, province_pay_share=0, "
        "central_pay_share=0, pay_source_region='', province_pay_arrears=0, "
        "central_pay_arrears=0, arrears=0, morale=80"
    )
    db.conn.execute(
        "UPDATE armies SET self_funded_pay=0, is_tusi=0, owner_power='ming', "
        "pay_source_region='liaodong', province_pay_share=.4, central_pay_share=.6, "
        "province_pay_arrears=0, central_pay_arrears=0, arrears=0, morale=80, "
        "manpower=10000, salary_rate=10 WHERE id='guanning'"
    )
    db.conn.commit()

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    central = next(row for row in flow_rows if row.get("category") == "中央军饷")
    army = db.conn.execute(
        "SELECT morale, province_pay_arrears, central_pay_arrears "
        "FROM armies WHERE id='guanning'"
    ).fetchone()
    settle = _read_settle(db, "liaodong")
    assert settle["st"]["军饷欠"] == pytest.approx(7)
    assert army["province_pay_arrears"] == pytest.approx(2)
    assert central["needed"] == pytest.approx(3)
    assert central["shortfall"] == pytest.approx(1)
    assert army["central_pay_arrears"] == pytest.approx(1)
    assert army["morale"] == 75


def test_fixed_flows_substrate_hub_failure_rolls_back_cutover_writes(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 2
    db.save_state(state)
    _set_all_settle_grants(db, 0)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0,
            central_pay_share = 1, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 5000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()
    before_balance = db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account = '国库'"
    ).fetchone()["balance"]

    def fail_after_hub(*_args, **_kwargs):
        raise RuntimeError("boom after hub")

    monkeypatch.setattr(flows_mod, "_advance_province_fiscal_substrate", fail_after_hub)

    with pytest.raises(RuntimeError, match="boom after hub"):
        flows_mod.apply_fixed_period_flows(db, state)

    ledger = db.conn.execute(
        """
        SELECT COALESCE(SUM(delta), 0) AS delta
        FROM economy_ledger
        WHERE category = '边饷hub'
        """
    ).fetchone()
    army = db.conn.execute(
        "SELECT central_pay_arrears, arrears FROM armies WHERE id = 'guanning'"
    ).fetchone()
    after_balance = db.conn.execute(
        "SELECT balance FROM economy_accounts WHERE account = '国库'"
    ).fetchone()["balance"]
    assert ledger["delta"] == 0
    assert army["central_pay_arrears"] == pytest.approx(0)
    assert army["arrears"] == pytest.approx(0)
    assert after_balance == before_balance
    assert state.metrics["国库"] == before_balance


def test_pre_s6_cutover_save_without_fiscal_engine_migrates_to_substrate_hub(fresh_db):
    import ming_sim.flows as flows_mod

    path = fresh_db.path
    content = fresh_db.content
    fresh_db.conn.execute(
        "DELETE FROM fiscal_config WHERE key = '__fiscal_engine'"
    )
    fresh_db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__army_pay_source_cutover', 1, 'meta', 'pre-S6 cutover save')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    fresh_db.conn.commit()

    reopened = GameDB(path, content)
    try:
        state = reopened.load_state()
        assert reopened.fiscal_engine() == "substrate_hub"
        row = reopened.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = '__fiscal_engine'"
        ).fetchone()
        assert row is not None
        assert int(row["value"]) == 1

        budget = flows_mod.compute_budget_lines(reopened, state)
        army_pay = next(
            row["amount"] for row in budget["国库"]["expense"]
            if row.get("budget_key") == "army_pay"
        )
        assert army_pay > 0

        flow_rows = flows_mod.apply_fixed_period_flows(reopened, state)
        assert not any(
            row.get("account") == "国库" and row.get("category") == "各军军饷"
            for row in flow_rows
        )
        assert any(row.get("category") == "中央军饷" for row in flow_rows)
    finally:
        reopened.conn.close()


@pytest.mark.parametrize("starting_schema_version", [6, 7])
def test_fiscal_config_v8_migration_preserves_deleted_old_keys(
    fresh_db, starting_schema_version
):
    path = fresh_db.path
    content = fresh_db.content
    new_loss_keys = (
        "central_taicang_human_loss_rate",
        "central_taicang_sink_loss_rate",
        "central_jingyun_human_loss_rate",
        "central_jingyun_sink_loss_rate",
    )
    fresh_db.conn.execute("DELETE FROM fiscal_config WHERE key = '官俸_base'")
    fresh_db.conn.executemany(
        "DELETE FROM fiscal_config WHERE key = ?",
        [(key,) for key in new_loss_keys],
    )
    fresh_db.conn.execute(
        "UPDATE fiscal_config SET value = ? WHERE key = '__schema_version'",
        (starting_schema_version,),
    )
    fresh_db.conn.commit()

    reopened = GameDB(path, content)
    try:
        deleted = reopened.conn.execute(
            "SELECT 1 FROM fiscal_config WHERE key = '官俸_base'"
        ).fetchone()
        assert deleted is None
        rows = reopened.conn.execute(
            f"SELECT key FROM fiscal_config WHERE key IN ({','.join('?' for _ in new_loss_keys)})",
            new_loss_keys,
        ).fetchall()
        assert {str(row["key"]) for row in rows} == set(new_loss_keys)
        version = reopened.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = '__schema_version'"
        ).fetchone()
        assert int(version["value"]) == 8
    finally:
        reopened.conn.close()


def test_province_pay_shortfall_reduces_pure_province_army_morale(fresh_db):
    _write_settle(
        fresh_db,
        "fujian",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 0,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'fujian', province_pay_share = 1.0,
            central_pay_share = 0.0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0, morale = 80,
            manpower = 10000, salary_rate = 10
        WHERE id = 'fujian_navy'
        """
    )
    fresh_db.conn.commit()

    fresh_db.settle_province_tick("fujian")

    row = fresh_db.conn.execute(
        """
        SELECT morale, arrears, province_pay_arrears, central_pay_arrears
        FROM armies WHERE id = 'fujian_navy'
        """
    ).fetchone()
    assert row["province_pay_arrears"] == pytest.approx(10)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(row["province_pay_arrears"])
    assert row["morale"] == 72
    morale_log = fresh_db.conn.execute(
        """
        SELECT old_value, new_value, delta, reason
        FROM army_logs
        WHERE army_id = 'fujian_navy' AND field = 'morale'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert morale_log is not None
    assert morale_log["old_value"] == "80"
    assert morale_log["new_value"] == "72"
    assert morale_log["delta"] == -8
    assert isinstance(morale_log["reason"], str) and morale_log["reason"].strip()
    army_name = fresh_db.conn.execute(
        "SELECT name FROM armies WHERE id = 'fujian_navy'"
    ).fetchone()["name"]
    arrears_log = fresh_db.conn.execute(
        """
        SELECT delta
        FROM army_logs
        WHERE army_id = 'fujian_navy' AND field = 'province_pay_arrears'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert arrears_log is not None and arrears_log["delta"] == pytest.approx(10)
    summary = fresh_db.turn_army_summary(fresh_db.load_state().turn)
    # summary 出口：军名 + 稳定字段标签分别绑定 province_pay_arrears +10 / morale -8；
    # 抽象键不泄漏。不钉 reason 自由中文整句。
    assert f"{army_name}{ARMY_FIELD_LABELS['province_pay_arrears']}+10" in summary
    assert f"{army_name}{ARMY_FIELD_LABELS['morale']}-8" in summary
    assert "province_pay_arrears" not in summary


def test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills(fresh_db):
    state = fresh_db.load_state()
    earlier_armies = [
        row["id"]
        for row in fresh_db.conn.execute(
            "SELECT id FROM armies WHERE id != 'fujian_navy' ORDER BY id LIMIT 10"
        ).fetchall()
    ]
    assert len(earlier_armies) == 10
    for army_id in earlier_armies:
        fresh_db.conn.execute(
            """
            INSERT INTO army_logs
            (turn, year, period, army_id, field, old_value, new_value, delta, reason, actor)
            VALUES (?, ?, ?, ?, 'morale', '80', '80', 0, '中央军饷足额', '户部')
            """,
            (state.turn, state.year, state.period, army_id),
        )
    fresh_db.conn.execute(
        """
        INSERT INTO army_logs
        (turn, year, period, army_id, field, old_value, new_value, delta, reason, actor)
        VALUES (?, ?, ?, 'fujian_navy', 'morale', '80', '72', -8, '本月省源军饷分账', '户部')
        """,
        (state.turn, state.year, state.period),
    )
    fresh_db.conn.commit()

    army_name = fresh_db.conn.execute(
        "SELECT name FROM armies WHERE id = 'fujian_navy'"
    ).fetchone()["name"]
    summary = fresh_db.turn_army_summary(state.turn)

    # log cap 仍应优先露出非零 delta；钉军名+delta，不钉自由中文拼句。
    assert army_name in summary
    assert "-8" in summary


def test_armies_provision_empty_mutiny_status_flag(fresh_db):
    columns = {
        row["name"]: row
        for row in fresh_db.conn.execute("PRAGMA table_info(armies)").fetchall()
    }

    assert "mutiny_status" in columns
    assert columns["mutiny_status"]["dflt_value"] in ("''", '""')
    assert fresh_db.conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM armies
        WHERE COALESCE(mutiny_status, '') != ''
        """
    ).fetchone()["count"] == 0


def test_zero_due_province_army_morale_short_circuits(fresh_db):
    _write_settle(
        fresh_db,
        "fujian",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 0,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'fujian', province_pay_share = 1.0,
            central_pay_share = 0.0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0, morale = 80,
            manpower = 0, salary_rate = 10
        WHERE id = 'fujian_navy'
        """
    )
    fresh_db.conn.commit()

    fresh_db.settle_province_tick("fujian")

    row = fresh_db.conn.execute(
        """
        SELECT morale, arrears, province_pay_arrears, central_pay_arrears
        FROM armies WHERE id = 'fujian_navy'
        """
    ).fetchone()
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(0)
    assert row["morale"] == 80


def test_tusi_self_funded_army_skips_pay_morale_channel(fresh_db):
    _write_settle(
        fresh_db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 0,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, owner_power = 'ming',
            pay_source_region = '', province_pay_share = 0,
            central_pay_share = 0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0, morale = 80,
            manpower = 24000, salary_rate = 10
        WHERE id = 'southwest_tusi'
        """
    )
    fresh_db.conn.commit()

    fresh_db.settle_province_tick("shaanxi")

    row = fresh_db.conn.execute(
        "SELECT morale, arrears FROM armies WHERE id = 'southwest_tusi'"
    ).fetchone()
    assert row["arrears"] == pytest.approx(0)
    assert row["morale"] == 80


def test_army_pay_morale_formula_clamps_shortfall_and_old_arrears_gate():
    from ming_sim.flows import army_pay_morale_delta

    assert army_pay_morale_delta(0, 5, 0) == 0
    assert army_pay_morale_delta(10, 12, 0) == -8
    assert army_pay_morale_delta(10, 0, 0) == 2
    assert army_pay_morale_delta(10, 0, 3) == 0


def test_fixed_flows_cutover_uses_total_source_shortfall_for_mixed_army_morale(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 0
    db.save_state(state)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    _zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0
            )
        """
    )
    _write_settle(
        db,
        "shaanxi",
        {
            "st": {
                "省库库银": 0,
                "C_地方截留": 0,
                "C_中饱": 0,
                "C_漂没": 0,
                "C_eff损耗": 0,
                "民欠旧赋": 0,
                "军饷欠": 0,
                "官俸欠": 0,
                "宗禄欠": 0,
                "官民田": 0,
                "隐田": 0,
            },
            "p": {
                "正赋应征": 0,
                "三饷应征": 0,
                "火耗率": 0,
                "逋赋率": 0,
                "起运定额": 0,
                "拨付gross": 0,
                "中饱率": 0,
                "漂没率": 0,
                "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
            },
        },
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0, morale = 80,
            manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    db.conn.commit()

    flows_mod.apply_fixed_period_flows(db, state)

    row = db.conn.execute(
        """
        SELECT morale, arrears, province_pay_arrears, central_pay_arrears
        FROM armies WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert row["province_pay_arrears"] == pytest.approx(6.5)
    assert row["central_pay_arrears"] == pytest.approx(3.5)
    assert row["arrears"] == pytest.approx(10)
    assert row["morale"] == 72


def test_army_delta_arrears_splits_positive_and_rejects_negative_under_cutover(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="剧情加欠")
    before = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()

    changes = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"arrears": 10, "reason": "剧情加欠"}},
        commit=False,
    )

    after = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert after["province_pay_arrears"] == pytest.approx(before["province_pay_arrears"] + 6.5)
    assert after["central_pay_arrears"] == pytest.approx(before["central_pay_arrears"] + 3.5)
    assert after["arrears"] == pytest.approx(after["province_pay_arrears"] + after["central_pay_arrears"])

    rejected = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"arrears": -1, "reason": "无现金减欠"}},
        commit=False,
    )
    assert rejected and rejected[0]["rejected"] is True
    again = fresh_db.conn.execute(
        "SELECT * FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    assert again["arrears"] == pytest.approx(after["arrears"])


def test_army_delta_arrears_rejects_exempt_army_under_cutover(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="剧情加欠")
    before = fresh_db.conn.execute(
        "SELECT arrears FROM armies WHERE id = 'southwest_tusi'"
    ).fetchone()

    changes = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {"southwest_tusi": {"arrears": 10, "reason": "误记欠饷"}},
        commit=False,
    )

    after = fresh_db.conn.execute(
        "SELECT arrears FROM armies WHERE id = 'southwest_tusi'"
    ).fetchone()
    logs = fresh_db.conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM army_logs
        WHERE army_id = 'southwest_tusi' AND field = 'arrears' AND reason = '误记欠饷'
        """
    ).fetchone()
    assert changes and changes[0]["rejected"] is True
    assert changes[0].get("category") == "invalid_enum"
    assert after["arrears"] == pytest.approx(before["arrears"])
    assert logs["count"] == 0


def test_army_delta_arrears_reconciles_pay_source_container_immediately(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="剧情加欠")

    fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"arrears": 10, "reason": "剧情加欠"}},
        commit=False,
    )

    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )


def test_pay_source_conservation_rejects_per_army_derived_arrears_drift(fresh_db):
    """旧 arrears 标量只是双累加器合计，不能被 offset poison 抵消总和。"""
    fresh_db.conn.execute(
        "UPDATE armies SET arrears = arrears + 10 WHERE id = 'shaanxi_army'"
    )
    fresh_db.conn.execute(
        "UPDATE armies SET arrears = arrears - 10 WHERE id = 'guanning'"
    )

    with pytest.raises(ValueError, match="军饷欠派生合计"):
        fresh_db.assert_army_pay_source_container_conservation()


def test_army_delta_manpower_reconciles_pay_source_due_immediately(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="募兵")
    before_due = _read_settle(fresh_db, "shaanxi")["p"]["Due"]["军饷"]

    fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"manpower": 10000, "reason": "募兵"}},
        commit=False,
    )

    settle = _read_settle(fresh_db, "shaanxi")
    assert settle["p"]["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shaanxi"))
    assert settle["p"]["Due"]["军饷"] > before_due


def test_army_delta_owner_power_to_ming_requires_same_delta_pay_source(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="招抚")
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET owner_power = 'houjin', pay_source_region = '',
            province_pay_share = 0, central_pay_share = 0,
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        WHERE id = 'shaanxi_army'
        """
    )
    fresh_db.conn.commit()

    rejected = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"owner_power": "ming"}},
        commit=False,
    )

    row = fresh_db.conn.execute("SELECT * FROM armies WHERE id = 'shaanxi_army'").fetchone()
    assert rejected and rejected[0]["rejected"] is True
    assert "pay_source_region" in rejected[0]["reason"]
    assert row["owner_power"] == "houjin"

    changes = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {
            "shaanxi_army": {
                "owner_power": "ming",
                "pay_source_region": "shaanxi",
                "province_pay_share": 0.65,
                "central_pay_share": 0.35,
            }
        },
        commit=False,
    )

    row = fresh_db.conn.execute("SELECT * FROM armies WHERE id = 'shaanxi_army'").fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert row["owner_power"] == "ming"
    assert row["pay_source_region"] == "shaanxi"
    assert row["province_pay_share"] == pytest.approx(0.65)
    assert row["central_pay_share"] == pytest.approx(0.35)
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )


def test_army_delta_rejects_unknown_owner_power_without_clearing_arrears(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="幻觉易主")
    before = fresh_db.conn.execute(
        """
        SELECT owner_power, pay_source_region, province_pay_share, central_pay_share,
               province_pay_arrears, central_pay_arrears, arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()

    rejected = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {"shaanxi_army": {"owner_power": "__missing_power__"}},
        commit=False,
    )

    after = fresh_db.conn.execute(
        """
        SELECT owner_power, pay_source_region, province_pay_share, central_pay_share,
               province_pay_arrears, central_pay_arrears, arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert rejected and rejected[0]["rejected"] is True
    assert rejected[0]["category"] == "hallucinated_id"
    assert dict(after) == dict(before)


def test_army_delta_rejects_pay_source_without_ming_settle_substrate(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="移饷源")
    fresh_db.conn.execute(
        "UPDATE regions SET controlled_by = 'ming', fiscal = '{}' WHERE id = 'taiwan'"
    )
    fresh_db.conn.commit()

    rejected = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {
            "shaanxi_army": {
                "pay_source_region": "taiwan",
                "province_pay_share": 1.0,
                "central_pay_share": 0.0,
            }
        },
        commit=False,
    )

    row = fresh_db.conn.execute(
        "SELECT pay_source_region FROM armies WHERE id = 'shaanxi_army'"
    ).fetchone()
    assert rejected and rejected[0]["rejected"] is True
    assert "pay_source_region" in rejected[0]["reason"]
    assert row["pay_source_region"] == "shaanxi"


def test_army_delta_owner_power_from_ming_clears_pay_source_arrears(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="陷没")
    before = _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"]
    before_due = _read_settle(fresh_db, "shaanxi")["p"]["Due"]["军饷"]
    assert before > 0
    assert before_due > 0

    changes = fresh_db.apply_army_deltas(
        state, event, None, "测试", {"shaanxi_army": {"owner_power": "houjin"}},
        commit=False,
    )

    row = fresh_db.conn.execute("SELECT * FROM armies WHERE id = 'shaanxi_army'").fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert row["owner_power"] == "houjin"
    assert row["pay_source_region"] == ""
    assert row["province_pay_share"] == pytest.approx(0)
    assert row["central_pay_share"] == pytest.approx(0)
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(0)
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )
    logs = fresh_db.conn.execute(
        """
        SELECT id, field, old_value, new_value, delta, reason
        FROM army_logs
        WHERE army_id = 'shaanxi_army'
          AND field IN ('arrears', 'owner_power')
        ORDER BY id DESC
        LIMIT 6
        """
    ).fetchall()
    writeoff = next(
        (log for log in logs if log["field"] == "arrears" and "核销" in log["reason"]),
        None,
    )
    owner_log = next((log for log in logs if log["field"] == "owner_power"), None)
    assert writeoff is not None
    assert owner_log is not None
    assert writeoff["id"] < owner_log["id"]
    assert float(writeoff["old_value"]) > 0
    assert float(writeoff["new_value"]) == pytest.approx(0)
    assert writeoff["delta"] < 0
    settle = _read_settle(fresh_db, "shaanxi")
    assert settle["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )
    assert settle["st"]["军饷欠"] < before
    assert settle["p"]["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shaanxi"))
    assert settle["p"]["Due"]["军饷"] < before_due


@pytest.mark.parametrize("field", ["self_funded_pay", "is_tusi"])
def test_army_delta_rejects_ming_exempt_flag_before_pay_arrears_writeoff(fresh_db, field):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="改隶")
    before = fresh_db.conn.execute(
        """
        SELECT owner_power, pay_source_region, province_pay_share, central_pay_share,
               is_tusi, self_funded_pay, province_pay_arrears, central_pay_arrears,
               arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert before["owner_power"] == "ming"
    assert before["arrears"] > 0

    rejected = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {"shaanxi_army": {field: 1}},
        commit=False,
    )

    after = fresh_db.conn.execute(
        """
        SELECT owner_power, pay_source_region, province_pay_share, central_pay_share,
               is_tusi, self_funded_pay, province_pay_arrears, central_pay_arrears,
               arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert rejected and rejected[0]["rejected"] is True
    assert rejected[0].get("category") == "invalid_enum"
    assert dict(after) == dict(before)
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )


def test_economy_pay_arrears_from_central_account_splits_by_current_debt_ratio(fresh_db):
    from ming_sim.flows import _apply_economy_list

    state = fresh_db.load_state()
    before_province = _province_pay_arrears(fresh_db, "shaanxi")
    before_army = fresh_db.conn.execute(
        """
        SELECT province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert before_province > 0
    assert before_army["province_pay_arrears"] > 0
    assert before_army["central_pay_arrears"] > 5
    before_total = (
        before_army["province_pay_arrears"] + before_army["central_pay_arrears"]
    )
    expected_province_pay = 5 * before_army["province_pay_arrears"] / before_total
    expected_central_pay = 5 * before_army["central_pay_arrears"] / before_total

    applied = _apply_economy_list(
        fresh_db,
        state,
        [{
            "account": "国库",
            "delta": -5,
            "category": "补饷",
            "reason": "测试补饷",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": "shaanxi_army",
        }],
        commit=False,
    )

    after_army = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()

    assert applied == [{
        "account": "国库", "delta": -5, "reason": "测试补饷",
        "origin_ref": "", "beyond_intent": False, "applied": True,
    }]
    assert after_army["province_pay_arrears"] == pytest.approx(
        before_army["province_pay_arrears"] - expected_province_pay, abs=1e-6
    )
    assert after_army["central_pay_arrears"] == pytest.approx(
        before_army["central_pay_arrears"] - expected_central_pay, abs=1e-6
    )
    assert after_army["arrears"] == pytest.approx(
        after_army["province_pay_arrears"] + after_army["central_pay_arrears"]
    )
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )
    assert _province_pay_arrears(fresh_db, "shaanxi") == pytest.approx(
        before_province - expected_province_pay, abs=1e-6
    )
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )


def test_economy_pay_arrears_from_central_account_can_repay_pure_province_source_army(fresh_db):
    from ming_sim.flows import _apply_economy_list

    state = fresh_db.load_state()
    before_province = _province_pay_arrears(fresh_db, "fujian")
    before_army = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'fujian_navy'
        """
    ).fetchone()
    assert before_army["province_pay_arrears"] > 3
    assert before_army["central_pay_arrears"] == pytest.approx(0)

    applied = _apply_economy_list(
        fresh_db,
        state,
        [{
            "account": "国库",
            "delta": -3,
            "category": "补饷",
            "reason": "测试纯省源补饷",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": "fujian_navy",
        }],
        commit=False,
    )

    after_army = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'fujian_navy'
        """
    ).fetchone()

    assert applied == [{
        "account": "国库", "delta": -3, "reason": "测试纯省源补饷",
        "origin_ref": "", "beyond_intent": False, "applied": True,
    }]
    assert after_army["province_pay_arrears"] == pytest.approx(
        before_army["province_pay_arrears"] - 3, abs=1e-6
    )
    assert after_army["central_pay_arrears"] == pytest.approx(0)
    assert after_army["arrears"] == pytest.approx(before_army["arrears"] - 3, abs=1e-6)
    assert _read_settle(fresh_db, "fujian")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "fujian"), abs=1e-6
    )
    assert _province_pay_arrears(fresh_db, "fujian") == pytest.approx(
        before_province - 3, abs=1e-6
    )


def test_economy_pay_arrears_preserves_fractional_pay_source_tail(fresh_db):
    from ming_sim.flows import _apply_economy_list

    state = fresh_db.load_state()
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET province_pay_arrears = 0.3,
            central_pay_arrears = 0.2,
            arrears = 0.5
        WHERE id = 'shaanxi_army'
        """
    )
    fresh_db._reconcile_army_pay_source_region_container("shaanxi")

    applied = _apply_economy_list(
        fresh_db,
        state,
        [{
            "account": "国库",
            "delta": -1,
            "category": "补饷",
            "reason": "测试小数欠饷补齐",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": "shaanxi_army",
        }],
        commit=False,
    )

    row = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    ledger_row = fresh_db.conn.execute(
        """
        SELECT delta
        FROM economy_ledger
        WHERE purpose = '补饷' AND target_kind = 'army' AND target_id = 'shaanxi_army'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    assert len(applied) == 1
    assert applied[0]["account"] == "国库"
    assert applied[0]["delta"] == 0
    assert isinstance(applied[0].get("reason"), str) and applied[0]["reason"].strip()
    assert ledger_row is None
    assert row["province_pay_arrears"] == pytest.approx(0.3)
    assert row["central_pay_arrears"] == pytest.approx(0.2)
    assert row["arrears"] == pytest.approx(0.5)
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )


def test_economy_pay_arrears_clamps_integer_spend_and_preserves_tail(fresh_db):
    from ming_sim.flows import _apply_economy_list

    state = fresh_db.load_state()
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET province_pay_arrears = 2.1,
            central_pay_arrears = 1.4,
            arrears = 3.5
        WHERE id = 'shaanxi_army'
        """
    )
    fresh_db._reconcile_army_pay_source_region_container("shaanxi")

    applied = _apply_economy_list(
        fresh_db,
        state,
        [{
            "account": "国库",
            "delta": -3,
            "category": "补饷",
            "reason": "测试小数欠饷不超扣",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": "shaanxi_army",
        }],
        commit=False,
    )

    row = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    ledger_row = fresh_db.conn.execute(
        """
        SELECT delta
        FROM economy_ledger
        WHERE purpose = '补饷' AND target_kind = 'army' AND target_id = 'shaanxi_army'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    assert applied == [{
        "account": "国库", "delta": -3, "reason": "测试小数欠饷不超扣",
        "origin_ref": "", "beyond_intent": False, "applied": True,
    }]
    assert ledger_row["delta"] == -3
    assert row["province_pay_arrears"] == pytest.approx(0.3)
    assert row["central_pay_arrears"] == pytest.approx(0.2)
    assert row["arrears"] == pytest.approx(0.5)
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )


@pytest.mark.parametrize(
    "move",
    [
        {
            "account": "国库",
            "delta": -5,
            "category": "补饷",
            "reason": "缺目标",
            "purpose": "补饷",
        },
        {
            "account": "国库",
            "delta": -5,
            "category": "补饷",
            "reason": "错目标",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": "__missing_army__",
        },
    ],
)
def test_economy_pay_arrears_rejects_missing_or_unknown_target_without_repaying_other_armies(
    fresh_db, move
):
    from ming_sim.flows import _apply_economy_list

    state = fresh_db.load_state()
    before_treasury = state.metrics["国库"]
    before_army = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    before_province = _province_pay_arrears(fresh_db, "shaanxi")

    applied = _apply_economy_list(fresh_db, state, [move], commit=False)

    after_army = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    ledger_row = fresh_db.conn.execute(
        """
        SELECT 1 FROM economy_ledger
        WHERE purpose = '补饷'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert applied and applied[0]["rejected"] is True
    assert applied[0]["category"] == "missing_ref"
    assert state.metrics["国库"] == before_treasury
    assert ledger_row is None
    assert dict(after_army) == dict(before_army)
    assert _province_pay_arrears(fresh_db, "shaanxi") == pytest.approx(before_province)


def test_manpower_zero_writeoffs_pay_source_arrears_before_retiring_army(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="陕西边军覆没")
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET manpower = 1000,
            province_pay_arrears = 6,
            central_pay_arrears = 4,
            arrears = 10
        WHERE id = 'shaanxi_army'
        """
    )
    fresh_db._reconcile_army_pay_source_region_container("shaanxi")
    fresh_db._reconcile_central_army_pay_arrears_container()

    changes = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {"shaanxi_army": {"manpower": -9999, "reason": "全军覆没"}},
        commit=False,
    )

    row = fresh_db.conn.execute(
        """
        SELECT manpower, arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    writeoff = fresh_db.conn.execute(
        """
        SELECT *
        FROM army_logs
        WHERE army_id = 'shaanxi_army'
          AND field = 'arrears'
          AND reason LIKE '%核销%'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    assert any(change["field"] == "manpower" for change in changes)
    assert row["manpower"] == 0
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(0)
    assert writeoff is not None
    assert float(writeoff["old_value"]) == pytest.approx(10)
    assert float(writeoff["new_value"]) == pytest.approx(0)
    assert writeoff["delta"] == pytest.approx(-10)
    assert _read_settle(fresh_db, "shaanxi")["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )


def test_manpower_zero_then_arrears_delta_does_not_resurrect_writeoff_debt(fresh_db):
    state = fresh_db.load_state()
    event = SimpleNamespace(id="test", title="陕西边军覆没")
    fresh_db.conn.execute(
        """
        UPDATE armies
        SET manpower = 1000,
            province_pay_arrears = 6,
            central_pay_arrears = 4,
            arrears = 10
        WHERE id = 'shaanxi_army'
        """
    )
    fresh_db._reconcile_army_pay_source_region_container("shaanxi")
    fresh_db._reconcile_central_army_pay_arrears_container()

    changes = fresh_db.apply_army_deltas(
        state,
        event,
        None,
        "测试",
        {"shaanxi_army": {"manpower": -9999, "arrears": 10, "reason": "全军覆没后误加欠饷"}},
        commit=False,
    )

    row = fresh_db.conn.execute(
        """
        SELECT manpower, arrears, province_pay_arrears, central_pay_arrears
        FROM armies
        WHERE id = 'shaanxi_army'
        """
    ).fetchone()
    assert row["manpower"] == 0
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(0)
    assert not any(change["field"] == "arrears" and not change.get("rejected") for change in changes)
    assert _province_pay_arrears(fresh_db, "shaanxi") == pytest.approx(0)
    assert fresh_db.get_central_army_pay_arrears_container() == pytest.approx(
        _non_self_funded_pay_arrears(fresh_db)[1], abs=1e-6
    )


def test_new_ming_army_requires_valid_pay_source_under_cutover(fresh_db):
    state = fresh_db.load_state()

    rejected = fresh_db.create_armies_from_extraction(state, [{
        "id": "no_pay_source",
        "name": "无饷源新军",
        "manpower": 1000,
        "owner_power": "ming",
    }], commit=False)

    assert rejected and rejected[0]["rejected"] is True
    assert "pay_source_region" in rejected[0]["reason"]
    assert fresh_db.conn.execute(
        "SELECT 1 FROM armies WHERE id = 'no_pay_source'"
    ).fetchone() is None


def test_new_ming_army_rejects_non_ming_pay_source_region(fresh_db):
    state = fresh_db.load_state()
    non_ming_power = fresh_db.conn.execute(
        "SELECT id FROM powers WHERE id <> 'ming' LIMIT 1"
    ).fetchone()[0]
    fresh_db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = 'shaanxi'", (non_ming_power,)
    )
    fresh_db.conn.commit()

    rejected = fresh_db.create_armies_from_extraction(state, [{
        "id": "rebel_source_army",
        "name": "逆境索饷军",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }], commit=False)

    assert rejected and rejected[0]["rejected"] is True
    assert "pay_source_region" in rejected[0]["reason"]
    assert fresh_db.conn.execute(
        "SELECT 1 FROM armies WHERE id = 'rebel_source_army'"
    ).fetchone() is None


def test_new_ming_army_stores_pay_source_columns_under_cutover(fresh_db):
    state = fresh_db.load_state()
    before_due = _read_settle(fresh_db, "shaanxi")["p"]["Due"]["军饷"]

    created = fresh_db.create_armies_from_extraction(state, [{
        "id": "valid_pay_source",
        "name": "有饷源新军",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "shaanxi",
        "province_pay_share": 0.65,
        "central_pay_share": 0.35,
    }], commit=False)

    assert created and created[0].get("created") is True
    row = fresh_db.conn.execute(
        """
        SELECT arrears, province_pay_arrears, central_pay_arrears,
               pay_source_region, province_pay_share, central_pay_share
        FROM armies WHERE id = 'valid_pay_source'
        """
    ).fetchone()
    assert row["pay_source_region"] == "shaanxi"
    assert row["province_pay_share"] == pytest.approx(0.65)
    assert row["central_pay_share"] == pytest.approx(0.35)
    assert row["province_pay_arrears"] == pytest.approx(0)
    assert row["central_pay_arrears"] == pytest.approx(0)
    assert row["arrears"] == pytest.approx(0)
    settle = _read_settle(fresh_db, "shaanxi")
    assert settle["st"]["军饷欠"] == pytest.approx(
        _province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6
    )
    assert settle["p"]["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shaanxi"))
    assert settle["p"]["Due"]["军饷"] > before_due


def test_new_ming_army_rejects_initial_arrears_under_cutover(fresh_db):
    state = fresh_db.load_state()

    rejected = fresh_db.create_armies_from_extraction(state, [{
        "id": "arrears_new_army",
        "name": "带欠饷新军",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "shaanxi",
        "province_pay_share": 0.65,
        "central_pay_share": 0.35,
        "arrears": 10,
    }], commit=False)

    assert rejected and rejected[0]["rejected"] is True
    assert rejected[0].get("category") == "invalid_enum"
    assert fresh_db.conn.execute(
        "SELECT 1 FROM armies WHERE id = 'arrears_new_army'"
    ).fetchone() is None


@pytest.mark.parametrize("bad_defaults", [None, [], "not-a-dict"])
def test_region_loader_rejects_bad_shared_settle_meta_defaults_container(monkeypatch, bad_defaults):
    fake_regions = {
        "settle_meta_defaults": bad_defaults,
        "regions": [_region_with_settle({"st": {}, "p": {}})],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match="content/regions.json.settle_meta_defaults"):
        content_mod.load_region_content()


def test_region_loader_rejects_bad_plain_settle_meta(monkeypatch):
    fake_regions = {
        "regions": [_region_with_settle({"_meta": [], "st": {}, "p": {}})],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match="_meta 必须是 JSON 对象"):
        content_mod.load_region_content()


@pytest.mark.parametrize(
    "settle,defaults,error",
    [
        (
            {"_meta_defaults": "", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta_defaults 必须是非空字符串",
        ),
        (
            {"_meta_defaults": "missing_group", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta_defaults 指向未知默认组：missing_group",
        ),
        (
            {"_meta_defaults": "ming_province", "_meta": [], "st": {}, "p": {}},
            {"ming_province": {}},
            "_meta 必须是 JSON 对象",
        ),
        (
            {"_meta_defaults": "ming_province", "_meta": {}, "st": {}, "p": {}},
            {"ming_province": []},
            "settle_meta_defaults.ming_province 必须是 JSON 对象",
        ),
    ],
)
def test_region_loader_rejects_bad_settle_meta_defaults(monkeypatch, settle, defaults, error):
    fake_regions = {
        "settle_meta_defaults": defaults,
        "regions": [_region_with_settle(settle)],
    }
    monkeypatch.setattr(content_mod, "load_json_asset", lambda name: fake_regions)

    with pytest.raises(SystemExit, match=error):
        content_mod.load_region_content()


ZHONGYUAN_JINGSHI_GOLDEN = {
    "beizhili": {
        "省库库银": 9.0,
        "C_地方截留": 0.861759,
        "民欠旧赋": 2.308283,
        "军饷欠": 0,
        "官俸欠": 0,
        "宗禄欠": 0,
    },
    "shandong": {
        "省库库银": 3.72375,
        "C_地方截留": 2.2542,
        "民欠旧赋": 7.58625,
        "军饷欠": 0,
        "官俸欠": 0,
        "宗禄欠": 0,
    },
    "henan": {
        "省库库银": 0,
        "C_地方截留": 2.31788,
        "民欠旧赋": 8.58474,
        "军饷欠": 0,
        "官俸欠": 0,
        "宗禄欠": 16.15,
    },
}


REGULAR_PROVINCE_FIRST_TICK_GOLDEN = {
    "beizhili": {
        "实征": 5.385992, "起运到京": 5.385992, "火耗实收": 0.861759,
        "省库库银": 9.0, "C_地方截留": 0.861759, "民欠旧赋": 2.308283,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "nanzhili": {
        "实征": 29.48187, "起运到京": 14.7235, "火耗实收": 4.127462,
        "省库库银": 2.75837, "C_地方截留": 4.127462, "民欠旧赋": 6.47163,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "shandong": {
        "实征": 14.08875, "起运到京": 8.175, "火耗实收": 2.2542,
        "省库库银": 3.72375, "C_地方截留": 2.2542, "民欠旧赋": 7.58625,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "shanxi": {
        "实征": 13.268416, "起运到京": 9.667061, "火耗实收": 2.255631,
        "省库库银": 0, "C_地方截留": 2.255631, "民欠旧赋": 7.144531,
        "军饷欠": 16.5, "官俸欠": 0, "宗禄欠": 6.888645,
    },
    "henan": {
        "实征": 12.87711, "起运到京": 12.87711, "火耗实收": 2.31788,
        "省库库银": 0, "C_地方截留": 2.31788, "民欠旧赋": 8.58474,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 16.15,
    },
    "shaanxi": {
        "实征": 3.989261, "起运到京": 2.196901, "火耗实收": 0.718067,
        "省库库银": 0, "C_地方截留": 0.718067, "民欠旧赋": 3.263941,
        "军饷欠": 16.25, "官俸欠": 1.107641, "宗禄欠": 4.07,
    },
    "zhejiang": {
        "实征": 21.202, "起运到京": 7.0325, "火耗实收": 2.75626,
        "省库库银": 11.1695, "C_地方截留": 2.75626, "民欠旧赋": 5.3005,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "jiangxi": {
        "实征": 18.75675, "起运到京": 7.709, "火耗实收": 2.813513,
        "省库库银": 7.25775, "C_地方截留": 2.813513, "民欠旧赋": 6.25225,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "huguang": {
        "实征": 39.48477, "起运到京": 18.5315, "火耗实收": 5.527868,
        "省库库银": 15.32327, "C_地方截留": 5.527868, "民欠旧赋": 11.13673,
        "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0,
    },
    "sichuan": {
        "实征": 2.031373, "起运到京": 1.853908, "火耗实收": 0.32502,
        "省库库银": 0, "C_地方截留": 0.32502, "民欠旧赋": 1.245035,
        "军饷欠": 0, "官俸欠": 0.522535, "宗禄欠": 0.8,
    },
    "fujian": {
        "实征": 2.211039, "起运到京": 1.752788, "火耗实收": 0.353766,
        "省库库银": 0, "C_地方截留": 0.353766, "民欠旧赋": 0.859849,
        "军饷欠": 6.541749, "官俸欠": 1.2, "宗禄欠": 0,
    },
    "guangdong": {
        "实征": 2.914652, "起运到京": 2.759789, "火耗实收": 0.466344,
        "省库库银": 0, "C_地方截留": 0.466344, "民欠旧赋": 1.249137,
        "军饷欠": 5.845137, "官俸欠": 1.1, "宗禄欠": 0,
    },
    "guangxi": {
        "实征": 0.747128, "起运到京": 0.705156, "火耗实收": 0.134483,
        "省库库银": 0, "C_地方截留": 0.134483, "民欠旧赋": 0.747128,
        "军饷欠": 0, "官俸欠": 0.158028, "宗禄欠": 0.72,
    },
    "yunnan": {
        "实征": 0.226695, "起运到京": 0.134952, "火耗实收": 0.040805,
        "省库库银": 0, "C_地方截留": 0.040805, "民欠旧赋": 0.209257,
        "军饷欠": 0, "官俸欠": 0.008257, "宗禄欠": 0,
    },
    "guizhou": {
        "实征": 0.065092, "起运到京": 0.03875, "火耗实收": 0.011717,
        "省库库银": 0, "C_地方截留": 0.011717, "民欠旧赋": 0.079557,
        "军饷欠": 0, "官俸欠": 0.173657, "宗禄欠": 0,
    },
}


@pytest.mark.parametrize(
    "region_id,expected",
    REGULAR_PROVINCE_FIRST_TICK_GOLDEN.items(),
    ids=list(REGULAR_PROVINCE_FIRST_TICK_GOLDEN),
)
def test_all_15_regular_provinces_first_tick_golden(region_id, expected, fresh_db):
    """#585 capstone: 全 15 布政司一手核 seed 的首 tick 末态硬锚。"""
    assert len(REGULAR_PROVINCE_FIRST_TICK_GOLDEN) == 15
    settle = _read_settle(fresh_db, region_id)

    result = settle_tick(settle["st"], settle["p"], [])

    for key, want in expected.items():
        got = (
            result.breakdown[key]
            if key in {"实征", "起运到京", "火耗实收"}
            else result.new_st[key]
        )
        assert math.isclose(
            got,
            want,
            rel_tol=0,
            abs_tol=1e-3,
        ), f"{region_id} {key}: {got} != {want}"


ZHONGYUAN_JINGSHI_PRIMARY_SOURCE = {
    "beizhili": {
        "guan_min_tian": 365,
        "settle_land": 4925.7,
        "huang_tian": 184,
        "正赋应征": 4.0,
        "三饷应征": 3.6942749999999993,
        "起运定额": 8.894275,
        "verified": {"官民田", "正赋应征", "起运定额"},
    },
    "shandong": {
        "guan_min_tian": 490,
        "settle_land": 4900,
        "huang_tian": 0,
        "正赋应征": 18,
        "三饷应征": 3.6749999999999994,
        "起运定额": 8.175,
        "verified": set(),
    },
    "henan": {
        "guan_min_tian": 380,
        "settle_land": 7415.8,
        "huang_tian": 0,
        "正赋应征": 15.9,
        "三饷应征": 5.56185,
        "起运定额": 15.66185,
        "verified": {"官民田", "正赋应征", "起运定额"},
    },
}


@pytest.mark.parametrize("region_id,expected", ZHONGYUAN_JINGSHI_PRIMARY_SOURCE.items())
def test_zhongyuan_jingshi_primary_source_refinement(region_id, expected, fresh_db):
    row = fresh_db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = ?", (region_id,)
    ).fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    settle = fiscal["settle"]
    p = settle["p"]
    st = settle["st"]
    meta = settle["_meta"]

    assert fiscal["guan_min_tian"] == pytest.approx(expected["guan_min_tian"])
    assert fiscal["huang_tian"] == pytest.approx(expected["huang_tian"])
    assert st["官民田"] == pytest.approx(expected["settle_land"], abs=0.1)
    assert p["正赋应征"] == pytest.approx(expected["正赋应征"], abs=0.05)
    assert p["三饷应征"] == pytest.approx(expected["三饷应征"], abs=0.05)
    assert p["起运定额"] == pytest.approx(expected["起运定额"], abs=0.05)
    # 吸收原 weak valid tracer：中原开局只 seed 辽饷（域枚举，非自由文案）
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]

    provisional = set(meta["provisional"])
    for field in expected["verified"]:
        assert field not in provisional

    if region_id == "shandong":
        assert {"官民田", "正赋应征", "起运定额"} <= provisional
        # typed 缺卷：notes schema 键 + 无 structured land-tax source；域字段名由 provisional 锁定
        assert "山东卷六缺口" in meta["notes"]
        assert not isinstance(meta.get("source"), dict)
        assert not isinstance(meta.get("source_grain"), dict)
    else:
        # 该外部义务在当前生产形态下无 typed 载体（beizhili/henan meta 无 source/
        # source_grain/primary_source；田赋来源仅 notes 自由文本；不得拿
        # royal_stipends_source 冒充），按清单不改生产原则保留原断言。
        source_notes = meta["notes"]["一手核"]
        assert "《万历会计录》" in source_notes
        assert "本色" in source_notes
        assert "扫描图核验" in meta["notes"]
        assert "识典扫描图" in meta["notes"]["扫描图核验"]

    if region_id in {"beizhili", "shandong", "henan"}:
        assert p["三饷应征"] == pytest.approx(
            st["官民田"] * 0.009 / 12,
            abs=0.05,
        )


SOUTH_SOUTHWEST_SEEDS = {
    "sichuan": {
        "zh": "四川", "官民田": 1348.276723, "正赋应征": 2.2652, "三饷应征": 1.01120754225,
        "正赋起运基线": 0.8427, "起运定额": 1.85390754225, "军饷": 5.0, "宗禄": 0.8,
        "source_grain": {
            "source": "《万历会计录》卷十「四川布政司田赋」",
            "taxable_land_qing": 134827.6723,
            "assessed_grain_shi": 1028545.133,
            "transport_grain_shi": 404497.2409,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.32502, "民欠旧赋": 1.245035, "军饷欠": 8.322535,
                       "官俸欠": 1.2, "宗禄欠": 0.8},
    },
    "fujian": {
        "zh": "福建", "官民田": 1342.25067, "正赋应征": 2.0642, "三饷应征": 1.0066880024999998,
        "正赋起运基线": 0.7461, "起运定额": 1.7527880024999998, "军饷": 4.0, "宗禄": 0,
        "source_grain": {
            "source": "《万历会计录》卷五「福建布政司田赋」",
            "taxable_land_qing": 134225.067,
            "assessed_grain_shi": 883121.6379,
            "transport_grain_shi": 314000.0,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.353766, "民欠旧赋": 0.859849, "军饷欠": 5.541749,
                       "官俸欠": 1.2, "宗禄欠": 0},
    },
    "guangdong": {
        "zh": "广东", "官民田": 2568.651366, "正赋应征": 2.2373, "三饷应征": 1.9264885244999999,
        "正赋起运基线": 0.8333, "起运定额": 2.7597885245, "军饷": 3.6, "宗禄": 0,
        "source_grain": {
            "source": "《万历会计录》卷十一「广东布政司田赋」",
            "taxable_land_qing": 256865.1366,
            "assessed_grain_shi": 999747.6116,
            "transport_grain_shi": 400000.0,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.466344, "民欠旧赋": 1.249137, "军饷欠": 5.445137,
                       "官俸欠": 1.1, "宗禄欠": 0},
    },
    "guangxi": {
        "zh": "广西", "官民田": 940.20748, "正赋应征": 0.7891, "三饷应征": 0.7051556099999999,
        "正赋起运基线": 0.0, "起运定额": 0.7051556099999999, "军饷": 2.2, "宗禄": 0.72,
        "source_grain": {
            "source": "《万历会计录》卷十二「广西布政司田赋」",
            "taxable_land_qing": 94020.748,
            "assessed_grain_shi": 373088.3344,
            "transport_grain_shi": 0.0,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.134483, "民欠旧赋": 0.747128, "军饷欠": 2.858028,
                       "官俸欠": 0.5, "宗禄欠": 0.72},
    },
    "yunnan": {
        "zh": "云南", "官民田": 179.93588, "正赋应征": 0.3010, "三饷应征": 0.13495190999999998,
        "正赋起运基线": 0.0, "起运定额": 0.13495190999999998, "军饷": 1.8, "宗禄": 0,
        "source_grain": {
            "source": "《万历会计录》卷十三「云南布政司田赋」",
            "taxable_land_qing": 17993.588,
            "assessed_grain_shi": 142690.2976,
            "transport_grain_shi": 0.0,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.040805, "民欠旧赋": 0.209257, "军饷欠": 2.208257,
                       "官俸欠": 0.5, "宗禄欠": 0},
    },
    "guizhou": {
        "zh": "贵州", "官民田": 51.66663, "正赋应征": 0.1059, "三饷应征": 0.03874997249999999,
        "正赋起运基线": 0.0, "起运定额": 0.03874997249999999, "军饷": 1.6, "宗禄": 0,
        "source_grain": {
            "source": "《万历会计录》卷十四「贵州布政司田赋」",
            "taxable_land_qing": 5166.663,
            "assessed_grain_shi": 50808.5896,
            "transport_grain_shi": 0.0,
        },
        "first_tick": {"省库库银": 0, "C_地方截留": 0.011717, "民欠旧赋": 0.079557, "军饷欠": 2.173657,
                       "官俸欠": 0.4, "宗禄欠": 0},
    },
}


@pytest.mark.parametrize("region_id,expected", SOUTH_SOUTHWEST_SEEDS.items(), ids=list(SOUTH_SOUTHWEST_SEEDS))
def test_south_southwest_seeds_have_valid_historical_settle_substrate(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    assert isinstance(settle, dict), f"{expected['zh']} fiscal 缺 settle 基座"
    assert isinstance(settle.get("st"), dict) and isinstance(settle.get("p"), dict), \
        f"{expected['zh']} settle 基座须含 st + p"

    st = settle["st"]
    assert st["官民田"] == pytest.approx(expected["官民田"])
    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(expected["正赋应征"])
    assert p["三饷应征"] == pytest.approx(expected["三饷应征"])
    assert p["三饷应征"] == pytest.approx(st["官民田"] * 0.009 / 12)
    assert p["起运定额"] == pytest.approx(expected["起运定额"])
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, region_id))
    assert p["Due"]["宗禄"] == pytest.approx(expected["宗禄"])
    assert p["Due"]["赈济"] == 0
    assert p["三饷应征"] > 0, f"{expected['zh']} 开局须 seed 辽饷"
    assert p["起运定额"] >= p["三饷应征"], f"{expected['zh']} 辽饷应可全额起运"
    assert "salt_tax" not in p and "commerce_tax" not in p, "盐税/商税不进 settle substrate"

    meta = settle["_meta"]
    assert "辽饷" in meta["levies"]["seeded"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]
    assert "salt_tax" in meta["excluded_from_settle"]
    assert "commerce_tax" in meta["excluded_from_settle"]
    assert meta["正赋起运基线"] == pytest.approx(expected["正赋起运基线"])
    assert p["起运定额"] == pytest.approx(meta["正赋起运基线"] + p["三饷应征"])
    source_grain = meta["source_grain"]
    for key, value in expected["source_grain"].items():
        if isinstance(value, (int, float)):
            assert source_grain[key] == pytest.approx(value)
        else:
            assert source_grain[key] == value
    assert settle["st"]["官民田"] == pytest.approx(
        source_grain["taxable_land_qing"] / 100,
        abs=1e-9,
    )
    assert source_grain["scan_checked"] is True
    assert isinstance(source_grain.get("ocr_status"), str) and source_grain["ocr_status"].strip()
    conversion = source_grain["conversion"]
    assert "official_anchor" in conversion
    assert conversion["assessed_formula"] == (
        "assessed_grain_shi * assessed_silver_liang_per_stone / 10000 / 12"
    )
    assert conversion["transport_formula"] == (
        "transport_grain_shi * transport_silver_liang_per_stone / 10000 / 12"
    )
    assert p["正赋应征"] == pytest.approx(
        source_grain["assessed_grain_shi"]
        * conversion["assessed_silver_liang_per_stone"]
        / 10000
        / 12,
        abs=0.0001,
    )
    assert meta["正赋起运基线"] == pytest.approx(
        source_grain["transport_grain_shi"]
        * conversion["transport_silver_liang_per_stone"]
        / 10000
        / 12,
        abs=0.0001,
    )
    assert "官民田" not in meta["provisional"]
    assert "起运定额" not in meta["provisional"]
    res = settle_tick(settle["st"], p, [])
    assert res.new_st["省库库银"] is not None


@pytest.mark.parametrize("region_id,expected", SOUTH_SOUTHWEST_SEEDS.items(), ids=list(SOUTH_SOUTHWEST_SEEDS))
def test_south_southwest_settle_tick_golden_and_bridge_persist(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    pure = settle_tick(settle["st"], settle["p"], [])
    bridged = fresh_db.settle_province_tick(region_id, [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db, region_id)["st"]

    for k, v in expected["first_tick"].items():
        if k in ("省库库银", "军饷欠", "官俸欠", "宗禄欠"):
            continue
        assert pure.new_st[k] == pytest.approx(v, abs=1e-4), f"{region_id} pure {k}"
        assert after[k] == pytest.approx(v, abs=1e-4), f"{region_id} DB {k}"
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id), abs=1e-6)
    for k, v in bridged.new_st.items():
        if k == "军饷欠":
            continue
        assert after[k] == pytest.approx(v, abs=1e-6), f"{region_id} 桥落库 {k} ≠ new_st"



def test_shaanxi_seed_is_relabelled_to_historical_shadow_scale(fresh_db):
    settle = _read_settle(fresh_db)
    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(5.0563, abs=1e-4)
    assert p["三饷应征"] == pytest.approx(2.1969011325)
    assert p["火耗率"] == pytest.approx(0.18)
    assert p["逋赋率"] == pytest.approx(0.45)
    assert p["起运定额"] == pytest.approx(2.1969011325)
    assert p["拨付gross"] == pytest.approx(4)
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shaanxi"))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 3, "宗禄": 4.07, "赈济": 0}
    assert settle["st"]["省库库银"] == 0
    assert settle["st"]["官民田"] == pytest.approx(2929.20151)
    assert settle["st"]["隐田"] == pytest.approx(1536.6303, abs=1e-4)

    meta = settle["_meta"]
    assert "宗禄" not in meta["provisional"]
    assert "起运定额" not in meta["provisional"]
    assert "官民田" not in meta["provisional"]
    assert "隐田" in meta["provisional"]
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]
    assert meta["辽饷九厘基线"] == pytest.approx(2.1969011325)
    assert meta["正赋起运基线"] == pytest.approx(0)
    assert isinstance(meta["notes"].get("辽饷九厘基线"), str) and meta["notes"]["辽饷九厘基线"].strip()
    assert isinstance(meta["notes"].get("正赋起运基线"), str) and meta["notes"]["正赋起运基线"].strip()
    primary = meta["primary_sources"]["万历会计录卷九陕西布政司田赋"]
    assert isinstance(primary.get("registered_land_raw"), str) and primary["registered_land_raw"].strip()
    assert primary["regular_tax_raw"]["實徵麥石"] == pytest.approx(688647.2416)
    assert primary["regular_tax_raw"]["實徵米石"] == pytest.approx(1044943.1241)



def test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues(fresh_db):
    settle = _read_settle(fresh_db, "shanxi")
    p = settle["p"]
    assert p["正赋应征"] == pytest.approx(17.652849583333335)
    assert p["三饷应征"] == pytest.approx(2.7600975)
    assert p["起运定额"] == pytest.approx(9.667061)
    assert p["拨付gross"] == pytest.approx(10)
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, "shanxi"))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 4, "宗禄": 10.99, "赈济": 0}
    assert settle["st"]["官民田"] == pytest.approx(3680.13, abs=1e-2)

    meta = settle["_meta"]
    assert "边镇军饷" in meta["postures"]
    assert "晋藩宗禄" in meta["postures"]
    assert "宗禄" not in meta["provisional"]
    assert "官民田" not in meta["provisional"]
    assert "起运定额" not in meta["provisional"]
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert meta["primary_source"]["田赋折银两_年"] == pytest.approx(2118341.95)
    assert meta["primary_source"]["起运折银两_年"] == pytest.approx(828835.62)
    assert meta["正赋起运基线"] == pytest.approx(828835.62 / 10000 / 12)
    assert meta["primary_source"]["粟米原额石"] == pytest.approx(1722851.38)
    assert set(meta["primary_source"]["fields_refined"]) >= {"官民田", "起运定额", "正赋应征"}


def test_border_slice_raw_content_keeps_primary_source_anchors():
    shanxi = _content_settle("shanxi")
    assert shanxi["p"]["正赋应征"] == pytest.approx(2118341.95 / 10000 / 12)
    assert shanxi["_meta"]["正赋起运基线"] == pytest.approx(828835.62 / 10000 / 12)
    assert shanxi["p"]["起运定额"] == pytest.approx(
        shanxi["_meta"]["正赋起运基线"] + shanxi["p"]["三饷应征"]
    )
    assert shanxi["st"]["官民田"] == pytest.approx(3680.13, abs=1e-2)
    assert "官民田" not in shanxi["_meta"]["provisional"]
    assert "起运定额" not in shanxi["_meta"]["provisional"]
    assert "正赋应征" not in shanxi["_meta"]["provisional"]
    assert set(shanxi["_meta"]["primary_source"]["fields_refined"]) >= {"官民田", "起运定额", "正赋应征"}
    assert shanxi["_meta"]["primary_source"]["田赋折银两_年"] == pytest.approx(2118341.95)
    assert shanxi["_meta"]["primary_source"]["起运米石"] == pytest.approx(640350)

    liaodong = _content_settle("liaodong")
    assert liaodong["p"]["Due"]["军饷"] == pytest.approx(711391 / 10000 / 12)
    assert liaodong["p"]["拨付gross"] == pytest.approx(409984 / 10000 / 12)
    assert liaodong["_meta"]["primary_source"]["粮料原额石"] == pytest.approx(279212)
    assert "军饷" not in liaodong["_meta"]["provisional"]
    assert "拨付gross" not in liaodong["_meta"]["provisional"]

    dongjiang = _content_settle("dongjiang_area")
    assert dongjiang["_meta"]["source_status"] == "no_wanli_accounting_record"
    coverage = dongjiang["_meta"]["notes"]["史料覆盖"]
    assert isinstance(coverage, str) and coverage.strip()
    assert set(dongjiang["_meta"]["provisional"]) >= {"军饷", "拨付gross", "军饷欠", "起运定额"}


def test_liaodong_and_dongjiang_are_pure_military_pay_funnels(fresh_db):
    expected = {
        "liaodong": {"grant": 409984 / 10000 / 12, "due": 711391 / 10000 / 12, "opening_arrears": 80},
        "dongjiang_area": {"grant": 5, "due": 14, "opening_arrears": 25},
    }
    for region_id, e in expected.items():
        settle = _read_settle(fresh_db, region_id)
        p = settle["p"]
        st = settle["st"]
        assert p["正赋应征"] == 0
        assert p["三饷应征"] == 0
        assert p["起运定额"] == 0
        assert p["拨付gross"] == pytest.approx(e["grant"])
        assert p["Due"]["军饷"] == pytest.approx(e["due"])
        assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == {"官俸": 0, "宗禄": 0, "赈济": 0}
        assert st["军饷欠"] == pytest.approx(e["opening_arrears"])

        res = settle_tick(st, p, [])
        assert res.breakdown["实征"] == 0
        assert res.breakdown["起运到京"] == 0
        assert res.new_st["军饷欠"] == pytest.approx(max(0, st["军饷欠"] + p["Due"]["军饷"] - e["grant"]))


def test_liaodong_primary_source_due_survives_fresh_db_pay_source_reconcile(fresh_db):
    settle = _read_settle(fresh_db, "liaodong")
    opening_arrears = settle["st"]["军饷欠"]
    expected_due = 711391 / 10000 / 12
    expected_grant = 409984 / 10000 / 12

    assert settle["p"]["Due"]["军饷"] == pytest.approx(expected_due)

    fresh_db.settle_province_tick("liaodong", [])
    fresh_db.conn.commit()

    after = _read_settle(fresh_db, "liaodong")
    assert after["p"]["Due"]["军饷"] == pytest.approx(expected_due)
    assert after["st"]["军饷欠"] == pytest.approx(
        max(0, opening_arrears + expected_due - expected_grant),
        abs=1e-6,
    )


def test_liaodong_pay_source_rows_add_to_standalone_military_funnel(fresh_db):
    state = fresh_db.load_state()
    settle = _read_settle(fresh_db, "liaodong")
    opening_arrears = settle["st"]["军饷欠"]
    standalone_due = settle["p"]["Due"]["军饷"]

    created = fresh_db.create_armies_from_extraction(state, [{
        "id": "liaodong_new_army",
        "name": "辽东新增营",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "liaodong",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }], commit=False)

    assert created and created[0].get("created") is True
    after = _read_settle(fresh_db, "liaodong")
    assert after["st"]["军饷欠"] == pytest.approx(
        opening_arrears + _province_pay_arrears(fresh_db, "liaodong"),
        abs=1e-6,
    )
    assert after["p"]["Due"]["军饷"] == pytest.approx(
        standalone_due + _province_pay_due(fresh_db, "liaodong"),
        abs=1e-6,
    )


def test_liaodong_settle_tick_keeps_standalone_funnel_deficit_out_of_pay_rows(fresh_db):
    state = fresh_db.load_state()
    created = fresh_db.create_armies_from_extraction(state, [{
        "id": "liaodong_new_army",
        "name": "辽东新增营",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "liaodong",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }], commit=False)
    assert created and created[0].get("created") is True

    before = _read_settle(fresh_db, "liaodong")
    row_due = _province_pay_due(fresh_db, "liaodong")
    row_opening_arrears = _province_pay_arrears(fresh_db, "liaodong")
    standalone_due = before["p"]["Due"]["军饷"] - row_due

    result = fresh_db.settle_province_tick("liaodong", [])
    fresh_db.conn.commit()

    new_debt = result.breakdown["NewDebt"]["军饷欠"]
    expected_row_arrears = row_opening_arrears + new_debt * row_due / (standalone_due + row_due)
    row_after = _province_pay_arrears(fresh_db, "liaodong")
    after = _read_settle(fresh_db, "liaodong")

    assert row_after == pytest.approx(expected_row_arrears, abs=1e-6)
    assert row_after < row_opening_arrears + new_debt - 1e-6
    assert after["_meta"]["standalone_military_pay_arrears"] == pytest.approx(
        after["st"]["军饷欠"] - row_after,
        abs=1e-6,
    )
    assert after["_meta"]["standalone_military_pay_arrears"] > 0


def test_dongjiang_content_pay_funnel_survives_fresh_db_pay_source_reconcile(fresh_db):
    settle = _read_settle(fresh_db, "dongjiang_area")

    assert settle["p"]["Due"]["军饷"] == pytest.approx(14)
    assert settle["st"]["军饷欠"] == pytest.approx(25)


def test_old_dongjiang_pay_funnel_due_backfills_before_new_pay_rows(fresh_db):
    settle = _read_settle(fresh_db, "dongjiang_area")
    old_due = settle["p"]["Due"]["军饷"]
    settle["_meta"].pop("standalone_military_pay_due", None)
    _write_settle(fresh_db, "dongjiang_area", settle)

    state = fresh_db.load_state()
    created = fresh_db.create_armies_from_extraction(state, [{
        "id": "dongjiang_new_army",
        "name": "东江新增营",
        "manpower": 1000,
        "owner_power": "ming",
        "pay_source_region": "dongjiang_area",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }], commit=False)

    assert created and created[0].get("created") is True
    row_due = _province_pay_due(fresh_db, "dongjiang_area")
    after = _read_settle(fresh_db, "dongjiang_area")

    assert after["_meta"]["standalone_military_pay_due"] == pytest.approx(old_due)
    assert after["p"]["Due"]["军饷"] == pytest.approx(old_due + row_due)


@pytest.mark.parametrize("bad_annual", [True, "711391", float("nan"), float("inf"), -1])
def test_primary_source_army_pay_due_rejects_dirty_annual_amount(fresh_db, bad_annual):
    settle = _read_settle(fresh_db, "liaodong")
    settle["_meta"]["primary_source"]["现额银两_年"] = bad_annual

    with pytest.raises(ValueError, match="primary_source 现额银两_年 非法"):
        fresh_db._derive_region_army_pay_due("liaodong", settle)


@pytest.mark.parametrize(
    ("region_id", "mutate", "match"),
    [
        ("dongjiang_area", lambda settle: settle.__setitem__("p", []), "settle.p 非法"),
        ("dongjiang_area", lambda settle: settle["p"].__setitem__("Due", []), "settle.p.Due 非法"),
        ("dongjiang_area", lambda settle: settle.__setitem__("st", []), "settle.st 非法"),
        ("liaodong", lambda settle: settle.__setitem__("st", []), "settle.st 非法"),
    ],
)
def test_standalone_army_pay_funnel_rejects_malformed_settle_shapes(
    fresh_db, region_id, mutate, match
):
    settle = _read_settle(fresh_db, region_id)
    mutate(settle)

    with pytest.raises(ValueError, match=match):
        fresh_db._derive_region_army_pay_due(region_id, settle)


def test_standalone_army_pay_container_total_uses_grouped_arrears(fresh_db, monkeypatch):
    def fail_single_region_lookup(region_id):
        raise AssertionError(f"unexpected per-region army pay lookup: {region_id}")

    monkeypatch.setattr(
        fresh_db,
        "_army_pay_source_rows_for_region",
        fail_single_region_lookup,
    )

    assert fresh_db._standalone_army_pay_container_total() >= 0


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda fiscal: fiscal.__setitem__("settle", []), "region dongjiang_area settle 非法"),
        (lambda fiscal: fiscal["settle"].__setitem__("st", []), "region dongjiang_area settle.st 非法"),
    ],
)
def test_standalone_army_pay_container_total_rejects_malformed_region_shapes(
    fresh_db, mutate, match
):
    fiscal = _read_fiscal(fresh_db, "dongjiang_area")
    mutate(fiscal)
    fresh_db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "dongjiang_area"),
    )

    with pytest.raises(ValueError, match=match):
        fresh_db._standalone_army_pay_container_total()


JIANGNAN_CORE_EXPECTED = {
    "nanzhili": {
        "正赋应征": 30, "三饷应征": 5.953499999999999, "起运定额": 14.723499999999998,
        "Due": {"官俸": 4, "宗禄": 0, "赈济": 0},
        "first_tick": {"起运到京": 14.7235, "省库库银": 2.75837, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "zhejiang": {
        "正赋应征": 23, "三饷应征": 3.5024999999999995, "起运定额": 7.032499999999999,
        "Due": {"官俸": 3, "宗禄": 0, "赈济": 0},
        "first_tick": {"起运到京": 7.0325, "省库库银": 11.1695, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "jiangxi": {
        "正赋应征": 22, "三饷应征": 3.009, "起运定额": 7.709,
        "Due": {"官俸": 3, "宗禄": 0.79, "赈济": 0},
        "first_tick": {"起运到京": 7.709, "省库库银": 7.25775, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
    "huguang": {
        "正赋应征": 34, "三饷应征": 16.6215, "起运定额": 18.5315,
        "Due": {"官俸": 3, "宗禄": 2.63, "赈济": 0},
        "first_tick": {"起运到京": 18.5315, "省库库银": 15.32327, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
    },
}


@pytest.mark.parametrize("region_id,expected", JIANGNAN_CORE_EXPECTED.items())
def test_jiangnan_core_seeds_have_positive_remittance_golden(fresh_db, region_id, expected):
    settle = _read_settle(fresh_db, region_id)
    assert isinstance(settle, dict), f"{region_id} fiscal 缺 settle 基座"
    meta = settle["_meta"]
    assert "江南财赋核心" in meta["postures"]
    assert meta["levies"]["seeded"] == ["辽饷"]
    assert "剿饷" in meta["levies"]["not_seeded"]
    assert "练饷" in meta["levies"]["not_seeded"]

    p = settle["p"]
    for key in ("正赋应征", "三饷应征", "起运定额"):
        assert p[key] == pytest.approx(expected[key])
    assert p["Due"]["军饷"] == pytest.approx(_province_pay_due(fresh_db, region_id))
    assert {k: p["Due"][k] for k in ("官俸", "宗禄", "赈济")} == expected["Due"]
    assert p["起运定额"] > p["三饷应征"], "江南起运定额须覆盖三饷并含正赋大份额"

    res = settle_tick(settle["st"], p, [])
    for key, value in expected["first_tick"].items():
        got = res.breakdown.get(key) if key == "起运到京" else res.new_st[key]
        assert got == pytest.approx(value, abs=1e-3), f"{region_id} {key}"
    assert res.breakdown["起运到京"] > 0, f"{region_id} 应跑出正起运"


def test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due(fresh_db):
    huguang = _read_settle(fresh_db, "huguang")
    nanzhili = _read_settle(fresh_db, "nanzhili")

    assert "楚藩重宗禄" in huguang["_meta"]["postures"]
    assert huguang["p"]["Due"]["宗禄"] > nanzhili["p"]["Due"]["宗禄"]

    res = settle_tick(huguang["st"], huguang["p"], [])
    assert res.breakdown["起运到京"] > 0
    assert res.new_st["省库库银"] > 0
    assert res.new_st["宗禄欠"] == pytest.approx(0)



def test_beizhili_huangzhuang_is_inner_treasury_not_transport_quota(fresh_db):
    settle = _read_settle(fresh_db, "beizhili")
    fiscal = json.loads(str(fresh_db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='beizhili'"
    ).fetchone()["fiscal"]))

    huang_meta = settle["_meta"]["huang_tian"]
    assert fiscal["huang_tian"] == pytest.approx(184)
    assert huang_meta["account"] == "内库"
    assert huang_meta["excluded_from"] == ["正赋应征", "起运到京"]
    assert settle["st"]["官民田"] == pytest.approx(4925.7, abs=0.1)
    assert settle["st"]["官民田"] != pytest.approx(
        fiscal["guan_min_tian"] * 10
    ), "一手核田亩保留小数，不再用小游戏字段反推"
    assert settle["_meta"]["正赋起运基线"] == pytest.approx(5.2)
    assert settle["p"]["起运定额"] == pytest.approx(
        settle["_meta"]["正赋起运基线"] + settle["p"]["三饷应征"]
    )


def test_henan_royal_grants_make_zonglu_due_heavy(fresh_db):
    henan = _read_settle(fresh_db, "henan")
    beizhili = _read_settle(fresh_db, "beizhili")
    shandong = _read_settle(fresh_db, "shandong")

    assert henan["_meta"]["wang_tian"]["houses"] == ["周王", "唐王", "赵王", "郑王", "崇王"]
    assert henan["_meta"]["wang_tian"]["basis"] == "wang_tian"
    assert henan["p"]["Due"]["宗禄"] > beizhili["p"]["Due"]["宗禄"]
    assert henan["p"]["Due"]["宗禄"] > shandong["p"]["Due"]["宗禄"]
    assert henan["p"]["Due"]["宗禄"] == pytest.approx(9.15)


@pytest.mark.parametrize("region_id,expect", ZHONGYUAN_JINGSHI_GOLDEN.items())
def test_zhongyuan_jingshi_settle_province_tick_golden(region_id, expect, fresh_db):
    res = fresh_db.settle_province_tick(region_id, [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db, region_id)["st"]

    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, region_id), abs=1e-6)
    for key, value in expect.items():
        assert key in after, f"{region_id} golden missing {key}"
        assert math.isclose(
            after[key],
            value,
            rel_tol=0,
            abs_tol=1e-3,
        ), f"{region_id} {key}: {after[key]} != {value}"
    for key, value in res.new_st.items():
        if key == "军饷欠":
            continue
        assert abs(after[key] - value) < 1e-6, f"{region_id} {key}: 落库 {after[key]} ≠ new_st {value}"


def test_settle_province_tick_persists_shaanxi_historical_shadow_golden(fresh_db):
    res = fresh_db.settle_province_tick("shaanxi", [])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    assert after["C_地方截留"] == pytest.approx(0.7181, abs=1e-3)
    assert after["民欠旧赋"] == pytest.approx(3.2639, abs=1e-3)
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(fresh_db, "shaanxi"), abs=1e-6)
    # 落库逐键 == settle_tick 的 new_st（桥不篡改）
    for k, v in res.new_st.items():
        if k == "军饷欠":
            continue
        assert abs(after[k] - v) < 1e-6, f"{k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_persists_border_remainder_golden(fresh_db):
    expected = {
        "shanxi": {
            "C_地方截留": 2.255631,
            "民欠旧赋": 7.144531,
        },
        "liaodong": {
            "C_地方截留": 0,
            "民欠旧赋": 0,
            "军饷欠": 80 + 711391 / 10000 / 12 - 409984 / 10000 / 12,
        },
        "dongjiang_area": {
            "C_地方截留": 0,
            "民欠旧赋": 0,
            "军饷欠": 34,
        },
    }
    for region_id, want in expected.items():
        res = fresh_db.settle_province_tick(region_id, [])
        after = _read_settle(fresh_db, region_id)["st"]
        for k, v in want.items():
            assert after[k] == pytest.approx(v, abs=1e-3), \
                f"{region_id} {k}：落库 {after[k]} ≠ #267 {v}"
        if "军饷欠" in want:
            assert after["军饷欠"] == pytest.approx(want["军饷欠"], abs=1e-6)
        else:
            assert after["军饷欠"] == pytest.approx(
                _region_pay_arrears_container_basis(fresh_db, region_id),
                abs=1e-6,
            )
        for k, v in res.new_st.items():
            if k == "军饷欠":
                continue
            assert abs(after[k] - v) < 1e-6, f"{region_id} {k}：落库 {after[k]} ≠ new_st {v}"


def test_settle_province_tick_qingzhang_action(fresh_db):
    row = fresh_db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["st"]["省库库银"] = 50
    fresh_db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    fresh_db.conn.commit()
    # 带 action 的桥：清丈挖隐田 300 → 万历见额官民田 +300、隐田 -300（土地守恒）
    fresh_db.settle_province_tick("shaanxi", [{"type": "清丈", "cost": 2, "挖隐田": 300}])
    fresh_db.conn.commit()
    after = _read_settle(fresh_db)["st"]
    assert abs(after["官民田"] - 3229.20151) < 1e-3, f"官民田 {after['官民田']} ≠ 3229.20151"
    assert abs(after["隐田"] - 1236.6303) < 1e-3, f"隐田 {after['隐田']} ≠ 1236.6303"


def test_settle_province_tick_port_lock_no_persist_on_raise(fresh_db):
    # 港口锁：坏 p（删必填火耗率）→ settle_tick raise → DB 绝不变（FAIL tick 不持久化）
    row = fresh_db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    del fiscal["settle"]["p"]["火耗率"]
    fresh_db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    fresh_db.conn.commit()
    st_before = _read_settle(fresh_db)["st"]
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("shaanxi", [])
    st_after = _read_settle(fresh_db)["st"]
    assert st_after == st_before, "港口锁破：FAIL tick 改了 DB"


def test_settle_province_tick_unknown_region_raises(fresh_db):
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("atlantis", [])


def test_settle_province_tick_nondict_fiscal_raises(fresh_db):
    # cmr R3（gemini）：fiscal JSON 非 dict（如 "[]"）→ ValueError（可被隔离捕获），
    # 非 fiscal.get 抛 AttributeError 逃逸。
    fresh_db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    fresh_db.conn.commit()
    with pytest.raises(ValueError):
        fresh_db.settle_province_tick("shaanxi", [])


# ── slice3：接入月末固定财政相位（shadow，不驱动国库；fail-loud 但隔离）──

@pytest.fixture
def fresh_game(fresh_db):
    """fresh_db + load_state，供调 apply_fixed_period_flows（需 GameState）。"""
    return fresh_db, fresh_db.load_state()


def test_apply_fixed_period_flows_advances_shaanxi_substrate(fresh_game):
    # 月末固定财政相位推进省级基座：陕西史实量级 seed 空 action 一 tick → 欠账螺旋累积
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    assert _read_settle(db)["st"]["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"))
    apply_fixed_period_flows(db, state)
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6)
    assert after["省库库银"] == pytest.approx(0, abs=1e-3)
    assert after["C_地方截留"] == pytest.approx(0.7181, abs=1e-3)
    assert after["民欠旧赋"] == pytest.approx(3.2639, abs=1e-3)


def test_apply_fixed_period_flows_uses_dynamic_ming_settle_spine(fresh_game):
    # #266: shadow spine is controlled_by==ming AND has fiscal.settle.
    # That lets lost provinces freeze naturally and lets newly-seeded Ming provinces tick.
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    shaanxi_settle = _read_settle(db)

    henan_settle = json.loads(json.dumps(shaanxi_settle, ensure_ascii=False))
    henan_settle["st"]["省库库银"] = 40
    henan_fiscal = {"settle": henan_settle}
    non_ming_power = db.conn.execute(
        "SELECT id FROM powers WHERE id <> 'ming' LIMIT 1"
    ).fetchone()[0]
    db.conn.execute(
        "UPDATE regions SET controlled_by = ?, fiscal = ? WHERE id = 'henan'",
        (non_ming_power, json.dumps(henan_fiscal, ensure_ascii=False)),
    )
    db.conn.execute("UPDATE regions SET controlled_by = 'ming' WHERE id = 'taiwan'")
    db.conn.commit()

    apply_fixed_period_flows(db, state)
    assert _read_settle(db)["st"]["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"))
    assert _read_settle(db, "henan")["st"]["省库库银"] == 40, "非明控制省不应 tick"
    assert _read_settle(db, "taiwan") is None, "明控但无 settle 的省不应被创建/推进"

    db.conn.execute("UPDATE regions SET controlled_by = 'ming' WHERE id = 'henan'")
    db.conn.commit()
    apply_fixed_period_flows(db, state)
    assert _read_settle(db, "henan")["st"]["省库库银"] != 40, "明控且有 settle 的省应 tick"




def test_substrate_absent_does_not_break_flows(game):
    # 旧档无 settle 种子 → shadow 隔离：固定财政照常完成，不抛。
    # 显式保证「无基座」前提（不依赖 probe.db 恰好缺 settle——刷新种子档也不失效，PR#110 coderabbit）。
    from ming_sim.flows import apply_fixed_period_flows
    db, state, _ = game
    _disable_army_pay_source_cutover(db)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}")) if row else {}
    fiscal.pop("settle", None)
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    assert _read_settle(db) is None, "前提：陕西无 settle 基座"
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "固定财政应照常落账（基座缺失不该掀翻 pre_settle）"


def test_substrate_corrupt_isolated_from_flows(fresh_game):
    # Legacy shadow：坏基座（删必填火耗率）→ settle_tick raise → 隔离：固定财政照常完成 + 基座不推进（港口锁）
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    del fiscal["settle"]["p"]["火耗率"]
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "坏基座不该掀翻固定财政（cmr S4 F4）"
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6), \
        "坏基座不该推进（港口锁：FAIL tick 不落库）"


def test_substrate_corrupt_due_isolated(fresh_game):
    # cmr ship-pre R1（codex+gemini concur P1）：Due 非字典曾抛 AttributeError 逃逸 flows 的
    # (ValueError, FiscalConservationError) 隔离 → 炸 pre_settle 固定财政。settle_tick 验形归
    # ValueError 后→被隔离捕获，固定财政照常完成 + 基座不推进（港口锁）。
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"]["Due"] = None  # 非字典
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "Due 非字典不该掀翻固定财政（AttributeError 逃逸隔离）"
    after = _read_settle(db)["st"]
    assert after["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6), \
        "坏 Due 不该推进（港口锁）"


def test_substrate_corrupt_stock_isolated(fresh_game):
    # cmr ship-pre R2（codex concur P1）：开账 stock 非数值（如 省库库银=[]）曾在 float() 抛
    # TypeError 逃逸 flows 隔离炸 pre_settle。前置验形归 ValueError 后→被隔离捕获，固定财政照常。
    from ming_sim.flows import apply_fixed_period_flows
    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["st"]["省库库银"] = []  # 非数值
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    flows = apply_fixed_period_flows(db, state)
    assert isinstance(flows, list) and flows, "非数值 stock 不该掀翻固定财政（TypeError 逃逸隔离）"
    after = _read_settle(db)["st"]
    assert after["省库库银"] == [], "坏 stock 不该推进（港口锁：原值不变）"


def test_substrate_malformed_settle_shape_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # cmr fix：动态 spine 只负责找「明控且已有 settle key」的省；st/p 形状坏态必须交给
    # settle_province_tick 验证并经 shadow 隔离日志留痕，不能在 spine 预过滤后静默跳过。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []  # malformed settle block: 有 settle key，但缺合法 p dict
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 settle 形状不该掀翻固定财政"
    assert _read_settle(db)["p"] == [], "坏 settle 形状不该被 tick 改写"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "ValueError" in m]
    assert surfaced, msgs


def test_substrate_malformed_fiscal_container_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # cmr step6 r2：动态 spine 不得在 selector 里静默跳过 fiscal='[]' 这类坏容器；
    # 应交给 settle_province_tick 归 ValueError，再由 shadow 隔离 tlog 留痕。
    # 这里刻意直打 shadow seam：完整 fixed-flow 的旧财政收入路径会先解析 fiscal。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "[]"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "ValueError" in m]
    assert surfaced, msgs


def test_cutover_pay_source_errors_abort_fixed_flows(fresh_game, monkeypatch, tmp_path):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    db.conn.execute(
        """
        UPDATE armies
        SET province_pay_share = 0.7, central_pay_share = 0.2
        WHERE id = 'shaanxi_army'
        """
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert "饷源比例和必须为 1" in (pack / "traceback.txt").read_text(encoding="utf-8")


def test_cutover_substrate_bad_state_uses_settlement_abort_error_pack(fresh_game, monkeypatch, tmp_path):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")
    assert _read_settle(db)["p"] == []


def test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"]["拨付gross"] = True
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    assert Path(abort.error_pack_path).exists()
    assert _read_settle(db)["p"]["拨付gross"] is True


def test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    state.metrics["国库"] = 5
    db.save_state(state)
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0,
            central_pay_share = 1, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 10000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()
    original_record = db.record_issue_economy_move

    def fail_border_hub_debit(state_arg, account, amount, category, reason):
        if category == "边饷hub":
            return None
        return original_record(state_arg, account, amount, category, reason)

    monkeypatch.setattr(db, "record_issue_economy_move", fail_border_hub_debit)

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert "边饷hub实拨失败" in (pack / "traceback.txt").read_text(encoding="utf-8")


def test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    _set_fiscal_config_value(db, "central_taicang_human_loss_rate", 80)
    _set_fiscal_config_value(db, "central_taicang_sink_loss_rate", 30)

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")


def test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    db.conn.execute(
        "DELETE FROM fiscal_config WHERE key = 'central_taicang_human_loss_rate'"
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert "central_taicang_human_loss_rate 缺失" in (
        pack / "traceback.txt"
    ).read_text(encoding="utf-8")


def test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    db.conn.execute(
        "UPDATE fiscal_config SET value = 0 WHERE key = 'central_taicang_sink_loss_rate'"
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        flows_mod.apply_fixed_period_flows(db, state)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")


def test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    from ming_sim.decree import pre_settle

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        pre_settle(state, db)

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")
    assert _read_settle(db)["p"] == []


def test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    """#1274：无旨完整结算 pre_settle 遇坏 fiscal 态 → SettlementAbort 错误包。"""
    import ming_sim.decree as decree_mod
    import ming_sim.error_pack as error_pack_mod
    import ming_sim.memories as memories
    from ming_sim.models import TurnPhase
    from ming_sim.session import GameSession

    db, state = fresh_game
    content = getattr(db, "content", None)
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    before_turn = state.turn
    before_phase = state.turn_phase

    # canned LLM；崩应在 pre_settle fiscal，到不了 simulator
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应到 simulator")),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", lambda *a, **k: ({}, "o", "i"))
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None

    with pytest.raises(SettlementAbort) as exc_info:
        sess.advance_without_decree()

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")
    assert _read_settle(db)["p"] == []
    reloaded = db.load_state()
    assert reloaded.turn == before_turn
    assert reloaded.turn_phase == before_phase == TurnPhase.SUMMONING.value


def test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack(
    fresh_game, monkeypatch, tmp_path
):
    import ming_sim.error_pack as error_pack_mod
    from ming_sim.decree import resolve_directives

    db, state = fresh_game
    monkeypatch.setattr(error_pack_mod, "user_data_dir", lambda: tmp_path)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    fiscal["settle"]["p"] = []
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort) as exc_info:
        resolve_directives(state, db, None, None, [object()], "诏曰：照旧。")

    abort = exc_info.value
    assert abort.stage == "fixed_fiscal"
    assert abort.error_pack_path
    pack = Path(abort.error_pack_path)
    assert pack.exists()
    assert (pack / "traceback.txt").read_text(encoding="utf-8")
    assert _read_settle(db)["p"] == []


def test_apply_fixed_period_flows_malformed_fiscal_container_isolated(fresh_game, monkeypatch):
    # Public entry contract: fixed fiscal must not crash before shadow substrate isolation can log.
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    db.conn.execute("UPDATE regions SET fiscal='[]' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal 容器不该掀翻固定财政"
    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "[]"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 省当月固定税收应出列，不能按默认 fiscal 造钱"
    assert any(isinstance(m, str) and m.startswith("[province-fiscal] shaanxi") for m in msgs), msgs
    assert any(
        isinstance(m, str) and "[fiscal-substrate] shaanxi" in m and "ValueError" in m
        for m in msgs
    ), msgs


def test_substrate_malformed_fiscal_json_is_logged_not_prefiltered(fresh_game, monkeypatch):
    # 动态 spine selector 解析 fiscal JSON 失败时仍应把该省交给 bridge，让 shadow 隔离
    # 统一 tlog 留痕；不能静默跳过坏 JSON。
    # 这里刻意直打 shadow seam：完整 fixed-flow 的旧财政收入路径会先解析 fiscal。
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    db.conn.execute("UPDATE regions SET fiscal='{bad' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "{bad"
    surfaced = [m for m in msgs if "[fiscal-substrate] shaanxi" in m and "JSONDecodeError" in m]
    assert surfaced, msgs


def test_apply_fixed_period_flows_malformed_fiscal_json_isolated(fresh_game, monkeypatch):
    # Public entry contract: syntax-bad fiscal JSON must not abort before shadow isolation.
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    db.conn.execute("UPDATE regions SET fiscal='{bad' WHERE id='shaanxi'")
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal JSON 不该掀翻固定财政"
    assert db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()["fiscal"] == "{bad"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 省当月固定税收应出列，不能按默认 fiscal 造钱"
    assert any(
        isinstance(m, str)
        and m.startswith("[province-fiscal] shaanxi")
        and "JSONDecodeError" in m
        for m in msgs
    ), msgs
    assert any("[fiscal-substrate] shaanxi" in m and "JSONDecodeError" in m for m in msgs), msgs


@pytest.mark.parametrize("field,bad_value", [
    ("corruption", []),
    ("liao_xiang", []),
])
def test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated(fresh_game, monkeypatch, field, bad_value):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    _disable_army_pay_source_cutover(db)
    _, _, before_details = flows_mod.calc_province_fiscal(state, db)
    expected_tax = sum(
        int(d["province_total"]) for d in before_details if d["region_id"] != "shaanxi"
    )
    fiscal = json.loads(str(db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='shaanxi'"
    ).fetchone()["fiscal"] or "{}"))
    fiscal[field] = bad_value
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    flow_rows = flows_mod.apply_fixed_period_flows(db, state)

    assert isinstance(flow_rows, list) and flow_rows, "坏 fiscal 标量不该掀翻固定财政"
    tax_flow = next(f for f in flow_rows if f.get("category") == "田赋辽饷盐商")
    assert tax_flow["amount"] == expected_tax, "坏 fiscal 标量省当月固定税收应出列"
    assert any(
        isinstance(m, str)
        and m.startswith("[province-fiscal] shaanxi")
        and f"fiscal.{field}" in m
        for m in msgs
    ), msgs


def test_fixed_flow_loader_accepts_already_decoded_fiscal_dict(monkeypatch):
    import ming_sim.flows as flows_mod

    fiscal = {"settle": {"st": {}, "p": {}}, "tax": 1}
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", fiscal) == fiscal
    assert msgs == []


@pytest.mark.parametrize("bad_scalar", [float("nan"), float("inf"), 10 ** 309])
def test_fixed_flow_loader_rejects_non_finite_numeric_values(monkeypatch, bad_scalar):
    import ming_sim.flows as flows_mod

    fiscal = {"settle": {"st": {}, "p": {}}, "liao_xiang": bad_scalar}
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", fiscal) is None
    assert any(
        isinstance(m, str)
        and m.startswith("[province-fiscal] shaanxi")
        and "fiscal.liao_xiang" in m
        for m in msgs
    ), msgs


@pytest.mark.parametrize("payload", [[], 0, False])
def test_fixed_flow_loader_rejects_decoded_non_dict_payloads(monkeypatch, payload):
    import ming_sim.flows as flows_mod

    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    assert flows_mod._load_region_fiscal_for_fixed_flow("shaanxi", payload) is None
    assert any(
        isinstance(m, str) and m.startswith("[province-fiscal] shaanxi")
        for m in msgs
    ), msgs


def test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    flows_mod.apply_fixed_period_flows(db, state)
    in_memory = _read_settle(db, "shaanxi")["st"]

    other = sqlite3.connect(db.path)
    try:
        row = other.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    finally:
        other.close()
    on_disk = json.loads(str(row[0] or "{}"))["settle"]["st"]

    assert on_disk["军饷欠"] == pytest.approx(in_memory["军饷欠"], abs=1e-3)
    assert on_disk["军饷欠"] == pytest.approx(_province_pay_arrears(db, "shaanxi"), abs=1e-6)


def test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic(fresh_game):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    before = _read_settle(db, "shaanxi")["st"]

    with pytest.raises(RuntimeError, match="rollback probe"):
        with atomic(db):
            flows_mod._advance_province_fiscal_substrate(db, state)
            in_transaction = _read_settle(db, "shaanxi")["st"]
            assert in_transaction["民欠旧赋"] != pytest.approx(before["民欠旧赋"])
            raise RuntimeError("rollback probe")

    after = _read_settle(db, "shaanxi")["st"]
    assert after["民欠旧赋"] == pytest.approx(before["民欠旧赋"])
    assert after["C_地方截留"] == pytest.approx(before["C_地方截留"])




def test_all_ming_settle_substrates_advance_with_observable_shadow_tlog(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    monkeypatch.setattr(flows_mod, "tlog", lambda msg: msgs.append(msg))

    fixed_flows = flows_mod.apply_fixed_period_flows(db, state)

    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()
    settle_region_ids = [
        str(row["id"])
        for row in rows
        if "settle" in json.loads(str(row["fiscal"] or "{}"))
    ]
    # 成功推进协议前缀（含 region_id + 推进标记）；隔离/中止路径不计入
    shadow_msgs = [
        m for m in msgs
        if isinstance(m, str)
        and m.startswith("[fiscal-substrate] ")
        and " 推进：" in m
    ]

    assert len(settle_region_ids) == 17
    assert len(shadow_msgs) == 17
    assert any(
        flow.get("account") == "国库"
        and flow.get("dir") == "income"
        and flow.get("category") == "起运"
        for flow in fixed_flows
    ), "cutover 基座应把起运作为 hub 国库收入落账"
    for region_id in settle_region_ids:
        surfaced = [
            m for m in shadow_msgs
            if m.startswith(f"[fiscal-substrate] {region_id} 推进：")
        ]
        # 每省成功消息恰为 1（总数 17 + 无重复）
        assert len(surfaced) == 1, f"{region_id} 成功 shadow 计数须恰为 1: {surfaced or msgs}"
        msg = surfaced[0]
        # 四个稳定诊断字段及其可判别值/字段—值绑定（协议：实征X/起运Y/火耗入截留Z；末态欠账 …）
        # 不钉完整中文句；禁止仅查字段中文是否出现。
        want = REGULAR_PROVINCE_FIRST_TICK_GOLDEN.get(region_id)
        if want is not None:
            assert f"实征{want['实征']:.1f}" in msg, f"{region_id} 实征值绑定失败: {msg}"
            assert f"起运{want['起运到京']:.1f}" in msg, f"{region_id} 起运值绑定失败: {msg}"
            assert f"火耗入截留{want['火耗实收']:.1f}" in msg, f"{region_id} 火耗值绑定失败: {msg}"
        else:
            # 军饷漏斗省（liaodong/dongjiang）：breakdown 为 0.0，仍须字段—值绑定
            assert "实征0.0" in msg, f"{region_id} 实征值绑定失败: {msg}"
            assert "起运0.0" in msg, f"{region_id} 起运值绑定失败: {msg}"
            assert "火耗入截留0.0" in msg, f"{region_id} 火耗值绑定失败: {msg}"
        # 末态欠账四子标签：日志值按生产格式（flows.py `.0f` + `/`/`（` 分隔）与落库 st 绑定；
        # 生产标签「民欠」对应 st 键「民欠旧赋」。右边界堵住前缀碰撞（期望 1、错写 10 必红）。
        st = _read_settle(db, region_id)["st"]
        assert f"军饷欠{st['军饷欠']:.0f}/" in msg, f"{region_id} 军饷欠值绑定失败: {msg} vs st={st.get('军饷欠')}"
        assert f"官俸欠{st['官俸欠']:.0f}/" in msg, f"{region_id} 官俸欠值绑定失败: {msg} vs st={st.get('官俸欠')}"
        assert f"宗禄欠{st['宗禄欠']:.0f}/" in msg, f"{region_id} 宗禄欠值绑定失败: {msg} vs st={st.get('宗禄欠')}"
        assert f"民欠{st['民欠旧赋']:.0f}（" in msg, f"{region_id} 民欠值绑定失败: {msg} vs st={st.get('民欠旧赋')}"

    # 吸收原 jiangnan advances_and_logs：flows 路径落库 first_tick 省库库银硬锚（非仅 >0）
    for region_id, expected in JIANGNAN_CORE_EXPECTED.items():
        settle = _read_settle(db, region_id)
        want = expected["first_tick"]["省库库银"]
        assert settle["st"]["省库库银"] == pytest.approx(want, abs=1e-3), (
            f"{region_id} flows 后省库库银 {settle['st']['省库库银']} ≠ first_tick {want}"
        )
    for region_id in ("shaanxi", "shanxi", "liaodong", "dongjiang_area"):
        settle = _read_settle(db, region_id)
        assert settle["st"]["军饷欠"] == pytest.approx(
            _region_pay_arrears_container_basis(db, region_id),
            abs=1e-6,
        )
    assert _read_settle(db, "henan")["st"]["宗禄欠"] > 0, "周/福藩重省应有宗禄欠压"
    assert _read_settle(db, "huguang")["p"]["Due"]["宗禄"] > _read_settle(db, "nanzhili")["p"]["Due"]["宗禄"], \
        "楚藩重省宗禄 Due 应重于江南基准"


def test_shadow_spine_uses_batch_bridge_without_per_region_reload(fresh_game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state = fresh_game
    msgs: list[str] = []
    calls = {"batch": 0}
    monkeypatch.setattr(flows_mod, "tlog", msgs.append)

    def fake_batch_bridge():
        calls["batch"] += 1
        return [
            SimpleNamespace(
                region_id="shaanxi",
                error=None,
                result=SimpleNamespace(
                    breakdown={"实征": 1.2, "起运到京": 0.3, "火耗实收": 0.4},
                    new_st={"军饷欠": 2, "官俸欠": 0, "宗禄欠": 0, "民欠旧赋": 1},
                ),
            )
        ]

    def fail_single_region_reload(*args, **kwargs):
        raise AssertionError("shadow spine must use the batch fiscal payload bridge")

    monkeypatch.setattr(db, "settle_ming_province_substrate_ticks", fake_batch_bridge)
    monkeypatch.setattr(db, "settle_province_tick", fail_single_region_reload)

    flows_mod._advance_province_fiscal_substrate(db, state)

    assert calls["batch"] == 1
    assert any(
        isinstance(msg, str) and msg.startswith("[fiscal-substrate] shaanxi 推进：")
        for msg in msgs
    )


def test_seeded_substrates_keep_multi_tick_historical_trajectories(fresh_db):
    """#70 capstone：用真实 content seed 跑多 tick 轨迹，而非只测首 tick golden。"""
    jiangnan = ("nanzhili", "zhejiang", "jiangxi", "huguang")
    border = ("shaanxi", "shanxi", "liaodong", "dongjiang_area")

    for region_id in jiangnan:
        settle = _read_settle(fresh_db, region_id)
        st = settle["st"]
        remittances = []
        for _ in range(3):
            res = settle_tick(st, settle["p"], [])
            remittances.append(res.breakdown["起运到京"])
            st = res.new_st
        assert all(value > 0 for value in remittances), \
            f"{region_id} 江南财赋核心应多 tick 保持正起运: {remittances}"

    for region_id in border:
        settle = _read_settle(fresh_db, region_id)
        st = settle["st"]
        arrears = []
        for _ in range(3):
            res = settle_tick(st, settle["p"], [])
            arrears.append(res.new_st["军饷欠"])
            st = res.new_st
        assert all(value >= 0 for value in arrears), \
            f"{region_id} 边镇军饷容器不得为负: {arrears}"
        assert arrears == sorted(arrears), \
            f"{region_id} 边镇军饷缺口在拨付不足时不得回落: {arrears}"
        if settle["p"]["Due"]["军饷"] > settle["p"]["拨付gross"]:
            assert arrears[-1] > 0, \
                f"{region_id} 拨付不足时边镇军饷缺口应持续存在: {arrears}"


def test_all_settle_substrate_provisional_meta_covers_virtual_fields(fresh_db):
    rows = fresh_db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()
    raw_meta_defaults_by_region = _raw_settle_meta_defaults_by_region()

    checked = 0
    for row in rows:
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle")
        if not settle:
            continue
        checked += 1
        region_id = str(row["id"])
        st = settle["st"]
        p = settle["p"]
        meta = settle["_meta"]
        provisional = set(settle["_meta"].get("provisional", []))
        if p["正赋应征"] == 0 and p["起运定额"] == 0:
            required = {"军饷", "拨付gross", "军饷欠", "起运定额"}
        elif region_id == "shaanxi" or "source_grain" in meta:
            required = {"隐田"}
        else:
            required = {"起运定额", "官民田", "隐田"}
        if meta.get("source_status") == "no_wanli_accounting_record" \
                and raw_meta_defaults_by_region.get(region_id) != "military_pay_funnel":
            required = set()
        refined = set((meta.get("primary_source") or {}).get("fields_refined", []))
        required -= refined
        source = meta.get("source")
        if isinstance(source, dict) and source.get("title") == "《万历会计录》":
            checked_fields = set(source.get("checked_fields") or [])
            required -= checked_fields
        if "一手核" in meta.get("notes", {}):
            required -= {"起运定额", "官民田"}
        assert required <= provisional, f"{region_id} provisional 缺 {sorted(required - provisional)}"
        if "官民田" in required:
            assert "官民田" in st and "隐田" in st, f"{region_id} 田亩虚字段缺 seed"

    assert checked == 17


def test_jiangnan_core_uses_wanli_huiji_lu_primary_seed(fresh_db):
    expected = {
        "nanzhili": {
            "chapter": "卷十六 南直隶田赋",
            "land": 7938,
            "raw_land_qing": 793846.71,
            "raw_grain_stone": 6011862.1734,
            "raw_transport_stone": 4208303.5214,
            "zhengfu": 30,
            "base_transport": 8.77,
            "sanxiang": 5.953499999999999,
        },
        "zhejiang": {
            "chapter": "卷二 浙江布政司田赋",
            "land": 4670,
            "raw_land_qing": 466969.8,
            "raw_grain_stone": 2522626.7288,
            "raw_transport_stone": 1695738.4281,
            "zhengfu": 23,
            "base_transport": 3.53,
            "sanxiang": 3.5024999999999995,
        },
        "jiangxi": {
            "chapter": "卷三 江西布政司田赋",
            "land": 4012,
            "raw_land_qing": 401151.2711,
            "raw_grain_stone": 2608352.3826,
            "raw_transport_stone": 2254000.0,
            "zhengfu": 22,
            "base_transport": 4.70,
            "sanxiang": 3.009,
        },
        "huguang": {
            "chapter": "卷四 湖广布政司田赋",
            "land": 22162,
            "raw_land_qing": 2216199.401,
            "raw_grain_stone": 2142761.2673,
            "raw_transport_stone": 914400.0,
            "zhengfu": 34,
            "base_transport": 1.91,
            "sanxiang": 16.6215,
        },
    }

    for region_id, exp in expected.items():
        settle = _read_settle(fresh_db, region_id)
        meta = settle["_meta"]
        source = meta.get("source")
        assert isinstance(source, dict), region_id
        assert source["title"] == "《万历会计录》"
        assert source["chapter"] == exp["chapter"]
        assert source["scan_checked"] is True
        expected_checked_fields = {"官民田", "正赋应征", "起运定额"}
        assert set(source["checked_fields"]) == expected_checked_fields
        assert source["conversion"]["grain_silver_liang_per_stone"] == 0.25
        effective_rate = source["conversion"]["effective_silver_liang_per_stone"]
        raw = source["raw"]
        scope_exception = source.get("scope_exception")
        assert raw["官民田_顷"] == pytest.approx(exp["raw_land_qing"], abs=1e-4)
        assert raw["正赋本色_石"] == pytest.approx(exp["raw_grain_stone"], abs=1e-4)
        assert raw["正赋起运本色_石"] == pytest.approx(exp["raw_transport_stone"], abs=1e-4)

        assert settle["st"]["官民田"] == exp["land"]
        assert settle["p"]["正赋应征"] == pytest.approx(exp["zhengfu"], abs=0.01)
        assert meta["正赋起运基线"] == pytest.approx(exp["base_transport"], abs=0.01)
        assert settle["p"]["起运定额"] == pytest.approx(
            exp["base_transport"] + exp["sanxiang"],
            abs=0.01,
        )
        assert "官民田" not in meta.get("provisional", [])
        assert "起运定额" not in meta.get("provisional", [])
        assert "正赋应征" not in meta.get("provisional", [])
        assert scope_exception is None
        assert "隐田" in meta.get("provisional", [])
        assert math.isclose(
            settle["p"]["正赋应征"],
            raw["正赋本色_石"] * effective_rate / 10000 / 12,
            abs_tol=0.01,
        )
