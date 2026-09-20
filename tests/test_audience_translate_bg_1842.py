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
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    NIGHT_STATUS_CLOSING,
    NIGHT_STATUS_OPEN,
    close_night,
    get_night,
    get_open_night,
    open_night,
)
from ming_sim.audience_translate import (
    build_audience_translate_prompt,
    normalize_audience_declaration,
)
from ming_sim.audience_translation import (
    abandon_owner_translations,
    catch_up_pending_translations,
    join_all_translations,
    join_night_translations,
    join_owner_translations,
    list_pending_translations,
    schedule_audience_turn_translation,
    translation_owner_key,
)
from ming_sim.session import GameSession
import ming_sim.audience_translation as _at_mod


def _reclaim_owner_translations(owner_key: int, *, timeout_s: float = 2.0) -> None:
    """本测所有权收口：owner-scoped join；超时则 abandon 并响亮失败。"""
    owner = int(owner_key)
    if join_owner_translations(owner, timeout_s=timeout_s):
        return
    abandoned = abandon_owner_translations(owner)
    pytest.fail(
        f"owner={owner} translations did not drain within {timeout_s}s; "
        f"abandoned={abandoned}"
    )


@pytest.fixture(autouse=True)
def _join_audience_translations_after_test():
    """防止后台 worker 在 game fixture 拆库后仍写共享 content。

    用既有 owner-scoped join/abandon 收本测残留；超时或 False 响亮失败，
    不得静默遗留（P2）。
    """
    yield
    with _at_mod._night_inflight_guard:
        owners = sorted({key[0] for key in _at_mod._night_inflight})
    stuck: list[int] = []
    for owner in owners:
        if not join_owner_translations(owner, timeout_s=2.0):
            abandon_owner_translations(owner)
            stuck.append(owner)
    if stuck:
        pytest.fail(
            f"audience translation teardown: owners still inflight after join; "
            f"abandoned={stuck}"
        )
    assert join_all_translations(timeout_s=0.0), (
        "audience translation teardown: residual inflight after owner reclaim"
    )


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
    # 未知顶层键原样保留，交既有分派器 durable invalid_shape（见 1837 tracer）
    assert decl.get("noise") == 1
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
    owner = translation_owner_key(gate, db)
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

    try:
        # 串行队列：先调度 t1（会卡住），再调度 t2；前台调度返回时 t1 仍在飞。
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
        assert started.wait(timeout=2.0), "t1 须已进入转译"
        assert not fut1.done(), "调度返回时 t1 仍在飞"
        assert db.get_story_extract_status(ctid1) == "pending"

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
        # 第二次调度返回时 t1 仍未完成——确定性证明前台未等（禁墙钟 SLA）
        assert not fut1.done(), "第二次调度返回时 t1 仍在飞"
        assert "t1-done" not in order
        assert db.get_story_extract_status(ctid1) == "pending"

        release.set()
        assert join_night_translations(nid, timeout_s=3.0, owner_key=owner)
        assert fut1.result(timeout=0.1) is not None
        assert fut2.result(timeout=0.1) is not None
        # 按轮串行：t2 不得在 t1 完成前跑
        assert order.index("t1-done") < order.index("t2-run")

        status, _reason = db.get_character_status(name)
        assert status == "imprisoned"
        assert db.get_story_extract_status(ctid1) == "done"
        assert db.get_story_extract_status(ctid2) == "done"
    finally:
        release.set()
        _reclaim_owner_translations(owner, timeout_s=3.0)


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
    entered_last = threading.Event()
    owner = translation_owner_key(gate, db)

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
        # 应允轮：进入阻塞接缝后再等 join 放行——模拟封夜时转译仍在飞
        entered_last.set()
        release.wait(timeout=5.0)
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

    try:
        ctid1 = _persist_round(db, state, nid, "任命并拨银赈灾", "臣等领旨。")
        schedule_audience_turn_translation(
            db, state,
            emperor_message="任命并拨银赈灾",
            reply="臣等领旨。",
            night_id=nid, chat_turn_id=ctid1,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn, write_gate=gate,
        )
        assert join_night_translations(nid, timeout_s=2.0, owner_key=owner)

        ctid2 = _persist_round(db, state, nid, "准", "遵旨。")
        schedule_audience_turn_translation(
            db, state,
            emperor_message="准",
            reply="遵旨。",
            night_id=nid, chat_turn_id=ctid2,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn, write_gate=gate,
        )
        assert entered_last.wait(timeout=2.0), "末轮转译须先进入阻塞接缝"

        # 成案前应允尚未落（转译仍在飞）
        assert db.conn.execute(
            "SELECT night_approved FROM pending_actions ORDER BY id LIMIT 1"
        ).fetchone()["night_approved"] == 0

        import ming_sim.audience_translation as at
        real_join_night = at.join_night_translations

        def join_and_release(night_id, *, timeout_s=120.0, owner_key=None):
            # close 已入 join：放行在飞转译，再走真实 join（禁 Timer 猜时序）
            release.set()
            return real_join_night(
                night_id, timeout_s=timeout_s, owner_key=owner_key,
            )

        monkeypatch.setattr(at, "join_night_translations", join_and_release)

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
    finally:
        release.set()
        _reclaim_owner_translations(owner, timeout_s=3.0)


def test_independent_owners_same_night_id_do_not_block_each_other(
    game, content, _game_template_path, monkeypatch,
):
    """断根：两独立会话同 night_id，一方阻塞不妨碍另一方 join/封夜。"""
    import os
    import shutil
    import tempfile

    from ming_sim.db import GameDB

    db_a, state_a, _ = game
    night_a = open_night(db_a, state_a, location="乾清宫", time_of_day="夜")
    nid_a = int(night_a["id"])
    gate_a = threading.Lock()
    release_a = threading.Event()

    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )

    fd, path_b = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_b = None
    owner_a = translation_owner_key(gate_a, db_a)
    owner_b = None
    try:
        shutil.copyfile(_game_template_path, path_b)
        db_b = GameDB(path_b, content)
        state_b = db_b.load_state()
        night_b = open_night(db_b, state_b, location="乾清宫", time_of_day="夜")
        nid_b = int(night_b["id"])
        # 同号夜是本案刀口；模板同核开局夜号应同为 1。
        assert nid_a == nid_b == 1
        gate_b = threading.Lock()

        entered_a = threading.Event()

        def translate_a(prompt, llm_config):
            entered_a.set()
            release_a.wait(timeout=5.0)
            return {"commissions": [], "promises": []}

        def translate_b(prompt, llm_config):
            return {
                "commissions": [{"text": "乙档交办"}],
                "promises": [],
            }

        owner_b = translation_owner_key(gate_b, db_b)
        assert owner_a != owner_b

        ctid_a = _persist_round(db_a, state_a, nid_a, "甲档阻塞", "……")
        schedule_audience_turn_translation(
            db_a, state_a,
            emperor_message="甲档阻塞",
            reply="……",
            night_id=nid_a, chat_turn_id=ctid_a,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_a, write_gate=gate_a,
        )
        assert entered_a.wait(timeout=2.0), "甲档转译须先进入阻塞接缝"
        # 甲仍在飞：timeout_s=0 桶非空则即时 False（禁墙钟短超时）
        assert not join_night_translations(
            nid_a, timeout_s=0.0, owner_key=owner_a,
        )

        ctid_b = _persist_round(db_b, state_b, nid_b, "乙档快走", "领旨。")
        # 同号源轮是撤回隔离刀口；模板同核首轮应为同 id。
        assert ctid_a == ctid_b
        schedule_audience_turn_translation(
            db_b, state_b,
            emperor_message="乙档快走",
            reply="领旨。",
            night_id=nid_b, chat_turn_id=ctid_b,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_b, write_gate=gate_b,
        )
        # 撤甲不得撤到乙（同 chat_turn_id、异 owner）
        from ming_sim.audience_translation import cancel_turn_translation
        assert cancel_turn_translation(ctid_a, owner_key=owner_a) == 1
        assert join_owner_translations(owner_b, timeout_s=2.0)
        assert db_b.get_story_extract_status(ctid_b) == "done"
        # 甲被撤后仍未落 done（worker 放行后复查死轮/空桶）
        assert db_a.get_story_extract_status(ctid_a) == "pending"

        # 乙可封夜，不因甲同夜号互等
        result = close_night(
            db_b, state_b, content=content, registry=None,
            wait_timeout_s=0.0, write_gate=gate_b,
        )
        assert result.get("closed") is True or get_open_night(db_b) is None
        assert db_a.get_story_extract_status(ctid_a) == "pending"
    finally:
        release_a.set()
        _reclaim_owner_translations(owner_a, timeout_s=2.0)
        if owner_b is not None:
            _reclaim_owner_translations(owner_b, timeout_s=2.0)
        if db_b is not None:
            db_b.close()
        for p in (path_b, f"{path_b}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def test_close_night_stays_open_until_translation_barrier_clears(game, monkeypatch):
    """断根：join 未清空不得置 CLOSING；清空后沿同一路径收夜。"""
    import ming_sim.audience_translation as at

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    release = threading.Event()
    entered_translate = threading.Event()
    saw_join_retry = threading.Event()
    join_calls = {"n": 0}
    owner = translation_owner_key(gate, db)

    def translate_fn(prompt, llm_config):
        entered_translate.set()
        release.wait(timeout=5.0)
        return {"commissions": [], "promises": []}

    real_join_night = at.join_night_translations

    def join_while_blocked(night_id, *, timeout_s=120.0, owner_key=None):
        # 已知 worker 仍阻塞：即时 False 迫使 while 重入（禁墙钟短超时造 False）。
        # 旧语义单次 join False 直推 CLOSING 永不 ≥2 → saw_join_retry 超时红。
        join_calls["n"] += 1
        if join_calls["n"] >= 2:
            saw_join_retry.set()
        if not release.is_set():
            return False
        return real_join_night(
            night_id, timeout_s=timeout_s, owner_key=owner_key,
        )

    monkeypatch.setattr(at, "join_night_translations", join_while_blocked)
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )

    worker = None
    try:
        ctid = _persist_round(db, state, nid, "屏障未清", "……")
        schedule_audience_turn_translation(
            db, state,
            emperor_message="屏障未清",
            reply="……",
            night_id=nid, chat_turn_id=ctid,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn, write_gate=gate,
        )
        assert entered_translate.wait(timeout=2.0), "转译须先进入阻塞接缝"
        # timeout_s=0：桶非空则即时 False（不耗尽墙钟）
        assert not real_join_night(nid, timeout_s=0.0, owner_key=owner)

        outcome: dict = {}

        def _run_close():
            try:
                outcome["result"] = close_night(
                    db, state, content=content, registry=None,
                    wait_timeout_s=0.0, write_gate=gate,
                )
            except Exception as exc:  # noqa: BLE001
                outcome["err"] = exc

        worker = threading.Thread(target=_run_close, daemon=True)
        worker.start()
        try:
            # while 续等真实发生后再断言外部态——单次 join 旧语义永不重入→超时红。
            assert saw_join_retry.wait(timeout=2.0), "close_night 须 while 重入 join（≥2）"
            row = get_night(db, nid)
            assert row is not None
            status = str(row["status"] or "")
            assert status == NIGHT_STATUS_OPEN
            assert status != NIGHT_STATUS_CLOSING, "屏障未清不得 CLOSING"
            assert worker.is_alive(), "close_night 应仍在等屏障"
            assert join_calls["n"] >= 2
        finally:
            # 变异红/断言失败亦须放行，避免 join_while_blocked 即时 False 热自旋卡 teardown
            release.set()
        worker.join(timeout=4.0)
        assert not worker.is_alive(), outcome
        assert outcome.get("err") is None, outcome
        assert outcome.get("result", {}).get("closed") is True or get_open_night(db) is None
        assert db.get_story_extract_status(ctid) == "done"
    finally:
        release.set()
        _reclaim_owner_translations(owner, timeout_s=3.0)
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)


def test_catch_up_query_exception_stays_pending_and_is_loud(game, monkeypatch):
    """断根：源轮查询异常响亮上抛，轮次保持 pending，不洗成空原话转译。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    translated = {"n": 0}

    def translate_fn(prompt, llm_config):
        translated["n"] += 1
        return {"commissions": [], "promises": []}

    ctid = _persist_round(db, state, nid, "查询炸", "……")
    # 人工标 pending（模拟耗尽后待补）
    db.mark_story_extraction_pending(ctid)
    assert db.get_story_extract_status(ctid) == "pending"

    real_execute = db.conn.execute

    def boom_execute(sql, params=()):
        if "SELECT user_message_id FROM chat_turns" in str(sql):
            raise RuntimeError("simulated chat_turns query failure")
        return real_execute(sql, params)

    monkeypatch.setattr(db.conn, "execute", boom_execute)

    with pytest.raises(RuntimeError, match="simulated chat_turns query failure"):
        catch_up_pending_translations(
            db, state,
            night_id=nid,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn,
            write_gate=gate,
        )
    assert translated["n"] == 0
    assert db.get_story_extract_status(ctid) == "pending"


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
    owner = translation_owner_key(gate, db)

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

    try:
        result = sess.scene_chat("边事如何？", chat_turn_id=ctid)
        assert result.answer == "臣等在。"
        # 前台已返回且转译仍被挡住 → 确定性证明未同步等待（禁墙钟 SLA）
        assert not release.is_set()
        assert db.get_story_extract_status(ctid) == "pending"
        assert ran.wait(timeout=1.0), "后台转译须已启动"
        release.set()
        assert join_night_translations(nid, timeout_s=2.0, owner_key=owner)
        assert db.get_story_extract_status(ctid) == "done"
    finally:
        release.set()
        _reclaim_owner_translations(owner, timeout_s=2.0)


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
    entered_translate = threading.Event()
    name = _active_name(db, content)
    saw_join = threading.Event()
    owner = translation_owner_key(gate, db)

    def translate_fn(prompt, llm_config):
        entered_translate.set()
        release.wait(timeout=5.0)
        return {
            "on_scene_facts": [{
                "name": name, "动作": "处置", "status": "imprisoned",
                "reason": "过月前 join 落定",
            }],
        }

    try:
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
        assert entered_translate.wait(timeout=2.0), "转译须先进入阻塞接缝"

        import ming_sim.audience_translation as at
        real_join = at.join_owner_translations

        def tracking_join(owner_key, *, timeout_s=120.0):
            # resolve 已入 join：放行在飞转译，再走真实 join（禁 Timer 猜时序）
            release.set()
            ok = real_join(owner_key, timeout_s=timeout_s)
            saw_join.set()
            return ok

        monkeypatch.setattr(at, "join_owner_translations", tracking_join)

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

        with pytest.raises(_StopAfterJoin):
            sess.resolve_turn(allow_empty_decree=True)

        assert saw_join.is_set(), "resolve_turn 必须调用 join_owner_translations"
        assert db.get_story_extract_status(ctid) == "done"
        status, _ = db.get_character_status(name)
        assert status == "imprisoned"
    finally:
        release.set()
        # tracking_join 可能仍挂着；收口走真实 join_owner
        monkeypatch.setattr(
            "ming_sim.audience_translation.join_owner_translations",
            join_owner_translations,
        )
        _reclaim_owner_translations(owner, timeout_s=3.0)


def test_resolve_turn_incomplete_join_waits_then_continues(game, monkeypatch):
    """类1①：真实在飞 → 闸外等完自动续跑；持闸只在 join 清空后（生产 entry 形）。"""
    db, state, content = game
    before_turn = int(state.turn)
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    release_llm = threading.Event()
    entered_translate = threading.Event()
    saw_incomplete_join = threading.Event()
    name = _active_name(db, content)
    owner = translation_owner_key(gate, db)
    import ming_sim.audience_translation as at

    def translate_fn(prompt, llm_config):
        # LLM 窗无锁；落账短持 write_gate。屏障未放行前保持在飞，迫使短 join False。
        entered_translate.set()
        release_llm.wait(timeout=5.0)
        return {
            "on_scene_facts": [{
                "name": name, "动作": "处置", "status": "imprisoned",
                "reason": "闸外等待后自动续跑",
            }],
        }

    try:
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
        assert entered_translate.wait(timeout=2.0), "转译须先进入阻塞接缝"

        real_join = at.join_owner_translations

        def join_while_blocked(owner_key, *, timeout_s=120.0):
            # 已知 LLM 窗仍阻塞：即时 False（禁 0.4s 墙钟造 incomplete）；放行后走真实 join。
            if not release_llm.is_set():
                saw_incomplete_join.set()
                return False
            return real_join(owner_key, timeout_s=timeout_s)

        monkeypatch.setattr(at, "join_owner_translations", join_while_blocked)

        class _StopAfterCatch(Exception):
            pass

        real_catch = at.catch_up_pending_translations
        catch_calls = {"n": 0}

        def catch_maybe_stop(*a, **k):
            # 第一次：闸外 await 真实 catch-up；第二次：持闸 resolve 内截断
            catch_calls["n"] += 1
            out = real_catch(*a, **k)
            if catch_calls["n"] >= 2:
                raise _StopAfterCatch()
            return out

        monkeypatch.setattr(at, "catch_up_pending_translations", catch_maybe_stop)

        sess = _sess(db, state, content, translate_fn=translate_fn, write_gate=gate)
        sess._begun = True
        sess.last_decree = ""
        sess._decree_draft_fingerprint = ()
        sess.deaths_this_turn = []
        sess.debuts_this_turn = []
        sess.previous_summary = ""
        sess.agno_db = None

        outcome = {"err": None}

        def run_production_shape():
            # 生产形（_settlement_period_entry）：闸外 await → 再持闸跑 body/resolve
            try:
                sess.await_translations_before_month()
                with gate:
                    # 持闸下再 resolve：join 已清空，立即续跑；不得自锁/Abort
                    sess.resolve_turn(allow_empty_decree=True)
            except _StopAfterCatch:
                outcome["err"] = "stop"
            except Exception as exc:  # noqa: BLE001
                outcome["err"] = exc

        worker = threading.Thread(target=run_production_shape, daemon=True)
        worker.start()
        try:
            # 先确认 join 至少一次未清空（while 续等），再放行转译——禁 sleep 猜时序。
            assert saw_incomplete_join.wait(timeout=2.0), "须至少一次 join 未清空"
        finally:
            # 变异红/断言失败亦须放行，避免即时 False 热自旋卡 teardown
            release_llm.set()
        worker.join(timeout=4.0)
        hung = worker.is_alive()
        if hung:
            try:
                if gate.locked():
                    gate.release()
            except RuntimeError:
                pass
            monkeypatch.setattr(at, "join_owner_translations", real_join)
            _reclaim_owner_translations(owner, timeout_s=1.0)
            worker.join(timeout=1.0)

        assert not hung, "闸外等 join 后持闸 resolve 不得自锁"
        assert outcome["err"] == "stop", f"须等完进 catch-up 后续跑，得 {outcome['err']!r}"
        assert db.get_story_extract_status(ctid) == "done"
        status, _ = db.get_character_status(name)
        assert status == "imprisoned"
        assert int(state.turn) == before_turn
        assert not gate.locked(), "不得悬持 write_gate"
    finally:
        release_llm.set()
        monkeypatch.setattr(
            "ming_sim.audience_translation.join_owner_translations",
            join_owner_translations,
        )
        _reclaim_owner_translations(owner, timeout_s=3.0)


def test_await_translations_does_not_steal_worker_write_gate(game, monkeypatch):
    """反案：调用方未持闸 + worker 落账持闸 → 不得 release 偷放后悬持。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    entered_apply = threading.Event()
    hold_apply = threading.Event()
    owner = translation_owner_key(gate, db)
    import ming_sim.audience_translation as at

    def translate_fn(prompt, llm_config):
        return {"commissions": [], "promises": []}

    real_apply = at.apply_audience_round_translation

    def blocked_apply(*a, **k):
        # 已在 run_turn_translation_job 的 with write_gate 内；事件拖住持闸窗（禁 sleep）。
        entered_apply.set()
        hold_apply.wait(timeout=5.0)
        return real_apply(*a, **k)

    monkeypatch.setattr(at, "apply_audience_round_translation", blocked_apply)

    try:
        ctid = _persist_round(db, state, nid, "反偷放", "……")
        schedule_audience_turn_translation(
            db, state,
            emperor_message="反偷放",
            reply="……",
            night_id=nid, chat_turn_id=ctid,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn, write_gate=gate,
        )

        assert entered_apply.wait(timeout=2.0), "worker 须进入 apply 持闸窗"
        assert gate.locked(), "worker 应正在持 write_gate 落账"

        real_join = at.join_owner_translations

        def join_and_release(owner_key, *, timeout_s=120.0):
            # await 已入 join：放行持闸 apply，再走真实 join
            hold_apply.set()
            return real_join(owner_key, timeout_s=timeout_s)

        monkeypatch.setattr(at, "join_owner_translations", join_and_release)

        sess = _sess(db, state, content, translate_fn=translate_fn, write_gate=gate)
        sess._begun = True
        sess.last_decree = ""
        sess._decree_draft_fingerprint = ()
        sess.deaths_this_turn = []
        sess.debuts_this_turn = []
        sess.previous_summary = ""
        sess.agno_db = None

        class _Stop(Exception):
            pass

        def catch_stop(*a, **k):
            raise _Stop()

        monkeypatch.setattr(at, "catch_up_pending_translations", catch_stop)

        # 调用方不持闸（CLI/直调形）；等待期间 worker 持闸——不得偷放
        err = None
        try:
            sess.await_translations_before_month()
        except _Stop:
            err = "stop"
        except Exception as exc:  # noqa: BLE001
            err = exc

        assert err == "stop"
        assert not gate.locked(), "await 返回后 write_gate 不得被偷放后悬持"
        assert db.get_story_extract_status(ctid) == "done"
    finally:
        hold_apply.set()
        monkeypatch.setattr(
            "ming_sim.audience_translation.join_owner_translations",
            join_owner_translations,
        )
        _reclaim_owner_translations(owner, timeout_s=2.0)


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
    monkeypatch.setattr(
        at, "join_owner_translations",
        lambda owner_key, *, timeout_s=120.0: True,
    )
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


def test_said_so_far_cuts_off_at_source_turn_and_excludes_self(game):
    """正确性 C2：生产 worker 路径 — 后轮已落库时，源轮转译 prompt 不含后轮/本轮正文。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    ctid1 = _persist_round(db, state, nid, "第一句已说", "第一答")
    ctid2 = _persist_round(db, state, nid, "第二句本轮", "第二答")
    ctid3 = _persist_round(db, state, nid, "第三句后轮", "第三答")

    seen: list[str] = []

    def translate_fn(prompt, llm_config):
        seen.append(prompt)
        return {"commissions": [], "promises": []}

    # 后轮已在库；调度本轮转译（生产 schedule→worker 缝，非直调 build_*）。
    fut = schedule_audience_turn_translation(
        db, state,
        emperor_message="第二句本轮",
        reply="第二答",
        night_id=nid, chat_turn_id=ctid2,
        llm_config=SimpleNamespace(channel="api"),
        translate_fn=translate_fn, write_gate=gate,
    )
    assert join_night_translations(nid, timeout_s=2.0)
    fut.result(timeout=0.5)
    assert seen, "worker 须调用 translate_fn"
    prompt = seen[0]
    # 本轮只走【本轮皇帝】【本轮回话】
    assert "【本轮皇帝】第二句本轮" in prompt
    assert "【本轮回话】第二答" in prompt
    # 先前轮可在已说
    assert "第一句已说" in prompt or "第一答" in prompt
    # 后轮不得入已说；本轮正文不得在已说区重复（只在本轮字段）
    said_block = prompt.split("【本夜暂存清单】")[0]
    assert "第三句后轮" not in said_block and "第三答" not in said_block, said_block
    # 已说区不得再抄本轮（防与本轮字段双挂）
    assert "第二句本轮" not in said_block.split("【本场已说的话】")[-1].split("【本轮皇帝】")[0]


def test_undo_cancels_inflight_translation_and_write_gate_blocks_dead_turn(game):
    """正确性 C1：撤回终结在飞转译；落账前复查源轮已死则不落。"""
    from ming_sim.audience_translation import cancel_turn_translation
    import ming_sim.audience_translation as at_mod

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    gate = threading.Lock()
    owner = translation_owner_key(gate, db)
    hold = threading.Event()
    entered = threading.Event()
    applied = {"n": 0}

    def translate_fn(prompt, llm_config):
        entered.set()
        assert hold.wait(timeout=2.0)
        return {
            "commissions": [{"text": "不该落的交办"}],
            "promises": [],
        }

    real_apply = at_mod.apply_audience_round_translation

    def counting_apply(*a, **k):
        applied["n"] += 1
        return real_apply(*a, **k)

    at_mod.apply_audience_round_translation = counting_apply
    try:
        ctid = _persist_round(db, state, nid, "撤回我", "……")
        fut = schedule_audience_turn_translation(
            db, state,
            emperor_message="撤回我",
            reply="……",
            night_id=nid, chat_turn_id=ctid,
            llm_config=SimpleNamespace(channel="api"),
            translate_fn=translate_fn, write_gate=gate,
        )
        assert entered.wait(timeout=2.0)
        n = cancel_turn_translation(ctid, owner_key=owner)
        assert n == 1
        db.conn.execute(
            "UPDATE chat_turns SET status='undone', undone_at=CURRENT_TIMESTAMP WHERE id=?",
            (ctid,),
        )
        db.conn.commit()
        hold.set()
        join_night_translations(nid, timeout_s=2.0, owner_key=owner)
        try:
            fut.result(timeout=0.5)
        except Exception:
            pass
        assert applied["n"] == 0, "死轮不得 apply 落账"
    finally:
        at_mod.apply_audience_round_translation = real_apply
        hold.set()
        _reclaim_owner_translations(owner, timeout_s=2.0)


def test_web_hall_chat_routes_to_scene_chat(game, monkeypatch):
    """完整性：Web 非流/重试/流式真实入口 → scene_chat，外部结果可见；旧四机制零调用。"""
    import web_app as wa
    from types import SimpleNamespace as NS
    from ming_sim.audience_night import open_night

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    name = next(iter(content.characters))
    calls = {"scene": 0, "chat": 0, "judge": 0, "extract": 0, "mind": 0, "intent": 0}

    class FakeResult:
        answer = "殿上戏文"
        court_action = ""
        next_minister = ""
        proposed_directive = None
        appointed_minister = ""
        registered_minister = ""
        displaced_minister = ""
        secret_order_id = 0
        pending_action_id = 0
        pending_action_failures = []
        directive_confirmation_ambiguous = None
        decree_validation_failure = None
        secret_order_landing_recovery = None

    # 真 WebGame 生命周期方法；session.scene_chat 计数
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = NS(get=lambda *a, **k: NS(run=lambda *a, **k: NS(content="x", tools=[])), session_ids={})
    sess.llm_config = NS(channel="api", base_url="", model="t", api_key="")
    sess.temporary_characters = set()
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = threading.Lock()
    sess._audience_translate_fn = lambda p, c: {"commissions": [], "promises": []}

    def _scene_chat(message, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        calls["scene"] += 1
        # 流式入口可经 stream_emit 推 delta；契约只计 scene 调用与 answer。
        if stream_emit is not None:
            stream_emit(FakeResult.answer, replace=False)
        return FakeResult()

    def _chat(*a, **k):
        calls["chat"] += 1
        return FakeResult()

    sess.scene_chat = _scene_chat
    sess.chat = _chat
    sess._character = lambda n: content.characters[n]
    sess.consume_audience_admission = lambda *a, **k: NS(allowed=True, reason="", result=None)
    sess.admit_audience = lambda *a, **k: NS(allowed=True, reason="", result=None)
    sess.join_chat_turn_scene = lambda *a, **k: []
    sess.persist_chat_turn_scene = lambda *a, **k: None
    sess.abandon_chat_turn_scene = lambda *a, **k: None
    sess.close_night_after_chat_if_needed = lambda *a, **k: None
    sess.start_chat_turn_scene = lambda *a, **k: None
    sess.note_chat_rollback = lambda **k: None
    sess.refresh_runtime_after_chat_rollback = lambda: None
    sess._start_cli_action_intent = lambda *a, **k: calls.__setitem__("intent", calls["intent"] + 1)

    wg = wa.WebGame.__new__(wa.WebGame)
    wg.session = sess
    wg.chat_history = {n: [] for n in content.characters}
    from ming_sim.session_write_queue import SessionWriteQueue
    wg._write_queue = SessionWriteQueue()
    wg._write_gate = wg._write_queue.write_gate
    wg._runtime_write_queue = lambda: wg._write_queue
    wg._runtime_write_gate = lambda: wg._write_gate
    wg._ticketed_write_gate = lambda ticket=None: wg._write_gate
    wg._mark_pending_write = lambda key=None: wg._write_queue.claim(key=key or ("pending",))
    wg._complete_pending_write = lambda ticket=None: wg._write_queue.complete(ticket)
    wg._reject_if_settlement_phase = lambda: None
    wg._audience_turn_in_flight = lambda *a, **k: False
    wg._persistent_chat_minister = lambda n: True
    wg._message_is_formal_secret_order = lambda t: False
    wg._open_night_court_break = lambda t: False
    wg.favorites = set()
    wg.suggestions_for = lambda _c: []
    wg._trail_highlight_judge_after_reply = lambda *a, **k: []
    wg._spawn_pending_write_thread = lambda *a, **k: None
    # 旧四机制：若生产仍调用则计数
    wg._dispatch_relation_judge = lambda *a, **k: calls.__setitem__("judge", calls["judge"] + 1)
    wg._spawn_extraction_trail = lambda *a, **k: calls.__setitem__("extract", calls["extract"] + 1) or None
    wg._trail_mindreading_after_reply = lambda *a, **k: calls.__setitem__("mind", calls["mind"] + 1)
    wg._finish_offsite_summon_scene = lambda *a, **k: None
    wg._summon_admission_success_payload = lambda *a, **k: {}
    # 用真 _start_chat_turn / _chat_payload / chat 方法
    import types
    for meth in (
        "_start_chat_turn", "_chat_payload", "_chat_core", "chat",
        "_record_chat_rollback_items", "_scene_chat_stream_payload",
        "chat_projection", "can_undo_last_chat", "pending_action_failures_for",
        "directive_rows", "directive_payload", "pending_directive_count",
        "_minister_agno_session_id", "_fail_chat_turn_and_reload",
    ):
        if hasattr(wa.WebGame, meth):
            setattr(wg, meth, types.MethodType(getattr(wa.WebGame, meth), wg))

    # 1) 非流式真实入口
    calls["scene"] = calls["chat"] = calls["judge"] = calls["extract"] = calls["mind"] = 0
    out = wg.chat(name, "边事如何？")
    assert calls["scene"] == 1, calls
    assert calls["chat"] == 0, calls
    assert calls["judge"] == 0 and calls["extract"] == 0 and calls["mind"] == 0, calls
    assert out.get("answer") == "殿上戏文"

    # 2) 流式 payload 入口（chat_stream worker 同核）
    calls["scene"] = 0
    deltas: list[str] = []
    payload = wg._scene_chat_stream_payload(
        name, "再问一句", 0, {}, int(state.turn),
        lambda d, replace=False: deltas.append(d),
        write_gate=wg._write_gate,
    )
    assert calls["scene"] == 1
    assert payload.get("answer") == "殿上戏文"
    assert "殿上戏文" in "".join(deltas)

    # 3) 重试入口：造 interrupted 轮后走 retry_interrupted_reply
    from ming_sim.audience_night import attach_chat_turn_to_night
    # 建一条 interrupted 轮（有问无答）
    agno = "s"
    uid = int(db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'user', ?, 'held')",
        (name, int(state.turn), "中断问话"),
    ).lastrowid)
    ctid = int(db.create_chat_turn(
        state, name, agno, 0, night_id=int(night["id"]), status="generating",
    ))
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=NULL, "
        "status='interrupted' WHERE id=?",
        (uid, ctid),
    )
    db.conn.commit()
    # bind retry method
    wg.retry_interrupted_reply = types.MethodType(wa.WebGame.retry_interrupted_reply, wg)
    wg.interrupted_reply_retries = types.MethodType(wa.WebGame.interrupted_reply_retries, wg)
    if hasattr(db, "reopen_interrupted_chat_turn_for_retry"):
        # 某些实现要 CAS
        pass
    calls["scene"] = calls["chat"] = calls["judge"] = calls["extract"] = calls["mind"] = 0
    try:
        rout = wg.retry_interrupted_reply(name)
        assert calls["scene"] == 1, calls
        assert calls["chat"] == 0, calls
        assert calls["judge"] == 0 and calls["extract"] == 0 and calls["mind"] == 0, calls
        assert rout.get("answer") == "殿上戏文"
    except Exception as exc:
        # 若 interrupted 列表空或 CAS 失败，至少非流+stream 已证入口
        # 但本构造应成功；失败则响亮
        raise AssertionError(f"retry 入口未接通 scene_chat: {exc}") from exc
