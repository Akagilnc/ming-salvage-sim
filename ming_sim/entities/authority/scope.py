"""典范授权事域：唯一验形与规范化。

机械旨意归一（db._normalize_directive_dossier_payload）与召对声明承接
（declaration_dispatch）共用此处，禁止平行 partition/strip/重组。
不猜补 character:持有人（#1912 J2）。
"""

from __future__ import annotations

from typing import Tuple


def canonical_authority_scope(
    *,
    scope: object = "",
    target_kind: object = "",
    target_id: object = "",
) -> Tuple[str, str, str]:
    """返回 ``(典范 scope, kind, id)``。

    可由完整 ``scope`` 或成对的 ``target_kind``+``target_id`` 构成；
    亦接受 ``target_id`` 已是 ``kind:id`` 且 kind 空的写法。
    缺冒号或任一段为空 → ``ValueError``（调用方映射拒收 / DMVE）。
    """
    scope_text = str(scope or "").strip()
    if not scope_text or ":" not in scope_text:
        kind = str(target_kind or "").strip()
        tid = str(target_id or "").strip()
        if tid and ":" in tid and not kind:
            scope_text = tid
        elif kind and tid:
            scope_text = f"{kind}:{tid}"
    kind, separator, target = scope_text.partition(":")
    if not separator or not kind.strip() or not target.strip():
        raise ValueError("委任授权缺少典范 scope")
    kind_s = kind.strip()
    target_s = target.strip()
    return f"{kind_s}:{target_s}", kind_s, target_s
