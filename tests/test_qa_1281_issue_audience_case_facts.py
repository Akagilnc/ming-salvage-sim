"""#1281：议题 audiences 案情（stage_text）注入召对见闻。

缺陷：seed「户部亏空」案情=「毕自严具题：太仓存银不足三百万」且 audiences
含毕自严，但召对毕自严时 LLM 上下文不含此案情——口径随机（当面翻供非骗是乱）。

修法：议题 originating event 的 audiences 含被召对人时，stage_text 级案情经既有
见闻投影缝注入召对上下文（非平行通道、非模板回话）。
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim.session import GameSession


CASE_MARKER = "太仓存银不足三百万"
ISSUE_TITLE = "户部亏空"


def _prompt_for(db, state, content, name: str) -> str:
    session = SimpleNamespace(db=db, state=state)
    return GameSession._audience_prompt_for_message(
        session, "户部钱粮近况如何？", content.characters[name],
    )


def test_audience_prompt_feeds_issue_stage_text_when_summoned_is_in_audiences(game):
    """正向：audiences 含毕自严 → 召对 context 含其具题案情。"""
    db, state, content = game
    prompt = _prompt_for(db, state, content, "毕自严")
    assert CASE_MARKER in prompt
    assert ISSUE_TITLE in prompt


def test_audience_prompt_withholds_issue_stage_text_when_not_in_audiences(game):
    """负向：audiences 不含者（崔呈秀）不注入此案情。"""
    db, state, content = game
    prompt = _prompt_for(db, state, content, "崔呈秀")
    assert CASE_MARKER not in prompt


def test_issue_audience_case_injection_is_llm_fact_not_player_face_change(game):
    """P4：注入为召对事实材料（读模型）；玩家面议题行与公开见闻表零写入。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT stage_text FROM issues WHERE title=? AND status='active' LIMIT 1",
        (ISSUE_TITLE,),
    ).fetchone()
    assert row is not None
    # 玩家议题板本就有 stage_text——本修不改其值
    assert CASE_MARKER in str(row["stage_text"] or "")
    stage_before = row["stage_text"]
    public_before = int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM character_knowledge_events WHERE character_name=''"
        ).fetchone()["n"]
    )

    prompt = _prompt_for(db, state, content, "毕自严")
    assert CASE_MARKER in prompt  # LLM 事实材料

    row_after = db.conn.execute(
        "SELECT stage_text FROM issues WHERE title=? AND status='active' LIMIT 1",
        (ISSUE_TITLE,),
    ).fetchone()
    assert row_after["stage_text"] == stage_before
    public_after = int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM character_knowledge_events WHERE character_name=''"
        ).fetchone()["n"]
    )
    assert public_after == public_before
