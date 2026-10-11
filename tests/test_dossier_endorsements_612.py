"""#612 endorsement contracts — one real entry tracer per independent external seam."""

import json
from types import SimpleNamespace

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_translation import apply_audience_round_translation
from ming_sim.db import GameDB
from ming_sim.decree import build_promulgation_judge_context
from tests.readback_helpers import active_character_name as _minister


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

    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            999999, form="会签", endorser_id=minister,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            dossier_id, form="联名", endorser_id=minister,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            dossier_id, form="会签", endorser_id="",
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            dossier_id, form="御笔手敕", endorser_id=minister, imperial=True,
            source_chat_turn_id=chat_turn_id,
        )
    # imperial=False 负例：御笔手敕不得假借非御笔标记。
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            dossier_id, form="御笔手敕", endorser_id="", imperial=False,
            source_chat_turn_id=chat_turn_id,
        )
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(
            dossier_id, form="当面站台", endorser_id="不存在的人",
            source_chat_turn_id=chat_turn_id,
        )
    for bad_imperial in ("false", 1, 0, None):
        with pytest.raises(ValueError):
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
