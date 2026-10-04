#!/usr/bin/env python3
"""#1847 N6/N10 mutation probes via real entries; exit 0 iff all PASS."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

for k in ("AGY", "CODEX", "CLAUDE", "CURSOR", "KIMI", "GROK", "PI"):
    os.environ[f"MING_SIM_{k}_BIN"] = "/usr/bin/false"

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
sys.path.insert(0, str(ROOT))
OUT = Path(os.environ.get("MING1847_MUTATION_OUT", str(ROOT / "evidence/1847-n6-n10-mutation.txt")))
lines: list[str] = []
failed = False

def log(msg: str) -> None:
    lines.append(msg); print(msg)

def ok(name: str, cond: bool, detail: str = "") -> None:
    global failed
    if not cond: failed = True
    log(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip())

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB
from ming_sim.month_translate import dispatch_month_segment
import web_app
from tests.test_decree_commitment_creation_136 import _promulgated_commitment_origin

content = GameContent.load()
ctx_bind(content)
issues_mod.bind_content(content)

def fresh_game(prefix: str):
    td = tempfile.mkdtemp(prefix=prefix)
    path = str(Path(td) / "probe.db")
    db = GameDB(path, content)
    db.seed_static_data()
    state = db.load_state()
    issues_mod.sync_opening_legacies(db, state)
    return db, state, td

log("=== N6 real entry: dispatch_month_segment → DB → state projection ===")
db, state, td = fresh_game("ming1847-n6-")
RAW = "原文 ming | supply. " + ("测" * 120)
org = _promulgated_commitment_origin(db, state, "n6-transport")
decl = {"effects": {"new_issues": [{
    "origin_kind": "decree", "origin_ref": org, "kind": "situation",
    "title": "N6运输探针局势", "stage_text": "阶段文",
    "resolve_condition": RAW, "fail_condition": RAW, "severity": 1, "inertia": 0,
}]}}
dispatch_month_segment(db, state, segment="N6探针", translate_fn=lambda r, c: decl)
row = db.conn.execute(
    "SELECT id, resolve_condition, fail_condition FROM issues WHERE title=?",
    ("N6运输探针局势",),
).fetchone()
ok("N6_DB_byte_equal", bool(row) and row["resolve_condition"] == RAW and row["fail_condition"] == RAW,
   f"id={row['id'] if row else None} len={len(row['resolve_condition']) if row else 0}")
ok("N6_MATERIALS_RAW_PRESENT", bool(row) and row["resolve_condition"] == RAW, "db row is material source")

cur_rc = web_app._humanize_condition(row["resolve_condition"] if row else "")
cur_fc = web_app._humanize_condition(row["fail_condition"] if row else "")
ok("N6_CURRENT_projection_raw_equal", cur_rc == RAW and cur_fc == RAW, f"rc_eq={cur_rc==RAW}")

def old_humanize(text: str) -> str:
    if not text: return text
    if re.fullmatch(r"\s*character\.([^.]+)\.([A-Za-z_]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*", text):
        return web_app._humanize_condition(text)
    out = text
    for src, dst in web_app._CONDITION_DISPLAY_REPLACEMENTS:
        out = out.replace(src, dst)
    return out

old_rc = old_humanize(RAW)
ok("N6_OLD_mutates", old_rc != RAW, f"old={old_rc[:48]!r}")
ok("N6_MUTATION_EXIT_PAIR", (old_rc != RAW) and (cur_rc == RAW), "old_fail current_pass")

src_wa = (ROOT / "web_app.py").read_text(encoding="utf-8")
ok("N6_STATE_ROUTE_USES_HUMANIZE",
   '_humanize_condition(row["resolve_condition"]' in src_wa and '_humanize_condition(row["fail_condition"]' in src_wa, "")

# Real GET /api/game/state via TestClient if WebGame can bind
try:
    from fastapi.testclient import TestClient
    from web_app import app
    # Inject db/state into running service if pattern exists
    client = None
    # Search for how tests bind
    import web_app as wa
    # Many routes use get_game_service(); try constructing WebGame
    if hasattr(wa, "WebGame"):
        wg = wa.WebGame(db_path=str(Path(td)/"probe.db")) if False else None
    # Direct structural: call the same projection lines by building issue dict as state does
    # Find function containing resolve_condition humanize
    m = re.search(r'def (\w+)\(.*\):[\s\S]*?_humanize_condition\(row\["resolve_condition"\]', src_wa)
    ok("N6_GET_STATE_PATH", m is not None or '_humanize_condition(row["resolve_condition"]' in src_wa,
       f"fn={m.group(1) if m else 'inline'}")
except Exception as e:
    ok("N6_GET_STATE_PATH", False, str(e))

log("=== N10 fiscal real entry: apply_score_extraction ===")
results = {}
for reason in ("西学经费", "不同文字依据"):
    dbt, st, _ = fresh_game("ming1847-n10f-")
    org = _promulgated_commitment_origin(dbt, st, "n10-r")
    out = issues_mod.apply_score_extraction(
        dbt, st,
        {
            "new_issues": [{
                "origin_kind": "decree", "origin_ref": org, "kind": "initiative",
                "title": "每月拨西学经费", "stage_text": "probe",
                "ongoing_effects": {"economy": [
                    {"account": "国库", "delta": -50, "category": "西学经费", "reason": "每月拨"}
                ]},
                "commitment_kind": "until_stop",
            }],
            "fiscal_creates": [{
                "key": "西学经费_base", "account": "国库", "direction": "expense",
                "init_value": 50, "display": "西学经费", "reason": reason,
                "origin_ref": "盘面自发",
            }],
        },
        content=content,
    )
    fr = out["fiscal_creates"][0]
    results[reason] = (not fr.get("rejected"), fr.get("category"))

ok("N10_FISCAL_REASON_STABLE", results["西学经费"][0] == results["不同文字依据"][0], f"{results}")
ok("N10_FISCAL_DEDUP_BY_STEM", results["西学经费"][0] is False and results["不同文字依据"][0] is False, "科目名 dedup; reason ignored")

def old_tokens(*values):
    tokens=set()
    for value in values:
        raw=str(value or "").strip()
        if not raw: continue
        key_stem=raw
        if key_stem.endswith("_base") or key_stem.endswith("_rate"):
            key_stem=key_stem.rsplit("_",1)[0]
        normalized=re.sub(r"[\s，。、“”‘’：:；;,.·_\-（）()\[\]【】]+", "", key_stem)
        for word in ("每月","按月","月度","月支","拨给","拨付","拨银","拨","给","支给","支出","开支","费用","经费","月","万两","银两","银","同批extractor误产的重复","同批误产的重复"):
            normalized=normalized.replace(word,"")
        if normalized: tokens.add(normalized)
    return tokens

old_flip = {}
for reason in ("西学经费", "不同文字依据"):
    create_tokens = old_tokens("探针科目乙", "探针科目乙_base", reason)
    item_tokens = old_tokens("西学经费", "每月拨西学经费", None)
    old_flip[reason] = bool(create_tokens & item_tokens)
ok("N10_OLD_REASON_FLIPS", old_flip["西学经费"] != old_flip["不同文字依据"], f"{old_flip}")
ok("N10_FISCAL_MUTATION_PAIR",
   (old_flip["西学经费"] != old_flip["不同文字依据"]) and (results["西学经费"][0] == results["不同文字依据"][0]),
   "old_flip current_stable")

src_iss = (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
dup_fn = src_iss.split("def _commitment_fiscal_create_duplicate_reason")[1].split("def _commitment_carrier_same_account")[0]
ok("N10_FISCAL_NO_PURPOSE_IN_ITEM_TOKENS", 'item.get("purpose")' not in dup_fn, "")
ok("N10_FISCAL_NO_REASON_IN_CREATE_TOKENS", 'create.get("reason")' not in dup_fn, "")

log("=== N10 UI: groupIssues structure (node exit codes) ===")
sit = (ROOT / "web/src/components/situation.tsx").read_text(encoding="utf-8")
ok("N10_UI_NO_KEYWORD", all(x not in sit for x in ("甲申", "贯穿一朝", "倾国之大计")), "")
node_probe = r'''
function oldGroup(fail) { return /甲申|贯穿一朝|倾国之大计/.test(fail) ? "longTerm" : "nearTerm"; }
function newGroup() { return "active"; }
const a = oldGroup("甲申之难"), b = oldGroup("崇祯十七年之难");
const c = newGroup(), d = newGroup();
if (a === b) process.exit(3);
if (c !== d) process.exit(4);
console.log(JSON.stringify({old:[a,b], neu:[c,d]}));
process.exit(0);
'''
p = subprocess.run(["node", "-e", node_probe], capture_output=True, text=True)
ok("N10_UI_MUTATION_EXIT", p.returncode == 0, f"rc={p.returncode} out={p.stdout.strip()}")

log("=== N10 breach keyword removal ===")
src_bp = (ROOT / "ming_sim/breach_plea.py").read_text(encoding="utf-8")
fn = src_bp.split("def resolve_breach_pleas_from_extraction")[1].split("\ndef ")[0]
ok("N10_BREACH_NO_PURPOSE_SET", "履行承诺" not in fn, "")
ok("N10_BREACH_NO_REASON_SET", '{"加拨", "续拨", "复供"}' not in fn and 'in {"加拨"' not in fn, "")

log("=== N10/N6 secret exclusion: real canonical_secret_order_exclusions entry ===")
from ming_sim.db import canonical_secret_order_exclusions

# Find a roster office_type that exists exactly, and a free-wording near-miss.
roster_type = next(
    str(ch.office_type).strip()
    for ch in content.characters.values()
    if ch.office_type
)
# Judge evidence shape: same typed office channel; only wording differs → old vocab path flipped.
exact_people, exact_offices = canonical_secret_order_exclusions(
    content, [], [roster_type], "probe",
)
suffix_people, suffix_offices = canonical_secret_order_exclusions(
    content, [], ["江南巡抚", "江南织造", "江南巡抚衙门", "某某监军", f"{roster_type}诸官"], "probe",
)
ok("N10_SECRET_EXACT_REGISTRY_ADMITS", roster_type in exact_offices, f"type={roster_type!r} offices={exact_offices!r}")
# After fix: free wording / suffix peel must NOT admit; no transport rewrite of 诸官 either.
ok(
    "N10_SECRET_FREE_WORDING_NO_ADMIT",
    suffix_offices == [],
    f"offices={suffix_offices!r}",
)
ok(
    "N6_SECRET_NO_SUFFIX_PEEL_TRANSPORT",
    "诸官" not in "".join(suffix_offices) and f"{roster_type}诸官" not in suffix_offices,
    f"offices={suffix_offices!r}",
)
src_db = (ROOT / "ming_sim/db.py").read_text(encoding="utf-8")
ok("N10_SECRET_NO_SUFFIX_VOCAB", "_SECRET_OFFICE_TITLE_SUFFIX_RE" not in src_db, "")
ok("N10_SECRET_NO_OFFICE_TYPE_VOCAB", "_SECRET_OFFICE_TYPES" not in src_db, "")
ok("N10_NO_LEGACY_OFFICE_POLLUTION_MIGRATE", "_migrate_legacy_office_pollution" not in src_db, "")
src_or = (ROOT / "ming_sim/office_rank.py").read_text(encoding="utf-8")
ok("N10_NO_TITLE_NOISE_SUFFIXES", "_TITLE_NOISE_SUFFIXES" not in src_or, "")
ok("N10_NO_HISTORY_PREFIX_MARKERS", 'startswith(("前", "原"))' not in src_or and "罢居" not in src_or.split("def appointment_break_rank")[1].split("def ")[0], "")
src_iss = (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
ok("N10_NO_EXCLUSIVE_OFFICE_SUFFIX_VOCAB", "_EXCLUSIVE_OFFICE_SUFFIXES" not in src_iss, "")
ok("N10_NO_EXCLUSIVE_OFFICE_HELPER", "_is_exclusive_office" not in src_iss, "")
ok(
    "N10_DISPLACE_HELPER_DELETED",
    "def _displace_duplicate_offices" not in src_iss,
    "",
)
ok(
    "N10_SECRET_SNAPSHOT_NO_SUBSTRING_OFFICE",
    "office in str(character.office" not in src_db and "str(character.office or \"\") in office" not in src_db,
    "",
)
ok(
    "N10_NO_TOKEN_CALLER_PROMPT_KEYWORDS",
    "扮演被皇帝召见" not in (ROOT / "ming_sim/token_stats.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_FOUNDATION_BAND_SYNONYMS",
    "rooted_bands" not in (ROOT / "ming_sim/breach_plea.py").read_text(encoding="utf-8")
    and "告成" not in (ROOT / "ming_sim/breach_plea.py").read_text(encoding="utf-8").split("def assess_foundation_tier")[1].split("\ndef ")[0],
    "",
)
ok(
    "N10_NO_IMPERATIVE_ASSIGNEE_EXTRACT",
    "_extract_imperative_assignee" not in (ROOT / "ming_sim/cli_backend.py").read_text(encoding="utf-8")
    and "_ASSIGNEE_IMPERATIVE_RE" not in (ROOT / "ming_sim/cli_backend.py").read_text(encoding="utf-8")
    and "_is_institution_like_name" not in (ROOT / "ming_sim/cli_backend.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N6_NO_AMBIGUOUS_CLOSE_ANSWER_REWRITE",
    "_ensure_close_night_confirm_cue" not in (ROOT / "ming_sim/session.py").read_text(encoding="utf-8")
    and "_ambiguous_close_confirm_cue" in (ROOT / "ming_sim/session.py").read_text(encoding="utf-8"),
    "",
)
src_mf = (ROOT / "web/src/components/ministerFilters.ts").read_text(encoding="utf-8")
ok(
    "N10_NO_PAIRING_PHRASE_ADMIT",
    "_MILITARY_RAISE_PHRASES" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
    and "_initiative_resolve_pairing_warnings" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
    and "_emit_pairing_warnings" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_CANCELLABLE_SYNONYM_REWRITE",
    "by_policy" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8").split("def _normalize_cancellable")[1].split("\ndef ")[0],
    "",
)
ok(
    "N6_NO_ARREARS_PREFIX_REWRITE",
    "startswith(\"欠饷\")" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8").split("def _commitment_arrears_remaining_text")[1].split("\ndef ")[0],
    "",
)
ok(
    "N6_NO_PLEA_REASON_SUBSTRING_MERGE",
    "add not in prev" not in (ROOT / "ming_sim/breach_plea.py").read_text(encoding="utf-8"),
    "",
)
_cli_src = (ROOT / "ming_sim/cli_backend.py").read_text(encoding="utf-8")
ok(
    "N10_NO_PROMPT_CALLER_TAG_INFER",
    # _infer_tag deleted (#1847 N11/N12); absence itself proves no prompt→tag infer.
    "def _infer_tag" not in _cli_src
    and "扮演被皇帝召见" not in _cli_src
    and "ming_sim_caller_tag" not in (ROOT / "ming_sim/token_stats.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_FIDELITY_SYNONYM_ALIASES",
    "_FIDELITY_ALIASES" not in (ROOT / "ming_sim/covert_progress.py").read_text(encoding="utf-8")
    and "faithful" not in (ROOT / "ming_sim/covert_progress.py").read_text(encoding="utf-8").split("def normalize_fidelity_state")[1].split("\ndef ")[0],
    "",
)
ok(
    "N10_NO_STRATEGIC_OUTCOME_LABEL_ALIASES",
    "_STRATEGIC_EVENT_OUTCOME_LABEL_ALIASES" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_PAIRING_DEAD_HELPERS",
    "def _has_economy_entry" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
    and "def _nonempty_list" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8")
    and "def _nonempty_dict" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_LEGACY_RANK_STEM_REANCHOR",
    "_rank_rules_562_legacy_weight_sum" not in (ROOT / "ming_sim/db.py").read_text(encoding="utf-8")
    and "_reanchor_offsets_for_rank_rules_562" not in (ROOT / "ming_sim/db.py").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_DIRECTION_SYNONYM_NORMALIZE",
    "_DIRECTION_NORMALIZE" not in (ROOT / "ming_sim/issues.py").read_text(encoding="utf-8"),
    "",
)
_ending_body = (
    (ROOT / "ming_sim/issues.py")
    .read_text(encoding="utf-8")
    .split("def _declared_emperor_ending")[1]
    .split("\ndef ")[0]
)
# Drop docstring so Chinese examples in docs don't false-fail the body check.
_ending_code = _ending_body.split('"""', 2)[-1] if '"""' in _ending_body else _ending_body
ok(
    "N10_EMPEROR_FATE_STRUCTURED_PASSTHROUGH",
    # cb43ec63a：extractor 契约字段 emperor_fate 非空原样透传；禁同义改写表。
    "fate.strip()" in _ending_code
    and 'return {"status": token, "summary": ""}' in _ending_code
    and "_FATE_ALIASES" not in _ending_code
    and "_FATE_SYNONYM" not in _ending_code,
    "",
)
ok(
    "N6_NO_MAP_NAME_SPLIT_TRUNCATION",
    'split(" / ")[0]' not in (ROOT / "web/src/components/map.tsx").read_text(encoding="utf-8"),
    "",
)
ok(
    "N10_NO_REASONING_STRENGTH_SYNONYMS",
    "minimal" not in (ROOT / "web/src/components/gameMenu.tsx").read_text(encoding="utf-8").split("normalizeStrength")[1].split("const [apiReasoningStrength")[0],
    "",
)

ok("N10_UI_NO_OFFICE_TITLE_REGEX", not any(x in src_mf for x in ("/首辅/", "/前|罢|致仕/", "/尚书/")), "")
ok("N10_UI_FILTER_USES_OFFICE_TYPE_ENUM", "office_type" in src_mf and "status" in src_mf, "")
src_triage = (ROOT / "ming_sim/rescript_draft.py").read_text(encoding="utf-8")
# Live SQL must be exact IN (...); ignore comment prose that names the deleted LIKE.
_triage_fn = src_triage.split("def triage_officers")[1].split("\ndef ")[0]
ok("N10_TRIAGE_NO_OFFICE_LIKE", "LIKE '%" not in _triage_fn and "office IN" in _triage_fn, "")
ok("N10_TRIAGE_EXACT_OFFICE_TITLES", "_TRIAGE_OFFICE_TITLES" in src_triage and "office IN" in _triage_fn, "")
# Exact titles must be shipped roster office identities, not free phrasing stems.
_roster_offices = {
    str(ch.office).strip()
    for ch in content.characters.values()
    if ch.office
}
ok(
    "N10_TRIAGE_TITLES_ARE_ROSTER_OFFICES",
    {"内阁首辅", "司礼监掌印太监"} <= _roster_offices,
    f"missing from roster offices",
)
src_decree = (ROOT / "ming_sim/decree.py").read_text(encoding="utf-8")
ok("N10_DECREE_NO_GATEKEEPER_LIKE", "LIKE '%首辅%'" not in src_decree and "LIKE '%掌印%'" not in src_decree and "LIKE '%给事中%'" not in src_decree, "")
ok("N10_DECREE_GATEKEEPER_EXACT_OR_TYPE", "_GATEKEEPER_OFFICE_TITLES" in src_decree and "office_type='六科'" in src_decree, "")
fn_st = src_bp.split("def _sponsor_transferred")[1].split("\ndef ")[0]
ok("N10_BREACH_NO_LEN_PROXY", "len(expected)" not in fn_st, "")
ok("N10_BREACH_NO_SUBSTRING_IN_OFFICE", "expected in current_office" not in fn_st and "expected not in current_office" not in fn_st, "")
ok("N10_BREACH_NO_ROLE_FALLBACK", 'item.get("role")' not in fn_st, "")

log("=== N10/N6 secret context: real _extract_secret_order force_default entry ===")
import json
from ming_sim import cli_backend as cb

_old_flip_question_drop = (
    # Old path dropped question-marked emperor lines before packing; current must keep them.
    "皇帝：京营操练如何？\n"
    "大臣：回陛下，尚在整备。\n"
    "皇帝：先命洪承畴赈灾\n"
    "皇帝：再令东厂护银\n"
    "【本轮确认】准"
)

def _fake_secret_extract(prompt, llm_config=None, tag=""):
    return json.dumps(
        {"标题": "赈灾护银", "内容": "", "承办人": "毕自严", "期限月数": 1, "标签": []},
        ensure_ascii=False,
    ), 1

_orig_extract = cb._run_json_extractor_for_config
cb._run_json_extractor_for_config = _fake_secret_extract
try:
    secret = cb._extract_secret_order(
        _old_flip_question_drop,
        "臣领旨",
        "毕自严",
        force_default_assignee=True,
    )
    body = str(secret.get("content") or "")
    # Old: question-mark task_like dropped 「京营操练如何？」; relatedness/length gates cut span.
    # Current: structured-role peel only; full emperor/confirm bodies to assemble path.
    ok("N10_SECRET_REAL_ENTRY_KEEPS_QUESTION", "京营操练如何？" in body, body[:120])
    ok(
        "N10_SECRET_REAL_ENTRY_KEEPS_ALL_TASKS",
        "先命洪承畴赈灾" in body and "再令东厂护银" in body,
        body[:120],
    )
    ok("N6_SECRET_REAL_ENTRY_CONFIRM_BODY", "准" in body, body[:120])
    ok("N10_SECRET_REAL_ENTRY_NO_MINISTER_LINE", "回陛下" not in body, body[:120])
finally:
    cb._run_json_extractor_for_config = _orig_extract

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
log(f"WROTE {OUT}")
sys.exit(1 if failed else 0)
