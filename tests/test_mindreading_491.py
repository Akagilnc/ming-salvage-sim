"""#491 近臣读心：独立生成、定性输入与流水线边界。

#1185：不锁自由散文措辞；经 build_mindreading_materials 真实入口证明 ledger
域值进入模型材料且裸分/机读键不泄。
"""

from dataclasses import replace
import inspect
import json
from types import SimpleNamespace

import pytest

import ming_sim.mindreading as mindreading
from ming_sim.agents import create_mindreading_agent
from ming_sim.db import GameDB
from ming_sim.mindreading import (
    build_mindreading_materials,
    build_scouting_precision_payload,
    current_inner_court_attendant_name,
    generate_mindreading_payload,
    is_inner_court_attendant,
)
from ming_sim.models import LLMConfig


class _SpyMindreadingAgent:
    def __init__(self, text="这话另有未尽之意。"):
        self.text = text
        self.inputs = []

    def run(self, material):
        self.inputs.append(json.loads(material))
        return SimpleNamespace(content=self.text)


def _generate(db, state, reader, target, reply, model=None, **kwargs):
    materials = build_mindreading_materials(
        db, state, reader, target, reply, **kwargs,
    )
    return materials, generate_mindreading_payload(
        materials, object(), mindreading_agent=model or _SpyMindreadingAgent(),
    )


def test_reader_is_selected_by_inner_court_post_not_name(game):
    _db, _state, content = game
    wang = content.characters["王承恩"]
    assert is_inner_court_attendant(wang)
    assert is_inner_court_attendant(replace(wang, name="随驾新内官", aliases=[]))
    assert is_inner_court_attendant(
        replace(wang, name="御前近臣", office="御前近臣", office_type="待铨")
    )
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    assert not is_inner_court_attendant(minister)


def test_only_exact_unique_attendant_slots_can_mindread(game):
    _db, _state, content = game
    for name in ("王体乾", "曹化淳", "高起潜"):
        assert not is_inner_court_attendant(content.characters[name])
    candidate = replace(
        content.characters["王承恩"], office="御前近臣候补", office_type="司礼监"
    )
    assert not is_inner_court_attendant(candidate)


def test_multi_office_attendant_survives_persistence_without_weakening_unique_slot(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]

    db.set_character_office(reader.name, "御前近臣，司礼监秉笔太监", "司礼监")

    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (reader.name,)
    ).fetchone()["office"] == "御前近臣,司礼监秉笔太监"
    assert current_inner_court_attendant_name(db) == reader.name
    assert build_mindreading_materials(
        db, state, reader, target, "臣有本奏。",
    )["reader"] == reader.name

    db.set_character_office("曹化淳", "御前近臣候补,司礼监秉笔太监", "司礼监")
    assert current_inner_court_attendant_name(db) == reader.name
    db.set_character_office("曹化淳", "御前近臣,司礼监秉笔太监", "司礼监")
    assert current_inner_court_attendant_name(db) == ""
    with pytest.raises(ValueError, match="当前唯一"):
        build_mindreading_materials(db, state, reader, target, "臣有本奏。")

    db.conn.execute("UPDATE characters SET status='dismissed' WHERE name=?", (reader.name,))
    db.conn.commit()
    with pytest.raises(ValueError, match="当前唯一"):
        build_mindreading_materials(db, state, reader, target, "臣有本奏。")


def test_mindreading_agent_has_no_minister_session_history_or_tools():
    agent = create_mindreading_agent(
        LLMConfig(api_key="test", base_url="http://localhost/v1", model="test")
    )

    assert agent.db is None
    assert agent.session_id is None
    assert agent.tools == []
    assert agent.add_history_to_context is False


def test_mindreading_agent_instructions_carry_wang_chengen_persona():
    """#1474：递话 agent 装王承恩个性——正向例句带、无硬一句、指令零负向。"""
    agent = create_mindreading_agent(
        LLMConfig(api_key="test", base_url="http://localhost/v1", model="test")
    )
    parts = [str(part) for part in (agent.instructions or [])]
    text = "\n".join(parts)

    assert "王承恩" in text
    # 北极星示范口吻入桩（正向例句，原句可含对话内用词）
    assert "皇爷" in text
    assert "奴婢替皇爷说透" in text or "替皇爷把那座金矿" in text
    assert "只输出一句简短旁白" not in text
    # 宁缺毋滥资格入桩
    assert "暗流" in text and "隐情" in text
    # 指令句（非「」例句）零负向：不要/禁止 只允许出现在例句引号内
    import re
    instructional = re.sub(r"「[^」]*」", "", text)
    for banned in ("不要", "禁止"):
        assert banned not in instructional, banned


def test_mindreading_and_scouting_consume_the_same_precision_contract(game, monkeypatch):
    calls = []

    def shared_precision(target_factor, channel_factor):
        calls.append((target_factor, channel_factor))
        return "隐约"

    monkeypatch.setattr(mindreading, "intelligence_precision", shared_precision)
    db, state, content = game
    materials = build_mindreading_materials(
        db, state, content.characters["王承恩"], content.characters["温体仁"],
        "臣愿肩起此事。",
        target_factor=0.5, channel_factor=1.0,
    )

    assert materials["precision"] == "隐约"
    assert build_scouting_precision_payload(0.5, 1.0) == {
        "source": "锦衣卫查探预留", "precision": "隐约",
    }
    assert calls == [(0.5, 1.0), (0.5, 1.0)]


def test_model_receives_complete_qualitative_sources_and_result_enters_payload(game):
    """结构键 + 回话/见闻入模 + payload 边界；裸机读键不泄。"""
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]
    db.record_public_knowledge_event(state, "旧闻", "内廷听闻此人旧日行止。")
    model = _SpyMindreadingAgent("近臣低声说，这话尚未说尽。")
    reply = "  臣先奏：忠诚=98。\n次陈军务，不敢删节。  "

    materials, payload = _generate(db, state, reader, target, reply, model)

    assert len(model.inputs) == 1
    material = model.inputs[0]
    assert set(material) == {"当轮回话", "党账", "君臣账", "底案", "近臣自身见闻"}
    assert material["当轮回话"] == reply
    assert any(item["title"] == "旧闻" for item in material["近臣自身见闻"])
    assert payload == {
        "reader": reader.name,
        "target": target.name,
        "source": "见闻",
        "precision": "清晰",
        "narration": model.text,
    }
    assert "忠诚=98" not in json.dumps(payload, ensure_ascii=False)
    rendered = json.dumps(material, ensure_ascii=False)
    assert "identity" not in rendered
    assert "loyalty" not in rendered
    assert "seed_guilt" not in rendered
    assert "truth_struct" not in materials


def test_mindreading_ledger_sample_and_diff_without_raw_scores(game):
    """ledger 域值入材料；单轴 identity/loyalty 隔离；默认 seed 不泄协议键。"""
    db, state, content = game
    reader, target = content.characters["王承恩"], content.characters["温体仁"]
    guilt_payload = {"crime": "合谋", "severity": "重"}
    db.conn.execute(
        "UPDATE characters SET faction=?, identity=?, loyalty=?, seed_guilt=? WHERE name=?",
        ("皇党", 92, 15, json.dumps(guilt_payload, ensure_ascii=False), target.name),
    )
    db.conn.commit()
    model = _SpyMindreadingAgent()
    materials, payload = _generate(db, state, reader, target, "臣有本奏。", model)
    material, truths = model.inputs[0], materials["truths"]
    assert set(truths) == {"党账", "君臣账", "底案"}
    assert "皇党" in material["党账"] and guilt_payload["crime"] in material["底案"]
    assert guilt_payload["severity"] in material["底案"]
    blob = json.dumps(material, ensure_ascii=False)
    for tok in ("92", "15", "identity", "loyalty", "seed_guilt"):
        assert tok not in blob
    assert "truth_struct" not in materials and "integ" not in blob.lower()
    assert payload["narration"] == model.text

    base = dict(truths)

    def _axis(identity=None, loyalty=None):
        sets, vals = [], []
        if identity is not None:
            sets.append("identity=?"); vals.append(identity)
        if loyalty is not None:
            sets.append("loyalty=?"); vals.append(loyalty)
        db.conn.execute(
            f"UPDATE characters SET {', '.join(sets)} WHERE name=?", (*vals, target.name),
        )
        db.conn.commit()
        return _generate(db, state, reader, target, "臣有本奏。", _SpyMindreadingAgent())[0]["truths"]

    # 单轴只改 identity → 仅党账变
    id_t = _axis(identity=10)
    assert id_t["党账"] != base["党账"] and id_t["君臣账"] == base["君臣账"] and id_t["底案"] == base["底案"]
    assert "10" not in json.dumps(id_t, ensure_ascii=False)
    # 单轴只改 loyalty → 仅君臣账变
    loy_t = _axis(identity=92, loyalty=90)
    assert loy_t["君臣账"] != base["君臣账"] and loy_t["党账"] == base["党账"] and loy_t["底案"] == base["底案"]
    assert "90" not in json.dumps(loy_t, ensure_ascii=False)

    # 恢复温体仁原始行后再做默认 seed 协议键检查
    o = content.characters[target.name]
    db.conn.execute(
        "UPDATE characters SET faction=?, identity=?, loyalty=?, seed_guilt=? WHERE name=?",
        (o.faction, int(o.identity), int(o.loyalty), json.dumps(o.seed_guilt, ensure_ascii=False), target.name),
    )
    db.conn.commit()
    for name in ("温体仁", "周延儒"):
        seeded = build_mindreading_materials(
            db, state, reader, content.characters[name], "臣有本奏。",
        )
        assert "truth_struct" not in seeded
        assert "integ" not in json.dumps(seeded["truths"], ensure_ascii=False).lower()


def test_mindreading_record_survives_restore_without_entering_shared_history(
    tmp_path, content
):
    path = tmp_path / "mindreading.db"
    db = GameDB(str(path), content)
    try:
        db.seed_static_data()
        state = db.load_state()
        reader = content.characters["王承恩"]
        target = content.characters["温体仁"]
        _materials, payload = _generate(
            db, state, reader, target, "臣有本奏。",
            _SpyMindreadingAgent("近臣低声陈明未尽之意。"),
        )
        chat_turn_id = db.create_chat_turn(state, target.name, "record-test", 0)
        db.record_mindreading(chat_turn_id, payload)
    finally:
        db.close()

    restored = GameDB(str(path), content)
    try:
        records = restored.list_mindreading_records(chat_turn_id)
        assert len(records) == 1
        assert records[0].pop("id") > 0
        assert records == [payload]
        assert restored.load_all_chat_history() == {}
        restored_state = restored.load_state()
        knowledge = restored.get_character_knowledge(restored_state, reader.name)
        assert payload["narration"] not in json.dumps(knowledge, ensure_ascii=False)
    finally:
        restored.close()


def test_undo_chat_turn_permanently_removes_mindreading_record(tmp_path, content):
    path = tmp_path / "mindreading-undo.db"
    db = GameDB(str(path), content)
    payload = {
        "reader": "王承恩",
        "target": "温体仁",
        "source": "臣有本奏。",
        "precision": "明晰",
        "narration": "近臣低声陈明未尽之意。",
    }
    try:
        db.seed_static_data()
        state = db.load_state()
        chat_turn_id = db.create_chat_turn(state, payload["target"], "undo-test", 0)
        db.record_mindreading(chat_turn_id, payload)

        db.undo_chat_turn(chat_turn_id)

        assert db.list_mindreading_records(chat_turn_id) == []
    finally:
        db.close()

    restored = GameDB(str(path), content)
    try:
        assert restored.list_mindreading_records(chat_turn_id) == []
    finally:
        restored.close()


def test_runtime_uses_existing_model_config_factory(game, monkeypatch):
    _db, _state, _content = game
    runtime_config = object()
    model = _SpyMindreadingAgent()
    seen = []
    monkeypatch.setattr(
        mindreading,
        "create_mindreading_agent",
        lambda config: seen.append(config) or model,
    )

    generate_mindreading_payload(
        {"truths": {}, "reader_context": {}}, runtime_config,
    )

    assert seen == [runtime_config]


def test_reply_is_an_explicit_pipeline_input():
    signature = inspect.signature(build_mindreading_materials)
    assert signature.parameters["minister_reply"].default is inspect.Parameter.empty


def test_reader_eligibility_uses_current_db_office_after_reassignment(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    db.conn.execute(
        "UPDATE characters SET office='礼部尚书', office_type='礼部' WHERE name=?",
        (reader.name,),
    )
    db.conn.commit()

    with pytest.raises(ValueError, match="御前近臣"):
        build_mindreading_materials(
            db, state, reader, content.characters["温体仁"], "臣有本奏。",
        )


def test_empty_model_text_is_legitimate_absence(game):
    """#1474：无真增量 → 空返回缺席（行为路径），非失败、非凑数旁白。"""
    db, state, content = game
    materials = build_mindreading_materials(
        db, state, content.characters["王承恩"], content.characters["温体仁"],
        "臣愿肩起此事。",
    )

    assert generate_mindreading_payload(
        materials, object(), mindreading_agent=_SpyMindreadingAgent(""),
    ) is None
    assert generate_mindreading_payload(
        materials, object(), mindreading_agent=_SpyMindreadingAgent("   "),
    ) is None


def test_nonempty_model_text_still_enters_narration(game):
    """#1474：有增量路径仍出话。"""
    db, state, content = game
    materials = build_mindreading_materials(
        db, state, content.characters["王承恩"], content.characters["温体仁"],
        "臣愿肩起此事。",
    )
    payload = generate_mindreading_payload(
        materials,
        object(),
        mindreading_agent=_SpyMindreadingAgent(
            "皇爷，他这句应承背后另有人事盘算。"
        ),
    )
    assert payload is not None
    assert payload["narration"] == "皇爷，他这句应承背后另有人事盘算。"
