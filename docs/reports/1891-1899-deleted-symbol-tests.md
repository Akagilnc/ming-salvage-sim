# #1891/#1899 CLEANUP-C1 已删符号 — 短回执（forward 删简）

现场：`ak-roles/1891-class-sweep`。范围：**仅** CLEANUP-C1；**CHOICE 不送修**。

## 撤回（框架超授权）

**明确撤回**：曾把仓内 `ENUMERATE_AND_RESOLVE.py`（835 行）+ `AUDIT_COMMANDS.sh` + 全员 JSON/TSV/卡片包装成「一次性／不新框架」——那是**新增永久扫描壳与报告生成物**，超出「inline 一次性审计」授权。

**本提交 forward 删除**（史保留，不 amend／reset）：上述脚本、66524 行 `sites.json`、3451 行 CRLF `sites.tsv`、runtime／missing／nonprod／dynamic 及 cards 八份重叠摘要。**不**再声称仓内永久脚本「不是新框架」。分类语义由人复核；复跑只用下方自包含 AST 枚举，**不以**旧 3k／判词名单 seed。

证据卷（仅取证，非 runtime／测试依赖）：
`/tmp/cleanup-c1-forward-delete.hIkScB`（`POINTER.md` + `repo-committed/` + `closure-logs/` + `prior-audit/`）。原 3k 全员冻结只在该卷，**不灌入本回执**。

## 本类真残留（已删）

| nodeid | 取证 | 处置 |
| --- | --- | --- |
| `tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement` | `AttributeError: ming_sim.decree has no attribute '_next_attempt'` | **删该 test 整段**（史：`4f277c384`）；不恢复符号；不改挂 `error_pack` |

KEEP：`ming_sim.error_pack._next_attempt` 与 `tests/test_error_pack.py` 现役案。

聚焦（七 BIN + 新 user／basetemp + no cache）删后：**19 passed**（史留 `4f277c384`；代码删不动）。

## 9 nonprod（确切 nodeid／理由；非本类删案）

| nodeid | target.attr | 理由 |
| --- | --- | --- |
| `tests/test_cli_backend.py::test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare` | `cb.os.path.isdir` | 经生产模块挂到 **stdlib** `os.path` |
| `tests/test_menu_lifecycle_drain_396.py::test_shutdown_waits_for_drain_before_returning_or_killing` | `os.kill` / `os._exit` / `time.sleep` | **stdlib** |
| `tests/test_menu_lifecycle_drain_396.py::test_shutdown_without_web_game_skips_drain_and_kills` | `os.kill` / `os._exit` / `time.sleep` | **stdlib** |
| `tests/test_person_transit_write_667.py::test_departure_reads_matrix_from_frozen_bundle_outside_cwd` | `sys.frozen` / `sys._MEIPASS` | **stdlib** |

## 6 dynamic（协议 + 真实位置；不解 class 映射猜 OK）

| 位置 | 协议／取证 |
| --- | --- |
| `tests/conftest.py::plant_character_axis_sentinels#332` | `setattr(character, field, value)` 非 const 字段循环 |
| `tests/test_audience_background.py` helper `__init__#71` | `setattr(self, _name, MethodType(...))` 测试双绑定 |
| `tests/test_cli_backend.py::test_run_backend_dispatch#161` | `monkeypatch.setattr(cb, attr, …)` 循环；现役 `_run_claude/_agy/_codex/_backend` 有，字面 `_run_backend_dispatch` 无＝循环名非符号 |
| `tests/test_cli_backend.py::test_run_backend_dispatch_new_runners#895` | 同上；现役 `_run_cursor/_kimi/_grok/_pi/_backend` |
| `tests/test_cli_backend.py::test_run_backend_for_config_dispatches_new_runners#909` | `setattr(cb, f"_run_{runner}", …)` |
| `tests/test_cli_backend.py::test_clichat_call_cli_dispatches_new_runners#932` | 同上 |

## 深解析候选（按真实目标合并；原「192 unresolved」无成员冻结）

原 `/tmp/cleanup-c1-audit/runtime_verified.json` 只报 **192 skip_unresolved_target** 摘要、无逐项表。闭包后按**可核目标**合并同 target（sites 重复折叠；全文员只在证据卷）：

| 真实目标 | 来源协议 | sites（合并后） | 语义 |
| --- | ---: | ---: | --- |
| `ming_sim.db.GameDB` | game unpack / `type(db)` / named fixture / `game.db` / `runtime.db` | 63 | fixture／解包→GameDB；hasattr 核 |
| `ming_sim.db.GameDB.affairs` / `.textual_facts` / `.conn` | 实例链 | 6 | 非顶层删符；协议核 |
| `ming_sim.session.GameSession` | `game.session` / `web_game.session` | 3 | 会话实例 |
| `ming_sim.cli_backend.CliChat` | 局部 `CliChat(...)` 构造赋值 | 5 | 非按名猜 |
| `ming_sim.models.GameState` | fixture `state` / `load_state` 返回注 | 2 | |
| `ming_sim.content.GameContent` | fixture `content` | 1 | dataclass 字段如 `event_by_id` |
| `*.subprocess` / `*.shutil` / `*.agents` 等 | 模块属性链到挂载对象 | ~24 | import 别名上的 attr |
| `session_write_queue…barrier` | **pytest PASSED** 取证回 OK | 1 | 静态曾误绑函数→假 MISSING |

不把「解不了的 class」映射猜成 OK；dynamic／fixture 见上表。

## 自包含复跑（~100 行；不 seed／tmp 旧表；不落仓脚本）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=${PY:-/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python}
$PY - <<'PY'
import ast, importlib, json, sys
from pathlib import Path
ROOT = Path(".").resolve()
PROD = ("ming_sim", "web_app")

def walk_py(base):
    for p in sorted(base.rglob("*.py")):
        if any(x in p.parts for x in (".venv", "node_modules", "__pycache__")):
            continue
        yield p

def import_map(tree):
    m = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                m[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                if a.name == "*":
                    continue
                m[a.asname or a.name] = f"{n.module}.{a.name}"
    return m

def resolve_mod(name, imap):
    if not name:
        return None
    if name in imap:
        return imap[name]
    top = name.split(".")[0]
    return imap.get(top)

def const_str(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None

cands = []
for path in walk_py(ROOT / "tests"):
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    imap = import_map(tree)
    rel = str(path.relative_to(ROOT))
    for node in ast.walk(tree):
        func = None
        # setattr / monkeypatch.setattr
        if isinstance(node, ast.Call):
            f = node.func
            name = None
            if isinstance(f, ast.Attribute) and f.attr == "setattr":
                name = "setattr"
            elif isinstance(f, ast.Name) and f.id == "setattr":
                name = "setattr"
            if name and len(node.args) >= 2:
                tgt, attr_n = node.args[0], node.args[1]
                attr = const_str(attr_n)
                te = ast.unparse(tgt) if hasattr(ast, "unparse") else None
                hint = None
                if isinstance(tgt, ast.Name):
                    hint = resolve_mod(tgt.id, imap)
                elif isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name):
                    base = resolve_mod(tgt.value.id, imap)
                    hint = f"{base}.{tgt.attr}" if base else None
                elif const_str(tgt):
                    hint = const_str(tgt)
                    te = hint
                cands.append({"kind": "setattr", "file": rel, "line": node.lineno,
                              "target": te, "hint": hint, "attr": attr,
                              "raw": ast.get_source_segment(src, node) or ""})
            # patch("mod.path") / patch.object
            if isinstance(f, ast.Attribute) and f.attr in ("patch", "object"):
                pass
            if isinstance(f, ast.Name) and f.id == "patch" and node.args:
                s = const_str(node.args[0])
                if s and s.split(".")[0] in PROD:
                    cands.append({"kind": "patch_str", "file": rel, "line": node.lineno,
                                  "target": s, "hint": s, "attr": s.rsplit(".", 1)[-1], "raw": s})
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "patch" and f.attr == "object":
                if len(node.args) >= 2:
                    te = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else None
                    attr = const_str(node.args[1])
                    hint = resolve_mod(te, imap) if isinstance(node.args[0], ast.Name) else None
                    cands.append({"kind": "patch.object", "file": rel, "line": node.lineno,
                                  "target": te, "hint": hint, "attr": attr, "raw": ""})
        # direct module.attr / Class.attr from import map
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod = resolve_mod(node.value.id, imap)
            if mod and mod.split(".")[0] in PROD:
                cands.append({"kind": "direct_ref", "file": rel, "line": node.lineno,
                              "target": node.value.id, "hint": mod, "attr": node.attr, "raw": ""})

# runtime hasattr for resolvable module/Class hints only (no fixture guess)
out = []
for c in cands:
    hint, attr = c.get("hint"), c.get("attr")
    verdict, detail = "candidate", "unresolved_or_nonconst"
    if hint and attr and all(x.isidentifier() for x in hint.split(".")):
        parts = hint.split(".")
        # try module path; if last is Class, import parent
        for cut in range(len(parts), 0, -1):
            modname = ".".join(parts[:cut])
            try:
                obj = importlib.import_module(modname)
                for p in parts[cut:]:
                    obj = getattr(obj, p)
                if cut == len(parts):
                    ok = hasattr(obj, attr)
                else:
                    ok = hasattr(obj, attr)
                verdict = "exists" if ok else "missing"
                detail = f"importlib:{modname}"
                break
            except Exception as e:
                detail = f"import_fail:{type(e).__name__}"
                continue
        else:
            verdict = "unresolved"
    elif not attr:
        verdict = "dynamic_attr"
        detail = "non-const attr"
    out.append({**c, "verdict": verdict, "detail": detail})

from collections import Counter
print(json.dumps({"candidates": len(out), "verdict_counts": Counter(x["verdict"] for x in out),
                  "missing_sample": [x for x in out if x["verdict"] == "missing"][:20]},
                 ensure_ascii=False, indent=2))
# semantic class (OK/nonprod/dynamic/deep) = human review against member tables above / evidence volume
PY
```

说明：命令只吐 **candidate 列表 + importlib/hasattr 可核存在性**；不把 fixture／实例链猜 OK；不写仓内 scanner；分类引用本回执成员表与证据卷冻结全员。

### 本轮实测复跑（自包含；不 seed）

```
candidates=2968
verdict_counts: exists=2521  candidate/unresolved=321  dynamic_attr=124  missing=2
missing 仅：tests/test_person_transit_write_667.py:64–65  sys.frozen / sys._MEIPASS
  → 属上表 9 nonprod（stdlib 可选属性；raising=False），非已删生产符号
decree._next_attempt：rejection_wiring 已无引用（删项闭合）
```

完整 JSON：`/tmp/cleanup-c1-forward-delete.hIkScB/rerun-enum.json`。

## 自查二连

1. **同类**：超授权框架／全员灌仓已 forward 删；真 MISSING 仅 `_next_attempt` 专属案已删；9／6 表有确切 nodeid；192 无成员冻结→合并目标表 +／tmp 全员指针；复跑命令自包含不 seed。
2. **引入 bug**：只删文档／报告生成物与脚本；不动已合入的合法测试删与 19 绿史；不为证删造测。
