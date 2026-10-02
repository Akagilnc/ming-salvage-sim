"""#623 挽留场（0075）——松手检测·哭谏·根基分档。

Seams:
- ENTRY_KIND_BREACH_PLEA 写端（stage_idx=触发 turn）
- list_due_review_scenes 哭谏场面（召对待裁通道）
- apply_pending_due_reviews 仅 staged 终裁；哭谏 pending 保留
- dossiers_with_pending_due_review 不含挽留
- 明确撤令走外廷颁布门（revoke verdict 物化），不写挽留 todo
- resolve_breach_pleas_from_extraction 召对真入口（反悔/坚持）
- 沉默滚存 / 承诺到期失效
- 坚持撤：0056 名声代价 + 授权收回 + 同源承诺停 tick（执行格终局归模型声明）
"""

from __future__ import annotations

import json

from ming_sim.breach_plea import (
    BREACH_KIND_FUNDING,
    BREACH_KIND_MISAPPROPRIATION,
    BREACH_KIND_POLICY_REVERSAL,
    BREACH_KIND_REMOVE_SPONSOR,
    ENTRY_KIND_BREACH_PLEA,
    decode_plea_meta,
    expire_breach_pleas_on_due,
    finalize_persist,
    scan_and_write_breach_pleas,
    write_breach_plea_todo,
)
from tests.test_due_review_621 import _settle_empty_month
from ming_sim.due_review import (
    apply_pending_due_reviews,
    dossiers_with_pending_due_review,
    list_due_review_scenes,
)
from ming_sim.issues import apply_issue_tracker_output, apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
)


# ── fixtures（复用 #621 三拍/_cost_events 口径）────────────────────────


def _cost_events(db, dossier_id, *, identity="breach"):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT * FROM decree_cost_events WHERE dossier_id=? AND cost_identity=? ORDER BY id",
            (int(dossier_id), identity),
        ).fetchall()
    ]


def _executing_policy_dossier(db, state, *, token: str = "breach-623", holder: str = ""):
    if not holder:
        holder = str(db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "ORDER BY name LIMIT 1"
        ).fetchone()["name"])
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "清丈"},
        ],
        payload={"mode": "ordinary", "text": token},
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id, holder


def _insert_commitment(
    db, state, *,
    title: str = "徐光启清丈之诺",
    origin_ref: str = "",
    stages=None,
    end_turn: int = 0,
    ongoing_effects=None,
    stop_condition=None,
    bar_value: int = 20,
    participants=None,
    tags=None,
):
    """经 insert_issue 直写 active 承诺（commitment_kind 非空）。"""
    if not origin_ref:
        did, _ = _executing_policy_dossier(db, state, token=title)
        origin_ref = f"dossier:{did}"
    kwargs = dict(
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin_ref,
        cancellable="decree",
        commitment_kind="until_stop",
        bar_value=bar_value,
        stage_text="在办",
        ongoing_effects=ongoing_effects or {},
        end_turn=int(end_turn or 0),
        stages_json=stages,
        participants=participants,
        tags=list(tags or []),
    )
    if stop_condition is not None:
        kwargs["stop_condition"] = stop_condition
    issue_id = db.insert_issue(state, **kwargs)
    return int(issue_id), origin_ref


def _pending_pleas(db):
    return [
        t for t in db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_BREACH_PLEA
    ]


# ── 四类松手：当回合无损 + 次回合哭谏 ────────────────────────────────


def test_funding_cutoff_writes_plea_no_damage_same_turn(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="fund")
    origin = f"dossier:{did}"
    # 历史月供
    db.record_issue_economy_move(
        state, "国库", -5, "清丈月供", "履行期月供",
        origin_ref=origin, commit=True,
    )
    # 今已断供：ongoing 无 economy
    cid, _ = _insert_commitment(
        db, state, title="清丈月供之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=15,
        end_turn=state.turn + 24,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)
    costs_before = _cost_events(db, did)

    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    assert pleas[0]["criterion_text"] == "断供"
    assert int(pleas[0]["stage_idx"]) == int(state.turn)
    # 当回合无损
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == costs_before
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before

    # 次回合场面
    scenes = list_due_review_scenes(db, state)
    plea_scenes = [s for s in scenes if s.get("entry_kind") == ENTRY_KIND_BREACH_PLEA]
    assert plea_scenes
    assert plea_scenes[0]["kind"] == "breach_plea"
    assert plea_scenes[0]["channel"] == "audience_pending"


def test_misappropriation_writes_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="misapp")
    origin = f"dossier:{did}"
    # 专款：真实 producer= tags「专款:账户」（new_issues.tags 写口），禁 stop_condition 夹具造假
    cid, _ = _insert_commitment(
        db, state, title="国库专款之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 12,
    )
    db.conn.execute(
        "UPDATE issues SET tags=? WHERE id=?",
        (json.dumps(["专款:国库"], ensure_ascii=False), cid),
    )
    db.conn.commit()
    # 本回合挪用：从专款账户支用且 origin 非本承诺
    db.record_issue_economy_move(
        state, "国库", -8, "他用", "挪作赏功",
        origin_ref="dossier:99999", commit=True,
    )
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert any(p["criterion_text"] == "挪用" for p in pleas)
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"


def test_remove_sponsor_writes_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="rm-sponsor")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="人存政举之诺", origin_ref=origin,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        bar_value=20, end_turn=state.turn + 18,
    )
    # 罢主办
    db.conn.execute(
        "UPDATE characters SET status='dismissed' WHERE name=?", (holder,),
    )
    db.conn.commit()
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert any(p["criterion_text"] == "撤人" for p in pleas)
    # 当回合承诺仍 active；0056 不落（撤人）
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == []


def test_policy_reversal_revoke_takes_effect_same_month(game):
    """#1894：撤旨照常过外廷——外庭准行当月落实，不写挽留 todo、不等下一场召对。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="revoke-defer")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="改弦可撤之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )

    # 走真实 revoke verdict 物化缝（外廷颁布判决）
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="前旨作废",
        target_kind="dossier",
        target_id=str(did),
        payload={
            "revoke_target_dossier_id": did,
            "text": "前旨作废，撤回成命",
        },
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": revoke_id, "decision": "promulgated"}],
        content=content,
    )
    # 当月即落：0056 代价已写、同源承诺已停 tick
    assert _cost_events(db, did, identity="breach")
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"
    # #1894：0056 不抢在模型执行格判决前关案——原案卷仍在 executing，
    # 等执行格判官本月声明 dossier_executions 落终局（见下一用例）。
    after = db.get_decree_dossier(did)
    assert str(after["status"]) == "executing"
    assert not str(after["execution_outcome"] or "")
    # 不写挽留 todo：没有「等下一次召对坚持撤」这道前置
    assert _pending_pleas(db) == []
    assert not any(
        s.get("kind") == "breach_plea" for s in list_due_review_scenes(db, state)
    )


def test_policy_reversal_revoke_model_verdict_lands_same_month(game):
    """#1894：撤令准行当月，模型对原案卷的办理结果照常落账结案。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="revoke-verdict")
    db.record_issue_economy_move(
        state, "国库", -12, "投入", "已投入", origin_ref=f"dossier:{did}", commit=True,
    )
    db.record_dossier_progress(
        did, state.turn, "在办", "过半", is_terminal=False, commit=True,
    )
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="前旨作废",
        target_kind="dossier",
        target_id=str(did),
        payload={"revoke_target_dossier_id": did, "text": "前旨作废，撤回成命"},
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": revoke_id, "decision": "promulgated"}], content=content,
    )
    out = apply_score_extraction(db, state, {"dossier_executions": [{
        "dossier_id": did, "outcome": "degraded",
        "note": "半途而止，已花之帑难回",
    }]}, content=content)
    assert not any(
        row.get("rejected") for row in out.get("dossier_executions") or []
    ), out.get("dossier_executions")
    settled = db.get_decree_dossier(did)
    assert str(settled["status"]) == "closed"
    assert str(settled["execution_outcome"]) == "degraded"


def test_policy_reversal_revoke_keeps_same_origin_world_situations(game):
    """#1894：撤令只停同源**承诺**，不无差别终结该案卷下长出的世界局势。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="revoke-keep-world")
    cid, _ = _insert_commitment(
        db, state, title="撤令停诺之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    # 同源长出的世界局势（民乱）：非 initiative，存废归世界段模型声明
    unrest_id = db.insert_issue(
        state, kind="situation", title="流民聚众抗粮",
        origin_kind="dossier", origin_ref=f"dossier:{did}",
    )
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="前旨作废",
        target_kind="dossier",
        target_id=str(did),
        payload={"revoke_target_dossier_id": did, "text": "前旨作废"},
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": revoke_id, "decision": "promulgated"}], content=content,
    )
    statuses = {
        int(row["id"]): str(row["status"])
        for row in db.conn.execute(
            "SELECT id, status FROM issues WHERE id IN (?, ?)", (cid, unrest_id),
        ).fetchall()
    }
    assert statuses[int(cid)] == "dropped"
    assert statuses[int(unrest_id)] == "active", "撤令不得无差别终结同源世界局势"


def test_audience_revoke_commission_stages_typed_revoke_decree(game):
    """#1894：召对转译声明撤令 → 既有 revoke_decree 交办写口，关联原案卷。

    撤令不再被当作无结构纯正文（special_decree/policy/commission-text）暂存。
    """
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _holder = _executing_policy_dossier(db, state, token="audience-revoke")
    affair = db.affairs.open(
        name="改弦事务", origin="旨意", year=state.year,
        period=state.period, turn=state.turn,
    )

    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "前旨作废，撤回成命",
            "revoke": {"target_kind": "dossier", "target_id": str(did)},
            "affair_declaration": {"attach": "existing", "affair_id": affair.id},
        }]},
        minister_name="",
    )
    assert not result.commissions.rejected, result.commissions.rejected
    row_id = int(result.commissions.applied[0]["id"])
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (row_id,),
    ).fetchone()["payload_json"])
    assert payload["dossier_action_type"] == "revoke_decree"
    assert int(payload["revoke_target_dossier_id"]) == did
    assert payload["target_kind"] == "dossier"
    assert str(payload["target_id"]) == str(did)
    assert payload["text"] == "前旨作废，撤回成命"
    # 原旨与撤令沿同一事务关联（ADR 0154）：暂存载荷承既有声明接缝，不另造推断
    assert payload["affair_declaration"] == {
        "attach": "existing", "affair_id": affair.id,
    }


def test_audience_revoke_commission_rejects_unrevocable_target(game):
    """目标不是可撤的已颁承诺/旨意（含「撤回最近一轮召对」）→ 既有准入零变化。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    before = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pending_actions WHERE status='pending'",
    ).fetchone()["c"]

    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "把方才那话收回去",
            "revoke": {"target_kind": "dossier", "target_id": "999999"},
        }]},
        minister_name="",
    )
    assert not result.commissions.applied
    assert result.commissions.rejected
    after = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pending_actions WHERE status='pending'",
    ).fetchone()["c"]
    assert int(after) == int(before)


def test_revoke_forecast_translation_input_carries_original_and_continuing_dossier(game, monkeypatch):
    """#1894：撤令的逐旨推演段文转译时，原案卷与在途案卷清单都在输入里。

    走真实推演入口 ``produce_forecast_product``：撤令的办理结果由执行格判官在
    本段声明 ``dossier_executions``，清单不给原案卷 id 就无从落它的执行格。
    同一段也验目标身份：载荷同时含原案与承诺 id 时两者都读到（不读到其一即止）。
    """
    from ming_sim import decree as decree_mod
    from ming_sim import decree_forecast as forecast_mod
    from ming_sim import month_translate
    from ming_sim.decree_forecast import forecast_snapshot, produce_forecast_product
    from tests.test_decree_forecast_1861 import _sess

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="forecast-input")
    db.record_issue_economy_move(
        state, "国库", -30, "投入", "已投入", origin_ref=f"dossier:{did}", commit=True,
    )
    db.record_dossier_progress(did, state.turn, "在办", "过半", commit=True)
    cid, _ = _insert_commitment(
        db, state, title="撤令连诺之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )

    # 召对真入口暂存的撤令载荷（含原案 + 承诺两个结构化身份）
    from ming_sim.declaration_dispatch import dispatch_declaration

    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "前旨作废，撤回成命",
            "revoke": {"target_kind": "issue", "target_id": str(cid)},
        }]},
        minister_name="",
    )
    assert not staged.commissions.rejected, staged.commissions.rejected
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (staged.commissions.applied[0]["id"],),
    ).fetchone()["payload_json"])
    assert int(payload["revoke_target_dossier_id"]) == did
    assert int(payload["revoke_target_issue_id"]) == int(cid)

    sess = _sess(db, state, content, monkeypatch, lambda request, config: {})
    captured = {}

    def forecast_text(_agent, _prompt, **kwargs):
        return "外廷准行，此令撤在途中。"

    def judge(_agent, prompt, **kwargs):
        entry = json.loads(prompt)["dossiers"][0]
        # 撤令的颁布判官据原旨事实判准行（真实链：判官供料不缺席）
        assert int(entry["revoke_target"]["dossier_id"]) == did
        assert int(entry["revoke_target"]["issue_id"]) == int(cid)
        return json.dumps({
            "verdicts": [{"dossier_id": entry["id"], "decision": "promulgated"}],
        })

    def capture_request(request, _llm_config):
        # 段文转译的结构化输入接缝（MonthTranslationInput），不解析 prompt 文本
        captured["request"] = request
        return {}

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", forecast_text)
    monkeypatch.setattr(month_translate, "_default_month_translate_runner", capture_request)
    snapshot = forecast_snapshot(
        sess, {"id": did, "action_type": "revoke_decree", "payload": payload,
               "decree_text": "前旨作废，撤回成命"},
        decree_ref="forecast:revoke",
    )
    product = produce_forecast_product(sess, snapshot)

    assert product["verdict"]["decision"] == "promulgated"
    # 推演本旨事实里带着原旨身份（逐旨推演判官与转译同一份供料）
    forecast_target = snapshot["this_decree"]["revoke_target"]
    assert int(forecast_target["dossier_id"]) == did
    assert int(forecast_target["issue_id"]) == int(cid)
    # 在途案卷清单进转译输入：撤令的办理结果由执行格判官在本段声明
    request = captured["request"]
    rows = {int(row["id"]): row for row in request.continuing_dossiers}
    assert did in rows, "撤令须在转译输入里看见原案卷，否则执行格无从落"
    assert rows[did]["status"] == "executing"
    assert int(rows[did]["paid"]) == 30
    assert dict(request.decree_payload)["revoke_target_issue_id"] == int(cid)


def test_revoke_target_identity_falls_back_to_dossier_row(game, monkeypatch):
    """载荷缺 ``revoke_target_*`` 时，撤令的目标身份取自案卷行本身。

    撤令案卷的目标身份本就同时存在行上：漏读行，判前供料交不出原旨事实、
    判后物化抛「缺少目标」，原案卷与承诺均不落终局。此处走三个真实入口——
    颁布判官上下文、逐旨推演本旨事实（判前）与颁布判决（判后）——
    不锁内部解析实现。
    """
    from ming_sim import decree as decree_mod
    from ming_sim.decree_forecast import forecast_snapshot, release_forecast_materials
    from tests.test_decree_forecast_1861 import _sess

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="row-fallback")
    cid, _ = _insert_commitment(
        db, state, title="行回退之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_progress(did, state.turn, "在办", "过半", commit=True)

    revoke_id = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤回前旨",
        target_kind="issue", target_id=str(cid),
        payload={"text": "撤回前旨"},
    )

    # 判前（颁布判官）：确定性上下文带着原旨事实（原案 + 承诺两个身份都在）
    row = db.get_decree_dossier(revoke_id)
    context = decree_mod.build_promulgation_judge_context(db, state, [row])
    entry = context["dossiers"][0]  # type: ignore[index]
    target = entry["revoke_target"]
    assert int(target["dossier_id"]) == did
    assert int(target["issue_id"]) == int(cid)
    assert int(target["paid"]) == 0
    assert [item["progress_band"] for item in target["progress"]] == ["在办"]

    # 判前（逐旨推演）：本旨事实同一读口，行身份也进推演输入
    sess = _sess(db, state, content, monkeypatch, lambda request, config: {})
    snapshot = forecast_snapshot(sess, row, decree_ref="forecast:row-fallback")
    try:
        forecast_target = snapshot["this_decree"]["revoke_target"]
    finally:
        release_forecast_materials(snapshot)
    assert int(forecast_target["dossier_id"]) == did
    assert int(forecast_target["issue_id"]) == int(cid)

    # 判后物化：撤令案卷不给 revoke_target_*，仍按行解析并落账
    db.apply_dossier_verdicts(
        state, [{"dossier_id": revoke_id, "decision": "promulgated"}], content=content,
    )
    assert _cost_events(db, did, identity="breach"), "0056 名声账应照落"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"
    assert str(db.get_decree_dossier(did)["status"]) == "executing"


def test_policy_reversal_revoke_rejected_leaves_everything_untouched(game):
    """#1894：外庭劝回/打回则撤令未生效——原案卷与承诺零变化，不伪报已撤。"""
    from dossier_test_helpers import rejected_verdict

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="revoke-rejected")
    cid, _ = _insert_commitment(
        db, state, title="劝回则不撤之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="前旨作废",
        target_kind="dossier",
        target_id=str(did),
        payload={"revoke_target_dossier_id": did, "text": "前旨作废"},
    )
    db.apply_dossier_verdicts(state, [rejected_verdict(revoke_id)], content=content)
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == []
    assert _pending_pleas(db) == []


# ── 同承诺两次松手各有独立条 ──────────────────────────────────────────


def test_two_successive_loosenings_get_independent_pleas(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="twice")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="两度松手之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
    )
    # 第一次：断供
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 推进一回合后第二次：改弦
    state.turn += 1
    db.save_state(state)
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 > 0
    assert t2 != t1
    pleas = _pending_pleas(db)
    assert len(pleas) == 2
    stage_idxs = sorted(int(p["stage_idx"]) for p in pleas)
    assert stage_idxs[0] != stage_idxs[1]


# ── 反悔 / 坚持 ────────────────────────────────────────────────────────


def test_regret_via_extraction_true_entry_zero_damage(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="regret")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="可反悔之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 20,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="欲撤", target_dossier_id=did, commit=True,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)

    # 召对真入口：既有键 issue_advances / economy 续拨（禁 breach_plea_decisions 显式通道）
    out = apply_score_extraction(
        db, state,
        {
            "issue_advances": [{
                "issue_id": cid, "delta_bar": 1,
                "narrative": "朕加拨复其供亿，前诺照旧",
            }],
        },
        content=content,
    )
    assert out.get("breach_plea_resolutions")
    assert out["breach_plea_resolutions"][0]["decision"] == "regret"
    # 两轨零落账（反悔不写撑腰边）
    assert _cost_events(db, did) == []
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before
    assert _pending_pleas(db) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events "
        "WHERE event_kind='撑腰' AND origin LIKE ?",
        (f"issue:{cid}:%",),
    ).fetchone()["c"] == 0


def test_persist_leaves_execution_verdict_to_model(game):
    """#1894 坚持分支：代码只落名声账与停 tick；执行格终局与半途后果归模型声明。

    无论已投入与实际进度如何，代码都不判档、不生成剧情后果、不关案：案卷仍在
    executing，执行格仍空，等执行格判官本月判决经 dossier_executions 落地。
    """
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="tier-halfway")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -10, "投入", "半途投入", origin_ref=origin, commit=True,
    )
    db.record_dossier_progress(did, state.turn, "在办", "过半", commit=True)
    cid, _ = _insert_commitment(
        db, state, title="办到一半之诺", origin_ref=origin,
        bar_value=45, end_turn=state.turn + 50,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·办到一半", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    minxin_before = int(state.metrics.get("民心", 0) or 0)
    huangwei_before = int(state.metrics.get("皇威", 0) or 0)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is True
    assert result["target_dossier_id"] == did
    # 0056 恰一次
    breach_costs = _cost_events(db, did, identity="breach")
    assert breach_costs
    # 幂等：不再双开
    assert db.breach_decree_dossier(state, did, reason="重复", commit=True) is False
    assert _cost_events(db, did, identity="breach") == breach_costs

    # 代码不判根基档、不生成事轴后果（P6 判断权归模型）
    assert "foundation_tier" not in result
    assert "setback" not in result
    assert int(state.metrics.get("民心", 0) or 0) == minxin_before
    assert int(state.metrics.get("皇威", 0) or 0) < huangwei_before  # 仅 0056 那一笔
    # 代码不抢在模型声明前关案：执行格仍空、案卷仍 executing
    after = db.get_decree_dossier(did)
    assert str(after["status"]) == "executing"
    assert not str(after["execution_outcome"] or "")

    # 承诺已停
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"


def test_model_execution_verdict_lands_after_persist(game):
    """撤令当月：执行格判官的判决经**真实转译→分派链**落地结案（不被 0056 抢先关案拒收）。

    走 ``stage_month_segment`` → ``settle_staged_declarations_in_decree_order``
    ——与逐旨预推同一入口，声明不是手工塞进 apply_score_extraction 的。
    """
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.month_translate import stage_month_segment

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="verdict-after")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -10, "投入", "半途投入", origin_ref=origin, commit=True,
    )
    db.record_dossier_progress(did, state.turn, "在办", "过半", commit=True)
    cid, _ = _insert_commitment(
        db, state, title="模型判决之诺", origin_ref=origin,
        bar_value=45, end_turn=state.turn + 50,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·模型判", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    finalize_persist(db, state, todo, commit=True)
    assert str(db.get_decree_dossier(did)["status"]) == "executing"

    # 执行格判官的声明：在途清单给出原案卷 id，段文交代它半途而废
    seen = {}

    def translate(request, _llm_config):
        seen["continuing"] = [int(row["id"]) for row in request.continuing_dossiers]
        return {"effects": {"dossier_executions": [{
            "dossier_id": did, "outcome": "failed", "note": "半途而废，案卷记为烂尾",
        }]}}

    assert stage_month_segment(
        db, decree_ref="revoke:verdict-after", segment="此令撤在途中，案遂烂尾。",
        turn=int(state.turn), decree_payload={"revoke_target_dossier_id": did},
        translate_fn=translate,
    ) > 0
    assert did in seen["continuing"]

    result = settle_staged_declarations_in_decree_order(db, state, ["revoke:verdict-after"])
    applied = result["revoke:verdict-after"].effects.applied[0]["dossier_executions"]
    assert applied and not applied[0].get("rejected"), applied
    settled = db.get_decree_dossier(did)
    assert str(settled["status"]) == "closed"
    assert str(settled["execution_outcome"]) == "failed"


def test_persist_remove_sponsor_no_0056(game):
    """0041③：撤人坚持不触发 0056；案卷终局仍归模型判决。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="no56")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="撤人不毁约名", origin_ref=origin,
        bar_value=15, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢主办", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is False
    assert _cost_events(db, did, identity="breach") == []
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"
    assert str(db.get_decree_dossier(did)["status"]) == "executing"


def test_persist_via_extraction_cancels_true_entry(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="persist-x")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="extraction坚持", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 15,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="仍撤", target_dossier_id=did, commit=True,
    )
    out = apply_score_extraction(
        db, state,
        {"cancels": [{"issue_id": cid, "narrative": "朕意已决，仍撤此诺"}]},
        content=content,
    )
    assert out.get("breach_plea_resolutions")
    assert out["breach_plea_resolutions"][0]["decision"] == "persist"
    assert _pending_pleas(db) == []
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"


# ── 沉默滚存 / 到期失效 ──────────────────────────────────────────────


def test_silence_keeps_pending_across_settle(game, monkeypatch):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="silence")
    cid, _ = _insert_commitment(
        db, state, title="沉默滚存之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_FUNDING, reason="断供",
        target_dossier_id=did, commit=True,
    )
    # 把 created_turn 调旧，使 apply 会扫到
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=? WHERE entry_kind=?",
        (state.turn - 1, ENTRY_KIND_BREACH_PLEA),
    )
    db.conn.commit()
    results = apply_pending_due_reviews(db, state, commit=True)
    # 哭谏被 skip 保留
    skipped = [r for r in results if r.get("skipped") and r.get("entry_kind") == ENTRY_KIND_BREACH_PLEA]
    assert skipped
    assert _pending_pleas(db)
    assert db.get_decree_dossier(did)["status"] == "executing"

    # 再过月一拍仍 pending 可顶出
    _settle_empty_month(db, state, content, monkeypatch)
    assert _pending_pleas(db)
    scenes = list_due_review_scenes(db, state)
    assert any(s.get("kind") == "breach_plea" for s in scenes)


def test_commitment_due_expires_plea_without_persist_damage(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="expire")
    due = state.turn  # 已到期
    cid, _ = _insert_commitment(
        db, state, title="到期失效之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=due,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL, reason="欲撤",
        target_dossier_id=did, commit=True,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)
    expired = expire_breach_pleas_on_due(db, state, commit=True)
    assert expired
    assert expired[0]["reason"] == "commitment_due"
    assert _pending_pleas(db) == []
    # 不补 0056 / 事轴倒退
    assert _cost_events(db, did) == []
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before
    # 承诺本身仍 active（#621 到期终局另管；此处只关挽留条）
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"


# ── kind 对称闸 / 接管窗 / restore ────────────────────────────────────


def test_kind_gate_apply_only_finalizes_staged(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="kind-gate")
    # staged todo
    stages = [{
        "stage_idx": 0, "due_turn": state.turn,
        "criterion_text": "火器", "origin_context": "三年火器",
    }]
    from ming_sim.issues import apply_score_extraction as ase
    # 用 staged 写端
    from ming_sim.staged_commitment import write_due_staged_commitment_todos
    cid_staged, _ = _insert_commitment(
        db, state, title="分段闸测", origin_ref=f"dossier:{did}",
        stages=stages, bar_value=20,
    )
    write_due_staged_commitment_todos(db, state, commit=True)
    # breach plea
    cid_plea, _ = _insert_commitment(
        db, state, title="哭谏闸测", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 10,
    )
    # 同 dossier 第二承诺——改用独立 dossier 避免互相干扰
    did2, _ = _executing_policy_dossier(db, state, token="kind-gate-2")
    db.conn.execute("UPDATE issues SET origin_ref=? WHERE id=?", (f"dossier:{did2}", cid_plea))
    db.conn.commit()
    write_breach_plea_todo(
        db, state, commitment_ref=cid_plea,
        breach_kind=BREACH_KIND_FUNDING, reason="断", target_dossier_id=did2,
        commit=True,
    )
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()

    before_plea = _pending_pleas(db)
    assert before_plea
    results = apply_pending_due_reviews(db, state, commit=True)
    staged_done = [r for r in results if r.get("entry_kind") == ENTRY_KIND_STAGED and r.get("consumed")]
    plea_skip = [r for r in results if r.get("entry_kind") == ENTRY_KIND_BREACH_PLEA and r.get("skipped")]
    assert staged_done or any(
        str(t.get("entry_kind")) == ENTRY_KIND_STAGED
        and str(t.get("status")) == TODO_STATUS_CONSUMED
        for t in db.list_next_audience_todos()
    )
    assert plea_skip
    assert _pending_pleas(db), "哭谏须仍 pending"
    # 非 staged 未连坐 did2
    assert _cost_events(db, did2, identity="连坐") == []


def test_takeover_window_excludes_breach_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="takeover-ex")
    cid, _ = _insert_commitment(
        db, state, title="不占接管窗", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 10,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL, reason="欲撤",
        target_dossier_id=did, commit=True,
    )
    owned = dossiers_with_pending_due_review(db, state)
    assert did not in owned


def test_breach_plea_survives_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="restore")
    cid, _ = _insert_commitment(
        db, state, title="restore挽留", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 20,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_MISAPPROPRIATION, reason="挪",
        target_dossier_id=did, commit=True,
    )
    path = db.path
    db.conn.close()
    from ming_sim.db import GameDB
    db2 = GameDB(path)
    state2 = db2.load_state()
    pleas = [
        t for t in db2.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if t.get("entry_kind") == ENTRY_KIND_BREACH_PLEA
    ]
    assert len(pleas) == 1
    scenes = list_due_review_scenes(db2, state2)
    assert any(s.get("kind") == "breach_plea" for s in scenes)
    db2.close()


def test_no_decision_pause_on_breach_plea_settle(game, monkeypatch):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="no-dec")
    db.record_issue_economy_move(
        state, "国库", -2, "月供", "史", origin_ref=f"dossier:{did}", commit=True,
    )
    _insert_commitment(
        db, state, title="不停轮", origin_ref=f"dossier:{did}",
        ongoing_effects={}, bar_value=15, end_turn=state.turn + 24,
    )
    result = _settle_empty_month(db, state, content, monkeypatch)
    assert result.awaiting is False
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value


# ── 修后四组新增用例 ──────────────────────────────────────────────────


def test_same_turn_dual_breach_kinds_merge_not_swallowed(game):
    """同回合第二类松手不得静默吞：并入既有 pending + meta 记全被吞类。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="dual-kind")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="同回合双类之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
        tags=["专款:国库"],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 同回合第二类：改弦（不推进 turn）
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 == t1  # 并入同一条
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    from ming_sim.breach_plea import decode_plea_meta
    meta = decode_plea_meta(pleas[0]["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    absorbed = meta.get("absorbed_breach_kinds") or []
    assert BREACH_KIND_POLICY_REVERSAL in absorbed
    # #1894：再撤一道不会另起挽留条（同回合已并入的那条也不因撤令而复活等待）


def test_persist_reclaims_bundled_authority(game):
    """坚持落地=立即 revoke 路径：捆带授权收回 fail-loud。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="auth-bundle")
    origin = f"dossier:{did}"
    # 目标案卷授予一条授权
    db.conn.execute(
        "INSERT INTO authority_records "
        "(holder_id, privilege, scope, effective_turn, expires_turn, dossier_id, revoked) "
        "VALUES (?, ?, ?, ?, NULL, ?, 0)",
        (holder, "便宜行事", f"region:shaanxi", int(state.turn), int(did)),
    )
    db.conn.commit()
    auth_id = int(db.conn.execute(
        "SELECT id FROM authority_records WHERE dossier_id=? AND revoked=0",
        (did,),
    ).fetchone()["id"])
    cid, _ = _insert_commitment(
        db, state, title="捆带授权之诺", origin_ref=origin,
        bar_value=15, end_turn=state.turn + 20,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·捆带", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is True
    row = db.conn.execute(
        "SELECT revoked FROM authority_records WHERE id=?", (auth_id,),
    ).fetchone()
    assert row is not None and int(row["revoked"] or 0) == 1
    assert result.get("authority_reclaims")


def test_remove_sponsor_persist_writes_credit_edge(game):
    """0079：撤人坚持撤有案卷时仍写辜负边（0056 不触发，不重复）。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="credit-rm")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="撤人信用边", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢主办", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is False
    edges = list(db.conn.execute(
        "SELECT event_kind, target, origin FROM relation_edge_events "
        "WHERE target=? AND event_kind='辜负' ORDER BY id",
        (holder,),
    ).fetchall())
    assert edges, "撤人坚持须写 0079 辜负边"
    assert any(f"issue:{cid}" in str(e["origin"] or "") for e in edges)


def test_same_sponsor_two_commitments_both_remove_edges(game):
    """同主办两承诺同回合各坚持撤人：两笔 issue:*:breach_plea 辜负边俱落。

    去重只对本 finalize 自己的 0056 落账；跨承诺同人边不得吞。
    """
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did_a, holder = _executing_policy_dossier(db, state, token="dual-rm-a")
    did_b, _ = _executing_policy_dossier(
        db, state, token="dual-rm-b", holder=holder,
    )
    cid_a, _ = _insert_commitment(
        db, state, title="撤人双案甲", origin_ref=f"dossier:{did_a}",
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    cid_b, _ = _insert_commitment(
        db, state, title="撤人双案乙", origin_ref=f"dossier:{did_b}",
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_a = write_breach_plea_todo(
        db, state, commitment_ref=cid_a,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢甲案主办", target_dossier_id=did_a, commit=True,
    )
    todo_b = write_breach_plea_todo(
        db, state, commitment_ref=cid_b,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢乙案主办", target_dossier_id=did_b, commit=True,
    )
    ta = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_a)
    tb = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_b)
    ra = finalize_persist(db, state, ta, commit=True)
    rb = finalize_persist(db, state, tb, commit=True)
    assert ra["breach_0056"] is False
    assert rb["breach_0056"] is False
    edges = list(db.conn.execute(
        "SELECT origin FROM relation_edge_events "
        "WHERE target=? AND event_kind='辜负' AND turn=? "
        "AND origin LIKE 'issue:%breach_plea%' ORDER BY id",
        (holder, int(state.turn)),
    ).fetchall())
    origins = [str(e["origin"] or "") for e in edges]
    assert any(
        o.startswith(f"issue:{cid_a}:breach_plea") for o in origins
    ), f"甲承诺撤人边须落，got={origins!r}"
    assert any(
        o.startswith(f"issue:{cid_b}:breach_plea") for o in origins
    ), f"乙承诺撤人边须落，got={origins!r}"


def test_misappropriation_via_tags_producer_pipeline(game):
    """挪用真实管线：tags 专款写口（模拟 new_issues.tags producer）可达。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="mis-pipe")
    origin = f"dossier:{did}"
    # 经 insert_issue tags 参数（与 new_issues.tags 同写口）
    cid, _ = _insert_commitment(
        db, state, title="tags专款管线", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 12,
        tags=["专款:国库", "清丈"],
        ongoing_effects={
            "economy": [{
                "account": "国库", "delta": -4,
                "category": "专款月供", "reason": "清丈专款",
            }],
        },
    )
    # 确认读口可达
    from ming_sim.breach_plea import _dedicated_accounts
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (cid,)).fetchone()
    assert "国库" in _dedicated_accounts(row)
    db.record_issue_economy_move(
        state, "国库", -6, "他用", "挪作赏功",
        origin_ref="盘面自发", commit=True,
    )
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    assert any(p["criterion_text"] == "挪用" for p in _pending_pleas(db))


# ── #623 r2：merged 条 persist 链只认 primary 的三面 ──────────────────


def _merge_funding_then_reversal(db, state, *, token: str):
    """同回合并入：断供 primary + 改弦 absorbed（生产写入口可达）。"""
    did, holder = _executing_policy_dossier(db, state, token=token)
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title=f"合并入坚持·{token}", origin_ref=origin,
        bar_value=15, end_turn=state.turn + 20,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        tags=["专款:国库"],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 == t1
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    meta = decode_plea_meta(pleas[0]["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    assert BREACH_KIND_POLICY_REVERSAL in (meta.get("absorbed_breach_kinds") or [])
    return cid, did, holder, int(pleas[0]["id"])


def test_merged_persist_via_tracker_cancel_settles(game):
    """㈠ cancel 路：merged（断供 primary+改弦 absorbed）→ tracker cancel 坚持撤。

    承诺结账 + todo consumed + applied_cancels 报实一致（禁虚报 persist）。
    """
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    cid, did, holder, todo_id = _merge_funding_then_reversal(
        db, state, token="trk-mrg",
    )
    out = apply_issue_tracker_output(
        db, state,
        {"cancels": [{"issue_id": cid, "narrative": "朕意已决，仍撤此诺"}]},
        content=content,
    )
    cancels = out.get("cancels") or []
    hit = [c for c in cancels if int(c.get("issue_id") or 0) == int(cid)]
    assert hit, f"cancel 须命中承诺，got={cancels!r}"
    assert hit[0].get("breach_plea_decision") == "persist"
    assert hit[0].get("rejected") is False
    # todo consumed
    assert _pending_pleas(db) == []
    todo_row = db.conn.execute(
        "SELECT status FROM next_audience_todos WHERE id=?", (todo_id,),
    ).fetchone()
    assert todo_row is not None
    assert str(todo_row["status"]) == TODO_STATUS_CONSUMED
    # 承诺非 active
    iss = db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()
    assert iss is not None and str(iss["status"]) != "active"
    # 0056 落（funding/改弦 均属触发集）
    assert _cost_events(db, did, identity="breach")


def test_merged_persist_via_extraction_settles(game):
    """㈠ extraction 路：merged 改弦 absorbed → resolve 真入口坚持撤结账。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    cid, did, holder, todo_id = _merge_funding_then_reversal(
        db, state, token="ext-mrg",
    )
    out = apply_score_extraction(
        db, state,
        {"cancels": [{"issue_id": cid, "narrative": "朕意已决，仍撤此诺"}]},
        content=content,
    )
    resolutions = out.get("breach_plea_resolutions") or []
    assert resolutions, "extraction 须 resolve merged 条"
    assert resolutions[0]["decision"] == "persist"
    assert int(resolutions[0].get("todo_id") or 0) == todo_id
    assert _pending_pleas(db) == []
    iss = db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()
    assert iss is not None and str(iss["status"]) != "active"
    assert _cost_events(db, did, identity="breach")


def test_merged_funding_primary_remove_sponsor_absorbed_accounts(game):
    """㈡ primary=funding + absorbed=[remove_sponsor]：0056 落一次、撤人辜负边在且不重复。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="f+rm")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="断供主+撤人并", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="撤人", target_dossier_id=did, commit=True,
    )
    assert t2 == t1
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == t1)
    meta = decode_plea_meta(todo["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    assert BREACH_KIND_REMOVE_SPONSOR in (meta.get("absorbed_breach_kinds") or [])

    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is True
    assert _cost_events(db, did, identity="breach")
    edges = list(db.conn.execute(
        "SELECT event_kind, target, origin FROM relation_edge_events "
        "WHERE target=? AND event_kind='辜负' AND turn=? ORDER BY id",
        (holder, int(state.turn)),
    ).fetchall())
    assert edges, "撤人/0056 须落辜负边"
    # 同人同回合不重复（0056 已写则 0079 跳过）
    assert len(edges) == 1


def test_merged_remove_sponsor_primary_funding_absorbed_accounts(game):
    """㈢ primary=remove_sponsor + absorbed=[funding]：0056 落、撤人边不丢且不重复。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="rm+f")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="撤人主+断供并", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="撤人", target_dossier_id=did, commit=True,
    )
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t2 == t1
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == t1)
    meta = decode_plea_meta(todo["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_REMOVE_SPONSOR
    assert BREACH_KIND_FUNDING in (meta.get("absorbed_breach_kinds") or [])

    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is True, "absorbed funding 须触发 0056"
    assert _cost_events(db, did, identity="breach")
    edges = list(db.conn.execute(
        "SELECT event_kind, target, origin FROM relation_edge_events "
        "WHERE target=? AND event_kind='辜负' AND turn=? ORDER BY id",
        (holder, int(state.turn)),
    ).fetchall())
    assert edges, "撤人边/0056 辜负不得丢"
    assert len(edges) == 1, "同人辜负不重复"
