"""#522 招抚：真实候选、案卷与既有 #190 人物变更纵切。"""

from types import SimpleNamespace
import json

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim import issues
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


def _ctx(db, character, candidates, turn):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message="招抚张献忠归顺朝廷。",
        reply="臣请招抚张献忠，归顺后授游击将军。",
        message_text="招抚张献忠归顺朝廷。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _stage_pacification(db, turn, target="张献忠"):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    candidate = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": target}, soft=False,
    )
    ctx = _ctx(db, actor, candidate, turn)
    run_materialize_pipeline(ctx)
    return ctx


def _activate_canonical_bandit(db, content, name="张献忠"):
    """Apply the production debut transition without rewriting power authority."""
    db.conn.execute("UPDATE characters SET status='active' WHERE name=?", (name,))
    content.characters[name].status = "active"
    db.conn.commit()


def _make_non_enemy(db, content, stance, name="张献忠", power_id="bandit_522"):
    db.conn.execute(
        """INSERT INTO powers
        (id,name,kind,leader,stance,leverage,satisfaction,military_strength,cohesion,
         supply,agenda,status,last_action,aliases)
        VALUES (?,?,'内乱',?,?,25,20,55,30,22,'招抚负向测试','小股啸聚','','[]')""",
        (power_id, "不可招抚测试股", name, stance),
    )
    db.conn.execute(
        "UPDATE characters SET power_id=?,status='active',office_type='外臣' WHERE name=?",
        (power_id, name),
    )
    ch = content.characters[name]
    ch.power_id, ch.status, ch.office_type = power_id, "active", "外臣"
    db.conn.commit()


def _prepare_ineligible_case(db, content, case):
    """Return (target, observe_person, observe_power_id) for one ineligible root."""
    if case == "foreign_enemy":
        return "皇太极", "皇太极", "houjin"
    if case == "same_faction_non_leader":
        db.conn.execute("UPDATE characters SET power_id='bandits' WHERE name='皇太极'")
        db.conn.commit()
        return "皇太极", "皇太极", "bandits"
    if case == "dead":
        _activate_canonical_bandit(db, content)
        db.conn.execute("UPDATE characters SET status='dead' WHERE name='张献忠'")
        db.conn.commit()
        return "张献忠", "张献忠", "bandit_zhang_xianzhong"
    if case == "unknown":
        _activate_canonical_bandit(db, content)
        return "并不存在的人", "张献忠", "bandit_zhang_xianzhong"
    if case in {"neutral", "pro_ming"}:
        stance = "中立" if case == "neutral" else "倾明"
        _make_non_enemy(db, content, stance)
        return "张献忠", "张献忠", "bandit_522"
    raise AssertionError(f"unknown ineligible case: {case}")


@pytest.mark.parametrize("target", ["李自成", "张献忠", "王嘉胤"])
def test_canonical_bandit_pacification_forms_proposed_dossier_without_world_effect(game, target):
    db, state, content = game
    _activate_canonical_bandit(db, content, target)
    before = dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name=?", (target,)
    ).fetchone())

    ctx = _stage_pacification(db, state.turn, target)
    assert ctx.out["pending_action_id"]
    db.commit_pending_actions(state, content=content)

    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    assert dossier["target_id"] == target
    assert dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name=?", (target,)
    ).fetchone()) == before, "成案前不得在 materializer 改世界"


def test_old_save_legacy_bandits_leader_admits_wang(game):
    """旧档 leader='王嘉胤等' 经 init_schema 规范化后，canonical 头目可成案且零世界效果。"""
    db, state, content = game
    db.conn.execute("UPDATE powers SET leader='王嘉胤等' WHERE id='bandits'")
    db.conn.commit()

    db.init_schema()
    assert db.conn.execute(
        "SELECT leader FROM powers WHERE id='bandits'"
    ).fetchone()["leader"] == "王嘉胤"

    wang_before = dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='王嘉胤'"
    ).fetchone())
    ctx = _stage_pacification(db, state.turn, "王嘉胤")
    assert ctx.out["pending_action_id"]
    db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    assert dossier["target_id"] == "王嘉胤"
    assert dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='王嘉胤'"
    ).fetchone()) == wang_before


@pytest.mark.parametrize(
    "case",
    [
        "foreign_enemy",
        "same_faction_non_leader",
        "dead",
        "unknown",
        "neutral",
        "pro_ming",
    ],
)
def test_pacification_rejects_ineligible_targets_without_world_effect(game, case):
    """真实入口→commit 失败→无案卷→观察人物/势力零世界效果；覆盖敌国/同股非首领/死亡/未知/中立/倾明。"""
    db, state, content = game
    target, person, power_id = _prepare_ineligible_case(db, content, case)
    person_before = dict(db.conn.execute(
        "SELECT * FROM characters WHERE name=?", (person,)
    ).fetchone())
    power_before = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id=?", (power_id,)
    ).fetchone())

    ctx = _stage_pacification(db, state.turn, target)
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    assert db.commit_pending_actions(state, content=content) == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["status"] == "failed"
    assert not [d for d in db.list_decree_dossiers()
                if d["action_type"] == "pacification"]
    assert dict(db.conn.execute(
        "SELECT * FROM characters WHERE name=?", (person,)
    ).fetchone()) == person_before
    assert dict(db.conn.execute(
        "SELECT * FROM powers WHERE id=?", (power_id,)
    ).fetchone()) == power_before


@pytest.mark.parametrize("decision", ["rejected", "promulgated"])
def test_pacification_verdict_controls_existing_190_effect_path(game, decision):
    """顺颁经 ADR 0055 物化接缝自动交 #190 易主；打回零效果。不得手工注入人物变更。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    power_before = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone())
    ctx = _stage_pacification(db, state.turn)
    db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    verdict = ({"dossier_id": dossier["id"], "decision": "promulgated"}
               if decision == "promulgated" else _rejected_verdict(dossier["id"]))
    db.apply_dossier_verdicts(state, [verdict], content=content)

    row = db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone()
    power_after = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone())
    if decision == "promulgated":
        assert row["power_id"] == "ming"
        assert row["office"] == "归附"
        # 顺颁反噬须按 #190 给目标原势力真实失方削弱并落账（非空对象）。
        assert power_after["id"] == power_before["id"]
        expected_strength = max(0, int(power_before["military_strength"]) - 1)
        assert int(power_after["military_strength"]) == expected_strength
        log = db.conn.execute(
            "SELECT field, delta, reason, origin_ref FROM power_logs "
            "WHERE power_id=? AND field='military_strength' "
            "ORDER BY id DESC LIMIT 1",
            ("bandit_zhang_xianzhong",),
        ).fetchone()
        assert log is not None
        assert int(log["delta"]) == expected_strength - int(power_before["military_strength"])
        assert "受抚" in str(log["reason"] or "")
        assert str(log["origin_ref"] or "").startswith("dossier:")
    else:
        assert dict(row) == before
        assert power_after == power_before


@pytest.mark.parametrize(
    ("classified", "draft_payload", "expected"),
    [
        ({"kind": "pacification", "target_id": "张献忠"}, None, "pacification"),
        ({"kind": "draft"}, {
            "dossier_action_type": "punishment", "target_kind": "character",
        }, "punishment"),
        ({"kind": "draft"}, {
            "dossier_action_type": "military_order", "target_kind": "region",
            "target_id": "shaanxi", "deadline_months": 3,
        }, "military_order"),
    ],
    ids=["pacification", "punishment", "military_order"],
)
def test_scripted_action_classes_are_mutually_exclusive(
    game, monkeypatch, classified, draft_payload, expected,
):
    """三类均由 #515 判词入口消费，并只交给本类既有 owner。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = dict(draft_payload or {})
    payload.setdefault("target_id", actor)
    payload.setdefault("assignee", actor)
    monkeypatch.setattr(
        "ming_sim.cli_backend.extract_draft_intent",
        lambda *a, **k: {
            "draft_action": "拟旨", "draft_text": "脚本化旨稿",
            "target_candidate": "", **payload,
        },
    )
    candidates = candidates_from_classifier_payload(classified, soft=False)
    ctx = _ctx(db, actor, candidates, state.turn)
    run_materialize_pipeline(ctx)

    pending_id = ctx.out["pending_action_id"]
    pending_payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["payload_json"])
    assert pending_payload["dossier_action_type"] == expected
    assert db.commit_pending_actions(state, content=content)
    produced = [d["action_type"] for d in db.list_decree_dossiers()]
    assert produced == [expected]
    assert all(produced.count(kind) == (1 if kind == expected else 0)
               for kind in ("pacification", "punishment", "military_order"))


def _promulgate_pacification(db, state, content, target="张献忠"):
    _activate_canonical_bandit(db, content, target)
    ctx = _stage_pacification(db, state.turn, target)
    db.commit_pending_actions(state, content=content)
    dossier = next(
        d for d in db.list_decree_dossiers(status="proposed")
        if d["action_type"] == "pacification" and d["target_id"] == target
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}], content=content,
    )
    return dossier


def _yi_zhu_item(name, origin, *, power_id):
    return {
        "name": name,
        "origin_ref": origin,
        "动作": "易主",
        "new_power": "ming",
        "方式": "主动归附",
        "反噬": {power_id: {"military_strength": -1, "reason": "受抚"}},
        "reason": "受抚归明",
    }


def test_pacification_effect_rejects_mismatched_target_binds_canonical(game):
    """C1：招抚案卷只可易主 canonical target；顺颁自动易主绑定 target，错配拒、其它 origin 不变。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "李自成")
    li_before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone())
    zhang_before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    assert zhang_before["power_id"] != "ming"

    dossier = _promulgate_pacification(db, state, content, "张献忠")
    origin = f"dossier:{dossier['id']}"

    # 顺颁自动物化：仅 canonical target 易主
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name='张献忠'"
    ).fetchone()["power_id"] == "ming"
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone()) == li_before

    crossed = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("李自成", origin, power_id="bandit_li_zicheng"),
    ]}, content=content)
    crossed_row = next(
        x for x in crossed["applied_person_changes"] if x.get("name") == "李自成"
    )
    assert crossed_row.get("rejected"), "错配目标不得借招抚案卷易主"
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone()) == li_before

    # 盘面自发仍可走既有 #190 路径（非案卷 origin 不受本绑定约束）
    _activate_canonical_bandit(db, content, "李自成")
    db.conn.execute(
        "UPDATE characters SET power_id='bandit_li_zicheng', office='流寇首领' WHERE name='李自成'"
    )
    db.conn.commit()
    content.characters["李自成"].power_id = "bandit_li_zicheng"
    spontaneous = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("李自成", "盘面自发", power_id="bandit_li_zicheng"),
    ]}, content=content)
    spont_row = next(
        x for x in spontaneous["applied_person_changes"] if x.get("name") == "李自成"
    )
    assert not spont_row.get("rejected")


@pytest.mark.parametrize(
    ("player_message", "intent_mode", "expected_mode"),
    [
        ("中旨直发招抚张献忠归顺朝廷。", None, "midzhi"),
        ("招抚张献忠归顺朝廷。", None, "ordinary"),
        ("招抚张献忠归顺朝廷。", "midzhi", "midzhi"),
    ],
    ids=["emperor_midzhi", "ordinary_default", "classifier_mode"],
)
def test_pacification_preserves_declared_mode(game, player_message, intent_mode, expected_mode):
    """C2：招抚候选保留皇帝/classifier 声明的颁布方式。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    raw = {"kind": "pacification", "target_id": "张献忠"}
    if intent_mode is not None:
        raw["mode"] = intent_mode
    candidates = candidates_from_classifier_payload(raw, soft=False)
    ctx = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message=player_message,
        reply="臣请招抚张献忠，归顺后授游击将军。",
        message_text=player_message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )
    run_materialize_pipeline(ctx)
    pending_id = ctx.out["pending_action_id"]
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["payload_json"])
    assert payload.get("mode") == expected_mode
    assert db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers() if d["action_type"] == "pacification")
    assert dossier["mode"] == expected_mode


def test_pacification_update_preserves_existing_mode(game):
    """C2/C4：同目标修订保留既有 mode，不因补充句无声明而掉 ordinary。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    first = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": "张献忠", "mode": "midzhi"}, soft=False,
    )
    ctx1 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="中旨直发招抚张献忠。",
        reply="臣请招抚张献忠。",
        message_text="中旨直发招抚张献忠。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=first,
    )
    run_materialize_pipeline(ctx1)
    pending_id = ctx1.out["pending_action_id"]
    pending_row = db.conn.execute(
        "SELECT id, payload_json, kind, minister_name FROM pending_actions WHERE id=?",
        (pending_id,),
    ).fetchone()
    pend = [dict(pending_row)]
    second = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": "张献忠"}, soft=False,
    )
    ctx2 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="再补：授游击将军。",
        reply="臣再请授游击将军。",
        message_text="再补：授游击将军。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend, out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=second,
    )
    run_materialize_pipeline(ctx2)
    rows = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
    ]
    assert len(rows) == 1
    assert int(rows[0]["id"]) == int(pending_id)
    payload = json.loads(rows[0]["payload_json"])
    assert payload["mode"] == "midzhi"
    assert "游击" in payload["text"] or "游击" in ctx2.reply


def test_pacification_same_target_updates_candidate_different_target_independent(game):
    """C4：同大臣同目标未确认招抚更新既有行；异目标独立。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    _activate_canonical_bandit(db, content, "李自成")
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    ctx_a = _ctx(
        db, actor,
        candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "张献忠"}, soft=False,
        ),
        state.turn,
    )
    run_materialize_pipeline(ctx_a)
    first_id = ctx_a.out["pending_action_id"]
    pend = list(db.list_pending_actions(state.turn, minister_name=actor))

    ctx_a2 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="招抚张献忠，再许免死。",
        reply="臣请招抚张献忠并许免死。",
        message_text="招抚张献忠，再许免死。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend, out={},
        intent=None, intent_kind="none", llm_config=None,
        intent_candidates=candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "张献忠"}, soft=False,
        ),
    )
    run_materialize_pipeline(ctx_a2)
    same_target = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
        and json.loads(r["payload_json"]).get("dossier_action_type") == "pacification"
        and json.loads(r["payload_json"]).get("target_id") == "张献忠"
    ]
    assert len(same_target) == 1
    assert int(same_target[0]["id"]) == int(first_id)
    assert "免死" in json.loads(same_target[0]["payload_json"])["text"]

    pend2 = list(db.list_pending_actions(state.turn, minister_name=actor))
    ctx_b = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="另旨招抚李自成。",
        reply="臣另请招抚李自成。",
        message_text="另旨招抚李自成。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend2, out={},
        intent=None, intent_kind="none", llm_config=None,
        intent_candidates=candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "李自成"}, soft=False,
        ),
    )
    run_materialize_pipeline(ctx_b)
    pac_rows = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
        and json.loads(r["payload_json"]).get("dossier_action_type") == "pacification"
    ]
    targets = {json.loads(r["payload_json"])["target_id"] for r in pac_rows}
    assert targets == {"张献忠", "李自成"}
    assert len(pac_rows) == 2


def test_api_tool_propose_directive_stages_pacification_with_admission(game):
    """C3：API propose_directive 与 CLI 同构进招抚准入；非法对象拒绝。"""
    from ming_sim.session import GameSession

    db, state, content = game
    _activate_canonical_bandit(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    class Agent:
        def __init__(self, text):
            self._text = text

        def run(self, _message):
            return SimpleNamespace(
                content="臣已拟招抚之旨，请陛下定夺。",
                tools=[SimpleNamespace(
                    tool_name="propose_directive",
                    result="",
                    arguments={"decree_text": self._text},
                )],
            )

    class Registry:
        def __init__(self, agent):
            self._agent = agent

        def get(self, _character):
            return self._agent

        def build_draft_line(self):
            return "无"

    def _api_session(agent):
        sess = GameSession.__new__(GameSession)
        sess.db = db
        sess.state = state
        sess.content = content
        sess.registry = Registry(agent)
        sess.llm_config = SimpleNamespace(channel="api")
        sess.temporary_characters = set()
        sess._audience_prompt_for_message = lambda message, *a, **k: message
        sess._start_cli_action_intent = lambda *_a, **_k: None
        sess._finish_cli_action_intent = lambda *_a, **_k: None
        return sess

    ok_sess = _api_session(Agent("着招抚张献忠归顺朝廷，授游击将军。"))
    result = GameSession.chat(ok_sess, minister, "中旨直发，招抚张献忠。")
    assert result.pending_action_id
    pending = [
        p for p in db.list_pending_actions(state.turn, minister_name=minister)
        if int(p["id"]) == int(result.pending_action_id)
    ][0]
    payload = json.loads(pending["payload_json"])
    assert payload["dossier_action_type"] == "pacification"
    assert payload["target_id"] == "张献忠"
    assert payload.get("mode") == "midzhi"
    assert db.commit_pending_actions(state, content=content, minister_name=minister)
    dossier = next(d for d in db.list_decree_dossiers() if d["action_type"] == "pacification")
    assert dossier["target_id"] == "张献忠"
    assert dossier["mode"] == "midzhi"

    # 非法对象：敌国首领零合格 → 解析期 fail-loud，不入档、不降级 special_decree
    bad_before = list(db.list_decree_dossiers())
    before_pending = _pending_directive_payloads(db, state.turn, minister)
    bad_sess = _api_session(Agent("着招抚皇太极归顺朝廷。"))
    bad_result = GameSession.chat(bad_sess, minister, "招抚皇太极。")
    assert not bad_result.pending_action_id
    assert bad_result.pending_action_failures
    assert all("招抚" in str(f.get("message") or "") for f in bad_result.pending_action_failures)
    after_pending = _pending_directive_payloads(db, state.turn, minister)
    assert after_pending == before_pending
    assert not any(
        p.get("dossier_action_type") in {"special_decree", "pacification"}
        for _, p in after_pending
    )
    assert list(db.list_decree_dossiers()) == bad_before


def _directive_session(db, state, content):
    """Minimal session bound to the API/stream shared staging seam."""
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    return sess


def _pending_directive_payloads(db, turn, minister):
    rows = [
        p for p in db.list_pending_actions(turn, minister_name=minister)
        if p.get("kind") == "directive" and p.get("status") == "pending"
    ]
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        out.append((int(row["id"]), payload if isinstance(payload, dict) else {}))
    return out


def test_api_tool_pacification_unknown_target_fails_loud_not_special_decree(game):
    """C3 r2：招抚 cue 命中但目标未知 → fail-loud，不得降级 special_decree。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    before = _pending_directive_payloads(db, state.turn, minister)
    failures = []

    pending_id = sess._stage_directive_tool_candidate(
        "着招抚流寇归顺朝廷，授游击将军。",
        minister,
        "中旨直发，着即招抚。",
        failures_out=failures,
    )

    assert pending_id == 0
    assert failures, "未知目标须经 pending_action_failures 显式诊断"
    assert all("招抚" in str(f.get("message") or "") for f in failures)
    after = _pending_directive_payloads(db, state.turn, minister)
    assert after == before
    assert not any(
        p.get("dossier_action_type") == "special_decree" for _, p in after
    )


def test_api_tool_pacification_ambiguous_target_fails_loud_not_special_decree(game):
    """C3 r2：招抚 cue 命中但同长多目标歧义 → fail-loud，不得降级 special_decree。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    _activate_canonical_bandit(db, content, "李自成")
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    before = _pending_directive_payloads(db, state.turn, minister)
    failures = []

    pending_id = sess._stage_directive_tool_candidate(
        "着招抚张献忠与李自成归顺朝廷。",
        minister,
        "中旨直发，招抚张献忠李自成。",
        failures_out=failures,
    )

    assert pending_id == 0
    assert failures, "歧义目标须经 pending_action_failures 显式诊断"
    assert all("招抚" in str(f.get("message") or "") for f in failures)
    after = _pending_directive_payloads(db, state.turn, minister)
    assert after == before
    assert not any(
        p.get("dossier_action_type") in {"special_decree", "pacification"}
        for _, p in after
    )


def test_pacification_unequal_length_dual_names_are_ambiguous(game):
    """不等长双名：张献忠(3)与闯将(2→李自成)须歧义，不得因最长匹配吞掉较短名。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    _activate_canonical_bandit(db, content, "李自成")
    assert "闯将" in (content.characters["李自成"].aliases or [])
    sess = _directive_session(db, state, content)

    assert sess._mentioned_pacification_target("招抚张献忠与闯将归顺") is None

    failures = []
    pending_id = sess._stage_directive_tool_candidate(
        "着招抚张献忠与闯将归顺朝廷。",
        db.conn.execute(
            "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
        ).fetchone()["name"],
        "招抚张献忠与闯将。",
        failures_out=failures,
    )
    assert pending_id == 0
    assert failures


def test_pacification_nested_alias_same_canonical_resolves(game):
    """同一 canonical 的嵌套别名（八大王⊂张献忠语境）最长匹配只消歧别名，不构成多目标。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    assert "八大王" in (content.characters["张献忠"].aliases or [])
    sess = _directive_session(db, state, content)
    assert sess._mentioned_pacification_target("着招抚八大王张献忠归顺") == "张献忠"


def test_pacification_unqualified_name_does_not_create_false_ambiguity(game):
    """C1 r5：非合格奏疏人名不得计为歧义；仅合格自新内乱头目参与聚合。

    张献忠(合格) + 杨嗣昌(明臣非合格) → 保留张献忠暂存，不 fail-loud。
    """
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    assert "杨嗣昌" in content.characters
    assert db._find_pacification_target(content, "杨嗣昌") is None
    assert db._find_pacification_target(content, "张献忠") == "张献忠"
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)

    assert sess._mentioned_pacification_target(
        "着杨嗣昌议，招抚张献忠归顺朝廷。"
    ) == "张献忠"

    failures = []
    pending_id = sess._stage_directive_tool_candidate(
        "着招抚张献忠归顺朝廷，授游击将军。",
        minister,
        "着杨嗣昌议，招抚张献忠。",
        failures_out=failures,
    )
    assert pending_id > 0
    assert not failures
    payloads = _pending_directive_payloads(db, state.turn, minister)
    staged = [p for _, p in payloads if p.get("dossier_action_type") == "pacification"]
    assert len(staged) == 1
    assert staged[0].get("target_id") == "张献忠"
    assert not any(
        p.get("dossier_action_type") == "special_decree" for _, p in payloads
    )


def test_api_tool_pacification_failure_diagnostic_reaches_chat_and_web_stream(game):
    """显式诊断须到非流式 ChatTurnResult 与 web stream payload 两通道。"""
    from ming_sim.session import GameSession
    import web_app

    db, state, content = game
    _activate_canonical_bandit(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已拟招抚之旨。",
                tools=[SimpleNamespace(
                    tool_name="propose_directive",
                    result="",
                    arguments={"decree_text": "着招抚流寇归顺朝廷。"},
                )],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None

    result = GameSession.chat(sess, minister, "中旨直发，着即招抚。")
    assert result.pending_action_id == 0
    assert result.pending_action_failures
    assert any("招抚" in str(f.get("message") or "") for f in result.pending_action_failures)

    # web stream 与 session 共用 _stage_directive_tool_candidate；经 commit 缝透出 failures。
    web_game = web_app.WebGame.__new__(web_app.WebGame)
    web_game.session = sess
    web_game.chat_history = {name: [] for name in content.characters}
    web_game.suggestions_for = lambda _character: []
    web_game.chat_projection = lambda name: list(web_game.chat_history.get(name) or [])
    web_game.directive_rows = lambda: []
    web_game.directive_payload = lambda row: row
    web_game.can_undo_last_chat = lambda _name: False
    web_game._record_chat_rollback_items = lambda *_a, **_k: None
    character = content.characters[minister]
    run_output = Agent().run("")
    payload = web_app.WebGame._chat_stream_payload_commit(
        web_game,
        minister,
        "中旨直发，着即招抚。",
        character,
        "臣已拟招抚之旨。",
        run_output,
        None,
        chat_turn_id=0,
        before_snapshot={
            "pending_action_ids": [],
            "secret_order_ids": [],
            "directive_ids": [],
        },
        accepted_turn=state.turn,
    )
    assert payload.get("pending_action_id") in (0, None)
    assert payload.get("pending_action_failures")
    assert any(
        "招抚" in str(f.get("message") or "")
        for f in payload["pending_action_failures"]
    )


def test_special_decree_origin_cannot_authorize_pacification_allegiance(game):
    """C3：generic special_decree 不得授权招抚式易主。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    dossier_id = db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text="着从权处置流寇。",
        target_kind="policy",
        target_id="narrative-special",
        payload={"mode": "ordinary", "text": "着从权处置流寇。"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")
    applied = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("张献忠", f"dossier:{dossier_id}", power_id="bandit_zhang_xianzhong"),
    ]}, content=content)
    row = next(x for x in applied["applied_person_changes"] if x.get("name") == "张献忠")
    assert row.get("rejected")
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone()) == before
