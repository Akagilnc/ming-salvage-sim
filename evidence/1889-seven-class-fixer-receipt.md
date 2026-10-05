# #1889 七类修内司回执（末判 6b513b99f · 转发壳/枚举整改）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-seven-class-fixer`
- 判词真源：`…/attachments/05-1889-judge-6b513b99f.json` → `outcome.payloads` **末份**
- 本轮相对开工：`52bfa5d4b`（其上为 `1f53dd887` 七类初修）
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建证明测试/护栏/兼容/功能补齐；不改治理/Soul/宿主/SDK/席位；不碰既存存档

---

## 授权未结类（末判原文类名）

K4 / K1 / K5 / K8 / K9 / K3 / K7

---

## 可复跑枚举（工作树内完整谓词脚本，非 /tmp）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 evidence/1889-seven-class-enumerate.py
```

脚本覆盖票面类定义全文：
- **K3**：全仓测试 AST 非契约文案断言候选 + 诊断负断言宽扫
- **K5**：Store 近重复 SQL + 纯 `return self.OTHER(...)` 转发壳 + GameDB 复活壳
- **K1**：旧兼容/accept-both/Agno blob API + baseline 孤立机制
- 并含 K4/K8/K9/K7 谓词；宽扫候选一律写入 disposition，**NON_MEMBER 带依据**，不缩为样本符号

### 修后复扫摘要（`/tmp/1889-seven-enum-final.out`）

| 处置 | 条数 |
|---|---|
| NON_MEMBER（宽扫非成员+依据） | 3552 |
| KEEP | 160 |
| DELETE_DONE（修前成员已清） | 29 |
| DELETE_REVOKED_K3 | 208 |
| LIVE 生产 DELETE 残差 | **0** |

成员车道（DELETE*/KEEP）按类：K1=25、K3=261、K4=2、K5=27、K7=1、K8=59、K9=22。

生产残差谓词（`ming_sim/` + `web_app.py`）：

| 谓词 | 命中 |
|---|---|
| `scale_tian_fu\|read_scale_tian_fu` | 0 |
| `callable(_commit) and not callable(_conn)` | 0 |
| `default_terminal_reason` | 0 |
| `def append_chat_message\|def clear_month_open_snapshot` | 0 |
| `read_ack_due_commitment_issue\|read_get_secret_order` | 0 |
| `Close only by explicit declaration\|close_from_declaration` | 0 |
| `_decode_agno_runs\|merge_runs_table_with_legacy` | 0 |
| 事件循环 `excluded_names = []` 宽松洗白 | 0 |

---

## 逐类结果

### K4 — 退役财政标量路径

**处置**：维持初修 DELETE（`scale_tian_fu` / `read_scale_tian_fu` / 田赋残差链）。本轮 disposition 记 `DELETE_DONE`×2；KEEP 现役 dynamic 旁路。LIVE DELETE=0。

### K1 — 被取代来源 / 旧存储兼容

**处置**：维持 bare `secret_order:` accept-both 与 Agno2 blob 解码清退。disposition：`DELETE_DONE`（blob API / legacy 专测）+ KEEP（live brief / 保密负向 / origin_ref）。未缩为样本符号；宽扫命中标 NON_MEMBER 并写依据。

### K5 — 同一持久规则双份权威 / 转发壳

**类定义**：收拢重复规则；**删除被替代入口及转发壳**；不改事务边界、不把批量写退化成逐项提交。

**本轮关键整改**：
- 确认上一轮恢复的 `GameDB.append_chat_message` / `clear_month_open_snapshot` **直接违背 K5**（基线 `6b513b99f` 已无这两壳；`1f53dd887` 复活的是 Store+commit 转发壳）。
- **DELETE** 上述两壳；调用方直用 `db.chat_messages.insert` / `db.month_open_snapshots.delete` + **既有** `db.conn.commit()`（无 callable 判别、无新层）。
- **DELETE** `IssueStore.read_ack_due_commitment_issue` → 消费者直用 `.row(id)`。
- **DELETE** `CharacterKnowledgeStore.read_get_secret_order` → 消费者直用 `.secret_order_row(id)`。
- AST 全仓 Store 纯转发壳复扫：仅上述两壳（已删）；无新增。
- KEEP 不同生命周期/status/class 的同形 SQL（与末判驳回 C6 一致）；`save_pending_*` 批量/`executemany` 边界未改。

### K8 — 宽松排除解码

**处置**：维持严格 `_load_list` / `_load_targets`。

**既有入口变异**（装回旧逻辑，非整合法/非法入参当变异）：
```
STRICT_RESULT EXC ValueError: 角色见闻名单 损坏
LENIENT_RESULT OK count=6 probe_excluded=[[]]   # 旧 wash 吞错
RESTORED_RESULT EXC ValueError: 角色见闻名单 损坏
K8_PROOF red_then_green=True
```
完整输出：`/tmp/1889-k8-mutation.out`。生产文件已恢复严格真源。

### K9 — 未授权护栏 + 提交判别

**处置**：维持 `default_terminal_reason` 护栏与七处 callable 判别已删（`DELETE_DONE`）。
**不可用恢复壳绕过 K5**：本轮删除复活的 GameDB 提交壳，调用处直接 Store + `conn.commit`，遵循既有提交契约（atomic 内 commit 仍为既有连接语义）。

### K3 — 自由诊断措辞负断言

**处置**：维持删除 `Internal Server Error` 缺席断言；证据 `KEEP_P4_ABSENCE` → `DELETE_REVOKED_K3`。KEEP `_assert_structured_llm_http` 结构化契约。

**上游合法诊断变异既有测试**：
```
CURRENT_EXIT 0   # 无措辞锁 + provider 含 Internal Server Error → 仍绿
LOCKED_EXIT 1    # 临时装回两行缺席断言 → 假红
RESTORED_EXIT 0
K3_PROOF current_green_with_ISE_upstream=True lock_false_red=True restored_green=True
```
完整输出：`/tmp/1889-k3-mutation.out`。测试文件已恢复。

### K7 — 撤回机制过期说明

**处置**：维持 docstring 过期句已删（`DELETE_DONE`）；不恢复显式了结。

---

## 聚焦测试

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`。

```bash
../Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_section_fiscal_rejections.py \
  tests/test_audience_restore_505.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_event_trigger_gate.py::test_load_event_requires_latest_or_open_window \
  tests/test_event_trigger_gate.py::test_load_event_rejects_non_boolean_open_window \
  tests/test_character_knowledge_489.py \
  tests/test_affairs_1831.py \
  tests/test_rescript_draft_656.py::test_clear_pending_decisions_keeps_rescript_drafts \
  tests/test_promulgation_seam_560.py \
  tests/test_new_game_smoke.py
```

**实测**：`148 passed in 4.32s`。完整输出：`/tmp/1889-seven-focused.out`。

测试改动（最小必要，非新造证明测）：
- `_WorkerPathDB` 补真实 `conn.commit` no-op，避免 `__getattr__` 把 `conn` 影成函数（配合生产直调 Store+commit）
- 未新增证明性用例

---

## Advisor 自查（修改前 + 最终）

**修改前**：
- 回执可复跑仅引 `/tmp/1889-seven-enum/enumerate.py` → **边界收窄/不可审计**；须入仓完整谓词脚本。
- disposition 仅 67 KEEP → **修前 DELETE 成员未入表**。
- K9 复活 GameDB 壳 **绕过 K5**；`read_ack_due_commitment_issue` / `read_get_secret_order` 仍为被替代转发入口。

**最终**：
- 枚举脚本在 `evidence/1889-seven-class-enumerate.py`；宽扫+AST+baseline/prior 全员 disposition；NON_MEMBER 均有依据；LIVE DELETE=0。
- 无新增护栏/兼容层/平行恢复/自动了结/功能补齐/callable 判别。
- K5 批量 `executemany` 与 clear 的 commit 边界未改。
- 未改治理宪法 / Soul / 宿主 / SDK / 席位 / 既存存档。
- 未 amend / stash / push / 开 PR。

---

## 证据路径

| 文件 | 用途 |
|---|---|
| `evidence/1889-seven-class-enumerate.py` | 完整可复跑枚举+处置谓词脚本 |
| `evidence/1889-seven-class-member-disposition.tsv` | 修前/修后全员处置（含 NON_MEMBER 依据） |
| `evidence/1889-seven-class-enum.tsv` | 成员车道（DELETE*/KEEP） |
| `evidence/1889-seven-class-enum-raw.tsv` | 宽谓词原始扫 |
| `evidence/1889-c6-member-disposition.tsv` | K3 错误 KEEP 撤销（沿用） |
| `evidence/1889-seven-class-fixer-receipt.md` | 本回执 |
| `/tmp/1889-seven-focused.out` | 聚焦测完整输出 |
| `/tmp/1889-k8-mutation.out` | K8 装回旧逻辑红→恢复绿 |
| `/tmp/1889-k3-mutation.out` | K3 上游诊断变异假红证明 |
| `/tmp/1889-seven-enum-final.out` | 最终枚举复跑输出 |
