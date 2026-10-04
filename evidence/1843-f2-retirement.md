# #1843 F2 旧结算／simulator 支持树清退回执

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`  
分支：`ak-roles/issue-1843-w5`  
底座：`claude/1812-w4` 是 HEAD 祖先（`git merge-base --is-ancestor claude/1812-w4 HEAD` → yes）  
施工前 HEAD：`ae4a2a3e6c60afd8a09f03252e692632d8c6bee6`  
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107fa-7c79-7613-87d5-0cf4e634cafd@fixer/fix-packet.md`  
判词附件：`.../attachments/00-1856-judge-324c29f16.json`（F2 成立、未结；本票承接整类）

## Advisor 前置判断（施工前）

- 授权：派单「执行派单全部授权 F2 清退」；F1/F3 只列不施工。
- 手段：互联网检索（Vulture README / dead-code sweep 实践 / StackOverflow 删除死码共识）确认简单手段=核对引用后直接删除，不造兼容 shim。本轮**仅删除、不造机制**。
- 根因类：旧结算后半／simulator 盘面供料退役后，专用合规合并、执行侧读端、候选绑定、财政盘面投影及只为旧路存在的测试仍残留。
- 保留：`_is_stalled_deliberation`、颁布校验、`project_applicable_authorities`、材料目录/`gather_candidate_events`、`open_affairs`/`transit_arrivals` 载荷写口、`decision_has_rescript_capability`、现役 `run_agent_text`。
- 不冒充庭审席结论；本文件是修内司施工回执。

## 完整枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5
git rev-parse HEAD
git branch --show-current
git merge-base --is-ancestor claude/1812-w4 HEAD
git ls-files '*.py' | wc -l   # 施工前受管 Python：360

python3 <<'PY'
import ast, subprocess
from pathlib import Path
from collections import defaultdict
root = Path('.')
files = subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
symbols = [
    '_collect_compliant_promulgation_items',
    '_merge_compliant_promulgation_items',
    '_promulgable_proposed_dossiers',
    'execution_side_read_fields',
    'resolve_executor_appointment_tenure',
    '_dossier_ids_from_simulator_payload',
    '_open_affair_ids_from_payload',
    'bind_decisions_to_candidate_events',
    'build_fiscal_fact_brief',
    'format_fiscal_fact_brief_tsv',
]
defs, refs = defaultdict(list), defaultdict(list)
for rel in files:
    src = Path(rel).read_text(encoding='utf-8', errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in symbols:
                defs[node.name].append(f'{rel}:{node.lineno}')
        if isinstance(node, ast.Name) and node.id in symbols:
            refs[node.id].append(f'{rel}:{node.lineno}')
        if isinstance(node, ast.Attribute) and node.attr in symbols:
            refs[node.attr].append(f'{rel}:{node.lineno}')
for s in symbols:
    d = defs[s]
    consumers = [x for x in refs[s] if x not in d]
    print(s)
    print('  defs:', d or 'NONE')
    print('  prod:', [c for c in consumers if c.startswith('ming_sim/')] or 'NONE')
    print('  tests:', [c for c in consumers if c.startswith('tests/')] or 'NONE')
PY
```

历史消费者交叉验证（`git log -S` / 判词点名提交）：

| 提交 | 说明 |
|---|---|
| `c90a43a1b` | 撤 `_dossier_ids_from_simulator_payload` 消费者（旧恢复落账） |
| `5047271cf` | 撤 `execution_side_read_fields` 生产消费者（旧 simulator 投影） |
| `53c83c3eb` | 撤旧 `candidate_events` 生产者 |
| `9d854eec3` / `7b3c94aa1` | 已在本底座祖先内：季入口／部分盘面投影退役；本轮清其残留支持 |

互联网结论摘要：删除未引用私有 helper／孤儿测试；不留兼容包装；静态枚举须交叉历史消费者与动态入口（本仓另核 `prepare_resolve` 载荷仅 `transit_arrivals`/`open_affairs`）。官方参考：[Python `ast`](https://docs.python.org/3/library/ast.html)、[Vulture](https://github.com/jendrikseipp/vulture)。

## 成员表（施工前 → 处置）

| 文件/符号 | 消费者（施工前） | 历史证据 | 删除/保留理由 |
|---|---|---|---|
| `ming_sim/decree.py::_collect_compliant_promulgation_items` | 无 | 旧颁布 heal 链；生产消费者已随月链退役 | **删**（专用合规收集） |
| `ming_sim/decree.py::_merge_compliant_promulgation_items` | 无 | 同上 | **删** |
| `ming_sim/decree.py::_promulgable_proposed_dossiers` | 无 | 包装 stalled 过滤；现役直接调 `_is_stalled_deliberation` | **删**包装；保留 `_is_stalled_deliberation` |
| `ming_sim/decree.py::execution_side_read_fields` | 仅测试 | `5047271cf` 撤生产读端 | **删** |
| `ming_sim/decree.py::resolve_executor_appointment_tenure` | 仅被上一符号调用 | 随执行侧读端 orphan | **删**（非现役写口） |
| `ming_sim/decree.py::_dossier_ids_from_simulator_payload` | 无 | `c90a43a1b` | **删** |
| `ming_sim/decree.py::_open_affair_ids_from_payload` | 无 | 旧载荷 ID 抽取；`open_affairs` 写口仍由月链保留 | **删**辅助；**保留**载荷写口 |
| `ming_sim/settlement_payload.py::bind_decisions_to_candidate_events` | `session.py` 转递 + 专用测试 | `53c83c3eb` 后绑定恒 noop | **删**定义与转递 |
| `ming_sim/session.py` 候选绑定块 | 调用上一符号 | 探针 `candidate_events_present=false` | **删**转递 |
| `ming_sim/decree.py` re-export `bind_decisions_to_candidate_events` | 仅 import | 无 body 使用 | **删** import；保留 `parse_decision_blocks`/`bind_decision_options` |
| `ming_sim/fiscal_fact_brief.py` 整模块 | 无生产消费者；仅测试 | 旧 simulator 财政盘面投影 | **删**模块 |
| `tests/test_decision_event_binding_389.py` | 整文件测 binder | 只为旧路 | **删**文件 |
| `tests/test_execution_tenure_613.py` 经 `execution_side_read_fields` 的装配案 | 死读端 | 同上 | **删**装配案；**保留**号令力纯函数案 |
| `tests/test_secret_dossier_participants_1252.py` 尾断言 | 读死读端 | 业务仍要验授权投影 | **改**为 `db.project_applicable_authorities`（现役写口） |
| `tests/test_pihong_dossier_1490.py::test_bind_*` | 直调 binder | 只为旧路 | **删**两案 |
| `tests/test_pay_order_override_653.py` 中 fact_brief 专用案 | 投影模块 | 只为旧投影 | **删** 20 案；`apply_score`/`claim_flow` 去掉 brief 观测、保留 DB/region_logs |
| `tests/test_mutiny_actual_residence_659.py` brief 段 | 投影模块 | 调防 DB 断言已够 | **删** brief 段 |
| `tests/test_llm_channel_config.py` `season_simulator_prompt=` | fake_ctx 死字段 | 季提示/`content` 已无该字段 | **删**字段 |
| `_is_stalled_deliberation` / `validate_promulgation_verdicts` / `_validate_promulgation_verdict_item` | `month_chain` / 颁布链 | 现役 | **保留** |
| `decision_has_rescript_capability` | `rescript_actions` | 现役批红识别 | **保留** |
| `gather_candidate_events` / `_world_candidate_events` / materials 目录 | 月链／材料 | 现役 | **保留** |
| `docs/raw/**/simulator*` | 冻结素材 | 判词：不作生产残留删除 | **保留（不施工）** |
| 旧季模拟器提示 `content/prompts/season_simulator.md` | 已不存在 | `7b3c94aa1` 等已清 | 枚举确认已退役；本轮无文件可删 |
| 「旧文本流调用」专用 stub | 生产无 `text_stream`/`call_text_stream`；`run_agent_text` 现役 | 全仓 rg | **无成员可删**；记入「已清／非死码」 |

## 原类复扫（施工后）

同枚举脚本对上表删除符号：`defs=NONE`、`refs=NONE`；`ming_sim/fiscal_fact_brief.py` 与 `tests/test_decision_event_binding_389.py` 不存在。  
`rg -n 'execution_side_read_fields|bind_decisions_to_candidate_events|build_fiscal_fact_brief|...' -g'*.py'` → 无命中。

## 非本票承接／本轮不施工成员

### F1（#1856 已结类，本单不施工）
- 旧单人材料／`audience_scene_recap`／`minister_speaker_role`／CLI 荐人信封等（判词 F1 disposition：已结）。

### F3（原召对／旁白切片，本单不施工）
- `ming_sim/audience_night.py::find_prior_speaker_still_present`
- `ming_sim/cli/terminal.py::_fail_cli_chat_turn_scene`
- `ming_sim/due_review.py::current_audience_scene`

### 其它边界
- 治理文件 / Soul / 宿主配置 / 席位：未改。
- `docs/raw` 冻结 simulator 素材：不删。
- 现役权限名单、材料目录、业务写口：见上表保留行。

## 聚焦测试

环境前缀（七个 BIN）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_execution_tenure_613.py \
  tests/test_secret_dossier_participants_1252.py \
  tests/test_pay_order_override_653.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_llm_channel_config.py \
  tests/test_month_chain_1843.py \
  tests/test_rescript_choices_563.py \
  -q -p no:cacheprovider --durations=8
```

实测结果：`235 passed in 34.10s`（`/usr/bin/time -p`：`real 34.75` `user 25.53` `sys 8.45`）。  
未跑全量 suite（派单禁止）。

## 自查质量／合法性

- 同类型：整类按共同根因删除，非逐实例补丁；样本外成员（财政投影、无消费者 payload 辅助、季 prompt 死字段）一并核销。
- 引入 bug：未复活 `candidate_events` 生产者；未新增证明性测试；密令参与人案改挂现役 `project_applicable_authorities`。
- 合法性：仅 F2；未改治理/Soul/宿主；未 amend/stash/push/PR；未动他人产物。
- 复杂度：净删约 1592 行，无新机制。

## Commit 与 git 状态

施工前 HEAD：`ae4a2a3e6c60afd8a09f03252e692632d8c6bee6`  
清退 commit：`b85cb3f16536aae7ff172fb22a848d12c717771d`  
标题：`ak-roles: fix(#1843) retire obsolete settlement/simulator support tree (F2)`  
该 commit diffstat：`13 files changed, 212 insertions(+), 1592 deletions(-)`（含本回执初版）。  
本文件补录 stamp 为后续独立 commit（禁止 amend）。

补录时 `git status --porcelain=v1 --untracked-files=all`：仅本 evidence 文件修改。

## 剩余范围

- F3 旁白／单场选择孤立支持：仍待原负责票。
- #1856 总核验：本回执不冒称总核收敛。
- 全量 CI / Web 构建：留最终待合并状态。
- Owner 开局体验与家族复杂度判断：不在本单。
