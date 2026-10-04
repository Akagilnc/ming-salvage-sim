# #1835 w5 修内司回执（人工读卷·禁默认豁免机）

HEAD 基线：`4b74f00cc7eca0b55233498ea046f7f6a47d820d`  
分支：`ak-roles/issue-1835-w5`  
判词：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a1081f-ad86-79fa-822c-b8a0e0004977@fixer/attachments/01-1835-judge-4b74f00cc.json` **payloads[-1]**  
本报告随本轮新提交落账；未 amend、rewrite 或 push。

### stash 违规记录

第一劳动调用产物明确自报误执行 `git stash push`（tmp-check），随后 `stash apply` 恢复、`stash drop` 丢弃该自建条目。这违反用户的禁止 stash 指令；不能以恢复产物洗白。依据是该次劳动回执，不是既有 stash 列表。后续调用要求并报告不再使用 stash；本席未执行任何 stash 命令。保留此违规上呈，不冒称全局无违规。

已删除违法产物：`artifacts/issue-1835-w5-classify.py`（默认全例外归类机）及其生成的 disposition.json 假全表。  
处置真源：`artifacts/issue-1835-w5-disposition.md`（人工读卷成员/例外；含 web 五类扫）。

自建大体积 AST 候选 JSON（`issue-1835-w5-ast-audit.json`）= 审计中间物，**不进 commit**；取证脚本可留树、**不需 commit**。只提交精简枚举命令、成员表、本报告。

---

## 类义（末份·未收窄）

| 类 | 全义 |
|---|---|
| F1 | 重复机制（不只 identity map） |
| F5 | 自由散文链删改（不限事务 name/origin） |
| F6 | 在场坏字段/异常→缺席正常（不限持久进度） |
| F10 | 盯自由文本/内部结构/重复检查（不限已断言结构） |
| F12 | 散文裁断胜负/拒收/状态/权限/身份（不限 reason/财政） |

---

## 本复检代码变化（相对工作树）

| 类 | 变化 |
|---|---|
| F1 | 删 `effects` pairing 恒空 stub 整链 + `IssueSectionResult.pairing_warnings`；`views` 平行名录；非保留调用形 |
| F12/F1 | `capture_commitment_stages` 删废参 `narrative_text`/`origin_turn`；迁 db/action_materialize/tracker；fiscal reason-token dedup 整删 |
| F6 | 合法缺席多处缩 `int(x or 0)`；在场坏上抛；`require_explicit_xiexang_fields` 单一 `_note`；不造 helper |
| F5 | affair name/origin strip 仅判空落库原文；population reason 查键副本 |
| F10 | 盯文测删；`test_initiative_resolve_pairing.py` 整删 |
| 扫描 | 五类扩到 `web/` TS/TSX/JS/Vue（见 disposition 可执行命令） |

未补证明测试；未恢复被拆功能；未为既有红装回非法机制。  
**本票无阻断**；#1873 等仅作功能移交/剩余范围，不入「真实缺前置」分类。

---

## 修复统计

| 项 | 数量/说明 |
|---|---|
| 相对基线 | 31 files，`+268 / -928`（生产侧约 `+245 / -634`） |
| pairing 恒空链 | 整删（2 函数 + 调用点 + 段结果字段） |
| capture 废参 / staged 散文 due | 形参与叙事回落整删 |
| F6 膨胀→缺席/上抛分立 | 多文件按成员独立缩 |
| stash | 第一劳动调用违规 push/apply/drop；如实上呈 |

### 改动 >400 行必要性（不可为行数拆遗漏）

授权强制**按类独立全覆盖**删简：F1 重复壳、F5 散文传递链、F6 坏字段洗白、F10 盯文测、F12 散文代判——五类各自通读成员后整删/收权，**不得以「控行数」拆掉任一已认定成员**。  
净删 ~900 行来自：pairing 整链、fiscal reason-token、staged 叙事 due、cli 密令散文抽标签、views 平行名录、多文件 F6 try/except 洗白收权、F10 整测文件删除。按类独立验收面叠加，行数必然过 400；拆遗漏=违授权。

---

## 枚举（每类；成员表见 disposition）

见 `artifacts/issue-1835-w5-disposition.md`「可执行枚举命令」（含 F1/F5/F6/F10/F12 分条）。  
Python AST：`artifacts/issue-1835-w5-ast-audit.py`（大 JSON 中间物不提交）。

### 真实变异探针（进程内 `git show 4b74f00cc` 装回旧函数/类方法）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  artifacts/issue-1835-w5-mutation-probes.py
```

| 类 | 装回对象 | 入口 | 旧 | 当前 |
|---|---|---|---|---|
| F1 | （不装旧；复扫） | `views.section` ≡ `sections().get` | — | 平行名录已删；单源等价 |
| F5 | `AffairStore.open` | `settle_delta` 嵌套事务→DB | name/origin **被 strip**（红） | **原文落库**（绿） |
| F6 | `commitment_progress_payload` | `apply_issue_inertia_and_ongoing` | 正常返回并伪造 progress（`months_elapsed=1`） | `ValueError` 上抛 |
| F12 | `fiscal.apply_creates`（含 token helpers 于其 globals） | `settle_delta` 同 payload 两 reason | 无关甲落账 / 每月拨…→`deduped_commitment_carrier` **分歧** | 两 reason **均落账相同** |

---

## 聚焦测试命令（仅七显式变量；无全量）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line \
  tests/test_execution_joint_liability_565.py \
  tests/test_decree_commitment_creation_136.py \
  tests/test_decree_dossiers_571.py \
  tests/test_commitment_display_348.py \
  tests/test_affairs_1831.py \
  tests/test_settlement_fixed_point_1835.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_section_fiscal_rejections.py \
  tests/test_credit_events_628.py \
  tests/test_issue_entities.py \
  tests/test_grant_reconciliation_567.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_month_chain_1847.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_relation_seed_638.py \
  tests/test_qa_h1_seed_data.py \
  tests/test_faction_leverage_9.py \
  tests/test_population_transfers_649.py \
  tests/test_covert_levy_651.py \
  tests/test_rescript_draft_656.py \
  tests/test_rescript_choices_563.py \
  tests/test_world_materials_1834.py \
  tests/test_material_directory_1830.py
```

### 实测（本回执七变量复跑）

**聚焦：** 劳动复跑 `3 failed, 674 passed in 14.24s`（`real 14.64`）；本席独立复验 `3 failed, 674 passed in 14.16s`（`real 14.70 / user 9.88 / sys 3.77`）。

保留既有 2 红 + 扩展聚焦露出的同根第 3 红（详见 `issue-1835-w5-failed-test-baseline.json`）：

1. `test_has_stop_condition_handles_preparsed_and_json_whitespace` — 既有红；移交剩余范围 #1873  
2. `test_commitment_progress_skips_non_numeric_gate_values` — 既有红（坏门值上抛）；不装回默认化  
3. `test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition` — 扩展聚焦露出；同根 `_has_stop_condition` JSONDecodeError；不装回吞异常  

**变异探针：** `real 1.51`；`mutation_mode=in_process_git_show_install`  
- F5 `old_red_current_green=true`  
- F6 `old_forge_ok_current_raises=true`  
- F12 `old_diverge_current_same=true`  
- F1 复扫：`_VIEW_TO_SECTION`/`view_keys` 已无；`section is sections().get`

产物：`artifacts/issue-1835-w5-mutation-probes.json`（大审计中间物不进 commit）。

---

## 本票阻断 / 剩余范围

| 项 | 性质 |
|---|---|
| 本票宪法/授权阻断 | **无** |
| #45/#46 结案配对等功能缺口 | **功能移交 / 剩余范围**（#1873）；本票不重开散文裁断、不替造证明测、不留恒空壳 |
| 上列聚焦 3 红 | **非本票引入**；不为绿装回 F6 洗白 / 吞异常 |
| 工作量 | **不是阻断** |

无宪法铁律冲突需停工项（P1/P6/P7：落库原文、不篡改 LLM 自由文本、不造散文代判）。
