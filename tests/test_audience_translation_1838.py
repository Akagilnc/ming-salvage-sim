"""#1838 C1b 召对转译：分段 / 可闻性 / 在场进出 / 御前主角 / 边事件 / 公开说法。

受控声明桩（模拟转译 LLM 一次产出）经真实 apply 入口落库，验收：
- 一轮戏文三段说话人与可闻性；御前低语不进不在场者经历（AC1）
- 入见 / 告退经转译记入在场进出（AC2）
- 御前主角随转译声明变化并可按源轮读回（AC3）
- 边事件、公开说法落对应记录并指向事务（AC4）

不启动故事抽取 / 边事件判官 / 读心——转译声明本身即承接。
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    get_night_protagonist,
    list_ledger,
    open_night,
    person_night_experience,
    present_names_at,
)
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.entities.affair.store import AffairStore
from ming_sim.public_sayings import list_public_sayings
from ming_sim.relations import summon_edge_origin
from ming_sim.session import GameSession
from tests.conftest import deterministic_test_beat_generator, persist_and_schedule_scene


def _activate(db, state, *names: str) -> None:
    for name in names:
        if db.get_character_status(name)[0] != "active":
            db.set_character_status(state, name, "active", reason="1838 测试置在场")


def test_three_speaker_segments_private_whisper_reaches_only_participant(game):
    """AC1：三段说话人可闻性；低语只进王承恩经历。"""
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

    # 外部可见：按源轮从 ledger 读回三段说话人 + 可闻性（不靠 applied 投影凑数）
    segments = [
        e for e in list_ledger(db, nid)
        if int(e.get("source_chat_turn_id") or 0) == ctid
        and not e.get("presence_effect")
    ]
    assert len(segments) == 3
    by_body = {e["body"]: e for e in segments}
    assert by_body[wang_reply]["person_names"] == ["王绍徽"]
    assert by_body[wang_reply]["audibility"] == AUDIBILITY_PUBLIC
    assert by_body[bi_interject]["person_names"] == ["毕自严"]
    assert by_body[bi_interject]["audibility"] == AUDIBILITY_PUBLIC
    assert by_body[wang_whisper]["person_names"] == ["王承恩"]
    assert by_body[wang_whisper]["audibility"] == AUDIBILITY_PRIVATE

    # 王绍徽在场期间可闻殿上公开；御前低语不进其经历投影
    wang_exp = person_night_experience(db, nid, "王绍徽")
    bodies = [e["body"] for e in wang_exp]
    assert wang_reply in bodies
    assert bi_interject in bodies
    assert wang_whisper not in bodies
    assert wang_whisper in [e["body"] for e in person_night_experience(db, nid, "王承恩")]

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


def _scene_session(db, state, content, monkeypatch):
    """搭 scene_chat 最小壳：挡真实 LLM，保留宣 X 确定性写口。"""
    from tests.conftest import stub_audience_translate, stub_scene_agent

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="殿上应对。", tools=[])

    stub_scene_agent(monkeypatch, FakeAgent())
    stub_audience_translate(monkeypatch)
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda out: str(getattr(out, "content", "") or ""),
    )
    monkeypatch.setattr("ming_sim.session._dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(
        "ming_sim.session.prepare_scene_materials",
        lambda *a, **k: SimpleNamespace(opening="开场", root=None),
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = SimpleNamespace(channel="")
    sess.temporary_characters = {}
    sess.agno_db = None
    from ming_sim.beat_orchestration import ChatTurnSceneRegistry
    from ming_sim.session import _CLI_ACTION_INTENT_EXECUTOR
    sess._beat_generator = deterministic_test_beat_generator
    sess._scene_registry = ChatTurnSceneRegistry(_CLI_ACTION_INTENT_EXECUTOR)
    sess._write_gate = None
    return sess


def _drain_scene_owner(sess, db, *, timeout_s: float = 5.0) -> None:
    """persist+schedule 后经会话唯一写队列排空。"""
    del db, timeout_s
    sess._write_queue.barrier(lambda: None)


def _active_chat_turn(db, state, night_id: int) -> int:
    """建可撤回的存活轮（status=active；挂夜默认 generating 不可 undo）。"""
    return int(db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night_id), status="active",
    ))


def test_protagonist_follows_translation_and_xuan_cut(game, monkeypatch):
    """AC3：御前主角随转译声明变化；宣 X 经 scene_chat 真入口当场先切并绑源轮。"""
    db, state, content = game
    _activate(db, state, "王绍徽", "王承恩")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    assert get_night_protagonist(db, nid) == ""

    sess = _scene_session(db, state, content, monkeypatch)
    t1 = _active_chat_turn(db, state, nid)
    # 真入口：scene_chat("宣王绍徽", chat_turn_id=t1) 当场先切并绑源轮
    cuts = []
    r_xuan = sess.scene_chat(
        "宣王绍徽", chat_turn_id=t1,
        on_protagonist_changed=lambda: cuts.append(get_night_protagonist(db, nid)),
    )
    persist_and_schedule_scene(sess, db, r_xuan)
    _drain_scene_owner(sess, db)
    assert get_night_protagonist(db, nid) == "王绍徽"
    assert cuts == ["王绍徽"]
    assert db.conn.execute(
        "SELECT protagonist_name FROM chat_turns WHERE id=?", (t1,),
    ).fetchone()["protagonist_name"] == "王绍徽"

    # 王承恩独自回奏一轮 → 转译声明主角是他
    ctid = _active_chat_turn(db, state, nid)
    result = apply_audience_round_translation(
        db, state,
        {"protagonist": {"person_name": "王承恩"}},
        night_id=nid, chat_turn_id=ctid,
    )
    assert result.protagonist.validated == {"person_name": "王承恩"}
    assert get_night_protagonist(db, nid) == "王承恩"
    assert db.conn.execute(
        "SELECT protagonist_name FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["protagonist_name"] == "王承恩"


def test_protagonist_undo_reprojects_night_current(game, monkeypatch):
    """御前主角夜当前值：宣 X → 转译覆盖 → undo 真入口按存活最近轮重投影。"""
    db, state, content = game
    _activate(db, state, "王绍徽", "王承恩")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    sess = _scene_session(db, state, content, monkeypatch)

    t1 = _active_chat_turn(db, state, nid)
    r_xuan = sess.scene_chat("宣王绍徽", chat_turn_id=t1)
    persist_and_schedule_scene(sess, db, r_xuan)
    _drain_scene_owner(sess, db)
    assert get_night_protagonist(db, nid) == "王绍徽"
    assert db.conn.execute(
        "SELECT protagonist_name FROM chat_turns WHERE id=?", (t1,),
    ).fetchone()["protagonist_name"] == "王绍徽"

    t2 = _active_chat_turn(db, state, nid)
    apply_audience_round_translation(
        db, state,
        {"protagonist": {"person_name": "王承恩"}},
        night_id=nid, chat_turn_id=t2,
    )
    assert get_night_protagonist(db, nid) == "王承恩"

    # 全局最后存活轮先撤 t2 → 夜主角回到 t1 的王绍徽
    db.undo_chat_turn(t2)
    assert get_night_protagonist(db, nid) == "王绍徽"

    # 再撤 t1 → 无存活声明，夜主角回初态空值
    db.undo_chat_turn(t1)
    assert get_night_protagonist(db, nid) == ""


def test_retry_older_round_keeps_newer_protagonist(game):
    db, state, _ = game
    _activate(db, state, "王绍徽", "王承恩")
    nid = int(open_night(db, state, location="乾清宫", time_of_day="戌时")["id"])
    older = _active_chat_turn(db, state, nid)
    newer = _active_chat_turn(db, state, nid)
    apply_audience_round_translation(
        db, state, {"protagonist": {"person_name": "王承恩"}},
        night_id=nid, chat_turn_id=newer,
    )
    apply_audience_round_translation(
        db, state, {"protagonist": {"person_name": "王绍徽"}},
        night_id=nid, chat_turn_id=older,
    )
    assert get_night_protagonist(db, nid) == "王承恩"


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
    edge_id = int(result.edge_events.applied[0]["id"])
    edge_row = db.conn.execute(
        "SELECT affair_id, context, origin FROM relation_edge_events WHERE id=?",
        (edge_id,),
    ).fetchone()
    assert edge_row["affair_id"] == affair.id
    assert edge_row["context"] == "当殿为赈灾站台"
    # 源轮绑定复用 summon_edge_origin，接入既有撤回删口（ADR 0082）
    assert str(edge_row["origin"]).startswith(summon_edge_origin(ctid))

    assert len(result.public_sayings.applied) == 1
    sayings = list_public_sayings(db, involved_character="毕自严")
    matched = next(s for s in sayings if s["body"] == saying_body)
    # 与边事件侧同严：affair_ref 必须精确等于该事务 origin_ref
    assert matched["affair_ref"] == AffairStore.origin_ref(affair.id)


def test_edge_event_undo_deletes_via_source_turn(game):
    """转译边事件 ctid>0 绑源轮 → undo_chat_turn 真入口删该事件。"""
    db, state, _ = game
    _activate(db, state, "王绍徽", "毕自严")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    ctid = _active_chat_turn(db, state, nid)

    result = apply_audience_round_translation(
        db, state,
        {
            "edge_events": [{
                "source": "毕自严",
                "target": "王绍徽",
                "event_kind": "撑腰",
                "context": "当殿为赈灾站台",
            }],
        },
        night_id=nid, chat_turn_id=ctid,
    )
    assert len(result.edge_events.applied) == 1
    edge_id = int(result.edge_events.applied[0]["id"])
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events WHERE id=?", (edge_id,),
    ).fetchone()["n"] == 1

    db.undo_chat_turn(ctid)
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events WHERE id=?", (edge_id,),
    ).fetchone()["n"] == 0


def test_on_scene_fact_undo_via_translation_entry(game):
    """#1839 类二姊妹缝：apply 入口委托公开分派自记前像 → undo 逆转人物处置。

    本入口是 #1842 后台 worker 的真实落账核；不另建平行前像机制。
    """
    db, state, _ = game
    _activate(db, state, "王绍徽", "毕自严")
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    ctid = _active_chat_turn(db, state, nid)

    result = apply_audience_round_translation(
        db, state,
        {
            "on_scene_facts": [{
                "name": "王绍徽", "动作": "处置", "status": "dead",
                "reason": "殿前斩杀",
            }],
        },
        night_id=nid, chat_turn_id=ctid, minister_name="毕自严",
    )
    assert len(result.on_scene_facts.applied) == 1
    assert result.on_scene_facts.rejected == []
    assert db.get_character_status("王绍徽")[0] == "dead"

    db.undo_chat_turn(ctid)
    assert db.get_character_status("王绍徽")[0] == "active"
    turn_row = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn_row["status"] == "undone"
