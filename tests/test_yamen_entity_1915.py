"""#1915 新设衙门成为账上实体：建账、月费、月度下落、供料边界、重开与撤回。"""

from __future__ import annotations

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import open_night
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.knowledge import origin_visible_to
from ming_sim.materials import prepare_world_materials, write_identity_materials
from ming_sim.month_chain import prepare_gazette_author_materials
from ming_sim.month_translate import _visible_effect_refs, dispatch_month_segment
from tests.conftest import stub_month_translate


CHIEF = "毕自严"
HANDLER = "杨嗣昌"
YAMEN_NAME = "钱粮稽查司"
# 与 fiscal_config / grant 同契约：月费单位＝万两
MONTHLY_FEE_WAN = 12
PROGRESS_BODY = "本月清出隐漏钱粮若干，已移交户部"


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


def _fee_base_from_origin(db, yamen_id: int) -> list[dict]:
    return [
        item
        for item in db.list_durable_effects_for_origin(f"yamen:{int(yamen_id)}")
        if str(item.get("effect_kind") or "") == "create"
        and str(item.get("key") or "").endswith("_base")
    ]


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

    base_effects = _fee_base_from_origin(db, yamen_id)
    assert base_effects
    assert int(base_effects[0]["value"]) == MONTHLY_FEE_WAN


def test_monthly_fee_by_origin_and_month_segment_progress(game, monkeypatch):
    """过月按 origin_ref 扣月费；真实月段入口据结构化身份记下落。"""
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
    assert moves, "月费须经公开 economy origin 读口可见，不得改查 SQL 兜底"
    assert any(abs(int(m["delta"])) == MONTHLY_FEE_WAN for m in moves)

    captured: dict = {}

    # 结构化效果回指（与提示词排版无关）：月段可见引用须含在职衙门身份
    effect_refs = _visible_effect_refs(db, int(state.turn))
    assert any(
        int(row["id"]) == int(yamen_id) and row["name"] == YAMEN_NAME
        for row in effect_refs.get("yamens") or ()
    ), "月段结构化引用须含在职衙门身份"

    def _month_runner(request, _config):
        captured["request"] = request
        # 主体身份取自账本在职衙门，不解析 target_grounding 排版
        active = [y for y in db.yamens.list_active() if int(y.id) == int(yamen_id)]
        assert active and active[0].name == YAMEN_NAME
        return {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(int(active[0].id)),
                    "body": PROGRESS_BODY,
                }
            ]
        }

    stub_month_translate(monkeypatch, _month_runner)
    progress = dispatch_month_segment(db, state, segment="世界")
    assert "request" in captured  # 真实月段入口已调用转译
    assert progress.textual_facts.rejected == []
    applied_ids = {
        str(item.get("subject_id") or "")
        for item in progress.textual_facts.applied
    }
    assert str(yamen_id) in applied_ids
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert [f.body for f in facts] == [PROGRESS_BODY]


def test_undo_chat_turn_reverses_yamen_fee_and_durable_effects(game):
    """撤回本轮：实体、live 科目与公开 durable 创建效果一并消失，不再扣款。"""
    db, state, _ = game
    result, _night_id, chat_turn_id = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    origin = f"yamen:{yamen_id}"
    assert _fee_base_from_origin(db, yamen_id)

    created_keys = {
        str(item.get("key") or "")
        for item in db.list_durable_effects_for_origin(origin)
        if str(item.get("effect_kind") or "") == "create" and item.get("key")
    }
    assert created_keys, "撤回前应有本轮创建的财政科目 key"

    db.undo_chat_turn(chat_turn_id)

    assert db.yamens.get(yamen_id) is None
    assert db.yamens.list_active() == ()
    assert db.list_durable_effects_for_origin(origin) == []
    live = db.fiscal_config.values()
    # 精确身份：只查本轮创建的 key，不扫子串误伤无关科目
    assert created_keys.isdisjoint(live)

    with atomic(db):
        apply_fixed_period_flows(db, state)
    leftover = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE origin_ref=? AND delta<0",
        (origin,),
    ).fetchall()
    assert leftover == []


def test_chief_sees_yamen_handler_sees_matter_not_yamen(game, tmp_path):
    """主官目录有衙门路径；经手人有事务路径、无衙门路径。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])

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
    db.affairs.attach_pointer("decree_dossiers", int(dossier_id), int(affair.id))

    # 推演目录含该衙门（结构化：list_for_chief / list_active 非空且路径存在）
    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    world_yamen_paths = [
        p for p in world.root.rglob("*")
        if p.is_file() and "衙门" in str(p).replace("\\", "/")
    ]
    assert world_yamen_paths
    assert db.yamens.list_active() and int(db.yamens.list_active()[0].id) == yamen_id

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "identity")
    write_identity_materials(prepared, db, state, [CHIEF, HANDLER])

    def _paths_for(person: str, *markers: str) -> list:
        out = []
        for path in prepared.root.rglob("*"):
            if not path.is_file():
                continue
            path_s = str(path).replace("\\", "/")
            if person not in path_s:
                continue
            if all(m in path_s for m in markers):
                out.append(path_s)
        return out

    assert _paths_for(CHIEF, "衙门"), "主官可及材料无衙门路径"
    # 经手事务目录键＝affair-{id}（结构化路径，非正文模板）
    assert _paths_for(HANDLER, f"affair-{int(affair.id)}"), "经手人未见其经手事务路径"
    assert not _paths_for(HANDLER, "衙门"), "经手人不应有无关衙门路径"


def test_reload_preserves_yamen_chief_fee_and_progress(game, content, monkeypatch):
    """存档重开后只读账本：衙门、主官、月费与历月下落完整接续。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])

    def _month_runner(request, _config):
        active = [y for y in db.yamens.list_active() if int(y.id) == int(yamen_id)]
        assert active
        return {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(int(active[0].id)),
                    "body": "首月清查完成",
                }
            ]
        }

    stub_month_translate(monkeypatch, _month_runner)
    dispatch_month_segment(db, state, segment="世界")

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
        base_effects = [
            item
            for item in reopened.list_durable_effects_for_origin(f"yamen:{yamen_id}")
            if str(item.get("effect_kind") or "") == "create"
            and str(item.get("key") or "").endswith("_base")
        ]
        assert base_effects
        assert int(base_effects[0]["value"]) == MONTHLY_FEE_WAN
    finally:
        reopened.conn.close()


def test_textual_fact_keeps_origin_and_affair_separate(game):
    """文字事实：origin_ref 存真实来源，affair_id 存事务关联，互不覆盖。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    affair = db.affairs.open(
        name="密查钱粮",
        origin="secret_order:1",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    out = dispatch_declaration(
        db, state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "密旨下清出隐漏",
                    "origin_ref": "secret_order:1",
                    "affair_declaration": {
                        "attach": "existing",
                        "affair_id": int(affair.id),
                    },
                }
            ]
        },
        source=Provenance.system_simulation,
    )
    assert out.textual_facts.rejected == []
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert len(facts) == 1
    assert facts[0].origin_ref == "secret_order:1"
    assert int(facts[0].affair_id) == int(affair.id)


def test_yamen_fee_rejects_non_storable_amounts(game):
    """月费拒绝 float 截断与超界整数；合法同批不因坏项丢失。"""
    db, state, _ = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    result = apply_audience_round_translation(
        db, state,
        {
            "yamen_creates": [
                {
                    "name": "截断月费司",
                    "chief": CHIEF,
                    "monthly_fee": 12.75,
                    "account": "国库",
                },
                {
                    "name": "超界月费司",
                    "chief": CHIEF,
                    "monthly_fee": 9223372036854775808,
                    "account": "国库",
                },
                {
                    "name": "合法月费司",
                    "chief": CHIEF,
                    "monthly_fee": 8,
                    "account": "国库",
                },
            ]
        },
        night_id=night_id,
        chat_turn_id=chat_turn_id,
        minister_name=CHIEF,
    )
    assert len(result.yamen_creates.rejected) == 2
    assert len(result.yamen_creates.applied) == 1
    assert int(result.yamen_creates.applied[0]["monthly_fee"]) == 8
    assert [y.name for y in db.yamens.list_active()] == ["合法月费司"]


def test_yamen_fact_overflow_id_rejects_without_batch_crash(game):
    """超界衙门 id 逐项拒收，不抛 OverflowError，同批合法事实仍落。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    out = dispatch_declaration(
        db, state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": "9223372036854775808",
                    "body": "坏引用",
                },
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "合法下落",
                },
            ]
        },
        source=Provenance.system_simulation,
    )
    assert len(out.textual_facts.rejected) == 1
    assert len(out.textual_facts.applied) == 1
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert [f.body for f in facts] == ["合法下落"]


def test_yamen_fact_normalizes_numeric_subject_id(game):
    """数值主体 '02' 规范化为 '2'，按实体身份可读。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    padded = f"{yamen_id:02d}" if yamen_id < 10 else f"0{yamen_id}"
    assert padded != str(yamen_id)
    out = dispatch_declaration(
        db, state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": padded,
                    "body": "规范化下落",
                }
            ]
        },
        source=Provenance.system_simulation,
    )
    assert out.textual_facts.rejected == []
    assert out.textual_facts.applied[0]["subject_id"] == str(yamen_id)
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert [f.body for f in facts] == ["规范化下落"]


def test_secret_yamen_hidden_from_public_materials_and_treasury(game, tmp_path):
    """密旨来源的衙门：世界全量保留；邸报不进实体路径；月费 yamen 回指公开不可见。"""
    from ming_sim.materials import release_material_tree

    db, state, _ = game
    origin = "secret_order:1"
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    created = apply_audience_round_translation(
        db, state,
        {
            "yamen_creates": [
                {
                    "name": "密设查弊司",
                    "chief": CHIEF,
                    "monthly_fee": 9,
                    "account": "内库",
                    "origin_ref": origin,
                }
            ]
        },
        night_id=night_id,
        chat_turn_id=chat_turn_id,
        minister_name=CHIEF,
    )
    assert created.yamen_creates.rejected == []
    yamen_id = int(created.yamen_creates.applied[0]["id"])
    yamen_origin = f"yamen:{yamen_id}"
    assert db.yamens.get(yamen_id).origin_ref == origin
    assert origin_visible_to(db, origin, "") is False
    assert origin_visible_to(db, yamen_origin, "") is False

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    assert any("衙门" in line for line in world.index_lines)

    gazette = prepare_gazette_author_materials(db, state)
    try:
        assert not any("衙门" in line for line in gazette.index_lines)
    finally:
        release_material_tree(gazette.root)

    with atomic(db):
        apply_fixed_period_flows(db, state)
    fee_moves = [
        item for item in db.reign.list_economy_moves_for_origin(yamen_origin)
        if int(item.get("delta") or 0) < 0
    ]
    assert fee_moves, "月费须能按 yamen 回指读到（世界/内部账）"
    assert all(
        not origin_visible_to(db, str(item.get("origin_ref") or ""), "")
        for item in fee_moves
    )


def test_yamen_origin_rejects_unstorable_and_backref(game):
    """建制来源：yamen 回指与读口同形的超界密令/案卷 id 均拒；合法同批仍落。"""
    from ming_sim.materials import release_material_tree

    db, state, _ = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    overflow = "9223372036854775808"
    result = apply_audience_round_translation(
        db, state,
        {
            "yamen_creates": [
                {
                    "name": "回指司",
                    "chief": CHIEF,
                    "monthly_fee": 1,
                    "account": "国库",
                    "origin_ref": "yamen:2",
                },
                {
                    "name": "超界密令后缀司",
                    "chief": CHIEF,
                    "monthly_fee": 1,
                    "account": "国库",
                    "origin_ref": f"secret_order:{overflow}:brief",
                },
                {
                    "name": "超界案卷后缀司",
                    "chief": CHIEF,
                    "monthly_fee": 1,
                    "account": "国库",
                    "origin_ref": f"dossier:{overflow}/step",
                },
                {
                    "name": "超界案卷别名司",
                    "chief": CHIEF,
                    "monthly_fee": 1,
                    "account": "国库",
                    "origin_ref": f"decree_dossier:{overflow}",
                },
                {
                    "name": "公开合法司",
                    "chief": CHIEF,
                    "monthly_fee": 1,
                    "account": "国库",
                },
            ]
        },
        night_id=night_id,
        chat_turn_id=chat_turn_id,
        minister_name=CHIEF,
    )
    assert len(result.yamen_creates.rejected) == 4
    assert len(result.yamen_creates.applied) == 1
    assert [y.name for y in db.yamens.list_active()] == ["公开合法司"]
    # 读口对不可存储身份 fail-closed，且不 OverflowError
    assert origin_visible_to(db, f"yamen:{overflow}", "") is False
    assert origin_visible_to(db, f"secret_order:{overflow}:brief", "") is False
    assert origin_visible_to(db, f"dossier:{overflow}/step", "") is False
    gazette = prepare_gazette_author_materials(db, state)
    try:
        assert any("衙门" in line for line in gazette.index_lines)
    finally:
        release_material_tree(gazette.root)
