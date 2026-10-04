# #1902 修内司 R1 回执 — 仅重开 N5（+ 依附 N1 死分支）

- 分支：`ak-roles/1902-n1-n7-fixer-ccbdf378a`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 本轮底座 HEAD（开工）：`043efc2ac`
- 本轮提交：`d450631d1fb9d84ddc80a6b3000ebd694f212057`
- 判词真源（完整原文，非摘要）：宿主 continue payload
  `AK_ROLE_RUN_DIR/.../session/session.jsonl` L41（`status=continue` finding R1）
  + 原法源/boundary：`fix-packet.md` + 附件 `03-1902-judge-ccbdf378a.json` 末 payload N5
- **本轮范围**：只重开 N5；N2/N3/N4/N6/N7 **不重开**
- 枚举原始输出：`/tmp/ming1902-r1-n5/enum.out`（复扫 `/tmp/ming1902-r1-n5/rescan.out`）
- 临时目录：`/tmp/ming1902-r1-n5/`（只清自建临时物；不入库永久扫描器）

七 BIN 前缀：

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

## 新判词原文（R1 / N5 重开；逐字自 session）

```json
{"status":"continue","findings":[{"id":"R1","severity":"P2","class":"共享抽取能力仍携带不可达旧模式（N5 未清净）；N1 首抽新增分支亦不可达","law":"#1902共享核只因现役消费者保留；#1812重构验收第1项（被取代/无消费者的旧路删净）；全局硬规12（复杂度即成本）；同类自归类自扫（陛下09-06原话）。","phenomenon":"N5 回执称 n5_dead_mode_sites=[] 已结清，但共享抽取仍带一整套无任何生产消费者的“召对交办后置点将/承办人必有”模式。","evidence":["全仓 grep：require_execution_lead=、harvest_participants= 在 ming_sim/、web_app.py、tests/ 内无任何调用点传入；唯一生产链是 resubmit_draft_admission_payload(cli_backend.py:2994)→extract_draft_intent_with_roster_heal，且它只传 initial_correction，不传 require_execution_lead。","遗留成员（均仅因该死模式存在）：cli_backend.py MissingExecutionLeadError(1310)、_extract_result_has_execution_lead(2195)、_missing_execution_lead_feedback(2224)、_participant_fields_from_draft_obj(2275)、heal 的 require_execution_lead 形参与 _lead_gate(2326；调用点 2429/2444/2508/2512)、extract_draft_intent 的 harvest_participants 形参及 2690 的 empty.update 分支。本轮 diff 反而把 **extract_kwargs 改写成显式 harvest_participants 形参，把死模式固化为签名。","N1 新增的首抽分支（cli_backend.py:~2616 `raise cli_runner_unavailable(...)`）：唯一生产调用 resubmit 的 initial_correction 恒非空（build_draft_admission_resubmit_feedback 总产出非空 failure_reason 文本），故 `if correction_block: raise` 恒先命中，新分支在生产不可达；回执所称“首抽真落痕变异”是在死路径上探的，是为死路径新增机制。","根因：N5 枚举谓词只按判词点名的四个 kwarg（draft_count/existing_candidates/has_pending_draft/existing_draft_text）取样，未按“该共享核有无现役消费者”定类，正是陛下09-06所斥的把判词样本当类边界。"]}],"fix":{"summary":"按类重扫：以“非测试生产调用链（仅 resubmit→heal→extract）是否消费”为谓词，枚举 extract_draft_intent / extract_draft_intent_with_roster_heal 及其 helper 中全部无现役消费者的模式，连同只为它们存在的测试一并删净（require_execution_lead、harvest_participants、MissingExecutionLeadError、_lead_gate 与上列 helper）；N1 新增的首抽 cli_runner_unavailable 分支若生产不可达则一并删除，不得为死路径保留机制或变异证明。保留现役单旨补交及其必要承接（判词 boundary）；解析失败/缺键/非法枚举响亮上抛真因与合法“无”保留不动。枚举命令与成员表写回执。其余 N2/N3/N4/N6/N7 本轮抽查未见问题，不重开。"},"note":"已核：N7 相对 10e64fbef 差分为空；N2/N3/N4 抽查入口已走共核/直调；N1 解析/缺键/非法枚举已上抛真因。仅 N5 类（及依附的 N1 新增死分支）未清净。"}
```

原 N5 boundary（附件 03，仍生效）：「保留现役单旨补交及其必要模式承接；不能按旧函数名整删。修理死多旨分支本身不能替代清退。」

---

## 纠正旧回执（`n1-n7-fix-receipt.md`）不适用之处

| 旧回执声称 | 本轮裁定 |
|---|---|
| N5「结清」：`n5_dead_mode_sites=[]`（只按旧四 kwarg） | **证据不适用 / 谓词收窄**。未按「非测试生产调用链是否消费」定类，漏掉整套 lead/harvest 死模式。 |
| N1「首抽 LLM Exception → `cli_runner_unavailable`」结清 + `n1_first_draw_trace` 变异 | **死路径结清 / 证据不适用**。生产链 `resubmit` 的 `initial_correction` 恒非空 → `if correction_block: raise` 恒先命中；该分支与为其做的变异证明一并清退。 |
| N1 解析失败/缺键/非法枚举真因上抛 | **仍成立，保留**（本轮未动）。 |
| N2/N3/N4/N6/N7 结清 | **本轮不重开**（判词 note 抽查未见问题）；不在此复验。 |

---

## 枚举命令（谓词：非测试生产调用链是否消费）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
# 1) 生产文件 = ming_sim/**/*.py + web_app.py（排除 tests/）
# 2) 机械扫：require_execution_lead= / harvest_participants= /
#    extract_draft_intent( / extract_draft_intent_with_roster_heal( /
#    MissingExecutionLeadError / _extract_result_has_execution_lead /
#    _missing_execution_lead_feedback / _participant_fields_from_draft_obj /
#    _lead_gate / cli_runner_unavailable(...draft_intent)
# 3) AST 枚举 extract / heal 全部形参与分支（不按旧四 kwarg 收窄）
# 4) tests/ 内 require_execution_lead= / harvest_participants= 传入点
# 5) build_draft_admission_resubmit_feedback 恒非空证明
# 完整脚本输出 → /tmp/ming1902-r1-n5/enum.out
```

关键生产链事实：

- 唯一生产消费者：`session._resubmit_draft_admission_failures` → `resubmit_draft_admission_payload` → `extract_draft_intent_with_roster_heal(..., initial_correction=feedback)` → `extract_draft_intent(..., correction_feedback=correction)`
- `build_draft_admission_resubmit_feedback` 对空/非空 reason 均 `empty=False`（恒有成案失败头 + 失败事实 + 原产物）
- `require_execution_lead=` / `harvest_participants=`：**生产 0 传入**；tests 0 传入
- `require_execution_lead_or_raise`（`executor_routing.py` / `db.py`）= **不同符号**，成案路由闸，**非本类成员**，保留

---

## 完整成员表（N5；谓词=生产是否消费）

| # | 成员 | 生产消费者？ | 处置 | 理由 |
|---|---|---|---|---|
| 1 | `MissingExecutionLeadError` | 无 | **删** | 仅服务 require_execution_lead 死模式 |
| 2 | `_extract_result_has_execution_lead` | 无 | **删** | 仅 `_lead_gate` 用 |
| 3 | `_missing_execution_lead_feedback` | 无 | **删** | 仅 `_lead_gate` 用 |
| 4 | `_participant_fields_from_draft_obj` | 无 | **删** | 仅 `harvest_participants` 空包 update |
| 5 | heal 形参 `require_execution_lead` | 无（生产从不传） | **删** | 签名固化死模式 |
| 6 | heal 内 `_lead_gate` + 4 调用点 | 无（`require_execution_lead` 恒假时恒直通） | **删**；调用点改直接 `return` | 无现役消费者模式 |
| 7 | heal→extract 的 `harvest_participants=` | 无 | **删** | 由 require 派生，无生产 True |
| 8 | extract 形参 `harvest_participants` | 无 | **删** | 同上 |
| 9 | extract「无」分支 `empty.update(_participant_fields...)` | 无 | **删** | 仅 harvest 真时可达 |
| 10 | extract 首抽 `cli_runner_unavailable(backend="draft_intent")`（`if not correction_block`） | 无（resubmit correction 恒非空） | **删** | 依附 N1 为死路径新增机制；不为死路径留变异证明 |
| 11 | extract try/except 中 `if correction_block: raise` | 有（生产恒走此臂） | **简化为异常原样上抛**（去掉整段 try/except） | 生产行为不变：LLM 失败原样冒泡 |
| 12 | 单旨补交 `resubmit→heal→extract` + `initial_correction` | **有** | **保留** | boundary：现役单旨补交必要承接 |
| 13 | heal 组合校验纠错 / 名册 heal / `UnknownParticipantEscalate` | **有**（经 resubmit） | **保留** | 补交必要模式承接 |
| 14 | 解析失败 / 缺「拟旨意图」/ 非法枚举 → `ValueError` 真因 | **有** | **保留** | N1 真因上抛；boundary 不洗「无」 |
| 15 | 合法「无」→ `draft_action=无` 短路；resubmit 承接「未返回拟旨意图」 | **有** | **保留** | boundary：合法「无」非解析失败 |
| 16 | extract 单旨成功路径（拟旨/push/grant/…/participant_roster 字段） | **有** | **保留** | 现役单旨结构，非后置点将模式 |
| 17 | `require_execution_lead_or_raise`（executor_routing/db） | 有（成案路由） | **保留（非本类）** | 不同 API；勿与 extract kwarg 混淆 |

仅为之存在的测试：全仓 `tests/` 对 `require_execution_lead=` / `harvest_participants=` / `MissingExecutionLeadError` **0 命中** → 无平行死夹具可删。

---

## 复扫（修后）

```text
MissingExecutionLeadError          0
_extract_result_has_execution_lead 0
_missing_execution_lead_feedback   0
_participant_fields_from_draft_obj 0
harvest_participants               0
require_execution_lead= (prod)     0
cli_runner_unavailable(...draft_intent) 0
_lead_gate / require_execution_lead 仅 docstring 清退注记 1 行
```

AST 签名（修后）：

- `extract_draft_intent_with_roster_heal(..., initial_correction='')` — 无 `require_execution_lead`
- `extract_draft_intent(..., db)` — 无 `harvest_participants`

---

## 聚焦测试（七 BIN；未跑全量）

```bash
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-r1-n5/focus \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_decree_dossiers_571.py \
  tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes \
  tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades \
  tests/test_executor_routing_721.py
# → 171 passed in 6.35s（墙钟 ~6.91s）
```

不为 finding 新增平行证明测试；不为死路径保留变异机制。

---

## 结清总表（本轮）

| 类 | 状态 | 依据 |
|---|---|---|
| N5 | **结清**（本轮） | 生产消费谓词全员表 + 复扫 0；lead/harvest/首抽不可达分支已删 |
| N1 依附死分支（首抽 `cli_runner_unavailable`） | **随 N5 清退** | 生产不可达；解析真因上抛与合法「无」保留 |
| N2/N3/N4/N6/N7 | **不重开** | 判词 note |

自查二连 done。
