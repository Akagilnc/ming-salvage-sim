# #1835 w5 处置表（人工读卷·非 classify 默认豁免机）

HEAD 施工基线：`4b74f00cc`；裸 int 误改：`d4a47f6db`。
**stash 违规仍留档**：第一劳动调用曾 `stash push`/`apply`/`drop`；后续轮次未再 stash，不以「本轮未 stash」抹去前轮违规。
已删：`classify.py` 假表；冗余大 JSON（`ast-audit`/`rejudge`/`mutation-probes`/`failed-test-baseline`）—缺文件非 blocker。
机械枚举脚本：`artifacts/issue-1835-w5-ast-audit.py`（只枚举）。本轮工作树收尾完成；**将提交**；无 push / amend。

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
| 全仓含 web JS/TS/Vue 五类 `rg` 机械扫 | **已跑**（见下） |
| 人工缩至文件/函数后通读 | 见下；未读区域已清零 |
| `ming_sim/db.py` F5/F6/F12 | **已读** |
| `web_app.py` / `cli_backend` / `action_materialize` / `rescript_*` / `materials` | **已读** |
| `web/src/**` TS/TSX | **已读** |
| F10 测试（py + web） | **已读归类** |

---

## 可执行枚举命令（全仓·含前端·按类）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5

/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  artifacts/issue-1835-w5-ast-audit.py

# --- F1 ---
rg -n --glob '!**/artifacts/**' --glob '!**/node_modules/**' \
  '_VIEW_TO_SECTION|view_keys|ITEM_FIELD_ALIASES|MODULE_FIELDS|pairing_warnings|_initiative_resolve_pairing' \
  ming_sim/ web/ web_app.py

# --- F5 ---
rg -n -g '*.py' --glob '!**/artifacts/**' --glob '!**/.venv/**' \
  '\.strip\(\)|\.replace\(|\.replaceAll\(' ming_sim/entities/affair ming_sim/entities/population web_app.py
rg -n --glob '!**/node_modules/**' --glob '!**/dist/**' \
  -g '*.{ts,tsx,js,jsx,vue}' \
  '\.replace\(|\.replaceAll\(|\.substring\(|\.slice\(|\.trim\(|new RegExp\(|\.match\(|\.matchAll\(' \
  web/

# --- F6 ---
rg -n -g '*.py' --glob '!**/artifacts/**' --glob '!**/.venv/**' \
  'except \(TypeError, ValueError\)|except ValueError|int\([^\n]*or 0\)' \
  ming_sim/entities/issue/commitment_display.py ming_sim/action_materialize.py \
  ming_sim/db.py ming_sim/rescript_actions.py ming_sim/cli_backend.py web_app.py
rg -n --glob '!**/node_modules/**' -g '*.{ts,tsx,js,jsx,vue}' \
  'catch\s*\(' web/

# --- F10 ---
rg -n -g 'test_*.py' --glob '!**/artifacts/**' \
  'toContain|toMatch|assert.*in |assertIn\(|pairing' tests/
rg -n --glob '!**/node_modules/**' -g '*.{ts,tsx,js,jsx,vue}' \
  'toContain\(|toMatch\(|\.includes\(|indexOf\(|startsWith\(|endsWith\(' \
  web/

# --- F12 ---
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
| `settlement/views.py` `_VIEW_TO_SECTION` / `view_keys` | 已删 | 平行投影；权威 `SettlementOutcome.sections()` |
| `effects` pairing 整链 + `IssueSectionResult.pairing_warnings` | 已删 | 恒空壳；缺口 #1873 |

### F5
| 成员 | 处置 | 依据 |
|---|---|---|
| `affair/store.py` name·origin | 已修 | strip 判空；落库原文 |
| `population/apply.py` reason | 已修 | 查键 strip 副本；ledger 写 `raw_reason` |

### F6
| 成员 | 处置 | 依据 |
|---|---|---|
| `commitment_display` origin_turn / bar | 已修 | 缺席回落；**持久**坏上抛 |
| `action_materialize` / `declaration_dispatch` | LLM 脏→ValidationError→`invalid_shape`；持久仍上抛 | 来源分流 |
| `db` normalize 收权/撤回/罚俸/军令/下议 | LLM→`DeclarationDataError` | 声明路径 |
| `_has_stop_condition` + `insert_issue` 空白 stop | legacy 散文≠结构化 stop；JSON 形坏上抛；空白不存 | 入口变异见 repair |
| `cli_backend` 期限月数 | 脏→`DeclarationDataError` | 抽取失败 |
| `rescript_actions` 期限/amount | **batch validated / server persisted**；§B.1 VE 整批回滚；删无分流 try/re-raise | 非当轮 LLM |
| `new_armies` `_score` | 上游 `dirty_field` 已拒；转换坏=不变量失败 | 非「在场坏上抛」叙事 |
| `faction` mid | 已有 `faction_delta「…」增量非整数` reject | 维持 |
| `breach_plea` / `covert_progress` / `materials` | 维持 | 在场坏上抛 |

### F10 / F12
已结成员见 `d4a47f6db` 处置表；本复检无新开。要点：pairing/词表/`parse_staged_year_promise`/`_secret_metadata_from_command` 已删。

---

## 已读例外（文件/函数级；可核）

| 类 | 成员 | 为何不是该类 |
|---|---|---|
| F1 | `_PI_THINKING_BY_STRENGTH` / `_OPENAI_REASONING_BY_STRENGTH` / `_ORDERED_DELTA_FIELDS` | 受控枚举/处理序，非结算平行投影 |
| F5 | credit/dispatch/dossier note / textual_fact / fiscal.display / web trim·SSE | strip 判空或展示/协议；落库原文 |
| F6 | `_norm_int_leaf` except→原值；拒收/`_fail`；`_coerce_new_salary_rate`；web HTTP/UI catch | 非缺席成功账 |
| F10 | fixture 保真；situation/settlementPresentation/ministerScrollLens；SSE/CSS | 非自由散文盯文 |
| F12 | `matching.compact_name` / `_humanize_condition` / `_LEGACY_DURATION_MONTHS` / scripts | 受控查键或非生产结算 |

---

## 未读区域

**无。**

---

## 本复检相对上轮增量

1. F6 来源分流落地；催办 `except→1`→拒收；`rescript_draft` amount 漏捕补。
2. `rescript_actions` 删无分流价值 try/re-raise；表标明 validated/persisted≠当轮 LLM。
3. stop 入口变异：d4a `_has_stop_condition`+写端旧 insert → 旧红/当前绿；持久 VE 注入不被宽 catch 吸收。
4. 删冗余 JSON 证据副本；repair 只摘结构结果；七变量每次显式。
5. 旧轮已结类引用 `4b74f00cc`/`d4a47f6db`，避免复制。
