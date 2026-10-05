#!/usr/bin/env python3
"""#1889 六类本票枚举（最小证据脚本，非生产机制）。

按末份判词六类定义全文枚举候选；输出 TSV 到 stdout 或 --out。
复跑：
  python3 scripts/1889_six_class_enumerate.py
  python3 scripts/1889_six_class_enumerate.py --class 2 --out /tmp/1889-c2.tsv
"""
from __future__ import annotations

import argparse
import ast
import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRAMEWORK_SQL = re.compile(
    r"\b(SAVEPOINT|RELEASE|ROLLBACK|BEGIN|COMMIT|PRAGMA)\b", re.I
)
DML = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|INTO|CREATE|DROP|ALTER)\b", re.I)
EXEC_ATTRS = frozenset({"execute", "executemany", "executescript"})

STOREISH = frozenset({
    "dossiers", "characters", "armies", "regions", "buildings", "issues",
    "affairs", "powers", "factions", "person_logs", "character_knowledge",
    "textual_facts", "fiscal_containers", "fiscal_config", "reign",
    "staged_declarations", "social_classes", "records", "decisions",
    "chat_messages", "month_open_snapshots", "resolve_contexts",
    "month_chains", "legacies", "events", "economy",
})

OWNER_BY_TABLE = {
    "pending_actions": "DossierStore",
    "decree_dossiers": "DossierStore",
    "dossier_presence": "DossierStore",
    "character_knowledge_events": "CharacterKnowledgeStore",
    "character_knowledge_sources": "CharacterKnowledgeStore",
    "secret_orders": "CharacterKnowledgeStore",
    "secret_order_briefs": "CharacterKnowledgeStore",
    "investigation_spoiled_facts": "CharacterKnowledgeStore",
    "public_sayings": "CharacterKnowledgeStore",
    "characters": "CharacterStore",
    "character_offices": "CharacterStore",
    "office_slots": "CharacterStore",
    "armies": "ArmyStore",
    "army_logs": "ArmyStore",
    "regions": "RegionStore",
    "buildings": "BuildingStore",
    "issues": "IssueStore",
    "issue_advances": "IssueStore",
    "affairs": "AffairStore",
    "powers": "PowerStore",
    "factions": "FactionStore",
    "person_logs": "PersonLogStore",
    "textual_facts": "TextualFactStore",
    "fiscal_containers": "FiscalContainerStore",
    "fiscal_config": "FiscalConfigStore",
    "game_state": "ReignStateStore",
    "metrics": "ReignStateStore",
    "audience_nights": "ReignStateStore",
    "story_ledger_entries": "ReignStateStore",
    "chat_turns": "ReignStateStore",
    "classes": "SocialClassStore",
    "staged_declarations": "StagedDeclarationStore",
}


def git_py_files() -> list[str]:
    import subprocess
    out = subprocess.check_output(
        ["git", "ls-files", "ming_sim", "tests", "web_app.py"],
        cwd=ROOT, text=True,
    )
    return [p for p in out.splitlines() if p.endswith(".py")]


def parse(rel: str) -> ast.AST | None:
    try:
        return ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def snip(rel: str, lineno: int, n: int = 1) -> str:
    lines = (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[lineno - 1:lineno - 1 + n]
    # rstrip after truncate: mid-line cut can leave trailing spaces that break git diff --check
    return " | ".join(s.strip() for s in chunk)[:220].rstrip()


def is_store_path(rel: str) -> bool:
    return rel.endswith("store.py") or rel.endswith("entities/column_write.py") \
        or rel.endswith("entities/fiscal_container/config.py") \
        or rel.endswith("entities/record_store.py")


def is_schema_path(rel: str) -> bool:
    return rel.endswith("schema.py")


def store_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


# ---------- Class 2: persistence SQL + GameDB forwards ----------

class ExecFinder(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.stack: list[tuple[str, str, int]] = []
        self.hits: list[dict] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(("cls", node.name, node.lineno))
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(("fn", node.name, node.lineno))
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in EXEC_ATTRS:
            ctx = " > ".join(f"{k}:{n}" for k, n, _ in self.stack[-3:])
            text = snip(self.rel, node.lineno, 4)
            framework = bool(FRAMEWORK_SQL.search(text)) and not DML.search(text)
            # PRAGMA / SAVEPOINT / ROLLBACK even when nearby prose mentions FROM imports
            if re.search(r"\bPRAGMA\b|\bSAVEPOINT\b|\bROLLBACK\s+TO\b|\bRELEASE\b|\bBEGIN\b|\bCOMMIT\b", text, re.I):
                if not re.search(r"\b(INSERT|UPDATE|DELETE)\b", text, re.I):
                    # SELECT 1 FROM sqlite_master is schema introspection, not entity fact SQL
                    if re.search(r"\bsqlite_master\b|\bPRAGMA\b", text, re.I) or not DML.search(text):
                        framework = True
                    if re.search(r"\b(SAVEPOINT|ROLLBACK|RELEASE|BEGIN|COMMIT)\b", text, re.I) and not re.search(
                        r"\b(INSERT|UPDATE|DELETE)\b.+\b(FROM|INTO)\b", text, re.I | re.S
                    ):
                        framework = True
            tables = sorted(set(re.findall(
                r"\b(?:FROM|INTO|UPDATE|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)",
                text, re.I,
            )))
            owner = ",".join(OWNER_BY_TABLE.get(t, "?") for t in tables) if tables else ""
            self.hits.append({
                "lane": "c2_sql",
                "member": f"{func.attr}@{node.lineno}",
                "location": f"{self.rel}:{node.lineno}",
                "class": "2",
                "detail": ctx,
                "framework": str(int(framework)),
                "tables": ",".join(tables),
                "owner": owner,
                "in_owner_store": str(int(is_store_path(self.rel))),
                "snippet": text.replace("\t", " "),
            })
        self.generic_visit(node)


class ForwardFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[dict] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name != "GameDB":
            return
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._method(item)

    def _method(self, node: ast.FunctionDef) -> None:
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        body = list(node.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
            body = body[1:]
        kind = ""
        detail = ""
        if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
            call = body[0].value
            if isinstance(call.func, ast.Attribute):
                store = store_attr(call.func.value)
                if store in STOREISH:
                    kind, detail = "pure_return_forward", f"return self.{store}.{call.func.attr}(...)"
        elif body and all(
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Attribute)
            and store_attr(s.value.func.value) in STOREISH
            for s in body
            if not (isinstance(s, ast.Return) and s.value is None)
        ):
            calls = []
            for s in body:
                if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                    store = store_attr(s.value.func.value)
                    calls.append(f"self.{store}.{s.value.func.attr}")
            if calls:
                kind, detail = "void_forward", "; ".join(calls)
        elif body:
            only = True
            calls: list[str] = []
            for s in body:
                if isinstance(s, (ast.Assign, ast.AnnAssign)):
                    val = s.value if isinstance(s, ast.Assign) else s.value
                    if not (isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute)
                            and store_attr(val.func.value)):
                        only = False
                        break
                    store = store_attr(val.func.value)
                    calls.append(f"self.{store}.{val.func.attr}")
                elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Attribute):
                    # allow self.conn.commit / close as framework alongside store
                    if isinstance(s.value.func.value, ast.Attribute) and store_attr(s.value.func.value) is None:
                        target = s.value.func
                        if isinstance(target.value, ast.Attribute) and target.value.attr == "conn" and target.attr in {"commit", "close", "execute"}:
                            calls.append(f"conn.{target.attr}")
                            continue
                    store = store_attr(s.value.func.value)
                    if store is None and isinstance(s.value.func.value, ast.Attribute):
                        # self.conn.commit
                        if getattr(s.value.func.value, "attr", "") == "conn" and s.value.func.attr in {"commit", "close"}:
                            calls.append(f"conn.{s.value.func.attr}")
                            continue
                    if store is None:
                        # self.conn.commit where value is Attribute self.conn
                        if isinstance(s.value.func.value, ast.Attribute) and isinstance(s.value.func.value.value, ast.Name) and s.value.func.value.value.id == "self" and s.value.func.value.attr == "conn":
                            calls.append(f"conn.{s.value.func.attr}")
                            continue
                        only = False
                        break
                    calls.append(f"self.{store}.{s.value.func.attr}")
                elif isinstance(s, ast.Return):
                    if s.value is None or isinstance(s.value, ast.Name):
                        pass
                    elif isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Attribute):
                        store = store_attr(s.value.func.value)
                        if store is None:
                            only = False
                            break
                        calls.append(f"return self.{store}.{s.value.func.attr}")
                    else:
                        only = False
                        break
                else:
                    only = False
                    break
            if only and calls and len(body) <= 5:
                kind, detail = "thin_store_wrapper", "; ".join(calls)
        if kind:
            self.hits.append({
                "lane": "c2_forward",
                "member": node.name,
                "location": f"ming_sim/db.py:{node.lineno}",
                "class": "2",
                "detail": kind,
                "framework": "0",
                "tables": "",
                "owner": "",
                "in_owner_store": "0",
                "snippet": detail,
            })


def enum_class2() -> list[dict]:
    rows: list[dict] = []
    for rel in git_py_files():
        if not rel.startswith("ming_sim/") and rel != "web_app.py":
            continue
        tree = parse(rel)
        if tree is None:
            continue
        f = ExecFinder(rel)
        f.visit(tree)
        for h in f.hits:
            # candidate if fact SQL outside owner store/schema
            if h["framework"] == "1":
                h["lane"] = "c2_sql_framework"
            elif is_schema_path(rel):
                h["lane"] = "c2_sql_schema"
            elif is_store_path(rel):
                h["lane"] = "c2_sql_in_store"
            else:
                h["lane"] = "c2_sql_leak_candidate"
            rows.append(h)
    tree = parse("ming_sim/db.py")
    if tree is not None:
        ff = ForwardFinder()
        ff.visit(tree)
        rows.extend(ff.hits)
    return rows


# ---------- Classes 1,3,4,5,6: definition-breadth text/AST scans ----------

C1_PAT = re.compile(
    r"calc_province_fiscal|USE_FISCAL_SUBSTRATE|fiscal_substrate_cutover|"
    r"use_fiscal_substrate|_read_use_fiscal|_write_use_fiscal|"
    r"__fiscal_engine|__army_pay_source_cutover|army_pay_source_cutover|"
    r"fiscal_engine\s*=|legacy.?engine|shadow.?parallel|"
    r"留作测试参照|cutover.?marker|read_use_fiscal",
    re.I,
)
# Class3: broad orphan / retired-helper signals (defs AND refs); not a delete whitelist
C3_PAT = re.compile(
    r"_fail_cli_chat_turn_scene|substantiate_covert|_covert_substantiat|"
    r"neutralize_covert_fiscal_effects|_COVERT_NEUTRALIZATION|"
    r"def upsert\b|debug_upsert|admin_debug|"
    r"progress\s*=\s*1|reason_code\s*=\s*['\"]依律|used\s*=\s*True|"
    r"满阈自动|旧清算轨|已退役.*辅助|孤立机制|"
    r"legacy_.?path|orphan.?mech|retired.?helper|compat.?shim|"
    r"旧坐实|满阈.*依律|test.?double.?补偿",
)
# Class4: all population accounting symbols / rates / dual-entry signals
C4_PAT = re.compile(
    r"apply_issue_inertia_and_ongoing|"
    r"apply_levy_driven_transfers|apply_recovery_driven_transfers|"
    r"_apply_levy_driven_transfers|_apply_recovery_driven_transfers|"
    r"inertia_and_ongoing|旧名兼容|population.?dual|双份.*人口|"
    r"LEVY_DISPLACEMENT_RATE|RECOVERY_DISPLACEMENT|"
    r"displaced_population|流民|加派.*人口|赈济.*人口|"
    r"read_apply_levy|read_apply_recovery|population_transfers|"
    r"apply_population|displace.*delta|displaced_delta",
    re.I,
)
C5_PAT = re.compile(
    r"close_from_declaration|declare_closed|ATTACH_RESULT_CLOSE|_ATTACH_CLOSE|"
    r"本阶段不能了结|顶层事务声明只接受了结|"
    r"attach\s*=\s*[\"']close[\"']|declare.?close|"
    r"AffairStore\.close|affairs.*status=.?closed.*declaration|"
    r"birth.?close|了结动作|显式了结",
)
C6_STRUCT = re.compile(
    r"scrollTop|aria-label=[\"']撤回召对确认[\"']|撤回召对确认",
)
HAN = re.compile(r"[\u4e00-\u9fff]")
MACHINEISH = re.compile(
    r"^[A-Za-z0-9_./:-]+$|^status$|^id$|^kind$|^role$|^open$|^closed$|^held$|"
    r"^pending$|^active$|^off$|^on$|^true$|^false$",
    re.I,
)
UI_CHROME = re.compile(
    r"继续|取消|确认|关闭|撤回|过月|载入|新档|返回|设置|关（|开（|"
    r"检查模型后端|重整朝堂名册|等待|锁定|菜单",
)


def text_scan(rel: str, pat: re.Pattern[str], lane: str, cls: str) -> list[dict]:
    path = ROOT / rel
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if pat.search(line):
            out.append({
                "lane": lane,
                "member": line.strip()[:80].rstrip(),
                "location": f"{rel}:{i}",
                "class": cls,
                "detail": "text_hit",
                "framework": "0",
                "tables": "",
                "owner": "",
                "in_owner_store": "0",
                "snippet": line.strip()[:220].rstrip(),
            })
    return out


def _row(lane: str, member: str, loc: str, cls: str, detail: str, snippet: str) -> dict:
    return {
        "lane": lane,
        "member": member[:80].rstrip(),
        "location": loc,
        "class": cls,
        "detail": detail,
        "framework": "0",
        "tables": "",
        "owner": "",
        "in_owner_store": "0",
        "snippet": snippet[:220].rstrip(),
    }


def enum_c3_defs_and_refs() -> list[dict]:
    """Full-repo: definitions (FunctionDef/Assign/Class) + Name/Attribute refs for C3 symbols."""
    import subprocess
    files = subprocess.check_output(
        ["git", "ls-files", "ming_sim", "tests", "web_app.py"],
        cwd=ROOT, text=True,
    ).splitlines()
    files = [p for p in files if p.endswith(".py")]
    # seed symbols from text hits + known retired names
    symbols = {
        "_fail_cli_chat_turn_scene", "substantiate_covert", "neutralize_covert_fiscal_effects",
        "_COVERT_NEUTRALIZATION_REASON", "debug_upsert", "admin_debug",
        "apply_issue_inertia_and_ongoing",
    }
    rows: list[dict] = []
    # collect defs
    for rel in files:
        tree = parse(rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if C3_PAT.search(node.name) or node.name in symbols:
                    symbols.add(node.name)
                    rows.append(_row(
                        "c3_orphan_mech", f"def:{node.name}", f"{rel}:{node.lineno}", "3",
                        "definition", snip(rel, node.lineno, 2),
                    ))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and (C3_PAT.search(t.id) or t.id in symbols):
                        symbols.add(t.id)
                        rows.append(_row(
                            "c3_orphan_mech", f"const:{t.id}", f"{rel}:{node.lineno}", "3",
                            "definition", snip(rel, node.lineno, 1),
                        ))
    # refs
    for rel in files:
        tree = parse(rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in symbols:
                rows.append(_row(
                    "c3_orphan_mech", f"ref:{node.id}", f"{rel}:{getattr(node, 'lineno', 0)}", "3",
                    "reference", snip(rel, getattr(node, "lineno", 1), 1),
                ))
            elif isinstance(node, ast.Attribute) and node.attr in symbols:
                rows.append(_row(
                    "c3_orphan_mech", f"ref:{node.attr}", f"{rel}:{getattr(node, 'lineno', 0)}", "3",
                    "reference", snip(rel, getattr(node, "lineno", 1), 1),
                ))
    # also keep broad text hits for comments / prose about retirement
    for rel in files:
        if rel.startswith(("ming_sim/", "tests/")) or rel == "web_app.py":
            rows += text_scan(rel, C3_PAT, "c3_orphan_mech", "3")
    return rows


def enum_c4_population() -> list[dict]:
    """Enumerate population-related defs/consts/calls; flag duplicate names."""
    import subprocess
    from collections import defaultdict
    files = subprocess.check_output(
        ["git", "ls-files", "ming_sim", "tests", "web_app.py"],
        cwd=ROOT, text=True,
    ).splitlines()
    files = [p for p in files if p.endswith(".py")]
    defs: dict[str, list[str]] = defaultdict(list)
    rows: list[dict] = []
    for rel in files:
        tree = parse(rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if C4_PAT.search(node.name) or "population" in node.name.lower() or "displac" in node.name.lower() or "levy" in node.name.lower() and "transfer" in node.name.lower():
                    loc = f"{rel}:{node.lineno}"
                    defs[node.name].append(loc)
                    rows.append(_row(
                        "c4_pop_parallel", f"def:{node.name}", loc, "4",
                        "definition", snip(rel, node.lineno, 2),
                    ))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and C4_PAT.search(t.id):
                        loc = f"{rel}:{node.lineno}"
                        defs[t.id].append(loc)
                        rows.append(_row(
                            "c4_pop_parallel", f"const:{t.id}", loc, "4",
                            "definition", snip(rel, node.lineno, 1),
                        ))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if C4_PAT.search(node.func.attr):
                    rows.append(_row(
                        "c4_pop_parallel", f"call:{node.func.attr}", f"{rel}:{node.lineno}", "4",
                        "call", snip(rel, node.lineno, 1),
                    ))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if C4_PAT.search(node.func.id):
                    rows.append(_row(
                        "c4_pop_parallel", f"call:{node.func.id}", f"{rel}:{node.lineno}", "4",
                        "call", snip(rel, node.lineno, 1),
                    ))
        rows += text_scan(rel, C4_PAT, "c4_pop_parallel", "4")
    for name, locs in defs.items():
        if len(locs) > 1:
            for loc in locs:
                rows.append(_row(
                    "c4_pop_parallel", f"dup:{name}", loc, "4",
                    f"duplicate_defs:{len(locs)}", ";".join(locs)[:220],
                ))
    return rows


def _const_strs(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def enum_c6_ast() -> list[dict]:
    """AST: ALL Python test assert / raises(match=) / string Compare;
    ALL Web expect toBe/toEqual/toContain/toMatch/getBy* with string args.
    Inclusion is not narrowed by Han length or field names — every string
    lock candidate is emitted; detail tags only aid disposition.
    """
    import subprocess
    rows: list[dict] = []

    def _tag(s: str) -> str:
        if MACHINEISH.match(s) or s in {"", "off", "on", "true", "false"}:
            return "machine"
        if UI_CHROME.search(s):
            return "ui_chrome"
        if HAN.search(s):
            return "han"
        return "other"

    py_files = subprocess.check_output(
        ["git", "ls-files", "tests"], cwd=ROOT, text=True,
    ).splitlines()
    py_files = [p_ for p_ in py_files if p_.endswith(".py")]
    for rel in py_files:
        tree = parse(rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                strs = _const_strs(node.test)
                if not strs:
                    continue
                tags = sorted({_tag(s) for s in strs})
                detail = "assert|" + "+".join(tags)
                rows.append(_row(
                    "c6_string_lock", detail, f"{rel}:{node.lineno}", "6", detail,
                    snip(rel, node.lineno, 1) + " :: " + "|".join(strs)[:120],
                ))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "raises"
            ):
                for kw in node.keywords:
                    if kw.arg == "match":
                        strs = _const_strs(kw.value)
                        if not strs:
                            continue
                        s = strs[0]
                        detail = "raises_match|" + _tag(s)
                        rows.append(_row(
                            "c6_string_lock", detail, f"{rel}:{node.lineno}", "6",
                            detail, snip(rel, node.lineno, 1) + " :: " + s[:120],
                        ))
            elif isinstance(node, ast.Compare):
                strs = _const_strs(node)
                if not strs:
                    continue
                ops_ok = any(
                    isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn))
                    for op in node.ops
                )
                if not ops_ok:
                    continue
                tags = sorted({_tag(s) for s in strs})
                detail = "compare|" + "+".join(tags)
                rows.append(_row(
                    "c6_string_lock", detail, f"{rel}:{getattr(node, 'lineno', 0)}", "6",
                    detail,
                    snip(rel, getattr(node, "lineno", 1), 1) + " :: " + "|".join(strs)[:120],
                ))
    web = subprocess.check_output(
        ["git", "ls-files", "web/src"], cwd=ROOT, text=True,
    ).splitlines()
    web = [
        p_
        for p_ in web
        if p_.endswith((".ts", ".tsx"))
        and ("test" in p_ or p_.endswith(".test.ts") or p_.endswith(".test.tsx"))
    ]
    web_pat = re.compile(
        r"(?:expect\([^\n]*\)\.(?:toBe|toEqual|toContain|toMatch|not\.toContain|not\.toBe)|"
        r"getByText|getByRole|getByLabelText|findByText)"
        r"\(\s*(['\"`])((?:\\.|(?!\1).)*)\1"
    )
    for rel in web:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if C6_STRUCT.search(line):
                rows.append(_row(
                    "c6_string_lock", "struct_scroll_or_aria", f"{rel}:{i}", "6",
                    "struct_scroll_or_aria", line.strip()[:220],
                ))
            for m in web_pat.finditer(line):
                s = m.group(2)
                detail = "web_expect|" + _tag(s)
                rows.append(_row(
                    "c6_string_lock", detail, f"{rel}:{i}", "6",
                    detail, line.strip()[:220] + " :: " + s[:80],
                ))
    return rows


def enum_text_classes() -> list[dict]:
    rows: list[dict] = []
    files = git_py_files()
    for rel in files:
        if rel.startswith("ming_sim/") or rel.startswith("tests/") or rel == "web_app.py":
            rows += text_scan(rel, C1_PAT, "c1_fiscal_retired", "1")
            rows += text_scan(rel, C5_PAT, "c5_affair_close", "5")
    rows += enum_c3_defs_and_refs()
    rows += enum_c4_population()
    rows += enum_c6_ast()
    return rows


FIELDS = (
    "lane", "member", "location", "class", "detail",
    "framework", "tables", "owner", "in_owner_store", "snippet",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="only", type=str, default="", help="1..6 or comma list")
    ap.add_argument("--out", type=str, default="")
    ap.add_argument("--leaks-only", action="store_true", help="only c2_sql_leak_candidate + forwards")
    args = ap.parse_args()
    wanted = {c.strip() for c in args.only.split(",") if c.strip()} if args.only else set()

    rows = enum_class2() + enum_text_classes()
    if wanted:
        rows = [r for r in rows if r["class"] in wanted]
    if args.leaks_only:
        rows = [r for r in rows if r["lane"] in {
            "c2_sql_leak_candidate", "c2_forward",
            "c1_fiscal_retired", "c3_orphan_mech", "c4_pop_parallel",
            "c5_affair_close", "c6_string_lock",
        }]

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, str):
                r[k] = v.rstrip()
        w.writerow(r)
    lines = [line.rstrip() for line in buf.getvalue().splitlines()]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        # summary to stderr
    # always print summary
    from collections import Counter
    c = Counter(r["lane"] for r in rows)
    print("=== lane counts ===", file=sys.stderr)
    for k, v in sorted(c.items()):
        print(f"{k}\t{v}", file=sys.stderr)
    if not args.out:
        sys.stdout.write(text)
    else:
        print(f"wrote {args.out} rows={len(rows)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
