import json
import threading
from types import SimpleNamespace

import pytest

from ming_sim import cli_backend
from ming_sim.session import GameSession
from ming_sim.skills import bind_content as bind_skills_content
from web_app import WebGame


def _make_dossier(db, state, text):
    return db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text=text,
        target_kind="policy",
        target_id=text,
    )


def test_one_protection_dossier_links_three_older_allocations_both_directions(game):
    db, state, _ = game
    targets = [_make_dossier(db, state, name) for name in ("辽东补饷", "宣大补饷", "东江补饷")]
    protection = _make_dossier(db, state, "密令护行三路饷银")

    db.add_dossier_links(
        protection,
        [{"target_dossier_id": target, "relation_type": "护卫", "note": "护送该路饷银"}
         for target in targets],
    )

    assert [row["target_dossier_id"] for row in db.list_dossier_links(protection)] == targets
    assert [db.list_dossier_links(target, direction="incoming")[0]["source_dossier_id"]
            for target in targets] == [protection] * 3
    assert all("status" not in row for row in db.list_dossier_links(protection))


def test_only_confirmed_narrowed_references_are_persisted(game):
    db, state, _ = game
    liaodong = _make_dossier(db, state, "辽东补饷")
    xuanda = _make_dossier(db, state, "宣大补饷")
    protection = _make_dossier(db, state, "只确认护卫辽东")

    db.add_dossier_links(
        protection,
        [{"target_dossier_id": liaodong, "relation_type": "护卫", "note": "确认只护辽东"}],
    )

    assert [row["target_dossier_id"] for row in db.list_dossier_links(protection)] == [liaodong]
    assert db.list_dossier_links(xuanda, direction="incoming") == []


def test_secret_order_extractor_only_carries_explicit_confirmed_dossier_ids(monkeypatch):
    extracted = {
        "标题": "护行三路饷银",
        "内容": "护卫辽东、宣大、东江三份补饷案卷。",
        "承办人": "孙承宗",
        "期限月数": 1,
        "标签": ["护饷"],
        "排除对象": {"人物": [], "机构": []},
        "案卷关联": [
            {"目标案卷ID": 11, "类型": "护卫", "说明": "护送辽东饷银"},
            {"目标案卷ID": 12, "类型": "护卫", "说明": "护送宣大饷银"},
            {"目标案卷ID": "模糊的东江案", "类型": "护卫", "说明": "未钉死"},
        ],
    }
    def run_extractor(*args, **kwargs):
        value = ({"confirmed_links": [{"target_dossier_id": 11, "relation_type": "护卫"}, {"target_dossier_id": 12, "relation_type": "护卫"}]}
                 if kwargs.get("tag") == "dossier_link_confirmation" else extracted)
        return json.dumps(value, ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "_run_json_extractor_for_config", run_extractor)

    result = cli_backend._extract_secret_order(
        "护卫边军饷银", "臣领命：只护辽东补饷、宣大补饷。", "孙承宗",
        dossier_candidates=[
            {"id": 11, "decree_text": "辽东补饷"},
            {"id": 12, "decree_text": "宣大补饷"},
            {"id": 13, "decree_text": "东江补饷"},
        ],
    )

    assert [link["target_dossier_id"] for link in result["dossier_links"]] == [11, 12]


@pytest.mark.parametrize("reply", [
    "臣不能确认护卫辽东补饷。",
    "臣只是引述旧案辽东补饷，并未承诺关联。",
    "臣会照看那份饷案。",
    "臣确认护卫辽东补饷补充。",
])
def test_semantic_verdict_rejects_negative_quote_vague_and_containment(monkeypatch, reply):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": []}), 1),
    )
    links = cli_backend.confirm_dossier_links(
        reply,
        [{"id": 11, "decree_text": "辽东补饷"},
         {"id": 12, "decree_text": "辽东补饷补充"}],
        [{"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"},
         {"target_dossier_id": 12, "relation_type": "护卫", "note": "护送补充案"}],
    )
    assert links == []


@pytest.mark.parametrize("verdict", [
    {"confirmed_ids": [True]},
    {"confirmed_ids": [{"id": 11}]},
    {"confirmed_ids": "11"},
    {"confirmed_ids": {"id": 11}},
    {},
    [11],
])
def test_semantic_verdict_bad_shape_fails_closed_without_crashing(monkeypatch, verdict):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps(verdict), 1),
    )

    assert cli_backend.confirm_dossier_links(
        "臣明确确认护卫辽东补饷。",
        [{"id": 11, "decree_text": "辽东补饷"}],
        [{"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"}],
    ) == []


def test_semantic_verdict_can_narrow_to_exactly_one_proposed_candidate(monkeypatch):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": [{"target_dossier_id": 12, "relation_type": "接应"}, {"target_dossier_id": 999, "relation_type": "接应"}]}), 1),
    )
    links = cli_backend.confirm_dossier_links(
        "臣明确确认接应辽东补饷补充案。",
        [{"id": 11, "decree_text": "辽东补饷"},
         {"id": 12, "decree_text": "辽东补饷补充"}],
        [{"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"},
         {"target_dossier_id": 12, "relation_type": "接应", "note": "接应补充案"}],
    )
    assert links == [{"target_dossier_id": 12, "relation_type": "接应", "note": "接应补充案"}]


def test_secret_order_extractor_rejects_model_id_outside_visible_candidates(monkeypatch):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({
            "内容": "护送旧案", "案卷关联": [
                {"目标案卷ID": 99, "类型": "护卫", "说明": "模型臆造"}
            ]
        }, ensure_ascii=False), 1),
    )

    result = cli_backend._extract_secret_order(
        "护送旧案", "臣领命，护卫虚构旧旨。", "孙承宗",
        dossier_candidates=[{"id": 11, "decree_text": "辽东补饷"}],
    )

    assert result["dossier_links"] == []


def test_reference_candidates_hide_other_ministers_secret_dossiers(game):
    db, state, _ = game
    draft_id = _make_dossier(db, state, "尚未明发饷案")
    public_id = _make_dossier(db, state, "公开饷案")
    db.record_dossier_decision(public_id, "promulgated")
    other_order = db.create_secret_order(state, "卢象升", "密查", "不可外泄", [])
    other_secret = db.get_dossier_for_secret_order(other_order)

    visible = db.list_referenceable_dossiers("孙承宗", state.turn)

    visible_ids = {row["id"] for row in visible}
    assert public_id in visible_ids
    assert draft_id not in visible_ids
    assert other_secret["id"] not in visible_ids
    assert other_secret["id"] in {
        row["id"] for row in db.list_referenceable_dossiers("卢象升", state.turn)
    }


def test_reference_candidates_obey_canonical_disclosure_blacklist(game):
    from ming_sim.knowledge import knowledge_row_visible_to

    db, state, _ = game
    order_id = db.create_secret_order(state, "卢象升", "密查辽饷", "不可外泄", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    source_id = f"secret_order_disclosure:{order_id}:test"
    db.record_public_knowledge_event(
        state, "密查辽饷已披露", source_id=source_id, excluded_names=["孙承宗"])
    event = db.conn.execute(
        "SELECT * FROM character_knowledge_events WHERE source_id=?", (source_id,)
    ).fetchone()

    assert knowledge_row_visible_to(db, event, "孙承宗") is False
    assert dossier["id"] not in {
        row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)
    }


@pytest.mark.parametrize("confirmed_ids, expected", [
    ("target", True), ([], False), ([{"target_dossier_id": True, "relation_type": "护卫"}], False), ([{"id": 1}], False),
])
def test_real_api_session_tool_path_commits_only_semantically_confirmed_link(
    game, monkeypatch, confirmed_ids, expected,
):
    db, state, content = game
    target = _make_dossier(db, state, "辽东补饷")
    db.record_dossier_decision(target, "promulgated")
    minister = "毕自严"
    payload = json.dumps({
        "title": "护行辽饷", "content": "护送辽饷", "assignee": minister,
        "dossier_links": [{"target_dossier_id": target, "relation_type": "护卫", "note": "护送"}],
    }, ensure_ascii=False)
    verdict_ids = [target] if confirmed_ids == "target" else confirmed_ids
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": ([{"target_dossier_id": target, "relation_type": "护卫"}] if verdict_ids == [target] else verdict_ids)}), 1),
    )

    class Agent:
        def run(self, _message):
            answer = "臣明确确认护卫辽东补饷。" if expected else "臣不能确认护卫辽东补饷。"
            return SimpleNamespace(
                content=answer,
                tools=[SimpleNamespace(tool_name="secret_order", result=f"__secret_order__{payload}")],
            )

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = SimpleNamespace(get=lambda _character: Agent(), build_draft_line=lambda: "无")
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message, *_args, **_kwargs: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "下密令护行辽饷。")
    db.commit_pending_actions(state, action_ids=[result.pending_action_id])
    order = db.list_secret_orders(minister_name=minister)[0]
    source = db.get_dossier_for_secret_order(order["id"])
    assert bool(db.list_dossier_links(source["id"])) is expected


@pytest.mark.parametrize("confirmed_ids, expected", [
    ("target", True), (None, False), ([{"target_dossier_id": True, "relation_type": "护卫"}], False), ([{"id": 1}], False),
])
def test_real_cli_materialize_path_commits_only_semantically_confirmed_link(
    game, monkeypatch, confirmed_ids, expected,
):
    db, state, content = game
    target = _make_dossier(db, state, "辽东补饷")
    db.record_dossier_decision(target, "promulgated")
    extracted = {
        "标题": "护行辽饷", "内容": "护送辽饷", "承办人": "毕自严",
        "案卷关联": [{"目标案卷ID": target, "类型": "护卫", "说明": "护送"}],
    }
    def runner(*args, **kwargs):
        ids = [target] if confirmed_ids == "target" else (confirmed_ids or [])
        value = ({"confirmed_links": ([{"target_dossier_id": target, "relation_type": "护卫"}] if ids == [target] else ids)}
                 if kwargs.get("tag") == "dossier_link_confirmation" else extracted)
        return json.dumps(value, ensure_ascii=False), 1
    monkeypatch.setattr(cli_backend, "_run_json_extractor_for_config", runner)
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = SimpleNamespace(refresh=lambda _name: None)
    sess.llm_config = SimpleNamespace(channel="cli")

    result = sess.apply_cli_conversation_actions(
        SimpleNamespace(name="毕自严", office_type="户部"),
        "密令：护行辽饷。",
        "臣明确确认护卫辽东补饷。" if expected else "臣不能确认护卫辽东补饷。",
        has_directive=False, secret_order_id=None,
    )
    db.commit_pending_actions(state, action_ids=[result["pending_action_id"]])
    order = db.list_secret_orders(minister_name="毕自严")[0]
    source = db.get_dossier_for_secret_order(order["id"])
    assert bool(db.list_dossier_links(source["id"])) is expected


@pytest.mark.parametrize("proposal, verdict, expected", [
    (lambda target: {"target_dossier_id": target, "relation_type": "护卫", "note": "护送"},
     lambda target: [{"target_dossier_id": target, "relation_type": "护卫"}], True),
    (lambda target: {"target_dossier_id": target, "relation_type": "护卫", "note": "护送"},
     lambda _target: [], False),
    (lambda target: {"target_dossier_id": target, "relation_type": "越权", "note": "坏类型"},
     lambda target: [{"target_dossier_id": target, "relation_type": "越权"}], False),
    (lambda _target: {"target_dossier_id": 999999, "relation_type": "护卫", "note": "不可见"},
     lambda _target: [{"target_dossier_id": 999999, "relation_type": "护卫"}], False),
    (lambda target: {"target_dossier_id": float(target), "relation_type": "护卫", "note": "浮点截断"},
     lambda target: [{"target_dossier_id": target, "relation_type": "护卫"}], False),
    (lambda target: {"target_dossier_id": target, "relation_type": "护卫", "note": "   "},
     lambda target: [{"target_dossier_id": target, "relation_type": "护卫"}], False),
])
def test_real_web_stream_pending_commit_traces_only_confirmed_visible_links(
    game, monkeypatch, proposal, verdict, expected,
):
    db, state, content = game
    target = _make_dossier(db, state, "辽东补饷")
    db.record_dossier_decision(target, "promulgated")
    minister = "毕自严"
    payload = json.dumps({
        "title": "护行辽饷", "content": "护送辽饷", "assignee": minister,
        "dossier_links": [proposal(target)],
    }, ensure_ascii=False)

    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": verdict(target)}, ensure_ascii=False), 1),
    )

    class RunOutput:
        def __init__(self):
            self.content = None
            self.tools = [
                SimpleNamespace(tool_name="secret_order", result=f"__secret_order__{payload}")]

    class Agent:
        def run(self, *_args, **_kwargs):
            yield SimpleNamespace(event="RunContent", content="臣明确确认护卫辽东补饷。")
            yield RunOutput()

    class Session:
        llm_config = SimpleNamespace(channel="api")
        temporary_characters = set()

        def __init__(self):
            self.db, self.state, self.content = db, state, content
            self.registry = SimpleNamespace(
                get=lambda _character: Agent(), refresh=lambda _name: None, session_ids={})

        def _character(self, name):
            return self.content.characters[name]

        def _start_cli_action_intent(self, *_args):
            return None

        def _finish_cli_action_intent(self, *_args):
            return None

        def _confirmation_intent_for_preexisting_pending(self, *args, **kwargs):
            return GameSession._confirmation_intent_for_preexisting_pending(self, *args, **kwargs)

        def apply_cli_conversation_actions(self, *_args, **_kwargs):
            return {"directive": None, "secret_order_id": None, "pending_action_id": 0}

        def _merge_staged_new_secret_order_content(self, *args, **kwargs):
            return GameSession._merge_staged_new_secret_order_content(self, *args, **kwargs)

        def pending_count(self):
            return 0

        def list_directives(self, include_pending=True):
            # WebGame.directive_rows 唯一权威：委托真 GameSession 过滤（含 dossier 剔除）。
            return GameSession.list_directives(self, include_pending=include_pending)

    bind_skills_content(content)
    runtime = WebGame.__new__(WebGame)
    runtime.session = Session()
    runtime.chat_history = {name: [] for name in content.characters}
    runtime.suggestions_for = lambda _character: []
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
    runtime._draining = False
    runtime._trail_extraction_after_reply = lambda *_args, **_kwargs: None
    runtime._trail_mindreading_after_reply = lambda *_args, **_kwargs: None

    events = list(runtime.chat_stream(minister, "下密令护行辽饷。"))
    assert not [event for event in events if event["type"] == "error"], events
    done = next(event for event in events if event["type"] == "done")
    pending_id = done["payload"]["pending_action_id"]
    applied = db.commit_pending_actions(state, action_ids=[pending_id])

    assert [item["id"] for item in applied] == [pending_id]
    assert db.list_pending_actions(state.turn, status="failed") == []
    order = db.list_secret_orders(minister_name=minister)[0]
    source = db.get_dossier_for_secret_order(order["id"])
    assert bool(db.list_dossier_links(source["id"])) is expected


def test_confirmed_secret_order_materializes_links_through_pending_commit(game):
    db, state, _ = game
    targets = [_make_dossier(db, state, name) for name in ("辽东补饷", "宣大补饷", "东江补饷")]
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "护行三路饷银", "content": "密护三路饷银", "assignee": "孙承宗",
         "dossier_links": [
             {"target_dossier_id": target, "relation_type": "护卫", "note": "护送该路饷银"}
             for target in targets
         ]},
    )

    applied = db.commit_pending_actions(state, action_ids=[action_id])

    assert [row["id"] for row in applied] == [action_id]
    order = db.list_secret_orders(minister_name="孙承宗")[0]
    dossier = db.get_dossier_for_secret_order(order["id"])
    assert [row["target_dossier_id"] for row in db.list_dossier_links(dossier["id"])] == targets


def test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited(game):
    db, state, _ = game
    before_orders = len(db.list_secret_orders())
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "护行密令", "content": "护送旧案", "assignee": "孙承宗",
         "dossier_links": [
             {"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}
         ]},
    )

    assert db.commit_pending_actions(state, action_ids=[action_id]) == []

    assert len(db.list_secret_orders()) == before_orders
    assert db.list_pending_actions(state.turn, status="failed")[0]["id"] == action_id
    audit = db.list_dossier_link_rejections(pending_action_id=action_id)
    assert audit[-1]["target_dossier_id"] == 999999
    assert "指向不存在案卷" in audit[-1]["reason"]


def test_unknown_target_link_is_rejected_and_audited(game):
    db, state, _ = game
    source = _make_dossier(db, state, "护行密令")

    with pytest.raises(ValueError, match="指向不存在案卷"):
        db.add_dossier_links(
            source,
            [{"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}],
        )

    assert db.list_dossier_links(source) == []
    audit = db.list_dossier_link_rejections(source)
    assert audit[-1]["target_dossier_id"] == 999999
    assert "指向不存在案卷" in audit[-1]["reason"]



def test_same_target_multiple_relations_keep_exact_confirmed_tuples(monkeypatch):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": [
            {"target_dossier_id": 11, "relation_type": "护卫"},
            {"target_dossier_id": 11, "relation_type": "稽核"},
        ]}, ensure_ascii=False), 1),
    )
    proposals = [
        {"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"},
        {"target_dossier_id": 11, "relation_type": "稽核", "note": "查账"},
        {"target_dossier_id": 11, "relation_type": "接应", "note": "接应"},
    ]
    assert cli_backend.confirm_dossier_links(
        "臣确认护卫并稽核该案。", [{"id": 11, "decree_text": "辽饷"}], proposals,
    ) == proposals[:2]


def test_force_promulgated_rejected_dossier_is_referenceable(game):
    db, state, _ = game
    dossier_id = _make_dossier(db, state, "中旨强颁的旧旨")

    db.apply_dossier_promulgation(state, dossier_id, "rejected", reason="封驳")
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["promulgation_decision"] == "rejected"
    assert dossier_id in {
        row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)
    }


def test_withdrawn_rejected_dossier_is_not_referenceable(game):
    db, state, _ = game
    dossier_id = _make_dossier(db, state, "收回的旧旨")
    db.record_dossier_decision(dossier_id, "rejected", reason="驳回")
    db.record_dossier_decision(dossier_id, "withdrawn", reason="收回")
    assert dossier_id not in {row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)}


def test_pending_rejection_does_not_follow_reused_rolled_back_source_id(game):
    db, state, _ = game
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "坏引用", "content": "坏引用", "assignee": "孙承宗", "dossier_links": [
            {"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}]},
    )
    assert db.commit_pending_actions(state, action_ids=[action_id]) == []
    reused_id = _make_dossier(db, state, "后建案卷")
    assert db.list_dossier_link_rejections(reused_id) == []
    assert db.list_dossier_link_rejections(pending_action_id=action_id)


def test_serial_and_parallel_join_share_proposal_normalization(monkeypatch):
    candidates = [{"id": 11, "decree_text": "辽饷"}]
    mixed = [
        {"target_dossier_id": 11, "relation_type": " 护卫 ", "note": " 护送 "},
        {"target_dossier_id": 11, "relation_type": "稽核", "note": "   "},
        {"target_dossier_id": 11, "relation_type": "越权", "note": "坏类型"},
        {"target_dossier_id": True, "relation_type": "护卫", "note": "坏 ID"},
        {"target_dossier_id": 99, "relation_type": "接应", "note": "不可见"},
    ]
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_links": [
            {"target_dossier_id": 11, "relation_type": "护卫"},
            {"target_dossier_id": 11, "relation_type": "稽核"},
        ]}, ensure_ascii=False), 1),
    )

    normalized = cli_backend._normalize_dossier_link_proposals(candidates, mixed)
    serial = cli_backend.confirm_dossier_links("臣确认护卫辽饷。", candidates, mixed)
    confirmed = {(11, "护卫"), (11, "稽核")}
    parallel_join = [item for identity, item in normalized.items() if identity in confirmed]

    assert serial == parallel_join == [
        {"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"}
    ]


def test_parallel_cli_bad_link_does_not_roll_back_valid_secret_order(game, monkeypatch):
    db, state, content = game
    target = _make_dossier(db, state, "辽东补饷")
    db.record_dossier_decision(target, "promulgated")
    extracted = {
        "标题": "护行辽饷", "内容": "护送辽饷", "承办人": "毕自严",
        "案卷关联": [{"目标案卷ID": target, "类型": "护卫", "说明": "   "}],
    }

    def runner(*args, **kwargs):
        value = ({"confirmed_links": [
            {"target_dossier_id": target, "relation_type": "护卫"}
        ]} if kwargs.get("tag") == "dossier_link_confirmation" else extracted)
        return json.dumps(value, ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "_run_json_extractor_for_config", runner)
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = SimpleNamespace(refresh=lambda _name: None)
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")

    result = sess.apply_cli_conversation_actions(
        SimpleNamespace(name="毕自严", office_type="户部"),
        "密令：护行辽饷。", "臣明确确认护卫辽东补饷。",
        has_directive=False, secret_order_id=None,
    )
    applied = db.commit_pending_actions(state, action_ids=[result["pending_action_id"]])

    assert [item["id"] for item in applied] == [result["pending_action_id"]]
    assert db.list_pending_actions(state.turn, status="failed") == []
    order = db.list_secret_orders(minister_name="毕自严")[0]
    source = db.get_dossier_for_secret_order(order["id"])
    assert db.list_dossier_links(source["id"]) == []


def test_cli_secret_extraction_overlaps_independent_confirmation(monkeypatch):
    import threading
    barrier = threading.Barrier(2)
    seen = []
    extracted = {"标题": "护饷", "内容": "护饷", "承办人": "孙承宗", "案卷关联": [
        {"目标案卷ID": 11, "类型": "护卫", "说明": "护送"}]}
    def runner(*args, **kwargs):
        seen.append(kwargs.get("tag"))
        barrier.wait(timeout=2)
        value = ({"confirmed_links": [{"target_dossier_id": 11, "relation_type": "护卫"}]}
                 if kwargs.get("tag") == "dossier_link_confirmation" else extracted)
        return json.dumps(value, ensure_ascii=False), 1
    monkeypatch.setattr(cli_backend, "_run_json_extractor_for_config", runner)
    result = cli_backend._extract_secret_order(
        "护饷", "臣确认护卫辽饷。", "孙承宗",
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
        dossier_candidates=[{"id": 11, "decree_text": "辽饷"}],
    )
    assert set(seen) == {"secret_extract", "dossier_link_confirmation"}
    assert result["dossier_links"][0]["target_dossier_id"] == 11


def test_real_secret_order_tool_schema_describes_dossier_link_contract(game):
    from agno.tools.function import Function
    from ming_sim.tools import build_minister_tools
    db, state, content = game
    character = content.characters["孙承宗"]
    context = SimpleNamespace(db=db, state=state, content=content)
    callable_tool = next(tool for tool in build_minister_tools(character, context)
                         if tool.__name__ == "secret_order")
    schema = Function.from_callable(callable_tool).to_dict()
    rendered = json.dumps(schema, ensure_ascii=False)
    assert "dossier_links_json" in rendered
    assert "target_dossier_id" in rendered
    assert "relation_type" in rendered
    assert "note" in rendered
    assert all(value in rendered for value in ("护卫", "稽核", "接应"))
