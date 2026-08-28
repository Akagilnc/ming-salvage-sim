"""密令创建后 refresh 承办大臣 agent，使其上下文立即带上新密令简报。

bug：CLI 后端创建密令后未 refresh，大臣缓存 agent 上下文冻结，
他"不知道自己有这密令"。修：web_app 创建密令后 registry.refresh(承办人)。
此处测 refresh 机制本身：建密令后 get() 仍陈旧；refresh 后重建且带上简报。
"""

from __future__ import annotations

import os
import tempfile

from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import MinisterRegistry, bind_content as _bind_registry
from ming_sim.skills import bind_content as _bind_skills
from ming_sim.llm_model import create_agno_db
from tests.conftest import active_ming_character
from tests.dossier_test_helpers import investigation_covert_task


def _registry(game, monkeypatch):
    db, state, content = game
    _bind_registry(content)                            # 注入 GameContent 给 registry
    _bind_skills(content)                               # skills 也需 content
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")  # CliChat，免 api key 即可建 agent
    fd, apath = tempfile.mkstemp(suffix="_agno.db")
    os.close(fd)
    agno_db = create_agno_db(apath)
    ctx = CourtContext(state=state, db=db, previous_summary="")
    reg = MinisterRegistry(LLMConfig(api_key="cli", base_url="", model="x"), agno_db, ctx)
    return reg, apath


def test_refresh_rebuilds_agent_with_new_secret_order(game, monkeypatch):
    db, state, content = game
    name = active_ming_character(db, content)
    char = content.characters[name]
    reg, apath = _registry(game, monkeypatch)
    try:
        a1 = reg.get(char)                      # 密令未建时建好、缓存
        db.create_secret_order(state, name, "辰字密令更新测试", "限期半年补饷", [], deadline_months=6, covert_task=investigation_covert_task("辰字密令更新测试"))
        assert reg.get(char) is a1              # 创建不触发刷新 → 仍是陈旧缓存
        reg.refresh(name)
        a2 = reg.get(char)
        assert a2 is not a1                      # refresh 后重建
        joined = "\n".join(str(x) for x in a2.instructions)
        assert "辰字密令更新测试" in joined        # 新 agent 上下文带上了新密令简报
    finally:
        if os.path.exists(apath):
            os.remove(apath)
