# #1843 F2-R10 补充腿施工回执（纠正收窄；禁止 amend）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r6-f2`
底座（本补充提交前）：`40df97af987d5f07d12df25e064c167b54355420`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-e49f-7a41-a7de-d543dc256654@fixer/fix-packet.md`
判词末 payload：同目录 `attachments/02-1843-judge-4d25772ae.json` → `payloads[-1]`（status=continue；F2-R10-1 / F2-R10-2 送修；G1 已结）

## 纠正上一腿不实交卷

上一腿 `evidence/1843-f2-r10-fixer-receipt.md` / `1843-f2-r10-enum-commands.txt`：

1. 宣称「谓词未收窄」——**不实**。
2. F2-R10-1 死夹具扫描实际仅限 `tests/test_rescript_draft_656.py`。
3. F2-R10-2 helper/internal/identity/mock/重复扫描实际仅限 `fiscal_substrate_bridge` + 判词点名符号。
4. 「枚举命令」写成抽象描述，不可复制执行。

本腿以全仓可复制 shell/python 重做机械枚举，并补删收窄遗漏成员。上一腿已删样本（rescript_draft_prompt / getsource / 措辞锁等）**保留不动**。

## 两类完整定义

### F2-R10-1
沿历史已退役旧结算／simulator 消费者向下核独占支持树：资产、加载绑定、夹具、互引死树、保护失效行为的测试。保留现役 normalize／revise／prewrite／共用存储。不以零引用或样本当边界。

### F2-R10-2
全仓（含 web）删除非契约源码／措辞锁、helper／内部结构案及重复案；复用真实入口→外部结构化；保留必要结构化负向与确定性 HUD。不得另造扫描机制／证明测。

## 枚举

见 `evidence/1843-f2-r10b-enum-commands.txt`（临时脚本在 `/tmp/1843-f2-r10b/`，未入库）。

关键实测：
- F2-R10-1：`hist_hits=61`；HEAD 种子 `still_defined_seeds=0`；`unloaded_prompts=0`；全仓死夹具初筛 88 → 精炼无引用 39 → 本类 DELETE 11
- F2-R10-2：`total_candidates=2101`（py 230 + web 25）；高信号强 DELETE 在底座已为 0

## 本补充腿 DELETE（11）

| 成员 | 理由 |
|---|---|
| `test_relation_capture_633::_CANNED` | 旧五模块 extractor canned；零引用 |
| `test_relation_capture_633::_module_of` | 仅服务上一符号 |
| `test_pre_settle_transaction::_drive_resolve_directives` | 旧 simulator stub；零挂接 |
| `test_opening_gazette_delete_1356::_canned_settle` | 死结算包装；现役 seam 保留 |
| `test_opening_gazette_delete_1356::_session` | 同文件互引死树壳 |
| `test_secret_order_monthly_progress_566::_canned_monthly_settlement` | extractor_calls 死包装 |
| `legacy_staging_helpers` 五个零引用 `_` 别名 | 改名残留死树；保留公开名与 `_active_minister_name` |

逐名全表：`evidence/1843-f2-r10b-member-table.tsv`。

## 保留（摘要）

- 现役：`scene_agent_prompt`、`normalize_*`／revise／prewrite、票拟存储、`canned_full_settlement`、`_active_minister_name` 调用方
- 类外：`faction_metrics`（无 hist 旧结算承接链）；18 个无 hist 链的一般零引用 helper（不借本类清扫）
- F2-R10-2：HUD 键集+工程词；fiscal 外部两测；全仓公共 I/O／UI mock／非 original_* identity —— 高信号表见 `evidence/1843-f2-r10b-f2-highsignal.tsv`

## 未做

- 未新增测试；未修活旧行为；未新增仓内扫描机制
- 未 stash／amend／push／PR／改配置
- 非全量 suite

## 聚焦测试（触及面；非全量；无 --deselect）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --durations=10 \
  tests/test_relation_capture_633.py \
  tests/test_pre_settle_transaction.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_state_reload.py \
  tests/test_rescript_draft_656.py \
  tests/test_advance_paths_atomic.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_pay_order_override_653.py \
  tests/test_qa_e1_numeric_presentation.py
```

结果：**350 passed, 1 skipped in 20.73s**；EXIT 0。日志：`evidence/1843-f2-r10b-pytest.log`。

完整聚焦文件列表（10）：
1. `tests/test_relation_capture_633.py`
2. `tests/test_pre_settle_transaction.py`
3. `tests/test_opening_gazette_delete_1356.py`
4. `tests/test_secret_order_monthly_progress_566.py`
5. `tests/test_state_reload.py`
6. `tests/test_rescript_draft_656.py`
7. `tests/test_advance_paths_atomic.py`
8. `tests/test_fiscal_substrate_bridge.py`
9. `tests/test_pay_order_override_653.py`
10. `tests/test_qa_e1_numeric_presentation.py`

## 自查二连

- 同类型：全仓枚举后按类定义逐名处置；纠正上一腿「未收窄」夸称与抽象命令。
- 引入 bug：聚焦 350 绿；未删现役 `canned_full_settlement`／`_active_minister_name` 调用方／HUD／fiscal 外部契约；未 stash／amend／push／开 PR。
