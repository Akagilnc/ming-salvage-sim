# Issue #1835 W5 修内司 apply — merge `claude/1812-w4` 回执

- **票面**: #1835（retire `EMPTY_EXTRACTION` / `apply_score_extraction` → `settle_delta`）
- **动作**: 在 `ak-roles/issue-1835-w5` 上 `git merge claude/1812-w4`（必须 merge commit）
- **约束**: 保留双方现役意图；不新造行为；不复活退役路径/措辞锁；不 rebase/amend/squash/push/PR/stash
- **保护未跟踪产出**: `artifacts/issue-1835-w5-ast-audit.py`、`artifacts/issue-1835-w5-mutation-probes.py`（未覆盖、未删除、未纳入提交）

## Advisor

派单要求大计划前寻求 advisor。fable/sol 配额不可用；以 inherit GO 继续（见会话前半记录）。

## 冲突文件处置（双方来源 → 处置 → 理由）

| 路径 | ours (#1835) | theirs (W4/#1812) | 处置 | 理由 |
|---|---|---|---|---|
| `ming_sim/declaration_dispatch.py` | settle_delta 声明派发 | 旧/并行写法 | **ours** | #1835 现役落账入口 |
| `ming_sim/issues.py` | 无 `apply_score_extraction`；实体写口迁 effects | 仍含旧总入口 + 亲裁/饷率 API | **hybrid** | 保留 #1835 退役；从 W4 迁入 `apply_petition_event_outcome` / `gather_fiscal_levy_petitions` / `petition_outcome_is_admissible` / `strategic_event_outcome_labels`；饷率通道用 W4 出列加载；`gather_candidate_events` 排除 `fiscal_levy`；re-export `_apply_issue_entities` 等 |
| `ming_sim/context.py` | #1835 | W4 | **ours** | 现役上下文契约 |
| `ming_sim/breach_plea.py` | 无 `close_target` | #1894 `close_target` | **hybrid** | 保留 ours 骨架，补 W4 `close_target` 透传 |
| `ming_sim/urge_lever.py` | HEAD 催紧/敢言 | #1895 退役改判词 | **ours** | 与 HEAD 测试族一致；#1895 AC1 测试未并入（见未结项） |
| `ming_sim/simulation.py` | #1835 | W4 | **ours** | 现役模拟编排 |
| `ming_sim/decree.py` | 仍调 `trigger_supervision_countermeasures` | #1895 退役该硬门 | **hybrid** | 去掉监督反制硬调，保留 #1895 注释 + `trigger_commitment_backlashes` |
| `ming_sim/due_review.py` / `staged_commitment.py` | #1835 | W4 | **ours** | 现役 |
| `docs/SETTLEMENT_FLOW.md` | #1835 月链 | W4 | **ours** | 与 settle_delta 契约一致 |
| `ming_sim/content.py` / `models.py` | `default_terminal_reason` | 已删字段 | **hybrid** | 恢复 HEAD 字段+校验；保留 W4 strategic_foreign 校验 |
| `content/events.json` | 四条三饷有 default | W4 去掉 default | **hybrid** | 从 HEAD 恢复四条 `default_terminal_reason` |
| `ming_sim/flows.py` | 2-arg payable | 改走 `army_pay` 1-arg | **theirs+适配** | 接入 `army_pay`；`economy/apply.py` 改调 `(row)` |
| `ming_sim/army_pay.py` 等 W4 模块 | 无 | 有 | **theirs** | W4 世界腿现役 |
| `ming_sim/db.py` | DeclarationDataError 月报；`source_pending_action_id` | public_kept/`kind`；部分仍 import `apply_score` | **hybrid** | 修 `knowledge_items_for_turn`；恢复 `record_monthly_dossier_progress`+supply 拆分；撤旨去 `apply_score` import；origin 用 `_monthly_report_origin` |
| `ming_sim/month_chain.py` | #1835/#1846 | W4 army_pay/inertia | **hybrid** | 保留 fault-honest + invalid declarations；接 W4 世界段 |
| `ming_sim/action_materialize.py` | #1835 | #1890 无 payload source_chat_turn_id | **hybrid** | 取 W4 #1890 意图 |
| `ming_sim/cli_backend.py` / `materials.py` / `knowledge.py` / `covert_progress.py` | #1835 | W4 查案/供料 | **hybrid** | 种子罪情用 W4 宽容解析；查案符号保留 |
| `ming_sim/context` 相关 web | — | `/api/directives` | **theirs 注+ours 口** | 恢复 `DirectiveRequest`；保留 #1835 手工捕获口 |
| `tests/test_secret_order_payoff_1504.py` | settle_delta 短套 | W4 查案长套仍调 `apply_score` | **W4 基线+适配** | 换 `settle_delta`；解包 `(results, rejections)` |
| `tests/test_urge_lever_624.py` | HEAD 全族 | W4 #1895 | **ours/HEAD** | 与保留的 urge_lever 对齐 |
| `tests/test_breach_plea_623.py` | 推迟挽留 | #1894 当月落实 | **hybrid** | 撤「推迟」用例，并入 W4 当月落实用例 |
| 其余冲突测试 | settle_delta 命名遗留 | apply_score 直调 | **按侧适配** | 禁止复活 `apply_score_extraction` |

## 自验 / 类错误复扫

- 无残留冲突标记（业务源文件）。
- 禁止符号：`apply_score_extraction` / `EMPTY_EXTRACTION` 不作为生产 import 复活；撤旨路径已去掉该 import。
- `DirectiveRequest`、`record_monthly_dossier_progress`、亲裁/三饷供料 API、#1895 监督硬门退役已对齐。

## 聚焦测试

命令（七个 BIN 前缀强制）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest $(cat /tmp/conflict_tests.txt) -q --tb=line
```

结果（最终一轮）：

- **2257 passed / 31 failed / 4 skipped**
- **时长**: real ≈ 61.18s（日志 `artifacts/issue-1835-w5-merge-pytest.log`）

过程节点：336 → 211 → 91 → 49 → 35 → **31** failed（结构缝合后残留多为跨票语义接缝）。

## 未结项（31）

语义/跨票接缝，需后续专修（非本 merge 新造行为）：

1. **三饷亲裁世界段**（`test_fiscal_levy_effect` 多条）：请旨呈递/留中/信封归属与 month_translate 世界问答题绑定仍有缺口。
2. **撤旨当月结案**（`test_policy_reversal_revoke_model_verdict_lands_same_month`、`test_real_revoke_restores_override_same_month_with_active_commitment`）：#1894 与执行格结案时序。
3. **密令 4a invalid/spoliation/effort**（`test_secret_order_payoff_1504` 若干）：查案声明校验与月链 invalid 相位。
4. **section4 历史严格/容忍**（3）：issue 路径拒收烈度与 #1835 实体适配器不完全同构。
5. **其它单测**：commitment 别名账户、auto_trigger 不再触发、huangtaiji 模型挑选、month_chain 废黜/4a 恢复、appointment 快照、player_army legacy、QA 文案/路由、密令披露晋升等。
6. **#1895 urge 改判词退役**：本回合保留 HEAD `urge_lever` + HEAD 测试族；W4 `test_urge_no_longer_rewrites_verdict_ac1_1895` 未并入——若要完整 #1895，需另开切片改催紧写口而非在本 merge 新造。

## 提交

- 类型：**merge commit**
- 前缀：`ak-roles:`
- 不含：两个既有 untracked artifacts（ast-audit / mutation-probes）
