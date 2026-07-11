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
    # 去掉 turn/kind/source 等机面元数据，只传读心者自己的世界与听闻正文。
    heard = []
    for item in [*(knowledge.get("public_events") or []), *(knowledge.get("events") or [])]:
        heard.append({
            "title": safe_historical_text(item.get("title"), "见闻标题"),
            "body": safe_historical_text(item.get("body"), "见闻正文"),
        })
    return {"world": dict(knowledge.get("world") or {}), "heard": heard[-20:]}


def _safe_reply_text(minister_reply: object) -> str:
    """Keep the explicit reply seam inside the P4 presentation boundary."""
    return safe_historical_text(minister_reply, "大臣回话")


def _infer_subtext(
    minister_reply: str,
    *,
    identity: int,
    loyalty: int,
    seed_guilt: str,
    reader_context: Mapping[str, object],
) -> str:
    """Turn the three truth sources into a small, deterministic soft reading.

    This is deliberately a content seam rather than a truth calculator: the
    durable axes only anchor the kind of suspicion, while the reply supplies
    the observable cue and the reader's heard history supplies its point of
    view.  The result is qualitative prose, never a score dump.
    """
    reply = str(minister_reply).strip()
    if any(word in reply for word in ("推给", "归咎", "责任", "同僚")):
        cue = "把责任往旁人身上移"
    elif any(word in reply for word in ("奉公", "忠心", "效死", "担责")):
        cue = "先把忠顺的话说满"
    else:
        cue = "话说得周全，却留着可转圜的余地"

    guilt_hint = "底案暂未坐实"
    if "无(" in seed_guilt or "污点" in seed_guilt or "合谋" in seed_guilt:
        guilt_hint = "旧日品性上的阴影仍在"
    elif seed_guilt and "无" not in seed_guilt:
        guilt_hint = "旧案的阴影尚未散尽"

    if identity < 40 and loyalty >= 60:
        axis_hint = "党账淡而君臣账较真"
    elif identity >= 60 and loyalty < 40:
        axis_hint = "党账深而君臣账偏冷"
    elif loyalty >= 60:
        axis_hint = "对君尚有可托之处"
    elif loyalty < 40:
        axis_hint = "对君的真心不甚牢靠"
    else:
        axis_hint = "党君两面都还隔着一层"

    heard = reader_context.get("heard") or []
    if heard:
        latest = heard[-1]
        title = str(latest.get("title") or "旧闻") if isinstance(latest, Mapping) else "旧闻"
        view_hint = f"近臣又想起听来的「{title}」"
    else:
        view_hint = "近臣眼下只凭当面这句话作判断"
    return f"{cue}；{axis_hint}，{guilt_hint}。{view_hint}。"


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
    if identity < 40 and loyalty >= 60:
        relation = "忠而不党"
    elif identity >= 60 and loyalty < 40:
        relation = "党而不忠"
    else:
        relation = "党君两账未见明显分裂"

    reader_context = _reader_context(db, state, reader)
    return {
        "reader": reader.name,
        "target": target.name,
        "source": "见闻",
        "precision": intelligence_precision(target_factor, channel_factor),
        "reader_context": reader_context,
        "truths": {
            "党账": (
                f"名义党派：{faction}；"
                f"对本党的认同：{_band(identity, _IDENTITY_BANDS)}；"
                f"{_seed_guilt_text(current_target)}"
            ),
            "君臣账": f"对君的真心：{_band(loyalty, _LOYALTY_BANDS)}。",
            "关系判断": relation,
            "潜台词": _infer_subtext(
                safe_reply,
                identity=identity,
                loyalty=loyalty,
                seed_guilt=str(_character_field(current_target, "seed_guilt") or ""),
                reader_context=reader_context,
            ),
        },
        # Keep this boundary local to the returned payload: callers may retain
        # the raw streamed reply separately, but this player-facing object may
        # only contain the sanitized form.
        "reply_text": _safe_reply_text(safe_reply),
    }
