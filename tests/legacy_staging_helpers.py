from __future__ import annotations
"""Test helpers that stage pending actions without the retired classifier chain.

#1871 deleted apply_cli_conversation_actions / run_materialize_pipeline.
Downstream settle/transaction tests plant pending rows via shared stage_* seams
or direct db.stage_pending_action.
"""



def active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.characters.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


_active_minister_name = active_minister_name
