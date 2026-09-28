"""#642 族尾收口：本片独有 CI——锚③召对写口徐杨协作 + 闸脚本生产缝主干。

既有指针（不平行重测）：
- 锚① seed 网：`tests/test_relation_seed_638.py`
- 锚② 活模型语义：闸级 `scripts/family_tail_relation_acceptance_642.py --anchor yang`
  （CI 只证 close_night 判官 Future + 按月 settle 主干，不直写三拍边）
- 锚④ prior 机械：`tests/test_relation_read_640.py` + `tests/test_relation_brew_636.py`
  + 本文件 coda mechanical-only
- R1 双表面：`tests/test_relation_store_632.py::test_relation_edges_survive_restore`
- R2：`tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_*`
- R3 / DoD 面4：seed_638 / capture_633
"""

from __future__ import annotations

import json
import threading

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.relation_brew import FOUNDINGS_KEY, MonthEndRelationBrewLeg, RECENT_KEY
from ming_sim.relations import MINISTER_EDGE_KINDS
from ming_sim.session import ChatTurnResult, GameSession
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent


class _CannedJudge:
    def __init__(self, payload):
        self.payload = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )

    def run(self, prompt):
        from types import SimpleNamespace
        return SimpleNamespace(content=self.payload)




def _gate_cfg() -> LLMConfig:
    return LLMConfig(api_key="x", base_url="http://x", model="x", channel="api")


def _bind_content() -> GameContent:
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    return content


def test_coda_acceptance_mechanical_only_skips_live_llm(monkeypatch):
    """锚④闸路径：prior 机械成立；不调用语义活模型。"""
    import scripts.family_tail_relation_acceptance_642 as gate

    def _boom(*_a, **_k):
        raise AssertionError("coda must not call live semantic LLM")

    monkeypatch.setattr(gate, "_llm_json_verdict", _boom)
    monkeypatch.setattr(gate, "run_agent_text", _boom)
    monkeypatch.setattr(gate, "create_chat_model", _boom)

    result = gate._run_coda_anchor(_gate_cfg(), _bind_content())
    assert result["anchor"] == "coda"
    assert result["checks"] == {"mechanical_ok": True}
    assert result["mechanical"]["prior_has_founding"] is True
    assert "semantic_pass" not in result["checks"]
    assert "semantic" not in result




