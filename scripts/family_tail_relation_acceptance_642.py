"""Live #642 family-tail relation acceptance anchors (P-1 闸级语义面).

Not ordinary CI: requires an explicitly selected live CLI/API provider.

  MING_SIM_TRACE_PATH=/tmp/issue-642-acceptance-trace.jsonl \
    python scripts/family_tail_relation_acceptance_642.py \
      --runner codex --model gpt-5.6-sol --samples 1 \
      --output docs/evidence/issue-642-acceptance-anchors.json

  # 默认 ds-flash 档（api）：
  # MING_SIM_API_KEY=... MING_SIM_API_BASE_URL=https://opencode.ai/zen/v1 \
  #   python scripts/family_tail_relation_acceptance_642.py --channel api \
  #     --model deepseek-v4-flash --samples 1 \
  #     --output docs/evidence/issue-642-acceptance-ds-flash.json

Anchors (independent --anchor select; default=all):
  seed  — ① 魏忠贤场 seed 网「可剪菜单」语义
  yang  — ② 杨嗣昌三拍真实生产单链（读面→召对→判官→settle brew）
  coda  — ④ prior_events 机械回声（typed；语义面不另付费）

Assertions on free text: none (P6/0142). Semantic verdicts are LLM-judge structured
fields only (pass/fail + method/summary/limitations/raw pointers).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agno.agent import Agent

from ming_sim.agents import run_agent_text
from ming_sim.cli_backend import (
    add_gate_llm_args,
    gate_evidence_config,
    gate_llm_config_from_args,
    require_fresh_cli_trace,
)
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.decree import _make_relation_brew_runner, settle_with_delta
import ming_sim.issues as issues_mod
from ming_sim.llm_model import create_chat_model
from ming_sim.models import LLMConfig
from ming_sim.relation_brew import build_brew_input
from ming_sim.relation_judge import (
    PreparedRelationJudge,
    finalize_summon_relation_judge,
    invoke_summon_relation_judge_provider,
    prepare_summon_relation_judge,
    summon_edge_origin,
)
from ming_sim.relation_read import load_relation_history_before, project_relation_ledger
from ming_sim.relations import EDGE_KINDS, EMPEROR_NODE
from ming_sim.session import GameSession

_LOG = logging.getLogger("issue-642-acceptance")
_ANCHORS = ("seed", "yang", "coda")

# 三拍玩家话语（fixture only）——素材取自 AUDIENCE_NORTH_STAR 连读三档；
# 不短路写边/摘要，只驱动真实召对入口。
_YANG_BEAT_UTTERANCES: Tuple[Dict[str, Any], ...] = (
    {
        "beat": 1,
        "label": "越次召对",
        "minister": "杨嗣昌",
        "utterance": (
            "宣杨嗣昌入对。太仓见底，盐课与清丈当如何动？"
            "谁可撑住说情的条子？朕意先令倪元璐、黄道周试点畿辅清丈，"
            "卿以户部郎中越次接应钱粮文书——这差事，朕记下了。"
        ),
    },
    {
        "beat": 2,
        "label": "一刚一柔·问配合",
        "minister": "杨嗣昌",
        "utterance": (
            "畿辅清丈一月：倪黄刚直硬顶，士绅抱团抗丈，细缝已现。"
            "卿献分化之策，与二公路线不同。如何与倪元璐、黄道周配合，"
            "既让清流攻坚、又不把缝隙撕成决裂，卿可有主意？"
        ),
    },
    {
        "beat": 3,
        "label": "委任加重",
        "minister": "杨嗣昌",
        "utterance": (
            "一刚一柔之议朕准了。清丈见你接应得力，朕加重委任："
            "隐田归属、屯田接应与钱粮调度仍归卿盯着，与倪黄各对朕负责。"
            "旧隙不必抹平，事要办成。"
        ),
    },
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_gate_llm_args(parser)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--anchor",
        action="append",
        choices=_ANCHORS,
        default=None,
        help="Run only selected anchor(s); repeatable. Default=all.",
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if not args.anchor:
        args.anchor = list(_ANCHORS)
    return args


def _config(args: argparse.Namespace) -> LLMConfig:
    return gate_llm_config_from_args(args)


def _fresh_session(content: GameContent, cfg: LLMConfig) -> GameSession:
    tmp = tempfile.mkdtemp(prefix="issue-642-")
    dbp = str(Path(tmp) / "gate.db")
    return GameSession(db_path=dbp, llm_config=cfg, content=content)


def _llm_json_verdict(cfg: LLMConfig, prompt: str, *, tag: str) -> Dict[str, Any]:
    """Ask live model for a structured pass/fail verdict JSON object."""
    agent = Agent(
        name="#642 关系锚语义判官",
        id="issue-642-relation-anchor-judge",
        model=create_chat_model(cfg, temperature=0.2, force_json_output=True),
        instructions=[
            "你是关系账验收语义判官。只依据调用方给出的结构化账本/事件/酿制输入作答。",
            "禁止引用未提供的史实长文；禁止输出 JSON 以外的解释。",
            "严格按本次 prompt 给出的 JSON 契约输出唯一 object。",
        ],
        add_history_to_context=False,
        markdown=False,
    )
    raw = run_agent_text(agent, prompt, tag=tag)
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no json object")
        parsed = json.loads(raw[start : end + 1])
    except Exception as exc:
        return {
            "pass": False,
            "reason": f"verdict parse failed: {exc}",
            "raw_excerpt": raw[:800],
        }
    ok = bool(parsed.get("pass") is True or parsed.get("passed") is True)
    return {
        "pass": ok,
        "reason": str(parsed.get("reason") or parsed.get("summary") or ""),
        "raw_excerpt": raw[:800],
        "parsed": parsed,
    }


def _dto_keys_ok(face: List[Dict[str, Any]]) -> bool:
    wanted = {"source", "target", "summary", "recent_context", "updated_at_period"}
    return all(set(d.keys()) == wanted for d in face)


def _run_seed_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    sess = _fresh_session(content, cfg)
    try:
        face = project_relation_ledger(sess.db, viewer=None)
        wei = [d for d in face if "魏忠贤" in (d["source"], d["target"])]
        mechanical = {
            "ledger_rows": len(face),
            "wei_related_rows": len(wei),
            "dto_keys_ok": _dto_keys_ok(face),
        }
        ledger_blob = json.dumps(wei or face[:20], ensure_ascii=False, indent=2)
        prompt = (
            "你是明史关系网判官。下面是开局关系账只读投影（五字段 DTO）。\n"
            "不要引用你记忆中的史实长文；只根据给定账本回答。\n"
            "问题：若皇帝要在「剪刀之夜」处置魏忠贤及其党羽，账本是否提供了可剪的"
            "网状线索（恩义/把柄/荐引/结怨等可读边）？\n"
            "只输出 JSON：{\"pass\": true|false, \"reason\": \"...\", "
            "\"menu_hints\": [\"...\"]}\n\n"
            f"账本：\n{ledger_blob}\n"
        )
        verdict = _llm_json_verdict(cfg, prompt, tag="issue-642-anchor-seed")
        return {
            "anchor": "seed",
            "mechanical": mechanical,
            "semantic": verdict,
            "checks": {
                "mechanical_dto": mechanical["dto_keys_ok"] and mechanical["wei_related_rows"] > 0,
                "semantic_pass": bool(verdict.get("pass")),
            },
        }
    finally:
        sess.close()


def _production_summon_turn(
    sess: GameSession,
    *,
    minister: str,
    utterance: str,
) -> Dict[str, Any]:
    """真实 session/CLI 召对缝：attach → scene → chat → persist minister reply。"""
    from ming_sim.audience_night import attach_chat_turn_to_night

    db, state = sess.db, sess.state
    accepted_turn = int(state.turn)
    rollback_snapshot = db.capture_chat_rollback_snapshot()
    _night_id, chat_turn_id = attach_chat_turn_to_night(
        db,
        state,
        minister,
        agno_session_id=f"gate642:{minister}",
        agno_runs_before=0,
        beat_generator=None,
    )
    # 气氛 scene 非本锚契约：不 start_chat_turn_scene（避免无 generator 时 join 炸，
    # 也不另启平行气氛 LLM）。召对主链=chat + persist_minister_reply。
    user_message_id = db.append_chat_message(
        minister, accepted_turn, "user", utterance,
    )
    db.update_chat_turn_messages(int(chat_turn_id), user_message_id=int(user_message_id))
    try:
        result = sess.chat(minister, utterance, chat_turn_id=int(chat_turn_id))
        answer = str(getattr(result, "answer", "") or "")
        db.persist_minister_reply(
            minister, accepted_turn, answer, int(chat_turn_id),
        )
        db.record_chat_turn_rollback_diffs(
            int(chat_turn_id),
            rollback_snapshot or {},
            db.capture_chat_rollback_snapshot(),
        )
    except BaseException:
        try:
            db.fail_chat_turn(int(chat_turn_id))
        except Exception:
            _LOG.exception("summon turn cleanup failed chat_turn_id=%s", chat_turn_id)
        raise
    return {
        "chat_turn_id": int(chat_turn_id),
        "night_id": int(_night_id or 0),
        "minister": minister,
        "user_message_id": int(user_message_id),
        "answer_chars": len(answer),
        "turn": accepted_turn,
        "year": int(state.year),
        "period": int(state.period),
    }


def _court_roster_names(sess: GameSession) -> set[str]:
    """与收夜 production 传入 prepare 的 source_night_roster 同形：当前朝堂名册。"""
    names: set[str] = set()
    for row in sess.db.current_court_roster_rows(sess.state):
        name = str(row["name"] if "name" in row.keys() else "")
        if name:
            names.add(name)
    return names


def _run_summon_relation_judge_phases(
    sess: GameSession,
    cfg: LLMConfig,
    *,
    write_gate: threading.Lock,
) -> Dict[str, Any]:
    """既有 prepare → invoke → finalize 单链（不另造平行 judge）。

    allowed_endpoint_names 对齐 audience_night 收夜扫尾：传入朝堂名册，避免 night 批
    仅 persons_entered_tonight 时把未入殿但对话点名的朝臣端点全部拒写。
    """
    prepared = prepare_summon_relation_judge(
        sess.db,
        sess.state,
        write_gate=write_gate,
        allowed_endpoint_names=_court_roster_names(sess),
    )
    if not isinstance(prepared, PreparedRelationJudge):
        return dict(prepared) if isinstance(prepared, dict) else {"skipped": "not_prepared"}
    provider_result = invoke_summon_relation_judge_provider(
        prepared, llm_config=cfg,
    )
    return finalize_summon_relation_judge(
        prepared, provider_result, write_gate=write_gate,
    )


def _settle_with_brew(sess: GameSession, content: GameContent, cfg: LLMConfig) -> Dict[str, Any]:
    """月末 settle_with_delta 既有酿制腿（生产注入工厂）。"""
    before_turn = int(sess.state.turn)
    before_year = int(sess.state.year)
    before_period = int(sess.state.period)
    report = settle_with_delta(
        sess.state,
        sess.db,
        {},
        before_turn=before_turn,
        content=content,
        registry=sess.registry,
        relation_brew_runner=_make_relation_brew_runner(cfg, sess.agno_db),
    )
    sess.begin_turn()
    return {
        "settled_turn": before_turn,
        "settled_year": before_year,
        "settled_period": before_period,
        "after_turn": int(sess.state.turn),
        "report_chars": len(str(report or "")),
    }


def _edge_pointer(row: Dict[str, Any]) -> Dict[str, Any]:
    ctx = str(row.get("context") or "")
    return {
        "id": int(row["id"]),
        "source": row["source"],
        "target": row["target"],
        "event_kind": row["event_kind"],
        "origin": row.get("origin"),
        "turn": row.get("turn"),
        "year": row.get("year"),
        "period": row.get("period"),
        "context": ctx,
        "context_chars": len(ctx),
    }


def _summary_pointer(db: Any, source: str, target: str) -> Optional[Dict[str, Any]]:
    row = db.get_relation_summary(source, target)
    if not row:
        return None
    founding = str(row.get("founding_segment") or "")
    recent = str(row.get("recent_segment") or "")
    return {
        "source": source,
        "target": target,
        "founding_segment": founding,
        "recent_segment": recent,
        "founding_chars": len(founding),
        "recent_chars": len(recent),
        "updated_at_period": row.get("updated_at_period"),
    }


def _chat_turn_pointer(db: Any, chat_turn_id: int) -> Dict[str, Any]:
    """语义裁判用的源轮指针：含问/答原文（非断言锁词，只作证据载荷）。"""
    row = db.conn.execute(
        "SELECT id, minister_name, user_message_id, minister_message_id, turn, night_id "
        "FROM chat_turns WHERE id = ?",
        (int(chat_turn_id),),
    ).fetchone()
    if row is None:
        return {"chat_turn_id": int(chat_turn_id), "missing": True}

    def _msg(mid: Any) -> str:
        mid_i = int(mid or 0)
        if mid_i <= 0:
            return ""
        m = db.conn.execute(
            "SELECT content FROM chat_messages WHERE id = ?", (mid_i,),
        ).fetchone()
        return str(m["content"] if m is not None else "")

    return {
        "chat_turn_id": int(row["id"]),
        "minister_name": row["minister_name"],
        "turn": row["turn"],
        "night_id": row["night_id"],
        "user_message": _msg(row["user_message_id"]),
        "minister_message": _msg(row["minister_message_id"]),
    }


def _run_yang_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    """锚②最短生产单链 tracer：读面→真实召对→判官 prepare/invoke/finalize→settle brew。"""
    sess = _fresh_session(content, cfg)
    write_gate = threading.Lock()
    try:
        sess.begin_turn()
        beat_traces: List[Dict[str, Any]] = []
        all_chat_turn_ids: List[int] = []
        all_judge_written = 0
        settle_traces: List[Dict[str, Any]] = []

        for spec in _YANG_BEAT_UTTERANCES:
            minister = str(spec["minister"])
            face_before = project_relation_ledger(sess.db, viewer=minister)
            face_all = project_relation_ledger(sess.db, viewer=None)
            chat_meta = _production_summon_turn(
                sess, minister=minister, utterance=str(spec["utterance"]),
            )
            all_chat_turn_ids.append(int(chat_meta["chat_turn_id"]))
            judge_result = _run_summon_relation_judge_phases(
                sess, cfg, write_gate=write_gate,
            )
            written = list(judge_result.get("written") or [])
            all_judge_written += int(judge_result.get("edges") or len(written) or 0)
            settle_meta = _settle_with_brew(sess, content, cfg)
            settle_traces.append(settle_meta)
            origin_prefix = summon_edge_origin(int(chat_meta["chat_turn_id"]))
            events_after = [
                _edge_pointer(e)
                for e in sess.db.get_relation_edge_events()
                if str(e.get("origin") or "").startswith(origin_prefix)
            ]
            beat_traces.append({
                "beat": int(spec["beat"]),
                "label": spec["label"],
                "face_before": {
                    "viewer": minister,
                    "rows": len(face_before),
                    "dto_keys_ok": _dto_keys_ok(face_before),
                    "all_rows": len(face_all),
                    "pairs": [
                        {
                            "source": d["source"],
                            "target": d["target"],
                            "summary": d.get("summary") or "",
                            "recent_context": d.get("recent_context") or "",
                        }
                        for d in face_before
                    ],
                },
                "chat": {
                    **chat_meta,
                    **_chat_turn_pointer(sess.db, int(chat_meta["chat_turn_id"])),
                },
                "judge": {
                    "edges": judge_result.get("edges"),
                    "judged_turn_ids": judge_result.get("judged_turn_ids"),
                    "origins": judge_result.get("origins"),
                    "degraded": judge_result.get("degraded"),
                    "skipped": judge_result.get("skipped"),
                    "rejected_count": len(judge_result.get("rejected") or []),
                    "written": [
                        {
                            "source": w.get("source"),
                            "target": w.get("target"),
                            "event_kind": w.get("event_kind"),
                            "origin": w.get("origin"),
                            "edge_id": w.get("edge_id"),
                        }
                        for w in written
                    ],
                },
                "settle": settle_meta,
                "edges_from_this_turn": events_after,
            })

        events = sess.db.get_relation_edge_events()
        # 召对判官 origin 含 chat_turn 段（summon_edge_origin 形）。
        summon_origin_edges = [
            e for e in events if "|chat_turn:" in str(e.get("origin") or "")
        ]
        kind_ok = all(
            str(e.get("event_kind") or "") in EDGE_KINDS for e in summon_origin_edges
        )
        context_ok = all(str(e.get("context") or "").strip() for e in summon_origin_edges)
        summary_ptrs = [
            p for p in (
                _summary_pointer(sess.db, EMPEROR_NODE, "杨嗣昌"),
                _summary_pointer(sess.db, "杨嗣昌", "倪元璐"),
                _summary_pointer(sess.db, "倪元璐", "杨嗣昌"),
            )
            if p is not None
        ]
        structural = {
            "beat_count": len(beat_traces),
            "chat_turns_completed": len(all_chat_turn_ids) == 3 and all(
                int(b["chat"]["answer_chars"]) > 0 for b in beat_traces
            ),
            "judge_wrote_edges": all_judge_written > 0 and len(summon_origin_edges) > 0,
            "edge_kinds_controlled": kind_ok if summon_origin_edges else False,
            "edge_contexts_nonempty": context_ok if summon_origin_edges else False,
            "settles_completed": len(settle_traces) == 3,
            "face_dto_ok_each_beat": all(b["face_before"]["dto_keys_ok"] for b in beat_traces),
        }
        # 语义裁判只读真实链指针（chat-turn / edge / summary），不喂直写剧本。
        # 召对关系判官只产大臣↔大臣类目；君→杨的知遇/委任加深看三拍问答应酬与
        # 委任加重轨迹（生产上君臣类目另归 0079 写端，本链不伪造知遇边）。
        prompt = (
            "你是关系演化判官。下面是杨嗣昌三拍**真实生产链**留下的证据指针"
            "（召对轮问/答原文、判官落边、读面 DTO、月末酿制摘要），不是测试直写事件。\n"
            "判定标准：\n"
            "1) 君→杨：三拍皇帝问话与杨答是否呈越次接应→问配合→委任加重的定性加深"
            "（不必要求 DB 已有「知遇」类目边；君臣类目不由召对判官写）。\n"
            "2) 杨↔倪/黄：边事件+摘要是否呈配合/协作关系在读面后回写、逐拍演进，"
            "而非一次跳变抹平或完全无回写；若对话/边语境出现路线张力再配合，更佳，"
            "但不以必须先有「使绊」边为硬条件。\n"
            "3) 配合段闭环：至少一拍在读面后出现召对判官回写的新边。\n"
            "证据不足则 pass=false。\n"
            "只输出 JSON：{\"pass\": true|false, \"reason\": \"...\", "
            "\"jun_yang\": \"deeper|flat|regress|unclear\", "
            "\"yang_ni\": \"deepen_reconcile|jump|other|unclear\"}\n\n"
            f"beat_traces={json.dumps(beat_traces, ensure_ascii=False)}\n"
            f"summon_edges={json.dumps([_edge_pointer(e) for e in summon_origin_edges], ensure_ascii=False)}\n"
            f"summaries={json.dumps(summary_ptrs, ensure_ascii=False)}\n"
            f"all_event_ids={[int(e['id']) for e in events]}\n"
        )
        verdict = _llm_json_verdict(cfg, prompt, tag="issue-642-anchor-yang")
        return {
            "anchor": "yang",
            "structural": structural,
            "semantic": verdict,
            "chat_turn_ids": all_chat_turn_ids,
            "event_ids": [int(e["id"]) for e in events],
            "summon_edge_ids": [int(e["id"]) for e in summon_origin_edges],
            "summary_pointers": summary_ptrs,
            "beats": beat_traces,
            "settles": settle_traces,
            "checks": {
                "structural_ok": all(structural.values()),
                "semantic_pass": bool(verdict.get("pass")),
            },
        }
    finally:
        sess.close()


def _run_coda_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    """锚④机械面：prior_events 原句进 brew_input；语义不另付费（r2 P-5 可选）。"""
    del cfg  # 机械锚不调用活模型；保留签名以对齐 runners 映射。
    sess = _fresh_session(content, LLMConfig(api_key="x", base_url="http://x", model="x", channel="api"))
    try:
        db = sess.db
        founding = "越次一召，擢杨嗣昌于五品郎中。"
        db.record_relation_edge_event(
            source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
            context=founding, origin="gate642:founding",
            turn=0, year=1628, period=11,
        )
        db.record_relation_edge_event(
            source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
            context="多年后委以更大任。", origin="gate642:later",
            turn=80, year=1635, period=6,
        )
        prior = load_relation_history_before(
            db, source=EMPEROR_NODE, target="杨嗣昌",
            before_year=1635, before_period=6,
        )
        new_events = [
            e for e in db.get_relation_edge_events(
                source=EMPEROR_NODE, target="杨嗣昌",
            )
            if int(e["year"]) == 1635
        ]
        payload = build_brew_input(
            source=EMPEROR_NODE, target="杨嗣昌", dimension="君臣",
            year=1635, period=6, summary=None, new_events=new_events,
            has_pending=False, prior_events=prior,
        )
        mechanical = {
            "prior_has_founding": any(e["context"] == founding for e in payload["prior_events"]),
            "prior_byte_equal": any(e["context"] == founding for e in prior),
            "prior_count": len(payload["prior_events"]),
        }
        return {
            "anchor": "coda",
            "mechanical": mechanical,
            "checks": {
                "mechanical_ok": all(
                    mechanical[k] for k in ("prior_has_founding", "prior_byte_equal")
                ),
            },
        }
    finally:
        sess.close()


def _run_selected_anchors(
    names: List[str],
    cfg: LLMConfig,
    content: GameContent,
) -> Dict[str, Dict[str, Any]]:
    """顶层无依赖锚并行；请求顺序稳定投影。三拍内部依赖仍在 yang 内串行。"""
    runners = {
        "seed": _run_seed_anchor,
        "yang": _run_yang_anchor,
        "coda": _run_coda_anchor,
    }
    if len(names) == 1:
        name = names[0]
        return {name: runners[name](cfg, content)}

    workers = min(len(names), 3)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(runners[name], cfg, content): name
            for name in names
        }
        by_name: Dict[str, Dict[str, Any]] = {}
        for fut in as_completed(futures):
            name = futures[fut]
            by_name[name] = fut.result()
    return {name: by_name[name] for name in names}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = _args()
    cfg = _config(args)
    require_fresh_cli_trace(cfg)
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)

    samples: List[Dict[str, Any]] = []
    for i in range(args.samples):
        sample_anchors = _run_selected_anchors(list(args.anchor), cfg, content)
        checks: Dict[str, bool] = {}
        for name, result in sample_anchors.items():
            for ck, ok in result.get("checks", {}).items():
                checks[f"{name}.{ck}"] = bool(ok)
        samples.append({"sample": i + 1, "anchors": sample_anchors, "checks": checks})

    check_names = sorted(samples[0]["checks"])
    aggregate = {
        name: all(bool(s["checks"].get(name)) for s in samples)
        for name in check_names
    }
    failed = [name for name, ok in aggregate.items() if not ok]
    artifact = {
        "gate": "issue-642-family-tail-relation-acceptance",
        "method": {
            "design": (
                "Live production-chain tracer: seed semantic on seed ledger; "
                "yang = project_relation_ledger → session summon Q&A → "
                "prepare/invoke/finalize_summon_relation_judge → "
                "settle_with_delta brew leg ×3 beats; "
                "coda = typed prior_events mechanical only; "
                "independent top-level anchors run via ThreadPoolExecutor; "
                "no free-text regex; structured pass/fail only."
            ),
            "samples": args.samples,
            "anchors": list(args.anchor),
            "config": gate_evidence_config(args, cfg),
        },
        "summary": {
            "samples": args.samples,
            "checks": aggregate,
            "failed": failed,
            "passed": not failed,
        },
        "limitations": [
            "Semantic judge is one configured model; not population calibration.",
            "Anchor ③ structural + restore are CI pytest only (no live LLM required).",
            "Yang three-beat drives fixture player utterances only; minister reply, "
            "relation judge edges, and brew summaries come from the live production chain.",
            "Coda live semantic sampling omitted per r2 P-5; mechanical prior_events "
            "locked here and by pytest history/brew seams.",
        ],
        "samples": samples,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(
        {"output": str(output), "summary": artifact["summary"]},
        ensure_ascii=False, indent=2,
    ))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
