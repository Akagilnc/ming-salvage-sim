# #1902 修内司 T1–T6 回执（w5 · 01a107df 判词）

- 工作树：`Ming_LLM-1902-w5`
- 判词：`01a107df-d9e2-73fc-ad6d-32b8504c7aad@judge` submission.latest.accepted
- 基线 HEAD：`62059d00b`（上轮 stamp）
- **不宣称合并/关票**；未 stash/push/PR/amend；未改治理文件与宿主席位

七 BIN 前缀全程显式展开（见 focus 日志）。

## 枚举

谓词与成员表：`evidence/issue-1902/t1t6-w5-member-tables.json`  
全仓 AST/词面枚举命令见该 JSON 各 class.enum_command。

## 逐类

### T1
- **根因**：测试子进程 `subprocess.run(timeout=)` 隐式 SIGKILL 路径遗漏。
- **扫描**：生产+测试 AST `subprocess.*(timeout=)`；kill/SIGKILL/force terminate。
- **修复**：`tests/test_pihong_dossier_1490.py` 去掉 timeout 参数与形参。
- **复扫**：actionable 0。保留：SIGTERM 自终、terminate 缺口 wait 报告、替身 kill 接口定义。

### T2
- **根因**：名册恢复用异常词面正则；CLI 交付 `strip` 改写正文。
- **修复**：
  - `UnknownParticipantRefError`（`participant_roster`）由 DB 校验抛出；
  - `is_unknown_participant_ref_error` / 取名只认类型与 `.names`；
  - 交付路径保留 `primary`/`final_text` 原文，strip 仅作空判定。
- **复扫**：无 PARTICIPANT_REF 正则；无交付 strip 改写。

### T3
- 上轮已结；本轮复扫无新增 actionable（auto_save/trace 有 logger；canonicalize 响亮）。

### T4
- **根因**：启动对账两端各抄；领域编排仍挂传输层 `cli_backend`。
- **修复**：
  - `GameSession.reconcile_crashed_audience_turns`；Web 建局/rebuild、CLI 起手/读档转调；
  - 现役领域（extract/heal/resubmit/enrich/roster/secret_order_land…）迁 `ming_sim/draft_intent.py`；
  - `cli_backend` 不保留领域 def、无兼容转发；消费者改 import；测试改补丁目标。
- **复扫**：cli_backend 无上述 def；draft_intent 为唯一产者。

### T5
- 上轮已结；`test_applier_contract` 仅公开结构化拒收落库契约。

### T6
- **根因**：场景入口不产旧 ChatTurnResult 字段，入口仍投影/打印。
- **修复**：`ChatTurnResult` 只留 `answer/court_action/pending_audience_translation`；清 Web `_chat_payload` 与 CLI 死消费者。
- **复扫**：dataclass 三字段；无 appointed/proposed/landing 等。

## 聚焦测试

```
253 passed in 10.49s
```
（`evidence/issue-1902/t1t6-w5-focus-pytest.txt`；另补 chat_stream/highlight/manual 等 117 passed）

## 探针

```
T2 prose ValueError → not heal; UnknownParticipantRefError → heal names
T1 _terminate no proc.kill
T4 draft_intent owns extract; session has reconcile core
T6 ChatTurnResult fields == {answer, court_action, pending_audience_translation}
ALL PROBES PASS
```

## 质量 / 合法性

- 未改 CLAUDE.md / AGENTS.md / CONTEXT.md / ADR / 席位。
- 未新增监督层、兼容转发、证明测试。
- 新模块 `draft_intent` 为既有领域迁出归位（非新编排机制）；传输工具仍在 cli_backend。
- 禁止 amend/stash/push。

## 剩余

- 家族收尾/合并/关票不在授权。
- Web 流式召对宿主票据/SSE 适配仍在入口（判词允许宿主资源适配）。
