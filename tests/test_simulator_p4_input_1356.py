"""#1356 / ADR 0143 — simulator 输入侧抽象轴定性投影钉。

构造缝：build_simulator_payload → build_simulator_context。
民心/皇威/地区民心/局势进度/派系·阶级满意度·势力走定性；钱粮/兵额等可数物保留。
#1483：factions_brief leverage<=30 以语义记号进 brief（代码预计算），禁裸数。
非 LLM 输出措辞扫描。期望档位经 qualitative 单源 helper 计算，禁本地复写词表。
"""

from __future__ import annotations

from ming_sim.agents import build_simulator_context
from ming_sim.qualitative import (
    imperial_authority_band,
    progress_band,
    public_support_band,
    satisfaction_band,
)
from ming_sim.simulation import (
    _LEVERAGE_BELOW_SUPPRESSION_MARK,
    build_simulator_payload,
)

_SENTINEL_MINXIN = 32
_SENTINEL_HUANGWEI = 16
_SENTINEL_SAT = 32
_SENTINEL_BAR = 28
_SENTINEL_LEV = 25  # <=30 → 应带压制线语义记号


def _plant_sentinels(db, state) -> None:
    state.metrics["民心"] = _SENTINEL_MINXIN
    state.metrics["皇威"] = _SENTINEL_HUANGWEI
    db.conn.execute("UPDATE regions SET public_support=?", (_SENTINEL_MINXIN,))
    db.conn.execute(
        "UPDATE factions SET satisfaction=?, leverage=?",
        (_SENTINEL_SAT, _SENTINEL_LEV),
    )
    db.conn.execute("UPDATE classes SET satisfaction=?", (_SENTINEL_SAT,))
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="P4输入钉测局势",
        origin_kind="decree",
        origin_ref="test-p4-input-1356",
        bar_value=_SENTINEL_BAR,
        inertia=0,
        stage_text="钉测",
    )
    db.conn.commit()


def test_simulator_payload_projects_four_abstract_axes(game):
    """民心/皇威/地区民心/局势进度/派系·阶级满意走定性档；可数物保留。"""
    db, state, _content = game
    _plant_sentinels(db, state)

    payload = build_simulator_payload(state, db, "", "")
    rendered = build_simulator_context(payload)

    # —— current_state：民心/皇威定性；国库保留数 ——
    cs = payload["current_state"]
    assert cs["民心"] == public_support_band(_SENTINEL_MINXIN)
    assert cs["皇威"] == imperial_authority_band(_SENTINEL_HUANGWEI)
    assert cs["民心"] != _SENTINEL_MINXIN
    assert cs["皇威"] != _SENTINEL_HUANGWEI
    assert isinstance(cs.get("国库"), (int, float))

    # —— regions TSV：public_support 定性 ——
    cols = payload["regions"]["cols"]
    rows = payload["regions"]["rows"]
    idx = cols.index("public_support")
    assert rows, "regions 不得空"
    for row in rows:
        cell = row[idx]
        assert cell == public_support_band(_SENTINEL_MINXIN)
        assert cell != _SENTINEL_MINXIN
        assert str(cell) != str(_SENTINEL_MINXIN)

    # —— factions / classes brief：满意{sentinel} 不得出现 ——
    bare_sat = f"满意{_SENTINEL_SAT}"
    bare_lev = f"势力{_SENTINEL_LEV}"
    assert bare_sat not in str(payload["factions_brief"])
    assert bare_lev not in str(payload["factions_brief"])
    assert bare_sat not in str(payload["classes_brief"])
    # 定性档 + 压制线语义记号（#1483 代码预计算）
    assert f"满意{satisfaction_band(_SENTINEL_SAT)}" in str(payload["factions_brief"])
    assert _LEVERAGE_BELOW_SUPPRESSION_MARK in str(payload["factions_brief"])
    assert "满意" in str(payload["classes_brief"])  # 定性档仍在

    # —— active_issues 进度 ——
    pinned = next(
        i for i in payload["active_issues"]
        if i.get("title") == "P4输入钉测局势"
    )
    assert pinned["进度"] == progress_band(_SENTINEL_BAR)
    assert pinned["进度"] != _SENTINEL_BAR
    assert str(pinned["进度"]) != str(_SENTINEL_BAR)

    # —— 渲染串：抽象轴标签紧邻哨兵裸值即红 ——
    for needle in (
        f'"民心": {_SENTINEL_MINXIN}',
        f'"民心":{_SENTINEL_MINXIN}',
        f"民心{_SENTINEL_MINXIN}",
        f'"皇威": {_SENTINEL_HUANGWEI}',
        f'"皇威":{_SENTINEL_HUANGWEI}',
        f"皇威{_SENTINEL_HUANGWEI}",
        bare_sat,
        bare_lev,
    ):
        assert needle not in rendered, f"rendered leaked {needle!r}"

    # 定性档应在渲染中
    assert str(cs["民心"]) in rendered
    assert str(cs["皇威"]) in rendered
    assert str(pinned["进度"]) in rendered
    assert _LEVERAGE_BELOW_SUPPRESSION_MARK in rendered
