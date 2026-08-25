"""#642 族尾收口：四锚机械面 + restore 点检引用 + DoD 面4 extractor tracer。

闸级（活模型）语义面见 scripts/family_tail_relation_acceptance_642.py。
本文件只收确定性 CI 面；复用既有 production 入口，禁止平行 ledger/DTO/harness。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.relation_brew import run_month_end_relation_brew
from ming_sim.relation_judge import run_summon_relation_judge, summon_edge_origin
from ming_sim.relation_read import load_relation_history_before, project_relation_ledger
from ming_sim.relations import EMPEROR_NODE, MINISTER_EDGE_KINDS
from ming_sim.session import GameSession
from ming_sim.simulation import EMPTY_EXTRACTION, MODULE_FIELDS

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "content" / "relation_seed.json"
FROZEN_DTO = frozenset({
    "source", "target", "summary", "recent_context", "updated_at_period",
})


class _CannedJudge:
    def __init__(self, payload):
        self.payload = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        self.calls = 0
        self.prompts: list[str] = []

    def run(self, prompt):
        from types import SimpleNamespace
        self.calls += 1
        self.prompts.append(str(prompt))
        return SimpleNamespace(content=self.payload)


def _fresh_session(tmp_path, monkeypatch):
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod

    monkeypatch.setattr(
        llm_mod, "verify_llm_available",
        lambda cfg: (_ for _ in ()).throw(AssertionError("不得连 LLM")),
    )
    monkeypatch.setattr(
        _cb, "_run_backend_for_config",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不得连 CLI")),
    )
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    sess = GameSession(
        db_path=str(tmp_path / "t642.db"), llm_config=cfg, content=content,
    )
    return sess, content


def _make_turn(db, state, minister, question, answer):
    ctid = db.create_chat_turn(state, minister, "t642:s", 0, night_id=0)
    umid = db.append_chat_message(minister, int(state.turn), "user", question)
    db.update_chat_turn_messages(ctid, user_message_id=umid)
    mid = db.append_chat_message(minister, int(state.turn), "minister", answer)
    db.update_chat_turn_messages(ctid, minister_message_id=mid)
    return ctid


# ── 锚① 机械面：新开档 seed → project_relation_ledger ────────────────


def test_anchor1_seed_net_readable_via_production_import(tmp_path, monkeypatch):
    """锚①：GameSession 新开档真实导入 seed；判官机面五字段可读；可选摘要不强制全有。"""
    sess, _content = _fresh_session(tmp_path, monkeypatch)
    try:
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        seed_pairs = {
            (str(e["source"]), str(e["target"])) for e in seed["events"]
        }
        seed_summary_pairs = {
            (str(s["source"]), str(s["target"]))
            for s in seed.get("summaries") or []
        }
        face = project_relation_ledger(sess.db, viewer=None)
        face_pairs = {(d["source"], d["target"]) for d in face}
        assert seed_pairs <= face_pairs
        for dto in face:
            assert set(dto.keys()) == FROZEN_DTO
            assert isinstance(dto["summary"], str)
            assert isinstance(dto["recent_context"], str)
            assert isinstance(dto["updated_at_period"], str)
        # 魏忠贤场网：至少能读到阉党骨干相关边（不以人数硬闸）。
        wei = [d for d in face if "魏忠贤" in (d["source"], d["target"])]
        assert wei, "seed 网应含魏忠贤相关有向对"
        # 初始摘要按 ADR 0086 可选：只校验 seed 实际提供的那几条非空可读。
        for source, target in seed_summary_pairs:
            hit = next(
                d for d in face if (d["source"], d["target"]) == (source, target)
            )
            assert hit["summary"].strip(), f"seed 摘要应对 {source}→{target} 可读"
        # 负向结构位：允许核心对无摘要（不强迫凡核心对必有 summary）。
        _core_without = [
            d for d in wei
            if (d["source"], d["target"]) not in seed_summary_pairs
            and not d["summary"].strip()
        ]
        assert isinstance(_core_without, list)
    finally:
        sess.close()


# ── 锚② 结构步：三拍边/读面闭环（加深语义仅闸级 LLM）────────────────


def test_anchor2_yang_three_beat_structural_read_write_loop(game):
    """锚② 结构面：读面→张力边→配合协作回写→知遇再深；旧张力不删。

    语义「逐拍加深/不跳变」归闸级 scripts/family_tail_relation_acceptance_642.py。
    """
    db, state, _content = game
    # 拍1：君→杨 知遇（经 canonical 写口）
    db.record_relation_edge_event(
        source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
        context="越次一召，擢杨嗣昌于五品郎中。",
        origin="anchor2:beat1", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    # 拍2：杨→倪 细缝；角色读面须可见自身参与边
    db.record_relation_edge_event(
        source="杨嗣昌", target="倪元璐", event_kind="使绊",
        context="清丈议上路线分歧，细缝初现。",
        origin="anchor2:beat2", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    yang_face = project_relation_ledger(db, viewer="杨嗣昌")
    yang_pairs = {(d["source"], d["target"]) for d in yang_face}
    assert (EMPEROR_NODE, "杨嗣昌") in yang_pairs
    assert ("杨嗣昌", "倪元璐") in yang_pairs
    tension = next(
        d for d in yang_face if (d["source"], d["target"]) == ("杨嗣昌", "倪元璐")
    )
    assert "细缝初现" in tension["recent_context"]
    # 拍3：配合段回写协作（调和）+ 君→杨 知遇再记一条；旧使绊仍在流水
    db.record_relation_edge_event(
        source="杨嗣昌", target="倪元璐", event_kind="协作",
        context="一刚一柔分工，当面调和而不抹去前隙。",
        origin="anchor2:beat3-collab", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    db.record_relation_edge_event(
        source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
        context="清丈委任加重，圣眷再深。",
        origin="anchor2:beat3-zhiyu", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    jun_yang = db.get_relation_edge_events(source=EMPEROR_NODE, target="杨嗣昌")
    assert sum(1 for e in jun_yang if e["event_kind"] == "知遇") >= 2
    yang_ni = db.get_relation_edge_events(source="杨嗣昌", target="倪元璐")
    kinds = {e["event_kind"] for e in yang_ni}
    assert "使绊" in kinds and "协作" in kinds
    # 旧张力事件字节仍在（和解不删旧事）
    assert any(e["context"] == "清丈议上路线分歧，细缝初现。" for e in yang_ni)
    for e in jun_yang + yang_ni:
        assert e["event_kind"]
        assert e["context"].strip()
        assert e["origin"]


# ── 锚③：召对判官落边生产缝生成徐杨协作 ─────────────────────────────


def test_anchor3_xuyang_collaboration_via_summon_judge(game):
    """锚③：真实召对判官链当场落协作边；端点覆盖徐光启与杨嗣昌；origin 绑源轮。"""
    db, state, _content = game
    # 北极星「徐杨相发明」场：徐光启开局为 offstage 罢居——fixture 推至在朝阁老态，
    # 使其成为召对判官合法端点（不短路写边）。
    db.conn.execute(
        "UPDATE characters SET status='active', office=?, office_type=? "
        "WHERE name=?",
        ("礼部尚书兼东阁大学士", "内阁", "徐光启"),
    )
    db.conn.commit()
    roster = {r["name"] for r in db.current_court_roster_rows(state)}
    assert {"徐光启", "杨嗣昌"} <= roster
    ctid = _make_turn(
        db, state, "杨嗣昌",
        "卿与徐阁老清丈屯田之议，可相发明否？",
        "臣与徐阁老相发明，清丈隐田与屯田番薯可三合一。",
    )
    context = "杨嗣昌与徐光启在御前就清丈屯田番薯相发明，结成协作。"
    agent = _CannedJudge({"events": [{
        "施动者": "杨嗣昌", "受动者": "徐光启", "类目": "协作", "语境": context,
    }]})
    res = run_summon_relation_judge(
        db, state, llm_config=object(), write_gate=threading.Lock(), agent=agent,
    )
    assert not res.get("degraded") and not res.get("skipped"), res
    rows = db.get_relation_edge_events(event_kind="协作")
    hit = [
        r for r in rows
        if {r["source"], r["target"]} == {"徐光启", "杨嗣昌"}
    ]
    assert len(hit) == 1
    row = hit[0]
    assert row["event_kind"] == "协作"
    assert row["event_kind"] in MINISTER_EDGE_KINDS
    assert row["context"] == context
    assert int(row["turn"]) == int(state.turn)
    assert row["origin"].startswith(summon_edge_origin(ctid))
    # restore 后仍在
    path = db.path
    db.close()
    reopened = GameDB(path)
    again = [
        r for r in reopened.get_relation_edge_events(event_kind="协作")
        if {r["source"], r["target"]} == {"徐光启", "杨嗣昌"}
    ]
    assert len(again) == 1 and again[0]["context"] == context
    reopened.close()


# ── 锚④ 机械装配：多年后 brew 输入含奠基原句 ────────────────────────


def test_anchor4_coda_brew_input_carries_founding_context(game):
    db, state, _ = game
    source, target = EMPEROR_NODE, "杨嗣昌"
    founding = "越次一召，擢杨嗣昌于五品郎中。"
    db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context=founding, origin="seed:founding:yueci",
        turn=0, year=1628, period=11,
    )
    # 推进到多年后 settled 月并写入新事件以入选
    state.year = 1635
    state.period = 6
    state.turn = 80
    db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context="多年后委以更大任。", origin="audience:later",
        turn=80, year=1635, period=6,
    )
    calls: list = []

    def brew_fn(payload_json: str) -> str:
        payload = json.loads(payload_json)
        calls.append(payload)
        if payload.get("view"):
            return json.dumps({"stance_segment": "派系态势。"}, ensure_ascii=False)
        return json.dumps(
            {"new_foundings": [], "recent_segment": "知遇回声近况。"},
            ensure_ascii=False,
        )

    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["selected"] >= 1
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls
    prior = relation_calls[0]["prior_events"]
    assert any(e["context"] == founding for e in prior)
    seam = load_relation_history_before(
        db, source=source, target=target, before_year=1635, before_period=6,
    )
    assert founding in [e["context"] for e in seam]


# ── DoD 面4：真实 extractor 产出路径 → 唯一写口 ──────────────────────


def test_dod_face4_real_extractor_section_lands_via_apply_score(game):
    """面4：relation_edge_events section 经 apply_score_extraction 真出口落库。"""
    db, state, content = game
    before = {int(r["id"]) for r in db.get_relation_edge_events()}
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [{
                "施动者": "毕自严", "受动者": "王绍徽", "类目": "使绊",
                "语境": "#642 DoD 面4 真 extractor 路径示踪。",
                "来源引用": "盘面自发",
            }],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    assert not any(r.get("rejected") for r in res), res
    rows = [
        r for r in db.get_relation_edge_events(source="毕自严", target="王绍徽")
        if int(r["id"]) not in before
    ]
    assert len(rows) == 1
    assert rows[0]["event_kind"] == "使绊"
    assert rows[0]["context"] == "#642 DoD 面4 真 extractor 路径示踪。"
    assert MODULE_FIELDS["relations"] == {"relation_edge_events"}
    assert "relation_edge_events" in EMPTY_EXTRACTION


# ── R1 双表面：边事件 + 摘要 restore ────────────────────────────────


def test_r1_edges_and_summaries_survive_reopen(game):
    """R1：边/摘要提交后重开 DB 逐字段一致（扩既有 restore 点检到双表面）。"""
    db, state, _ = game
    db.record_relation_edge_event(
        source="温体仁", target="周延儒", event_kind="结怨",
        context="当殿讦奏。", origin="audience:r1",
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    last_id = db.get_relation_edge_events(source="温体仁", target="周延儒")[-1]["id"]
    db.apply_relation_brew_result(
        source="温体仁", target="周延儒", dimension="大臣",
        founding_segment="温周初隙。",
        recent_segment="朝堂侧目。",
        last_event_id=last_id,
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    edge = db.get_relation_edge_events(source="温体仁", target="周延儒")[0]
    summary = db.get_relation_summary("温体仁", "周延儒")
    path = db.path
    db.close()
    reopened = GameDB(path)
    edge2 = reopened.get_relation_edge_events(source="温体仁", target="周延儒")[0]
    summary2 = reopened.get_relation_summary("温体仁", "周延儒")
    for key in (
        "source", "target", "event_kind", "context", "origin",
        "year", "period", "turn",
    ):
        assert edge2[key] == edge[key]
    for key in (
        "founding_segment", "recent_segment", "last_event_id",
        "last_brewed_year", "last_brewed_period", "dimension",
    ):
        assert summary2[key] == summary[key]
    reopened.close()


# ── 文档契约机械钉（P-4）────────────────────────────────────────────


def test_settlement_flow_documents_relation_brew_leg_order():
    text = (ROOT / "docs" / "SETTLEMENT_FLOW.md").read_text(encoding="utf-8")
    assert "MonthEndRelationBrewLeg" in text
    assert "settle_with_delta" in text
    assert "认领" in text
    assert "persist" in text
    assert "pending" in text


def test_delta_schema_relation_edge_events_matches_minister_kinds():
    text = (ROOT / "docs" / "DELTA_SCHEMA.md").read_text(encoding="utf-8")
    assert "relation_edge_events" in text
    for kind in sorted(MINISTER_EDGE_KINDS):
        assert kind in text
    brew_docs = (ROOT / "docs" / "SETTLEMENT_FLOW.md").read_text(encoding="utf-8")
    # 文档必须明文禁止输出字数 clamp（P-0 / P6），不得写成实现要求。
    assert "禁止" in brew_docs and "字数 clamp" in brew_docs
