# #1853 修内司交卷（J2–J5）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-j2-j5-unify`（自 `ak-roles/issue-1853-retired-residue` / `acc7a7c6d` 新开）
- 授权：本局「apply #1853」施工劳务指令
- 票面：`gh issue view 1853` / `1812`（`--repo Akagilnc/ming-salvage-sim`）
- 判词：末份 payloads（`05-1853-judge-acc7a7c6d.json`）未结类别 **J2–J5**；前份仅参考
- 官方方向：React「Avoid duplication in state / single source of truth」→ https://react.dev/learn/choosing-the-state-structure （旁证；裁决依据仍为仓库法源）
- **未合入目标分支；不声称关票或家族完成**

## 自审（合法性 / 复杂度）

- 未新增同步、轮询、恢复或分类账本；J3 只删无消费者观察链，转译轮询保留。
- J2 归一夜卷投影，删前端平行数组与缺字段回退。
- J4 共同异常分流归一，保留拟旨路径的事务包装与内存恢复差异。
- J5 终态业务拒收不再进系统失败传输／计数；真实未成落库路径与拒收审计保留。
- 净复杂度下降：删并行权威与死观察链；未造第三层框架。

---

## J2「回话重试存在两份前端权威」

### 根因
夜卷 `/api/audience/scroll` 已提供 `reply_retries`，但 `useChatActions` 另维一份数组，`chatModal` 又对缺字段兼容并回退到 props——双权威。

### 全仓枚举命令
```bash
rg -n --hidden -g '!node_modules' -g '!.git' \
  'reply_retries|replyRetries|setReplyRetries|ReplyRetry' \
  web/ ming_sim/ web_app.py tests/
```

### 成员表（施工前）
| 成员 | 处置 |
|---|---|
| `web/src/useChatActions.ts` 状态 `replyRetries` / set 于 history·undo·retry | **删**平行状态 |
| `web/src/components/chatModal.tsx` `hasOwnProperty` 缺字段兼容 + props 回退 | **删**；只读夜卷 |
| `web/src/main.tsx` 传 `replyRetries` | **删**传参 |
| `web_app.py` 夜卷 `reply_retries` | **保留**（唯一投影） |
| `/api/audience/chat` 仍可返回 `reply_retries` | **保留后端字段**；前端不再消费为平行权威 |
| 测试夹具把 retries 放在 history | **改**到 scroll mock |

### 修复
- 夜卷始终写入 `replyRetries`；`liveReplyRetries` 只读夜卷。
- 恢复轮询成功读 history 后 `invalidateAudienceScroll()`，刷新夜卷权威。
- 重试钮的 `recovery_phase` 由夜卷传入，不再查本地数组。

### 复扫
```bash
rg -n 'setReplyRetries|hasOwnProperty\.call\(data, "reply_retries"\)' web/src
# 无匹配；仅剩 night 态 liveReplyRetries 消费
```

### 保留理由
后端夜卷与 DB 重试投影是失败呈现真源；history API 字段不构成第二前端权威。

---

## J3「退役预推恢复链遗留无消费者的轮询支线」

### 根因
`forecast_inflight` → 夜卷传输 → `chatModal` 并入 `keepPolling`，但无呈现读者；预推只写暂存声明。

### 全仓枚举命令
```bash
rg -n --hidden -g '!node_modules' -g '!.git' \
  'forecast_inflight|forecastInflight|has_open_key_prefix|_forecast_work_inflight' \
  web/ ming_sim/ web_app.py tests/
```

### 成员表
| 成员 | 处置 |
|---|---|
| `web_app.py` `_forecast_work_inflight` + 夜卷字段 | **删** |
| `ming_sim/session_write_queue.py` `has_open_key_prefix` | **删**（仅此消费者） |
| `chatModal` `forecastInflight` / 轮询或条件 | **删**；保留 `translation_pending` 轮询 |
| `tests/test_audience_scroll_539.py` 契约键 | **改**去掉 `forecast_inflight` |

### 复扫
```bash
rg -n 'forecast_inflight|forecastInflight|has_open_key_prefix' web/ ming_sim/ web_app.py tests/
# 无匹配
```

### 保留理由
转译在飞轮询仍有呈现与整理重试消费者。

---

## J4「暂存提交异常分流政策双实现」

### 根因
`commit_pending_actions` 与 `_commit_conversational_draft` 各抄一份：归属缺口上抛、案卷拒收审计、typed 拒收、failed 落账、真异常上抛。

### 全仓枚举命令
```bash
rg -n 'dossier_link_rejection|_is_typed_business_refusal|业务拒收 id=' ming_sim/db.py
rg -n 'def commit_pending_actions|def _commit_conversational_draft' ming_sim/db.py
```

### 成员表
| 成员 | 处置 |
|---|---|
| 两段重复 `except` 政策 | **归一**为 `_dispose_pending_action_apply_exception` |
| 拟旨路径 `atomic` / savepoint / 外层日志 | **保留**必要事务差异 |
| 普通路径 `restore_office_memory` | **保留**必要内存恢复差异 |

### 复扫
`业务拒收 id=` 仅出现在共享方法内两处分支（案卷 / typed）；两调用点只调 dispose。

### 保留理由
输入准备、事务边界、office 内存恢复仍属必要差异，未造第三层框架。

---

## J5「业务拒收仍被旧支线呈为未处理系统故障」

### 根因
终态业务拒收（如 `ineligible_power`）把 `pending_actions` 标 `failed` 后，仍被 `_new_secret_order_failure_payloads*` 与 `failed_secret_order_count` 当成系统待办；edict `failedOnly`、settlement/decision 失败列表、CLI 打印同吃该传输。且 typed 审计 `item_json` 曾缺 `pending_action_id`，无法按审计排除。

### 全仓枚举命令
```bash
rg -n --hidden -g '!node_modules' -g '!.git' \
  'pending_action_failures|failed_secret_order_count|failedOnly|_new_secret_order_failure_payloads|list_failed_secret_order_actions' \
  web/ ming_sim/ web_app.py tests/
```

### 成员表
| 成员 | 处置 |
|---|---|
| `_record_typed_business_refusal` 不保证 `pending_action_id` | **修**审计戳记 |
| `_is_terminal_business_refusal_action` + `_system_secret_order_failure_payloads` | **新增共享过滤**（非新账本，读既有审计） |
| `web_app` / CLI 载荷建造 | **改**走共享过滤 |
| `failed_secret_order_count` | **改**排除终态拒收 |
| `edictModal` `failedOnly` / `decisionModal` / `useSettlementFlow` | **保留**；数据源已干净后不再误呈拒收 |
| 真实未成落库（非拒收的 `failed`）传输 | **保留** |

### 复扫
业务拒收案：`_system_secret_order_failure_payloads` 不含该 id；`_is_terminal_business_refusal_action` 为真。无业务拒收的 failed 仍可出载荷。

### 保留理由
拒收审计、原动作行、真异常上抛路径不动；不删仍承担真实未成故障唯一传输的路径。

---

## 测试与变异证据

环境前缀（全部本机测试）：
```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### 聚焦
```text
python3 -m pytest tests/test_audience_commit_failure_1853.py \
  tests/test_audience_scroll_539.py tests/test_decree_forecast_1861.py \
  tests/test_cli_play_turn.py -q
→ 56 passed in ~4.0s

cd web && npx vitest run src/components/modals.test.tsx src/appDurableWiring.test.tsx \
  --environment jsdom --no-cache
→ 120 passed in ~4.3s

npx tsc --noEmit -p tsconfig.json → exit 0
```

### 测试改动说明（复用既有行为案，非新增证明夹具）
| 改动 | 契约 | 成本 |
|---|---|---|
| scroll 契约去掉 `forecast_inflight` | 夜卷字段集 | 1 行 |
| modals / durableWiring：retries 改由 scroll mock 供给 | 夜卷唯一权威 | 夹具对齐 |
| durableWiring 成功回复后 scroll 失败条件避开 `replied` | 成功后应以夜卷空列表清钮 | 1 条件 |

### 变异红 → 恢复绿
1. **J5**：临时 monkeypatch 去掉业务拒收过滤 → 真实应允入口后载荷含拒收 id（红断言成立）；恢复后过滤生效、既有 `test_ineligible_*` / `test_dossier_link_*` 绿。
2. **J4**：临时把 `_dispose_pending_action_apply_exception` 改为直接 `raise` → 同入口业务拒收变系统抛错；恢复后既有分流案绿。
3. **J3**：临时把 scroll 契约加回 `forecast_inflight` → `test_live_and_closed_night_share_the_real_http_contract` 红；恢复绿。

临时 mutation 文件仅用系统/工作树临时路径，跑完已删。

---

## Commit

见本分支最新 `ak-roles:` 提交（交卷时 `git rev-parse HEAD`）。
