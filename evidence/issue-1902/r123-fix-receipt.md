# #1902 修内司 R1–R3 回执（谓词纠偏续修）

- 分支：`ak-roles/1902-r123-fixer-f21f118da`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`f21f118da251bc2fa971255bb6f47bfa704a8de6`
- 判词真源：附件 `04-1902-judge-f21f118da.json` → `outcome.payloads[-1]`（status=continue；findings R1/R2/R3）
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10975-803c-7cac-80e8-e2ad1c6ae22c@fixer/fix-packet.md`
- 官方生态：变异用现成 [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) 临时插件；不另造注入机制、不落永久扫描器/生产钩子
- 枚举输出：
  - `evidence/issue-1902/r123-r1-enum.out`
  - `evidence/issue-1902/r123-r2-enum.out`
  - `evidence/issue-1902/r123-r3-enum.out`
  - 复扫：`evidence/issue-1902/r123-final-rescan.out`
- 聚焦测试：`evidence/issue-1902/r123-focus-pytest.txt`
- 临时变异：`evidence/issue-1902/r123-mutations.out`（及自产 `/tmp/ming1902-r123v2/`，交卷前清理）
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

## 自查纠偏（相对上轮收窄谓词）

上轮回执把 R2 收窄为「仅 `pytest.raises(..., match=)`」、R3 收窄为「仅 `validate_all` 且同文件已有 fixture」、R1 局限已知字段。本轮按判词类定义全文重扫：

| 类 | 上轮收窄 | 本轮谓词 |
|---|---|---|
| R1 | 已知批次字段名 | 全部抽取入口 CALL + 实际 return 键 + 下游 SUB/ATTR/KW 消费 `drafts`/`draft_failures`/`draft_combo_flags`/`baseline_draft_failures`/`draft_count` |
| R2 | 仅 `match=` | Python：`raises.match` + reason/message/caplog 子串断言；Web：`toThrow`/`toMatch`/`toContain`/`toHaveTextContent`；逐成员分 INJECT_OR_SOURCE / SOURCE_PASSTHROUGH / STRUCTURED_* / DIAG_LOCK |
| R3 | 仅 validate_all + 同文件 fixture | 全仓 test_* 含 helper（validate_all/map_*/apply_*/prewrite/canonical）且 `pytest.raises`、无 orch 调用 → HELPER_ONLY_NEG；按生产入口/编排关系分类 |

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

边界：不新增护栏、兼容层、永久扫描器或平行测试；不恢复退役手拟入口；不索全量。

---

## 扫描命令（可重放；临时 AST，未入库永久扫描器）

### R1

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
# 机械：生产调用点
rg -n --glob '*.py' --glob '!tests/**' \
  -e 'resubmit_draft_admission_payload' \
  -e 'extract_draft_intent_with_roster_heal' \
  -e 'extract_draft_intent' \
  -e 'draft_combo_flags' -e 'draft_failures' -e 'baseline_draft_failures' \
  "$ROOT/ming_sim" "$ROOT/web_app.py"
# AST 全枚举（Call / Return keys / SUB|ATTR|KW batch）→ evidence/issue-1902/r123-r1-enum.out
# 结果：CALL 10；BATCH 下游读写 0；仅注释残留（见 r123-final-rescan.out）
```

### R2

```bash
# AST 全仓 tests/**/*.py：pytest.raises(match=) + assert reason/message/caplog 字符串
# + web/**/*.test.*：toThrow/toMatch/toContain/toHaveTextContent
# → evidence/issue-1902/r123-r2-enum.out
# 分类计数（本轮实测）：
#   STRUCTURED_OR_OTHER 140 | WEB_OTHER 131 | INJECT_OR_SOURCE 68
#   SOURCE_PASSTHROUGH 21 | STRUCTURED_DOMAIN 14 | DIAG_LOCK 0（误报「王绍徽」归 SOURCE_PASSTHROUGH）
```

### R3

```bash
# AST 全仓 test_*：若调用 HELPERS={validate_all,map_*,apply_*,prewrite,canonical}
# 且 pytest.raises，且无 ORCH={submit_hitl_choices,_adjudicate_cli_decisions,_post_resolve,...}
# → HELPER_ONLY_NEG；产出 evidence/issue-1902/r123-r3-enum.out
```

---

## 完整成员表

### R1 — 无现役消费者的抽取模式与承接

| 成员 | 处置 | 保留/删除依据 |
|---|---|---|
| `extract_draft_intent` 单旨 / 合法「无」/ push / `acting_appointment`→「无」 | **保留** | 现役生产返回形状；resubmit 消费者 |
| `_finalize_extract_with_combo(..., needs_combo=)` 单旨组合闸 | **保留** | 必要组合 heal；生产调用 |
| `extract_draft_intent_with_roster_heal` + roster 名册校验/纠错 | **保留** | 必要名册 heal；resubmit 唯一生产调用 |
| `_affair_declaration_from_draft_obj` / `_stamp_split_birth_key` | **保留** | 真实事务声明承接 |
| `draft_combo_flags` / `draft_failures` / drafts 合并环 / batch revalidate / baseline_draft_failures / StructuredDecreeCombinationError.draft_failures / drafts 遍历 helpers | **已删**（上轮+本轮复扫 0 功能符号） | 无生产传入；extract 不产 `drafts` |
| 批抽专用测试 | **无成员** | 测试侧无 `extract+drafts` 专用案 |
| `rescript_draft` / DB `list_rescript_drafts` | **保留（类外）** | 非抽取批抽 `result["drafts"]` |

生产链：`session.resubmit_draft_admission_payload` → `extract_draft_intent_with_roster_heal` → `extract_draft_intent` → `_finalize_extract_with_combo`。

### R2 — 非契约诊断文本证明

#### 修（移除措辞依赖；补回结构化 category/source/原子性）

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_decree_dossiers_571` 多处 `match=参与人物/委派人/机械档/打回判决/typed` | **修**（上轮） | `pytest.raises(ValueError)` + 空表/roster/decisions 终态 |
| 同文件 `any("account" in reason)` / `canonical target` / `assignee` 子串 | **修→再修** | 上轮仅 `assert rej/reasons` **丢失 category/source**；本轮改为断言 `category==locality_fanout_failed`、`source==player_decree`、`item_json.directive_id` + draft 原子性 |
| `test_error_pack.py` `match=atomic` | **修**（上轮） | 去 match；断言未写出 manifest |
| `test_pay_order_override_extraction_653` `match=entries` | **修**（上轮） | 去 match；保留 ValueError 拒收 |

#### 保留（逐类，非统称「其余都是来源」）

| 分类 | 代表成员 | 合法保留依据 |
|---|---|---|
| INJECT_OR_SOURCE（68× raises.match） | `match="boom"/inject/模拟…/dossier close failed/派系…不可写/association boom/…` | 测试注入精确异常串；钉实际异常来源透传 |
| SOURCE_PASSTHROUGH | `LLM 不可用` in note；`幻觉甲/丙` in reason；`王绍徽` in reason；web `settleStream` toThrow 用注入 `httpErrorLabel`/`detail` | 实际输入/异常来源原文透传，非生产诊断锁词 |
| STRUCTURED_DOMAIN | effect_origin `reason==奉旨裁撤`；scroll speaker；`请奏` 原文 | 结构化领域字段或输入原文，非诊断措辞 |
| STRUCTURED_OR_OTHER / WEB_OTHER | 字段缺席、`status`/`pending`、非诊断 UI | 非 R2 诊断词面 |
| 闸类负向本体 | 各 `raises(ValueError)` 无 match | 真实拒收+终态 |

生产诊断词面 `raises.match` DIAG_LOCK：**0**（复扫残留 `later`/`orig`/`translation unavailable` 属注入/来源短哨兵）。

### R3 — 绕过真实编排的负向证明

#### 修（helper-only 平行 → 真编排）

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_cli_entry_1902::…ordinary…rejected_by_core` | **修**（上轮） | `_real_submit_session` + `submit_hitl_choices` |
| `test_657_c1_validate_rejects_stale_capability_and_desk_outsider` | **修** | 复用 `_real_submit_session`；拒收后 `status==pending` |
| `test_657_c1_decided_mismatch_rejects_and_cas0` | **修** | 真 submit 落 hold 后再拒异票/空 choice |
| `test_657_default_hold_missing_and_empty_action` | **修** | 真 submit 承载 hold+异票+revise 空 action；HTTP 正向平行案保留 |
| `test_657_capability_revalidate_on_follow` | **修** | 真 submit 拒旧 cap；derive 结构化对齐保留 |

#### 保留（按生产入口/编排关系分类；不以「核 API」之名免责）

| 成员 | 生产关系 | 保留依据 |
|---|---|---|
| `test_cli_blank_pick_on_urgent…` / note-only 真编排案 | CLI → submit | 已有真实提交夹具 |
| `test_657_http_default_hold_*` / `_post_resolve` HTTP 负向 | Web ASGI → submit | 真实 HTTP 入口 |
| `test_1682_phase2_surfaces_ambiguous_*` | `make_light_session`+submit | 真编排歧义拒 |
| mapper 闸：`map_rescript_option_or_choice` 拒（p6 title>80、appointment name≠target、execution_pressure locality、abi matrix） | 生产：`submit`→`validate`→**同一 mapper** | 被测接缝=mapper 单一边界；硬规13④；非与入口案同契约的第二份平行证明 |
| apply/prewrite 领域：`record_event_choice_failure`、`prewrite_failure`、`1682_late_grants`、`midzhi`、`658_deliberate*`、`658_candidates*` | 生产：`session` 在 validate 后调 **同一** `apply_rescript_batch`/`run_prewrite_llms` | 被测=领域写/prewrite 闸与回滚；raises 落在 apply/prewrite/注入，非入口平行 |
| `test_658_stage_rejects_bad_backing_*` | `stage_punishment_candidate` 首写闸；validate 仅种 deliberate 前置 | 被测=stage 接缝；非 validate_all 平行入口证明 |
| `test_adjudication_blank_on_ordinary…` 入口录音 | 入口输入接缝 | 与核内拒收独立（末判完整性 C3） |

---

## 根因 / 修法

- **R1**：批抽承接已清；本轮宽谓词复扫生产 BATCH 读写 **0**。
- **R2**：上轮去措辞后 `assert rej` 过弱，丢失 `category`/`source`/directive 归属；本轮补结构化契约。宽扫后无生产诊断 `match=` 残留。
- **R3**：上轮只改 CLI ordinary；宽扫后将 pihong/rescript_choices 中 validate_all 平行拒收改走 `_real_submit_session`。变异改为**禁用 submit 行为**（恒接受）使真实负向 DID NOT RAISE，而非改名 AttributeError。

---

## 聚焦测试

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
    tests/test_cli_backend.py \
    tests/test_pihong_dossier_1490.py::test_657_c1_validate_rejects_stale_capability_and_desk_outsider \
    tests/test_pihong_dossier_1490.py::test_657_c1_decided_mismatch_rejects_and_cas0 \
    tests/test_pihong_dossier_1490.py::test_657_default_hold_missing_and_empty_action \
    tests/test_pihong_dossier_1490.py::test_657_http_default_hold_keyed_empty_action_and_betray \
    tests/test_rescript_choices_563.py::test_657_capability_revalidate_on_follow
```

结果：`270 passed in 7.34s`（`/usr/bin/time -p`：real 7.95 / user 5.37 / sys 2.05）。未跑全量。

---

## 临时变异证据（不落永久证明测试）

方法：临时 pytest 插件 + 进程内改回；参照 monkeypatch 官方 API。

| 类 | 变异 | 结果 |
|---|---|---|
| R3 | `GameSession.submit_hitl_choices` **恒接受**（禁用拒收行为，非改名） | ordinary / stale-cap / old-cap 均 **DID NOT RAISE** RED → 恢复 GREEN |
| R2 | `locality_fanout_failed` → `locality_fanout_CORRUPTED` | 结构化 category 断言 RED → 恢复 GREEN |
| R1 | （上轮）batch kw TypeError / 抽空 finalize | 已在既有 commits；本轮复扫 0 功能残留 |

原文：`evidence/issue-1902/r123-mutations.out`。

---

## 测试最小必要成本

- 未新增平行测试文件；R2/R3 改既有案。
- 聚焦约 270 案，~8s；未跑全量。
- 临时枚举/变异仅 `/tmp/ming1902-r123v2`，交卷清理；不碰他席 `/tmp/ming1902-*`。

---

## 合法性 / 复杂度复检

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增护栏、兼容层、永久扫描器、错误码、生产测试钩子。
- 优先复用 `_real_submit_session` / HTTP 夹具；不 mock 被测编排。

---

## 最终 git 查询

```bash
git rev-parse HEAD
git status -sb
git log -3 --oneline
```

（交卷提交后以 `git rev-parse HEAD` 为准；不为回执自引用 SHA 反复盖章提交。）
