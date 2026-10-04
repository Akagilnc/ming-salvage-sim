# #1843 F2 旧结算／simulator 支持树清退回执

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5`
底座：`claude/1812-w4` 是 HEAD 祖先（`git merge-base --is-ancestor claude/1812-w4 HEAD` → yes）
派单：`~/.ak-roles/books/Ming_LLM/1843/runs/01a107fa-7c79-7613-87d5-0cf4e634cafd@fixer/fix-packet.md`
判词附件：`.../attachments/00-1856-judge-324c29f16.json`（F2 成立、未结；本票承接整类）
重交原文：`evidence/1843-returned-finding.json`

## 轮次

| 轮次 | HEAD（施工前） | 说明 |
|---|---|---|
| R1 | `ae4a2a3e6c60afd8a09f03252e692632d8c6bee6` | 合规合并／读端／候选绑定／财政投影清退 → `b85cb3f16`；stamp → `d3a3688f2` |
| R2 | `d3a3688f222a6f0b2c9d276b5d7f054a4e52e63e` | 纠正旧文本流／季提示／军队投影假阴性 → `44f87c4c5`；stamp → `641201cde` |
| R3 | `9d4152542c226bc890dd5d231fdacc947d4381c2` | 封驳后穷尽删一批 ≤1-ref F2 → `ea297e120`；stamp → `79661de14`；**回执成员表用≈／多数／等聚合，被用户封驳** |
| R4 | `79661de14b745cb3f16f18099b2edb00bfb70730` | 补全联合枚举（AST 空消费者 ∪ 词边界≤1）；逐名 git log -S；再删 3 个 F2；例外 57 行逐名；精确 pytest 命令 |

## Advisor 前置判断（R4；不冒充庭审）

- 授权：派单 F2 全类；requiredAction＝完整「全仓引用数≤1」枚举（含 tests，排除 docs/raw），逐成员追历史消费者；属 F2 删；不属列例外并附依据。
- R3 失败点（必须保留）：例外表写「ORPHAN≈60」「多数 db.list_*」「require_*等」「各异」「无证 F2」——不是逐名历史消费者表；测试只写类别与「422 passed」无完整文件列表。
- R4 手段：禁止名字 regex 预筛；ming_sim 全定义索引；受管 py AST 引用 + 词边界≤1 联合清单；逐名 `git log -S`；无消费者记录实际查询与引入提交，不以缺证据自动保留；F2 删、F1/F3 邻接只归类；删后复扫固定点。
- 原始枚举落盘：`evidence/1843-f2-r4-enum-raw.txt`。

## 精确枚举数字（R4）

施工前（HEAD `79661de14`，删前）：

| 指标 | 数量 |
|---|---|
| managed_py | 352 |
| ming_sim_def_names | 2534 |
| AST_ORPHAN（AST 消费者为空） | 60 |
| WB_LE1（词边界≤1） | 51 |
| JOINT（并集） | 60 |
| AST_ONLY（AST0 且 WB>1） | 9 |
| WB_ONLY | 0 |

施工后固定点：

| 指标 | 数量 |
|---|---|
| managed_py | 352 |
| ming_sim_def_names | 2531 |
| AST_ORPHAN | 57 |
| WB_LE1 | 48 |
| JOINT | 57 |
| F2 本轮删除 | 3 |
| 例外（JOINT 全员逐名） | 57 |
| 级联新孤儿 | 0 |

AST_ONLY 九名：`MaterialsRoot`、`__enter__`、`__exit__`、`ainvoke`、`experiences`、`faction_report`、`flag_directive_needs_clarification`、`list_night_promulgated_directives`、`minister_speaker_role`。

## R4 枚举脚本（实际执行）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5
git rev-parse HEAD   # 施工前 79661de14b745cb3f16f18099b2edb00bfb70730

python3 <<'PY'
import ast, subprocess, re
from pathlib import Path
from collections import defaultdict

files = [f for f in subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
         if not f.startswith('docs/raw/')]
sources = {rel: Path(rel).read_text(encoding='utf-8', errors='ignore') for rel in files}

defs = defaultdict(list)
for rel, src in sources.items():
    if not rel.startswith('ming_sim/'):
        continue
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[node.name].append(f'{rel}:{node.lineno}')

refs = defaultdict(list)
for rel, src in sources.items():
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

token_hits = defaultdict(list)
token_pat = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\b')
for rel, src in sources.items():
    for i, line in enumerate(src.splitlines(), 1):
        for m in token_pat.finditer(line):
            name = m.group(1)
            if name in defs:
                token_hits[name].append(f'{rel}:{i}')

ast_orphans, wb_le1 = [], []
for name, dlocs in sorted(defs.items()):
    consumers = [r for r in refs.get(name, []) if r not in set(dlocs)]
    hits = token_hits.get(name, [])
    if not consumers:
        ast_orphans.append(name)
    if len(hits) <= 1:
        wb_le1.append(name)
joint = sorted(set(ast_orphans) | set(wb_le1))
print('managed_py', len(files))
print('ming_sim_def_names', len(defs))
print('AST_ORPHAN', len(ast_orphans))
print('WB_LE1', len(wb_le1))
print('JOINT', len(joint))
for name in joint:
    print(name)
PY

# 历史交叉（联合清单每一名）：
# git log -S'<symbol>' --oneline -- ming_sim tests
```
## 成员表（R4 处置：F2 删除，精确 3）

| 符号 | 文件 | 引用状态 | 历史消费者／提交 | 归类 | 处置及理由 |
|---|---|---|---|---|---|
| `record_economy_moves` | ming_sim/db.py（已删） | 施工前 AST0／WB1 | git log -S -- ming_sim tests：仅 `de0d7ad41 Initial public release`；`git log -G'record_economy_moves('` 无调用加减 | F2 | Event/edict_id 旧结算流水写口；现役为 `_apply_economy_list`／案卷 ledger insert；无历史调用亦按 F2 形状删 |
| `list_open_grant_reconciliations` | ming_sim/db.py（已删） | 施工前 AST0／WB1 | tip `81c4d2098` drop extractor leftovers 删除 `slim["grant_reconciliations"]=db.list_open_grant_reconciliations()`；引入 `2e9d54fc5` #567 | F2 | extractor slim 盘面专用读缝 |
| `executable_decree_dossier_ids` | ming_sim/db.py（已删） | 施工前 AST0／WB1 | tip `7b3676765` drop unreachable promulgated world-segment branch 删除唯一消费者；引入于案卷 simulation 查询链 | F2 | 旧 simulation／world-segment T/T+1 id 过滤 |

## 成员表（R4 例外：不施工，精确 57；一行一名）

列：符号 | 定义位置 | 引用状态 | git log -S tip（最多 4） | 归类 | 为何非 F2（正向依据；非「缺证据」）

| 符号 | 定义位置 | 引用状态 | git log -S | 归类 | 为何非 F2 |
|---|---|---|---|---|---|
| `ChatResult` | ming_sim/models.py:339 | AST消费者=0；词边界=1 | de0d7ad41	Initial public release | 非F2形状 | git log -S -- ming_sim tests 仅 de0d7ad41；Chat DTO，非结算／simulator／extractor 盘面 |
| `MaterialsRoot` | ming_sim/materials.py:159 | AST消费者=0；词边界=2 | cedbc1f69	ak-roles: fix(#1830): 删户部底账数字子串与经历哨兵，契约落结构化来源与读者面；3f73fb3c1	ak-roles: #1837 reopen 删旧大臣 agent，转译承接禁摊派/荐人/查访/催办/行程语气；94b112b79	ak-roles: fix(#1812): close seven seat/materials/dispatch root classes；98e456a6b	ak-roles: fix(#1865): prove materials handle via real Agent+OpenAIChat entrance | 协议 | 材料树根类型；构造与类型标注／动态入口仍用，wb=2 含类内自引用 |
| `__call__` | ming_sim/materials.py:182 | AST消费者=0；词边界=1 | 4cf4eb0a1	ak-roles: fix(#1898): 会合改标准库 Barrier + 终态观测缝，删任务生命周期推断；e3f982a9d	ak-roles: fix(#1898): 会合握手认任务终态，失败腿不再把测试挂死；511e82788	ak-roles: migrate secret-order matrix and unblock scene translation endpoint；aa60aafaf	ak-roles: remove retired minister secret-order entry tests | 协议 | MaterialsRoot 可调用协议；运行时 __call__ 触发，AST Name 不计 |
| `__enter__` | ming_sim/applier.py:108,ming_sim/session_write_queue.py:124,ming_sim/session_write_queue.py:224 | AST消费者=0；词边界=8 | 242837870	ak-roles: #1843 reopen 删旧结算核与 turn_extractions，修回 #670/#651；d68fbd9b6	ak-roles: fix(#1842): ClassifiedWriteGate atomic translation holder kind；a135e2615	ak-roles: test(#1831): remove permanent thread-race test and its gate scaffolding；1bdf0a5b2	ak-roles: test(#1831): race-lock proof pins read to inside first gate | 协议 | context manager；with 语句协议，AST Name 不计消费者 |
| `__exit__` | ming_sim/applier.py:111,ming_sim/session_write_queue.py:128,ming_sim/session_write_queue.py:228 | AST消费者=0；词边界=11 | d68fbd9b6	ak-roles: fix(#1842): ClassifiedWriteGate atomic translation holder kind；a135e2615	ak-roles: test(#1831): remove permanent thread-race test and its gate scaffolding；1bdf0a5b2	ak-roles: test(#1831): race-lock proof pins read to inside first gate；bc854212a	ak-roles: fix(#1465): migrate CLI runners onto unified transport, drop private loops and 300s walls | 协议 | context manager；with 语句协议，AST Name 不计消费者 |
| `__post_init__` | ming_sim/decree.py:312 | AST消费者=0；词边界=1 | 350d84dec	ak-roles: fix(#1753): scope promulgation judge Agno session per attempt | 协议 | dataclass 协议钩子；运行时自动调用 |
| `_cli_prompt` | ming_sim/cli_backend.py:4316 | AST消费者=0；词边界=1 | dd8c0f072	ak-roles: align CLI scene rollback history and remove retired recommendation envelope；afbcbbbd8	claude: test unadvanced cli retry structurally；7b3607f9f	claude: fix(decree): bind held dossier identity and isolate unadvanced cli turn；8489f4002	codex: fix(#485): converge P4 and streaming recommendation seams | F1 | 已判 F1 CLI 信封；派单不施工 |
| `_cli_recommendation_call` | ming_sim/cli_backend.py:4348 | AST消费者=0；词边界=1 | dd8c0f072	ak-roles: align CLI scene rollback history and remove retired recommendation envelope；8489f4002	codex: fix(#485): converge P4 and streaming recommendation seams；cbc522a1b	codex: fix(#485): close family correctness findings | F1 | 已判 F1 CLI 信封；派单不施工 |
| `_cli_stream_safe_prefix` | ming_sim/cli_backend.py:4336 | AST消费者=0；词边界=1 | dd8c0f072	ak-roles: align CLI scene rollback history and remove retired recommendation envelope；8489f4002	codex: fix(#485): converge P4 and streaming recommendation seams | F1 | 已判 F1 CLI 信封；派单不施工 |
| `_fail_cli_chat_turn_scene` | ming_sim/cli/terminal.py:156 | AST消费者=0；词边界=1 | 2879e69e0	ak-roles: #1838 reopen 删旁白 beat 整层，戏文只由场景 LLM 写；38018852b	ak-roles: fix(#542): close scene via ChatTurnSceneRegistry + exit cleanup chain | F3 | 已判 F3；#1838 旁白退役残留 |
| `_fiscal_container_value` | ming_sim/flows.py:285 | AST消费者=0；词边界=1 | d785a0a8f	fix: address online fiscal hub review findings；1b638a13d	sandcastle: cmr step6: persist outbound hub budget truth；8a26ada12	sandcastle: cmr step6: accumulate central loss containers；e445dde60	sandcastle: codex: fix(fiscal): address substrate hub review findings | 财政基座 | d785a0a8f 等 fiscal hub 评审后改调 _fiscal_container_values_when_complete；基座 helper 残留，非旧结算核／simulator 盘面 |
| `_is_audience_chat_shared_channel` | ming_sim/db.py:21086 | AST消费者=0；词边界=1 | cbc522a1b	codex: fix(#485): close family correctness findings；269bf8736	sandcastle: fix #485/#976: audience hold-and-release dual-track (no scrub)；25f5e7f9b	sandcastle: fix #485 completeness: structural scrub of assignee audience chat (#883)；39b84d5df	sandcastle: fix #485 completeness: scrub audience secret text from shared knowledge (#883) | F3邻接 | cbc522a1b／#485 召对双轨知识；共享频道判定 |
| `_matched_prefix` | ming_sim/cli_backend.py:3543 | AST消费者=0；词边界=1 | b5cda8126	ak-roles: remove superseded CLI action dispatcher and prefix tests；ecb062ead	ak-roles: remove retired conversation classifiers and stale inventory；fbd78f120	feat(probe): CLI LLM backend (agy/codex) — play without api key | F1邻接 | b5cda8126 撤 CLI action dispatcher；属 CLI 前缀路由残留 |
| `_primary_source_only_army_pay_container_total` | ming_sim/db.py:4381 | AST消费者=0；词边界=1 | d19f391b0	sandcastle: cmr fix: preserve Dongjiang pay funnel seed；15bc834e0	sandcastle: cmr fix: repair fiscal seed and pay funnel findings | 财政军饷 | d19f391b0／15bc834e0 东江饷漏斗种子修复后无外部调用；军饷容器合计，非 simulator board |
| `_province_collection_rate` | ming_sim/flows.py:59 | AST消费者=0；词边界=1 | 7b4e5f734	feat(后宫): 打通选妃流程 + 调教 tool 提权 + candidate 升格修复 | 选妃stub | git log -S 仅 7b4e5f734 后宫选妃；非结算／simulator |
| `_province_transport_ratio` | ming_sim/flows.py:54 | AST消费者=0；词边界=1 | 7b4e5f734	feat(后宫): 打通选妃流程 + 调教 tool 提权 + candidate 升格修复 | 选妃stub | git log -S 仅 7b4e5f734 后宫选妃；非结算／simulator |
| `_secret_prefix_needs_recent_context` | ming_sim/cli_backend.py:4290 | AST消费者=0；词边界=1 | b5cda8126	ak-roles: remove superseded CLI action dispatcher and prefix tests；ecb062ead	ak-roles: remove retired conversation classifiers and stale inventory；d891e4b6d	sandcastle: fix: preserve secret-order context from audience confirmation | F1邻接 | b5cda8126 撤 CLI action dispatcher；属 CLI 前缀路由残留 |
| `_target_active_officeholder` | ming_sim/session.py:409 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；1b9a22146	ak-roles: fix(#1380): r1 前缀零LLM闸 + parallel P5/DRY + 删重复观测；bf2df57b6	ak-roles: fix(#1380/#1355): QA-C P0 起复当回合落库 + 密令存活钉 | F1邻接 | 82be2f178／e2fc6369d 撤分类器 materialize；官职目标解析 |
| `ainvoke` | ming_sim/cli_backend.py:4466 | AST消费者=0；词边界=2 | ae3739f09	ak-roles: fix(#1843): hold month advance until the gazette exists；9eb510a8a	ak-roles: fix #884 drop invalid ainvoke wrap from transport bind；e5ff017b2	ak-roles: fix #884 Agno non-stream typed transport boundary for API verify；a9f1b1f8e	ak-roles: test(#1753): real seal/advance HTTP entry and Agent history resume | F1邻接 | ae3739f09 撤 CLI Agent 假适配；动态协议方法名，llm_transport 仍有同名字符串引用 |
| `ainvoke_stream` | ming_sim/cli_backend.py:4528 | AST消费者=0；词边界=1 | ae3739f09	ak-roles: fix(#1843): hold month advance until the gazette exists；a9f1b1f8e	ak-roles: test(#1753): real seal/advance HTTP entry and Agent history resume；8489f4002	codex: fix(#485): converge P4 and streaming recommendation seams；8110e9753	test(probe): 补 CLI 后端/会话胶水/扩编测试,新增代码覆盖 79→92% | F1邻接 | ae3739f09 撤 CLI Agent 假适配；流式协议方法 |
| `attach_secret_oral_pin` | ming_sim/db.py:11181 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；3f73fb3c1	ak-roles: #1837 reopen 删旧大臣 agent，转译承接禁摊派/荐人/查访/催办/行程语气；bcacdf379	sandcastle: fix(#515): registry materialize dispatcher + real-entry P5/undo tracers | F1邻接 | 82be2f178／e2fc6369d 撤分类器 materialize；密令口述钉 |
| `building_detail` | ming_sim/db.py:8859 | AST消费者=0；词边界=1 | 7182174c8	sandcastle: cmr S4 r1: close minister knowledge read bypasses；09aea3cf9	feat(buildings): 建筑系统 + 推演 token 优化 + token 遥测 | 知识读口 | 7182174c8／#1889 关大臣知识旁路／工具读；建筑定性详情，非 extractor slim／simulator board |
| `clear_directive_needs_clarification` | ming_sim/db.py:17543 | AST消费者=0；词边界=1 | b5cda8126	ak-roles: remove superseded CLI action dispatcher and prefix tests；4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；f6b5bbe4d	ak-roles: test: keep live entry boundaries after extractor retirement | F1邻接 | b5cda8126／4508956e5 撤 dispatcher／收夜背书批；澄清旗写口 |
| `cluster_effect` | ming_sim/action_clusters.py:215 | AST消费者=0；词边界=1 | b5cda8126	ak-roles: remove superseded CLI action dispatcher and prefix tests；69be199b5	ak-roles: #1871 reopen 删分类器候选处理与 materialize_fn 字段；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；23a5b9a8d	sandcastle: fix(#515): close PR 1120 review evidence gaps | F1邻接 | b5cda8126／#1871 撤分类器候选；ACTION_CLUSTERS 意图映射 |
| `complete_rescript_summon_scaffold_turn` | ming_sim/db.py:9230 | AST消费者=0；词边界=1 | 2879e69e0	ak-roles: #1838 reopen 删旁白 beat 整层，戏文只由场景 LLM 写；185698d55	ak-roles: fix(#657) 六类断根——desk入相/共享首选投影/phase2保旧并生新/单一终态清锚/默认hold保note/任命身份冲突拒；a4dfa1bfd	ak-roles: fix(#657) 收敛 HITL 唯一编排出口与 scaffold consumed 终态 | F3邻接 | 2879e69e0 #1838 旁白 beat 退役；批红召见脚手架 |
| `compose_decree_validation_recovery` | ming_sim/cli_backend.py:1915 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；c56b4d025	ak-roles: fix(#1778): audience assignee from post-extract, no code fill；4ca0717bd	ak-roles: exercise recovery composer path | F1邻接 | 历史消费者 #1871 分类器落地链（e2fc6369d／82be2f178）；非旧结算／simulator |
| `compose_secret_order_landing_recovery` | ming_sim/cli_backend.py:2002 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；68852e0e6	ak-roles: remove unreachable secret-prefix HTTP recovery suite；aaab7d590	ak-roles: retire API secret-prefix extraction cases after typed deadline coverage；aa60aafaf	ak-roles: remove retired minister secret-order entry tests | F1邻接 | 历史消费者 #1871 分类器落地链（e2fc6369d／82be2f178）；非旧结算／simulator |
| `current_audience_scene` | ming_sim/due_review.py:313 | AST消费者=0；词边界=1 | 51af199b6	ak-roles: fix multi-dossier exposure routing and remove retired dialogue benchmark；53d9a7435	ak-roles: repair #1837 source pins, grounding and recommendation; retire legacy routes and skills；ce9527f7b	ak-roles: bind audience cases and preserve report and scene facts；82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers | F3 | 已判 F3；单场召对场景读口 |
| `dict_of_string_lists` | ming_sim/content.py:600 | AST消费者=0；词边界=1 | 53d9a7435	ak-roles: repair #1837 source pins, grounding and recommendation; retire legacy routes and skills；006705ced	ak-roles: remove obsolete skill grants and keyword inquiry reports；0fb025ebe	ak-roles: fix character knowledge by durable scope；06ac92688	sandcastle: cmr fix(#489): load office knowledge domains from content | 内容加载 | 53d9a7435 #1837 撤旧路由／skills 后无直调；content.py JSON 形状校验 |
| `dict_of_strings` | ming_sim/content.py:605 | AST消费者=0；词边界=1 | 53d9a7435	ak-roles: repair #1837 source pins, grounding and recommendation; retire legacy routes and skills；006705ced	ak-roles: remove obsolete skill grants and keyword inquiry reports；90523a0fa	ak-roles: preserve urge reasons and retire minister tool materials；de0d7ad41	Initial public release | 内容加载 | 53d9a7435 #1837 撤旧路由／skills 后无直调；content.py JSON 形状校验 |
| `discard_pending_directives` | ming_sim/db.py:18788 | AST消费者=0；词边界=1 | ecb062ead	ak-roles: remove retired conversation classifiers and stale inventory；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；413b5e209	ak-roles: repair forecast rollback and event alignment；faec8ba6b	sandcastle: codex: fix: wire decree dossiers into settlement (#571) | F1邻接 | ecb062ead／45b11dc7a 撤会话分类器与 inventory；旨意草稿丢弃 |
| `discover_character_write_sql_locations` | ming_sim/person_write_inventory.py:112 | AST消费者=0；词边界=1 | 90015569f	ak-roles: test(#1185): wave1 delete 24 + move 20 knowledge→489；daf63e7cc	test(person): inventory character write points | 人物写点清单 | 90015569f #1185 测试搬迁后无测消费；inventory 工具，非结算 |
| `experiences` | ming_sim/entities/affair/store.py:429 | AST消费者=0；词边界=2 | 45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；b81af35ff	ak-roles: refactor: remove retired M18 paths；7149c9414	ak-roles: per-item reject unauthorized story and event-person origins；a135e2615	ak-roles: test(#1831): remove permanent thread-race test and its gate scaffolding | 事务经历 | 45b11dc7a #1871 撤读心／故事抽取；affair store 属性／方法，wb=2 自文件 |
| `faction_report` | ming_sim/db.py:6714 | AST消费者=0；词边界=5 | 3f73fb3c1	ak-roles: #1837 reopen 删旧大臣 agent，转译承接禁摊派/荐人/查访/催办/行程语气；5047271cf	ak-roles: unify decree forecast snapshot and drop simulator board feed (#1861 reopen)；81c4d2098	ak-roles: fix: connect world-segment material reads and drop extractor leftovers；0fb025ebe	ak-roles: fix character knowledge by durable scope | 知识权限钉 | wb=5：tests/test_character_knowledge_489.py 以 setattr／字符串钉权限边界；5047271cf／81c4d2098 曾从 simulator／extractor 载荷撤出，定义仍供知识契约 |
| `find_prior_speaker_still_present` | ming_sim/audience_night.py:2463 | AST消费者=0；词边界=1 | 3e4d4fcd2	ak-roles: retire orphan beat writer and route offsite summons through scene；2879e69e0	ak-roles: #1838 reopen 删旁白 beat 整层，戏文只由场景 LLM 写；6f0c3cb56	ak-roles: fix(#1585) close night writes last exit then unnamed divider；1f2dc2a60	ak-roles: #1585 handoff narration, concurrent enter+handoff generation, soft-segment divider | F3 | 已判 F3 召对／旁白；派单不施工 |
| `flag_directive_needs_clarification` | ming_sim/db.py:17702 | AST消费者=0；词边界=2 | b5cda8126	ak-roles: remove superseded CLI action dispatcher and prefix tests；4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；f6b5bbe4d	ak-roles: test: keep live entry boundaries after extractor retirement | F1邻接 | b5cda8126／4508956e5 撤 dispatcher／收夜背书批；澄清旗写口 |
| `has_player_visible_rejection` | ming_sim/applier.py:387 | AST消费者=0；词边界=1 | 5b6c868bc	ak-roles: fix(#1745): 判牒五类——section 隔离/删自有 collector/去固定邸报句/测减；d3c1550f2	issue #63: implement ADR0015 per-item rejection handoff；9f1c0da2b	fix(provenance): 皇帝下旨结算贯穿 player_decree 来源 + 重抽不丢 (Refs #146)；ee141f3b5	cmr C2 online R1 fix (codex P2 + CodeRabbit Major): hint after inertia collection; defer source-recovery to #144 | 拒收呈现 | 5b6c868bc #1745 判牒 section；玩家可见拒收判定，非旧结算核 |
| `holder_kind` | ming_sim/session_write_queue.py:110 | AST消费者=0；词边界=1 | a9be44bb6	ak-roles: fix: unify audience translation lifecycle；7a2dfd1d5	ak-roles: fix(#1842): clear six-class residuals — drain core, AC tracers, docs；d68fbd9b6	ak-roles: fix(#1842): ClassifiedWriteGate atomic translation holder kind | 协议 | session_write_queue 属性／协议面；动态读取 |
| `list_night_promulgated_directives` | ming_sim/db.py:17571 | AST消费者=0；词边界=2 | 4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；60cbfcc1c	ak-roles: fix(#612): scheme A night-level endorsement-only batch；7fa758ee8	ak-roles: test(#612): fold five parallel tracers into three existing ones | F3邻接 | 4508956e5 #1842 收夜背书批测试消费者撤；夜颁布读口 |
| `list_office_vacancies` | ming_sim/db.py:4046 | AST消费者=0；词边界=1 | 006705ced	ak-roles: remove obsolete skill grants and keyword inquiry reports；5bb968919	ak-roles: test(#1185): wave2a rewrite 盯文→结构 (mindreading/near-minister/城防/密令/army)；77399e9c7	codex: cmr S3 r6: converge roster and office truth；cbc522a1b	codex: fix(#485): close family correctness findings | 名册读口 | 006705ced 撤 obsolete skill grants／keyword inquiry；官缺列表，非结算／simulator |
| `list_promulgated_directives` | ming_sim/db.py:17607 | AST消费者=0；词边界=1 | 4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批；45b11dc7a	ak-roles: #1871 reopen 删读心/分类器/故事抽取残留/递话 agent；8fb055a5d	ak-roles: fix(#612): night candidates, OPEN restore, chat admission, SQL range；60cbfcc1c	ak-roles: fix(#612): scheme A night-level endorsement-only batch | F3邻接 | 4508956e5 #1842 收夜背书批测试消费者撤；颁布读口 |
| `mark_chat_turn_failed` | ming_sim/db.py:9562 | AST消费者=0；词边界=1 | 2879e69e0	ak-roles: #1838 reopen 删旁白 beat 整层，戏文只由场景 LLM 写；69c050596	ak-roles: refactor(#1585) reuse chat-turn failure transition；806d29019	支持撤回最后一次召对发言 | F3邻接 | 2879e69e0 #1838 旁白退役；会话失败标记 |
| `minister_speaker_role` | ming_sim/action_materialize.py:29 | AST消费者=0；词边界=3 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；81f8bacff	ak-roles: fix(#1765): C5–C7 residual + loud secret extract contract；23196d8ed	ak-roles: fix(#1765): gate r1 — drop count locks, parallel prose/transport | F1邻接 | 82be2f178／e2fc6369d 撤分类器 materialize；召对／CLI 档料 helper |
| `night_dossiers_ready` | ming_sim/audience_night.py:345 | AST消费者=0；词边界=1 | d469fc404	ak-roles: remove duplicate and white-box endorsement tests；4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批 | F3邻接 | 4508956e5／d469fc404 #1842 收夜背书批；非结算／simulator |
| `person_write_locations_by_disposition` | ming_sim/person_write_inventory.py:157 | AST消费者=0；词边界=1 | 90015569f	ak-roles: test(#1185): wave1 delete 24 + move 20 knowledge→489；daf63e7cc	test(person): inventory character write points | 人物写点清单 | 90015569f #1185 测试搬迁后无测消费；inventory 工具，非结算 |
| `point_dossier` | ming_sim/entities/affair/store.py:284 | AST消费者=0；词边界=1 | f3e697fb3	ak-roles: fix(#1812): closed affair 拒收 active linked issue，materials 单次冻结投影；98ac175ab	ak-roles: fix(#1812): affair id path collision, dead test-only helper, double prepare, closed-affair reattach；60e90ea6a	ak-roles: fix(#1831): unify affair pointers and wire real declarations；bcf6c202d	ak-roles: feat(#1831): affair records, pointers, and night-close birth | 事务指针 | f3e697fb3／#1831 affair 指针；实体 store API |
| `point_issue` | ming_sim/entities/affair/store.py:316 | AST消费者=0；词边界=1 | f3e697fb3	ak-roles: fix(#1812): closed affair 拒收 active linked issue，materials 单次冻结投影；356495e31	ak-roles: fix(#1812): 关闭事务上仍活跃的 linked issue 回退到自己身份进开场；e6aea5637	ak-roles: fix(#1812): linked issue 归并到 affair 身份，不再连带丢弃可见材料；69f100b70	ak-roles: fix(#1812): affair 单一投影+全量文字事实，删授权全量透传改当场验证 | 事务指针 | f3e697fb3／#1831 affair 指针；实体 store API |
| `pointing_at` | ming_sim/entities/textual_fact/store.py:113 | AST消费者=0；词边界=1 | 48f1c48f7	ak-roles: #1896 assert investigation outcomes on the month entry；c653d4719	ak-roles: #1896 investigation by per-fact difficulty and actual effort, not fixed progress；dc7e4bd8e	ak-roles: fix(#1831): unique batch declaration, ground existing, bind results；28a35575b	ak-roles: fix(#1831): narrow affair declarations by stage | 文字事实指针 | 48f1c48f7／#1896／#1831 textual_fact 指针 API |
| `qualitative_character_attribute` | ming_sim/qualitative.py:53 | AST消费者=0；词边界=1 | 534b9be53	sandcastle: fix: unify qualitative projection and remove prose scrubbers；5fdac5884	sandcastle: codex: fix(web): #1022 remove player-facing raw ledgers | 呈现投影 | 534b9be53 统一定性投影撤 prose scrubber 调用；人物属性定性，非结算落账 |
| `read_credit_events_as_edges` | ming_sim/db.py:22463 | AST消费者=0；词边界=1 | e5f45136b	codex: implement directed relation edge storage | 关系边 | git log -S 仅 e5f45136b directed relation edge storage；边读口，非结算／simulator |
| `release_previous_material_tree` | ming_sim/materials.py:227 | AST消费者=0；词边界=1 | 3f73fb3c1	ak-roles: #1837 reopen 删旧大臣 agent，转译承接禁摊派/荐人/查访/催办/行程语气；94b112b79	ak-roles: fix(#1812): close seven seat/materials/dispatch root classes | 材料目录 | 3f73fb3c1 #1837 撤旧大臣 agent 后无直调；材料树生命周期 helper，非结算／simulator |
| `require_bool` | ming_sim/llm_contract.py:41 | AST消费者=0；词边界=1 | de0d7ad41	Initial public release | 非F2形状 | git log -S 仅 de0d7ad41；llm_contract 校验叶，现役 abort_llm_contract 路径未改用此三函数 |
| `require_int_range` | ming_sim/llm_contract.py:24 | AST消费者=0；词边界=1 | de0d7ad41	Initial public release | 非F2形状 | git log -S 仅 de0d7ad41；llm_contract 校验叶，非结算／simulator |
| `require_non_empty_text` | ming_sim/llm_contract.py:18 | AST消费者=0；词边界=1 | de0d7ad41	Initial public release | 非F2形状 | git log -S 仅 de0d7ad41；llm_contract 校验叶，非结算／simulator |
| `run_audience_turn_translation` | ming_sim/audience_translate.py:551 | AST消费者=0；词边界=1 | 4508956e5	ak-roles: #1842 reopen 转译唯一后台路径、背书并进转译、删收夜背书批；b3fc0c93e	ak-roles: test: restore court-break and translation tracers；f16aa3a51	ak-roles: #1842 T2 转译后台化与封夜提交 join；a5255bce0	ak-roles: fix(#1837): 本场已说读 chat_messages、拒收幻影实体、禁模板正文 | F3邻接 | 4508956e5 #1842 转译后台化；召对转译入口 |
| `stage_referral_candidate` | ming_sim/action_materialize.py:1703 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；b62fb8d48	ak-roles: feat(#524): 下议 ACTION_CLUSTERS 纵切 | F1邻接 | 82be2f178／e2fc6369d 撤分类器落地；荐人候选 staging |
| `stage_revoke_authority_candidate` | ming_sim/action_materialize.py:1815 | AST消费者=0；词边界=1 | 82be2f178	ak-roles: repair #1837 audience provenance and retire classifier materializers；e2fc6369d	ak-roles: #1871 reopen 删分类器落地链残留死码；5efb7c3e9	ak-roles: feat(#523): 收权·罢差 + 撤回成命 ACTION_CLUSTERS 纵切 | F1邻接 | 82be2f178／e2fc6369d 撤分类器落地；收权候选 staging |

例外归类计数：F1=3；F3=3；F1邻接=16；F3邻接=7；协议=7；选妃stub=2；财政基座=1；财政军饷=1；知识读口=1；知识权限钉=1；内容加载=2；非F2形状=4；人物写点清单=2；事务指针=2；文字事实指针=1；事务经历=1；呈现投影=1；关系边=1；拒收呈现=1；名册读口=1；材料目录=1。合计 57。

## 原类复扫（R4 固定点）

- 本轮删除三符号 defs/refs=NONE。
- 复扫 JOINT=57；相对删前 JOINT=60 仅少三删除名；NEW_ORPHANS=空。
- R1–R3 已删 F2 符号抽查仍无生产／测试残留。

## 聚焦测试（R4；完整可复现命令）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_grant_reconciliation_567.py \
  tests/test_month_chain_1843.py \
  tests/test_value_matrix_691.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_covert_levy_651.py \
  tests/test_rescript_draft_656.py \
  tests/test_rescript_choices_563.py \
  tests/test_character_knowledge_489.py \
  tests/test_pay_order_override_653.py \
  tests/test_economy_section_rejections.py \
  tests/test_section_fiscal_rejections.py \
  tests/test_secret_dossier_participants_1252.py \
  tests/test_secret_order_section_rejections.py \
  tests/test_execution_tenure_613.py \
  -q -p no:cacheprovider --durations=8
```

实测（`/usr/bin/time -p`）：`401 passed, 1 skipped in 9.48s`；`real 10.27` `user 6.87` `sys 2.22`。日志：`/tmp/1843-f2-r4/pytest-r4.log`（系统临时）。未跑全量。

### 关于 R3「422 passed」

R3 回执只写类别「value_matrix／secret_order／covert／month_chain／report／rescript／section／knowledge／pay_order」与「422 passed, 1 skipped in 11.71s」，**未保存完整 pytest 文件列表**；fixer session／本机 terminals 亦未检索到可复现的 422 文件集。R4 不伪造该命令；以上为 R4 实际执行的完整命令与计数。R1（235）／R2（171）的完整文件列表仍见附录。

## 自查质量／合法性（advisor，非审官）

- 同类型：继续清退 extractor slim／simulation world-segment／Event-edict 旧结算写口。
- 引入 bug：未动 `record_monthly_grant_reconciliations`／`_apply_economy_list`／现役月链写口。
- 合法性：仅 F2 删 3；F1/F3 及邻接只归类；未 amend/stash/push/PR；未造证明性测试；不冒称 #1856 总核收敛。
- 证据形态：禁止≈／多数／等；JOINT 57 行逐名；原始枚举另文件。

## Commit 与 git 状态（R4）

- 施工前 HEAD：`79661de14b745cb3f16f18099b2edb00bfb70730`
- R4 清退＋证据：`66d8d86d0f00a250a6b8f7014f1b95c2481dd1bf`
- 标题：`ak-roles: fix(#1843) complete F2 joint enum member table and retire 3 residuals`
- diffstat：`3 files changed, 341 insertions(+), 71 deletions(-)`
- `git diff --check`：干净

## 剩余范围

F1／F3／分类器／收夜邻接零引用仍非本票；#1856 总核与全量 CI 留最终待合并。

---

## 附录 A：R3 不完整回执原文（封驳对象；保留失败经过）

<details>
<summary>R3 stamp 正文（含≈／多数／等聚合，已封驳）</summary>

~~~
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

~~~bash
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
~~~

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

## Commit 与 git 状态（R3）

- 施工前 HEAD：`9d4152542c226bc890dd5d231fdacc947d4381c2`
- R3 清退：`ea297e120e090c68a86b6cd2885f611497988b69`
- 标题：`ak-roles: fix(#1843) exhaust F2 ≤1-ref retirement after enum false-negatives`
- diffstat：`8 files changed, 152 insertions(+), 281 deletions(-)`
- `git diff 9d4152542..ea297e120 --check`：干净
- 含 `evidence/1843-returned-finding.json` 原文重交

## 剩余范围

F1／F3／分类器／收夜邻接零引用仍非本票；#1856 总核与全量 CI 留最终待合并。

---
~~~

</details>

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
