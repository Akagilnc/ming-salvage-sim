"""#628 / ADR 0079 信用事件写端。

测试预算 ≤4：
① AC1：#623 既有辜负写口行为覆盖，本片不重写该 origin
② 兑付/撑完 + 谏处置三型（正）；校验拒收（fulfilled/任命）不落伪信用（负）
③ 处置映射：丢卒两笔 / 包庇撑腰 / 查办不记（负）；真变形案卷 + #565 连坐面
④ 幂等（origin 写前判重）+ 叙事语境 + restore + 只写不读 + banned 单源
"""

from __future__ import annotations

from ming_sim.breach_plea import (
    BREACH_KIND_REMOVE_SPONSOR,
    finalize_persist,
    write_breach_plea_todo,
)
from ming_sim.credit_events import (
    CREDIT_BANNED_PLAYER_TOKENS,
    CREDIT_BANNED_SCAN_SURFACES,
    KIND_BACK,
    KIND_BETRAY,
    KIND_FULFILL,
    KIND_SCAPEGOAT,
    resolve_credit_events_from_extraction,
    scapegoat_actor_kind_from_origin,
    write_credit_event,
)
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
)
from ming_sim.urge_lever import (
    _record_commitment_urge,
)


# ── helpers ───────────────────────────────────────────────────────────


def _executing_dossier(db, state, *, token: str, roster=None):
    if roster is None:
        roster = [
            {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
        ]
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"信用写端·{token}",
        target_kind="issue",
        target_id=token,
        participants=roster,
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    assert db.get_decree_dossier(did)["status"] == "executing"
    return did


def _transformed_dossier(db, state, *, token: str, roster=None):
    """真实暴露的变形案卷（非空 fixture）——先落执行格 transformed。"""
    did = _executing_dossier(db, state, token=token, roster=roster)
    db.record_dossier_execution(
        did, "transformed", f"名实已乖·{token}", int(state.turn),
        close=True, commit=True,
    )
    d = db.get_decree_dossier(did)
    assert d["execution_outcome"] == "transformed"
    return did


def _insert_commitment(db, state, *, title: str, origin_ref: str, host: str = "倪元璐"):
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin_ref,
        cancellable="decree",
        commitment_kind="until_stop",
        bar_value=12,
        stage_text="在办",
        end_turn=int(state.turn) + 12,
        participants=[host],
        stages_json=[{
            "stage_idx": 0,
            "due_turn": int(state.turn) + 6,
            "criterion_text": "见成数",
            "origin_context": title,
        }],
        commit=True,
    )
    db.conn.execute(
        "UPDATE issues SET participant_roster=? WHERE id=?",
        (
            '[{"character_id":"%s","tier":"主办","role":"承办"}]' % host,
            int(issue_id),
        ),
    )
    db.conn.commit()
    return int(issue_id)


def _credit_edges(db, *, event_kind=None, target=None, source=None):
    sql = "SELECT * FROM relation_edge_events WHERE 1=1"
    params = []
    if event_kind is not None:
        sql += " AND event_kind=?"
        params.append(event_kind)
    if target is not None:
        sql += " AND target=?"
        params.append(target)
    if source is not None:
        sql += " AND source=?"
        params.append(source)
    sql += " ORDER BY id"
    return [dict(r) for r in db.conn.execute(sql, params).fetchall()]


def _SCAPEGOAT_ROSTER():
    # #565 同构：主办倪元璐←委派徐光启；卒=倪，车=徐
    return [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
    ]


# ── ① AC1：#623 既有，不重复 ─────────────────────────────────────────


def test_ac1_breach_plea_guofu_not_reimplemented(game):
    """挽留回绝→辜负仍由 #623 finalize_persist 写出；本片 resolve 不重写该 origin。"""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did = _executing_dossier(db, state, token="ac1-623")
    holder = "倪元璐"
    cid = _insert_commitment(
        db, state, title="撤人信用既有", origin_ref=f"dossier:{did}", host=holder,
    )
    # 同步案卷主办
    db.conn.execute(
        "UPDATE decree_dossiers SET participant_roster=? WHERE id=?",
        (
            '[{"character_id":"倪元璐","tier":"主办","role":"承办"}]',
            did,
        ),
    )
    db.conn.commit()
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢主办试既有", target_dossier_id=did, commit=True,
    )
    todo = next(
        t for t in db.list_next_audience_todos(status="pending")
        if int(t["id"]) == todo_id
    )
    before = len(_credit_edges(db, event_kind="辜负", target=holder))
    result = finalize_persist(db, state, todo, commit=True)
    assert result["decision"] == "persist"
    edges = _credit_edges(db, event_kind="辜负", target=holder)
    assert len(edges) == before + 1
    assert any("breach_plea" in str(e["origin"]) for e in edges)
    # 本片 resolve 不吞、不重写该 origin
    resolve_credit_events_from_extraction(db, state, {}, commit=True)
    edges2 = _credit_edges(db, event_kind="辜负", target=holder)
    assert len(edges2) == len(edges)


# ── ② 兑付/撑完 + 谏三型 + 校验拒收不落伪信用 ───────────────────────


def test_fulfill_back_and_urge_three_decisions(game):
    """兑付→兑现所托；撑完→撑腰；准宽限撑腰 / 拒宽限·斥退辜负；被拒 fulfilled/任命不落。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    # ── 兑付 ──
    did_f = _executing_dossier(
        db, state, token="fulfill-628",
        roster=[{"character_id": "倪元璐", "tier": "主办", "role": "承办"}],
    )
    note_f = "依限办结"
    out_f = apply_score_extraction(
        db, state,
        {"dossier_executions": [{
            "dossier_id": did_f, "outcome": "fulfilled",
            "note": note_f,
        }]},
        content=content,
    )
    assert out_f.get("credit_event_resolutions", {}).get("fulfillment")
    fulfill_edges = _credit_edges(db, event_kind=KIND_FULFILL, source="倪元璐")
    assert fulfill_edges, "兑付须写兑现所托"
    fe = fulfill_edges[-1]
    assert fe["target"] == "皇帝"
    assert fe["context"] == note_f  # 承接 extraction 真叙事
    assert f"dossier:{did_f}:credit:fulfill" in str(fe["origin"])
    assert fe["context"].strip()

    # ── 撑完承诺（承催压后兑付）──
    did_b = _executing_dossier(
        db, state, token="back-628",
        roster=[{"character_id": "毕自严", "tier": "主办", "role": "承办"}],
    )
    cid_b = _insert_commitment(
        db, state, title="撑完之诺", origin_ref=f"dossier:{did_b}", host="毕自严",
    )
    _record_commitment_urge(
        db, state,
        commitment_ref=cid_b, stage_idx=0,
        old_due=state.turn + 12, new_due=state.turn + 2,
        deadline_months=2, reason="着速办",
    )
    db.conn.commit()
    note_b = "顶住办结"
    apply_score_extraction(
        db, state,
        {"dossier_executions": [{
            "dossier_id": did_b, "outcome": "fulfilled", "note": note_b,
        }]},
        content=content,
    )
    back_edges = [
        e for e in _credit_edges(db, event_kind=KIND_BACK, target="毕自严")
        if f"dossier:{did_b}:credit:back" in str(e["origin"])
    ]
    assert back_edges, "撑完承诺须写撑腰"
    assert back_edges[-1]["context"] == note_b
    assert any(
        f"dossier:{did_b}:credit:fulfill" in str(e["origin"])
        for e in _credit_edges(db, event_kind=KIND_FULFILL, source="毕自严")
    )

    # ── C1 负向：缺 note 的 fulfilled 被 applier 拒 → 不得落兑现所托 ──
    # 夹具=真 executing 案卷 + outcome=fulfilled + 缺 note（issues.py:7103 必拒，
    # 拒项带 item=源对象）。DB 预置 execution_outcome=fulfilled（close=False 保持
    # executing）：漏 minus-rejections 闸时 resolve 见 DB 终值必落兑现边——反空壳
    # （旧夹具幽灵 dossier_id=10**9 且自带 note，双闸全拆仍绿）。
    did_rej_f = _executing_dossier(
        db, state, token="rej-ful-628",
        roster=[{"character_id": "刘鸿训", "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_execution(
        did_rej_f, "fulfilled", "预置终值语境", int(state.turn),
        close=False, commit=True,
    )
    before_fake = len(_credit_edges(db, event_kind=KIND_FULFILL))
    out_rej_f = apply_score_extraction(
        db, state,
        {"dossier_executions": [{
            "dossier_id": did_rej_f, "outcome": "fulfilled",
        }]},
        content=content,
    )
    assert any(
        isinstance(r, dict) and r.get("rejected")
        for r in (out_rej_f.get("dossier_executions") or [])
    )
    assert len(_credit_edges(db, event_kind=KIND_FULFILL)) == before_fake

    # ── C1 负向：人物变更被拒 → 不得落信用边（包庇/弃卒等）──
    # 夹具=任命+缺 office（必拒 missing_field）；_is_cover_change 对任命无条件命中，
    # 漏 rejected 闸即落包庇撑腰边——反空壳（旧夹具处置+非法 status 不可归类，拆闸仍绿）。
    did_rd = _transformed_dossier(
        db, state, token="rej-appt-628",
        roster=[{"character_id": "孙承宗", "tier": "主办", "role": "承办"}],
    )
    before_rd = len(_credit_edges(db))
    out_rd = apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "孙承宗", "动作": "任命",
            "reason": "包庇伪装应拒", "origin_ref": f"dossier:{did_rd}",
        }]},
        content=content,
    )
    pcs_rd = out_rd.get("applied_person_changes") or []
    assert any(isinstance(r, dict) and r.get("rejected") for r in pcs_rd)
    assert not any(
        f"dossier:{did_rd}:credit:" in str(e["origin"])
        for e in _credit_edges(db)
    )
    assert len(_credit_edges(db)) == before_rd

    # ── 谏处置三型（案卷主办=谏者，resolve_host 读案卷面）──
    def _host_roster(name: str):
        return [{"character_id": name, "tier": "主办", "role": "承办"}]

    # 准宽限
    did_g = _executing_dossier(
        db, state, token="grace-628", roster=_host_roster("倪元璐"),
    )
    cid_g = _insert_commitment(
        db, state, title="乞宽限案", origin_ref=f"dossier:{did_g}", host="倪元璐",
    )
    db.insert_next_audience_todo(
        commitment_ref=cid_g, stage_idx=0, due_turn=state.turn + 2,
        criterion_text="乞恩宽限", origin_context="催紧",
        entry_kind=ENTRY_KIND_GRACE_PLEA, created_turn=state.turn - 1,
        payload_json={"kind": "grace_plea"}, commit=True,
    )
    # 拒宽限
    did_rg = _executing_dossier(
        db, state, token="rej-grace-628", roster=_host_roster("徐光启"),
    )
    cid_rg = _insert_commitment(
        db, state, title="拒宽限案", origin_ref=f"dossier:{did_rg}", host="徐光启",
    )
    db.insert_next_audience_todo(
        commitment_ref=cid_rg, stage_idx=0, due_turn=state.turn + 2,
        criterion_text="乞恩宽限", origin_context="再催",
        entry_kind=ENTRY_KIND_GRACE_PLEA, created_turn=state.turn - 1,
        payload_json={"kind": "grace_plea"}, commit=True,
    )
    # 斥退顶谏
    did_rr = _executing_dossier(
        db, state, token="rej-rem-628", roster=_host_roster("黄道周"),
    )
    cid_rr = _insert_commitment(
        db, state, title="斥退谏案", origin_ref=f"dossier:{did_rr}", host="黄道周",
    )
    db.insert_next_audience_todo(
        commitment_ref=cid_rr, stage_idx=0, due_turn=state.turn + 1,
        criterion_text="期限过急，恐难如期", origin_context="急催",
        entry_kind=ENTRY_KIND_RUSH_REMONSTRANCE, created_turn=state.turn - 1,
        payload_json={"kind": "rush_remonstrance"}, commit=True,
    )

    grace_purpose = "准宽限加拨"
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                # 非负 delta + 显式宽限叙事；合法 origin 须落格（C1/C2）
                "account": "国库", "delta": 5, "category": "军费",
                "purpose": grace_purpose, "reason": "准宽限",
                "origin_ref": "盘面自发",
                "issue_id": cid_g,
            }],
            "cancels": [
                {"issue_id": cid_rg},
                {"issue_id": cid_rr},
            ],
        },
        content=content,
    )
    g_edges = [
        e for e in _credit_edges(db, event_kind=KIND_BACK, target="倪元璐")
        if f"issue:{cid_g}:credit:grant_grace" in str(e["origin"])
    ]
    assert g_edges, "准宽限须写撑腰"
    assert g_edges[-1]["context"] in {grace_purpose, "准宽限", "乞恩宽限"}

    rg_edges = [
        e for e in _credit_edges(db, event_kind=KIND_BETRAY, target="徐光启")
        if f"issue:{cid_rg}:credit:reject_grace" in str(e["origin"])
    ]
    assert rg_edges and rg_edges[-1]["context"] == "乞恩宽限"

    rr_edges = [
        e for e in _credit_edges(db, event_kind=KIND_BETRAY, target="黄道周")
        if f"issue:{cid_rr}:credit:reject_remonstrance" in str(e["origin"])
    ]
    assert rr_edges and rr_edges[-1]["context"] == "期限过急，恐难如期"


# ── ③ 处置映射正负 ───────────────────────────────────────────────────


def test_disposition_scapegoat_cover_prosecute_on_transformed(game):
    """丢卒保车两笔；包庇→撑腰；查办→不记。对象=真变形案卷，复用 #565 连坐面。"""
    db, state, content = game

    roster = _SCAPEGOAT_ROSTER()

    # ── 丢卒保车：惩卒倪元璐、保车徐光启 ──
    did_sg = _transformed_dossier(db, state, token="sg-628", roster=roster)
    # 方案 b：origin 可派生施弃方=皇帝
    assert scapegoat_actor_kind_from_origin(
        f"dossier:{did_sg}:credit:scapegoat:pawn:倪元璐"
    ) == "皇帝"
    assert scapegoat_actor_kind_from_origin("random:foo") is None

    before_sg = len(_credit_edges(db, event_kind=KIND_SCAPEGOAT))
    reason_sg = "顶罪下狱"
    apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "倪元璐", "动作": "处置", "status": "imprisoned",
            "reason": reason_sg, "origin_ref": f"dossier:{did_sg}",
        }]},
        content=content,
    )
    sg_edges = _credit_edges(db, event_kind=KIND_SCAPEGOAT)
    assert len(sg_edges) == before_sg + 2
    by_target = {e["target"]: e for e in sg_edges if f"dossier:{did_sg}" in str(e["origin"])}
    assert set(by_target) == {"倪元璐", "徐光启"}
    assert by_target["倪元璐"]["context"] == reason_sg
    assert by_target["徐光启"]["context"] == reason_sg
    assert by_target["倪元璐"]["source"] == "皇帝"
    for e in by_target.values():
        assert scapegoat_actor_kind_from_origin(e["origin"]) == "皇帝"

    # ── 包庇：庇护主办 → 撑腰（另人，避免与上文弃卒入狱撞状态）──
    did_cv = _transformed_dossier(
        db, state, token="cover-628",
        roster=[{"character_id": "孙承宗", "tier": "主办", "role": "承办"}],
    )
    reason_cv = "着仍供职，勿深究"
    apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "孙承宗", "动作": "调任",
            "office": "兵部尚书", "office_type": "文官",
            "reason": reason_cv,
            "origin_ref": f"dossier:{did_cv}",
        }]},
        content=content,
    )
    cover_edges = [
        e for e in _credit_edges(db, event_kind=KIND_BACK, target="孙承宗")
        if f"dossier:{did_cv}:credit:cover" in str(e["origin"])
    ]
    assert cover_edges, "包庇须写撑腰给被包庇者"
    assert cover_edges[-1]["context"] == reason_cv

    # ── 查办：依法惩主办 → 不记事件（负向）──
    did_pr = _transformed_dossier(
        db, state, token="prosecute-628",
        roster=[{"character_id": "毕自严", "tier": "主办", "role": "承办"}],
    )
    before_all = len(_credit_edges(db))
    before_kinds = {
        k: len(_credit_edges(db, event_kind=k))
        for k in (KIND_BETRAY, KIND_BACK, KIND_SCAPEGOAT, KIND_FULFILL)
    }
    res = apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "毕自严", "动作": "处置", "status": "dismissed",
            "reason": "依律查办削籍", "origin_ref": f"dossier:{did_pr}",
        }]},
        content=content,
    )
    disp = (res.get("credit_event_resolutions") or {}).get("dispositions") or []
    assert any(d.get("disposition") == "查办" for d in disp)
    # 不得因查办新增四类信用边
    for k, n in before_kinds.items():
        assert len(_credit_edges(db, event_kind=k)) == n, f"查办不应写 {k}"
    # 亦无 dossier:…:credit: 新 origin（查办）
    new_credit_origins = [
        e for e in _credit_edges(db)
        if f"dossier:{did_pr}:credit:" in str(e["origin"])
    ]
    assert new_credit_origins == []
    assert len(_credit_edges(db)) >= before_all  # 人事边可能有其它，但不要求


# ── ④ 幂等 + 叙事语境 + restore + 只写不读 + banned ─────────────────


def test_idempotent_narrative_restore_write_only_banned(game, tmp_path):
    """同处置同窗不双写；跨案同人不错吞；叙事语境；restore；零消费；banned 单源。"""
    db, state, content = game

    # banned 单源扩展 + 扫描面清单（AC8 票面交付物，#629 收口）
    assert CREDIT_BANNED_PLAYER_TOKENS
    assert "credit:scapegoat" in CREDIT_BANNED_PLAYER_TOKENS
    assert CREDIT_BANNED_SCAN_SURFACES
    assert "memorial_text" in CREDIT_BANNED_SCAN_SURFACES

    roster = _SCAPEGOAT_ROSTER()
    did_a = _transformed_dossier(db, state, token="idem-a-628", roster=roster)
    did_b = _transformed_dossier(db, state, token="idem-b-628", roster=roster)

    reason_a = "顶罪"
    payload = {"人物变更": [{
        "name": "倪元璐", "动作": "处置", "status": "exiled",
        "reason": reason_a, "origin_ref": f"dossier:{did_a}",
    }]}
    apply_score_extraction(db, state, payload, content=content)
    edges_once = [
        e for e in _credit_edges(db, event_kind=KIND_SCAPEGOAT)
        if f"dossier:{did_a}" in str(e["origin"])
    ]
    assert len(edges_once) == 2
    ids_once = sorted(e["id"] for e in edges_once)

    # 同窗重识别不双写（origin 写前判重）
    apply_score_extraction(db, state, payload, content=content)
    edges_twice = [
        e for e in _credit_edges(db, event_kind=KIND_SCAPEGOAT)
        if f"dossier:{did_a}" in str(e["origin"])
    ]
    assert sorted(e["id"] for e in edges_twice) == ids_once

    # 跨案同人：案 B 另落，不错吞
    reason_b = "另案顶罪"
    apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "倪元璐", "动作": "处置", "status": "exiled",
            "reason": reason_b, "origin_ref": f"dossier:{did_b}",
        }]},
        content=content,
    )
    edges_b = [
        e for e in _credit_edges(db, event_kind=KIND_SCAPEGOAT)
        if f"dossier:{did_b}" in str(e["origin"])
    ]
    assert len(edges_b) == 2
    assert {e["target"] for e in edges_b} == {"倪元璐", "徐光启"}

    # 叙事语境（非固定模板）
    for e in edges_once:
        assert e["context"] == reason_a
        assert e["context"].strip()

    # restore 后可考古
    backup = tmp_path / "credit-628.db"
    db.backup_to(str(backup))
    restored = GameDB(str(backup), content=content)
    try:
        r_edges = [
            dict(r) for r in restored.conn.execute(
                "SELECT * FROM relation_edge_events WHERE event_kind=? "
                "AND origin LIKE ? ORDER BY id",
                (KIND_SCAPEGOAT, f"%dossier:{did_a}:credit:scapegoat%"),
            ).fetchall()
        ]
        assert len(r_edges) == 2
        assert all(str(r["context"] or "").strip() for r in r_edges)
    finally:
        restored.close()

    # 只写不读：本轴无消费端 API（调用侧断言）
    import ming_sim.credit_events as ce
    public = [n for n in dir(ce) if not n.startswith("_")]
    assert "read_credit" not in " ".join(public).lower()
    assert "consume_credit" not in " ".join(public).lower()
    assert "apply_loyalty" not in " ".join(public).lower()
    # write_credit_event 为写；resolve_* 为识别写，非账本消费
    assert callable(write_credit_event)

