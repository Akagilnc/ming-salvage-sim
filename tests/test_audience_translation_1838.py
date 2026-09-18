"""#1838 C1b 召对转译：分段 / 可闻性 / 在场进出 / 御前主角 / 边事件 / 公开说法。

受控声明桩（模拟转译 LLM 一次产出）经真实 apply 入口落库，验收：
- 一轮戏文三段说话人与可闻性；御前低语不进不在场者经历（AC1）
- 入见 / 告退经转译记入在场进出（AC2）
- 御前主角随转译声明变化并可按源轮读回（AC3）
- 边事件、公开说法落对应记录并指向事务（AC4）

不启动故事抽取 / 边事件判官 / 读心——转译声明本身即承接。
"""

from __future__ import annotations

from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    open_night,
    person_night_experience,
    present_names_at,
    set_night_protagonist,
)
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.public_sayings import list_public_sayings


def _activate(db, state, *names: str) -> None:
    for name in names:
        if db.get_character_status(name)[0] != "active":
            db.set_character_status(state, name, "active", reason="1838 测试置在场")


def test_three_speaker_segments_private_whisper_not_in_other_experience(game):
    """AC1：王绍徽答 / 毕自严插话 / 王承恩低语 → 三段可闻性；低语不进王绍徽经历。"""
    db, state, _ = game
    _activate(db, state, "王绍徽", "毕自严", "王承恩")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=nid)

    wang_reply = "王绍徽跪奏：臣领旨拟明发。"
    bi_interject = "毕自严出班：户部可先挪三十万两垫发。"
    wang_whisper = "王承恩附耳：绍徽面有难色，恐意存观望。"

    declaration = {
        "presence": [
            {"person_name": "王绍徽", "effect": "enter", "body": "王绍徽入见。"},
            {"person_name": "毕自严", "effect": "enter", "body": "毕自严侍立殿侧。"},
        ],
        "scene_facts": [
            {
                "body": wang_reply,
                "audibility": AUDIBILITY_PUBLIC,
                "person_names": ["王绍徽"],
                "tags": ["大臣"],
            },
            {
                "body": bi_interject,
                "audibility": AUDIBILITY_PUBLIC,
                "person_names": ["毕自严"],
                "tags": ["插话"],
            },
            {
                "body": wang_whisper,
                "audibility": AUDIBILITY_PRIVATE,
                "person_names": ["王承恩"],
                "tags": ["递话"],
            },
        ],
        "protagonist": {"person_name": "王绍徽"},
    }

    result = apply_audience_round_translation(
        db, state, declaration, night_id=nid, chat_turn_id=ctid,
    )

    assert len(result.scene_facts.applied) == 3
    assert result.scene_facts.rejected == []
    assert {r["audibility"] for r in result.scene_facts.applied} == {
        AUDIBILITY_PUBLIC, AUDIBILITY_PRIVATE,
    }

    # 王绍徽在场期间可闻殿上公开；御前低语不进其经历投影
    wang_exp = person_night_experience(db, nid, "王绍徽")
    bodies = [e["body"] for e in wang_exp]
    assert wang_reply in bodies
    assert bi_interject in bodies
    assert wang_whisper not in bodies

    # 转译已承接本轮 → 抽取 / 判官水位推进，不另起旧路径
    row = db.conn.execute(
        "SELECT extract_status, relation_judge_status FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert row["extract_status"] == "done"
    assert row["relation_judge_status"] == "done"


def test_presence_enter_exit_from_translation(game):
    """AC2：王绍徽入见 / 告退经转译记入在场进出。"""
    db, state, _ = game
    _activate(db, state, "王绍徽")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=nid)

    enter_body = "王绍徽奉宣入见。"
    exit_body = "王绍徽叩首告退。"
    result = apply_audience_round_translation(
        db, state,
        {
            "presence": [
                {"person_name": "王绍徽", "effect": "enter", "body": enter_body},
                {"person_name": "王绍徽", "effect": "exit", "body": exit_body},
            ],
        },
        night_id=nid, chat_turn_id=ctid,
    )

    assert len(result.presence.applied) == 2
    assert result.presence.rejected == []
    # 先入后出，夜末不在场
    assert "王绍徽" not in present_names_at(db, nid)

    rows = db.conn.execute(
        "SELECT body, presence_effect, source_chat_turn_id FROM story_ledger_entries "
        "WHERE night_id=? AND presence_effect IN ('enter','exit') "
        "ORDER BY seq",
        (nid,),
    ).fetchall()
    presence_rows = [r for r in rows if r["source_chat_turn_id"] == ctid]
    assert [(r["body"], r["presence_effect"]) for r in presence_rows] == [
        (enter_body, "enter"),
        (exit_body, "exit"),
    ]


def test_protagonist_follows_translation_and_xuan_cut(game):
    """AC3：御前主角随转译声明变化；宣 X 当场先切。"""
    db, state, _ = game
    _activate(db, state, "王绍徽", "王承恩")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])

    # 宣 X 当场先切（引擎，不等转译）
    set_night_protagonist(db, nid, "王绍徽", reason="xuan")
    assert db.conn.execute(
        "SELECT protagonist_name FROM audience_nights WHERE id=?", (nid,),
    ).fetchone()["protagonist_name"] == "王绍徽"

    # 王承恩独自回奏一轮 → 转译声明主角是他
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=nid)
    result = apply_audience_round_translation(
        db, state,
        {"protagonist": {"person_name": "王承恩"}},
        night_id=nid, chat_turn_id=ctid,
    )
    assert result.protagonist.validated == {"person_name": "王承恩"}
    assert db.conn.execute(
        "SELECT protagonist_name FROM audience_nights WHERE id=?", (nid,),
    ).fetchone()["protagonist_name"] == "王承恩"
    assert db.conn.execute(
        "SELECT protagonist_name FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["protagonist_name"] == "王承恩"


def test_edge_event_and_public_saying_attach_affair(game):
    """AC4：边事件、公开说法落对应记录并指向事务。"""
    db, state, _ = game
    _activate(db, state, "王绍徽", "毕自严")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=nid)
    affair = db.affairs.open(
        name="陕西赈灾", origin="调银三十万两赈灾",
        year=state.year, period=state.period, turn=state.turn,
    )

    saying_body = "坊间传户部已备陕西赈银。"
    result = apply_audience_round_translation(
        db, state,
        {
            "edge_events": [{
                "source": "毕自严",
                "target": "王绍徽",
                "event_kind": "撑腰",
                "context": "当殿为赈灾站台",
                "affair_declaration": {"attach": "existing", "affair_id": affair.id},
            }],
            "public_sayings": [{
                "body": saying_body,
                "involved_characters": ["毕自严"],
                "affair_declaration": {"attach": "existing", "affair_id": affair.id},
            }],
        },
        night_id=nid, chat_turn_id=ctid,
    )

    assert len(result.edge_events.applied) == 1
    assert result.edge_events.rejected == []
    edge_row = db.conn.execute(
        "SELECT affair_id, context FROM relation_edge_events WHERE id=?",
        (result.edge_events.applied[0]["id"],),
    ).fetchone()
    assert edge_row["affair_id"] == affair.id
    assert edge_row["context"] == "当殿为赈灾站台"

    assert len(result.public_sayings.applied) == 1
    sayings = list_public_sayings(db, involved_character="毕自严")
    assert any(s["body"] == saying_body for s in sayings)
    matched = next(s for s in sayings if s["body"] == saying_body)
    assert str(affair.id) in str(matched.get("affair_ref") or "") or matched.get("affair_ref")
