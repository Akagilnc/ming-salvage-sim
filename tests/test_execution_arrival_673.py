"""#673 r3：承办人到差态行 + 同一 transit_semantics 对象直传 + 20 列 TSV ABI。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ming_sim.execution_pressure import (
    ABSENT,
    BAND_FAR,
    BAND_LOCAL,
    BAND_MID,
    BAND_NEAR,
    build_execution_two_axis_surface,
)
from ming_sim.simulation import (
    build_extractor_shared_context,
    build_simulator_payload,
    project_transit_semantics,
)


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


def _promote_executing(db, dossier_id, region_id="shaanxi"):
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', region_id=? WHERE id=?",
        (region_id, int(dossier_id)),
    )
    db.conn.commit()


def _make_executing_dossier(db, state, *, owner: str, region_id: str, tag: str):
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text=f"差务-{tag}",
        target_kind="issue",
        target_id=tag,
        payload={
            "target_kind": "issue",
            "target_id": tag,
            "locality_scope": "none",
            "assignee_id": owner,
            "transaction_category": "清丈",
            "participant_roster": [
                {
                    "character_id": owner,
                    "tier": "主办",
                    "role": "",
                    "delegator_id": None,
                },
            ],
        },
        participants=[
            {
                "character_id": owner,
                "tier": "主办",
                "role": "",
                "delegator_id": None,
            },
        ],
    )
    _promote_executing(db, did, region_id)
    return did


def _set_char(db, name: str, *, location: str, transit_to: str = ""):
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to=? WHERE name=?",
        (location, transit_to, name),
    )
    db.conn.commit()


def _block(surface, region_id: str):
    return next(p for p in surface["provinces"] if p["region_id"] == region_id)


def _arrival_by_owner(block):
    return {r["owner_name"]: r for r in block.get("arrival_rows") or []}


def _owner_dist(block, owner: str) -> str:
    return next(
        o["distance_semantic_band"]
        for o in block["owners"]
        if o["owner_name"] == owner
    )


# ── B×G 矩阵：直调 surface，显式 collection 夹具 ──────────────────


def test_arrival_in_transit_to_duty_region(env):
    """在途本差 → 到差态=在途；距离仍 D3 不参与。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="beizhili", transit_to="shaanxi")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="t-duty")
    collection = [{"name": owner, "transit_to": "shaanxi", "semantic": "x"}]

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=collection,
    )
    block = _block(surface, "shaanxi")
    row = _arrival_by_owner(block)[owner]
    assert set(row) == {"owner_name", "duty_region_id", "duty_arrival_status"}
    assert row == {
        "owner_name": owner,
        "duty_region_id": "shaanxi",
        "duty_arrival_status": "在途",
    }
    assert _owner_dist(block, owner) == ABSENT


def test_arrival_in_transit_elsewhere(env):
    """在途别处（transit_to ≠ 差务地）仍按 name 命中 → 在途；距离不参与。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="beizhili", transit_to="henan")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="t-else")
    collection = [{"name": owner, "transit_to": "henan", "semantic": "x"}]

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=collection,
    )
    block = _block(surface, "shaanxi")
    assert _arrival_by_owner(block)[owner]["duty_arrival_status"] == "在途"
    assert _owner_dist(block, owner) == ABSENT


def test_arrival_not_in_transit_elsewhere(env):
    """非在途异地 → 尚未到差 + #654 对应距离档。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="beizhili", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="away")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    block = _block(surface, "shaanxi")
    assert _arrival_by_owner(block)[owner]["duty_arrival_status"] == "尚未到差"
    assert _owner_dist(block, owner) == BAND_MID  # beizhili→shaanxi 2.5


def test_arrival_same_province_arrived(env):
    """同地 → 已到差 + BAND_LOCAL；不得与近/中/远并存。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="shaanxi", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="local")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    block = _block(surface, "shaanxi")
    assert _arrival_by_owner(block)[owner]["duty_arrival_status"] == "已到差"
    dist = _owner_dist(block, owner)
    assert dist == BAND_LOCAL
    assert dist not in {BAND_NEAR, BAND_MID, BAND_FAR}


def test_arrival_empty_location_omits_row(env):
    """location=='' → 无该到差态行（无哨兵）。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="no-loc")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    block = _block(surface, "shaanxi")
    assert owner not in _arrival_by_owner(block)
    assert all(r["owner_name"] != owner for r in block.get("arrival_rows") or [])
    # 距离仍走 #654 D2
    assert _owner_dist(block, owner) == ABSENT


def test_arrival_empty_region_omits_row(env):
    """region_id==''（非属地）→ 无到差态行；距离 D1 不参与。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="beizhili", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="", tag="no-rid")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    block = _block(surface, "")
    assert block.get("arrival_rows") == []
    assert all(
        o["owner_name"] != owner or o["distance_semantic_band"] == ABSENT
        for o in block["owners"]
    )


def test_arrival_same_owner_multi_province_independent(env):
    """同主办跨多省 → 每省独立一行。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="shaanxi", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="p-sx")
    _make_executing_dossier(db, state, owner=owner, region_id="henan", tag="p-hn")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    sx = _arrival_by_owner(_block(surface, "shaanxi"))[owner]
    hn = _arrival_by_owner(_block(surface, "henan"))[owner]
    assert sx["duty_arrival_status"] == "已到差"
    assert sx["duty_region_id"] == "shaanxi"
    assert hn["duty_arrival_status"] == "尚未到差"
    assert hn["duty_region_id"] == "henan"


def test_surface_requires_transit_semantics_kwarg(env):
    """缺必需形参 → 普通 TypeError；无 [] fallback。"""
    db, state, _ = env
    with pytest.raises(TypeError):
        build_execution_two_axis_surface(db, state.turn)


# ── C′ TSV 20 列 ABI ──────────────────────────────────────────────


_EXPECTED_HEADER = (
    "行类\t省\t省在办数\t士绅阻力\t流寇压力\t贼强度\t督抚派系\t督抚操守"
    "\t士绅盘\t官僚盘\t主办\t在办数\t能力\t负荷\t距离档"
    "\t灾情id\t灾种\t严重度\t标题\t到差态"
)


def test_tsv_header_exactly_20_cols_and_arrival_rows(env):
    """header 逐字 20 列；到差态行三格；旧行第 20 空；arrival_rows↔TSV 1:1。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location="beizhili", transit_to="")
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="tsv")

    # 一灾以便验旧行第 20 列
    db.insert_issue(
        state,
        kind="situation",
        title="旱灾",
        origin_kind="test",
        severity=50,
        region_hint="shaanxi",
        tags=["灾情"],
        bar_value=10,
        bar_good_meaning="缓",
        bar_bad_meaning="剧",
        stage_text="s",
        cancellable="never",
        commit=True,
    )

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    lines = surface["tsv"].splitlines()
    assert lines[1] == _EXPECTED_HEADER
    assert len(lines[1].split("\t")) == 20

    data = [ln for ln in lines[2:] if ln.split("\t", 1)[0] in
            ("灾情", "省盘", "主办", "到差态")]
    for ln in data:
        cells = ln.split("\t")
        assert len(cells) == 20, (len(cells), ln)

    # 旧三类行第 20 列空
    for kind in ("灾情", "省盘", "主办"):
        for ln in data:
            cells = ln.split("\t")
            if cells[0] == kind:
                assert cells[19] == "", (kind, ln)

    arrival_tsv = [ln for ln in data if ln.startswith("到差态\t")]
    block = _block(surface, "shaanxi")
    assert len(arrival_tsv) == len(block["arrival_rows"]) == 1
    cells = arrival_tsv[0].split("\t")
    # 仅 省 / 主办 / 到差态 有值
    assert cells[0] == "到差态"
    assert cells[1] == "shaanxi"
    assert cells[10] == owner
    assert cells[19] == "尚未到差"
    empty_idxs = [i for i in range(20) if i not in (0, 1, 10, 19)]
    assert all(cells[i] == "" for i in empty_idxs)

    # 块内顺序：灾情 → 省盘 → 主办 → 到差态
    sx_lines = [
        ln for ln in lines
        if ln.startswith(("灾情\tshaanxi", "省盘\tshaanxi",
                          "主办\tshaanxi", "到差态\tshaanxi"))
    ]
    kinds = [ln.split("\t", 1)[0] for ln in sx_lines]
    assert kinds == ["灾情", "省盘", "主办", "到差态"]


# ── F′ 真 phase1→phase2 装配（禁假绿）────────────────────────────


def test_phase1_phase2_same_transit_semantics_object_and_single_projector(env):
    """真 payload → context：projector 恰一次；入参 is 同一对象；在途可按 name 关联。"""
    db, state, _ = env
    owner = "毕自严"
    # 真实在途账，让 phase1 projector 产出非空 collection
    db.set_character_transit(
        owner,
        location="beizhili",
        transit_to="shaanxi",
        distance_remaining=2.0,
        speed_factor=1.0,
        start_turn=max(1, int(state.turn) - 1),
        commit=True,
    )
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="wire")

    real_project = project_transit_semantics
    call_count = {"n": 0}

    def _spy(db_, state_, matrix):
        call_count["n"] += 1
        return real_project(db_, state_, matrix)

    captured: dict = {}

    def _capture_surface(db_, turn=0, *, transit_semantics):
        captured["transit_semantics"] = transit_semantics
        return build_execution_two_axis_surface(
            db_, turn, transit_semantics=transit_semantics,
        )

    with patch(
        "ming_sim.simulation.project_transit_semantics", side_effect=_spy,
    ):
        payload = build_simulator_payload(
            state, db, decree_text="d", previous_narrative="n",
        )
        assert call_count["n"] == 1
        C = payload["transit_semantics"]
        assert isinstance(C, list)
        assert any(r.get("name") == owner for r in C)

        with patch(
            "ming_sim.execution_pressure.build_execution_two_axis_surface",
            side_effect=_capture_surface,
        ):
            # 模拟 phase2：把 payload 内既成对象原样下传
            ctx = build_extractor_shared_context(
                db, state, narrative="n", decree_text="d",
                module="issues",
                transit_semantics=payload["transit_semantics"],
            )

    # 装配缝收到同一 list 对象
    assert captured["transit_semantics"] is payload["transit_semantics"]
    assert captured["transit_semantics"] is C
    # projector 全链仍恰一次（context 不得再投影）
    assert call_count["n"] == 1

    surface = ctx["execution_two_axis"]
    block = _block(surface, "shaanxi")
    arr = _arrival_by_owner(block)[owner]
    assert arr["duty_arrival_status"] == "在途"
    # 到差「在途」行的 owner_name 可在同一 collection 按 name 关联
    assert any(r.get("name") == arr["owner_name"] for r in C)


def test_poison_projector_isolated_old_path_not_accepted(env):
    """禁止：poison projector 后孤立旧 builder 未传同对象仍绿。"""
    db, state, _ = env
    owner = "毕自严"
    db.set_character_transit(
        owner,
        location="beizhili",
        transit_to="shaanxi",
        distance_remaining=2.0,
        speed_factor=1.0,
        start_turn=max(1, int(state.turn) - 1),
        commit=True,
    )
    _make_executing_dossier(db, state, owner=owner, region_id="shaanxi", tag="poison")

    payload = build_simulator_payload(
        state, db, decree_text="d", previous_narrative="n",
    )
    C = payload["transit_semantics"]
    assert any(r.get("name") == owner for r in C)

    def _poison(*_a, **_k):
        raise AssertionError("second project_transit_semantics call forbidden")

    with patch(
        "ming_sim.simulation.project_transit_semantics", side_effect=_poison,
    ):
        # 正确路径：传同一对象，不触发 projector
        ctx = build_extractor_shared_context(
            db, state, narrative="n", decree_text="d",
            module="issues",
            transit_semantics=C,
        )
    assert _arrival_by_owner(
        _block(ctx["execution_two_axis"], "shaanxi"),
    )[owner]["duty_arrival_status"] == "在途"

    # 错误路径：不传 collection 且 surface 缺参 → 必须失败（不得静默绿）
    with pytest.raises(TypeError):
        build_execution_two_axis_surface(db, state.turn)


# ── 门控回归 / H 删旧 ─────────────────────────────────────────────


def test_non_issues_and_simulator_still_no_two_axis(env):
    db, state, _ = env
    _make_executing_dossier(
        db, state, owner="毕自严", region_id="shaanxi", tag="gate",
    )
    payload = build_simulator_payload(
        state, db, decree_text="d", previous_narrative="n",
    )
    assert "execution_two_axis" not in payload

    other = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="internal",
        transit_semantics=payload["transit_semantics"],
    )
    assert "execution_two_axis" not in other

    issues = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="issues",
        transit_semantics=payload["transit_semantics"],
    )
    assert "execution_two_axis" in issues


def test_prompt_and_source_hygiene_h():
    prompt = Path("content/prompts/score_extractor_issues.md").read_text(
        encoding="utf-8",
    )
    assert "到差态" in prompt
    assert "已到差" in prompt or "尚未到差" in prompt
    # 不得再用「不参与」兼表在途
    assert "值为「不参与」时（非属地、承办人无驻地、在途）" not in prompt

    sim_src = Path("ming_sim/simulation.py").read_text(encoding="utf-8")
    assert "#673 判官清单复用" not in sim_src
    assert "#673 将来复用" not in sim_src

    # 零 schema：region_id 列仍在，无新增到差表
    ep_src = Path("ming_sim/execution_pressure.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in ep_src
