"""#654 差务属地 + 两轴清单：聚焦验收（oracle / fan-out / 距离档 / P4 哨兵）。"""

from __future__ import annotations

import json
import re

import pytest

from ming_sim.decree_vocabulary import NATIONAL_FANOUT_ACTION_TYPES
from ming_sim.distance import DistanceMatrix
from ming_sim.execution_pressure import (
    ABSENT,
    BAND_FAR,
    BAND_LOCAL,
    BAND_MID,
    BAND_NEAR,
    build_execution_two_axis_surface,
    distance_semantic_band,
    fold_distance_band,
    ming_province_ids,
    normalize_locality_scope,
    resolve_dossier_region_ids,
)
from ming_sim.paths import bundled_path
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


def _matrix():
    return DistanceMatrix.from_file(bundled_path("content", "distance_matrix.json"))


# ── 词表 / scope 归一 ──────────────────────────────────────────────


def test_national_fanout_whitelist_subset():
    assert NATIONAL_FANOUT_ACTION_TYPES == frozenset({"policy", "special_decree"})


@pytest.mark.parametrize("raw,expected", [
    (None, "none"),
    ("", "none"),
    ("无", "none"),
    ("全国", "national"),
    ("单省", "single"),
    ("national", "national"),
])
def test_normalize_locality_scope(raw, expected):
    assert normalize_locality_scope(raw) == expected


def test_normalize_locality_scope_rejects_unknown():
    with pytest.raises(ValueError, match="locality_scope"):
        normalize_locality_scope("全省")


# ── 距离档（r4-A / D1–D6）────────────────────────────────────────


@pytest.mark.parametrize("months,band", [
    (0.0, BAND_LOCAL),
    (0.5, BAND_NEAR),
    (1.0, BAND_NEAR),
    (1.05, BAND_MID),
    (3.0, BAND_MID),
    (3.1, BAND_FAR),
])
def test_fold_distance_band_boundaries(months, band):
    assert fold_distance_band(months) == band


def test_distance_d4_same_province_is_local_phrase():
    assert distance_semantic_band(
        owner_location="shaanxi", region_id="shaanxi", matrix=_matrix(),
    ) == BAND_LOCAL


def test_distance_d5_real_matrix_samples():
    m = _matrix()
    assert distance_semantic_band(
        owner_location="beizhili", region_id="shandong", matrix=m,
    ) == BAND_NEAR  # 1.0
    assert distance_semantic_band(
        owner_location="beizhili", region_id="shaanxi", matrix=m,
    ) == BAND_MID  # 2.5
    assert distance_semantic_band(
        owner_location="beizhili", region_id="sichuan", matrix=m,
    ) == BAND_FAR  # 5.7


@pytest.mark.parametrize("kwargs", [
    {"owner_location": "beizhili", "region_id": ""},
    {"owner_location": "", "region_id": "shaanxi"},
    {"owner_location": "beizhili", "region_id": "shaanxi", "transit_to": "henan"},
])
def test_distance_d1_d2_d3_absent(kwargs):
    assert distance_semantic_band(matrix=_matrix(), **kwargs) == ABSENT


def test_distance_d6_missing_matrix_node_fail_loud():
    with pytest.raises(KeyError):
        distance_semantic_band(
            owner_location="beizhili",
            region_id="not_a_region_node_xyz",
            matrix=_matrix(),
        )


def test_no_placeholder_673_wording_in_module_source():
    from pathlib import Path
    src = Path("ming_sim/execution_pressure.py").read_text(encoding="utf-8")
    assert "#673 占位" not in src
    assert "恒不参与" not in src


# ── locality oracle 组合矩阵 ───────────────────────────────────────


def test_ming_province_set_is_fifteen(env):
    db, _, _ = env
    ids = ming_province_ids(db.conn)
    assert len(ids) == 15
    assert "shaanxi" in ids and "beizhili" in ids


def test_national_policy_fanout_returns_all_provinces(env):
    db, _, content = env
    regions = resolve_dossier_region_ids(
        db.conn,
        action_type="policy",
        payload={
            "target_kind": "policy",
            "target_id": "清丈田亩",
            "locality_scope": "national",
        },
        regions_content=content.regions,
    )
    assert regions == ming_province_ids(db.conn)


def test_special_decree_without_national_is_single_empty(env):
    db, _, content = env
    regions = resolve_dossier_region_ids(
        db.conn,
        action_type="special_decree",
        payload={
            "target_kind": "policy",
            "target_id": "manual-directive",
            "locality_scope": "none",
        },
        regions_content=content.regions,
    )
    assert regions == [""]


def test_region_single_by_id(env):
    db, _, content = env
    assert resolve_dossier_region_ids(
        db.conn,
        action_type="policy",
        payload={
            "target_kind": "region",
            "target_id": "shaanxi",
            "locality_scope": "single",
        },
        regions_content=content.regions,
    ) == ["shaanxi"]


def test_region_outside_province_set_yields_empty_locality(env):
    db, _, content = env
    # 辽东边镇不入省集合
    assert resolve_dossier_region_ids(
        db.conn,
        action_type="policy",
        payload={
            "target_kind": "region",
            "target_id": "liaodong",
            "locality_scope": "single",
        },
        regions_content=content.regions,
    ) == [""]


@pytest.mark.parametrize("payload,action", [
    ({"target_kind": "region", "target_id": "shaanxi", "locality_scope": "national"}, "policy"),
    ({"target_kind": "region", "target_id": "shaanxi", "locality_scope": "none"}, "policy"),
    ({"target_kind": "policy", "target_id": "x", "locality_scope": "single"}, "policy"),
    ({"target_kind": "character", "target_id": "袁崇焕", "locality_scope": "national"}, "policy"),
    ({"target_kind": "policy", "target_id": "x", "locality_scope": "national"}, "assignment"),
    ({"target_kind": "unknown", "target_id": "x", "locality_scope": "none"}, "policy"),
])
def test_oracle_contradictions_fail_loud(env, payload, action):
    db, _, content = env
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, action_type=action, payload=payload,
            regions_content=content.regions,
        )


def test_region_zero_hit_fail_loud(env):
    db, _, content = env
    with pytest.raises(ValueError, match="零命中|歧义"):
        resolve_dossier_region_ids(
            db.conn,
            action_type="policy",
            payload={
                "target_kind": "region",
                "target_id": "不存在的行省xyz",
                "locality_scope": "single",
            },
            regions_content=content.regions,
        )


# ── schema + create_decree_dossiers fan-out ────────────────────────


def test_region_id_column_and_composite_indexes(env):
    db, _, _ = env
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(decree_dossiers)")}
    assert "region_id" in cols
    idx = {
        r["name"]: r["sql"] or ""
        for r in db.conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_decree_dossiers_%'"
        ).fetchall()
    }
    assert "idx_decree_dossiers_directive" in idx
    assert "idx_decree_dossiers_pending_action" in idx
    # 复合唯一：sql 含 region_id
    assert "region_id" in (idx["idx_decree_dossiers_directive"] or "")
    assert "region_id" in (idx["idx_decree_dossiers_pending_action"] or "")
    # secret_order 单列索引保留
    assert "idx_decree_dossiers_secret_order" in idx


def test_national_fanout_creates_n_rows_idempotent(env):
    db, state, content = env
    provinces = ming_province_ids(db.conn)
    # 点将路径：assignee 落主办
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "assignee_id": "毕自严",
        "transaction_category": "清丈",
        "participant_roster": [
            {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
        ],
    }
    # 需 directive 行以挂复合键
    cur = db.conn.execute(
        """
        INSERT INTO turn_directives
        (turn, year, period, event_id, actor, skill_id, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严", "",
            "清丈天下田亩", "test", "draft", "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    directive_id = int(cur.lastrowid)
    db.conn.commit()

    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        directive_id=directive_id,
        payload=payload,
        commit=True,
    )
    assert len(ids) == len(provinces)
    rows = db.list_dossiers_for_directive(directive_id)
    assert len(rows) == len(provinces)
    assert [r["region_id"] for r in rows] == provinces
    # 点将：N 行同名主办
    for r in rows:
        leads = [
            e["character_id"] for e in r["participant_roster"] if e.get("tier") == "主办"
        ]
        assert leads == ["毕自严"]

    # 幂等重放
    ids2 = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        directive_id=directive_id,
        payload=payload,
        commit=True,
    )
    assert ids2 == ids
    assert len(db.list_dossiers_for_directive(directive_id)) == len(provinces)


def test_create_decree_dossier_int_abi_single_row(env):
    db, state, _ = env
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="京内申饬",
        target_kind="policy",
        target_id="court-rebuke",
        payload={"locality_scope": "none", "target_kind": "policy", "target_id": "court-rebuke"},
    )
    assert isinstance(did, int) and did > 0
    row = db.get_decree_dossier(did)
    assert row["region_id"] == ""


def test_get_dossier_for_directive_existence_sentinel(env):
    db, state, _ = env
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "dossier_action_type": "policy",
    }
    cur = db.conn.execute(
        """
        INSERT INTO turn_directives
        (turn, year, period, event_id, actor, skill_id, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严", "",
            "陕西清丈", "test", "draft", "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    directive_id = int(cur.lastrowid)
    db.conn.commit()
    assert db.get_dossier_for_directive(directive_id) is None
    db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="陕西清丈",
        target_kind="region",
        target_id="shaanxi",
        directive_id=directive_id,
        payload=payload,
    )
    assert db.get_dossier_for_directive(directive_id) is not None
    listed = db.list_dossiers_for_directive(directive_id)
    assert len(listed) == 1 and listed[0]["region_id"] == "shaanxi"


def test_ensure_directive_dossier_returns_list(env):
    db, state, _ = env
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "region",
        "target_id": "henan",
        "locality_scope": "single",
    }
    cur = db.conn.execute(
        """
        INSERT INTO turn_directives
        (turn, year, period, event_id, actor, skill_id, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严", "",
            "河南清丈", "test", "draft", "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    directive_id = int(cur.lastrowid)
    db.conn.commit()
    ids = db._ensure_directive_dossier(
        state, directive_id, "河南清丈", payload, commit=True,
    )
    assert isinstance(ids, list) and len(ids) == 1 and ids[0] > 0


# ── 两轴清单 + P4 哨兵 ────────────────────────────────────────────


def _promote_executing(db, dossier_id, region_id="shaanxi"):
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', region_id=? WHERE id=?",
        (region_id, int(dossier_id)),
    )
    db.conn.commit()


def test_two_axis_owner_load_and_province_count(env):
    db, state, _ = env
    # 毕自严 location 置 beizhili 以便距离档非空
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='' WHERE name='毕自严'",
    )
    # 十旨砸一省
    for i in range(10):
        did = db.create_decree_dossier(
            state,
            action_type="assignment",
            decree_text=f"陕西差务{i}",
            target_kind="issue",
            target_id=f"errand-{i}",
            payload={
                "target_kind": "issue",
                "target_id": f"errand-{i}",
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
        _promote_executing(db, did, "shaanxi")

    surface = build_execution_two_axis_surface(db, state.turn)
    shaanxi = next(p for p in surface["provinces"] if p["region_id"] == "shaanxi")
    assert shaanxi["province_open_count"] == 10
    owners = {o["owner_name"]: o for o in shaanxi["owners"]}
    assert "毕自严" in owners
    assert owners["毕自严"]["owner_open_count"] == 10
    ability = owners["毕自严"]["owner_ability"]
    assert owners["毕自严"]["owner_load"] == 10 * ability
    assert owners["毕自严"]["distance_semantic_band"] == BAND_MID  # beizhili→shaanxi 2.5
    # 士绅盘 / 官僚盘有记录
    assert shaanxi["gentry_slice"] != "无记录"
    assert shaanxi["officials_slice"] != "无记录"
    # 督抚出缺
    assert shaanxi["dutang_faction"] == "出缺"
    # 党派因子不重列
    blob = json.dumps(surface, ensure_ascii=False)
    assert "faction_factor" not in blob
    assert "党派因子" not in surface["tsv"]


def test_two_axis_disaster_pinned_top_order(env):
    db, state, _ = env
    # 灾情族 kind 由事件涌现轨写入；直插 DB 钉置顶序（insert_issue 仅 situation/initiative）
    for title, kind, sev in (("轻灾", "灾情", 20), ("重灾", "饥荒", 80)):
        db.conn.execute(
            """
            INSERT INTO issues
            (kind, title, origin_kind, origin_ref, origin_turn, bar_value,
             bar_good_meaning, bar_bad_meaning, inertia, phase, stage_text,
             status, severity, region_hint, cancellable)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                kind, title, "test", "", int(state.turn), 10,
                "缓", "剧", 0, "stalemate", "s",
                "active", sev, "shaanxi", "never",
            ),
        )
    db.conn.commit()
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="赈陕",
        target_kind="issue",
        target_id="relief",
        payload={
            "target_kind": "issue", "target_id": "relief", "locality_scope": "none",
            "assignee_id": "毕自严", "transaction_category": "督赈",
            "participant_roster": [
                {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
            ],
        },
        participants=[
            {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
        ],
    )
    _promote_executing(db, did, "shaanxi")
    surface = build_execution_two_axis_surface(db, state.turn)
    shaanxi = next(p for p in surface["provinces"] if p["region_id"] == "shaanxi")
    titles = [d["title"] for d in shaanxi["disaster_rows"]]
    assert titles == ["重灾", "轻灾"]


def test_two_axis_only_in_issues_extractor_not_simulator(env):
    db, state, _ = env
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="差",
        target_kind="issue",
        target_id="x",
        payload={
            "target_kind": "issue", "target_id": "x", "locality_scope": "none",
            "assignee_id": "毕自严", "transaction_category": "清丈",
        },
        participants=[
            {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
        ],
    )
    _promote_executing(db, did, "shaanxi")

    issues_ctx = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="issues",
    )
    assert "execution_two_axis" in issues_ctx
    assert "owner_ability" in json.dumps(issues_ctx["execution_two_axis"], ensure_ascii=False)

    other = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="internal",
    )
    assert "execution_two_axis" not in other

    sim = build_simulator_payload(state, db, decree_text="d", previous_narrative="n")
    assert "execution_two_axis" not in sim
    # 裸 ability 不得进 simulator
    dumped = json.dumps(sim, ensure_ascii=False)
    assert "owner_ability" not in dumped
    assert "execution_two_axis" not in dumped


def test_normalize_payload_locality_and_target_kind(env):
    db, _, _ = env
    out = db._normalize_directive_dossier_payload({
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "全国",
        "mode": "ordinary",
    })
    assert out["locality_scope"] == "national"
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "not_a_kind",
            "target_id": "x",
            "mode": "ordinary",
        })
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "全省",
            "mode": "ordinary",
        })


def test_cli_backend_invalid_target_kind_fail_loud():
    """r3-B.2：废除静默改 policy。"""
    from ming_sim import cli_backend as cb
    # 直接测归一辅助：若存在公开 helper 用它；否则测 extract 后机械段逻辑
    # 生产路径：capture 合并处对非法 target_kind 抛错
    with pytest.raises(ValueError):
        cb._coerce_draft_target_kind("not_a_real_kind")


def test_score_extractor_issues_mentions_two_axis():
    from pathlib import Path
    text = Path("content/prompts/score_extractor_issues.md").read_text(encoding="utf-8")
    assert "两轴" in text or "execution_two_axis" in text
    assert "忙" in text and "拖磨" in text
    assert "顶" in text and "变形" in text
    assert "distance_semantic_band" in text or "距离档" in text
    assert "#673 占位" not in text
    assert "恒不参与" not in text
