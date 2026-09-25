"""御前近臣职位识别，供召对与夜内场景复用。"""

from __future__ import annotations

from typing import Mapping

from ming_sim.db import normalize_office


_INNER_COURT_ATTENDANT_OFFICES = frozenset({"信邸内官随驾", "御前近臣"})


def _character_field(character: object, field: str) -> object:
    if isinstance(character, Mapping) or hasattr(character, "keys"):
        try:
            return character[field]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return ""
    return getattr(character, field, "")


def is_inner_court_attendant(character: object) -> bool:
    """按御前近臣的职位识别近侍，不把具体姓名写死。"""
    offices = normalize_office(str(_character_field(character, "office") or ""))
    # 内廷/司礼监是机构，不是御前唯一近臣位。近臣资格由当前占据的
    # 槽位授予，而非职位描述中碰巧出现的词；例如「御前近臣候补」不能
    # 因包含槽名而取得旁人底账。名称可变，已登记的槽位标题不可泛化。
    return any(
        office in _INNER_COURT_ATTENDANT_OFFICES
        for office in offices.split(",")
    )
