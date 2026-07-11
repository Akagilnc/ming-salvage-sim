"""近臣读心内容生成（#491）。

这是内容层 seam，不负责 UI 或召对编排：回话正文必须由调用方显式传入，
因此可以在回话流式完成后后台排队，而不会让生成器偷偷等待另一条会话管线。
读心者只携带角色见闻投影；目标的内部底账仅在此处转译成给玩家可读的定性
旁白，不把机器分值带进 payload。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from ming_sim.models import Character
from ming_sim.qualitative import safe_historical_text


_IDENTITY_BANDS = ("几乎不染党色", "党色较淡", "党色不显", "党色较深", "党色极深")
_LOYALTY_BANDS = ("未见深交", "略有隔膜", "尚可托付", "颇得倚重", "深受信任")


def _band(value: object, words: tuple[str, ...]) -> str:
    try:
        score = max(0, min(100, int(value)))
    except (TypeError, ValueError):
        score = 50
    return words[min(score // 20, len(words) - 1)]


def _character_field(character: object, field: str) -> object:
    if isinstance(character, Mapping) or hasattr(character, "keys"):
        try:
            return character[field]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return ""
    return getattr(character, field, "")


def _inner_role_text(character: object) -> str:
    return " ".join(
        str(_character_field(character, field) or "")
        for field in ("office", "office_type")
    )


def is_inner_court_attendant(character: object) -> bool:
    """按御前近臣的职位识别读心者，不把王承恩姓名写死。"""
    text = _inner_role_text(character)
    office_type = str(_character_field(character, "office_type") or "")
    role_tokens = ("随驾", "内官", "内侍", "太监", "大总管", "御前")
    if office_type in {"司礼监", "内廷"}:
        return True
    # office_type may be stale on a legacy/in-flight character object; a
    # strongly identifying office title is sufficient on its own.
    return any(token in text for token in role_tokens)


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


def _seed_guilt_text(character: Character) -> str:
    raw = getattr(character, "seed_guilt", "") or ""
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
    # 去掉 turn/kind/source 等机面元数据，只传读心者自己的世界与听闻正文。
    heard = []
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        heard.append({
            "title": safe_historical_text(item.get("title"), "见闻标题"),
            "body": safe_historical_text(item.get("body"), "见闻正文"),
        })
    return {"world": dict(knowledge.get("world") or {}), "heard": heard[-20:]}


def build_mindreading_payload(
    db: Any,
    state: Any,
    reader: Character,
    target: Character,
    minister_reply: str,
    *,
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

    identity = int(getattr(target, "identity", 50) or 0)
    loyalty = int(getattr(target, "loyalty", 50) or 0)
    if identity < 40 and loyalty >= 60:
        relation = "忠而不党"
    elif identity >= 60 and loyalty < 40:
        relation = "党而不忠"
    else:
        relation = "党君两账未见明显分裂"

    return {
        "reader": reader.name,
        "target": target.name,
        "source": "见闻",
        "precision": intelligence_precision(target_factor, channel_factor),
        "reader_context": _reader_context(db, state, reader),
        "truths": {
            "党账": f"对本党的认同：{_band(identity, _IDENTITY_BANDS)}；{_seed_guilt_text(target)}",
            "君臣账": f"对君的真心：{_band(loyalty, _LOYALTY_BANDS)}。",
            "关系判断": relation,
            "潜台词": str(minister_reply).strip(),
        },
        "reply_text": str(minister_reply).strip(),
    }
