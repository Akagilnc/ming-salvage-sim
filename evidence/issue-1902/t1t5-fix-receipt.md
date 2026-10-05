# #1902 修内司 T1/T5 续修回执（pexpect 强杀漏项 + BEHAVIOR_OR_UNKNOWN 假清）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`6ff0dc6f5`
- 本轮 HEAD：（见 stamp commit）
- 判词真源：PI session `01a10a10-a917-76cc-966b-7ef94176ba78@fixer` 用户消息（T2/T3/T4/T6 本轮认可不重做；只续修 T1/T5）
- **不宣称已合并 / 总票完成**；未 stash/push/PR；未改治理文件

七 BIN 前缀（本轮全部测试显式展开）：

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

## 本轮硬纠偏

| 问题 | 处置 |
|---|---|
| T1 谓词漏 `pexpect.terminate(force=True)`（官方文档：force 时发 SIGKILL） | `scripts/play_as_emperor.py` 改为 `terminate(force=False)`；未退如实记终止缺口；谓词扩至 killpg/psutil/send_signal/close(force=True)/subprocess timeout 等变体 |
| T5 `BEHAVIOR_OR_UNKNOWN`≈1050 全部 `KEEP_behavior_or_unknown` 假清 | 逐条独立外部契约判定；删纯内部/helper/重复证明 63 案（其中原 UNKNOWN 桶 57）；保留闸类负向、来源、公开结构化、真入口；**不再存在** `KEEP_behavior_or_unknown` |

成员表：`evidence/issue-1902/t1t5-member-tables.json`  
T5 重裁：`evidence/issue-1902/t5-t1t5-reclassified.json`  
枚举脚本：`evidence/issue-1902/t1t6-enum-script.py.txt`（T1_RE 已扩）  
变异：`evidence/issue-1902/t1t5-mutations.out`

### 可核命令

```bash
# T1：执行路径无 force=True；仅注释提及禁 SIGKILL
rg -n 'terminate\s*\(\s*force\s*=\s*True' scripts/play_as_emperor.py ming_sim web_app.py
rg -n 'terminate\(force=False\)|终止缺口，不 SIGKILL' scripts/play_as_emperor.py

# T1 全谓词复扫（生产树）
python3 - <<'PY'
import re
from pathlib import Path
ROOT=Path('.')
T1_RE=re.compile(r"\.kill\s*\(|\.send_signal\s*\(|\bSIGKILL\b|signal\.SIGKILL|\bkillpg\b|os\.kill(?:pg)?\s*\(|\bpsutil\b|terminate\s*\(\s*force\s*=\s*True|\.close\s*\(\s*force\s*=\s*True|subprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^;]*timeout\s*=|Popen\.[A-Za-z_]*kill|\.communicate\s*\([^)]*timeout\s*=")
for base in ['ming_sim','scripts','web_app.py']:
    p=Path(base)
    for f in ([p] if p.is_file() else p.rglob('*.py')):
        for i,l in enumerate(f.read_text(errors='ignore').splitlines(),1):
            if T1_RE.search(l): print(f'{f}:{i}:{l.strip()[:120]}')
PY

# T5 判词样本已删
rg -n 'def test_issues_schema_has_commitment_deadline_columns|def test_effect_dict_has_work_|def test_override_key_legal_shapes' tests/
# 预期：无 def 命中（已删）；非法形闸类仍在：
rg -n 'def test_override_key_illegal_shapes_fail_loud' tests/test_pay_order_override_653.py
```

| 类 | 候选宇宙 | actionable / 本轮 |
|---|---|---|
| T1 | 全仓强杀 API 变体（见谓词） | **0** 执行强杀；11 命中均为注释/自 SIGTERM/缺口日志 |
| T5 | 先验 3360；UNKNOWN 1050 | 删 63（UNKNOWN 57）；KEEP 均带显式 disposition，无 UNKNOWN 整桶 |

---

## 逐类结果

### T1
官方文档确认：`pexpect.spawn.terminate(force=True)` 在 SIGHUP→SIGCONT→SIGINT 后仍存活则发 **SIGKILL**（[pexpect API](https://pexpect.readthedocs.io/en/stable/api/pexpect.html)）。

`scripts/play_as_emperor.py` finally：

- `child.terminate(force=False)`
- 未退 / 异常 → 日志「终止缺口，不 SIGKILL」
- 不另造监督层

全仓复扫（扩谓词）：无 `terminate(force=True)` 执行路径；`web_app.py` `_os.kill(getpid(), SIGTERM)` 为本进程优雅退出 KEEP；`cli_backend` 仅文档/缺口日志。

### T5
禁止「不明即保留」。对先验 `BEHAVIOR_OR_UNKNOWN` 与同类 helper 桶逐条读源码/调用链：

**删除（样本+同类，既有真入口承接）** — 完整表见 `t1t5-member-tables.json` / `t5-deleted-applied`：

| 删除例 | 承接 |
|---|---|
| `test_issues_schema_has_commitment_deadline_columns` | `test_insert_issue_persists_commitment_deadline_columns` + 迁移幂等案 |
| `test_effect_dict_has_work_*` | `test_issue_resolution_removes_building_*` 等 issue resolve 入口 |
| `test_override_key_legal_shapes` | `test_override_key_illegal_shapes_fail_loud` 闸类 |
| pairing 纯 `_w` helper 案 | `test_resolve_surfaces_pairing_warning_in_result` 等 apply 入口 |
| 其它 coerce/infer/normalize/oracle helper | 同域入口/公开契约案 |

**保留**：闸类负向、来源/provenance、公开结构化契约、DB/Web/CLI 真入口与前端 render/fetch 行为。

夹具适配（非新增证明测）：`_FakeSession` 绑 `close_night_after_chat_if_needed` / `fail_audience_chat_turn` / `_record_persisted_audience_reply_failure`，以承接 T4 共核收口缝。

### T2/T3/T4/T6
本轮用户认可，不重做。

---

## 聚焦测试

```
782 passed, 2 skipped in 14.64s
```

命令见 `evidence/issue-1902/t1t5-focus-pytest.txt`。

**未**新增红→绿证明测。

---

## 变异真跑

`evidence/issue-1902/t1t5-mutations.out`（复用既有 Web/session 缝 + M4b pexpect）

| 变异 | 结果 |
|---|---|
| M1–M5（既有） | PASS |
| M4b pexpect terminate(force=False) 无 SIGKILL | PASS |
| **SUMMARY** | **8 / 8** |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、证明测；枚举脚本仅 evidence 临时复现。
- 自查二连 done：同类型（force 隐含 SIGKILL≠显式 .kill；不明 KEEP≠逐条契约）+ 引入（删 helper 后入口/闸类承接；FakeSession 绑共核防误 error）。

## 剩余 / 阻断

- T1 执行强杀：**0**。
- T5：`KEEP_behavior_or_unknown` **已消灭**；剩余 KEEP 均带显式 disposition。
- T2/T3/T4/T6 本轮不重开。
- 家族收尾/合并/关票不在授权内。
