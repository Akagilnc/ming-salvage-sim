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


def _seed_provincial_hubu(db, state, provinces):
    """每省一名户部主官（尚书 stem），location=省 id；真实 resolver 可逐省命中。"""
    from ming_sim.models import Character

    names = []
    for i, rid in enumerate(provinces):
        name = f"清丈使{i:02d}"
        names.append(name)
        db.add_character(
            state,
            Character(
                name=name,
                office="户部尚书",
                office_type="户部",
                faction="中立",
                aliases=[],
                personal_skills=[],
                loyalty=50,
                ability=60,
                integrity=50,
                courage=50,
                style="稳健",
                power_id="ming",
                location=rid,
                status="active",
            ),
            source="test-654",
            commit=False,
        )
    db.conn.commit()
    return names


def test_unnamed_national_fanout_fifteen_distinct_duty_leads(env):
    """未点将 15 省：transaction_category 命中 duty_routes → 逐省真实主办互异。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    holders = _seed_provincial_hubu(db, state, provinces)
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
    assert leads == holders
    assert len(set(leads)) == 15


def test_partial_replay_fills_missing_regions_only(env):
    """partial replay：先插真子集 → bulk 补齐全集；每 (directive, region) 恰一行、id 稳定。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    _seed_provincial_hubu(db, state, provinces)
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
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
    provinces = ming_province_ids(db.conn)
    _seed_provincial_hubu(db, state, provinces)
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "修仙",  # 未映射
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
    """1 道 national 旨 vs N 道单省旨 → 两轴承办/属地层逐格相同。"""
    db, state, _ = env
    provinces = ming_province_ids(db.conn)
    holders = _seed_provincial_hubu(db, state, provinces)

    def _leads_surface(directive_ids):
        # 全部 promote executing 后建表面
        for did in directive_ids:
            for row in db.list_dossiers_for_directive(did):
                db.conn.execute(
                    "UPDATE decree_dossiers SET status='executing' WHERE id=?",
                    (int(row["id"]),),
                )
        db.conn.commit()
        surface = build_execution_two_axis_surface(db, state.turn)
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

    # A: 一道 national
    payload_n = {
        "target_kind": "policy",
        "target_id": "清丈-A",
        "locality_scope": "national",
        "dossier_action_type": "policy",
        "transaction_category": "清丈",
    }
    did_n = _insert_directive(db, state, text="清丈-A", payload=payload_n)
    db.create_decree_dossiers(
        state, action_type="policy", decree_text="清丈-A",
        target_kind="policy", target_id="清丈-A",
        directive_id=did_n, payload=payload_n, commit=True,
    )
    surface_a = _leads_surface([did_n])

    # 清场 executing，改用 N 道单省（新库行）
    db.conn.execute("UPDATE decree_dossiers SET status='closed'")
    db.conn.commit()

    dids = []
    for rid, holder in zip(provinces, holders):
        payload_s = {
            "target_kind": "region",
            "target_id": rid,
            "locality_scope": "single",
            "dossier_action_type": "policy",
            "transaction_category": "清丈",
            # 单省未点将：region_id 接缝应解析到该省 holder
        }
        did = _insert_directive(db, state, text=f"清丈-{rid}", payload=payload_s)
        db.create_decree_dossiers(
            state, action_type="policy", decree_text=f"清丈-{rid}",
            target_kind="region", target_id=rid,
            directive_id=did, payload=payload_s, commit=True,
        )
        dids.append(did)
    surface_b = _leads_surface(dids)

    assert set(surface_a) == set(surface_b) == set(provinces)
    for rid in provinces:
        assert surface_a[rid]["province_open_count"] == surface_b[rid]["province_open_count"] == 1
        assert surface_a[rid]["owners"] == surface_b[rid]["owners"]


# ── 21 格 locality 矩阵（参数化）──────────────────────────────────


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
def test_locality_matrix_21_and_unknown(env, target_kind, scope, action, expect):
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
    # 两灾 + 一主办案卷
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

    surface = build_execution_two_axis_surface(db, state.turn)
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
    # 重灾先于轻灾
    disaster_titles = [ln.split("\t")[-1] for ln in lines if ln.startswith("灾情")]
    assert disaster_titles[0] == "重灾"
    # 切片紧凑串或哨兵出现在省盘行
    province_line = next(ln for ln in lines if ln.startswith("省盘"))
    assert re.search(r"\d+/\d+/\d+|无记录|不参与", province_line)
    # 两主办均在
    owner_blob = "\n".join(ln for ln in lines if ln.startswith("主办"))
    assert "毕自严" in owner_blob and "杨嗣昌" in owner_blob


def test_cli_target_kinds_accepts_canonical_seven():
    """producer 与 durable 共七值：合法通过、法外 fail-loud（不测 import 身份）。"""
    from ming_sim import cli_backend as cb
    from ming_sim.execution_pressure import TARGET_KINDS
    for kind in sorted(TARGET_KINDS):
        assert cb._coerce_draft_target_kind(kind) == kind
    with pytest.raises(ValueError):
        cb._coerce_draft_target_kind("not_a_real_kind")
