"""#1830 S1：同一公开记录经场景／单人／世界三类目录的准入一致（共用读侧契约）。

现象（两轮）：其一，场景目录的 _write_one_present_person 曾自行逐条写 公开说法/，
与 _write_public_by_month 的邸报排除门分叉；其二，改走共用入口后，单人目录仍留一份
render_character_knowledge 的整体重投影 人物/<名>/见闻.txt——world.public 把公开层
正文再拼一遍，public_events/events 又逐条重述，于是同一条邸报同时可经
公开说法/邸报/ 与 见闻.txt 读到。公开材料因此存在非既定重复载体。

契约面：来源身份、列目录的载体路径集合、载体归属、API 与文件树一致性；终端文件
及两种读取入口保留独立输入原文，不规定标题／正文分隔符、记录顺序或拼接
换行。原文存在不替代 source_id 的准入证明，也不证明同正文记录的出现次数。
"""

from __future__ import annotations

from ming_sim.materials import list_materials
from ming_sim.models import GameState
from ming_sim.public_sayings import list_public_sayings, record_public_saying


def _active_minister(db, content):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.characters.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _seed_public_world(db, state):
    """一条独立公开说法 + 一份已落邸报（各带真实年月，供路径契约使用）。"""
    saying_state = GameState(
        turn=int(state.turn), year=int(state.year) + 50, period=6,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, saying_state, "公开说法探针正文")
    assert any(True for _ in list_public_sayings(db))

    past_state = GameState(
        turn=max(1, int(state.turn)), year=int(state.year) - 1,
        period=max(1, int(state.period) - 1), metrics=dict(state.metrics),
    )
    # 邸报的公开层来源是已入档的公开说法载体（turn_report:<turn>:public），
    # 与归档标题（turn_reports.title）各司其职——与 #1830 人物目录同一条真源。
    db.record_public_knowledge_event(
        past_state, "邸报", "邸报探针正文",
        source_id=f"turn_report:{past_state.turn}:public",
    )
    db.save_turn_report(past_state, "邸报探针正文", title="辽东告急")
    return saying_state, past_state


def _layer_paths(root, prefix):
    """公开层的结构化形状：相对路径集合。不读任何正文。"""
    return {
        path[len(prefix):] for path in list_materials(root)
        if path.startswith(prefix)
    }


def _public_layer(root, prefix):
    """公开层按既定载体划分：按月公开说法 vs 邸报载体。"""
    shape = _layer_paths(root, prefix)
    return (
        {rel for rel in shape if not rel.startswith("邸报/")},
        {rel for rel in shape if rel.startswith("邸报/")},
    )
