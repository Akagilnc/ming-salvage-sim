"""#1837 C1a：召对转译——交办载荷与应允。

Seams:
- translate_audience_turn / run_audience_turn_translation（转译 → C0 分派）
- GameSession.scene_chat（回话后转译；退役并行分类器）
- close_night 收夜成案 → 过月落账
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from ming_sim.audience_night import (
    close_night,
    list_chat_turns_for_night,
    open_night,
)
from ming_sim.audience_translate import (
    build_night_said_so_far,
    normalize_audience_declaration,
)
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.session import GameSession


def _sess(db, state, content, *, llm_config=None, translate_fn=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = None
    sess._audience_translate_fn = translate_fn
    return sess


def _region_id(db, preferred: str = "shaanxi") -> str:
    row = db.conn.execute(
        "SELECT id FROM regions WHERE id=? LIMIT 1", (preferred,),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def _hong_name(db, content) -> str:
    if "洪承畴" in getattr(content, "characters", {}):
        return "洪承畴"
    row = db.conn.execute(
        "SELECT name FROM characters WHERE name='洪承畴' LIMIT 1"
    ).fetchone()
    if row is not None:
        return str(row["name"])
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _persist_night_chat(db, state, night_id: int, user_text: str, reply: str) -> int:
    """把一轮皇帝/回话落到 chat_messages + chat_turns（真表形）。"""
    speaker = "殿上"
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'user', ?, 'held')",
        (speaker, int(state.turn), user_text),
    )
    uid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?, ?, 'minister', ?, 'held')",
        (speaker, int(state.turn), reply),
    )
    mid = int(cur.lastrowid)
    db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name, turn, year, period, user_message_id, minister_message_id, "
        " status, night_id, night_seq) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 1)",
        (
            speaker, int(state.turn), int(state.year), int(state.period),
            uid, mid, int(night_id),
        ),
    )
    db.conn.commit()
    return uid


def test_normalize_keeps_only_c1a_sections():
    raw = {
        "commissions": [{"text": "拟旨"}],
        "promises": [{"action_id": 1, "decision": "应允"}],
        "presence": [{"name": "王绍徽", "effect": "enter"}],
        "noise": 1,
    }
    out = normalize_audience_declaration(raw)
    assert set(out) == {"commissions", "promises"}
    assert out["commissions"] == [{"text": "拟旨"}]
    assert out["promises"] == [{"action_id": 1, "decision": "应允"}]


def test_build_night_said_reads_chat_messages_not_missing_turn_columns(game):
    """本场已说：从 chat_messages 经 message_id 取正文，不读不存在的 user_text 列。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    _persist_night_chat(db, state, night_id, "边饷如何？", "边关尚稳。")
    said = build_night_said_so_far(db, night_id)
    assert any("边饷如何" in line for line in said), said
    assert any("边关尚稳" in line for line in said), said
    # 真 turn 行上没有 user_text
    turn = list_chat_turns_for_night(db, night_id)[0]
    assert "user_text" not in turn or turn.get("user_text") in (None, "")


def test_appointment_and_relief_through_scene_chat_then_close_and_settle(game, monkeypatch):
    """AC1：scene_chat 转译 → typed 暂存 → 应允收夜成案 → 过月落账。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    person = _hong_name(db, content)
    region = _region_id(db)
    edict = f"任命{person}为陕西巡抚，调银三十万两赈灾"

    commission = {
        "text": edict,
        "appointment": {
            "name": person, "office": "陕西巡抚", "appoint_action": "任命",
        },
        "grant": {
            "grant_action": "赈灾",
            "amount": 30,
            "account": "国库",
            "target_kind": "region",
            "target_id": region,
            "cadence": "一次性",
            "execution_surface": "immediate",
        },
    }
    # 第一轮：交办；第二轮：「准」应允上一轮全部 pending
    calls = {"n": 0}

    def translate_fn(prompt, llm_config):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"commissions": [commission], "promises": []}
        # 应允本夜全部 pending directive+office
        rows = db.conn.execute(
            "SELECT id FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
        return {
            "commissions": [],
            "promises": [
                {"action_id": int(r["id"]), "decision": "应允"} for r in rows
            ],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, translate_fn=translate_fn)

    r1 = sess.scene_chat(edict)
    assert r1.pending_action_id > 0
    pending = [
        dict(r) for r in db.conn.execute(
            "SELECT id, kind, action, payload_json, night_approved "
            "FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
    ]
    kinds = {p["kind"] for p in pending}
    assert "directive" in kinds and "office" in kinds
    dir_row = next(p for p in pending if p["kind"] == "directive")
    payload = json.loads(dir_row["payload_json"])
    assert payload["text"] == edict
    assert payload["grant_action"] == "赈灾"
    assert int(payload["amount"]) == 30
    assert payload["name"] == person
    assert payload["office"] == "陕西巡抚"
    assert all(int(p["night_approved"] or 0) == 0 for p in pending)

    r2 = sess.scene_chat("准")
    assert r2.answer == "臣等遵旨。"
    approved = db.conn.execute(
        "SELECT id, kind, night_approved FROM pending_actions "
        "WHERE id IN ({})".format(",".join(str(p["id"]) for p in pending))
    ).fetchall()
    assert all(int(r["night_approved"] or 0) == 1 for r in approved), approved

    close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)
    for p in pending:
        row = db.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (int(p["id"]),),
        ).fetchone()
        assert row["status"] == "committed", (p["kind"], row["status"])

    appt = db.conn.execute(
        "SELECT id, status, action_type FROM decree_dossiers "
        "WHERE action_type='appointment' AND target_id=? "
        "ORDER BY id DESC LIMIT 1",
        (person,),
    ).fetchone()
    assert appt is not None

    grant_dossiers = [
        d for d in db.list_decree_dossiers()
        if d["action_type"] == "grant_allocation"
        and str(d.get("target_id") or "") == region
    ]
    assert grant_dossiers

    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)
    db.save_state(state)
    for d in grant_dossiers:
        db.apply_dossier_promulgation(
            state, int(d["id"]), decision="promulgated", content=content,
        )
    if str(appt["status"]) == "proposed":
        db.apply_dossier_promulgation(
            state, int(appt["id"]), decision="promulgated", content=content,
        )

    char = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (person,),
    ).fetchone()
    assert "陕西巡抚" in str(char["office"] or "")
    moved = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE account='国库' "
        "AND target_id=? AND delta < 0 ORDER BY id DESC LIMIT 1",
        (region,),
    ).fetchone()
    assert moved is not None and int(moved["delta"]) == -30


def test_emperor_准_via_scene_chat_approves_no_reply_stays_unapproved(game, monkeypatch):
    """AC2：经 scene_chat 转译，「准」应允；不声明 promises 则默认不应允。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "着户部备赈灾银"}]},
        minister_name="", night_id=int(
            db.conn.execute(
                "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
        ),
    )
    staged_id = int(staged.commissions.applied[0]["id"])

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣在。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )

    # 不表态：空 promises
    sess = _sess(
        db, state, content,
        translate_fn=lambda p, c: {"commissions": [], "promises": []},
    )
    sess.scene_chat("边事如何？")
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 0

    # 「准」
    def approve_fn(prompt, cfg):
        # 皇帝原话必须进 prompt 正文区，不能只靠规则段里的「准」字样。
        assert "【本轮皇帝】准" in prompt, prompt[-200:]
        return {
            "commissions": [],
            "promises": [{"action_id": staged_id, "decision": "应允"}],
        }

    sess._audience_translate_fn = approve_fn
    sess.scene_chat("准")
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1

    close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)
    pa = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert pa["status"] == "committed"
    assert int(pa["committed_directive_id"] or 0) > 0


def test_scene_chat_cli_and_api_same_translation_shape(game, monkeypatch):
    """AC3：CLI 与 API 通道产出同一形状，不再前缀+二次分类两套路。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    region = _region_id(db)
    person = _hong_name(db, content)
    edict = f"任命{person}为陕西巡抚，调银三十万两赈灾"
    declaration = {
        "commissions": [{
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }],
        "promises": [],
    }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    import ming_sim.cli_backend as cb

    def boom(*a, **k):
        raise AssertionError("scene_chat 不得再调 classify_cli_action_intent")

    monkeypatch.setattr(cb, "classify_cli_action_intent", boom)

    shapes = []
    for channel in ("api", "cli"):
        def translate_fn(prompt, llm_config, _decl=declaration):
            shapes.append(normalize_audience_declaration(_decl))
            return _decl

        sess = _sess(
            db, state, content,
            llm_config=SimpleNamespace(channel=channel),
            translate_fn=translate_fn,
        )
        before = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        result = sess.scene_chat(edict)
        after = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        assert after > before
        assert result.pending_action_id > 0

    assert len(shapes) == 2
    assert shapes[0] == shapes[1]
    assert set(shapes[0]) == {"commissions", "promises"}


def test_unhandleable_commission_rejected_as_fact_no_forced_ask(game):
    """AC4：查无此人 / 幻影地区 → 拒收当事实；不强制追问。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    missing_person = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "任命子虚乌有为陕西巡抚",
            "appointment": {
                "name": "子虚乌有某某", "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert missing_person.commissions.applied == []
    assert missing_person.commissions.rejected
    assert any(
        getattr(r, "category", "") == "hallucinated_id"
        for r in missing_person.commissions.rejected
    )

    missing_region = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "着拨银赈济无此州",
            "grant": {
                "grant_action": "赈灾",
                "amount": 10,
                "account": "国库",
                "target_kind": "region",
                "target_id": "no-such-region-xyz",
                "execution_surface": "immediate",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert missing_region.commissions.applied == []
    assert missing_region.commissions.rejected
    assert any(
        getattr(r, "category", "") == "hallucinated_id"
        for r in missing_region.commissions.rejected
    )


def test_appointment_without_text_is_rejected_not_templated(game):
    """P7：任免缺正文拒收，不拼「任命X为Y」。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    person = _hong_name(db, content)
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    # 库中不得出现模板拼装正文
    rows = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE status='pending'"
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        assert f"任命{person}为陕西巡抚" != str(payload.get("text") or "")


def test_scene_chat_translate_prompt_carries_pending_and_spoken(game, monkeypatch):
    """转译 prompt 含本轮皇帝原话区、回话、本夜暂存 id。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    _persist_night_chat(db, state, night_id, "昨夜已问边饷", "臣已回奏。")
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "旧暂存旨正文独特标记XYZ"}]},
        minister_name="", night_id=night_id,
    )
    staged_id = int(staged.commissions.applied[0]["id"])

    seen = {}

    def translate_fn(prompt, llm_config):
        seen["prompt"] = prompt
        return {
            "commissions": [],
            "promises": [{"action_id": staged_id, "decision": "应允"}],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, translate_fn=translate_fn)
    # 用不会与规则段「准」混淆的皇帝原话
    sess.scene_chat("着即照办")

    prompt = seen["prompt"]
    assert "【本轮皇帝】着即照办" in prompt
    assert "【本轮回话】臣领旨。" in prompt
    assert f"#{staged_id}" in prompt
    assert "旧暂存旨正文独特标记XYZ" in prompt
    assert "昨夜已问边饷" in prompt
    assert "臣已回奏" in prompt
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1
