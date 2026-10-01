"""#654 差务属地 oracle：组合矩阵及案卷归属。"""

from __future__ import annotations

import json

import pytest

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    TARGET_KINDS as EP_TARGET_KINDS,
    normalize_locality_scope,
    resolve_dossier_region_ids,
)


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


# ── 词表 / scope 归一 ──────────────────────────────────────────────


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


def test_mapper_rejects_contradictory_locality_scope_without_overwrite():
    """#1624：禁止按 target_kind 覆盖 locality 掩盖错误目标；显式矛盾 fail-loud。

    契约落在 StructuredDecreeCombinationError.field_failures/failed_fields
    （权威结构化失败事实）；不得盯异常措辞。
    """
    from ming_sim.rescript_actions import map_rescript_option_or_choice
    from ming_sim.structured_decree import StructuredDecreeCombinationError

    with pytest.raises(StructuredDecreeCombinationError) as ei_issue_single:
        map_rescript_option_or_choice({
            "action_type": "authorization",
            "label": "赈抚",
            "target_kind": "issue",
            "target_id": "relief",
            "locality_scope": "single",
            "holder_id": "毕自严",
            "privilege": "便宜行事",
        })
    assert "locality_scope" in ei_issue_single.value.failed_fields
    assert "target_kind" in ei_issue_single.value.failed_fields
    ff_issue = {
        str(f["field"]): f for f in ei_issue_single.value.field_failures
    }
    assert ff_issue["locality_scope"]["current"] == "single"
    assert ff_issue["target_kind"]["current"] == "issue"

    with pytest.raises(StructuredDecreeCombinationError) as ei_region_none:
        map_rescript_option_or_choice({
            "action_type": "authorization",
            "label": "陕赈",
            "target_kind": "region",
            "target_id": "shaanxi",
            "locality_scope": "none",
            "holder_id": "毕自严",
            "privilege": "便宜行事",
        })
    assert ei_region_none.value.failed_fields == frozenset({"locality_scope"})
    ff_region = {
        str(f["field"]): f for f in ei_region_none.value.field_failures
    }
    assert ff_region["locality_scope"]["current"] == "none"
    assert ff_region["locality_scope"]["expected"] == ["single"]

    # 合法组合：issue+none / region+single 原样通过
    qa_shape = map_rescript_option_or_choice({
        "action_type": "authorization",
        "label": "赈抚",
        "target_kind": "issue",
        "target_id": "relief",
        "locality_scope": "none",
        "holder_id": "毕自严",
        "privilege": "便宜行事",
    })
    assert qa_shape["locality_scope"] == "none"
    assert resolve_dossier_region_ids(
        None,
        payload=qa_shape,
    ) == [""]

    region_shape = map_rescript_option_or_choice({
        "action_type": "authorization",
        "label": "陕赈",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "holder_id": "毕自严",
        "privilege": "便宜行事",
    })
    assert region_shape["locality_scope"] == "single"
    assert region_shape["region_id"] == "shaanxi"


# ── locality oracle 组合矩阵 ───────────────────────────────────────


def test_national_policy_is_one_dossier_not_per_province(env):
    """#1778 决定 4：全国政令也是一份案卷，region_id 空——不按省拆。"""
    db, _, content = env
    regions = resolve_dossier_region_ids(
        db.conn,
        payload={
            "target_kind": "policy",
            "target_id": "清丈田亩",
            "locality_scope": "national",
        },
        regions_content=content.regions,
    )
    assert regions == [""]


def test_special_decree_without_national_is_single_empty(env):
    db, _, content = env
    regions = resolve_dossier_region_ids(
        db.conn,
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
        payload={
            "target_kind": "region",
            "target_id": "liaodong",
            "locality_scope": "single",
        },
        regions_content=content.regions,
    ) == [""]


@pytest.mark.parametrize("payload", [
    {"target_kind": "region", "target_id": "shaanxi", "locality_scope": "national"},
    {"target_kind": "region", "target_id": "shaanxi", "locality_scope": "none"},
    {"target_kind": "policy", "target_id": "x", "locality_scope": "single"},
    {"target_kind": "character", "target_id": "袁崇焕", "locality_scope": "national"},
    {"target_kind": "unknown", "target_id": "x", "locality_scope": "none"},
])
def test_oracle_contradictions_fail_loud(env, payload):
    db, _, content = env
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, payload=payload, regions_content=content.regions,
        )


def test_region_zero_hit_fail_loud(env):
    db, _, content = env
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
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
    # 复合唯一：directive 含 region_id；pending 含 region_id + action_type（#1837 组合载荷）
    assert "region_id" in (idx["idx_decree_dossiers_directive"] or "")
    pending_sql = idx["idx_decree_dossiers_pending_action"] or ""
    assert "region_id" in pending_sql
    assert "action_type" in pending_sql
    # secret_order 单列索引保留
    assert "idx_decree_dossiers_secret_order" in idx


def test_national_creates_one_row_idempotent(env):
    """#1778 决定 4：全国政令成一份案卷（region_id 空），重交不增行。"""
    db, state, content = env
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
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
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
    assert len(ids) == 1
    rows = db.list_dossiers_for_directive(directive_id)
    assert len(rows) == 1
    assert [r["region_id"] for r in rows] == [""]
    # 点将：主办与 executor_* 同步（#654 named-lead 断根）
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
    assert len(db.list_dossiers_for_directive(directive_id)) == 1


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
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
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
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
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
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
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
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
            text, "test", status, "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def test_validate_all_unknown_roster_name_zero_rows_before_insert(env):
    """Validate-all：名单上的人不在名册 → 首个 INSERT 前整旨零行（#1778 决定 3）。"""
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
    }
    did = _insert_directive(db, state, text="清丈天下田亩", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    with pytest.raises(ValueError, match="查无此人"):
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="清丈天下田亩",
            target_kind="policy",
            target_id="清丈天下田亩",
            directive_id=did,
            payload=payload,
            commit=True,
        )
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before
    assert db.list_dossiers_for_directive(did) == []


def test_path2_pending_bad_roster_stays_draft_on_ensure_batch(env):
    """路 2（#1769）：pending→confirm 只翻 draft；ensure 批缝产物错 → 零行 + 保持 draft。

    旧合同 confirm 内 ensure 并标 rejected 已废；产物错不踢出批缝。
    """
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
        "mode": "ordinary",
    }
    did = _insert_directive(
        db, state, text="清丈天下田亩", payload=payload, status="pending",
    )
    db.confirm_directive(did, state)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert db.list_dossiers_for_directive(did) == []

    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert any(int(r["directive_id"]) == did for r in rejections)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
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


def test_path1_conversational_draft_bad_roster_marks_failed(env):
    """路 1 _commit_conversational_draft：成案零行 → pending failed、无案卷。"""
    db, state, _ = env
    payload = {
        "text": "清丈天下田亩",
        "actor": "毕自严",
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
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


# ── 8×3 locality 矩阵（参数化）──────────────────────────────────


@pytest.mark.parametrize(
    "target_kind,scope,expect",
    [
        # policy/issue/account × national → 单行 ''（#1778：不按省拆，无动作白名单）
        ("policy", "national", "empty"),
        ("issue", "national", "empty"),
        ("account", "national", "empty"),
        # policy/issue/account × single → fail
        ("policy", "single", "fail"),
        ("issue", "single", "fail"),
        # policy/issue/account × none → ''
        ("policy", "none", "empty"),
        ("issue", "none", "empty"),
        ("account", "none", "empty"),
        # character/office/army × national → fail
        ("character", "national", "fail"),
        ("office", "national", "fail"),
        ("army", "national", "fail"),
        # character/office/army × single → fail
        ("character", "single", "fail"),
        ("office", "single", "fail"),
        ("army", "single", "fail"),
        # character/office/army × none → ''
        ("character", "none", "empty"),
        ("office", "none", "empty"),
        ("army", "none", "empty"),
        # region × national/none → fail；single → R1
        ("region", "national", "fail"),
        ("region", "none", "fail"),
        ("region", "single", "R1"),
        # dossier 三格：仅 none → 单行 ''；single/national fail-loud
        ("dossier", "none", "empty"),
        ("dossier", "single", "fail"),
        ("dossier", "national", "fail"),
        ("dossier", None, "empty"),
        # 缺省 scope（normalize → none）
        ("policy", None, "empty"),
        ("region", None, "fail"),
        # unknown
        ("unknown", "none", "fail"),
        ("policy", "全省", "fail"),
    ],
)
def test_locality_matrix_8x3_and_unknown(env, target_kind, scope, expect):
    db, _, content = env
    payload = {"target_kind": target_kind, "target_id": "shaanxi" if target_kind == "region" else "x"}
    if scope is not None:
        payload["locality_scope"] = scope
    if expect == "fail":
        with pytest.raises(ValueError):
            resolve_dossier_region_ids(
                db.conn, payload=payload, regions_content=content.regions,
            )
        return
    regions = resolve_dossier_region_ids(
        db.conn, payload=payload, regions_content=content.regions,
    )
    if expect == "empty":
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


def test_cli_target_kinds_accepts_canonical_eight():
    """producer 与 durable 共八值（含 dossier）：合法通过、法外 fail-loud。"""
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


