"""#654 差务属地 oracle：组合矩阵及案卷归属。"""

from __future__ import annotations

import json

import pytest

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

@pytest.mark.parametrize("target_kind,scope,expect", [
    ("policy", "national", ""), ("policy", "全国", ""),
    ("issue", "national", ""), ("account", "national", ""),
    ("policy", "single", None), ("issue", "single", None),
    ("policy", "none", ""), ("issue", "none", ""), ("account", "none", ""),
    ("character", "national", None), ("office", "national", None), ("army", "national", None),
    ("character", "single", None), ("office", "single", None), ("army", "single", None),
    ("character", "none", ""), ("office", "none", ""), ("army", "none", ""),
    ("region", "national", None), ("region", "none", None), ("region", "single", "shaanxi"),
    ("dossier", "none", ""), ("dossier", "无", ""),
    ("dossier", "single", None), ("dossier", "national", None), ("dossier", None, ""),
    ("policy", None, ""), ("region", None, None),
    ("unknown", "none", None), ("policy", "全省", None),
    ("region", "single", ""), ("region", "single", None),
])
def test_locality_matrix_8x3_and_unknown(env, target_kind, scope, expect):
    """属地组合仅经批量成案入口验证：合法持久属地；非法零案卷。"""
    db, state, _ = env
    target_id = {
        "character": "毕自严", "office": "户部", "army": "guanning",
        "region": "shaanxi", "account": "国库",
    }.get(target_kind, "x")
    if target_kind == "region" and scope == "single" and expect != "shaanxi":
        target_id = "liaodong" if expect == "" else "不存在的行省xyz"
    payload = {"target_kind": target_kind, "target_id": target_id,
        "assignee_id": "毕自严", "participant_roster": [
            {"character_id": "毕自严", "tier": "主办"}], "mode": "ordinary"}
    if scope is not None:
        payload["locality_scope"] = scope
    directive_id = _insert_directive(db, state, text="核办", payload=payload)
    if expect is None:
        with pytest.raises(ValueError):
            db.create_decree_dossiers(state, action_type="policy", decree_text="核办",
                target_kind=target_kind, target_id=target_id,
                directive_id=directive_id, payload=payload)
        assert db.dossiers.list_dossiers() == []
    else:
        ids = db.create_decree_dossiers(state, action_type="policy", decree_text="核办",
            target_kind=target_kind, target_id=target_id,
            directive_id=directive_id, payload=payload)
        assert [db.dossiers.get(did)["region_id"] for did in ids] == [expect]


@pytest.mark.parametrize("target_kind", [
    "policy", "character", "office", "army", "region", "issue", "account", "dossier", "not_a_real_kind",
])
def test_cli_target_kinds_accepts_canonical_eight(env, monkeypatch, target_kind):
    """闭集由真实拟旨捕获入口验证，不直接调用 coercion helper。"""
    from ming_sim import cli_backend as cb
    db, state, content = env
    response = {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": target_kind,
        "目标ID": "shaanxi" if target_kind == "region" else "x",
        "属地范围": "single" if target_kind == "region" else "none",
        "参与人": [{"character_id": "毕自严", "tier": "主办"}]}
    monkeypatch.setattr(cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps(response, ensure_ascii=False), 1))
    if target_kind == "not_a_real_kind":
        with pytest.raises(ValueError):
            cb.capture_manual_directive_payload("核办", db=db, content=content)
        assert db.issues.list_directives(state.turn) == []
        assert db.dossiers.list_dossiers() == []
    else:
        payload = cb.capture_manual_directive_payload("核办", db=db, content=content)
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
    db, state, _ = env
    payload = {'target_kind': 'policy', 'target_id': '清丈天下田亩', 'locality_scope': 'national', 'dossier_action_type': 'assignment', 'participant_roster': [{'character_id': '查无此人', 'tier': '主办'}], 'mode': 'ordinary'}
    did = _insert_directive(db, state, text='清丈天下田亩', payload=payload, status='pending')
    db.confirm_directive(did, state)
    row = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (did,)).fetchone()
    assert row['status'] == 'draft'
    assert [r for r in db.dossiers.list_dossiers() if r["directive_id"] == did] == []
    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert any((int(r['directive_id']) == did for r in rejections))
    row = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (did,)).fetchone()
    assert row['status'] == 'draft'
    assert [r for r in db.dossiers.list_dossiers() if r["directive_id"] == did] == []


def test_path3_locality_fail_keeps_draft_no_text_in_rejection(env):
    db, state, _ = env
    long_text = '敕令陕西清丈田亩' + '甲' * 120
    payload = {'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'none', 'dossier_action_type': 'policy', 'mode': 'ordinary'}
    did = _insert_directive(db, state, text=long_text, payload=payload, status='draft')
    other_payload = {'target_kind': 'region', 'target_id': 'henan', 'locality_scope': 'single', 'dossier_action_type': 'policy', 'assignee_id': '毕自严', 'mode': 'ordinary'}
    other_id = _insert_directive(db, state, text='河南清丈', payload=other_payload, status='draft')
    db.ensure_dossiers_for_draft_directives(state)
    bad = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (did,)).fetchone()
    good = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (other_id,)).fetchone()
    assert bad['status'] == 'draft'
    assert [r for r in db.dossiers.list_dossiers() if r["directive_id"] == did] == []
    assert good['status'] == 'draft'
    assert len([r for r in db.dossiers.list_dossiers() if r["directive_id"] == other_id]) == 1
    rej = db.conn.execute("SELECT item_json, reason, category FROM rejection_reports WHERE section='directive_locality' ORDER BY id DESC LIMIT 5").fetchall()
    assert rej, '应记 locality rejection'
    matched = [json.loads(r['item_json']) for r in rej]
    hit = next((item for item in matched if item.get('directive_id') == did))
    assert 'text' not in hit


def test_national_creates_one_row_idempotent(env):
    db, state, _ = env
    payload = {"locality_scope": "national", "assignee_id": "毕自严",
        "transaction_category": "清丈", "participant_roster": [
            {"character_id": "毕自严", "tier": "主办", "role": "清丈"}]}
    directive_id = db.issues.add_directive(state.turn, state.year, state.period, None, "清丈天下", "test")
    ids = db.create_decree_dossiers(state, action_type="policy", decree_text="清丈天下",
        target_kind="policy", target_id="land", directive_id=directive_id, payload=payload, commit=True)
    replay = db.create_decree_dossiers(state, action_type="policy", decree_text="清丈天下",
        target_kind="policy", target_id="land", directive_id=directive_id, payload=payload, commit=True)
    assert replay == ids
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (directive_id,)).fetchone()[0] == 1
