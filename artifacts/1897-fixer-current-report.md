# #1897 修内司回执（J1 续修：无调用退休附属物）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-j1-j2-f3-fixer-20261005-101325`
- 相对基线：`10e64fbef2857a4603c51394d16cea791b4f44c2`
- 施工前 tip：`cb2dec1cc62c7e6a49d24274f2f5a14a40ec8ca1`
- 判词来源：本 pi 会话用户续修令（仅 J1 无调用退休附属物）；原 fix-packet=`~/.ak-roles/books/Ming_LLM/1897/runs/01a1099e-2506-7580-a2b3-0f15a8209f3b@fixer/fix-packet.md`；末份封存判词仍为 `…/attachments/03-1897-judge-5d0b04dec.json`（J2/F3 本回不扩改）
- 票面：`gh issue view 1897` / `1812`；验收真源=#1812「重构验收」
- 本回代码提交 SHA：`dc0470e445366fd411e0627ce672ff15ece149e2`（`git rev-parse HEAD` 于提交后实测；本段若另有 docs tip 钉针提交则以最新 HEAD 为准）

## 环境前缀

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

---

## J1：无人消费任命后传召旧路及附属物

### 类定义（本回用户判词）

boundary：任命后传召写缝及其无人消费附属物  
direction：核实生产唯一 `_apply_existing_appointment_hit` 调用不传 `summon_after`（默认 False）；清退 `_persist_appointment_summon`、参数/分支、`ensure_inactive_office_summon` 及其 activate/discard/延期批消费、专属测试与说明；有独立行为价值的用例复用现役入口，不造平行体系。  
保留：`dismiss_from_audience` / `stay_attend_in_audience`（玩家当场口令，开夜为来源）。

### 生产核实（施工前）

唯一生产调用：`ming_sim/declaration_dispatch.py:1624`

```
kwargs=['extracted_mode', 'region_id', 'minister_name', 'turn', 'annotate',
        'recommendation_fields', 'night_id', 'source_chat_turn_id']
summon_after_passed=False
```

`_commission_appointment_fields` 亦不透传 `summon_after`。故 `summon_after=True` 写路在生产无调用。

### 枚举命令（可复跑）

```bash
python3 - <<'PY'
import ast, re
from pathlib import Path
PATTERNS = [
    r'_persist_appointment_summon\b',
    r'ensure_inactive_office_summon\b',
    r'activate_office_summon\b',
    r'discard_inactive_office_summon\b',
    r'summon_after\b',
    r'任命后传召',
    r'stage_yuan_appointment_summon\b',
    r'_deferred_office_summon_nights\b',
]
hits = 0
for root in [Path('ming_sim'), Path('tests'), Path('docs'), Path('README.md')]:
    paths = [root] if root.is_file() else sorted(root.rglob('*'))
    for path in paths:
        if path.is_dir(): continue
        if path.suffix not in {'.py', '.md', '.json'} and path.name != 'README.md': continue
        if any(x in str(path) for x in ('__pycache__', 'CMR_', 'TEST_AUDIT', 'docs/raw', 'artifacts')): continue
        try: text = path.read_text(encoding='utf-8')
        except Exception: continue
        for i, line in enumerate(text.splitlines(), 1):
            matched = [p for p in PATTERNS if re.search(p, line)]
            if matched:
                hits += 1
                print(f'{path}:{i}: {matched} :: {line.strip()[:160]}')
print(f'# TOTAL_HITS={hits}')
src = Path('ming_sim/declaration_dispatch.py').read_text(encoding='utf-8')
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = ast.get_source_segment(src, node.func) or ''
        if '_apply_existing_appointment_hit' in fn:
            kws = [k.arg for k in (node.keywords or []) if k.arg]
            print(f'declaration_dispatch.py:{node.lineno}: kwargs={kws} summon_after_passed={"summon_after" in kws}')
PY
rg -n 'dismiss_from_audience|stay_attend_in_audience' ming_sim -g'*.py'
```

### 枚举实际输出（施工前 → 记账；落盘 `/tmp/1897-j1-summon/enum-pre.txt`）

施工前命中（逐项）：

| # | 位置 | 成员 |
|---:|---|---|
| 1 | `action_materialize.py:78` | `_persist_appointment_summon` 定义 |
| 2 | `action_materialize.py:96,121` | 调 `ensure_inactive_office_summon` |
| 3 | `action_materialize.py:114,116,172,183,229-230` | `summon_after` 写/参/分支 |
| 4 | `action_materialize.py:2310` | FieldSpec `summon_after`/`任命后传召` |
| 5 | `audience_night.py:1764` | `ensure_inactive_office_summon` |
| 6 | `audience_night.py:1791` | `discard_inactive_office_summon` |
| 7 | `audience_night.py:1820` | `activate_office_summon` |
| 8 | `db.py:15507-15525` | 颁布时 `summon_after==是` → activate + 延期夜批 |
| 9 | `db.py:18485` | slice 键 `summon_after` |
| 10 | `db.py:18799-800,18861-62,18945-47` | withdraw/drop/void 调 discard |
| 11 | `db.py:17081-17126` | `_deferred_office_summon_nights` 批脚手架 |
| 12 | `tests/legacy_staging_helpers.py:64-94,132` | `stage_yuan_appointment_summon`（无人 import） |
| 13 | `tests/test_audience_undo_506.py:578-635` | 两案直接调 `ensure_inactive_office_summon` |
| 14 | `tests/test_audience_travel_gating_670.py:1278-1345` | 专属任命+传召批消费案 |
| 15 | `docs/character-office-changes.md` / `README.md` | 任命并传召说明 |

调用图要点：生产 `_persist` 仅被 `_apply_existing_appointment_hit` 在 `summon_after and person_name` 时调用；生产唯一 hit 调用 **不传** `summon_after`。

### 成员与处置（本回）

| # | 成员 | 处置 |
|---:|---|---|
| 1 | `_persist_appointment_summon` | **删** |
| 2 | `_apply_existing_appointment_hit.summon_after` / `person_name` / `origin_chat_turn_id` 及分支 | **删**（仅服务传召写） |
| 3 | FieldSpec `summon_after` | **删** |
| 4 | `ensure_inactive_office_summon` | **删**（生产唯消费=_persist） |
| 5 | `activate_office_summon` | **删**（唯消费=颁布 summon_after 枝） |
| 6 | `discard_inactive_office_summon` + db withdraw/drop/void 调用 | **删** |
| 7 | `_deferred_office_summon_nights` 批脚手架 | **删** |
| 8 | db slice 键 / 颁布 summon_after 枝 | **删** |
| 9 | `stage_yuan_appointment_summon` | **删**（死夹具） |
| 10 | `test_undo_erases_inactive_office_summon_…` / `test_reject_pending_discards_…` | **删**（专属直调 ensure） |
| 11 | `test_fresh_summon_same_beizhili_journey_…` | **删**；#670 同人多 origin 已由 `record_summon_fresh` 现役入口案承接（同文件 `test_multi_origin_fresh_*`） |
| 12 | `docs/character-office-changes.md` / `README.md` 任命并传召说明 | **清** |
| 13 | `CHANGELOG.md` #672 历史条 | **保留**（发行史，非现役路径说明） |

### 保留依据：`dismiss_from_audience` / `stay_attend_in_audience`

- 非任命后传召旧路；是召对夜内玩家当场口令（告退／留侍）。
- 现役消费：`cli/terminal.py`、`session.py`（留侍写缝）；开夜为来源，经 `origin_chat_turn_id` 绑轮，与 `#506` undo 同构。
- 本回枚举后仍在；未触删。

### 复扫（施工后实测）

落盘：`/tmp/1897-j1-summon/enum-post.txt`

```
# TOTAL_HITS=0
declaration_dispatch.py:1624: … summon_after_passed=False
```

`dismiss_from_audience` / `stay_attend_in_audience` 定义与 CLI/session 调用仍在。

---

## J2 / F3

本回用户明示：当前已经审核无新增，**勿再扩改**。未动 J2/F3 代码或授权测试清单。

---

## 测试（聚焦，非全量；七变量前缀）

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_audience_undo_506.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_audience_presence_500.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_secret_order_declaration_landing_1897.py \
  --basetemp=/tmp/1897-j1-summon/pytest-focus
```

**实测 stdout**（`/tmp/1897-j1-summon/pytest-focus.txt`）：

```
111 passed in 2.98s
real 3.43
user 2.63
sys 0.65
```

失败：无。未跑全量；未调真实模型。合法负向闸（presence 空名拒收、`pytest.raises(match=…)` 注入哨兵、#670 applier 失败可重试等）仍在触及面内。

### 测试最小必要成本（一行）

聚焦 5 文件 111 例 / ~3.4s real；契约=任命后传召旧路及附属清退，现役传召／告退留侍／声明任命入口不回归。

---

## 自查二连

1. **同类型**：全仓按类枚举后再删，不只点删 `_persist`；FieldSpec／颁布枝／discard／延期批／死夹具／说明一并清；#670 独立价值留在 `record_summon_fresh` 现役案。
2. **引入面**：未扩 J2/F3；未造平行传召体系；未 stash/amend/push/PR；未动 Soul/宪法/宿主；自建物仅本仓 `artifacts/` 与 `/tmp/1897-j1-summon/`。

## 账目

- 本轮相对 `cb2dec1cc`：8 files，`+11 / −385`（以 `git diff --stat` 为准）+ 本回执
- 未 push / 未 PR / 未 amend
- 代码提交 SHA：`dc0470e445366fd411e0627ce672ff15ece149e2`
