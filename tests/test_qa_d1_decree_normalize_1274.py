"""#1274 QA D-1 拟诏归一残余：验证庭 r1 四类处方聚焦测。

1) #1391 泛称闭集（大臣）capture 零 409；「不存在之人甲」仍 409
2) #1331/#1339 起居注 involved_people 投影滤非人；默认时辰非「此时」
3) #1341/#1338 PATCH /api/decree 零调用方已拆，OpenAPI/实现一致
4) #1327 空载短路；#1465 切片③：外层 30s 总罩已删
"""

from __future__ import annotations

import json
import types
import threading

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
    from tests.directive_entry_helpers import live_draft_payload

    payload = live_draft_payload(text, None, db=db, content=content)
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
    from tests.directive_entry_helpers import live_draft_payload

    with pytest.raises(ValueError) as ei:
        live_draft_payload(text, None, db=db, content=content)
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


def test_patch_decree_and_manual_directive_routes_removed():
    """#1341 删 PATCH /api/decree；#1902 再删拟诏台手写拟旨/改稿路由，只留删旧草稿。"""
    import web_app

    patch_decree = [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/decree"
        and "PATCH" in (getattr(r, "methods", None) or set())
    ]
    assert patch_decree == []
    assert not hasattr(web_app, "api_edit_decree")

    manual_writes = [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/directives"
        and ({"POST", "PATCH"} & (getattr(r, "methods", None) or set()))
    ]
    assert manual_writes == [], "拟诏台手写拟旨/改稿路由必须已退役"
    assert [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/directives/{directive_id}"
        and "DELETE" in (getattr(r, "methods", None) or set())
    ], "删旧草稿入口保留"


# ── 4) #1327 空载/有界 capture ─────────────────────────────────────


def test_web_create_directive_long_extract_still_lands_real_draft(game, monkeypatch):
    """#1465 切片③：拟旨 capture 跨旧 30s 罩仍成案（真实入口 → 读回 pending 案卷）。

    真实抽取核入口（#1902 后经会话写入面）；抽取把注入时钟推过 120s（旧外层 30s 总罩下
    remaining 会扣穿 → 抽取被饿死、落 special_decree 或 LLMUnavailable）。罩既已
    删，长抽取仍须落**真**草案：结构字段照 LLM 结果走，且读回 pending/案卷可见。
    确定性、无线程、不跑真墙钟。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cli_backend
    import web_app
    from ming_sim.session import GameSession

    db, state, content = game
    text = "着毕自严核清太仓实存"
    clock = {"t": 1000.0}
    monkeypatch.setattr(
        cli_backend, "time", types.SimpleNamespace(monotonic=lambda: clock["t"]),
    )
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(tag)
        clock["t"] += 120.0  # 单次抽取就跨过旧 30s 总罩
        return (
            json.dumps({
                "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
                "目标ID": "treasury-audit",
                "参与人": [{"character_id": "毕自严", "tier": "主办"}],
            }, ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    web_game = types.SimpleNamespace(
        _write_gate=threading.Lock(),
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: db.list_directives(
            state, statuses=("pending", "draft"),
        ),
        directive_payload=lambda row: dict(row),
    )
    # #1902：摆一条 draft 作**测试数据准备**（拟诏台入口已退役，玩家拟旨只从召对来）。
    from tests.directive_entry_helpers import stage_draft_directive

    staged = stage_draft_directive(session, text)
    assert clock["t"] - 1000.0 > 30.0, clock  # 确实跨过旧罩
    directive_id = int(staged.id)
    assert directive_id > 0
    assert staged.text == text
    rows = db.list_directives(state, statuses=("pending", "draft"))
    row = next(item for item in rows if int(item["id"]) == directive_id)
    payload = db.read_directive_dossier_payload(row)
    assert payload.get("dossier_action_type") == "policy"
    assert payload.get("target_id") == "treasury-audit"
    assert [str(i["character_id"]) for i in (payload.get("participant_roster") or [])] == [
        "毕自严",
    ]


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
    from tests.directive_entry_helpers import live_draft_payload

    payload = live_draft_payload(text, None, db=db, content=content)
    assert payload["dossier_action_type"] == "policy"
    assert payload["target_id"] == "treasury-audit"
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
