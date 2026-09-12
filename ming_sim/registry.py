"""大臣 Agent 创建与注册表。读取走材料目录（#1830 / #1833）。

通过 bind_content() 注入 GameContent。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills
from agno.skills.loaders.local import LocalSkills

from ming_sim.constants import TURN_UNIT
from ming_sim.content import GameContent
from ming_sim.context import character_context_with_db
from ming_sim.models import Character, CourtContext, LLMConfig
from ming_sim.llm_model import create_chat_model
from ming_sim.materials import (
    MaterialsRoot,
    material_tools,
    prepare_character_materials,
    release_material_tree,
)
from ming_sim.tools import _duty_location, build_minister_tools

_content: Optional[GameContent] = None
_skills_cache: Dict[str, Skills] = {}

# 各 office_type 对应的 skill 子集。只给该类大臣实际需要的 skill，
# 避免把 simulator/extractor 专用 skill 注入大臣 system prompt 浪费 token。
# 读取一律走材料目录（#1819 / #1830）；此处只留动作类 skill。
_OFFICE_SKILLS: Dict[str, List[str]] = {
    "_base": ["memory-recall", "decree-drafting", "secret-order", "summon"],
    "礼部":   ["consort-selection"],
    "司礼监": ["consort-selection"],
}


def _skills_for(office_type: str) -> Skills:
    """按 office_type 返回精简 skill 集。"""
    if office_type not in _skills_cache:
        names = list(_OFFICE_SKILLS["_base"])
        names += _OFFICE_SKILLS.get(office_type, [])
        loaders = [LocalSkills(f".agno_skills/{n}", validate=False) for n in names]
        _skills_cache[office_type] = Skills(loaders)
    return _skills_cache[office_type]


def bind_content(content: GameContent) -> None:
    global _content
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("registry.bind_content() 未调用：GameContent 未注入。")
    return _content


def _minister_game_world_prompt(prompt: str) -> str:
    """给大臣的世界观说明只保留呈现口径，不把引擎量表喂给角色。"""
    lines = []
    for line in prompt.splitlines():
        if "国势核心数值四个：" in line:
            line = "- 国势以奏报呈现：国库、内库保留钱粮口径；民心、皇威只作定性描述。"
        elif "地区盘面使用两京十三省的核心字段：" in line:
            line = "- 地区盘面中人口、粮食、田亩、隐田、每回合税收等可数物照实呈报；民心、动乱、士绅阻力、军事压力以定性描述呈报。"
        elif "军队盘面使用主要军队核心字段：" in line:
            line = "- 军队盘面中驻地、统帅、兵种、人数、月饷与欠饷等可数物照实呈报；补给、士气、训练、装备、火器、机动、忠诚以定性描述呈报；随军大炮照门数呈报。"
        lines.append(line)
    return "\n".join(lines)


def _make_cultivate_tool(character: Character, context: CourtContext):
    """生成后宫调教 tool，绑定到当前妃嫔。"""
    name = character.name

    def cultivate_consort(skill: str = "", trait: str = "") -> str:
        """皇帝调教妃嫔，为其新增技能或改变性格。skill：新增技能名（如"书法精通"），可为空；trait：新增性格词（如"更加温婉"），可为空。效果永久生效，下次召见时体现在人物描述中。"""
        context.db.cultivate_consort(
            name, context.state.turn, skill=skill.strip(), trait=trait.strip()
        )
        parts = []
        if skill.strip():
            parts.append(f"习得技能「{skill.strip()}」")
        if trait.strip():
            parts.append(f"性情添了「{trait.strip()}」")
        if not parts:
            return "未指定技能或性格，调教无效。"
        return "已记录：" + "、".join(parts) + "。下次召见时将体现。"

    return cultivate_consort


# 后宫预设立绘池：编号 → 该图的人物身份/气质（LLM 据此为秀女配图，确保人图一致）。
# 与 web/public/portraits/consort_pool_<N>.png 及 docs/portrait-prompts.md 文末清单对应。
CONSORT_POOL_IDENTITIES: Dict[int, str] = {
    1: "满洲格格——英武明艳，关外贵女，骑射出身",
    2: "江湖卖艺女——活泼灵动，杂耍歌舞，市井出身",
    3: "女侠——飒爽英姿，习武佩剑，江湖出身",
    4: "江南名妓——才情风流，诗词歌赋，秦淮出身",
    5: "才女画师——洒脱灵动，丹青妙笔，书香出身",
    6: "棋待诏——冷静知性，精于围棋，弈林出身",
    7: "道姑——仙气飘逸，修道清修，方外出身",
    8: "忧郁美人——秋色清愁，沉静寡言，文士门第",
    9: "波斯商女——异域浓彩，丝路而来，西域胡商之女",
    10: "琴师——清雅文艺，善抚瑶琴，乐坊出身",
    11: "娇艳贵女——明丽妩媚，雍容华贵，勋贵门第",
    12: "女医——温柔聪慧，通晓医药，杏林出身",
    13: "东厂女探——暗黑魅惑，身手不凡，厂卫出身",
    14: "端庄贵妇——母仪雍容，知书达礼，名门嫡女",
    15: "茶道名媛——温润恬静，精于茶艺，士绅之家",
    16: "南洋舶来——海岛风情，远渡而来，南洋舶商之女",
}


def _make_select_consort_tool(context: CourtContext):
    """生成选妃呈名单 tool，挂在司礼监/礼部大臣上。
    秀女由 LLM 据预设立绘池的身份现场拟就，tool 落库为待选采女（status=candidate），
    人设与所选立绘一致。只立候选不册封——皇帝看中后另下诏册封，走 candidate 升格路径。"""

    def _pool_used() -> set:
        rows = context.db.conn.execute(
            "SELECT portrait_id FROM characters WHERE portrait_id LIKE 'consort_pool_%'"
        ).fetchall()
        used = set()
        for r in rows:
            try:
                used.add(int(str(r["portrait_id"]).replace("consort_pool_", "")))
            except ValueError:
                pass
        return used

    def present_consort_candidates(consorts_json: str = "") -> str:
        """呈上待选秀女名单。

        可用立绘身份（portrait 编号→身份；已被占用的编号不要再选，先以空参调用可查当前可用编号）：
        {POOL_TABLE}

        consorts_json：JSON 数组字符串，3-5 人。每名秀女对象：
          {{"portrait": 4, "name": "柳如烟", "style": "才情风流",
            "skills": ["诗词","琵琶"], "summary": "秦淮名妓，色艺双绝", "faction": "中宫"}}
        """
        content = _ctx()
        try:
            raw = json.loads(consorts_json) if isinstance(consorts_json, str) and consorts_json.strip() else consorts_json
        except (json.JSONDecodeError, TypeError):
            return "（拟选名单格式有误，请以 JSON 数组重拟，每名含 portrait/name/style/skills/summary。）"
        if isinstance(raw, dict):
            raw = raw.get("consorts") or raw.get("candidates") or [raw]
        if not isinstance(raw, list) or not raw:
            free = sorted(set(CONSORT_POOL_IDENTITIES) - _pool_used())
            table = "\n".join(f"  {i}：{CONSORT_POOL_IDENTITIES[i]}" for i in free)
            return ("（尚未拟出秀女。请按下列可用立绘配人，回传 JSON 数组：\n"
                    + table + "\n每名含 portrait/name/style/skills/summary。）")

        existing_names = set(content.characters.keys())
        used = _pool_used()
        chosen: List[tuple[Character, int]] = []
        for item in raw[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in existing_names:
                continue
            try:
                pid = int(item.get("portrait"))
            except (TypeError, ValueError):
                continue
            if pid not in CONSORT_POOL_IDENTITIES or pid in used:
                continue  # 编号非法或已占用，跳过
            skills = item.get("skills") or []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.replace("、", ",").split(",") if s.strip()]
            consort = Character(
                name=name,
                office="采女（待选）",
                office_type="后宫",
                faction=str(item.get("faction") or "中宫"),
                aliases=[],
                personal_skills=[str(s).strip() for s in skills if str(s).strip()],
                loyalty=int(item.get("loyalty") or 60),
                ability=int(item.get("ability") or 55),
                integrity=int(item.get("integrity") or 60),
                courage=int(item.get("courage") or 50),
                style=str(item.get("style") or "温婉"),
                power_id="ming",
                status="candidate",
                summary=str(item.get("summary") or "").strip(),
                portrait_id=f"consort_pool_{pid}",  # 显式指定，add_character 不再自动分配
            )
            context.db.add_character(context.state, consort)
            content.characters[name] = consort
            existing_names.add(name)
            used.add(pid)
            chosen.append((consort, pid))

        if not chosen:
            free = sorted(set(CONSORT_POOL_IDENTITIES) - _pool_used())
            return ("（拟选的秀女或重名、或立绘编号非法/已占用，未能立为候选。"
                    f"当前可用立绘编号：{free}，请重拟。）")

        lines = ["臣等已为陛下物色数名待选采女，恭呈御览："]
        for idx, (c, _pid) in enumerate(chosen, 1):
            tags = "、".join(c.personal_skills) if c.personal_skills else "—"
            summary = (c.summary or "").strip()
            if len(summary) > 50:
                summary = summary[:50] + "…"
            lines.append(
                f"{idx}. {c.name}　性情：{c.style or '—'}　特质：{tags}"
                + (f"　{summary}" if summary else "")
            )
        lines.append("陛下若有中意者，可降诏册封其位份，即可入宫。")
        return "\n".join(lines)

    # 池身份表烤进 docstring（全 16 槽静态，不含动态 free 列表 → 工具 schema 跨回合不变，保缓存）。
    pool_table = "\n".join(f"  {i}：{CONSORT_POOL_IDENTITIES[i]}" for i in sorted(CONSORT_POOL_IDENTITIES))
    present_consort_candidates.__doc__ = present_consort_candidates.__doc__.replace("{POOL_TABLE}", pool_table)
    return present_consort_candidates


def create_minister_agent(
    character: Character,
    llm_config: LLMConfig,
    context: CourtContext,
    agno_db: SqliteDb,
    session_id: Optional[str] = None,
) -> Agent:
    # 召对不再另立一套超时分档（#353 的 90/300 随硬墙钟一同删）：等多久算死由设置页
    # 那一格（静默判死阈值）统一说了算，召对与结算同吃 transport 策略（#1465 切片③
    # owner 2026-09-07）。此处按原配置构造，不改调用方对象。
    # temperature 0.6：保留人物个性，但收敛发挥——少在拟旨里夹带题外私货。
    model = create_chat_model(llm_config, temperature=0.6, top_p=0.9)
    # 开场只带最小集（身份、在场、日期、正经手事务、本场已说的话）。
    # 钱粮/奏报/地区/军队/派系等加工材料进材料目录，由模型自读（#1830 / ADR 0155）。
    # The caller owns the live content/state pair.  Requiring the module-level
    # registry binding here makes this public construction seam fail in fresh
    # sessions (and lets a stale binding win over a restored context).
    c = context.db.content or _ctx()
    is_consort = character.office_type == "后宫"
    materials_root: MaterialsRoot | None = None
    minister_skills = None
    if is_consort:
        # 从 DB 取调教记录
        cultivated = context.db.get_consort_traits(character.name)
        extra_skills_str = ("、".join(cultivated["extra_skills"])) if cultivated["extra_skills"] else ""
        extra_traits_str = ("、".join(cultivated["extra_traits"])) if cultivated["extra_traits"] else ""
        cultivate_desc = ""
        if extra_skills_str:
            cultivate_desc += f"经皇帝调教后习得：{extra_skills_str}。"
        if extra_traits_str:
            cultivate_desc += f"性情逐渐变化：{extra_traits_str}。"
        instructions = [
            _minister_game_world_prompt(c.game_world_prompt),
            c.consort_agent_prompt,
            f"你当前扮演：{character.name}，{character.office}，性格{character.style}，"
            f"人物特质：{'、'.join(character.personal_skills)}。个人简介：{character.summary}"
            + (f"\n{cultivate_desc}" if cultivate_desc else ""),
            f"你与皇帝的对话在后宫寝殿；同一回合复召时接续此前对话，不要重置记忆。",
            f"当前为 {context.state.year} 年 {context.state.period} 月。",
        ]
        tools = [_make_cultivate_tool(character, context)]
    else:
        # 开场只带最小集；其余加工材料进目录，由 list/read 或 CLI cwd 自取（#1830）。
        prepared = prepare_character_materials(context.db, context.state, character)
        materials_root = MaterialsRoot(prepared.root)
        if hasattr(model, "materials_dir"):
            model.materials_dir = materials_root.root
        monthly_block_parts = [
            prepared.opening,
        ]
        instructions = [
            _minister_game_world_prompt(c.game_world_prompt),
            c.minister_agent_prompt,
            f"你当前扮演：{character_context_with_db(character, context.db)}，"
            f"任事处：{_duty_location(character.office, character.office_type, 'active')}。",
            f"你与皇帝的多轮对话会持续到本{TURN_UNIT}退朝；同一{TURN_UNIT}复召时要接续此前奏对，不要重置记忆。",
            "\n\n".join(monthly_block_parts),
        ]
        # API tools + CLI cwd share MaterialsRoot; model.materials_dir is optional.
        tools = material_tools(materials_root) + build_minister_tools(
            character, context,
        )
        # 司礼监（内官管后宫）与礼部（议礼册封）可奉旨选妃：现场拟就秀女名单呈御览。
        if character.office_type in ("司礼监", "礼部"):
            tools.append(_make_select_consort_tool(context))
        minister_skills = _skills_for(character.office_type)
    agent = Agent(
        name=character.name,
        id=f"minister-{character.name}",
        session_id=session_id or f"minister-{character.name}-turn-{context.state.turn}",
        db=agno_db,
        model=model,
        instructions=instructions,
        tools=tools,
        skills=minister_skills if not is_consort else None,
        add_history_to_context=True,
        num_history_runs=6,
        markdown=False,
    )
    if materials_root is not None:
        try:
            agent.materials_root = materials_root
        except Exception:
            # Construction doubles may return a plain mapping; tools already
            # close over materials_root, so ownership still tracks the live path.
            pass
    return agent


class MinisterRegistry:
    def __init__(
        self,
        llm_config: LLMConfig,
        agno_db: SqliteDb,
        context: CourtContext,
    ) -> None:
        self.llm_config = llm_config
        self.agno_db = agno_db
        self.context = context
        self.agents: Dict[str, Agent] = {}
        # The CourtContext owns the live content/state pair.  Do not depend on
        # a module-global binding here: fresh sessions and registry refreshes
        # must build from the same restored content that supplied the context.
        self.content = context.db.content or _ctx()
        characters = self.content.characters
        self.session_ids: Dict[str, str] = {
            name: f"minister-{name}-turn-{context.state.turn}"
            for name in characters
        }
        # 懒加载：不在构造时预建全人物 agent（一整月通常只召见两三人，预建 50+ 个
        # 都要查 DB 拼材料目录，纯浪费）。改由 get() 首次取用时按需建并缓存。

    def _create(self, character: Character) -> Agent:
        return create_minister_agent(
            character,
            self.llm_config,
            self.context,
            self.agno_db,
            session_id=self.session_ids[character.name],
        )

    def get(self, character: Character) -> Agent:
        """懒加载：首次召见某大臣才建其 Agent（含材料目录），之后本回合复用缓存。"""
        agent = self.agents.get(character.name)
        if agent is None:
            agent = self._create(character)
            self.agents[character.name] = agent
        return agent

    @staticmethod
    def _materials_handle(agent: Agent | None) -> MaterialsRoot | None:
        if agent is None:
            return None
        handle = getattr(agent, "materials_root", None)
        if isinstance(handle, MaterialsRoot):
            return handle
        handle = MaterialsRoot()
        model = getattr(agent, "model", None)
        if model is not None and hasattr(model, "materials_dir"):
            handle.set(getattr(model, "materials_dir", "") or "")
        try:
            agent.materials_root = handle
        except Exception:
            pass
        return handle

    @staticmethod
    def _release_materials(agent: Agent | None) -> None:
        handle = MinisterRegistry._materials_handle(agent)
        root = handle.clear() if handle is not None else ""
        model = getattr(agent, "model", None) if agent is not None else None
        if not root and model is not None:
            root = str(getattr(model, "materials_dir", "") or "")
        if model is not None and hasattr(model, "materials_dir"):
            model.materials_dir = ""
        if root:
            release_material_tree(root)

    def adopt_materials(self, character_name: str, root: Path | str) -> None:
        """Point the live agent (if any) at a new materials root; release the old tree.

        Ownership is the agent MaterialsRoot handle — not optional model.materials_dir.
        """
        new_root = str(root or "")
        if not new_root:
            return
        agent = self.agents.get(character_name)
        handle = self._materials_handle(agent)
        if handle is None:
            release_material_tree(new_root)
            return
        old = handle.set(new_root)
        model = getattr(agent, "model", None) if agent is not None else None
        if model is not None and hasattr(model, "materials_dir"):
            model.materials_dir = new_root
        if old and old != new_root:
            release_material_tree(old)

    def _replace_agent(self, name: str, agent: Agent) -> None:
        old = self.agents.get(name)
        self.agents[name] = agent
        if old is not None and old is not agent:
            self._release_materials(old)

    def close(self) -> None:
        agents = list(self.agents.values())
        self.agents.clear()
        errors: list[BaseException] = []
        for agent in agents:
            try:
                self._release_materials(agent)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def refresh(self, character_name: str) -> None:
        character = self.content.characters.get(character_name)
        if character is None:
            return
        self._replace_agent(character.name, self._create(character))

    def project_outcome(self, character_name: str) -> None:
        """Outer-commit projection for formal people after durable settlement.

        Brand-new formal people (no session_ids entry yet) must register;
        already-known roster members refresh. Temporary runtime registration
        is untouched (those names already have session_ids). Fail-loud: no
        swallow of register/refresh errors (ADR 0005).
        """
        character = self.content.characters.get(character_name)
        if character is None:
            return
        if character.name not in self.session_ids:
            self.register(character)
        else:
            self.refresh(character.name)

    def register(self, character: Character) -> None:
        """运行时新建人物（吏部铨选任命）后注册其 Agent，使本回合即可召见。"""
        self.session_ids[character.name] = (
            f"minister-{character.name}-turn-{self.context.state.turn}"
        )
        self._replace_agent(character.name, self._create(character))

    def register_runtime(self, character: Character) -> None:
        """注册不入正式名册的临时召见人物。"""
        self.session_ids[character.name] = (
            f"temporary-{character.name}-turn-{self.context.state.turn}"
        )
        self._replace_agent(character.name, self._create(character))
