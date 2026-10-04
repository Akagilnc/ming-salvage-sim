# #1901 J11 重交通（c8215188f 之后）

本轮承接 J11「删简误删必要行为证明、留下空验收」。J3 前卷已清，不重送。用户指出的 10 个未提交测试文件均属 J11；本轮只改这些测试及证据，不改生产、Soul、ADR、宿主或席位，不 amend/stash/push/开 PR。旧 completed 回执不覆盖这些未提交内容；本记录及新提交是补充交卷，不是合并或关票。

## 范围与整类处置

定义不收窄：输入传递、诊断事实、业务负向条件、数值不变式及空验收。逐项审计两轮 `192603c52^..192603c52`、`192603c52..c8215188f` 的测试删除/修改：Python AST 154 条（120 修改、34 删除）；TypeScript compiler 56 条，包括同一案两轮的独立记录。完整 210 条成员表见 [issue-1901-j11-members.md](issue-1901-j11-members.md)，冻结前后源码在 `/tmp/1901-j11-audit.json`、`/tmp/1901-j11-web.json`，不以几个样本代替整类。

枚举方法：对每个范围用 `git diff --name-only <old> <new> -- tests web/src` 取文件；`git show <rev>:<path>` 取冻结源码；Python `ast` 遍历 test 函数，TypeScript `createSourceFile`/`forEachChild` 遍历 it/test 回调；按函数/测试元数据配对，收录删除或正文发生变化的全部成员。归类由角色读前后正文，不用测试名称或自由文本 regex 判断合法性。另按前卷全仓枚举命令复查断言与无断言候选。无 assert 不自动判空：不抛异常本身可为契约。

修复共同错误：前卷只检查显式断言，漏掉真实消费者的不抛异常契约；部分删减未核对唯一行为出处；知识档案先过滤再排除导致空证明。

- 恢复非 dict ongoing（月漂移真正读取 `"oops"`、5、true、数组）的不崩溃案；通用解析器单测不能代替消费者。
- 删除知识改写空案；由现存三案分别验证持久来源投影、回合报告对应来源、共享档案不能写受限 aggregate。不是删除失败路径求绿。
- 同一异名 carrier 案参数化国库/内库：同时保护同账户信号、异账户无信号及财政项不被错误去重。
- 恢复坏容器/坏 JSON 的 shadow 消费者隔离诊断；坏值不被预过滤/覆写。shadow 继续是既有契约，不用继续洗白未落痕失败。
- 恢复军队日志 cap 满时真实变化的军队标识传递；只验实际输入军名，不恢复 prose 数字提取、`-8` 字符串或拼句锁。
- 材料真实地区/军队标识必须传递，不能只有目录/文件存在。
- 删除账本刚读即比较自身的无效证明；该案保留月份不推进，财政落账/恢复由既有真实收尾案验证。
- Web API/CLI 门控合并到已有夹具的参数化案，验 URL、runner、timeout 的实际 control value；恢复 tax、兵力、月饷原始标量输入传递；定位驻军事实表而非误取地区表。不解析散文数字、不恢复单位/表头/句式锁。
- 关闭组回调必须携带非空理由；不锁理由措辞。游戏内菜单以实际按钮输入和结构化 HTTP 调用验证不请求 new_game，不恢复页签标签缺席钉。

## 变异证据与有效性边界

仅变异生产实现；测试输入、夹具和断言不变。Python 使用原 globals/闭包的代码对象，finally 恢复；Web 在自建 `/tmp` 副本改生产 body，finally 恢复并校验源码；工作树生产无 diff。复用 pytest hooks、TypeScript compiler、Vitest JSON reporter，没有生产 hook、新通用件或测量行为 mock。mock 仅为现存外部调用边界。

入口删失 KO 只证明消费者/数据必要性，不声称它单独证明每项算法；数值、诊断、隔离、账户和不可达条件另作专项变异。初始找错入口、未匹配、编译错误或变异仍绿的结果不计红证据。曾有 5 条 Python 无 producer 的探针错误、9 条 Web 未定位，已纠正并独立重跑；不得以那些错误冒充检出。

所有 pytest/Vitest 命令设置：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

| 生产变异 / 命令 | 真实结果及指针 |
| --- | --- |
| `python /tmp/1901-j11-probe.py ongoing`：消费方去 dict 守门 | 恢复案 1 failed（str 无 get）；其余 151 passed。`/tmp/1901-j11-ongoing-results.json` |
| 同脚本 `archive`：共享报告写原 aggregate | 3 个现存来源/存储边界案全部 failed；`/tmp/1901-j11-archive-results.json` |
| 同脚本 `account`：忽略账户不相等 | 异账户参数 failed，同账户 passed；`/tmp/1901-j11-account-results.json` |
| 同脚本 `region-material` / `army-material`：真正公开 reader 丢内容 | 各 1 failed；对应 `*-results.json`。军队实际入口是 army_roster，不是 army_detail |
| 同脚本 `shadow-log`：删除实际隔离诊断 | 3 failed、2 passed；`/tmp/1901-j11-shadow-log-results.json`。仍绿的纯 DB no-corruption 案不宣称保护日志 |
| `python /tmp/1901-j11-member-probe.py`：逐案生产函数删失、吞异常、遗失 CLI 只读参数、额外预算收入、错误 army_needed、取消日志变化优先级等 | 180 call failed；4 声明案普通模式 passed，另由 schema 模式验证。不计普通模式这 4 次绿为检出。`/tmp/1901-j11-members-results.json`、`/tmp/1901-j11-member-final.log` |
| 同脚本 `--schema`：变异实际公开 route/闭集/schema 声明 | 4 call failed；`/tmp/1901-j11-schemas-results.json`、`/tmp/1901-j11-schema-final.log` |
| 同脚本 `--only=tests/test_population_unit_648.py::test_new_save_regions_seed_persons_scale`：真正 seed 输出漏乘万人转换 | 1 call failed；`/tmp/1901-j11-seed-results.json`。单独进程使变异发生在模板 fixture 首次生产之前，不变异已缓存输入 |
| `python /tmp/1901-j11-web-members.py`，再以参数 `2 3 4 5 6 7 8 48 49` 重跑未定位成员 | 43 个唯一保留案实际 failed，4 条复用同一有效结果；`/tmp/1901-j11-web-members-complete.json` 中每条附生产入口及 Vitest JSON 路径；不是无匹配/构建错误 |
| `python /tmp/1901-j11-web-probe.py <mode>` | URL/timeout/runner、tax、map/army 兵力及月饷、聊天关闭、空关闭理由、递话条显隐、外链资源、暂停菜单错误 POST 均实际报红；各 `/tmp/1901-j11-web-*/result.json`，具体路径列于成员表。失败的早期驻军定位与聊天单按钮变异不计 |

Python 使用 `../Ming_LLM/.venv/bin/python`。源报告/测试源码可按上述路径直接核对；临时脚本是本轮取证物，不是安装或运行包的用户家目录前置。查阅并复用官方 JSONDecoder、pytest caplog/hooks 与已有 TypeScript/Vitest API，没有新增产品机制。

## 聚焦绿证据与成本

- `python /tmp/1901-j11-member-probe.py --green`：184 passed、1 skipped、1 warning / 9.12s；生产原样，覆盖被审计保留案及补充行为出处；`/tmp/1901-j11-member-green-final.log`、`/tmp/1901-j11-members-green-results.json`。
- `python -m pytest -q -p no:cacheprovider tests/test_fiscal_substrate_bridge.py tests/test_enrich_list_guards.py tests/test_character_knowledge_489.py tests/test_material_directory_1830.py tests/test_decree_commitment_creation_136.py`：274 passed / 16.54s；`/tmp/1901-j11-focused-final.log`。
- `cd web && npm test -- --no-cache src/components/drawers.test.tsx src/components/map.test.tsx src/components/gameMenu.test.tsx src/components/settlementFaces.test.tsx`：62 passed / 993ms；`/tmp/1901-j11-web-green-final.log`。随后 `tsc --noEmit -p tsconfig.json` exit 0，无输出。
- Python 本片无静态 typecheck 配置，不把 compile 冒称类型验证。`git diff --check`。

测试改动必要价值：恢复唯一消费者/诊断证明；合并同类 API/CLI 案；删除真实空验收而不造平行替代。最小成本为复用现有 fixture/入口并对实际结果或传递字段补一条必要断言；cap 案仅保留合法标识传递，容器案合并两坏值参数。SQLite/ASGI/DOM 属单机中型验证，不冒称纯单模块单测。不跑全量、不验真实宿主/模型，不修改本机安装或配置。
