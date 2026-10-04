# #1835 w5 修内司回执（fixer · advisor 复审补扫）

本轮只交修理提交，未 merge、未 push、未开 PR；不宣告关票。不提交终局回执（由驱动 session 汇验）。

## 授权与法源

- 任务包：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108ff-575c-70a9-a4e6-3f226f700bcf@fixer/fix-packet.md`
- 冻结判词末份：`attachments/02-1835-judge-e22cba1e3.json` → `outcome.payloads[-1]` 七类未结
- 票面：#1835 / #1812 / #1901；ADR 0150、0008、0015、0142、0154、0047、0158
- 本轮动因：advisor 复审——上轮枚举谓词主要锁定点名符号，未证明覆盖七类定义全文

## 先前失误 / 红灯（禁止洗白）

1. **上轮枚举收窄**：谓词点名 `_apply_metric_dict` / `STAY_ATTEND_COMMANDS` 等样本符号，未按类定义做形状+AST 消费者全表；把「无命中点名」当成「类已清」。
2. **`declare_closed` 伪保留**：上轮回执写「供夹具/将来自然归档」——违反 C3/C5「仅测试消费者不是自然归档未来借口」；AST 仅 `tests/test_month_translate_1840.py` 三处夹具。
3. **NL 软收夜「今日且到此」**：留在 `COURT_BREAK_COMMANDS`，自称「明确退朝」却无 ADR 0047/0158 依据（ADR 只认「退朝」加速器）；与 #1812 第5项样本「今日就到这里吧」同族。
4. **`TAG_STAY_ATTEND`**：声称「只读投影旧账」但 AST 零引用（定义即死）。
5. **本会话误触 `git stash`**：诊断时误执行 `stash push`；立即 `stash pop` 恢复，工作树改动完好。 stash 栈上另有历史条目未动。
6. **聚焦扩面撞预存红灯**：为覆盖 `declare_closed` 夹具迁约把 `test_month_translate_1840` 纳入聚焦；暴露 `audience_translate._loads_lenient(..., accepted_types=)` 与签名不符（W4 合并缝，HEAD 已有）。已删非法 kwargs，与全仓其它调用对齐；**不是**新造证明测试。

## 枚举命令（类定义全文，未收窄为点名）

全表处置：`evidence/issue-1835/advisor-rescan/disposition-full-table.md`  
宽扫原始：`evidence/issue-1835/advisor-rescan/enumeration-broad.txt`

```sh
# C1 平行核 / re-export / 月链接线
rg -n '^def (apply_|_apply_).*(metric|economy|levy|recovery|inertia|drift|class)' ming_sim
rg -n 'apply_levy|apply_situation|apply_recovery|situation_drift|displaced_population|apply_issue_inertia' ming_sim/month_chain.py
# AST 同名 def 跨模块 + from issues/flows re-export

# C2 成功载荷拒收嵌套 / 特殊搬运
rg -n 'backlash_results|backlash_rejections|\.pop\([\'"]backlash|rejections\.extend\(backlash' ming_sim tests

# C3 无消费者接口（AST Attribute/Name 引用计数）
# ordinal / ordered_sections / section_for_delta_key / declare_closed / TAG_STAY_ATTEND / caller_transaction

# C4 平行证明 / 仅测试摘要
rg -n 'fixed_point|def describe|views\.describe' tests ming_sim
ls tests/test_settlement_fixed_point_1835.py

# C5 事务 close 动作 / 守门 / 词表
rg -n 'declare_closed|close_from_declaration|ATTACH_RESULT_CLOSE|事务尚有未了|_ATTACH_CLOSE' ming_sim tests

# C6 退役 NL 口令 / 固定 cue / 词集 / session 分派
rg -n 'STAY_ATTEND|AMBIGUOUS_CLOSE|陛下是要退朝么|stay_attend|recognize_audience_command|CMD_CLOSE_NIGHT|COURT_BREAK|今日且到此|今日就到这里|留下听着' ming_sim tests web_app.py

# C7 供料原文裁剪传递链（不止 resolve_condition）
rg -n 'resolve_condition|fail_condition|stage_text|precondition|\.strip\(' ming_sim/materials.py ming_sim/knowledge.py
rg -n '(resolve_condition|fail_condition).{0,40}\.strip\(|\.strip\(\).{0,40}(resolve_condition|fail_condition)' ming_sim
```

## 逐类全表处置摘要

### 1. 完整性C1 — 旧核/兼容桥/平行路径

| 成员 | 分类 | 处置 |
|---|---|---|
| `entities.{metric,economy,social_class}.*` | #1901 实体单一真源 | **保留** |
| `situation_drift` / `displaced_population` / `population.recovery` | #1901 接缝；month_chain 唯一接线 | **保留** |
| `issues` inertia/levy 旧核与 re-export；`flows` 重复 metric/economy | 平行旧核 | **已删（上轮）**；本轮 AST 无 def/reexport |
| `issues._apply_fiscal_levy_targets` | 三饷终态钱面，非月漂移双持 | **保留**（类外） |

### 2. 完整性C2 — 拒收藏成功载荷

| 成员 | 处置 |
|---|---|
| `character/apply` → `rejections.extend(backlash_rejections)` | **保留**（既有返回通道） |
| `applied.backlash_results` / `.pop("backlash*")` / preflight 嵌套扫 | **已删**；本轮 rg 无命中 |
| `credit_events._collect_reject_issue_ids` | **保留**（读 cancels 显式信号，非成功载荷嵌套） |

外部结构化：既有 `test_rejection_wiring` 聚焦绿；独立进程探针 C2 extend GREEN / nest RED 可观测。

### 3. 完整性C3 — 无消费者接口

| 成员 | 处置 |
|---|---|
| `ordinal` / `ordered_sections` / `section_for_delta_key` / `SettlementRun.caller_transaction` 字段 | **已删（上轮）** |
| `run.py` 局部 `caller_transaction` | **保留**（判词明示除外） |
| `AffairStore.declare_closed` | **本轮删除**（仅测试消费者） |
| `TAG_STAY_ATTEND` | **本轮删除**（零引用） |

### 4. 完整性C4 — 平行证明 / 测试专用摘要

| 成员 | 处置 |
|---|---|
| `test_settlement_fixed_point_1835.py` / `views.describe` | **已删** |
| 既有玩家契约与直接 `settle_delta` 行为案 | **保留** |

### 5. 正确性C1（C5）— 事务 close

| 成员 | 处置 |
|---|---|
| delta_section close+未了守门 / `close_from_declaration` / `ATTACH_RESULT_CLOSE` | **已删** |
| `declare_closed` 生产方法 | **本轮删除**；夹具改 SQL `UPDATE … status='closed'` |
| `status` 列可读态 | **保留**（往事查询需要；无宣布了结写口） |
| `test_affairs_1831` close 拒收 | **保留**（声明拒收契约，非守门专测） |

法源：ADR 0154「不设宣布了结动作及拒绝该动作的守门」。

### 6. 正确性C2（C6）— 退役 NL 口令

| 成员 | 处置 | 确切依据 |
|---|---|---|
| 留侍/含糊退朝词集、固定 cue、`stay_attend_in_audience`、专属旧测 | **已删** | #1812 待拍事项第5项；P7；ADR 0142 |
| 「今日且到此」 | **本轮移出** `COURT_BREAK_COMMANDS` | 同族 NL 软收夜；无 ADR 明确口令授权 |
| `recognize_audience_command` / `CMD_CLOSE_NIGHT` / session `court_break` / CLI 同集 | **保留** | **ADR 0047**：退朝钮=「退朝」口令；**ADR 0158**：散夜钮=「退朝」；边界「不扩张删除无关命令」 |
| `COURT_BREAK_COMMANDS`={q,quit,退朝,下朝} | **保留** | 同上；`下朝`=明确封闭同义词；q/quit=CLI 同管线 |
| `MINISTER_DISMISS_COMMANDS` | **保留** | 大臣告退，非收夜类 |

**不许自称无关**：保留项均挂 ADR 0047/0158；裁撤项挂 #1812§5。

### 7. 正确性C3（C7）— 供料原文传递链

链（全表，不止 resolve_condition）：

1. knowledge/DB → `_visible_affair_lines`：`resolve`/`fail`/`situation(stage_text)` 原值入库字典  
2. 写 `当前情况.txt`：`.strip()` 仅判空副本；写出用原值  
3. `_candidate_event_fact` → 候选事件文件：`resolve`/`fail`/`precondition`/`summary` 原值  
4. `knowledge._prose`：`str(text or "")` 不 strip  

| 成员 | 处置 |
|---|---|
| materials 条件 strip-then-store | **已改为保留原值** |
| issues/db 匹配用 strip 副本 | **保留**（非供料写出） |
| content seed `clear_narrative` strip | **保留**（装载，非模型声明供料） |

## 变异证据（真实行为红/绿，非 AST 缺席冒充）

独立进程 `/tmp/1835-w5-mut-advisor/mutate_probes.py`（不改工作树持久态）：  
`evidence/issue-1835/advisor-rescan/mutation-probes.txt` — **21/21 PASS**

含：C6 今日且到此→none / 退朝→close_night / 再插入软词 RED→恢复 GREEN；C5 declare_closed 缺席 + SQL 夹具可关 + 注入方法可见/删除恢复；C7 空白保留 / strip 变异 RED / 当前路径 GREEN；C2 extend GREEN vs nest RED 可观测；C4 SettlementOutcome 赋属性 FrozenInstanceError。

## 聚焦测试

强制前缀七 BIN=/usr/bin/false。解释器：工作树无 `.venv`，用 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`（cwd=本树，`ming_sim` 解析到本树）。

```sh
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q --tb=line \
  tests/test_declaration_dispatch_1835.py tests/test_affairs_1831.py \
  tests/test_person_delta_adapter.py tests/test_rejection_wiring.py \
  tests/test_month_chain_1847.py tests/test_issue_entities.py \
  tests/test_audience_translate_1837.py tests/test_material_directory_1830.py \
  tests/test_population_transfers_649.py tests/test_commitment_backlash_626.py \
  tests/test_section4_rejections.py tests/test_decree_commitment_settlement_229.py \
  tests/test_style_temperament_641.py tests/test_effect_origin_558.py \
  tests/test_deformation_dual_rail_622.py tests/test_fiscal_beyond_intent_1260.py \
  tests/test_month_translate_1840.py
```

结果（实查）：`421 passed, 1 skipped in 9.67s`（wall `real 10.10`）。日志：`evidence/issue-1835/advisor-rescan/focused.txt`。未跑全量。

首次聚焦曾 `1 failed`（`_loads_lenient` kwargs）；修齐后全绿。如实记，不抹。

## 剩余范围 / 缺口

- 家族复杂度对比、全量 CI、真宿主验收留家族收尾。
- 自然归档机制未建（授权不要求；且已删除伪归档借口方法）。
- `_apply_fiscal_levy_targets` 等财政终态通道不在本七类施工面。
- 未向 #1873 代登功能缺口（判词：调用方补交）。

## 约束遵守

未 amend / rewrite / push / PR；误 stash 已立即 pop。未改宪法/Soul/宿主配置；未新造兼容桥/递归拒收收集器/护栏/识别层/证明性测试。
