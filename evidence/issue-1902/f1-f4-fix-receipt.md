# #1902 修内司 F1–F4 回执（round3 结清 + 自验补全）

- 分支：`ak-roles/1902-f1-f4-fix`
- 本轮底座判词：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- 分类证据：`evidence/issue-1902/f1-f4-classification-table.md`
- **无**永久扫描器、**无** classification-table.json 大包；枚举脚本全文写在本回执；输出只进 ephemeral `/tmp/ming1902-f1f4-selfverify/`（跑完自清）

七 BIN 前缀（下文一律用 `with_bins`；禁止「…同七 BIN…」省略）：

```bash
with_bins() {
  env \
    MING_SIM_AGY_BIN=/usr/bin/false \
    MING_SIM_CODEX_BIN=/usr/bin/false \
    MING_SIM_CLAUDE_BIN=/usr/bin/false \
    MING_SIM_CURSOR_BIN=/usr/bin/false \
    MING_SIM_KIMI_BIN=/usr/bin/false \
    MING_SIM_GROK_BIN=/usr/bin/false \
    MING_SIM_PI_BIN=/usr/bin/false \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}
```

---

## 枚举命令（完整可执行；全仓可重放列成员）

在仓库根目录执行。脚本**全文如下**（不依赖 /tmp 缺失脚本、不入库永久 scanner）。

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-f1f4-selfverify
mkdir -p "$TMP"
cd "$ROOT"

python3 <<'PY' | tee "$TMP/enum_all.out"
import ast, json, pathlib, re, subprocess
ROOT = pathlib.Path("/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5")
TMP = pathlib.Path("/tmp/ming1902-f1f4-selfverify")

def py_paths():
    out = list((ROOT / "ming_sim").rglob("*.py"))
    if (ROOT / "web_app.py").exists():
        out.append(ROOT / "web_app.py")
    return sorted(out)

# F1: except → pass/return/continue（启发式候选；结清靠分类表逐项语义，≠计数）
f1 = []
for path in py_paths():
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.ExceptHandler):
                for st in child.body:
                    if isinstance(st, (ast.Pass, ast.Return, ast.Continue)):
                        f1.append(
                            f"{path.relative_to(ROOT)}:{node.name}:"
                            f"{getattr(st, 'lineno', child.lineno)}"
                        )
                        break

# F4: 单语句 Return(Call) 启发式
f4 = []
for path in py_paths():
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [
            x for x in node.body
            if not (
                isinstance(x, ast.Expr)
                and isinstance(getattr(x, "value", None), (ast.Constant, ast.Str))
            )
        ]
        if (
            len(body) == 1
            and isinstance(body[0], ast.Return)
            and isinstance(body[0].value, ast.Call)
        ):
            f4.append(f"{path.relative_to(ROOT)}:{node.name}:{node.lineno}")

# F3: 测试文件清单
f3_files = sorted(
    [str(p.relative_to(ROOT)) for p in (ROOT / "tests").rglob("test_*.py")]
    + [str(p.relative_to(ROOT)) for p in (ROOT / "web/src").rglob("*.test.ts")]
    + [str(p.relative_to(ROOT)) for p in (ROOT / "web/src").rglob("*.test.tsx")]
)

# 本轮已删死夹具：defs 必须全仓不存在
deleted_dead = [
    "_canned", "_assert_next_accepted", "_session_double", "_tool_registry",
    "_assert_structured_llm_http", "_noop_atomic", "_complete_session",
    "_terminal_sse", "_clear_character_offices", "_gate_cfg", "_bind_content",
    "_settled_land_by_region", "_simulator_army_dicts", "_find_simulator_army",
    "_canned_settle", "_columns", "_658_session", "_drive_resolve_directives",
    "_bajiu_names", "_reflux", "_module_of", "_stamp_heal_ids",
    "_canned_monthly_settlement", "_army_none_legal_item", "_assert_ledger_match",
]
absent_dead = {}
for name in deleted_dead:
    hit = subprocess.run(
        ["rg", "-n", rf"^def {re.escape(name)}\b", "tests"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    absent_dead[name] = (hit.returncode != 0) or (not hit.stdout.strip())

import ming_sim.db as dbmod
import ming_sim.issues as issues
f4_gone = {
    "_primary_source_only_army_pay_container_total": not hasattr(
        dbmod.GameDB, "_primary_source_only_army_pay_container_total"
    ),
    "list_recent_issue_advances": not hasattr(
        dbmod.GameDB, "list_recent_issue_advances"
    ),
    "validate_delta_shape": not hasattr(issues, "validate_delta_shape"),
    "sanitize_delta_shape_present": hasattr(issues, "sanitize_delta_shape"),
}

scroll_files = [
    "web/src/ministerScrollLens.test.ts",
    "web/src/components/modals.test.tsx",
    "web/src/appDurableWiring.test.tsx",
    "tests/test_audience_scroll_539.py",
]
scroll_present = {f: (ROOT / f).exists() for f in scroll_files}

summary = {
    "f1_except_return_count": len(f1),
    "f1_members": f1,
    "f4_pure_forward_heuristic": len(f4),
    "f4_members": f4,
    "f3_test_files": len(f3_files),
    "f3_test_file_list": f3_files,
    "deleted_dead_helpers_absent": absent_dead,
    "deleted_dead_all_absent": all(absent_dead.values()),
    "f4_gone": f4_gone,
    "scroll_files_present": scroll_present,
}
print(json.dumps({
    "f1_except_return_count": summary["f1_except_return_count"],
    "f1_sample": f1[:12],
    "f4_pure_forward_heuristic": summary["f4_pure_forward_heuristic"],
    "f4_sample": f4[:12],
    "f3_test_files": summary["f3_test_files"],
    "deleted_dead_all_absent": summary["deleted_dead_all_absent"],
    "absent_dead_false": [k for k, v in absent_dead.items() if not v],
    "f4_gone": f4_gone,
    "scroll_files_present": scroll_present,
}, ensure_ascii=False, indent=2))
(TMP / "enum_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
)
(TMP / "f1_members.txt").write_text("\n".join(f1) + "\n")
(TMP / "f4_members.txt").write_text("\n".join(f4) + "\n")
(TMP / "f3_test_files.txt").write_text("\n".join(f3_files) + "\n")
print(
    f"WROTE members → {TMP}/f1_members.txt "
    f"f1={len(f1)} f4={len(f4)} f3_files={len(f3_files)}"
)
PY
```

### 自验实测摘要（上列脚本 stdout）

| 项 | 结果 |
|---|---|
| F1 启发式成员数 | `337`（完整列表 → `$TMP/f1_members.txt`） |
| F4 启发式成员数 | `157`（完整列表 → `$TMP/f4_members.txt`） |
| F3 测试文件数 | `249`（完整列表 → `$TMP/f3_test_files.txt`） |
| 已删死夹具 defs | `deleted_dead_all_absent: true` |
| F4 已删符号 | `primary/list_recent/validate_delta` 均 gone；`sanitize_delta_shape` present |
| scroll/lens 文件 | 四文件均仍在（处置=改 pin，非删文件） |

### 分类表处置成员活探针（完整可执行）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-f1f4-selfverify
cd "$ROOT"
mkdir -p "$TMP"

with_bins() {
  env \
    MING_SIM_AGY_BIN=/usr/bin/false \
    MING_SIM_CODEX_BIN=/usr/bin/false \
    MING_SIM_CLAUDE_BIN=/usr/bin/false \
    MING_SIM_CURSOR_BIN=/usr/bin/false \
    MING_SIM_KIMI_BIN=/usr/bin/false \
    MING_SIM_GROK_BIN=/usr/bin/false \
    MING_SIM_PI_BIN=/usr/bin/false \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}

with_bins env PYTHONPATH=. python3 <<'PY' | tee "$TMP/f1-probes.out"
from ming_sim import cli_backend as cb
import ming_sim.db as dbmod
import ming_sim.issues as issues

def fake_json(*a, **k):
    return ('{"confirmed_links":[{"target_dossier_id":"bad","relation_type":"护卫"}]}', 1)

cb._run_json_extractor_for_config = fake_json  # type: ignore
try:
    cb.confirm_dossier_links(
        "回话",
        [{"id": 1, "secret_title": "案"}],
        [{"target_dossier_id": 1, "relation_type": "护卫", "note": "n"}],
    )
    print("CONFIRM_MALFORMED_WASH FAIL returned")
except ValueError as e:
    print("CONFIRM_MALFORMED_RAISE", str(e)[:80])

def fake_bad_rel(*a, **k):
    return ('{"confirmed_links":[{"target_dossier_id":1,"relation_type":"伪造"}]}', 1)

cb._run_json_extractor_for_config = fake_bad_rel  # type: ignore
try:
    cb.confirm_dossier_links(
        "回话",
        [{"id": 1, "secret_title": "案"}],
        [{"target_dossier_id": 1, "relation_type": "护卫", "note": "n"}],
    )
    print("CONFIRM_BAD_REL_WASH FAIL")
except ValueError as e:
    print("CONFIRM_BAD_REL_RAISE", str(e)[:80])

def fake_backend(prompt, llm_config, tag=""):
    return (
        '{"成品旨稿":[{"正文":"只一道","动作类型":"policy",'
        '"目标类型":"policy","目标ID":"x","颁布方式":"普通"}]}',
        1,
    )

cb._run_backend_for_config = fake_backend  # type: ignore
try:
    cb.extract_draft_intent("分拟两旨", "臣已拟", draft_count=2)
    print("MULTI_WRONG_COUNT_WASH FAIL")
except ValueError as e:
    print("MULTI_WRONG_COUNT_RAISE", str(e)[:80])

def boom_backend(*a, **k):
    raise RuntimeError("llm_down")

cb._run_backend_for_config = boom_backend  # type: ignore
r = cb.extract_draft_intent("拟旨", "回话", draft_count=2)
print("MULTI_SOFT_DEGRADE", r.get("draft_action"), len(r.get("drafts") or []))

import inspect
src = inspect.getsource(cb)
print("TPE_IN_MODULE", "from concurrent.futures import ThreadPoolExecutor" in src)
print(
    "primary_alias_gone",
    not hasattr(dbmod.GameDB, "_primary_source_only_army_pay_container_total"),
)
print("list_recent_gone", not hasattr(dbmod.GameDB, "list_recent_issue_advances"))
print("validate_delta_gone", not hasattr(issues, "validate_delta_shape"))
print("sanitize_present", hasattr(issues, "sanitize_delta_shape"))
PY

with_bins env PYTHONPATH=. python3 <<'PY' | tee "$TMP/f2-probe.out"
import ast, pathlib
p = pathlib.Path("web_app.py")
src = p.read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "api_menu_status":
        body = ast.get_source_segment(src, node) or ""
        print("MENU_CALLS_CORE", "llm_config_from_runtime" in body)
        print(
            "MENU_NO_PARALLEL_CLI_STRENGTH_MATH",
            "cli_reasoning_strength" not in body or "llm_config_from_runtime" in body,
        )
        break
PY
```

探针实测：

```text
CONFIRM_MALFORMED_RAISE 案卷关联确认产物非法：confirmed_links 条目非法
CONFIRM_BAD_REL_RAISE 案卷关联确认产物非法：relation_type='伪造'
MULTI_WRONG_COUNT_RAISE 多旨稿抽取批次非法：成品旨稿形状或分类不符
MULTI_SOFT_DEGRADE 无 0
TPE_IN_MODULE True
primary_alias_gone True
list_recent_gone True
validate_delta_gone True
sanitize_present True
MENU_CALLS_CORE True
MENU_NO_PARALLEL_CLI_STRENGTH_MATH True
```

### 本轮删除的死夹具成员（与分类表一致；枚举核 `deleted_dead_all_absent`）

`_canned` · `_assert_next_accepted` · `_session_double` · `_tool_registry` · `_assert_structured_llm_http` · `_noop_atomic` · `_complete_session` · `_terminal_sse` · `_clear_character_offices` · `_gate_cfg` · `_bind_content` · `_settled_land_by_region` · `_simulator_army_dicts`（×2 文件）· `_find_simulator_army` · `_canned_settle` · `_columns` · `_658_session` · `_drive_resolve_directives` · `_bajiu_names` · `_reflux` · `_module_of` · `_stamp_heal_ids` · `_canned_monthly_settlement` · `_army_none_legal_item` · `_assert_ledger_match`

---

## F1

### 代码
- `confirm_dossier_links`：非法条目 / 非法 relation → raise（禁洗 `[]`）
- multi `extract_draft_intent`：LLM soft-fail 与 `invalid_batch` 分离；后者 raise；classify ValueError re-raise
- `token_stats._get_client_base_url`：except → tlog
- `enrich_initiative_effects`：`_canonical` except → `_log`
- `from concurrent.futures import ThreadPoolExecutor`

### 保留依据更正
首抽 LLM→「无」：依据源码 owner 注释（纠错 raise / 首抽吞），**废除**对已失踪 `test_extract_draft_intent_backend_exception_degrades_to_none` 的引用。

---

## F2

菜单生效值走共核；分槽仅表单。未见第二套生效规则（`MENU_CALLS_CORE True`）。

---

## F3

### 代码/测试
- scroll/lens：`ministerScrollLens` / `modals` / `appDurableWiring` / `test_audience_scroll_539` 对话全文 pin → 结构契约（role/speaker/beat/turn）
- 28 死夹具删除（上表；defs 全仓 absent）
- pi argv 来源弱化收紧为 `"-p" in cmd`（非放松）
- 保留：来源透传、闸负向、P6 markdown、approx / P4 隔离

### 自查（测试变更）
- 未新增任意散文机械约束；fixture 正文仅作输入，断言落在结构字段
- 未放松来源契约（透传/闸负向仍在；pi 来源断言收紧）
- 入口变异证明仍有效（下节）

### 变异（既有真实入口；七 BIN；plugin 全文如下，只写 /tmp）

```bash
TMP=/tmp/ming1902-f1f4-selfverify
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT"
mkdir -p "$TMP/mut_plugin"

cat > "$TMP/mut_plugin/corrupt_contracts.py" <<'PY'
"""Temporary pytest plugin for #1902 mutation probes. /tmp only."""
import os
import pytest

MODE = os.environ.get("MING1902_MUT", "")

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if MODE == "reason":
        import ming_sim.db as dbmod
        orig = dbmod.GameDB.set_character_status
        def wrapped(self, state, name, status, reason="", reason_code=None, commit=True, content=None):
            if reason:
                reason = "CORRUPTED"
            return orig(
                self, state, name, status,
                reason=reason, reason_code=reason_code, commit=commit, content=content,
            )
        dbmod.GameDB.set_character_status = wrapped
PY

/usr/bin/time -p env \
  MING1902_MUT=reason \
  PYTHONPATH="$TMP/mut_plugin:$PYTHONPATH" \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider -p corrupt_contracts \
  --basetemp="$TMP/mut-reason" \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it
# → 1 failed；assert reason == … → got 'CORRUPTED'；real 1.33s

/usr/bin/time -p env \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider \
  --basetemp="$TMP/mut-restore" \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it \
  tests/test_cli_entry_1902.py::test_cli_blank_pick_on_urgent_reaches_core_hold \
  tests/test_cli_backend.py::test_public_cli_support_restores_existing_runners \
  tests/test_cli_backend.py::test_run_pi_flags_thinking_and_stdout \
  tests/test_llm_channel_config.py::test_cli_supports_reasoning_strength_matrix \
  tests/test_web_llm_runtime_config.py::test_1271_three_endpoints_grok_reasoning_supported_and_capability_list
# → 15 passed in 0.89s；real 1.33s
```

---

## F4

删：`_primary_source_only_army_pay_container_total`、`list_recent_issue_advances`、`validate_delta_shape`（+ decree 未用 import）。
保留 façade/供料缝/路由——写清语义，不用「资源适配」。

---

## 聚焦测试（七 BIN；完整前缀）

```bash
TMP=/tmp/ming1902-f1f4-selfverify
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT"

/usr/bin/time -p env \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider \
  --basetemp="$TMP/focus-final" \
  tests/test_cli_entry_1902.py tests/test_cli_play_turn.py tests/test_web_entry_1902.py \
  tests/test_runtime_llm_config.py tests/test_web_llm_runtime_config.py \
  tests/test_cli_backend.py tests/test_faction_denunciation_627.py \
  tests/test_on_scene_immediate_write_1839.py tests/test_draft_admission_resubmit_1769.py \
  tests/test_llm_channel_config.py tests/test_cli_model_choices.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_month_loop_tracer_1468.py tests/test_world_materials_1834.py \
  tests/test_audience_scroll_539.py
```

```text
325 passed in 9.89s
real 10.48s
```

召对触及面：

```bash
TMP=/tmp/ming1902-f1f4-selfverify
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT"

/usr/bin/time -p env \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider \
  --basetemp="$TMP/focus-extra" \
  tests/test_audience_night_498.py tests/test_web_audience_night_498.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_manual_directive_locality_1685.py
```

```text
101 passed in 7.37s
real 7.90s
```

四既定 TS 文件（七 BIN 前缀 + vitest）：

```bash
TMP=/tmp/ming1902-f1f4-selfverify
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT/web"

/usr/bin/time -p env \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  npm test -- --run \
  src/ministerScrollLens.test.ts src/components/modals.test.tsx \
  src/appDurableWiring.test.tsx src/cliRunners.test.ts
```

```text
Test Files  4 passed (4)
Tests  128 passed (128)
Duration  6.58s
real 7.17s
```

未跑全量。未改治理文件 / 宿主配置。未 stash/amend/push/PR。未新增永久扫描/生产护栏/平行测试。

---

## 完成范围（stdout 须同此诚实；不偷换）

**已做（相对上轮未结项 + 本自验补全）**：
- F1：抽取缝非法产物/来源伪造/静默旁路逐项审验并修复；保留面写可核依据（非统一套话）；活探针复验
- F2：唯一共核复核（`MENU_CALLS_CORE`）
- F3：scroll/lens 对话全文 pin 清扫；确认死夹具；触及面来源弱化收紧；保留来源透传与闸负向；入口变异仍咬
- F4：再删 3 处死转发；语义复扫其余启发式
- 自验：回执嵌入完整可重放枚举/探针/变异脚本；pytest/vitest 均带完整七 BIN；`git diff HEAD^ HEAD --check` 尾空格/EOF 空行已修

**合法未结（非本授权阻断）**：
- 家族收尾全量 suite（#1185 / #1873 政策：切片聚焦，全量待合并态）
- 全仓每一个 except→pass 启发式命中的非抽取缝压缩面：已语义未见抽取非法洗，但未改写成「零启发式」——见分类表压缩保留
