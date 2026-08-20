"""近臣读心内容生成（#491）。

这是内容层 seam，不负责 UI 或召对编排：回话正文必须由调用方显式传入，
因此可以在回话流式完成后后台排队，而不会让生成器偷偷等待另一条会话管线。
读心者只携带角色见闻投影；目标的内部底账仅在此处转译成给玩家可读的定性
旁白，不把机器分值带进 payload。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from ming_sim.agents import create_mindreading_agent
from ming_sim.db import normalize_office
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import extract_agent_text
from ming_sim.models import Character
from ming_sim.qualitative import (
    identity_band,
    qualitative_character_axis,
)


_INNER_COURT_ATTENDANT_OFFICES = frozenset({"信邸内官随驾", "御前近臣"})
def _character_field(character: object, field: str) -> object:
    if isinstance(character, Mapping) or hasattr(character, "keys"):
        try:
            return character[field]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return ""
    return getattr(character, field, "")


def is_inner_court_attendant(character: object) -> bool:
    """按御前近臣的职位识别读心者，不把王承恩姓名写死。"""
    offices = normalize_office(str(_character_field(character, "office") or ""))
    # 内廷/司礼监是机构，不是御前唯一近臣位。读心权是由当前占据的
    # 槽位授予，而非职位描述中碰巧出现的词；例如「御前近臣候补」不能
    # 因包含槽名而取得旁人底账。名称可变，已登记的槽位标题不可泛化。
    return any(
        office in _INNER_COURT_ATTENDANT_OFFICES
        for office in offices.split(",")
    )


def current_inner_court_attendant_name(db: Any) -> str:
    """返回当前唯一御前近臣位者；空缺或重位时不授权任何人读心。"""
    if not hasattr(db, "conn"):
        return ""
    rows = db.conn.execute(
        "SELECT name, office, office_type FROM characters "
        "WHERE status='active' ORDER BY name"
    ).fetchall()
    eligible = [str(row["name"]) for row in rows if is_inner_court_attendant(row)]
    return eligible[0] if len(eligible) == 1 else ""


def intelligence_precision(target_factor: float = 1.0, channel_factor: float = 1.0) -> str:
    """读心/查探共用的精度口径；探针期目标侧因子恒为常量但保留参数。"""
    try:
        score = max(0.0, min(1.0, float(target_factor) * float(channel_factor)))
    except (TypeError, ValueError):
        score = 0.0
    if score >= 0.75:
        return "清晰"
    if score >= 0.4:
        return "隐约"
    return "模糊"


def build_scouting_precision_payload(
    target_factor: float = 1.0,
    channel_factor: float = 1.0,
) -> Dict[str, str]:
    """为后续锦衣卫查探链提供精度 payload，复用读心的同一口径。"""
    return {
        "source": "锦衣卫查探预留",
        "precision": intelligence_precision(target_factor, channel_factor),
    }


def _seed_guilt_text(character: object) -> str:
    raw = _character_field(character, "seed_guilt") or ""
    try:
        guilt = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        guilt = {}
    if not isinstance(guilt, Mapping):
        return "底案未见坐实之事。"
    crime = str(guilt.get("crime") or "无")
    severity = str(guilt.get("severity") or "无")
    if crime == "无" and severity == "无":
        return "底案未见坐实之事。"
    return f"底案留有{crime}（案情分量：{severity}）。"


def _reader_context(db: Any, state: Any, reader: Character) -> Dict[str, object]:
    knowledge = db.get_character_knowledge(state, reader.name)
    # 去掉 turn/kind/source 等机面元数据，只传读心者自己的听闻正文。当前盘面
    # 会包含可数军政事实；读心 payload 的职责是转译人物底账，不能把无关盘面
    # 混入而意外重现裸人物分值。
    heard = []
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        heard.append({
            "title": str(item.get("title") or ""),
            "body": str(item.get("body") or ""),
        })
    return {"heard": heard[-20:]}


def build_mindreading_materials(
    db: Any,
    state: Any,
    reader: Character,
    target: Character,
    minister_reply: str,
    *,
    target_factor: float = 1.0,
    channel_factor: float = 1.0,
) -> Dict[str, object]:
    """锁内组装读心所需的纯材料，不调用模型。

    ``minister_reply`` 是已经完成的大臣回话原文；除空白判定外不做任何
    解析或改写，锁外模型与最终 payload 都消费同一份原文。
    """
    current_reader: object = reader
    if hasattr(db, "conn"):
        row = db.conn.execute(
            "SELECT office, office_type FROM characters WHERE name=?",
            (reader.name,),
        ).fetchone()
        if row is not None:
            current_reader = row
        if current_inner_court_attendant_name(db) != reader.name:
            raise ValueError("读心 payload 只能由当前唯一御前近臣位生成")
    if not is_inner_court_attendant(current_reader):
        raise ValueError("读心 payload 只能由御前近臣位生成")
    if not str(minister_reply or "").strip():
        raise ValueError("读心 payload 需要显式的大臣回话正文")

    current_target: object = target
    if hasattr(db, "conn"):
        row = db.conn.execute(
            "SELECT faction, identity, loyalty, seed_guilt FROM characters WHERE name=?",
            (target.name,),
        ).fetchone()
        if row is not None:
            current_target = row

    identity = int(_character_field(current_target, "identity") or 0)
    loyalty = int(_character_field(current_target, "loyalty") or 0)
    faction = str(_character_field(current_target, "faction") or "未明党籍")
    reader_context = _reader_context(db, state, reader)
    party_truth = f"名义党派：{faction}；对本党的认同：{identity_band(identity)}。"
    loyalty_truth = f"对君的真心：{qualitative_character_axis('loyalty', loyalty)}。"
    guilt_truth = _seed_guilt_text(current_target)
    return {
        "reader": reader.name,
        "target": target.name,
        "source": "见闻",
        "precision": intelligence_precision(target_factor, channel_factor),
        "reader_context": reader_context,
        "truths": {
            "党账": party_truth,
            "君臣账": loyalty_truth,
            "底案": guilt_truth,
        },
        "reply_text": minister_reply,
    }


def generate_mindreading_payload(
    materials: Mapping[str, object],
    llm_config: object,
    *,
    mindreading_agent: Any = None,
) -> Dict[str, object] | None:
    """仅凭纯材料生成尾随旁白；不得读取 DB 或会话状态。

    #1474：无真增量时模型空返回 → None（本轮缺席，非失败）。
    """
    truths = materials.get("truths")
    reader_context = materials.get("reader_context")
    if not isinstance(truths, Mapping) or not isinstance(reader_context, Mapping):
        raise ValueError("读心材料缺少真相投影或近臣见闻")
    model_materials = {
        "当轮回话": materials.get("reply_text"),
        "党账": truths.get("党账"),
        "君臣账": truths.get("君臣账"),
        "底案": truths.get("底案"),
        "近臣自身见闻": reader_context.get("heard", []),
    }
    agent = mindreading_agent
    if agent is None:
        if llm_config is None:
            raise LLMUnavailable("当前会话没有可用的模型配置")
        agent = create_mindreading_agent(llm_config)
    subtext = extract_agent_text(agent.run(json.dumps(model_materials, ensure_ascii=False)))
    if not subtext:
        # 宁缺毋滥：空返回 = 本轮不递话（合法缺席）
        return None

    return {
        "reader": materials.get("reader"),
        "target": materials.get("target"),
        "source": materials.get("source"),
        "precision": materials.get("precision"),
        "narration": subtext,
    }


# P5（#499）：读心语义依赖当轮完整回话，不可与回话生成并行；编排层据此串行尾随。
generate_mindreading_payload.parallel_safe = False
generate_mindreading_payload.dependencies = frozenset({"minister_reply"})
build_mindreading_materials.dependencies = frozenset({"minister_reply"})
