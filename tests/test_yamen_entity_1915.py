"""#1915 新设衙门成为账上实体：建账、月费、月度下落、供料边界、重开与撤回。"""

from __future__ import annotations

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import open_night
from ming_sim.audience_translate import build_translation_target_grounding
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.flows import apply_fixed_period_flows, compute_budget_lines
from ming_sim.materials import prepare_world_materials, write_identity_materials
from ming_sim.month_translate import _visible_effect_refs


CHIEF = "毕自严"
HANDLER = "杨嗣昌"
YAMEN_NAME = "钱粮稽查司"
# 与 fiscal_config / grant 同契约：月费单位＝万两
MONTHLY_FEE_WAN = 12


def _active_chat_turn(db, state, night_id: int) -> int:
    return int(
        db.create_chat_turn(
            state,
            minister_name=CHIEF,
            agno_session_id="test-yamen-1915",
            agno_runs_before=0,
            night_id=int(night_id),
            status="active",
        )
    )


def _create_yamen_via_night(db, state, *, name=YAMEN_NAME, chief=CHIEF, fee=MONTHLY_FEE_WAN):
    """真实召对夜入口：apply_audience_round_translation + 源轮前像。"""
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    result = apply_audience_round_translation(
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
        night_id=night_id,
        chat_turn_id=chat_turn_id,
        minister_name=chief,
    )
    return result, night_id, chat_turn_id


def test_audience_night_creates_yamen_with_chief_and_monthly_fee(game):
    """从真实召对入口新设衙门：账上有此衙门、主官与月费科目（万两）。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)

    assert result.yamen_creates.rejected == []
    assert len(result.yamen_creates.applied) == 1
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    yamen = db.yamens.get(yamen_id)
    assert yamen is not None
    assert yamen.name == YAMEN_NAME
    assert yamen.chief_name == CHIEF
    assert yamen.monthly_fee == MONTHLY_FEE_WAN
    assert yamen.fiscal_key

    effects = db.fiscal_config.effects_for_origin(f"yamen:{yamen_id}")
    base_effects = [
        item for item in effects
        if str(item.get("key") or "").endswith("_base")
    ]
    assert base_effects, f"月费科目未挂 origin_ref；effects={effects}"
    assert int(base_effects[0]["value"]) == MONTHLY_FEE_WAN


def test_monthly_fee_deducted_by_origin_and_progress_via_grounding(game):
    """过月按 origin_ref 扣月费；月末身份目录可把名称映射为 id 再记下落。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    origin = f"yamen:{yamen_id}"

    with atomic(db):
        apply_fixed_period_flows(db, state)

    moves = [
        item for item in db.reign.list_economy_moves_for_origin(origin)
        if int(item.get("delta") or 0) < 0
    ]
    # 固定收支也可只在 fiscal 侧；流水 origin_ref 由 budget line 透传
    if not moves:
        rows = db.conn.execute(
            "SELECT delta, origin_ref FROM economy_ledger "
            "WHERE origin_ref=? AND delta<0 ORDER BY id",
            (origin,),
        ).fetchall()
        moves = [dict(row) for row in rows]
    assert moves, f"未见 origin_ref={origin} 的月费扣款"
    assert any(abs(int(m["delta"])) == MONTHLY_FEE_WAN for m in moves)

    # 身份供给：权威目录与 visible refs 均带名称
    grounding = build_translation_target_grounding(db, state)
    assert f"yamen\t{yamen_id}\t{YAMEN_NAME}" in grounding
    refs = _visible_effect_refs(db, int(state.turn))
    assert {"id": yamen_id, "name": YAMEN_NAME} in refs.get("yamens", [])

    # 转译按目录 id 记下落（不猜）
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


def test_undo_chat_turn_reverses_yamen_and_monthly_fee(game):
    """撤回本轮：衙门实体与月费科目一并消失，不再扣款。"""
    db, state, _ = game
    result, _night_id, chat_turn_id = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    origin = f"yamen:{yamen_id}"
    assert db.yamens.get(yamen_id) is not None
    assert db.fiscal_config.effects_for_origin(origin)

    fee_keys_before = [
        str(item.get("key") or "")
        for item in db.fiscal_config.effects_for_origin(origin)
        if str(item.get("key") or "").endswith("_base")
    ]
    assert fee_keys_before

    db.undo_chat_turn(chat_turn_id)

    assert db.yamens.get(yamen_id) is None
    assert db.yamens.list_active() == ()
    # 活科目须逆转；append-only 创建史不挡扣款（扣款只读 live fiscal_config）
    live = db.fiscal_config.values()
    for key in fee_keys_before:
        assert key not in live, f"撤回后月费科目仍在 live：{key}"

    budget = compute_budget_lines(db, state)
    expense_names = [str(it.get("name") or "") for it in budget["国库"]["expense"]]
    assert not any(YAMEN_NAME in name for name in expense_names)

    with atomic(db):
        apply_fixed_period_flows(db, state)
    leftover = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE origin_ref=? AND delta<0",
        (origin,),
    ).fetchall()
    assert leftover == []


def test_chief_sees_yamen_handler_sees_matter_not_yamen(game, tmp_path):
    """主官读整本衙门；经手人只读其经手事务，不读无关衙门整本。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
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

    # 经手人另有一事（dossier 参与 → 可见事务；与衙门整本无关）
    matter_name = "押解银两赴宁远"
    affair = db.affairs.open(
        name=matter_name,
        origin="本月派杨嗣昌押解",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair",
        subject_id=str(int(affair.id)),
        body="银两已出京，尚未抵宁远",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="着杨嗣昌押解银两赴宁远",
        target_kind="character",
        target_id=HANDLER,
        executor_kind="character",
        executor_id=HANDLER,
        payload={"assignee": HANDLER},
        status="proposed",
        participants=[{
            "character_id": HANDLER,
            "tier": "主办",
            "role": "押解",
            "delegator_id": None,
        }],
        commit=True,
    )
    # proposed 即可：材料投影只认参与人+affair_id，不按 status 过滤。
    db.affairs.attach_pointer("decree_dossiers", int(dossier_id), int(affair.id))

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    world_text = "\n".join(p.read_text(encoding="utf-8") for p in world.root.rglob("*.txt"))
    assert YAMEN_NAME in world_text
    assert "本月清核各衙门册籍" in world_text
    assert f"id：{yamen_id}" in world_text

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "identity")
    write_identity_materials(prepared, db, state, [CHIEF, HANDLER])

    chief_yamen = []
    handler_yamen = []
    handler_matter = []
    for path in prepared.root.rglob("*.txt"):
        path_s = str(path).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        if CHIEF in path_s and YAMEN_NAME in text:
            chief_yamen.append(path_s)
        if HANDLER in path_s and YAMEN_NAME in text:
            handler_yamen.append(path_s)
        if HANDLER in path_s and matter_name in text:
            handler_matter.append(path_s)

    assert chief_yamen, "主官可及材料未见衙门整本"
    assert handler_matter, "经手人未见其经手事务"
    assert handler_yamen == [], f"经手人不应读到无关衙门整本：{handler_yamen}"


def test_reload_preserves_yamen_chief_fee_and_progress(game, content):
    """存档重开后只读账本：衙门、主官、月费与历月下落完整接续。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
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
        assert yamen.monthly_fee == MONTHLY_FEE_WAN
        facts = reopened.textual_facts.readable_materials(
            subject_kind="yamen", subject_id=str(yamen_id),
        )
        assert [f.body for f in facts] == ["首月清查完成"]
        effects = reopened.fiscal_config.effects_for_origin(f"yamen:{yamen_id}")
        assert any(
            str(item.get("key") or "").endswith("_base")
            and int(item.get("value") or 0) == MONTHLY_FEE_WAN
            for item in effects
        )
    finally:
        reopened.conn.close()
