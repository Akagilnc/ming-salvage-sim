"""CLI 后端会话落地的共享真源（session.apply_cli_conversation_actions）。

补 toolcall 缺口——agy/codex 不做 function-calling，原 propose_directive /
secret_order / 会话动作工具不触发。靠 apply_cli_conversation_actions 一处把
拟旨/密令前缀入档 + LLM 判会话动作（更新/催办/提交核议/记进展/调教）落地；
session.chat 非流式路径与 web streaming 路径共用它，杜绝漂移（CMR F3 / codexC-1）。

方法只用 self.db/state/registry，故用 fake self（绑定方法）测，不构造完整 GameSession。
"""

from __future__ import annotations

import json
import threading
import types
from types import SimpleNamespace

import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.session import GameSession


def _result():
    return SimpleNamespace(answer="", proposed_directive=None, secret_order_id=None, pending_action_id=0)


def test_non_streaming_path_surfaces_pending_action_id(game, monkeypatch):
    """非流式 session 路径(_cli_backend_fallback_actions)也要 surface pending_action_id,
    与流式不漂移(ship-pre CMR);暂存不当场落 secret_order_id。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "非流式承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", [], deadline_months=0)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid, "new_title": "改", "new_content": "改",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    result = _result()
    result.answer = "臣领旨，已记改。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"), "改一下要旨")
    assert result.pending_action_id        # 非流式也回传 staged 信号
    assert result.secret_order_id is None  # 暂存不当场落库


def _session(db, state, registry=None, llm_config=None):
    """fake self：带 db/state/registry + 绑定共享方法与适配器。"""
    s = SimpleNamespace(
        db=db,
        state=state,
        registry=registry,
        llm_config=llm_config or SimpleNamespace(channel=""),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    s._cli_backend_fallback_actions = types.MethodType(
        GameSession._cli_backend_fallback_actions, s)
    return s


def _no_conv_action(monkeypatch):
    """默认让会话动作判定返回「无」，避免无关测试触发真 backend。"""
    monkeypatch.setattr(cb, "extract_minister_actions",
                        lambda *a, **k: {"secret_action": "无", "order_id": 0,
                                         "new_title": "", "new_content": "", "deadline_months": 0,
                                         "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "_trace", lambda rec: None)


def test_draft_prefix_with_active_secret_order_runs_zero_llm(game, monkeypatch):
    """#344「按钮前缀路零 LLM」(US3)：玩家用『拟旨如下：』前缀、且该大臣有 active 密令时，
    旧的会话密令抽取器(extract_minister_actions, LLM)不得被触发——前缀已由 resolve_minister_actions
    零 LLM 落拟旨。整合 cmr r2/r3 codex 完整性腿抓出：原实现 secret 块未按 explicit_prefixed 把门，
    于是前缀消息在有 active 密令时仍多跑一次 LLM extractor。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "前缀零LLM承办官"
    db.create_secret_order(state, who, "原密令", "查某亏空", [], deadline_months=0)

    def _forbidden(*a, **k):
        raise AssertionError("前缀拟旨不应触发任何后置 LLM 抽取器")

    monkeypatch.setattr(cb, "extract_minister_actions", _forbidden)
    monkeypatch.setattr(cb, "extract_draft_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_appointment_action", _forbidden)
    monkeypatch.setattr(cb, "extract_confirmation_intent", _forbidden)

    result = _result()
    result.answer = "臣遵旨，当即清核辽饷。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"),
        "拟旨如下：着户部清核辽饷。")

    # 前缀拟旨零 LLM 落库：directive 入档，无 secret/pending 误触发
    assert result.proposed_directive is not None
    assert result.proposed_directive.text == "臣遵旨，当即清核辽饷。"
    assert result.secret_order_id is None
    assert not result.pending_action_id


def test_chat_starts_cli_action_classification_before_reply_finishes(game, monkeypatch):
    """CLI 召对动作判断只看皇帝消息，应与大臣回话并发；无动作消息回话后不再跑抽取器。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    classifier_started = threading.Event()
    allow_reply = threading.Event()
    calls = []

    def fake_classify(*args, **kwargs):
        calls.append("classify")
        classifier_started.set()
        return {"kind": "none"}

    def forbidden_post_reply(*args, **kwargs):
        raise AssertionError("普通问询回话后不应再跑动作抽取")

    class FakeAgent:
        def run(self, message):
            assert classifier_started.wait(1), "动作判断应在大臣回话完成前启动"
            allow_reply.set()
            return SimpleNamespace(content="臣谨奏：辽饷尚可支应。", tools=[])

    registry = SimpleNamespace(
        get=lambda character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = registry
    sess.llm_config = SimpleNamespace(channel="cli")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message

    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(cb, "extract_minister_actions", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_appointment_action", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_draft_intent", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_confirmation_intent", forbidden_post_reply)

    result = sess.chat(minister.name, "辽东军饷如何？")

    assert allow_reply.is_set()
    assert result.answer == "臣谨奏：辽饷尚可支应。"
    assert calls == ["classify"]


def test_begin_turn_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(
        load_state=lambda: state,
        apply_historical_deaths=lambda state: [],
        apply_historical_debuts=lambda state: [],
        apply_historical_power_renames=lambda state: [],
        previous_turn_summary=lambda state: "",
        save_state=lambda state: None,
    )
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
        registry=None,
        last_decree="",
        last_report="",
        _begun=False,
        auto_save=lambda label: None,
        turn_snapshot=lambda: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))
    monkeypatch.setattr(session_mod, "MinisterRegistry",
                        lambda llm_config, agno_db, context: SimpleNamespace())

    GameSession.begin_turn(fake)

    assert seen == [cfg]


def test_chat_rollback_refresh_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(load_state=lambda: state)
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
        registry=SimpleNamespace(),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))
    monkeypatch.setattr(session_mod, "MinisterRegistry",
                        lambda llm_config, agno_db, context: SimpleNamespace())

    GameSession.refresh_runtime_after_chat_rollback(fake)

    assert seen == [cfg]


def test_no_backend_is_noop(game, monkeypatch):
    """未启 CLI 后端（走原 api 路径）时，胶水不动任何东西。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    result = _result()
    result.answer = "臣领旨。敕谕户部发银三万两。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is None
    assert result.secret_order_id is None


def test_draft_prefix_registers_directive(game, monkeypatch):
    """玩家『拟旨如下：』→ 大臣回话原文入 turn_directives（pending 待核）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is not None
    assert result.proposed_directive.text == result.answer
    assert result.proposed_directive.status == "pending"
    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE id=?",
        (result.proposed_directive.id,),
    ).fetchone()
    assert row["text"] == result.answer        # 真落库
    assert row["status"] == "pending"


def test_runtime_cli_channel_without_env_registers_directive(game, monkeypatch):
    """runtime 选择 CLI 通道时，即使无 MING_SIM_LLM_BACKEND，也要启用会话写动作胶水。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")

    assert result.proposed_directive is not None
    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE id=?",
        (result.proposed_directive.id,),
    ).fetchone()
    assert row["text"] == result.answer
    assert row["status"] == "pending"


def test_runtime_cli_secret_prefix_uses_zero_llm_without_env(game, monkeypatch):
    """runtime CLI 通道的前缀密令直接取回话文本，不调用任何 runner。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    calls = []

    def fake_codex(prompt, model=None, timeout=None):
        calls.append(("codex", model, timeout))
        raise AssertionError("前缀密令不应调 codex")

    def fake_agy(prompt, timeout=None):
        calls.append(("agy", timeout))
        raise AssertionError("前缀密令不应调 agy")

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)
    result = _result()
    result.answer = "臣领密旨，可授李若琏暗查。"
    _session(
        db,
        state,
        llm_config=SimpleNamespace(
            channel="cli", cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
        ),
    )._cli_backend_fallback_actions(
        result, SimpleNamespace(name="王在晋", office_type="兵部"),
        "密令如下：查辽东军饷有无侵冒，三月内回奏")

    assert calls == []
    row = db.conn.execute(
        "SELECT title, content, minister_name FROM secret_orders WHERE id=?",
        (result.secret_order_id,),
    ).fetchone()
    assert row["title"] == "查辽东军饷有无侵冒，三月内回奏"
    assert row["content"] == "臣领密旨，可授李若琏暗查。"
    assert row["minister_name"] == "王在晋"


def test_secret_prefix_creates_order(game, monkeypatch):
    """玩家『密令如下：』→ 取大臣回话文本建 active 密令，回填 secret_order_id。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_run_agy", lambda p: (_ for _ in ()).throw(AssertionError("前缀密令不应调 LLM")))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    result = _result()
    result.answer = "臣领密旨，可授李若琏暗查。"
    _session(db, state, registry=None)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="王在晋", office_type="兵部"),
        "密令如下：查辽东军饷有无侵冒，三月内回奏")
    assert result.secret_order_id
    row = db.conn.execute(
        "SELECT title, content, minister_name, status FROM secret_orders WHERE id=?",
        (result.secret_order_id,),
    ).fetchone()
    assert row["title"] == "查辽东军饷有无侵冒，三月内回奏"
    assert row["content"] == "臣领密旨，可授李若琏暗查。"
    assert row["minister_name"] == "王在晋"
    assert row["status"] == "active"


def test_secret_prefix_upserts_not_duplicates_and_refreshes(game, monkeypatch):
    """CMR F3：CLI 胶水须走 upsert（同承办人再下=更新同条，不建重复）+ registry.refresh。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    refreshed = []
    registry = SimpleNamespace(refresh=lambda name: refreshed.append(name))
    s = _session(db, state, registry=registry)
    who = "测试承办官F3"

    monkeypatch.setattr(cb, "_run_agy", lambda p: (_ for _ in ()).throw(AssertionError("前缀密令不应调 LLM")))
    r1 = _result(); r1.answer = "臣领旨一。"
    s._cli_backend_fallback_actions(r1, SimpleNamespace(name=who, office_type="兵部"), "密令如下：查甲")
    oid1 = r1.secret_order_id
    assert oid1

    r2 = _result(); r2.answer = "臣领旨二。"
    s._cli_backend_fallback_actions(r2, SimpleNamespace(name=who, office_type="兵部"), "密令如下：改查甲")
    assert r2.secret_order_id == oid1            # 同一条，不建重复
    cnt = db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE minister_name=? AND status='active'", (who,)
    ).fetchone()[0]
    assert cnt == 1
    row = db.conn.execute("SELECT content FROM secret_orders WHERE id=?", (oid1,)).fetchone()
    assert row["content"] == "臣领旨二。"        # 内容真被更新为大臣回话
    assert refreshed.count(who) == 2             # 两次都刷新了承办大臣 agent


def test_existing_directive_not_overwritten(game, monkeypatch):
    """agno 工具已产 directive 时，胶水不重复入档（result.proposed_directive 非空）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    sentinel = SimpleNamespace(id=999, text="原工具产出", status="draft")
    result = _result()
    result.answer = "臣另拟一道。钦此。"
    result.proposed_directive = sentinel
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两")
    assert result.proposed_directive is sentinel    # 不被覆盖


# ── codexC-1：会话动作（非前缀）必须经 session 路径落地，不再只在 web 有 ──

def test_conversation_update_lands_via_session_path(game, monkeypatch):
    """无前缀、口头说『更新密令』→ session 路径(apply_cli_conversation_actions)把更新进 pending 暂存,
    颁诏 commit 才落真实表(ADR 0006 动作闸门);召对当场不直写、不丢动作。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "会话动作承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", ["甲"], deadline_months=0)
    # LLM 判意图：更新该密令（不走真 backend，直接喂结构化动作）
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid, "new_title": "改后标题",
        "new_content": "改后内容", "deadline_months": 0,
        "cultivate_skill": "", "cultivate_trait": ""})
    s = _session(db, state, registry=SimpleNamespace(refresh=lambda n: None))
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "你那道密令改一下，内容换成……", "臣领旨，已记改。",
        has_directive=False, secret_order_id=None,
    )
    # 召对当场：进暂存、不报"已交付"、真实表不动
    assert res["secret_order_id"] is None
    assert res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    # 颁诏 commit 才落库
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


def test_runtime_cli_conversation_update_uses_configured_runner_without_env(game, monkeypatch):
    """无前缀会话动作的 LLM 判定也必须按 runtime CLI 配置分派。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "配置通道承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", [], deadline_months=0)
    calls = []
    canned = json.dumps({
        "密令动作": "更新",
        "目标密令编号": oid,
        "新标题": "改后标题",
        "新内容": "改后内容",
        "期限月数": 0,
    }, ensure_ascii=False)

    def fake_codex(prompt, model=None, timeout=None):
        calls.append(("codex", model, timeout))
        return canned, 1

    def fake_agy(prompt, timeout=None):
        calls.append(("agy", timeout))
        raise RuntimeError("agy should not be used")

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)
    s = _session(
        db,
        state,
        llm_config=SimpleNamespace(
            channel="cli", cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
        ),
    )

    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "你那道密令改一下，内容换成……",
        "臣领旨，已记改。",
        has_directive=False,
        secret_order_id=None,
    )

    # 会话动作判定按配置 runner 分派，且密令动作命中后不再串行跑任免抽取。
    assert calls == [("codex", "gpt-5.5", 240)]
    # 动作闸门：暂存,颁诏 commit 才落库(不在召对当场直写)
    assert res["secret_order_id"] is None
    assert res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


def test_conversation_rush_skips_pending_review(game, monkeypatch):
    """催办目标恰为 pending_review 时不抛错、不误置成功（target_active 守门）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "待核承办官"
    oid = db.create_secret_order(state, who, "待核令", "内容", [], deadline_months=6)
    db.submit_secret_order_for_review(oid, "已呈核", state.year, state.period)  # → pending_review
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "催办", "order_id": oid, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    s = _session(db, state, registry=None)
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "那事催一下", "臣加紧。", has_directive=False, secret_order_id=None,
    )
    assert res["secret_order_id"] is None        # pending_review 不被催办，不抛错
    row = db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["status"] == "pending_review"     # 状态未被动
