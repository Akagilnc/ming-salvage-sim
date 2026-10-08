# #1830 删测越界修正回执

本轮基线 `dd7ff6dc7`，仍在 `ak-roles/issue-1830-w4merge`。接受续审两项 finding，不把“出现文本断言”当作删测授权。身份增补 append 已成立，本轮不改 `materials.py`，不重跑该类变异。

## 一致类界

搜索域与施工域不是一回事。#1830 的对象是本票公开读侧及直接相关测试中，以正文／展示推断记录身份、权限、完整性、底账裁切的证明。独立军备呈现、金额近似、火器炮门数值／定性两态、原字段搬运，不能仅因使用字符串而整条删除。必要负向准入也不能删掉后以别的界面的测试冒充覆盖。

本轮全扫前次 diff 中删去的测试函数及断言，核其所保护的行为，再沿共享 helper 核调用者；不是只恢复判词点名行。军备的字段披露／近似呈现，与公开记录依正文判来源是不同契约。173 与 321 因同属前者，使用同一把尺保留，不再一删一留。

```sh
git diff 88d114e21 dd7ff6dc7 -- tests
git diff 88d114e21 dd7ff6dc7 -- tests | grep -E '^[-+]def test_|^diff --git'
git grep -n -E '_approx_wanliang|_expected_army_card_from_row|_assert_chain_embeds_situation|header_army_sentinel|12\.5|province_pay_arrears|central_pay_arrears' -- tests
git grep -n -E 'choose_minister|can_summon|visible_in_court' -- tests/test_web_court_visibility.py
git grep -n -E 'minister_dossier|featured_dossier' -- ming_sim/materials.py ming_sim/knowledge.py
```

最后一项无命中：前次把旧 context 的独立 featured dossier 测试也当作本票材料目录测试删掉，同样超出本票读侧。已一并恢复，不把全仓候选当成施工白名单。

## 成员与实际处置

| 成员 | 本轮处置与覆盖 |
| --- | --- |
| `test_army_firearms.py::test_army_public_exits_surface_firearm_and_cannon` | 原样恢复整条：detail、report、roster 数值／定性两态与新建军营出口，均执行；不以仅检查 armies DB 行冒充出口覆盖。 |
| `test_army_display_173.py::test_army_arrears_presentation_rounds_half_steps_up` | 恢复既有测试，直接调用 `_approx_wanliang`，独立预期保护 12.5→15、15→15、12→10、25→30、30→30；不再用 renderer 输出回验同 renderer。没有新增平行用例。 |
| 同文件 `test_army_payload_exposes_approx_arrears_text_not_raw` | 恢复 army_payload 的真实结构化字段出口及 raw arrears 缺席契约。 |
| 同文件 `test_army_public_exits_approx_arrears_and_hide_split_accounts` | 恢复 report 目标军段，与 detail／roster 一起核对近似与分账字段隐藏；原 bare-number 负向保留，与 321 一致。 |
| `test_army_card_status_1501.py::_expected_army_card_from_row` 及 `test_army_payload_omits_static_status_exposes_arrears_text` | 恢复逐字段对照、完整契约键集、status/raw 字段缺席、seed status 不混入任何卡面字段、关宁欠饷输出；对照 helper 仅取 DB 搬运字段和现有 `army_needed`，不复制 `_player_army_situation` 的三派生字段。三派生字段的装配值仍由既有 321 链测试核对，此处保留其类型／键集。删除旧 status 兼容中间字典。 |
| 同文件 `test_army_report_keeps_row_status`、`test_shared_consumers_still_surface_status` | 恢复欠饷文案、军报／详情／名册的原 status 搬运，以及 military 和人物材料不携 seed status 的军备读者呈现契约。 |
| `test_web_court_visibility.py::test_choose_minister_real_entry_excludes_weishi_includes_court` | 恢复 CLI 真入口，但不再搜索 printed blob。输入先史可法、后温体仁，断言返回的是温体仁 Character 对象；两人在 DB 强制 active、在京、无在途，避免用“异地不能即刻入殿”偶然掩盖未仕资格失败。真实资格／地点闸未 mock。此项证明 CLI 不接受未仕且接受真臣，不冒称验证了菜单打印措辞。 |
| `test_featured_dossiers_494.py` 三个既有测试及 helper | 原样恢复完整文件。属于旧 context 的独立 featured dossier／人格呈现契约，不能以与本票源记录裁切无关的字面“身份”归入 #1830 后整条删除。 |
| `test_player_army_projection_321.py::_assert_chain_embeds_situation`、`_assert_structured_situation` 与 print_header 负向 | 原样保留并执行。前两者保护军备三派生字段的跨出口装配／raw 字段隐藏，header 负向保护 header 不回流 army_report；不是以 prose 判断公开记录来源。与恢复后的 173、1501 用同一依据，不宣称这里的字符串负向已删除。 |

前次 diff 的整条删除包括 173 两条、firearms 一条、CLI 一条、featured dossier 三条；现已全部恢复。前次月报测试改名不是删除整条：其原文搬运仍保留，其正文权限证明与本轮独立军备契约不同。其他已获有效修复的源 ID／ledger ID 断言不倒退。

## 更正声明

`evidence/1830-w4merge-fixer-class-followup.md` 中“无独立契约价值…直接删除”、成员全部处置及 CLI 覆盖的说明，对上述独立契约不成立；该回执省略 321 而把 173 相同形状判成失效，亦不成立。以本回执逐项更正，旧提交／旧回执保留，不改历史，不再用“文本断言”解释越界删除。前次测试绿灯没有证明被删契约仍受保护。

## 聚焦验证

所有本轮 pytest／变异进程均前缀七个 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`，并用 `PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`。Python 为 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short tests/test_army_card_status_1501.py tests/test_army_display_173.py tests/test_army_firearms.py tests/test_web_court_visibility.py tests/test_featured_dossiers_494.py tests/test_player_army_projection_321.py
```

最终 **76 passed、1 skipped，1.67s**。skip 是原有 seed 军饷排序前提。只跑本轮六文件，不跑全量，不调用真实模型。AST 解析及 diff whitespace 检查通过；没有独立 Python 静态 typecheck 工具，不冒称已运行。

复用上述两个既有测试做临时变异（`/tmp/1830-scope-probe.py`，仅独立进程内替换，不改工作树）：

- rounding mutant：把 `_round_half_up_to_step` 换成 `int(round(value / step) * step)`。既有 `_approx_wanliang` 测试报红：12.5 输出 10 而非 15，1 failed，0.57s；恢复后 1 passed，0.54s。这是所恢复独立舍入契约的变异验证，不冒称装回了本票 INDEX 旧逻辑。
- CLI mutant：把 session／terminal 的 `_is_summonable_court_minister` 换成原在册身份谓词 `_is_ming_court_minister_character`，取消未仕可召资格限制。真实 choose_minister 返回史可法，结构化对象断言红：1 failed，0.26s；恢复后返回温体仁，1 passed，0.24s。两次有 pytest 预导入 anyio 的 rewrite warning，不是被测失败原因。

命令模式为带上述七旗、`PYTHONPATH=$PWD` 的同一 Python 执行 ` /tmp/1830-scope-probe.py rounding mutant/current` 或 `cli mutant/current`；脚本每次调用 pytest 现有具名测试，未新增永久证明性测试或夹具。

## 交卷

本轮只恢复／修正越界测试及另写此回执；生产 append 与先前有效来源修复不动。`git diff --cached --numstat`：6 文件，+322/-6；其中测试 +262/-6，回执 +60/-0，生产零改动。独立 forward commit，不 amend／stash／push／开 PR；复审收敛前仍不得并入家族底座。不宣告整票或家族已收敛。
