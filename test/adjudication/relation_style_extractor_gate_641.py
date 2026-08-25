"""#641 bare-seam live gate: relation-only gazette → edge, not style.

Not ordinary CI. Ordinary canned edge→apply suite cannot reach the real
extractor role boundary (personnel must not put relations into style;
relations owns edge events). This gate is the single durable re-run entry.

  MING_SIM_TRACE_PATH=/tmp/issue-641-trace-$$.jsonl \\
  MING_SIM_TRACE_CAP=500000 \\
    python test/adjudication/relation_style_extractor_gate_641.py \\
      --runner <gate-runner> --model <model> \\
      --output docs/evidence/issue-641-relation-only-extractor.json

claim_scope is always single_observed_pass. Do not call one pass \"stable\".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agno.db.sqlite import SqliteDb

from ming_sim.agents import (
    bind_content as bind_agent_content,
    create_json_sanitizer_agent,
    create_score_extractor_module_agent,
)
from ming_sim.cli_backend import (
    add_gate_llm_args,
    gate_evidence_config,
    gate_llm_config_from_args,
    require_fresh_cli_trace,
)
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.issues import apply_score_extraction, bind_content as bind_issue_content
from ming_sim.models import LLMConfig
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_extractor_shared_context,
    build_simulator_payload,
    extract_scores_by_modules_with_agno,
)
import ming_sim.simulation as simulation_mod

SOURCE = "毕自严"
TARGET = "王绍徽"
# Pure interpersonal friction: no appointment / disposition / assessment /
# bereavement / inherent-layer rewrite triggers. Wording is not locked.
SCENARIO_NARRATIVE = (
    f"本月邸报：户部尚书{SOURCE}核销用度时屡次驳回吏部尚书{TARGET}所请拨付，"
    f"{TARGET}因此衔恨，二人在朝会议事时互相掣肘使绊，声气不通。"
    "本月未见任免、处置、评定或丧亲破胆等人事固有层变故。"
)
MINISTER_EDGE_KINDS = frozenset({
    "荐引", "恩义", "结怨", "站台", "使绊", "联名", "连坐", "把柄", "协作",
})


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#641 relation-only extractor bare-seam live gate",
    )
    add_gate_llm_args(parser)
    parser.add_argument(
        "--output",
        required=True,
        help="Evidence JSON path (typically docs/evidence/issue-641-relation-only-extractor.json)",
    )
    return parser.parse_args()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            text=True,
        ).strip()
    except Exception as exc:  # noqa: BLE001 — evidence field, not control flow
        return f"unavailable:{exc}"


def _style_of(db: GameDB, content: GameContent, name: str) -> str:
    row = db.conn.execute(
        "SELECT style FROM characters WHERE name=?", (name,),
    ).fetchone()
    db_style = str(row["style"] if row is not None else "")
    rt = content.characters[name].style if name in content.characters else ""
    if db_style != rt:
        raise RuntimeError(f"style desync for {name}: db={db_style!r} rt={rt!r}")
    return db_style


def _pair_edge_rows(db: GameDB, a: str, b: str) -> List[Dict[str, Any]]:
    forward = db.get_relation_edge_events(source=a, target=b)
    reverse = db.get_relation_edge_events(source=b, target=a)
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in forward + reverse:
        by_id[int(row["id"])] = dict(row)
    return [by_id[i] for i in sorted(by_id)]


def _edge_ids(rows: List[Dict[str, Any]]) -> Set[int]:
    return {int(r["id"]) for r in rows}


def _person_change_actions(merged: Dict[str, Any]) -> List[str]:
    items = merged.get("人物变更")
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for item in items:
        if isinstance(item, dict):
            action = item.get("动作")
            if action is not None:
                out.append(str(action))
    return out


def _endpoint_name(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        names = [str(x).strip() for x in value if str(x).strip()]
        return names[0] if len(names) == 1 else None
    return None


def _merged_pair_events(
    merged: Dict[str, Any], a: str, b: str,
) -> List[Dict[str, Any]]:
    """Return relation_edge_events items whose endpoints are exactly {a,b}."""
    items = merged.get("relation_edge_events")
    if not isinstance(items, list):
        # localized key may still be present if merge skipped alias (defensive)
        items = merged.get("大臣互动")
    if not isinstance(items, list):
        return []
    hits: List[Dict[str, Any]] = []
    pair = {a, b}
    for item in items:
        if not isinstance(item, dict):
            continue
        src = _endpoint_name(item.get("施动者") if "施动者" in item else item.get("source"))
        tgt_raw = item.get("受动者") if "受动者" in item else item.get("target")
        kind = item.get("类目") if "类目" in item else item.get("event_kind")
        if isinstance(tgt_raw, list):
            targets = [str(x).strip() for x in tgt_raw if str(x).strip()]
        elif isinstance(tgt_raw, str) and tgt_raw.strip():
            targets = [tgt_raw.strip()]
        else:
            targets = []
        if src is None or not targets:
            continue
        for tgt in targets:
            if {src, tgt} == pair and str(kind or "") in MINISTER_EDGE_KINDS:
                hits.append(dict(item))
                break
    return hits


def _accepted_pair_resolutions(
    resolutions: List[Dict[str, Any]], a: str, b: str,
) -> List[Dict[str, Any]]:
    pair = {a, b}
    out: List[Dict[str, Any]] = []
    for row in resolutions:
        if not isinstance(row, dict):
            continue
        if row.get("rejected"):
            continue
        src = str(row.get("source") or "").strip()
        tgt = str(row.get("target") or "").strip()
        if {src, tgt} == pair:
            out.append(row)
    return out


def _link_capture_to_trace(
    capture: Dict[str, Any],
    trace_records: List[Dict[str, Any]],
    used_seqs: Set[int],
) -> Optional[Dict[str, Any]]:
    """Associate one caller-boundary capture with a generic extractor trace row."""
    full = str(capture.get("full_response") or "")
    resp_chars = int(capture.get("resp_chars") or 0)
    candidates = [
        r for r in trace_records
        if r.get("tag") == "extractor"
        and r.get("error") is None
        and int(r.get("seq") or -1) not in used_seqs
    ]
    # 1) exact full response match
    for r in candidates:
        if str(r.get("response") or "") == full:
            return {
                "trace_seq": int(r["seq"]),
                "match": "exact_response",
                "trace_truncated": False,
            }
    # 2) CAP-truncated: head+tail fragments inside full raw + resp_chars
    for r in candidates:
        tr = str(r.get("response") or "")
        truncated = "...[截断" in tr
        if not truncated:
            continue
        if int(r.get("resp_chars") or -1) != resp_chars:
            continue
        head, _, tail_part = tr.partition("...[截断")
        # tail_part like " N 字]...\n<tail>"
        tail = ""
        if "]..." in tail_part:
            tail = tail_part.split("]...", 1)[-1].lstrip("\n")
        head = head.rstrip("\n")
        if head and tail and head in full and tail in full:
            return {
                "trace_seq": int(r["seq"]),
                "match": "cap_fragments_and_resp_chars",
                "trace_truncated": True,
            }
    # 3) untruncated equal-length prefix equality (resp_chars match + response prefix)
    for r in candidates:
        tr = str(r.get("response") or "")
        if "...[截断" in tr:
            continue
        if int(r.get("resp_chars") or -1) != resp_chars:
            continue
        if full and tr and (full == tr or full.startswith(tr) or tr.startswith(full[: min(200, len(full))])):
            return {
                "trace_seq": int(r["seq"]),
                "match": "resp_chars_and_prefix",
                "trace_truncated": False,
            }
    return None


def _install_run_agent_text_capture() -> Tuple[Dict[str, Dict[str, Any]], Any]:
    """Wrap simulation.run_agent_text (the binding _run_raw resolves)."""
    orig = simulation_mod.run_agent_text
    capture: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()
    ordinal = {"n": 0}

    def wrapped(agent: Any, prompt: str, tag: str) -> str:
        t0 = time.time()
        text = orig(agent, prompt, tag)
        with lock:
            ordinal["n"] += 1
            seq_or_ordinal = ordinal["n"]
            capture[str(tag)] = {
                "full_response": text,
                "prompt_chars": len(prompt or ""),
                "resp_chars": len(text or ""),
                "seq_or_ordinal": seq_or_ordinal,
                "wall_ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            }
        return text

    simulation_mod.run_agent_text = wrapped  # type: ignore[assignment]
    return capture, orig


def _restore_run_agent_text(orig: Any) -> None:
    simulation_mod.run_agent_text = orig  # type: ignore[assignment]


def _load_trace_records(trace_path: Optional[Path]) -> List[Dict[str, Any]]:
    if trace_path is None or not trace_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _public_trace_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        if r.get("tag") != "extractor":
            continue
        out.append({
            "seq": r.get("seq"),
            "ts": r.get("ts"),
            "backend": r.get("backend"),
            "model_id": r.get("model_id"),
            "prompt_chars": r.get("prompt_chars"),
            "resp_chars": r.get("resp_chars"),
            "error": r.get("error"),
            "response": r.get("response"),
            "tag": r.get("tag"),
        })
    return out


def run_gate(args: argparse.Namespace) -> Dict[str, Any]:
    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    cfg: LLMConfig = gate_llm_config_from_args(args)
    trace_path = require_fresh_cli_trace(cfg)

    module_raw_capture: Dict[str, Dict[str, Any]] = {}
    orig_run = None
    evidence: Dict[str, Any]

    with tempfile.TemporaryDirectory(prefix="ming-641-gate-") as tmp:
        tmp_path = Path(tmp)
        db = GameDB(str(tmp_path / "game.db"), content)
        try:
            db.seed_static_data()
            state = db.load_state()
            styles_before = {
                SOURCE: _style_of(db, content, SOURCE),
                TARGET: _style_of(db, content, TARGET),
            }
            temperament_logs_before = int(db.conn.execute(
                "SELECT COUNT(*) AS c FROM person_logs WHERE action=?",
                ("性情",),
            ).fetchone()["c"])

            edge_rows_before = _pair_edge_rows(db, SOURCE, TARGET)
            ids_before = _edge_ids(edge_rows_before)
            edge_baseline = {
                "target_pair": {"source": SOURCE, "target": TARGET},
                "pair_note": "ordered pair names the scenario principals; accepted direction follows merged",
                "ids_before": sorted(ids_before),
                "count_before": len(ids_before),
            }

            simulator_payload = build_simulator_payload(
                state, db, decree_text="", previous_narrative="",
            )
            # #673: settle always supplies transit_semantics list.
            if "transit_semantics" not in simulator_payload:
                simulator_payload["transit_semantics"] = []

            extractor_shared_contexts = {
                module: build_extractor_shared_context(
                    db, state, SCENARIO_NARRATIVE, "",
                    module=module,
                    decree_dossiers=[],
                    transit_semantics=simulator_payload.get("transit_semantics") or [],
                )
                for module in EXTRACTION_MODULES
            }
            agno_db = SqliteDb(db_file=str(tmp_path / "agno.db"))
            sanitizer = create_json_sanitizer_agent(cfg, agno_db)
            extractors = {
                module: create_score_extractor_module_agent(
                    cfg,
                    agno_db,
                    module,
                    simulator_payload=simulator_payload,
                    supplemental_context=extractor_shared_contexts[module],
                )
                for module in EXTRACTION_MODULES
            }

            module_raw_capture, orig_run = _install_run_agent_text_capture()
            try:
                merged, _localized, _inputs = extract_scores_by_modules_with_agno(
                    extractors,
                    db,
                    state,
                    SCENARIO_NARRATIVE,
                    decree_text="",
                    sanitizer=sanitizer,
                    parallel=True,
                )
            finally:
                if orig_run is not None:
                    _restore_run_agent_text(orig_run)
                    orig_run = None

            if not isinstance(merged, dict):
                raise RuntimeError(f"extractor merged is not a dict: {type(merged)}")

            pair_events = _merged_pair_events(merged, SOURCE, TARGET)
            # Prefer ordered pair from first merged hit for baseline target_pair update
            applied_direction = None
            if pair_events:
                first = pair_events[0]
                src = _endpoint_name(first.get("施动者") if "施动者" in first else first.get("source"))
                tgt_raw = first.get("受动者") if "受动者" in first else first.get("target")
                if isinstance(tgt_raw, list) and tgt_raw:
                    tgt = str(tgt_raw[0]).strip()
                else:
                    tgt = _endpoint_name(tgt_raw)
                if src and tgt:
                    applied_direction = {"source": src, "target": tgt}
                    edge_baseline["target_pair"] = dict(applied_direction)
                    directed_before = db.get_relation_edge_events(source=src, target=tgt)
                    edge_baseline["ids_before"] = sorted(int(r["id"]) for r in directed_before)
                    edge_baseline["count_before"] = len(edge_baseline["ids_before"])
                    ids_before = set(edge_baseline["ids_before"])

            applied = apply_score_extraction(db, state, merged, content=content)
            resolutions = list(applied.get("relation_edge_event_resolutions") or [])
            accepted = _accepted_pair_resolutions(resolutions, SOURCE, TARGET)

            if applied_direction is not None:
                src = applied_direction["source"]
                tgt = applied_direction["target"]
                rows_after = db.get_relation_edge_events(source=src, target=tgt)
            else:
                rows_after = _pair_edge_rows(db, SOURCE, TARGET)
            ids_after = _edge_ids(rows_after)
            new_ids = sorted(ids_after - ids_before)
            count_after = len(ids_after)

            styles_after = {
                SOURCE: _style_of(db, content, SOURCE),
                TARGET: _style_of(db, content, TARGET),
            }
            temperament_logs_after = int(db.conn.execute(
                "SELECT COUNT(*) AS c FROM person_logs WHERE action=?",
                ("性情",),
            ).fetchone()["c"])
            person_actions = _person_change_actions(merged)
            has_temperament_action = "性情" in person_actions

            styles_unchanged = styles_after == styles_before
            no_temperament_logs = temperament_logs_after == temperament_logs_before
            edge_delta_ok = (
                bool(pair_events)
                and bool(accepted)
                and bool(new_ids)
                and count_after == edge_baseline["count_before"] + len(new_ids)
            )
            # New rows correspond to accepted resolutions by edge_id when present.
            accepted_edge_ids = {
                int(r["edge_id"]) for r in accepted if r.get("edge_id") is not None
            }
            new_rows = [r for r in rows_after if int(r["id"]) in set(new_ids)]
            if accepted_edge_ids:
                edge_ids_match_accepted = set(new_ids) == accepted_edge_ids or accepted_edge_ids.issubset(set(new_ids))
            else:
                edge_ids_match_accepted = bool(new_ids) and bool(accepted)

            # Fresh CLI trace + linkage
            trace_records = _load_trace_records(trace_path)
            public_trace = _public_trace_records(trace_records)
            expected_tags = [f"extractor/{m}" for m in EXTRACTION_MODULES]
            linkage: List[Dict[str, Any]] = []
            used_seqs: Set[int] = set()
            linkage_ok = True
            critical_tags = ("extractor/personnel_secret", "extractor/relations")
            for tag in expected_tags:
                cap = module_raw_capture.get(tag)
                if cap is None:
                    linkage.append({
                        "caller_tag": tag,
                        "linked": False,
                        "reason": "missing_caller_capture",
                    })
                    if tag in critical_tags:
                        linkage_ok = False
                    continue
                link = _link_capture_to_trace(cap, trace_records, used_seqs)
                if link is None:
                    linkage.append({
                        "caller_tag": tag,
                        "linked": False,
                        "reason": "no_unique_trace_association",
                        "resp_chars": cap.get("resp_chars"),
                    })
                    if tag in critical_tags:
                        linkage_ok = False
                    continue
                used_seqs.add(int(link["trace_seq"]))
                # Critical modules: truncated without unique link already failed above;
                # if truncated but linked via fragments, still ok per plan.
                linkage.append({
                    "caller_tag": tag,
                    "linked": True,
                    **link,
                })

            # Require all five module captures present (production shape)
            all_modules_captured = all(
                f"extractor/{m}" in module_raw_capture for m in EXTRACTION_MODULES
            )

            checks = {
                "no_temperament_in_merged_person_changes": not has_temperament_action,
                "styles_unchanged": styles_unchanged,
                "no_new_temperament_person_logs": no_temperament_logs,
                "merged_has_pair_relation_edge_events": bool(pair_events),
                "accepted_pair_resolution": bool(accepted),
                "edge_id_delta_nonempty": bool(new_ids),
                "edge_count_matches_new_ids": (
                    count_after == edge_baseline["count_before"] + len(new_ids)
                ),
                "new_ids_correspond_to_accepted": edge_ids_match_accepted,
                "all_modules_raw_captured": all_modules_captured,
                "critical_raw_trace_linkage": linkage_ok,
                "edge_write_proven": edge_delta_ok and edge_ids_match_accepted,
            }
            checks["passed"] = all(checks.values())

            evidence = {
                "gate": (
                    "issue-641-relation-only-extractor-bare-seam"
                    " (test/adjudication/relation_style_extractor_gate_641.py)"
                ),
                "claim_scope": "single_observed_pass",
                "git_head": _git_head(),
                "config": gate_evidence_config(args, cfg),
                "scenario": {
                    "narrative": SCENARIO_NARRATIVE,
                    "principals": [SOURCE, TARGET],
                    "styles_before": styles_before,
                },
                "edge_baseline": edge_baseline,
                "module_raw_capture": module_raw_capture,
                "fresh_trace": {
                    "path": str(trace_path) if trace_path is not None else None,
                    "records": public_trace,
                    "linkage": linkage,
                },
                "extractor_output": {
                    "merged": merged,
                },
                "apply": {
                    "relation_edge_event_resolutions": resolutions,
                    "accepted_pair_resolutions": accepted,
                    "new_edge_ids": new_ids,
                    "new_edge_rows": [
                        {
                            "id": int(r["id"]),
                            "source": r.get("source"),
                            "target": r.get("target"),
                            "event_kind": r.get("event_kind"),
                            "context": r.get("context"),
                        }
                        for r in new_rows
                    ],
                    "styles_before": styles_before,
                    "styles_after": styles_after,
                    "temperament_log_count_before": temperament_logs_before,
                    "temperament_log_count_after": temperament_logs_after,
                    "person_change_actions_in_merged": person_actions,
                    "count_after": count_after,
                },
                "checks": checks,
            }
        finally:
            if orig_run is not None:
                _restore_run_agent_text(orig_run)
            db.close()

    return evidence


def main() -> int:
    args = _args()
    evidence = run_gate(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "output": str(output),
        "claim_scope": evidence.get("claim_scope"),
        "checks": evidence.get("checks"),
        "new_edge_ids": (evidence.get("apply") or {}).get("new_edge_ids"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if (evidence.get("checks") or {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
