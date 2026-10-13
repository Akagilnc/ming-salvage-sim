"""场景 Agent 创建（#1836 / #1837 reopen）。

旧大臣 agent（MinisterRegistry / create_minister_agent / 动作工具）已退役：
生成链零动作工具，只有场景 LLM 一个说话者（ADR 0155）。
读取走材料目录（#1830 / #1833）。
"""

from __future__ import annotations

from typing import Any, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from ming_sim.content import GameContent
from ming_sim.models import LLMConfig
from ming_sim.llm_model import create_chat_model
from ming_sim.materials import PreparedMaterials, bind_material_tree

def create_scene_agent(
    llm_config: LLMConfig,
    prepared: PreparedMaterials,
    *,
    model: Any = None,
    agno_db: Optional[SqliteDb] = None,
    content: GameContent,
    session_id: Optional[str] = None,
) -> Agent:
    """#1836 / ADR 0155：一个 LLM 演整场召对。

    生成链零动作 / 写入工具、零格式约束（ADR 0033）；读材料只用目录只读工具。
    """
    chat_model = model if model is not None else create_chat_model(
        llm_config, temperature=0.6, top_p=0.9,
    )
    tools = bind_material_tree(chat_model, prepared.root)
    scene_prompt = str(getattr(content, "scene_agent_prompt", "") or "")
    if not scene_prompt.strip():
        # 无 bundled prompt 时的最低特征化底（真源仍是 content/prompts/scene_agent.md）。
        scene_prompt = (
            "你演一场御前召对整场戏。以整段自由戏文回应；可含多人答话、插话与递话人低语。"
            "材料在当前目录，按需自读。"
        )
    instructions = [
        str(getattr(content, "game_world_prompt", "") or ""),
        scene_prompt,
        prepared.opening,
    ]
    instructions = [part for part in instructions if part]
    # ADR 0155：本夜全量 runs 入上下文，不得设票面未授权的固定 run 裁切。
    # agno 3.0.9 Agent.__init__ 在 num_history_runs 与 num_history_messages 皆
    # 为 None 时会归一 num_history_runs=3；session.get_messages(last_n_runs=None)
    # 才是全量。故构造后显式放开，不换另一个固定正整数。
    agent = Agent(
        name="殿上",
        id="scene-audience",
        session_id=session_id or f"scene-turn-{id(prepared)}",
        db=agno_db,
        model=chat_model,
        instructions=instructions,
        tools=tools,
        add_history_to_context=True,
        markdown=False,
    )
    agent.num_history_runs = None
    return agent
