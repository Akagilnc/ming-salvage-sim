# #1835 w5 处置表（人工读卷·非 classify 默认豁免机）

HEAD 施工基线：`4b74f00cc`；本表随新提交落账，未 amend、未 push。  
**stash 违规**：第一劳动调用自报 `stash push`/`apply`/`drop`，违反用户禁令；后续不再操作。依据及经过见 `issue-1835-w5-repair.md`，不以恢复为无违规。  
已删除：`artifacts/issue-1835-w5-classify.py` 及由其生成的全例外假表。  
机械枚举仍可用：`artifacts/issue-1835-w5-ast-audit.py`（只枚举、不归类；生成的大 JSON 为审计中间物，不进 commit）。取证脚本不需 commit。

类定义（末份全文，施工未收窄）：

| 类 | 全义 |
|---|---|
| F1 | 重复机制须删简（不只 identity map；结果视图平行名录等） |
| F5 | 自由散文传递链删改（不限事务 name/origin） |
| F6 | 在场坏字段/异常被洗成缺席正常结果（不限 months_elapsed） |
| F10 | 盯自由文本 / 内部结构 / 重复检查（不限「已断言结构后再锁」） |
| F12 | 自由散文裁断胜负/拒收/状态/权限/身份（不限 reason/财政） |

---

## 审计覆盖（如实）

| 范围 | 状态 |
|---|---|
| AST 机械候选（全仓 `*.py`，跳过 venv/artifacts） | 可复跑；语义归类以本表为准 |
| 全仓含 web JS/TS/Vue 五类 `rg` 机械扫 | **已跑**（见下「可执行枚举命令」） |
| 人工缩至文件/函数后通读 | 见下「已读成员/例外」；未读区域已清零 |
| `ming_sim/db.py` F5/F6/F12 | **已读** |
| `web_app.py` / `cli_backend` / `action_materialize` / `rescript_*` / `materials` | **已读** |
| `web/src/**` TS/TSX | **已读**（机械命中后人工归例外/非成员） |
| F10 测试（py + web） | **已读归类** |

不得冒称「机械计数=语义完整」；下表成员/例外均可对照源码核验。

---

## 可执行枚举命令（全仓·含前端·按类）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5

# --- 共用：Python AST 机械枚举（大 JSON 中间物不提交）---
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  artifacts/issue-1835-w5-ast-audit.py
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -c \
  "import json;d=json.load(open('artifacts/issue-1835-w5-ast-audit.json'));print({k:len(v) for k,v in d.items()})"

# --- F1：平行名录 / 双投影 ---
rg -n --glob '!**/artifacts/**' --glob '!**/node_modules/**' \
  '_VIEW_TO_SECTION|view_keys|ITEM_FIELD_ALIASES|MODULE_FIELDS|pairing_warnings|_initiative_resolve_pairing' \
  ming_sim/ web/ web_app.py

# --- F5：散文传递链删改（Py + 前端 trim/replace/slice）---
rg -n -g '*.py' --glob '!**/artifacts/**' --glob '!**/.venv/**' \
  '\.strip\(\)|\.replace\(|\.replaceAll\(' ming_sim/entities/affair ming_sim/entities/population web_app.py
rg -n --glob '!**/node_modules/**' --glob '!**/dist/**' \
  -g '*.{ts,tsx,js,jsx,vue}' \
  '\.replace\(|\.replaceAll\(|\.substring\(|\.slice\(|\.trim\(|new RegExp\(|\.match\(|\.matchAll\(' \
  web/

# --- F6：坏字段洗白 / catch 默认回落 ---
rg -n -g '*.py' --glob '!**/artifacts/**' --glob '!**/.venv/**' \
  'except \(TypeError, ValueError\)|except ValueError|int\([^\n]*or 0\)' \
  ming_sim/entities/issue/commitment_display.py ming_sim/action_materialize.py \
  ming_sim/db.py ming_sim/rescript_actions.py ming_sim/cli_backend.py web_app.py
rg -n --glob '!**/node_modules/**' -g '*.{ts,tsx,js,jsx,vue}' \
  'catch\s*\(' web/

# --- F10：盯自由文本 / 内部结构 ---
rg -n -g 'test_*.py' --glob '!**/artifacts/**' \
  'toContain|toMatch|assert.*in |assertIn\(|pairing' tests/
rg -n --glob '!**/node_modules/**' -g '*.{ts,tsx,js,jsx,vue}' \
  'toContain\(|toMatch\(|\.includes\(|indexOf\(|startsWith\(|endsWith\(' \
  web/

# --- F12：散文裁断胜负/拒收/身份 ---
rg -n -g '*.py' --glob '!**/artifacts/**' \
  '_recurring_funding_label_tokens|_commitment_fiscal_create_duplicate_reason|parse_staged_year_promise|_secret_metadata_from_command' \
  ming_sim/
rg -n -g '*.py' --glob '!**/artifacts/**' \
  're\.(search|match|findall|sub)' \
  ming_sim/entities ming_sim/staged_commitment.py ming_sim/cli_backend.py 2>/dev/null | head -80
```

---

## 实际成员（已修）

### F1
| 成员 | 处置 | 依据 |
|---|---|---|
| `settlement/views.py` `_VIEW_TO_SECTION` / `view_keys` | 已删 | 24×key==value 平行投影；权威 `SettlementOutcome.sections()` |
| `effects._initiative_resolve_pairing_warnings` + `_emit_pairing_warnings` + tracker/issues 调用 + `IssueSectionResult.pairing_warnings` | **本复检删整链** | 恒空 stub/调用形=兼容壳反例；缺口仍归 #1873，不装回散文配对 |

### F5
| 成员 | 处置 | 依据 |
|---|---|---|
| `entities/affair/store.py` name·origin | 已修 | strip 仅判空；INSERT/出参原文 |
| `entities/population/apply.py` reason | 已修 | 查键 strip 副本；ledger 写 `raw_reason` |

### F6
| 成员 | 处置 | 依据 |
|---|---|---|
| `commitment_display` origin_turn / bar | 已修 | 缺席回落；在场坏 `int()` 上抛 |
| `action_materialize` 罚俸/协饷/end_turn/months/aid/expires/origin_cid | 已修；本复检将合法缺席缩回 `int(x or 0)`（无 try/except 洗白） | 不造 helper；0/false 原语义不当坏则保留 |
| `require_explicit_xiexang_fields` amount | 本复检 | except→`n=None` 后单一 `_note`，去重复判断 |
| `breach_plea` / `covert_progress` | 已修 | 在场坏上抛 |
| `rescript_actions` due/months/amount；`rescript_draft` forbid amount | 已修；缺席支缩 `int(x or 0)` | 同上 |
| `db` normalize 收权/撤回/罚俸/军令/下议；revoke；dossier links；urge；faction；origin_cid；cannon/arrears | 已修；cannon/arrears/suffix 缩 `int(x or 0)` | 缺席拒或 0；在场坏上抛 |
| `cli_backend` 期限月数 / affair_declaration | 已修；期限缩 `int(x or 0)` | 坏声明上抛 |
| `web_app._runtime_float` | 已修 | 缺席 default；在场坏上抛（default≠0 契约，保留显式分支） |
| `materials.dossier_paid_amount` | 已修；缩 `int(dossier_id or 0)` | 缺席 0；在场坏上抛 |

### F10
| 成员 | 处置 | 依据 |
|---|---|---|
| 多测盯 note/context/stage/sim_note；`test_initiative_resolve_pairing.py` 整删 | 已删 | 盯文 / 散文配对证明面 |
| `test_faction_leverage_9` 内部结构 flag | 已删 | 私有结构绿卡 |

### F12
| 成员 | 处置 | 依据 |
|---|---|---|
| `fiscal/delta_section` reason token 词表 | 已删 | 散文代判科目 |
| `effects` pairing 词表 | 已拆；**本复检连恒空壳一并删** | 缺口 #1873 |
| `staged_commitment.parse_staged_year_promise` + `capture` 叙事回落形参 | 已删；**本复检删 `narrative_text`/`origin_turn` 废参并迁调用方** | 散文不得代判 due |
| `cli_backend._secret_metadata_from_command` | 已删 | 从命令散文抽标签/期限 |

---

## 已读例外（文件/函数级；可核）

| 类 | 成员 | 为何不是该类 |
|---|---|---|
| F1 | `cli_backend._PI_THINKING_BY_STRENGTH` / `llm_model._OPENAI_REASONING_BY_STRENGTH` | 受控 thinking/reasoning 枚举，非结算段平行投影 |
| F1 | `preflight._ORDERED_DELTA_FIELDS` | extracted 字段处理序 |
| F5 | `credit_events` / `declaration_dispatch` / `dossier` note / `textual_fact` / `fiscal.display` / action body·title·note | strip 判空，落库原文 |
| F5 | `web_app._humanize_condition` replace | 仅展示层技术 key→中文 |
| F5 | `db` seed office replace / SQL quote / path `\`→`/` | 非 LLM 自由散文传递链 |
| F5 | `web/src/format.ts` `splitReportItems` | 展示层拆报告前缀/合计尾；不落库、不裁断结算 |
| F5 | `web` 多处 `.trim()` 判空发信/配置 | 空则禁用；非空用原文 |
| F5 | `web` SSE `slice`/`startsWith("event: ")` | 传输协议帧 |
| F6 | `fiscal._norm_int_leaf` except→原值 | 损坏原样返回 |
| F6 | 多项 `except → RejectedItem` / `_fail` / `_note` | 异常转拒收，非缺席成功 |
| F6 | `_coerce_new_salary_rate` | #44 已结清设计，不重开 |
| F6 | `web` `response.json().catch(() => ({detail}))` | HTTP 错误展示回落，非账本字段洗白 |
| F6 | `web` UI `.catch(setError)` | 失败呈现，非伪造成功账 |
| F10 | fixture `memorial_text`/`body`/`title` == 输入 | 字段保真 |
| F10 | `web/src/components/situation.test.tsx` `toContain(commitmentText)` | fixture 结构化进度字段往返展示 |
| F10 | `web/src/settlementPresentation.test.ts` 固定 UI 口令 | P7 界面固定话语，非自由散文盯文 |
| F10 | `web/src/ministerScrollLens.test.ts` not.toContain 他臣卷 | 隔离透镜契约（空透镜/不泄漏），非呈现措辞锁 |
| F10 | SSE `'event: done' in r.text` / CSS/协议 match | 传输/样式契约 |
| F12 | `matching.compact_name` / office concurrent / pay_order override | 受控查键归一 |
| F12 | `web_app._humanize_condition` / CLI 传召 regex | 展示或短令路由 |
| F12 | `effects._LEGACY_DURATION_MONTHS` | legacy 受控枚举 |
| F12 | `scripts/*` / `docs/raw/06_harness_scripts/*` | 非生产结算 |

---

## 未读区域

**无。**

---

## 本复检相对上轮增量

1. 删除 pairing 恒空整链（effects 两函数 + tracker/issues 调用 + `IssueSectionResult.pairing_warnings`）。
2. `capture_commitment_stages` 去掉仅 `_=` 的 `narrative_text`/`origin_turn`，迁 db/action_materialize/tracker。
3. F6 合法缺席多处缩回 `int(x or 0)`；xiexang `_note` 去重复；不造 helper、不洗真值坏字段。
4. 五类扫描扩到 `web/` JS/TS/Vue；成员/例外入表。
