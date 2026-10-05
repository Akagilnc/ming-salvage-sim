# #1902 修内司 R1–R3 回执

- 分支：`ak-roles/1902-r123-fixer-f21f118da`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`f21f118da251bc2fa971255bb6f47bfa704a8de6`
- 本轮代码+回执提交：`ece7bfdfb551d49a73d3fe9e766c5f667f7a5e10`
- 回执盖章链：`1a0e6c54d` → 本文件最终以 `git rev-parse HEAD` 为准（交卷时查询）
- 判词真源：附件 `04-1902-judge-f21f118da.json` → `outcome.payloads[-1]`（status=continue；findings R1/R2/R3）
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10975-803c-7cac-80e8-e2ad1c6ae22c@fixer/fix-packet.md`
- 枚举原始输出：
  - `evidence/issue-1902/r123-r1-enum.out`
  - `evidence/issue-1902/r123-r2-enum.out`
  - `evidence/issue-1902/r123-r3-enum.out`
  - 复扫：`evidence/issue-1902/r123-r2-rescan.out`、`evidence/issue-1902/r123-final-rescan.out`
- 聚焦测试：`evidence/issue-1902/r123-focus-pytest.txt`
- 临时变异：`evidence/issue-1902/r123-mutations.out`（及 `/tmp/ming1902-r123/`）
- **不宣称已合并 / 总票完成**

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

## 末判三类完整定义（逐字自 payloads[-1].fix.classes）

1. **R1：无现役消费者的抽取模式与承接**  
   direction：按非测试生产调用、实际返回形状和下游消费枚举并删净死模式、批次专属字段及专用测试。保留现役单旨补交、必要组合／名册heal及真实事务声明承接。  
   law：#1902；#1812验收第1项；硬规12。

2. **R2：非契约诊断文本证明**  
   direction：移除措辞依赖，保留真实拒收、原子性、结构化终态和实际异常来源契约。不得按match或字符串操作符整删，不新增错误码或生产测试钩子。  
   law：硬规13；《测试对行为负责》。

3. **R3：绕过真实编排的负向证明**  
   direction：复用现有真实提交夹具承载必要负向契约，删除helper-only平行证明；不得删除拒收行为或mock替代被测编排。  
   law：硬规13；《测试对行为负责》。

边界（同 payload fix.boundary）：不新增护栏、兼容层、永久扫描器或平行测试；不恢复退役手拟入口；不索全量。授权外取舍上呈。

---

## 扫描命令（可重放；heredoc AST，未入库永久扫描器）

### R1 — 生产调用链 + 返回形状 + 批次字段消费

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
# 机械：生产调用点
rg -n --glob '*.py' --glob '!tests/**' \
  -e 'resubmit_draft_admission_payload' \
  -e 'extract_draft_intent_with_roster_heal' \
  -e 'extract_draft_intent' \
  -e 'draft_combo_flags' -e 'draft_failures' \
  "$ROOT/ming_sim" "$ROOT/web_app.py"
# AST：见 evidence/issue-1902/r123-r1-enum.out（extract 返回键 / Call 图 / batch readers）
```

**生产链事实（AST）**：唯一非测试调用链  
`session.py:resubmit_draft_admission_payload` → `extract_draft_intent_with_roster_heal` → `extract_draft_intent` → `_finalize_extract_with_combo(..., needs_combo=...)`。  
`extract_draft_intent` 字面返回键从不含 `drafts`（仅单旨 / 合法「无」/ push）。

### R2 — 全仓 `pytest.raises(..., match=)` AST 枚举

```bash
# 产出 → evidence/issue-1902/r123-r2-enum.out
# TOTAL match= : 80（修理前）
# 分类谓词：注入哨兵 / 实际异常来源 → KEEP；生产诊断词面 / reason 子串 → 移除措辞依赖
```

### R3 — helper-only `validate_all` 负向 vs 真实提交夹具

```bash
# 产出 → evidence/issue-1902/r123-r3-enum.out
# 谓词：pytest.raises + 仅调 validate_all，且同文件已有 _real_submit_session / submit_hitl_choices 真编排夹具
```

---

## 完整成员表

### R1 — 无现役消费者的抽取模式与承接

| 成员 | 处置 | 保留/删除依据 |
|---|---|---|
| `extract_draft_intent` 单旨 / 合法「无」/ push / `acting_appointment`→「无」 | **保留** | 现役生产返回形状；resubmit 消费者 |
| `_finalize_extract_with_combo(..., needs_combo=)` 单旨组合闸 | **保留** | 必要组合 heal；生产调用 L2706 |
| `extract_draft_intent_with_roster_heal` + roster 名册校验/纠错 | **保留** | 必要名册 heal；resubmit 唯一生产调用 |
| `_affair_declaration_from_draft_obj` / `_stamp_split_birth_key` | **保留** | 真实事务声明承接 |
| `draft_combo_flags` 批次校验分支（原 2063–2088） | **删** | 无生产传入；extract 不产 `drafts` |
| `_finalize_extract_with_combo` 的 `draft_combo_flags` 形参 | **删** | 批次专属字段 |
| `_merge_combo_correction_preserving_roster` 的 `draft_failures` + drafts 合并环 | **删** | 批次纠错承接不可达 |
| `_revalidate_merged_combo_result` 的 batch collect-all 路径 | **删** | 仅服务 draft_failures |
| heal 内 `baseline_draft_failures` 冻结/回传 | **删** | 批次专属；单旨只留 `baseline_failed_fields` |
| `StructuredDecreeCombinationError.draft_failures` | **删** | 批次专属运输字段 |
| `_person_ids_from_extract_result` / `_count_failed_person_slots` / `_backfill_healed_participant_refs` / `_apply_validated_roster_to_extract_result` / `_ground_relative_pay_order_deadlines` / `has_roster_field` 的 drafts 遍历 | **删** | 下游消费批次形状；现役只读顶层 |
| 批抽专用测试（draft_combo_flags / extract+drafts） | **无成员** | 修理前 AST 扫 tests：0 命中 |
| `rescript_draft` / DB `list_rescript_drafts` 等「急务草稿」 | **保留（类外）** | 非抽取批抽 `result["drafts"]`；批红急务实体 |

**复扫**：`r123-final-rescan.out` — 功能符号 0；仅注释标记。

### R2 — 非契约诊断文本证明

谓词：证明依赖生产诊断词面（`match=` 锁措辞 / reason 子串），而非拒收·原子性·结构化终态·注入/真实异常来源。

#### 修（移除措辞依赖，保留契约）

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_decree_dossiers_571.py` L69/82 `match=参与人物不存在/委派人不存在` | **修** | 改 `pytest.raises(ValueError)` + 空表/名册不变 |
| 同文件 L105/117 `match=委派人须为…` | **修** | 同上 + 空表/长度不变 |
| 同文件 L155/159 `match=机械档不同` | **修** | 同上 + roster 终态 |
| 同文件 L1503 `any("account" in reason)` | **修** | 改 `assert rej`（拒收行存在） |
| 同文件 L1610 `canonical target`/`target` 子串 | **修** | 改 `assert reasons` |
| 同文件 L1914 `assignee` 子串 | **修** | 改 `assert reasons` |
| 同文件 L2043/2060/2078/2100 `match=打回判决缺少/typed 判据快照` | **修** | 去 match；补 `decisions==[]` + `status==proposed` |
| `test_error_pack.py:45` `match=atomic` | **修** | 去 match；断言未写出 `manifest.json` |
| `test_pay_order_override_extraction_653.py:80` `match=entries` | **修** | 去 match；保留 `ValueError` 拒收 |

#### 保留（实际异常来源 / 注入哨兵 — 非本类）

全仓其余 `match=`（枚举见 `r123-r2-enum.out` / 复扫 `r123-r2-rescan.out`）均为测试注入的精确异常串（`boom`/`inject`/`模拟 …`/`dossier close failed`/`派系认领库不可写` 等）或同类来源契约 → **KEEP**。不得按 `match=` 操作符整删。

闸类负向拒收本体、结构化终态断言 → **KEEP**。

### R3 — 绕过真实编排的负向证明

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_cli_entry_1902.py::test_cli_blank_pick_on_ordinary_decision_is_rejected_by_core`（原仅 `ra.validate_all`） | **修** | 改走 `_real_submit_session` + `session.submit_hitl_choices`；断言 `ValueError` + `status==pending` |
| 同文件 `_real_submit_session` / urgent hold / note 拒收等真编排案 | **保留** | 已有真实提交夹具 |
| `test_pihong_dossier_1490.py` 等直接测 `ra.validate_all` 的闸/领域案 | **保留** | 被测对象即核 API（Web 同走）；非 CLI 编排平行证明；硬规13④闸类负向不可删 |
| `test_adjudication_blank_on_ordinary_decision_reprompts`（入口录音替身） | **保留** | 保护入口输入接缝，与核内拒收独立（末判完整性 C3 已驳「重复」） |

---

## 根因 / 修法

- **R1**：N5 清退后 extract 只产单旨，但 heal/finalize/structured_decree 仍携批次 `drafts`/`draft_failures`/`draft_combo_flags` 死路径。按生产调用与返回形状删净批次承接，保留单旨组合+名册 heal+事务声明。
- **R2**：拒收案以诊断正则/子串当契约；亲验改述 ValueError 后结构化终态仍成立、旧 match 却红。去措辞依赖，钉拒收/原子性/终态。
- **R3**：核侧空 pick 负向只调 `validate_all`，禁用 `submit_hitl_choices` 仍绿。复用同文件真实提交夹具承载拒收，不删拒收、不 mock 被测编排。

---

## 聚焦测试

命令（实测）：

```bash
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  python3 -m pytest -q \
    tests/test_cli_entry_1902.py \
    tests/test_decree_dossiers_571.py \
    tests/test_error_pack.py \
    tests/test_pay_order_override_extraction_653.py \
    tests/test_draft_admission_resubmit_1769.py \
    tests/test_structured_decree_contract_1624.py \
    tests/test_cli_backend.py
```

结果：`265 passed in 8.44s`（`/usr/bin/time -p`：real 9.43 / user 5.09 / sys 2.55）。原文：`r123-focus-pytest.txt`。

---

## 临时变异证据（不落永久证明测试）

原文：`evidence/issue-1902/r123-mutations.out`。

| 类 | 变异 | 结果 |
|---|---|---|
| R1 | `draft_combo_flags` / `draft_failures` kw → TypeError；抽空 `_finalize` 组合校验 | RED（1624 combo roster 案）→ 恢复 GREEN |
| R2 | `strict_types.py` 将「打回判决缺少…」改述为「判决字段不齐（改述）」 | 相关拒收案仍 GREEN（措辞无关）→ 恢复 GREEN |
| R3 | 改名 `GameSession.submit_hitl_choices` | ordinary 拒收 + urgent hold 均 RED → 恢复 GREEN |

变异后确认无残留：`NO_LEFTOVERS_OK`。

---

## 测试最小必要成本

- 未新增平行测试文件；R2/R3 均改既有案。
- 聚焦 7 文件 265 案，约 9s；未跑全量。
- 临时变异仅在 `/tmp` + 进程内改回，不入库。

---

## 合法性 / 复杂度复检

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR（治理法源不动）。
- 未新增护栏、兼容层、永久扫描器、错误码、生产测试钩子。
- 净删：`cli_backend.py` 批次死路径大幅收缩（diff 约 −120 行量级）；测试去措辞/改真编排，无加机制。
- 优先删简复用：R3 复用既有 `_real_submit_session`；R1 不另造单旨 API。

---

## 最终 git 查询

```bash
git rev-parse HEAD
git status -sb
git log -3 --oneline
```

实测：

```text
BRANCH: ak-roles/1902-r123-fixer-f21f118da
BASE:   f21f118da251bc2fa971255bb6f47bfa704a8de6
FIX:    ece7bfdfb551d49a73d3fe9e766c5f667f7a5e10
STAMP:  1a0e6c54d25e0013e565fb5d21be6222153b80d3
NOTE:   delivery HEAD = git rev-parse after this docs correction commit
status: working tree clean after docs correction
```
