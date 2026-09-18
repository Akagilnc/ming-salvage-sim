"""#1842 T2：转译后台化与封夜提交 join。

Seams:
- build_audience_translate_prompt / normalize_audience_declaration（完整声明契约）
- schedule / trail / join 转译（按轮串行；前台不等）
- GameSession.scene_chat（ctid>0 后台；ctid==0 同步兼容）
- close_night join 最后一轮转译后再成案
- 转译耗尽 → extract_status 待补，不挡下一句
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    close_night,
    get_open_night,
    open_night,
)
from ming_sim.audience_translate import (
    build_audience_translate_prompt,
    normalize_audience_declaration,
)
from ming_sim.audience_translation import (
    catch_up_pending_translations,
    join_all_translations,
    join_night_translations,
    list_pending_translations,
    schedule_audience_turn_translation,
)
from ming_sim.session import GameSession


@pytest.fixture(autouse=True)
def _join_audience_translations_after_test():
    """防止后台 worker 在 game fixture 拆库后仍写共享 content。"""
    yield
    join_all_translations(timeout_s=2.0)


def _sess(db, state, content, *, llm_config=None, translate_fn=None, write_gate=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = write_gate
    sess._audience_translate_fn = translate_fn
    return sess


def _active_name(db, content, preferred: str = "王绍徽") -> str:
    if preferred in getattr(content, "characters", {}):
        return preferred
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _persist_round(db, state, night_id: int, user_text: str, reply: str) -> int:
    speaker = "殿上"
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'user', ?, 'held')",
        (speaker, int(state.turn), user_text),
    )
    uid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'minister', ?, 'held')",
        (speaker, int(state.turn), reply),
    )
    mid = int(cur.lastrowid)
    ctid = int(db.create_chat_turn(
        state, speaker, "s", 0, night_id=int(night_id), status="active",
    ))
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=? WHERE id=?",
        (uid, mid, ctid),
    )
    db.conn.commit()
    return ctid


def test_translate_prompt_declares_on_scene_and_full_sections():
    """Owner resolution：补全 schema/prompt，可声明生死/下狱/革职/文字事实等。"""
    prompt = build_audience_translate_prompt(
        emperor_message="斩杀魏忠贤",
        reply="臣遵旨。",
        night_said=["皇帝：宣魏忠贤"],
        pending_summaries=[],
    )
    for key in (
        "commissions", "promises", "on_scene_facts", "textual_facts",
        "public_sayings", "presence", "scene_facts", "edge_events",
        "protagonist", "registrations",
    ):
        assert f'"{key}"' in prompt or f'"{key}":' in prompt, key
    # 人物实况字段须可声明（闭集词汇提示，不锁整段措辞）
    assert "status" in prompt
    assert "dead" in prompt or "imprisoned" in prompt
    assert "处置" in prompt or "罢黜" in prompt

    raw = {
        "commissions": [{"text": "着办"}],
        "promises": [],
        "on_scene_facts": [{"name": "魏忠贤", "动作": "处置", "status": "dead"}],
        "textual_facts": [{"subject_kind": "character", "subject_id": "x", "body": "伤"}],
        "public_sayings": [{"body": "外间有说", "involved_characters": ["x"]}],
        "presence": [{"person_name": "x", "effect": "exit", "body": "出"}],
        "scene_facts": [{"body": "答", "audibility": "殿上公开", "person_names": ["x"]}],
        "edge_events": [{"source": "a", "target": "b", "event_kind": "结怨", "context": "c"}],
        "protagonist": {"person_name": "x"},
        "registrations": [{"name": "新人", "office": "某职", "office_type": "文"}],
        "noise": 1,
    }
    decl = normalize_audience_declaration(raw)
    assert "noise" not in decl
    assert len(decl["on_scene_facts"]) == 1
    assert decl["protagonist"]["person_name"] == "x"
    assert decl["commissions"][0]["text"] == "着办"


def test_second_sentence_does_not_wait_for_first_translation(game):
    """AC1：皇帝连说两句，第二句不等第一句转译。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    name = _active_name(db, content)
    gate = threading.Lock()

    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def translate_fn(prompt, llm_config):
        # 只认本轮皇帝行，避免 night_said 里上轮正文误伤。
        if "【本轮皇帝】第一句：拿下" in prompt:
            order.append("t1-enter")
            started.set()
            assert release.wait(timeout=2.0)
            order.append("t1-done")
            return {
                "commissions": [],
                "promises": [],
                "on_scene_facts": [{
                    "name": name, "动作": "处置", "status": "imprisoned",
                    "reason": "第一句当场拿下",
                }],
            }
        order.append("t2-run")
        return {"commissions": [], "promises": []}

    ctid1 = _persist_round(db, state, nid, "第一句：拿下", "臣遵旨。")
    ctid2 = _persist_round(db, state, nid, "第二句：再问边饷", "边饷尚可。")

    # 串行队列：先调度 t1（会卡住），再调度 t2；前台调度本身必须立刻返回。
    t_sched = time.monotonic()
    fut1 = schedule_audience_turn_translation(
        db, state,
        emperor_message="第一句：拿下",
        reply="臣遵旨。",
        night_id=nid,
        chat_turn_id=ctid1,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn,
        write_gate=gate,
    )
    assert time.monotonic() - t_sched < 0.5
    assert started.wait(timeout=2.0), "t1 须已进入转译"

    t_sched2 = time.monotonic()
    fut2 = schedule_audience_turn_translation(
        db, state,
        emperor_message="第二句：再问边饷",
        reply="边饷尚可。",
        night_id=nid,
        chat_turn_id=ctid2,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn,
        write_gate=gate,
    )
    # 调度返回不等 t1 完成
    assert time.monotonic() - t_sched2 < 0.5
    assert "t1-done" not in order

    release.set()
    assert join_night_translations(nid, timeout_s=3.0)
    assert fut1.result(timeout=0.1) is not None
    assert fut2.result(timeout=0.1) is not None
    # 按轮串行：t2 不得在 t1 完成前跑
    assert order.index("t1-done") < order.index("t2-run")

    status, _reason = db.get_character_status(name)
    assert status == "imprisoned"
    assert db.get_story_extract_status(ctid1) == "done"
    assert db.get_story_extract_status(ctid2) == "done"


def test_close_night_joins_last_translation_before_commit(game, monkeypatch):
    """AC2：最后一轮应允后立刻退朝；封夜提交 join 转译后成案仍含这道旨。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    person = _active_name(db, content, "洪承畴")
    region = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert region is not None
    region_id = str(region["id"])
    gate = threading.Lock()

    release = threading.Event()

    def translate_fn(prompt, llm_config):
        if "【本轮皇帝】任命并拨银赈灾" in prompt:
            return {
                "commissions": [{
                    "text": "任命并拨银赈灾",
                    "appointment": {
                        "name": person, "office": "陕西巡抚", "appoint_action": "任命",
                    },
                    "grant": {
                        "grant_action": "赈灾", "amount": 30,
                        "account": "国库", "target_kind": "region",
                        "target_id": region_id, "cadence": "一次性",
                    },
                }],
                "promises": [],
            }
        # 应允轮：等 join 才会放行——模拟封夜时转译仍在飞
        release.wait(timeout=2.0)
        rows = db.conn.execute(
            "SELECT id FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
        return {
            "commissions": [],
            "promises": [
                {"action_id": int(r["id"]), "decision": "应允"} for r in rows
            ],
        }

    # 背书批不在本票刀口：确定性空批，避免无 llm_config 拖垮收夜。
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )

    ctid1 = _persist_round(db, state, nid, "任命并拨银赈灾", "臣等领旨。")
    schedule_audience_turn_translation(
        db, state,
        emperor_message="任命并拨银赈灾",
        reply="臣等领旨。",
        night_id=nid, chat_turn_id=ctid1,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)

    ctid2 = _persist_round(db, state, nid, "准", "遵旨。")
    schedule_audience_turn_translation(
        db, state,
        emperor_message="准",
        reply="遵旨。",
        night_id=nid, chat_turn_id=ctid2,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn, write_gate=gate,
    )
    # 不在此 release——close_night 必须 join 等到转译完成
    threading.Timer(0.15, release.set).start()

    # 成案前应允尚未落（转译仍在飞）
    assert db.conn.execute(
        "SELECT night_approved FROM pending_actions ORDER BY id LIMIT 1"
    ).fetchone()["night_approved"] == 0

    result = close_night(
        db, state, content=content, registry=None,
        wait_timeout_s=0.0, write_gate=gate,
    )
    assert result.get("closed") is True or get_open_night(db) is None

    pending = db.conn.execute(
        "SELECT id, status, night_approved, night_id FROM pending_actions ORDER BY id"
    ).fetchall()
    assert pending, "须有交办"
    assert db.get_story_extract_status(ctid2) == "done"
    assert all(int(r["night_approved"] or 0) == 1 for r in pending), [
        dict(r) for r in pending
    ]
    assert all(str(r["status"]) == "committed" for r in pending)


def test_translation_exhaustion_is_pending_and_does_not_block_next(game):
    """AC3：某轮转译耗尽 → 待补可查可重试；对话照常续。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()

    def boom(prompt, llm_config):
        raise RuntimeError("model exhausted")

    def ok(prompt, llm_config):
        return {"commissions": [], "promises": []}

    ctid1 = _persist_round(db, state, nid, "第一句失败", "……")
    fut = schedule_audience_turn_translation(
        db, state,
        emperor_message="第一句失败",
        reply="……",
        night_id=nid, chat_turn_id=ctid1,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=boom, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)
    with pytest.raises(Exception):
        fut.result(timeout=0.1)
    assert db.get_story_extract_status(ctid1) == "pending"
    pending_rows = list_pending_translations(db, night_id=nid)
    assert any(int(r["chat_turn_id"]) == ctid1 for r in pending_rows)

    # 下一句照常调度并完成
    ctid2 = _persist_round(db, state, nid, "第二句继续", "臣在。")
    fut2 = schedule_audience_turn_translation(
        db, state,
        emperor_message="第二句继续",
        reply="臣在。",
        night_id=nid, chat_turn_id=ctid2,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=ok, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)
    assert fut2.result(timeout=0.1) is not None
    assert db.get_story_extract_status(ctid2) == "done"

    # 待补可重试
    recovered = catch_up_pending_translations(
        db, state,
        night_id=nid,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=ok,
        write_gate=gate,
    )
    assert recovered.get("extracted", 0) >= 1 or db.get_story_extract_status(ctid1) == "done"
    assert db.get_story_extract_status(ctid1) == "done"


def test_scene_chat_background_when_chat_turn_id(game, monkeypatch):
    """scene_chat 生产路径：ctid>0 时转译后台化，返回不等待。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    release = threading.Event()
    ran = threading.Event()

    def translate_fn(prompt, llm_config):
        ran.set()
        release.wait(timeout=2.0)
        return {"commissions": [], "promises": []}

    def fake_agent_run(self_agent, prompt):
        return SimpleNamespace(content="臣等在。", tools=[])

    ctid = _persist_round(db, state, nid, "边事如何？", "")  # reply 由 scene 填
    # create turn without minister message yet — scene_chat will produce reply
    db.conn.execute(
        "UPDATE chat_turns SET minister_message_id=NULL WHERE id=?", (ctid,),
    )
    db.conn.commit()

    sess = _sess(db, state, content, translate_fn=translate_fn, write_gate=gate)
    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent",
        lambda *a, **k: SimpleNamespace(run=lambda prompt: fake_agent_run(None, prompt)),
    )
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda out: str(getattr(out, "content", "") or ""),
    )
    monkeypatch.setattr(
        "ming_sim.session._dump_llm_messages",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "ming_sim.session.prepare_scene_materials",
        lambda *a, **k: SimpleNamespace(opening="开场", root=None),
    )

    t0 = time.monotonic()
    result = sess.scene_chat("边事如何？", chat_turn_id=ctid)
    elapsed = time.monotonic() - t0
    assert result.answer == "臣等在。"
    assert elapsed < 0.8, "前台不得等卡住的转译"
    # 后台已启动
    assert ran.wait(timeout=1.0)
    release.set()
    assert join_night_translations(nid, timeout_s=2.0)
    assert db.get_story_extract_status(ctid) == "done"


def test_scene_chat_sync_without_chat_turn_still_applies(game, monkeypatch):
    """ctid==0 同步路径仍落交办（既有 C1a 测兼容）。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    person = _active_name(db, content, "洪承畴")
    region = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    region_id = str(region["id"])

    def translate_fn(prompt, llm_config):
        return {
            "commissions": [{
                "text": "着拨银",
                "grant": {
                    "grant_action": "赈灾", "amount": 10,
                    "account": "国库", "target_kind": "region",
                    "target_id": region_id, "cadence": "一次性",
                },
            }],
            "promises": [],
        }

    sess = _sess(db, state, content, translate_fn=translate_fn)
    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent",
        lambda *a, **k: SimpleNamespace(
            run=lambda prompt: SimpleNamespace(content="领旨。"),
        ),
    )
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda out: str(getattr(out, "content", "") or ""),
    )
    monkeypatch.setattr(
        "ming_sim.session._dump_llm_messages",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "ming_sim.session.prepare_scene_materials",
        lambda *a, **k: SimpleNamespace(opening="开场", root=None),
    )

    result = sess.scene_chat("着拨银")
    assert result.answer == "领旨。"
    assert result.pending_action_id > 0


def test_resolve_turn_joins_pending_translations_before_month(game, monkeypatch):
    """AC4：过月 resolve_turn 真入口 join 全部后台转译后再继续。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    release = threading.Event()
    name = _active_name(db, content)
    saw_join = threading.Event()

    def translate_fn(prompt, llm_config):
        release.wait(timeout=2.0)
        return {
            "on_scene_facts": [{
                "name": name, "动作": "处置", "status": "imprisoned",
                "reason": "过月前 join 落定",
            }],
        }

    ctid = _persist_round(db, state, nid, "拿下", "遵旨。")
    schedule_audience_turn_translation(
        db, state,
        emperor_message="拿下",
        reply="遵旨。",
        night_id=nid, chat_turn_id=ctid,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn, write_gate=gate,
    )
    assert db.get_story_extract_status(ctid) == "pending"

    import ming_sim.audience_translation as at
    real_join = at.join_all_translations

    def tracking_join(*, timeout_s=120.0):
        ok = real_join(timeout_s=timeout_s)
        saw_join.set()
        return ok

    monkeypatch.setattr(at, "join_all_translations", tracking_join)

    sess = _sess(db, state, content, translate_fn=translate_fn, write_gate=gate)
    sess._begun = True
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.previous_summary = ""
    sess.agno_db = None

    # resolve_turn 跑完 join 前缀后立刻停（不进整月结算 LLM）
    class _StopAfterJoin(Exception):
        pass

    real_catch = at.catch_up_pending_translations

    def catch_then_stop(*a, **k):
        out = real_catch(*a, **k)
        raise _StopAfterJoin()

    monkeypatch.setattr(at, "catch_up_pending_translations", catch_then_stop)
    threading.Timer(0.1, release.set).start()

    with pytest.raises(_StopAfterJoin):
        sess.resolve_turn(allow_empty_decree=True)

    assert saw_join.is_set(), "resolve_turn 必须调用 join_all_translations"
    assert db.get_story_extract_status(ctid) == "done"
    status, _ = db.get_character_status(name)
    assert status == "imprisoned"


def test_resolve_turn_incomplete_join_waits_then_continues(game, monkeypatch):
    """类1①：join 先未完成再完成 → 系统内等待后自动续跑；非 SettlementAbort/409。"""
    db, state, content = game
    before_turn = int(state.turn)
    import ming_sim.audience_translation as at

    calls = {"n": 0}

    def flaky_join(*, timeout_s=120.0):
        calls["n"] += 1
        # 第一次未清空（未完成），第二次清空 → 等待后自动续跑
        return calls["n"] >= 2

    monkeypatch.setattr(at, "join_all_translations", flaky_join)

    class _StopAfterWait(Exception):
        pass

    def catch_then_stop(*a, **k):
        raise _StopAfterWait()

    # join 清空后才进 catch-up；此处截断以证「等完后续跑」，不进整月结算
    monkeypatch.setattr(at, "catch_up_pending_translations", catch_then_stop)

    sess = _sess(db, state, content)
    sess._begun = True
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.previous_summary = ""
    sess.agno_db = None

    with pytest.raises(_StopAfterWait):
        sess.resolve_turn(allow_empty_decree=True)

    assert calls["n"] >= 2, "未完成须在 join 缝上继续等，不得一次 False 就中止"
    assert int(state.turn) == before_turn


def test_resolve_turn_exhausted_pending_uses_0157_form(game, monkeypatch, tmp_path):
    """类1：catch-up 后仍 pending=真耗尽 → 0157（错误包+停步）；月份不推进。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    before_turn = int(state.turn)
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def boom(prompt, llm_config):
        raise RuntimeError("model exhausted")

    ctid = _persist_round(db, state, nid, "耗尽句", "……")
    schedule_audience_turn_translation(
        db, state,
        emperor_message="耗尽句",
        reply="……",
        night_id=nid, chat_turn_id=ctid,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=boom, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)
    assert db.get_story_extract_status(ctid) == "pending"

    import ming_sim.audience_translation as at
    monkeypatch.setattr(at, "join_all_translations", lambda *, timeout_s=120.0: True)
    # catch-up 仍失败 → pending 残留
    monkeypatch.setattr(
        at, "catch_up_pending_translations",
        lambda *a, **k: {"extracted": 0, "pending": 1, "scanned": 1},
    )

    sess = _sess(db, state, content, translate_fn=boom, write_gate=gate)
    sess._begun = True
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.previous_summary = ""
    sess.agno_db = None

    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn(allow_empty_decree=True)

    assert ei.value.stage == "audience_translation_exhausted"
    assert ei.value.error_pack_path
    assert int(state.turn) == before_turn


def test_pending_translation_structured_status_and_source_retry(game):
    """类2：待补可投影结构化系统提示态；按源轮收窄 catch-up 重试。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()

    def boom(prompt, llm_config):
        raise RuntimeError("exhausted")

    def ok(prompt, llm_config):
        return {"commissions": [], "promises": []}

    ctid1 = _persist_round(db, state, nid, "失败轮", "……")
    ctid2 = _persist_round(db, state, nid, "另一失败", "……")
    for ctid, msg in ((ctid1, "失败轮"), (ctid2, "另一失败")):
        schedule_audience_turn_translation(
            db, state,
            emperor_message=msg, reply="……",
            night_id=nid, chat_turn_id=ctid,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=boom, write_gate=gate,
        )
    assert join_night_translations(nid, timeout_s=2.0)

    rows = list_pending_translations(db, night_id=nid)
    assert len(rows) >= 2
    for r in rows:
        assert r["kind"] == "translation_pending"
        assert r["retryable"] is True
        assert r["extract_status"] == "pending"
        assert int(r["chat_turn_id"]) in {ctid1, ctid2}

    # 只补 ctid1
    summary = catch_up_pending_translations(
        db, state,
        chat_turn_id=ctid1,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=ok,
        write_gate=gate,
    )
    assert summary.get("scanned", 0) == 1
    assert db.get_story_extract_status(ctid1) == "done"
    assert db.get_story_extract_status(ctid2) == "pending"
    only2 = list_pending_translations(db, chat_turn_id=ctid2)
    assert len(only2) == 1 and int(only2[0]["chat_turn_id"]) == ctid2


def test_apply_round_translation_bind_failure_rolls_back_sections(game, monkeypatch):
    """类3：主角/水位与 section 同权威事务——bind 失败则 section 一并回滚。"""
    from ming_sim.audience_translation import apply_audience_round_translation
    import ming_sim.audience_translation as at

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    name = _active_name(db, content)
    ctid = _persist_round(db, state, nid, "当场处置", "遵旨。")

    def boom_bind(db_, night_id, chat_turn_id, result):
        raise RuntimeError("bind boom")

    monkeypatch.setattr(at, "_bind_round_after_dispatch", boom_bind)

    with pytest.raises(RuntimeError, match="bind boom"):
        apply_audience_round_translation(
            db, state,
            {
                "on_scene_facts": [{
                    "name": name, "动作": "处置", "status": "imprisoned",
                    "reason": "原子回滚验证",
                }],
            },
            night_id=nid, chat_turn_id=ctid,
        )

    status, _ = db.get_character_status(name)
    assert status == "active", "section 须与 bind 同事务回滚"
    assert db.get_story_extract_status(ctid) != "done"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_turn_rollback_items WHERE chat_turn_id=?",
        (ctid,),
    ).fetchone()["c"] == 0


def test_close_night_no_longer_fail_closed_on_exhausted_pending(game, monkeypatch):
    """0036 修订：待补不 fail-closed；生产同形（llm_config+write_gate）旧抽取不得抢水位。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()

    def boom(prompt, llm_config):
        raise RuntimeError("exhausted")

    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    # 若旧 drain 仍被调用，FactsAgent 会把水位标 done——本测咬住「不得抢」。
    monkeypatch.setattr(
        "ming_sim.agents.create_audience_extractor_agent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("旧故事抽取不得被收夜调用")),
    )

    ctid = _persist_round(db, state, nid, "这句转译会耗尽", "……")
    schedule_audience_turn_translation(
        db, state,
        emperor_message="这句转译会耗尽",
        reply="……",
        night_id=nid, chat_turn_id=ctid,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=boom, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)
    assert db.get_story_extract_status(ctid) == "pending"

    # 生产同形：必传 llm_config + write_gate（旧路径会借此跑故事 drain）
    result = close_night(
        db, state, content=content, registry=None,
        wait_timeout_s=0.0, write_gate=gate,
        llm_config=SimpleNamespace(channel="api", model="x", base_url="", api_key=""),
        translate_fn=boom,
    )
    assert result.get("closed") is True or get_open_night(db) is None
    # 待补仍可查可重试——旧抽取未抢水位
    assert db.get_story_extract_status(ctid) == "pending"
    assert any(int(r["chat_turn_id"]) == ctid for r in list_pending_translations(db, night_id=nid))
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"] == 0
