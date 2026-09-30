"""#1891 端到端：真实过月链上，请饷奏疏由世界段生成、经 #1847 批红页由皇帝亲裁。

不打桩本票被测的供料与裁断行为——只桩最外层模型调用（``agents.run_agent_text``
与转译 runner），生产的世界段消息构造、材料目录、案头物化、答复落账、C0 转译与
applier 全部真跑。断开任一处供料或写口，本文件即红（#1891 J5）。

覆盖：呈批→亲裁准→事件终局、驳回、留中、跨月再呈、恢复后身份不丢、以及本月批准
下月起征。断言实账与事件身份，不机械匹配自由文本（ADR 0043 批红页形态、
ADR 0115 事件绑定、ADR 0142 不解析御批文字）。
"""

from __future__ import annotations

import json
import math

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
from ming_sim.agents import strip_json_fence  # noqa: F401  (保证 parse_agent_json 同源)
from ming_sim.db import GameDB
from ming_sim.issues import FISCAL_LEVY_RESCRIPT_SOURCE
from ming_sim.models import LLMConfig
from ming_sim.month_chain import _LEVY_PETITION_PREFIX
from tests.month_chain_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor


def _settle_p(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _petition_decision(event_id="liao_levy_rise_1631", title="辽饷升至一分二厘"):
    """世界段上疏：拟批措辞是自由文，结局不由选项载荷携带。"""
    return (
        "<<DECISION>>"
        + json.dumps(
            {
                "title": title,
                "context": "边镇欠饷日深，户部请加辽饷。",
                "event_id": event_id,
                "options": [
                    {"label": "准行加派", "hint": "边饷稍续而民间加派更重"},
                    {"label": "不准，仍照九厘", "hint": "民力已困"},
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
    db.save_state(state)
    _forbid_extractor(monkeypatch)


def _install_model_boundary(monkeypatch, *, world_text, continue_text="遵旨。", declaration=None):
    """只桩最外层模型调用；生产供料、物料、案头、转译与 applier 全部真跑。

    转译 runner 按真实 prompt 里的答复事实作答：御批原话与闭集都在 prompt 里，
    这里模拟模型读懂后按闭集声明结局（生产代码只认闭集值）。
    """
    seen: dict = {
        "world_messages": [], "continue_prompts": [], "translate_prompts": [],
        "gazette": 0,
    }

    def _agent_text(_agent, prompt, tag="", **_kwargs):
        if tag == "world-segment":
            seen["world_messages"].append(prompt)
            return world_text
        if tag == "world-segment-continue":
            seen["continue_prompts"].append(prompt)
            return continue_text
        if tag == "gazette":
            seen["gazette"] += 1
            return json.dumps({"title": "邸报", "report": "边情邸报。"}, ensure_ascii=False)
        return ""

    monkeypatch.setattr("ming_sim.agents.run_agent_text", _agent_text)
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")

    import ming_sim.month_translate as month_translate

    def _translate(prompt, llm_config=None, *, tag="", policy=None):
        # 收下模型真实收到的那份 prompt：J2 的转译入口供料（事件身份＋闭集）是否
        # 真的到达模型，由调用方按结构化字段断言，不靠本桩静默接受一切。
        seen["translate_prompts"].append(prompt)
        # 声明取自测试给定（模拟模型按闭集声明）；未给则空声明。
        return dict(declaration or {"effects": {}})

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", _translate)
    return seen


# 转译 prompt 里那份额定 JSON 的定位按数据字段，不按句子措辞：找出含
# terminal_reason_labels 的那个 JSON 数组。措辞改写不影响本判据，供料断开则查无此项。
_ROSTER_KEY = "terminal_reason_labels"


def _levy_roster(prompt: str) -> list[dict]:
    """从转译 prompt 里取出本段答复的请饷事件名单（结构化字段，非契约文本）。

    用 JSON 解码器扫出候选数组（名单内含嵌套的标签数组，不能用平铺正则）；只认真正
    带 terminal_reason_labels 字段的那些。
    """
    decoder = json.JSONDecoder()
    out: list[dict] = []
    for index, char in enumerate(prompt or ""):
        if char != "[":
            continue
        try:
            parsed, _end = decoder.raw_decode(prompt[index:])
        except ValueError:
            continue
        if isinstance(parsed, list) and any(
            isinstance(row, dict) and _ROSTER_KEY in row for row in parsed
        ):
            out.extend(row for row in parsed if isinstance(row, dict))
    return out


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


def test_emperor_approves_levy_petition_through_real_month_chain(game, monkeypatch):
    """世界段上疏 → 同一批红页亲裁「准」→ 转译按闭集声明 → 事件终局。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    seen = _install_model_boundary(
        monkeypatch,
        world_text="关外告急，户部请加辽饷以济边饷。" + _petition_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]},
    )
    session = _make_session(db, state, content)

    result = session.resolve_turn(allow_empty_decree=True)

    # 真实供料：世界段消息里带得到本月请饷名单（构造与材料真跑）。
    assert seen["world_messages"], "世界段模型边界应被调用"
    assert "liao_levy_rise_1631" in seen["world_messages"][0]
    # 呈上批红页：同一请旨入口，不新增案头、不另起 run。
    assert result.awaiting is True
    assert result.stage == "rescript"
    assert result.advanced is False
    desk = session.pending_decisions()
    assert len(desk) == 1
    row = desk[0]
    assert row["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    assert row["title"] == "辽饷升至一分二厘"
    # 到点但未裁 → 账上无终局行（不再自动置已准）。
    assert _ledger_field(db, "terminal_state") == ""

    # 皇帝在批红页点「准行加派」。submit 入口内的 phase2 接既有续推与转译：
    # 答复先按事实落账，结局由同一段转译按闭集声明后落唯一写口。
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
        write_gate=session._write_gate,
    )
    # 答复确实经既有世界段续推（不是代码当场判的语义）。
    assert seen["continue_prompts"], "答复后续推应经既有世界段续推"
    # J2：转译入口必须把「哪些事件有御批可译」及其闭集真的交给模型——这是模型
    # 得知该声明什么的唯一通道。断开该供料，真实模型无从声明结局（断线必红）。
    # 本段可能有多次转译（答复后又有下一段），按“哪一次真的带名单”定位，不认位置。
    assert seen["translate_prompts"], "答复后的转译应经既有转译入口"
    rosters = [r for prompt in seen["translate_prompts"] if (r := _levy_roster(prompt))]
    assert rosters, "答复后的转译必须拿到本段请饷事件的闭集名单"
    assert [row["event_id"] for row in rosters[0]] == ["liao_levy_rise_1631"]
    assert rosters[0][0]["terminal_reason_labels"] == ["已准", "已驳"]

    ledger = _ledger(db)
    assert ledger["terminal_state"] == "triggered"
    assert ledger["terminal_reason"] == "已准"
    assert ledger["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
    # 亲笔/拟批措辞原样留在 choice 事实里，不被改写成结局标签以外的任何东西。
    assert json.loads(ledger["choice_json"])["label"] == "准行加派"
    # 本月已提交的财政不被回写重跑：仍按九厘。
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_approved_rate_takes_effect_and_then_enters_province_books(game, monkeypatch):
    """本月批准加派，下月唯一财政 tick 才消费新额（本月实账保持原额）。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    target = before * 4.0 / 3.0
    _install_model_boundary(
        monkeypatch,
        world_text="本月边情，户部请加辽饷。" + _petition_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_reason") == "已准"

    # 下月：走真实过月链，唯一财政 tick 消费新额。
    _install_model_boundary(monkeypatch, world_text="本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)

    after = _settle_p(db)
    assert math.isclose(after["p"]["三饷应征"], target, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        after["p"]["起运定额"],
        after["_meta"]["正赋起运基线"] + target,
        rel_tol=1e-9, abs_tol=1e-9,
    )


def test_emperor_rejects_levy_petition_keeps_nine_li(game, monkeypatch):
    """驳征不加派：辽饷仍九厘，终局一次落「已驳」。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    seen = _install_model_boundary(
        monkeypatch,
        world_text="本月边情，户部请加辽饷。" + _petition_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        }]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "不准，仍照九厘"}],
        write_gate=session._write_gate,
    )

    # J2：驳同样经转译入口拿到事件身份与闭集（与准同一通道，不另设一条）。
    assert [{
        "event_id": "liao_levy_rise_1631",
        "terminal_reason_labels": ["已准", "已驳"],
    }] in [_levy_roster(p) for p in seen["translate_prompts"]]
    assert _ledger_field(db, "terminal_reason") == "已驳"

    _install_model_boundary(monkeypatch, world_text="本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_held_levy_petition_advances_month_without_terminal_state(game, monkeypatch):
    """留中：本次奏疏已答、事件未裁定、征收不变；本月仍能续推推进。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    closed_turn = int(state.turn)
    # 留中＝转译不声明该事件结局（代码不据批语文字补结局）。
    seen = _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _petition_decision(),
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    # 只批朱笔、不点拟批＝留中。
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision",
          "label": "", "note": "留中，俟户部再议"}],
        write_gate=session._write_gate,
    )

    # J2 负向闸案：闭集照常交给模型（御批已答），但模型不声明结局 → 账上零终局。
    # 这证明「无终局」出于模型不声明，而非代码拿不到闭集就无从判。
    assert [{
        "event_id": "liao_levy_rise_1631",
        "terminal_reason_labels": ["已准", "已驳"],
    }] in [_levy_roster(p) for p in seen["translate_prompts"]]
    assert _ledger_field(db, "terminal_state") == ""
    assert _ledger_field(db, "terminal_reason") == ""
    assert "留中" in _ledger_field(db, "choice_json")
    # 留中不改征收。
    assert _settle_p(db)["p"]["三饷应征"] == before
    assert int(state.turn) > closed_turn


def test_outcome_label_outside_closed_set_is_rejected_not_written(game, monkeypatch):
    """转译声明闭集外的结局＝响亮失败，事务回滚、账上零终局行（不写脏串）。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _petition_decision(),
        declaration={"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "胡乱"},
        }]},
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        session.submit_hitl_choices(
            [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
            write_gate=session._write_gate,
        )

    assert _ledger_field(db, "terminal_state") == ""
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_no_levy_petition_means_no_extra_ask_and_no_new_run(game, monkeypatch):
    """未到点月份不新增请旨行、不新增模型调用（世界段消息保持原样）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)
    _forbid_extractor(monkeypatch)
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
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _petition_decision(),
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision",
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_state") == ""

    # 下月同一事件带 re_presentation 与原疏、亲笔批语交回同一世界段 run。
    from ming_sim.issues import list_fiscal_levy_petitions_due

    due = list_fiscal_levy_petitions_due(state, db)
    assert [d["event_id"] for d in due] == ["liao_levy_rise_1631"]
    assert due[0]["re_presentation"] is True
    assert "留中" in json.dumps(due[0]["prior_petition"], ensure_ascii=False)

    # 再上疏 → 仍绑原事件（不是新事件、不是首次重触发）。
    seen = _install_model_boundary(
        monkeypatch, world_text="户部再请罢辽饷加派。" + _petition_decision(),
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
    assert len(petition_rows) == 1
    assert petition_rows[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    # 名单事实真跑到了世界段消息里。
    assert "留中" in seen["world_messages"][0]

    session.submit_hitl_choices(
        [{"decision_key": petition_rows[0]["decision_key"], "action": "decision",
          "label": "不准，仍照九厘"}],
        write_gate=session._write_gate,
    )
    assert _ledger_field(db, "terminal_reason") == "已驳"
    # 一事件一终局裁断：只一行。
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("liao_levy_rise_1631",),
    ).fetchone()[0] == 1


def test_reopen_after_petition_stored_keeps_event_identity(game, tmp_path, monkeypatch):
    """#1891 J1：呈批存盘后关档重开，案头仍是原请饷事件、亲裁仍落该事件一次。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _petition_decision(),
    )
    session = _make_session(db, state, content)
    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    assert row["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    db.conn.commit()
    path = str(tmp_path / "reopen.db")
    import shutil

    shutil.copyfile(db.path, path)
    db.close()

    reopened = GameDB(path, content)
    try:
        issues.bind_content(content)
        state2 = reopened.load_state()
        # 重开后案头仍指向原请饷事件，未退化成普通世界段身份。
        desk = reopened.list_rescript_desk(int(state2.turn))
        petition_rows = [
            r for r in desk if str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
        ]
        assert len(petition_rows) == 1
        assert petition_rows[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
        assert petition_rows[0]["title"] == "辽饷升至一分二厘"
    finally:
        reopened.close()


def test_materialize_desk_uses_pinned_identity_not_live_eligibility(game):
    """#1891 J1：案头物化只认交接时钉的身份，不看当前 due 名单是否还在。"""
    from ming_sim.month_chain import _pin_world_question_identities
    from ming_sim.settlement_payload import parse_decision_blocks

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    offered = issues.list_fiscal_levy_petitions_due(state, db)
    chain = {
        "levy_petitions": offered,
        "world_questions": _pin_world_question_identities(
            offered, parse_decision_blocks("本月边情。" + _petition_decision()),
        ),
    }
    # 此刻事件在 due 名单里（尚未呈批），先物化一次使其进入待裁状态。
    first = month_chain._materialize_rescript_desk(db, state, chain)
    assert first[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    # 已呈待裁 → 不再在 due 名单里；身份仍由已存问题给出。
    assert issues.list_fiscal_levy_petitions_due(state, db) == []
    again = month_chain._materialize_rescript_desk(db, state, chain)
    assert again[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"


def test_model_sees_exactly_the_roster_that_pins_the_identities(game, monkeypatch):
    """#1891 J1：模型看见的名单 ≡ 钉进问题身份的那份 ≡ 案头行的事件。

    交接只有一份名单快照。若供料与身份钉定按各自时机各查一次实时资格，账本在
    两者之间一变，模型就会看到与实际被绑定的不一致——本断言直接以实账比较三者。
    """
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    seen = _install_model_boundary(
        monkeypatch, world_text="本月边情，户部请加辽饷。" + _petition_decision(),
    )
    session = _make_session(db, state, content)

    session.resolve_turn(allow_empty_decree=True)

    # 模型真实收到的名单（世界段消息是本票供料面，真跑）。
    payload = json.loads(seen["world_messages"][0])
    offered = [p["event_id"] for p in payload["levy_petitions"]]
    # 月链上持久化的交接快照（读真实存库相位，非测试自造）。
    chain = month_chain._load_chain(db, int(state.turn))
    snapshotted = [p["event_id"] for p in chain["levy_petitions"]]
    # 案头行的身份 = 依那份快照钉定的。
    desk = [
        r["event_id"] for r in session.pending_decisions()
        if str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
    ]

    assert offered == snapshotted == ["liao_levy_rise_1631"]
    assert desk == [f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"]
