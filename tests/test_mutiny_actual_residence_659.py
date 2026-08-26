"""#659：军队结构化实际驻地 → 财政事实属地 / S7 军镇 / 逃亡人口闭环。

票面根修：station_region=regions.id；station 只做人读细地点；欠饷事实 region
改取 station_region（饷源 pay_source_region 只服务分账）；逃亡落既有
population_transfers。禁止 station 文本解析、第二事实核、第二转移核。

主行为闭环（#659 判词）：simulator / internal extractor 输入面同时可见哗变
（zero_combat）／长期分源欠饷／station_region 与该省军户·流民余额，再沿
apply_score_extraction 落既有 shape 的 reason=逃亡 转移并守恒记账。
"""

from __future__ import annotations

import os
import shutil

from ming_sim.db import GameDB
from ming_sim.execution_pressure import build_execution_two_axis_surface
from ming_sim.fiscal_fact_brief import build_fiscal_fact_brief
from ming_sim.issues import apply_score_extraction
from ming_sim.models import Event
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload

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


def _simulator_army_dicts(payload_armies):
    if isinstance(payload_armies, dict) and "rows" in payload_armies:
        cols = payload_armies.get("cols") or payload_armies.get("columns") or []
        return [dict(zip(cols, row)) for row in payload_armies["rows"]]
    return list(payload_armies)


def test_mutiny_arrears_desertion_real_payload_tracer(game, tmp_path):
    """真实入口 tracer：盘面哗变+长期欠饷+station_region → simulator/extractor 可见 → 逃亡落账守恒。

    只构造盘面事实与既有 shape 的 population_transfers；不 fake 触发公式、
    不 grep prompt 文案、不加第二转移核。S7 军镇属地同缝顺带钉住。
    """
    db, state, content = game
    # 人读 station 故意不可解析；结构化驻地与饷源分属；闩哗变 + 分源长期欠饷
    db.conn.execute(
        "UPDATE armies SET station=?, station_region='dongjiang_area',"
        " pay_source_region='liaodong', is_mutinied=1, loyalty=10 WHERE id='dongjiang'",
        ("___not_a_place___",),
    )
    _pin_split_arrears(db, "dongjiang", province=40.0, central=20.0)
    assert _pop(db, "军户", "dongjiang_area") == JUNHU_DONGJIANG
    assert _pop(db, "流民", "dongjiang_area") == LIUMIN_DONGJIANG
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG

    # 1) simulator 输入面：zero_combat / station_region / 分源欠饷属地=驻地
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    armies = _simulator_army_dicts(payload["armies"])
    dong = next(
        a for a in armies
        if "东江" in str(a.get("name", "")) or str(a.get("id", "")) == "dongjiang"
    )
    assert dong.get("zero_combat") is True
    assert dong.get("station_region") == "dongjiang_area"
    assert "is_mutinied" not in dong

    fiscal = payload["fiscal_fact_brief"]
    dong_arrears = [
        e for e in fiscal
        if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
    ]
    assert dong_arrears
    assert all(e["region"] == "dongjiang_area" for e in dong_arrears)
    assert all(int(e["window_turns"]) >= 1 for e in dong_arrears)
    assert not any(
        e["subject_id"] == "dongjiang" and e["region"] == "liaodong"
        for e in fiscal
    )

    # 2) internal extractor 输入面：该驻地省军户/流民余额可见
    context = build_extractor_shared_context(
        db, state, "东江驻军哗变日久，军户私逃为流民。", "", module="internal",
    )
    balances = context["class_population_balances"]
    assert balances["cols"] == ["class_region", "population", "population_unit"]
    assert any(row[:2] == ["军户@dongjiang_area", JUNHU_DONGJIANG] for row in balances["rows"])
    assert any(row[:2] == ["流民@dongjiang_area", LIUMIN_DONGJIANG] for row in balances["rows"])

    # 3) S7 军镇压力按 station_region 挂属地（既有契约，不新开核）
    _executing_dossier(db, state, "dongjiang_area")
    _executing_dossier(db, state, "liaodong")
    surface = build_execution_two_axis_surface(db, transit_semantics=())
    by_rid = {str(p["region_id"]): p for p in surface["provinces"]}
    assert any(g["army_id"] == "dongjiang" for g in by_rid["dongjiang_area"]["garrison_pressure_rows"])
    assert not any(g["army_id"] == "dongjiang" for g in by_rid["liaodong"]["garrison_pressure_rows"])

    # 4) 沿既有 applier 申报 reason=逃亡；守恒、属地不串
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
    assert _pop(db, "军户", "liaodong") == JUNHU_LIAODONG  # 非驻地省不串
    assert _global_population(db) == total_before

    # 5) save/restore 只读 DB 接续
    path = str(tmp_path / "659_restore.db")
    db.conn.commit()
    shutil.copyfile(db.path, path)
    restored = GameDB(path, content)
    try:
        row = restored.conn.execute(
            "SELECT station, station_region, pay_source_region, is_mutinied "
            "FROM armies WHERE id='dongjiang'"
        ).fetchone()
        assert row["station"] == "___not_a_place___"
        assert row["station_region"] == "dongjiang_area"
        assert row["pay_source_region"] == "liaodong"
        assert int(row["is_mutinied"]) == 1
        assert _pop(restored, "军户", "dongjiang_area") == JUNHU_DONGJIANG - desert_amt
        assert _pop(restored, "流民", "dongjiang_area") == LIUMIN_DONGJIANG + desert_amt
        r_entries = build_fiscal_fact_brief(restored)
        assert all(
            e["region"] == "dongjiang_area"
            for e in r_entries
            if e["subject_id"] == "dongjiang" and e["metric"] == "分源欠饷月数"
        )
        r_payload = build_simulator_payload(
            restored.load_state(), restored, decree_text="", previous_narrative="",
        )
        r_dong = next(
            a for a in _simulator_army_dicts(r_payload["armies"])
            if "东江" in str(a.get("name", "")) or str(a.get("id", "")) == "dongjiang"
        )
        assert r_dong.get("zero_combat") is True
        assert r_dong.get("station_region") == "dongjiang_area"
    finally:
        restored.close()
        if os.path.exists(path):
            os.remove(path)


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
