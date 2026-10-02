"""#654 差务属地 oracle：组合矩阵及案卷归属。"""

from __future__ import annotations

import json

import pytest

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    resolve_dossier_region_ids,
)


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


# ── 词表 / scope 归一 ──────────────────────────────────────────────








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


@pytest.mark.parametrize("target_kind, scope, accepted", [
    ("region", "单省", True),
    ("region", "无", False),
    ("not_a_real_kind", "单省", False),
])
def test_cli_capture_rejects_bad_target_or_scope(env, monkeypatch, target_kind, scope, accepted):
    from ming_sim import cli_backend as cb
    db, state, content = env
    data = {
        "拟旨意图": "拟旨", "动作类型": "assignment", "目标类型": target_kind,
        "目标ID": "shaanxi", "地区ID": "shaanxi", "施行范围": scope,
        "事务类别": "督赈", "承办人": "", "颁布方式": "普通",
        "参与人": [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}],
    }
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (json.dumps(data), None))
    if accepted:
        captured = cb.capture_manual_directive_payload("陕西赈务", db=db, content=content)
        assert captured["target_kind"] == "region"
        assert captured["locality_scope"] == "single"
    else:
        with pytest.raises(ValueError):
            cb.capture_manual_directive_payload("陕西赈务", db=db, content=content)


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
    with pytest.raises(ValueError):
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


@pytest.mark.parametrize("scope, accepted", [(None, False), ("全省", False), ("single", True)])
def test_locality_fail_create_decree_dossiers_zero_rows(env, scope, accepted):
    """fail 格走真实 bulk 入口：异常 + 零行。"""
    db, state, _ = env
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": scope,
        "dossier_action_type": "policy",
    }
    did = _insert_directive(db, state, text="陕", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    if accepted:
        created = db.create_decree_dossiers(
            state, action_type="policy", decree_text="陕",
            target_kind="region", target_id="shaanxi",
            directive_id=did, payload=payload, commit=True,
        )
        assert len(created) == 1
    else:
        with pytest.raises(ValueError):
            db.create_decree_dossiers(
                state, action_type="policy", decree_text="陕",
                target_kind="region", target_id="shaanxi",
                directive_id=did, payload=payload, commit=True,
            )
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before + int(accepted)




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
        payload={"target_kind": "dossier", "target_id": str(target_id),
                 "locality_scope": "none"},
    ) == [""]
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "single"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "national"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
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
    with pytest.raises(ValueError):
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
    with pytest.raises(ValueError):
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
