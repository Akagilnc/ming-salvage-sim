"""#1274 QA S2：文案/prompt 小包钉测（#1429/#1430 + #1344 夹带 + #1356 + #1402）。

四条真缝各一钉：
1. minister_agent 召对称谓正向口径（陛下/皇上/臣；亲王才殿下）
2. season_simulator 停自算年号，上下文喂 reign_period_label 事实
3. #1356 邸报报头年月 ≡ 报文自身月（后端 previous_reign_period_label 投影；FE 渲染见 vitest）
4. web _require_active_minister 改调 can_summon 取文案（删「已尚未登场」平行副本）
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_minister_agent_address_terms_positive_in_audience_section():
    """#1429/#1430：召对场面用词补正向称谓——陛下/皇上/臣；亲王才殿下。

    P7/prompts-positive：正向极简，禁负向句、禁模板。
    """
    text = (ROOT / "content/prompts/minister_agent.md").read_text(encoding="utf-8")
    assert "## 召对场面用词" in text
    # 切出该节（到下一 ## 或文末）
    start = text.index("## 召对场面用词")
    rest = text[start + 2 :]
    end_rel = rest.find("\n## ")
    section = text[start:] if end_rel < 0 else text[start : start + 2 + end_rel]
    assert "陛下" in section
    assert "皇上" in section
    assert "臣" in section
    assert "亲王" in section and "殿下" in section
    # 禁负向句/模板铁律：本节不得出现「不得/不要/禁止/勿」类负向或 `{` 模板
    for bad in ("不得称", "不要称", "禁止称", "勿称", "{name}", "${", "{{"):
        assert bad not in section, bad


def test_season_simulator_uses_fed_reign_label_not_self_compute():
    """#1344 夹带：prompt 停令 LLM 自算年号；上下文 turn_header 喂 reign_period_label 事实。"""
    prompt = (ROOT / "content/prompts/season_simulator.md").read_text(encoding="utf-8")
    # 不得再教模型从 year/period 西历「直填年号纪年」自算
    assert "直填年号纪年" not in prompt
    assert "reign_period_label" in prompt or "本回合年月" in prompt
    # 抬头模板走喂入的年号事实，不再 {year}年{period}月 西历拼
    assert "{year}年{period}月" not in prompt
    # F2：骨架不得把字段名 {reign_period_label} 原样写入玩家可见第一行
    assert "{reign_period_label}" not in prompt

    from ming_sim.agents import build_simulator_context
    from ming_sim.models import reign_period_label

    label = reign_period_label(1627, 10)
    assert label == "天启七年十月"
    ctx = build_simulator_context(
        {
            "turn": {
                "year": 1627,
                "period": 10,
                "turn": 1,
                "reign_period_label": label,
            },
            "decree_text": "",
        }
    )
    assert "天启七年十月" in ctx
    assert "【本回合年月】" in ctx
    # 西历裸拼不得作为抬头权威
    assert "【本回合年月】1627 年 10 月" not in ctx


def test_gazette_header_uses_report_own_month_not_current_turn(game):
    """#1356：报头年月 ≡ 报文自身月；开局九月 / 跨年十二月→正月。

    后端 previous_reign_period_label 与 previous_summary 同源（turn_reports year/period），
    不得用当前 turn.reign_period_label 混充上月报头。真渲染见 vitest ReportModal。
    """
    from ming_sim.models import GameState, reign_period_label

    db, state, _content = game

    # 开局：state=天启七年十月，turn0 九月报文 → 报头必须九月
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)
    assert reign_period_label(state.year, state.period) == "天启七年十月"
    opening_label = db.previous_turn_reign_period_label(state)
    assert opening_label == "天启七年九月"
    opening_body = db.previous_turn_summary(state)
    assert opening_body.startswith("天启七年九月")

    # 禁前端第二份年号表：无天启/崇祯 epoch 常量平行表
    web_src = ROOT / "web/src"
    offenders: list[str] = []
    for path in web_src.rglob("*.ts*"):
        if "node_modules" in path.parts:
            continue
        body = path.read_text(encoding="utf-8")
        if "1621" in body and ("天启" in body or "TIANQI" in body or "tianqi" in body):
            offenders.append(str(path.relative_to(ROOT)))
        if "CHONGZHEN_EPOCH" in body or "TIANQI_EPOCH" in body:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []

    # 菜单重开提示仍钉当前开局月（HUD/菜单用 turn 标签，不混充报头）
    menu = (ROOT / "web/src/components/gameMenu.tsx").read_text(encoding="utf-8")
    assert "天启七年十月" in menu


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
    assert current == "崇祯元年正月"
    header = db.previous_turn_reign_period_label(state)
    assert header == "天启七年十二月"
    assert header != current
    body = db.previous_turn_summary(state)
    assert "十二月" in body


def test_state_payload_projects_previous_reign_period_label(game):
    """#1356：state_payload 挂 previous_reign_period_label；turn 标签仍是当前月。"""
    import web_app
    from types import SimpleNamespace
    from ming_sim.models import reign_period_label

    db, state, content = game
    assert db.previous_turn_reign_period_label(state) == "天启七年九月"

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
    assert payload["previous_reign_period_label"] == "天启七年九月"
    assert payload["previous_summary"].startswith("天启七年九月")
    assert payload["turn"]["reign_period_label"] == reign_period_label(state.year, state.period)
    assert payload["turn"]["reign_period_label"] == "天启七年十月"
    assert payload["previous_reign_period_label"] != payload["turn"]["reign_period_label"]


def test_require_active_minister_uses_can_summon_copy_no_yi_shangwei(game, monkeypatch):
    """#1402：offstage 文案走 session.can_summon，不得「已尚未登场」。"""
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

    ok, reason = sess.can_summon(content.characters[name])
    assert ok is False
    assert "尚未登场" in reason
    assert "已尚未" not in reason

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
    detail = ei.value.detail
    assert "尚未登场" in detail
    assert "已尚未" not in detail
    # DRY：与 can_summon 文案同源
    assert detail == reason.strip()
