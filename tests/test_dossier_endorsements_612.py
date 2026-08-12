import json
import threading

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_extraction import (
    ExtractionShapeError,
    parse_extraction_facts,
    run_extraction_for_turn,
    trail_extraction_after_reply,
)
from ming_sim.db import GameDB
from ming_sim.decree import build_promulgation_judge_context


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


class _Agent:
    def __init__(self, payload):
        self.payload = payload

    def run(self, _materials):
        return json.dumps(self.payload, ensure_ascii=False)


def test_spoken_cosign_is_persisted_restored_and_read_by_promulgation_judge(game):
    db, state, content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="liao-pay",
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    result = _extract(
        db, minister=minister, reply="臣愿会签此旨。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={
            "body": "大臣当殿愿为辽饷旨意会签。", "person_names": [minister],
            "tags": ["会签"], "endorsement": {
                "dossier_id": dossier_id, "form": "会签", "endorser_id": minister,
            },
        },
    )
    assert result["status"] == "done"
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
            "tags": ["当面站台"], "endorsement": {
                "dossier_id": dossier_id, "form": "当面站台",
                "endorser_id": minister, "imperial": False,
            },
        },
    )
    assert result["status"] == "done"
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
    """皇帝问话「朕亲书手敕」经真实 user-message 生产路径进入 #501 抽取，一次落库且判官可读。"""
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
    # 与 CLI/Web 同序：先落皇帝问话并链接，再落大臣回话，最后走共用尾随抽取入口。
    emperor_text = "朕亲书手敕为此旨作保。"
    minister_reply = "臣叩领圣恩。"
    user_message_id = db.append_chat_message(
        minister, int(state.turn), "user", emperor_text,
    )
    db.update_chat_turn_messages(chat_turn_id, user_message_id=user_message_id)
    db.persist_minister_reply(minister, int(state.turn), minister_reply, chat_turn_id)

    seen_materials: list[str] = []

    class _CaptureAgent:
        def run(self, materials):
            seen_materials.append(str(materials))
            return json.dumps({
                "facts": [{
                    "body": "皇帝亲书手敕。",
                    "endorsement": {
                        "dossier_id": dossier_id, "form": "御笔手敕",
                        "endorser_id": "", "imperial": True,
                    },
                }],
            }, ensure_ascii=False)

    result = trail_extraction_after_reply(
        db=db,
        minister_name=minister,
        minister_reply=minister_reply,
        chat_turn_id=chat_turn_id,
        llm_config=object(),
        write_gate=threading.Lock(),
        extractor_agent=_CaptureAgent(),
    )
    assert result is not None and result["status"] == "done"
    assert len(seen_materials) == 1  # 单次抽取，无第二趟
    assert emperor_text in seen_materials[0]
    assert minister_reply in seen_materials[0]

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
    # ADR 0005 / 严格类型：写边界拒收非 bool，不得 bool("false")/bool(1) 归一化搭救。
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
    result = _extract(
        db, minister=minister, reply="臣愿会签此旨。",
        chat_turn_id=chat_turn_id, night_id=night_id, seq=seq,
        fact={
            "body": "大臣当殿愿为辽饷旨意会签。", "person_names": [minister],
            "tags": ["会签"], "endorsement": {
                "dossier_id": dossier_id, "form": "会签",
                "endorser_id": minister, "imperial": False,
            },
        },
    )
    assert result["status"] == "done"
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


def test_bad_endorsement_item_is_rejected_without_rolling_back_valid_sibling(game):
    db, state, _content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="mixed-endorsements",
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣愿会签。",
        chat_turn_id=chat_turn_id, night_id=night_id, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_Agent({"facts": [
            {"body": "合法事实", "person_names": [minister]},
            {"body": "坏背书", "endorsement": {
                "dossier_id": "not-an-id", "form": "会签", "endorser_id": minister,
            }},
        ]}),
    )
    assert result["status"] == "done"
    assert result["fact_count"] == 1
    assert [row["body"] for row in an.list_ledger(db, night_id) if row.get("source_chat_turn_id")] == ["合法事实"]
    rejection = db.conn.execute(
        "SELECT section, category FROM rejection_reports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert dict(rejection) == {"section": "story_facts", "category": "invalid_item"}


def test_normal_post_reply_defers_once_until_close_night_creates_dossier(game):
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
    calls = []

    class _SameNightAgent:
        def run(self, materials):
            calls.append(json.loads(materials))
            candidates = calls[-1]["可背书案卷"]
            assert len(candidates) == 1
            assert candidates[0]["ref"] == {"dossier_id": candidates[0]["ref"]["dossier_id"]}
            assert candidates[0]["decree_text"] == "清核辽饷"
            return json.dumps({"facts": [{
                "body": "皇帝亲书手敕。", "endorsement": {
                    "dossier_ref": candidates[0]["ref"], "form": "御笔手敕",
                    "endorser_id": "", "imperial": True,
                },
            }]}, ensure_ascii=False)

    extracted = trail_extraction_after_reply(
        db=db, minister_name=minister, minister_reply="臣叩领圣恩。",
        chat_turn_id=chat_turn_id, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=_SameNightAgent(),
    )
    assert extracted["status"] == "deferred"
    assert calls == []
    assert db.get_story_extract_status(chat_turn_id) == ""
    assert db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_dossier_endorsements'"
    ).fetchone() is None

    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=threading.Lock(), extractor_agent=_SameNightAgent(),
    )
    assert result["closed"] is True
    dossiers = db.list_decree_dossiers(status="proposed")
    assert len(dossiers) == 1
    assert len(calls) == 1
    assert emperor_text == calls[0]["皇帝问话"]
    assert db.list_dossier_endorsements(int(dossiers[0]["id"]))[0]["imperial"] is True


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


def test_close_extraction_failure_reopens_at_transfer_and_can_continue(game):
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣愿作保。")
    candidate_id = db.stage_directive_candidate(
        state.turn, minister,
        payload={"text": "清核辽饷", "dossier_action_type": "policy",
                 "target_kind": "issue", "target_id": "retryable", "actor": minister},
    )
    db.mark_pending_night_approved([candidate_id], night_id=night_id)

    class _Boom:
        def run(self, _materials):
            raise RuntimeError("extract boom")

    with pytest.raises(an.AudienceNightError) as exc:
        an.close_night(
            db, state, night_id=night_id, content=content, llm_config=object(),
            write_gate=threading.Lock(), extractor_agent=_Boom(),
        )
    assert exc.value.code == "pending_extraction"
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert failed["close_commit_cursor"] == an.CLOSE_STEP_TRANSFER_CANDIDATES
    assert db.get_story_extract_status(chat_turn_id) == "pending"
    assert db.list_night_approved_pending(night_id, kind="directive") == []
    assert len(db.list_decree_dossiers(status="proposed")) == 1

    result = an.close_night(
        db, state, night_id=night_id, content=content, llm_config=object(),
        write_gate=threading.Lock(), extractor_agent=_Agent({"facts": []}),
    )
    assert result["closed"] is True
    assert db.get_story_extract_status(chat_turn_id) == "done"
    assert len(db.list_decree_dossiers(status="proposed")) == 1


def test_parse_extraction_facts_keeps_valid_endorsement_and_rejects_bad_shape():
    facts = parse_extraction_facts({
        "facts": [{
            "body": "大臣愿会签。", "person_names": ["毕自严"],
            "audibility": "殿上公开", "tags": ["会签"],
            "endorsement": {
                "dossier_id": 3, "form": "会签", "endorser_id": "毕自严",
                "imperial": False,
            },
        }],
    })
    assert facts[0]["endorsement"] == {
        "dossier_id": 3, "form": "会签", "endorser_id": "毕自严", "imperial": False,
    }

    with pytest.raises(ExtractionShapeError, match="endorsement"):
        parse_extraction_facts({
            "facts": [{
                "body": "坏背书", "endorsement": {
                    "dossier_id": "3", "form": "会签", "endorser_id": "毕自严",
                },
            }],
        })
    with pytest.raises(ExtractionShapeError, match="endorsement"):
        parse_extraction_facts({
            "facts": [{
                "body": "坏形式", "endorsement": {
                    "dossier_id": 1, "form": "联署", "endorser_id": "毕自严",
                },
            }],
        })
