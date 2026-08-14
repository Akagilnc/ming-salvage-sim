import json
import threading
import pytest

from ming_sim import agents as agents_mod
from ming_sim import audience_night as an
from ming_sim.audience_extraction import (
    ExtractionShapeError,
    catch_up_pending_extractions,
    parse_endorsement_batch,
    parse_extraction_facts,
    run_endorsement_batch_for_night,
    run_extraction_for_turn,
    trail_extraction_after_reply,
)
from ming_sim.db import GameDB
from ming_sim.decree import advance_without_edict, build_promulgation_judge_context


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _night_reply(db, state, minister, reply="臣愿会签此旨。"):
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    an.ensure_summon_enter(db, night_id, minister)
    chat_turn_id = db.create_chat_turn(
        state, minister, "endorsement-612", 0, night_id=night_id,
    )
    db.persist_minister_reply(minister, state.turn, reply, chat_turn_id)
    row = db.conn.execute("SELECT night_seq FROM chat_turns WHERE id=?", (chat_turn_id,)).fetchone()
    return night_id, chat_turn_id, int(row["night_seq"] or 0)


def _extract(db, *, minister, reply, chat_turn_id, night_id, seq, fact):
    return run_extraction_for_turn(
        db=db, minister_name=minister, reply=reply,
        chat_turn_id=chat_turn_id, night_id=night_id, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_Agent({"facts": [fact]}),
    )


def _bind_endorsements(db, night_id, endorsements, *, agent=None):
    payload = {"endorsements": endorsements}
    return run_endorsement_batch_for_night(
        db=db, night_id=night_id, llm_config=object(),
        write_gate=threading.Lock(),
        extractor_agent=agent or _Agent(payload),
    )


class _Agent:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, materials):
        self.calls.append(materials if isinstance(materials, str) else str(materials))
        return json.dumps(self.payload, ensure_ascii=False)


def test_spoken_cosign_is_persisted_restored_and_read_by_promulgation_judge(game):
    db, state, content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="liao-pay",
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    story = _extract(
        db, minister=minister, reply="臣愿会签此旨。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={
            "body": "大臣当殿愿为辽饷旨意会签。", "person_names": [minister],
            "tags": ["会签"],
        },
    )
    assert story["status"] == "done"
    assert db.list_dossier_endorsements(dossier_id) == []

    bound = _bind_endorsements(db, night_id, [{
        "dossier_id": dossier_id, "form": "会签", "endorser_id": minister,
        "imperial": False, "source_chat_turn_id": chat_turn_id,
    }])
    assert bound["status"] == "done"
    expected = [{
        "id": 1, "dossier_id": dossier_id, "form": "会签",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }]
    assert db.list_dossier_endorsements(dossier_id) == expected
    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    assert context["dossiers"][0]["endorsements"] == expected
    assert context["dossiers"][0]["criteria_snapshot_source"]["endorsement_entry_ids"] == [1]

    reopened = GameDB(db.path, content=content)
    try:
        restored_state = reopened.load_state()
        assert reopened.list_dossier_endorsements(dossier_id) == expected
        restored_context = build_promulgation_judge_context(
            reopened, restored_state, reopened.list_decree_dossiers(),
        )
        assert restored_context["dossiers"][0]["endorsements"] == expected
        assert restored_context["dossiers"][0]["criteria_snapshot_source"][
            "endorsement_entry_ids"
        ] == [1]
    finally:
        reopened.close()


def test_spoken_public_backing_is_persisted_without_joining_participant_roster(game):
    """当面站台落背书条目；担名≠办事，不入参与人/毁约追责名单。"""
    db, state, _content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="南迁之议",
        target_kind="issue", target_id="south-move",
    )
    before = db.get_decree_dossier(dossier_id)["participant_roster"]
    night_id, chat_turn_id, seq = _night_reply(
        db, state, minister, reply="臣愿当面为此旨站台。",
    )
    result = _extract(
        db, minister=minister, reply="臣愿当面为此旨站台。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={
            "body": "大臣当殿愿为此旨当面站台。", "person_names": [minister],
            "tags": ["当面站台"],
        },
    )
    assert result["status"] == "done"
    _bind_endorsements(db, night_id, [{
        "dossier_id": dossier_id, "form": "当面站台",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }])
    rows = db.list_dossier_endorsements(dossier_id)
    assert rows == [{
        "id": 1, "dossier_id": dossier_id, "form": "当面站台",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }]
    after = db.get_decree_dossier(dossier_id)["participant_roster"]
    assert after == before
    assert all(item.get("character_id") != minister for item in after)
    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    assert context["dossiers"][0]["endorsements"] == rows


def test_imperial_hand_endorsement_is_captured_without_authority_suppression(game):
    """皇帝问话经真实 user-message 入普通抽取；背书由夜级批处理绑定，判官可读。"""
    db, state, _content = game
    minister = _minister(db)
    state.metrics["皇威"] = 100
    dossier_id = db.create_decree_dossier(
        state, action_type="appointment", decree_text="擢任兵部侍郎",
        target_kind="character", target_id=minister,
    )
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    an.ensure_summon_enter(db, night_id, minister)
    chat_turn_id = db.create_chat_turn(
        state, minister, "endorsement-612", 0, night_id=night_id,
    )
    emperor_text = "朕亲书手敕为此旨作保。"
    minister_reply = "臣叩领圣恩。"
    user_message_id = db.append_chat_message(
        minister, int(state.turn), "user", emperor_text,
    )
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    db.persist_minister_reply(minister, int(state.turn), minister_reply, chat_turn_id)

    story_agent = _Agent({"facts": [{"body": "皇帝亲书手敕，大臣叩领。"}]})
    result = trail_extraction_after_reply(
        db=db,
        minister_name=minister,
        minister_reply=minister_reply,
        chat_turn_id=chat_turn_id,
        llm_config=object(),
        write_gate=threading.Lock(),
        extractor_agent=story_agent,
    )
    assert result is not None and result["status"] == "done"
    assert len(story_agent.calls) == 1
    assert emperor_text in story_agent.calls[0]
    assert minister_reply in story_agent.calls[0]
    assert "可背书案卷" not in story_agent.calls[0]
    assert db.list_dossier_endorsements(dossier_id) == []

    bind_agent = _Agent({"endorsements": [{
        "dossier_id": dossier_id, "form": "御笔手敕",
        "endorser_id": "", "imperial": True,
        "source_chat_turn_id": chat_turn_id,
    }]})
    bound = run_endorsement_batch_for_night(
        db=db, night_id=night_id, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=bind_agent,
    )
    assert bound["status"] == "done"
    row = db.list_dossier_endorsements(dossier_id)[0]
    assert row == {
        "id": 1, "dossier_id": dossier_id, "form": "御笔手敕",
        "endorser_id": "", "imperial": True,
        "source_chat_turn_id": chat_turn_id,
    }
    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    assert context["dossiers"][0]["endorsements"] == [row]
    assert context["dossiers"][0]["criteria_snapshot_source"]["endorsement_entry_ids"] == [1]


def test_endorsement_write_boundary_rejects_unknown_or_illegal_forms(game):
    db, state, _content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="核饷",
        target_kind="issue", target_id="pay-check",
    )
    _night_id, chat_turn_id, _seq = _night_reply(db, state, minister)

    with pytest.raises(ValueError, match="案卷不存在"):
        db.add_dossier_endorsement(
            999999, form="会签", endorser_id=minister,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError, match="背书形式非法"):
        db.add_dossier_endorsement(
            dossier_id, form="联名", endorser_id=minister,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError, match="会签/当面站台必须具名背书人"):
        db.add_dossier_endorsement(
            dossier_id, form="会签", endorser_id="",
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError, match="御笔手敕必须使用御笔标记且不得具名大臣"):
        db.add_dossier_endorsement(
            dossier_id, form="御笔手敕", endorser_id=minister, imperial=True,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError, match="背书人物不存在"):
        db.add_dossier_endorsement(
            dossier_id, form="当面站台", endorser_id="不存在的人",
            source_chat_turn_id=chat_turn_id,
        )
    for bad_imperial in ("false", 1, 0, None):
        with pytest.raises(ValueError, match="御笔标记须为布尔"):
            db.add_dossier_endorsement(
                dossier_id, form="会签", endorser_id=minister,
                imperial=bad_imperial,  # type: ignore[arg-type]
                source_chat_turn_id=chat_turn_id,
            )
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossier_endorsements").fetchone()[0] == 0


def test_undo_chat_turn_removes_source_bound_endorsements_from_judge(game):
    """撤回已说出口的会签后，背书条目须一并撤销；判官不得再读到已撤销对话的背书。"""
    db, state, _content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="liao-pay-undo",
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    assert _extract(
        db, minister=minister, reply="臣愿会签此旨。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣当殿愿为辽饷旨意会签。", "person_names": [minister], "tags": ["会签"]},
    )["status"] == "done"
    _bind_endorsements(db, night_id, [{
        "dossier_id": dossier_id, "form": "会签",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }])
    assert db.list_dossier_endorsements(dossier_id)

    db.undo_chat_turn(chat_turn_id)

    assert db.list_dossier_endorsements(dossier_id) == []
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossier_endorsements WHERE source_chat_turn_id=?",
        (chat_turn_id,),
    ).fetchone()[0] == 0
    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    dossier_ctx = next(item for item in context["dossiers"] if item["id"] == dossier_id)
    assert dossier_ctx["endorsements"] == []
    assert dossier_ctx["criteria_snapshot_source"]["endorsement_entry_ids"] == []


def test_ordinary_extraction_rejects_embedded_endorsement_without_blocking_siblings(game):
    """普通抽取不得携带 endorsement；整批 shape 非法项不得混入。"""
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    with pytest.raises(ExtractionShapeError, match="endorsement"):
        parse_extraction_facts({"facts": [{
            "body": "坏", "endorsement": {
                "dossier_id": 1, "form": "会签", "endorser_id": minister,
            },
        }]})
    # Runtime path: agent returning endorsement is loud pending (not silent drop).
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣愿会签。",
        chat_turn_id=chat_turn_id, night_id=night_id, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_Agent({"facts": [
            {"body": "合法事实", "person_names": [minister]},
            {"body": "坏背书", "endorsement": {
                "dossier_id": 1, "form": "会签", "endorser_id": minister,
            }},
        ]}),
    )
    assert result["status"] == "pending"
    assert db.get_story_extract_status(chat_turn_id) == "pending"


def test_unrelated_malformed_fact_remains_retryable_and_writes_error_artifact(game):
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣奏。", chat_turn_id=chat_turn_id,
        night_id=night_id, source_night_seq=seq, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=_Agent({"facts": [
            {"body": "合法事实"}, {"body": 501},
        ]}),
    )
    assert result["status"] == "pending"
    assert db.get_story_extract_status(chat_turn_id) == "pending"
    assert result["code"] == "extraction_bad_shape"
    assert result["error_pack_path"]
    assert [row for row in an.list_ledger(db, night_id) if row.get("source_chat_turn_id")] == []


def test_post_reply_extracts_ordinary_facts_immediately_even_with_approved_pending(game):
    """方案 A：有 approved office/directive 时，回话后普通 story 仍当轮 done。"""
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣愿会签。")
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "immediate-story", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)
    agent = _Agent({"facts": [{
        "body": "大臣当殿愿会签。", "person_names": [minister], "tags": ["会签"],
    }]})
    extracted = trail_extraction_after_reply(
        db=db, minister_name=minister, minister_reply="臣愿会签。",
        chat_turn_id=chat_turn_id, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=agent,
    )
    assert extracted["status"] == "done"
    assert db.get_story_extract_status(chat_turn_id) == "done"
    assert len(agent.calls) == 1
    materials = json.loads(agent.calls[0])
    assert "可背书案卷" not in materials
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossier_endorsements"
    ).fetchone()[0] == 0
    # startup catch-up must not re-run done turns or trigger endorsement batch
    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        night_id=night_id, extractor_agent=agent,
    )
    assert summary["extracted"] == 0
    assert "deferred" not in summary
    assert len(agent.calls) == 1


def test_close_night_endorsement_batch_once_gate_free_and_parallel_independent_work(game, monkeypatch):
    """真实收夜：稳定 dossier id；整夜一次 endorsement-only LLM；调用期无 write gate/
    无 DB transaction；与真实 close beat 生成重叠。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣叩领圣恩。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    # Ordinary facts already settled immediately (scheme A).
    assert _extract(
        db, minister=minister, reply="臣叩领圣恩。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣叩领圣恩。", "person_names": [minister]},
    )["status"] == "done"

    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "gate-free-batch", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)

    runtime_gate = threading.Lock()
    llm_saw_gate_free = []
    llm_saw_no_db_tx = []
    beat_overlap = threading.Event()
    endorsement_entered = threading.Event()
    calls = []

    class _EndorsementAgent:
        def run(self, materials):
            calls.append(json.loads(materials))
            # Probe: endorsement LLM must not hold the runtime write gate.
            acquired = runtime_gate.acquire(blocking=False)
            llm_saw_gate_free.append(acquired)
            if acquired:
                runtime_gate.release()
            # Probe: no DB transaction held across the LLM call.
            llm_saw_no_db_tx.append(db.conn.in_transaction is False)
            endorsement_entered.set()
            # Wait until real close beat generator has overlapped this window.
            assert beat_overlap.wait(5)
            candidates = calls[-1]["可背书案卷"]
            assert len(candidates) == 1
            did = int(candidates[0]["ref"]["dossier_id"])
            return json.dumps({"endorsements": [{
                "dossier_id": did, "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    def _real_close_beat(_inputs):
        # Production close beat path (threaded by close_night) overlaps endorsement LLM.
        assert endorsement_entered.wait(5)
        beat_overlap.set()
        return "王承恩代宣退朝，今夜召对到此。"

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent", lambda cfg: _EndorsementAgent(),
    )

    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=runtime_gate,
        beat_generator=_real_close_beat,
    )
    assert result["closed"] is True
    assert len(calls) == 1
    assert llm_saw_gate_free == [True]
    assert llm_saw_no_db_tx == [True]
    assert beat_overlap.is_set()
    assert "surviving_source_turns" in calls[0]
    assert emperor_text == calls[0]["surviving_source_turns"][0]["皇帝问话"]
    dossiers = db.list_decree_dossiers(status="proposed")
    assert len(dossiers) == 1
    assert db.list_dossier_endorsements(int(dossiers[0]["id"]))[0]["imperial"] is True
    night = an.get_night(db, night_id)
    assert an.night_endorsement_bound(night)
    assert int(night["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE


def test_close_night_beat_and_endorsement_exceptions_terminate_before_reopen(game, monkeypatch):
    """真实 close tracer：beat 或 endorsement 代码异常均在 finalize/重开前终结两支，
    不留后台线程继续访问 db/state；失败保持 OPEN、无 CLOSED。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣愿作保。")
    assert _extract(
        db, minister=minister, reply="臣愿作保。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣愿作保。", "person_names": [minister]},
    )["status"] == "done"
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "phase2-exc", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)

    # ── Case A: beat code error while endorsement overlaps ─────────────────
    runtime_gate = threading.Lock()
    endorsement_entered = threading.Event()
    beat_entered = threading.Event()
    active_threads_at_raise: list[int] = []

    class _OkEndorsement:
        def run(self, materials):
            endorsement_entered.set()
            assert beat_entered.wait(5)
            payload = json.loads(materials)
            did = int(payload["可背书案卷"][0]["ref"]["dossier_id"])
            return json.dumps({"endorsements": [{
                "dossier_id": did, "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    def _boom_beat(_inputs):
        beat_entered.set()
        assert endorsement_entered.wait(5)
        # Snapshot non-main threads still alive when beat fails; join must clear them
        # before close_night reopens / returns.
        active_threads_at_raise.append(
            sum(1 for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive())
        )
        raise RuntimeError("close beat code fault")

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent", lambda cfg: _OkEndorsement(),
    )
    before_threads = {t.ident for t in threading.enumerate() if t.ident is not None}
    with pytest.raises(RuntimeError, match="close beat code fault"):
        an.close_night(
            db, state, night_id=night_id, content=content,
            llm_config=object(), write_gate=runtime_gate,
            beat_generator=_boom_beat,
        )
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    assert not an.night_endorsement_bound(failed)
    # No orphan close-owned threads left accessing shared state after return.
    leftover = [
        t for t in threading.enumerate()
        if t.ident not in before_threads and t.is_alive() and not t.daemon
    ]
    assert leftover == [], leftover
    assert active_threads_at_raise  # beat really overlapped / ran

    # ── Case B: endorsement boom while real beat overlaps ──────────────────
    night_id2, chat_turn_id2, seq2 = _night_reply(db, state, minister, reply="臣再保。")
    assert _extract(
        db, minister=minister, reply="臣再保。",
        chat_turn_id=chat_turn_id2, night_id=night_id2, seq=seq2,
        fact={"body": "大臣再保。", "person_names": [minister]},
    )["status"] == "done"
    candidate_id2 = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "续核京饷", "dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "phase2-endorsement-exc", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id2], night_id=night_id2)

    runtime_gate2 = threading.Lock()
    endorsement_entered2 = threading.Event()
    beat_done2 = threading.Event()

    class _BoomEndorsement:
        def run(self, materials):
            endorsement_entered2.set()
            assert beat_done2.wait(5)
            raise RuntimeError("endorsement boom with beat")

    def _ok_beat(_inputs):
        assert endorsement_entered2.wait(5)
        beat_done2.set()
        return "退朝，今夜召对到此。"

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent", lambda cfg: _BoomEndorsement(),
    )
    before_threads2 = {t.ident for t in threading.enumerate() if t.ident is not None}
    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id2, content=content,
            llm_config=object(), write_gate=runtime_gate2,
            beat_generator=_ok_beat,
        )
    assert ei.value.code == "endorsement_extract_failed"
    failed2 = an.get_night(db, night_id2)
    assert failed2["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed2["close_commit_cursor"] or 0) == 0
    leftover2 = [
        t for t in threading.enumerate()
        if t.ident not in before_threads2 and t.is_alive() and not t.daemon
    ]
    assert leftover2 == [], leftover2
    assert beat_done2.is_set()
    assert endorsement_entered2.is_set()
    # CLOSED must not appear after either phase-2 fault.
    assert an.get_night(db, night_id)["status"] == an.NIGHT_STATUS_OPEN
    assert an.get_night(db, night_id2)["status"] == an.NIGHT_STATUS_OPEN


def test_endorsement_failure_keeps_open_drafts_and_retries_idempotently(game):
    """首批失败 → OPEN/draft 保留/无重 consent；重试成功复用 ids，依赖步骤才推进。"""
    db, state, content = game
    minister = _minister(db)
    consort_row = db.conn.execute(
        "SELECT name FROM characters WHERE office_type='后宫' AND status='active' "
        "ORDER BY name LIMIT 1"
    ).fetchone()
    if consort_row is None:
        pytest.skip("基底无 active 后宫角色")
    consort = str(consort_row["name"])
    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣愿作保。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    assert _extract(
        db, minister=minister, reply="臣愿作保。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣愿作保。", "person_names": [minister]},
    )["status"] == "done"

    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy",
                 "target_kind": "issue", "target_id": "retry-keep", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)
    consort_pa = db.stage_pending_action(
        state.turn, kind="consort", action="调教", minister_name=consort,
        payload={"name": consort, "skill": "理财", "trait": ""},
    )
    db.mark_pending_night_approved([consort_pa], night_id=night_id)
    consort_before = db.get_consort_traits(consort)
    calls = []

    class _BoomThenOk:
        def run(self, materials):
            payload = json.loads(materials)
            calls.append(payload)
            if len(calls) == 1:
                raise RuntimeError("endorsement boom")
            candidates = payload["可背书案卷"]
            target = next(row for row in candidates if row["decree_text"] == "清核辽饷")
            return json.dumps({"endorsements": [{
                "dossier_id": target["ref"]["dossier_id"], "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id, content=content,
            llm_config=object(), write_gate=threading.Lock(),
            endorsement_extractor_agent=_BoomThenOk(),
        )
    assert ei.value.code == "endorsement_extract_failed"
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    assert not an.night_endorsement_bound(failed)
    dossiers = db.list_decree_dossiers(status="proposed")
    assert [row["decree_text"] for row in dossiers] == ["清核辽饷"]
    first_id = int(dossiers[0]["id"])
    first_directive = int(dossiers[0]["directive_id"])
    assert db.list_dossier_endorsements(first_id) == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (consort_pa,)
    ).fetchone()["status"] == "pending"
    assert db.get_consort_traits(consort) == consort_before
    assert db.list_night_promulgated_directives(night_id) == []
    assert db.list_promulgated_directives(turn_from=state.turn, turn_to=state.turn) == []
    assert an.engine_command_mingfa_publication_ids(an.list_ledger(db, night_id)) == set()

    # New consent after failure is absorbed; original draft id stable; no re-consent needed.
    appended_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "续核京饷", "dossier_action_type": "policy",
                 "target_kind": "issue", "target_id": "retry-keep-appended", "actor": minister},
    )
    db.mark_pending_night_approved([appended_id], night_id=night_id)

    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=threading.Lock(),
        endorsement_extractor_agent=_BoomThenOk(),
    )
    assert result["closed"] is True
    assert len(calls) == 2
    kept = next(row for row in db.list_decree_dossiers(status="proposed") if row["decree_text"] == "清核辽饷")
    assert int(kept["id"]) == first_id
    assert int(kept["directive_id"]) == first_directive
    assert db.list_dossier_endorsements(first_id)[0]["imperial"] is True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossier_endorsements WHERE dossier_id=?",
        (first_id,),
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (consort_pa,)
    ).fetchone()["status"] == "committed"
    assert "理财" in (db.get_consort_traits(consort).get("extra_skills") or [])
    published = db.list_night_promulgated_directives(night_id)
    assert {str(p.get("text") or "") for p in published} == {"清核辽饷", "续核京饷"}


def test_startup_catchup_only_ordinary_facts_never_endorsement_batch(game):
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣奏边饷。")
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="边饷",
        target_kind="issue", target_id="catchup-no-endorsement",
    )
    endorse_calls = []

    class _EndorseBoom:
        def run(self, materials):
            endorse_calls.append(materials)
            raise AssertionError("startup catch-up must not run endorsement batch")

    story_agent = _Agent({"facts": [{"body": "大臣奏边饷。", "person_names": [minister]}]})
    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        night_id=night_id, extractor_agent=story_agent,
    )
    assert summary["extracted"] == 1
    assert db.get_story_extract_status(chat_turn_id) == "done"
    assert endorse_calls == []
    assert db.list_dossier_endorsements(dossier_id) == []
    assert not an.night_endorsement_bound(an.get_night(db, night_id))


def test_office_phase1_draft_only_materializes_once_after_endorsement(game):
    """Phase 1 office = stable draft dossier only; real office effect after bound,
    exactly once. Failure keeps OPEN/draft/consent and leaves office unchanged."""
    db, state, content = game
    minister = _minister(db)
    target = db.conn.execute(
        "SELECT name, office FROM characters WHERE status='active' "
        "AND power_id='ming' AND name != ? ORDER BY name LIMIT 1",
        (minister,),
    ).fetchone()
    if target is None:
        pytest.skip("no second active ming minister")
    target_name = str(target["name"])
    office_before = str(target["office"] or "")
    new_office = "户部尚书" if office_before != "户部尚书" else "兵部尚书"

    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣愿作保。")
    assert _extract(
        db, minister=minister, reply="臣愿作保。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣愿作保。", "person_names": [minister]},
    )["status"] == "done"

    office_pa = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister,
        payload={"name": target_name, "office": new_office},
    )
    db.mark_pending_night_approved([office_pa], night_id=night_id)
    calls = []

    class _BoomThenOk:
        def run(self, materials):
            payload = json.loads(materials)
            calls.append(payload)
            if len(calls) == 1:
                raise RuntimeError("endorsement boom")
            candidates = payload["可背书案卷"]
            target_row = next(
                row for row in candidates
                if str(row.get("decree_text") or "").startswith(f"任命{target_name}")
            )
            return json.dumps({"endorsements": [{
                "dossier_id": target_row["ref"]["dossier_id"], "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id, content=content,
            llm_config=object(), write_gate=threading.Lock(),
            endorsement_extractor_agent=_BoomThenOk(),
        )
    assert ei.value.code == "endorsement_extract_failed"
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    # Draft carrier exists; real office/registry untouched.
    dossiers = [
        row for row in db.list_decree_dossiers(status="proposed")
        if str(row.get("decree_text") or "").startswith(f"任命{target_name}")
    ]
    assert len(dossiers) == 1
    draft_id = int(dossiers[0]["id"])
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"] == office_before
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (office_pa,)
    ).fetchone()["status"] == "committed"

    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=threading.Lock(),
        endorsement_extractor_agent=_BoomThenOk(),
    )
    assert result["closed"] is True
    assert len(calls) == 2
    kept = db.get_decree_dossier(draft_id)
    assert kept is not None
    assert int(kept["id"]) == draft_id
    assert db.list_dossier_endorsements(draft_id)[0]["imperial"] is True
    # Still proposed after close: payload effect materializes at promulgation.
    assert str(kept["status"]) == "proposed"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"] == office_before

    # Endorsement-bound success barrier cleared; promulgation materializes once.
    db.apply_dossier_promulgation(
        state, draft_id, "promulgated", content=content, registry=None,
    )
    after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"]
    assert str(after) == new_office
    final = db.get_decree_dossier(draft_id)
    assert str(final["status"]) != "proposed"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE pending_action_id=?",
        (office_pa,),
    ).fetchone()[0] == 1
    # Second promulgation must not re-apply / invent another carrier.
    with pytest.raises(Exception):
        db.apply_dossier_promulgation(
            state, draft_id, "promulgated", content=content, registry=None,
        )
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"] == new_office


def _public_mingfa_projection(db, night_id):
    ledger = an.list_ledger(db, night_id)
    fact_ids = an.engine_command_mingfa_publication_ids(ledger)
    entries = [
        e for e in ledger
        if int(e.get("source_chat_turn_id") or 0) == 0
        and any(
            an.exact_mingfa_publication_directive_id(t) in fact_ids
            for t in (e.get("tags") or [])
        )
    ]
    mingfa_ids = sorted(str(i) for i in fact_ids)
    bodies = [str(e.get("body") or "") for e in entries]
    return entries, mingfa_ids, bodies


def test_mingfa_publication_ignores_extractor_source_and_malformed_suffix_on_retry(game):
    """抽取账 明发# 与畸形后缀不得冒充/阻挡 exact engine-command publication fact。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣愿作保。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    assert _extract(
        db, minister=minister, reply="臣愿作保。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣愿作保。", "person_names": [minister]},
    )["status"] == "done"
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy",
                 "target_kind": "issue", "target_id": "retry-collision", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)
    calls = []

    class _BoomThenOk:
        def run(self, materials):
            payload = json.loads(materials)
            calls.append(payload)
            if len(calls) == 1:
                raise RuntimeError("endorsement boom")
            candidates = payload["可背书案卷"]
            target = next(row for row in candidates if row["decree_text"] == "清核辽饷")
            return json.dumps({"endorsements": [{
                "dossier_id": target["ref"]["dossier_id"], "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id, content=content,
            llm_config=object(), write_gate=threading.Lock(),
            endorsement_extractor_agent=_BoomThenOk(),
        )
    assert ei.value.code == "endorsement_extract_failed"
    dossiers = db.list_decree_dossiers(status="proposed")
    first_id = int(dossiers[0]["id"])
    first_directive = int(dossiers[0]["directive_id"])
    assert db.list_night_promulgated_directives(night_id) == []

    an.append_ledger_entry(
        db, night_id,
        person_names=[minister],
        audibility=an.AUDIBILITY_PUBLIC,
        body="抽取叙事妄称已明发",
        tags=[an.TAG_MINGFA, an.mingfa_publication_tag(first_directive)],
        source_chat_turn_id=chat_turn_id,
        check_dead=False,
    )
    malformed_tag = f"{an.mingfa_publication_tag(first_directive)}abc"
    an.append_ledger_entry(
        db, night_id, person_names=[], audibility=an.AUDIBILITY_PUBLIC,
        body="畸形后缀碰撞", tags=[malformed_tag], source_chat_turn_id=0, check_dead=False,
    )
    an.append_ledger_entry(
        db, night_id, person_names=[], audibility=an.AUDIBILITY_PUBLIC,
        body="上标数字不得冒充明发", tags=["明发#²"], source_chat_turn_id=0, check_dead=False,
    )
    assert an.engine_command_mingfa_publication_ids(an.list_ledger(db, night_id)) == set()
    assert db.list_night_promulgated_directives(night_id) == []

    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=threading.Lock(),
        endorsement_extractor_agent=_BoomThenOk(),
    )
    assert result["closed"] is True
    assert len(calls) == 2
    assert int(
        next(row for row in db.list_decree_dossiers(status="proposed")
             if row["decree_text"] == "清核辽饷")["id"]
    ) == first_id
    published = db.list_night_promulgated_directives(night_id)
    assert [int(p["directive_id"]) for p in published] == [first_directive]
    fact_ids = an.engine_command_mingfa_publication_ids(an.list_ledger(db, night_id))
    assert fact_ids == {first_directive}
    exact_tags = [
        t for e in an.list_ledger(db, night_id)
        if int(e.get("source_chat_turn_id") or 0) == 0
        for t in (e.get("tags") or [])
        if an.exact_mingfa_publication_directive_id(t) == first_directive
    ]
    assert exact_tags == [an.mingfa_publication_tag(first_directive)]


def test_parse_endorsement_batch_and_ordinary_facts_boundaries():
    items = parse_endorsement_batch({
        "endorsements": [{
            "dossier_id": 3, "form": "会签", "endorser_id": "毕自严",
            "imperial": False, "source_chat_turn_id": 9,
        }],
    })
    assert items[0] == {
        "dossier_id": 3, "form": "会签", "endorser_id": "毕自严",
        "imperial": False, "source_chat_turn_id": 9,
    }
    with pytest.raises(ExtractionShapeError, match="facts"):
        parse_endorsement_batch({"facts": []})
    with pytest.raises(ExtractionShapeError, match="endorsement"):
        parse_extraction_facts({
            "facts": [{
                "body": "坏背书", "endorsement": {
                    "dossier_id": 3, "form": "会签", "endorser_id": "毕自严",
                },
            }],
        })
    facts = parse_extraction_facts({
        "facts": [{
            "body": "大臣愿会签。", "person_names": ["毕自严"],
            "audibility": "殿上公开", "tags": ["会签"],
        }],
    })
    assert "endorsement" not in facts[0]


def test_no_edict_chain_binds_endorsement_after_draft(game, monkeypatch):
    """真实 no-edict 链：先普通即时抽取，收夜一次 endorsement-only。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣叩领圣恩。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "same-night-endorsement", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)

    story_agent = _Agent({"facts": [{"body": "大臣叩领。", "person_names": [minister]}]})
    trail = trail_extraction_after_reply(
        db=db, minister_name=minister, minister_reply="臣叩领圣恩。",
        chat_turn_id=chat_turn_id, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=story_agent,
    )
    assert trail["status"] == "done"

    endorse_calls = []

    class _Endorse:
        def run(self, materials):
            endorse_calls.append(json.loads(materials))
            candidates = endorse_calls[-1]["可背书案卷"]
            return json.dumps({"endorsements": [{
                "dossier_ref": candidates[0]["ref"], "form": "御笔手敕",
                "endorser_id": "", "imperial": True,
                "source_chat_turn_id": chat_turn_id,
            }]}, ensure_ascii=False)

    monkeypatch.setattr(agents_mod, "create_endorsement_extractor_agent", lambda cfg: _Endorse())
    advance_without_edict(
        state, db, content=content, registry=None, inflight_wait_s=0.0,
        llm_config=object(), write_gate=threading.Lock(),
    )
    assert an.get_night(db, night_id)["status"] == an.NIGHT_STATUS_CLOSED
    assert len(endorse_calls) == 1
    dossiers = db.list_decree_dossiers(status="proposed")
    assert len(dossiers) == 1
    assert db.list_dossier_endorsements(int(dossiers[0]["id"]))[0]["imperial"] is True
