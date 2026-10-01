"""#1862：邸报作者在过月暂停点一次写出标题和正文，随邸报入档后交回主链。"""

from __future__ import annotations

import json

import pytest

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
from ming_sim.audience_night import AUDIBILITY_PRIVATE, append_ledger_entry
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.materials import (
    list_materials,
    prepare_character_materials,
    prepare_world_materials,
    read_material,
    release_material_tree,
)
from ming_sim.audience_night import record_summon_in_transit
from ming_sim.models import LLMConfig, reign_period_label
from tests.conftest import append_night_chat, open_audience_night
from tests.dossier_test_helpers import TYPED_COVERT_TASK
from tests.month_chain_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict

_SECRET_DECL = "SECRET_DECL_1862"
_SECRET_FORECAST = "SECRET_FORECAST_1862"
_SECRET_FACT = "SECRET_FACT_1862"
_SECRET_REJ = "SECRET_REJ_1862"
_PUBLIC_FACT = "PUBLIC_FACT_1862"
_PUBLIC_REJ = "PUBLIC_REJ_1862"
_SECRET_BRIEF = "SECRET_BRIEF_BODY_1862"
_SECRET_AUDIENCE = "AUD_SECRET_SRC_1862"
_PRIVATE_KEEP = "AUD_PRIVATE_KEEP_1862"
_SECRET_DOSSIER_TEXT = "SECRET_DOSSIER_OPEN_1862"
_PLAIN_DOSSIER_TEXT = "PLAIN_DOSSIER_OPEN_1862"
_SECRET_DOSSIER_LEDGER = "SECRET_DOSSIER_LEDGER_1862"
_PLAIN_DOSSIER_LEDGER = "PLAIN_DOSSIER_LEDGER_1862"
_SECRET_DOSSIER_FACT = "SECRET_DOSSIER_FACT_1862"
_PLAIN_DOSSIER_FACT = "PLAIN_DOSSIER_FACT_1862"
_TITLE = "关山烽火"
_REPORT = "本月实况正文"


def _llm() -> LLMConfig:
    return LLMConfig(api_key="test", base_url="http://127.0.0.1:9", model="gazette-test")


def _session(db, state, content, monkeypatch):
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *_a, **_k: {"effects": {}})
    session = make_light_session(db, state, content)
    session.llm_config = _llm()
    session._write_gate = session._write_queue.write_gate
    return session


def _assert_author_directory_keeps_each_public_record(db, state, minister, secret_did, plain_did):
    """作者目录是 prepare_gazette_author_materials 的产出，不是事后再滤的第二份树。"""
    from ming_sim.assets import format_money
    from ming_sim.materials import (
        _person_audience_experience,
        _safe_segment,
        _secret_order_chat_turn_ids,
        dossier_id_in_origin,
        is_secret_order_origin,
        secret_order_dossier_ids,
    )
    from ming_sim.models import period_label

    prepared = month_chain.prepare_gazette_author_materials(db, state)
    try:
        secret_dossiers = secret_order_dossier_ids(db)

        def author_fact(fact) -> bool:
            origin = str(fact.origin_ref or "")
            if is_secret_order_origin(origin):
                return False
            dossier_id = dossier_id_in_origin(origin)
            return dossier_id is None or dossier_id not in secret_dossiers

        facts = [
            fact for fact in db.textual_facts.readable_materials(
                subject_kind="character", subject_id=minister,
            )
            if author_fact(fact)
        ]
        origins = {str(fact.origin_ref or "") for fact in facts}
        assert f"dossier:{plain_did}" in origins
        assert f"dossier:{secret_did}" not in origins
        assert "secret_order:9" not in origins
        month_body = "\n".join(
            f"{fact.occurred_month}：{fact.body}" for fact in facts
        ) or "（无）"
        month_rel = f"人物/{_safe_segment(minister)}/按月实况.txt"
        assert read_material(prepared.root, month_rel) == (
            month_body if month_body.endswith("\n") else month_body + "\n"
        )
        flat_parts = [str(fact.body or "") for fact in facts if str(fact.body or "").strip()]
        flat_rel = f"事实/character-{_safe_segment(minister)}.txt"
        if flat_parts:
            flat = "\n".join(flat_parts)
            assert read_material(prepared.root, flat_rel) == (
                flat if flat.endswith("\n") else flat + "\n"
            )
        else:
            assert flat_rel not in list_materials(prepared.root)

        def author_event(item) -> bool:
            kind = str(item.get("kind") or "")
            source = str(item.get("source_id") or "")
            if kind in {"secret_order", "secret_order_brief"}:
                return False
            if is_secret_order_origin(source):
                return False
            origin = item.get("origin_ref") or source
            dossier_id = dossier_id_in_origin(origin)
            return dossier_id is None or dossier_id not in secret_dossiers

        knowledge = db.get_character_knowledge(state, minister)
        lines = []
        for item in knowledge.get("events") or []:
            if not author_event(item):
                continue
            title = str(item.get("title") or "")
            body = str(item.get("body") or "")
            if not title.strip() and not body.strip():
                continue
            lines.append(f"{title}：{body}" if title and body else (title or body))
        secret_turns = _secret_order_chat_turn_ids(db)
        audience = [
            entry for entry in _person_audience_experience(db, minister)
            if int(entry.get("source_chat_turn_id") or 0) not in secret_turns
        ]
        lines.extend(str(entry["body"]) for entry in audience if entry.get("body"))
        experience = "\n".join(lines) or "（无）"
        experience_rel = f"人物/{_safe_segment(minister)}/经历.txt"
        assert read_material(prepared.root, experience_rel) == (
            experience if experience.endswith("\n") else experience + "\n"
        )

        board = read_material(prepared.root, "盘面/全局.txt")
        rows = db.conn.execute(
            "SELECT year, period, account, delta, category, reason, origin_ref "
            "FROM economy_ledger WHERE turn=?",
            (int(state.turn),),
        ).fetchall()
        secret_lines = []
        public_lines = []
        for row in rows:
            origin = str(row["origin_ref"] or "")
            dossier_id = dossier_id_in_origin(origin)
            rendered = (
                f"{period_label(int(row['year']), int(row['period']))} "
                f"{row['account']}{'+' if int(row['delta']) > 0 else ''}{format_money(int(row['delta']))} "
                f"{row['category']}：{row['reason']}"
            )
            if is_secret_order_origin(origin) or (
                dossier_id is not None and dossier_id in secret_dossiers
            ):
                secret_lines.append(rendered)
            else:
                public_lines.append(rendered)
        assert secret_lines and public_lines
        assert all(line not in board for line in secret_lines)
        assert any(line in board for line in public_lines)
    finally:
        release_material_tree(prepared.root)


def test_author_waits_until_rescript_is_done(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="请旨挡邸报", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (
            '[{"title":"是否加赈","context":"c","options":[{"label":"加","hint":"h1"},{"label":"否","hint":"h2"}]}]',
            ref,
        ),
    )
    db.conn.commit()
    calls = []
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *_a, **_k: "")
    monkeypatch.setattr(
        month_chain, "run_gazette_text",
        lambda *_a, **_k: calls.append(1) or (_TITLE, _REPORT),
    )
    session = _session(db, state, content, monkeypatch)
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False
    assert calls == []


def test_author_archives_own_title_and_same_run_advances(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    character = next(iter(content.characters.values()))
    affair = db.affairs.open(
        name="过月可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    turn = int(state.turn)
    year, period = int(state.year), int(state.period)
    db.conn.execute(
        "INSERT INTO staged_declarations "
        "(decree_ref, declaration_json, visible_refs_json, status, created_turn, forecast_text) "
        "VALUES (?, ?, ?, 'settled', ?, ?)",
        (
            "secret_order:9",
            json.dumps({"kind": "secret_order", "origin_ref": "secret_order:9", "body": _SECRET_DECL}, ensure_ascii=False),
            json.dumps({"secret_orders": [9]}),
            turn,
            _SECRET_FORECAST,
        ),
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_SECRET_FACT,
        year=year, period=period, turn=turn, origin_ref="secret_order:9",
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_PUBLIC_FACT,
        year=year, period=period, turn=turn, origin_ref=f"affair:{affair.id}",
    )
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn, year, period, account, delta, balance_after, category, reason, origin_ref) "
        "VALUES (?, ?, ?, '国库', -3, 1, 'SECRET_LEDGER', '密令账', 'secret_order:9')",
        (turn, year, period),
    )
    collector = RejectionCollector()
    collector.record(
        "密令", RejectedItem(
            {"kind": "secret_order", "origin_ref": "secret_order:9", "note": _SECRET_REJ},
            "密令拒收", "invalid_shape", Provenance.secret_order,
        ), turn,
    )
    collector.record(
        "旨意", RejectedItem(
            {"origin_ref": f"affair:{affair.id}", "note": _PUBLIC_REJ},
            "公开拒收", "invalid_shape", Provenance.player_decree,
        ), turn,
    )
    collector.flush_to_db(db)
    night_id = open_audience_night(db, state)
    secret_turn, first_mid = append_night_chat(db, state, night_id, minister, "问密", "答密", 1)
    pending_create = db.stage_pending_action(
        turn, kind="secret_order", action="新建", minister_name=minister,
        payload={
            "title": "密题不入邸报", "content": "密令原件", "assignee": minister,
            "origin_chat_message_id": first_mid,
            "tags": ["查办"], "covert_task": TYPED_COVERT_TASK,
        },
    )
    committed = db.commit_pending_actions(state, minister_name=minister, action_ids={pending_create}, content=content)
    assert committed
    order_id = int(db.conn.execute("SELECT id FROM secret_orders ORDER BY id DESC LIMIT 1").fetchone()[0])

    secret_did = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', decree_text=? WHERE id=?",
        (_SECRET_DOSSIER_TEXT, secret_did),
    )
    plain_did = db.create_decree_dossier(
        state, action_type="policy", decree_text=_PLAIN_DOSSIER_TEXT,
        target_kind="issue", target_id="plain-dossier-1862",
    )
    db.apply_dossier_promulgation(state, plain_did, "promulgated")
    for category, reason, origin in (
        (_SECRET_DOSSIER_LEDGER, "密令案卷账", f"dossier:{secret_did}"),
        (_PLAIN_DOSSIER_LEDGER, "普通案卷账", f"dossier:{plain_did}"),
    ):
        db.conn.execute(
            "INSERT INTO economy_ledger "
            "(turn, year, period, account, delta, balance_after, category, reason, origin_ref) "
            "VALUES (?, ?, ?, '国库', -2, 1, ?, ?, ?)",
            (turn, year, period, category, reason, origin),
        )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_SECRET_DOSSIER_FACT,
        year=year, period=period, turn=turn, origin_ref=f"dossier:{secret_did}",
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_PLAIN_DOSSIER_FACT,
        year=year, period=period, turn=turn, origin_ref=f"dossier:{plain_did}",
    )
    plain_turn, _ = append_night_chat(db, state, night_id, minister, "问私", "答私", 2)
    later_turn, later_mid = append_night_chat(db, state, night_id, minister, "再问密", "再答密", 3)
    pending_update = db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=minister,
        target_id=order_id, payload={
            "new_title": "密报题", "new_content": _SECRET_BRIEF,
            "origin_chat_message_id": later_mid,
        },
    )
    assert db.commit_pending_actions(state, minister_name=minister, action_ids={pending_update}, content=content)
    pending_turn, pending_mid = append_night_chat(db, state, night_id, minister, "待决密", "待决答", 4)
    db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=minister,
        target_id=999999, payload={"new_title": "待决密题", "new_content": "待决密令", "origin_chat_message_id": pending_mid},
    )
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body=_SECRET_AUDIENCE, tags=["scroll_role:minister"],
        source_chat_turn_id=secret_turn, origin_chat_turn_id=secret_turn,
    )
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body="密令分轮应允经历1862", tags=["scroll_role:minister"],
        source_chat_turn_id=later_turn, origin_chat_turn_id=later_turn,
    )
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body="待决密令经历1862", tags=["scroll_role:minister"],
        source_chat_turn_id=pending_turn, origin_chat_turn_id=pending_turn,
    )
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body=_PRIVATE_KEEP, tags=["scroll_role:minister"],
        source_chat_turn_id=plain_turn, origin_chat_turn_id=plain_turn,
    )
    names = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
        ).fetchall()
    ]
    old_waiter, arriver = names
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='' WHERE name=?",
        (old_waiter,),
    )
    record_summon_in_transit(
        db, night_id, old_waiter, origin_id="gazette-old-wait-1862",
    )
    db.set_character_transit(
        arriver,
        location="liaodong",
        transit_to="beizhili",
        distance_remaining=0.5,
        speed_factor=1.0,
        start_turn=int(turn) - 1,
        content=content,
    )
    record_summon_in_transit(
        db, night_id, arriver, origin_id="gazette-arrive-1862",
    )
    for origin, title in (
        ("", "到期公开承诺1862"),
        ("secret_order:9", "密令到期承诺1862"),
        (f"dossier:{secret_did}", "密令案卷到期承诺1862"),
        (f"dossier:{plain_did}", "普通案卷到期承诺1862"),
    ):
        db.conn.execute(
            "INSERT INTO issues (kind, title, origin_turn, commitment_kind, end_turn, stage_text, origin_ref) "
            "VALUES ('commitment', ?, ?, 'once', ?, ?, ?)",
            (title, turn, turn, title, origin),
        )
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (night_id,),
    )
    db.conn.commit()
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, status) "
        "VALUES (?, 1, 'note:1', '公开答复题', 'ctx', '[]', ?, 'decided')",
        (turn, json.dumps({"label": "准了", "note": "朱批可见"}, ensure_ascii=False)),
    )
    db.conn.commit()
    _assert_author_directory_keeps_each_public_record(
        db, state, minister, secret_did, plain_did,
    )
    seen = {}

    def world(*_a, **_k):
        return "WORLD_PUBLIC_SEGMENT"

    def run_agent(agent, prompt, tag, **_k):
        # 过月主链先走 4a 整月供料再写邸报；假模型须按调用角色供合法产物，
        # 不得用邸报 JSON 冒充密奏（否则 0058 缺报校验响亮中止，用例到不了归档断言）。
        if tag == "secret_orders_supply":
            return json.dumps(
                {
                    "dossier_progress_reports": [{
                        "dossier_id": secret_did,
                        "progress_band": "持平",
                        "memorial_text": "本月密奏供料正文。",
                    }],
                    "covert_exec_selections": [{
                        "order_id": order_id,
                        "fidelity": "忠实",
                    }],
                },
                ensure_ascii=False,
            )
        assert tag == "gazette", f"unexpected agent tag: {tag!r}"
        seen["tag"] = tag
        seen["prompt"] = prompt
        return json.dumps({"title": _TITLE, "report": _REPORT}, ensure_ascii=False)

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr("ming_sim.agents.run_agent_text", run_agent)
    session = _session(db, state, content, monkeypatch)
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.advanced is True
    assert int(state.turn) == turn + 1
    archive = db.get_turn_report_archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
    listed = next(row for row in db.list_turn_reports() if int(row["turn"]) == turn)
    assert listed["title"] == _TITLE
    payload = json.loads(seen["prompt"])
    assert any(row.get("category") == "宁远补饷" for row in payload["landed"])
    assert all(str(row.get("origin_ref") or "") != "secret_order:9" for row in payload["landed"])
    assert all(str(row.get("origin_ref") or "") != f"dossier:{secret_did}" for row in payload["landed"])
    assert any(str(row.get("origin_ref") or "") == f"dossier:{plain_did}" for row in payload["landed"])
    assert "预推不可见:宁远补饷" in payload["forecasts"]
    assert _SECRET_FORECAST not in payload["forecasts"]
    assert all(item.get("decree_ref") != "secret_order:9" for item in payload["nominal"])
    assert any(
        str((item.get("item") or {}).get("origin_ref") or "") == f"affair:{affair.id}"
        for item in payload["rejections"]
    )
    assert all(
        str((item.get("item") or {}).get("origin_ref") or "") != "secret_order:9"
        for item in payload["rejections"]
    )
    assert payload["world_segment"] == "WORLD_PUBLIC_SEGMENT"
    assert any(row.get("note") == "朱批可见" for row in payload["rescript_answers"])
    label = reign_period_label(year, period)
    assert payload["reign_period_label"] == label
    assert {item["origin_ref"] for item in payload["due_commitments"]} == {
        "", f"dossier:{plain_did}",
    }
    assert any(
        item.get("person_name") == arriver and item.get("origin_id") == "gazette-arrive-1862"
        for item in payload["waiting_audience"]
    ), payload["waiting_audience"]
    assert all(
        item.get("person_name") != old_waiter
        for item in payload["waiting_audience"]
    ), payload["waiting_audience"]
    assert set(payload["month_open"]) == {"国库", "内库", "民心", "皇威"}
    knowledge = db.get_character_knowledge(state, minister)
    public_ids = {
        str(item.get("source_id") or "") for item in knowledge.get("public_events") or []
    }
    event_ids = {
        str(item.get("source_id") or "") for item in knowledge.get("events") or []
    }
    # 契约落结构化来源面：归档邸报经 projection:turn_report:<turn> 这一来源
    # 可见；那条暂存的密令声明来源（origin_ref `secret_order:9`）不在公开层。
    # 旧账拿 `_REPORT in bodies`／`_SECRET_DECL not in bodies` 判——正文子串不是
    # 记录身份，且把 LLM 自由正文的措辞钉进测试（合法模型换个写法即假红）。
    # 来源 ID 才是记录身份。
    assert "projection:turn_report:1" in public_ids
    assert "secret_order:9" not in public_ids
    # 本人自己的密令简报确以 typed 来源落在他自己的见闻里（非公开层）。
    assert f"secret_order_brief:{order_id}" in event_ids
    assert f"secret_order_brief:{order_id}" not in public_ids
    prepared = prepare_character_materials(db, state, character)
    try:
        rel = next(
            path for path in list_materials(prepared.root)
            if path.startswith("公开说法/邸报/")
        )
        text = read_material(prepared.root, rel)
        gazette = next(
            line for line in prepared.index_lines
            if line == rel or line.startswith(rel + " ")
        )
        # 载体契约：本月邸报载体逐字承载模型写的正文（引擎对 LLM 输出零删改，
        # ADR 0142）。这是「原样搬运」而非「推断身份」——两侧同为模型产出，
        # 断言的是载体与产物同一，而不是从正文里认记录。索引行只由路径＋朝代
        # 月标签＋已入档标题拼成，不夹带正文。
        report = str(archive["report"])
        assert text == (report if report.endswith("\n") else report + "\n")
        assert gazette == f"{rel} {label} {archive['title']}"
        # 亲历载体：本人经历.txt 在册且非空。旧账在正文里找 `_SECRET_BRIEF`
        # 等哨兵串，已删（大理寺 553d581fb）：那是对人读正文做子串推断，人读
        # 正文不是记录身份，一次合法改写即假红。密令简报确以 typed 来源落在
        # 本人见闻里，由上一条来源 ID 承担。
        experience = next(path for path in prepared.index_lines if path.endswith("/经历.txt"))
        assert read_material(prepared.root, experience).strip()
    finally:
        release_material_tree(prepared.root)
    world_tree = prepare_world_materials(db, state)
    try:
        # 世界目录：每位在册人物都有亲历载体，且盘面载体在册可读。
        world_experience = [
            rel for rel in world_tree.index_lines if rel.endswith("/经历.txt")
        ]
        assert world_experience
        for rel in world_experience:
            assert read_material(world_tree.root, rel).strip()
        board = next(rel for rel in world_tree.index_lines if rel.endswith("全局.txt"))
        assert read_material(world_tree.root, board).strip()
    finally:
        release_material_tree(world_tree.root)


def test_gazette_failure_retries_report_only(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="重试可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    turn = int(state.turn)
    world_calls = []
    gazette_calls = {"n": 0}

    def world(*_a, **_k):
        world_calls.append(1)
        return "世界段一次"

    def gazette(*_a, **_k):
        gazette_calls["n"] += 1
        if gazette_calls["n"] == 1:
            raise LLMUnavailable("邸报写失败", stage="gazette")
        return _TITLE, _REPORT

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_chain, "run_gazette_text", gazette)
    session = _session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    charged = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    assert charged == 1
    assert world_calls == [1]
    assert db.get_turn_report(turn) == ""
    failure = month_chain.month_chain_call_failure(db, turn)
    assert failure["step"] == "gazette"

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert gazette_calls["n"] == 2
    assert world_calls == [1]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == 1
    archive = db.get_turn_report_archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
