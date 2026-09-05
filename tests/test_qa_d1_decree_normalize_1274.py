"""#1274 QA D-1 拟诏归一残余：验证庭 r1 四类处方聚焦测。

1) #1391 泛称闭集（大臣）capture 零 409；「不存在之人甲」仍 409
2) #1331/#1339 起居注 involved_people 投影滤非人；默认时辰非「此时」
3) #1341/#1338 PATCH /api/decree 零调用方已拆，OpenAPI/实现一致
4) #1327 空载短路 + 非空载有界超时降级 special_decree 草案照落
"""

from __future__ import annotations

import asyncio
import json
import time
import types

import pytest


# ── 1) #1391 泛称闭集 ──────────────────────────────────────────────


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
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(item["character_id"]) for item in (payload.get("participant_roster") or [])]
    assert "大臣" not in ids
    assert ids == ["毕自严"]

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
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
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    msg = str(ei.value)
    assert "不存在之人甲" in msg
    assert any(m in msg for m in ("乞陛下明示", "朝籍", "查无"))
    assert "参与人物不存在" not in msg  # F5：禁原始 409 泄漏


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
    assert night["time_of_day"] != "此时"
    assert night["time_of_day"] == an.DEFAULT_TIME_OF_DAY

    an.summon_enter(db, night["id"], "杨嗣昌", method=an.METHOD_XUANRU)
    an.append_ledger_entry(
        db, night["id"],
        body="议边饷。",
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
    # 标题不得出现「此时」
    assert "此时" not in str(entries[0]["title"])


def test_default_time_of_day_is_shichen_not_cishi():
    import ming_sim.audience_night as an

    assert an.DEFAULT_TIME_OF_DAY != "此时"
    # 时辰单字「时」结尾的更次/时刻口径
    assert an.DEFAULT_TIME_OF_DAY.endswith("时")


# ── 3) #1341/#1338 PATCH 死契约拆除 ────────────────────────────────


def test_patch_decree_route_removed_and_directives_remain():
    """调用方扫描结论：web/src 零真实调用 → 删路由；directives 入口仍在。"""
    import web_app

    patch_decree = [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/decree"
        and "PATCH" in (getattr(r, "methods", None) or set())
    ]
    assert patch_decree == []
    assert not hasattr(web_app, "api_edit_decree")

    post_dirs = [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/directives"
        and "POST" in (getattr(r, "methods", None) or set())
    ]
    assert post_dirs, "逐道旨意入口必须保留"


# ── 4) #1327 空载/有界 capture ─────────────────────────────────────


def test_empty_text_capture_short_circuits_without_llm(monkeypatch):
    """空载：无可抽取正文 → 零 LLM、直落 special_decree。"""
    import ming_sim.cli_backend as cli_backend

    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("空载不得调用 LLM")

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", boom)
    monkeypatch.setattr(cli_backend, "extract_draft_intent", boom)

    payload = cli_backend.capture_manual_directive_payload("   ", None)
    assert payload["dossier_action_type"] == "special_decree"
    assert payload["target_id"] == "manual-directive"
    assert calls == []


def test_capture_timeout_degrades_to_special_decree_and_lands(game, monkeypatch):
    """非空载：LLM 慢/死时有界返回 special_decree，草案仍落库。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    text = "着户部核太仓实存，边饷京营优先发放。"

    def slow_extract(*_a, **_k):
        time.sleep(2.0)
        return {"draft_action": "拟旨", "dossier_action_type": "policy",
                "target_kind": "issue", "target_id": "x"}

    monkeypatch.setattr(cli_backend, "extract_draft_intent", slow_extract)

    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content, capture_timeout_s=0.3,
    )
    # 生产 capture_timeout_s 输入保留；旁侧 elapsed 墙钟证据删除（接缝无「N 秒内」契约）。
    assert payload["dossier_action_type"] == "special_decree"

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0
    assert any(r["text"] == text for r in db.list_directives(state))


def test_web_create_directive_bounded_when_capture_hangs(game, monkeypatch):
    """POST /api/directives：capture 挂起时仍经生产 timeout 返回且草案落库。"""
    import ming_sim.cli_backend as cli_backend
    import web_app
    from ming_sim.session import GameSession

    db, state, content = game
    text = "着户部核太仓实存，不得加派于民。"

    # capture 内部超时路径：挂 extract，短 timeout
    def slow_extract(*_a, **_k):
        time.sleep(2.0)
        return {"draft_action": "无"}

    monkeypatch.setattr(cli_backend, "extract_draft_intent", slow_extract)
    # 压短默认有界，避免测时 20s
    monkeypatch.setattr(cli_backend, "MANUAL_DIRECTIVE_CAPTURE_TIMEOUT_S", 0.3)

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    web_game = types.SimpleNamespace(
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: db.list_directives(
            state, statuses=("pending", "draft"),
        ),
        directive_payload=lambda row: dict(row),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)

    result = asyncio.run(web_app.api_create_directive(
        web_app.DirectiveRequest(text=text, notes="朝堂QA拟诏"),
    ))
    # 生产 MANUAL_DIRECTIVE_CAPTURE_TIMEOUT_S 输入保留；旁侧 elapsed 墙钟证据删除。
    assert result["directive"]["id"] > 0
    assert result["directive"]["text"] == text
    assert db.list_directives(state)


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
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    assert payload["dossier_action_type"] == "policy"
    assert payload["target_id"] == "treasury-audit"
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
