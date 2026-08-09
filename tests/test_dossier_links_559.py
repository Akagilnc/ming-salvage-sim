import json

import pytest

from ming_sim import cli_backend


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
        value = ({"confirmed_ids": [11, 12]}
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
        lambda *args, **kwargs: (json.dumps({"confirmed_ids": []}), 1),
    )
    links = cli_backend.confirm_dossier_links(
        reply,
        [{"id": 11, "decree_text": "辽东补饷"},
         {"id": 12, "decree_text": "辽东补饷补充"}],
        [{"target_dossier_id": 11, "relation_type": "护卫", "note": "护送"},
         {"target_dossier_id": 12, "relation_type": "护卫", "note": "护送补充案"}],
    )
    assert links == []


def test_semantic_verdict_can_narrow_to_exactly_one_proposed_candidate(monkeypatch):
    monkeypatch.setattr(
        cli_backend, "_run_json_extractor_for_config",
        lambda *args, **kwargs: (json.dumps({"confirmed_ids": [12, 999]}), 1),
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
    db.conn.execute("UPDATE decree_dossiers SET status='promulgated' WHERE id=?", (public_id,))
    db.conn.commit()
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
