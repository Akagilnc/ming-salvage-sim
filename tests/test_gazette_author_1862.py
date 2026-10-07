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
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order
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
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *_a, **_k: "")
    # 外部 LLM 边界：挡邸报作者；可见结果是请旨台阶段，不锁调用次数。
    monkeypatch.setattr(
        month_chain, "run_gazette_text",
        lambda *_a, **_k: (_TITLE, _REPORT),
    )
    session = _session(db, state, content, monkeypatch)
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False


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

    secret_did = int(db.dossiers.get_for_secret_order(order_id)["id"])
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
        seen["instructions"] = "\n".join(
            str(part) for part in (getattr(agent, "instructions", None) or [])
        )
        listing = ""
        for tool in getattr(agent, "tools", []) or []:
            entry = getattr(tool, "entrypoint", tool)
            if getattr(entry, "__name__", "") == "list_materials":
                listing = entry()
                break
        seen["files"] = listing
        read = None
        for tool in getattr(agent, "tools", []) or []:
            entry = getattr(tool, "entrypoint", tool)
            if getattr(entry, "__name__", "") == "read_material":
                read = entry
                break
        if read is not None:
            for rel in listing.splitlines():
                if rel.endswith(".txt"):
                    seen["files"] += "\n" + read(rel)
        return json.dumps({"title": _TITLE, "report": _REPORT}, ensure_ascii=False)

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr("ming_sim.agents.run_agent_text", run_agent)

    # 作者 prepare 深度内：观察最终消费筛选结果（_keep_fact / _knowledge_for_experience），
    # 不观察谓词布尔本身；agent 接缝绑定同一 prepared。
    import ming_sim.agents as agents_mod
    import ming_sim.materials as materials_mod
    import ming_sim.month_chain as month_chain_mod

    author_capture: dict[str, object] = {
        "dossier_ids": None,
        "fact_origins_kept": [],
        "event_source_ids_kept": [],
        "audience_source_turns_kept": [],
        "prepared": None,
        "agent_prepared": None,
    }
    real_prepare = month_chain_mod.prepare_gazette_author_materials
    real_world_opening = materials_mod._world_opening_text
    real_keep_fact = materials_mod._keep_fact
    real_knowledge_exp = materials_mod._knowledge_for_experience
    real_omit_audience = materials_mod._omit_secret_order_audience
    real_create = agents_mod.create_gazette_author_agent
    depth = {"n": 0}

    def _spy_world_opening(state_arg, board_text, affair_lines, dossier_facts, **kwargs):
        if depth["n"] > 0:
            author_capture["dossier_ids"] = [int(f["id"]) for f in dossier_facts]
        return real_world_opening(
            state_arg, board_text, affair_lines, dossier_facts, **kwargs,
        )

    def _spy_keep_fact(fact, include_fact):
        kept = real_keep_fact(fact, include_fact)
        if depth["n"] > 0 and kept:
            origin = getattr(fact, "origin_ref", None)
            if origin is None and isinstance(fact, dict):
                origin = fact.get("origin_ref")
            author_capture["fact_origins_kept"].append(str(origin or ""))
        return kept

    def _spy_knowledge_exp(knowledge, include_event):
        projected = real_knowledge_exp(knowledge, include_event)
        if depth["n"] > 0:
            for item in projected.get("events") or []:
                if isinstance(item, dict):
                    author_capture["event_source_ids_kept"].append(
                        str(item.get("source_id") or "")
                    )
        return projected

    def _spy_omit_audience(entries, secret_turn_ids):
        kept = real_omit_audience(entries, secret_turn_ids)
        if depth["n"] > 0:
            for entry in kept:
                if isinstance(entry, dict):
                    author_capture["audience_source_turns_kept"].append(
                        int(entry.get("source_chat_turn_id") or 0)
                    )
        return kept

    def _spy_prepare(db_arg, state_arg):
        depth["n"] += 1
        try:
            monkeypatch.setattr(materials_mod, "_world_opening_text", _spy_world_opening)
            monkeypatch.setattr(materials_mod, "_keep_fact", _spy_keep_fact)
            monkeypatch.setattr(
                materials_mod, "_knowledge_for_experience", _spy_knowledge_exp,
            )
            monkeypatch.setattr(
                materials_mod, "_omit_secret_order_audience", _spy_omit_audience,
            )
            prepared = real_prepare(db_arg, state_arg)
            author_capture["prepared"] = prepared
            return prepared
        finally:
            depth["n"] -= 1

    def _spy_create(llm_config, prepared, *a, **k):
        author_capture["agent_prepared"] = prepared
        return real_create(llm_config, prepared, *a, **k)

    monkeypatch.setattr(month_chain_mod, "prepare_gazette_author_materials", _spy_prepare)
    monkeypatch.setattr(agents_mod, "create_gazette_author_agent", _spy_create)

    before = prepare_world_materials(db, state)
    try:
        next((rel for rel in before.index_lines if rel.endswith('全局.txt')))
        assert _PLAIN_DOSSIER_TEXT in before.opening
    finally:
        release_material_tree(before.root)
    session = _session(db, state, content, monkeypatch)
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.advanced is True
    assert int(state.turn) == turn + 1
    archive = db.turn_reports.archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
    listed = next(row for row in db.turn_reports.list_archives() if int(row["turn"]) == turn)
    assert listed["title"] == _TITLE
    payload = json.loads(seen["prompt"])
    assert any(row.get("category") == "宁远补饷" for row in payload["landed"])
    assert all(str(row.get("origin_ref") or "") != "secret_order:9" for row in payload["landed"])
    assert all(str(row.get("origin_ref") or "") != f"dossier:{secret_did}" for row in payload["landed"])
    assert any(str(row.get("origin_ref") or "") == f"dossier:{plain_did}" for row in payload["landed"])
    # 公开预推文是 staged 行 forecast_text 字段搬运；密令来源以 decree_ref 滤出 nominal，
    # 同缝不进 forecasts——不拿自由预推正文当来源身份 oracle。
    assert "预推不可见:宁远补饷" in payload["forecasts"]
    assert all(
        str(row.get("decree_ref") or "") != "secret_order:9"
        for row in (payload.get("nominal") or [])
    )
    assert any(
        str((row.get("item") or {}).get("origin_ref") or "") == f"affair:{affair.id}"
        for row in (payload.get("rejections") or [])
    )
    assert all(
        str((row.get("item") or {}).get("origin_ref") or "") != "secret_order:9"
        for row in (payload.get("rejections") or [])
    )
    assert payload["world_segment"] == "WORLD_PUBLIC_SEGMENT"
    assert any(
        "朱批可见" in (
            str(row.get("note") or ""),
            str(row.get("label") or ""),
            str(row.get("title") or ""),
        )
        for row in (payload.get("rescript_answers") or [])
        if isinstance(row, dict)
    )
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
    assert all(str(row.get("category") or "") != "SECRET_LEDGER" for row in payload["landed"])
    assert any(str(row.get("category") or "") == _PLAIN_DOSSIER_LEDGER for row in payload["landed"])
    assert all(str(row.get("category") or "") != _SECRET_DOSSIER_LEDGER for row in payload["landed"])

    # 作者 prepare 与 agent 接缝绑定同一 prepared；dossier 身份在该次 opening 入参上。
    assert author_capture.get("prepared") is not None
    assert author_capture.get("agent_prepared") is author_capture.get("prepared")
    gaz_ids = set(author_capture.get("dossier_ids") or [])
    assert int(secret_did) not in gaz_ids
    assert int(plain_did) in gaz_ids
    # 最终 _keep_fact 消费结果：公开 origin 入选，密令/密令案卷 origin 不入选
    kept_facts = set(author_capture.get("fact_origins_kept") or [])
    assert f"affair:{affair.id}" in kept_facts
    assert f"dossier:{plain_did}" in kept_facts
    assert "secret_order:9" not in kept_facts
    assert f"dossier:{secret_did}" not in kept_facts
    assert all(not str(o).startswith("secret_order:") for o in kept_facts)
    # 最终经历投影：knowledge.events 不含密令 brief
    kept_events = set(author_capture.get("event_source_ids_kept") or [])
    assert f"secret_order_brief:{order_id}" not in kept_events
    assert all(not str(s).startswith("secret_order") for s in kept_events)
    # 召对 audience 轨最终保留：普通 plain_turn 入选；密令关联轮排除
    kept_audience_turns = set(author_capture.get("audience_source_turns_kept") or [])
    assert int(plain_turn) in kept_audience_turns
    assert int(secret_turn) not in kept_audience_turns
    assert int(later_turn) not in kept_audience_turns
    assert int(pending_turn) not in kept_audience_turns
    # agent tools 消费发生，且接到作者 prepare 同一份
    assert str(seen.get("files") or "").strip() != ""
    assert str(seen.get("instructions") or "").strip() != ""

    prepared = prepare_character_materials(db, state, character)
    try:
        rel = next(
            path for path in list_materials(prepared.root)
            if path.startswith("公开说法/邸报/")
        )
        text = read_material(prepared.root, rel)
        # 原字段无损搬运：归档 report 读回
        assert text.strip() == _REPORT
        # 索引行携带 title 字段（机器路径 + 原字段），不负向锁 report 不得出现在索引
        gazette_line = next(
            line for line in prepared.index_lines
            if line == rel or line.startswith(rel + " ")
        )
        assert _TITLE in gazette_line
        next((path for path in prepared.index_lines if path.endswith('/经历.txt')))
    finally:
        release_material_tree(prepared.root)
    world = prepare_world_materials(db, state)
    try:
        next((rel for rel in world.index_lines if rel.endswith('全局.txt')))
    finally:
        release_material_tree(world.root)


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
    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert "邸报写失败" in str(caught.value.__cause__)
    charged = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    assert charged == 1
    assert world_calls == [1]
    assert db.turn_reports.report_text(turn) == ""
    failure = month_chain.month_chain_call_failure(db, turn)
    assert failure["step"] == "gazette"

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert gazette_calls["n"] == 2
    assert world_calls == [1]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == 1
    archive = db.turn_reports.archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
