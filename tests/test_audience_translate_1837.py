"""#1837 C1a：召对转译——交办载荷与应允。

Seams:
- translate_audience_turn / run_audience_turn_translation（转译 → C0 分派）
- GameSession.scene_chat（回话后转译；退役并行分类器）
- close_night 收夜成案 → 过月落账
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

import ming_sim.audience_translate as audience_translate
from ming_sim.audience_night import (
    AudienceNightError,
    close_night,
    list_chat_turns_for_night,
    open_night,
)
from ming_sim.audience_translate import normalize_audience_declaration
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.session import GameSession
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
    stub_scene_agent,
)


def _sess(db, state, content, monkeypatch, *, llm_config=None, translate_fn=None):
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
    stub_audience_translate(monkeypatch, translate_fn)
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
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name, turn, year, period, user_message_id, minister_message_id, "
        " status, night_id, night_seq) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, "
        "COALESCE((SELECT MAX(night_seq) + 1 FROM chat_turns WHERE night_id=?), 1))",
        (
            speaker, int(state.turn), int(state.year), int(state.period),
            uid, mid, int(night_id), int(night_id),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


@pytest.mark.parametrize("retry_at_month", [False, True])
def test_pending_round_approval_commits_before_close_or_after_month_join(
    game, monkeypatch, retry_at_month,
):
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    action = dispatch_declaration(
        db, state, {"commissions": [{"text": "着户部备赈济"}]},
        minister_name="", night_id=nid,
    )
    aid = int(action.commissions.applied[0]["id"])
    ctid = _persist_night_chat(db, state, nid, "准", "臣领旨。")
    db.mark_story_extraction_pending(ctid)
    sess = _sess(db, state, content, monkeypatch)
    sess._write_gate = threading.Lock()
    queue = get_session_write_queue(sess)

    def approve(prompt, config):
        return {
            **offline_empty_audience_translate(prompt, config),
            "promises": [{"action_id": aid, "decision": "应允"}],
        }

    def fail(_prompt, _config):
        raise RuntimeError("translation unavailable")

    attempts = 0

    def recover_on_closing(prompt, config):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return fail(prompt, config)
        return approve(prompt, config)

    close_night(
        db, state, content=content, registry=None, llm_config=sess.llm_config,
        write_gate=sess._write_gate, write_queue=queue,
        translate_fn=fail if retry_at_month else recover_on_closing,
        endorsement_extractor_agent=SimpleNamespace(
            run=lambda _: SimpleNamespace(content='{"endorsements": []}'),
        ),
    )
    row = db.conn.execute(
        "SELECT status, night_approved, committed_directive_id "
        "FROM pending_actions WHERE id=?", (aid,),
    ).fetchone()
    if retry_at_month:
        assert row["status"] == "pending"
        with pytest.raises(AudienceNightError, match="夜已收"):
            db.mark_pending_night_approved([aid], night_id=nid)
        stub_audience_translate(monkeypatch, approve)
        sess.await_translations_before_month()
        row = db.conn.execute(
            "SELECT status, night_approved, committed_directive_id "
            "FROM pending_actions WHERE id=?", (aid,),
        ).fetchone()
    assert row["status"] == "committed"
    assert int(row["night_approved"]) == 1
    assert int(row["committed_directive_id"] or 0) > 0


def test_translation_entry_preserves_unknown_rejection_and_source_cutoff(
    game, monkeypatch,
):
    """真实转译入口：未知 section 留痕；上下文只含严格早于源轮的轮次。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    _persist_night_chat(db, state, night_id, "第一问", "第一答")
    source = _persist_night_chat(db, state, night_id, "本轮问", "本轮答")
    _persist_night_chat(db, state, night_id, "后轮问", "后轮答")
    captured: dict[str, object] = {}
    real_build_prompt = audience_translate.build_audience_translate_prompt

    def capture_prompt(**kwargs):
        captured["night_said"] = tuple(kwargs["night_said"])
        return real_build_prompt(**kwargs)

    monkeypatch.setattr(audience_translate, "build_audience_translate_prompt", capture_prompt)
    declaration = {
        "commissions": [{"text": "拟旨赈济"}],
        "commisssions": [{"text": "拼错交办"}],
        "scene_facts": [
            {"body": "提及未在册者", "role": "scene", "person_names": ["未在册者"]},
        ],
    }
    audience_translate.run_audience_turn_translation(
        db,
        state,
        emperor_message="本轮问",
        reply="本轮答",
        night_id=night_id,
        chat_turn_id=source,
        minister_name=_hong_name(db, content),
        translate_fn=lambda prompt, config: {**offline_empty_audience_translate(prompt, config), **declaration},
    )

    said = captured["night_said"]
    assert isinstance(said, tuple)
    # 每轮两条消息；源轮与后轮若越过严格截止，条数会从 2 增至 4/6。
    assert len(said) == 2
    pending = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE status='pending' ORDER BY id"
    ).fetchall()
    assert any("拟旨赈济" in str(row["payload_json"]) for row in pending)
    rejected = db.conn.execute(
        "SELECT section, category FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert any(
        row["section"] == "commisssions" and row["category"] == "invalid_shape"
        for row in rejected
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM story_ledger_entries WHERE night_id=? AND body=?",
        (night_id, "提及未在册者"),
    ).fetchone()[0] == 1
    malformed = dispatch_declaration(
        db, state,
        {"scene_facts": [{"body": "坏形状", "role": ["scene"], "person_names": []}]},
        minister_name="", night_id=night_id,
    )
    assert len(malformed.scene_facts.rejected) == 1


def test_scene_stay_attend_uses_actual_protagonist_not_virtual_speaker(game, monkeypatch):
    from ming_sim.audience_night import (
        SCENE_CHAT_SPEAKER, list_ledger, set_night_protagonist, summon_enter,
    )

    db, state, content = game
    person = _hong_name(db, content)
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    summon_enter(db, night_id, person)
    set_night_protagonist(db, night_id, person, reason="test")
    result = _sess(db, state, content, monkeypatch).scene_chat(
        "留下听着", minister_name=SCENE_CHAT_SPEAKER,
    )
    assert result.court_action == "stay_attend"
    assert list_ledger(db, night_id)[-1]["person_names"] == [person]


def test_appointment_and_relief_through_scene_chat_then_close_and_settle(game, monkeypatch):
    """AC1：scene_chat 转译 → 一条组合暂存 → 应允收夜 → 任免与拨帑两类效果全。

    同入口覆盖属地赈灾与非属地赏赉：后者 region_id=''，咬住案卷幂等键须含
    action_type（否则 appointment 会被既有 grant 行短路吞掉）。
    """
    db, state, content = game
    person = _hong_name(db, content)
    region = _region_id(db)
    # 赏赉目标用人名（非 region），region_id 落 ''——与 appointment 同键碰撞面。
    grant_cases = (
        {
            "label": "region_relief",
            "edict": f"任命{person}为陕西巡抚，调银三十万两赈灾",
            "grant": {
                "grant_action": "赈灾",
                "amount": 30,
                "account": "国库",
                "target_kind": "region",
                "target_id": region,
                "cadence": "一次性",
                "execution_surface": "immediate",
            },
            "grant_target_id": region,
            "ledger_target_id": region,
            "ledger_delta": -30,
        },
        {
            "label": "character_reward",
            "edict": f"任命{person}为陕西巡抚，赏银二十万两",
            "grant": {
                "grant_action": "赏赉",
                "amount": 20,
                "account": "国库",
                "target_kind": "character",
                "target_id": person,
                "execution_surface": "immediate",
            },
            "grant_target_id": person,
            "ledger_target_id": person,
            "ledger_delta": -20,
        },
    )

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )

    for case in grant_cases:
        open_night(db, state, location="乾清宫", time_of_day="夜")
        edict = case["edict"]
        commission = {
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
            "grant": case["grant"],
        }
        calls = {"n": 0}

        def translate_fn(prompt, llm_config, _c=commission, _db=db):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    **offline_empty_audience_translate(prompt, llm_config),
                    "commissions": [_c], "promises": [],
                }
            rows = _db.conn.execute(
                "SELECT id FROM pending_actions WHERE status='pending' ORDER BY id"
            ).fetchall()
            return {
                **offline_empty_audience_translate(prompt, llm_config),
                "commissions": [],
                "promises": [
                    {"action_id": int(r["id"]), "decision": "应允"} for r in rows
                ],
            }

        sess = _sess(db, state, content, monkeypatch, translate_fn=translate_fn)
        r1 = sess.scene_chat(edict)
        assert r1.pending_action_id > 0, case["label"]
        pending = [
            dict(r) for r in db.conn.execute(
                "SELECT id, kind, action, payload_json, night_approved "
                "FROM pending_actions WHERE status='pending' ORDER BY id"
            ).fetchall()
        ]
        # ADR 0028 / #1837：任免+拨帑只落一条组合 directive，不拆 office 第二条。
        assert len(pending) == 1, (case["label"], pending)
        assert pending[0]["kind"] == "directive", case["label"]
        payload = json.loads(pending[0]["payload_json"])
        assert payload["text"] == edict, case["label"]
        assert payload["grant_action"] == case["grant"]["grant_action"], case["label"]
        assert int(payload["amount"]) == int(case["grant"]["amount"]), case["label"]
        assert payload["name"] == person, case["label"]
        assert payload["office"] == "陕西巡抚", case["label"]
        assert payload["appoint_action"] == "任命", case["label"]
        assert int(pending[0]["night_approved"] or 0) == 0, case["label"]

        r2 = sess.scene_chat("准")
        assert r2.answer == "臣等遵旨。", case["label"]
        approved = db.conn.execute(
            "SELECT id, kind, night_approved FROM pending_actions "
            "WHERE id IN ({})".format(",".join(str(p["id"]) for p in pending))
        ).fetchall()
        assert all(int(r["night_approved"] or 0) == 1 for r in approved), (
            case["label"], approved,
        )

        close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)
        for p in pending:
            row = db.conn.execute(
                "SELECT status FROM pending_actions WHERE id=?", (int(p["id"]),),
            ).fetchone()
            assert row["status"] == "committed", (case["label"], p["kind"], row["status"])

        # 同一 pending 必须同时产 appointment 与 grant_allocation（非靠 region_id 碰巧分键）。
        paired = db.conn.execute(
            "SELECT action_type FROM decree_dossiers WHERE pending_action_id=? "
            "ORDER BY action_type",
            (int(pending[0]["id"]),),
        ).fetchall()
        paired_types = {str(r["action_type"]) for r in paired}
        assert "appointment" in paired_types and "grant_allocation" in paired_types, (
            case["label"], paired_types,
        )

        appt = db.conn.execute(
            "SELECT id, status, action_type FROM decree_dossiers "
            "WHERE action_type='appointment' AND target_id=? "
            "ORDER BY id DESC LIMIT 1",
            (person,),
        ).fetchone()
        assert appt is not None, case["label"]

        grant_dossiers = [
            d for d in db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
            and str(d.get("target_id") or "") == case["grant_target_id"]
            and int(d.get("pending_action_id") or 0) == int(pending[0]["id"])
        ]
        assert grant_dossiers, case["label"]

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
        assert "陕西巡抚" in str(char["office"] or ""), case["label"]
        moved = db.conn.execute(
            "SELECT delta FROM economy_ledger WHERE account='国库' "
            "AND target_id=? AND delta < 0 ORDER BY id DESC LIMIT 1",
            (case["ledger_target_id"],),
        ).fetchone()
        assert moved is not None and int(moved["delta"]) == case["ledger_delta"], (
            case["label"], moved,
        )


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
        db, state, content, monkeypatch,
        translate_fn=offline_empty_audience_translate,
    )
    sess.scene_chat("边事如何？")
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 0

    # 「准」
    def approve_fn(prompt, cfg):
        return {
            **offline_empty_audience_translate(prompt, cfg),
            "commissions": [],
            "promises": [{"action_id": staged_id, "decision": "应允"}],
        }

    stub_audience_translate(monkeypatch, approve_fn)
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
            return {**offline_empty_audience_translate(prompt, llm_config), **_decl}

        sess = _sess(
            db, state, content, monkeypatch,
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
    assert "commissions" in shapes[0] and "promises" in shapes[0]
    assert "noise" not in shapes[0]


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


def test_translate_call_failure_is_not_empty_success_dispatch(game, monkeypatch):
    """转译调用失败 ≠ 成功空声明：不进分派、真因经 pending_action_failures 回场。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    before = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
    ).fetchone()["c"]

    def boom(prompt, llm_config):
        raise RuntimeError("simulated translate transport failure")

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣在。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn=boom)
    result = sess.scene_chat("边饷如何？")
    assert result.answer == "臣在。"
    after = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
    ).fetchone()["c"]
    assert after == before  # 失败不得当分派成功写库
    assert result.pending_action_id == 0
    failures = list(result.pending_action_failures or [])
    assert failures, failures
    assert any(
        f.get("category") == "translate_failed"
        and "simulated translate transport failure" in str(f.get("message") or "")
        for f in failures
    ), failures


def test_translate_empty_success_still_dispatches_without_failure(game, monkeypatch):
    """成功空声明仍可分派（零写），与调用失败可区分。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣在。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=offline_empty_audience_translate,
    )
    result = sess.scene_chat("边事如何？")
    assert result.answer == "臣在。"
    assert not any(
        f.get("category") == "translate_failed"
        for f in (result.pending_action_failures or [])
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


def _active_chat_turn(db, state, night_id: int) -> int:
    """建可撤回的存活轮（status=active；挂夜默认 generating 不可 undo）。"""
    return int(db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night_id), status="active",
    ))


def test_translation_pending_create_approve_reject_undo_via_real_chat_turn(
    game, monkeypatch,
):
    """源轮贯穿 scene_chat→转译链：pending 新增/应允/拒绝三向真 undo 可逆。

    不另造平行快照；ctid 下传 dispatch_declaration 入口自记前像（#1839 C2）。
    """
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )

    # ── 1) 新增：转译落 pending → undo 删行 ──
    ctid_create = _active_chat_turn(db, state, night_id)
    create_text = "着户部备陕西赈灾银UNIQUE-CREATE"
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [{"text": create_text}],
            "promises": [],
        },
    )
    r = sess.scene_chat("拟赈灾", chat_turn_id=ctid_create)
    assert r.pending_action_id == 0  # #1842：前台不等后台转译
    persist_and_schedule_scene(sess, db, r)
    sess._write_queue.barrier(lambda: None)
    created = db.conn.execute(
        "SELECT id FROM pending_actions WHERE payload_json LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{create_text}%",),
    ).fetchone()
    assert created is not None
    created_id = int(created["id"])
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=? AND status='pending'",
        (created_id,),
    ).fetchone()["n"] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM chat_turn_rollback_items WHERE chat_turn_id=?",
        (ctid_create,),
    ).fetchone()["n"] > 0
    db.undo_chat_turn(ctid_create)
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=?",
        (created_id,),
    ).fetchone()["n"] == 0

    # ── 2) 应允：night_approved 0→1 → undo 回 0 ──
    baseline = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "旧暂存待应允UNIQUE-APPROVE"}]},
        minister_name="", night_id=night_id,
    )
    approve_id = int(baseline.commissions.applied[0]["id"])
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 0

    ctid_approve = _active_chat_turn(db, state, night_id)
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [],
            "promises": [{"action_id": approve_id, "decision": "应允"}],
        },
    )
    r_approve = sess.scene_chat("准", chat_turn_id=ctid_approve)
    persist_and_schedule_scene(sess, db, r_approve)
    sess._write_queue.barrier(lambda: None)
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 1
    db.undo_chat_turn(ctid_approve)
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 0

    # ── 3) 拒绝：删 pending 行 → undo 复原 ──
    reject_base = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "旧暂存待拒绝UNIQUE-REJECT"}]},
        minister_name="", night_id=night_id,
    )
    reject_id = int(reject_base.commissions.applied[0]["id"])
    before_payload = db.conn.execute(
        "SELECT payload_json, kind, action, status FROM pending_actions WHERE id=?",
        (reject_id,),
    ).fetchone()
    assert before_payload is not None

    ctid_reject = _active_chat_turn(db, state, night_id)
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [],
            "promises": [{"action_id": reject_id, "decision": "拒绝"}],
        },
    )
    r_reject = sess.scene_chat("不准", chat_turn_id=ctid_reject)
    persist_and_schedule_scene(sess, db, r_reject)
    sess._write_queue.barrier(lambda: None)
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=?", (reject_id,),
    ).fetchone()["n"] == 0
    db.undo_chat_turn(ctid_reject)
    restored = db.conn.execute(
        "SELECT payload_json, kind, action, status FROM pending_actions WHERE id=?",
        (reject_id,),
    ).fetchone()
    assert restored is not None
    assert restored["status"] == before_payload["status"]
    assert restored["kind"] == before_payload["kind"]
    assert restored["action"] == before_payload["action"]
    assert restored["payload_json"] == before_payload["payload_json"]


def test_pure_office_dossier_uses_payload_text_not_template(game):
    """纯任免成案核消费 payload 原样 text，不拼「任命X为Y」模板。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    person = _hong_name(db, content)
    edict = f"  着以{person}巡抚陕西，专办边饷UNIQUE-OFFICE-TEXT\n"
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert len(staged.commissions.applied) == 1
    pa = staged.commissions.applied[0]
    assert pa["kind"] == "office"
    pending_id = int(pa["id"])
    payload = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
        ).fetchone()["payload_json"]
    )
    assert payload["text"] == edict

    db.mark_pending_night_approved([pending_id], night_id=night_id)
    close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)

    dossier = db.conn.execute(
        "SELECT decree_text, payload_json, action_type, status "
        "FROM decree_dossiers WHERE pending_action_id=? "
        "AND action_type='appointment' ORDER BY id DESC LIMIT 1",
        (pending_id,),
    ).fetchone()
    assert dossier is not None, "纯任免应收夜成 appointment 案卷"
    assert dossier["decree_text"] == edict
    template = f"任命{person}为陕西巡抚"
    assert dossier["decree_text"] != template
    dossier_payload = json.loads(dossier["payload_json"] or "{}")
    assert dossier_payload.get("text") == edict


def test_appointment_region_id_stages_into_pending_payload(game):
    """地方任命声明带 region_id 时原样进 office pending，不从官名推断。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    person = _hong_name(db, content)
    region = _region_id(db)
    edict = f"着以{person}巡抚陕西 UNIQUE-REGION-SEAT"
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": edict,
            "appointment": {
                "name": person,
                "office": "陕西巡抚",
                "appoint_action": "任命",
                "region_id": region,
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert len(staged.commissions.applied) == 1
    pa = staged.commissions.applied[0]
    assert pa["kind"] == "office"
    payload = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?",
            (int(pa["id"]),),
        ).fetchone()["payload_json"]
    )
    assert payload.get("region_id") == region
    assert payload.get("text") == edict


def test_scene_chat_translation_can_approve_staged_action(game, monkeypatch):
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

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "commissions": [],
            "promises": [{"action_id": staged_id, "decision": "应允"}],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn=translate_fn)
    # 用不会与规则段「准」混淆的皇帝原话
    sess.scene_chat("着即照办")

    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1
