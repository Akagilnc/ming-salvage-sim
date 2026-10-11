from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
import json
import pytest
from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    normalize_locality_scope,
    resolve_dossier_region_ids,
)
"""#654 差务属地 oracle：组合矩阵及案卷归属。"""




@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content

# ── 词表 / scope 归一 ──────────────────────────────────────────────


def test_mapper_rejects_contradictory_locality_scope_without_overwrite():
    """#1624：禁止按 target_kind 覆盖 locality 掩盖错误目标；显式矛盾 fail-loud。

    契约落在 StructuredDecreeCombinationError.field_failures/failed_fields
    （权威结构化失败事实）；不得盯异常措辞。
    """
    from ming_sim.structured_decree import assemble_structured_decree as map_rescript_option_or_choice
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


# ── schema + create_decree_dossiers fan-out ────────────────────────


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
    row = db.dossiers.get(did)
    assert row["region_id"] == ""


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
            "directive", "拟旨", None,
            json.dumps(payload, ensure_ascii=False), "pending",
        ),
    )
    pa_id = int(cur.lastrowid)
    db.conn.commit()
    db.commit_pending_actions(state, content=db.content, action_ids=[pa_id])
    st = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pa_id,),
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
    ("target_kind", "scope"),
    [
        ("region", "national"),
        ("region", "none"),
        ("dossier", "single"),
        ("dossier", "national"),
        ("region", None),
        ("unknown", "none"),
        ("policy", "全省"),
        # 下列五组负向无其它等价拒收案覆盖，须保留（policy/character+national 等同文件已有）
        ("office", "national"),
        ("army", "national"),
        ("character", "single"),
        ("office", "single"),
        ("army", "single"),
    ],
)
def test_locality_matrix_8x3_and_unknown(env, target_kind, scope):
    """矛盾 locality 组合 fail-loud（正向列表返回由真实 bulk 成案覆盖）。"""
    db, _, content = env
    payload = {"target_kind": target_kind, "target_id": "shaanxi" if target_kind == "region" else "x"}
    if scope is not None:
        payload["locality_scope"] = scope
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, payload=payload, regions_content=content.regions,
        )


@pytest.mark.parametrize("target_kind", [
    "policy", "character", "office", "army", "region", "issue", "account", "dossier", "not_a_real_kind",
])
def test_resubmit_target_kinds_accepts_canonical_eight(env, monkeypatch, target_kind):
    """闭集由真实拟旨捕获入口验证，不直接调用 coercion helper。"""
    from ming_sim import cli_backend as cb
    from ming_sim.draft_intent import resubmit_draft_admission_payload
    db, state, content = env
    response = {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": target_kind,
        "目标ID": "shaanxi" if target_kind == "region" else "x",
        "施行范围": "single" if target_kind == "region" else "无",
        "颁布方式": "普通", "entries": [],
        "参与人": [{"character_id": "毕自严", "tier": "主办"}]}
    monkeypatch.setattr(cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps(response, ensure_ascii=False), {}))
    if target_kind == "not_a_real_kind":
        with pytest.raises(ValueError):
            resubmit_draft_admission_payload("核办", bad_payload={}, failure_reason="injected retry", db=db, content=content)
        assert db.issues.list_directives(state.turn) == []
        assert db.dossiers.list_dossiers() == []
    else:
        payload = resubmit_draft_admission_payload("核办", bad_payload={}, failure_reason="injected retry", db=db, content=content)
        assert payload["target_kind"] == target_kind

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
    apply_dossier_promulgation(db, state, target_id, "promulgated")

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
        d for d in db.dossiers.list_dossiers()
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

def test_location_canonical_seed_and_write_seam(env):
    """G/#1889：fresh seed location；写缝别名归一；未知 fail-loud。

    旧档开档 migrate 别名梯已退役（#1812 无历史包袱）；不测 ALTER/开档清洗。
    """
    db, state, content = env
    for name in ("乔允升", "许誉卿", "韩一良"):
        loc = db.conn.execute(
            "SELECT location FROM characters WHERE name=?", (name,),
        ).fetchone()["location"]
        assert loc == "beizhili", name
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
    # 写缝已钉未知非空 fail-loud。开档别名 migrate / 开档扫 location 已随
    # _migrate_character_location_aliases 退役，不再造旧档副本期待写回。


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
    db.issues.confirm_directive(did)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers WHERE directive_id=?", (did,)).fetchone()["n"] == 0

    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert any(int(r["directive_id"]) == did for r in rejections)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers WHERE directive_id=?", (did,)).fetchone()["n"] == 0


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
    assert db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers WHERE directive_id=?", (did,)).fetchone()["n"] == 0
    # 并列第二旨不受影响
    assert good["status"] == "draft"
    assert db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers WHERE directive_id=?", (other_id,)).fetchone()["n"] == 1

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
