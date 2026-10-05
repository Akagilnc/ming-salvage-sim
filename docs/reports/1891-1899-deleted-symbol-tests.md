# #1891/#1899 CLEANUP-C1 已删符号 — 短回执

现场：`ak-roles/1891-class-sweep`。仅 CLEANUP-C1；CHOICE 不送修。主助手 readonly：冻结卷缺符闭包 **PASS**（代码合法不动；不新框架；不复跑测试）。
**本轮：仅追加主助手独立复核事实（docs-only forward）**——不改码；不重复施工／测试。复核前 HEAD＝`04c488a4c48d2c49364f2ba0a624c486aec9bc2d`。

## 撤回

1. 超授权：`ENUMERATE_AND_RESOLVE.py`+AUDIT+全员 JSON/TSV/卡片已 forward 删（`a0ae52798`）。证据只在 `/tmp/cleanup-c1-forward-delete.hIkScB`。
2. 簿记／统计口径失败史：`members=3450`／`unique(file,line,kind,target,attr)=3445`／`sites_total=3447` 有重复差异——**撤回唯一精准总数**；独立去重≈3447 候选、**dedup=3445**。**member 不证明 1 missing**。不得再把 3450／3445／3447 当sole totals。
3. 旧 inline 摘要 **破损史**（`exists=2521 dynamic=124 missing=2`）：(a) `except SyntaxError: continue` 吞错；(b) `setattr("a.b.attr", value)` 118 条两参 string 误当 `attr=None`→dynamic124=118+6。勿用于全扫。

## 真残留（已删）／nonprod／dynamic

| nodeid | 取证 | 处置 |
| --- | --- | --- |
| `tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement` | `AttributeError: ming_sim.decree has no attribute '_next_attempt'`；**1 failed in 0.67s**（史：`/tmp/cleanup-c1-narrow-red.log`；forensic 0.69s） | 删 test（`4f277c384`） |

KEEP `error_pack._next_attempt`。barrier pytest PASSED。第二缺符：无。邻批史 **1 failed, 20 passed**；删后聚焦史 **19 passed**（`test_rejection_wiring` 整文件 −1 案 + error_pack 两案 + barrier）。

**9 nonprod**（原记录 `…/nonprod.json`）：`cb.os.path.isdir`；`os.kill`/`os._exit`/`time.sleep`×2；`sys.frozen`/`sys._MEIPASS`（raising=False）。

**6 dynamic**（真非 const）：`conftest#332` field；`audience_background#71` `_name`；`cli_backend#161/#895` attr 循环；`#909/#932` `f"_run_{runner}"`。

## 192／32（不冒称）

原 audit 只报 **192** 摘要、**无成员**——不冒称逐项全解析。冻结 `prior_pass_note`：**32 unresolved→0**；dynamic **6**。fixture／candidate **无法机械判定**；深解析证据在卷，不称纯静态全闭合。

## 自包含辅助扫描（七 BIN + 新 user；不 seed／不落仓）

```bash
TMPROOT=$(mktemp -d /tmp/cleanup-c1-aux-scan.XXXXXX)
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR="$TMPROOT/user"; mkdir -p "$MING_SIM_USER_DATA_DIR"
PY=${PY:-/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python}
$PY - <<'PY'
import ast, importlib, json
from collections import Counter
from pathlib import Path
ROOT, PROD = Path(".").resolve(), ("ming_sim", "web_app")
def walk(base):
    for p in sorted(base.rglob("*.py")):
        if any(x in p.parts for x in (".venv", "node_modules", "__pycache__")): continue
        yield p
def imap(tree):
    m = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names: m[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                if a.name != "*": m[a.asname or a.name] = f"{n.module}.{a.name}"
    return m
def rmod(name, m): return m.get(name) or m.get(name.split(".")[0]) if name else None
def cstr(n): return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None
def kwb(node, k, d):
    for kw in node.keywords:
        if kw.arg == k and isinstance(kw.value, ast.Constant): return bool(kw.value.value)
    return d
def exists(parts, attr):
    last = None
    for cut in range(len(parts), 0, -1):
        mod = ".".join(parts[:cut])
        try: obj = importlib.import_module(mod)
        except ModuleNotFoundError as e:
            last = {"class": type(e).__name__, "message": str(e),
                    "cause": type(e.__cause__).__name__ if e.__cause__ else None, "mod": mod}; continue
        except Exception as e:
            return "import_error", {"class": type(e).__name__, "message": str(e),
                "cause": type(e.__cause__).__name__ if e.__cause__ else None, "mod": mod}
        try:
            for p in parts[cut:]: obj = getattr(obj, p)
            return (("exists" if hasattr(obj, attr) else "missing") if attr is not None else "target_ok"), mod
        except AttributeError as e:
            last = {"class": type(e).__name__, "message": str(e),
                    "cause": type(e.__cause__).__name__ if e.__cause__ else None, "mod": mod}; continue
        except Exception as e:
            return "import_error", {"class": type(e).__name__, "message": str(e),
                "cause": type(e.__cause__).__name__ if e.__cause__ else None, "mod": mod}
    return "unresolved_import", last
errs, cands = [], []
for path in walk(ROOT / "tests"):
    src, rel = path.read_text(encoding="utf-8"), str(path.relative_to(ROOT))
    try: tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        errs.append({"file": rel, "lineno": e.lineno, "msg": e.msg}); continue
    m = imap(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod = rmod(node.value.id, m)
            if mod and mod.split(".")[0] in PROD:
                cands.append({"kind":"direct_ref","file":rel,"line":node.lineno,"target":node.value.id,"hint":mod,"attr":node.attr,"raising":None,"create":None})
        if not isinstance(node, ast.Call): continue
        f = node.func
        sattr = (isinstance(f, ast.Attribute) and f.attr == "setattr") or (isinstance(f, ast.Name) and f.id == "setattr")
        if sattr and len(node.args) >= 2:
            t0, t1, raising = node.args[0], node.args[1], kwb(node, "raising", True)
            if isinstance(t0, ast.Constant) and isinstance(t0.value, str):
                s0 = t0.value; parent, attr = (s0.rsplit(".", 1) if "." in s0 else (s0, None))
                cands.append({"kind":"setattr_string","file":rel,"line":node.lineno,"target":s0,"hint":parent,"attr":attr,"raising":raising,"create":None}); continue
            attr = cstr(t1) or next((cstr(kw.value) for kw in node.keywords if kw.arg == "name"), None)
            te = ast.unparse(t0) if hasattr(ast, "unparse") else None; hint = None
            if isinstance(t0, ast.Name): hint = rmod(t0.id, m)
            elif isinstance(t0, ast.Attribute) and isinstance(t0.value, ast.Name):
                b = rmod(t0.value.id, m); hint = f"{b}.{t0.attr}" if b else None
            cands.append({"kind":"setattr","file":rel,"line":node.lineno,"target":te,"hint":hint,"attr":attr,"raising":raising,"create":None})
        if isinstance(f, ast.Name) and f.id == "patch" and node.args:
            s = cstr(node.args[0])
            if s and s.split(".")[0] in PROD:
                parent, attr = (s.rsplit(".", 1) if "." in s else (s, None))
                cands.append({"kind":"patch_str","file":rel,"line":node.lineno,"target":s,"hint":parent,"attr":attr,"raising":True,"create":kwb(node,"create",False)})
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "patch" and f.attr == "object" and len(node.args) >= 2:
            hint = rmod(node.args[0].id, m) if isinstance(node.args[0], ast.Name) else None
            cands.append({"kind":"patch.object","file":rel,"line":node.lineno,"target":ast.unparse(node.args[0]) if hasattr(ast,"unparse") else None,
                "hint":hint,"attr":cstr(node.args[1]),"raising":kwb(node,"raising",True),"create":kwb(node,"create",False)})
if errs: raise SystemExit("PARSE_ERRORS " + json.dumps(errs, ensure_ascii=False))
out = []
for c in cands:
    hint, attr, raising, create, kind = c.get("hint"), c.get("attr"), c.get("raising"), c.get("create"), c["kind"]
    if hint == "sys" and attr in ("frozen", "_MEIPASS"):
        out.append({**c, "verdict": "nonprod_stdlib"}); continue
    if attr is None and kind in ("setattr", "patch.object"):
        out.append({**c, "verdict": "dynamic_attr"}); continue
    if (not hint or not all(x.isidentifier() for x in str(hint).split("."))
            or (hint.split(".")[0] not in PROD and kind not in ("setattr_string", "patch_str"))):
        out.append({**c, "verdict": "candidate"}); continue  # fixture 不猜 db/cc
    v, d = exists(hint.split("."), attr)
    if v == "missing":
        if raising is False: v = "missing_raising_false"
        elif create is True: v = "missing_create_true"
    out.append({**c, "verdict": v, "detail": d})
key = lambda x: (x.get("file"), x.get("line"), x.get("kind"), x.get("target"), x.get("attr"))
dedup = list({key(x): x for x in out}.values())
print(json.dumps({"candidates_raw": len(out), "candidates_dedup": len(dedup),
    "setattr_string": sum(1 for x in dedup if x["kind"] == "setattr_string"),
    "verdict_counts_dedup": dict(Counter(x["verdict"] for x in dedup)),
    "dynamic": [{"file": x["file"], "line": x["line"]} for x in dedup if x["verdict"] == "dynamic_attr"],
    "nonprod_stdlib": [{"file": x["file"], "line": x["line"], "attr": x.get("attr"), "raising": x.get("raising")}
                       for x in dedup if x["verdict"] == "nonprod_stdlib"],
    "missing": [x for x in dedup if str(x["verdict"]).startswith("missing")],
    "import_error": [x for x in dedup if x["verdict"] == "import_error"][:10],
    "parse_errors": errs}, ensure_ascii=False, indent=2))
PY
```

inline＝枚举+存在性；string／`raising=False`／`patch.create` 缺失单独记非自动 OK；真 import 异常保留 type/message/cause；缩短路径只吞预期 ModuleNotFound／AttributeError；未 resolve→`candidate`。

### 实测（`$TMPROOT=/tmp/cleanup-c1-aux-scan.UNanwE`）

```
candidates_raw=2968  dedup=2967  setattr_string=118
verdicts: exists=2632  candidate=327  dynamic_attr=6  nonprod_stdlib=2
missing=[]  import_error=[]  parse_errors=[]
```

副本：`/tmp/cleanup-c1-forward-delete.hIkScB/aux-scan-corrected-summary.json`。旧 `rerun-enum.json` 破损勿用。

## 自查二连

1. 同类：框架已删；`_next_attempt` 唯一真红已删；barrier 绿；32→0／6 dynamic；192 不冒称；簿记已撤回；**0.67 红／19 绿／超框架 forward 删／统计口径失败史原样保留**。
2. 引入：本 forward **只 docs**；不动码；不新工具；不复跑测试。

## 主助手独立复核（CLEANUP-C1；事实证据；非施工／非庭审）

**执行者**：主助手（非 worker）。**性质**：对短回执既有修正辅助扫描 + 聚焦选择器的**独立复跑取证**；**不重复施工／不另写测试／不改生产代码**。
**代码结果交付边界**：目标＝事实证据回执 forward；**非**目标 merge，**非**庭审收敛。
**复核 HEAD**：`04c488a4c48d2c49364f2ba0a624c486aec9bc2d`（相对代码交卷 `1045ec657`／删红案 `4f277c384`／超框架删 `a0ae52798`）。
**临时根**：`/tmp/1891-deleted-symbol-independent.3sPPTP/`（`enum.py`／`enum.log`／`command.txt`／`focus.log`／`user`／`pytest`）。
**失败史**：上文 **0.67 红／19 绿／超授权框架 forward 删／簿记与破损统计口径** **原样保留、不改写**；本节只证修后修正口径。
**边界**：非 fixture 候选闭包**不能**靠此辅助机械断言；沿原冻结深解析取证（fixture／candidate 无法机械判定——见「192／32」）。

### A) 独立辅助扫描（回执 inline 抽取）

做法：从本短回执既有 bash fence 抽取修正口径 inline，写入 `$TMPROOT/enum.py` 后直接运行。

```bash
TMPROOT=/tmp/1891-deleted-symbol-independent.3sPPTP
$PY "$TMPROOT/enum.py" | tee "$TMPROOT/enum.log"
```

主助手实测摘要（数字以 `enum.log` 为准，不改写）：

| 指标 | 值 |
| --- | --- |
| candidates_raw／dedup／setattr_string | **2968／2967／118** |
| exists／candidate／dynamic_attr／nonprod_stdlib | **2632／327／6／2** |
| missing／import_error／parse_errors | **[]／[]／[]** |

### B) 独立聚焦 pytest（8 selectors → 参数化 34）

8 选择器：`test_rejection_wiring` 整文件 + `error_pack` 两案 + barrier 案 + CLI 4 个 dynamic nodeids（实际 parameter 扩成 **34**）。真实命令全文在 `$TMPROOT/command.txt`：

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider --basetemp=/tmp/1891-deleted-symbol-independent.3sPPTP/pytest -q --tb=short tests/test_rejection_wiring.py tests/test_error_pack.py::test_next_attempt_skips_malformed_and_foreign_entries tests/test_error_pack.py::test_attempt_derived_from_existing_dirs tests/test_mechanical_tail_1845.py::test_web_barrier_resumes_pending_tail_before_join tests/test_cli_backend.py::test_run_backend_dispatch tests/test_cli_backend.py::test_run_backend_dispatch_new_runners tests/test_cli_backend.py::test_run_backend_for_config_dispatches_new_runners tests/test_cli_backend.py::test_clichat_call_cli_dispatches_new_runners
```

安全 env（七项 BIN=`/usr/bin/false` + 字节码关 + 新 user／basetemp；`-p no:cacheprovider`）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR=/tmp/1891-deleted-symbol-independent.3sPPTP/user
```

结果：`focus.log` → **`34 passed in 1.17s`**；主助手墙钟 **1.633s**。未跑全量／真实宿主／网络模型。不冒称 typecheck。

### C) 独立 Ruff F401／F821

```bash
UV_TOOL_DIR=/tmp/1891-uv-tools UV_CACHE_DIR=/tmp/1891-uv-cache \
  uv tool run --from ruff==0.11.2 ruff check --target-version py313 --select F401,F821 \
  tests/test_rejection_wiring.py
```

结果：**All checks passed!**

### D) 工作树洁净

相对复核前 HEAD `04c488a4c48d2c49364f2ba0a624c486aec9bc2d`：`git diff --check 1045ec657..HEAD` 与 `git status` **均无输出**（本 forward 提交前工作树仅追加本节后的 docs diff）。

## 提交约束声明（本轮：docs-only 独立复核 forward）

本轮仅 forward `ak-roles:` **docs**（追加主助手独立复核事实证据；保留 0.67 红／19 绿／超框架 forward 删／统计口径失败史）；不 amend／stash／reset／checkout 覆盖／rebase／squash／push／PR；不改生产／测试代码；不改宪法／Soul／宿主配置／席位表；不造通用机制或永久自证测试；不重复施工／测试；不抹失败史；不冒称正式庭审；不把辅助机械扫描冒称非 fixture 候选全闭合；`git diff --check` 绿。
