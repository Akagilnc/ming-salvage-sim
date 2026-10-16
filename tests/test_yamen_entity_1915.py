"""#1915 新设衙门成为账上实体：建账、月费、月度下落、供料边界、重开与撤回。"""

from __future__ import annotations

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import open_night
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.flows import apply_fixed_period_flows, fixed_config_amount
from ming_sim.knowledge import origin_visible_to
from ming_sim.materials import (
    prepare_world_materials,
    release_material_tree,
    write_identity_materials,
)
from ming_sim.month_chain import prepare_gazette_author_materials
from ming_sim.month_translate import dispatch_month_segment
from ming_sim.settlement.run import SettlementContext, settle_delta
from tests.conftest import stub_month_translate
from tests.dossier_test_helpers import create_test_secret_order


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


def _audience_yamen_creates(db, state, items, *, minister=CHIEF):
    """真实召对夜入口：一批 yamen_creates。"""
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    result = apply_audience_round_translation(
        db,
        state,
        {"yamen_creates": list(items)},
        night_id=night_id,
        chat_turn_id=chat_turn_id,
        minister_name=minister,
    )
    return result, night_id, chat_turn_id


def _create_yamen_via_night(
    db, state, *, name=YAMEN_NAME, chief=CHIEF, fee=MONTHLY_FEE_WAN,
    account="国库", origin_ref="",
):
    item = {
        "name": name,
        "chief": chief,
        "monthly_fee": fee,
        "account": account,
    }
    if origin_ref:
        item["origin_ref"] = origin_ref
    return _audience_yamen_creates(db, state, [item], minister=chief if chief else CHIEF)


def _yamen_item(name, *, chief=CHIEF, fee=1, account="国库", origin_ref=None, **extra):
    item = {"name": name, "chief": chief, "monthly_fee": fee, **extra}
    if account is not None:
        item["account"] = account
    if origin_ref is not None:
        item["origin_ref"] = origin_ref
    return item


def _fee_base_from_origin(db, yamen_id: int) -> list[dict]:
    return [
        item
        for item in db.list_durable_effects_for_origin(f"yamen:{int(yamen_id)}")
        if str(item.get("effect_kind") or "") == "create"
        and str(item.get("key") or "").endswith("_base")
    ]


def _fiscal_change(db, state, content, *, key: str, delta: int, reason: str):
    out = settle_delta(
        state, db,
        {
            "fiscal_changes": [{
                "key": key,
                "delta": delta,
                "reason": reason,
                "origin_ref": "盘面自发",
            }]
        },
        SettlementContext(content=content),
    )
    assert out.fiscal is not None
    assert out.fiscal.changes.rejected == []
    return out


def _charge_moves(db, yamen_id: int, *, delta: int | None = None) -> list[dict]:
    origin = f"yamen:{int(yamen_id)}"
    moves = [
        item for item in db.reign.list_economy_moves_for_origin(origin)
        if int(item.get("delta") or 0) < 0
    ]
    if delta is not None:
        moves = [m for m in moves if int(m["delta"]) == int(delta)]
    return moves


def _person_paths(root, person: str, *markers: str) -> list[str]:
    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        path_s = str(path).replace("\\", "/")
        if person not in path_s:
            continue
        if all(m in path_s for m in markers):
            out.append(path_s)
    return out


def _yamen_path_exists(root, yamen_name: str = YAMEN_NAME) -> bool:
    return any(
        p.is_file() and "衙门" in str(p).replace("\\", "/") and yamen_name in str(p)
        for p in root.rglob("*")
    )


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
    assert fixed_config_amount(db.fiscal_config.values(), yamen.fiscal_key) == MONTHLY_FEE_WAN


def test_monthly_fee_present_value_follows_fiscal_not_entity_copy(game):
    """合法 base/rate 调额与裁撤后：现值与扣款跟财政 base×rate；实体成立额可保留为历史。

    归属经 fiscal_key→yamen 预算接缝，不锁 live catalogue origin 内部形状。
    """
    db, state, content = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    yamen = db.yamens.get(yamen_id)
    fiscal_key = str(yamen.fiscal_key)
    rate_key = fiscal_key[:-5] + "_rate"
    cfg = db.fiscal_config.values()
    assert fixed_config_amount(cfg, fiscal_key) == MONTHLY_FEE_WAN

    # rate 100→50：现值 6，扣款 -6
    _fiscal_change(db, state, content, key=rate_key, delta=50 - 100, reason="核减月费 rate")
    cfg = db.fiscal_config.values()
    assert cfg.get(rate_key) == 50
    assert cfg.get(fiscal_key) == MONTHLY_FEE_WAN
    assert fixed_config_amount(cfg, fiscal_key) == 6
    assert int(db.yamens.get(yamen_id).monthly_fee) == MONTHLY_FEE_WAN

    with atomic(db):
        apply_fixed_period_flows(db, state)
    assert _charge_moves(db, yamen_id, delta=-6), "rate 调整后扣款须跟 base×rate"

    # base 12→8，rate 仍 50 → 现值 4；成立历史不变；扣款仍挂 yamen
    _fiscal_change(
        db, state, content, key=fiscal_key, delta=8 - MONTHLY_FEE_WAN, reason="核减月费 base",
    )
    cfg = db.fiscal_config.values()
    assert cfg.get(fiscal_key) == 8
    assert fixed_config_amount(cfg, fiscal_key) == 4
    assert int(db.yamens.get(yamen_id).monthly_fee) == MONTHLY_FEE_WAN
    history = db.fiscal_config.changes_for(fiscal_key, "盘面自发")
    assert history, "调额来源须在变更史留痕"

    with atomic(db):
        apply_fixed_period_flows(db, state)
    assert _charge_moves(db, yamen_id, delta=-4), "base 调额后扣款仍须挂 yamen 回指"

    removed = settle_delta(
        state, db,
        {
            "fiscal_removes": [{
                "key": fiscal_key,
                "reason": "裁撤月费",
                "origin_ref": "盘面自发",
            }]
        },
        SettlementContext(content=content),
    )
    assert removed.fiscal is not None
    assert removed.fiscal.removes.rejected == []
    assert fiscal_key not in db.fiscal_config.values()
    assert int(db.yamens.get(yamen_id).monthly_fee) == MONTHLY_FEE_WAN


def test_month_segment_progress_and_reload(game, content, monkeypatch):
    """真实月段入口落进展；存档重开后只读账本接续衙门/主官/成立费/下落。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])

    stub_month_translate(
        monkeypatch,
        lambda _request, _config: {
            "textual_facts": [{
                "subject_kind": "yamen",
                "subject_id": str(yamen_id),
                "body": "首月清查完成",
            }]
        },
    )
    progress = dispatch_month_segment(db, state, segment="世界")
    assert progress.textual_facts.rejected == []
    assert str(yamen_id) in {
        str(item.get("subject_id") or "") for item in progress.textual_facts.applied
    }
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert [f.body for f in facts] == ["首月清查完成"]

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
        base_effects = _fee_base_from_origin(reopened, yamen_id)
        assert base_effects
        assert int(base_effects[0]["value"]) == MONTHLY_FEE_WAN
    finally:
        reopened.conn.close()


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
    assert created_keys.isdisjoint(live)

    with atomic(db):
        apply_fixed_period_flows(db, state)
    leftover = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE origin_ref=? AND delta<0",
        (origin,),
    ).fetchall()
    assert leftover == []


def test_materials_paths_for_chief_handler_and_gazette(game, tmp_path):
    """主官有衙门路径、经手人仅有事务路径；公开衙门进邸报路径。

    材料正文过滤不在此锁子串——以变异真跑观察留证。
    """
    db, state, _ = game
    _create_yamen_via_night(db, state)
    affair = db.affairs.open(
        name="押解银两赴宁远",
        origin="本月派杨嗣昌押解",
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

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    assert _yamen_path_exists(world.root)
    write_identity_materials(world, db, state, [CHIEF, HANDLER])
    assert _person_paths(world.root, CHIEF, "衙门"), "主官可及材料无衙门路径"
    assert _person_paths(world.root, HANDLER, f"affair-{int(affair.id)}"), (
        "经手人未见其经手事务路径"
    )
    assert not _person_paths(world.root, HANDLER, "衙门"), "经手人不应有无关衙门路径"

    gazette = prepare_gazette_author_materials(db, state)
    try:
        assert _yamen_path_exists(gazette.root), "公开衙门须进邸报路径"
    finally:
        release_material_tree(gazette.root)


def test_secret_yamen_hidden_from_public_materials_and_treasury(game, tmp_path):
    """密旨来源的衙门：世界全量保留；邸报不进实体路径；月费 yamen 回指公开不可见。

    含 base 公开调额后：扣款仍挂 yamen 回指（来源边界不因调额断链）。
    """
    db, state, content = game
    order_id = create_test_secret_order(db, state, CHIEF, "密设查弊", "暗中查弊", [])
    origin = f"secret_order:{order_id}"
    created, _night_id, _ctid = _create_yamen_via_night(
        db, state, name="密设查弊司", fee=9, account="内库", origin_ref=origin,
    )
    assert created.yamen_creates.rejected == []
    yamen_id = int(created.yamen_creates.applied[0]["id"])
    yamen = db.yamens.get(yamen_id)
    assert yamen.origin_ref == origin
    fiscal_key = str(yamen.fiscal_key)

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    assert any("衙门" in line for line in world.index_lines)
    assert _yamen_path_exists(world.root, "密设查弊司")

    gazette = prepare_gazette_author_materials(db, state)
    try:
        assert not any("衙门" in line for line in gazette.index_lines)
        assert not _yamen_path_exists(gazette.root, "密设查弊司")
    finally:
        release_material_tree(gazette.root)

    _fiscal_change(db, state, content, key=fiscal_key, delta=8 - 9, reason="核减密衙门月费")

    with atomic(db):
        apply_fixed_period_flows(db, state)
    fee_moves = _charge_moves(db, yamen_id, delta=-8)
    assert fee_moves, "月费须能按 yamen 回指读到（世界/内部账）"
    assert all(
        not origin_visible_to(db, str(item.get("origin_ref") or ""), "")
        for item in fee_moves
    )
    public_fee = [
        item for item in db.reign.list_economy_moves_for_origin("盘面自发")
        if int(item.get("delta") or 0) == -8
    ]
    assert public_fee == []


def test_textual_fact_keeps_origin_and_affair_separate(game):
    """文字事实：origin_ref 存真实来源，affair_id 存事务关联，互不覆盖。"""
    db, state, _ = game
    result, _night_id, _ctid = _create_yamen_via_night(db, state)
    yamen_id = int(result.yamen_creates.applied[0]["id"])
    order_id = create_test_secret_order(db, state, CHIEF, "密查钱粮", "清出隐漏", [])
    origin = f"secret_order:{order_id}"
    affair = db.affairs.open(
        name="密查钱粮",
        origin=origin,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    bad_origins = (
        "yamen:999999",
        "yamen:abc",
        "yamen:-1",
        "yamen:999999oops",
    )
    out = dispatch_declaration(
        db, state,
        {
            "textual_facts": [
                {
                    "subject_kind": "yamen",
                    "subject_id": str(yamen_id),
                    "body": "密旨下清出隐漏",
                    "origin_ref": origin,
                    "affair_declaration": {
                        "attach": "existing",
                        "affair_id": int(affair.id),
                    },
                },
                *[
                    {
                        "subject_kind": "yamen",
                        "subject_id": str(yamen_id),
                        "body": f"坏来源{i}",
                        "origin_ref": bad,
                    }
                    for i, bad in enumerate(bad_origins)
                ],
            ]
        },
        source=Provenance.system_simulation,
    )
    assert len(out.textual_facts.rejected) == len(bad_origins)
    assert len(out.textual_facts.applied) == 1
    facts = db.textual_facts.readable_materials(
        subject_kind="yamen", subject_id=str(yamen_id),
    )
    assert len(facts) == 1
    assert facts[0].origin_ref == origin
    assert int(facts[0].affair_id) == int(affair.id)
    for bad in bad_origins:
        assert origin_visible_to(db, bad, "") is False


def test_yamen_fee_rejects_non_storable_amounts(game):
    """月费拒绝 float 截断与超界整数；合法同批不因坏项丢失。"""
    db, state, _ = game
    result, _night_id, _ctid = _audience_yamen_creates(
        db, state,
        [
            _yamen_item("截断月费司", fee=12.75),
            _yamen_item("超界月费司", fee=9223372036854775808),
            _yamen_item("合法月费司", fee=8),
        ],
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


def test_yamen_origin_rejects_unstorable_and_backref(game):
    """建制来源：回指/超界/不存在/零号均拒；合法同批仍落。"""
    db, state, _ = game
    overflow = "9223372036854775808"
    bad_items = (
        ("回指司", "yamen:2"),
        ("超界密令后缀司", f"secret_order:{overflow}:brief"),
        ("超界案卷后缀司", f"dossier:{overflow}/step"),
        ("超界案卷别名司", f"decree_dossier:{overflow}"),
        ("幻觉密令司", "secret_order:999999"),
        ("幻觉案卷司", "dossier:999999"),
        ("零号案卷司", "dossier:0"),
        ("零号案卷前导零司", "dossier:000"),
        ("零号案卷别名后缀司", "decree_dossier:0/step"),
        ("零号密令司", "secret_order:0"),
    )
    result, _night_id, _ctid = _audience_yamen_creates(
        db, state,
        [
            *(_yamen_item(name, origin_ref=origin) for name, origin in bad_items),
            _yamen_item("公开合法司"),
        ],
    )
    assert len(result.yamen_creates.rejected) == len(bad_items)
    assert len(result.yamen_creates.applied) == 1
    assert [y.name for y in db.yamens.list_active()] == ["公开合法司"]
    closed_origins = (
        f"yamen:{overflow}",
        f"secret_order:{overflow}:brief",
        f"dossier:{overflow}/step",
        "dossier:999999",
        "secret_order:999999",
        "dossier:0",
        "dossier:000",
        "decree_dossier:0/step",
        "secret_order:0",
    )
    for origin in closed_origins:
        assert origin_visible_to(db, origin, "") is False
    assert origin_visible_to(db, "", "") is True
    assert origin_visible_to(db, "廷议传闻", "") is True
    gazette = prepare_gazette_author_materials(db, state)
    try:
        assert any("衙门" in line for line in gazette.index_lines)
    finally:
        release_material_tree(gazette.root)


def test_yamen_chief_status_account_and_zero_fee(game):
    """主官须在事；账户须显式；零月费可建且不造财政科目。"""
    db, state, _ = game
    dead = "袁崇焕"
    dismissed = "孙承宗"
    db.set_character_status(state, dead, "dead", reason="测试", commit=True)
    db.set_character_status(state, dismissed, "dismissed", reason="测试", commit=True)
    offstage_row = db.conn.execute(
        "SELECT name FROM characters WHERE status='offstage' AND name!=? LIMIT 1",
        (CHIEF,),
    ).fetchone()
    offstage = str(offstage_row["name"]) if offstage_row is not None else None

    rejected_items = [
        _yamen_item("死人主官司", chief=dead),
        _yamen_item("革职主官司", chief=dismissed),
        _yamen_item("缺账户司", account=None),
        _yamen_item("空白账户司", account=""),
    ]
    if offstage is not None:
        rejected_items.insert(2, _yamen_item("未登场主官司", chief=offstage))
    applied_items = [
        _yamen_item("零费合法司", fee=0, account="内库"),
        _yamen_item("在事合法司", fee=3),
    ]
    result, _night_id, _ctid = _audience_yamen_creates(
        db, state, [*rejected_items, *applied_items],
    )
    assert len(result.yamen_creates.rejected) == len(rejected_items)
    assert len(result.yamen_creates.applied) == len(applied_items)
    names = {y.name for y in db.yamens.list_active()}
    assert names == {"零费合法司", "在事合法司"}
    zero = next(y for y in db.yamens.list_active() if y.name == "零费合法司")
    assert int(zero.monthly_fee) == 0
    assert zero.fee_account == "内库"
    assert not zero.fiscal_key
    assert _fee_base_from_origin(db, zero.id) == []
    assert not zero.fiscal_key or zero.fiscal_key not in db.fiscal_config.values()
    assert db.characters.get_character_status(dead)[0] == "dead"
    assert db.characters.get_character_status(dismissed)[0] == "dismissed"
