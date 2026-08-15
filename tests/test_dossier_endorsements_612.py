"""#612 endorsement contracts — one real entry tracer per independent external seam."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ming_sim import agents as agents_mod
from ming_sim import audience_night as an
from ming_sim import beat_orchestration as bo
from ming_sim.audience_extraction import (
    ExtractionShapeError,
    catch_up_pending_extractions,
    parse_endorsement_batch,
    parse_extraction_facts,
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


def _approve_directive(db, state, minister, night_id, *, text, target_id):
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={
            "text": text, "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": target_id, "actor": minister,
        },
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)
    return candidate_id


class _Agent:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, materials):
        self.calls.append(materials if isinstance(materials, str) else str(materials))
        return json.dumps(self.payload, ensure_ascii=False)


def test_endorsement_forms_persist_restore_and_judge_without_roster_join(game):
    """Durable form CRUD + judge restore; 担名≠办事（当面站台不入参与人）。"""
    db, state, content = game
    minister = _minister(db)
    cosign_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="liao-pay",
    )
    backing_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="南迁之议",
        target_kind="issue", target_id="south-move",
    )
    imperial_id = db.create_decree_dossier(
        state, action_type="appointment", decree_text="擢任兵部侍郎",
        target_kind="character", target_id=minister,
    )
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister)
    before_roster = db.get_decree_dossier(backing_id)["participant_roster"]

    db.add_dossier_endorsement(
        cosign_id, form="会签", endorser_id=minister, imperial=False,
        source_chat_turn_id=chat_turn_id,
    )
    db.add_dossier_endorsement(
        backing_id, form="当面站台", endorser_id=minister, imperial=False,
        source_chat_turn_id=chat_turn_id,
    )
    db.add_dossier_endorsement(
        imperial_id, form="御笔手敕", endorser_id="", imperial=True,
        source_chat_turn_id=chat_turn_id,
    )

    cosign = db.list_dossier_endorsements(cosign_id)
    assert cosign == [{
        "id": 1, "dossier_id": cosign_id, "form": "会签",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }]
    backing = db.list_dossier_endorsements(backing_id)
    assert backing[0]["form"] == "当面站台"
    assert db.get_decree_dossier(backing_id)["participant_roster"] == before_roster
    assert all(item.get("character_id") != minister for item in before_roster)
    imperial = db.list_dossier_endorsements(imperial_id)
    assert imperial[0]["form"] == "御笔手敕" and imperial[0]["imperial"] is True

    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    by_id = {int(d["id"]): d for d in context["dossiers"]}
    assert by_id[cosign_id]["endorsements"] == cosign
    assert by_id[cosign_id]["criteria_snapshot_source"]["endorsement_entry_ids"] == [1]
    assert by_id[backing_id]["endorsements"] == backing
    assert by_id[imperial_id]["endorsements"] == imperial

    reopened = GameDB(db.path, content=content)
    try:
        restored = reopened.load_state()
        assert reopened.list_dossier_endorsements(cosign_id) == cosign
        restored_ctx = build_promulgation_judge_context(
            reopened, restored, reopened.list_decree_dossiers(),
        )
        restored_by = {int(d["id"]): d for d in restored_ctx["dossiers"]}
        assert restored_by[cosign_id]["endorsements"] == cosign
    finally:
        reopened.close()
    # night unused except as source turn host
    assert an.get_night(db, night_id) is not None


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
    # imperial=False 负例：御笔手敕不得假借非御笔标记。
    with pytest.raises(ValueError, match="御笔手敕必须使用御笔标记且不得具名大臣"):
        db.add_dossier_endorsement(
            dossier_id, form="御笔手敕", endorser_id="", imperial=False,
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
    db.add_dossier_endorsement(
        dossier_id, form="会签", endorser_id=minister, imperial=False,
        source_chat_turn_id=chat_turn_id,
    )
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


def test_ordinary_extraction_and_parse_boundaries(game):
    """普通抽取拒 endorsement；背书 envelope 整批失败、单项畸形留给 settle。"""
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)

    with pytest.raises(ExtractionShapeError, match="endorsement"):
        parse_extraction_facts({"facts": [{
            "body": "坏", "endorsement": {
                "dossier_id": 1, "form": "会签", "endorser_id": minister,
            },
        }]})
    with pytest.raises(ExtractionShapeError, match="facts"):
        parse_endorsement_batch({"facts": []})
    with pytest.raises(ExtractionShapeError, match="endorsements"):
        parse_endorsement_batch({})

    # Envelope ok：单项畸形仍返回，合法 sibling 保留；ref → 扁平 dossier_id。
    items = parse_endorsement_batch({
        "endorsements": [
            {
                "dossier_ref": {"dossier_id": 3}, "form": "会签",
                "endorser_id": "毕自严", "imperial": False,
                "source_chat_turn_id": 9,
            },
            {"body": "故事字段不得入背书", "dossier_id": 3, "form": "会签",
             "endorser_id": "毕自严", "imperial": False, "source_chat_turn_id": 9},
            "not-an-object",
        ],
    })
    assert items[0]["dossier_id"] == 3
    assert "dossier_ref" not in items[0]
    assert "body" in items[1]
    assert items[2] == {"raw": repr("not-an-object")}

    # Runtime ordinary path: embedded endorsement → loud pending, no silent drop.
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
    assert result["code"] == "extraction_bad_shape"
    assert result["error_pack_path"]
    assert db.get_story_extract_status(chat_turn_id) == "pending"


def test_post_reply_extracts_ordinary_facts_immediately_even_with_approved_pending(game):
    """方案 A：有 approved office/directive 时，回话后普通 story 仍当轮 done；
    startup catch-up 只补普通事实，不触发夜级 endorsement。"""
    db, state, _content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣愿会签。")
    _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="immediate-story",
    )
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

    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        night_id=night_id, extractor_agent=agent,
    )
    assert summary["extracted"] == 0
    assert "deferred" not in summary
    assert len(agent.calls) == 1
    assert not an.night_endorsement_bound(an.get_night(db, night_id))


def test_close_night_endorsement_batch_once_gate_free_and_parallel_independent_work(game, monkeypatch):
    """真实收夜：夜级候选；整夜一次 endorsement-only；调用期无 write gate/
    无 DB transaction；与真实 close beat 重叠；单项畸形走 rejection、合法 sibling 落；
    他夜/全局 proposed 不入候选。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, seq = _night_reply(db, state, minister, reply="臣叩领圣恩。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    assert _extract(
        db, minister=minister, reply="臣叩领圣恩。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={"body": "大臣叩领圣恩。", "person_names": [minister]},
    )["status"] == "done"

    _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="gate-free-batch",
    )
    # 他夜/全局 proposed：不得进入本夜候选。
    foreign_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="他案",
        target_kind="issue", target_id="foreign-dossier",
    )

    runtime_gate = threading.Lock()
    llm_saw_gate_free = []
    llm_saw_no_db_tx = []
    beat_overlap = threading.Event()
    endorsement_entered = threading.Event()
    scene_registry = bo.ChatTurnSceneRegistry(
        ThreadPoolExecutor(max_workers=2, thread_name_prefix="close-scene-test"),
    )

    class _EndorsementAgent:
        def run(self, materials):
            endorsement_entered.set()
            assert beat_overlap.wait(5)
            llm_saw_gate_free.append(not runtime_gate.locked())
            in_tx = bool(getattr(db.conn, "_commit_suspended", False)) or (
                int(getattr(db.conn, "_atomic_depth", 0) or 0) > 0
            )
            llm_saw_no_db_tx.append(not in_tx)
            payload = json.loads(materials)
            candidates = payload["可背书案卷"]
            assert all(
                int(c["ref"]["dossier_id"]) != foreign_id for c in candidates
            ), candidates
            target = next(row for row in candidates if row["decree_text"] == "清核辽饷")
            did = int(target["ref"]["dossier_id"])
            return json.dumps({"endorsements": [
                {
                    "dossier_id": did, "form": "御笔手敕",
                    "endorser_id": "", "imperial": True,
                    "source_chat_turn_id": chat_turn_id,
                },
                # 单项畸形：故事字段 → rejection，不拖垮合法 sibling。
                {
                    "dossier_id": did, "form": "会签", "endorser_id": minister,
                    "imperial": False, "source_chat_turn_id": chat_turn_id,
                    "body": "不得入背书",
                },
                # 非本夜候选 → rejection。
                {
                    "dossier_id": foreign_id, "form": "会签", "endorser_id": minister,
                    "imperial": False, "source_chat_turn_id": chat_turn_id,
                },
            ]}, ensure_ascii=False)

    def _real_close_beat(_inputs):
        # Production close beat path (registry Future) overlaps endorsement LLM.
        beat_overlap.set()
        assert endorsement_entered.wait(5)
        return "退朝，今夜召对到此。"

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda cfg: _EndorsementAgent(),
    )
    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=runtime_gate,
        beat_generator=_real_close_beat,
        scene_registry=scene_registry,
    )
    assert result["closed"] is True
    assert llm_saw_gate_free == [True]
    assert llm_saw_no_db_tx == [True]
    assert beat_overlap.is_set() and endorsement_entered.is_set()

    night_dossiers = [
        row for row in db.list_decree_dossiers(status="proposed")
        if row["decree_text"] == "清核辽饷"
    ]
    assert len(night_dossiers) == 1
    did = int(night_dossiers[0]["id"])
    rows = db.list_dossier_endorsements(did)
    assert len(rows) == 1
    assert rows[0]["form"] == "御笔手敕" and rows[0]["imperial"] is True
    assert db.list_dossier_endorsements(foreign_id) == []
    # rejection channel recorded malformed + foreign candidate items
    rejected = db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports "
        "WHERE section='endorsements' AND category='invalid_item'"
    ).fetchone()
    assert int(rejected[0] or 0) >= 2
    night = an.get_night(db, night_id)
    assert an.night_endorsement_bound(night)
    assert int(night["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE


def test_close_night_beat_and_endorsement_exceptions_terminate_before_reopen(game, monkeypatch):
    """真实 close tracer：beat 或 endorsement 代码异常均在 finalize/重开前终结两支；
    双支同时失败 → 先观察者传播、另一支仍 drain，cleanup 经 __cause__ 链；
    endorsement_not_bound 前恢复 OPEN。"""
    db, state, content = game
    minister = _minister(db)
    scene_registry = bo.ChatTurnSceneRegistry(
        ThreadPoolExecutor(max_workers=2, thread_name_prefix="close-scene-test"),
    )

    def _prep(target_id, reply):
        nid, cid, seq = _night_reply(db, state, minister, reply=reply)
        assert _extract(
            db, minister=minister, reply=reply,
            chat_turn_id=cid, night_id=nid, seq=seq,
            fact={"body": reply, "person_names": [minister]},
        )["status"] == "done"
        _approve_directive(
            db, state, minister, nid, text="清核辽饷", target_id=target_id,
        )
        return nid, cid

    def _no_owned_leftover(before_idents):
        leftover = [
            t for t in threading.enumerate()
            if t.ident not in before_idents and t.is_alive() and not t.daemon
            and not (t.name or "").startswith("close-scene-test")
        ]
        assert leftover == [], leftover

    # ── Case A: beat code error while endorsement overlaps ─────────────────
    night_id, chat_turn_id = _prep("phase2-exc", "臣愿作保。")
    runtime_gate = threading.Lock()
    endorsement_entered = threading.Event()
    beat_entered = threading.Event()

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
            scene_registry=scene_registry,
        )
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    _no_owned_leftover(before_threads)

    # ── Case B: endorsement boom while real beat overlaps ──────────────────
    night_id2, chat_turn_id2 = _prep("phase2-endorsement-exc", "臣再保。")
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
    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=night_id2, content=content,
            llm_config=object(), write_gate=runtime_gate2,
            beat_generator=_ok_beat,
            scene_registry=scene_registry,
        )
    assert ei.value.code == "endorsement_extract_failed"
    failed2 = an.get_night(db, night_id2)
    assert failed2["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed2["close_commit_cursor"] or 0) == 0
    assert beat_done2.is_set() and endorsement_entered2.is_set()

    # ── Case C: both branches fail → first observed propagates; other drains ─
    night_id3, _cid3 = _prep("phase2-both-exc", "臣三保。")
    runtime_gate3 = threading.Lock()
    endorsement_entered3 = threading.Event()
    beat_entered3 = threading.Event()

    class _BoomBothEndorsement:
        def run(self, materials):
            endorsement_entered3.set()
            assert beat_entered3.wait(5)
            raise RuntimeError("endorsement boom dual")

    def _boom_both_beat(_inputs):
        beat_entered3.set()
        assert endorsement_entered3.wait(5)
        raise RuntimeError("close beat dual fault")

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda cfg: _BoomBothEndorsement(),
    )
    with pytest.raises(an.AudienceNightError) as eg:
        an.close_night(
            db, state, night_id=night_id3, content=content,
            llm_config=object(), write_gate=runtime_gate3,
            beat_generator=_boom_both_beat,
            scene_registry=scene_registry,
        )
    # No ExceptionGroup failure bus: primary = endorsement; join still drained.
    assert eg.value.code == "endorsement_extract_failed"
    assert "endorsement boom dual" in str(eg.value)
    assert eg.value.__cause__ is not None
    assert "close beat dual fault" in str(eg.value.__cause__)
    assert beat_entered3.is_set() and endorsement_entered3.is_set()
    failed3 = an.get_night(db, night_id3)
    assert failed3["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed3["close_commit_cursor"] or 0) == 0

    # ── Case D: endorsement_not_bound hard fault restores OPEN ─────────────
    night_id4, _cid4 = _prep("phase3-not-bound", "臣四保。")
    class _SkipBind:
        def run(self, materials):
            return json.dumps({"endorsements": []}, ensure_ascii=False)

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent", lambda cfg: _SkipBind(),
    )
    real_settle = db.settle_endorsement_batch

    def _settle_no_cursor(nid, items):
        # Persist nothing and leave cursor below ENDORSEMENT_BOUND.
        return []

    monkeypatch.setattr(db, "settle_endorsement_batch", _settle_no_cursor)
    with pytest.raises(an.AudienceNightError) as ei4:
        an.close_night(
            db, state, night_id=night_id4, content=content,
            llm_config=object(), write_gate=threading.Lock(),
        )
    assert ei4.value.code == "endorsement_not_bound"
    assert ei4.value.detail.get("cursor") is not None
    failed4 = an.get_night(db, night_id4)
    assert failed4["status"] == an.NIGHT_STATUS_OPEN
    assert failed4.get("closed_at") in (None, "")
    assert int(failed4["close_commit_cursor"] or 0) == 0
    # Player can retry after restore (admission accepts OPEN).
    open_n = an.assert_night_accepts_player_input(db, what="召对")
    assert int(open_n["id"]) == night_id4
    monkeypatch.setattr(db, "settle_endorsement_batch", real_settle)

    # ── Case E: story-drain fails → still join/drain; original from cleanup ─
    night_id5, _cid5 = _prep("phase2-story-drain-cleanup", "臣五保。")
    drain_joined = threading.Event()

    def _boom_drain(*_a, **_k):
        raise RuntimeError("story drain boom")

    def _boom_join(*_a, **_k):
        drain_joined.set()
        raise RuntimeError("close join cleanup boom")

    def _ok_beat(_inputs):
        return "不应落账的收夜旁白"

    monkeypatch.setattr(an, "_drain_story_extraction_or_fail_closed", _boom_drain)
    monkeypatch.setattr(bo, "join_close_scene_on_registry", _boom_join)
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda cfg: _SkipBind(),
    )
    with pytest.raises(RuntimeError, match="story drain boom") as ei5:
        an.close_night(
            db, state, night_id=night_id5, content=content,
            llm_config=object(), write_gate=threading.Lock(),
            beat_generator=_ok_beat,
            scene_registry=scene_registry,
        )
    assert drain_joined.is_set(), "story-drain failure must still join/drain close scene"
    assert ei5.value.__cause__ is not None
    assert "close join cleanup boom" in str(ei5.value.__cause__)
    failed5 = an.get_night(db, night_id5)
    assert failed5["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed5["close_commit_cursor"] or 0) == 0


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

    _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="retry-keep",
    )
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
    # SQL-narrowed range reader agrees with night reader.
    ranged = db.list_promulgated_directives(turn_from=state.turn, turn_to=state.turn)
    assert {int(p["directive_id"]) for p in ranged} == {
        int(p["directive_id"]) for p in published
    }


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
    assert str(kept["status"]) == "proposed"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"] == office_before

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
    with pytest.raises(ValueError, match="只有 proposed 案卷可写颁布"):
        db.apply_dossier_promulgation(
            state, draft_id, "promulgated", content=content, registry=None,
        )
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target_name,)
    ).fetchone()["office"] == new_office


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
    _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="retry-collision",
    )
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
    ranged = db.list_promulgated_directives(turn_from=state.turn, turn_to=state.turn)
    assert [int(p["directive_id"]) for p in ranged] == [first_directive]


def test_no_edict_chain_binds_endorsement_after_draft(game, monkeypatch):
    """真实 no-edict 链：先普通即时抽取，收夜一次 endorsement-only。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣叩领圣恩。")
    emperor_text = "准此旨，朕亲书手敕作保。"
    user_message_id = db.append_chat_message(minister, int(state.turn), "user", emperor_text)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="same-night-endorsement",
    )

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
    assert len(endorse_calls) == 1
    did = int(endorse_calls[0]["可背书案卷"][0]["ref"]["dossier_id"])
    assert db.list_dossier_endorsements(did)[0]["imperial"] is True
    assert an.get_night(db, night_id)["status"] == an.NIGHT_STATUS_CLOSED
