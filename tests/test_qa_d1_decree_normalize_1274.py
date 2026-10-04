"""#1274 QA D-1 拟诏归一残余：验证庭 r1 四类处方聚焦测。

1) #1391 泛称闭集（大臣）capture 零 409；「不存在之人甲」仍 409
2) #1331/#1339 起居注 involved_people 投影滤非人；默认时辰非「此时」
3) #1341/#1338 PATCH /api/decree 零调用方已拆，OpenAPI/实现一致
4) 补交抽取核：结构字段按 LLM 结果落地
"""

from __future__ import annotations

import json

import pytest


# ── 1) #1391 泛称闭集 ──────────────────────────────────────────────


from types import SimpleNamespace
def test_capture_drops_dachen_generic_no_409(game, monkeypatch):
    """#1391：参与人「大臣」不进 roster、零 409，草案可落库。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    text = "着大臣核办边饷，不得加派于民"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "border-pay",
        "参与人": [
            {"character_id": "大臣", "tier": "主办"},
            {"character_id": "毕自严", "tier": "协办"},
        ],
    }

    def backend(prompt, *_a, **_k):
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.resubmit_draft_admission_payload(
        text, bad_payload={}, failure_reason="成案未入档",
        db=db, content=content,
    )
    ids = [str(item["character_id"]) for item in (payload.get("participant_roster") or [])]
    assert "大臣" not in ids
    assert ids == ["毕自严"]

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = SimpleNamespace(
        id=db.add_directive(state, None, text, "手动新增", dossier_payload=payload),
        text=text, status="draft",
    )
    assert dv.id > 0
    assert any(int(r["id"]) == int(dv.id) for r in db.list_directives(state))


def test_capture_unknown_person_still_409(game, monkeypatch):
    """#1391 负向：纠错耗尽后真正不存在之人仍拒收（ADR 0053 缝不松；#1274 V-1 人话）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着不存在之人甲核太仓"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "x",
        "参与人": [{"character_id": "不存在之人甲", "tier": "主办"}],
    }
    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.resubmit_draft_admission_payload(
            text, bad_payload={}, failure_reason="成案未入档",
            db=db, content=content,
        )


@pytest.mark.parametrize("name", ["大臣", "群臣", "边将", "朝鲜边军", "陛下", "皇帝"])
def test_is_non_person_covers_generics_and_collectives(name):
    """泛称/集体通名单真源（participant_roster）覆盖票面字样。"""
    from ming_sim.participant_roster import is_non_person_participant_name
    import ming_sim.cli_backend as cli_backend

    assert is_non_person_participant_name(name) is True
    # cli_backend 别名同源，禁平行第二份闭集
    assert cli_backend._is_non_person_participant_name(name) is True


# ── 2) #1331/#1339 起居注投影 ──────────────────────────────────────


def test_night_archive_involved_people_drops_non_persons(game):
    """投影缝：户部/陛下/皇帝/朝鲜边军/大臣不进；王承恩/杨嗣昌保留。"""
    import ming_sim.audience_night as an

    db, state, _ = game
    night = an.open_night(db, state)  # 默认时辰须为更次口径
    assert night["time_of_day"] == an.DEFAULT_TIME_OF_DAY

    an.summon_enter(db, night["id"], "杨嗣昌", method=an.METHOD_XUANRU)
    an.append_ledger_entry(
        db, night["id"],
        tags=["军务"],
        person_names=[
            "王承恩", "杨嗣昌", "皇帝", "陛下", "户部", "大臣",
            "朝鲜边军", "边将", "司礼监",
        ],
    )
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (night["id"],),
    )
    db.conn.commit()

    entries = db.list_closed_night_archives()
    assert len(entries) == 1
    people = entries[0]["involved_people"]
    for banned in ("户部", "陛下", "皇帝", "朝鲜边军", "大臣", "边将", "司礼监"):
        assert banned not in people, banned
    assert "王承恩" in people
    assert "杨嗣昌" in people


# ── 3) #1341/#1338 PATCH 死契约拆除 ────────────────────────────────
# 退役闸类负向由 tests/test_web_audience_night_498.py::
# test_asgi_dossiered_directive_has_no_retired_review_surface 真实 HTTP 承担；
# 不在此维护 app.routes / OpenAPI 注册表平行证明。


# ── 4) 补交抽取核 ────────────────────────────────────────────────


def test_normal_capture_path_unchanged(game, monkeypatch):
    """正常抽取路径：结构字段仍按 LLM 结果落地（非一律 special_decree）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着毕自严核清太仓实存"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "treasury-audit",
        "参与人": [{"character_id": "毕自严", "tier": "主办"}],
    }
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    payload = cli_backend.resubmit_draft_admission_payload(
        text, bad_payload={}, failure_reason="成案未入档",
        db=db, content=content,
    )
    assert payload["dossier_action_type"] == "policy"
    assert payload["target_id"] == "treasury-audit"
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
