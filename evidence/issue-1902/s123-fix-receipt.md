# #1902 修内司 S1–S3 回执（全类枚举纠正）

- 分支：`ak-roles/1902-s123-fixer-6850e0b5f`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工本轮）：`4e6e16882`（其上轮仍以 FOCUS 缩窄，本轮纠正）
- 判词真源：附件 `05-1902-judge-6850e0b5f.json` → `outcome.payloads[-1]`（status=continue；S1/S2/S3）
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a109b6-e895-77f7-818f-eecda14836ac@fixer/fix-packet.md`
- **不宣称已合并 / 总票完成**
- **不宣称样本 FOCUS 为完整全集**（上轮错误；本轮已取消）

七 BIN 前缀（显式展开）：

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

## 上轮收窄与本轮纠正

| 问题 | 纠正 |
|---|---|
| S2 扫描开篇 `FOCUS={validate_all,map_*,RescriptAdjudication,...}` | **取消 FOCUS**；枚举全部 tracked `tests/*.py` 的 `test_*`（2976）+ web `*.{test,spec}.{ts,tsx}` 的 `it/test`（317）= **3293** 案例；TSV+逐案分类 md |
| S1 以样本名/理解链正则门控候选 | 全 tracked 生产 FunctionDef/ClassDef/Assign(const)；**零生产 Load/Attribute 全集发出**；框架路由/动态字符串/dunder 分栏；人工核删除 |
| S3 点名 `_runtime_float` / startswith 样本 | 全仓 event:/data: 同构拆包 + 小 float coerce + web timeout 数值槽；权威外零 inline SSE；web 双份 `parseFloat\|\|default` → `slotNumber` |
| 枚举冒称完整 | 成员覆盖数写明；分类表点名每一案（同文件同类组合列出） |

---

## 末判三类定义（逐字）

1. **S1：退役实现清退** — 依实际生产消费者清退无用途旧根、独占子树与专属测试；保留现役共享能力，不恢复手拟新旨入口。
2. **S2：真实行为测试归位** — 按独立外部行为契约核对剩余内部证明，复用已有真实入口 tracer 承载必要拒收及持久结果，删除内部形状和重复证明；不得删除负向契约或 mock 替代被测编排。
3. **S3：解析单源** — 消费者复用已有 SSE、数值取值实现，删除同构副本；保留原有输入、协议和外部结果契约。

---

## 可重放枚举（临时 AST，`.ast.py.txt` 证据，非永久扫描器）

```bash
cp evidence/issue-1902/s123-scan-s1.ast.py.txt /tmp/scan_s1.py
cp evidence/issue-1902/s123-scan-s2.ast.py.txt /tmp/scan_s2.py
cp evidence/issue-1902/s123-scan-s3.ast.py.txt /tmp/scan_s3.py
SCAN_ROOT=. SCAN_OUT=/tmp/ming1902-s123-full python3 /tmp/scan_s1.py | tee evidence/issue-1902/s123-s1-rescan-summary.txt
SCAN_ROOT=. SCAN_OUT=/tmp/ming1902-s123-full python3 /tmp/scan_s2.py | tee evidence/issue-1902/s123-s2-rescan-summary.txt
SCAN_ROOT=. SCAN_OUT=/tmp/ming1902-s123-full python3 /tmp/scan_s3.py | tee evidence/issue-1902/s123-s3-enum.txt
```

产出：

| 文件 | 内容 |
|---|---|
| `s123-s1-enum.json` | S1 全零生产引用成员 |
| `s123-s2-full.tsv` | S2 **每一案**一行（3293） |
| `s123-s2-classification.md` | 同文件+同类组合列出**全部案例名** |
| `s123-s3-enum.json` / `.txt` | SSE + 数值同构枚举 |

### 谓词（覆盖类定义全文，未收窄）

- **S1**：tracked `*.py` 生产 defs/consts；非测试 Load/Attribute refs==0 → `ZERO_PROD_REF_CANDIDATE`；`@app.*`/`router` → `FRAMEWORK_ROUTE`；字符串字面提及 → `DYNAMIC_STRING_REF`；dunder 单列。**无样本名门控。**
- **S2**：全部 `test_*` + web `it/test`；**无 FOCUS**；逐案归类 `EXTERNAL_REAL_ENTRY` / `INTERNAL_SHAPE` / `DUPLICATE` / `INPUT_ADAPT_OR_DOMAIN_FIRST_WRITE`；orch 含 submit/HTTP/`_657_subprocess_resolve`/`prepare_rescript_prewrite` 等。
- **S3**：startswith/split/re/slice 的 `event:`/`data:`；小 float+except helpers；web timeout `parseFloat`/`slotNumber`；权威=`parse_sse_*` + `_slot_number` + `web/src/slotNumber.ts`。

---

## S1 成员处置（全零引用集审计后动手者）

复扫：`ZERO_PROD_REF_CANDIDATE=187`（另 FRAMEWORK=3 / DYNAMIC=1 / DUNDER=6）。**不全删**——大量为 FastAPI 装饰器入口（AST 无 Load）、同文件仅 Attribute 漏检、或 #1847 待接线能力。

| 成员 | 可核契约 | 真实生产入口 | 外部结果 | 处置 |
|---|---|---|---|---|
| `_CLAUSE_SPLIT` / `_ASSIGNEE_*` / `_ASSIGNEE_IMPERATIVE_RE` / `_ASSIGN_NAME_HEAD_ADVERB_RE` + 无用 INSTITUTION import | 旧密令理解承办人抽取 | 无（随 `_extract_secret_order` 已死） | — | **本轮删** |
| `_CONFIRM_WORDS` / `_REJECT_WORDS`（`cli/terminal.py`） | 旧手拟确认词表 | 无 | — | **本轮删** |
| `GameDB.append_rescript_drafts` | phase2 追加票拟行 | 全仓零调用（现役改票走 UPDATE CAS） | — | **本轮删** |
| `GameDB.complete_rescript_summon_scaffold_turn` | scaffold → consumed | 全仓零调用 | — | **本轮删** |
| `_extract_secret_order` / `compose_*_recovery` / 旧前缀 / `upsert_secret_order` / `attach_secret_oral_pin` | 旧理解/恢复/upsert | 无 | — | **上轮已删**（复扫 defs 缺席） |
| `api_secret_orders` 等 `@app.*` | HTTP | 框架路由 | JSON | **保留**（FRAMEWORK / 假死） |
| `generate_rescript_draft` / `create_rescript_draft_agent` | 票拟 LLM 生成 | 生产 Call=0；ADR0093/#1847 待接线 | — | **保留**（现役共享能力，非专属死根整删） |
| `save_rescript_drafts` | DB 种急务行 | 生产 Call=0；测试种 fixture + 月链他路写 pending | — | **保留**（共享 DB API） |
| `CliChat` / `secret_order_can_land` / `update_secret_order_by_id` / resubmit→heal→extract | 现役 | 有消费者 | — | **保留** |

---

## S2 全类覆盖与处置

**宇宙：py=2976 + web=317 = 3293。** 逐案表见 `s123-s2-classification.md`（禁止文件统称保留）。

分类计数（本轮）：

| 类 | 数 | 含义 |
|---|---|---|
| EXTERNAL_REAL_ENTRY | 3186 | 真实入口/编排外部结果 |
| INPUT_ADAPT_OR_DOMAIN_FIRST_WRITE | 107 | 合法输入适配或领域首写接缝 |
| INTERNAL_SHAPE | 0 | 须迁真/删除的内部形状（本轮清零） |
| DUPLICATE | 0 | 重复证明（上轮删五动作 helper；本轮删 abi map 正形状） |

### 本轮修复的内部/重复成员（逐案）

| 成员 | 可核契约 | 真实生产入口 | 外部结果 | 既有 tracer | 处置 |
|---|---|---|---|---|---|
| `test_657_abi_mapper_matrix_a1_a12` 内 **正向** `map_rescript_option_or_choice`→`assert p[...]` | mapper 返回形状 | 同测已有 `_submit_hitl` 世界事实 | initiative/army/流水等 | `_submit_hitl` / `_apply_mapped_choice` | **删内部正形状**（重复于 submit 腿）；**保留** `pytest.raises(map…)` 类型输入拒收 + submit 落库 |
| `test_validate_all_unknown_roster_name_*` | 名含 validate_all 假阳性 | `create_decree_dossiers` | COUNT 不变 | 直调 create | **更名**为 `test_create_decree_dossiers_unknown_roster_name_*`；契约=领域首写，非 validate_all |
| 上轮已迁真之 hold/prewrite/follow/midzhi/HTTP 冲突等 | — | submit/HTTP | — | — | **维持** |

### 内部证明候选（复扫后）处置原则摘要

凡曾落 `INTERNAL_SHAPE_CANDIDATE` 的 apply_dossier / stage / assemble / normalize / create_decree / parse_decision / subprocess HTTP 案：逐案核为 **领域首写或输入适配或真 HTTP**（`_657_subprocess_resolve` / `prepare_rescript_prewrite`），**不**因含 helper 名整删。完整名单在 classification md。

---

## S3 完整成员表

| 成员 | 处置 | 依据 |
|---|---|---|
| `tests/sse_helpers.py` `parse_sse_*` | **权威保留** | 复扫非权威 inline SSE 有意义命中=∅ |
| scroll/qa_b3/player_payload / court_break / night 薄包装 | **保留转发** | 仅调权威，非同构实现 |
| `_runtime_float` | **上轮已删** → `_slot_number` | defs 缺席 |
| `distance._number` / `issues._as_float` / `flows._as_*` / `db._coerce_pay_source_float` 等 | **保留** | 响亮拒收/图代价/财政，**非** runtime slot 默认回落同构 |
| `gameMenu.tsx` + `menuPage.tsx` 双份 `parseFloat(x)\|\|default`（timeout 槽） | **本轮** → 共用 `web/src/slotNumber.ts` | 与 `_slot_number` 同职责（跨语言单源） |

---

## 变异证明（临时进程内，不入库插件）

证据：`s123-mutations.out`。

| 模式 | 入口 | 结果 | 性质 |
|---|---|---|---|
| `submit_hitl_choices`→恒接受 | default_hold / follow_draft overlay / CLI ordinary 空 pick | **3 failed** | **行为变异红** |
| 恢复 | 同上 | **3 passed** | 恢复绿 |
| `parse_sse_*`→`[]` | audience_scroll SSE 两案 | **2 failed**（另 20 非 SSE 腿仍绿） | **行为变异红** |
| 恢复 | scroll 全文件 | **22 passed** | 恢复绿 |
| `_slot_number`→恒 1.0 | `cli_idle_timeout_seconds({timeout:99})` | 99→1.0→99 | **真入口秒级** |
| hasattr 删根 | append/scaffold/_CLAUSE_SPLIT | False；CliChat True | **仅删除观察** |

---

## 聚焦测试

`evidence/issue-1902/s123-focus-pytest.txt`：

```
374 passed in 31.28s
```

Web：`gameMenu.test.tsx` + `menuPage.test.tsx` → **45 passed**。

未跑全量、未真调模型。

---

## 自查二连

- **合法性**：未改 CLAUDE.md/AGENTS.md/CONTEXT.md/ADR；未恢复手拟入口；未增护栏/永久扫描器/生产钩子；扫描以 `.ast.py.txt` + 枚举 JSON/TSV/md 证据存放；`/tmp/ming1902-s123-full` 自建可清。
- **质量**：S2 取消 FOCUS，3293 案全表；abi 内部 map 正形状删除；S1 清孤儿正则/死方法；S3 web timeout 单源；负向 map/create/stage 契约保留。
- **复杂度**：净删死根与内部正形状；不整删 generate_rescript_draft（#1847）。

---

## 例外 / 上呈

无缺 owner 决定项。`generate_rescript_draft` 生产 Call=0 但按 ADR0093/#1847 保留为待接线共享能力，不按死根整删专属测。
