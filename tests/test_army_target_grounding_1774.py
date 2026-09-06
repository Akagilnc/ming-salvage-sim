"""#1774 军队目标接地：两真实入口共同准入语义 + 皇帝自然表达无须报机器 ID。

诊断：两入口共用 require_materializable_xiexang_payload，同一 raw 下规范化
target_id / 可物化 / typed 拒因一致（H2 证伪）；「关宁军前」不可物化是供料缺口
（H1 证实）。刀口：army_identity_aliases 编成抽取接地事实，写缝仍 exact。

Seams（真实入口 / 抽取 LLM 边界；不测私有 helper 内部结构）：
- extract_draft_intent → _run_backend_for_config（供料调用输入）
- POST chat/stream 拟旨 / POST /api/directives（共同准入）
- ensure_dossiers_for_draft_directives（手拟成案）
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cli_backend
from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.matching import army_identity_aliases
from ming_sim.session import GameSession

AUDIENCE_MESSAGE = (
    "着户部从国库拨银十五万两，解赴关宁军前专补欠饷。卿即拟旨呈览。"
)
MANUAL_TEXT = "命户部从国库核拨欠饷十五万两，解赴关宁军前，不得加派于民。"


def _canned_draft(target: str) -> dict:
    """真实局同形 draft_intent 返回（附件 1772 trace）。"""
    return {
        "拟旨意图": "拟旨",
        "动作类型": "grant_allocation",
        "entries": [],
        "恩赏拨帑": "协饷",
        "姓名": "郭允厚",
        "目标": target,
        "目标类型": "army",
        "金额": 15,
        "账户": "国库",
        "用途": "补饷",
        "拨付节奏": "一次性",
        "颁布方式": "ordinary",
        "执行面": "in_transit",
        "目标候选": target,
        "目标ID": "",
        "地区ID": "",
        "施行范围": "",
        "事务类别": "",
        "承办人": "郭允厚",
        "参与人": [],
        "期限月数": None,
        "目标案卷ID": None,
    }


def _active_ming_minister(db, content, *, office: str | None = None):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and (office is None or getattr(ch, "office_type", "") == office)
        and db.get_character_status(ch.name)[0] == "active"
    )


def _run_audience_draft(db, state, content, monkeypatch, *, message: str, canned: dict):
    """召对拟旨真实缝（同 #1729）：preclassified draft → materialize。"""
    minister = _active_ming_minister(db, content)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(canned, ensure_ascii=False), 1),
    )
    session = types.SimpleNamespace(
        db=db, state=state, content=content,
        llm_config=types.SimpleNamespace(channel="cli"), registry=None,
    )
    return GameSession.apply_cli_conversation_actions(
        session, minister, player_message=message, answer="臣谨拟旨，请陛下裁可。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )


def _persisted_payload(db, pending_id: int) -> dict:
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert row is not None
    return json.loads(row["payload_json"])


def _admission_from_audience(out: dict) -> dict:
    """外部可见准入结果：规范化 target_id 或 typed 拒因。"""
    failure = out.get("decree_validation_failure") or {}
    failed = set(failure.get("failed_fields") or [])
    pending_id = int(out.get("pending_action_id") or 0)
    return {
        "landed": pending_id > 0,
        "target_id": None,  # 调用方填
        "failed_fields": frozenset(failed),
        "has_report": bool(failure.get("report")),
    }


# ── 供料：抽取 LLM 边界一次特征化观察（同 #1428 人物 roster 缝）──────────


def test_extract_draft_intent_prompt_grounds_army_identity_when_content_given(
    game, monkeypatch,
):
    """抽取调用输入须含军队 canonical id 与身份别名（特征化观察，不锁标题/句式）。"""
    db, _state, content = game
    seen: list[str] = []
    guanning = content.armies["guanning"]
    aliases = army_identity_aliases(guanning)

    def backend(prompt, *_a, **_k):
        seen.append(prompt)
        return json.dumps(_canned_draft("@guanning"), ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    cli_backend.extract_draft_intent(
        AUDIENCE_MESSAGE, "臣谨拟旨。", content=content, db=db,
    )
    assert seen, "须调用抽取"
    prompt = seen[0]
    # 机面 canonical id 与身份别名出现在调用输入（#1428 同规特征化，不锁模板措辞）
    assert "guanning" in prompt
    assert "关宁军" in prompt
    for alias in aliases:
        if alias in ("guanning", "关宁军 / 宁锦防线"):
            continue
        assert alias in prompt, alias


# ── 验收 1：同产物两入口共同准入（结构化字段）──────────────────────────


@pytest.mark.parametrize(
    ("target", "expect"),
    [
        ("关宁军", {"landed": True, "target_id": "guanning", "failed_fields": frozenset()}),
        ("@guanning", {"landed": True, "target_id": "guanning", "failed_fields": frozenset()}),
        (
            "关宁军前",
            {
                "landed": False,
                "target_id": None,
                "failed_fields": frozenset({"target_id", "target_kind"}),
            },
        ),
        (
            "",
            {
                "landed": False,
                "target_id": None,
                "failed_fields": frozenset({"target_id"}),
            },
        ),
        (
            "宁远军前",
            {
                "landed": False,
                "target_id": None,
                "failed_fields": frozenset({"target_id", "target_kind"}),
            },
        ),
    ],
)
def test_audience_and_manual_share_xiexang_admission(game, monkeypatch, target, expect):
    """同盘面同原始返回：两入口规范化 target_id / 可物化 / typed 拒因一致。"""
    db, state, content = game
    canned = _canned_draft(target)
    raw = json.dumps(canned, ensure_ascii=False)

    # ── 召对 ──
    out = _run_audience_draft(
        db, state, content, monkeypatch,
        message=AUDIENCE_MESSAGE, canned=canned,
    )
    audience = _admission_from_audience(out)
    pending_id = int(out.get("pending_action_id") or 0)
    if pending_id > 0:
        audience["target_id"] = _persisted_payload(db, pending_id).get("target_id")
    else:
        audience["target_id"] = None

    # 清夜内暂存，再走手拟（同盘面，不串扰）
    if pending_id > 0:
        db.conn.execute("DELETE FROM pending_actions WHERE id=?", (pending_id,))
        db.conn.commit()

    # ── 手拟：capture 真缝（与 POST /api/directives 同 capture）──
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (raw, 1),
    )
    manual = {"landed": False, "target_id": None, "failed_fields": frozenset(), "has_report": False}
    try:
        payload = _real_capture(MANUAL_TEXT, None, db=db, content=content, capture_timeout_s=0)
        if (
            payload.get("dossier_action_type") == "grant_allocation"
            and payload.get("grant_action") == "协饷"
            and payload.get("target_id")
        ):
            manual = {
                "landed": True,
                "target_id": payload.get("target_id"),
                "failed_fields": frozenset(),
                "has_report": False,
            }
    except Exception as exc:
        # capture 把 DecreeMaterializationValidationError 透为 ValueError；
        # 取 typed failed_fields（若有）——与召对 decree_validation_failure 同权威。
        fields = getattr(exc, "failed_fields", None)
        if fields is None and getattr(exc, "__cause__", None) is not None:
            fields = getattr(exc.__cause__, "failed_fields", None)
        manual = {
            "landed": False,
            "target_id": None,
            "failed_fields": frozenset(str(f) for f in (fields or ())),
            "has_report": False,
        }
        # 手拟 HTTP 层无 failed_fields 时，从消息仍不得抠散文；用 require 再取一次 typed。
        if not manual["failed_fields"]:
            from ming_sim.action_materialize import (
                DecreeMaterializationValidationError,
                require_materializable_xiexang_payload,
            )
            try:
                require_materializable_xiexang_payload(
                    db,
                    text=MANUAL_TEXT,
                    amount=canned.get("金额") or canned.get("amount"),
                    account=str(canned.get("账户") or canned.get("account") or ""),
                    purpose=str(canned.get("用途") or canned.get("purpose") or ""),
                    target_kind=str(canned.get("目标类型") or canned.get("target_kind") or ""),
                    target_id=str(
                        canned.get("目标") or canned.get("目标ID") or canned.get("target_id") or ""
                    ),
                    cadence=str(canned.get("拨付节奏") or canned.get("cadence") or ""),
                )
            except DecreeMaterializationValidationError as typed:
                manual["failed_fields"] = frozenset(str(f) for f in typed.failed_fields)

    # 共同准入语义：可物化、规范化 target_id、typed 拒因
    assert audience["landed"] == expect["landed"] == manual["landed"]
    assert audience["target_id"] == expect["target_id"] == manual["target_id"]
    assert audience["failed_fields"] == expect["failed_fields"] == manual["failed_fields"]
    if expect["landed"]:
        assert not audience["failed_fields"]
    else:
        assert expect["failed_fields"] <= audience["failed_fields"]
        assert expect["failed_fields"] <= manual["failed_fields"]
        # 召对不可解析须有戏内回禀通道（有 report 键即可，不锁措辞）
        assert audience["has_report"]


# ── 验收 2：召对应允收夜 ──────────────────────────────────────────────


def test_audience_grounded_army_pay_lands_through_close_night(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """拟旨 → 皇帝应允 → 收夜 → GET state；目标/金额正确、无重复。"""
    from fastapi.testclient import TestClient

    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state, _post_issue_stream, _resolve_decisions_via_stream, _stub_outer_llm_seams,
        _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes
    from tests.test_audience_background import RunContent, RunOutput

    class _Agent:
        def __init__(self):
            self._n = 0

        def run(self, *_a, **_k):
            self._n += 1
            text = "臣领旨，谨拟敕谕。" if self._n == 1 else "臣遵旨，即刻解发。"
            return iter((RunContent(text), RunOutput([])))

        def get_last_run_output(self):
            return None

    monkeypatch.setattr(cli_backend, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)

    def backend(_prompt, _config=None, *, tag=""):
        if tag == "action_intent":
            return json.dumps({"kind": "draft"}, ensure_ascii=False), 1
        if tag == "draft_intent":
            return json.dumps(_canned_draft("@guanning"), ensure_ascii=False), 1
        return "臣谨回禀。", 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    monkeypatch.setattr(
        cli_backend, "extract_confirmation_intent",
        lambda player_message, *_a, **_k: (
            "应允" if str(player_message or "").strip() == "准" else "无"
        ),
    )

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        if game.session.llm_config is not None:
            game.session.llm_config.channel = "cli"
        name = _active_ming_minister(game.db, game.content, office="户部").name
        game.session.registry.get = lambda _ch: _Agent()
        client = TestClient(web_app.app)
        turn_before = int(game.state.turn)

        draft = client.post(
            f"/api/ministers/{name}/chat/stream", json={"message": AUDIENCE_MESSAGE},
        )
        assert draft.status_code == 200, draft.text
        wait_pending_writes(game)
        pend = [
            json.loads(r["payload_json"])
            for r in game.db.list_pending_actions(game.state.turn)
            if r["kind"] == "directive"
        ]
        assert [p.get("target_id") for p in pend] == ["guanning"]

        approve = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert approve.status_code == 200, approve.text
        wait_pending_writes(game)

        body = _post_issue_stream(client, expected_turn=turn_before, step="#1774 收夜")
        if body.get("awaiting_decision"):
            _resolve_decisions_via_stream(
                client, body.get("decisions") or [], step="#1774 亲裁",
            )
        wait_pending_writes(game)

        assert _turn_of(_get_state(client)) == turn_before + 1
        pay = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation" and d["target_id"] == "guanning"
        ]
        assert len(pay) == 1, pay
        payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (pay[0]["id"],),
        ).fetchone()[0])
        assert payload["grant_action"] == "协饷"
        assert int(payload["amount"]) == 15
        assert payload["account"] == "国库"
    finally:
        wait_pending_writes(game)
        if game.session:
            game.session.close()


def test_audience_unresolvable_army_target_forms_no_case(game, monkeypatch):
    """追问案：不可解析 → typed failed_fields + 零落桌零成案（不锁回禀措辞）。"""
    db, state, content = game
    out = _run_audience_draft(
        db, state, content, monkeypatch,
        message=AUDIENCE_MESSAGE, canned=_canned_draft("平辽大军"),
    )
    failure = out.get("decree_validation_failure") or {}
    assert {"target_id", "target_kind"} <= set(failure.get("failed_fields") or [])
    assert failure.get("report")  # 有回禀通道即可，不锁正文
    assert not int(out.get("pending_action_id") or 0)
    assert not [
        r for r in db.list_pending_actions(state.turn) if r["kind"] == "directive"
    ]
    assert db.ensure_dossiers_for_draft_directives(state) == []
    assert not db.list_decree_dossiers()


# ── 验收 3：手拟可见结果 + 成案边界 ────────────────────────────────────


def test_manual_grounded_army_pay_directive_forms_case(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """POST /api/directives 可见结果；ensure_dossiers 真实成案。"""
    from fastapi.testclient import TestClient

    import web_app
    from tests.test_month_loop_tracer_1468 import _stub_outer_llm_seams
    from tests.test_session_write_queue_1353 import wait_pending_writes

    monkeypatch.setattr(cli_backend, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(_canned_draft("@guanning"), ensure_ascii=False), 1),
    )

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        if game.session.llm_config is not None:
            game.session.llm_config.channel = "cli"
        client = TestClient(web_app.app)
        resp = client.post("/api/directives", json={"text": MANUAL_TEXT, "notes": ""})
        assert resp.status_code == 200, resp.text
        wait_pending_writes(game)
        body = resp.json()
        assert body["directive"]["status"] == "draft"
        assert body["directive"]["text"] == MANUAL_TEXT
        drafts = game.db.list_directives(game.state, statuses=("draft",))
        assert len(drafts) == 1
        payload = game.db.read_directive_dossier_payload(drafts[0])
        assert payload.get("target_id") == "guanning"

        assert game.db.ensure_dossiers_for_draft_directives(game.state) == []
        cases = game.db.list_decree_dossiers()
        assert len(cases) == 1
        assert cases[0]["action_type"] == "grant_allocation"
        assert cases[0]["target_id"] == "guanning"
        case_payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (cases[0]["id"],),
        ).fetchone()[0])
        assert int(case_payload["amount"]) == 15
        assert case_payload["grant_action"] == "协饷"
    finally:
        wait_pending_writes(game)
        if game.session:
            game.session.close()
