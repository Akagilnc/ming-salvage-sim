"""#1503 拨饷诏颁布即落账销欠。

Seams:
- stage_grant_allocation_candidate / commit_pending_actions（成案结构化载荷）
- apply_dossier_verdicts / apply_dossier_promulgation（颁布缝一次消费）
- _apply_economy_list / _pay_single_army_arrears（扣库+销欠 + ADR 0023 clamp）
- apply_score_extraction economy_moves 过滤（单写者；extractor 不二扣）
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ActionCandidateShapeError,
    assert_action_candidate_shape,
)
from ming_sim.issues import apply_score_extraction
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent






def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


def _set_guanning_arrears(db, arrears: float, *, central: float | None = None,
                          province: float | None = None) -> None:
    if central is None and province is None:
        central = float(arrears)
        province = 0.0
    elif central is None:
        central = max(0.0, float(arrears) - float(province or 0))
    elif province is None:
        province = max(0.0, float(arrears) - float(central or 0))
    db.conn.execute(
        """
        UPDATE armies
        SET arrears=?, province_pay_arrears=?, central_pay_arrears=?
        WHERE id='guanning'
        """,
        (float(arrears), float(province), float(central)),
    )
    db.conn.commit()


def _army_row(db, army_id="guanning"):
    return dict(db.conn.execute(
        "SELECT arrears, province_pay_arrears, central_pay_arrears FROM armies WHERE id=?",
        (army_id,),
    ).fetchone())


def _promulgate(db, state, content, dossier_id, decision="promulgated"):
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier_id, "decision": decision}],
        content=content,
    )


# ── ① 成案结构化载荷 ──────────────────────────────────────────────



def test_army_pay_missing_fields_fail_loud_at_admission(game):
    """真实成案 admission 同时缺五项：一次 typed 聚合，案卷/账本/国库零写。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    ledger_before = db.conn.execute("SELECT COUNT(*) AS n FROM economy_ledger").fetchone()["n"]
    before_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    candidate_id = db.stage_pending_action(
        state.turn, "directive", "拟旨", "兵部尚书",
        {"text": "拟旨如下：准拨军饷。"},
    )
    from ming_sim.action_materialize import IncompleteXiexangPayloadError

    with pytest.raises(IncompleteXiexangPayloadError) as caught:
        db.update_directive_candidate(
            candidate_id,
            {
                "text": "拟旨如下：准拨军饷。",
                "dossier_action_type": "grant_allocation",
                "grant_action": "协饷",
            },
        )
    assert caught.value.missing_fields == (
        "amount", "account", "purpose", "target_kind", "target_id",
    )
    with pytest.raises(IncompleteXiexangPayloadError) as cadence_error:
        from ming_sim.action_materialize import require_explicit_xiexang_fields
        require_explicit_xiexang_fields(
            amount=15, account="国库", purpose="补饷",
            target_kind="army", target_id="guanning", cadence="每季",
        )
    assert "cadence" in cadence_error.value.missing_fields
    assert {int(d["id"]) for d in db.list_decree_dossiers()} == before_ids
    assert int(state.metrics["国库"]) == treasury_before
    ledger_after = db.conn.execute("SELECT COUNT(*) AS n FROM economy_ledger").fetchone()["n"]
    assert ledger_after == ledger_before


def test_xiexang_unresolvable_target_rejected_before_pending(game):
    """五项齐全但 target 无法解析为军队：fail-loud、零写入。"""
    db, state, content = game
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    treasury_before = int(state.metrics["国库"])
    before_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    before_pending = db.list_pending_actions(state.turn, minister_name=actor)

    with pytest.raises(ValueError, match=r"协饷旨意 target 无法解析为军队"):
        stage_grant_allocation_candidate(
            db, state.turn, actor,
            text="臣请协饷辽东。",
            grant_action="协饷",
            target_kind="army",
            target_id="liaodong",
            amount=15,
            account="国库",
            purpose="补饷",
        )
    after_pending = db.list_pending_actions(state.turn, minister_name=actor)
    assert len(after_pending) == len(before_pending)
    assert int(state.metrics["国库"]) == treasury_before
    after_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    assert after_ids == before_ids


def test_revise_away_from_xiexang_clears_pay_only_fields(game):
    """改案离开协饷时清 purpose/immediate，不得残留销欠语义。"""
    db, state, content = game
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    first_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text="臣请协饷关宁十五万。",
        grant_action="协饷",
        target_kind="army",
        target_id="guanning",
        amount=15,
        account="国库",
        purpose="补饷",
    )
    assert first_id > 0
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (first_id,),
    ).fetchone()["payload_json"])
    assert pending["purpose"] == "补饷"
    assert pending.get("execution_surface") == "immediate"

    updated = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text="臣请改拨军械项目经费十万。",
        grant_action="项目经费",
        target_kind="army",
        target_id="guanning",
        amount=10,
        account="国库",
        target_candidate=str(first_id),
    )
    assert updated == first_id
    revised = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (first_id,),
    ).fetchone()["payload_json"])
    assert revised["grant_action"] == "项目经费"
    assert revised.get("purpose") in (None, "")
    assert not db._is_army_pay_grant_payload(revised)
    assert revised.get("execution_surface") != "immediate" or revised.get("purpose") != "补饷"


# ── ② 颁布缝一次消费：扣库+销欠同回合 ────────────────────────────





# ── ④ 协饷同规 + ADR 0023 clamp ──────────────────────────────────





def test_army_pay_forces_immediate_over_inherited_in_transit(game):
    """拨饷覆盖继承的 in_transit 默认；不得进月度在途对账轨。"""
    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 50)

    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨关宁军饷十万两。",
        target_kind="army",
        target_id="guanning",
        payload={
            "grant_action": "协饷",
            "purpose": "补饷",
            "amount": 10,
            "account": "国库",
            "target_kind": "army",
            "target_id": "guanning",
            # 模拟旧 pending / normalize 前置插入的在途默认
            "execution_surface": "in_transit",
        },
    )
    row = db.get_decree_dossier(dossier_id)
    payload = json.loads(row["payload_json"])
    assert payload["execution_surface"] == "immediate"

    _promulgate(db, state, content, dossier_id)
    closed = db.get_decree_dossier(dossier_id)
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "fulfilled"
    # 已结案的 immediate 不得出现在在途对账扫描面
    open_ids = {
        int(t["dossier_id"])
        for t in db.list_monthly_grant_reconciliation_targets()
    }
    assert dossier_id not in open_ids


# ── 负向：非拨饷不误落；extractor 单写者 ─────────────────────────



def test_army_target_non_pay_grant_does_not_clear_arrears(game):
    """army 对象的项目经费：可扣库，不得升格协饷销欠。"""
    grant_action = "项目经费"
    reply = "臣请户部发帑十万两作军械项目经费。"
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    # 显式 army 目标 + 非协饷 grant_action：不得因 army+金额+账户升格补饷。
    from ming_sim.action_materialize import stage_grant_allocation_candidate
    pending_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=reply,
        grant_action=grant_action,
        target_kind="army",
        target_id="guanning",
        amount=10,
        account="国库",
    )
    assert pending_id > 0
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("purpose") != "补饷"
    assert pending.get("grant_action") == grant_action
    assert not db._is_army_pay_grant_payload(pending)

    dossier = _close_night_dossier(db, state, content, pending_id)
    payload = json.loads(dossier["payload_json"])
    assert payload.get("purpose") != "补饷"
    assert not db._is_army_pay_grant_payload(payload)

    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves and int(moves[0]["delta"]) == -10
    assert moves[0].get("purpose") != "补饷"
    assert int(state.metrics["国库"]) == treasury_before - 10
    # 根因：不得因 army 目标误销欠饷
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])
    assert _army_row(db)["central_pay_arrears"] == pytest.approx(
        before["central_pay_arrears"]
    )










# ── ⑦ #1503 上游 carrier：显式拟旨前缀 → typed grant 单轨 ─────────────

def _scripted_xiexang_candidates(*, amount=15, account="国库", target_id="guanning"):
    return [assert_action_candidate_shape(
        {
            "kind": "grant_allocation",
            "grant_action": "协饷",
            "amount": amount,
            "account": account,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": target_id,
        },
    )]


@pytest.mark.parametrize("amount", [True, 15.9, "15"])
def test_xiexang_amount_rejects_non_json_integer(amount):
    from ming_sim.action_materialize import IncompleteXiexangPayloadError, require_explicit_xiexang_fields

    with pytest.raises(IncompleteXiexangPayloadError) as exc:
        require_explicit_xiexang_fields(
            amount=amount, account="国库", purpose="补饷",
            target_kind="army", target_id="guanning",
        )
    assert "amount" in exc.value.missing_fields


def test_manual_directive_admission_real_http_tracer_1591(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """#1591/#1769 真实入口 tracer：同一 WebGame/TestClient 内证外部行为。

    ① `POST /api/directives` 手工拟旨 account=太仓 经 capture 透传五字段后 canonical 为国库。
    ②–③ 非法 cadence/account/地域在写入前 409，相关表零写。
    ④ #1769 替代旧 #1591 整月阻断：既存非法草案在 issue/stream 边界拒因留痕、
    draft 留到下月、月份照常推进；确定性诊断不透传引擎拒因串。

    stub 仅 LLM payload 产出边界（拟旨抽取/结算外层）；不 mock
    ensure_dossiers_for_draft_directives / list_dossiered_draft_directives /
    preview_pending_directives / list_pending_actions / resolve_turn。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state, _post_issue_stream, _stub_outer_llm_seams, _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes

    raw_captures = [
        {
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            # #1620：展示名入 capture；admission 须 canonicalize → guanning
            "目标": "关宁军",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "太仓",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
        {
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            "目标": "guanning",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "国库",
            "拨付节奏": "每季",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
        {
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            "目标": "guanning",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "藩库",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
        {
            # #1620：theater/地域散文不得模糊升格为真实军队
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            "目标": "辽东",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "国库",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
        {
            # #1769 ④ 第一次重写仍坏账户 → 继续第二次重写
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            "目标": "guanning",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "藩库",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
        {
            # #1769 ④ 第二次重写仍坏 → 耗尽留 draft（总计 3=原抽+重写2）
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "恩赏拨帑": "协饷",
            "用途": "补饷",
            "目标类型": "army",
            "目标": "guanning",
            "颁布方式": "ordinary",
            "金额": 15,
            "账户": "藩库",
            "执行面": "immediate",
            "承办人": "",
            "参与人": [],
            "施行范围": "无",
            "期限月数": None,
            "目标案卷ID": None,
            "entries": [],
        },
    ]

    def fake_backend(*_a, **_k):
        return json.dumps(raw_captures.pop(0), ensure_ascii=False), {}

    real_capture = cb.capture_manual_directive_payload
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)
    monkeypatch.setattr(cb, "capture_manual_directive_payload", real_capture)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        if getattr(game.session, "llm_config", None) is not None:
            try:
                game.session.llm_config.channel = "cli"
            except Exception:
                pass

        client = TestClient(web_app.app)

        # ── ① 手工拟旨太仓→国库：原票 POST /api/directives 入口 ──
        turn1 = int(game.state.turn)
        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics["国库"]), 100)
        arrears_before = _army_row(game.db)["arrears"]
        logs_before = game.db.conn.execute(
            "SELECT COUNT(*) FROM army_logs WHERE army_id='guanning'"
        ).fetchone()[0]
        ledger_before_id = game.db.conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM economy_ledger"
        ).fetchone()[0]
        directive_ok = client.post(
            "/api/directives",
            json={"text": "准从太仓见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert directive_ok.status_code == 200, directive_ok.text
        wait_pending_writes(game)
        # #1620：POST 后、结算前——首次承重 payload 已是 canonical guanning
        draft_row = game.db.conn.execute(
            "SELECT dossier_payload_json FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert draft_row is not None
        draft_payload = json.loads(str(draft_row["dossier_payload_json"] or "{}"))
        assert draft_payload.get("target_id") == "guanning"
        _post_issue_stream(client, expected_turn=turn1, step="1591①太仓 issue/stream")
        after = _get_state(client)
        assert _turn_of(after) == turn1 + 1, after.get("turn")
        dossier = next(
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
        )
        payload = json.loads(dossier["payload_json"])
        assert {
            key: payload.get(key)
            for key in (
                "grant_action", "purpose", "amount", "account",
                "target_kind", "target_id", "execution_surface",
            )
        } == {
            "grant_action": "协饷", "purpose": "补饷", "amount": 15,
            "account": "国库", "target_kind": "army", "target_id": "guanning",
            "execution_surface": "immediate",
        }
        moves = [
            move for move in game.db.list_economy_moves_for_dossier(dossier["id"])
            if move.get("purpose") == "补饷"
        ]
        assert len(moves) == 1
        assert int(moves[0]["delta"]) == -15
        dossier_logs = list(game.db.conn.execute(
            "SELECT delta FROM army_logs WHERE army_id='guanning' AND field='arrears' "
            "AND origin_ref=?", (f"dossier:{dossier['id']}",),
        ).fetchall())
        assert len(dossier_logs) == 1
        assert float(dossier_logs[0]["delta"]) == pytest.approx(-15)
        tick_delta = sum(float(row["delta"] or 0) for row in game.db.conn.execute(
            "SELECT delta FROM army_logs WHERE army_id='guanning' AND field='arrears' "
            "AND turn=? AND (origin_ref IS NULL OR origin_ref='')", (turn1,),
        ).fetchall())
        assert _army_row(game.db)["arrears"] == pytest.approx(
            arrears_before - 15 + tick_delta
        )
        assert game.db.conn.execute(
            "SELECT COUNT(*) FROM army_logs WHERE army_id='guanning'"
        ).fetchone()[0] >= logs_before + 1
        dossier_ledger = list(game.db.conn.execute(
            "SELECT delta FROM economy_ledger WHERE id>? AND account='国库' AND origin_ref=?",
            (ledger_before_id, f"dossier:{dossier['id']}"),
        ).fetchall())
        assert [int(row["delta"]) for row in dossier_ledger] == [-15]

        # ── ② manual capture 须在写入前拒绝非法 cadence ──
        turn2 = int(game.state.turn)
        invalid_cadence = client.post(
            "/api/directives",
            json={"text": "准每季拨关宁军饷十五万两。", "notes": ""},
        )
        assert invalid_cadence.status_code == 409, invalid_cadence.text
        assert int(game.state.turn) == turn2

        # ── ③ account 是唯一坏因；HTTP 409 后所有相关表零写 ──
        counts_before = {
            table: game.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("turn_directives", "pending_actions", "decree_dossiers", "economy_ledger", "army_logs")
        }
        invalid_account = client.post(
            "/api/directives",
            json={"text": "准从藩库见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert invalid_account.status_code == 409, invalid_account.text
        assert int(game.state.turn) == turn2
        assert {
            table: game.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in counts_before
        } == counts_before

        # ── ③b #1620：地域「辽东」不得升格 guanning；相关表零写 ──
        treasury_before = int(game.state.metrics.get("国库") or 0)
        arrears_now = float(_army_row(game.db)["arrears"])
        region_reject = client.post(
            "/api/directives",
            json={"text": "准从国库见银拨辽东军饷十五万两即发。", "notes": ""},
        )
        assert region_reject.status_code == 409, region_reject.text
        assert int(game.state.turn) == turn2
        assert {
            table: game.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in counts_before
        } == counts_before
        assert int(game.state.metrics.get("国库") or 0) == treasury_before
        assert float(_army_row(game.db)["arrears"]) == pytest.approx(arrears_now)

        # ── ④ #1769 替代 #1591「产物错即整月不推进」：既存非法草案 → 月照过。
        # 票面完整耗尽（第二次仍坏产物、下月 list、诊断不透传）见
        # tests/test_draft_admission_resubmit_1769.py；此处只改旧整月阻断契约所需最小断言。
        # 删除旧断言：HTTP 400 + message==引擎拒因 + 拒案不得推进回合。
        directive_id = game.db.add_directive(
            game.state, None, "准从藩库见银拨关宁军饷十五万两即发。",
            "player", status="draft", dossier_payload={
                "dossier_action_type": "grant_allocation", "grant_action": "协饷",
                "purpose": "补饷", "target_kind": "army", "target_id": "guanning",
                "mode": "ordinary", "amount": 15, "account": "藩库",
            },
        )

        game.db.stage_pending_action(
            turn2, kind="office", action="任命", minister_name=name,
            payload={"text": "测试任免原文",
                "name": name, "office": "经略关宁", "_office_action": "任命",
                "region_id": "liaodong",
            },
        )
        assert game.db.list_pending_actions(turn2), "无关非旨 pending action 应在场"

        _post_issue_stream(client, expected_turn=turn2, step="1769 replace-1591 month")
        after = _get_state(client)
        assert _turn_of(after) == turn2 + 1, after.get("turn")
        assert game.db.conn.execute(
            "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
        ).fetchone()["status"] == "draft"
        # 真实拒因留痕、不误报无草案（#1591 保留面）
        rejection_rows = game.db.conn.execute(
            "SELECT category, source FROM rejection_reports "
            "WHERE section = 'directive_locality' "
            "AND json_extract(item_json, '$.directive_id') = ?",
            (directive_id,),
        ).fetchall()
        assert rejection_rows
        assert any(r["category"] == "locality_fanout_failed" for r in rejection_rows)
        assert any(r["source"] == "player_decree" for r in rejection_rows)
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_non_xiexang_payload_cannot_smuggle_army_pay_purpose(game):
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    ledger_before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger"
    ).fetchone()[0]
    pending_id = db.stage_directive_candidate(state.turn, actor, payload={
        "text": "拨关宁军械项目经费十万两。",
        "actor": actor,
        "dossier_action_type": "grant_allocation",
        "grant_action": "项目经费",
        "target_kind": "army",
        "target_id": "guanning",
        "amount": 10,
        "account": "国库",
        "purpose": "补饷",
        "mode": "ordinary",
    })

    db.commit_pending_actions(state, content=content, action_ids=[pending_id])

    assert not any(
        row["pending_action_id"] == pending_id for row in db.list_decree_dossiers()
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger"
    ).fetchone()[0] == ledger_before
    assert _army_row(db) == before


def test_plain_scene_commission_does_not_create_army_pay(game):
    """纯正文交办不凭补饷措辞制造拨饷载荷；颁布后亦不误落军饷。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    seed = "臣遵旨，着户部清核辽饷。钦此。"
    out = dispatch_declaration(db, state, {"commissions": [{
        "text": seed,
    }]}, minister_name=actor)
    assert out.commissions.rejected == []
    pending_id = out.commissions.applied[0]["id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("dossier_action_type") == "special_decree"
    assert pending.get("text") == seed
    assert pending.get("purpose") != "补饷"

    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    dossier = _close_night_dossier(db, state, content, pending_id)
    _promulgate(db, state, content, dossier["id"])
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert all(m.get("purpose") != "补饷" for m in moves)
    pay_ledger = [
        dict(r) for r in db.conn.execute(
            """
            SELECT purpose, origin_ref FROM economy_ledger
            WHERE purpose='补饷' AND origin_ref=?
            """,
            (f"dossier:{dossier['id']}",),
        ).fetchall()
    ]
    assert pay_ledger == []
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])






def test_scene_grant_force_promulgation_consumes_one_dossier(game, monkeypatch):
    """一份拨饷声明只建一案；封驳后强颁只拨款一次。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration
    import ming_sim.decree as decree_mod

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "敕户部发太仓银十五万两协济关宁军前。",
        "grant": {"grant_action": "协饷", "amount": 15, "account": "太仓",
                  "purpose": "补饷", "target_kind": "army", "target_id": "guanning"},
    }]})
    dispatched = dispatch_declaration(db, state, declaration, minister_name=actor)
    assert dispatched.commissions.rejected == []
    rows = list(db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 1
    pending_id = int(rows[0]["id"])
    pending = json.loads(rows[0]["payload_json"])
    assert pending["dossier_action_type"] == "grant_allocation"
    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["mode"] == "ordinary"

    import ming_sim.month_chain as month_chain
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], dossier["decree_text"],
        content=content,
    )
    assert result.advanced is False
    assert not any(
        row.get("event_id") == f"dossier:{dossier['id']}"
        for row in result.decisions
    )

    db.apply_dossier_verdicts(
        state, [_rejected_verdict(dossier["id"])], content=content,
    )
    treasury_before = int(state.metrics["国库"])
    arrears_before = _army_row(db)
    _promulgate(db, state, content, dossier["id"], "force_promulgated")
    moves = [
        move for move in db.list_economy_moves_for_dossier(dossier["id"])
        if move.get("purpose") == "补饷" and move.get("target_id") == "guanning"
    ]
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -15
    assert int(state.metrics["国库"]) == treasury_before - 15
    after = _army_row(db)
    assert after["arrears"] == pytest.approx(float(arrears_before["arrears"]) - 15)
    assert after["central_pay_arrears"] == pytest.approx(
        float(arrears_before["central_pay_arrears"]) - 15
    )


def test_scene_grant_and_punishment_stage_independent_pending(game):
    """场景一轮两件独立交办：拨饷与罚俸都各自暂存。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != actor and str(getattr(ch, "office", "") or "").strip()
    )
    declaration = normalize_audience_declaration({"commissions": [
        {"text": "敕户部发太仓银十五万两协济关宁军前。", "grant": {
            "grant_action": "协饷", "amount": 15, "account": "太仓",
            "purpose": "补饷", "target_kind": "army", "target_id": "guanning",
        }},
        {"text": f"着罚{target.name}俸示惩。", "punishment": {
            "punish_action": "罚俸", "target_id": target.name, "amount": 120,
        }},
    ]})
    result = dispatch_declaration(db, state, declaration, minister_name=actor)
    assert result.commissions.rejected == []
    rows = list(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 2
    types = {json.loads(row["payload_json"]).get("dossier_action_type") for row in rows}
    assert types == {"grant_allocation", "punishment"}


def test_scene_grant_and_assignment_two_durable_dossiers(game):
    """一轮两道独立交办：拨饷与责成各自暂存、各自成案。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    declaration = normalize_audience_declaration({"commissions": [
        {"text": "敕户部发太仓银十五万两协济关宁军前。", "grant": {
            "grant_action": "协饷", "amount": 15, "account": "太仓",
            "purpose": "补饷", "target_kind": "army", "target_id": "guanning",
        }},
        {"text": "着户部清查辽饷收支。", "assignment": {
            "title": "清查辽饷收支", "target_id": "hubu", "assignee": actor,
            "participant_roster": [{"character_id": actor, "tier": "主办"}],
            "transaction_category": "钱粮", "commitment_kind": "无",
        }},
    ]})
    result = dispatch_declaration(db, state, declaration, minister_name=actor)
    assert result.commissions.rejected == []
    rows = list(db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 2
    payloads = [json.loads(row["payload_json"]) for row in rows]
    grant = next(p for p in payloads if p.get("dossier_action_type") == "grant_allocation")
    assert {key: grant.get(key) for key in (
        "grant_action", "purpose", "amount", "account", "target_kind", "target_id",
    )} == {
        "grant_action": "协饷", "purpose": "补饷", "amount": 15,
        "account": "国库", "target_kind": "army", "target_id": "guanning",
    }
    assignment = next(p for p in payloads if p.get("dossier_action_type") == "assignment")
    assert assignment["title"] == "清查辽饷收支"
    assert assignment["target_id"] == "hubu"
    assert assignment["transaction_category"] == "钱粮"

    ids = {int(row["id"]) for row in rows}
    db.commit_pending_actions(state, content=content, action_ids=list(ids))
    dossiers = [
        d for d in db.list_decree_dossiers() if int(d["pending_action_id"] or 0) in ids
    ]
    assert len(dossiers) == 2
    assert {d["action_type"] for d in dossiers} == {"grant_allocation", "assignment"}






@pytest.mark.parametrize(
    "validation_case",
    ["incomplete_xiexang", "region_mismatch", "existing_draft_region_mismatch"],
)
def test_http_chat_stream_exposes_typed_decree_validation_recovery(
    tmp_path, monkeypatch, _offline_scene_beat_generator, validation_case,
):
    """#1842：殿上坏拨帑经转译拒收当事实；不经旧 classifier / sync recovery SSE。

    incomplete → commissions invalid_enum（缺 amount/account/target_id）；
    region* → 幻影军 target：协饷 canonicalize 抛 DecreeMaterializationValidationError
    → 分派归 invalid_enum（非 KeyError/hallucinated_id）；
    existing_draft 案：既有 pending 不变。ctid>0 后台转译，等 rejection_reports。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_audience_background import RunContent, RunOutput
    from tests.test_menu_continue_stream_1195 import _parse_sse
    from tests.test_month_loop_tracer_1468 import _stub_outer_llm_seams
    from tests.test_session_write_queue_1353 import wait_pending_writes

    class _AudienceAgent:
        def run(self, *_args, **_kwargs):
            return iter((RunContent("臣已奉旨查议。"), RunOutput([])))

        def get_last_run_output(self):
            return None

    # cli_backend resolves its default trace path at import time; isolate the
    # real composer path explicitly so this tracer leaves no repository probe.
    monkeypatch.setattr(cb, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        stub_scene_agent(monkeypatch, _AudienceAgent())
        if game.session.llm_config is not None:
            game.session.llm_config.channel = "cli"
        if validation_case == "existing_draft_region_mismatch":
            game.db.stage_directive_candidate(game.state.turn, name, payload={
                "text": "整饬京师。", "actor": name,
                "dossier_action_type": "special_decree",
                "target_kind": "policy", "target_id": "整饬京师",
            })
        pending_before = [row["id"] for row in game.db.list_pending_actions(game.state.turn)]
        dossiers_before = [row["id"] for row in game.db.list_decree_dossiers()]

        if validation_case == "incomplete_xiexang":
            commission = {
                "text": "拟旨如下：整饬京师",
                "grant": {
                    "grant_action": "协饷",
                    "amount": 0, "account": "", "purpose": "补饷",
                    "target_kind": "army", "target_id": "",
                },
            }
            expected_category = "invalid_enum"
            message = "拟旨如下：整饬京师"
        else:
            # 旧 draft region_id/target_id 组合形已退役；幻影军走协饷权威缝 → invalid_enum。
            commission = {
                "text": "请拟旨整饬京师",
                "grant": {
                    "grant_action": "协饷",
                    "amount": 15, "account": "国库", "purpose": "补饷",
                    "target_kind": "army", "target_id": "no_such_army_1774",
                },
            }
            expected_category = "invalid_enum"
            message = "请拟旨整饬京师"

        stub_audience_translate(
            monkeypatch,
            lambda prompt, cfg: {
                **offline_empty_audience_translate(prompt, cfg),
                "commissions": [commission],
                "promises": [],
            },
        )

        response = TestClient(web_app.app).post(
            f"/api/ministers/{name}/chat/stream",
            json={"message": message},
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert all(event != "error" for event, _payload in events)
        assert any(event == "done" for event, _payload in events)

        turn = int(game.state.turn)

        def _ledger():
            # rejection_reports 由 flush 懒建表；后台转译尚未 flush 时表可能不存在，
            # 视作尚未就绪（禁把建表竞态当失败，也禁放松最终断言）。
            try:
                return game.db.conn.execute(
                    "SELECT item_json, reason, category, source FROM rejection_reports "
                    "WHERE turn=? AND section='commissions'",
                    (turn,),
                ).fetchall()
            except Exception as exc:  # noqa: BLE001 — sqlite DatabaseError/OperationalError
                msg = str(exc).lower()
                if "no such table" in msg and "rejection_reports" in msg:
                    return []
                raise

        game._runtime_write_queue().barrier(lambda: None)
        assert _ledger()
        assert [row["id"] for row in game.db.list_pending_actions(turn)] == pending_before
        assert [row["id"] for row in game.db.list_decree_dossiers()] == dossiers_before
        ledger = _ledger()
        assert all(row["category"] == expected_category for row in ledger), ledger
        assert all(row["reason"] for row in ledger)
        items = [json.loads(row["item_json"]) for row in ledger]
        assert all(isinstance(item, dict) and item for item in items)
        if validation_case == "incomplete_xiexang":
            assert any(
                (item.get("grant") or {}).get("grant_action") == "协饷"
                for item in items
            )
        else:
            assert any(
                (item.get("grant") or {}).get("target_id") == "no_such_army_1774"
                for item in items
            )
    finally:
        wait_pending_writes(game)
        if game.session:
            game.session.close()


def test_http_chat_issue_stream_pay_decree_keeps_month_unadvanced(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """原轨真 HTTP：召对户部拨饷并请求 issue/stream；本链路不推进月份。

    stub 仅 LLM 边界；不得用 store helper 代替收夜/颁布 HTTP 链。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state,
        _post_issue_stream,
        _stub_outer_llm_seams,
        _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes

    class _TwoRoundHubuAgent:
        """#1503 独有：召对请拨 + 准后遵旨两轮户部回话。"""

        def __init__(self):
            self._calls = 0

        def run(self, *_a, **kwargs):
            from tests.test_audience_background import RunContent, RunOutput

            self._calls += 1
            if self._calls == 1:
                content = "臣请户部发帑十五万两协济关宁军前，请陛下定夺准驳。"
            else:
                content = "臣遵旨。敕户部发太仓银十五万两协济关宁军前。钦此。"
            if kwargs.get("stream"):
                def chunks():
                    yield RunContent(content)
                    yield RunOutput([])
                return chunks()
            return SimpleNamespace(content=content, tools=[])

        def get_last_run_output(self):
            return None

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    # The first grant enters through audience night; the second is a season
    # decision whose selected server option is its legal origin.
    import ming_sim.decree as decree_mod
    decision_report = """本月邸报。
<<DECISION>>
{"title":"内帑济关宁","context":"关宁欠饷尚重，奏请圣裁","options":[{"label":"发内库银三十万两济关宁","hint":"军心稍定，内帑益绌","action_type":"grant_allocation","grant_action":"协饷","account":"内库","amount":30,"purpose":"补饷","target_kind":"army","target_id":"guanning","cadence":"一次性"},{"label":"暂缓内帑","hint":"内帑得保，边军仍困"}]}
<<END>>
<<DECISION>>
{"title":"国帑济关宁","context":"关宁欠饷尚重，奏请圣裁","options":[{"label":"发国库银三十万两济关宁","hint":"军心稍定，国库益绌","action_type":"grant_allocation","grant_action":"协饷","account":"国库","amount":30,"purpose":"补饷","target_kind":"army","target_id":"guanning","cadence":"一次性"},{"label":"暂缓国帑","hint":"国库得保，边军仍困"}]}
<<END>>"""
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (decision_report, k.get("simulator_payload") or {}),
    )

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        stub_scene_agent(monkeypatch, _TwoRoundHubuAgent())
        if getattr(game.session, "llm_config", None) is not None:
            try:
                game.session.llm_config.channel = "cli"
            except Exception:
                pass

        def _translate(prompt, _cfg):
            text = str(prompt or "")
            scene = offline_empty_audience_translate(prompt, _cfg)
            if "【本轮皇帝】准" in text:
                rows = [
                    r for r in game.db.list_pending_actions(game.state.turn)
                    if r.get("kind") == "directive" and r.get("status") == "pending"
                ]
                if not rows:
                    return scene
                return {
                    **scene,
                    "promises": [{"action_id": int(rows[0]["id"]), "decision": "应允"}],
                }
            return {
                **scene,
                "commissions": [{
                    "text": "敕户部发太仓银十五万两协济关宁军前。",
                    "grant": {
                        "grant_action": "协饷",
                        "amount": 15,
                        "account": "太仓",
                        "purpose": "补饷",
                        "target_kind": "army",
                        "target_id": "guanning",
                    },
                }],
            }

        stub_audience_translate(monkeypatch, _translate)

        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics["国库"]), 100)
        game.db.save_state(game.state)
        treasury_before = int(game.state.metrics["国库"])
        arrears_before = _army_row(game.db)
        turn_before = int(game.state.turn)

        client = TestClient(web_app.app)
        petition = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "拨关宁军饷十五万两。"},
        )
        assert petition.status_code == 200, petition.text
        # #1842：ctid>0 转译后台；前台 pending_action_id 可仍为 0——join 后读表。
        game._runtime_write_queue().barrier(lambda: None)
        wait_pending_writes(game)
        staged = [
            r for r in game.db.list_pending_actions(turn_before)
            if r.get("kind") == "directive" and r.get("status") == "pending"
        ]
        assert len(staged) == 1, staged
        pending_id = int(staged[0]["id"])
        assert pending_id > 0
        assert int(game.state.metrics["国库"]) == treasury_before
        assert _army_row(game.db)["arrears"] == pytest.approx(arrears_before["arrears"])
        from ming_sim.audience_night import get_open_night
        night = get_open_night(game.db)
        assert night is not None
        approved_ids = {
            int(row["id"])
            for row in game.db.list_night_approved_pending(int(night["id"]))
        }
        assert pending_id not in approved_ids

        confirm = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "准"},
        )
        assert confirm.status_code == 200, confirm.text
        game._runtime_write_queue().barrier(lambda: None)
        wait_pending_writes(game)
        assert int(game.state.metrics["国库"]) == treasury_before
        assert _army_row(game.db)["arrears"] == pytest.approx(arrears_before["arrears"])
        night = get_open_night(game.db)
        assert night is not None
        approved_ids = {
            int(row["id"])
            for row in game.db.list_night_approved_pending(int(night["id"]))
        }
        assert pending_id in approved_ids

        body = _post_issue_stream(
            client, expected_turn=turn_before, step="1503 issue/stream",
        )
        if body.get("awaiting_decision"):
            decisions = body.get("decisions") or []
            assert len(decisions) == 2, body
            decisions_by_account = {
                decision["options"][0]["account"]: decision
                for decision in decisions
            }
            assert set(decisions_by_account) == {"内库", "国库"}
            resolved = client.post(
                "/api/decree/resolve_decisions/stream",
                json={"choices": [
                    {
                        "decision_key": decision["decision_key"],
                        "label": decision["options"][0]["label"],
                    }
                    for decision in decisions_by_account.values()
                ]},
            )
            assert resolved.status_code == 200, resolved.text
            assert "event: error" not in resolved.text, resolved.text
            assert "event: done" in resolved.text, resolved.text
        wait_pending_writes(game)

        after = _get_state(client)
        assert _turn_of(after) == turn_before + 1, after.get("turn")
        assert not body.get("awaiting_decision")

        dossiers = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
            and d["target_id"] == "guanning"
        ]
        dossier = next(d for d in dossiers if d["pending_action_id"] == pending_id)
        moves = game.db.list_economy_moves_for_dossier(dossier["id"])
        pay_moves = [
            m for m in moves
            if m.get("purpose") == "补饷" and m.get("target_id") == "guanning"
        ]
        assert len(pay_moves) == 1, moves
        assert int(pay_moves[0]["delta"]) == -15
        assert pay_moves[0]["account"] == "国库"
        ledger = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT account, delta, purpose, origin_ref FROM economy_ledger
                WHERE purpose='补饷' AND target_id='guanning' AND origin_ref=?
                """,
                (f"dossier:{dossier['id']}",),
            ).fetchall()
        ]
        assert len(ledger) == 1
        assert int(ledger[0]["delta"]) == -15
        assert ledger[0]["account"] == "国库"
        logs = [
            dict(row) for row in game.db.conn.execute(
                """
                SELECT * FROM army_logs
                WHERE army_id='guanning' AND field='arrears' AND origin_ref=?
                ORDER BY id DESC
                """,
                (f"dossier:{dossier['id']}",),
            ).fetchall()
        ]
        assert len(logs) == 1
        assert float(logs[0]["delta"]) == pytest.approx(-15)

    finally:
        try:
            game.session.close()
        except Exception:
            pass


def _pending_rows(db, turn):
    return [
        {
            "id": int(row["id"]),
            "kind": row["kind"],
            "action": row["action"],
            "payload_json": row["payload_json"],
            "status": row["status"],
        }
        for row in db.list_pending_actions(int(turn))
    ]


def _bad_sibling_candidate(*, kind: str) -> dict:
    """Typed-failing sibling shared by create/update/delete/tail batch cases."""
    if kind == "grant_allocation":
        return {
            "kind": "grant_allocation", "grant_action": "协饷",
            "amount": 10, "account": "国库", "purpose": "补饷",
            "target_kind": "army", "target_id": "not_an_army", "cadence": "一次性",
        }
    return {
        "kind": "draft", "draft_action": "拟旨", "grant_action": "协饷",
        "amount": 10, "account": "国库", "purpose": "补饷",
        "target_kind": "army", "target_id": "not_an_army", "cadence": "一次性",
    }


def _office_summon_ledger(db, pending_id):
    """Structured inactive office summon row (undo pin included)."""
    row = db.conn.execute(
        "SELECT id, origin_ref, origin_chat_turn_id, night_id, person_names, tags "
        "FROM story_ledger_entries WHERE origin_ref=? LIMIT 1",
        (f"office:{int(pending_id)}",),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "origin_ref": str(row["origin_ref"] or ""),
        "origin_chat_turn_id": int(row["origin_chat_turn_id"] or 0),
        "night_id": int(row["night_id"] or 0),
        "person_names": json.loads(row["person_names"] or "[]"),
        "tags": json.loads(row["tags"] or "[]"),
    }


def _story_ledger_ids(db):
    return [
        int(row["id"])
        for row in db.conn.execute(
            "SELECT id FROM story_ledger_entries ORDER BY id"
        ).fetchall()
    ]


def _path_nature_ledger_rows(db, pending_id):
    """Structured 特旨/署理 path-nature story rows tagged pending:<id>."""
    pin = f"pending:{int(pending_id)}"
    out = []
    for row in db.conn.execute(
        "SELECT id, tags, origin_ref FROM story_ledger_entries ORDER BY id"
    ).fetchall():
        tags = json.loads(row["tags"] or "[]")
        if pin in tags and ("特旨" in tags or "署理" in tags):
            out.append({
                "id": int(row["id"]),
                "tags": tags,
                "origin_ref": str(row["origin_ref"] or ""),
            })
    return out
