# #1902 修内司 T1–T6 回执（T4 响亮收口 · T5 语义合并 · 清误称 BLOCK）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`b2c2c54ef`（stamp）／功能基线 `7eca74e0e`
- 本轮 HEAD：`652d2dfbb`（独立新 commit，禁止 amend）
- 判词真源：`06-1902-judge-092109acf.json` → `outcome.payloads[-1]`（T1–T6）
- fix-packet：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10a10-a917-76cc-966b-7ef94176ba78@fixer/fix-packet.md`
- **不宣称已合并 / 总票完成**；未 stash/push/PR；未改治理文件与宿主席位

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

## 本轮硬纠偏（相对 7eca74e0e 误称 BLOCK）

| 问题 | 处置 |
|---|---|
| T4 新增 after-snapshot `try/except` + 跳过 diff + 谎称需第二套回滚 → **误称 BLOCK** | **删除** snapshot catch，恢复原响亮 `capture → record diffs`；快照故障原错上抛；回执如实记「宿主/存储故障无法记 diff／可能残留副作用」，**不**另造机制、**不** BLOCK |
| T5 以「未授权按行数盲删」阻断整仓重复契约合并 | 授权已明：语义契约分类合并。全仓 **3360**（3364−本轮删 4）逐案归类+重复分组；删内部/重复（既有测承接）+死夹具；保留拒收/来源 |
| T6 例外依据不清 | 全文授权谓词枚举；`generate_rescript_draft` KEEP（现役共享）；`_require_active_minister` 已清；无授权内未清残根 |

成员表：`evidence/issue-1902/t1t6-member-tables.json`  
全量 T5 分类：`evidence/issue-1902/t5-full-classified.json`  
复扫：`evidence/issue-1902/t1t6-rescan.json`  
变异脚本：`evidence/issue-1902/t1t6-mutations-script.py.txt`

### 可核命令

```bash
rg -n 'after-snapshot failed|after_snapshot = None|skip rollback diffs' ming_sim/session.py
# 预期：无命中（catch 已删）
rg -n 'capture_chat_rollback_snapshot\(\)' ming_sim/session.py
python3 evidence/issue-1902/t1t6-mutations-script.py.txt   # 或 /tmp 副本；七 BIN 前缀
```

| 类 | 候选宇宙 | actionable |
|---|---|---|
| T1–T3 | （上轮已结；本轮未重开） | 0 |
| T4 | 恢复共核 + snapshot 路径 | **0 BLOCK**（响亮失败+诚实回执） |
| T5 | 3360 全分类；dup 同入口组 70（均 KEEP 异场景） | 删 4 测 + 4 死夹具符号 |
| T6 | auth 命名定义 1（`generate_rescript_draft` KEEP） | 0 授权内残根 |

---

## 逐类结果

### T4
删除 `fail_audience_chat_turn` 内 after-snapshot catch。恢复：

```python
self.db.record_chat_turn_rollback_diffs(
    turn.chat_turn_id, turn.before_snapshot,
    self.db.capture_chat_rollback_snapshot(),
)
```

- 快照失败 → **原错上抛**（M3a：`RuntimeError: snap boom`），不伪造 diffs。
- 重试路径：fail 收口二次失败只 `logger.exception`，**外层仍抛原始 LLM 失败**（M3b：`raised=重试 LLM 失败`）；`rollback_items=0`；loyalty 可残留 → 回执写「宿主快照故障导致无法诚实记 diff／未安全回滚」，**不是**缺第二套回滚机制的 BLOCK。
- 对照 M3c：快照正常时既有回滚真源仍还原副作用。

### T5
全仓语义分类（`REJECT_GATE` / `SOURCE_CONTRACT` / `EXTERNAL_BEHAVIOR` / `EXTERNAL_ENTRY` / `BEHAVIOR_OR_UNKNOWN`）。同入口重复组 70 个均为**异场景** KEEP（不按行数盲删）。

本轮删除（既有测承接）：

| 删除 | 承接 |
|---|---|
| `test_origin_turn_unset_falls_back_to_state_turn` | 同文件 wall-clock 集成 + `insert_issue` 真 origin_turn |
| `test_657_s1_derive_draft_capability_stable_and_sensitive` | layer_a roundtrip + choices_563 stamp + pihong capability 不等式 |
| `test_run_agent_text_prior_messages_sent_as_message_list` | 1746 heal 经 `_prior_roles/_prior_contents` |
| `test_run_agent_text_without_prior_passes_plain_prompt` | 同上入口无 prior 路径；solo adapter 属内部 |

死夹具清退：`tests/conftest.py` 的 `InlineExecutor` / `DeferredExecutor` / `run_deferred` / `deferred_background_jobs`（零引用）。

拒收闸与 ADR 0008 来源/Provenance/RejectionCollector 落库契约 **保留**。

### T6
授权谓词全文枚举生产命名定义：仅 `generate_rescript_draft` 命中 → **KEEP_live_shared_capability**（批红/急务/CLI 现役共享；非退役入口）。`_require_active_minister` 定义已不在；测试仅历史注释。无「底座时点豁免」KEEP。授权外零引用整仓盲删不在本票——本轮无此类可执行残根冒称已清。

---

## 聚焦测试

```
411 passed in 8.29s
```

命令与文件集见 `evidence/issue-1902/t1t6-focus-pytest.txt`（含七 BIN + 本轮触及的 commitment/rescript 文件）。

**未**新增红→绿证明测。

---

## 变异真跑

`evidence/issue-1902/t1t6-mutations.out` + `t1t6-mutations.collected.txt`

| 变异 | 结果 |
|---|---|
| M1 CAS 未赢 → None | PASS |
| M2 CAS 后 KeyError → interrupted | PASS |
| M3a after-snapshot 响亮原错 | PASS（`snap boom`；recorded=0） |
| M3b 快照故障+副作用 | PASS（原错保留；items=0；**诚实无法恢复**，非 BLOCK） |
| M3c 快照正常回滚 | PASS |
| M4 terminate 无 kill | PASS |
| M5 canonicalize 响亮 | PASS |
| **SUMMARY** | **7 / 7** |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、第二套回滚/编排、证明测。
- 自查二连 done：同类型（catch 洗白≠诚实失败；未授权≠已授权的语义合并）+ 引入（删测后契约由既有 roundtrip/heal/wall-clock 承接；响亮上抛不伪造 interrupted）。

## 剩余 / 阻断

- **无 BLOCK。** 上轮 T4「需第二套回滚」为误称——已用删 catch + 响亮失败 + 诚实回执收口。
- 家族收尾/合并/关票不在授权内。
- T5 同入口 70 组保持异场景 KEEP；若后续要再压场景密度，须按契约 ID 点名，不按行数。
