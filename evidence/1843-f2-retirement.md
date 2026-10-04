# #1843 F2 旧结算／simulator 支持树清退回执

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5`
底座：`claude/1812-w4` 是 HEAD 祖先（`git merge-base --is-ancestor claude/1812-w4 HEAD` → yes）
派单：`~/.ak-roles/books/Ming_LLM/1843/runs/01a107fa-7c79-7613-87d5-0cf4e634cafd@fixer/fix-packet.md`
判词附件：`.../attachments/00-1856-judge-324c29f16.json`（F2 成立、未结；本票承接整类）
重交原文：`evidence/1843-returned-finding.json`（用户封驳：枚举未穷尽；本轮按其 requiredAction 执行）

## 轮次

| 轮次 | HEAD（施工前） | 说明 |
|---|---|---|
| R1 | `ae4a2a3e6c60afd8a09f03252e692632d8c6bee6` | 合规合并／读端／候选绑定／财政投影清退 → `b85cb3f16`；回执 stamp → `d3a3688f2` |
| R2 | `d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e` | 纠正「旧文本流／季提示／军队投影」假阴性；沿错误形状全类 AST 核销 → `44f87c4c5`；stamp → `641201cde` |
| R3 | `9d4152542c226bc890dd5d231fdacc947d4381c2` | 封驳后：禁止名字 regex 预筛；全 ming_sim 定义 ≤1 引用穷尽枚举 + 历史交叉 + 递归固定点 |

## Advisor 前置判断（R3；不冒充庭审）

- 授权：派单 F2 全类；重交 requiredAction 要求完整「全仓引用数≤1」枚举（含 tests，排除 docs/raw），逐成员追历史消费者；属 F2 删（含专用测试）；不属列例外。
- R1/R2 失败经过（必须保留）：
  - R1：固定符号列表／轻量枚举 → 漏掉大量零引用旧支持；曾误判「旧文本流无成员可删」。
  - R2：虽改线性 AST，但仍用名字 regex 预筛选候选（run_agent_stream|season_.* 等），只覆盖已发现错误形状 → 再次假阴性；historical_anchor_for_month 等全仓零引用未进成员表。
- R3 手段：禁止名字 regex 预筛。对全部 ming_sim/**/*.py 的 FunctionDef/AsyncFunctionDef/ClassDef 做定义索引；在全部受管 *.py（git ls-files，排除 docs/raw/）上统计 Name + Attribute + Import 别名引用；消费者为空者入成员表；再 git log -S 逐个核。删除后复扫至固定点（本轮级联：format_metric_delta／first_character）。
- F1 三符号（_cli_prompt／_cli_stream_safe_prefix／_cli_recommendation_call）与 F3 三符号（find_prior_speaker_still_present／_fail_cli_chat_turn_scene／current_audience_scene）不施工。
- 用户点名核对：compose_decree_validation_recovery／compose_secret_order_landing_recovery → 历史消费者为 #1871 分类器落地链（F1 邻接，例外）；night_dossiers_ready → #1842 收夜背书批（F3／召对邻接，例外）。
- 保留：现役共用权限、名单、材料目录、业务写口；不增机制、不复活旧链、不造证明性测试、不改治理/Soul。

## 完整枚举命令（R3 实际执行）

见本文件「R3 枚举脚本」小节；施工前 managed_py=352，ORPHAN=76（计 Import 后）；施工后 ORPHAN≈60 全入例外。

### R3 枚举脚本

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5
git rev-parse HEAD
# managed_py via: git ls-files '*.py' | grep -v '^docs/raw/' | wc -l  → 352

python3 <<'PY'
import ast, subprocess
from pathlib import Path
from collections import defaultdict
files = [f for f in subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
         if not f.startswith('docs/raw/')]
defs, refs = defaultdict(list), defaultdict(list)
for rel in files:
    src = Path(rel).read_text(encoding='utf-8', errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if rel.startswith('ming_sim/') and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            defs[node.name].append(f'{rel}:{node.lineno}')
for rel in files:
    src = Path(rel).read_text(encoding='utf-8', errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs[node.id].append(f'{rel}:{node.lineno}')
        elif isinstance(node, ast.Attribute):
            refs[node.attr].append(f'{rel}:{node.lineno}')
        elif isinstance(node, ast.alias):
            n = node.asname or node.name.split('.')[-1]
            refs[n].append(f'{rel}:{getattr(node, "lineno", 0) or 0}')
print('managed_py', len(files))
print('ming_sim_def_names', len(defs))
orphans = []
for name, dlocs in sorted(defs.items()):
    consumers = [r for r in refs.get(name, []) if r not in set(dlocs)]
    if not consumers:
        orphans.append(name)
        print(name, dlocs)
print('ORPHAN', len(orphans))
PY

# 历史交叉（每个 ORPHAN）：
# git log -S'<symbol>' --oneline -- ming_sim tests | head
```

对 ming_sim 全部定义做 defs 索引；对 git ls-files *.py（排除 docs/raw）统计 Name/Attribute/Import alias；consumers 为空即 ORPHAN；再对每个 ORPHAN 执行 git log -S。

## 成员表（R3 处置：F2 删除）

| 文件/符号 | 历史消费者／退役提交 | 归类 | 处置及理由 |
|---|---|---|---|
| context.historical_anchor_for_month | 53c83c3eb／5047271cf 撤 simulator 盘面 historical_anchor | F2 | 删 |
| context.state_context | 34e5c181b 撤 board query tools | F2 | 删 |
| context.event_context / first_character_name / first_character / parse_json_dict | 自首发 de0d7ad41 起无仓内消费者；旧事件回合 LLM 上下文 | F2 | 删（finding 点名） |
| context.format_metric_delta | 仅被已删 period-report 链消费；固定点级联 | F2 级联 | 删 |
| report.build_period_report / status_delta / status_delta_from_delta / metric_delta | 旧月末总结奏章；无现役／测试消费者 | F2 | 删 |
| covert_progress.parse_covert_exec_selections | 242837870 #1843 删旧结算核 | F2 | 删 |
| covert_progress.contract_axes_direction | d4362928d 撤 simulation／covert fidelity | F2 | 删 |
| value_matrix.mean_aligned_stance | 同上 | F2 | 删 |
| qualitative.disaster_severity_band + DISASTER_SEVERITY_BANDS | 9d854eec3 #1861 simulator board | F2 | 删 |
| db.append_rescript_drafts | ff63db72b #1846 ready=1 重放追加 | F2 | 删（保留 save_rescript_drafts） |
| db.turn_economy_summary / turn_power_summary | 242837870 旧 previous_turn_summary 盘面 | F2 | 删 |
| db.treasury_ledger | 34e5c181b board query tools | F2 | 删 |
| db.list_recent_issue_advances | 53c83c3eb simulator issue 盘面 | F2 | 删 |

## 成员表（R3 例外：不施工）

| 符号 | 历史 tip | 归类 | 保留理由 |
|---|---|---|---|
| _cli_prompt／_cli_stream_safe_prefix／_cli_recommendation_call | dd8c0f072 | F1 | 已判归属；不施工 |
| find_prior_speaker_still_present／_fail_cli_chat_turn_scene／current_audience_scene | #1838／旁白／单场 | F3 | 已判归属；不施工 |
| compose_decree_validation_recovery／compose_secret_order_landing_recovery | e2fc6369d／82be2f178 #1871 | F1 邻接 | 确认归类；非 F2 |
| night_dossiers_ready | 4508956e5 #1842 | F3／召对邻接 | 确认归类；非 F2 |
| minister_speaker_role／cluster_effect／_target_active_officeholder／stage_referral_candidate／stage_revoke_authority_candidate | #1871 | F1 邻接 | 非本票 F2 |
| _matched_prefix／_secret_prefix_needs_recent_context | CLI dispatcher 退役 | F1 邻接 | 非本票 F2 |
| _province_collection_rate／_province_transport_ratio | 7b4e5f734 选妃 stub | 例外 | 非结算／simulator |
| _fiscal_container_value | fiscal hub | 例外 | 财政基座 helper |
| faction_report | setattr 字符串钉权限 | 例外 | 知识权限边界仍钉 |
| building_detail／record_economy_moves／多数 db.list_*／affair pointers／materials 协议 | 各异 | 例外 | 无证 F2 或业务候存 |
| ainvoke／ainvoke_stream／__enter__／__exit__／__call__／__post_init__／MaterialsRoot／holder_kind | 协议 | 例外 | 动态调用 |
| ChatResult／require_*／dict_of_strings*／qualitative_character_attribute 等 | 无旧结算证据 | 例外 | 无引用≠自动 F2 |
| run_audience_turn_translation 等 | #1842 | 例外 | 召对邻接 |

## 原类复扫（R3 固定点）

F2 删除符号 defs/refs=NONE；级联 format_metric_delta／first_character 亦清；剩余 ORPHAN≈60 全入例外。

## 聚焦测试（R3）

七个 MING_SIM_*_BIN=/usr/bin/false 前缀；触及面 pytest（value_matrix／secret_order／covert／month_chain／report 消费者／rescript／section／knowledge／pay_order）。

实测：422 passed, 1 skipped in 11.71s（real 12.83）。未跑全量。

## 自查质量／合法性（advisor，非审官）

同类型清退旧结算／simulator／board／ready-delta；未动现役写口；仅 F2；F1/F3 只归类；未 amend/stash/push/PR；不冒称 #1856 总核收敛。

## 剩余范围

F1／F3／分类器／收夜邻接零引用仍非本票；#1856 总核与全量 CI 留最终待合并。

---

## 附录：R1／R2 历史回执全文（保留失败经过与当时成员表）


工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5`
底座：`claude/1812-w4` 是 HEAD 祖先（`git merge-base --is-ancestor claude/1812-w4 HEAD` → yes）
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107fa-7c79-7613-87d5-0cf4e634cafd@fixer/fix-packet.md`
判词附件：`.../attachments/00-1856-judge-324c29f16.json`（F2 成立、未结；本票承接整类）

## 轮次

| 轮次 | HEAD（施工前） | 说明 |
|---|---|---|
| R1 | `ae4a2a3e6c60afd8a09f03252e692632d8c6bee6` | 合规合并／读端／候选绑定／财政投影清退 → `b85cb3f16`；回执 stamp → `d3a3688f2` |
| R2 | `d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e` | 纠正「旧文本流／季提示／军队投影」假阴性；沿错误形状全类 AST 核销 → `44f87c4c5`；stamp → `641201cde` |

## Advisor 前置判断（不冒充庭审）

- 授权：派单「执行派单全部授权 F2 清退」；F1/F3 只列不施工。
- R1 回执曾写「旧文本流调用……无成员可删」——**假阴性**（仅枚举 `text_stream`/`call_text_stream`，未覆盖 `run_agent_stream_text` 及专用依赖／测试）；R2 已纠正，见下「纠正 R1 不实结论」。本合并回执**不复制**该不实结论为现行事实。
- 手段演进：
  - R1 曾尝试 O(n²) 两两全文件互扫式死码扫描，**中止、未产完整结果**（无完整矩阵落盘）。后改轻量枚举：固定符号列表 + 受管 `.py` 线性 AST（defs/Name/Attribute refs）+ `git log -S` 历史交叉。
  - R2：禁止 O(n²) 两两全文件互扫；改用受管 Python 线性 AST 索引（定义 + Name/Attribute 引用）→ 消费者矩阵 → `git log -S` 历史交叉。
- 保留（两轮合计）：`_is_stalled_deliberation`、颁布校验、`project_applicable_authorities`、材料目录/`gather_candidate_events`、`open_affairs`/`transit_arrivals` 载荷写口、`decision_has_rescript_capability`、现役 `run_agent_text`、`_agent_run_accepts_stream`（供前者）、`season_option_fields` / `validate_season_option` / `_season_specs`、`CliChat.response_stream` 现役 CLI 流。
- 不冒充庭审席结论；本文件是修内司施工回执。

## 完整枚举命令（R1 实际执行）

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

注：上列为 R1 **改轻量枚举后**实际产出完整矩阵的命令。此前 O(n²) 两两互扫已中止，**无完整结果可附**。

R1 历史消费者交叉验证（`git log -S` / 判词点名提交）：

| 提交 | 说明 |
|---|---|
| `c90a43a1b` | 撤 `_dossier_ids_from_simulator_payload` 消费者（旧恢复落账） |
| `5047271cf` | 撤 `execution_side_read_fields` 生产消费者（旧 simulator 投影） |
| `53c83c3eb` | 撤旧 `candidate_events` 生产者 |
| `9d854eec3` / `7b3c94aa1` | 已在本底座祖先内：季入口／部分盘面投影退役；本轮清其残留支持 |

互联网结论摘要（R1）：删除未引用私有 helper／孤儿测试；不留兼容包装；静态枚举须交叉历史消费者与动态入口（本仓另核 `prepare_resolve` 载荷仅 `transit_arrivals`/`open_affairs`）。官方参考：[Python `ast`](https://docs.python.org/3/library/ast.html)、[Vulture](https://github.com/jendrikseipp/vulture)。

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

R2 历史交叉：

| 提交 | 说明 |
|---|---|
| `7b3c94aa1` | 撤 `simulate_season_with_payload` 对 `run_agent_stream_text` 的生产调用 |
| `5047271cf` / `1c2b68ba7` | 撤 `season_option_contract_prompt` 生产调用（季 simulator agent 供料） |
| `5047271cf` / `fcd177234` | `_simulator_army_dicts` 随盘面投影退役失去消费者 |
| `c90a43a1b` / `53c83c3eb` | R1 已核：载荷辅助／候选绑定历史消费者 |

## 成员表（R1 处置）

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
| 旧季模拟器提示 `content/prompts/season_simulator.md` | 已不存在 | `7b3c94aa1` 等已清 | 枚举确认文件已退役；**代码侧** `season_option_contract_prompt` 残留由 R2 另核销（见下） |
| 「旧文本流调用」类 | （R1 当时仅扫 `text_stream`/`call_text_stream`） | — | R1 曾误判「无成员可删」＝**假阴性**；真成员见 R2 成员表，**不采纳** R1 该结论 |

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
- 「季模拟器提示已无文件可删」→ `content/prompts/season_simulator.md` 确已不存在；但 **`season_option_contract_prompt` 代码残留** 仍属同类，R2 已删。

## 原类复扫

### R1 施工后
同轻量枚举脚本对 R1 表删除符号：`defs=NONE`、`refs=NONE`；`ming_sim/fiscal_fact_brief.py` 与 `tests/test_decision_event_binding_389.py` 不存在。
`rg` 对 `execution_side_read_fields|bind_decisions_to_candidate_events|build_fiscal_fact_brief` 等 → 无命中。

### R2 施工后
同 AST 脚本：`run_agent_stream_text`／`season_option_contract_prompt`／`_simulator_army_dicts`／`_find_simulator_army`／`record_stream_metrics` → `defs=NONE`、`refs=NONE`。
`rg -n 'run_agent_stream_text|season_option_contract_prompt|_simulator_army_dicts|_find_simulator_army|record_stream_metrics|text_stream|call_text_stream' ming_sim tests -g'*.py'` → 无命中。
现役保留：`run_agent_text`、`season_option_fields`、`validate_season_option` 生产引用仍在。

## 非本票承接／本轮不施工成员

### F1（#1856 已结类或边界残留，本单不施工）
- 旧单人材料／`audience_scene_recap`／`minister_speaker_role`／CLI 荐人信封等（判词 F1 disposition：已结）
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

环境前缀（七个 BIN，两轮共用）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  <files> \
  -q -p no:cacheprovider --durations=8
```

### R1 聚焦（清退合规／读端／绑定／财政投影后）

```bash
# <files> =
  tests/test_execution_tenure_613.py \
  tests/test_secret_dossier_participants_1252.py \
  tests/test_pay_order_override_653.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_llm_channel_config.py \
  tests/test_month_chain_1843.py \
  tests/test_rescript_choices_563.py
```

实测结果：`235 passed in 34.10s`（`/usr/bin/time -p`：`real 34.75` `user 25.53` `sys 8.45`）。

### R2 聚焦（清退 stream／season／army 残留后）

```bash
# <files> =
  tests/test_cli_backend.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_run_agent_text_transport_1465.py \
  tests/test_month_chain_1843.py \
  tests/test_rescript_choices_563.py
```

实测结果：`171 passed in 3.83s`。

两轮均未跑全量 suite（派单禁止）。

## 自查质量／合法性（advisor，非审官）

- 同类型：R1 按共同根因删合规／读端／绑定／财政投影；R2 沿「旧结算／simulator 专用支持」错误形状全类索引，专用依赖（metrics／thinking limit／专用测试）一并核销。
- 引入 bug：未改现役 `run_agent_text` transport；未撤 `season_option_fields`／`validate_season_option`；未复活季入口／`candidate_events` 生产者；密令参与人案改挂现役 `project_applicable_authorities`。
- 合法性：仅 F2；未改治理/Soul/宿主；未 amend/stash/push/PR；未杀 worker；F1/F3 只列。
- 复杂度：两轮均为净删专用定义与死测，无新机制、无证明性测试。
- **不冒称** #1856 总核收敛或庭审结清。

## Commit 与 git 状态

R1 清退：`b85cb3f16536aae7ff172fb22a848d12c717771d`
标题：`ak-roles: fix(#1843) retire obsolete settlement/simulator support tree (F2)`
diffstat：`13 files changed, 212 insertions(+), 1592 deletions(-)`

R1 stamp：`d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e`

R2 清退：`44f87c4c50d7429d87e068384a041312350156d8`
标题：`ak-roles: fix(#1843) retire stream/season/army F2 residuals after false-negative`
diffstat：`7 files changed, 119 insertions(+), 433 deletions(-)`

R2 stamp：`641201cde`（既有）

本段为独立 docs commit：合并 R1/R2 回执证据（恢复 R1 成员表与 235-passed 聚焦命令；清除 Markdown 尾空白；不复制假阴性结论）（禁止 amend）。

## 剩余范围

- F3 旁白／单场选择孤立支持：仍待原负责票。
- F1 边界 CLI 信封三符号：仍 ORPHAN，归属非本票。
- #1856 总核验：本回执不冒称总核收敛。
- 全量 CI / Web 构建：留最终待合并状态。
