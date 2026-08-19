"""#498 召对夜容器与故事账本地基——真实入口→DB 末态 tracer。

一条贯穿：web/CLI 会话 seam 与 GameSession 公开颁诏/过回合入口，断言 DB 可观察
结果。覆盖 AC1–10 核心：账本骨架、多夜隔离、完成态与 night_seq 对齐、死账、
员额、AC8 顺势收夜顺序、AC9 崩溃续跑真实任免/候选、AC10 完成等待与超时、旧档迁移。

不锁 LLM 叙事正文；不接受 failed 当成功。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

from ming_sim import audience_night as an
from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    CLOSE_STEP_COMMIT_OFFICE,
    METHOD_XUANRU,
    METHOD_YUECI,
    TAG_AUTO_CLOSE,
    TAG_CLOSE_NIGHT,
    TAG_ENTER,
    TAG_OPEN_NIGHT,
    TAG_STANDING_ROSTER,
    AudienceNightError,
)
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.decree import pre_settle
from ming_sim.session import TurnPhase


def _active_minister(db, content, *, exclude: set[str] | None = None) -> str:
    skip = exclude or set()
    for name, ch in content.characters.items():
        if name in skip:
            continue
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _find_entries(entries, *required_tags):
    need = set(required_tags)
    return [e for e in entries if need.issubset(set(e["tags"]))]


def _real_session(tmp_path, content, name="s"):
    """真实 GameSession（构造即不连 LLM，不建 _partial fake）。返回 sess，用 sess.db/state。"""
    from ming_sim.models import LLMConfig
    from ming_sim.session import GameSession
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    return GameSession(
        db_path=str(tmp_path / f"{name}.db"), llm_config=cfg,
        content=content,
    )


def _land_reply(db, state, minister: str, chat_id: int, text: str = "臣遵旨。") -> None:
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, text),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(chat_id, minister_message_id=int(mid))
    # #501：production 里回话落库后由尾随/收夜前 drain 抽取落账，收夜时无待补。本 #498
    # 时序/隔离用例不涉抽取，直接把水位推到 done 以反映合法收夜前态（否则引擎收夜 drain
    # 闸对未抽回话 fail-closed）。
    db.conn.execute(
        "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?", (int(chat_id),)
    )
    db.conn.commit()


# ── AC1/2/5 开夜→宣人→收夜 ──────────────────────────────────────────


def test_open_summon_close_chain_readable_by_night(game):
    db, state, content = game
    minister = _active_minister(db, content)

    night = an.open_night(
        db, state, time_of_day="戌时", location="乾清宫",
        body="乾清宫灯火初上。",
    )
    an.summon_enter(db, night["id"], minister, method=METHOD_XUANRU)
    an.close_night(db, state, night_id=night["id"], body="秋深夜寒，退朝。")

    loaded = an.get_night(db, night["id"])
    assert loaded["status"] == "closed"
    assert loaded["time_of_day"] == "戌时"
    assert loaded["location"] == "乾清宫"

    entries = an.list_ledger(db, night["id"])
    for e in entries:
        assert isinstance(e["seq"], int)
        assert isinstance(e["person_names"], list)
        assert e["audibility"] in {AUDIBILITY_PUBLIC, an.AUDIBILITY_PRIVATE}
        assert isinstance(e["body"], str)
        assert isinstance(e["tags"], list)
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs)

    assert len(_find_entries(entries, TAG_OPEN_NIGHT)) == 1
    enter_e = _find_entries(entries, TAG_ENTER, METHOD_XUANRU)
    assert any(minister in e["person_names"] for e in enter_e)
    assert len(_find_entries(entries, TAG_CLOSE_NIGHT)) == 1


def test_summon_method_and_bad_method(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="文华殿", time_of_day="午时")
    an.summon_enter(db, night["id"], minister, method=METHOD_YUECI)
    hit = _find_entries(an.list_ledger(db, night["id"]), TAG_ENTER, METHOD_YUECI)
    assert hit and minister in hit[0]["person_names"]
    with pytest.raises(AudienceNightError) as ei:
        an.summon_enter(db, night["id"], minister, method="密召")
    assert ei.value.code == "bad_summon_method"


# ── AC3 多夜隔离 + AC4 timeline ──────────────────────────────────────


def test_two_nights_isolated_and_timeline_alignable(game):
    db, state, content = game
    a = _active_minister(db, content)
    b = _active_minister(db, content, exclude={a})

    n1 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    an.summon_enter(db, n1["id"], a, method=METHOD_XUANRU)
    tid1 = db.create_chat_turn(state, a, "sess-a", 0, night_id=n1["id"])
    _land_reply(db, state, a, tid1)
    an.close_night(db, state, night_id=n1["id"])

    n2 = an.open_night(db, state, location="文华殿", time_of_day="日")
    an.summon_enter(db, n2["id"], b, method=METHOD_XUANRU)
    tid2 = db.create_chat_turn(state, b, "sess-b", 0, night_id=n2["id"])
    _land_reply(db, state, b, tid2)
    an.close_night(db, state, night_id=n2["id"])

    assert n1["id"] != n2["id"]
    n1_persons = {p for e in an.list_ledger(db, n1["id"]) for p in e["person_names"]}
    n2_persons = {p for e in an.list_ledger(db, n2["id"]) for p in e["person_names"]}
    assert a in n1_persons and a not in n2_persons
    assert b in n2_persons and b not in n1_persons
    assert [int(x["id"]) for x in an.list_chat_turns_for_night(db, n1["id"])] == [tid1]
    assert [int(x["id"]) for x in an.list_chat_turns_for_night(db, n2["id"])] == [tid2]

    # AC4：合流 timeline 按 night_seq 单调，chat 与 ledger 同桶
    tl = an.list_night_timeline(db, n1["id"])
    seqs = [int(ev["seq"]) for ev in tl]
    assert seqs == sorted(seqs)
    assert any(ev["kind"] == "chat_turn" for ev in tl)
    assert any(ev["kind"] == "ledger" for ev in tl)
    chat_ev = next(ev for ev in tl if ev["kind"] == "chat_turn")
    assert int(chat_ev["payload"]["night_seq"]) == int(chat_ev["seq"]) > 0

    state.turn_phase = TurnPhase.SUMMONING.value
    pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value


def test_chat_completion_via_attach(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s1", agno_runs_before=0,
        location="便殿", time_of_day="申时",
    )
    row = db.conn.execute("SELECT * FROM chat_turns WHERE id=?", (chat_id,)).fetchone()
    assert int(row["night_id"]) == night_id
    assert row["status"] == "generating"
    assert int(row["night_seq"]) > 0
    _land_reply(db, state, minister, chat_id)
    done = db.conn.execute("SELECT status FROM chat_turns WHERE id=?", (chat_id,)).fetchone()
    assert done["status"] == "active"


def test_attach_without_scene_anchors_persists_readable_defaults(game):
    """真实入口（web/CLI attach）不带玩家选值时，夜容器时辰/地点仍持久非空、可读（#498 AC）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _chat_id = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s1", agno_runs_before=0,
    )
    row = db.conn.execute(
        "SELECT time_of_day, location FROM audience_nights WHERE id=?", (night_id,)
    ).fetchone()
    assert str(row["time_of_day"]).strip()  # 非空可读，非裸空串
    assert str(row["location"]).strip()


# ── AC6/7 死账与员额 ────────────────────────────────────────────────


def test_dead_person_enter_rejected_with_error_pack(game):
    db, state, content = game
    minister = _active_minister(db, content)
    db.set_character_status(state, minister, "dead", reason="测试身故")
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.summon_enter(db, night["id"], minister, method=METHOD_XUANRU)
    assert ei.value.code == "dead_present"
    assert ei.value.error_pack_path
    assert Path(ei.value.error_pack_path).is_dir()


def test_standing_roster_skips_dead(game):
    db, state, content = game
    roster_before = an.resolve_standing_roster(db)
    assert roster_before
    victim = roster_before[0]
    db.set_character_status(state, victim, "dead", reason="测试")
    night = an.open_night(db, state, location="乾清宫")
    names = {
        p
        for e in _find_entries(an.list_ledger(db, night["id"]), TAG_ENTER, TAG_STANDING_ROSTER)
        for p in e["person_names"]
    }
    assert victim not in names


# ── AC8：公开入口顺势收夜（GameSession.resolve_turn / advance）────────


def test_advance_without_edict_auto_closes(game, monkeypatch):
    """AC8：过回合（真实退朝入口 session.advance_without_decree）顺势收夜。

    #1274 r1：prep 归 resolve_turn；本测钉 session 真缝收夜 + 全链推进。
    """
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.session import GameSession

    db, state, content = game
    night = an.open_night(db, state, location="便殿")
    state.turn_phase = TurnPhase.SUMMONING.value
    before = state.turn

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("收夜后无旨月邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", lambda *a, **k: ({}, "o", "i"))
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    sess.advance_without_decree()

    closed = an.get_night(db, night["id"])
    assert closed["status"] == "closed"
    close_e = _find_entries(an.list_ledger(db, night["id"]), TAG_CLOSE_NIGHT)
    assert close_e and TAG_AUTO_CLOSE in close_e[0]["tags"]
    assert state.turn == before + 1


def test_write_decree_leaves_unacted_pending_unchanged(tmp_path, content, monkeypatch):
    """finding3 / #497：拟诏（write_decree）是 preview——不得把未表态 pending directive
    默认同意成 draft、不改其 status；无可用 draft 时响亮拒绝（default-agree 只到真实颁诏/过回合）。"""
    monkeypatch.setattr("ming_sim.session.write_decree_with_agno", lambda *a, **k: "诏曰……")
    sess = _real_session(tmp_path, content, "wd")
    try:
        db, state = sess.db, sess.state
        minister = _active_minister(db, content)
        old_office = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"]
        pid = db.upsert_pending_directive(
            state.turn, minister, payload={**_POLICY_FIELDS, "text": "着户部核边饷", "actor": minister})
        # 无 draft：拟诏响亮拒绝、不为 preview 造持久态
        with pytest.raises(ValueError, match="草案"):
            sess.write_decree()
        # 未表态 pending 原样不动（没被默认同意成 draft）
        assert db.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (pid,)).fetchone()["status"] == "pending"
        assert db.list_directives(state, statuses=("draft",)) == []
    finally:
        sess.close()


def test_cross_night_directive_reassigned_to_second_night(game):
    """同臣跨两夜拟旨：第一夜未应允 directive 留 pending；第二夜复用更新时归属原子迁到第二夜，
    第二夜应允 → 只在第二夜收夜提交，不被旧夜漏挂。"""
    db, state, content = game
    minister = _active_minister(db, content)

    n1 = an.open_night(db, state, location="乾清宫")
    d_id = db.upsert_pending_directive(state.turn, minister, payload={**_POLICY_FIELDS, "text": "初稿：缓征辽饷", "actor": minister})
    # 第一夜不应允 → 留 pending；收夜不提交
    an.close_night(db, state, night_id=n1["id"], content=content)
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (d_id,)).fetchone()["status"] == "pending"

    n2 = an.open_night(db, state, location="文华殿")
    # 同臣同回合复用更新（last-write-wins）→ 归属须迁到第二夜、清 approval
    same_id = db.upsert_pending_directive(state.turn, minister, payload={**_POLICY_FIELDS, "text": "定稿：改折色", "actor": minister})
    assert same_id == d_id
    row = db.conn.execute("SELECT night_id, night_approved FROM pending_actions WHERE id=?", (d_id,)).fetchone()
    assert int(row["night_id"]) == n2["id"]
    assert int(row["night_approved"]) == 0
    # 第二夜应允 + 收夜 → 提交
    assert db.mark_pending_night_approved([d_id], night_id=n2["id"]) == 1
    an.close_night(db, state, night_id=n2["id"], content=content)
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (d_id,)).fetchone()["status"] == "committed"
    drafts = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=? AND status='draft'", (state.turn,)).fetchall()
    assert any("改折色" in (r["text"] or "") for r in drafts)


# ── AC9：真实任免 + 候选转档 + 崩溃续跑 ──────────────────────────────


def test_close_night_crash_then_reopen_db_resumes_idempotent(content):
    """AC9：合法任免已 commit、候选转档前 crash → 关 GameDB、重开续跑收齐；
    真实任免落盘、候选真实转档、单条收夜账、幂等无重复、无半提交终态。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        state = db.load_state()
        minister = _active_minister(db, content)
        old_office = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"]
        night = an.open_night(db, state)

        new_office = "兵部郎中"
        pa_id = db.stage_pending_action(
            state.turn, kind="office", action="任命",
            minister_name=minister,
            payload={
                "name": minister, "office": new_office, "office_type": "六部",
                "faction": "中立", "reason": "测试任免",
            },
        )
        db.mark_pending_night_approved([pa_id], night_id=night["id"])
        dir_id = db.upsert_pending_directive(
            state.turn, minister, payload={**_POLICY_FIELDS, "text": "着户部清查边饷", "actor": minister},
        )
        db.mark_pending_night_approved([dir_id], night_id=night["id"])

        # crash：任免已 commit（step1）、候选转档（step2）前崩
        with pytest.raises(AudienceNightError) as ei:
            an.close_night(
                db, state, night_id=night["id"], content=content,
                crash_after_step=CLOSE_STEP_COMMIT_OFFICE,
            )
        assert ei.value.code == "close_crash"
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"] == old_office
        assert db.list_decree_dossiers(
            status="proposed", target_kind="character", target_id=minister
        )
        db.close()  # 进程崩溃：关库

        # 重开 GameDB / state，从游标续跑（跨进程恢复）
        db2 = GameDB(path, content)
        state2 = db2.load_state()
        mid = an.get_night(db2, night["id"])
        assert mid["status"] == "closing"
        assert int(mid["close_commit_cursor"]) == CLOSE_STEP_COMMIT_OFFICE

        result = an.close_night(db2, state2, night_id=night["id"], content=content)
        assert result["closed"] is True
        final = an.get_night(db2, night["id"])
        assert final["status"] == "closed"
        assert int(final["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE
        # 任免案卷仍在（不因重开丢失）且判决前不改盘 + 候选真实转档
        assert db2.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"] == old_office
        assert db2.list_decree_dossiers(
            status="proposed", target_kind="character", target_id=minister
        )
        assert db2.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (dir_id,),
        ).fetchone()["status"] == "committed"
        drafts = db2.conn.execute(
            "SELECT text FROM turn_directives WHERE turn=? AND status='draft'",
            (state2.turn,),
        ).fetchall()
        assert any("清查边饷" in (r["text"] or "") for r in drafts)
        # 单条收夜账，再收幂等无重复
        assert len(_find_entries(an.list_ledger(db2, night["id"]), TAG_CLOSE_NIGHT)) == 1
        again = an.close_night(db2, state2, night_id=night["id"], content=content)
        assert again.get("already") is True
        assert len(_find_entries(an.list_ledger(db2, night["id"]), TAG_CLOSE_NIGHT)) == 1

        # 真实收夜只负责成案；结算判决入口消费结构化 verdict 后才物化任免。
        dossier = db2.list_decree_dossiers(
            status="proposed", target_kind="character", target_id=minister
        )[0]
        db2.apply_dossier_verdicts(
            state2,
            [{"dossier_id": dossier["id"], "decision": "promulgated"}],
            content=content,
        )
        assert db2.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"] == new_office
        db2.close()
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def test_close_night_only_commits_this_night_approved(game):
    """收夜只交本夜已应允白名单；他夜/未应允项不被串走。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state)
    approved = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister,
        payload={"name": minister, "office": "兵部郎中", "office_type": "六部",
                 "faction": "中立", "reason": "测试"},
    )
    db.mark_pending_night_approved([approved], night_id=night["id"])
    # 未应允项（同回合、另一夜语义）
    unapproved = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister,
        payload={"name": minister, "office": "不该落的官", "office_type": "六部"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET night_id=0, night_approved=0 WHERE id=?", (unapproved,))
    db.conn.commit()

    an.close_night(db, state, night_id=night["id"], content=content)
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (approved,)).fetchone()["status"] == "committed"
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (unapproved,)).fetchone()["status"] == "pending"


def test_closing_cursor0_reopen_refuses_new_and_explicit_resume_commits(content):
    """finding1：status=closing,cursor=0（office 提交前断电）→ 关库重开。
    新召对（open_night 无 content）被响亮拒绝、不隐式封夜丢任免；携 content 的显式续收
    才提交合法已应允任免并封夜。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        state = db.load_state()
        minister = _active_minister(db, content)
        old_office = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,),
        ).fetchone()["office"]
        night = an.open_night(db, state)
        new_office = "兵部郎中"
        pa_id = db.stage_pending_action(
            state.turn, kind="office", action="任命", minister_name=minister,
            payload={"name": minister, "office": new_office, "office_type": "六部",
                     "faction": "中立", "reason": "测试"},
        )
        db.mark_pending_night_approved([pa_id], night_id=night["id"])
        # 断电前态：已 durable 写 status=closing、cursor=0，office 尚未提交
        an._set_night_fields(db, night["id"], status=an.NIGHT_STATUS_CLOSING)
        db.close()

        db2 = GameDB(path, content)
        state2 = db2.load_state()
        assert an.get_night(db2, night["id"])["status"] == "closing"
        # 新召对：open_night 无 content/registry → 响亮拒绝，不隐式封夜、不丢任免
        with pytest.raises(AudienceNightError) as ei:
            an.attach_chat_turn_to_night(
                db2, state2, minister, agno_session_id="new", agno_runs_before=0)
        assert ei.value.code == "night_closing_incomplete"
        assert an.get_night(db2, night["id"])["status"] == "closing"
        assert db2.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (pa_id,)).fetchone()["status"] == "pending"
        # 携 content 的显式续收：合法任免成案并封夜，判决前不改盘
        an.close_night(db2, state2, night_id=night["id"], content=content)
        assert an.get_night(db2, night["id"])["status"] == "closed"
        assert db2.conn.execute(
            "SELECT office FROM characters WHERE name=?", (minister,)).fetchone()["office"] == old_office
        assert db2.list_decree_dossiers(
            status="proposed", target_kind="character", target_id=minister
        )
        assert db2.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (pa_id,)).fetchone()["status"] == "committed"
        db2.close()
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


# ── AC10 在飞回话 × 真实 web 入口 → tests/test_web_audience_night_498.py ──
# 完成回话入档→收夜、挂起 fail-closed 409/夜保持开、同步端点 offload 不冻结 loop、
# 拟诏 preview 不收夜，均走真实 WebGame.chat_stream + 真实 ASGI 路由验证（只 fake LLM）。


# ── 开夜原子 + 旧档迁移 ──────────────────────────────────────────────


def test_open_night_atomic_on_dead_roster_injection(game, monkeypatch):
    """开夜原子：落账失败时不留缺账 open 夜。"""
    db, state, content = game
    real_append = an.append_ledger_entry
    calls = {"n": 0}

    def flaky_append(*args, **kwargs):
        calls["n"] += 1
        # 开夜账成功后，第一条员额账炸掉
        if calls["n"] >= 2 and kwargs.get("tags") and an.TAG_STANDING_ROSTER in kwargs["tags"]:
            raise RuntimeError("inject roster fail")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(an, "append_ledger_entry", flaky_append)
    # 确保有员额可触发
    assert an.resolve_standing_roster(db)
    with pytest.raises(RuntimeError, match="inject roster fail"):
        an.open_night(db, state, location="乾清宫")
    open_n = an.get_open_night(db)
    assert open_n is None
    n_nights = db.conn.execute("SELECT COUNT(*) AS c FROM audience_nights").fetchone()["c"]
    assert int(n_nights) == 0


def test_old_save_migration_night_id_index_order(content):
    """旧档无 night_id 列：ensure_column 后再建索引，重开不炸。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minister_name TEXT NOT NULL,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                user_message_id INTEGER,
                minister_message_id INTEGER,
                agno_session_id TEXT NOT NULL DEFAULT '',
                agno_runs_before INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                undone_at TEXT
            );
            CREATE TABLE game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                turn_phase TEXT NOT NULL DEFAULT 'summoning'
            );
            INSERT INTO game_state (id, year, period, turn) VALUES (1, 1628, 1, 1);
            """
        )
        conn.commit()
        conn.close()
        # 完整 GameDB 初始化会 ensure 列 + 建索引
        db = GameDB(path, content)
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(chat_turns)").fetchall()}
        assert "night_id" in cols
        assert "night_seq" in cols
        # 索引存在
        idxs = {
            r["name"]
            for r in db.conn.execute("PRAGMA index_list(chat_turns)").fetchall()
        }
        assert "idx_chat_turns_night" in idxs
        # 可写挂夜轮
        state = db.load_state()
        minister = _active_minister(db, content)
        night = an.open_night(db, state)
        cid = db.create_chat_turn(state, minister, "migrate", 0, night_id=night["id"])
        row = db.conn.execute(
            "SELECT night_id, night_seq, status FROM chat_turns WHERE id=?", (cid,),
        ).fetchone()
        assert int(row["night_id"]) == night["id"]
        assert row["status"] == "generating"
        db.close()
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


# 结算相位不得召对 + 等 gate 期间相位翻转（TOCTOU）被拒 → 真实 WebGame.chat_stream 验证，
# 见 tests/test_web_audience_night_498.py::test_phase_flip_while_waiting_gate_is_rejected。


# ── 负向 ─────────────────────────────────────────────────────────────


def test_bad_audibility_and_append_after_close(game):
    db, state, content = game
    night = an.open_night(db, state)
    with pytest.raises(AudienceNightError) as ei:
        an.append_ledger_entry(
            db, night["id"], person_names=[], audibility="全知", body="x", tags=["试"],
        )
    assert ei.value.code == "bad_audibility"
    an.close_night(db, state, night_id=night["id"])
    with pytest.raises(AudienceNightError) as ei2:
        an.append_ledger_entry(db, night["id"], body="不该", tags=["试"])
    assert ei2.value.code == "night_closed"


def test_cli_minister_chat_anchors_turn_to_night(game, monkeypatch):
    """CLI 真实输入入口 terminal.minister_chat 起聊 → 对话轮挂夜（非 night_id=0 旁路）。"""
    import ming_sim.cli.terminal as term
    from types import SimpleNamespace

    db, state, content = game
    character = next(c for c in content.characters.values()
                     if db.get_character_status(c.name)[0] == "active"
                     and getattr(c, "power_id", "ming") == "ming"
                     and getattr(c, "office_type", "") != "后宫")

    def chat(_name, _question, chat_turn_id=0):
        assert chat_turn_id > 0  # 挂夜轮以 generating 起笔，回话须带 chat_turn_id
        return SimpleNamespace(
            answer="臣有本奏。", proposed_directive=None, appointed_minister="",
            registered_minister="", displaced_minister="", court_action="",
            next_minister="", secret_order_id=0, pending_action_id=0,
            pending_action_failures=[],
        )

    session = SimpleNamespace(
        db=db, state=state, content=content, temporary_characters=set(), chat=chat,
        # #542 scene lifecycle seams — CLI minister_chat start/join/persist/abandon.
        start_chat_turn_scene=lambda *_a, **_k: None,
        start_chat_turn_exit_scene=lambda *_a, **_k: None,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
    )
    answers = iter(["朕问卿边事如何？", "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(session, character) == "dismiss"

    open_n = an.get_open_night(db)
    assert open_n is not None
    turns = an.list_chat_turns_for_night(db, int(open_n["id"]))
    assert turns and turns[-1]["minister_name"] == character.name
    assert int(turns[-1]["night_id"]) == int(open_n["id"]) > 0
