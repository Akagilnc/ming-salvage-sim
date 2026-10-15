"""#1915 新设衙门成为账上实体：建账、月费、月度下落、供料边界、重开接续。"""

from __future__ import annotations

from ming_sim.applier import Provenance, atomic
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.materials import (
    prepare_world_materials,
    write_identity_materials,
)


CHIEF = "毕自严"
OTHER = "杨嗣昌"
YAMEN_NAME = "钱粮稽查司"
MONTHLY_FEE = 12


def _create_yamen_via_dispatch(db, state, *, name=YAMEN_NAME, chief=CHIEF, fee=MONTHLY_FEE):
    return dispatch_declaration(
        db,
        state,
        {
            "yamen_creates": [
                {
                    "name": name,
                    "chief": chief,
                    "monthly_fee": fee,
                    "account": "国库",
                }
            ]
        },
        source=Provenance.player_decree,
        night_id=0,
    )


def _fee_base_amount(db, yamen) -> int:
    cfg = db.fiscal_config.values()
    key = yamen.fiscal_key
    if key in cfg:
        return int(cfg[key])
    base = key if key.endswith("_base") else f"{key}_base"
    if base in cfg:
        return int(cfg[base])
    for item in db.iter_budget_items():
        display = str(item.get("display") or "")
        item_key = str(item.get("key") or "")
        if YAMEN_NAME in display or str(yamen.id) in item_key:
            return int(cfg.get(item_key, 0))
    raise AssertionError(f"月费科目未建；fiscal_key={key!r}")


def test_audience_dispatch_creates_yamen_with_chief_and_monthly_fee(game):
    """从真实声明入口新设衙门：账上有此衙门、主官与月费科目。"""
    db, state, _ = game
    result = _create_yamen_via_dispatch(db, state)

    assert result.yamen_creates.rejected == []
    assert len(result.yamen_creates.applied) == 1
    applied = result.yamen_creates.applied[0]
    yamen_id = int(applied["id"])

    yamen = db.yamens.get(yamen_id)
    assert yamen is not None
    assert yamen.name == YAMEN_NAME
    assert yamen.chief_name == CHIEF
    assert yamen.monthly_fee == MONTHLY_FEE
    assert yamen.status == "active"
    assert yamen.fiscal_key
    assert _fee_base_amount(db, yamen) == MONTHLY_FEE


def test_monthly_fee_deducted_and_progress_recorded(game):
    """经真实过月固定收支入口扣月费；月末文字事实记入该衙门月度下落。"""
    db, state, _ = game
    result = _create_yamen_via_dispatch(db, state)
    yamen = db.yamens.get(int(result.yamen_creates.applied[0]["id"]))
    assert yamen is not None
    yamen_id = int(yamen.id)
    fee_key = yamen.fiscal_key

    with atomic(db):
        apply_fixed_period_flows(db, state)

    # 国库月内还有收入；用流水证明月费科目实扣，不比净余额。
    rows = db.conn.execute(
        "SELECT delta, reason, category FROM economy_ledger "
        "WHERE account='国库' AND delta < 0 ORDER BY id DESC",
    ).fetchall()
    fee_hits = [
        dict(row) for row in rows
        if YAMEN_NAME in str(row["reason"] or "")
        or YAMEN_NAME in str(row["category"] or "")
        or (fee_key and fee_key.removesuffix("_base") in str(row["reason"] or ""))
    ]
    assert fee_hits, f"未见衙门月费扣款流水；sample={ [dict(r) for r in rows[:8]] }"
    assert any(abs(int(row["delta"])) == MONTHLY_FEE for row in fee_hits)

    progress = dispatch_declaration(
        db,
        state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "本月清出隐漏钱粮若干，已移交户部",
                }
            ]
        },
        source=Provenance.system_simulation,
        night_id=0,
    )
    assert progress.textual_facts.rejected == []
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert [f.body for f in facts] == ["本月清出隐漏钱粮若干，已移交户部"]


def test_chief_materials_include_yamen_handler_does_not(game, tmp_path):
    """主官下一场材料有此衙门近况；非主官无关人员没有该衙门材料。"""
    db, state, _ = game
    result = _create_yamen_via_dispatch(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    dispatch_declaration(
        db,
        state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "本月清核各衙门册籍",
                }
            ]
        },
        source=Provenance.system_simulation,
        night_id=0,
    )

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    world_text = "\n".join(
        p.read_text(encoding="utf-8") for p in world.root.rglob("*.txt")
    )
    assert YAMEN_NAME in world_text
    assert "本月清核各衙门册籍" in world_text

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "identity")
    write_identity_materials(prepared, db, state, [CHIEF, OTHER])

    chief_hits = []
    other_hits = []
    for path in prepared.root.rglob("*.txt"):
        path_s = str(path).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        if YAMEN_NAME not in text:
            continue
        if f"人物/{OTHER}/" in path_s or f"/{OTHER}/" in path_s and "可及材料" in path_s:
            # identity materials path is 人物/<name>/可及材料/...
            if OTHER in path_s and CHIEF not in path_s:
                other_hits.append((path_s, text[:200]))
        if CHIEF in path_s:
            chief_hits.append(path_s)

    assert chief_hits, "主官可及材料未见衙门"
    assert other_hits == [], f"非主官不应读到无关衙门材料：{other_hits}"


def test_reload_preserves_yamen_chief_fee_and_progress(game, content):
    """存档重开后只读账本：衙门、主官、月费与历月下落完整接续。"""
    db, state, _ = game
    result = _create_yamen_via_dispatch(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    dispatch_declaration(
        db,
        state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "首月清查完成",
                }
            ]
        },
        source=Provenance.system_simulation,
        night_id=0,
    )
    path = db.path
    db.conn.close()

    reopened = GameDB(path, content)
    try:
        yamen = reopened.yamens.get(yamen_id)
        assert yamen is not None
        assert yamen.name == YAMEN_NAME
        assert yamen.chief_name == CHIEF
        assert yamen.monthly_fee == MONTHLY_FEE
        facts = reopened.textual_facts.readable_materials(
            subject_kind="yamen", subject_id=str(yamen_id),
        )
        assert [f.body for f in facts] == ["首月清查完成"]
        assert _fee_base_amount(reopened, yamen) == MONTHLY_FEE
    finally:
        reopened.conn.close()
