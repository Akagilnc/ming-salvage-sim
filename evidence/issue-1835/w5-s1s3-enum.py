#!/usr/bin/env python3
"""#1835 S1/S2/S3 full-class mechanical enumeration (reproducible).

Class defs (末份冻结判词 fix.classes):
  S1: 拒收只沿 canonical 管线表示和消费；删除旧 dict 失败回声及双形扫描；保留 invalid 停续。
  S2: 清除预检重复领域准入与校验，复用现役领域写核拒收；事件整封归属与领域准入分开。
  S3: 按消费者清除退役元数据特例及附属物；说明对齐现役显式契约；删重复/helper-only/无独立必要价值迁约测试。

谓词覆盖类定义全文（非点名样本）：
  S1-prod-standalone: 生产路径产出 {"rejected": True}/{"invalid": True} 失败回声 dict（可不与 RejectedItem 同函数）
  S1-cons-standalone: 消费端用 .get("rejected"| "invalid") / ["rejected"] 把 applied/结果 dict 当拒收通道
  S1-dual-prod: 同函数体同时出现 RejectedItem 构造与 rejected/invalid dict 回声
  S1-dual-cons: 同函数体同时扫 RejectedItem 与 applied dict rejected/invalid
  S2-preflight-admission: preflight 在调用写核前做字段白名单/整数/势力/炮转移/实体存在等准入并早 return
  S2-preflight-helpers: 专供上述平行准入的 helper
  S3-retired-accessory: 退役协议键特免、EMPTY_EXTRACTION 壳、旧模块拒收桥、死别名特判
  S3-wrong-contract-doc: 现行 docs 仍教 reason 战役名锚点或示例缺 event_id（与显式 event_id 契约抵触）
  S3-mig-test: #1835 迁约面测试中 helper-only / 重复 / 失去所称契约检出能力者
"""
from __future__ import annotations
import ast, json, os, re, sys
from pathlib import Path

ROOT = Path(os.environ.get("ENUM_ROOT", Path.cwd())).resolve()

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
             "archive", "evidence", "data", "dist", "build", ".mypy_cache"}

def iter_py(root: Path):
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p

def iter_md(root: Path):
    for p in root.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        # 现行说明：docs/ + CLAUDE/AGENTS/CONTEXT/TODOS + content prompts
        rel = p.relative_to(root).as_posix()
        if rel.startswith("docs/") or rel.startswith("content/") or p.name in {
            "CLAUDE.md", "AGENTS.md", "CONTEXT.md", "TODOS.md", "README.md"
        }:
            yield p

def src(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()

DICT_REJECTED_RE = re.compile(r"""["']rejected["']\s*:\s*True""")
DICT_INVALID_RE = re.compile(r"""["']invalid["']\s*:\s*True""")
GET_REJECTED_RE = re.compile(r"""\.get\(\s*["']rejected["']""")
GET_INVALID_RE = re.compile(r"""\.get\(\s*["']invalid["']""")
IDX_REJECTED_RE = re.compile(r"""\[\s*["']rejected["']\s*\]""")
REJECTED_ITEM_RE = re.compile(r"""\bRejectedItem\b""")

# S2: parallel admission early-return markers still living in preflight
S2_ADMISSION_PATTERNS = [
    (re.compile(r"非法(?:地区|军队)字段"), "field_whitelist"),
    (re.compile(r"_int_delta_error"), "int_parallel"),
    (re.compile(r"值非整数"), "int_msg"),
    (re.compile(r"controlled_by.*powers\.id|powers WHERE id"), "faction_admission"),
    (re.compile(r"随军炮转移目标或负数拟转量非法"), "cannon_transfer_prejudge"),
    (re.compile(r"战果引用未入库(?:地区|军队)"), "entity_missing_early"),
    (re.compile(r"region_valid_fields|army_valid_fields"), "valid_fields_set"),
]

S3_RETIRED = [
    (re.compile(r"""if\s+key\s*==\s*["']_module_rejections["']"""), "module_rejections_exempt"),
    (re.compile(r"""\bEMPTY_EXTRACTION\b"""), "empty_extraction"),
    (re.compile(r"""\bapply_score_extraction\b"""), "apply_score_extraction_prod"),
    (re.compile(r"""_module_rejections"""), "module_rejections_ref"),
]

S3_DOC = [
    (re.compile(r"reason.*(战役名|事件名)|战役名.*reason|必须带事件名或战役名"), "reason_campaign_anchor"),
    (re.compile(r"缺锚点不能单独触发"), "missing_anchor_prose"),
]

# Migration-surface test files for S3 helper-only / duplicate scan
S3_MIG_TEST_GLOBS = [
    "tests/test_person_delta_adapter.py",
    "tests/test_declaration_dispatch_1835.py",
    "tests/test_settlement_fixed_point_1835.py",
    "tests/test_applier_contract.py",
    "tests/test_rejection_wiring.py",
    "tests/test_secret_order_payoff_1504.py",
    "tests/test_issue_entities.py",
    "tests/test_enrich_list_guards.py",
    "tests/test_month_translate_1840.py",
    "tests/test_event_trigger_gate.py",
]

def line_no(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1

def function_spans(tree: ast.AST):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out

def body_src(text: str, node) -> str:
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1: node.end_lineno])

members = {"S1": [], "S2": [], "S3": []}

# ---- S1 production + consumption over all py ----
for p in iter_py(ROOT):
    text = src(p)
    r = rel(p)
    in_prod = r.startswith("ming_sim/")
    in_test = r.startswith("tests/")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        members["S1"].append({"kind": "parse_error", "file": r, "err": str(e)})
        continue

    # standalone dict production (line-level, then attach enclosing func if any)
    for m in DICT_REJECTED_RE.finditer(text):
        ln = line_no(text, m.start())
        # skip comments-only / docstring-ish in tests that are fixtures of rejected *payload items*
        # still enumerate; disposition later
        members["S1"].append({
            "kind": "S1-prod-standalone-dict_rejected_true",
            "file": r, "lineno": ln,
            "line": text.splitlines()[ln-1].strip()[:200],
            "scope": "prod" if in_prod else ("test" if in_test else "other"),
        })
    for m in DICT_INVALID_RE.finditer(text):
        ln = line_no(text, m.start())
        members["S1"].append({
            "kind": "S1-prod-standalone-dict_invalid_true",
            "file": r, "lineno": ln,
            "line": text.splitlines()[ln-1].strip()[:200],
            "scope": "prod" if in_prod else ("test" if in_test else "other"),
        })

    # standalone consumption of dict rejection channel
    for m in GET_REJECTED_RE.finditer(text):
        ln = line_no(text, m.start())
        members["S1"].append({
            "kind": "S1-cons-standalone-get_rejected",
            "file": r, "lineno": ln,
            "line": text.splitlines()[ln-1].strip()[:200],
            "scope": "prod" if in_prod else ("test" if in_test else "other"),
        })
    for m in GET_INVALID_RE.finditer(text):
        ln = line_no(text, m.start())
        # many .get("invalid") are declaration field reads, not rejection channel —
        # still list; semantic disposition filters.
        members["S1"].append({
            "kind": "S1-cons-standalone-get_invalid",
            "file": r, "lineno": ln,
            "line": text.splitlines()[ln-1].strip()[:200],
            "scope": "prod" if in_prod else ("test" if in_test else "other"),
        })
    for m in IDX_REJECTED_RE.finditer(text):
        ln = line_no(text, m.start())
        members["S1"].append({
            "kind": "S1-cons-standalone-idx_rejected",
            "file": r, "lineno": ln,
            "line": text.splitlines()[ln-1].strip()[:200],
            "scope": "prod" if in_prod else ("test" if in_test else "other"),
        })

    # dual-prod / dual-cons per function
    for fn in function_spans(tree):
        body = body_src(text, fn)
        has_ri = bool(REJECTED_ITEM_RE.search(body))
        has_dict_echo = bool(DICT_REJECTED_RE.search(body) or DICT_INVALID_RE.search(body))
        has_get_rej = bool(GET_REJECTED_RE.search(body) or (".get(\"invalid\")" in body and "rejected" in body))
        # dual production: RejectedItem + dict echo in same function
        if has_ri and has_dict_echo and in_prod:
            members["S1"].append({
                "kind": "S1-dual-prod",
                "file": r, "func": fn.name, "lineno": fn.lineno, "end": fn.end_lineno,
            })
        # dual consumption: scans RejectedItem category AND applied dict rejected
        if has_ri and has_get_rej and ("rejected" in body) and in_prod:
            # refine: both category check and get rejected
            if ("category" in body or "RejectedItem" in body) and GET_REJECTED_RE.search(body):
                members["S1"].append({
                    "kind": "S1-dual-cons",
                    "file": r, "func": fn.name, "lineno": fn.lineno, "end": fn.end_lineno,
                })

# ---- S2 preflight ----
pf = ROOT / "ming_sim/settlement/preflight.py"
if pf.exists():
    text = src(pf)
    r = rel(pf)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        members["S2"].append({"kind": "parse_error", "err": str(e)})
        tree = None
    for pat, label in S2_ADMISSION_PATTERNS:
        for m in pat.finditer(text):
            ln = line_no(text, m.start())
            line = text.splitlines()[ln-1].strip()
            # skip pure comments documenting deletion
            if line.startswith("#"):
                continue
            members["S2"].append({
                "kind": f"S2-admission-{label}",
                "file": r, "lineno": ln, "line": line[:220],
            })
    if tree:
        for fn in function_spans(tree):
            if fn.name in {"_int_delta_error"} or fn.name.endswith("_valid_fields"):
                members["S2"].append({
                    "kind": "S2-preflight-helper",
                    "file": r, "func": fn.name, "lineno": fn.lineno, "end": fn.end_lineno,
                })
        # strategic preflight still calling write cores — note presence for envelope check
        for fn in function_spans(tree):
            if fn.name == "_strategic_event_result_preflight_error":
                body = body_src(text, fn)
                members["S2"].append({
                    "kind": "S2-envelope-owner-fn",
                    "file": r, "func": fn.name, "lineno": fn.lineno, "end": fn.end_lineno,
                    "calls_write_kernel": any(x in body for x in (
                        "apply_region_deltas", "apply_army_delta_with_cannon_transfer",
                        "apply_power_updates", "apply_person",
                    )),
                    "has_field_whitelist_return": "非法" in body and "字段" in body,
                    "has_int_delta_helper": "_int_delta_error" in body,
                    "has_cannon_prejudge_msg": "随军炮转移目标或负数拟转量非法" in body,
                })

# Also scan other preflight-like parallel admission in settlement/
for p in (ROOT / "ming_sim/settlement").rglob("*.py"):
    r = rel(p)
    if r.endswith("preflight.py"):
        continue
    text = src(p)
    for label, pat in [
        ("parallel_field_whitelist", re.compile(r"非法(?:地区|军队)字段")),
        ("parallel_cannon_prejudge", re.compile(r"随军炮转移目标或负数拟转量非法")),
    ]:
        for m in pat.finditer(text):
            ln = line_no(text, m.start())
            members["S2"].append({"kind": f"S2-{label}", "file": r, "lineno": ln,
                                  "line": text.splitlines()[ln-1].strip()[:200]})

# ---- S3 retired accessories in prod ----
for p in iter_py(ROOT):
    r = rel(p)
    if not (r.startswith("ming_sim/") or r.startswith("tests/") or r.startswith("docs/")):
        continue
    text = src(p)
    for pat, label in S3_RETIRED:
        for m in pat.finditer(text):
            ln = line_no(text, m.start())
            line = text.splitlines()[ln-1].strip()
            # production apply_score_extraction / EMPTY only matter in ming_sim
            if label in {"empty_extraction", "apply_score_extraction_prod"} and not r.startswith("ming_sim/"):
                # still list under S3 as mig-test / doc residue via separate kinds
                members["S3"].append({
                    "kind": f"S3-name-residue-{label}",
                    "file": r, "lineno": ln, "line": line[:200],
                })
                continue
            members["S3"].append({
                "kind": f"S3-retired-{label}",
                "file": r, "lineno": ln, "line": line[:200],
            })

# ---- S3 wrong-contract docs ----
for p in iter_md(ROOT):
    r = rel(p)
    text = src(p)
    for pat, label in S3_DOC:
        for m in pat.finditer(text):
            ln = line_no(text, m.start())
            line = text.splitlines()[ln-1].strip()
            # negative guidance ("不得靠 reason 战役名") is aligned, still list
            members["S3"].append({
                "kind": f"S3-doc-{label}",
                "file": r, "lineno": ln, "line": line[:240],
                "negative_guidance": ("不得" in line or "不靠" in line or "禁止" in line),
            })
    # examples of strategic envelope missing event_id key nearby
    if "战略" in text or "外敌" in text:
        # find fenced json blocks mentioning jisi_lubian without event_id
        for m in re.finditer(r"```(?:json)?\n(.*?)```", text, re.S):
            block = m.group(1)
            if "jisi_lubian" in block or "dalingghe" in block:
                if "event_id" not in block:
                    ln = line_no(text, m.start())
                    members["S3"].append({
                        "kind": "S3-doc-example-missing-event_id",
                        "file": r, "lineno": ln,
                        "snippet": block[:180].replace("\n", "\\n"),
                    })

# ---- S3 migration tests: helper-only / duplicate ----
# Heuristic within S3_MIG_TEST_GLOBS:
#  - function body < 40 non-empty lines AND only calls normalize_*/helper without dispatch/settle/month_chain
#  - OR name contains retired/legacy/normalize and no public entrance
ENTRANCE_MARKERS = ("dispatch_declaration", "settle_delta", "run_player_month_chain",
                    "apply_monthly_covert", "GameSession", "month_chain", "settle_with")
HELPER_MARKERS = ("normalize_person_changes", "normalize_", "sanitize_delta_shape",
                  "stages_to_json", "stages_list_from_source")

for rel_path in S3_MIG_TEST_GLOBS:
    p = ROOT / rel_path
    if not p.exists():
        members["S3"].append({"kind": "S3-mig-missing-file", "file": rel_path})
        continue
    text = src(p)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        members["S3"].append({"kind": "parse_error", "file": rel_path, "err": str(e)})
        continue
    for fn in function_spans(tree):
        if not fn.name.startswith("test_"):
            continue
        body = body_src(text, fn)
        non_empty = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        size = sum(len(x) for x in non_empty)
        has_entrance = any(m in body for m in ENTRANCE_MARKERS)
        has_helper = any(m in body for m in HELPER_MARKERS)
        name_mig = any(k in fn.name for k in (
            "retired", "legacy", "normalize", "empty_extraction", "module_rejection",
            "old_key", "旧", "迁约", "canonical_key", "response_key",
        ))
        # helper-only candidate: uses helper, no entrance, small, migration-named OR normalize-only
        if has_helper and not has_entrance and (name_mig or size < 800):
            members["S3"].append({
                "kind": "S3-mig-helper_only_candidate",
                "file": rel_path, "func": fn.name, "lineno": fn.lineno,
                "end": fn.end_lineno, "size": size,
                "has_helper": has_helper, "has_entrance": has_entrance, "name_mig": name_mig,
            })
        # asserts old dict rejection shape for settlement invalid
        if re.search(r"""assert.*\[["']rejected["']\]|assert.*\.get\(\s*["']rejected["']""", body):
            if "RejectedItem" not in body and not has_entrance:
                members["S3"].append({
                    "kind": "S3-mig-asserts-old-dict-reject-shape",
                    "file": rel_path, "func": fn.name, "lineno": fn.lineno,
                })
        # lost contract: test claims no old keys but never asserts them
        if "旧" in (fn.name + body[:200]) or "legacy" in fn.name:
            if "assert" not in body and "pytest.raises" not in body:
                members["S3"].append({
                    "kind": "S3-mig-no-assert",
                    "file": rel_path, "func": fn.name, "lineno": fn.lineno,
                })

# Deduplicate by (kind,file,lineno/func)
def dedupe(items):
    seen = set(); out = []
    for it in items:
        key = (it.get("kind"), it.get("file"), it.get("lineno"), it.get("func"))
        if key in seen:
            continue
        seen.add(key); out.append(it)
    return out

for k in members:
    members[k] = dedupe(members[k])

out = {
    "root": str(ROOT),
    "counts": {k: len(v) for k, v in members.items()},
    "members": members,
}
print(json.dumps(out, ensure_ascii=False, indent=2))
