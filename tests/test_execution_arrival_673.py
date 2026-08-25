"""#673 r3：承办人到差态行 + 同一 transit_semantics 对象直传 + 20 列 TSV ABI。"""

from __future__ import annotations

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


# ── B×G 矩阵：直调 surface，显式 collection 夹具（参数化压缩） ─────


@pytest.mark.parametrize(
    "case,location,transit_to,region_id,collection,expect_status,expect_dist,multi",
    [
        (
            "in_transit_duty",
            "beizhili", "shaanxi", "shaanxi",
            [{"name": "毕自严", "transit_to": "shaanxi", "semantic": "x"}],
            "在途", ABSENT, False,
        ),
        (
            "in_transit_elsewhere",
            "beizhili", "henan", "shaanxi",
            [{"name": "毕自严", "transit_to": "henan", "semantic": "x"}],
            "在途", ABSENT, False,
        ),
        (
            "not_in_transit_elsewhere",
            "beizhili", "", "shaanxi",
            [],
            "尚未到差", BAND_MID, False,
        ),
        (
            "same_province_arrived",
            "shaanxi", "", "shaanxi",
            [],
            "已到差", BAND_LOCAL, False,
        ),
        (
            "empty_location_omits",
            "", "", "shaanxi",
            [],
            None, ABSENT, False,
        ),
        (
            "empty_region_omits",
            "beizhili", "", "",
            [],
            None, ABSENT, False,
        ),
        (
            "multi_province_independent",
            "shaanxi", "", "shaanxi",
            [],
            "已到差", None, True,
        ),
    ],
    ids=[
        "in_transit_duty",
        "in_transit_elsewhere",
        "not_in_transit_elsewhere",
        "same_province_arrived",
        "empty_location_omits",
        "empty_region_omits",
        "multi_province_independent",
    ],
)
def test_arrival_matrix_cases(
    env, case, location, transit_to, region_id, collection,
    expect_status, expect_dist, multi,
):
    """B/G 矩阵：在途/到差/省略/跨省独立——共享 setup，按表断言。"""
    db, state, _ = env
    owner = "毕自严"
    _set_char(db, owner, location=location, transit_to=transit_to)
    _make_executing_dossier(
        db, state, owner=owner, region_id=region_id, tag=f"m-{case}",
    )
    if multi:
        _make_executing_dossier(
            db, state, owner=owner, region_id="henan", tag=f"m-{case}-hn",
        )

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=collection,
    )

    if multi:
        sx = _arrival_by_owner(_block(surface, "shaanxi"))[owner]
        hn = _arrival_by_owner(_block(surface, "henan"))[owner]
        assert sx["duty_arrival_status"] == "已到差"
        assert sx["duty_region_id"] == "shaanxi"
        assert hn["duty_arrival_status"] == "尚未到差"
        assert hn["duty_region_id"] == "henan"
        return

    block = _block(surface, region_id)
    arrivals = _arrival_by_owner(block)
    if expect_status is None:
        assert owner not in arrivals
        assert all(r["owner_name"] != owner for r in block.get("arrival_rows") or [])
    else:
        row = arrivals[owner]
        assert set(row) == {"owner_name", "duty_region_id", "duty_arrival_status"}
        assert row["duty_arrival_status"] == expect_status
        assert row["duty_region_id"] == region_id
        if expect_status == "在途" and case == "in_transit_duty":
            assert row == {
                "owner_name": owner,
                "duty_region_id": "shaanxi",
                "duty_arrival_status": "在途",
            }

    if expect_dist is not None:
        dist = _owner_dist(block, owner)
        assert dist == expect_dist
        if expect_dist == BAND_LOCAL:
            assert dist not in {BAND_NEAR, BAND_MID, BAND_FAR}


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


# ── F′ 真 phase1→phase2 装配（经 _settle_after_narrative）──────────


def test_phase1_phase2_same_transit_semantics_object_and_single_projector(env, monkeypatch):
    """#652：payload 装配钉 transit_semantics 同引用 + projector 恰一次；到差从 two_axis 读。"""
    import ming_sim.decree as decree_mod

    db, state, content = env
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

    # 贵 LLM 全 stub；禁止 stub build_extractor_shared_context 本体为假实现
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_rescript_draft_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "extractor-out", "extractor-in"),
    )

    real_build_ctx = decree_mod.build_extractor_shared_context
    captured: dict = {}

    def _wrap_ctx(*args, **kwargs):
        ctx = real_build_ctx(*args, **kwargs)
        if kwargs.get("module") == "issues":
            captured["ctx"] = ctx
            captured["has_two_axis"] = "execution_two_axis" in ctx
        return ctx

    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", _wrap_ctx)

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
        # builder 入参与 payload 顶层同一 list（#652 装配）
        assert "execution_two_axis" in payload
        surface = payload["execution_two_axis"]
        block = _block(surface, "shaanxi")
        arr = _arrival_by_owner(block)[owner]
        assert arr["duty_arrival_status"] == "在途"
        assert any(r.get("name") == arr["owner_name"] for r in C)

        # 真实 phase2 装配缝（非孤立直调 context）
        decree_mod._settle_after_narrative(
            state, db, None, None,
            decree_text="d", narrative="n",
            simulator_payload=payload,
            relevant_memories=[], secret_orders={},
            before_turn=state.turn, _emit=lambda *a: None, content=content,
        )

    assert "ctx" in captured, "issues 模块未调用真实 build_extractor_shared_context"
    # issues 不得见 two_axis；projector 全链恰一次
    assert captured["has_two_axis"] is False
    assert call_count["n"] == 1
    # settle 后 payload 顶层 transit_semantics 仍是原 list
    assert payload["transit_semantics"] is C
