"""开场/入殿/收夜 beat 编排——输入路由 + 零形式约束传递（#503 / PRD #497「开场与收夜 beat」）。

编排层的唯一职责：把一个 beat 的 **in-world 输入路由到位**，交内容生成填充对应账正文，
落进故事账本。设计 canonical = ADR 0033（特征化不约束）/ 0034（角色见闻非全知）/ 0035
（召对夜=容器+开放账本）。

送到位的输入（PRD #497「开场与收夜 beat」段）：
- 他是谁      —— ADR 0033 客观特征化（minister_dossier；身份/脾性/动机/包袱/事例，无裸数值）
- 他知道什么  —— ADR 0034 角色见闻，**经见闻供给接口注入**（默认 get_character_knowledge=#489 底座）
- 他怎么被召来 —— 发起账召法（宣入/传召/越次）
- 时辰地点    —— 召对夜容器持久属性（cmr R7：取自夜，不另传）
- 当下朝局张力 —— 见闻内的定性朝局切片（court/security 域；无此域＝此人不感知，perspectival）
- 前次入殿与奏对 —— 该人本夜先前的入殿账 + 奏对回话（AC2）
- 本夜公开层账 —— 同夜先发生的殿上公开账（该知扩散取数；御前低语不入，PRD R1）

铁律（ADR 0033 覆盖整条组装链）：
- **零形式约束**：BeatInputs 只承载 in-world 内容，绝不含长度/结构/格式参数；生成器只收
  一个 BeatInputs，编排层不施加任何形式约束。
- **P4 由不喂实现**：BeatInputs 各字段皆 str / tuple[str]，无裸抽象数值（忠诚/能力…）；
  特征化走 minister_dossier（不含量表轴），不走带轴的 character_context。
- **不调全知 builder**：组装只经见闻供给接口取世界，绝不调 court_brief / 全员名册类全局块。

内容生成质量与声音形态归 #472/#478；本模块只管编排 + 落账 + 输入路由。
"""

from __future__ import annotations

from concurrent.futures import Executor, Future
from dataclasses import dataclass, fields as _dc_fields
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import threading

from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    METHOD_XUANRU,
    SUMMON_METHODS,
    TAG_ENTER,
    TAG_OPEN_NIGHT,
    get_night,
    list_chat_turns_for_night,
    list_ledger,
    resolve_standing_roster,
)

BEAT_OPEN = "open"
BEAT_ENTER = "enter"
BEAT_EXIT = "exit"
BEAT_CLOSE = "close"
# #1566：场外传召 scene beat ——人在途未入殿，场景围绕「传召已发、人在途」承接，
# 而非「入殿」。ADR 0096：本回合开不成召对、抵京候旨召见。
BEAT_SUMMON = "summon"

# 见闻供给接口：character_name -> 角色见闻投影（get_character_knowledge 契约的 dict）。
# 空名返回 {}。默认实现包 get_character_knowledge（#489 底座）；可注入 fake 做切片验收。
KnowledgeProvider = Callable[[str], Dict[str, Any]]
# 内容生成器：BeatInputs -> 账正文。本模块只定义 seam，实现归 #472/#478。
BeatGenerator = Callable[["BeatInputs"], str]


@dataclass(frozen=True)
class BeatInputs:
    """一个 beat 的路由后 in-world 输入。

    刻意让每个字段都是 str / tuple[str]：既结构性保证「零形式约束」（无长度/结构参数），
    又结构性保证 P4（无裸抽象数值字段）。新增字段须同守此二律。
    """

    beat_kind: str
    time_of_day: str = ""
    location: str = ""
    person_name: str = ""
    characterization: str = ""       # 他是谁（ADR 0033）
    summon_method: str = ""          # 他怎么被召来（发起账召法）
    perspectival_world: str = ""     # 他知道什么（ADR 0034，经供给接口）
    court_tension: str = ""          # 当下朝局张力（定性，见闻内切片）
    prior_appearances: Tuple[str, ...] = ()  # 前次入殿与奏对账目
    public_layer: Tuple[str, ...] = ()       # 本夜公开层账（该知扩散取数）
    audience_scenes: Tuple[str, ...] = ()    # 待顶出场面的结构化在世事实（由开夜内容生成自然呈现）
    # #1294/#1313 r4：当期权威年号（天启七年十月…），in-world 特征；不钉 scene 不改散文
    reign_period_label: str = ""


def _default_knowledge_provider(db: Any, state: Any) -> KnowledgeProvider:
    """默认见闻供给接口：走 get_character_knowledge（#489 per-character 见闻底座）。"""

    def provider(character_name: str) -> Dict[str, Any]:
        name = str(character_name or "").strip()
        if not name or not hasattr(db, "get_character_knowledge"):
            return {}
        return db.get_character_knowledge(state, name) or {}

    return provider


def _court_tension(knowledge: Dict[str, Any]) -> str:
    """从见闻投影取定性朝局张力：court/security 域（皆 audience=True 定性口径，P4 安全）。
    此人所任官职不含该域＝他不感知这层张力，返回空（perspectival，非全知）。"""
    world = knowledge.get("world") if isinstance(knowledge, dict) else None
    world = world or {}
    for domain in ("court", "security"):
        value = str(world.get(domain) or "").strip()
        if value:
            return value
    return ""


def _characterization(db: Any, person_name: str) -> str:
    """他是谁：ADR 0033 客观特征化（minister_dossier）。不走带量表轴的 character_context（P4）。"""
    content = getattr(db, "content", None)
    if content is None or not person_name:
        return ""
    character = content.characters.get(person_name)
    if character is None:
        return ""
    from ming_sim.context import minister_dossier

    return minister_dossier(character)


def _public_layer_bodies(
    db: Any, night_id: int, *, before_entry_id: int = 0,
) -> Tuple[str, ...]:
    """本夜公开层账正文（该知扩散取数）：只取殿上公开；御前低语不入侍立者取数区间（PRD R1）。

    before_entry_id>0 时仅取该 id 之前的账，避免 enter 把自己的垫位正文当前情。
    """
    if not night_id:
        return ()
    bound = int(before_entry_id or 0)
    bodies: List[str] = []
    for entry in list_ledger(db, night_id):
        if bound and int(entry.get("id") or 0) >= bound:
            continue
        if entry.get("audibility") != AUDIBILITY_PUBLIC:
            continue
        body = str(entry.get("body") or "").strip()
        if body:
            bodies.append(body)
    return tuple(bodies)


def _person_prior_appearances(
    db: Any, night_id: int, person_name: str, *, before_entry_id: int = 0,
) -> Tuple[str, ...]:
    """该人本夜先前的入殿账 + 奏对回话（AC2：第二次宣入时组装输入含首次入殿/奏对账目）。

    before_entry_id>0 时排除目标 entry 自身及其后账，保证因果：生成中的入殿不自见。
    """
    if not night_id or not person_name:
        return ()
    bound = int(before_entry_id or 0)
    bodies: List[str] = []
    for entry in list_ledger(db, night_id):
        if bound and int(entry.get("id") or 0) >= bound:
            continue
        if TAG_ENTER not in (entry.get("tags") or []):
            continue
        if person_name not in (entry.get("person_names") or []):
            continue
        body = str(entry.get("body") or "").strip()
        if body:
            bodies.append(body)
    for turn in list_chat_turns_for_night(db, night_id):
        if str(turn.get("minister_name") or "") != person_name:
            continue
        mid = turn.get("minister_message_id")
        if not mid:
            continue
        row = db.conn.execute(
            "SELECT content FROM chat_messages WHERE id = ?", (int(mid),)
        ).fetchone()
        if row is not None:
            reply = str(row["content"] or "").strip()
            if reply:
                bodies.append(reply)
    return tuple(bodies)


def assemble_beat_inputs(
    db: Any,
    state: Any,
    *,
    beat_kind: str,
    time_of_day: str = "",
    location: str = "",
    night_id: int = 0,
    person_name: str = "",
    summon_method: str = "",
    knowledge_provider: Optional[KnowledgeProvider] = None,
    extra_public_layer: Tuple[str, ...] = (),
    before_entry_id: int = 0,
) -> BeatInputs:
    """把一个 beat 的 in-world 输入路由成 BeatInputs。只经见闻供给接口取世界，不调全知 builder。

    extra_public_layer：临时公开层供给（新夜首入殿时夜尚未落库、无 night_id 可取，
    以刚生成的开夜气氛作临时公开层——避免持写锁跨 LLM 调用，见 attach_chat_turn_to_night）。
    before_entry_id：enter/exit 组装时排除目标 entry 自身（及之后）的 prior/public。
    """
    provider = knowledge_provider or _default_knowledge_provider(db, state)

    if beat_kind in (BEAT_ENTER, BEAT_EXIT, BEAT_SUMMON):
        subject = str(person_name or "").strip()
    else:
        # 夜级框架 beat（开夜/收夜）：视角取常在员额首席（王承恩），无则空。
        roster = resolve_standing_roster(db)
        subject = roster[0] if roster else ""

    knowledge = provider(subject) if subject else {}
    from ming_sim.knowledge import render_character_knowledge

    perspectival_world = (
        render_character_knowledge(knowledge, subject, db=db, state=state)
        if subject else ""
    )
    court_tension = _court_tension(knowledge)

    characterization = ""
    prior_appearances: Tuple[str, ...] = ()
    prior_bound = int(before_entry_id or 0)
    if beat_kind in (BEAT_ENTER, BEAT_EXIT, BEAT_SUMMON):
        characterization = _characterization(db, person_name)
        prior_appearances = _person_prior_appearances(
            db, night_id, person_name, before_entry_id=prior_bound,
        )

    # #1294：open/enter 当期年号事实；复用 models.reign_period_label，不另写投影。
    era_label = ""
    if beat_kind in (BEAT_OPEN, BEAT_ENTER, BEAT_SUMMON):
        year = getattr(state, "year", None)
        period = getattr(state, "period", None)
        if year is not None and period is not None:
            from ming_sim.models import reign_period_label as _reign_period_label

            era_label = _reign_period_label(int(year), int(period))

    audience_scenes: Tuple[str, ...] = ()
    if beat_kind == BEAT_OPEN:
        from ming_sim.due_review import current_audience_scene
        current = current_audience_scene(db, state)
        audience_scenes = (() if current is None else (
            json.dumps(current, ensure_ascii=False, sort_keys=True),
        ))
    elif beat_kind == BEAT_SUMMON:
        # ADR 0096 / #1566：场外传召的正向结构化事实（旨意已发、驰递未达、尚未入殿）。
        # 走既有 audience_scenes 槽进 LLM 材料，不另开字段、不写玩家可见模板。
        audience_scenes = (
            json.dumps(
                {
                    "decree_issued": True,
                    "courier_traveling": True,
                    "courier_arrived": False,
                    "person_entered_court": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    return BeatInputs(
        beat_kind=beat_kind,
        time_of_day=str(time_of_day or ""),
        location=str(location or ""),
        person_name=str(person_name or "") if beat_kind in (BEAT_ENTER, BEAT_EXIT, BEAT_SUMMON) else "",
        characterization=characterization,
        summon_method=str(summon_method or "") if beat_kind in (BEAT_ENTER, BEAT_SUMMON) else "",
        perspectival_world=perspectival_world,
        court_tension=court_tension,
        prior_appearances=prior_appearances,
        public_layer=tuple(extra_public_layer) + _public_layer_bodies(
            db, night_id, before_entry_id=prior_bound,
        ),
        audience_scenes=audience_scenes,
        reign_period_label=era_label,
    )


def run_beat_generator(beat_generator: Optional[BeatGenerator], inputs: BeatInputs) -> str:
    """调内容生成器——只递 BeatInputs 一件，绝不附加长度/结构等形式约束参数。

    共用薄 seam：generate_* 与 close_night worker 同走此处。
    调用方须已在主线程 assemble 完全部 DB-backed BeatInputs；本 seam 零 DB。
    生产 scene 的空白输出是失败，不得伪装成模板成功；异常由 chat-turn 生命周期处理。
    """
    if beat_generator is None:
        raise RuntimeError("scene generator is required")
    body = str(beat_generator(inputs) or "").strip()
    if not body:
        raise RuntimeError(f"scene generator returned blank output for {inputs.beat_kind}")
    return body


def create_llm_beat_generator(llm_config: Any) -> BeatGenerator:
    """创建真实 scene LLM adapter。

    prompt 只陈列已路由的 in-world 材料，不携带字数、段落、结构或格式约束；失败原样抛出，
    由召对轮既有失败/重试生命周期处理，禁止静默模板降级。

    每次 generate 新建 Agent：并发 open/enter 不得共享粘性 session/run 状态。
    """
    from agno.agent import Agent
    from ming_sim.llm_model import create_chat_model, extract_agent_text

    instructions = [
        "你是御前召对的叙事声音。依据人物自身可知的朝局与殿上前情，让场景从具体人物、时地和局势中自然长出。",
        # #1295/#1314(2)：开场/入殿只立局势与悬念——不写皇帝答复、不预演奏对
        "开场与入殿只立局势与悬念，不预告后来结果；入殿写人物入殿气象，不写皇帝答复、不预演奏对；"
        "收束忠于已经发生的史实。玩家可见文案不要把召对硬称为夜。",
    ]

    def generate(inputs: BeatInputs) -> str:
        agent = Agent(
            name="Scene Beat Narrator",
            model=create_chat_model(llm_config, temperature=0.7),
            instructions=instructions,
        )
        materials = {
            "场景节点": inputs.beat_kind,
            "时辰": inputs.time_of_day,
            "地点": inputs.location,
            "人物": inputs.person_name,
            "人物特征": inputs.characterization,
            "召法": inputs.summon_method,
            "人物所知": inputs.perspectival_world,
            "人物感知的朝局张力": inputs.court_tension,
            "此前入殿与奏对": inputs.prior_appearances,
            "此前殿上公开之事": inputs.public_layer,
        }
        # #1294/#1313 r4b：仅 open/enter 且 label 非空时发射「当期年月」；
        # exit/close（及空 label）不加入该键，避免越界空键。
        label = str(inputs.reign_period_label or "").strip()
        if inputs.beat_kind in (BEAT_OPEN, BEAT_ENTER, BEAT_SUMMON) and label:
            materials["当期年月"] = label
        # Structured living facts: open-beat 场面；summon 场外传召（#1566）。
        # Without a generator, opening remains an empty typed placeholder.
        if inputs.beat_kind == BEAT_OPEN and inputs.audience_scenes:
            materials["待呈御前的结构化场面事实"] = inputs.audience_scenes
        if inputs.beat_kind == BEAT_SUMMON and inputs.audience_scenes:
            materials["场外传召结构化事实"] = inputs.audience_scenes
        return extract_agent_text(agent.run(json.dumps(materials, ensure_ascii=False)))

    return generate


def generate_open_beat_body(
    db: Any,
    state: Any,
    *,
    time_of_day: str = "",
    location: str = "",
    beat_generator: Optional[BeatGenerator] = None,
    knowledge_provider: Optional[KnowledgeProvider] = None,
) -> str:
    """开夜账正文（夜级框架气氛）；无生成器时保留空垫位。"""
    if beat_generator is None:
        return ""
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_OPEN,
        time_of_day=time_of_day, location=location,
        knowledge_provider=knowledge_provider,
    )
    return run_beat_generator(beat_generator, inputs)


def generate_enter_beat_body(
    db: Any,
    state: Any,
    *,
    night: Dict[str, Any],
    person_name: str,
    summon_method: str = METHOD_XUANRU,
    beat_generator: Optional[BeatGenerator] = None,
    knowledge_provider: Optional[KnowledgeProvider] = None,
    extra_public_layer: Tuple[str, ...] = (),
) -> str:
    """入殿账正文。时辰/地点取自夜容器持久属性（cmr R7）。

    extra_public_layer：新夜首入殿时夜尚未落库，以刚生成的开夜气氛作临时公开层供给。
    """
    if beat_generator is None:
        return ""
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER,
        time_of_day=str(night.get("time_of_day") or ""),
        location=str(night.get("location") or ""),
        night_id=int(night.get("id") or 0),
        person_name=person_name,
        summon_method=summon_method,
        knowledge_provider=knowledge_provider,
        extra_public_layer=extra_public_layer,
    )
    return run_beat_generator(beat_generator, inputs)


def generate_exit_beat_body(
    db: Any,
    state: Any,
    *,
    night: Dict[str, Any],
    person_name: str,
    beat_generator: Optional[BeatGenerator] = None,
    knowledge_provider: Optional[KnowledgeProvider] = None,
) -> str:
    """退侍账正文；人物、时地、见闻与本夜公开层均走同一 BeatInputs seam。"""
    if beat_generator is None:
        return ""
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_EXIT,
        time_of_day=str(night.get("time_of_day") or ""),
        location=str(night.get("location") or ""),
        night_id=int(night.get("id") or 0), person_name=person_name,
        knowledge_provider=knowledge_provider,
    )
    return run_beat_generator(beat_generator, inputs)


def generate_close_beat_body(
    db: Any,
    state: Any,
    *,
    night: Dict[str, Any],
    beat_generator: Optional[BeatGenerator] = None,
    knowledge_provider: Optional[KnowledgeProvider] = None,
) -> str:
    """收夜账正文（收尾余韵）。时辰/地点取自夜容器持久属性（cmr R7）。

    单线程调用方可直接用本入口（内部 assemble + run）。生产收夜路径经
    ChatTurnSceneRegistry.start_close + join（#542：与 endorsement 并行后再汇合）。
    """
    if beat_generator is None:
        return ""
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_CLOSE,
        time_of_day=str(night.get("time_of_day") or ""),
        location=str(night.get("location") or ""),
        night_id=int(night.get("id") or 0),
        knowledge_provider=knowledge_provider,
    )
    return run_beat_generator(beat_generator, inputs)


def beat_input_field_names() -> Tuple[str, ...]:
    """BeatInputs 的字段名（审计断言用：断言无形式约束/裸数值字段）。"""
    return tuple(f.name for f in _dc_fields(BeatInputs))


# ── chat-turn scene lifecycle（#542）：单一 registry，GameSession 只委托 ─────────


def discover_open_enter_tasks(
    db: Any,
    state: Any,
    *,
    minister_name: str,
    chat_turn_id: int,
) -> List[Tuple[int, BeatInputs]]:
    """主线程：发现本轮可生成的开场/入殿账并组装 BeatInputs（零 LLM、可持短读）。"""
    row = db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id = ?", (int(chat_turn_id),),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"durable chat turn disappeared: {chat_turn_id}")
    night_id = int(row["night_id"] or 0)
    night = get_night(db, night_id) or {}
    entries = list_ledger(db, night_id)
    tasks: List[Tuple[int, BeatInputs]] = []
    # Failed/undone/consumed turns do not consume first-turn opening eligibility (C12/T13).
    count = db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_turns "
        "WHERE night_id = ? AND id <= ? "
        "AND status NOT IN ('failed', 'undone', 'consumed')",
        (night_id, int(chat_turn_id)),
    ).fetchone()["c"]
    if int(count) == 1:
        opening = next(e for e in entries if TAG_OPEN_NIGHT in (e.get("tags") or []))
        tasks.append((int(opening["id"]), assemble_beat_inputs(
            db, state, beat_kind=BEAT_OPEN,
            time_of_day=str(night.get("time_of_day") or ""),
            location=str(night.get("location") or ""),
        )))
    entering = next((
        e for e in entries
        if int(e.get("origin_chat_turn_id") or 0) == int(chat_turn_id)
        and TAG_ENTER in (e.get("tags") or [])
    ), None)
    if entering is not None:
        # Recover real summon method from enter-ledger tags (same source as
        # night_archive_metadata); never hardcode 宣入 over 越次/传召.
        enter_tags = entering.get("tags") or []
        summon_method = next(
            (method for method in SUMMON_METHODS if method in enter_tags),
            METHOD_XUANRU,
        )
        enter_id = int(entering["id"])
        tasks.append((enter_id, assemble_beat_inputs(
            db, state, beat_kind=BEAT_ENTER,
            time_of_day=str(night.get("time_of_day") or ""),
            location=str(night.get("location") or ""), night_id=night_id,
            person_name=minister_name, summon_method=summon_method,
            before_entry_id=enter_id,
        )))
    return tasks


def persist_chat_turn_scene(db: Any, generated: List[Tuple[int, str]]) -> None:
    """短写：把已 join 的 scene 正文写入故事账（调用方事务内）。"""
    for entry_id, body in generated:
        db.conn.execute(
            "UPDATE story_ledger_entries SET body = ? WHERE id = ?",
            (body, int(entry_id)),
        )


def _offsite_summon_entry_id(db: Any, *, origin_id: str, person_name: str) -> int:
    """场外传召 entry_id 唯一 lookup（key 派生与 discover 幂等重读共用同一权威）。"""
    from ming_sim.audience_night import list_unsettled_summons

    origin = str(origin_id or "").strip()
    name = str(person_name or "").strip()
    if not origin or not name:
        raise ValueError(
            f"assemble_offsite_summon_inputs 须有 origin_id 与 person_name，"
            f"got origin_id={origin_id!r} person_name={person_name!r}"
        )
    item = next(
        (row for row in list_unsettled_summons(db)
         if row["origin_id"] == origin and row["person_name"] == name),
        None,
    )
    if item is None:
        raise RuntimeError(
            f"场外传召账未落库，无法物化 scene：origin_id={origin!r} person={name!r}"
        )
    return int(item["entry_id"])


def assemble_offsite_summon_inputs(
    db: Any,
    state: Any,
    *,
    origin_id: str,
    person_name: str,
) -> Optional[Tuple[int, BeatInputs]]:
    """#1566：场外传召账 → (entry_id, BeatInputs)。调用方须在 ticketed gate 内调用。

    BEAT_SUMMON（非 BEAT_ENTER）：人在途未入殿，ADR 0096。
    body 已物化时返回 None（幂等）。生成器在 gate 外跑。
    """
    from ming_sim.audience_night import SUMMON_METHODS, get_night
    import json as _json

    name = str(person_name or "").strip()
    entry_id = _offsite_summon_entry_id(db, origin_id=origin_id, person_name=person_name)
    row = db.conn.execute(
        "SELECT body, tags, night_id FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"传召 ledger 行消失：entry_id={entry_id}")
    if str(row["body"] or "").strip():
        return None
    tags = _json.loads(row["tags"] or "[]")
    method = next((m for m in SUMMON_METHODS if m in tags), None)
    if method is None:
        raise RuntimeError(
            f"传召账缺召法 tag：entry_id={entry_id} tags={tags!r}"
        )
    night_id = int(row["night_id"])
    night = get_night(db, night_id) or {}
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_SUMMON,
        time_of_day=str(night.get("time_of_day") or ""),
        location=str(night.get("location") or ""),
        night_id=night_id,
        person_name=name,
        summon_method=method,
        before_entry_id=entry_id,
    )
    return (entry_id, inputs)


class ChatTurnSceneRegistry:
    """本轮 scene 工作的唯一 registry（open/enter/exit 同桶，禁止平行第二表）。

    无依赖 beat 各提交独立 Future 真并发。join/abandon 排空整桶。
    Future.cancel 挡不住已在跑的 LLM——abandon 必须 join drain。
    只拥有 chat-turn scene（int key）。
    """

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self._lock = threading.Lock()
        self._futures: Dict[int, List[Future]] = {}

    def has(self, chat_turn_id: int) -> bool:
        with self._lock:
            return int(chat_turn_id) in self._futures

    def active_turn_ids(self) -> List[int]:
        with self._lock:
            return list(self._futures.keys())

    def _submit(
        self,
        chat_turn_id: int,
        tasks: List[Tuple[int, BeatInputs]],
        beat_generator: Optional[BeatGenerator],
        *,
        create: bool = True,
    ) -> None:
        if not chat_turn_id or not tasks:
            return

        def _run(entry_id: int, inputs: BeatInputs) -> Tuple[int, str]:
            return (int(entry_id), run_beat_generator(beat_generator, inputs))

        with self._lock:
            key = int(chat_turn_id)
            if create:
                bucket = self._futures.setdefault(key, [])
            else:
                # Claimed bucket already drained by join/abandon — never rebuild.
                bucket = self._futures.get(key)
                if bucket is None:
                    return
            for entry_id, inputs in tasks:
                bucket.append(self._executor.submit(_run, int(entry_id), inputs))

    def start_open_enter(
        self,
        db: Any,
        state: Any,
        *,
        minister_name: str,
        chat_turn_id: int,
        beat_generator: Optional[BeatGenerator],
    ) -> None:
        """锁内一次原子 claim：同 chat_turn_id 至多启动一轮 discover/submit。"""
        if not chat_turn_id:
            return
        key = int(chat_turn_id)
        # Claim under lock before any discover work — closes TOCTOU where two
        # callers both pass has() then each submit a full open/enter round.
        with self._lock:
            if key in self._futures:
                return
            self._futures[key] = []
        try:
            tasks = discover_open_enter_tasks(
                db, state, minister_name=minister_name, chat_turn_id=key,
            )
        except BaseException:
            # Discover failed: drop our still-empty claim so retry can re-claim.
            with self._lock:
                if self._futures.get(key) == []:
                    self._futures.pop(key, None)
            raise
        # create=False: join/abandon may have popped the empty claim during
        # discover; do not setdefault-rebuild a late-living bucket.
        self._submit(key, tasks, beat_generator, create=False)

    def start_exit(
        self,
        db: Any,
        state: Any,
        *,
        person_name: str,
        chat_turn_id: int,
        entry_id: int,
        night_id: int,
        beat_generator: Optional[BeatGenerator],
        knowledge_provider: Optional[KnowledgeProvider] = None,
    ) -> None:
        if not chat_turn_id or not entry_id:
            return
        night = get_night(db, int(night_id)) or {}
        exit_id = int(entry_id)
        inputs = assemble_beat_inputs(
            db, state, beat_kind=BEAT_EXIT,
            time_of_day=str(night.get("time_of_day") or ""),
            location=str(night.get("location") or ""),
            night_id=int(night_id),
            person_name=person_name,
            knowledge_provider=knowledge_provider,
            before_entry_id=exit_id,
        )
        self._submit(int(chat_turn_id), [(exit_id, inputs)], beat_generator)

    def start_relation_judge_provider(
        self, chat_turn_id: int, task: Callable[[], Any],
    ) -> Future:
        """Attach the provider-only judge phase to the close bucket."""
        if not chat_turn_id:
            raise ValueError("relation judge provider requires close chat turn")
        with self._lock:
            bucket = self._futures.setdefault(int(chat_turn_id), [])
            future = self._executor.submit(lambda: (-1, task()))
            bucket.append(future)
            return future

    def start_close(
        self,
        db: Any,
        state: Any,
        *,
        chat_turn_id: int,
        night_id: int,
        beat_generator: Optional[BeatGenerator],
        knowledge_provider: Optional[KnowledgeProvider] = None,
    ) -> None:
        """收夜 scene：与 open/enter/exit 同桶，entry_id=0 表示只产正文、finalize 再落账。"""
        if not chat_turn_id:
            return
        night = get_night(db, int(night_id)) or {}
        inputs = assemble_beat_inputs(
            db, state, beat_kind=BEAT_CLOSE,
            time_of_day=str(night.get("time_of_day") or ""),
            location=str(night.get("location") or ""),
            night_id=int(night_id),
            knowledge_provider=knowledge_provider,
        )
        # entry_id=0：close 账仍由 close_night finalize 落；此处只经 registry 产正文。
        self._submit(int(chat_turn_id), [(0, inputs)], beat_generator)

    @staticmethod
    def _drain(
        futures: List[Future],
        *,
        keep_results: bool,
    ) -> List[Tuple[int, str]]:
        """排空同桶 Future：能 cancel 则 cancel，已在跑则 join。

        keep_results=True（join）：收集成功结果；任一 Future 抛错时仍 drain 剩余 sibling，
        桶完整排空后再传播首个异常。keep_results=False（abandon）：丢弃结果与异常。
        """
        results: List[Tuple[int, str]] = []
        first_exc: Optional[BaseException] = None
        for fut in futures:
            if first_exc is not None or not keep_results:
                if fut.cancel():
                    continue
                try:
                    fut.result()
                except BaseException:
                    pass
                continue
            try:
                results.append(fut.result())
            except BaseException as exc:
                first_exc = exc
        if first_exc is not None:
            raise first_exc
        return results

    def join(self, chat_turn_id: int) -> List[Tuple[int, str]]:
        """等待本轮全部 scene Future；不持 DB/写锁。

        默认 pop+drain：ordinary web chat / close scene 共用。summon 长等
        窗口须走 join_retained + release，避免 drain 前 pop 打开 dual-start 窗。
        """
        with self._lock:
            futures = self._futures.pop(int(chat_turn_id), None)
        if not futures:
            return []
        return self._drain(futures, keep_results=True)

    def join_retained(self, chat_turn_id: int) -> List[Tuple[int, str]]:
        """#657 summon 专用：drain 结果但保留 claim，使同 body 重试 coalesce。

        不 pop。终态（consumed/failed 已落 durable）后须 release。
        """
        key = int(chat_turn_id)
        with self._lock:
            futures = list(self._futures.get(key) or ())
        if not futures:
            return []
        return self._drain(futures, keep_results=True)

    def release(self, chat_turn_id: int) -> None:
        """#657 summon 终态释放：pop residual claim + abandon-drain 残余 Future。

        仅 finish_rescript_phase2 在 durable consumed/failed 写后调用。
        """
        with self._lock:
            futures = self._futures.pop(int(chat_turn_id), None)
        if not futures:
            return
        self._drain(futures, keep_results=False)

    def abandon(self, chat_turn_id: int) -> None:
        """排空本轮 scene：能 cancel 则 cancel，已在跑则 join 丢结果。"""
        with self._lock:
            futures = self._futures.pop(int(chat_turn_id), None)
        if not futures:
            return
        self._drain(futures, keep_results=False)

    def abandon_all(self) -> None:
        """teardown：排空全部 chat-turn scene bucket 后再关库。"""
        with self._lock:
            pending = list(self._futures.items())
            self._futures.clear()
        for _key, futures in pending:
            self._drain(futures, keep_results=False)


def start_close_scene_on_registry(
    db: Any,
    state: Any,
    *,
    night_id: int,
    scene_registry: ChatTurnSceneRegistry,
    beat_generator: Optional[BeatGenerator],
    knowledge_provider: Optional[KnowledgeProvider] = None,
    chat_turn_id: int = 0,
) -> Tuple[int, bool]:
    """收夜 scene 启动：进既有 ChatTurnSceneRegistry，不 join。

    无 chat_turn_id 时 scaffold 一轮（与 CLI exit 同族）。返回 (ctid, scaffold_owned)。
    调用方与 endorsement 等无依赖任务并行后，再 join_close_scene_on_registry。
    无 generator 或无 start_close 能力时返回 (ctid, False) 且不提交 Future。
    """
    ctid = int(chat_turn_id or 0)
    if beat_generator is None or not hasattr(scene_registry, "start_close"):
        return (ctid, False)

    scaffold_owned = False
    if not ctid:
        ctid = int(db.create_chat_turn(
            state, "收夜", "close-scene", 0, night_id=int(night_id),
        ))
        scaffold_owned = True

    try:
        scene_registry.start_close(
            db, state,
            chat_turn_id=ctid,
            night_id=int(night_id),
            beat_generator=beat_generator,
            knowledge_provider=knowledge_provider,
        )
    except BaseException as start_exc:
        # #542 r6e: create 后 start 同步抛错时，把 ctid/ownership 挂到异常上，
        # 调用方仍拿得到 ownership，既有 abandon/fail/OPEN 清理才能跑到。
        try:
            start_exc.close_scene_ownership = (int(ctid), bool(scaffold_owned))  # type: ignore[attr-defined]
        except Exception:
            pass
        raise
    return (ctid, scaffold_owned)


def join_close_scene_on_registry(
    db: Any,
    *,
    scene_registry: ChatTurnSceneRegistry,
    chat_turn_id: int,
    scaffold_owned: bool = False,
) -> str:
    """收夜 scene 汇合：join 既有 registry 桶，返回正文。

    成功后退役 scaffold；失败 abandon + fail_chat_turn 后原样抛出——
    不重开夜、不自建 Thread/executor。
    """
    ctid = int(chat_turn_id or 0)
    if not ctid or not hasattr(scene_registry, "join"):
        return ""

    try:
        generated = scene_registry.join(ctid)
        body = ""
        for entry_id, text in generated:
            # The close bucket also carries provider-only siblings (relation judge
            # marker=-1).  Only the close scene owns marker 0 and may supply the
            # player-facing ledger body.
            if int(entry_id) == 0 and text:
                body = str(text)
                break
        if scaffold_owned and hasattr(db, "conn") and getattr(db, "conn", None) is not None:
            # 成功后退役 scaffold，避免 wait_in_flight 把 generating 空轮当在飞。
            db.conn.execute(
                "UPDATE chat_turns SET status = 'failed' "
                "WHERE id = ? AND status = 'generating' AND minister_message_id IS NULL",
                (int(ctid),),
            )
            db.conn.commit()
        return body
    except BaseException as scene_exc:
        try:
            if hasattr(scene_registry, "abandon"):
                scene_registry.abandon(ctid)
            if ctid and hasattr(db, "fail_chat_turn"):
                db.fail_chat_turn(int(ctid))
        except BaseException as cleanup_exc:
            raise scene_exc from cleanup_exc
        raise
