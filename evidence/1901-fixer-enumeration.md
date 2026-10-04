# #1901 fixer — 退役军饷 path 脚手架全仓枚举

只记扫描事实与成员处置；不复制宪法。

## 类定义（本轮残余谓词）

票面/判词类：迁出军饷模块仍保留退役财政兼容路径。  
本轮复扫在上轮已把 `PATHS` 收成单值之后，谓词为：

1. 只有现役一值（`PATHS = ("substrate_hub",)` 或等价）却仍维护旧军饷 `fiscal_path` 参数 / 三元 / 矩阵；
2. 关 cutover 种 scalar 反事实若只是旧 scalar 维护；
3. DB 第三振 `apply_army_deltas` adapter 事实契约（非结算兼容）可保留须说明。

## 实际执行命令（AST 扫描）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1901-w5`  
解释器：`../Ming_LLM/.venv/bin/python`

```bash
PYTHONDONTWRITEBYTECODE=1 ../Ming_LLM/.venv/bin/python <<'PY'
"""AST scan: retired army-pay fiscal-path scaffolding with single active value."""
from __future__ import annotations
import ast, json
from pathlib import Path

ROOT = Path('.').resolve()
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', 'dist', 'build', 'evidence'}
results = []

def walk_py():
    for p in ROOT.rglob('*.py'):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p

for path in sorted(walk_py()):
    try:
        src = path.read_text(encoding='utf-8')
        tree = ast.parse(src, filename=str(path))
    except Exception as e:
        results.append({"file": str(path.relative_to(ROOT)), "parse_error": str(e)})
        continue
    lines = src.splitlines()
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == 'PATHS' and isinstance(node.value, (ast.Tuple, ast.List)):
                    vals = [e.value if isinstance(e, ast.Constant) else ast.unparse(e) for e in node.value.elts]
                    hits.append({
                        "kind": "PATHS_ASSIGN", "line": node.lineno, "values": vals,
                        "single_active_substrate_hub": vals == ["substrate_hub"],
                        "snippet": lines[node.lineno-1].strip(),
                    })
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'parametrize' and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and a0.value == 'fiscal_path':
                hits.append({"kind": "PARAMETRIZE_FISCAL_PATH", "line": node.lineno,
                             "arg1": ast.unparse(node.args[1]) if len(node.args) > 1 else None,
                             "snippet": lines[node.lineno-1].strip()})
            if isinstance(a0, ast.Constant) and a0.value == 'cutover':
                hits.append({"kind": "PARAMETRIZE_CUTOVER", "line": node.lineno,
                             "arg1": ast.unparse(node.args[1]) if len(node.args) > 1 else None,
                             "snippet": lines[node.lineno-1].strip()})
        if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == 'fiscal_path':
            hits.append({"kind": "TERNARY_FISCAL_PATH", "line": node.lineno,
                         "snippet": lines[node.lineno-1].strip(), "expr": ast.unparse(node)})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            if 'fiscal_path' in args:
                hits.append({"kind": "FUNC_PARAM_FISCAL_PATH", "line": node.lineno, "name": node.name, "args": args})
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'fiscal_path':
            if node.comparators and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value in ("substrate_hub", "legacy"):
                hits.append({"kind": "COMPARE_FISCAL_PATH", "line": node.lineno,
                             "rhs": node.comparators[0].value, "snippet": lines[node.lineno-1].strip()})
    for i, line in enumerate(lines, 1):
        if "__army_pay_source_cutover" in line and ('value=0' in line or ',0,' in line or ', 0,' in line):
            hits.append({"kind": "CUTOVER_OFF_LINE", "line": i, "snippet": line.strip()})
        if '_disable_army_pay_source_cutover' in line:
            hits.append({"kind": "DISABLE_CUTOVER_HELPER", "line": i, "snippet": line.strip()})
        if 'across_paths' in line or '跨财政路径' in line:
            hits.append({"kind": "CROSS_PATH_PROSE", "line": i, "snippet": line.strip()})
    if hits:
        results.append({"file": str(path.relative_to(ROOT)), "hit_count": len(hits), "hits": hits})

print(json.dumps(results, ensure_ascii=False, indent=2))
PY
```

原始 JSON 落盘：`/tmp/1901-fixer-enum/scan.json`（修前）、`/tmp/1901-fixer-enum/post_scan.json`（修后同脚本）。

## 修前成员表

| # | 文件 | hit_count | kinds | 处置 |
|---|------|-----------|-------|------|
| 1 | `tests/test_mutiny_latch_315.py` | 25 | PATHS_ASSIGN, PARAMETRIZE_FISCAL_PATH, FUNC_PARAM_FISCAL_PATH, TERNARY_FISCAL_PATH, COMPARE_FISCAL_PATH, CUTOVER_OFF_LINE | **修**：删 PATHS/参数/三元/parametrize；豁免军关 cutover 种 scalar → 现役合法零份额零欠饷种子 |
| 2 | `tests/test_mutiny_progression_316.py` | 11 | PATHS_ASSIGN, PARAMETRIZE_FISCAL_PATH, FUNC_PARAM_FISCAL_PATH, TERNARY_FISCAL_PATH, COMPARE_FISCAL_PATH | **修**：删 PATHS/参数/三元/parametrize；central=arrears 分源种子 |
| 3 | `tests/test_mutiny_redemption_317.py` | 12 | 同上 + CROSS_PATH_PROSE | **修**：同上；去「跨财政路径」措辞 |
| 4 | `tests/test_mutiny_third_strike_318.py` | 22 | 同上 + PARAMETRIZE_CUTOVER×3 | **修**：删 fiscal_path 脚手架；**保留** cutover(0,1) adapter 矩阵并注明非结算兼容 |
| 5 | `tests/test_mutiny_noop_whitelist_319.py` | 7 | PATHS_ASSIGN, PARAMETRIZE_FISCAL_PATH, FUNC_PARAM_FISCAL_PATH, TERNARY_FISCAL_PATH, COMPARE_FISCAL_PATH | **修**：删 PATHS/参数/三元/parametrize；清 `"substrate_hub"` 位置参 |
| 6 | `tests/test_player_army_projection_321.py` | 8 | 同上 + CROSS_PATH_PROSE | **修**：删 PATHS/参数/三元；`across_paths` 用例改名 survives_reopen |
| 7 | `tests/test_effect_origin_558.py` | 1 | CUTOVER_OFF_LINE | **修**：删 cutover=0 legacy no-op 分支；改现役 cutover=1 + 分源欠饷种子 |
| 8 | `tests/test_fiscal_substrate_bridge.py` | 11 | CUTOVER_OFF_LINE, DISABLE_CUTOVER_HELPER | **不属本残余类**：无 PATHS/fiscal_path 单值脚手架；关 cutover 是为省级 substrate shadow 隔离坏基座（非种旧 scalar 军饷反事实）。记入扫描事实，本轮不改 |

### 逐成员扫描摘录（修前）

- `test_mutiny_latch_315.py:15` `PATHS = ("substrate_hub",)`；`:47/:59` `arrears if fiscal_path == "substrate_hub" else 0`；`:40-44` 关 cutover 种豁免 scalar。
- `test_mutiny_progression_316.py:13` PATHS 单值；`:35` 死三元；parametrize ×3。
- `test_mutiny_redemption_317.py:12` PATHS 单值；`:1` 「跨财政路径」；`:34` 死三元。
- `test_mutiny_third_strike_318.py:17` PATHS 单值；`:67` 死三元；`:229/:328/:371` cutover(0,1) adapter。
- `test_mutiny_noop_whitelist_319.py:17` PATHS 单值；`:94` 死三元；硬编码 `_set(db, "substrate_hub", ...)`。
- `test_player_army_projection_321.py:24` PATHS 单值；`:150` 死三元；`:315` across_paths parametrize。
- `test_effect_origin_558.py:321` cutover=0 `test legacy no-op`。
- `test_fiscal_substrate_bridge.py:283+` `_disable_army_pay_source_cutover` + 9 处调用（shadow 隔离）。

## 修后复扫

同脚本结果：仅 2 文件仍命中谓词相关 kind：

| 文件 | kinds | 说明 |
|------|-------|------|
| `tests/test_mutiny_third_strike_318.py` | PARAMETRIZE_CUTOVER ×3（L224/L323/L367） | **保留**：DB `apply_army_deltas` adapter 事实契约，非结算财政 path 兼容；用例 docstring 已标明 |
| `tests/test_fiscal_substrate_bridge.py` | DISABLE_CUTOVER_HELPER / CUTOVER_OFF_LINE | **保留扫描记录**：非本残余类（见上） |

`PATHS_ASSIGN` / `PARAMETRIZE_FISCAL_PATH` / `TERNARY_FISCAL_PATH` / `FUNC_PARAM_FISCAL_PATH` / `COMPARE_FISCAL_PATH` / `CROSS_PATH_PROSE` 在军饷消费者测试中 **0**。

## 聚焦测试（七环境变量前缀）

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1901-fixer-enum/focused2 \
  tests/test_mutiny_latch_315.py \
  tests/test_mutiny_progression_316.py \
  tests/test_mutiny_redemption_317.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_player_army_projection_321.py \
  tests/test_junxin_monthly_tick_314.py \
  tests/test_effect_origin_558.py \
  tests/test_army_salary_44.py
```

输出（`/usr/bin/time -p`）：

```
135 passed in 3.26s
real 3.80
user 2.49
sys 0.65
```

复用原入口用例，未造新案；不全量。
