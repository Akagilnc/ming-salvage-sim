from __future__ import annotations
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import ming_sim.cli_backend as cb
import ming_sim.draft_intent as di
import ming_sim.session as session_mod
import web_app
from tests.sse_helpers import parse_sse_event_pairs
from ming_sim.error_pack import latest_error_pack_for_turn
from tests.army_pay_helpers import _set_guanning_arrears
from tests.test_month_loop_tracer_1468 import (
    _get_state,
    _post_issue_stream,
    _stub_outer_llm_seams,
    _turn_of,
)
from tests.test_session_write_queue_1353 import wait_pending_writes
from tests.test_month_loop_tracer_1468 import _get_state, _stub_outer_llm_seams, _turn_of
"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：草稿落桌（#1849 后走现行 capture 核 + session.add_directive；
独立手拟新增 Web 口已退役）→ POST /api/decree/issue/stream；
未入档草案在现行 resolve_turn 成案准入路径验证，不依赖已退役拟诏入口。
断言 SSE 终态与 turn_directives / rejection_reports / dossier 结构化字段。

本文件只断言结构化事实（供料入参 / 案卷字段 / DB 终态 / 错误包 manifest），
不扫 LLM 自由文本——回禀措辞由 LLM 自己长（P7 / ADR 0142）。

人工审读指针（验收 2 与 4，不锁 LLM 措辞）：
  - issue #1769 真实局证据：qa-1765-run3（driver.out / net-016-SSE /
    cli_trace_16204.jsonl / m-1627-10-t1-issue-error.png）；真实局 #3 为跨月留存局。
  - 验收 4：回禀是否把 override 键名/键族语法透传给皇帝，由人工核对该局。
  - 验收 2 的「下次召对大臣可就此追问」：本文件只证供料到位（召对组装输入含原旨
    与「尚未入档」事实）；大臣实际怎么开口追问，人工对着上述真实局与
    docs/AUDIENCE_NORTH_STAR.md 审读。
"""






_DECREE_TEXT = (
    "命户部尚书郭允厚从国库核拨关宁军欠饷十五万两，"
    "解赴宁远军前，十日内奏报实发数目，不得加派于民。"
)

# 产键证据同形（真实局 cli_trace_16204）
_BAD_PAY_ORDER = {
    "拟旨意图": "拟旨",
    "动作类型": "pay_order_override",
    "entries": [{"key": "arrears_priority_军饷", "value": 1}],
    "恩赏拨帑": "无",
    "目标": "关宁军",
    "目标类型": "army",
    "目标ID": "guanning",
    "金额": None,
    "账户": "国库",
    "用途": "补饷",
    "拨付节奏": "一次性",
    "颁布方式": "ordinary",
    "执行面": "in_transit",
    "施行范围": "无",
    "承办人": "郭允厚",
    "参与人": [],
    "期限月数": None,
    "目标案卷ID": None,
}

_GOOD_XIEANG = {
    "拟旨意图": "拟旨",
    "动作类型": "grant_allocation",
    "恩赏拨帑": "协饷",
    "用途": "补饷",
    "目标类型": "army",
    "目标": "关宁军",
    "目标ID": "guanning",
    "颁布方式": "ordinary",
    "金额": 15,
    "账户": "国库",
    "拨付节奏": "一次性",
    "执行面": "immediate",
    "承办人": "郭允厚",
    "参与人": [],
    "施行范围": "无",
    "期限月数": None,
    "目标案卷ID": None,
    "entries": [],
}


# 名册产物错同形：结构合法但点名朝中查无此人 → heal 耗尽 → UnknownParticipantEscalate
_UNKNOWN_NAME = "张三丰"
_BAD_UNKNOWN_PARTICIPANT = {
    **_GOOD_XIEANG,
    "参与人": [
        {"character_id": _UNKNOWN_NAME, "tier": "协办", "role": "转运",
         "delegator_id": None},
    ],
}


@pytest.fixture
def admission_game(web_game, monkeypatch):
    """共享 web_game；模型边界由各测 _queue_backend 喂。

    生命周期（开档／关档）只经 conftest.web_game；本夹具仅叠加准入特化：
    不替换结算、补交或写库行为；财政前置在开档后设定。
    """
    _stub_outer_llm_seams(monkeypatch)
    game = web_game
    if getattr(game.session, "llm_config", None) is not None:
        game.session.llm_config.channel = "cli"
    _set_guanning_arrears(game.db, 60, central=60, province=0)
    game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)
    # 非首回合区分相对月数与绝对期限，也保住正值已过期的拒收边界。
    game.state.turn = 7
    game.db.reign.save_game_state(game.state)
    return game


def _queue_backend(monkeypatch, captures: list) -> None:
    """模型边界供料：按序返回，队尾之后一直重复最后一条。

    队列枯竭**不得**抛异常——那是测试自造的替代故障，会顶替被测的真故障
    （错误包/中止案由此在宽吞变异下仍误绿）。供料永不断，故障只能来自被测对象。
    """
    queue = list(captures)
    assert queue, "模型供料不得为空"

    def fake_backend(prompt, *_a, **_k):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return json.dumps(item, ensure_ascii=False), {}

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)








_ENSURE_FAULT_MARK = "simulated ensure code fault #1769"
_RESUBMIT_FAULT_MARK = "simulated resubmit code fault #1769"


def _assert_error_pack_from(game, turn: int, marker: str) -> None:
    """错误包须来自被测的真故障本身——不认「有个包就行」。"""
    pack = latest_error_pack_for_turn(game.db.path, turn)
    assert pack, "须出错误包"
    assert Path(pack).is_dir()
    manifest = json.loads(
        (Path(pack) / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["exception_type"] == "RuntimeError"
    assert manifest["exception_message"] == marker
    assert (Path(pack) / "traceback.txt").is_file()




def _post_directive(game, text: str, dossier_payload: dict) -> None:
    """摆一条显式结构化 draft。不抽取，不占用补交重写的模型供料。"""
    from tests.directive_entry_helpers import stage_draft_directive

    stage_draft_directive(game.session, text, dossier_payload=dossier_payload)




def _rejection_rows(game, directive_id: int):
    return game.db.conn.execute(
        "SELECT reason, category, source, turn FROM rejection_reports "
        "WHERE section = 'directive_locality' "
        "AND json_extract(item_json, '$.directive_id') = ?",
        (directive_id,),
    ).fetchall()














# ── 线上材料庭 r1 三类负向 / pending / 零成案耗尽 ──────────────────────────


_NO_INTENT_REWRITE = {
    # 缺「拟旨意图」或垃圾 → extract 映 draft_action=无 → project 曾落 special_decree
    # fallback；结算路 B 不得 replace_payload 毁掉原 pay_order。
    "动作类型": "special_decree",
    "目标类型": "policy",
    "目标ID": "manual-directive",
}










def test_advance_without_edict_vacuum_no_decree_issued(
    admission_game, monkeypatch,
):
    """类B：POST 真空退朝成功 → 月份推进且不算本月已颁。"""
    game = admission_game
    turn = int(game.state.turn)
    assert not (game.session.last_decree or "").strip()
    client = TestClient(web_app.app)
    resp = client.post(
        "/api/decree/advance_without_edict/stream",
        json={"expected_turn": turn},
    )
    assert resp.status_code == 200, resp.text
    kind, body = parse_sse_event_pairs(resp.text)[-1]
    assert kind == "done"
    assert _turn_of(_get_state(client)) == turn + 1

    assert body.get("advanced") is True
    assert not (game.session.last_decree or "").strip()


def test_draft_admission_code_fault_aborts_with_error_pack(admission_game, monkeypatch):
    """真代码故障（ensure）：SSE error + 错误包记真故障 + 月份不推进。

    模型供料不断（枯竭不抛），故中止只能来自 boom；ensure 宽吞变异下本案必红。
    """
    game = admission_game
    _queue_backend(monkeypatch, [_GOOD_XIEANG])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(game, "准从国库见银拨关宁军饷十五万两即发。", _STORED_GOOD_XIEANG)
    wait_pending_writes(game)

    def boom(*_a, **_k):
        raise RuntimeError(_ENSURE_FAULT_MARK)

    monkeypatch.setattr(game.db, "_ensure_directive_dossier", boom)
    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 code-fault", allow_error=True,
    )
    assert body.get("_event") == "error"
    assert int(game.state.turn) == turn
    _assert_error_pack_from(game, turn, _ENSURE_FAULT_MARK)


@pytest.mark.parametrize("bad_rewrite,expected_error_type", [
    *[(rewrite, None) for rewrite in (
        _BAD_UNKNOWN_PARTICIPANT,
        *[{**_GOOD_XIEANG, "参与人": roster} for roster in (
            ["韩阁老"], [{"character_id": "毕自严"}],
            [{"character_id": "毕自严", "tier": ""}],
            [{"character_id": "毕自严", "tier": "旁听"}],
        )],
        {"拟旨意图": "拟旨", "动作类型": "pay_order_override",
         "目标类型": "account", "目标ID": "pay_order"},
        {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
         "目标ID": "river", "目标案卷ID": 1},
    )],
    ({"拟旨意图": "拟旨", "动作类型": "pay_order_override",
      "目标类型": "account", "目标ID": "pay_order",
      "entries": [{"key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": 3}]},
     "ValueError"),
])
def test_draft_admission_mixed_good_and_bad_independent(
    admission_game, monkeypatch, bad_rewrite, expected_error_type,
):
    """混合：好旨成案、坏旨补交耗尽 → draft 留、月推进，坏旨不连带好旨。

    已识别的名册/组合产物错走补交预算；未识别的期限 ValueError 保真中止。
    第二次重写须听见第一次重写自己的失败事实，而不是拿旧拒因再问一遍。
    """
    game = admission_game
    _queue_backend(monkeypatch, [bad_rewrite])
    resubmit_calls, product_faults = _spy_resubmit_kwargs(monkeypatch)
    ensure_rounds = _spy_ensure_rejection_reasons(monkeypatch, game)
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(game, "准从国库见银拨关宁军饷十五万两即发。", _STORED_GOOD_XIEANG)
    wait_pending_writes(game)
    good_id = _latest_directive_id(game)
    _post_directive(game, _DECREE_TEXT, _STORED_BAD_PAY_ORDER)
    wait_pending_writes(game)
    bad_id = _latest_directive_id(game)
    assert bad_id != good_id

    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 mixed",
        allow_error=expected_error_type is not None,
    )
    if expected_error_type is not None:
        assert body["_event"] == "error"
        assert int(game.state.turn) == turn
        assert game.db.dossiers.get_for_directive(bad_id) is None
        assert str(game.db.issues.directive(bad_id)["status"]) == "draft"
        manifest = json.loads(
            (Path(body["error_pack_path"]) / "manifest.json").read_text(encoding="utf-8"),
        )
        assert manifest["exception_type"] == expected_error_type
        assert manifest["exception_message"] == product_faults[0]
        return
    assert _turn_of(_get_state(client)) == turn + 1
    assert game.db.dossiers.get_for_directive(good_id) is not None
    _finish_month_after_gazette(game, turn)
    assert str(game.db.issues.directive(good_id)["status"]) == "issued"
    assert game.db.dossiers.get_for_directive(bad_id) is None
    assert str(game.db.issues.directive(bad_id)["status"]) == "draft"
    assert len(_rejection_rows(game, bad_id)) == 1
    assert not _rejection_rows(game, good_id)
    # 名册产物错未被当成系统故障：无错误包、月已推进（上方断言）
    assert not latest_error_pack_for_turn(game.db.path, turn)
    # 来源保真：第二次重写的 failure_reason = 第一次 resubmit 自身产物错原文
    assert len(resubmit_calls) == 2
    assert ensure_rounds, "ensure 须至少一轮"
    assert resubmit_calls[0]["failure_reason"] == _reason_for_directive(ensure_rounds[0], bad_id)
    assert product_faults, "第一次重写须留下本轮产物失败事实"
    assert resubmit_calls[1]["failure_reason"] == product_faults[0]

def test_exhaust_zero_dossier_system_simulation_no_steam_decree(
    admission_game, monkeypatch,
):
    """类3：耗尽零成案 → source=system_simulation；陈旧 last_decree 不进 resolve、不算本月已颁。"""
    game = admission_game
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _BAD_PAY_ORDER])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(game, _DECREE_TEXT, _STORED_BAD_PAY_ORDER)
    wait_pending_writes(game)
    did = _latest_directive_id(game)

    # 陈旧拟诏稿：旧行为会把它当本月已颁送入 resolve（player_decree + Steam 误计）
    stale = "陈旧拟诏稿·不得视为本月已颁·#1769"
    game.session.last_decree = stale
    game.session._decree_draft_fingerprint = ((did, "stale"),)

    resolve_calls: list[dict] = []
    real_resolve = session_mod.resolve_directives

    def spy_resolve(*args, **kwargs):
        resolve_calls.append({
            "source": kwargs.get("source"),
            "decree_text": args[4] if len(args) > 4 else kwargs.get("decree_text"),
        })
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(session_mod, "resolve_directives", spy_resolve)

    _post_issue_stream(
        client, expected_turn=turn, step="1769 zero-exhaust system_simulation",
    )
    assert _turn_of(_get_state(client)) == turn + 1
    assert str(game.db.issues.directive(did)["status"]) == "draft"
    assert game.db.dossiers.get_for_directive(did) is None

    assert resolve_calls, "须进入 resolve_directives"
    call = resolve_calls[0]
    from ming_sim.applier import Provenance
    assert call["source"] == Provenance.system_simulation
    assert not (call["decree_text"] or "").strip()
    assert (game.session.last_decree or "") != stale


_STORED_BAD_PAY_ORDER = di.project_draft_extract_to_directive_payload(
    {
        "draft_action": "拟旨",
        "dossier_action_type": "pay_order_override",
        "target_kind": "army",
        "target_id": "guanning",
        "mode": "ordinary",
        "entries": [{"key": "arrears_priority_军饷", "value": 1}],
        "assignee": "郭允厚",
    },
    decree_text=_DECREE_TEXT,
)


_STORED_GOOD_XIEANG = di.project_draft_extract_to_directive_payload(
    {
        "draft_action": "拟旨",
        "dossier_action_type": "grant_allocation",
        "grant_action": "协饷",
        "purpose": "补饷",
        "target_kind": "army",
        "target_id": "guanning",
        "mode": "ordinary",
        "amount": 15,
        "account": "国库",
        "assignee": "郭允厚",
        "execution_surface": "immediate",
        "entries": [],
    },
    decree_text=_DECREE_TEXT,
)


def _spy_resubmit_kwargs(monkeypatch) -> tuple[list[dict], list[str]]:
    """截获补交结构化入参与本轮产物失败事实（failure_reason 源），不扫 prompt。

    返回 (calls, product_faults)：
    - calls[i]["failure_reason"] = 实际回喂给 LLM 的诊断
    - product_faults = 各次 resubmit 自身抛出的 ValueError 原文（carry_over 源）
    来源保真：下一轮 failure_reason 必须等于对应 product_fault，不得只验非空/次数。
    """
    calls: list[dict] = []
    product_faults: list[str] = []
    real = di.resubmit_draft_admission_payload

    def wrapper(decree_text, *, bad_payload, failure_reason, **kwargs):
        calls.append({
            "failure_reason": str(failure_reason or ""),
            "bad_payload": dict(bad_payload or {}),
            "decree_text": str(decree_text or ""),
        })
        try:
            return real(
                decree_text,
                bad_payload=bad_payload,
                failure_reason=failure_reason,
                **kwargs,
            )
        except ValueError as exc:
            product_faults.append(str(exc))
            raise

    monkeypatch.setattr(di, "resubmit_draft_admission_payload", wrapper)
    return calls, product_faults


def _spy_ensure_rejection_reasons(monkeypatch, game) -> list[list[tuple[int, str]]]:
    """按轮截获 ensure_dossiers 拒因（directive_id, reason），作回喂源真值。"""
    rounds: list[list[tuple[int, str]]] = []
    real = game.db.ensure_dossiers_for_draft_directives

    def wrapper(state, record_rejections=False):
        result = real(state, record_rejections=record_rejections)
        rounds.append([
            (int(item["directive_id"]), str(item.get("reason") or ""))
            for item in (result or [])
            if item.get("directive_id") is not None
        ])
        return result

    monkeypatch.setattr(game.db, "ensure_dossiers_for_draft_directives", wrapper)
    return rounds


def _reason_for_directive(
    round_rows: list[tuple[int, str]], directive_id: int,
) -> str:
    matched = [reason for did, reason in round_rows if did == int(directive_id)]
    assert matched, f"ensure 轮次无 directive#{directive_id} 拒因"
    return matched[0]


def _finish_month_after_gazette(game, turn: int) -> None:
    """ADR 0157：写成邸报后主链才推进。作者替身已写成时不再推进第二次。"""
    from tests.conftest import wait_for_background_jobs

    wait_for_background_jobs(game.db)
    if int(game.state.turn) > int(turn):
        assert int(game.state.turn) == int(turn) + 1
        return
    game.db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (int(turn), int(game.state.year), int(game.state.period), "邸报已成"),
    )
    game.db.conn.commit()
    from ming_sim.month_chain import run_player_month_chain
    result = run_player_month_chain(
        game.state, game.db, game.session.agno_db, game.session.llm_config,
    )
    wait_for_background_jobs(game.db)
    assert result.advanced is True
    assert int(game.state.turn) == int(turn) + 1


def _latest_directive_id(game) -> int:
    row = game.db.issues.directive(
        int(game.db.conn.execute(
            "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"])
    )
    assert row is not None
    return int(row["id"])
