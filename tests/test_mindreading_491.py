"""#491 近臣读心：独立生成、定性输入与流水线边界。

#1185：不锁自由散文措辞；经 build_mindreading_materials 真实入口 + 测试侧
renderer 哨兵/差分，证明 ledger 值进入模型材料且裸分不泄。
"""

from dataclasses import replace
import inspect
import json
from types import SimpleNamespace

import pytest

import ming_sim.mindreading as mindreading
from ming_sim.agents import create_mindreading_agent
from ming_sim.db import GameDB
from ming_sim.exceptions import LLMUnavailable
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


def test_model_receives_complete_qualitative_sources_and_result_enters_payload(
    game, monkeypatch
):
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]
    db.record_public_knowledge_event(state, "旧闻", "内廷听闻此人旧日行止。")
    model = _SpyMindreadingAgent("近臣低声说，这话尚未说尽。")
    reply = "  臣先奏：忠诚=98。\n次陈军务，不敢删节。  "

    # renderer 哨兵：证明 identity/loyalty 经定性层进入材料，不锁中文 band 词
    monkeypatch.setattr(
        mindreading, "identity_band", lambda value: f"IDBAND_{value}"
    )
    monkeypatch.setattr(
        mindreading,
        "qualitative_character_axis",
        lambda field, value: f"AXIS_{field}_{value}",
    )

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
    # materials 读当前 DB ledger，不是静态 content 快照
    row = db.conn.execute(
        "SELECT identity, loyalty, seed_guilt FROM characters WHERE name=?",
        (target.name,),
    ).fetchone()
    identity_v = int(row["identity"])
    loyalty_v = int(row["loyalty"])
    id_tok = f"IDBAND_{identity_v}"
    loy_tok = f"AXIS_loyalty_{loyalty_v}"
    assert id_tok in material["党账"]
    assert loy_tok in material["君臣账"]
    seed = json.loads(row["seed_guilt"] or "{}") if row["seed_guilt"] else {}
    if not isinstance(seed, dict):
        seed = {}
    crime = str(seed.get("crime") or "无")
    severity = str(seed.get("severity") or "无")
    if crime == "无" and severity == "无":
        assert material["底案"]
    else:
        assert crime in material["底案"]
        assert severity in material["底案"]
    rendered = json.dumps(material, ensure_ascii=False)
    cleaned = rendered.replace(id_tok, "").replace(loy_tok, "")
    assert "identity" not in cleaned
    assert "loyalty" not in cleaned
    assert "seed_guilt" not in cleaned
    assert str(identity_v) not in cleaned
    assert str(loyalty_v) not in cleaned
    assert "truth_struct" not in materials


def test_default_seed_mindreading_materials_do_not_expose_integration_markers(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    marker_keys = {"integration", "integ", "marker", "only_clue", "仅线索", "truth_struct"}

    def _all_keys(obj, acc=None):
        acc = set() if acc is None else acc
        if isinstance(obj, dict):
            for key, value in obj.items():
                acc.add(str(key))
                _all_keys(value, acc)
        elif isinstance(obj, list):
            for value in obj:
                _all_keys(value, acc)
        return acc

    for name in ("温体仁", "周延儒"):
        materials = build_mindreading_materials(
            db, state, reader, content.characters[name], "臣有本奏。",
        )
        truths = materials["truths"]
        assert set(truths) == {"党账", "君臣账", "底案"}
        keys = _all_keys(materials)
        assert marker_keys.isdisjoint(keys)
        assert not any("integ" in key.lower() for key in keys)
        # 底案正文亦不夹 integration 标记词
        guilt_text = str(truths["底案"])
        assert "仅线索" not in guilt_text
        assert "integ" not in guilt_text.lower()


def test_mindreading_reads_current_structured_ledger_without_raw_scores(
    game, monkeypatch
):
    """读当前 ledger；renderer 哨兵绑定显式样例，裸分不进模型材料。"""
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]
    guilt_payload = {"crime": "合谋", "severity": "重"}
    db.conn.execute(
        "UPDATE characters SET faction=?, identity=?, loyalty=?, seed_guilt=? WHERE name=?",
        ("皇党", 92, 15, json.dumps(guilt_payload, ensure_ascii=False), target.name),
    )
    db.conn.commit()
    model = _SpyMindreadingAgent()

    monkeypatch.setattr(
        mindreading, "identity_band", lambda value: f"IDBAND_{value}"
    )
    monkeypatch.setattr(
        mindreading,
        "qualitative_character_axis",
        lambda field, value: f"AXIS_{field}_{value}",
    )

    materials, payload = _generate(db, state, reader, target, "臣有本奏。", model)

    material = model.inputs[0]
    row = db.conn.execute(
        "SELECT faction, identity, loyalty, seed_guilt FROM characters WHERE name=?",
        (target.name,),
    ).fetchone()
    assert row["faction"] == "皇党"
    assert int(row["identity"]) == 92
    assert int(row["loyalty"]) == 15
    assert json.loads(row["seed_guilt"]) == guilt_payload
    assert set(material) >= {"党账", "君臣账", "底案"}
    assert "皇党" in material["党账"]
    assert "IDBAND_92" in material["党账"]
    assert "AXIS_loyalty_15" in material["君臣账"]
    assert guilt_payload["crime"] in material["底案"]
    assert guilt_payload["severity"] in material["底案"]
    blob = json.dumps(material, ensure_ascii=False)
    cleaned = blob.replace("IDBAND_92", "").replace("AXIS_loyalty_15", "")
    assert "92" not in cleaned
    assert "15" not in cleaned
    assert "identity" not in cleaned
    assert "loyalty" not in cleaned
    assert "seed_guilt" not in cleaned
    assert "truth_struct" not in materials
    assert payload["narration"] == model.text

    # 差分：换 ledger 值 → 材料可判别变化
    db.conn.execute(
        "UPDATE characters SET identity=?, loyalty=? WHERE name=?",
        (10, 90, target.name),
    )
    db.conn.commit()
    materials2, _ = _generate(db, state, reader, target, "臣有本奏。", _SpyMindreadingAgent())
    m2 = json.dumps(materials2["truths"], ensure_ascii=False)
    assert "IDBAND_10" in m2
    assert "AXIS_loyalty_90" in m2
    assert "IDBAND_92" not in m2


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


def test_empty_model_text_fails_without_keyword_fallback(game):
    db, state, content = game
    materials = build_mindreading_materials(
        db, state, content.characters["王承恩"], content.characters["温体仁"],
        "臣愿肩起此事。",
    )

    with pytest.raises(LLMUnavailable, match="模型返回空文本"):
        generate_mindreading_payload(
            materials, object(), mindreading_agent=_SpyMindreadingAgent(""),
        )
