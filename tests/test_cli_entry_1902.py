"""#1902 CLI 入口接缝：拟诏台手写入口退役 + 批红等皇帝亲裁。

法源：#1902 票面「CLI 手拟新旨也不保留，但共享抽取核若仍有现役消费者则搬为其能力」、
「CLI 批红须等皇帝亲裁，不自动选第一项」；#1812 待拍第 6、9 项；ADR 0152（后出第 6 项
已批准整体删拟诏台，前置不阻止已批准删除）。

本文件只测入口适配层行为：审阅界面不再新增/改写旨意，批红由 input() 逐案取皇帝所选，
choice 投影只经 ``rescript_actions.project_hitl_option`` 一个真源。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import ming_sim.cli.terminal as term
from ming_sim import audience_night as an
from ming_sim.session import GameSession


def _draft_row(decision_key: str = "rescript_draft:3:0") -> dict:
    return {
        "decision_key": decision_key,
        "kind": "rescript_draft",
        "source_turn": 3,
        "idx": 0,
        "title": "边饷欠额",
        "context": "辽东饷银已欠两月。",
        "options": [
            {"label": "先发半饷", "hint": "量入为出", "draft_capability": "cap-a"},
            {"label": "照旧额全发", "hint": "不改额", "draft_capability": "cap-b"},
        ],
    }


class _AdjudicateSession:
    """submit_hitl_choices 唯一编排的录音替身（真核由 session 负责）。"""

    def __init__(self, decisions):
        self._decisions = decisions
        self.submitted: list[dict] = []
        self.gate: object | None = None

    def pending_decisions(self):
        return list(self._decisions)

    def submit_hitl_choices(self, choices, *, write_gate):
        assert write_gate is self.gate
        self.submitted.append(choices)
        return "邸报"


def _wire_gate(monkeypatch, session):
    """替身案：把 CLI 唯一 write gate 换成可断言的哨兵（真核案不得走这条）。"""
    gate = object()
    monkeypatch.setattr(term, "_cli_write_gate", lambda _session: gate)
    session.gate = gate
    return session


def test_review_directives_retires_manual_add_and_edit(monkeypatch):
    """拟诏台手写新旨/改稿退役：CLI 审阅只剩审阅、颁布与删旧草案。"""

    class Session:
        def __init__(self):
            self.db = SimpleNamespace(list_pending_actions=lambda _turn: [])
            self.state = SimpleNamespace(turn=1, turn_phase="reviewing")
            self.calls: list[str] = []

        def enter_review(self):
            self.calls.append("enter_review")

        def back_to_summoning(self):
            self.calls.append("back_to_summoning")

        def list_directives(self, include_pending=True):
            return [SimpleNamespace(id=7, text="拟旨旧稿", status="draft")]

        def add_directive(self, *args, **kwargs):
            self.calls.append("add_directive")
            raise AssertionError("CLI 不得再新增手写旨意")

        def update_directive(self, *args, **kwargs):
            self.calls.append("update_directive")
            raise AssertionError("CLI 不得再改写旨意")

    answers = iter(["add", "拟一道新旨", "edit 7", "改稿", "back"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    session = Session()

    assert term.review_directives(session) == "back"
    assert session.calls == ["enter_review", "back_to_summoning"]


def test_adjudication_takes_emperor_pick_not_first_option(monkeypatch):
    """批红按皇帝所选编号提交；不取首选项。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    assert term._adjudicate_cli_decisions(session, result) == "邸报"

    (choices,) = session.submitted
    assert len(choices) == 1
    choice = choices[0]
    assert choice["decision_key"] == "rescript_draft:3:0"
    assert choice["label"] == "照旧额全发"
    assert choice["action"] == "follow_draft"
    assert choice["draft_capability"] == "cap-b"


def _ordinary_row(decision_key: str = "decision:3:0") -> dict:
    """普通 decision 案头行（核内要求实选项，回车不成立）。"""
    return {
        "decision_key": decision_key,
        "kind": "decision",
        "source_turn": 3,
        "idx": 0,
        "title": "毛文龙裁断",
        "context": "东江事急，须御前亲裁。",
        "options": [
            {"label": "斩", "hint": "严肃军纪"},
            {"label": "留", "hint": "暂稳东江"},
        ],
    }


def test_adjudication_blank_pick_on_urgent_leaves_choice_to_core(monkeypatch):
    """急务回车＝不另批：入口只交 decision_key，动作由核内机械处置（hold）。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    term._adjudicate_cli_decisions(session, result)

    assert session.submitted == [[{"decision_key": "rescript_draft:3:0"}]]


def test_adjudication_blank_on_ordinary_decision_reprompts(monkeypatch):
    """普通 decision 回车不是核内认的留中：入口重问，不代造空 choice。

    核内 validate_all 对缺 action 的 decision 行既不默认 hold 也拒收（"decision 选项
    不在当前 options"），入口若替皇帝交空 pick 会让整批被拒、连同已答的案作废。
    """
    session = _wire_gate(monkeypatch, _AdjudicateSession([_ordinary_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    answers = iter(["", "  ", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices == [{
        "decision_key": "decision:3:0",
        "label": "留",
        "hint": "暂稳东江",
    }]


def test_adjudication_reprompts_on_out_of_range_number(monkeypatch):
    """越界编号不落 choice：留在本案重问，案头与核都不动（非编号输入是朱笔批语，另一条）。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    answers = iter(["9", "0", "3", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices[0]["label"] == "先发半饷"
    assert choices[0]["draft_capability"] == "cap-a"


def test_adjudication_uses_desk_readback_when_result_has_no_decisions(monkeypatch):
    """result.decisions 空时回读同一案头（session.pending_decisions），入口不另读库。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row("decision:4:1")]))
    result = SimpleNamespace(awaiting=True, report="", decisions=[])
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices[0]["decision_key"] == "decision:4:1"


def test_adjudication_skips_when_not_awaiting():
    session = _AdjudicateSession([])
    result = SimpleNamespace(awaiting=False, report="邸报已归档", decisions=[])
    assert term._adjudicate_cli_decisions(session, result) == "邸报已归档"
    assert session.submitted == []


# #1902 F4：原此处另有一条 ``test_project_hitl_option_is_the_single_projection``
# ——直接对 ``project_hitl_option`` 这个 helper 做参数化单测（helper-only）。它的
# 契约（按 index 取案上那条、越界回首项）已由上面「按编号择定 → 真编排收下并落库
# choice 就是皇帝所选那条」和「越界编号不落 choice」两条**经入口**的用例覆盖，
# 生产 helper 整个坏掉那两条就会红。故删，不换形再造。


# ── 经真核的 tracer：入口产出的 choices 必须被生产 submit_hitl_choices 收下 ──
# #1902：这组用例此前把 GameSession.submit_hitl_choices 换成测试自写的
# validate→apply 链，生产提交入口整个坏掉也照样绿。现改为走真编排，只中和
# 最外层 LLM 缝（与 tests/test_cli_play_turn.py 的 play_turn tracer 同一手法）。


def _real_submit_session(monkeypatch, db, state, content, *, candidate_ids=()):
    """真 GameSession 壳 + 真 submit_hitl_choices；只中和外部 LLM 缝。

    本回合暂存上下文照真实 phase1 形状落一份（phase2 要读它续跑）。``candidate_ids``
    给本回合候选快照：核内 ``bind_decisions_to_candidate_events`` 只在快照非空时按
    快照重绑 event_id，故请旨等非事件身份那几条不传（它们的身份不是 events 表事件）。
    """
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import make_light_session

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    simulator_payload = {
        "candidate_events": [{"id": cid, "title": ""} for cid in candidate_ids],
        "transit_semantics": [],
    } if candidate_ids else None
    db.save_resolve_context(
        int(state.turn), "测试诏书", {"simulator_payload": simulator_payload},
    )
    db.save_turn_report(state, "邸报已成")
    session = make_light_session(db, state, content)
    # 最外层 LLM 缝：世界段推演与月链转译。中和它们，核内编排与领域写全走真逻辑。
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    return session


def test_cli_blank_pick_on_urgent_reaches_core_hold(game, monkeypatch):
    """急务回车 → 经真 submit_hitl_choices 机械 hold，案卷落 decided（外部可见）。"""
    db, state, content = game
    db.save_rescript_drafts(int(state.turn), [{
        "title": "陕西告饥", "context": "秦地赤旱",
        "options": [{"label": "发饷", "hint": "照拟", "draft_capability": "cap-1"}],
    }])
    db.conn.commit()
    session = _real_submit_session(monkeypatch, db, state, content)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    # 外部可见：经真编排落库即 decided + hold。
    # （不在此案重复正向断言 validate_all helper；核侧空 pick 契约见 ordinary 拒收案。）
    stored = db.list_rescript_drafts()[0]
    assert stored["status"] == "decided"
    assert stored["choice"]["action"] == "hold"


def test_cli_blank_pick_on_ordinary_decision_is_rejected_by_core(game, monkeypatch):
    """回车语义只在急务成立：若入口交空 pick，真核整批拒（此钉核侧事实）。"""
    from ming_sim import rescript_actions as ra

    db, state, _content = game
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    desk_row = db.list_rescript_desk(int(state.turn))[0]
    with pytest.raises(ValueError):
        ra.validate_all([desk_row], [{"decision_key": desk_row["decision_key"]}])


def test_cli_chosen_option_reaches_core_and_lands_decision(game, monkeypatch):
    """按编号择定 → 真编排收下并落 decided，落库 choice 就是皇帝所选那条（非首选项）。"""
    db, state, content = game
    turn_before = int(state.turn)
    db.save_pending_decisions(turn_before, [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    session = _real_submit_session(
        monkeypatch, db, state, content, candidate_ids=("mao_wenlong",),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    # 真编排跑完了整条亲裁续推（月份已推进），断言落在本回合那一行上。
    assert int(state.turn) > turn_before
    stored = db.list_pending_decisions(turn_before)[0]
    assert stored["choice"]["label"] == "留"
    assert stored["status"] == "decided"


def test_cli_imperial_note_reaches_core_for_question(game, monkeypatch):
    """#1902：请旨只交亲笔批语 → 经真编排落库，批语不被改写成某条票拟。

    资格判定只在核内（``rescript_actions.validate_all`` 的 note-only 通道，与 Web
    decisionModal 同一口径）；入口只负责把皇帝的原话透传过去。
    """
    db, state, content = game
    turn_before = int(state.turn)
    db.save_pending_decisions(turn_before, [{
        "event_id": "decree-question:ref-1:0", "title": "是否加赈",
        "context": "灾民待哺",
        "options": [{"label": "准", "hint": "出仓"}, {"label": "驳", "hint": "缓"}],
    }])
    db.conn.commit()
    # 请旨身份不是 events 表事件（核内 apply 已按前缀豁免 event 账），故不给候选快照。
    session = _real_submit_session(monkeypatch, db, state, content)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "着户部另议")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    stored = db.list_pending_decisions(turn_before)[0]
    assert stored["status"] == "decided"
    assert stored["choice"]["note"] == "着户部另议"
    assert stored["choice"].get("label", "") == ""


def test_cli_imperial_note_on_non_question_decision_is_refused_by_core(game, monkeypatch):
    """非请旨的普通裁断不给 note-only：核整批拒，案卷仍 pending（入口不代造票拟）。"""
    db, state, content = game
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    session = _real_submit_session(monkeypatch, db, state, content)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "着户部另议")

    with pytest.raises(ValueError):
        term._adjudicate_cli_decisions(
            session, SimpleNamespace(
                awaiting=True, report="", decisions=session.pending_decisions(),
            ),
        )

    stored = db.list_pending_decisions(int(state.turn))[0]
    assert stored["status"] == "pending"


# ── F2：中断回话重试与建轮关联失败的真实行为 ────────────────────────────
# 判官原证：建轮归属修回「殿上」后，CLI 仍按被召大臣名查询中断轮 → 实际中断问话
# 不可重试（RETRY_COUNTS hall 1 / selected_minister 0）。另：建轮方法只保护 append，
# 问话关联更新失败发生在保护之外 → 遗留 generating 孤儿轮挡住下一次问话。


def _hall_session(game):
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    return make_light_session(db, state, content)


def _mark_interrupted(db, chat_turn_id: int) -> None:
    db.conn.execute(
        "UPDATE chat_turns SET status='interrupted' WHERE id=?", (int(chat_turn_id),),
    )
    db.conn.commit()


def test_cli_retry_finds_hall_owned_interrupted_turn(game, monkeypatch):
    """建轮归殿上的中断问话，CLI 重试真能取到（不再按大臣名反查查不到）。"""
    db, state, content = game
    session = _hall_session(game)
    minister = next(
        name for name, c in content.characters.items() if c.status == "active"
    )
    turn = GameSession.begin_audience_chat_turn(
        session, "边饷如何？", message_speaker=minister, agno_session_id="cli:殿上",
    )
    assert db.list_hall_chat_turns(int(turn.night_id))[0]["id"] == turn.chat_turn_id
    _mark_interrupted(db, turn.chat_turn_id)

    # 取数：共核方法按建轮归属取到，并带回原问话归属。
    retries = session.pending_audience_reply_retries()
    assert [r["chat_turn_id"] for r in retries] == [turn.chat_turn_id]
    assert retries[0]["message_speaker"] == minister

    session.scene_chat = lambda *a, **k: SimpleNamespace(  # type: ignore[method-assign]
        answer="回话正文", court_action="", proposed_directive=None,
        appointed_minister="", registered_minister="", displaced_minister="",
        pending_action_failures=[], next_minister="",
    )
    session.schedule_pending_scene_translation = lambda result: None  # type: ignore[method-assign]

    assert term._retry_interrupted_reply_cli(session, minister) is None

    # 回话真落库，且挂回原问话的那位大臣（不是建轮的殿上）。
    row = db.conn.execute(
        "SELECT status, minister_message_id FROM chat_turns WHERE id=?",
        (int(turn.chat_turn_id),),
    ).fetchone()
    assert row["status"] == "active"
    assert int(row["minister_message_id"] or 0) >= 1
    msg = db.conn.execute(
        "SELECT minister_name, role FROM chat_messages WHERE id=?",
        (int(row["minister_message_id"]),),
    ).fetchone()
    assert msg["minister_name"] == minister
    assert msg["role"] == "minister"


def test_pending_retries_empty_without_open_night(game):
    """无本夜 → 无可重试（不因查不到而误报有轮）。"""
    session = _hall_session(game)
    assert session.pending_audience_reply_retries() == []


def test_question_association_failure_leaves_no_orphan_turn(game, monkeypatch):
    """问话与轮关联失败时整段回滚：库里不留问话，也不留占着本夜的轮。"""
    db, _state, _content = game
    session = _hall_session(game)

    def _boom_update(chat_turn_id, **kwargs):
        raise RuntimeError("association boom")

    monkeypatch.setattr(db, "update_chat_turn_messages", _boom_update)
    with pytest.raises(RuntimeError, match="association boom"):
        session.begin_audience_chat_turn("边饷如何？", message_speaker="张瑞图")

    assert db.list_in_flight_chat_turns() == []
    assert db.conn.execute("SELECT id, role, content FROM chat_messages").fetchall() == []
    assert db.conn.execute(
        "SELECT id, status, user_message_id FROM chat_turns"
    ).fetchall() == []
    assert an.get_open_night(db) is not None

    monkeypatch.undo()
    turn = session.begin_audience_chat_turn("再问一句", message_speaker="张瑞图")
    assert int(turn.chat_turn_id) >= 1
    linked = db.conn.execute(
        "SELECT user_message_id FROM chat_turns WHERE id = ?",
        (int(turn.chat_turn_id),),
    ).fetchone()
    assert int(linked["user_message_id"] or 0) >= 1
    assert an.get_open_night(db) is not None


def test_save_load_round_trip_through_shared_core(game):
    """CLI 存档 → 改库 → 读档：真走共享核 ``save_slots.replace_database``（#1902 F2）。

    判官原证：备份/热替换/失败恢复/候选重建/可恢复判定全在 WebGame 私有方法里，
    CLI 入口根本没有读档能力，两端存读档事实不一致。此处钉 CLI 真能存、真能读回。
    """
    from ming_sim.paths import save_slot_path
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    session = make_light_session(db, state, content)

    term._cli_save(session, "cli-slot")
    slot = save_slot_path("cli-slot")
    assert os.path.isfile(slot), slot
    turn_at_save = int(session.state.turn)

    # 存后写一条只由玩家动作产生的痕迹（直写库只为构造「存档之后」的差异）。
    session.db.kv_set("cli_probe_marker", "after-save")
    assert session.db.kv_get("cli_probe_marker") == "after-save"

    loaded = term._cli_load(session, "cli-slot")
    assert loaded is not None, "读档失败"
    try:
        assert loaded is not session, "读档后应是新会话对象"
        assert loaded.db.kv_get("cli_probe_marker") is None, "读档应回到存档时的库"
        assert int(loaded.state.turn) == turn_at_save
        # 新会话真能用（不是只建了个壳）。
        assert loaded.db.conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        loaded.close()


def test_load_missing_slot_keeps_current_game(game):
    """读不存在的档：留在原局，不动活会话。"""
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    session = make_light_session(db, state, content)
    marker_before = session.db.conn.execute("SELECT 1").fetchone()[0]

    assert term._cli_load(session, "no-such-slot") is None
    assert session.db.conn.execute("SELECT 1").fetchone()[0] == marker_before == 1


def test_save_to_rejects_unsafe_names(game):
    """穿越档名在会话存档入口拒收。Web 公共删档入口另有菜单路由案。"""
    from ming_sim.paths import UnsafeSaveNameError
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    session = make_light_session(db, state, content)

    for bad in ("../../etc/passwd", ".hidden", "   "):
        with pytest.raises(UnsafeSaveNameError):
            session.save_to(bad)


# ── F1：真实 CLI 入口必须消费运行档保存的配置（不再索要 key、不跑默认地址） ──


def _write_api_profile(tmp_path, monkeypatch, **api_over) -> None:
    from ming_sim import llm_config

    payload = {
        "channel": "api",
        "api": {
            "base_url": "https://saved.example/v1",
            "model": "saved-model",
            "api_key": "sk-saved",
            "timeout_seconds": 77,
        },
        "cli": {},
    }
    payload["api"].update(api_over)
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))


def test_run_cli_uses_saved_profile_and_never_prompts_for_key(tmp_path, monkeypatch):
    """真实 run_cli 入口：档里的地址/模型/key/超时全部生效，且不向人索要 API key。

    这是判官 F1 原证的回归：修复前 CLI 把入参当最终值，跑默认地址/默认模型/API 超时，
    并因「档里的 key 没被读」而索要 key。
    """
    _write_api_profile(tmp_path, monkeypatch)
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)

    prompts: list = []
    monkeypatch.setattr("getpass.getpass", lambda prompt="": prompts.append(prompt) or "")
    built: dict = {}

    def _fake_session(db_path, llm_config, start_ym=""):
        built["cfg"] = llm_config
        raise SystemExit("stop-after-config")

    monkeypatch.setattr("ming_sim.cli.terminal.GameSession", _fake_session)

    with pytest.raises(SystemExit):
        term.run_cli(
            base_url="https://api.openai.com/v1", model="gpt-4o-mini",
            db_path=str(tmp_path / "probe.db"), api_key="", timeout_seconds=180,
        )

    cfg = built["cfg"]
    assert cfg.base_url == "https://saved.example/v1"
    assert cfg.model == "saved-model"
    assert cfg.api_key == "sk-saved"
    assert cfg.timeout_seconds == 77
    assert prompts == [], "档里已有真 key，不得再向人索要"


def test_run_cli_falls_back_to_entry_args_when_profile_empty(tmp_path, monkeypatch):
    """档为空时才回落入口入参（回落保留，落差归位）。"""
    from ming_sim import llm_config

    monkeypatch.setattr(
        llm_config, "RUNTIME_LLM_PATH", str(tmp_path / "missing.json"),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-typed")
    built: dict = {}

    def _fake_session(db_path, llm_config, start_ym=""):
        built["cfg"] = llm_config
        raise SystemExit("stop-after-config")

    monkeypatch.setattr("ming_sim.cli.terminal.GameSession", _fake_session)

    with pytest.raises(SystemExit):
        term.run_cli(
            base_url="https://env.example/v1", model="env-model",
            db_path=str(tmp_path / "probe2.db"), api_key="", timeout_seconds=180,
        )

    cfg = built["cfg"]
    assert cfg.base_url == "https://env.example/v1"
    assert cfg.model == "env-model"
    assert cfg.api_key == "sk-env"
