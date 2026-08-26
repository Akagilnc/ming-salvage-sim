"""#654 差务属地 + 两轴清单：聚焦验收（oracle / fan-out / 距离档 / P4 哨兵）。"""

from __future__ import annotations

import json
import re

import pytest

from ming_sim.decree_vocabulary import NATIONAL_FANOUT_ACTION_TYPES, TARGET_KINDS
from ming_sim.distance import DistanceMatrix
from ming_sim.execution_pressure import (
    ABSENT,
    BAND_FAR,
    BAND_LOCAL,
    BAND_MID,
    BAND_NEAR,
    TARGET_KINDS as EP_TARGET_KINDS,
    _escape_tsv_cell,
    _render_two_axis_tsv,
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
    # 点将：N 行同名主办，且 executor_* 与首名主办同步（#654 named-lead 断根）
    for r in rows:
        leads = [
            e["character_id"] for e in r["participant_roster"] if e.get("tier") == "主办"
        ]
        assert leads == ["毕自严"]
        assert r["executor_kind"] == "character"
        assert r["executor_id"] == "毕自严"

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


def test_named_lead_bulk_single_region_syncs_executor(env):
    """#654：非 fan-out 批量入口点将亦同步 executor_*（与 national 同根）。"""
    db, state, _ = env
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "dossier_action_type": "policy",
        "assignee_id": "毕自严",
        "participant_roster": [
            {"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None},
        ],
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

    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="陕西清丈",
        target_kind="region",
        target_id="shaanxi",
        directive_id=directive_id,
        payload=payload,
        commit=True,
    )
    assert len(ids) == 1
    row = db.list_dossiers_for_directive(directive_id)[0]
    assert row["region_id"] == "shaanxi"
    leads = [
        e["character_id"] for e in row["participant_roster"] if e.get("tier") == "主办"
    ]
    assert leads == ["毕自严"]
    assert row["executor_kind"] == "character"
    assert row["executor_id"] == "毕自严"


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
        "assignee_id": "毕自严",
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
        "assignee_id": "毕自严",
        "mode": "ordinary",
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

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
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
    # D1：durable kind=situation；灾种真源=tags ∩ DISASTER_KINDS
    for title, tag, sev in (("轻灾", "灾情", 20), ("重灾", "饥荒", 80)):
        db.insert_issue(
            state,
            kind="situation",
            title=title,
            origin_kind="test",
            severity=sev,
            region_hint="shaanxi",
            tags=[tag],
            bar_value=10,
            bar_good_meaning="缓",
            bar_bad_meaning="剧",
            stage_text="s",
            cancellable="never",
            commit=True,
        )
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
    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    shaanxi = next(p for p in surface["provinces"] if p["region_id"] == "shaanxi")
    titles = [d["title"] for d in shaanxi["disaster_rows"]]
    assert titles == ["重灾", "轻灾"]


def test_two_axis_in_simulator_not_extractors(env):
    """#652：execution_two_axis 仅 simulator 定性投影；extractors 不见；无裸分。"""
    db, state, _ = env
    # 同省灾情占用面
    db.insert_issue(
        state,
        kind="situation",
        title="陕西大饥",
        origin_kind="test",
        severity=80,
        region_hint="shaanxi",
        tags=["饥荒"],
        bar_value=10,
        bar_good_meaning="缓",
        bar_bad_meaning="剧",
        stage_text="s",
        cancellable="never",
        commit=True,
    )
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

    sim = build_simulator_payload(state, db, decree_text="d", previous_narrative="n")
    assert "execution_two_axis" in sim
    surface = sim["execution_two_axis"]
    dumped_surface = json.dumps(surface, ensure_ascii=False)
    # 投影面：无裸能力分、无派生负荷
    assert "owner_ability" not in dumped_surface
    assert "owner_load" not in dumped_surface
    block = next(p for p in surface["provinces"] if p["region_id"] == "shaanxi")
    assert isinstance(block["province_open_count"], int) and block["province_open_count"] >= 1
    assert block["owners"], "须有主办带宽行"
    owner = block["owners"][0]
    assert "owner_open_count" in owner
    assert "ability_band" in owner and isinstance(owner["ability_band"], str)
    assert owner["ability_band"]  # 非空档位词
    assert "distance_semantic_band" in owner
    assert "arrival_rows" in block
    assert isinstance(block["gentry_resistance"], str) and block["gentry_resistance"]
    assert block["disaster_rows"], "有灾 fixture 时须含灾情占用"
    assert all(
        isinstance(d.get("severity"), str) and d.get("severity")
        for d in block["disaster_rows"]
    )

    issues_ctx = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="issues",
    )
    assert "execution_two_axis" not in issues_ctx
    other = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="internal",
    )
    assert "execution_two_axis" not in other


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
    # owner A：dossier 为 canonical 八值成员，合法 none 归一
    dossier_out = db._normalize_directive_dossier_payload({
        "dossier_action_type": "revoke_decree",
        "target_kind": "dossier",
        "target_id": "42",
        "revoke_target_dossier_id": 42,
        "locality_scope": "无",
        "mode": "ordinary",
    })
    assert dossier_out["target_kind"] == "dossier"
    assert dossier_out["locality_scope"] == "none"
    assert int(dossier_out["revoke_target_dossier_id"]) == 42
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


# ── #654 断根 tracer（外部行为）────────────────────────────────────


def _insert_directive(db, state, *, text: str, payload: dict, status: str = "draft") -> int:
    cur = db.conn.execute(
        """
        INSERT INTO turn_directives
        (turn, year, period, event_id, actor, skill_id, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严", "",
            text, "test", status, "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def test_unnamed_national_fanout_fifteen_bi_ziyan_leads(env):
    """R2：真实 seed 未点将 national → 15 子案主办字面均为「毕自严」。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
    }
    did = _insert_directive(db, state, text="清丈天下田亩", payload=payload)
    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        directive_id=did,
        payload=payload,
        commit=True,
    )
    assert len(ids) == 15
    rows = db.list_dossiers_for_directive(did)
    assert [r["region_id"] for r in rows] == provinces
    leads = []
    for r in rows:
        own = [e["character_id"] for e in r["participant_roster"] if e.get("tier") == "主办"]
        assert len(own) == 1
        leads.append(own[0])
    assert leads == ["毕自严"] * 15
    # 辅证：中央空 rid 职司链首位（assignment 有 multi_month coverage）
    from ming_sim.executor_routing import resolve_lead_executors
    central = resolve_lead_executors(
        db.conn,
        action_type="assignment",
        payload={"transaction_category": "清丈"},
        region_id="",
    )
    assert central["leads"] == ["毕自严"]


def test_partial_replay_fills_missing_regions_only(env):
    """partial replay：先插真子集 → bulk 补齐全集；每 (directive, region) 恰一行、id 稳定。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
        "assignee_id": "毕自严",
    }
    did = _insert_directive(db, state, text="清丈天下田亩", payload=payload)
    # 先只落期望集真子集（前 3 省）
    subset = provinces[:3]
    kept = {}
    for rid in subset:
        row_id = db._create_decree_dossier_row(
            state,
            action_type="policy",
            decree_text="清丈天下田亩",
            target_kind="policy",
            target_id="清丈天下田亩",
            directive_id=did,
            payload=payload,
            participants=[{
                "character_id": "毕自严", "tier": "主办",
                "role": "", "delegator_id": None,
            }],
            region_id=rid,
            _skip_lead_route=True,
            commit=False,
        )
        kept[rid] = int(row_id)
    db.conn.commit()
    assert len(db.list_dossiers_for_directive(did)) == 3

    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        directive_id=did,
        payload=payload,
        commit=True,
    )
    rows = db.list_dossiers_for_directive(did)
    assert len(rows) == len(provinces)
    assert len(ids) == len(provinces)
    by_region = {r["region_id"]: r for r in rows}
    for rid, old_id in kept.items():
        assert by_region[rid]["id"] == old_id  # id 稳定
    # 复合键唯一
    pairs = [(r["region_id"], r["id"]) for r in rows]
    assert len({p[0] for p in pairs}) == len(provinces)


def test_validate_all_unmapped_zero_rows_before_insert(env):
    """任一省映射失败 → 首个 INSERT 前整旨零行。"""
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "修仙",  # 未映射
        "assignee_id": "",  # 显式未点将，走 duty 表
    }
    did = _insert_directive(db, state, text="清丈天下田亩", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        directive_id=did,
        payload=payload,
        commit=True,
    )
    assert ids == []
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before
    assert db.list_dossiers_for_directive(did) == []


def test_path2_confirm_directive_unmapped_rejects_zero_rows(env):
    """路 2 confirm_directive：映射失败 → 零行 + rejected。"""
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "修仙",
        "mode": "ordinary",
    }
    did = _insert_directive(
        db, state, text="清丈天下田亩", payload=payload, status="pending",
    )
    db.confirm_directive(did, state)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "rejected"
    assert db.list_dossiers_for_directive(did) == []


def test_path3_locality_fail_keeps_draft_no_text_in_rejection(env):
    """路 3：locality 失败保持 draft；rejection 仅 directive_id（P6 不裁剪旨文）。"""
    db, state, _ = env
    long_text = "敕令陕西清丈田亩" + ("甲" * 120)
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "none",  # region∧none fail-loud
        "dossier_action_type": "policy",
        "mode": "ordinary",
    }
    did = _insert_directive(db, state, text=long_text, payload=payload, status="draft")
    other_payload = {
        "target_kind": "region",
        "target_id": "henan",
        "locality_scope": "single",
        "dossier_action_type": "policy",
        "assignee_id": "毕自严",
        "mode": "ordinary",
    }
    other_id = _insert_directive(
        db, state, text="河南清丈", payload=other_payload, status="draft",
    )
    db.ensure_dossiers_for_draft_directives(state)
    bad = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    good = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (other_id,),
    ).fetchone()
    assert bad["status"] == "draft"  # 保持 draft
    assert db.list_dossiers_for_directive(did) == []
    # 并列第二旨不受影响
    assert good["status"] == "draft"
    assert len(db.list_dossiers_for_directive(other_id)) == 1

    rej = db.conn.execute(
        "SELECT item_json, reason, category FROM rejection_reports "
        "WHERE section='directive_locality' ORDER BY id DESC LIMIT 5",
    ).fetchall()
    assert rej, "应记 locality rejection"
    matched = [json.loads(r["item_json"]) for r in rej]
    hit = next(item for item in matched if item.get("directive_id") == did)
    assert "text" not in hit
    assert set(hit.keys()) == {"directive_id"}
    # 旨文片段不得出现在 item_json
    raw = next(r["item_json"] for r in rej if json.loads(r["item_json"]).get("directive_id") == did)
    assert "敕令陕西" not in raw
    assert "甲甲" not in raw


def test_path1_conversational_draft_unmapped_marks_failed(env):
    """路 1 _commit_conversational_draft：成案零行 → pending failed、无案卷。"""
    db, state, _ = env
    payload = {
        "text": "清丈天下田亩",
        "actor": "毕自严",
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "修仙",
        "mode": "ordinary",
        "_canonical_pending_directive": True,
        "_directive_status": "draft",
    }
    cur = db.conn.execute(
        """
        INSERT INTO pending_actions
        (turn, minister_name, kind, action, target_id, payload_json, status)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            state.turn, "毕自严",
            "directive", "拟旨", "清丈天下田亩",
            json.dumps(payload, ensure_ascii=False), "pending",
        ),
    )
    pa_id = int(cur.lastrowid)
    db.conn.commit()
    pa = dict(db.conn.execute(
        "SELECT * FROM pending_actions WHERE id=?", (pa_id,),
    ).fetchone())
    from ming_sim.applier import RejectionCollector
    result = db._commit_conversational_draft(
        state, pa, payload, content=db.content,
        rejection_collector=RejectionCollector(),
    )
    assert result is None
    st = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE id=?",
        (pa_id,),
    ).fetchone()
    assert st["status"] == "failed"
    # 回滚后不应残留 directive 案卷
    n = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    # 允许他用例无关行；本 pending 名下必须为空
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers WHERE pending_action_id=?",
        (pa_id,),
    ).fetchone()["n"] == 0


def test_national_vs_per_province_two_axis_equivalence(env):
    """R2：(a) national 未点将 → 15×毕自严；(b) 单省未点将无本地对口 → 空链怠办；
    两侧均点将后再比两轴等价。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    from ming_sim.executor_routing import resolve_lead_executors

    # (a) national 未点将
    payload_n = {
        "target_kind": "policy",
        "target_id": "清丈-A",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
    }
    did_n = _insert_directive(db, state, text="清丈-A", payload=payload_n)
    ids_n = db.create_decree_dossiers(
        state, action_type="policy", decree_text="清丈-A",
        target_kind="policy", target_id="清丈-A",
        directive_id=did_n, payload=payload_n, commit=True,
    )
    assert len(ids_n) == 15
    leads_n = []
    for r in db.list_dossiers_for_directive(did_n):
        own = [e["character_id"] for e in r["participant_roster"] if e.get("tier") == "主办"]
        assert own == ["毕自严"]
        leads_n.append(own[0])
    assert leads_n == ["毕自严"] * 15

    # (b) 单省未点将、无本地对口 → 空链/怠办（钉无通用 fallback）
    payload_s = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
    }
    single = resolve_lead_executors(
        db.conn, action_type="policy", payload=payload_s, region_id="shaanxi",
    )
    assert single["leads"] == []
    assert (single.get("signal") or {}).get("reason") == "vacancy_chain_exhausted"

    # 两侧均合法点将后再比两轴
    def _leads_surface(directive_ids):
        for did in directive_ids:
            for row in db.list_dossiers_for_directive(did):
                db.conn.execute(
                    "UPDATE decree_dossiers SET status='executing' WHERE id=?",
                    (int(row["id"]),),
                )
        db.conn.commit()
        surface = build_execution_two_axis_surface(
            db, state.turn, transit_semantics=[],
        )
        out = {}
        for block in surface["provinces"]:
            rid = block["region_id"]
            if rid == "":
                continue
            out[rid] = {
                "province_open_count": block["province_open_count"],
                "owners": sorted(
                    (
                        o["owner_name"],
                        o["owner_open_count"],
                        o["distance_semantic_band"],
                    )
                    for o in block["owners"]
                ),
            }
        return out

    db.conn.execute("UPDATE decree_dossiers SET status='closed'")
    db.conn.commit()

    payload_n2 = {
        "target_kind": "policy",
        "target_id": "清丈-B",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
        "assignee_id": "毕自严",
    }
    did_n2 = _insert_directive(db, state, text="清丈-B", payload=payload_n2)
    db.create_decree_dossiers(
        state, action_type="policy", decree_text="清丈-B",
        target_kind="policy", target_id="清丈-B",
        directive_id=did_n2, payload=payload_n2, commit=True,
    )
    surface_a = _leads_surface([did_n2])

    db.conn.execute("UPDATE decree_dossiers SET status='closed'")
    db.conn.commit()

    dids = []
    for rid in provinces:
        payload_sp = {
            "target_kind": "region",
            "target_id": rid,
            "locality_scope": "single",
            "dossier_action_type": "policy",
            "transaction_category": "清丈",
            "assignee_id": "毕自严",
        }
        did = _insert_directive(db, state, text=f"清丈-{rid}", payload=payload_sp)
        db.create_decree_dossiers(
            state, action_type="policy", decree_text=f"清丈-{rid}",
            target_kind="region", target_id=rid,
            directive_id=did, payload=payload_sp, commit=True,
        )
        dids.append(did)
    surface_b = _leads_surface(dids)

    assert set(surface_a) == set(surface_b) == set(provinces)
    for rid in provinces:
        assert surface_a[rid]["province_open_count"] == surface_b[rid]["province_open_count"] == 1
        assert surface_a[rid]["owners"] == surface_b[rid]["owners"]


# ── 8×3 locality 矩阵（参数化）──────────────────────────────────


@pytest.mark.parametrize(
    "target_kind,scope,action,expect",
    [
        # policy/issue/account × national → N（白名单动作）
        ("policy", "national", "policy", "N"),
        ("issue", "national", "policy", "N"),
        ("account", "national", "special_decree", "N"),
        # policy/issue/account × single → fail
        ("policy", "single", "policy", "fail"),
        ("issue", "single", "policy", "fail"),
        # policy/issue/account × none → ''
        ("policy", "none", "policy", "empty"),
        ("issue", "none", "special_decree", "empty"),
        ("account", "none", "policy", "empty"),
        # character/office/army × national → fail
        ("character", "national", "policy", "fail"),
        ("office", "national", "policy", "fail"),
        ("army", "national", "policy", "fail"),
        # character/office/army × single → fail
        ("character", "single", "policy", "fail"),
        ("office", "single", "policy", "fail"),
        ("army", "single", "policy", "fail"),
        # character/office/army × none → ''
        ("character", "none", "policy", "empty"),
        ("office", "none", "policy", "empty"),
        ("army", "none", "policy", "empty"),
        # region × national/none → fail；single → R1
        ("region", "national", "policy", "fail"),
        ("region", "none", "policy", "fail"),
        ("region", "single", "policy", "R1"),
        # dossier 三格：仅 none → 单行 ''；single/national fail-loud
        ("dossier", "none", "revoke_decree", "empty"),
        ("dossier", "single", "revoke_decree", "fail"),
        ("dossier", "national", "revoke_decree", "fail"),
        ("dossier", None, "revoke_decree", "empty"),
        # 缺省 scope（normalize → none）
        ("policy", None, "policy", "empty"),
        ("region", None, "policy", "fail"),
        # unknown
        ("unknown", "none", "policy", "fail"),
        ("policy", "全省", "policy", "fail"),
        # national 动作不在白名单
        ("policy", "national", "assignment", "fail"),
    ],
)
def test_locality_matrix_8x3_and_unknown(env, target_kind, scope, action, expect):
    db, _, content = env
    payload = {"target_kind": target_kind, "target_id": "shaanxi" if target_kind == "region" else "x"}
    if scope is not None:
        payload["locality_scope"] = scope
    if expect == "fail":
        with pytest.raises(ValueError):
            resolve_dossier_region_ids(
                db.conn, action_type=action, payload=payload,
                regions_content=content.regions,
            )
        return
    regions = resolve_dossier_region_ids(
        db.conn, action_type=action, payload=payload,
        regions_content=content.regions,
    )
    if expect == "N":
        assert regions == ming_province_ids(db.conn)
    elif expect == "empty":
        assert regions == [""]
    elif expect == "R1":
        assert regions == ["shaanxi"]


def test_locality_fail_create_decree_dossiers_zero_rows(env):
    """fail 格走真实 bulk 入口：异常 + 零行。"""
    db, state, _ = env
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "none",
        "dossier_action_type": "policy",
    }
    did = _insert_directive(db, state, text="陕", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    with pytest.raises(ValueError):
        db.create_decree_dossiers(
            state, action_type="policy", decree_text="陕",
            target_kind="region", target_id="shaanxi",
            directive_id=did, payload=payload, commit=True,
        )
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before


# ── 两轴 TSV 一省一块 + 字段完备 ─────────────────────────────────


def test_two_axis_tsv_province_block_golden(env):
    """完整 TSV 字符串：灾行先于非灾行；gentry_slice/officials_slice 在串内。"""
    db, state, _ = env
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='' WHERE name='毕自严'",
    )
    # 两灾 + 一主办案卷（D1 tags 真源）
    for title, tag, sev in (("轻灾", "灾情", 20), ("重灾", "饥荒", 80)):
        db.insert_issue(
            state,
            kind="situation",
            title=title,
            origin_kind="test",
            severity=sev,
            region_hint="shaanxi",
            tags=[tag],
            bar_value=10,
            bar_good_meaning="缓",
            bar_bad_meaning="剧",
            stage_text="s",
            cancellable="never",
            commit=True,
        )
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
    # 第二主办
    did2 = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="清丈陕",
        target_kind="issue",
        target_id="survey",
        payload={
            "target_kind": "issue", "target_id": "survey", "locality_scope": "none",
            "assignee_id": "杨嗣昌", "transaction_category": "清丈",
            "participant_roster": [
                {"character_id": "杨嗣昌", "tier": "主办", "role": "", "delegator_id": None},
            ],
        },
        participants=[
            {"character_id": "杨嗣昌", "tier": "主办", "role": "", "delegator_id": None},
        ],
    )
    db.conn.execute(
        "UPDATE characters SET location='shaanxi', transit_to='' WHERE name='杨嗣昌'",
    )
    _promote_executing(db, did2, "shaanxi")

    surface = build_execution_two_axis_surface(
        db, state.turn, transit_semantics=[],
    )
    tsv = surface["tsv"]
    assert "gentry_slice" in tsv or "士绅盘" in tsv
    assert "officials_slice" in tsv or "官僚盘" in tsv
    # 省块内：灾情行先于省盘/主办
    lines = [ln for ln in tsv.splitlines() if ln.startswith("灾情\tshaanxi")
             or ln.startswith("省盘\tshaanxi") or ln.startswith("主办\tshaanxi")]
    assert lines, tsv
    kinds = [ln.split("\t", 1)[0] for ln in lines]
    assert kinds[0] == "灾情"
    assert "省盘" in kinds
    assert kinds.index("灾情") < kinds.index("省盘")
    first_owner = next(i for i, k in enumerate(kinds) if k == "主办")
    assert kinds.index("省盘") < first_owner
    # 重灾先于轻灾（标题仍在第 19 列 / 0-based 18；第 20 列为到差态空串）
    disaster_titles = [ln.split("\t")[18] for ln in lines if ln.startswith("灾情")]
    assert disaster_titles[0] == "重灾"
    # 切片紧凑串或哨兵出现在省盘行
    province_line = next(ln for ln in lines if ln.startswith("省盘"))
    assert re.search(r"\d+/\d+/\d+|无记录|不参与", province_line)
    # 两主办均在
    owner_blob = "\n".join(ln for ln in lines if ln.startswith("主办"))
    assert "毕自严" in owner_blob and "杨嗣昌" in owner_blob


def test_two_axis_tsv_transport_framing_three_text_entrances():
    """#654/#673 TSV framing：title/owner_name/dutang_faction 控制符不破 20 列 ABI。

    纯调 _render_two_axis_tsv；逐物理行验列数，禁靠行类前缀过滤（伪行可任意开头）。
    """
    title_raw = "甲\t伪列\n主办\tx"
    owner_raw = "乙\t伪\n丙"
    faction_raw = "甲\t伪\n主办\tx"
    literal_bs_t = "\\t"  # two chars: backslash + t

    provinces = [
        {
            "region_id": "shaanxi",
            "province_open_count": 1,
            "gentry_resistance": 0,
            "bandit_pressure": 0,
            "bandit_strength": "无",
            "dutang_faction": faction_raw,
            "dutang_integrity": "无记录",
            "gentry_slice": None,
            "officials_slice": None,
            "disaster_rows": [
                {
                    "id": "d1",
                    "kind": "灾情",
                    "severity": 50,
                    "title": title_raw,
                },
                {
                    "id": "d2",
                    "kind": "灾情",
                    "severity": 10,
                    "title": literal_bs_t,  # distinguish from raw TAB encode
                },
            ],
            "owners": [
                {
                    "owner_name": owner_raw,
                    "owner_open_count": 1,
                    "owner_ability": 50,
                    "owner_load": 1.0,
                    "distance_semantic_band": BAND_LOCAL,
                },
            ],
        }
    ]

    tsv = _render_two_axis_tsv(provinces)
    physical = tsv.splitlines()
    # 导语 + header + 灾×2 + 省盘×1 + 主办×1 = 6 物理行（无分裂残行；无 arrival_rows）
    assert len(physical) == 6, physical
    assert physical[0].startswith("##")
    header = physical[1]
    assert len(header.split("\t")) == 20
    assert header.endswith("\t到差态")

    data_lines = physical[2:]
    assert len(data_lines) == 4
    for ln in data_lines:
        cells = ln.split("\t")
        assert len(cells) == 20, (len(cells), ln)
        assert cells[19] == ""  # 旧行第 20 列空
        # 单元格内无 raw TAB/LF/CR（split 已按 TAB；行内亦不得含 LF/CR）
        assert "\n" not in ln and "\r" not in ln
        for cell in cells:
            assert "\t" not in cell
            assert "\n" not in cell
            assert "\r" not in cell

    # 可逆可见编码：raw 控制符 → 字面 \t/\n；反斜杠可区分
    assert "\\t" in tsv and "\\n" in tsv
    # title 含 raw TAB+LF → 编码后出现 \t 与 \n（非 raw）
    disaster_title_cell = data_lines[0].split("\t")[18]
    assert disaster_title_cell == _escape_tsv_cell(title_raw)
    assert disaster_title_cell == "甲\\t伪列\\n主办\\tx"
    # 字面 \t（两字符）先翻倍反斜杠 → \\t，与 raw TAB 的 \t 可区分
    literal_title_cell = data_lines[1].split("\t")[18]
    assert literal_title_cell == _escape_tsv_cell(literal_bs_t)
    assert literal_title_cell == "\\\\t"
    assert literal_title_cell != disaster_title_cell

    faction_cell = data_lines[2].split("\t")[6]
    assert faction_cell == _escape_tsv_cell(faction_raw)
    assert faction_cell == "甲\\t伪\\n主办\\tx"

    owner_cell = data_lines[3].split("\t")[10]
    assert owner_cell == _escape_tsv_cell(owner_raw)
    assert owner_cell == "乙\\t伪\\n丙"

    # durable/structured 不动：同一 fixture 原值仍含控制符
    assert provinces[0]["dutang_faction"] is faction_raw
    assert provinces[0]["dutang_faction"] == "甲\t伪\n主办\tx"
    assert provinces[0]["disaster_rows"][0]["title"] is title_raw
    assert provinces[0]["disaster_rows"][0]["title"] == "甲\t伪列\n主办\tx"
    assert provinces[0]["owners"][0]["owner_name"] is owner_raw
    assert provinces[0]["owners"][0]["owner_name"] == "乙\t伪\n丙"

    # CR 变体
    cr_provinces = [
        {
            "region_id": "henan",
            "province_open_count": 0,
            "gentry_resistance": 0,
            "bandit_pressure": 0,
            "bandit_strength": "无",
            "dutang_faction": "派\r系",
            "dutang_integrity": "无记录",
            "gentry_slice": None,
            "officials_slice": None,
            "disaster_rows": [
                {"id": "c1", "kind": "灾情", "severity": 1, "title": "题\r目"},
            ],
            "owners": [
                {
                    "owner_name": "主\r办",
                    "owner_open_count": 0,
                    "owner_ability": 1,
                    "owner_load": 0.0,
                    "distance_semantic_band": BAND_NEAR,
                },
            ],
        }
    ]
    cr_tsv = _render_two_axis_tsv(cr_provinces)
    cr_phys = cr_tsv.splitlines()
    assert len(cr_phys) == 5  # 导语+header+灾+省+主办
    for ln in cr_phys[2:]:
        assert len(ln.split("\t")) == 20
        assert "\r" not in ln
    assert "\\r" in cr_tsv


def test_two_axis_tsv_escape_noop_on_clean_cells():
    """无控制符时转义 no-op，既有 golden 语义不漂移。"""
    clean = "陕西饥荒"
    assert _escape_tsv_cell(clean) == clean
    assert _escape_tsv_cell(42) == "42"
    assert _escape_tsv_cell(None) == "None"
    provinces = [
        {
            "region_id": "shaanxi",
            "province_open_count": 0,
            "gentry_resistance": 0,
            "bandit_pressure": 0,
            "bandit_strength": "无",
            "dutang_faction": "东林",
            "dutang_integrity": "无记录",
            "gentry_slice": None,
            "officials_slice": None,
            "disaster_rows": [
                {"id": "x", "kind": "灾情", "severity": 1, "title": clean},
            ],
            "owners": [
                {
                    "owner_name": "毕自严",
                    "owner_open_count": 1,
                    "owner_ability": 70,
                    "owner_load": 1.0,
                    "distance_semantic_band": BAND_LOCAL,
                },
            ],
        }
    ]
    tsv = _render_two_axis_tsv(provinces)
    lines = tsv.splitlines()
    assert len(lines) == 5
    # 标题在第 19 列；第 20 列到差态为空
    assert lines[2].split("\t")[18] == clean
    assert lines[2].split("\t")[19] == ""
    assert "毕自严" in lines[4]
    assert "东林" in lines[3]
    # 无额外 escape 产物
    assert "\\t" not in tsv and "\\n" not in tsv and "\\r" not in tsv


def test_cli_target_kinds_accepts_canonical_eight():
    """producer 与 durable 共八值（含 dossier）：合法通过、法外 fail-loud。
    单旨/多旨 guidance 均由 TARGET_KINDS 派生，含 dossier、无七值残留。"""
    from ming_sim import cli_backend as cb
    assert TARGET_KINDS is EP_TARGET_KINDS
    assert "dossier" in TARGET_KINDS
    assert TARGET_KINDS == frozenset({
        "policy", "character", "office", "army", "region", "issue", "account",
        "dossier",
    })
    for kind in sorted(TARGET_KINDS):
        assert cb._coerce_draft_target_kind(kind) == kind
    with pytest.raises(ValueError):
        cb._coerce_draft_target_kind("not_a_real_kind")
    guidance = cb._draft_target_kind_guidance()
    assert guidance == "|".join(sorted(TARGET_KINDS))
    assert "dossier" in guidance
    # 七值残留（缺 dossier）不得再出现
    seven = "policy|character|office|army|region|issue|account"
    assert seven != guidance
    assert guidance.count("|") == 7  # 八值七分隔


def test_revoke_decree_523_producer_durable_oracle_chain(env):
    """#523 producer→durable→oracle：dossier 目标恰落一条 region_id='' 案卷。

    owner A：八值成员、dossier 三格、unknown 拒绝、revoke identity 保留。
    """
    import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
    from ming_sim.action_materialize import stage_revoke_decree_candidate

    db, state, content = env
    holder = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])

    # 已颁可撤成命（目标身份）
    target_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="河工成命",
        target_kind="issue",
        target_id="河工成命",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={
            "mode": "ordinary", "text": "河工成命",
            "target_kind": "issue", "target_id": "河工成命",
            "locality_scope": "none",
        },
    )
    db.apply_dossier_promulgation(state, target_id, "promulgated")

    # 1) #523 真实 producer
    pending_id = stage_revoke_decree_candidate(
        db,
        state.turn,
        holder,
        text=f"前旨作废，撤回案卷{target_id}。",
        target_id=str(target_id),
        target_kind="dossier",
    )
    assert pending_id
    pending_row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    pending = json.loads(pending_row["payload_json"])
    assert pending["dossier_action_type"] == "revoke_decree"
    assert pending["target_kind"] == "dossier"
    assert int(pending["revoke_target_dossier_id"]) == int(target_id)
    assert pending["target_kind"] in TARGET_KINDS

    # 2) durable normalization 闭集直校验（无 dossier 暗例外）
    normalized = db._normalize_directive_dossier_payload(
        pending, content=content, current_turn=int(state.turn),
    )
    assert normalized["target_kind"] == "dossier"
    assert normalized["locality_scope"] == "none"
    assert int(normalized["revoke_target_dossier_id"]) == int(target_id)

    # 3) 真实收夜成案入口（commit_pending_actions → normalize → create_decree_dossiers）
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    revoke_rows = [
        d for d in db.list_decree_dossiers()
        if int(d.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert len(revoke_rows) == 1
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before + 1
    row = revoke_rows[0]
    assert row["region_id"] == ""
    assert row["action_type"] == "revoke_decree"
    assert row["target_kind"] == "dossier"
    assert str(row["target_id"]) == str(target_id)
    stored = json.loads(str(row.get("payload_json") or "{}"))
    assert int(stored.get("revoke_target_dossier_id") or 0) == int(target_id)
    assert stored.get("target_kind") == "dossier"

    # 4) dossier 三格 + unknown 拒绝（与矩阵同契约）
    assert resolve_dossier_region_ids(
        db.conn,
        action_type="revoke_decree",
        payload={"target_kind": "dossier", "target_id": str(target_id),
                 "locality_scope": "none"},
    ) == [""]
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            action_type="revoke_decree",
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "single"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            action_type="revoke_decree",
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "national"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            action_type="policy",
            payload={"target_kind": "not_a_kind", "target_id": "x",
                     "locality_scope": "none"},
        )
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "not_a_kind",
            "target_id": "x",
            "mode": "ordinary",
        })


# ── #654 A–H 断根补测 ─────────────────────────────────────────────


def test_issues_only_region_id_projection(env):
    """C：region_id 仅 issues 模块 slim 投影；internal/personnel_secret 等不见该键。"""
    db, state, _ = env
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="陕差",
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
    sim = build_simulator_payload(state, db, decree_text="d", previous_narrative="n")
    issues_ctx = build_extractor_shared_context(
        db, state, narrative="n", decree_text="d", module="issues",
    )
    dossiers = issues_ctx["decree_dossiers"]
    assert dossiers and "region_id" in dossiers[0]
    assert dossiers[0]["region_id"] == "shaanxi"
    for module in ("internal", "personnel_secret", "military_external"):
        other = build_extractor_shared_context(
            db, state, narrative="n", decree_text="d", module=module,
        )
        for row in other.get("decree_dossiers") or []:
            assert "region_id" not in row, module


def test_dutang_three_states(env):
    """F：无 slot=无记录；有 slot 无 holder=出缺；有 holder=派系/操守。"""
    from ming_sim.execution_pressure import _dutang_fields, NO_RECORD, VACANT
    db, state, _ = env
    # shandong 无督抚 slot
    assert _dutang_fields(db.conn, "shandong") == (NO_RECORD, NO_RECORD)
    # shaanxi 有 slot、holder 空
    fac, integ = _dutang_fields(db.conn, "shaanxi")
    assert fac == VACANT and integ == VACANT
    # 视图像：holder 由 characters.office 对齐 office_slots.office_title
    db.conn.execute(
        "UPDATE characters SET office='陕西巡抚', office_type='督抚', "
        "status='active', power_id='ming' WHERE name='毕自严'"
    )
    db.conn.commit()
    fac2, integ2 = _dutang_fields(db.conn, "shaanxi")
    ch = db.conn.execute(
        "SELECT faction, integrity FROM characters WHERE name='毕自严'"
    ).fetchone()
    assert fac2 == str(ch["faction"] or "")
    assert integ2 == int(ch["integrity"] or 0)


def test_location_canonical_seed_and_write_seam(env, tmp_path):
    """G：fresh seed 三人 beizhili；写缝别名归一；未知 fail-loud；在途保全。"""
    import shutil
    from ming_sim.db import GameDB
    from ming_sim.matching import canonical_region_id_exact
    from ming_sim.distance import DistanceMatrix
    from ming_sim.paths import bundled_path

    db, state, content = env
    for name in ("乔允升", "许誉卿", "韩一良"):
        loc = db.conn.execute(
            "SELECT location FROM characters WHERE name=?", (name,),
        ).fetchone()["location"]
        assert loc == "beizhili", name
    # exact helper
    assert canonical_region_id_exact("beijing", content.regions) == "beizhili"
    assert canonical_region_id_exact("京师", content.regions) == "beizhili"
    assert canonical_region_id_exact("beizhili", content.regions) == "beizhili"
    assert canonical_region_id_exact("", content.regions) == ""
    assert canonical_region_id_exact("atlantis", content.regions) is None
    # distance beizhili→shaanxi 不炸
    matrix = DistanceMatrix.from_file(bundled_path("content", "distance_matrix.json"))
    assert matrix.travel_time("beizhili", "shaanxi") > 0
    # write seam alias + 在途字段按入参保留
    db.set_character_transit(
        "毕自严",
        location="beijing",
        transit_to="shaanxi",
        distance_remaining=2.5,
        speed_factor=1.0,
        start_turn=3,
        commit=True,
    )
    row = db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name='毕自严'"
    ).fetchone()
    assert row["location"] == "beizhili"
    assert row["transit_to"] == "shaanxi"
    assert float(row["transit_distance_remaining"]) == 2.5
    assert float(row["transit_speed_factor"]) == 1.0
    assert int(row["transit_start_turn"]) == 3
    db.set_character_transit("毕自严", location="京师", commit=True)
    assert db.conn.execute(
        "SELECT location FROM characters WHERE name='毕自严'"
    ).fetchone()["location"] == "beizhili"
    with pytest.raises(ValueError, match="location"):
        db.set_character_transit("毕自严", location="atlantis", commit=True)
    # 旧档在途保全：独立副本预置别名 + transit → 开档 migrate 后四字段不变
    clone = tmp_path / "loc_migrate.db"
    shutil.copyfile(db.path, clone)
    # 绕过写缝，直接预置旧别名（模拟旧档）
    import sqlite3
    conn = sqlite3.connect(clone)
    conn.execute(
        "UPDATE characters SET location='beijing', transit_to='shaanxi', "
        "transit_distance_remaining=2.5, transit_speed_factor=1.0, "
        "transit_start_turn=3 WHERE name='毕自严'"
    )
    conn.commit()
    conn.close()
    restored = GameDB(str(clone), content)
    try:
        row = restored.conn.execute(
            "SELECT location, transit_to, transit_distance_remaining, "
            "transit_speed_factor, transit_start_turn FROM characters "
            "WHERE name='毕自严'"
        ).fetchone()
        assert row["location"] == "beizhili"
        assert row["transit_to"] == "shaanxi"
        assert float(row["transit_distance_remaining"]) == 2.5
        assert float(row["transit_speed_factor"]) == 1.0
        assert int(row["transit_start_turn"]) == 3
    finally:
        restored.close()
    # 未知非空开档 fail-loud
    bad = tmp_path / "loc_bad.db"
    shutil.copyfile(db.path, bad)
    conn = sqlite3.connect(bad)
    conn.execute("UPDATE characters SET location='atlantis' WHERE name='毕自严'")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="location|别名"):
        GameDB(str(bad), content)


def test_authorization_region_gets_single_locality(env):
    """D：authorization region 目标 producer 写 locality_scope=single。"""
    import ming_sim.action_materialize  # noqa: F401
    from ming_sim.action_materialize import stage_authorization_candidate

    db, state, _ = env
    holder = "毕自严"
    pending_id = stage_authorization_candidate(
        db,
        state.turn,
        holder,
        text="准其便宜行事于陕西。",
        privilege="便宜行事",
        target_id="shaanxi",
        target_kind="region",
    )
    assert pending_id
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["target_kind"] == "region"
    assert payload["locality_scope"] == "single"
    # 新建非 region 路径每次显式 none
    pending2 = stage_authorization_candidate(
        db,
        state.turn,
        holder,
        text="准其便宜行事。",
        privilege="便宜行事",
        target_id=holder,
        target_kind="character",
    )
    assert pending2
    row2 = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending2,),
    ).fetchone()
    payload2 = json.loads(row2["payload_json"])
    assert payload2["locality_scope"] == "none"


def test_grant_region_to_character_amendment_clears_single_locality(env):
    """#654 P2：同一 pending grant region→character 改草须覆盖 locality_scope=none。"""
    import ming_sim.action_materialize  # noqa: F401
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    db, state, content = env
    actor = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])

    pending_id = stage_grant_allocation_candidate(
        db,
        state.turn,
        actor,
        text="发内帑赈陕西。",
        grant_action="赈灾",
        target_kind="region",
        target_id="shaanxi",
        amount=10,
        account="内库",
    )
    assert pending_id
    first = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert first["target_kind"] == "region"
    assert first["locality_scope"] == "single"

    updated = stage_grant_allocation_candidate(
        db,
        state.turn,
        actor,
        text=f"赏赉{actor}银两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=actor,
        amount=5,
        account="内库",
        target_candidate=str(pending_id),
    )
    assert updated == pending_id
    revised = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert revised["target_kind"] == "character"
    assert revised["locality_scope"] == "none"

    normalized = db._normalize_directive_dossier_payload(
        revised, content=content, current_turn=int(state.turn),
    )
    assert normalized["target_kind"] == "character"
    assert normalized["locality_scope"] == "none"

    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    rows = [
        d for d in db.list_decree_dossiers()
        if int(d.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert len(rows) == 1
    stored = json.loads(str(rows[0].get("payload_json") or "{}"))
    assert stored.get("locality_scope") == "none"
    assert rows[0]["target_kind"] == "character"


def test_authorization_region_to_character_amendment_clears_single_locality(env):
    """#654 P2：同一 pending authorization region→character 改草须覆盖 locality_scope=none。"""
    import ming_sim.action_materialize  # noqa: F401
    from ming_sim.action_materialize import stage_authorization_candidate

    db, state, content = env
    holder = "毕自严"

    pending_id = stage_authorization_candidate(
        db,
        state.turn,
        holder,
        text="准其便宜行事于陕西。",
        privilege="便宜行事",
        target_id="shaanxi",
        target_kind="region",
    )
    assert pending_id
    first = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert first["target_kind"] == "region"
    assert first["locality_scope"] == "single"

    updated = stage_authorization_candidate(
        db,
        state.turn,
        holder,
        text="准其便宜行事。",
        privilege="便宜行事",
        target_id=holder,
        target_kind="character",
        target_candidate=str(pending_id),
    )
    assert updated == pending_id
    revised = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert revised["target_kind"] == "character"
    assert revised["locality_scope"] == "none"

    normalized = db._normalize_directive_dossier_payload(
        revised, content=content, current_turn=int(state.turn),
    )
    assert normalized["target_kind"] == "character"
    assert normalized["locality_scope"] == "none"

    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    rows = [
        d for d in db.list_decree_dossiers()
        if int(d.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert len(rows) == 1
    stored = json.loads(str(rows[0].get("payload_json") or "{}"))
    assert stored.get("locality_scope") == "none"
    assert rows[0]["target_kind"] == "character"
