"""#612 endorsement contracts — one real entry tracer per independent external seam."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.session_write_queue import SessionWriteQueue
from ming_sim.db import GameDB
from ming_sim.decree import build_promulgation_judge_context


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _extract(db, *, chat_turn_id, night_id, fact, **_ignored):
    """用现役转译入口落场景事实；背书测试不复活旧抽取员。"""
    row = db.conn.execute(
        "SELECT turn FROM chat_turns WHERE id=?", (int(chat_turn_id),),
    ).fetchone()
    apply_audience_round_translation(
        db, SimpleNamespace(turn=int(row["turn"])), {"scene_facts": [fact]},
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    return {"status": "done"}


def _night_reply(db, state, minister, reply="臣愿会签此旨。"):
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    an.ensure_summon_enter(db, night_id, minister)
    chat_turn_id = db.create_chat_turn(
        state, minister, "endorsement-612", 0, night_id=night_id,
    )
    db.persist_minister_reply(minister, state.turn, reply, chat_turn_id)
    row = db.conn.execute("SELECT night_seq FROM chat_turns WHERE id=?", (chat_turn_id,)).fetchone()
    return night_id, chat_turn_id, int(row["night_seq"] or 0)




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
        "decision_key": "",
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







def test_turn_translation_endorsement_inherits_on_close(game):
    """#1842：转译声明背书挂暂存 → 收夜成案继承；来源为声明轮。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣愿会签此旨。")
    action_id = _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷", target_id="liao-endorsement-1842",
    )
    # 应允后再声明背书（同轮转译顺序：promises 后 endorsements）
    apply_audience_round_translation(
        db, state,
        {
            "endorsements": [{
                "action_id": action_id,
                "form": "会签",
                "endorser_id": minister,
            }],
            "scene_facts": [{
                "body": "臣愿会签此旨。",
                "role": "minister",
                "audibility": "殿上公开",
                "person_names": [minister],
                "tags": [],
            }],
        },
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    payload = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()
    import json as _json
    loaded = _json.loads(payload["payload_json"])
    assert loaded["endorsements"][0]["form"] == "会签"
    assert loaded["endorsements"][0]["source_chat_turn_id"] == chat_turn_id

    write_queue = SessionWriteQueue()
    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=write_queue.write_gate,
        write_queue=write_queue,
    )
    assert result["closed"] is True
    dossiers = [
        row for row in db.list_decree_dossiers(status="proposed")
        if row["decree_text"] == "清核辽饷"
    ]
    assert len(dossiers) == 1
    ends = db.list_dossier_endorsements(int(dossiers[0]["id"]))
    assert len(ends) == 1
    assert ends[0]["form"] == "会签"
    assert ends[0]["endorser_id"] == minister
    assert ends[0]["source_chat_turn_id"] == chat_turn_id
    assert an.night_dossiers_ready(an.get_night(db, night_id))
    assert int(an.get_night(db, night_id)["close_commit_cursor"]) == an.CLOSE_STEP_FINALIZE


def test_turn_translation_endorsement_undo_clears_payload(game):
    """撤回声明轮 → 暂存载荷背书随前像还原（成案前）。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣愿会签。")
    action_id = _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷-撤", target_id="liao-undo-endorsement",
    )
    apply_audience_round_translation(
        db, state,
        {
            "endorsements": [{
                "action_id": action_id, "form": "会签", "endorser_id": minister,
            }],
            "scene_facts": [{
                "body": "臣愿会签。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        },
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    import json as _json
    before = _json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["payload_json"])
    assert before.get("endorsements")
    db.undo_chat_turn(chat_turn_id)
    after = _json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["payload_json"])
    assert not after.get("endorsements")


def test_close_night_no_longer_invokes_endorsement_llm(game, monkeypatch):
    """#1842：收夜路径不得再 import/调用 audience_extraction。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣领旨。")
    apply_audience_round_translation(
        db, state,
        {"scene_facts": [{
            "body": "臣领旨。", "role": "minister",
            "audibility": "殿上公开", "person_names": [minister], "tags": [],
        }]},
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    import sys
    sys.modules.pop("ming_sim.audience_extraction", None)
    # 若 close_night 仍 import audience_extraction，会 ModuleNotFoundError 或找到残壳
    monkeypatch.setitem(sys.modules, "ming_sim.audience_extraction", None)
    write_queue = SessionWriteQueue()
    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=write_queue.write_gate,
        write_queue=write_queue,
    )
    assert result["closed"] is True


def test_late_translation_endorsement_attaches_to_committed_dossier(game):
    """迟到路径：案卷已成 → 转译背书直写案卷。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="先应允。")
    action_id = _approve_directive(
        db, state, minister, night_id,
        text="清核辽饷-迟到", target_id="liao-late-endorsement",
    )
    write_queue = SessionWriteQueue()
    an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=write_queue.write_gate,
        write_queue=write_queue,
    )
    did = int(db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?",
        (action_id,),
    ).fetchone()["id"])
    assert db.list_dossier_endorsements(did) == []
    # 夜已关：只声明背书（不再写 scene_facts，避免已关夜账）
    apply_audience_round_translation(
        db, state,
        {"endorsements": [{
            "action_id": action_id, "form": "当面站台", "endorser_id": minister,
        }]},
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    ends = db.list_dossier_endorsements(did)
    assert len(ends) == 1
    assert ends[0]["form"] == "当面站台"
    assert ends[0]["source_chat_turn_id"] == chat_turn_id


def test_office_phase1_still_commits_without_endorsement_batch(game):
    """office 草稿成案不再等 endorsement-bound 水位。"""
    db, state, content = game
    minister = _minister(db)
    night_id, chat_turn_id, _seq = _night_reply(db, state, minister, reply="臣请准。")
    # stage office appointment
    name = minister
    office_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,),
    ).fetchone()
    office = str(office_row["office"] or "兵部尚书")
    pa_id = db.stage_pending_action(
        int(state.turn), "office", "任命", minister,
        {"name": name, "office": office, "text": f"准 {name} 仍任{office}"},
    )
    db.mark_pending_night_approved([pa_id], night_id=night_id)
    apply_audience_round_translation(
        db, state,
        {"scene_facts": [{
            "body": "臣请准。", "role": "minister",
            "audibility": "殿上公开", "person_names": [minister], "tags": [],
        }]},
        night_id=night_id, chat_turn_id=chat_turn_id,
    )
    write_queue = SessionWriteQueue()
    result = an.close_night(
        db, state, night_id=night_id, content=content,
        llm_config=object(), write_gate=write_queue.write_gate,
        write_queue=write_queue,
    )
    assert result["closed"] is True
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pa_id,),
    ).fetchone()["status"] == "committed"
