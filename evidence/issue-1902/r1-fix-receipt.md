# #1902 修内司 R1 回执 — 仅重开 N5（+ 依附 N1 死分支）

- 分支：`ak-roles/1902-n1-n7-fixer-ccbdf378a`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 本轮底座 HEAD（开工）：`043efc2ac`
- 本轮代码提交：`d450631d1fb9d84ddc80a6b3000ebd694f212057`
- 回执盖章 HEAD（初版）：`8b6e640529fd637b0d5c31c2e703e17a59408370`
- **本轮回执纠正提交**：`8836dff2c05ce3d04a8a956a57df7bb8aa29eac1`
- 判词真源（完整原文，非摘要）：宿主 continue payload
  `AK_ROLE_RUN_DIR/.../session/session.jsonl` L41（`status=continue` finding R1）
  + 原法源/boundary：`fix-packet.md` + 附件 `03-1902-judge-ccbdf378a.json` 末 payload N5
- **本轮范围**：只重开 N5；N2/N3/N4/N6/N7 **不重开**
- 枚举原始输出（入库，可重放）：`evidence/issue-1902/r1-n5-enum.out`
- 复扫原始输出：`evidence/issue-1902/r1-n5-rescan.out`
- 聚焦测试原始输出：`evidence/issue-1902/r1-n5-focus-pytest.txt`
- 临时目录（墙钟副份，**不替代**入库证据 / **不替代**下方可执行命令）：`/tmp/ming1902-r1-n5-replay/`

七 BIN 前缀（显式展开七个，非 brace 简写）：

```bash
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest ...
```

---

## 新判词原文（R1 / N5 重开；逐字自 session）

```json
{"status":"continue","findings":[{"id":"R1","severity":"P2","class":"共享抽取能力仍携带不可达旧模式（N5 未清净）；N1 首抽新增分支亦不可达","law":"#1902共享核只因现役消费者保留；#1812重构验收第1项（被取代/无消费者的旧路删净）；全局硬规12（复杂度即成本）；同类自归类自扫（陛下09-06原话）。","phenomenon":"N5 回执称 n5_dead_mode_sites=[] 已结清，但共享抽取仍带一整套无任何生产消费者的“召对交办后置点将/承办人必有”模式。","evidence":["全仓 grep：require_execution_lead=、harvest_participants= 在 ming_sim/、web_app.py、tests/ 内无任何调用点传入；唯一生产链是 resubmit_draft_admission_payload(cli_backend.py:2994)→extract_draft_intent_with_roster_heal，且它只传 initial_correction，不传 require_execution_lead。","遗留成员（均仅因该死模式存在）：cli_backend.py MissingExecutionLeadError(1310)、_extract_result_has_execution_lead(2195)、_missing_execution_lead_feedback(2224)、_participant_fields_from_draft_obj(2275)、heal 的 require_execution_lead 形参与 _lead_gate(2326；调用点 2429/2444/2508/2512)、extract_draft_intent 的 harvest_participants 形参及 2690 的 empty.update 分支。本轮 diff 反而把 **extract_kwargs 改写成显式 harvest_participants 形参，把死模式固化为签名。","N1 新增的首抽分支（cli_backend.py:~2616 `raise cli_runner_unavailable(...)`）：唯一生产调用 resubmit 的 initial_correction 恒非空（build_draft_admission_resubmit_feedback 总产出非空 failure_reason 文本），故 `if correction_block: raise` 恒先命中，新分支在生产不可达；回执所称“首抽真落痕变异”是在死路径上探的，是为死路径新增机制。","根因：N5 枚举谓词只按判词点名的四个 kwarg（draft_count/existing_candidates/has_pending_draft/existing_draft_text）取样，未按“该共享核有无现役消费者”定类，正是陛下09-06所斥的把判词样本当类边界。"]}],"fix":{"summary":"按类重扫：以“非测试生产调用链（仅 resubmit→heal→extract）是否消费”为谓词，枚举 extract_draft_intent / extract_draft_intent_with_roster_heal 及其 helper 中全部无现役消费者的模式，连同只为它们存在的测试一并删净（require_execution_lead、harvest_participants、MissingExecutionLeadError、_lead_gate 与上列 helper）；N1 新增的首抽 cli_runner_unavailable 分支若生产不可达则一并删除，不得为死路径保留机制或变异证明。保留现役单旨补交及其必要承接（判词 boundary）；解析失败/缺键/非法枚举响亮上抛真因与合法“无”保留不动。枚举命令与成员表写回执。其余 N2/N3/N4/N6/N7 本轮抽查未见问题，不重开。"},"note":"已核：N7 相对 10e64fbef 差分为空；N2/N3/N4 抽查入口已走共核/直调；N1 解析/缺键/非法枚举已上抛真因。仅 N5 类（及依附的 N1 新增死分支）未清净。"}
```

原 N5 boundary（附件 03，仍生效）：「保留现役单旨补交及其必要模式承接；不能按旧函数名整删。修理死多旨分支本身不能替代清退。」

---

## 纠正旧回执（`n1-n7-fix-receipt.md`）不适用之处

| 旧回执声称 | 本轮裁定 |
|---|---|
| N5「结清」：`n5_dead_mode_sites=[]`（只按旧四 kwarg） | **证据不适用 / 谓词收窄**。未按「非测试生产调用链是否消费」定类，漏掉整套 lead/harvest 死模式。 |
| N1「首抽 LLM Exception → `cli_runner_unavailable`」结清 + `n1_first_draw_trace` 变异 | **死路径结清 / 证据不适用**。生产链 `resubmit` 的 `initial_correction` 恒非空 → `if correction_block: raise` 恒先命中；该分支与为其做的变异证明一并清退。 |
| N1 解析失败/缺键/非法枚举真因上抛 | **仍成立，保留**（本轮未动）。 |
| N2/N3/N4/N6/N7 结清 | **本轮不重开**（判词 note 抽查未见问题）；不在此复验。 |

---

## 枚举命令（谓词：非测试生产调用链是否消费；可重放原文）

以下为**本轮实际运行**的命令（heredoc AST 一次性内联，**未**入库永久扫描脚本）。
完整 stdout → `evidence/issue-1902/r1-n5-enum.out`。

### A) 机械扫生产调用点 + tests 死 kwarg + session 链

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
{
echo "=== PROD CALL SITES (ming_sim/ + web_app.py; exclude tests/; rg -F) ==="
for pat in \
  'require_execution_lead=' \
  'harvest_participants=' \
  'extract_draft_intent(' \
  'extract_draft_intent_with_roster_heal(' \
  'resubmit_draft_admission_payload(' \
  'MissingExecutionLeadError' \
  '_extract_result_has_execution_lead' \
  '_missing_execution_lead_feedback' \
  '_participant_fields_from_draft_obj' \
  '_lead_gate' \
  'cli_runner_unavailable'
do
  echo
  echo "[$pat]"
  rg -nF --glob '*.py' --glob '!tests/**' -e "$pat" "$ROOT/ming_sim" "$ROOT/web_app.py" 2>/dev/null \
    | sed "s|^$ROOT/||" || true
  echo "count=$(rg -nF --glob '*.py' --glob '!tests/**' -e "$pat" "$ROOT/ming_sim" "$ROOT/web_app.py" 2>/dev/null | wc -l | tr -d ' ')"
done

echo
echo "=== TESTS kwarg pass-in (rg -F) ==="
rg -nF --glob '*.py' -e 'require_execution_lead=' -e 'harvest_participants=' -e 'MissingExecutionLeadError' "$ROOT/tests" 2>/dev/null \
  | sed "s|^$ROOT/||" || echo "(none)"
echo "count=$(rg -nF --glob '*.py' -e 'require_execution_lead=' -e 'harvest_participants=' -e 'MissingExecutionLeadError' "$ROOT/tests" 2>/dev/null | wc -l | tr -d ' ')"

echo
echo "=== session→resubmit production chain ==="
rg -nF -e '_resubmit_draft_admission_failures' -e 'resubmit_draft_admission_payload' \
  "$ROOT/ming_sim/session.py" "$ROOT/ming_sim/cli_backend.py" \
  | sed "s|^$ROOT/||"

echo
echo "=== draft_intent cli_runner_unavailable (backend=\"draft_intent\") ==="
rg -n -e 'backend=["'\'']draft_intent["'\'']' "$ROOT/ming_sim" "$ROOT/web_app.py" 2>/dev/null \
  | sed "s|^$ROOT/||" || echo "(none)"
} > /tmp/ming1902-r1-n5-replay/enum-mech.out
```

### B) AST：extract / heal 签名、分支、生产调用图、feedback 恒非空

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
python3 - <<'PY' > /tmp/ming1902-r1-n5-replay/enum-ast.out
import ast
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5")
src = (ROOT / "ming_sim/cli_backend.py").read_text(encoding="utf-8")
tree = ast.parse(src)

TARGETS = {
    "extract_draft_intent_with_roster_heal",
    "extract_draft_intent",
    "build_draft_admission_resubmit_feedback",
    "resubmit_draft_admission_payload",
    "MissingExecutionLeadError",
    "_extract_result_has_execution_lead",
    "_missing_execution_lead_feedback",
    "_participant_fields_from_draft_obj",
}

print("=== AST SIGNATURES / CLASS DEFS in cli_backend.py ===")
found = set()
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name in TARGETS:
        found.add(node.name)
        print(f"class {node.name} @ L{node.lineno}")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in TARGETS:
        found.add(node.name)
        args = []
        a = node.args
        for x in list(a.posonlyargs) + list(a.args):
            args.append(x.arg)
        if a.vararg:
            args.append("*" + a.vararg.arg)
        for x in a.kwonlyargs:
            args.append(x.arg + "=")
        if a.kwarg:
            args.append("**" + a.kwarg.arg)
        print(f"def {node.name}({', '.join(args)}) @ L{node.lineno}-L{node.end_lineno}")

missing = sorted(TARGETS - found)
print("missing_defs=", missing)

print()
print("=== BRANCH / MODE SITES inside extract + heal (If / nested defs / Name refs) ===")
for node in tree.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if node.name not in {"extract_draft_intent_with_roster_heal", "extract_draft_intent"}:
        continue
    print(f"\n--- {node.name} L{node.lineno}-L{node.end_lineno} ---")
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not node:
            if node.lineno <= sub.lineno <= (node.end_lineno or node.lineno):
                print(f"  nested def {sub.name} @ L{sub.lineno}")
    interest = (
        "require_execution_lead", "harvest_participants", "correction_block",
        "correction_feedback", "initial_correction", "_lead_gate",
        "cli_runner_unavailable", "MissingExecutionLeadError",
        "_participant_fields_from_draft_obj", "_extract_result_has_execution_lead",
    )
    for sub in ast.walk(node):
        if isinstance(sub, ast.If):
            snippet = ast.get_source_segment(src, sub.test) or ""
            if any(k in snippet for k in interest):
                print(f"  if {snippet} @ L{sub.lineno}")
        if isinstance(sub, ast.Call):
            seg = ast.get_source_segment(src, sub) or ""
            if any(k in seg for k in (
                "cli_runner_unavailable", "_lead_gate",
                "_participant_fields_from_draft_obj",
                "_extract_result_has_execution_lead",
                "_missing_execution_lead_feedback",
                "MissingExecutionLeadError",
            )):
                head = seg.split("\n", 1)[0][:120]
                print(f"  call {head} @ L{sub.lineno}")
        if isinstance(sub, ast.keyword) and sub.arg in {
            "require_execution_lead", "harvest_participants", "initial_correction",
            "correction_feedback",
        }:
            val = ast.get_source_segment(src, sub.value) or "?"
            print(f"  kw {sub.arg}={val} @ L{sub.lineno}")

print()
print("=== CALL GRAPH: who calls extract/heal/resubmit (prod py via AST Name) ===")
prod_files = list((ROOT / "ming_sim").rglob("*.py")) + [ROOT / "web_app.py"]
want_calls = {
    "extract_draft_intent",
    "extract_draft_intent_with_roster_heal",
    "resubmit_draft_admission_payload",
    "build_draft_admission_resubmit_feedback",
}
for path in sorted(prod_files):
    text = path.read_text(encoding="utf-8")
    try:
        t = ast.parse(text)
    except SyntaxError as e:
        print(f"SYNTAX {path}: {e}")
        continue
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            fn = n.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name in want_calls:
                rel = path.relative_to(ROOT)
                print(f"  {rel}:{n.lineno}: {name}(...)")
                for kw in n.keywords:
                    if kw.arg:
                        v = ast.get_source_segment(text, kw.value) or "?"
                        print(f"    kw {kw.arg}={v.splitlines()[0][:80]}")

print()
print("=== build_draft_admission_resubmit_feedback emptiness proof ===")
import sys
sys.path.insert(0, str(ROOT))
from ming_sim.cli_backend import build_draft_admission_resubmit_feedback
for reason in ("", "x", "fail"):
    fb = build_draft_admission_resubmit_feedback(
        failure_reason=reason,
        bad_payload={"draft_action": "拟旨", "draft_text": "t"},
        decree_text="旨文",
    )
    print(
        f"  reason={reason!r} len={len(fb)} empty={not bool(fb.strip())} "
        f"head={fb[:40]!r}"
    )
PY
```

### C) 合并入库

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
{
  cat /tmp/ming1902-r1-n5-replay/enum-mech.out
  echo
  cat /tmp/ming1902-r1-n5-replay/enum-ast.out
} > "$ROOT/evidence/issue-1902/r1-n5-enum.out"
```

### 枚举输出短摘（完整见 `r1-n5-enum.out`）

```text
[require_execution_lead=] count=0
[harvest_participants=] count=0
[extract_draft_intent(] count=2
  ming_sim/cli_backend.py:2265: result = extract_draft_intent(
  ming_sim/cli_backend.py:2479: def extract_draft_intent(
[extract_draft_intent_with_roster_heal(] count=2
  def @ L2228 ; call from resubmit @ L2887
[resubmit_draft_admission_payload(] count=2
  def @ L2861 ; session.py:1844
MissingExecutionLeadError / _extract_result_has_execution_lead /
_missing_execution_lead_feedback / _participant_fields_from_draft_obj → 0
_lead_gate → 仅 docstring 清退注记 1 行
backend="draft_intent" → (none)
TESTS kwarg pass-in → count=0
AST missing_defs= [MissingExecutionLeadError, _extract_result_has_execution_lead,
  _missing_execution_lead_feedback, _participant_fields_from_draft_obj]
heal 签名：initial_correction=（无 require_execution_lead）
extract 签名：correction_feedback, …（无 harvest_participants）
CALL GRAPH 唯一生产链：
  session._resubmit → resubmit_draft_admission_payload
    → build_draft_admission_resubmit_feedback → heal(initial_correction=feedback)
    → extract(correction_feedback=correction)
feedback emptiness：reason=''/'x'/'fail' 均 empty=False
```

关键生产链事实：

- 唯一生产消费者：`session._resubmit_draft_admission_failures` → `resubmit_draft_admission_payload` → `extract_draft_intent_with_roster_heal(..., initial_correction=feedback)` → `extract_draft_intent(..., correction_feedback=correction)`
- `build_draft_admission_resubmit_feedback` 对空/非空 reason 均 `empty=False`（恒有成案失败头 + 失败事实 + 原产物）→ **生产 resubmit 必非空 correction**
- `require_execution_lead=` / `harvest_participants=`：**生产 0 传入**；tests 0 传入
- `require_execution_lead_or_raise`（`executor_routing.py` / `db.py`）= **不同符号**，成案路由闸，**非本类成员**，保留

---

## 完整成员表（N5；谓词=生产是否消费）

| # | 成员 | 生产消费者？ | 处置 | 理由 |
|---|---|---|---|---|
| 1 | `MissingExecutionLeadError` | 无 | **删** | 仅服务 require_execution_lead 死模式 |
| 2 | `_extract_result_has_execution_lead` | 无 | **删** | 仅 `_lead_gate` 用 |
| 3 | `_missing_execution_lead_feedback` | 无 | **删** | 仅 `_lead_gate` 用 |
| 4 | `_participant_fields_from_draft_obj` | 无 | **删** | 仅 `harvest_participants` 空包 update |
| 5 | heal 形参 `require_execution_lead` | 无（生产从不传） | **删** | 签名固化死模式 |
| 6 | heal 内 `_lead_gate` + 4 调用点 | 无（`require_execution_lead` 恒假时恒直通） | **删**；调用点改直接 `return` | 无现役消费者模式 |
| 7 | heal→extract 的 `harvest_participants=` | 无 | **删** | 由 require 派生，无生产 True |
| 8 | extract 形参 `harvest_participants` | 无 | **删** | 同上 |
| 9 | extract「无」分支 `empty.update(_participant_fields...)` | 无 | **删** | 仅 harvest 真时可达 |
| 10 | extract 首抽 `cli_runner_unavailable(backend="draft_intent")`（`if not correction_block`） | 无（resubmit correction 恒非空） | **删** | 依附 N1 为死路径新增机制；不为死路径留变异证明 |
| 11 | extract try/except 中 `if correction_block: raise` | 有（生产恒走此臂） | **简化为异常原样上抛**（去掉整段 try/except） | 生产行为不变：LLM 失败原样冒泡 |
| 12 | 单旨补交 `resubmit→heal→extract` + `initial_correction` | **有** | **保留** | boundary：现役单旨补交必要承接 |
| 13 | heal 组合校验纠错 / 名册 heal / `UnknownParticipantEscalate` | **有**（经 resubmit） | **保留** | 补交必要模式承接 |
| 14 | 解析失败 / 缺「拟旨意图」/ 非法枚举 → `ValueError` 真因 | **有** | **保留** | N1 真因上抛；boundary 不洗「无」 |
| 15 | 合法「无」→ `draft_action=无` 短路；resubmit 承接「未返回拟旨意图」 | **有** | **保留** | boundary：合法「无」非解析失败 |
| 16 | extract 单旨成功路径（拟旨/push/grant/…/participant_roster 字段） | **有** | **保留** | 现役单旨结构，非后置点将模式 |
| 17 | `require_execution_lead_or_raise`（executor_routing/db） | 有（成案路由） | **保留（非本类）** | 不同 API；勿与 extract kwarg 混淆 |

### 死路径测试清退核对（不得用跑绿替代删除）

依 R1：只删「仅因死路径存在」的测试；**不得**因聚焦绿就留下死夹具。

| 候选 | 是否仅服务死模式？ | 处置 |
|---|---|---|
| tests 内 `require_execution_lead=` / `harvest_participants=` / `MissingExecutionLeadError` | **0 命中**（见 enum） | 无平行死夹具可删 |
| `n1_first_draw_trace` 变异 / `backend="draft_intent"` 首抽夹具 | 已随代码清退；仓库内无残留 | 无 |
| `tests/...::test_first_draw_parse_failure_heals_then_degrades` | **否** — `#1801` 批红 `generate_rescript_draft` heal，**不**触 `extract_draft_intent` / 死 correction 臂 | **保留**（现役批红 heal） |
| `test_combo_correction_preserves_first_draw_roster` | **否** — 现役 heal 组合纠错名册冻结 | **保留**（必要承接案） |

结论：本轮**无需再删测试**；生产代码侧死模式已在 `d450631d1` 清退。跑绿只作触及面复核，不替代清退判定。

---

## 复扫（修后；可重放）

实际运行：

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
{
echo "=== RESCAN zero-table (prod + tests; rg -F) ==="
for pat in \
  'MissingExecutionLeadError' \
  '_extract_result_has_execution_lead' \
  '_missing_execution_lead_feedback' \
  '_participant_fields_from_draft_obj' \
  'harvest_participants' \
  'require_execution_lead=' \
  '_lead_gate'
do
  c_prod=$(rg -nF --glob '*.py' --glob '!tests/**' -e "$pat" "$ROOT/ming_sim" "$ROOT/web_app.py" 2>/dev/null | wc -l | tr -d ' ')
  c_test=$(rg -nF --glob '*.py' -e "$pat" "$ROOT/tests" 2>/dev/null | wc -l | tr -d ' ')
  echo "$pat  prod=$c_prod  tests=$c_test"
done
echo
echo "backend=draft_intent:"
rg -n -e 'backend=["'\'']draft_intent["'\'']' "$ROOT" --glob '*.py' 2>/dev/null | sed "s|^$ROOT/||" || echo "(none)"
echo
echo "require_execution_lead (any, docstring note):"
rg -n -e 'require_execution_lead' "$ROOT/ming_sim/cli_backend.py" | sed "s|^$ROOT/||" || true
} > "$ROOT/evidence/issue-1902/r1-n5-rescan.out"
```

输出短摘（完整见 `r1-n5-rescan.out`）：

```text
MissingExecutionLeadError  prod=0  tests=0
_extract_result_has_execution_lead  prod=0  tests=0
_missing_execution_lead_feedback  prod=0  tests=0
_participant_fields_from_draft_obj  prod=0  tests=0
harvest_participants  prod=0  tests=0
require_execution_lead=  prod=0  tests=0
_lead_gate  prod=1  tests=0   # 仅 docstring 清退注记
backend=draft_intent: (none)
```

AST 签名（修后，见 enum）：

- `extract_draft_intent_with_roster_heal(..., initial_correction=)` — 无 `require_execution_lead`
- `extract_draft_intent(..., correction_feedback, …, db)` — 无 `harvest_participants`

---

## 聚焦测试（七 BIN 显式展开；未跑全量）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT"
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-r1-n5-replay/focus \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_decree_dossiers_571.py \
  tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes \
  tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades \
  tests/test_executor_routing_721.py \
  | tee evidence/issue-1902/r1-n5-focus-pytest.txt
```

结果：`171 passed in 5.83s`（见 `r1-n5-focus-pytest.txt`）。

不为 finding 新增平行证明测试；不为死路径保留变异机制。`test_first_draw_parse_failure_heals_then_degrades` 留在触及面是因为批红现役 heal，不是 draft_intent 无 correction 死臂。

---

## 结清总表（本轮）

| 类 | 状态 | 依据 |
|---|---|---|
| N5 | **结清**（本轮） | 可重放枚举命令 + 入库原始输出 + 生产消费谓词全员表 + 复扫 0 |
| N1 依附死分支（首抽 `cli_runner_unavailable`） | **随 N5 清退** | 生产不可达；解析真因上抛与合法「无」保留 |
| N2/N3/N4/N6/N7 | **不重开** | 判词 note |

自查二连 done。

---

## 交卷（回执纠正轮）

- 状态：`STATUS=receipt-corrected`（仅回执/证据；生产代码仍为 `d450631d1`）
- query SHA：`8836dff2c05ce3d04a8a956a57df7bb8aa29eac1`（内容纠正 commit；本 stamp 另笔，禁 amend）
- 实际枚举命令所在行（`evidence/issue-1902/r1-fix-receipt.md`）：
  - A 机械扫：L64–L105
  - B AST heredoc：L109–L242
  - C 合并入库：L246–L253
  - 复扫：L333–L357
  - 聚焦七 BIN：L381–L404
- 测试：`171 passed in 5.83s`（七 BIN 显式展开；`r1-n5-focus-pytest.txt`）
