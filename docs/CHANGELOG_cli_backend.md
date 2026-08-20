# CLI 后端探针 — 把 LLM 从「api key 调远端」换成「本地 agy/codex」

> 一句话:**游戏现在能脱 api key 跑——LLM 后端改走本机的 agy(默认)/ codex CLI,纯 subprocess,合规、机器本地、不兼容别的机器(探针预期)。**
>
> 分支:`probe/session-as-llm`(基于 `origin/main` @ `d566ea6`)。日期:2026-06-07。

---

## 0. 这是什么 / 为什么

探针主目标的一刀:验证「不依赖商业 api key 也能玩」。原游戏 LLM 走 `OpenAIChat`(agno)→ HTTP + api_key。本次把这一层在**单一咽喉点**换成本地 CLI 自治 agent(agy/codex),其余游戏逻辑一行未改。

**为什么不走 HTTP proxy**:把 agy/codex 包成 OpenAI 端点 = 把 CLI 当 API 转售,违反两家使用条款。纯 subprocess 调用合规。

**为什么能成**(关键事实,挖过别重来):
- `create_chat_model()` 是**唯一咽喉点**——8 个 Agent 创建点(大臣/写诏/推演/打分/sanitizer/章节记忆/结局/烟测)全过它。改它的返回值 = 整个真游戏换后端。
- 除大臣外全是「文本进文本出」,映射 CLI 干净。
- 大臣的 agno 工具**非必需**:查名册/地区是 DB 纯函数,而盘面快照游戏本就注入进大臣 system prompt(实测大臣能报对国库真值 1781);下旨/退下/换人在 terminal.py 里本就有纯文字退路。所以大臣退化成「纯文本进谏」,不接 agno function-calling 也能玩。

---

## 1. 改了哪些文件

| 文件 | 改动 | 性质 |
|---|---|---|
| `ming_sim/cli_backend.py` | **新增**。`CliChat(OpenAIChat)` 只覆盖 `invoke`/`response_stream`,subprocess 调 agy/codex,把文本包成假 `ChatCompletion` 交回 agno 原生 `_parse_provider_response`。含 warm-keychain + retry、结构化 trace。 | 探针核心 |
| `ming_sim/llm_model.py` | `create_chat_model` 读 `MING_SIM_LLM_BACKEND`,为 agy/codex 时返回 `CliChat`;`verify_llm_available` 在 CLI 后端时跳过网络烟测。 | 接线 |
| `ming_sim/llm_config.py` | `load_llm_config` 在 CLI 后端时跳过「请输入 API key」交互、用占位符。 | 接线 |
| `ming_sim/tools.py` | 修上游潜伏 bug:`query_court_roster` 用了未定义的 `_ctx`(应为别名 `_content_ctx`),原版只要大臣查在朝名册就 `NameError`,被 agno 工具异常吞掉没人发现。 | 上游 bugfix(已授权) |
| `scripts/cli_tools_probe.py` | **新增**。只读探针:独立进程重建 context、复现大臣 10+ 只读工具,验证「GameSession 之外工具输出正确」。 | 验证工具 |
| `scripts/agy_turn_probe.py` | **新增**。非交互探针:跳大臣对话,塞诏书 → 推演 → HITL 决策点自动选第一项 → 4 模块 extractor → 落库 → end_turn,打印邸报 + 盘面 diff。 | 验证工具 |

**未改 / 不碰**:agno function-calling、大臣核心逻辑、结算管线、schema 契约、web 层。原 api key 路径完整保留(不设 env 时走原 `OpenAIChat`,零影响)。

---

## 2. CliChat 怎么工作(架构)

```
agno Agent.run()
  → model.response() / response_stream()      ← 复用 agno 原生
    → CliChat.invoke()                         ← 唯一覆盖点
        ├ _messages_to_prompt(messages)        把 agno Message 列表压成单 prompt
        ├ subprocess 调 agy -p --sandbox       (warm keychain + retry×4)
        ├ _fake_completion(text)               文本 → 假 ChatCompletion
        └ self._parse_provider_response(...)   ← 复用 agno 原生解析
```

- **不传 tools**:无 function-calling,大臣只出文本。
- **流式**:`response_stream` 委托给非流式 `response()` 产单个 chunk(agy 一次出全文,无真增量);上游 `run_agent_stream_text` 的事件循环照常消费。
- **JSON**:extractor 的严格 JSON 由其 `.md` system prompt 自带要求;实测 agy 首次即吐合法 JSON,连兜底 sanitizer 都没触发。`_messages_to_prompt` 另对 `response_format=json_object` 的调用追加硬约束兜底。

调用约定遵 wiki(`codex-bot-conventions.md` / `cross-model-review.md`):agy 先暖 keychain(auth 是 race)+ retry,`--sandbox`;codex `exec -` 走 stdin pipe。

---

## 3. 验证结果(真数据)

**整回合脱 key 跑通**(turn 12,1628年9月,probe.db),7 次 agy 调用 ~131–150s:

| 环节 | 结果 |
|---|---|
| 写诏 decree | ✅ 正经诏书 |
| 推演 simulator | ✅ 邸报叙事 + HITL 决策点 |
| HITL 暂停→提交 | ✅ |
| 4 模块 extractor JSON | ✅ **全部一次解析成功,未触发 sanitizer** |
| apply 落库 | ✅ 国库 1781→1587、内库 2796→3108(金手指建筑在工作) |
| 章节记忆 | ✅ 产 `{body,tags}` 并入库 |
| end_turn | ✅ 推进回 SUMMONING |

**交互式真游戏**(`python main.py`)脱 key 启动:大臣毕自严入殿,用文言作答且**盘面数字正确**(「国库千七百八十余万两」= DB 真值 1781)——证明路 B 的事实注入是游戏内建的,大臣不靠工具也有据。

---

## 4. 日志 / 可观测性

| 来源 | 路径 | 内容 |
|---|---|---|
| **结构化 trace**(默认开) | `scripts/runs/cli_trace_<pid>.jsonl` | 每次 LLM 调用一行:序号 / **agent 标签**(大臣/写诏/推演/extractor/章节记忆,已验证标对) / 耗时 / 重试 / prompt 全文 / 响应全文 |
| 游戏 stdout | 需 `tee` | 确定性结算细节:实际落库 delta、事项推进、结局判定、数值变化 |

开关:`MING_SIM_TRACE=0` 关 trace、`MING_SIM_TRACE_PATH=...` 改路径、`MING_SIM_LLM_DEBUG=1` 调用摘要打屏、`MING_SIM_DUMP_LLM=1` 额外 dump 原始 agno messages。

---

## 5. 怎么玩

```bash
MING_SIM_LLM_BACKEND=agy MING_SIM_DB=data/probe.db \
.venv/bin/python main.py 2>&1 | tee scripts/runs/play_$(date +%m%d_%H%M).log
```

- `MING_SIM_LLM_BACKEND=agy`:走本地 agy(必需,否则回原 api key 路径)。
- `MING_SIM_DB=data/probe.db`:用现有存档(turn 12,含金手指);开新档去掉这行用默认 `data/ming_sim.db`。
- 机器前提:本机已装并登录 `agy`(`~/.local/bin/agy`)。换 codex 后端:`MING_SIM_LLM_BACKEND=codex`。

---

## 6. 已知缺口 / 待办

- **token 统计抓不到**:`[TOKEN-SUMMARY] no LLM calls captured` —— token hook 挂在 OpenAI HTTP client 上,CLI 后端绕过了(agy 本也不报 token)。cosmetic,trace 里有字符数可估。
- **速度**:agy ~15–25s/次,一回合 7 次结算调用 + N 次大臣对话 ≈ 分钟级。探针可接受。
- **大臣工具未接**:当前大臣纯文本进谏。若要恢复「大臣按需查名册/地区」,需让 codex/agy 自己 call CLI 工具脚本(`scripts/cli_tools_probe.py` 是地基),或预解析注入——探针阶段先不做。
- **🔴 试玩暴露两个待修(2026-06-07,详见 [TODO.md](TODO.md) B2/B3,已拍板一起改)**:
  - **B2**:agy 没设 cwd,继承游戏仓库当 workspace → 自治探查源码、英文行动计划泄进大臣对话(孙承宗开口说英文)+ 元游戏泄漏。修法 = cwd 隔离到空目录 + prompt 加固 + 剥英文兜底。
  - **B3**:大臣聊天里「拟旨/下密令」不入档(动作工具无 function-calling)。修法 = 文本协议桥接,合成 tool_call 复用现有入档逻辑。查询类不受影响(盘面已注入)。
- **红线**:本改动**仅本地探针**。公开/商用前须净重写,且在此之前不 push 到公开仓库(沿用项目 CLAUDE.md)。

---

## 7. #1256 闸脚本 runner 扩缝（2026-08-19）

- `cli_backend` 新增 `cursor` / `kimi` / `grok` 三 runner（opencode **不**入清单，走 api 通道）。
- 名单单源：`_CLI_BACKENDS` / `GATE_CLI_RUNNERS`；月末多 extractor 并发对所有 runner 一视同仁（无按模型串行白名单）。
- 四闸脚本 `--channel api|cli` + choices 共享；ds-flash 群友基线走 OpenCode Go `https://opencode.ai/zen/v1`。
- 用法与基线纪律见 [`LLM_BACKEND_BENCH.md` §十三](LLM_BACKEND_BENCH.md)；端点核实 [`evidence/issue-1256-opencode-go-ds-flash-api.json`](evidence/issue-1256-opencode-go-ds-flash-api.json)。
