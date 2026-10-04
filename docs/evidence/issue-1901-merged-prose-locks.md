# #1901 J3 — 合并恢复自由文本测试机械依赖

## 范围与根因

法源：本 run 末份冻结判词 `06-1901-judge-27340d9c3.json`，finding J3；现行 #1901、#1812 正文已用 `gh issue view … --json body` 读取。只处理合并带回的本类，不重开已结清的领域拆搬、诊断格式等类别。

调查起点 `27340d9c3574ef8808125bd9c36f1c8a423b01a9`，比较合并前 `4b9184f0c`、W4 `dd9184891` 与两次 merge `523b28dc3`、`27340d9c3`。根因是合并选择 W4 的测试片段，带回已删的措辞依赖及新并入的同形状测试；不是生产行为需要措辞锁。

谓词：全仓测试及断言辅助代码，对人读日志、stdout、异常消息、prompt、混合材料正文等自由文本的措辞、子串、正则、模板或定位解析建立机械依赖，且由本次合并带回。不限语言、不限文件、不限判词点名符号；原样输入的存读搬运与结构化 ID、枚举、路径、拒收状态不是呈现措辞锁。先枚举所有断言，再核数据来源和合并前等价行为，不用中文筛选或只查冲突文件代替枚举。

## 枚举命令

仓内执行（输出文件是本轮自行创建的系统临时文件，不进入运行机制或测试）：

```sh
git grep -n -E 'assert|raises\(|warns\(|expect\(|\.to(Equal|Be|Contain|Match)|snapshot' -- '*.py' '*.js' '*.jsx' '*.ts' '*.tsx' '*.mjs' '*.cjs' > /tmp/1901-all-assert-sites.txt
git diff --unified=2 4b9184f0c 27340d9c3 -- '*test*.py' '*test*.ts' '*test*.tsx' > /tmp/1901-all-test-delta.diff
git diff --name-only 4b9184f0c 27340d9c3 -- '*test*' '*spec*'
git show --remerge-diff 523b28dc3
git show --remerge-diff 27340d9c3
```

首命令施工前输出 16,332 行候选。另用标准库 AST 无语言/措辞筛选地枚举所有已跟踪 Python 文件的 `assert`、`raises`、`warns`，比较合并前的等价节点（以下脚本可在任意后续 HEAD 复扫；初次结果为 236 文件、13,958 节点、859 个不同节点）。节点不是自动裁判，正文数据来源、重命名前等价断言及调用上下文仍逐项阅读。

```python
import ast
import pathlib
import subprocess

paths = subprocess.check_output(['git', 'ls-files', '-z'], text=True).split('\0')
old = '4b9184f0c'
out = []
counts = [0, 0]
for p in paths:
    if not p.endswith('.py'):
        continue
    s = pathlib.Path(p).read_text()
    try:
        tree = ast.parse(s)
    except SyntaxError:
        continue
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assert) or
             isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
             n.func.attr in {'raises', 'warns'}]
    if not nodes:
        continue
    counts[0] += 1
    counts[1] += len(nodes)
    r = subprocess.run(['git', 'show', f'{old}:{p}'], capture_output=True, text=True)
    try:
        prev = ast.parse(r.stdout)
    except SyntaxError:
        prev = ast.parse('')
    prior = {ast.dump(n, include_attributes=False) for n in ast.walk(prev)
             if isinstance(n, (ast.Assert, ast.Call))}
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for n in sorted(nodes, key=lambda n: n.lineno):
        if ast.dump(n, include_attributes=False) in prior:
            continue
        f = next((f.name for f in funcs if f.lineno <= n.lineno <= f.end_lineno), 'module')
        out.append(f'{p}:{n.lineno}::{f}\n{ast.get_source_segment(s, n)}\n')
pathlib.Path('/tmp/1901-assert-enumeration.txt').write_text('\n'.join(out))
print(counts, len(out))
```

AST 结果全卷读取；Web 新增断言另按完整 diff 及上下文核对，不以 Python AST 覆盖 Web。

## 成员表与处置

行号为施工前，仅辅助定位；函数名与 Git 对比是复核入口。

| 文件 / 函数 | 成员形状 | 处置及保留契约 |
| --- | --- | --- |
| `test_fiscal_levy_effect.py::test_fiscal_levy_skips_bad_settle_shape_without_blocking_other_regions` | 296–329：`expected_log` 参数、日志子串双锁 | 删参数及措辞，只保日志确有记录、其他省应征继续增长；沿用既有 `assert msgs`，不造诊断出口 |
| 同文件 `::test_fiscal_levy_outcome_label_outside_closed_set_aborts` | 748：异常中文 `match` | 删 match，保 SettlementAbort、event_triggers 无行 |
| 同文件 `::test_fiscal_levy_pending_choice_waits_for_event_window` | 805：异常中文 `match` | 删 match，保拒收、未落触发、当期财政及后期合法办理 |
| 同文件 `::test_fiscal_levy_held_petition_is_supplied_to_next_world_segment` | 1566–1577：glob 人读正文再找两个散文子串 | 删整块及仅服务它的 Path 导入；保留推进、不结清、不改应征、held/id 与结构化输入原文搬运 |
| `test_decree_dossiers_571.py::test_manual_directive_capture_rejects_malformed_roster` | 1054、1082：capsys 和 stdout 措辞 | 删 capsys 形参及断言；保真实 CLI review 返回 back、三处无落库 |
| 同文件 `::test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes` | 1117：异常消息 match | 删 match，保 ValueError、三处无落库 |
| `test_pay_order_override_extraction_653.py::test_single_pay_order_capture_rejects_missing_entries` | 74：英文异常 `match="entries"` | 字段名不使异常 prose 成为结构化契约；删 match，保真实入口 ValueError |
| `test_month_translate_1840.py::test_month_translation_receives_person_candidate_identity` | 935–970：prompt 子串、在混合正文里搜索 `[` 再 JSON raw_decode 定位 | 删除整条文本扫描测试及顶层 json 导入；不换形复造。既有 `test_candidate_supply_1893.py::test_translate_request_carries_current_candidate_facts`、`::test_supplied_outcome_labels_match_writer_whitelist` 分别保 request.candidates 和合法标签集合 |

共 8 个函数中的本类成员处置，不限三处样本。只删违规依赖及失效附属物，没有生产改动、新通用件、护栏、平行测试或新诊断机制。

## 保留项依据

- `presented_context` / `emperor_note`：留中测试保留的结构化字段原文与输入对应，验证原始奏疏及玩家批语存读，不解析材料呈现。不能把这类合法搬运证明同正文扫描一起误删。
- 邸报标题、旨文、密令、公开说法、宣告等独立输入原文，在 typed body、archive、request 或 read_material 中的存读搬运：不预测模型台词或锁定生成布局。包括 `test_material_directory_1830`、`test_world_materials_1834`、`test_gazette_author_1862`、`test_public_projection_consistency_1830`、`test_secret_order_monthly_progress_566`、`test_due_review_621`、`test_scene_llm_1836` 等候选。部分只是合并前既有契约的改写，不是恢复违规锁。
- `test_pre_settle_transaction.py` 的 auto_submit boom 和 Web 的 stream-fail：测试主动注入的异常透传，不依赖生产自撰错误措辞；前者合并前已有同等 auto_trigger boom 透传断言。拒绝无前提地按「英文不是本类」排除：entries 已因此纳入修理。
- `origin_ref`、source_id、终态枚举、罪证键、财政配置键、路径集合、按钮/菜单固定 UI、结构化数值：契约输入/结果，不是自由文本措辞依赖；Web 新增固定界面断言不作人物叙事归类。
- `test_intrigue_concealment_1896` 的类型与非裸数字检查不是措辞/模板定位锁；不是本类合并恢复的散文机械依赖。

## 复扫与聚焦验证

复扫同一全仓断言枚举、合并 delta 与上述成员上下文：AST 结果为 `[236, 13950] 846`，8 处函数的违规依赖均已去除；保留项见上表依据。剩余 capsys 形参与注入错误 `dossier close failed` 经 `git show 4b9184f0c:tests/test_decree_dossiers_571.py` 核对均在合并前已有，不属于本轮合并恢复项。`git diff --check` 无输出。代码 diff：4 测试文件，8 行增加 / 80 行删除，增加行仅是既有参数或 raises 的替换。

运行命令：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false python3 -m pytest -q \
 tests/test_fiscal_levy_effect.py::test_fiscal_levy_skips_bad_settle_shape_without_blocking_other_regions \
 tests/test_fiscal_levy_effect.py::test_fiscal_levy_outcome_label_outside_closed_set_aborts \
 tests/test_fiscal_levy_effect.py::test_fiscal_levy_pending_choice_waits_for_event_window \
 tests/test_fiscal_levy_effect.py::test_fiscal_levy_held_petition_is_supplied_to_next_world_segment \
 tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_malformed_roster \
 tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes \
 tests/test_pay_order_override_extraction_653.py::test_single_pay_order_capture_rejects_missing_entries \
 tests/test_candidate_supply_1893.py::test_translate_request_carries_current_candidate_facts \
 tests/test_candidate_supply_1893.py::test_supplied_outcome_labels_match_writer_whitelist
```

结果：`14 passed in 1.31s`。首尝试使用 `python` 返回 `command not found`（127），改用现有 python3 后通过，不改安装或宿主配置。

最小必要成本：复用原负向及结构化测试，只删除措辞锁和一条重复扫描证明，没有新增测试。未跑全量、真实宿主/网络模型或变异证明：末份判词明确不恢复这些要求，本轮不是家族最终待合并状态。未 amend、stash、push 或开 PR。
