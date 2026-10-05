# #1835-w5 S1–S4 修内司回执

## 本局交付

分支：`ak-roles/issue-1835-w5-s1s4-fixer`（自 `ak-roles/issue-1835-w5@e1ffba6ef` 新建）  
票：#1835；末份判词现役未结类 S1–S4。  
**不宣称 merge／关票。**

## 逐类根因

见 `disposition-table.md`。

## 改动要点

1. S1：`issue_summary.rejected` 属性写入。
2. S2：删预检影子数量公式；地区／军队 noop／拒收复用写核结果；删 `capture_commitment_stages`，统一 `stages_to_json`。
3. S3：删 legacy stop gate 与写侧 fallback；删失效测／死夹具；保留 typed stop 与负向契约。
4. S4：删民心 +1 floor 及保活测；enrich 空即空。

## 复扫

`enum-post.txt`：S1 仅剩两处普通 dict（保留）；S2 影子公式／capture 消失；S3 legacy helper／专属旧测／死夹具消失；S4 floor 消失。

## 聚焦测试

命令（七变量前缀）：

```
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=<tmp>/user PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=<tmp>/pytest \
  tests/test_declaration_dispatch_1835.py tests/test_person_delta_adapter.py \
  tests/test_issue_entities.py tests/test_new_issues_section_rejections.py \
  tests/test_decree_commitment_settlement_229.py tests/test_decree_commitment_creation_136.py \
  tests/test_commitment_display_348.py tests/test_event_trigger_gate.py \
  tests/test_qa_e1_numeric_presentation.py tests/test_rejection_wiring.py
```

结果：`424 passed, 1 skipped in 6.91s`（约 8s 墙钟；见 `focused-tests.txt`）。未跑全量。

## 变异证据（真实入口／进程内；未新增证明测试）

见 `mutation-probes.txt`：

- S1：旧 `IssueSectionResult["rejected"]` → TypeError；属性写入绿。
- S2：散文 stages 经严格面拒收；结构化 stages 绿；影子符号消失；tracker 真实入口拒收散文 stages。
- S3：仅 `resolve_condition` 不再成 gate；typed stop 仍成 gate。
- S4：空 enrich 后 `effect_on_resolve={}`，无民心 floor；`settle_delta` 同。

## 剩余范围

- 本局仅交 S1–S4；不扩 #1572 D5、不恢复已声明缺口功能。
- 功能缺口／红灯登记 #1873 仍由调用方补记（本局未改该票）。
- 未 push、未开 PR。
