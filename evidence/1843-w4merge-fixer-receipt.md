# #1843 W5 R5 F2：合并 `claude/1812-w4` 修内司回执

## 基线（git 实测）

| 项 | 全 SHA | 短 | 说明 |
| --- | --- | --- | --- |
| 本票分支 | — | `ak-roles/issue-1843-w5-r5-f2` | |
| 开工 HEAD（ours / merge^1） | `7eb8a1208fe589959bf5792d0e0981cffa3565cb` | `7eb8a1208` | `ak-roles: fix(#1843) retire dead pending_promulgation_verdicts storage (F2 R9)` |
| 并入底座（theirs / merge^2） | `10e64fbef2857a4603c51394d16cea791b4f44c2` | `10e64fbef` | `claude/1812-w4` tip；`ak-roles: merge #1901 into W4 …` |
| merge-base | `ae4a2a3e6c60afd8a09f03252e692632d8c6bee6` | `ae4a2a3e6` | `git merge-base HEAD^1 HEAD^2` |
| 合并提交 | `ea2489098ea32a1f8805778bd61bcff571bd4ee0` | `ea2489098` | `ak-roles: merge claude/1812-w4 into #1843 preserving F2 retirements` |

约束：merge commit；禁 rebase/amend/squash/stash/push/开 PR；不改席位/宿主/Soul/宪法。
优先：底座已收敛结果 + 本票 F2 退役责任（旧结算/simulator 支持树不复活；措辞锁不恢复）。

## 票面可核指针（`gh issue view` 实测 2026-10-05）

| 票 | URL | 标题（实测） | 与本合并关系 |
| --- | --- | --- | --- |
| #1812 | https://github.com/Akagilnc/ming-salvage-sim/issues/1812 | `[重构总规格] 游戏世界记录与双向中间层` | 总规格；fix-packet 引用「重构验收」真源 |
| #1843 | https://github.com/Akagilnc/ming-salvage-sim/issues/1843 | `[M18 衔接] M1 过月主链：暂存声明按序落账、世界段、批红页、邸报、自动推进` | 本票 |
| #1856 | https://github.com/Akagilnc/ming-salvage-sim/issues/1856 | `[M18 收口] X1 退役旧路与文档同步` | fix-packet：F2 旧结算/simulator 支持树退役职责 |
| #1901 | https://github.com/Akagilnc/ming-salvage-sim/issues/1901 | `[M18 W5] 领域旧大块按职责拆搬并清除平行路径` | 底座军饷迁出 / J3 去措辞锁与形状测 |
| #1838 | https://github.com/Akagilnc/ming-salvage-sim/issues/1838 | `[M18 转译] C1b 召对转译：分段、可闻性、在场进出、御前主角、边事件、公开说法` | 底座二次并入（orphan narration）；证据 `docs/evidence/issue-1901-w4-1838-merge.md` |
| #1471 | https://github.com/Akagilnc/ming-salvage-sim/issues/1471 | `[QA][P4] 国库月度定额 tooltip 漏渲染工程注记…` | `test_qa_e1` 工程词不泄漏侧 |

派单原文：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10878-0d34-732c-9e63-52814d1f1884@fixer/fix-packet.md`。

## Advisor 预检（动手前）

- 工作树干净；冲突清单与 fix-packet 一致
- 无待决产品设计：逐冲突可按「F2 退役 vs 底座 #1901 迁出/去措辞锁」归类
- 阻断项：无（未猜新行为）

## 逐文件处置（双方 last-touch 全 SHA + 票面）

查询：`git log -1 --format='%H|%s' HEAD^1|--path` / `HEAD^2|--path`；`git ls-tree` 判 ABSENT。
「双方 last-touch」= 该侧 tip 可达历史上**最后一次改该路径**的 commit（常为 merge 提交；不以推断回填更早语义 commit）。

| 文件 | 冲突 | ours last-touch | theirs last-touch | 处置 | 理由 / 票面 |
| --- | --- | --- | --- | --- | --- |
| `ming_sim/agents.py` | content | `7a96584abf67d0a4817752dbcde5a36b5835a034` `#1843` F2 R5 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` merge W4→#1901（msg：dump/JSONL） | 保留 `asdict`/`is_dataclass`；不保留未用 `Callable` | 底座 #1901 dump 现役；F2 已退役 stream 用 `Callable`（#1843/#1856） |
| `ming_sim/decree.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `523b28dc3a085e92e5f70e21719cc8c529f907d4`（msg：decree 仅留 live fiscal-levy import） | 仅 `apply_historical_fiscal_rates` | 底座清死导入；#1901 符号迁出后 decree 体无引用 |
| `ming_sim/fiscal_fact_brief.py` | modify/delete | **ABSENT**（删于 `b85cb3f16536aae7ff172fb22a848d12c717771d` `#1843` F2） | `2eceb78c3a79a3830f3e52aee9c3650a3963e505` `#1901` refactor（改 import） | **删除**（ours） | F2 退役旧 simulator 财政盘面投影；底座仅改路径，无生产消费者 |
| `tests/test_army_card_status_1501.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | `army_roster`；去「欠饷严重」措辞锁；`army_needed`→`army_pay` | F2 退役 `army_detail`；#1901 军饷属主 + 去措辞锁 |
| `tests/test_army_display_173.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `192603c5223654519266007e575dcc64c57bfad7` `#1901` J3/J11 | 取底座 payload 键契约侧 | 去 roster/report 措辞锁；保留 `army_pay.army_needed` |
| `tests/test_army_firearms.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | 删 `test_army_public_exits_*` | 底座 J3 删形状/措辞测；且依赖已退役 `army_detail` |
| `tests/test_mutiny_third_strike_318.py` | content | `44f87c4c50d7429d87e068384a041312350156d8` `#1843` | `c399a9dfb9ef29f94295569fa2ee5e62957afb41` `#1901` retire single-value pay path | 底座 `_configure(db)` substrate-only；**不**恢复 `_simulator_*` / 源码形状测 | F2 退役 simulator 助手；#1901 删源码形状测 |
| `tests/test_power_section_rejections.py` | content | `7a96584abf67d0a4817752dbcde5a36b5835a034` `#1843` F2 R5 | `405fe50759d400ce225c2937772b6adf28dc38e1` `#1901` drop wording locks | **不**恢复 `format_power_changes` 测 | F2 已删 formatter |
| `tests/test_section4_rejections.py` | content | `7a96584abf67d0a4817752dbcde5a36b5835a034` `#1843` F2 R5 | `16f3ef3bf5c0fc5a8bfa0b75401793c7b04cbfa7` `#1901` remove prose locks | **不**恢复 `format_region/army_changes` 测 | 同上 |
| `tests/test_secret_order_payoff_1504.py` | content | `7a96584abf67d0a4817752dbcde5a36b5835a034` `#1843` F2 R5 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | 保留底座 settlement/seed_guilt/合同测；**不**导入 `build_secret_covert_effect_briefs` | F2 R5 退役 briefs；底座单元契约现役 |
| `tests/test_llm_channel_config.py` | content | `6a232bee546067809cfb0b44635dcaca72dcac05` `#1843` R6 | `c8215188fd2984b6004a1089d19a86b953e2393b` `#1901` J3/J11 | 删 SSOT 源码形状测；保留 `create_rescript_revise_agent` 头表行为测 | 底座 J3；F2 退役 draft agent |
| `tests/test_rescript_draft_656.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | **整文件取 HEAD（F2）** | 底座仍含 `generate_rescript_draft` 树，不得复活（#1843/#1856） |
| `tests/test_pihong_dossier_1490.py` | content | `7eb8a1208fe589959bf5792d0e0981cffa3565cb` `#1843` R9 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | S10 取 HEAD（`normalize_rescript_layer_a_option`） | 底座侧走已退役 `generate_rescript_draft` |
| `tests/test_pay_order_override_653.py` | content | `7a96584abf67d0a4817752dbcde5a36b5835a034` `#1843` F2 R5 | `523b28dc3a085e92e5f70e21719cc8c529f907d4` | HEAD（无 fact_brief）；hub golden 查 `army_pay`；不恢复 brief/`turn_region_summary` | F2 退役 brief/summary；#1901 军饷迁出 |
| `tests/test_fiscal_substrate_bridge.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `27340d9c3574ef8808125bd9c36f1c8a423b01a9` merge #1838→#1901 | HEAD + 端口座两则现役测；import→`army_pay`；删 legacy/`turn_army_summary` | F2 退役 summary；#1901 去 legacy 单值路 |
| `tests/test_qa_e1_numeric_presentation.py` | content | `819ea33aeec9579d099fbb2596045c3df9d86fea` `#1843` R8 | `192603c5223654519266007e575dcc64c57bfad7` `#1901` J3/J11 | 底座反散文结构 + HEAD #1471 工程词不泄漏 | 不恢复浮点/万两措辞锁；#1471 |

## 退役/措辞锁扫描（解决后）

生产与 tests 中未复活：`fiscal_fact_brief`、`build_secret_covert_effect_briefs`、`create_rescript_draft_agent`/`generate_rescript_draft`、`run_agent_stream_text`、`GameDB.army_detail`、`pending_promulgation_verdicts`、`_simulator_army_dicts`、`format_power/region_changes`、`turn_region/army_summary`。

## 聚焦测试（可复跑准确命令；**本补证回合未重跑**）

实测来源：`evidence/1843-w4merge-fixer-pytest.log` 末行
`542 passed, 2 skipped in 55.80s`（EXIT 0；非全量）。
命令真源：合并会话 transcript
`~/.cursor/projects/Users-akagilnc-WorkSpace-Ming-LLM-1843-w5/agent-transcripts/c50ff53b-f08a-4990-972b-b9eefb40a57f/`
（写入 log 的那次：13 冲突测试文件 + 七 BIN + `-q --tb=line`）。

```sh
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$PY -m pytest \
  tests/test_army_card_status_1501.py \
  tests/test_army_display_173.py \
  tests/test_army_firearms.py \
  tests/test_llm_channel_config.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_power_section_rejections.py \
  tests/test_qa_e1_numeric_presentation.py \
  tests/test_rescript_draft_656.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_section4_rejections.py \
  tests/test_pay_order_override_653.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_fiscal_substrate_bridge.py \
  -q --tb=line
```

结果：**542 passed, 2 skipped in 55.80s**；EXIT 0。非全量。

### 为何测试改动是最低必要成本契约

1. 派单范围=冲突涉及文件的聚焦测，不是全量 suite（#1185 / fix-packet）。
2. 测试侧本意是接缝对齐（属主改径 `army_needed`→`army_pay`、不复活 F2 已删符号）。**事后纠正（#1843 F2-R10-2）**：合并 diff 实际恢复了非契约源码／措辞／内部结构锁及平行案（如 `inspect.getsource` 公式锁、`rescript_draft.md` 措辞锁、fiscal identity／tlog 形状锁）；不得再写「不恢复 #1901 已清措辞/形状锁」——该句与当时合并树不符。处置见本轮 `evidence/1843-f2-r10-fixer-receipt.md`。
3. 删测仅当依赖已退役生产符号或与双方退役意图冲突（如 `army_detail` public-exits、`format_*_changes`、`turn_*_summary`、`generate_rescript_draft` 树）；保留底座现役契约测与 F2 现役改票路径。
4. 七 `MING_SIM_*_BIN=/usr/bin/false` 为派单硬门（防真调模型）；本补证不重跑已绿聚焦。

## 格式清理（本补证提交；不改行为）

`git diff --check HEAD^1 HEAD`（合并提交相对 ours）曾报：

| 路径 | 问题 | 出处（实测） | 处置 |
| --- | --- | --- | --- |
| `docs/evidence/issue-1901-w4-1838-merge.md:36-37` | trailing whitespace | **底座原有**：ours 无此文件；theirs/merged blob 同为 `96417a5a8c8dcdd62cfe07d6c30fe7b583ec20b4`；引入于 `27340d9c3574ef8808125bd9c36f1c8a423b01a9`（#1838→#1901 merge 证据） | 仅剥行尾空白 |
| `tests/test_mutiny_third_strike_318.py` EOF | new blank line at EOF | **合并决议新引入**：`HEAD^1`/`HEAD^2` 均无 `\n\n`，`ea2489098` 有 | 压成单行末尾换行 |
| `tests/test_pay_order_override_653.py` EOF | 同上 | 同上 | 同上 |

## Advisor 终检

- 合并冲突已全部解决于 `ea2489098`；本提交仅文档/格式
- 未 push / 未开 PR / 未 stash / 未改席位配置 / 未 amend / 未 rewrite
- 无新增产品行为
- 剩余问题：无阻断。家族收尾全量 suite 不在本派工范围

## 未能核证项（诚实边界）

1. **未重跑** 55.80s 聚焦测；时长与 542/2 仅核证自既有 `evidence/1843-w4merge-fixer-pytest.log` + 产生该 log 的会话命令，非本回合 wall-clock。
2. 若干 theirs last-touch 为 **merge commit**（如 `523b28dc3`、`27340d9c3`）：可核 `git log`/`git show` 主题与 body，**未**在回执中推断 merge 父辈上更早的「首次语义改动」单 commit（避免推断历史）。
3. commit subject 中的 `#1843`/`#1901`/`#1838` 与 `gh issue view` URL/标题已交叉核证；**未**逐条把 commit 挂到 GitHub timeline/cross-ref 事件（远端未要求）。

## 移交

合并提交 `ea2489098` + 本补证文档/格式提交；证据本文件 + `evidence/1843-w4merge-fixer-pytest.log`。
