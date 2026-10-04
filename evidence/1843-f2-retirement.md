# #1843 F2 旧结算／simulator 支持树清退回执

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`  
分支：`ak-roles/issue-1843-w5`  
底座：`claude/1812-w4` 是 HEAD 祖先（`git merge-base --is-ancestor claude/1812-w4 HEAD` → yes）  
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107fa-7c79-7613-87d5-0cf4e634cafd@fixer/fix-packet.md`  
判词附件：`.../attachments/00-1856-judge-324c29f16.json`（F2 成立、未结；本票承接整类）

## 轮次

| 轮次 | HEAD（施工前） | 说明 |
|---|---|---|
| R1 | `ae4a2a3e6c60afd8a09f03252e692632d8c6bee6` | 合规合并／读端／候选绑定／财政投影清退 → `b85cb3f16`；回执 stamp → `d3a3688f2` |
| R2（本轮） | `d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e` | 纠正「旧文本流／季提示／军队投影」假阴性；沿错误形状全类 AST 核销 |

## Advisor 前置判断（不冒充庭审）

- 授权：派单「执行派单全部授权 F2 清退」；F1/F3 只列不施工。
- R1 回执「旧文本流调用无成员可删」**不实**：仅枚举 `text_stream`/`call_text_stream`，未覆盖 `run_agent_stream_text` 及专用依赖／测试。
- 手段：受管 Python 线性 AST 索引（定义 + Name/Attribute 引用）→ 消费者矩阵 → `git log -S` 历史交叉；禁止 O(n²) 两两全文件互扫。
- 保留：现役 `run_agent_text`、`_agent_run_accepts_stream`（供前者）、`season_option_fields` / `validate_season_option` / `_season_specs`、`CliChat.response_stream` 现役 CLI 流、材料目录／月链／权限写口。
- 不冒充庭审席结论；本文件是修内司施工回执。

## 完整枚举命令（R2 实际执行）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5
git rev-parse HEAD
git ls-files '*.py' | wc -l   # 受管 Python：358

# 用户复扫（样本入口，非全类证明）
rg -n 'run_agent_stream_text|season.*prompt|simulator_army_dicts|_find_simulator_army' ming_sim tests

# 线性 AST 索引 + 消费者矩阵（全类；一次扫完全部受管 .py）
python3 <<'PY'
import ast, subprocess, re
from pathlib import Path
from collections import defaultdict
files = subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
pat = re.compile(
    r'(run_agent_stream|stream_text|text_stream|call_text_stream|'
    r'season_option_contract|season_simulator|season_.*prompt|'
    r'simulator_army|_find_simulator|army_dicts|'
    r'fiscal_fact|record_stream_metrics|'
    r'compliant_promulgation|execution_side_read|'
    r'bind_decisions_to_candidate|dossier_ids_from_simulator|'
    r'open_affair_ids_from_payload|cli_stream_safe)'
)
defs, refs, all_names = defaultdict(list), defaultdict(list), defaultdict(list)
candidates = set()
for rel in files:
    src = Path(rel).read_text(encoding='utf-8', errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            all_names[node.name].append(f'{rel}:{node.lineno}')
            if pat.search(node.name):
                candidates.add(node.name)
                defs[node.name].append(f'{rel}:{node.lineno}')
for rel in files:
    src = Path(rel).read_text(encoding='utf-8', errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in candidates:
            refs[node.id].append(f'{rel}:{node.lineno}')
        elif isinstance(node, ast.Attribute) and node.attr in candidates:
            refs[node.attr].append(f'{rel}:{node.lineno}')
for name in sorted(candidates):
    dlocs = all_names[name]
    consumers = [r for r in refs[name] if r not in dlocs]
    prod = [c for c in consumers if c.startswith('ming_sim/')]
    tests = [c for c in consumers if c.startswith('tests/')]
    flag = 'ORPHAN' if not prod and not tests else ('TEST-ONLY' if not prod else 'LIVE')
    print(name, flag)
    print('  defs:', dlocs)
    print('  prod:', prod or 'NONE')
    print('  tests:', tests or 'NONE')
PY

# 历史消费者交叉
git log -S'run_agent_stream_text' --oneline -- ming_sim tests | head
git log -S'season_option_contract_prompt' --oneline -- ming_sim tests | head
git log -S'_simulator_army_dicts' --oneline -- tests | head
```

R2 施工前矩阵（摘录）：

| 符号 | 状态 | defs | prod | tests |
|---|---|---|---|---|
| `run_agent_stream_text` | TEST-ONLY | `agents.py:369` | NONE | `test_cli_backend.py` ×3 |
| `record_stream_metrics` | 仅被上一符号调用 | `token_stats.py:89` | `agents.py:495` | NONE |
| `season_option_contract_prompt` | ORPHAN | `action_clusters.py:185` | NONE | NONE |
| `_simulator_army_dicts` | ORPHAN | 两测试文件 | NONE | NONE |
| `_find_simulator_army` | ORPHAN | `test_mutiny_third_strike_318.py:28` | NONE | NONE |
| `season_option_fields` / `validate_season_option` | LIVE | action_clusters | settlement_payload / rescript_actions | — |
| `run_agent_text` | LIVE | agents | month_chain 等 | — |
| `_cli_stream_safe_prefix` 等 | ORPHAN | cli_backend | NONE | NONE → **F1 边界，本单不施工** |

历史交叉：

| 提交 | 说明 |
|---|---|
| `7b3c94aa1` | 撤 `simulate_season_with_payload` 对 `run_agent_stream_text` 的生产调用 |
| `5047271cf` / `1c2b68ba7` | 撤 `season_option_contract_prompt` 生产调用（季 simulator agent 供料） |
| `5047271cf` / `fcd177234` | `_simulator_army_dicts` 随盘面投影退役失去消费者 |
| `c90a43a1b` / `53c83c3eb` | R1 已核：载荷辅助／候选绑定历史消费者 |

## 成员表（R2 处置）

| 文件/符号 | 消费者（施工前） | 历史证据 | 删除/保留理由 |
|---|---|---|---|
| `ming_sim/agents.py::run_agent_stream_text` | 仅测试 | `7b3c94aa1` 撤季入口生产调用 | **删**（旧文本流专用；非现役 `run_agent_text`） |
| `ming_sim/agents.py::_THINKING_STREAM_CHAR_LIMIT` | 仅上一符号 | 流式思考截断专用 | **删** |
| `ming_sim/token_stats.py::record_stream_metrics` | 仅上一符号 | docstring 自承为 stream_text 补记 | **删**；保留 `_record_usage`／`tlog` |
| `ming_sim/action_clusters.py::season_option_contract_prompt` | 无 | `5047271cf` 撤生产调用 | **删**；**保留** `season_option_fields`／`validate_season_option` |
| `tests/test_cli_backend.py` 三案钉 stream_text | 死路径 | tag=`simulator`／专用 API 流钉 | **删**三案；**保留** `CliChat.response_stream` 案 |
| `tests/test_mutiny_*::_simulator_army_dicts` / `_find_simulator_army` | 无引用 | 旧盘面军队投影助手 | **删**助手；**保留**调防／哗变业务案 |
| R1 已删合规／读端／绑定／财政投影 | — | 见 R1 表 | 复扫 defs/refs=NONE |
| `_cli_prompt`／`_cli_stream_safe_prefix`／`_cli_recommendation_call` | 无 | F1 CLI 荐人信封类 | **不施工**（非本票 F2） |
| F3：`find_prior_speaker_still_present` 等 | 无 | 旁白／单场类 | **不施工** |

### 纠正 R1 不实结论

- ~~「旧文本流调用……无成员可删」~~ → 假阴性。真成员：`run_agent_stream_text` + `record_stream_metrics` + `_THINKING_STREAM_CHAR_LIMIT` + 三专用测试。
- 「季模拟器提示已无文件可删」→ `content/prompts/season_simulator.md` 确已不存在；但 **`season_option_contract_prompt` 代码残留** 仍属同类，本轮已删。

## 原类复扫（R2 施工后）

同 AST 脚本：`run_agent_stream_text`／`season_option_contract_prompt`／`_simulator_army_dicts`／`_find_simulator_army`／`record_stream_metrics` → `defs=NONE`、`refs=NONE`。  
`rg -n 'run_agent_stream_text|season_option_contract_prompt|_simulator_army_dicts|_find_simulator_army|record_stream_metrics|text_stream|call_text_stream' ming_sim tests -g'*.py'` → 无命中。  
现役保留：`run_agent_text`、`season_option_fields`、`validate_season_option` 生产引用仍在。

## 非本票承接／本轮不施工成员

### F1（#1856 已结类或边界残留，本单不施工）
- `_cli_prompt`／`_cli_stream_safe_prefix`／`_cli_recommendation_call`（cli_backend 荐人信封；判词 F1 历史点名）

### F3（原召对／旁白切片，本单不施工）
- `ming_sim/audience_night.py::find_prior_speaker_still_present`
- `ming_sim/cli/terminal.py::_fail_cli_chat_turn_scene`
- `ming_sim/due_review.py::current_audience_scene`

### 其它边界
- 治理文件 / Soul / 宿主配置：未改。
- `docs/raw` 冻结 simulator 素材：不删。
- `docs/结算流程_代码地图.md` 等历史叙述：非生产代码，不施工。
- 现役权限名单、材料目录、业务写口、`CliChat.response_stream`：保留。

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
  tests/test_cli_backend.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_run_agent_text_transport_1465.py \
  tests/test_month_chain_1843.py \
  tests/test_rescript_choices_563.py \
  -q -p no:cacheprovider --durations=8
```

实测结果：`171 passed in 3.83s`。  
未跑全量 suite（派单禁止）。

## 自查质量／合法性（advisor，非审官）

- 同类型：沿「旧结算／simulator 专用支持」错误形状全类索引，非只修用户点名四符号；专用依赖（metrics／thinking limit／专用测试）一并核销。
- 引入 bug：未改现役 `run_agent_text` transport；未撤 `season_option_fields`／`validate_season_option`；未复活季入口。
- 合法性：仅 F2；未改治理/Soul/宿主；未 amend/stash/push/PR；未杀 worker；F1/F3 只列。
- 复杂度：本轮净删专用定义与死测，无新机制、无证明性测试。
- **不冒称** #1856 总核收敛或庭审结清。

## Commit 与 git 状态

R1 清退：`b85cb3f16536aae7ff172fb22a848d12c717771d`  
R1 stamp：`d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e`  
R2 清退 commit：（本文件随 R2 独立 `ak-roles:` commit 写入后回填 hash）

## 剩余范围

- F3 旁白／单场选择孤立支持：仍待原负责票。
- F1 边界 CLI 信封三符号：仍 ORPHAN，归属非本票。
- #1856 总核验：本回执不冒称总核收敛。
- 全量 CI / Web 构建：留最终待合并状态。
