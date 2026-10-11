"""#654 差务属地 oracle：组合矩阵及案卷归属。"""

from __future__ import annotations

import json

import pytest

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import (
    resolve_dossier_region_ids,
)


def _dossiers_for_directive(db, directive_id):
    """存储读面：已删 list_dossiers_for_directive → 同表 ORDER BY region_id, id。"""
    rows = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE directive_id=? "
        "ORDER BY region_id, id",
        (int(directive_id),),
    ).fetchall()
    return [int(r["id"]) for r in rows]


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


def test_mapper_rejects_contradictory_locality_scope_without_overwrite():
    """#1624：禁止按 target_kind 覆盖 locality 掩盖错误目标；显式矛盾 fail-loud。

    契约落在 StructuredDecreeCombinationError.field_failures/failed_fields
    （权威结构化失败事实）；不得盯异常措辞。
    """
    from ming_sim.structured_decree import validate_structured_decree_combination
    from ming_sim.structured_decree import StructuredDecreeCombinationError

    with pytest.raises(StructuredDecreeCombinationError) as ei_issue_single:
        validate_structured_decree_combination({
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
        validate_structured_decree_combination({
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

# ── locality oracle 组合矩阵 ───────────────────────────────────────


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
    row_ids = _dossiers_for_directive(db, directive_id)
    assert len(row_ids) == 1
    rows = [db.get_decree_dossier(i) for i in row_ids]
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
    assert len(_dossiers_for_directive(db, directive_id)) == 1

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
    row = db.get_decree_dossier(_dossiers_for_directive(db, directive_id)[0])
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
    listed_ids = _dossiers_for_directive(db, directive_id)
    assert len(listed_ids) == 1
    assert db.get_decree_dossier(listed_ids[0])["region_id"] == "shaanxi"

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
    assert _dossiers_for_directive(db, did) == []

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
    assert _dossiers_for_directive(db, did) == []

    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert any(int(r["directive_id"]) == did for r in rejections)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert _dossiers_for_directive(db, did) == []

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
    assert _dossiers_for_directive(db, did) == []
    # 并列第二旨不受影响
    assert good["status"] == "draft"
    assert len(_dossiers_for_directive(db, other_id)) == 1

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

# ── locality 矛盾与未知值负向矩阵 ──────────────────────────────

@pytest.mark.parametrize(
    "target_kind,scope",
    [
        # policy/issue/account × single → fail
        ("policy", "single"),
        ("issue", "single"),
        # character/office/army × national → fail
        ("character", "national"),
        ("office", "national"),
        ("army", "national"),
        # character/office/army × single → fail
        ("character", "single"),
        ("office", "single"),
        ("army", "single"),
        # region × national/none → fail
        ("region", "national"),
        ("region", "none"),
        # dossier × single/national → fail
        ("dossier", "single"),
        ("dossier", "national"),
        ("region", None),
        # unknown
        ("unknown", "none"),
        ("policy", "全省"),
    ],
)
def test_locality_matrix_rejects_contradictions_and_unknown(env, target_kind, scope):
    db, _, content = env
    payload = {"target_kind": target_kind, "target_id": "shaanxi" if target_kind == "region" else "x"}
    if scope is not None:
        payload["locality_scope"] = scope
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, payload=payload, regions_content=content.regions,
        )

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

    # 2) 真实收夜成案入口（commit_pending_actions → normalize → create_decree_dossiers）
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

# ── #654 A–H 断根补测 ─────────────────────────────────────────────

def test_location_canonical_seed_and_write_seam(env):
    """G：fresh seed 三人 beizhili；写缝别名归一；未知 fail-loud。"""

    db, state, content = env
    for name in ("乔允升", "许誉卿", "韩一良"):
        loc = db.conn.execute(
            "SELECT location FROM characters WHERE name=?", (name,),
        ).fetchone()["location"]
        assert loc == "beizhili", name
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
    # 写缝已钉未知非空 fail-loud。开档别名 migrate / 开档扫 location 已随
    # _migrate_character_location_aliases 退役，不再造旧档副本期待写回。
