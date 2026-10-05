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
    return " | ".join(s.strip() for s in chunk)[:220]


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
C3_PAT = re.compile(
    r"_fail_cli_chat_turn_scene|substantiate_covert|_covert_substantiat|"
    r"neutralize_covert_fiscal_effects|_COVERT_NEUTRALIZATION|"
    r"def upsert\b|debug_upsert|admin_debug|"
    r"progress\s*=\s*1|reason_code\s*=\s*['\"]依律|used\s*=\s*True|"
    r"满阈自动|旧清算轨|已退役.*辅助|孤立机制",
)
C4_PAT = re.compile(
    r"apply_issue_inertia_and_ongoing|"
    r"def apply_levy_driven_transfers|def apply_recovery_driven_transfers|"
    r"def _apply_levy_driven_transfers|def _apply_recovery_driven_transfers|"
    r"inertia_and_ongoing|旧名兼容|population.?dual|双份.*人口|"
    r"LEVY_DISPLACEMENT_RATE|RECOVERY_DISPLACEMENT",
)
C5_PAT = re.compile(
    r"close_from_declaration|declare_closed|ATTACH_RESULT_CLOSE|_ATTACH_CLOSE|"
    r"本阶段不能了结|顶层事务声明只接受了结|"
    r"attach\s*=\s*[\"']close[\"']|declare.?close|"
    r"AffairStore\.close|affairs.*status=.?closed.*declaration",
)
C6_PROSE_PY = re.compile(
    r"AGENDA_FROZEN|"
    r"(?:content|agenda|body|narrative|summary|report_text)\s*\]?\s*==\s*[\"'][\u4e00-\u9fff].{12,}|"
    r"assertEqual\([^)]*(?:content|agenda|body|narrative)[^)]*[\"'][\u4e00-\u9fff].{12,}",
)
C6_PROSE_TS = re.compile(
    r"AGENDA_FROZEN|"
    r"(?:textContent|innerText|content|agenda)\b[^;\n]{0,40}(?:toBe|toEqual|toContain|toMatch)\(\s*[\"'][\u4e00-\u9fff].{12,}",
)
C6_STRUCT = re.compile(
    r"scrollTop|aria-label=[\"']撤回召对确认[\"']|撤回召对确认",
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
                "member": line.strip()[:80],
                "location": f"{rel}:{i}",
                "class": cls,
                "detail": "text_hit",
                "framework": "0",
                "tables": "",
                "owner": "",
                "in_owner_store": "0",
                "snippet": line.strip()[:220],
            })
    return out


def enum_text_classes() -> list[dict]:
    rows: list[dict] = []
    files = git_py_files()
    # also web ts/tsx under git
    import subprocess
    web = subprocess.check_output(
        ["git", "ls-files", "web/src", "tests"],
        cwd=ROOT, text=True,
    ).splitlines()
    web = [p for p in web if p.endswith((".ts", ".tsx", ".py"))]
    for rel in files:
        if rel.startswith("ming_sim/") or rel.startswith("tests/") or rel == "web_app.py":
            rows += text_scan(rel, C1_PAT, "c1_fiscal_retired", "1")
            rows += text_scan(rel, C3_PAT, "c3_orphan_mech", "3")
            rows += text_scan(rel, C4_PAT, "c4_pop_parallel", "4")
            rows += text_scan(rel, C5_PAT, "c5_affair_close", "5")
            if rel.startswith("tests/"):
                rows += text_scan(rel, C6_PROSE_PY, "c6_prose_lock", "6")
                rows += text_scan(rel, C6_STRUCT, "c6_struct_contract", "6")
    for rel in web:
        if rel.endswith((".ts", ".tsx")):
            rows += text_scan(rel, C6_PROSE_TS, "c6_prose_lock", "6")
            rows += text_scan(rel, C6_STRUCT, "c6_struct_contract", "6")
        if rel.startswith("tests/"):
            rows += text_scan(rel, C6_PROSE_PY, "c6_prose_lock", "6")
            rows += text_scan(rel, C6_STRUCT, "c6_struct_contract", "6")
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
            "c5_affair_close", "c6_prose_lock",
        }]

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    text = buf.getvalue()
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
