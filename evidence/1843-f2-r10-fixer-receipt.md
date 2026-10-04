# #1843 F2-R10 修内司施工回执

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r6-f2`（自 `ak-roles/issue-1843-w5-r5-f2` @ `4d25772ae`）
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-e49f-7a41-a7de-d543dc256654@fixer/fix-packet.md`
判词附件：同目录 `00-…sealed1.json`、`01-…sealed2.json`、`02-1843-judge-4d25772ae.json`
**未结类别依据**：仅 `02-…json` 的 **最后一个 payload**（status=continue；G1 纠正后仍送修 F2-R10-1 / F2-R10-2）

方法：先查 pytest 官方夹具文档 / unused-fixture 生态——结论是删无消费者夹具与失效测，不新增扫描插件或仓库内证明机制。

## 两类完整定义（判词末 payload）

### F2-R10-1｜旧结算／simulator 独占支持及专属测试退役未闭合
- **law**：#1843 退役旧路定义／调用方／专属夹具；#1812 重构验收第 1 项；全局 #12
- **direction**：沿旧消费者追清独占资产、加载绑定、夹具和失效行为测试；保留现役 normalize、revise、prewrite 及共用存储；不补回旧功能、不用裸 SQL 续命

### F2-R10-2｜合并恢复非契约源码／措辞锁、内部结构测试及重复测试
- **law**：全局 #13／#14；复杂度与测试质量法；锚定宪法
- **direction**：删除非契约源码／措辞锁、helper／内部结构案及重复案；复用真实入口→外部结构化结果；保留必要结构化负向；不得另造证明性测试／平行护栏／扫描机制；同步纠正不实交卷说明
- **G1（本 payload 已结，不送修新闸）**：确定性 HUD 负向契约（键集 + 工程词）保留；键集后三个同义字段否定按重复删除

## 枚举命令

见 `evidence/1843-f2-r10-enum-commands.txt`。

## 逐名成员表

见 `evidence/1843-f2-r10-member-table.tsv`（含 DELETE／RETAIN／CORRECT／OUT_OF_CLASS）。

### F2-R10-1 处置摘要

| 成员 | 处置 |
|---|---|
| `rescript_draft_prompt` 字段+load | 删 |
| `content/prompts/rescript_draft.md` | 删 |
| `content/prompts/event_selector.md`（零加载旧 simulator 情势挑选） | 删 |
| `_CANNED` / `_retire_existing_actors` / `_add_character` / `_valid_item` / 悬空 `parametrize(mutate)`+`_legal_item` | 删 |
| `test_submit_event_decision_binds_from_candidate_snapshot_without_event_id` | 删（失效猜绑） |
| `scene_agent_prompt`、`normalize_*`／`rescript_layer_a_prompt_contract`／`_parse_rescript_json_strict`、票拟存储／`save_resolve_context` | **保留** |
| `faction_metrics` | 保留（类外孤儿字段，无本票 F2 删除消费者承接） |

### F2-R10-2 处置摘要

| 成员 | 处置 |
|---|---|
| `test_central_hub_tier_order_and_old_arrears_unchanged_by_haircut`（getsource） | 删 |
| `test_prompt_zero_numeric_instruction_is_positive_qualitative` | 删 |
| `hasattr(RESCRIPT_ROUTABLE/NATIONAL_FANOUT)` | 删；保留 emitted⊂dossier |
| fiscal identity / shadow tlog 格式锁 / mock bridge call_count | 删 |
| HUD 键集后 `note`/`internal`/`budget_key` not-in | 删 |
| HUD `set=={name,amount}` + 工程词钉扫；`preserves_persisted`／`advance_through_fixed_flows` | **保留** |
| `evidence/1843-w4merge-fixer-receipt.md`「不恢复措辞/形状锁」 | **纠正为不实** |

## 复扫（施工后）

- `rescript_draft_prompt`／md／`event_selector.md`：gone
- 死夹具／悬空 parametrize／猜绑测：gone
- `inspect.getsource`：tests 全仓 none
- 措辞锁／identity／shadow_tlog／mock bridge：gone
- 保留：`scene_agent_prompt` getattr 消费；normalize／revise／prewrite／存储；budget 外部契约两测；HUD 键集+词扫
- `GameContent.load` 探针：OK

## 聚焦测试（触及面；非全量；无 --deselect）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --durations=10 \
  tests/test_rescript_draft_656.py \
  tests/test_advance_paths_atomic.py \
  tests/test_pay_order_override_653.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_qa_e1_numeric_presentation.py
```

结果：**280 passed in 18.15s**（wall `real 18.48`）；EXIT 0。日志：`evidence/1843-f2-r10-pytest.log`。

完整聚焦文件列表（5）：
1. `tests/test_rescript_draft_656.py`
2. `tests/test_advance_paths_atomic.py`
3. `tests/test_pay_order_override_653.py`
4. `tests/test_fiscal_substrate_bridge.py`
5. `tests/test_qa_e1_numeric_presentation.py`

## 测试删除的契约与最小必要成本

- 删的是：独占旧资产／失效猜绑／源码公式锁／prompt 措辞锁／内部符号缺席锁／identity-only／tlog 形状锁／mock 内部次数／键集后重复否定。
- 不新造证明测试；结构化负向与真实入口落库契约沿用既有测。
- 变异证据指针沿用判词末 payload `evidence.currentProbes`（c4edb6／79ac2d／9aec5b），本腿不重造证明测。

## 自查二连

- 同类型：复扫确认两类谓词成员已处置或有理由保留；未用引用数／固定种子／整文件 live 白名单收窄。
- 引入 bug：聚焦 280 绿；未 stash／amend／push／开 PR；未改 Soul／宪法；未修活旧功能。

## 剩余问题

- `faction_metrics` 仍为零生产消费者（类外，未动）。
- 家族全量 suite 不在本派工范围。
- 未宣称合并或关票。
