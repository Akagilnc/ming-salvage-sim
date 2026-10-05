"""#1274 QA S2：文案/prompt 小包钉测（#1429/#1430 + #1344 夹带 + #1356 + #1402）。

四条真缝各一钉：
1. minister_agent 召对称谓正向口径（陛下/皇上/臣；亲王才殿下）
2. season_simulator 停自算年号，上下文喂 reign_period_label 事实
3. #1356 邸报报头年月 ≡ 报文自身月（后端 previous_reign_period_label 投影；FE 渲染见 vitest）
4. web _require_active_minister：offstage 走 can_summon 闸并以 409 拒收（不锁拒绝散文）
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest






def test_gazette_header_uses_report_own_month_not_current_turn(game):
    """#1356：报头年月 ≡ 报文自身月；跨年十二月→正月。

    #1356 删除方案后开局不再 seed 九月固定邸报；报头同源仍钉真实 turn_reports 行。
    不得用当前 turn.reign_period_label 混充上月报头。真渲染见 vitest ReportModal。
    """
    from ming_sim.models import reign_period_label

    db, state, _content = game

    # 开局 t0：无固定 seed 邸报（删除方案）；当前回合仍是天启七年十月
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)
    # 开局无上月 turn_reports 行时，previous 月份投影为空标签。
    assert db.previous_turn_reign_period_label(state) == ""

    # 落一条真实「九月」报文 → 报头必须九月（与报文自身月）
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (0, 1627, 9, "天启七年九月邸报\n\n一、真结算九月报文"),
    )
    db.conn.commit()
    assert db.previous_turn_reign_period_label(state) == reign_period_label(1627, 9)
    # 月份投影是结构契约；不锁邸报自由正文。


def test_gazette_header_cross_year_december_report_under_january_state(game):
    """#1356 F4：十二月报文 + 正月状态 → 报头十二月（跨年边界）。"""
    from ming_sim.models import reign_period_label

    db, state, _content = game
    # 落一条「十二月」报文（turn=N），再把 state 推到正月
    state.year, state.period, state.turn = 1627, 12, 5
    db.save_turn_report(state, "天启七年十二月邸报·跨年钉测")
    # 过月后 state 已是崇祯元年正月
    state.year, state.period, state.turn = 1628, 1, 6
    current = reign_period_label(state.year, state.period)
    header = db.previous_turn_reign_period_label(state)
    assert header == reign_period_label(1627, 12)
    assert header != current
    # 上月 turn_reports 行身份（turn/year/period）；不跨字段等值／type 断言正文。
    stored = db.conn.execute(
        "SELECT turn, year, period FROM turn_reports WHERE turn=? AND year=? AND period=?",
        (5, 1627, 12),
    ).fetchone()
    assert stored is not None
    assert (int(stored["turn"]), int(stored["year"]), int(stored["period"])) == (5, 1627, 12)


def test_state_payload_projects_previous_reign_period_label(game):
    """#1356：state_payload 挂 previous_reign_period_label；turn 标签仍是当前月。

    删除固定开局邸报后：先落一条真实上月报文再钉月份投影。
    """
    import web_app
    from types import SimpleNamespace
    from ming_sim.models import reign_period_label

    db, state, content = game
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (0, 1627, 9, "天启七年九月邸报\n\n一、真结算九月报文·payload 钉"),
    )
    db.conn.commit()
    assert db.previous_turn_reign_period_label(state) == reign_period_label(1627, 9)

    # 与 c3 同形轻壳：经 WebGame.state_payload 真投影
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary=db.previous_turn_summary(state),
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"

    payload = web_app.WebGame.state_payload(runtime)
    assert payload["previous_reign_period_label"] == reign_period_label(1627, 9)
    assert "previous_summary" in payload
    assert payload["turn"]["reign_period_label"] == reign_period_label(state.year, state.period)
    assert payload["previous_reign_period_label"] != payload["turn"]["reign_period_label"]


def test_require_active_minister_rejects_offstage_via_can_summon(game, monkeypatch):
    """#1402：offstage 拒绝走 session.can_summon；web 以 409 拒收（不锁拒绝散文）。"""
    import web_app
    from fastapi import HTTPException
    from ming_sim.session import GameSession

    db, state, content = game
    # 挑一个可物化的非宗藩大明人物，置 offstage
    name = next(
        (
            n
            for n, c in content.characters.items()
            if getattr(c, "office_type", "") not in ("宗藩", "后宫")
            and getattr(c, "power_id", "ming") == "ming"
        ),
        None,
    )
    assert name is not None
    db.add_character(state, content.characters[name], source="测试物化")
    db.set_character_status(state, name, "offstage", "史实尚未登场")
    assert db.get_character_status(name)[0] == "offstage"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.temporary_characters = {}

    ok, _reason = sess.can_summon(content.characters[name])
    assert ok is False

    stub = SimpleNamespace(
        session=sess,
        content=content,
        db=db,
        character_power_id=lambda c: web_app._character_power_id(c, db),
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    with pytest.raises(HTTPException) as ei:
        web_app._require_active_minister(name)
    assert ei.value.status_code == 409
