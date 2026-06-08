"""大臣上下文 READ 注入 + CLI 后端去工具/技能（防英文 code-switch）。

- 地区危情 + 建筑表注入（CLI 无 list_regions/list_buildings 工具）。
- 建筑表用中文地区名，不漏拼音 region_id（曾把 beizhili 等英文塞进上下文）。
- CLI 后端大臣 agent 不挂 tools/skills（无 function-calling，且其英文元数据诱发 code-switch）。
"""

from __future__ import annotations

import os
import tempfile

from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import (
    build_region_brief, build_building_brief, create_minister_agent,
    bind_content as _bind_registry,
)
from ming_sim.skills import bind_content as _bind_skills
from ming_sim.llm_model import create_agno_db
from tests.conftest import active_ming_character


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_region_brief_has_content(game):
    b = build_region_brief(_ctx(game))
    assert b and ("民心" in b or "动乱" in b)


def test_building_brief_uses_chinese_region_name(game):
    b = build_building_brief(_ctx(game))
    assert b and "现有建筑" in b and "Lv" in b
    # 不漏拼音 region_id（英文 code-switch 诱因）
    for pinyin in ("beizhili", "shaanxi", "nanzhili", "zhejiang", "guangdong"):
        assert pinyin not in b


def test_cli_backend_minister_has_no_tools(game, monkeypatch):
    """CLI 后端大臣 agent 不挂 tools/skills（无 function-calling，去英文元数据）。"""
    db, state, content = game
    _bind_registry(content)
    _bind_skills(content)
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    fd, apath = tempfile.mkstemp(suffix="_agno.db")
    os.close(fd)
    agno_db = create_agno_db(apath)
    try:
        ctx = CourtContext(state=state, db=db, previous_summary="")
        char = content.characters[active_ming_character(db, content)]
        agent = create_minister_agent(char, LLMConfig(api_key="cli", base_url="", model="x"), ctx, agno_db)
        assert not agent.tools          # 无工具
        assert not agent.skills         # 无技能
        joined = "\n".join(str(x) for x in agent.instructions)
        assert "召对行事" in joined and "不可自称已办成" in joined  # 行为约束以纯中文补回
        import re as _re
        from ming_sim.registry import _CLI_MINISTER_GUIDE
        assert not _re.search(r"[A-Za-z]", _CLI_MINISTER_GUIDE)   # 补回的指引零英文，不再诱发 code-switch
    finally:
        if os.path.exists(apath):
            os.remove(apath)
