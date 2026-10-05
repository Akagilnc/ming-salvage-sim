# #1891/#1899 CHOICE-C1 + CLEANUP-C1 闭包回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。  
开工 HEAD：`34262577af3f6dbf455e64698ee5335dfcd51ddd`。  
法源：末判原卷最后 payload——`1891m-judge-34262577a.json`、`1899c-judge-34262577a.json`（本局只送两根因）。  
用户类原文方向：退役选项契约残留；退役消费者与测试支持物闭包不全。  
advisor（只读 PASS，非正式）：`canonical_choice` 键表删 `terminal_reason` 最简；equality 走既有统一真源；保留事件账 `db.mark_event_triggered`／`Event.terminal_reason_labels` 等。

旧回执 `docs/reports/1891-1899-dry-test-closure.md` 已文首追加**范围错误撤回**；原失败史留存，不在本文增厚。

## 环境

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
TMPROOT=/tmp/1891-choice-cleanup.nKTt1L
UV_TOOL_DIR=/tmp/1891-uv-tools UV_CACHE_DIR=/tmp/1891-uv-cache
# ruff 0.11.2 via: uv tool run --from ruff==0.11.2 ruff
```

官方文档先查：Astral Ruff F401/F841／linter ignoring；Python `ast` 库文档。审计为 inline 自包含标准库 AST + 现成 ruff，不新造通用扫描框架；parse 失败直抛。

## 枚举命令（修前）

1. `git ls-files '*.py'` → 351 文件 `ast.parse`（`PARSED_PYTHON 351`）。  
2. 递归收集 `FunctionDef|AsyncFunctionDef`（function／method／nested）+ `Import`/`ImportFrom` 绑定。  
3. 消费者语义区分：`Name(Load)`／`Attribute`／`ImportFrom`／字符串注解／fixture 参数／`usefixtures`／pytest&SDK 协议动态注册；**禁止**机械零删。  
4. `ruff check --select F401,F841 --ignore-noqa`（含伪保留 noqa）。  
5. 全仓 `terminal_reason` 与 `_require_active_minister` 文本扫描。

## CHOICE-C1 成员表

| # | qualified 成员 | 处置 | 依据 |
| --- | --- | --- | --- |
| 1 | `ming_sim.rescript_actions.canonical_choice` 键表项 `"terminal_reason"`（原 L132） | **DELETE** | 旧选项解释者已删；该键仅残留于接收规范化，并进入 `_choices_equal`；全仓无第二份 choice 键表含此字段 |

**附属**：无专属测试／兼容层／迁移机制；未改 decided 比较入口，equality 继续经 `canonical_choice` → `_stable_json`。

### KEEP（真实事件账，不删）

| qualified | 保留依据 |
| --- | --- |
| `ming_sim.db.GameDB.mark_event_triggered(..., terminal_reason=...)` | 事件终局写口；财政／月链测试真实消费 |
| `event_triggers.terminal_reason` 列与读写 SQL（`db.py`） | 持久事件账 |
| `Event.terminal_reason_labels`／`content.py` 加载 | 事件配置契约 |
| `issues.py`／月链／财政测试对 ledger `terminal_reason` 的断言 | 现役事件终局消费者，非 choice 接收 |

### 临时内存变异取证（不入仓）

日志：`$TMPROOT/logs/choice-mutation.txt`

- 当前：带／不带多余 `terminal_reason` 的 choice → `canonical_choice` 均无该键；`_choices_equal` = True。  
- 内存装回旧键表后：带字段规范化保留 `terminal_reason`；`_choices_equal` = False。  
- 恢复后 equality 再 True。  
未新增永久证明测试。

## CLEANUP-C1 成员表（全类；实例非白名单）

修前候选经 AST+ruff+反向消费者复核后，**DELETE** 如下：

| # | qualified 成员 | 种类 | 处置 | 消费者复核 |
| --- | --- | --- | --- | --- |
| 1 | `tests.test_web_chat_serialization_393._FakeSession._merge_staged_new_secret_order_content` | method | DELETE | Name/Attribute 全仓 0；非 fixture／协议 |
| 2 | `tests.test_pihong_dossier_1490.test_657_web_http_hitl_lock_boundary_same_gate._gen` | nested | DELETE | 案内无接线；setprofile 历史 0 调用 |
| 3 | `tests.test_levy_petition_month_chain_1891` → `import math` | import binding | DELETE | 文件内无 Name 消费 |
| 4 | `tests.test_levy_petition_month_chain_1891` → `from ming_sim.agents import strip_json_fence`（noqa「保证同源」） | import binding | DELETE | 伪保留；权威 `ming_sim.assets.strip_json_fence` 仍由 `agents` 等消费 |
| 5 | `tests.test_secret_order_payoff_1504` → `offline_empty_audience_translate` | import binding | DELETE | 本文件无 Load；权威 `tests.conftest` 定义仍有他案消费 |
| 6 | 同上 → `stub_audience_translate` | import binding | DELETE | 同上 |
| 7 | 同上 → `stub_scene_agent` | import binding | DELETE | 同上 |
| 8 | `ming_sim.context` → `army_aliases` re-export import | import binding | DELETE | `from ming_sim.context import …` 反向 0；权威 `ming_sim.matching.army_aliases` KEEP |
| 9 | `ming_sim.context` → `compact_name` | import binding | DELETE | 同上；权威 matching KEEP |
| 10 | `ming_sim.context` → `region_aliases` | import binding | DELETE | 同上；权威 matching KEEP |
| 11 | `web_app` → `LLMContractError`（noqa「保留：供错误处理」） | import binding | DELETE | web_app 内 Name Load 0；权威 `ming_sim.exceptions.LLMContractError` 仍被 decree／terminal 等消费 |
| 12 | `ming_sim.models.is_vassal_prince` 文档守面项 `_require_active_minister` | 失效说明 | DELETE 字样 | 生产函数已不存在；清单改列现役 web／session 面 |
| 13 | `ming_sim.session.GameSession.can_summon` 注释中「web _require_active_minister」 | 失效说明 | DELETE 字样 | 改为 `is_vassal_prince`／roster 同口径 |

### 枚举后 KEEP（不得机械零删）

| qualified / 面 | 保留依据 |
| --- | --- |
| `web_app._NonBlockingWebWriteGate.__enter__`／`__exit__` | 上下文管理器协议方法（SDK／语言协议），非死方法 |
| `ming_sim.matching.{army_aliases,compact_name,region_aliases}` | 权威实现；matching 内部 Name 消费 |
| `ming_sim.context.match_{region,army}_id_from_text` | 现役包装，仍 import `_match_*` |
| `tests.conftest.{offline_empty_audience_translate,stub_audience_translate,stub_scene_agent}` | 多文件真实调用 |
| `ming_sim.assets.strip_json_fence`／`agents` 内调用 | 权威与生产消费 |
| `ming_sim.exceptions.LLMContractError` | 多模块 raise／catch |
| `ming_sim.session` re-export `FRONT_HALF_DONE_PHASES`／`TurnPhase` | `cli/terminal.py` 等 `from ming_sim.session import …` |
| `action_materialize` F401 副作用 import | 安装 package catalog |
| pytest fixture discovery 的 `game`／`tracer_client` noqa 导入 | 参数／发现协议 |
| 测试历史注释中提及已删 `_require_active_minister` | 叙述退役史，非主张现役守面 |

**不在本类**：无关 F841 局部变量、既结 DRY 结算合流、财政现役行为。未新增测试、未放松断言。

## 修后复扫

```
PARSED_PYTHON 351
CHOICE_canonical_choice_has_terminal_reason False
DEF_GONE _merge_staged_new_secret_order_content []
DEF_GONE _gen []
UNUSED_IMPORTS (levy/payoff/context/web_app) []
REQUIRE_ACTIVE in prod: (无)
ruff F401 --ignore-noqa on focus imports: All checks passed!
```

触及文件 `ruff --select F401,F821`：`web_app.py` 既有 `ExceptionGroup` F821（ruff 默认 target 低于 3.11 时的误报），**非本轮引入**；不冒称 typecheck。运行时 Python 3.13。

## 聚焦测试

七 BIN + `MING_SIM_USER_DATA_DIR=$TMPROOT/user` + `--basetemp` + `-p no:cacheprovider`：

| 日志 | 选择器摘要 | 结果 |
| --- | --- | --- |
| `$TMPROOT/logs/focus-core.log` | levy 月链／财政废除／财政 effect／rescript_choices／cli_play_turn／zongfan can_summon | **113 passed in 33.38s** |
| `$TMPROOT/logs/focus-support.log` | web_chat_serialization／pihong 657 锁窗／payoff1504／web_court_visibility／qa_s2 | **83 passed in 3.38s** |

未跑全量、未调真实模型。

## 自查二连

1. **同类**：CHOICE 仅一处键表成员；CLEANUP 覆盖方法／嵌套／导入／伪保留 noqa／失效守面；复扫无同类残留。  
2. **引入 bug**：未改财政／DRY；choice equality 经变异对照确认；权威实现仅删冗余绑定。

## 文档扫描失效说明

| 文档 | 说明 |
| --- | --- |
| `docs/reports/1891-1899-dry-test-closure.md` | 文首已撤回「顶层 ORPHAN=0＝全类清净」；失败史保留 |
| 其他 `1891-*.md` 历史 | 可含已删符号名作病史；不作现役契约 |

## 交卷

代码 diff：`rescript_actions`／`context`／`models`／`session`／`web_app` + 四测试文件；净删。  
commit：见 git log（`ak-roles:` 前缀 forward，禁止 amend）。
