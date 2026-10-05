# #1902 修内司 T1/T5 续修回执 r2（pexpect close 默认强杀 + T5 993 假清）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`2f6ebc4f4`（T1/T5 回执戳）/ 代码 `4ba1218ce`
- 本轮 FIX SHA：`b3087ac1a6c45727c66c22a3ba0d4940cbf52f21`
- 判词真源：PI session 用户消息（T5 993 全同 reason 假清；T1 close 默认 force=True；T2/T3/T4/T6 不重开）
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
| T1 谓词漏 **pexpect/ptyprocess `close()` 默认 `force=True`**（官方已装源；`__exit__`→`close()`） | `play_as_emperor.py` 注明禁 `child.close()` / 禁 `with pexpect.spawn`；执行路径仅 `terminate(force=False)`；谓词改为 `(child\|spawn\|ptyproc).close(` / `with pexpect.spawn` / `close(force=True)`，**不含** `session.close`/`math.isclose` |
| T5 原 UNKNOWN 桶 993 条共用一句「信号之一」+ `KEEP_external_or_public_on_reread` 假清 | **逐条**读源码/调用链，填 `entry` / `external_contract` / `assert_field_or_source` / `necessity` / `dup_group`；**3288** 条 KEEP **3288** 个互异 reason；再删纯 helper/常量形状 **9** 案（不回滚先前 63） |

成员表：`evidence/issue-1902/t1t5-member-tables.json`  
逐条全表：`evidence/issue-1902/t5-t1t5-reclassified.json`（字段含 entry…）  
原 993 切片：`evidence/issue-1902/t5-former993-per-item.json`  
本轮删除：`evidence/issue-1902/t1t5-r2-deleted.json`  
枚举脚本：`evidence/issue-1902/t1t6-enum-script.py.txt`（T1_RE 已扩）  
变异：`evidence/issue-1902/t1t5-r2-mutations.out`

### 可核命令

```bash
# T1：执行路径无 force 强杀；注释记载 close 默认 force
rg -n 'terminate\(force=False\)|故意不调用 child.close|with pexpect.spawn' scripts/play_as_emperor.py
python3 - <<'PY'
import re
from pathlib import Path
code='\n'.join(l for l in Path('scripts/play_as_emperor.py').read_text().splitlines() if not l.lstrip().startswith('#'))
assert 'terminate(force=False)' in code
assert not re.search(r'child\.close\s*\(|with pexpect\.spawn|terminate\s*\(\s*force\s*=\s*True', code)
print('T1 code path OK')
PY

# T5：无通用假清句；reason 互异且含「入口」「断言」
python3 - <<'PY'
import json
d=json.load(open('evidence/issue-1902/t5-t1t5-reclassified.json'))
rs=[c['reason'] for c in d['cases']]
assert '逐条复读：具入口/闸/来源/公开结构化信号之一，非不明保留' not in rs
assert len(set(rs))==d['kept']==d['unique_reasons']
assert all('入口 ' in r and '断言 ' in r for r in rs)
print('kept', d['kept'], 'unique', d['unique_reasons'], 'del_this', d['deleted_this_round'])
PY
```

| 类 | 候选宇宙 | actionable / 本轮 |
|---|---|---|
| T1 | 收紧后生产树命中 15（注释/自 SIGTERM） | **0** 执行强杀 |
| T5 | KEEP 3288（含原 993）；本轮删 9；先验 63 保留 | 表可核实际入口；**禁止**「无 UNKNOWN 标签即结清」 |

---

## 逐类结果

### T1
已装源确认：

- `pexpect.spawn.close(self, force=True)` → `ptyproc.close(force=force)`；文档写明 force 时可 SIGKILL
- `spawn.__exit__` → `self.close()`（默认 force）
- `terminate(force=False)` 默认不发 SIGKILL

`scripts/play_as_emperor.py` finally：

- `child.terminate(force=False)`
- **不**调用 `child.close()`；**不**使用 `with pexpect.spawn`
- 未退 / 异常 → 日志「终止缺口，不 SIGKILL」

全仓复扫（收紧谓词）：执行强杀 **0**；`web_app.py` 本进程 `SIGTERM` KEEP。

### T5
禁止「不明即保留」与「信号之一」整桶改名。

对先验全宇宙（含原 `BEHAVIOR_OR_UNKNOWN` 993 与其它桶通用一句 KEEP）逐条 AST/窗口读：

**本轮删除 9（纯 helper/脚本内形状/常量集合；负向闸与来源/公开契约保留）**

| 删除 | 承接 |
|---|---|
| `test_normalize_legacy_person_changes_preserves_origin` | `test_apply_score_extraction_does_not_echo_normalized_person_changes` |
| `test_is_real_api_key_*`（整文件） | `api_set_llm_config` / `_llm_config_from_runtime` 入口案 |
| `test_office_rank_deputy/aux_*`（`_office_rank_multiplier`） | faction leverage / `set_character_office` 入口案 |
| 颁诏脚本内 `_appointment_rejection_*` / `_ordinary_class_*` / `APPOINTMENT_TEXT` 字面 | 同文件颁诏闸入口案 |
| `test_657_s1_rescript_emitted_set_subset_of_dossier` | `test_save_and_list_rescript_drafts_roundtrip` |

**保留并重填理由**：闸类负向（含 `gate_text_key_form_error` 公开校验）、来源/seed、DB/Web/CLI/render 真入口；每条 reason 形如  
`入口 <具体调用/fixture>；契约/…；断言 <字段>；必要性/重复组…`。

先前 63 删除**未回滚**。

### T2/T3/T4/T6
本轮用户指令不重开。

---

## 聚焦测试

```
650 passed, 1 skipped in 10.91s
```

命令见 `evidence/issue-1902/t1t5-r2-focus-pytest.txt`。

**未**新增红→绿证明测。

---

## 变异真跑

`evidence/issue-1902/t1t5-r2-mutations.out`

| 变异 | 结果 |
|---|---|
| M4b/c/d pexpect terminate(force=False) + 禁 close/with | PASS |
| T5 helper 已删 + 承接仍在 | PASS |
| T5 unique reasons == kept | PASS |
| focus pytest | PASS |
| **SUMMARY** | **6 / 6** |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、证明测；枚举脚本仅 evidence 临时复现。
- 自查二连 done：同类型（close 默认 force≠显式 force=True；通用「信号之一」≠逐条入口）+ 引入（删 helper 后入口/闸承接；谓词收紧避免 math.isclose/session.close 误伤）。

## 剩余 / 阻断

- T1 执行强杀：**0**。
- T5：假清句已消灭；KEEP 表可核实际入口；**不**以「无 UNKNOWN 标签」宣称结清。
- T2/T3/T4/T6 本轮不重开。
- 家族收尾/合并/关票不在授权内。
