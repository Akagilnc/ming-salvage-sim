"""#659：军队结构化实际驻地 → 财政事实属地 / S7 军镇 / 逃亡人口闭环。

票面根修：station_region=regions.id；station 只做人读细地点；欠饷事实 region
改取 station_region（饷源 pay_source_region 只服务分账）；逃亡落既有
population_transfers。禁止 station 文本解析、第二事实核、第二转移核。
"""

from __future__ import annotations

import os

from ming_sim.db import GameDB
from ming_sim.execution_pressure import build_execution_two_axis_surface
from ming_sim.fiscal_fact_brief import build_fiscal_fact_brief
from ming_sim.issues import apply_score_extraction
from ming_sim.models import Event

# content/classes.json 冻结字面（施工 oracle，非实现推导）
JUNHU_LIAODONG = 230000
JUNHU_DONGJIANG = 95000
LIUMIN_LIAODONG = 0
LIUMIN_DONGJIANG = 0


def _pop(db: GameDB, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _global_population(db: GameDB) -> int:
    return int(db.conn.execute("SELECT COALESCE(SUM(population),0) FROM classes").fetchone()[0])


def _pin_split_arrears(db: GameDB, army_id: str, *, province: float, central: float) -> None:
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears=?, central_pay_arrears=?, arrears=? WHERE id=?",
        (province, central, province + central, army_id),
    )
    db.conn.commit()


def _pseudo_event(title: str = "调防") -> Event:
    return Event(
        id="test_659", title=title, kind="圣旨", summary="",
        urgency=0, severity=0, credibility=100, interests=[], audiences=[],
    )


def _executing_dossier(db, state, region_id: str) -> int:
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text=f"属地差务@{region_id}",
        target_kind="issue",
        target_id=f"errand-{region_id}",
        payload={
            "target_kind": "issue",
            "target_id": f"errand-{region_id}",
            "locality_scope": "none",
            "assignee_id": "毕自严",
            "transaction_category": "清丈",
            "participant_roster": [
                {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
            ],
        },
        participants=[
            {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
        ],
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', region_id=? WHERE id=?",
        (region_id, int(did)),
    )
    db.conn.commit()
    return int(did)


def test_unparseable_station_facts_s7_desertion_restore_follow_station_region(game, tmp_path):
    """station 不可解析文字 + station_region=dongjiang_area：事实/S7/逃亡/restore 只落东江。"""
    db, state, content = game
    # 人读 station 故意不可解析；结构化驻地与饷源分属
    db.conn.execute(
        "UPDATE armies SET station=?, station_region='dongjiang_area',"
        " pay_source_region='liaodong' WHERE id='dongjiang'",
        ("___not_a_place___",),
    )
    _pin_split_arrears(db, "dongjiang", province=40.0, central=20.0)
    assert _pop(db, "军户", "dongjiang_area") == JUNHU_DONGJIANG
    assert _pop(db, "流民", "dongjiang_area") == LIUMIN_DONGJIANG

    entries = build_fiscal_fact_brief(db)
    dong_facts = [
        e for e in entries
        if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
    ]
    assert dong_facts
    assert all(e["region"] == "dongjiang_area" for e in dong_facts)
    assert not any(
        e["subject_id"] == "dongjiang" and e["region"] == "liaodong"
        for e in entries
    )

    _executing_dossier(db, state, "dongjiang_area")
    _executing_dossier(db, state, "liaodong")
    surface = build_execution_two_axis_surface(db, transit_semantics=())
    by_rid = {str(p["region_id"]): p for p in surface["provinces"]}
    dong_garrison = by_rid["dongjiang_area"]["garrison_pressure_rows"]
    assert any(g["army_id"] == "dongjiang" for g in dong_garrison)
    liao_garrison = by_rid["liaodong"]["garrison_pressure_rows"]
    assert not any(g["army_id"] == "dongjiang" for g in liao_garrison)
    assert "\t军镇\tdongjiang_area\t" in surface["tsv"] or any(
        ln.startswith("军镇\tdongjiang_area\t") for ln in surface["tsv"].splitlines()
    )

    total_before = _global_population(db)
    desert_amt = 3000
    applied = apply_score_extraction(db, state, {
        "population_transfers": [{
            "source": "军户@dongjiang_area",
            "target": "流民@dongjiang_area",
            "amount": desert_amt,
            "reason": "逃亡",
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert _pop(db, "军户", "dongjiang_area") == JUNHU_DONGJIANG - desert_amt
    assert _pop(db, "流民", "dongjiang_area") == LIUMIN_DONGJIANG + desert_amt
    # 辽东军户不被串扣
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG
    assert _global_population(db) == total_before

    path = str(tmp_path / "659_restore.db")
    db.conn.commit()
    # 拷贝当前库文件再 reopen（同票 save/restore 接续）
    import shutil
    shutil.copyfile(db.path, path)
    restored = GameDB(path, content)
    try:
        row = restored.conn.execute(
            "SELECT station, station_region, pay_source_region FROM armies WHERE id='dongjiang'"
        ).fetchone()
        assert row["station"] == "___not_a_place___"
        assert row["station_region"] == "dongjiang_area"
        assert row["pay_source_region"] == "liaodong"
        assert _pop(restored, "军户", "dongjiang_area") == JUNHU_DONGJIANG - desert_amt
        assert _pop(restored, "流民", "dongjiang_area") == LIUMIN_DONGJIANG + desert_amt
        r_entries = build_fiscal_fact_brief(restored)
        assert all(
            e["region"] == "dongjiang_area"
            for e in r_entries
            if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
        )
    finally:
        restored.close()
        if os.path.exists(path):
            os.remove(path)


def test_same_pay_source_split_residence_no_cross_book(game):
    """关宁/东江同饷源 liaodong、分属地：事实与逃亡扣减互不串。"""
    db, state, content = game
    g = db.conn.execute(
        "SELECT station_region, pay_source_region FROM armies WHERE id='guanning'"
    ).fetchone()
    d = db.conn.execute(
        "SELECT station_region, pay_source_region FROM armies WHERE id='dongjiang'"
    ).fetchone()
    assert g["pay_source_region"] == d["pay_source_region"] == "liaodong"
    assert g["station_region"] == "liaodong"
    assert d["station_region"] == "dongjiang_area"

    _pin_split_arrears(db, "guanning", province=30.0, central=15.0)
    _pin_split_arrears(db, "dongjiang", province=24.0, central=12.0)

    entries = build_fiscal_fact_brief(db)
    g_regions = {
        e["region"] for e in entries
        if e["subject_id"] == "guanning" and e["metric"] == "分源欠饷月数"
    }
    d_regions = {
        e["region"] for e in entries
        if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
    }
    assert g_regions == {"liaodong"}
    assert d_regions == {"dongjiang_area"}

    applied = apply_score_extraction(db, state, {
        "population_transfers": [
            {
                "source": "军户@liaodong", "target": "流民@liaodong",
                "amount": 1000, "reason": "逃亡", "origin_ref": "盘面自发",
            },
            {
                "source": "军户@dongjiang_area", "target": "流民@dongjiang_area",
                "amount": 500, "reason": "逃亡", "origin_ref": "盘面自发",
            },
        ],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG - 1000
    assert _pop(db, "流民", "liaodong") == LIUMIN_LIAODONG + 1000
    assert _pop(db, "军户", "dongjiang_area") == JUNHU_DONGJIANG - 500
    assert _pop(db, "流民", "dongjiang_area") == LIUMIN_DONGJIANG + 500


def test_redeploy_moves_fact_region_keeps_pay_source(game):
    """真实调防写核：下一投影 region 跟随 station_region；pay_source_region 不变。"""
    db, state, _content = game
    before = db.conn.execute(
        "SELECT station_region, pay_source_region FROM armies WHERE id='dongjiang'"
    ).fetchone()
    assert before["station_region"] == "dongjiang_area"
    pay_src = str(before["pay_source_region"])
    _pin_split_arrears(db, "dongjiang", province=40.0, central=10.0)

    changes = db.apply_army_deltas(
        state, _pseudo_event("东江调防登莱"), None, "兵部",
        {
            "dongjiang": {
                "station": "山东 / 登州",
                "station_region": "shandong",
                "reason": "移镇登莱",
            },
        },
    )
    assert not any(c.get("rejected") for c in changes if isinstance(c, dict))
    row = db.conn.execute(
        "SELECT station, station_region, pay_source_region FROM armies WHERE id='dongjiang'"
    ).fetchone()
    assert row["station"] == "山东 / 登州"
    assert row["station_region"] == "shandong"
    assert row["pay_source_region"] == pay_src == "liaodong"

    entries = build_fiscal_fact_brief(db)
    d_regions = {
        e["region"] for e in entries
        if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
    }
    assert d_regions == {"shandong"}
    assert "dongjiang_area" not in d_regions
    assert "liaodong" not in d_regions


def test_desertion_transfer_conserves_global_population(game):
    """逃亡转移前后 SUM(classes.population) 守恒。"""
    db, state, content = game
    total_before = _global_population(db)
    applied = apply_score_extraction(db, state, {
        "population_transfers": [{
            "source": "军户@liaodong",
            "target": "流民@liaodong",
            "amount": 7777,
            "reason": "逃亡",
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert _global_population(db) == total_before
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG - 7777
    assert _pop(db, "流民", "liaodong") == LIUMIN_LIAODONG + 7777


def test_station_region_rejects_unknown_region_id(game):
    """非空 station_region 必须是已入库 regions.id；不从 station 反推。"""
    db, state, _content = game
    changes = db.apply_army_deltas(
        state, _pseudo_event(), None, "test",
        {"dongjiang": {"station_region": "not_a_real_region", "reason": "坏 id"}},
    )
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected and rejected[0]["field"] == "station_region"
    row = db.conn.execute(
        "SELECT station_region FROM armies WHERE id='dongjiang'"
    ).fetchone()
    assert row["station_region"] == "dongjiang_area"


def test_fresh_seed_station_region_and_class_slices(game):
    """fresh seed：关宁/东江 station_region 与两地军户/流民切片就位。"""
    db, _state, _content = game
    rows = {
        r["id"]: r for r in db.conn.execute(
            "SELECT id, station_region, pay_source_region FROM armies "
            "WHERE id IN ('guanning','dongjiang')"
        ).fetchall()
    }
    assert rows["guanning"]["station_region"] == "liaodong"
    assert rows["dongjiang"]["station_region"] == "dongjiang_area"
    assert rows["guanning"]["pay_source_region"] == rows["dongjiang"]["pay_source_region"] == "liaodong"
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG
    assert _pop(db, "流民", "liaodong") == LIUMIN_LIAODONG
    assert _pop(db, "军户", "dongjiang_area") == JUNHU_DONGJIANG
    assert _pop(db, "流民", "dongjiang_area") == LIUMIN_DONGJIANG
    # 旧档 ensure_column 路径：新列存在且默认空串合法
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(armies)").fetchall()}
    assert "station_region" in cols
