# #1902 修内司 G1/G2 回执

- 分支：`ak-roles/1902-f1-f4-fix`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座：相对 `94f5289f1` + 上轮 F1–F4 结清后重交
- **判词**：本轮用户判词在角色会话新消息；本回执**未**冒称已读取原判全文——目标按用户转述 + 现代码/既有用例核实

七 BIN 前缀（下文一律完整写出；禁止省略）：

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

临时目录（仅工作树外 / 系统临时；跑完可清）：`/tmp/ming1902-g1g2-selfverify/`

---

## 上轮回执更正（事实）

上一回执 `evidence/issue-1902/f1-f4-fix-receipt.md` 写「325 passed」——那是**子集聚焦**（cli/web entry + 若干召对文件），**没有**覆盖本票触及的全部现存 Python 测试面。

本票触及面真源 = `git diff --name-only --diff-filter=d 94f5289f1 HEAD -- tests` 中现存 `tests/test_*.py`（33 文件；不含 `conftest.py` 作路径参数）。上轮用户口径 `3 failed / 740 passed / 1 skipped` 即该面；本轮修后应为全绿。

---

## G1 — 合法全署理多旨 `acting_appointment` 无颁布方式

### 根因

`extract_draft_intent` 多旨路径在 `acting_appointment` 旁路**之前**执行：

```text
if not text or mode is None or ... → invalid_batch = True
```

全署理合法产物常无「颁布方式」→ `mode is None` → 被标非法。F1 把 `invalid_batch` 从「洗成无意图」改成 `raise ValueError` 后，原先靠洗白碰巧绿的多旨全署理案（`test_draft_extraction_does_not_capture_acting_appointment[2]`）变红。单旨路径本就在 mode 校验前旁路署理，故 `[1]` 仍绿。

### 官方简单方案

与单旨等价：classify 之后、`mode`/正文校验之前处理 `acting_appointment`（`drafts.append(None); continue`）。只旁路署理；其它动作缺 mode / 错计数 / 非法动作仍 `invalid_batch`→raise，不放松非法负向。

### 代码

- `ming_sim/cli_backend.py`：多旨循环内署理旁路上移到 `mode is None` 门之前

### 入口案

- 基底绿当前红→修后绿：`tests/test_decree_dossiers_571.py::test_draft_extraction_does_not_capture_acting_appointment[2]`
- 单旨仍无：同参 `[1]`

### 非法负向探针（不得放松）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-g1g2-selfverify
cd "$ROOT"
mkdir -p "$TMP"
with_bins env PYTHONPATH=. python3 <<'PY' | tee "$TMP/g1-illegal-probes.out"
import json, ming_sim.cli_backend as cb

def run(raw, n):
    cb._run_backend_for_config = lambda *a, **k: (json.dumps(raw, ensure_ascii=False), {})
    return cb.extract_draft_intent("x", "y", draft_count=n)

r = run({"成品旨稿":[
    {"正文":"命洪承畴暂署兵部尚书","动作类型":"acting_appointment","目标类型":"office","目标ID":"兵部尚书"},
    {"正文":"命卢象升暂署五军都督府都督同知","动作类型":"acting_appointment","目标类型":"office","目标ID":"五军都督府都督同知"},
]}, 2)
print("LEGAL_ALL_ACTING", r["draft_action"], r.get("drafts"))

try:
    run({"成品旨稿":[
        {"正文":"拨银赈陕","动作类型":"grant_allocation","目标类型":"region","目标":"shaanxi","金额":1,"账户":"国库"},
        {"正文":"再拨","动作类型":"grant_allocation","目标类型":"region","目标":"shaanxi","金额":1,"账户":"国库"},
    ]}, 2)
    print("ILLEGAL_NO_MODE FAIL washed")
except ValueError as e:
    print("ILLEGAL_NO_MODE_RAISE", str(e)[:60])

try:
    run({"成品旨稿":[
        {"正文":"只一道","动作类型":"policy","目标类型":"policy","目标ID":"x","颁布方式":"普通"},
    ]}, 2)
    print("ILLEGAL_WRONG_COUNT FAIL washed")
except ValueError as e:
    print("ILLEGAL_WRONG_COUNT_RAISE", str(e)[:60])

r1 = run({"拟旨意图":"拟旨","正文":"命洪承畴暂署兵部尚书","动作类型":"acting_appointment","目标类型":"office","目标ID":"兵部尚书"}, 1)
print("SINGLE_ACTING", r1["draft_action"])
PY
```

实测：

```text
LEGAL_ALL_ACTING 无 []
ILLEGAL_NO_MODE_RAISE 多旨稿抽取批次非法：成品旨稿形状或分类不符
ILLEGAL_WRONG_COUNT_RAISE 多旨稿抽取批次非法：成品旨稿形状或分类不符
SINGLE_ACTING 无
```

### 变异（临时改源码旧序；只 /tmp 备份；立刻恢复）

旧序（`mode` 门在署理旁路前）→ `[2]` 红、`[1]` 绿；恢复后 4 入口案全绿。

```text
MUT G1: 1 failed, 1 passed  （[2] ValueError invalid_batch；real ~1.07s）
RESTORE: 4 passed in 0.75s
```

---

## G2 — CLI 会话轻壳缺 `pending_audience_reply_retries`

### 根因

`terminal._print_interrupted_reply_retry_hint` / `_retry_interrupted_reply_cli` 取数走会话层 `pending_audience_reply_retries`（#1902 F2）。`tests/test_audience_presence_500.py` 的 `_cli_session` SimpleNamespace 未挂该方法 → dismiss / court_break 两案基底即 `AttributeError`。

### 官方简单方案

与已修的 `tests/test_audience_night_498.py` 同形：轻壳补

```python
pending_audience_reply_retries=lambda: [],
```

（无中断可重试 → 空列表；与真会话无夜同形。）

### 全类机械枚举与成员保留理由

类定义：**会进入 `minister_chat` → `_print_interrupted_reply_retry_hint` 的 CLI 会话轻壳**（`SimpleNamespace` 带 `chat`/`scene_chat` 或 `schedule_pending_scene_translation`+db/state/content，且所在文件调用 `minister_chat`）。

枚举（AST；完整可重放）：

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-g1g2-selfverify
cd "$ROOT"
mkdir -p "$TMP"
python3 <<'PY' | tee "$TMP/g2-class-enum.out"
import ast, pathlib
ROOT = pathlib.Path(".")
members = []
for path in sorted((ROOT/"tests").rglob("*.py")):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name != "SimpleNamespace":
            continue
        keys = {kw.arg for kw in node.keywords if kw.arg}
        if not (
            keys & {"chat", "scene_chat"}
            or (
                {"db", "state", "content"} <= keys
                and "schedule_pending_scene_translation" in keys
            )
        ):
            continue
        if "answer" in keys and "db" not in keys:
            continue
        members.append({
            "file": str(path),
            "line": node.lineno,
            "has": "pending_audience_reply_retries" in keys,
            "keys": sorted(keys),
            "minister_chat_file": "minister_chat" in src,
        })
for m in members:
    if not m["minister_chat_file"]:
        status = "OUT_OF_CLASS"
        reason = "文件不调 minister_chat；不经 terminal 重试提示"
    elif m["has"]:
        status = "OK_HAS"
        reason = "轻壳已挂 pending_audience_reply_retries"
    else:
        status = "NEED_FIX"
        reason = "缺方法会 AttributeError"
    print(f"{status}\t{m['file']}:{m['line']}\t{reason}\tkeys={m['keys']}")
print("NEED_FIX", sum(1 for m in members if m["minister_chat_file"] and not m["has"]))
PY
```

修后实测成员：

| 状态 | 成员 | 保留/处置理由 |
|---|---|---|
| OK_HAS | `tests/test_audience_night_498.py:621` | 上轮 F2 已挂空 lambda；保留 |
| OK_HAS | `tests/test_audience_presence_500.py:101` | **本轮补挂**；与 498 同形 |
| OUT_OF_CLASS | `tests/test_chat_stream_failpaths_393.py:110` | Web `install_hall_admission` 壳，不经 `minister_chat` / `_print_interrupted_reply_retry_hint` |
| （真会话） | `_hall_session` / `_sess`→`GameSession` | 类方法已有；非 SimpleNamespace 轻壳， naturally OK |

`NEED_FIX` count = **0**。

生产侧仅 `ming_sim/cli/terminal.py` 调用该方法；Web 轻壳不在本类。

### 变异

剥离轻壳方法 → dismiss/court_break 两案红（AttributeError）；恢复后绿。

```text
MUT G2: 2 failed  （AttributeError pending_audience_reply_retries；real ~1.07s）
RESTORE: 4 passed
```

---

## 聚焦测试（本票触及全部现存 Python；非全仓 suite）

文件列表真源：`/tmp/ming1902-g1g2-selfverify/focus-py.txt`（33 个 `tests/test_*.py`，来自 `git diff --name-only --diff-filter=d 94f5289f1 HEAD -- tests`）。

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-g1g2-selfverify
cd "$ROOT"
FOCUS=()
while IFS= read -r f; do FOCUS+=("$f"); done < "$TMP/focus-py.txt"

/usr/bin/time -p env \
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp="$TMP/focus-final" \
  "${FOCUS[@]}"
```

实测：

```text
743 passed, 1 skipped in 39.89s
real 40.55s
```

对照上轮用户口径 `3 failed / 740 passed / 1 skipped`：三红已消，740+3=743。

### TS

本轮未改 TS。上轮 F1–F4 回执四文件 vitest（`ministerScrollLens` / `modals` / `appDurableWiring` / `cliRunners`）128 passed——**沿用此前实测，本轮不可伪称新跑**。

---

## 自查二连

- 同类型：G1 多旨与单旨署理旁路顺序对齐；G2 轻壳与 `test_audience_night_498` 同形挂空重试取数
- 引入 bug：非法缺 mode / 错计数仍 raise；未放松负向；未新增证明测试；未改治理/宿主；未 stash/amend/push/PR

未跑全量 suite（#1185：切片聚焦）。
