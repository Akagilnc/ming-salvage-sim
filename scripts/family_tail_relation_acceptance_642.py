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
  yang  — ② 杨嗣昌三拍加深/不跳变语义（读面+事件序列指针）
  coda  — ④ prior_events 回声进戏（可选语义；机械面由 pytest 锁）

Assertions on free text: none (P6/0142). Semantic verdicts are LLM-judge structured
fields only (pass/fail + method/summary/limitations/raw pointers).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

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
import ming_sim.issues as issues_mod
from ming_sim.llm_model import create_chat_model
from ming_sim.models import LLMConfig
from ming_sim.relation_brew import build_brew_input
from ming_sim.relation_read import load_relation_history_before, project_relation_ledger
from ming_sim.relations import EMPEROR_NODE
from ming_sim.session import GameSession

_LOG = logging.getLogger("issue-642-acceptance")
_ANCHORS = ("seed", "yang", "coda")


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
        # Strict-ish: find first JSON object.
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


def _run_seed_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    sess = _fresh_session(content, cfg)
    try:
        face = project_relation_ledger(sess.db, viewer=None)
        wei = [d for d in face if "魏忠贤" in (d["source"], d["target"])]
        mechanical = {
            "ledger_rows": len(face),
            "wei_related_rows": len(wei),
            "dto_keys_ok": all(
                set(d.keys())
                == {"source", "target", "summary", "recent_context", "updated_at_period"}
                for d in face
            ),
        }
        # 语义：不另喂史实长文，只据账本读面问「可剪菜单」类网状问题。
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


def _run_yang_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    """三拍结构序列 + 语义加深裁判（事件/摘要指针，不盯文）。"""
    sess = _fresh_session(content, cfg)
    try:
        db, state = sess.db, sess.state
        beats = []
        # 拍1：君→杨 知遇
        db.record_relation_edge_event(
            source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
            context="越次一召，擢杨嗣昌于五品郎中。",
            origin="gate642:beat1", turn=1, year=1628, period=11,
        )
        beats.append({"beat": 1, "kind": "知遇", "pair": [EMPEROR_NODE, "杨嗣昌"]})
        # 拍2：杨↔倪 细缝 + 读面
        db.record_relation_edge_event(
            source="杨嗣昌", target="倪元璐", event_kind="使绊",
            context="清丈议上路线分歧，细缝初现。",
            origin="gate642:beat2", turn=2, year=1628, period=11,
        )
        face2 = project_relation_ledger(db, viewer="杨嗣昌")
        beats.append({
            "beat": 2, "kind": "使绊", "pair": ["杨嗣昌", "倪元璐"],
            "readable_pairs": [(d["source"], d["target"]) for d in face2],
        })
        # 拍3：调和协作（不消除旧使绊）+ 君→杨 再深
        db.record_relation_edge_event(
            source="杨嗣昌", target="倪元璐", event_kind="协作",
            context="一刚一柔分工，当面调和而不抹去前隙。",
            origin="gate642:beat3a", turn=3, year=1628, period=12,
        )
        db.record_relation_edge_event(
            source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
            context="清丈委任加重，圣眷再深。",
            origin="gate642:beat3b", turn=3, year=1628, period=12,
        )
        beats.append({"beat": 3, "kinds": ["协作", "知遇"]})
        events = db.get_relation_edge_events()
        prompt = (
            "你是关系演化判官。下面是三拍边事件结构化序列（非玩家叙事）。\n"
            "判定：君→杨嗣昌知遇是否逐拍定性加深；杨↔倪细缝是否呈"
            "「苗头→细缝→调和而不消除」而非跳变抹平。\n"
            "只输出 JSON：{\"pass\": true|false, \"reason\": \"...\", "
            "\"jun_yang\": \"deeper|flat|regress\", \"yang_ni\": \"deepen_reconcile|jump|other\"}\n\n"
            f"beats={json.dumps(beats, ensure_ascii=False)}\n"
            f"events={json.dumps([{k: e[k] for k in ('source','target','event_kind','context','year','period') if k in e} for e in events], ensure_ascii=False)}\n"
        )
        verdict = _llm_json_verdict(cfg, prompt, tag="issue-642-anchor-yang")
        structural = {
            "beat_count": len(beats),
            "has_jun_yang_two_zhiyu": sum(
                1 for e in events
                if e["source"] == EMPEROR_NODE and e["target"] == "杨嗣昌"
                and e["event_kind"] == "知遇"
            ) >= 2,
            "has_yang_ni_tension_and_collab": (
                any(e["event_kind"] == "使绊" and e["source"] == "杨嗣昌" for e in events)
                and any(e["event_kind"] == "协作" and e["source"] == "杨嗣昌" for e in events)
            ),
            "old_tension_not_deleted": any(
                e["event_kind"] == "使绊" and {e["source"], e["target"]} == {"杨嗣昌", "倪元璐"}
                for e in events
            ),
        }
        return {
            "anchor": "yang",
            "structural": structural,
            "semantic": verdict,
            "event_ids": [int(e["id"]) for e in events],
            "checks": {
                "structural_ok": all(structural.values()),
                "semantic_pass": bool(verdict.get("pass")),
            },
        }
    finally:
        sess.close()


def _run_coda_anchor(cfg: LLMConfig, content: GameContent) -> Dict[str, Any]:
    sess = _fresh_session(content, cfg)
    try:
        db, state = sess.db, sess.state
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
        prompt = (
            "你是关系酿制读面观察者。下面是月末酿制输入 JSON（含 prior_events 完整历史）。\n"
            "判定：多年前奠基原句是否作为可回声语境出现在 prior_events 中"
            "（而非仅「恩义：深」式蒸馏残留）。\n"
            "只输出 JSON：{\"pass\": true|false, \"reason\": \"...\"}\n\n"
            f"brew_input={json.dumps(payload, ensure_ascii=False)}\n"
        )
        verdict = _llm_json_verdict(cfg, prompt, tag="issue-642-anchor-coda")
        return {
            "anchor": "coda",
            "mechanical": mechanical,
            "semantic": verdict,
            "checks": {
                "mechanical_ok": all(mechanical[k] for k in ("prior_has_founding", "prior_byte_equal")),
                "semantic_pass": bool(verdict.get("pass")),
            },
        }
    finally:
        sess.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = _args()
    cfg = _config(args)
    require_fresh_cli_trace(cfg)
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)

    runners = {
        "seed": _run_seed_anchor,
        "yang": _run_yang_anchor,
        "coda": _run_coda_anchor,
    }
    samples: List[Dict[str, Any]] = []
    for i in range(args.samples):
        sample_anchors = {}
        checks: Dict[str, bool] = {}
        for name in args.anchor:
            result = runners[name](cfg, content)
            sample_anchors[name] = result
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
                "Live LLM semantic judge on production read/brew seams; "
                "seed/yang/coda anchors independently selectable; "
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
            "Yang three-beat uses production write/read seams with fixture beats; "
            "full multi-month live summon chain is optional extension.",
            "Coda semantic is optional per r2; mechanical prior_events locked by pytest.",
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
