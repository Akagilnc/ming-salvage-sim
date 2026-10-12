from ming_sim.entities.issue.tracker import apply_issue_tracker_output
from ming_sim.applier import Provenance
import json
from pathlib import Path
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section, view




def _promulgated_commitment_origin(db, state, token: str) -> str:
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"测试承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _issue_by_title(db, title: str):
    return db.conn.execute("SELECT * FROM issues WHERE title=?", (title,)).fetchone()


def test_until_stop_commitment_issue_is_created_with_carrier_fields(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    stop_condition = {"army.guanning.arrears": "<=0"}

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'pay-guanning-arrears'), 'kind': 'initiative', 'title': '每月补关宁军饷直到补齐', 'bar_value': 20, 'stage_text': '户部按月拨银补关宁旧欠', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'category': '补饷承诺', 'reason': '每月补关宁欠饷', 'purpose': '补饷', 'target_kind': 'army', 'target_id': 'guanning'}]}, 'stop_condition': stop_condition, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    created = out.issue.new_issues[0]
    row = _issue_by_title(db, "每月补关宁军饷直到补齐")
    assert row is not None
    assert row["origin_kind"] == "decree"
    assert row["origin_ref"].startswith("dossier:")
    assert db.dossiers.authorizes_effects(int(row["origin_ref"].split(":", 1)[1]))
    assert row["kind"] == "initiative"
    assert row["commitment_kind"] == "until_stop"
    assert row["inertia"] == 0
    assert row["cancellable"] == "decree"
    assert json.loads(row["ongoing_effects"])["economy"][0]["target_id"] == "guanning"
    assert json.loads(row["stop_condition"]) == stop_condition
    assert json.loads(row["effect_on_resolve"]) == {}




def test_decree_commitment_does_not_dedup_same_name_income_fiscal_create(game, monkeypatch):
    """同账户、同名但 direction=income 的新科目与月度【支出】承诺载体无关，照常落账。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'xixue-monthly'), 'kind': 'initiative', 'title': '每月拨西学经费', 'stage_text': '太仓每月拨银五十万两办西学。', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'category': '西学经费', 'reason': '每月拨西学经费'}]}, 'commitment_kind': 'until_stop'}], 'fiscal_creates': [{'key': '西学经费_base', 'account': '国库', 'direction': 'income', 'init_value': 50, 'display': '西学经费', 'reason': '新设西学专项捐输（收入）', 'origin_ref': '盘面自发'}]}, SettlementContext(content=content))

    assert section(out, "fiscal_creates").rejected == []
    fiscal_result = view(out, "fiscal_creates")[0]
    assert fiscal_result["key"]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key IN ('西学经费_base', '西学经费_rate')"
    ).fetchone()[0] >= 1






def test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn(read_game, monkeypatch):
    db, state, content = read_game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': 'decree:turn-1:current-turn-expired-pay', 'kind': 'initiative', 'title': '本回合即到期的每月补饷承诺', 'stage_text': '户部按月拨银补饷，但 end_turn 错落在当前回合。', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'category': '补饷承诺', 'reason': '每月补饷', 'purpose': '补饷'}]}, 'end_turn': state.turn, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    rejected = section(out, "issue_summary").rejected[0]
    assert rejected.category == "invalid_enum"
    assert _issue_by_title(db, "本回合即到期的每月补饷承诺") is None


def test_future_one_shot_commitment_issue_is_created_with_deadline_only(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'sunchengzong-review'), 'kind': 'initiative', 'title': '三月后复试孙承宗', 'stage_text': '孙承宗暂听候政，三月后复试军国大计。', 'end_turn': state.turn + 3, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    created = out.issue.new_issues[0]
    row = _issue_by_title(db, "三月后复试孙承宗")
    assert row is not None
    assert row["commitment_kind"] == "until_stop"
    assert row["end_turn"] == state.turn + 3
    assert row["stop_condition"] == ""
    assert json.loads(row["ongoing_effects"]) == {}
    assert row["inertia"] == 0
    assert row["cancellable"] == "decree"


def test_open_ended_ongoing_commitment_issue_is_created_with_explicit_marker(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'open-ended-appeasement'), 'kind': 'initiative', 'title': '长期安抚毛文龙', 'stage_text': '遣臣常驻皮岛安抚，未设硬时限。', 'ongoing_effects': {'metrics': {'皇威': -1}}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    created = out.issue.new_issues[0]
    row = _issue_by_title(db, "长期安抚毛文龙")
    assert row is not None
    assert row["commitment_kind"] == "until_stop"
    assert row["end_turn"] == 0
    assert row["stop_condition"] == ""
    assert json.loads(row["ongoing_effects"]) == {"metrics": {"皇威": -1}}
    assert row["cancellable"] == "decree"


def test_until_stop_commitment_supports_character_loyalty_condition(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'appease-mao'), 'kind': 'initiative', 'title': '安抚毛文龙直到效顺', 'stage_text': '遣臣赴皮岛安抚', 'ongoing_effects': {'metrics': {'皇威': -1}}, 'stop_condition': {'character.毛文龙.loyalty': '>=65'}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    row = _issue_by_title(db, "安抚毛文龙直到效顺")
    assert row["commitment_kind"] == "until_stop"
    assert json.loads(row["stop_condition"]) == {"character.毛文龙.loyalty": ">=65"}


def test_until_stop_commitment_rejects_direct_resolved_close(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'pay-liao-close-guard'), 'kind': 'initiative', 'title': '每月补辽饷直到补齐防误结案', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'reason': '每月补饷'}]}, 'stop_condition': {'army.guanning.arrears': '<=0'}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))
    row = _issue_by_title(db, "每月补辽饷直到补齐防误结案")

    out = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": row["id"], "reason": "resolved", "narrative": "误按承诺完成结案"}]},
    source=Provenance.system_simulation)

    assert out.closes == []
    close = out.rejected[0]
    assert close.category == "invalid_enum"
    after = db.conn.execute("SELECT status FROM issues WHERE id=?", (row["id"],)).fetchone()
    assert after["status"] == "active"


def test_until_stop_commitment_rejects_direct_failed_close_without_effects(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    starting_popular_support = int(state.metrics["民心"])

    settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'pay-liao-fail-guard'), 'kind': 'initiative', 'title': '每月补辽饷直到补齐防失败误结案', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'reason': '每月补饷'}]}, 'effect_on_fail': {'metrics': {'民心': -7}}, 'stop_condition': {'army.guanning.arrears': '<=0'}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))
    row = _issue_by_title(db, "每月补辽饷直到补齐防失败误结案")

    out = apply_issue_tracker_output(
        db,
        state,
        {"close_issues": [{"issue_id": row["id"], "reason": "failed", "narrative": "误按承诺失败结案"}]},
    source=Provenance.system_simulation)

    assert out.closes == []
    close = out.rejected[0]
    assert close.category == "invalid_enum"
    after = db.conn.execute("SELECT status FROM issues WHERE id=?", (row["id"],)).fetchone()
    assert after["status"] == "active"
    assert int(state.metrics["民心"]) == starting_popular_support
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issue_advances WHERE issue_id=? AND trigger_kind='close'",
        (row["id"],),
    ).fetchone()[0] == 0


def test_until_stop_commitment_advance_to_full_stays_active(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'pay-liao-advance-guard'), 'kind': 'initiative', 'title': '每月补辽饷直到补齐防推进误结案', 'bar_value': 90, 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'reason': '每月补饷'}]}, 'stop_condition': {'army.guanning.arrears': '<=0'}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))
    row = _issue_by_title(db, "每月补辽饷直到补齐防推进误结案")

    advanced = db.advance_issue(
        state,
        row["id"],
        trigger_kind="decree",
        delta_bar=20,
        narrative="承诺履行有进展，但停止条件尚未由专门闭环判定。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "active"
    assert advanced["closed_turn"] is None


def test_stop_condition_without_commitment_kind_advance_to_full_stays_active(game):
    """insert_issue 可直接持久化 stop_condition；即便 commitment_kind 为空，
    advance_issue 也不能仅因 bar_value 到 100 自动 resolved，必须等停止条件闭环判定。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="直接插入停止条件防推进误结案",
        origin_kind="decree",
        origin_ref="decree:turn-1:direct-stop",
        bar_value=90,
        stop_condition={"army.guanning.arrears": "<=0"},
    )

    advanced = db.advance_issue(
        state,
        issue_id,
        trigger_kind="decree",
        delta_bar=20,
        narrative="进度满值，但停止条件尚未由专门闭环判定。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "active"
    assert advanced["closed_turn"] is None


def test_empty_json_stop_condition_allows_advance_to_resolved(game):
    """stop_condition 里若只是带空白的空 JSON 对象，不应被误判为承诺停止条件。"""
    db, state, _content = game
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="空停止条件不阻止结案",
        origin_kind="decree",
        origin_ref="decree:turn-1:empty-stop",
        bar_value=90,
        stop_condition=" { } ",
    )

    advanced = db.advance_issue(
        state,
        issue_id,
        trigger_kind="decree",
        delta_bar=20,
        narrative="进度满值且没有真实停止条件。",
    )

    assert advanced["bar_value"] == 100
    assert advanced["status"] == "resolved"
    assert advanced["closed_turn"] == state.turn




def test_one_shot_appeasement_economy_move_does_not_create_commitment_issue(game, monkeypatch):
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    before = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]

    out = settle_delta(state, db, {'economy_moves': [{'account': '内库', 'delta': -20, 'category': '一次性赏赐', 'reason': '赏毛文龙银二十万安其心', 'origin_ref': '盘面自发'}]}, SettlementContext(content=content))

    assert view(out, "economy_moves")[0]["delta"] == -20
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before

def test_decree_commitment_same_account_alias_miss_still_lands_fiscal_create(game, monkeypatch):
    """同批、同账户、有 decree 承诺却**异名**未匹配上的 fiscal_create 照常落账（不被拒）。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'xixue-monthly'), 'kind': 'initiative', 'title': '每月拨西学经费', 'stage_text': '太仓每月拨银五十万两办西学。', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'category': '西学经费', 'reason': '每月拨西学经费'}]}, 'commitment_kind': 'until_stop'}], 'fiscal_creates': [{'key': 'xuguangqi_gongfei_base', 'account': '国库', 'direction': 'expense', 'init_value': 50, 'display': '徐光启三务公费', 'reason': '月支', 'origin_ref': '盘面自发'}]}, SettlementContext(content=content))

    # 异名 → 未去重，fiscal_create 照常落账（不被拒）。日志措辞非契约，不锁。
    assert section(out, "fiscal_creates").rejected == []
    assert view(out, "fiscal_creates")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key IN "
        "('xuguangqi_gongfei_base', 'xuguangqi_gongfei_rate')"
    ).fetchone()[0] >= 1


def test_resolve_condition_loyalty_expression_is_ordinary_initiative(game, monkeypatch):
    """resolve_condition 忠诚表达式不再被旧表示识别为承诺形态（#1835 J17）。

    无 commitment_kind 时按普通 initiative 落库；停止条件只认 typed commitment_kind/stop_condition。
    """
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    origin = _promulgated_commitment_origin(db, state, "ordinary-loyalty-resolve")
    # 仅 resolve_condition 忠诚表达式：不得再被旧表示认成承诺形态而索 commitment_kind
    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': origin, 'kind': 'initiative', 'title': '安抚毛文龙', 'stage_text': '普通 initiative 可带 resolve_condition 文本。', 'resolve_condition': 'character.毛文龙.loyalty >= 65'}]}, SettlementContext(content=content))

    assert not section(out, "issue_summary").rejected, out
    row = _issue_by_title(db, "安抚毛文龙")
    assert row is not None
    assert not row["commitment_kind"]


def test_commitment_lands_without_invented_resolve_effect(game, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")

    settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': _promulgated_commitment_origin(db, state, 'pay-liao-arrears'), 'kind': 'initiative', 'title': '每月补辽饷直到补齐', 'ongoing_effects': {'economy': [{'account': '国库', 'delta': -50, 'category': '补饷承诺', 'reason': '每月补辽饷'}]}, 'stop_condition': {'army.guanning.arrears': '<=0'}, 'commitment_kind': 'until_stop'}]}, SettlementContext(content=content))

    row = _issue_by_title(db, "每月补辽饷直到补齐")
    assert json.loads(row["effect_on_resolve"]) == {}
