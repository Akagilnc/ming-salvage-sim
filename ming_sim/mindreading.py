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
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import Character
from ming_sim.qualitative import identity_band, qualitative_band, safe_historical_text


_INNER_COURT_ATTENDANT_OFFICES = frozenset({"信邸内官随驾", "御前近臣"})
_LOYALTY_BANDS = ("未见深交", "略有隔膜", "尚可托付", "颇得倚重", "深受信任")


def _character_field(character: object, field: str) -> object:
    if isinstance(character, Mapping) or hasattr(character, "keys"):
        try:
            return character[field]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return ""
    return getattr(character, field, "")


def is_inner_court_attendant(character: object) -> bool:
    """按御前近臣的职位识别读心者，不把王承恩姓名写死。"""
    office = str(_character_field(character, "office") or "").replace(" ", "")
    # 内廷/司礼监是机构，不是御前唯一近臣位。读心权是由当前占据的
    # 槽位授予，而非职位描述中碰巧出现的词；例如「御前近臣候补」不能
    # 因包含槽名而取得旁人底账。名称可变，已登记的槽位标题不可泛化。
    return office in _INNER_COURT_ATTENDANT_OFFICES


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
    if severity == "无":
        return "底案未见可坐实之罪，另有品性记录。"
    return f"底案留有{crime}（案情分量：{severity}）。"


def _reader_context(db: Any, state: Any, reader: Character) -> Dict[str, object]:
    knowledge = db.get_character_knowledge(state, reader.name)
    # 去掉 turn/kind/source 等机面元数据，只传读心者自己的听闻正文。当前盘面
    # 会包含可数军政事实；读心 payload 的职责是转译人物底账，不能把无关盘面
    # 混入而意外重现裸人物分值。
    heard = []
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        heard.append({
            "title": safe_historical_text(item.get("title"), "见闻标题"),
            "body": safe_historical_text(item.get("body"), "见闻正文"),
        })
    return {"heard": heard[-20:]}


def _safe_reply_text(minister_reply: object) -> str:
    """Keep the explicit reply seam inside the P4 presentation boundary."""
    return safe_historical_text(minister_reply, "大臣回话")


def build_mindreading_payload(
    db: Any,
    state: Any,
    reader: Character,
    target: Character,
    minister_reply: str,
    *,
    mindreading_agent: Any = None,
    target_factor: float = 1.0,
    channel_factor: float = 1.0,
) -> Dict[str, object]:
    """生成一轮召对后的低声旁白 payload。

    ``minister_reply`` 是显式流水线输入；调用方可先把它流式交给玩家，
    再把同一正文传入本函数。目标侧 identity/seed_guilt 与君臣 loyalty
    分开读，identity/loyalty 的机器值只在此处转成定性词。
    """
    current_reader: object = reader
    if hasattr(db, "conn"):
        row = db.conn.execute(
            "SELECT office, office_type FROM characters WHERE name=?",
            (reader.name,),
        ).fetchone()
        if row is not None:
            current_reader = row
    if not is_inner_court_attendant(current_reader):
        raise ValueError("读心 payload 只能由御前近臣位生成")
    if not str(minister_reply or "").strip():
        raise ValueError("读心 payload 需要显式的大臣回话正文")
    safe_reply = _safe_reply_text(minister_reply)

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
    loyalty_truth = f"对君的真心：{qualitative_band(loyalty, _LOYALTY_BANDS)}。"
    guilt_truth = _seed_guilt_text(current_target)
    materials = {
        "当轮回话": safe_reply,
        "党账": party_truth,
        "君臣账": loyalty_truth,
        "底案": guilt_truth,
        "近臣自身见闻": reader_context["heard"],
    }
    agent = mindreading_agent
    if agent is None:
        llm_config = getattr(db, "llm_config", None)
        if llm_config is None:
            raise LLMUnavailable("当前会话没有可用的模型配置")
        agent = create_mindreading_agent(llm_config)
    result = agent.run(json.dumps(materials, ensure_ascii=False))
    subtext = getattr(result, "content", None)
    if not isinstance(subtext, str) or not subtext.strip():
        raise LLMUnavailable("模型返回空文本")
    subtext = subtext.strip()

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
            "潜台词": subtext,
        },
        # Keep this boundary local to the returned payload: callers may retain
        # the raw streamed reply separately, but this player-facing object may
        # only contain the sanitized form.
        "reply_text": _safe_reply_text(safe_reply),
    }
