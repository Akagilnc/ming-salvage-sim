# LLM 后端基准 — 崇祯模拟器探针

> 日期：2026-06-07　分支：`probe/session-as-llm`
> 目的：探针要把游戏 LLM 后端从「api key 调远端」换成本机 CLI（agy/codex）或 `claude -p`。
> 本文比较候选后端在游戏各 LLM 角色上的**质量 / 速度**，给选型依据。
> 全部原始产物（输入 prompt / 各模型输出 / 日志 / 脚本）存于 [docs/raw/](raw/)。

---

## 一句话结论

- **建 issue（结构化落库）**：codex 系（5.5 / mini / spark）最稳，spark 最快；agy 偶发漏 `origin_kind` 被拒。
- **叙事（邸报 / 大臣奏对）**：claude（sonnet/haiku）味道最像人、最懂盘面；codex 系信息密度高但偏公文报告体；agy 够用。
- **速度可用档（simulator ~40-50s）**：`gpt-5.3-codex-spark`、`gpt-5.5`、`agy`、**`haiku4.5 + MAX_THINKING_TOKENS=10000`**。
- **淘汰（交互）**：`sonnet4.6`（simulator 5-7 分钟，生成吃时间，关思考也救不动）、`gpt-5.4-mini`（漏 `<<DECISION>>` 块，砍 HITL 功能）。
- **真正的在位 baseline = Opus 4.8 在 session 里直接当 LLM**（形态1），它建了现存档绝大多数国策，本基准**未把它当受测项**——见 [§8](#八重要纠正probedb-是谁建的)。

---

## 二、方法学局限（必读，先泼冷水）

这套基准有三处硬伤，结论要照此打折：

1. **单快照、非真实多回合**。建 issue 与各 extractor 都只喂了**同一条冻结的 prompt**（取自 `cli_trace_32408` 的某个真实回合快照，约 1628 年 11 月）。LLM 输出非确定，单一场景跑 N 次估出的"成功率"方差极大，**不代表真实游戏跨回合的表现**（见 §7 的实证反例）。
2. **并发竞争污染计时**。全角色批次用并发 5（部分还混着 codex 互抢），排队/抢占噪声会盖过模型本身的速度差。**唯一干净的速度数据是 [§6](#六claude-思考预算变量清洁串行) 的串行 4 跑**。
3. **质量判定分两类**：结构化（issue/extractor）可程序判 JSON 合法+字段；叙事（simulator/minister）**程序判不了，靠人看原文**（原文全在 [docs/raw/02_narratives/](raw/02_narratives/) 与 [03_thinking_serial/](raw/03_thinking_serial/)）。

---

## 三、测了什么

- **后端 7 个**：`gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini` / `gpt-5.3-codex-spark`（codex，reasoning=medium）、`agy`（默认）、`sonnet4.6` / `haiku4.5`（走 `claude -p`）。
- **角色 9 类**（取自真实 trace）：simulator(邸报)、minister(大臣奏对)、decree(拟旨)、chapter_memory(章节记忆)、extractor×4(issues/经济internal/军务external/人事密令personnel)、secret_extract(密令聚焦)。
- **专项**：建 issue 5×5；claude thinking 预算变量。

---

## 四、建 issue 专项（5×5，reasoning=medium）

> 数据：[docs/raw/05_logs/bench.log](raw/05_logs/bench.log)、[results_issue_5x5.json](raw/04_structured_raw/results_issue_5x5.json)

| 后端 | 落库成功 | origin_kind对 | 解决效果填 | 失败效果填 | 推进有效(均值) | 速度 s(min/中/max) |
|---|---|---|---|---|---|---|
| **gpt-5.5** | 5/5 | 5/5 | 5/5 | 4/5 | 0.0 条 | 24/27/29 |
| gpt-5.4 | 4/5 | 4/5 | 1/5 | 1/5 | 1.8 条 | 28/34/41 |
| **gpt-5.4-mini** | 5/5 | 5/5 | 5/5 | 1/5 | 2.0 条 | 55/69/93 |
| **gpt-5.3-codex-spark** | 5/5 | 5/5 | 0/5 | 0/5 | 2.0 条 | 11/14/16 |
| **agy** | 2/5 | 2/5 | 0/5 | 0/5 | 0.4 条 | 19/21/96 |

- 落库成功 = 产了新立局势 **且** `origin_kind=decree`（能过落库的硬指标）。
- **agy 唯一漏 `origin_kind`**：它把 `decree` 填进了 `可撤销`（且写成不存在的别名 `可否撤销`），漏填 `来源类型` → 落库静默拒（实锤见 `scripts/runs/web_server.log:97`）。**但这是单快照下的偶发，不是常态**，见 §7。
- effect 填充：只有 5.5 / mini 肯填 `解决效果`；spark/agy 从不填（靠 `enrich_initiative_effects` 兜底）。

---

## 五、全角色结构化（自动判，每模块×2 跑）

> 数据：[docs/raw/05_logs/bench3.log](raw/05_logs/bench3.log)、[bench2.log](raw/05_logs/bench2.log)；codex 输出剥壳后重抽（见 §9 坑）。

| 后端 | JSON 合法率 | 平均非空字段 | 平均耗时 s |
|---|---|---|---|
| gpt-5.5 | 8/8 | 3.0 | 18 |
| gpt-5.4 | 8/8 | 2.4 | 23 |
| gpt-5.4-mini | 8/8 | 2.1 | 30 |
| gpt-5.3-codex-spark | 8/8 | 1.9 | 11 |
| sonnet4.6 | 8/8 | 2.6 | 60 |
| haiku4.5 | 8/8 | 1.8 | 43 |
| agy | 8/8 | 2.1 | 34 |

**结论：结构化抽取大家都行（全 8/8 合法）**，非空字段数只是弱代理（字段多≠对）。结构化不是区分点。

---

## 六、叙事质量（simulator 邸报）

> 全文：[docs/raw/02_narratives/simulator__*.txt](raw/02_narratives/)（七后端各 1 份）

| 后端 | 字数 | 耗时 s* | 人工评要点 |
|---|---|---|---|
| gpt-5.5 | 3729 | 47 | 机理扎实：「红夷炮利在倚城拒敌、不利野战」，点佛山铸炮厂/潞安铁冶所；DECISION 稳 |
| gpt-5.4 | 5217 | 60 | 最详尽，多一整节「军国大势」扫辽东/陕西/江南；偏长 |
| gpt-5.4-mini | 2524 | 87 | 偏薄，**漏了 `<<DECISION>>` 块**（砍 HITL） |
| gpt-5.3-codex-spark | 3672 | 20 | 标题《蓟塞有尘》好；自填账目数（盘面未必对，有臆造风险）；偶多产越界 DECISION |
| **sonnet4.6** | 6830 | 见§7 | **最深**：唯一抓到「毕自严职衔悬置」盘面矛盾、毛文龙皮岛虚报、魏忠贤东厂筹码 |
| haiku4.5 | 3218 | 见§7 | 聚焦言官攻讼；奏对最有戏（见 minister）；DECISION 齐全 |
| agy | 3431 | 38 | 合格在角色；短板在建 issue 不在叙事 |

\* codex/agy 耗时来自并发批次，有噪声，仅供相对参考。

minister 大臣奏对全文见 [docs/raw/02_narratives/minister__*.txt](raw/02_narratives/)。**人工评：sonnet/haiku 的孙承宗奏对最像人**——主动提「红夷炮非一蹴」、荐徐光启西学炮师、点破密饷政治风险并给「修缮墩台/月课火器遮掩」的具体话术。codex 系更像「信息齐全的公文」。

---

## 七、claude 思考预算变量（清洁串行）

> 全文：[docs/raw/03_thinking_serial/](raw/03_thinking_serial/)。这是**唯一零并发竞争**的速度数据。

| 跑 | 耗时 | 字数 |
|---|---|---|
| sonnet 限制10k | 398s | 5456 |
| sonnet 不限制(默认满开) | 336s | 6239 |
| **haiku 限制10k** | **43s** | 3539 |
| haiku 不限制 | 189s | 5951 |

两个模型对「限思考」反应**相反**，是真效应不是噪声：

- **sonnet：限不限都没用**（398 vs 336，限制甚至略慢）。它跑 simulator 是**生成 5-6 千字本身慢**，思考占比小，关了也救不动，稳定 ~350s。
- **haiku：限思考省一大截**（189s → **43s**，快 4.4×），质量没被砍坏（邸报五节俱全 + 两个 DECISION + 盘面追踪到位）。

**这推翻了「`claude -p` 一律太慢」的早期一刀切**：那是因为最初拿 haiku 默认重思考 + 并发竞争测的。`haiku4.5 + MAX_THINKING_TOKENS=10000` 的 simulator = **43s**，与 codex spark(20-39s)、gpt-5.5(47s)、agy(38s) 同档。

> 保留：43s 是单样本，haiku 计时波动大（43 串行 vs 184 并发），要定主力得再串行重复 2-3 次确认稳。

---

## 八、重要纠正：probe.db 是谁建的

`data/probe.db`（现 turn 17 / 1629年2月）存有 17 条 `origin_kind=decree` 国策。**绝大多数是 Opus 4.8 在 session 里建的（形态1，本探针 step1），不是 agy。**

| issue | 立项回合 | 实际后端 |
|---|---|---|
| id 4–18（清丈/西学/练秦兵/太学府/蓟宣备虏…14 条） | turn 1–8 | **Opus 4.8 在 session 里** |
| id 19、20（公费稽查、禁摊派） | turn 16 | agy |

含义：

1. **不能拿 DB 给 agy 的建 issue 能力平反**——那 14 条是 Opus 4.8 的功劳。agy 真实战绩只有 turn 16 一回合（成 2 条）+ §4 那次被拒，样本太小。
2. **真正的在位 baseline（Opus-4.8-in-session）本基准没测**。DB 证明它最强（一整年建 14 条连贯国策），这正是「session as LLM」探针要验证的。选型的真实参照系是：**Opus-in-session（强，但只在对话里，step2 才想搬进 subagent）** vs **codex/agy/haiku（能脱离对话、走订阅额度，各有短板）**。

---

## 九、工程坑（实测撞出来的）

1. **codex 必须 `--skip-git-repo-check`**：项目 `_run_codex` 用 `cwd=/tmp/ming_agy_sandbox`（非 git 目录）却没传此 flag → 一调就报 *"Not inside a trusted directory"* 秒失败。`ming_sim/cli_backend.py:150` 待补。
2. **codex 并发必须 `--ephemeral`**：并发跑多个 `codex exec` 会撞共享 session 状态（`failed to record rollout items: thread not found`），导致最终消息丢空。加 `--ephemeral`（不落盘 session）解决。
3. **codex 输出要剥壳**：`codex exec` 把干净最终消息打到 **stdout**，日志噪声打到 **stderr**；合并后用「`OpenAI Codex v` 之前的部分」= stdout = 干净答案（`--ephemeral` 下最终消息在文件顶部）。
4. **claude 思考用 `MAX_THINKING_TOKENS` 控**（Claude 无 gpt 的 `reasoning_effort` 档；~10k≈medium）。`claude -p` 默认重思考，短调用会慢，务必显式限制。

---

## 十、选型结论

- **可用主力（~40s 档）**：`gpt-5.3-codex-spark`（最快+建issue满分，effect 空靠 enrich 补）、`gpt-5.5`（叙事机理最扎实+字段最全，慢一档）、`agy`（够用，建 issue 偶漏靠落库容错兜）、`haiku4.5+10k思考`（叙事最像人，待确认计时稳定）。
- **淘汰交互**：`sonnet4.6`（5-7 分钟，生成 bound，救不动；但叙事最深，可留离线鉴赏）、`gpt-5.4-mini`（漏 DECISION）。
- **落库容错（方向1）**：模型无关防御，接住 agy/codex 偶发漏 `origin_kind`；优先级中等（不是救崩溃，是补边角）。
- **下一步**：要 sonnet 那级叙事又要速度，只有走 **API**（可并发、无 CLI 启动开销、thinking 精调），`claude -p` 这条路对 sonnet 堵死、对 haiku 通。

---

## 十一、证据索引（docs/raw/）

| 目录 | 内容 |
|---|---|
| [00_inputs_role_prompts/](raw/00_inputs_role_prompts/) | 9 类角色真实 prompt（测试输入） |
| [01_issue_building/](raw/01_issue_building/) | 建 issue 单条 A/B + 4 模型原始输出 |
| [02_narratives/](raw/02_narratives/) | 七后端 × 各角色 干净叙事原文（28 份） |
| [03_thinking_serial/](raw/03_thinking_serial/) | claude 思考变量清洁串行 4 跑 + stderr |
| [04_structured_raw/](raw/04_structured_raw/) | codex RAW 壳 + 各 results.json |
| [05_logs/](raw/05_logs/) | 4 个基准运行日志 |
| [06_harness_scripts/](raw/06_harness_scripts/) | 6 个基准脚本（方法学证据） |

---

## 十二、2026-07-10 增补：大臣奏对中文叙事五模横评（毕自严卷）

> 起因：hy3（腾讯混元3）在 hermes/OpenRouter 限免（至 7/21）+ grok-4.5 / GPT-5.6 发布，用户令做小测试比中文叙事成色。
> 考卷：单场景「毕自严乾清宫奏对——太仓实存几何、辽东欠饷何时补齐」（persona+盘面+问题一体，200-400字奏对）。原始产物全存 [docs/raw/12_minister_bench_20260710/](raw/12_minister_bench_20260710/)。

### 方法学局限（先泼冷水，同 §二基调）

单场景 n=1、单判官（Fable 5 判卷）、各腿传输不同（hy3/ds-flash 走 hermes→nous、grok-4.5 走 Grok Build CLI、luna 走 codex CLI 钉 low 档、haiku 走 subagent）——文本质量与传输无关但延迟不可比。**要坐实排名须多场景采样**；本节结论只配当「谁值得进一步测」的初筛。

### 结果（五轴 ×10：语体保真/史实肌理/账目叙事化/角色纪律/文采张力）

| 模型 | 五轴合计 | 一句话画像 |
|---|---|---|
| **grok-4.5** | **47.5** | 「臣若妄称『数月可清』，是罔上也」——拒开空头支票本身即角色行为；敢提内帑；直臣人格全场最立体 |
| **deepseek-v4-flash** | **46** | 唯一把整数拆成「三百一十九万七千两有奇」、算出「可动支二百三十万」、搬出真考成法——账房肌理第一；群友基线名不虚传 |
| **hy3** | **45.5** | 「实解到库者十不及七」+ 最诚实时间表（一年半至二年）；好，但没超越 ds-flash，无档位优势 |
| gpt-5.6-luna (low) | 41.5 | 方案最果断（120万十日解辽东）但语体偏现代政务文，缺规制词 |
| haiku 4.5 | 36 | 「开空头支票」直接出戏，现代公文腔多处；不进叙事池（它的位置是快速机械活） |

### 选型影响

1. **§一「淘汰交互」与旧口径需修一条**：CLAUDE.md「xai（SuperGrok）中文叙事弱」是旧 grok 时代判词，**grok-4.5 单样本表现为全场第一**——待多场景复测后正式改判；建议给 grok-4.5 排一局真游戏（simulator 邸报 + extractor）验证长文。
2. **hy3**：中文奏对确实强但对 ds-flash 无档位优势；:free 7/21 到期、20 RPM/日限硬顶——白嫖期可当对照样本，不进承重选型。
3. **ds-flash 作为群友事实基线**，正式进本文档基线行——后续任何叙事后端候选先过它这一关。
4. 本卷（prompt.txt）固化为**叙事考察标准卷**，后续候选模型按同卷加测。

---

## 十三、2026-08-19 增补：judge-in-loop 闸脚本 runner / 通道用法（#1256）

闸脚本形制族（`scripts/promulgation_gate_561.py`、`break_rank_judge_gate_562.py`、`midzhi_spiral_judge_gate_570.py`、`family_tail_acceptance_570.py`）共享 CLI runner 缝；dispatch 只在 `ming_sim/cli_backend.py`，脚本只传名。

### 基线纪律（owner 令）

- **族尾闸（#570）新跑默认 ds-flash 档**：便宜、群友事实基线（§十二）。
- **opus / 高价 CLI 仅争议复裁与同基对照**，不作为族尾闸默认腿。
- **opencode 不入 runner 清单**：OpenCode Go 凭证是 API key，走既有 `channel=api`（key + base_url），不要再造 `opencode` CLI runner。

### CLI runners（`--channel cli`，默认）

| `--runner` | 本机 invocation（模型旗各 runner 如实） | 备注 |
|---|---|---|
| `codex` | `codex exec -` stdin | 既有（调用形含 `--ephemeral`，非并发护栏） |
| `claude` | `claude -p --output-format text` | 既有 |
| `cursor` | `cursor-agent -p --output-format text --trust [--model <id>]` | #1256；`--trust` 免非交互 workspace 信任闸 |
| `kimi` | `kimi -p <prompt> --output-format text [-m <alias>]`（**禁**与 `--yolo`/`--auto` 组合；只取 stdout） | #1256 |
| `grok` | `grok -p <prompt> --output-format plain [-m <id>] [--effort low\|med\|high]` | #1256 / §十二 grok-4.5 腿 |
| `pi` | `pi -p --mode text --no-tools [--model <provider/id>] [--thinking off\|minimal\|low\|medium\|high\|xhigh\|max] <prompt>` | #1274-qa-y1 / #1456；`--no-tools` 关内置工具 |

choices 单一真源：`ming_sim.cli_backend.GATE_CLI_RUNNERS`。非法名 argparse 拒收；`opencode` 不在 choices。

```bash
# CLI 例（需新鲜 MING_SIM_TRACE_PATH）
MING_SIM_TRACE_PATH=/tmp/gate-trace.jsonl \
  python scripts/family_tail_acceptance_570.py \
    --runner kimi --model <alias> --samples 1 \
    --output docs/evidence/issue-570-acceptance-kimi.json
```

### API 通道（`--channel api`）— ds-flash / OpenCode Go

OpenCode Go OpenAI 兼容端点（#1256 实测写死）：

- **base_url**：`https://opencode.ai/zen/v1`
- **model id**：裸名 `deepseek-v4-flash`（**不要** `opencode-go/deepseek-v4-flash`）
- **key**：`~/.local/share/opencode/auth.json` 的 `opencode-go.key`，经 `--api-key` 或 env（`MING_SIM_API_KEY` / `OPENAI_API_KEY`）注入，**不落库**
- 端点核实 + 冒烟记录：[`docs/evidence/issue-1256-opencode-go-ds-flash-api.json`](evidence/issue-1256-opencode-go-ds-flash-api.json)

```bash
# 族尾闸新跑默认 ds-flash 档
export MING_SIM_API_KEY="$(python3 -c 'import json,pathlib;print(json.loads(pathlib.Path.home().joinpath(".local/share/opencode/auth.json").read_text())["opencode-go"]["key"])')"
export MING_SIM_API_BASE_URL=https://opencode.ai/zen/v1
python scripts/family_tail_acceptance_570.py --channel api \
  --model deepseek-v4-flash --samples 1 \
  --output docs/evidence/issue-570-acceptance-ds-flash.json

# 争议复裁 / 同基对照才上 opus（CLI）
MING_SIM_TRACE_PATH=/tmp/gate-opus.jsonl \
  python scripts/family_tail_acceptance_570.py \
    --runner claude --model claude-opus-4-8 --samples 1 \
    --output docs/evidence/issue-570-acceptance-opus-rejudge.json
```

证据 JSON 的 `method.config` / 顶层 `config` 块：`channel` / `runner` / `model` 如实（api 时 `runner=""`）。
