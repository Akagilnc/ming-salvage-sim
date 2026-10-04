# #1901 J3/J11 判词重交（6ea2fb530 后）

本页是施工回执证据，不是合并、关票或审官结论。受理冻结判词 run `01a0f9ed-190c-75bb-b53b-ce5e1e585903`；票面用 `gh issue view 1901 --repo Akagilnc/ming-salvage-sim --json body` 实读。沿用两类全文，不限定 signature、dir、usage 或军饷几个样本。

## 全仓枚举与复扫

J3：所涉既有测试只认契约和外部行为；非契约源码、名称、呈现依赖，等价源码或同义措辞误红；包括归一化、散文解析及禁句扫描。
J11：删改丢失必要输入传递、诊断事实、业务负向条件、时序及数值不变式；空验收；不能用入口 KO 代替具体行为证明。

本轮执行以下命令，临时输出只写自建 `/tmp/1901-w5-repair/`。所有断言都进候选全集，专项 grep 只用于分类，**不是成员资格的收窄谓词**。

```sh
git ls-files '*test*' '*spec*'
rg -n 'assert|expect\(' $(git ls-files '*test*.py' '*test*.ts' '*test*.tsx')
rg -n 'getsource|signature\(|__code__|__dict__|__module__|__name__|__dataclass_fields__|\bdir\(|hasattr|ast\.|read_text\(|readFileSync|toString\(|raw_decode|\.index\(|json.loads|toHaveTextContent|toContain|toMatch|textContent|innerHTML|outerHTML|querySelector|caplog|mock_calls|re\.(search|match|findall)|pytest.raises.*match=' $(git ls-files '*test*.py' '*test*.ts' '*test*.tsx')
git diff 0ca77fecc HEAD -- tests web/src '*test*'
git diff 192603c52^ HEAD -- tests web/src
```

首扫：268 个 test/spec 路径；14701 行断言/断言相关候选；1785 行专项候选。已打开完整专项结果，结合既有删减成员表双向复核，未将 grep 命中直接判罪。全仓不是只扫 `tests/` 和 App。仓内其他 test/spec 路径是规格、历史证据或文档，不是另一个可执行测试体系。

空案机械枚举复用 [上一回执的 Python AST 与 TypeScript compiler 命令](issue-1901-j3-j11-w5.md)，Python 路径改用 `git ls-files '*test*.py'`；断言 helper 同时认 `_assert*`。输出：Python 2960 个 test 函数，仅 `test_enrich_list_guards.py::test_inertia_ongoing_non_dict_no_crash` 一个候选；Web 26 文件、327 回调、0 空案。该 Python 案按判词维持保留：真实月漂移消费四种持久非对象 effects，以不抛异常为独立契约，判词已以移除守门后的真实 AttributeError 核验，不能再删成解析器单测。没有把所有“不抛”案机械视为空验收。

## 成员表与处置

历史 J3 全类成员采用 [既有 J3 成员表](issue-1901-j3-j11-w5.md#j3-成员表与处置)，历史 J11 采用 [210 条完整成员表](issue-1901-j11-members.md)。这些是成员身份/历史处置引用，不是继承旧“核销”措辞或入口 KO 证明。本轮修订如下，其余既有成员未撤销必要行为断言，未恢复反射或名称扫描。

| 类 / 成员 | 当前处置及观察面 |
| --- | --- |
| J3，`test_deepseek_thinking_disable_1797.py::test_dump_llm_messages_records_reasoning_usage_finish_reason`（P039/P133） | 删除首个 `{` 定位及混合散文 JSON 解析。包装既有标准库真实 `json.dumps`，记录实际输入对象和实际返回值，断完整 metrics 对象的编码确实传入磁盘文件。没有 mock 序列化结果、标题/键序/空格锁或新生产钩子。 |
| J11，同上 | 保留 100/20/120/42 全部 usage 数据、两路 reasoning、两种 finish_reason 容器证明；补正文输入原样落盘断言。 |
| J11，App「只读组逐面可达且吃月初叠影；关闭组不可达且半程面不泄漏」（W004） | 真实 App 开经济面；名义应发输入进入真实金额 formatter，其实际输出到抽屉；三项已结算输入未进入展示通道。 |
| J11，App「phase=awaiting_decision：核账门控唯一谓词=settlement_display，同样隐藏半程结算三项」（W005） | 同上，覆盖真实等待批红相位；不是只验抽屉存在。 |
| J11，App「月完后 settlement_display=false：关闭组入口恢复；递话条收；局势半程面重现」（W006） | 名义应发及实拨/到达/损耗四项真实数值输入与实际格式化输出均到经济面；仍保留月份展示门控及关闭组恢复行为。 |

保留候选依据：JSON/JSONL/SSE、SQL 字段、CLI argv、显式材料工具名是形式/结构契约；注入异常原样传递及夹具正文原样显示不是生产散文措辞锁；固定菜单/按钮/界面标题与用户交互定位不是 LLM 叙事模板。DB 数值、人口守恒、预算合计、知识来源边界及失败段终态断言照留。`release_bundle_assets` 执行实际 PyInstaller spec 装配，不是源码等价写法 oracle。上述候选不通过恢复旧单位、标签、排版或自由文本数字解析来补证明。

复扫：`raw_decode`/`text.index` 的 dump 定位无残留；签名/源码反射和模块 dir 名称扫描没有恢复。两处改动只复用既有四案及实际标准库/格式化边界，保留生产真实实现；局部共享军饷断言避免三案平行规则，describe 结束恢复 spies。

## 验证证据

以下每个测试命令均以前缀执行（含临时副本探针）：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
```

- `../Ming_LLM/.venv/bin/python -m pytest -q tests/test_deepseek_thinking_disable_1797.py`：首轮 **21 passed / 1.00s**。
- `cd web && npm test -- --no-cache src/appDurableWiring.test.tsx -t '只读组逐面可达|phase=awaiting_decision：核账门控|月完后 settlement_display=false'`：首轮 **3 passed、51 skipped / 1.06s**，测试体 274ms。
- `cd web && ./node_modules/.bin/tsc --noEmit -p tsconfig.json`：exit 0、无输出。Python 本片无配置静态类型检查，不冒称 typecheck。

确定性变异真跑（不新增永久测试）：

| 命令 / 变异 | 真实入口结果 |
| --- | --- |
| `PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1901-w5-repair/python_probe.py`：进程内只改 dump 标题为 `{usage/metrics}`；旧案从 `git show HEAD:<test path>` 写入自建临时文件 | 旧案 **1 failed / 0.05s**（JSONDecodeError）；修后 **1 passed / 0.18s**。 |
| 同命令：仅删除实际 metrics 落盘 append | 修后 **1 failed / 0.04s**（usage 对象及编码传递证明失败）；恢复 **1 passed / 0.02s**。各轮 `RESTORED True`。 |
| `../Ming_LLM/.venv/bin/python /tmp/1901-w5-repair/web_probe.py`：临时 Web 副本 ArmyPaySection 返回 null | **3 failed / 742ms**。 |
| 同命令：仅关闭 settledArmyPay 展示分支，保留名义应发 | **1 failed、2 passed / 847ms**，与判词同一失效形状。 |
| 同命令：金额 formatter 等价改成 `银 ${value}（万两）` | **3 passed / 855ms**，不锁旧单位排版。 |
| 同命令：恢复真实生产 | **3 passed / 874ms**；每轮 `RESTORED True`。 |

首次标题探针准备把花括号未转义地放进 f-string，出现 NameError，不是等价变异红证据；已改成双花括号后重跑，上表仅计正确探针结果。不洗白准备失败。探针用源 AST 提取当前真实函数并保持原 globals，结束恢复函数；Web 仅动自建临时副本。没有在工作树改生产。

最小必要成本：不新增测试案、生产机制或平行测试体系；一个真实序列化输入/结果观测，三个既有 App 案共用一条金额输入→真实格式化结果→抽屉的断言。查阅 Python 官方 `unittest.mock` 文档的 wraps 约定并采用真实调用透传；仓内已有 formatter 与标准库 json 足够，不造序列化、扫描兼容、日志或通用组件。诊断 skill 的多假说/新仪表阶段不重做：冻结判词已给两类最小可重现原因，本轮用同形变异直接复核；永久回归复用既有案而非另造证明测试。

最终施工状态复验同一聚焦命令：Python **21 passed / 0.67s**；Web **3 passed、51 skipped / 903ms**（测试体262ms）；`tsc` exit 0；`git diff --check` 无输出。最终专项复扫只有 `test_centrifuge_ledger_690.py` 文档字符串里的 `inspect.signature` 历史说明命中，不是执行断言。自建临时根随后清理。

只跑触及面聚焦测试，没有全量、真实模型/网络验收，没有修改席位、宿主配置、Soul、宪法或 ADR；没有 amend、stash、push 或 PR。本轮剩余审面仍交大理寺裁决。
