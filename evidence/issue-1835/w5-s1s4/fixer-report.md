# #1835-w5 S1–S4 修内司回执（全类复扫）

## 本局交付

分支：`ak-roles/issue-1835-w5-s1s4-fixer`  
票：#1835；末份判词未结类 S1–S4。  
基线：上轮 `825a372e5`（点名样本已修，但枚举收窄被复核驳回）→ 本局全类复扫 + 清扫遗漏 + 如实重做变异证据。  
**不宣称 merge／关票。**

## 复核结论（针对上轮收窄）

上轮 `enum-commands.sh` 确属禁止的收窄：S1 七键+变量名 hint；S2 只搜 preflight／capture 点名；S3／S4 近乎样本符号。本局改为 `full_enum.py`：

| 类 | 全类谓词 |
|---|---|
| S1 | 全部 typed 生产者 + 数据流消费者闭包（get/items/下标）+ 旧响应字段全列 |
| S2 | 全仓数量／钳制／封顶／准入 + stages 解析校验行／函数；同体平行组 |
| S3 | 停止条件触点（含 docs）+ 弱／失效测 + 零引用夹具；不限点名 |
| S4 | 政治度量默认／floor／兜底语言；不限民心字面 |

## 逐类根因与本局增量

见 `disposition-table.md`。

本局相对 `825a372e5` 的代码／说明增量：

1. **S3**：删除 `db._is_commitment_stop_condition` 及 `advance_issue` 中 `resolve_condition` 冒充 stop 的分支；仅保留 `commitment_kind`／typed `stop_condition`。
2. **S3 说明**：`docs/DELTA_SCHEMA.md`、`docs/test-cleanup-audit-1185.md` 对齐已删兼容／floor／失效测。
3. **证据**：重写枚举谓词；撤回过强变异主张；真实 `settle_delta`／`advance_issue`／`dispatch_month_segment` 装回旧逻辑。

上轮已落且本局复扫确认仍成立：S1 `.rejected.append`；S2 预检影子／capture 删除；S3 legacy stop gate／失效测／死夹具删除；S4 民心 floor 删除。

## 复扫

`enum-post.txt` COUNTS：`S1_producers=67`，数据流 dict 消费者仅 `extras.items()`（保留）+ 财政 tick 测试 dict 字段；S2 `identical_body_groups=0` 且 preflight 无 `max(0,min(`；S3 无 `_is_commitment_stop_condition`；S4 无生产 floor。

## 聚焦测试

```
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=<tmp>/user PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=<tmp>/pytest \
  tests/test_declaration_dispatch_1835.py tests/test_person_delta_adapter.py \
  tests/test_issue_entities.py tests/test_new_issues_section_rejections.py \
  tests/test_decree_commitment_settlement_229.py tests/test_decree_commitment_creation_136.py \
  tests/test_commitment_display_348.py tests/test_event_trigger_gate.py \
  tests/test_qa_e1_numeric_presentation.py tests/test_rejection_wiring.py \
  tests/test_mutiny_noop_whitelist_319.py
```

结果：`449 passed, 1 skipped in 8.91s`（见 `focused-tests.txt`）。未跑全量。

## 变异证据（真实入口；已撤回过强主张）

命令：

```
env MING_SIM_*_BIN=/usr/bin/false \
  .venv/bin/python -B evidence/issue-1835/w5-s1s4/run_mutation_probes.py
```

| 探针 | 旧（装回） | 当前 |
|---|---|---|
| S1 `settle_delta` 缺事件结局 → `_resolve_strategic_events` | `TypeError: IssueSectionResult not subscriptable` | `rejected_len=1` `missing_event_outcome` |
| S2 `settle_delta` 散文 stages | `new=1 rejected=[]`（旧 capture 静默） | `rejected=[invalid_enum stages_json…]` |
| S2 事件整封 `dispatch_month_segment` 哗变 cap 信封 | — | loyalty/pressure 不变，`triggered=False` |
| S3 `advance_issue` resolve 散文 | `status=active`（冒充 stop） | `status=resolved`；typed stop 仍 `active` |
| S4 `settle_delta` 空 enrich | `effect={"metrics":{"民心":1}}` | `effect={}` |

**撤回**：上轮 S1 直接构造结果下标、S2 helper／符号探针及日志中两次 `ImportError`——不得再作入口证据。

## 剩余范围

- 本局仅 S1–S4；不扩 #1572 D5；不恢复已声明缺口功能。
- 功能缺口／红灯登记 #1873 仍由调用方补记。
- 未 push、未开 PR、未 stash、未 amend。
