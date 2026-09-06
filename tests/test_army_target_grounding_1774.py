"""#1774 军队目标接地：两真实入口共同准入语义 + 皇帝自然表达无须报机器 ID。

诊断结论（本卷取证）：两入口（召对拟旨 / 手拟）共用
``require_materializable_xiexang_payload``，同一原始模型返回下规范化 target_id、
可物化判定与 typed 拒因逐字一致——H2「两套校验」证伪。真正的体验根因是抽取器
根本没被告知军队 canonical id 与身份别名，皇帝最自然的说法（「解赴关宁军前」）
落不到 guanning——H1 证实。

刀口：把既有 ``matching.army_identity_aliases`` 编成抽取接地事实块喂给抽取器
（同 ``_pay_order_grounding_facts`` 地区 ``name=@id`` 与 #1428 人物 roster 供料模式），
写缝 ``canonical_army_id_exact`` 仍是精确等值，不新增模糊匹配/子串升格。

Seams:
- cli_backend._draft_intent_army_grounding_facts（接地事实；单源=army_identity_aliases）
- cli_backend.extract_draft_intent 两分支 prompt（真实 LLM 边界 _run_backend_for_config）
- POST /api/ministers/{name}/chat/stream（召对拟旨）/ POST /api/directives（手拟）
- action_materialize.require_materializable_xiexang_payload（两入口共用准入）
- db.ensure_dossiers_for_draft_directives（手拟真实成案边界）
"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import _draft_intent_army_grounding_facts
from ming_sim.matching import army_identity_aliases

AUDIENCE_MESSAGE = (
    "着户部从国库拨银十五万两，解赴关宁军前专补欠饷。卿即拟旨呈览。"
)
MANUAL_TEXT = "命户部从国库核拨欠饷十五万两，解赴关宁军前，不得加派于民。"


def _canned_draft(target: str) -> dict:
    """真实局同形的 draft_intent 原始返回（附件 1772 trace 逐字段同形）。"""
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


class _AudienceAgent:
    """召对回话替身：只顶大臣 agent，抽取/校验/物化全走真链。"""

    def __init__(self, replies=("臣领旨，谨拟敕谕。",)):
        self._replies = list(replies)
        self._calls = 0

    def run(self, *_args, **_kwargs):
        from tests.test_audience_background import RunContent, RunOutput

        idx = min(self._calls, len(self._replies) - 1)
        self._calls += 1
        return iter((RunContent(self._replies[idx]), RunOutput([])))

    def get_last_run_output(self):
        return None


def _boot_game(tmp_path, monkeypatch, *, draft_raw: str, prompts: dict):
    """真实 WebGame + TestClient；模型替身只置于 _run_backend_for_config。"""
    import ming_sim.cli_backend as cb
    from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
    import web_app
    from tests.test_month_loop_tracer_1468 import _stub_outer_llm_seams

    monkeypatch.setattr(cb, "_TRACE_PATH", str(tmp_path / "cli_trace.jsonl"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    # tracer 夹具把手拟 capture 整个替掉；本卷要真跑手拟准入，装回真件。
    monkeypatch.setattr(cb, "capture_manual_directive_payload", _real_capture)

    def backend(prompt, _config=None, *, tag=""):
        prompts.setdefault(tag, prompt)
        if tag == "action_intent":
            return json.dumps({"kind": "draft"}, ensure_ascii=False), 1
        if tag == "draft_intent":
            return draft_raw, 1
        return "臣谨回禀，伏候圣裁。", 1

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    if getattr(game.session, "llm_config", None) is not None:
        game.session.llm_config.channel = "cli"
    return game


def _hubu_minister(game) -> str:
    return next(
        getattr(ch, "name", key)
        for key, ch in game.content.characters.items()
        if getattr(ch, "office_type", "") == "户部"
        and getattr(ch, "power_id", "ming") == "ming"
        and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
    )


def _shutdown(game) -> None:
    from tests.test_session_write_queue_1353 import wait_pending_writes

    wait_pending_writes(game)
    if game.session:
        game.session.close()


def _staged_target_ids(game) -> list:
    return [
        json.loads(row["payload_json"]).get("target_id")
        for row in game.db.list_pending_actions(game.state.turn)
        if row["kind"] == "directive"
    ]


def _draft_directive_target_ids(game) -> list:
    return [
        game.db.read_directive_dossier_payload(row).get("target_id")
        for row in game.db.list_directives(game.state, statuses=("draft",))
    ]


def test_army_grounding_facts_carry_canonical_id_and_identity_aliases(content):
    """接地事实块单源于 army_identity_aliases：每军一行 canonical id + 身份别名。

    驻地/战区/将领/统属是模糊 matcher 的上下文，不是身份别名，不得混入供料。
    """
    facts = _draft_intent_army_grounding_facts(content)
    assert facts.startswith("【军队接地事实】")
    lines = [line for line in facts.splitlines() if "=@" in line]
    assert len(lines) == len(content.armies)
    by_id = {line.rsplit("=@", 1)[1]: line for line in lines}
    assert set(by_id) == set(content.armies)
    for army_id, army in content.armies.items():
        head = by_id[army_id].rsplit("=@", 1)[0]
        name, _, alias_part = head.partition("（别名：")
        listed = {name} | {
            token for token in alias_part.rstrip("）").split("、") if token
        }
        # 供料词条恰是身份别名集合（含 id 本身），一个不多一个不少：
        # 驻地/战区/将领/统属属模糊 matcher 上下文，多出来即污染了身份轴。
        assert listed | {army_id} == set(army_identity_aliases(army)), army_id


@pytest.mark.parametrize("entrance", ["audience", "manual"])
@pytest.mark.parametrize(
    ("target", "expect_landed"),
    [
        ("关宁军", True),          # 既有受控身份别名
        ("@guanning", True),       # 接地后抽取器应产的机面 canonical id
        ("关宁军前", False),        # 玩家自然说法：接地前抽取器原样吐出 → 不可物化
        ("", False),               # 规范目标真空
        ("宁远军前", False),        # 未知目标（驻地说法不是身份别名）
    ],
)
def test_both_entrances_share_army_admission_outcome(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
    entrance, target, expect_landed,
):
    """验收 1：同盘面同原始返回，两真实入口共同准入语义一致。

    比较可物化判定与规范化 target_id；不比较夜内暂存与手拟 draft 行逐字同态。
    同一跑内断言 draft_intent 的**调用输入**已带军队接地事实（修复咬点）。
    """
    from fastapi.testclient import TestClient

    prompts: dict = {}
    game = _boot_game(
        tmp_path, monkeypatch,
        draft_raw=json.dumps(_canned_draft(target), ensure_ascii=False),
        prompts=prompts,
    )
    try:
        name = _hubu_minister(game)
        game.session.registry.get = lambda _ch: _AudienceAgent()
        client = TestClient(web_app_module().app)
        if entrance == "audience":
            resp = client.post(
                f"/api/ministers/{name}/chat/stream",
                json={"message": AUDIENCE_MESSAGE},
            )
            assert resp.status_code == 200, resp.text
            _shutdown_writes(game)
            landed = _staged_target_ids(game)
        else:
            resp = client.post(
                "/api/directives", json={"text": MANUAL_TEXT, "notes": ""},
            )
            _shutdown_writes(game)
            assert resp.status_code == (200 if expect_landed else 409), resp.text
            landed = _draft_directive_target_ids(game)

        assert landed == (["guanning"] if expect_landed else [])
        assert not game.db.list_decree_dossiers()

        draft_prompt = prompts.get("draft_intent") or ""
        assert "【军队接地事实】" in draft_prompt
        for army_id in game.content.armies:
            assert f"=@{army_id}" in draft_prompt
        assert "关宁军" in draft_prompt
    finally:
        _shutdown(game)


def test_audience_grounded_army_pay_lands_through_close_night(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """验收 2 正案：拟旨 → 皇帝应允 → 收夜 → GET state；目标/金额正确且不重复。"""
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    from tests.test_month_loop_tracer_1468 import (
        _get_state, _post_issue_stream, _resolve_decisions_via_stream, _turn_of,
    )

    prompts: dict = {}
    game = _boot_game(
        tmp_path, monkeypatch,
        draft_raw=json.dumps(_canned_draft("@guanning"), ensure_ascii=False),
        prompts=prompts,
    )
    try:
        name = _hubu_minister(game)
        game.session.registry.get = lambda _ch: _AudienceAgent(
            ("臣领旨，谨拟敕谕。", "臣遵旨，即刻解发。"),
        )
        monkeypatch.setattr(
            cb, "extract_confirmation_intent",
            lambda player_message, *_a, **_k: (
                "应允" if str(player_message or "").strip() == "准" else "无"
            ),
        )
        client = TestClient(web_app_module().app)
        turn_before = int(game.state.turn)

        draft = client.post(
            f"/api/ministers/{name}/chat/stream", json={"message": AUDIENCE_MESSAGE},
        )
        assert draft.status_code == 200, draft.text
        _shutdown_writes(game)
        assert _staged_target_ids(game) == ["guanning"]

        approve = client.post(f"/api/ministers/{name}/chat", json={"message": "准"})
        assert approve.status_code == 200, approve.text
        _shutdown_writes(game)

        body = _post_issue_stream(
            client, expected_turn=turn_before, step="#1774 收夜过月",
        )
        if body.get("awaiting_decision"):
            _resolve_decisions_via_stream(
                client, body.get("decisions") or [], step="#1774 亲裁",
            )
        _shutdown_writes(game)

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
        _shutdown(game)


def test_audience_unresolvable_army_target_asks_and_forms_no_case(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """验收 2 追问案：不可解析目标 → typed 失败字段 + 零落桌零成案（不锁回禀措辞）。"""
    from fastapi.testclient import TestClient

    from tests.test_menu_continue_stream_1195 import _parse_sse

    prompts: dict = {}
    game = _boot_game(
        tmp_path, monkeypatch,
        draft_raw=json.dumps(_canned_draft("平辽大军"), ensure_ascii=False),
        prompts=prompts,
    )
    try:
        name = _hubu_minister(game)
        game.session.registry.get = lambda _ch: _AudienceAgent()
        client = TestClient(web_app_module().app)
        resp = client.post(
            f"/api/ministers/{name}/chat/stream", json={"message": AUDIENCE_MESSAGE},
        )
        assert resp.status_code == 200, resp.text
        _shutdown_writes(game)

        events = _parse_sse(resp.text)
        assert all(event != "error" for event, _payload in events)
        done = next(payload for event, payload in events if event == "done")
        failure = done.get("decree_validation_failure") or {}
        assert {"target_id", "target_kind"} <= set(failure.get("failed_fields") or [])
        assert failure.get("report")
        assert _staged_target_ids(game) == []
        assert game.db.ensure_dossiers_for_draft_directives(game.state) == []
        assert not game.db.list_decree_dossiers()
    finally:
        _shutdown(game)


def test_manual_grounded_army_pay_directive_forms_case(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """验收 3：手拟 POST /api/directives 可见结果 + 真实成案边界 ensure_dossiers。"""
    from fastapi.testclient import TestClient

    prompts: dict = {}
    game = _boot_game(
        tmp_path, monkeypatch,
        draft_raw=json.dumps(_canned_draft("@guanning"), ensure_ascii=False),
        prompts=prompts,
    )
    try:
        client = TestClient(web_app_module().app)
        resp = client.post(
            "/api/directives", json={"text": MANUAL_TEXT, "notes": ""},
        )
        assert resp.status_code == 200, resp.text
        _shutdown_writes(game)
        body = resp.json()
        assert body["directive"]["status"] == "draft"
        assert body["directive"]["text"] == MANUAL_TEXT
        assert _draft_directive_target_ids(game) == ["guanning"]

        assert game.db.ensure_dossiers_for_draft_directives(game.state) == []
        cases = game.db.list_decree_dossiers()
        assert len(cases) == 1, cases
        assert cases[0]["action_type"] == "grant_allocation"
        assert cases[0]["target_id"] == "guanning"
        payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (cases[0]["id"],),
        ).fetchone()[0])
        assert int(payload["amount"]) == 15
        assert payload["grant_action"] == "协饷"
    finally:
        _shutdown(game)


def web_app_module():
    import web_app

    return web_app


def _shutdown_writes(game) -> None:
    from tests.test_session_write_queue_1353 import wait_pending_writes

    wait_pending_writes(game)
