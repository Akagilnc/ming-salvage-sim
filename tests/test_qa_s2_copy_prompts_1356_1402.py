"""#1274 QA S2：文案/prompt 小包钉测（#1429/#1430 + #1344 夹带 + #1356 + #1402）。

四条真缝各一钉：
1. minister_agent 召对称谓正向口径（陛下/皇上/臣；亲王才殿下）
2. season_simulator 停自算年号，上下文喂 reign_period_label 事实
3. ReportModal/gameMenu 报头走 reign_period_label 投影（禁前端第二份年号表）
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


def test_report_and_menu_project_reign_period_label_no_second_table():
    """#1356：报头/重开提示走 reign_period_label 投影；前端无第二份年号 epoch 表。"""
    from ming_sim.models import GameState, reign_period_label

    opening = reign_period_label(GameState().year, GameState().period)
    assert opening == "天启七年十月"

    menu = (ROOT / "web/src/components/gameMenu.tsx").read_text(encoding="utf-8")
    assert opening in menu
    assert "天启七年十二月" not in menu

    report_modal = (ROOT / "web/src/components/reportModal.tsx").read_text(encoding="utf-8")
    # 写死「本月故事」须让位给 periodLabel 投影
    assert "periodLabel" in report_modal
    assert 'subtitle="本月故事"' not in report_modal

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
