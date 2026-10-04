#!/usr/bin/env python3
"""One-off auditor for shard-2.jsonl → decisions TSV (human-reviewed dispositions)."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARD = Path(__file__).parent / "shard-2.jsonl"
OUT_TSV = Path(__file__).parent / "shard-2-decisions.tsv"
OUT_SUM = Path(__file__).parent / "shard-2-summary.txt"


def R(lens, file, line, fn, kind, disp, reason, src, sink):
    return {
        "lens": lens,
        "file": file,
        "line": str(line),
        "fn": fn,
        "kind": kind,
        "disposition": disp,
        "reason": reason,
        "source_field": src,
        "sink_contract": sink,
    }


def main() -> None:
    groups = [
        json.loads(line)
        for line in SHARD.read_text().splitlines()
        if line.strip()
    ]
    rows: list[dict[str, str]] = []

    def emit(g, member, disp, reason, src, sink):
        rows.append(
            R(
                g["lens"],
                g["file"],
                member["line"],
                g["fn"],
                member["kind"],
                disp,
                reason,
                src,
                sink,
            )
        )

    for g in groups:
        fn = g["fn"]
        file = g["file"]
        lens = g["lens"]
        members = g["members"]

        if fn == "_pending_person_changes_block_event_gate":
            for m in members:
                k, ln = m["kind"], int(m["line"])
                if ln == 3076:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=item.动作 → sink=overlay branch; closed {罢黜,处置} action enum",
                        "item.动作",
                        "dismissal_branch",
                    )
                elif ln == 3083:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=item.status → sink=skip when active; closed {active} sentinel",
                        "item.status",
                        "处置_active_skip",
                    )
                elif ln in (3094, 3131, 3160):
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=transition code → sink=skip reject; form-language reject: prefix",
                        "transition",
                        "reject_prefix_gate",
                    )
                elif ln == 3145:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=item.动作 → sink=appointment path; closed {任命,调任}",
                        "item.动作",
                        "appointment_branch",
                    )
                elif ln == 3162:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=row.power_id → sink=ming-only appoint gate; closed {empty,ming}",
                        "row.power_id",
                        "ming_power_gate",
                    )
                elif ln == 3122:
                    emit(
                        g,
                        m,
                        "KEEP_field_ref",
                        "source=new_power → sink=power_shadow_rows key membership; id registry",
                        "item.new_power",
                        "power_shadow_registry",
                    )
                else:
                    emit(g, m, "NEEDS_HUMAN", "unmapped member in gate fn", "", "")

        elif fn == "stage_grant_allocation_candidate":
            for m in members:
                ln = int(m["line"])
                if ln == 806:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=grant_action → sink=return 0; GRANT_ACTIONS−{无} closed registry",
                        "grant_action",
                        "GRANT_ACTIONS",
                    )
                elif ln == 845:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=shaped.amount key → sink=int(n); presence gate only",
                        "shaped.amount",
                        "amount_field",
                    )
                elif ln == 891:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=account → sink=staged.account; {国库,内库} enum",
                        "account",
                        "treasury_account_enum",
                    )
                elif ln == 893:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=cadence → sink=staged.cadence; {一次性,每月} enum",
                        "cadence",
                        "cadence_enum",
                    )

        elif fn == "run" and file == "scripts/play_as_emperor.py":
            for m in members:
                emit(
                    g,
                    m,
                    "FIX",
                    "source=prompt_hint/cli_chunk UI prose → sink=test harness branch; substring admission violates N10",
                    "prompt_hint|cli_chunk",
                    "structured_cli_phase",
                )

        elif fn == "persist_answers":
            for m in members:
                ln = int(m["line"])
                if ln == 39:
                    emit(
                        g,
                        m,
                        "KEEP_field_ref",
                        "source=decision_key → sink=open_keys set membership",
                        "choice.decision_key",
                        "open_keys",
                    )
                elif ln in (45, 48, 51):
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=action/dossier_decision → sink=validate against row.options closed set",
                        "choice.action",
                        "desk_option_enum",
                    )
                elif ln == 55:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=choice.label → sink=must match option labels from row; closed set",
                        "choice.label",
                        "option_label_enum",
                    )

        elif fn == "effect_origin_rejection":
            for m in members:
                ln = int(m["line"])
                if ln == 6868:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=origin_ref → sink=dossier id parse branch; dossier: form prefix",
                        "origin_ref",
                        "dossier_prefix_parse",
                    )
                elif ln == 6875:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=origin_ref → sink=affair id parse branch; affair: form prefix",
                        "origin_ref",
                        "affair_prefix_parse",
                    )

        elif fn == "_apply_decided_triad":
            for m in members:
                ln = int(m["line"])
                if ln == 1809:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=event_id → sink=raw_id after : split; colon form-language",
                        "event_id",
                        "namespaced_id_split",
                    )
                elif ln == 1819:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=decision token → sink=triad apply; closed {force_promulgated,withdrawn,hold}",
                        "decision",
                        "triad_decision_enum",
                    )

        elif fn == "<module>" and file == "web/src/components/chatModal.tsx":
            for m in members:
                k = m["kind"]
                ln = int(m["line"])
                if k == "filter_call" and ("status" in m["snip"] or ln in (218, 222)):
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=candidate.status → sink=roster filter; closed active/default enum",
                        "candidate.status",
                        "minister_active_roster",
                    )
                elif k == "filter_call" and (ln == 366 or "replyRetries" in m["snip"]):
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=retry.chat_turn_id → sink=match displayMessages; id equality not prose",
                        "retry.chat_turn_id",
                        "turn_id_join",
                    )
                elif k == "trim_call":
                    emit(
                        g,
                        m,
                        "KEEP_empty_check",
                        "source=input text → sink=send button disabled/CSS; empty gate only",
                        "input",
                        "composer_nonempty_gate",
                    )
                else:
                    emit(g, m, "NEEDS_HUMAN", "unmapped chatModal member", "", "")

        elif fn == "_dispatch_promises":
            for m in members:
                ln = int(m["line"])
                if ln == 2092:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=decision → sink=reject invalid; closed {应允,拒绝,修改,留中}",
                        "item.decision",
                        "promise_decision_enum",
                    )
                elif ln == 2121:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=declared_mode → sink=应允 validation; closed {ordinary,midzhi}",
                        "item.mode",
                        "dossier_mode_enum",
                    )

        elif fn == "<module>" and file == "web/src/reasoningSupport.ts":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=LLM baseUrl/model host strings → sink=reasoning capability flag; infra config not game prose admission",
                    "baseUrl|modelName",
                    "llm_provider_capability",
                )

        elif fn == "_apply_authority_change_item":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_empty_check",
                    "source=item op/privilege/scope fields → sink=strip then closed enum/SQL lookup; whitespace gate only before registry",
                    "item.动作|privilege|scope",
                    "authority_field_normalize",
                )

        elif fn == "_resolve_kind":
            for m in members:
                ln = int(m["line"])
                if ln == 284:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=obj.kind → sink=KNOWN_KINDS registry membership",
                        "obj.kind",
                        "KNOWN_KINDS",
                    )
                elif ln == 287:
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=动作类型 label → sink=LABEL_TO_KIND exact map",
                        "obj.动作类型",
                        "LABEL_TO_KIND",
                    )

        elif fn == "update_summon_travel_tone":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=ledger tags → sink=drop old tone tags; _SUMMON_TRAVEL_TONE_PREFIX form prefix",
                    "tags[]",
                    "tone_tag_replace",
                )

        elif fn == "stopped_covert_effect":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=origin → sink=early exit unless dossier: prefix; form-language id gate",
                    "origin",
                    "dossier_origin_gate",
                )

        elif fn == "append_decree_dossier_participants":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=lead dict → sink=location field; key presence optional passthrough",
                    "lead.location",
                    "optional_field_presence",
                )

        elif fn == "release_held_audience_knowledge":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_field_ref",
                    "source=memory id mid → sink=exclude/protection sets; id set membership",
                    "mid",
                    "exclude_set",
                )

        elif fn == "list_due_review_scenes":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_identity_or_formal",
                    "source=lane → sink=filter scenes; closed audience lane constants",
                    "lane",
                    "AUDIENCE_LANE_ENUM",
                )

        elif fn == "_canonical_issue_origin":
            for m in members:
                if "盘面自发" in m["snip"]:
                    emit(
                        g,
                        m,
                        "FIX",
                        "source=stored_ref non-dossier → sink=rewrite to 盘面自发; free-text origin transport rewrite forbidden N6",
                        "row.origin_ref",
                        "preserve_canonical_origin_forms",
                    )
                else:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=stored_ref → sink=dossier branch; dossier: prefix parse only",
                        "row.origin_ref",
                        "dossier_prefix_branch",
                    )

        elif fn == "dossier_id_in_origin":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=text origin → sink=parse dossier id; dossier: prefix gate",
                    "text",
                    "dossier_prefix_gate",
                )

        elif fn == "materialize_pay_order_decree":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=origin → sink=reject missing dossier body; dossier: prefix + non-empty id",
                    "origin",
                    "dossier_origin_validate",
                )

        elif fn == "declared_report_action_origin":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_structural",
                    "source=raw origin → sink=parse dossier-report namespace; form prefix branch",
                    "raw",
                    "dossier_report_prefix",
                )

        elif fn == "<module>" and file == "web/src/settleStream.ts":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_transport",
                    "source=SSE line → sink=event/data frame parse; wire protocol prefixes not game prose",
                    "line",
                    "sse_framing",
                )

        elif fn == "stage_punishment_candidate":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_empty_check",
                    "source=punish_action/issue_disposition → sink=strip whitespace before registry checks",
                    "punish_action|issue_disposition",
                    "punishment_field_gate",
                )

        elif fn == "_investigation_knowledge_known":
            for m in members:
                if m["kind"] == "strip_call":
                    emit(
                        g,
                        m,
                        "KEEP_empty_check",
                        "source=source/target names → sink=strip then SQL/tip equality; empty gate",
                        "source|target|tip.source",
                        "character_id_equality",
                    )
                else:
                    emit(g, m, "NEEDS_HUMAN", "unexpected kind in investigation known", "", "")

        elif fn == "resolve_commitment_origin_ref":
            for m in members:
                if m["kind"] == "strip_call":
                    emit(
                        g,
                        m,
                        "KEEP_empty_check",
                        "source=supplied_ref → sink=strip then prefix handlers; whitespace gate",
                        "supplied_ref",
                        "origin_normalize",
                    )
                else:
                    emit(
                        g,
                        m,
                        "KEEP_structural",
                        "source=supplied_ref → sink=dossier branch when dossier: prefix",
                        "supplied_ref",
                        "dossier_prefix_branch",
                    )

        elif fn == "apply_issue_inertia_and_ongoing":
            for m in members:
                if "fate.strip" in m["snip"] or "emperor_" in m["snip"]:
                    emit(
                        g,
                        m,
                        "NEEDS_HUMAN",
                        "jsonl line/snip not in fn body (scanner drift vs _declared_emperor_ending); re-anchor member",
                        "emperor_fate",
                        "declared_emperor_ending",
                    )
                elif m["kind"] == "strip_call":
                    emit(
                        g,
                        m,
                        "KEEP_empty_check",
                        "source=row.commitment_kind → sink=is_commitment bool; strip for empty gate",
                        "row.commitment_kind",
                        "commitment_kind_gate",
                    )
                else:
                    emit(g, m, "NEEDS_HUMAN", "unmapped apply_issue_inertia member", "", "")

        elif fn == "<module>" and file == "web/src/components/audienceArchiveModal.tsx":
            for m in members:
                if m["kind"] == "filter_call":
                    emit(
                        g,
                        m,
                        "KEEP_identity_or_formal",
                        "source=item.kind → sink=night list filter; closed kind=night enum",
                        "item.kind",
                        "history_turn_kind",
                    )
                else:
                    emit(
                        g,
                        m,
                        "KEEP_transport",
                        "source=involved_people[] → sink=UI join display; names passthrough not rewrite",
                        "night.involved_people",
                        "display_join",
                    )

        elif fn == "validate_season_option":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=FieldSpec.name → sink=required key in option dict; schema shape not prose",
                "spec.name",
                "option_schema_keys",
            )

        elif fn == "_sponsor_dismissed":
            emit(
                g,
                members[0],
                "KEEP_identity_or_formal",
                "source=character.status → sink=sponsor unavailable; closed PERSON_STATUSES offstage set",
                "status",
                "sponsor_inactive_statuses",
            )

        elif fn == "_normalize_settle_meta_defaults":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=default_key → sink=meta defaults dict key membership",
                "default_key",
                "settle_meta_defaults",
            )

        elif fn == "_resolve_one_urge_todo":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=candidate id → sink=grant/reject id sets; numeric id membership",
                "cid",
                "grant_reject_sets",
            )

        elif fn == "_snapshot_secret_order_people":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=character name/aliases → sink=participant match; identity set membership",
                "name|character.aliases",
                "character_identity_set",
            )

        elif fn == "knowledge_items_for_turn":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=item.name → sink=target_people filter; name id membership",
                "item.name",
                "target_people_set",
            )

        elif fn == "<module>" and file == "ming_sim/decree_vocabulary.py":
            emit(
                g,
                members[0],
                "KEEP_identity_or_formal",
                "source=dossier action type → sink=execution_surface policy; _DOSSIER_TERMINAL_ACTIONS registry",
                "action",
                "DOSSIER_TERMINAL_ACTIONS",
            )

        elif fn == "_auto_pay_arrears_by_priority":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=army row id → sink=order bucket; ARMY_SALARY_PRIORITY registry membership",
                "row.id",
                "ARMY_SALARY_PRIORITY",
            )

        elif fn == "_validate_event_dependency_graph_acyclic":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=dependency ids → sink=prune graph to known nodes; id set filter not prose",
                "dep",
                "graph_node_filter",
            )

        elif fn == "_pin_world_question_event_bindings":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=echoed event id → sink=binding pin; due_set/used id membership",
                "echoed",
                "due_set_used",
            )

        elif fn == "prune_auto_saves":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=auto-save filename → sink=turn bucket; regex _t(\\d+)_ form parse",
                "filename",
                "autosave_turn_parse",
            )

        elif fn == "_prepare_reconsideration_facts" and lens == "N10":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=named_opponent → sink=first_names roster membership",
                "named_opponent",
                "first_names_roster",
            )

        elif fn == "_require_active_minister":
            emit(
                g,
                members[0],
                "KEEP_field_ref",
                "source=minister_name → sink=content.characters dict key membership",
                "minister_name",
                "characters_registry",
            )

        elif fn == "_resolve_unique_active_authority":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=privilege → sink=strip before AUTHORITY_PRIVILEGE_SET lookup",
                "privilege",
                "privilege_registry_gate",
            )

        elif fn == "resolve_grant_account":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=grant_action → sink=strip before account resolver",
                "grant_action",
                "grant_account_resolver",
            )

        elif fn == "settle_applied_arrived_summons":
            emit(
                g,
                members[0],
                "KEEP_identity_or_formal",
                "source=transit_to/去向 → sink=accepted set; closed canonical beizhili id",
                "item.transit_to",
                "beizhili_arrival_token",
            )

        elif fn == "write_breach_plea_todo":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=breach_kind → sink=strip before typed todo write",
                "breach_kind",
                "breach_kind_gate",
            )

        elif fn == "_draft_intent_army_grounding_facts":
            emit(
                g,
                members[0],
                "KEEP_transport",
                "source=aliases[] → sink=LLM grounding fact line join; passthrough names not admission",
                "aliases",
                "grounding_fact_assembly",
            )

        elif fn == "_resolve_cli_bin":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=MING_SIM_TRACE env → sink=trace disabled flag; env token strip+closed {0,false,no}",
                "MING_SIM_TRACE",
                "trace_env_gate",
            )

        elif fn == "supported_cli_runners_text":
            emit(
                g,
                members[0],
                "KEEP_transport",
                "source=_CLI_BACKENDS registry → sink=help text join; sorted backend ids",
                "_CLI_BACKENDS",
                "cli_backend_list_display",
            )

        elif fn == "_apply_investigation_selection":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=tip.source → sink=strip before tip identity compare",
                "tip.source",
                "tip_source_identity",
            )

        elif fn == "_existing_edge_id":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=origin → sink=strip before edge id derivation",
                "origin",
                "origin_edge_key",
            )

        elif fn == "_normalize_dossier_mode":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=mode value → sink=strip then DOSSIER_MODES enum check",
                "mode",
                "DOSSIER_MODES",
            )

        elif fn == "army_report":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=_qualitative_army_stat label → sink=report fragment; removeprefix fixed 装备： form label only",
                "qualitative_stat",
                "report_label_strip",
            )

        elif fn == "list_next_audience_todos":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=SQL clauses[] → sink=WHERE assembly; structural join not prose rewrite",
                "clauses",
                "sql_where_join",
            )

        elif fn == "set_fiscal_config_batch":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=config keys → sink=strip key strings before int map",
                "values.keys",
                "fiscal_config_key_normalize",
            )

        elif fn == "_dispatch_endorsements":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=item.form → sink=strip before endorsement dispatch enum",
                "item.form",
                "endorsement_form_gate",
            )

        elif fn == "write_error_pack":
            emit(
                g,
                members[0],
                "KEEP_transport",
                "source=traceback lines → sink=error pack file bytes; diagnostic assembly",
                "traceback",
                "error_pack_bytes",
            )

        elif fn == "_apply_ordinary_entity_step":
            for m in members:
                if "startswith" in m["kind"]:
                    emit(
                        g,
                        m,
                        "NEEDS_HUMAN",
                        "member snip startswith not present at line in fn body (scanner drift); no dossier gate in 8319-8355",
                        "origin_ref",
                        "remap_member",
                    )
                else:
                    emit(
                        g,
                        m,
                        "NEEDS_HUMAN",
                        "unexpected member kind in ordinary entity step",
                        "",
                        "",
                    )

        elif fn == "_strategic_event_result_preflight_error":
            for m in members:
                emit(
                    g,
                    m,
                    "KEEP_transport",
                    "source=allowed outcome labels set → sink=ValueError message join; closed event labels listed not used to classify input",
                    "allowed",
                    "error_message_join",
                )

        elif fn == "canonicalize_location_region_id":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=location → sink=strip before region id canonicalization lookup",
                "location",
                "region_lookup_gate",
            )

        elif fn == "resolve_dossier_owner_name":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=executor_kind → sink=strip before roster owner resolution",
                "dossier.executor_kind",
                "owner_resolution_gate",
            )

        elif fn == "compose_report_origin":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=marks[] → sink=origin string; ORIGIN_MARK_SEP structured join",
                "marks",
                "origin_mark_compose",
            )

        elif fn == "_prepare_reconsideration_facts" and lens == "N6":
            emit(
                g,
                members[0],
                "KEEP_empty_check",
                "source=target_kind → sink=strip then default issue sentinel",
                "held.target_kind",
                "target_kind_default",
            )

        elif fn == "<module>" and file == "web/src/components/situation.tsx":
            emit(
                g,
                members[0],
                "KEEP_identity_or_formal",
                "source=item.kind → sink=initiative filter; closed {situation,initiative}",
                "item.kind",
                "situation_kind_enum",
            )

        elif fn == "_save_visible_for_campaign":
            emit(
                g,
                members[0],
                "KEEP_structural",
                "source=save basename → sink=campaign autosave parse; regex structure not prose",
                "fname",
                "autosave_name_re",
            )

        else:
            for m in members:
                emit(g, m, "NEEDS_HUMAN", f"unhandled group {file}:{fn}", "", "")

    assert len(rows) == sum(len(g["members"]) for g in groups), (
        len(rows),
        sum(len(g["members"]) for g in groups),
    )

    header = [
        "lens",
        "file",
        "line",
        "fn",
        "kind",
        "disposition",
        "reason",
        "source_field",
        "sink_contract",
    ]
    lines = ["\t".join(header)]
    for r in rows:
        lines.append("\t".join(r[h].replace("\t", " ") for h in header))

    OUT_TSV.write_text("\n".join(lines) + "\n")

    counts = Counter(r["disposition"] for r in rows)
    fixes = [
        f"{r['file']}:{r['line']} {r['fn']} ({r['kind']}) — {r['reason']}"
        for r in rows
        if r["disposition"] == "FIX"
    ]
    needs = sum(1 for r in rows if r["disposition"] == "NEEDS_HUMAN")

    summary = [
        f"shard-2 members: {len(rows)}",
        "disposition counts:",
    ]
    for k in sorted(counts.keys()):
        summary.append(f"  {k}: {counts[k]}")
    summary.append("")
    summary.append("FIX list:")
    if fixes:
        summary.extend(f"  - {x}" for x in fixes)
    else:
        summary.append("  (none)")
    summary.append("")
    summary.append(f"NEEDS_HUMAN: {needs}")
    OUT_SUM.write_text("\n".join(summary) + "\n")

    print("\n".join(summary))


if __name__ == "__main__":
    main()
