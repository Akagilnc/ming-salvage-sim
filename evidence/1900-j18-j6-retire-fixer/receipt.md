# #1900 修内司施工回执（J6 源头语义审阅 + 七条质量 migrate 落地）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
分支：`ak-roles/1900-j18-retire-revoked-mechanisms`
既存 `?? .baseline/` 未动；无 stash / amend / rewrite / push / PR。

未结类别以末份判词 continue payload 为准：J18（P1）、J6（P2）。本轮主攻：先前误 pen 为「功能接续缺口」的 7 条 J6 测试质量 migrate。

---

## 1. 两类区分（HARD）

| 类 | 本轮处置 | 归宿 |
|---|---|---|
| **J6 测试质量**（helper/mock/文字 oracle / 确认类调用形） | 7 条 migrate 全部落地 → `action=retain`（有具体必要契约理由）或离场宽旗 | **本轮 completed**；不得再 pen #1873 |
| **功能接续真实缺口** | 未宣称补齐；不借测试质量残留冒充 | 仍归 #1873 / 家族收尾 |

先前 `continuity_gap_migrate_names` 列 7 条同时写 `migrate_outstanding_in_tree=0` —— 已纠正：该 7 条是未结 J6 质量债，不是家族功能缺口。

---

## 2. 七条落地

| 成员 | 代码处置 | 权威表 |
|---|---|---|
| `test_settling_context_retry_does_not_recompute_substrate_hub_pre_settle` | hub-identity oracle 已不在树；保留公开 snapshot 相等 | migrate→retain（必要 DB 快照读） |
| `test_apply_fixed_period_flows_malformed_fiscal_*` ×3 | 删 assert 文案与 tlog spy；保留 isolation + 税收出列 | migrate→retain（必要 non-cutover 路径 setup） |
| `test_all_ming_settle_substrates_advance_into_ledger` | 私有 container_basis oracle 已不在树；删措辞锁 | migrate→retain（公开 settle/起运/江南硬锚） |
| `test_verify_llm_available_smokes_legacy_env_only_backend` | 删 prompt 措辞锁；保留「进入 smoke」 | migrate→retain（CLI IO 边界 mock） |
| `test_resolve_turn_write_gate_held_by_caller_no_reenter` | 删 auto_close spy/stub；真 `resolve_turn` + 公开 `ValueError` | migrate→retain；复扫后离场宽旗（flags=[]） |

不新增平行夹具钩子。写闸负向未盲删。

---

## 3. 复扫摘要（`j6-wide-disposition-summary.json`）

- 结构候选：**2535**；权威表：**2617**；按 `(file,name)` 全覆盖。
- `needs_manual`：**0**；`wide_flag_left`：**0**。
- `migrate_outstanding_in_tree`：**0**（`OUTSTANDING_MIGRATE.jsonl` 空）。
- `j6_quality_seven_landed`：**7**。
- `continuity_gap_migrate_still_structural`：**0**；`continuity_gap_migrate_names`：**[]**。
- `migrate_still_structural`：**122**——先前轮次权威表仍标 migrate 的宽旗成员账，**不**再 pen 为本轮/#1873 功能接续缺口。

---

## 4. 聚焦测试（七 BIN=/usr/bin/false）

本轮触及：

```
tests/test_fiscal_substrate_bridge.py
tests/test_llm_channel_config.py
tests/test_qa_t1_extraction_dual_source_1353.py
```

```
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_llm_channel_config.py \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  -q --tb=line -p no:cacheprovider
```

- `focused-j6-seven-migrate.log`：七成员（含 parametrize）**13 passed**。
- `focused-j6-seven-files.log`：三文件 **197 passed**，`real ~14s`。
- 不再跑上一最终 95 文件集；不全量。

---

## 5. 合法阻断 / 交卷边界

无合法阻断。施工 **completed**（本轮 J6 质量七条）。**不**关票 / merge / converged；**不**自行宣布 J6 类净。J18 与真实功能接续仍归 #1873。
