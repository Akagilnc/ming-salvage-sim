"""#321 — 玩家军心/士气/欠饷投影：复用 derive + qualitative/arrears helper，四链去 raw。"""
from __future__ import annotations

import contextlib
import io
import sqlite3
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.db import (
    GameDB,
    _army_arrears_report_text,
    _player_army_situation,
    _qualitative_army_stat,
    mutiny_loyalty_cap,
)
from ming_sim.flows import apply_fixed_period_flows, derive_army_mutiny_state
from ming_sim.intelligence import _qualitative_domain_statement
from ming_sim.knowledge import build_character_knowledge
from ming_sim.models import CourtContext
from ming_sim.report import print_header
from ming_sim.tools import build_board_query_tools, build_minister_tools

ARMY = "guanning"
PATHS = ("legacy", "substrate_hub")

# 旧 loyalty 五档词——玩家链不得再出现
_LEGACY_LOYALTY_WORDS = ("危殆", "浮动", "不稳", "稳固")
_RAW_KEYS = frozenset({"morale", "loyalty", "arrears"})
_SIT_KEYS = frozenset({"mutiny_tier", "morale_text", "arrears_text"})
_MUTINY_ORDINAL_KEYS = frozenset(
    {
        "is_mutinied",
        "mutiny_count",
        "mutiny_probation",
        "full_pay_streak",
        "redemption_count",
        "mutiny_status",
        "mutiny_level",
        "mutiny_state",
    }
)
_PERSISTENT_COL_TOKENS = (
    "is_mutinied",
    "mutiny_count",
    "mutiny_probation",
    "full_pay_streak",
    "redemption_count",
)

# 六档真值表（票面 latch / 边界 / probation；含全部明确边界样本）
_TIER_CASES = (
    # (is_mutinied, loyalty, probation, expected_tier)
    (1, 100, 0, "哗变"),  # latch L=100
    (1, 100, 1, "哗变"),  # latch 盖过 probation
    (1, 95, 0, "哗变"),
    (1, 10, 3, "哗变"),
    (0, 39, 0, "鼓噪"),
    (0, 19, 0, "鼓噪"),  # L<20 未闩 → 鼓噪，非哗变
    (0, 30, 1, "鼓噪"),  # probation 不覆盖低档
    (0, 40, 0, "不满"),
    (0, 50, 1, "不满"),  # probation 不覆盖中低档
    (0, 59, 0, "不满"),
    (0, 60, 1, "不满"),  # probation 只挡回正常
    (0, 80, 2, "不满"),
    (0, 60, 0, "一般"),
    (0, 69, 0, "一般"),
    (0, 70, 0, "优秀"),
    (0, 79, 0, "优秀"),
    (0, 80, 0, "死忠"),
    (0, 100, 0, "死忠"),
)

_TIER_IDS = [
    f"L{loyalty}-latch{latch}-p{prob}-{tier}"
    for latch, loyalty, prob, tier in _TIER_CASES
]


def _row(
    *,
    is_mutinied: int = 0,
    loyalty: int = 70,
    mutiny_probation: int = 0,
    morale: int = 73,
    arrears: float = 0.0,
    **extra,
):
    base = {
        "is_mutinied": is_mutinied,
        "loyalty": loyalty,
        "mutiny_probation": mutiny_probation,
        "morale": morale,
        "arrears": arrears,
    }
    base.update(extra)
    return base


@pytest.mark.parametrize(
    "is_mutinied,loyalty,probation,expected",
    _TIER_CASES,
    ids=_TIER_IDS,
)
def test_player_army_situation_six_tier_truth_table(
    is_mutinied, loyalty, probation, expected
):
    row = _row(is_mutinied=is_mutinied, loyalty=loyalty, mutiny_probation=probation)
    sit = _player_army_situation(row, monthly_pay=10)
    assert sit["mutiny_tier"] == expected
    assert sit["morale_text"] == _qualitative_army_stat("morale", row["morale"])
    assert sit["arrears_text"] == _army_arrears_report_text(row, 10)
    # derive 非「正常」时档名必须与 derive 一致；正常时再细分
    derived = derive_army_mutiny_state(row)
    if derived != "正常":
        assert sit["mutiny_tier"] == derived
    else:
        assert sit["mutiny_tier"] in ("一般", "优秀", "死忠")


def test_player_army_situation_arrears_is_approximate_only():
    row = _row(arrears=12.5, morale=50)
    sit = _player_army_situation(row, monthly_pay=4)
    text = sit["arrears_text"]
    assert text == _army_arrears_report_text(row, 4)
    assert "12.5" not in text
    assert text.startswith("欠饷") or text == "无欠饷"


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


def _write_mutiny_fixture(
    db,
    fiscal_path: str,
    *,
    loyalty: int,
    arrears: float,
    is_mutinied: int,
    mutiny_count: int,
    mutiny_probation: int,
    full_pay_streak: int,
    redemption_count: int,
    morale: int = 55,
) -> None:
    central = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           mutiny_count=?, mutiny_probation=?, full_pay_streak=?, redemption_count=?,
           morale=?, province_pay_arrears=0, central_pay_arrears=?,
           manpower=10000, owner_power='ming'
           WHERE id=?""",
        (
            loyalty,
            arrears,
            is_mutinied,
            mutiny_count,
            mutiny_probation,
            full_pay_streak,
            redemption_count,
            morale,
            central,
            ARMY,
        ),
    )
    db.conn.commit()


def _payload_by_id(db):
    return {p["id"]: p for p in db.army_payload()}


def _web_runtime(db, state, content):
    """轻壳 WebGame：走真实 state_payload / map_nodes（session 属性代理 db/state）。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary="",
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.ending_payload = lambda: None
    runtime.budget_payload = lambda: {}
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime._month_open_snapshot = lambda: None
    runtime._display_metrics = lambda: dict(state.metrics)
    # 真实 map_nodes（army_payload 片段挂到节点）
    runtime.map_nodes = lambda: web_app.WebGame.map_nodes(runtime)
    runtime._army_belongs_to_theater = (
        lambda army, tid: web_app.WebGame._army_belongs_to_theater(runtime, army, tid)
    )
    runtime._army_belongs_to_region = (
        lambda army, region: web_app.WebGame._army_belongs_to_region(
            runtime, army, region
        )
    )
    runtime._theater_label = lambda tid: web_app.WebGame._theater_label(runtime, tid)
    return runtime


def _find_army_in_map_nodes(nodes, army_id: str = ARMY):
    for node in nodes:
        for army in node.get("armies") or []:
            if army.get("id") == army_id:
                return army
    raise AssertionError(f"map_nodes 未挂载军队 {army_id}")


def _assert_structured_situation(card: dict, sit: dict, label: str) -> None:
    assert _SIT_KEYS <= set(card.keys()), f"{label} 缺 situation 三键: {sorted(card)}"
    assert _RAW_KEYS.isdisjoint(card.keys()), f"{label} 泄漏 raw 轴: {sorted(_RAW_KEYS & set(card.keys()))}"
    assert _MUTINY_ORDINAL_KEYS.isdisjoint(card.keys()), (
        f"{label} 泄漏 mutiny ordinal/五持久列: {sorted(_MUTINY_ORDINAL_KEYS & set(card.keys()))}"
    )
    assert card["mutiny_tier"] == sit["mutiny_tier"], f"{label}.mutiny_tier"
    assert card["morale_text"] == sit["morale_text"], f"{label}.morale_text"
    assert card["arrears_text"] == sit["arrears_text"], f"{label}.arrears_text"
    assert isinstance(card["mutiny_tier"], str)
    assert isinstance(card["morale_text"], str)
    assert isinstance(card["arrears_text"], str)
    joined = f"{card['mutiny_tier']}|{card['morale_text']}|{card['arrears_text']}"
    for word in _LEGACY_LOYALTY_WORDS:
        assert word not in joined, f"{label} 残留旧 loyalty 五档词 {word!r}"


def _assert_chain_embeds_situation(text: str, sit: dict, label: str, *, row=None) -> None:
    assert sit["mutiny_tier"] in text, f"{label} 缺 mutiny_tier={sit['mutiny_tier']!r}\n{text}"
    assert sit["morale_text"] in text, f"{label} 缺 morale_text={sit['morale_text']!r}\n{text}"
    assert sit["arrears_text"] in text, f"{label} 缺 arrears_text={sit['arrears_text']!r}\n{text}"
    for word in _LEGACY_LOYALTY_WORDS:
        assert word not in text, f"{label} 残留旧 loyalty 五档词 {word!r}\n{text}"
    for token in _PERSISTENT_COL_TOKENS:
        assert token not in text, f"{label} 泄漏五持久列名 {token!r}\n{text}"
    # 禁止「忠诚：NN」裸 loyalty 序数呈现
    if row is not None:
        loyalty = int(row["loyalty"])
        assert f"忠诚：{loyalty}" not in text, f"{label} 泄漏忠诚裸数\n{text}"
        morale = int(row["morale"])
        # 士气裸数不得作为独立呈现；situation 串已嵌入则允许子串巧合
        if str(morale) in text:
            assert sit["morale_text"] in text
            # 禁「士气：NN」数值形态
            assert f"士气：{morale}" not in text, f"{label} 泄漏士气裸数\n{text}"


def test_army_payload_emits_situation_strings_not_raw_axes(game):
    db, _state, _ = game
    _configure(db, "legacy")
    _write_mutiny_fixture(
        db,
        "legacy",
        loyalty=55,
        arrears=12.5,
        is_mutinied=0,
        mutiny_count=0,
        mutiny_probation=0,
        full_pay_streak=0,
        redemption_count=0,
        morale=73,
    )
    card = _payload_by_id(db)[ARMY]
    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    pay = db._army_pay(row)
    expected = _player_army_situation(row, pay)

    _assert_structured_situation(card, expected, "army_payload")
    assert card["mutiny_tier"] == "不满"
    assert "12.5" not in f"{card['mutiny_tier']}|{card['morale_text']}|{card['arrears_text']}"


@pytest.mark.parametrize(
    "is_mutinied,loyalty,probation,expected",
    _TIER_CASES,
    ids=_TIER_IDS,
)
def test_four_chains_embed_situation_matrix(
    game, is_mutinied, loyalty, probation, expected
):
    """AC1：共享六档矩阵逐出口覆盖链1–4（含 warning/intel/knowledge/tools/map_nodes）。"""
    db, state, content = game
    _configure(db, "legacy")
    arrears = 63.0 if expected in ("不满", "鼓噪", "哗变") else 0.0
    _write_mutiny_fixture(
        db,
        "legacy",
        loyalty=loyalty,
        arrears=arrears,
        is_mutinied=is_mutinied,
        mutiny_count=1 if is_mutinied or probation else 0,
        mutiny_probation=probation,
        full_pay_streak=0,
        redemption_count=0,
        morale=52,
    )
    # 压低他军 danger、抬高关宁短板，确保 limit 窗口（warning/header/list）必含目标军；
    # 不改 loyalty/latch/probation（档位输入）。
    db.conn.execute(
        """UPDATE armies SET supply=100, training=100, morale=100, loyalty=100,
           arrears=0, province_pay_arrears=0, central_pay_arrears=0,
           is_mutinied=0, mutiny_probation=0
           WHERE id != ?""",
        (ARMY,),
    )
    db.conn.execute(
        "UPDATE armies SET supply=1, training=1 WHERE id=?",
        (ARMY,),
    )
    db.conn.commit()
    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    sit = _player_army_situation(row, db._army_pay(row))
    assert sit["mutiny_tier"] == expected

    # 链1：army_payload / state_payload.armies / map_nodes
    card = _payload_by_id(db)[ARMY]
    _assert_structured_situation(card, sit, "army_payload")

    runtime = _web_runtime(db, state, content)
    payload = web_app.WebGame.state_payload(runtime)
    armies = {a["id"]: a for a in (payload.get("armies") or [])}
    assert ARMY in armies
    _assert_structured_situation(armies[ARMY], sit, "state_payload.armies")
    warning = payload.get("army_warning") or ""
    _assert_chain_embeds_situation(warning, sit, "state_payload.army_warning", row=row)

    map_army = _find_army_in_map_nodes(payload.get("map_nodes") or [])
    _assert_structured_situation(map_army, sit, "map_nodes.armies")
    # 直接 map_nodes 缝（非仅 state_payload 内嵌）
    map_army2 = _find_army_in_map_nodes(runtime.map_nodes())
    _assert_structured_situation(map_army2, sit, "WebGame.map_nodes")

    # 链2：report / intelligence / knowledge / tools.list_armies
    report = db.army_report(limit=30)
    _assert_chain_embeds_situation(report, sit, "army_report", row=row)
    if arrears:
        # 欠饷裸数不得进入散文（63 是 fixture 总额）
        assert "63" not in report

    intel_text, intel_src = _qualitative_domain_statement(db, "各军欠饷如何")
    assert intel_src == "armies"
    _assert_chain_embeds_situation(intel_text, sit, "intelligence", row=row)

    war = next(c for c in content.characters.values() if c.office_type == "兵部")
    knowledge = build_character_knowledge(db, state, war.name)
    military = (knowledge.get("world") or {}).get("military") or ""
    _assert_chain_embeds_situation(military, sit, "knowledge.world.military", row=row)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_header(state, db)
    _assert_chain_embeds_situation(buf.getvalue(), sit, "report.print_header", row=row)

    ctx = CourtContext(state=state, db=db, previous_summary="")
    board = {f.__name__: f for f in build_board_query_tools(ctx)}
    _assert_chain_embeds_situation(
        board["list_armies"](), sit, "tools.list_armies", row=row
    )

    # 链3：detail / inspect
    detail = db.army_detail(ARMY)
    _assert_chain_embeds_situation(detail, sit, "army_detail", row=row)
    _assert_chain_embeds_situation(
        board["inspect_army"](ARMY), sit, "tools.inspect_army", row=row
    )

    # 链4：roster / query tool
    roster = db.army_roster()
    _assert_chain_embeds_situation(roster, sit, "army_roster", row=row)
    mtools = {
        f.__name__: f for f in build_minister_tools(war, ctx, use_army_tool=True)
    }
    _assert_chain_embeds_situation(
        mtools["query_army_roster"]([]), sit, "tools.query_army_roster", row=row
    )


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_restore_five_columns_and_player_tier_across_paths(game, tmp_path, fiscal_path):
    """AC6–9：五持久列跨 reopen；仅凭 DB load_state 接续 tick；tick 后逐字段 oracle。"""
    db, _state, content = game
    path = str(tmp_path / f"restore-321-{fiscal_path}.db")
    copied = sqlite3.connect(path)
    db.conn.backup(copied)
    copied.close()

    opened = GameDB(path, content)
    try:
        _configure(opened, fiscal_path)
        # 票面 literal：count=2 redemption=1 → cap=70；streak=7 → tick 后 8；probation 2→1
        _write_mutiny_fixture(
            opened,
            fiscal_path,
            loyalty=95,
            arrears=0,
            is_mutinied=1,
            mutiny_count=2,
            mutiny_probation=2,
            full_pay_streak=7,
            redemption_count=1,
            morale=60,
        )
        opened.close()

        reopened = GameDB(path, content)
        try:
            row = reopened.conn.execute(
                "SELECT * FROM armies WHERE id=?", (ARMY,)
            ).fetchone()
            assert tuple(
                row[k]
                for k in (
                    "is_mutinied",
                    "mutiny_count",
                    "mutiny_probation",
                    "full_pay_streak",
                    "redemption_count",
                )
            ) == (1, 2, 2, 7, 1)
            assert int(row["loyalty"]) == 95
            assert float(row["arrears"]) == pytest.approx(0)
            assert int(row["manpower"]) == 10000
            assert mutiny_loyalty_cap(2, redemption_count=1) == 70
            assert derive_army_mutiny_state(row) == "哗变"
            pay = reopened._army_pay(row)
            sit_before = _player_army_situation(row, pay)
            assert sit_before["mutiny_tier"] == "哗变"
            card_before = _payload_by_id(reopened)[ARMY]
            assert card_before["mutiny_tier"] == "哗变"

            # P1：仅凭 DB 重建恢复态，再在恢复态上设测用国库并 tick
            restored_state = reopened.load_state()
            restored_state.metrics["国库"] = 10**9
            apply_fixed_period_flows(reopened, restored_state)
            after = reopened.conn.execute(
                "SELECT * FROM armies WHERE id=?", (ARMY,)
            ).fetchone()
            assert int(after["loyalty"]) == 70
            assert int(after["is_mutinied"]) == 0
            assert int(after["mutiny_count"]) == 2
            assert int(after["mutiny_probation"]) == 1
            assert int(after["full_pay_streak"]) == 8
            assert int(after["redemption_count"]) == 1
            assert float(after["arrears"]) == pytest.approx(0)
            assert int(after["manpower"]) == 10000
            assert mutiny_loyalty_cap(2, redemption_count=1) == 70
            assert derive_army_mutiny_state(after) == "不满"
            sit_after = _player_army_situation(after, reopened._army_pay(after))
            assert sit_after["mutiny_tier"] == "不满"
            assert _payload_by_id(reopened)[ARMY]["mutiny_tier"] == "不满"
        finally:
            reopened.close()
    finally:
        if opened.conn is not None:
            try:
                opened.close()
            except Exception:
                pass


@pytest.mark.parametrize(
    "field",
    ("is_mutinied", "mutiny_count", "mutiny_probation", "full_pay_streak", "redemption_count"),
)
def test_apply_army_deltas_rejects_five_persistent_mutiny_columns(game, field):
    """AC10：五持久列对 extractor 唯一 allowlist 拒收，不新守门。"""
    db, state, _ = game
    before = db.conn.execute(
        f"SELECT {field} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()[field]
    event = SimpleNamespace(id="test-321", title="非法写哗变列")
    changes = db.apply_army_deltas(
        state, event, None, "测试", {ARMY: {field: 1, "reason": "probe"}}
    )
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected, f"{field} 应被拒收"
    assert all(c.get("category") == "invalid_enum" for c in rejected)
    after = db.conn.execute(
        f"SELECT {field} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()[field]
    assert after == before
