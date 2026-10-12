from __future__ import annotations
"""#1891 端到端：真实过月链上，请饷奏疏由世界段生成、经批红页由皇帝亲裁。

只桩最外层模型调用。供料、案头、答复落账、转译与 applier 走生产路径。
断言落在事件身份、闭集供料、终局、月份，以及已落的结构化账字段上。
"""


import json

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
from ming_sim.db import GameDB
from ming_sim.issues import FISCAL_LEVY_RESCRIPT_SOURCE
from ming_sim.entities.issue.event_terminal import apply_petition_event_outcome
from ming_sim.models import LLMConfig
from ming_sim.month_chain import _LEVY_PETITION_PREFIX
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import _drain_registered_sessions_before_close
from tests.month_chain_helpers import make_light_session

def _settle_p(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]

def _levy_block(title="辽饷升至一分二厘"):
    """按交接顺序上疏。块内不带事件 id：关联由名单下标构造。"""
    return (
        "<<LEVY>>"
        + json.dumps(
            {
                "title": title,
                "context": "边镇欠饷日深，户部请加辽饷。",
                "options": [
                    {"label": "准行加派", "hint": "边饷稍续而民间加派更重"},
                    {"label": "不准，仍照九厘", "hint": "民力已困"},
                    {"label": "留中", "hint": "俟户部再议"},
                ],
            },
            ensure_ascii=False,
        )
        + "<<END>>"
    )

def _ordinary_decision():
    return (
        "<<DECISION>>"
        + json.dumps(
            {
                "title": "是否拨内库存银济饷",
                "context": "内库尚有余银。",
                "event_id": "lian_levy_start_1639",
                "options": [
                    {"label": "准拨", "hint": "暂济眉急"},
                    {"label": "不准", "hint": "内库另有用途"},
                ],
            },
            ensure_ascii=False,
        )
        + "<<END>>"
    )

def _prepare(db, state, content, monkeypatch, year=1631, period=1):
    issues.bind_content(content)
    state.year = year
    state.period = period
    db.reign.save_game_state(state)

def _install_model_boundary(
    monkeypatch, *, world_text, continue_text="遵旨。", declaration=None, world_log=None,
):
    """只桩最外层模型调用；生产供料、物料、案头、转译与 applier 全部真跑。

    转译 runner 返回给定结构化声明，只证明声明至实账的行为；不证明模型
    已读取批语或闭集，真实模型供料不以此桩作证。

    ``world_log`` 是跨多次安装累积的世界段调用记录——重试是否真的重跑了世界段，
    靠它证明，而不是靠「重试没报错」。
    """
    seen: dict = {
        "world_messages": world_log if world_log is not None else [],
        "continue_prompts": [], "translate_prompts": [],
        "segments": [], "answered_verdicts": [], "gazette": 0,
    }

    def _agent_text(_agent, prompt, tag="", **_kwargs):
        if tag == "rescript-draft":
            payload = json.loads(prompt)
            return json.dumps({"actor_name": payload["officers"][-1]["name"], "items": [], "revisions": []})
        if tag == "world-segment":
            seen["world_messages"].append(prompt)
            return world_text
        if tag == "world-segment-continue":
            seen["continue_prompts"].append(prompt)
            return continue_text
        if tag == "decree-forecast-continue":
            return "遵旨，内库拨银修城。"
        if tag == "gazette":
            seen["gazette"] += 1
            return json.dumps({"title": "邸报", "report": "边情邸报。"}, ensure_ascii=False)
        return ""

    monkeypatch.setattr("ming_sim.agents.run_agent_text", _agent_text)
    monkeypatch.setattr("ming_sim.rescript_draft.run_agent_text", _agent_text)
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")

    import ming_sim.month_translate as month_translate

    def _translate(prompt, llm_config=None, *, tag="", policy=None):
        seen["translate_prompts"].append(prompt)
        # 声明取自测试给定（模拟模型按闭集声明）；未给则空声明。
        return dict(declaration or {"effects": {}})

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", _translate)

    dispatch_month_segment = month_translate.dispatch_month_segment

    def _dispatch(db, state, *args, **kwargs):
        # 转译入口实际收到的段文。请旨机标须已在切前缀时拿掉。
        seen["segments"].append(str(kwargs.get("segment") or ""))
        seen["answered_verdicts"].append(kwargs.get("answered_verdicts", ()))
        return dispatch_month_segment(db, state, *args, **kwargs)

    monkeypatch.setattr(month_translate, "dispatch_month_segment", _dispatch)
    return seen

def _supplied_levy_petitions(message: str) -> list[dict]:
    """世界段消息里的请饷名单。消息是生产代码交出的 JSON，断言只读结构化字段。"""
    parsed = json.loads(message)
    petitions = parsed["levy_petitions"]
    assert isinstance(petitions, list)
    return petitions

def _make_session(db, state, content):
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    return session

def _ledger(db, event_id="liao_levy_rise_1631"):
    """事件账行；尚未有过任何写入时返回 None（账上零行也是合规事实）。"""
    return db.conn.execute(
        "SELECT terminal_state, terminal_reason, source, choice_json FROM event_triggers "
        "WHERE event_id=?",
        (event_id,),
    ).fetchone()

def _ledger_field(db, field, event_id="liao_levy_rise_1631", default=""):
    row = _ledger(db, event_id)
    return default if row is None else str(row[field] or "")

@pytest.mark.parametrize("choice", [
    {"label": "准行加派"},
    {"label": "", "note": "准奏，依所请加派"},
])
def test_emperor_approves_levy_petition_through_real_month_chain(game, monkeypatch, choice):
    """世界段上疏 → 同一批红页亲裁「准」→ 转译按闭集声明 → 事件终局。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    world_text = "关外告急，户部请加辽饷以济边饷。" + _levy_block()
    seen = _install_model_boundary(
        monkeypatch,
        world_text=world_text,
        continue_text="",
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]},
    )
    session = _make_session(db, state, content)

    result = session.resolve_turn(allow_empty_decree=True)

    # 真实供料：世界段消息里的名单带本月请饷身份与首次应呈的权限事实。
    assert seen["world_messages"], "世界段模型边界应被调用"
    petitions = _supplied_levy_petitions(seen["world_messages"][0])
    assert [item["event_id"] for item in petitions] == ["liao_levy_rise_1631"]
    assert petitions[0]["presentation_due"] is True
    assert petitions[0]["re_presentation"] is False
    assert "prior_petition" not in petitions[0]
    # 呈上批红页：同一请旨入口，不新增案头、不另起 run。
    assert result.awaiting is True
    assert result.stage == "rescript"
    assert result.advanced is False
    desk = session.pending_decisions()
    assert len(desk) == 1
    row = desk[0]
    assert row["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    assert row["title"] == "辽饷升至一分二厘"
    # 请饷块只走交接，不进送去转译的段文。段文仍是世界段原文的前缀。
    handed = [segment for segment in seen["segments"] if segment and segment in world_text]
    assert handed
    assert all("<<LEVY>>" not in segment for segment in seen["segments"])
    # 到点但未裁 → 账上无终局行（不再自动置已准）。
    assert _ledger_field(db, "terminal_state") == ""

    # Approve by draft or handwritten note through the same submission path:
    # 答复先按事实落账，结局由同一段转译按闭集声明后落唯一写口。
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], **choice}],
        write_gate=session._write_gate,
    )
    # 答复确实经既有世界段续推（不是代码当场判的语义）。
    assert seen["continue_prompts"], "答复后续推应经既有世界段续推"
    ledger = _ledger(db)
    assert ledger["terminal_state"] == "triggered"
    assert ledger["terminal_reason"] == "已准"
    assert ledger["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
    # 亲笔/拟批措辞原样留在 choice 事实里，不被改写成结局标签以外的任何东西。
    stored_choice = json.loads(ledger["choice_json"])
    assert {key: stored_choice[key] for key in choice} == choice
    verdict = seen["answered_verdicts"][-1][0]
    assert verdict["event_id"] == "liao_levy_rise_1631"
    assert {key: verdict["rescript"][key] for key in choice} == choice
    # 本月三饷应征参数仍是批准前的九厘。
    assert _settle_p(db)["p"]["三饷应征"] == before

@pytest.mark.parametrize("abolition", [None, "remove_before", "zero_before", "remove_after", "zero_after"])
def test_approved_rate_updates_next_month_settle_levy_and_transport(game, monkeypatch, abolition):
    """最后有效旨意经月链消费；重开不重算本月，旧终局重交不复征。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    target = before * 4.0 / 3.0

    def abolish(zeroing=False):
        field = "fiscal_changes" if zeroing else "fiscal_removes"
        item = {"key": "辽饷_rate", "origin_ref": "盘面自发", "reason": "罢征"}
        if zeroing:
            item["delta"] = -100
        dispatch_declaration(db, state, {"effects": [{field: [item]}]})

    if abolition and abolition.endswith("before"):
        abolish(abolition.startswith("zero"))
    _install_model_boundary(monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block())
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    effects = [{
        "event_id": "liao_levy_rise_1631",
        "事件结局": {"liao_levy_rise_1631": "已准"},
    }]
    if abolition and abolition.endswith("after"):
        field = "fiscal_changes" if abolition.startswith("zero") else "fiscal_removes"
        item = {"key": "辽饷_rate", "origin_ref": "盘面自发", "reason": "准后罢征"}
        if field == "fiscal_changes":
            item["delta"] = -100
        effects.append({field: [item]})
        target = 0
    _install_model_boundary(monkeypatch, world_text="", declaration={"effects": effects})
    # 已算本月财政，不因答复重算。
    closed_turn = int(state.turn)
    def remittance(turn):
        return [tuple(row) for row in db.conn.execute(
            "SELECT delta FROM economy_ledger WHERE account='国库' "
            "AND category='起运' AND turn=? ORDER BY id", (turn,),
        )]
    paid = remittance(closed_turn)
    assert paid
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "label": "准行加派"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_reason") == "已准"
    assert _settle_p(db)["p"]["三饷应征"] == (0 if abolition and abolition.endswith("before") else before)
    assert remittance(closed_turn) == paid
    path = db.path
    session.close()
    db = GameDB(path, content)
    state = db.load_state()
    session = _make_session(db, state, content)
    try:
        assert remittance(closed_turn) == paid
        _install_model_boundary(monkeypatch, world_text="本月无大事。")
        second = session.resolve_turn(allow_empty_decree=True)
        assert second.advanced is True, (second.stage, second.awaiting)
        after = _settle_p(db)
        assert after["p"]["三饷应征"] == pytest.approx(target)
        assert after["p"]["起运定额"] == pytest.approx(after["_meta"]["正赋起运基线"] + target)
        assert remittance(closed_turn) == paid
        assert sum(value[0] for value in remittance(int(state.turn) - 1)) > 0
        # 同标签及相反标签重交都不是新决定；下月不得重放复征。
        # advanced 后机械尾可能仍占共享连接：先等会话写队列清空再直接写库（#1891 F1）。
        assert get_session_write_queue(session).wait_idle()
        if target:
            abolish()
        for label in ("已准", "已驳"):
            result = apply_petition_event_outcome(state, db, "liao_levy_rise_1631", label)
            assert result["settled"] is False
            assert result["terminal_reason"] == "已准"
        session.resolve_turn(allow_empty_decree=True)
        assert _settle_p(db)["p"]["三饷应征"] == 0
    finally:
        session.close()

@pytest.mark.parametrize("abolished", [False, True])
def test_emperor_rejects_levy_petition_keeps_nine_li(game, monkeypatch, abolished):
    """驳征不加派：辽饷仍九厘，终局一次落「已驳」。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    if abolished:
        from ming_sim.declaration_dispatch import dispatch_declaration
        dispatch_declaration(db, state, {"effects": [{"fiscal_removes": [{
            "key": "辽饷_rate", "origin_ref": "盘面自发", "reason": "罢征",
        }]}]})
        before = 0
    _install_model_boundary(
        monkeypatch,
        world_text="本月边情，户部请加辽饷。" + _levy_block(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        }]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "label": "不准，仍照九厘"}],
        write_gate=session._write_gate,
    )

    assert _ledger_field(db, "terminal_reason") == "已驳"

    _install_model_boundary(monkeypatch, world_text="本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)
    assert _settle_p(db)["p"]["三饷应征"] == before

@pytest.mark.parametrize("abolished", [False, True])
def test_held_levy_petition_advances_month_without_terminal_state(game, monkeypatch, abolished):
    """留中：本次奏疏已答、事件未裁定、征收不变；本月仍能续推推进。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    closed_turn = int(state.turn)
    if abolished:
        from ming_sim.declaration_dispatch import dispatch_declaration
        dispatch_declaration(db, state, {"effects": [{"fiscal_removes": [{
            "key": "辽饷_rate", "origin_ref": "盘面自发", "reason": "罢征",
        }]}]})
        before = 0
    from tests.test_month_chain_1843 import _stage_edict
    affair = db.affairs.open(
        name="修城", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _, ref = _stage_edict(
        db, state, next(iter(content.characters.values())).name, "修城", "修城", 0, affair.id,
    )
    db.staged_declarations.replace_questions(ref, [{
        "title": "是否拨内库修城", "context": "城垣需修。",
        "options": [{"label": "准拨", "hint": "拨银修城"}],
    }], forecast_text="修城请旨。")
    # The model leaves the first rescript unresolved; an unrelated later
    # segment cannot borrow that old answer to declare a terminal outcome.
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
        continue_text="户部再议。",
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    desk = session.pending_decisions()
    row = next(item for item in desk if str(item["event_id"]).startswith(_LEVY_PETITION_PREFIX))
    ordinary = next(item for item in desk if str(item["event_id"]).startswith("decree-question:"))
    def translate(request, _config):
        # Independent calls may finish in either order. Only the unrelated
        # decree tries to borrow the levy verdict; the held petition stays empty.
        if request.this_decree is None:
            return {"effects": {}}
        return {"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]}

    monkeypatch.setattr(
        "ming_sim.month_translate._default_month_translate_runner", translate,
    )
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"],
          "label": "留中", "note": "留中，俟户部再议"},
         {"decision_key": ordinary["decision_key"], "label": "准拨"}],
        write_gate=session._write_gate,
    )

    assert _ledger_field(db, "terminal_state") == ""
    assert _ledger_field(db, "terminal_reason") == ""
    held_choice = json.loads(_ledger_field(db, "choice_json"))
    assert held_choice["label"] == "留中"
    assert held_choice["note"] == "留中，俟户部再议"
    # 留中不改征收。
    assert _settle_p(db)["p"]["三饷应征"] == before
    assert int(state.turn) > closed_turn
    _install_model_boundary(monkeypatch, world_text="本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True
    assert _ledger_field(db, "terminal_state") == ""
    assert _settle_p(db)["p"]["三饷应征"] == before

@pytest.mark.parametrize("raw_label", ["胡乱", {}])
def test_outcome_label_outside_closed_set_is_rejected_not_written(game, monkeypatch, raw_label):
    """闭集外标签或显式空声明，即使同组后项是合法标签，也走既有续推失败且不写终局。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    closed_turn = int(state.turn)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
        declaration={"effects": [
            {
                "event_id": "liao_levy_rise_1631",
                "事件结局": {"liao_levy_rise_1631": raw_label},
            },
            {
                "event_id": "liao_levy_rise_1631",
                "事件结局": {"liao_levy_rise_1631": "已准"},
            },
        ]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]

    with pytest.raises(SettlementAbort) as caught:
        session.submit_hitl_choices(
            [{"decision_key": row["decision_key"], "label": "准行加派"}],
            write_gate=session._write_gate,
        )

    assert caught.value.stage == "world_continue"
    assert caught.value.error_pack_path
    failure = month_chain.month_chain_call_failure(db, closed_turn)
    assert failure is not None
    assert failure["step"] == "world_continue"
    assert failure["kind"] == "code_exception"
    assert failure.get("error_pack_path")
    stored = db.conn.execute(
        "SELECT status, choice_json FROM pending_decisions WHERE event_id=?",
        (f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",),
    ).fetchone()
    assert stored["status"] == "decided"
    assert json.loads(stored["choice_json"])["label"] == "准行加派"
    assert _ledger_field(db, "terminal_state") == ""
    assert _settle_p(db)["p"]["三饷应征"] == before
    assert int(state.turn) == closed_turn
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_questions")

def test_no_levy_petition_means_no_extra_ask_and_no_new_run(game, monkeypatch):
    """未到点月份不新增请旨行、不新增模型调用（世界段消息保持原样）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.reign.save_game_state(state)
    seen = _install_model_boundary(monkeypatch, world_text="本月无大事。")
    session = _make_session(db, state, content)

    result = session.resolve_turn(allow_empty_decree=True)

    assert len(seen["world_messages"]) == 1
    # 无待呈事件时消息不加壳（真实供料行为，非打桩断言）：不夹带请饷载荷。
    assert "levy_petitions" not in seen["world_messages"][0]
    assert all(
        not str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
        for r in session.pending_decisions()
    )
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id LIKE '%levy%' AND terminal_state='triggered'"
    ).fetchone() is None
    assert result.advanced is True

def test_re_presentation_after_hold_still_binds_same_event(game, monkeypatch):
    """留中后大臣再上疏：新疏仍绑原事件，终局裁断只落该事件一次。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"],
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_state") == ""

    # 再上疏：块内不带事件 id，按名单顺序绑回原事件。同段另有一条普通请旨，
    # 即便回显了别的饷率事件 id，也不抢走请饷身份。
    seen = _install_model_boundary(
        monkeypatch, world_text="户部再请罢辽饷加派。" + _levy_block() + _ordinary_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        }]},
    )
    session.resolve_turn(allow_empty_decree=True)
    desk = session.pending_decisions()
    petition_rows = [
        r for r in desk if str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
    ]
    ordinary_rows = [
        r for r in desk if str(r["event_id"]).startswith("world-question:")
    ]
    assert len(petition_rows) == 1
    assert petition_rows[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    assert len(ordinary_rows) == 1
    assert "lian_levy" not in ordinary_rows[0]["event_id"]
    petitions = _supplied_levy_petitions(seen["world_messages"][0])
    assert [item["event_id"] for item in petitions] == ["liao_levy_rise_1631"]
    assert petitions[0]["re_presentation"] is True
    assert petitions[0]["presentation_due"] is False
    rescript = petitions[0]["prior_petition"]["rescript"]
    assert rescript["label"] == ""
    assert rescript["note"] == "留中"

    session.submit_hitl_choices(
        [
            {"decision_key": petition_rows[0]["decision_key"],
             "label": "不准，仍照九厘"},
            {"decision_key": ordinary_rows[0]["decision_key"],
             "label": "不准"},
        ],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_reason") == "已驳"
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("lian_levy_start_1639",),
    ).fetchone() is None
    # 一事件一终局裁断：只一行。
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("liao_levy_rise_1631",),
    ).fetchone()[0] == 1

def test_reopen_after_petition_stored_keeps_event_identity(game, tmp_path, monkeypatch):
    """关档重开后按原 decision_key 续办：身份与终局落在原请饷事件上，月份推进。"""
    import shutil

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    decision_key = row["decision_key"]
    assert row["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    db.conn.commit()
    path = str(tmp_path / "reopen.db")
    shutil.copyfile(db.path, path)
    _drain_registered_sessions_before_close(db)
    db.conn.close()

    reopened = GameDB(path, content)
    try:
        issues.bind_content(content)
        state2 = reopened.load_state()
        closed_turn = int(state2.turn)
        seen = _install_model_boundary(
            monkeypatch,
            world_text="重开后不得再跑已提交的世界段。",
            declaration={"effects": [{
                "event_id": "liao_levy_rise_1631",
                "事件结局": {"liao_levy_rise_1631": "已准"},
            }]},
        )
        session2 = _make_session(reopened, state2, content)
        session2.submit_hitl_choices(
            [{"decision_key": decision_key, "label": "准行加派"}],
            write_gate=session2._write_gate,
        )

        assert seen["world_messages"] == []
        assert len(seen["continue_prompts"]) == 1
        ledger = _ledger(reopened)
        assert ledger["terminal_state"] == "triggered"
        assert ledger["terminal_reason"] == "已准"
        assert ledger["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
        stored = reopened.conn.execute(
            "SELECT event_id, status FROM pending_decisions WHERE event_id=?",
            (f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",),
        ).fetchone()
        assert stored["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
        assert stored["status"] == "decided"
        assert int(state2.turn) > closed_turn
    finally:
        _drain_registered_sessions_before_close(reopened)
        reopened.conn.close()

def test_declined_presentation_keeps_following_world_facts(game, monkeypatch):
    """合法不呈请不是暂停切点：交接块之后的世界事实仍进既有转译并落账。"""
    import ming_sim.month_translate as month_translate

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"],
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_state") == ""

    # submit_hitl_choices 推进后机械尾可能仍占共享连接：先等写队列清空再布置（#1891 F1）。
    assert get_session_write_queue(session).wait_idle()
    affair = db.affairs.open(
        name="户部发赈", origin="世界段", year=state.year, period=state.period,
        turn=state.turn,
    )
    origin_ref = f"affair:{affair.id}"
    world_text = (
        "<<LEVY>>"
        + json.dumps({"present": False}, ensure_ascii=False)
        + "<<END>>"
        + "交接标记之后仍有本月事实。"
    )
    seen = _install_model_boundary(monkeypatch, world_text=world_text)

    def _translate(prompt, llm_config=None, *, tag="", policy=None):
        seen["translate_prompts"].append(prompt)
        return {"effects": {"economy_moves": [{
            "origin_ref": origin_ref,
            "account": "国库",
            "delta": -1,
            "category": "赈银",
            "reason": "户部发赈",
        }]}}

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", _translate)

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.advanced is True
    assert seen["translate_prompts"]
    assert any(
        segment.strip() and "<<LEVY>>" not in segment for segment in seen["segments"]
    )
    assert all(
        not str(item["event_id"]).startswith(_LEVY_PETITION_PREFIX)
        for item in session.pending_decisions()
    )
    assert _ledger_field(db, "terminal_state") == ""
    move = db.conn.execute(
        "SELECT account, delta, category FROM economy_ledger WHERE origin_ref=?",
        (origin_ref,),
    ).fetchone()
    assert move is not None
    assert move["account"] == "国库"
    assert int(move["delta"]) == -1
    assert move["category"] == "赈银"

# ------------------------------------------- 实际落账目标＝本段御批授权目标

def test_outcome_for_unanswered_petition_is_rejected_and_writes_nothing(game, monkeypatch):
    """#1891 J1：辽饷仍在批红页待裁时，转译声明它的结局必须被拒收且零终局行。

    走真实过月链（真实转译入口 + 真实 applier）：声明里没有外层 event_id，按旧
    读法预检无从判资格，而写口照「事件结局」的全部键落账——皇帝还没答，事件却
    先成了「已准」，且 first-wins 不可回改。断言拒收留痕与账上零终局。
    """
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    # 世界段照常上疏（绑定成立、案头待裁），但同一段转译抢在皇帝答复前声明结局。
    _install_model_boundary(
        monkeypatch,
        world_text="本月边情，户部请加辽饷。" + _levy_block(),
        continue_text="遵旨。",
        declaration={"effects": [{"事件结局": {"liao_levy_rise_1631": "已准"}}]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)

    # 该请饷仍在批红页待裁，账上零终局行——授权只来自皇帝实际答复。
    assert [r["event_id"] for r in session.pending_decisions()] == [
        f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    ]
    assert _ledger_field(db, "terminal_state") == ""
    assert _settle_p(db)["p"]["三饷应征"] == before

def test_outcome_for_never_presented_event_cannot_ride_another_events_verdict(
    game, monkeypatch,
):
    """#1891 J1：辽饷已答的 envelope 不得夹带练饷的结局。

    授权只覆盖皇帝本段实际答复的那件事。按外层 event_id 判资格、按内层键落账，
    就会在 1631 年（练饷尚未到点、更未呈批）提前裁定 lian_levy_start_1639。

    夹带即归属不一致＝契约违反，整封拒收、零写账：既不写练饷，也不把同一封里
    夹带授权的那笔当成合规写入。
    """
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch,
        world_text="本月边情，户部请加辽饷。" + _levy_block(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {
                "liao_levy_rise_1631": "已准",
                "lian_levy_start_1639": "已准",
            },
        }]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "label": "准行加派"}],
        write_gate=session._write_gate,
    )

    # 练饷（无御批）零终局行；辽饷那笔因同封夹带未获授权而一并未落——皇帝本月
    # 的准已按事实存进 choice，辽饷仍在名单上可再呈，不因拒收而丢答复。
    for event_id in ("liao_levy_rise_1631", "lian_levy_start_1639"):
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
            (event_id,),
        ).fetchone() is None
    assert json.loads(_ledger_field(db, "choice_json"))["label"] == "准行加派"

# ------------------------------------------------ 交接身份由构造保证（J2）

def test_held_month_ordinary_ask_does_not_bind_or_abort(game, monkeypatch):
    """#1891 J2：留中后本月可以不再上疏。普通请旨保持世界段身份，不绑饷率事件。

    回显别的事件 id 也不构成请饷关联。不再上疏是合法的；已形成的请饷新疏走
    交接槽，不靠这条普通请旨猜配。
    """
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"],
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )

    # 上一段的留中不是本段御批。转译若声明辽饷结局，必须被拒、零终局。
    _install_model_boundary(
        monkeypatch, world_text="内库是否拨银。" + _ordinary_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]},
    )
    session.resolve_turn(allow_empty_decree=True)

    desk = session.pending_decisions()
    assert desk
    assert all(not str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX) for r in desk)
    assert any(str(r["event_id"]).startswith("world-question:") for r in desk)
    assert _ledger_field(db, "terminal_state") == ""
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("lian_levy_start_1639",),
    ).fetchone() is None

def test_misaligned_levy_blocks_fail_loud_and_retry_reruns_world(game, monkeypatch):
    """#1891 J2/J3：应呈件的交接块数与名单对不上，响亮失败并走既有恢复。

    回显事件 id 的普通请旨不能顶替交接槽。失败留下 call_failure 与错误包；
    无效段文按既有重试口丢弃，换合规模型后世界段真的再跑一次，案头绑回原事件。
    """
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    world_log: list[str] = []
    # 应呈件只有普通请旨、没有交接槽：回显事件 id 也不能顶上，不得降格成匿名案头。
    _install_model_boundary(
        monkeypatch, world_log=world_log,
        world_text="本月边情，户部请加辽饷。" + _ordinary_decision(),
    )
    session = _make_session(db, state, content)

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    failure = month_chain.month_chain_call_failure(db, int(state.turn))
    assert failure is not None
    assert failure["step"] == "world_bind"
    assert failure["error_pack_path"]
    assert len(world_log) == 1

    # 块数与名单对不上同样无法唯一对齐，仍走同一失败通道，并丢掉这份无效段文。
    _install_model_boundary(
        monkeypatch, world_log=world_log,
        world_text="本月边情。" + _levy_block() + _levy_block(title="另一件"),
    )
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    failure = month_chain.month_chain_call_failure(db, int(state.turn))
    assert failure is not None
    assert failure["step"] == "world_bind"
    assert len(world_log) == 2

    _install_model_boundary(
        monkeypatch, world_log=world_log,
        world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session.resolve_turn(allow_empty_decree=True)
    assert len(world_log) == 3
    assert month_chain.month_chain_call_failure(db, int(state.turn)) is None
    assert [r["event_id"] for r in session.pending_decisions()] == [
        f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    ]

def test_explicit_bad_levy_marker_after_hold_stops_at_world_bind(game, monkeypatch):
    """留中后再上：显式坏交接停在 world_bind。没写块仍可推进。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _levy_block(),
    )
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"],
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )
    held_turn = int(state.turn)
    assert _ledger_field(db, "terminal_state") == ""

    for marker in (
        "<<LEVY>>null<<END>>",
        "<<LEVY>>[{}]<<END>>",
        "<<LEVY>>{broken}<<END>>",
        "<<LEVY>>",
        "<<LEVY>>{\"present\": false}",
        "<<LEVY>>{\"title\": \"户部请饷\"}",
    ):
        _install_model_boundary(
            monkeypatch, world_text="边饷仍紧。" + marker,
        )
        with pytest.raises(SettlementAbort):
            session.resolve_turn(allow_empty_decree=True)
        failure = month_chain.month_chain_call_failure(db, held_turn)
        assert failure is not None
        assert failure["step"] == "world_bind"
        assert int(state.turn) == held_turn
        assert _ledger_field(db, "terminal_state") == ""

    _install_model_boundary(monkeypatch, world_text="户部本月不再上疏。")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert int(state.turn) > held_turn
    assert _ledger_field(db, "terminal_state") == ""
