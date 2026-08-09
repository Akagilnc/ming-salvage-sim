# Prompt/Soul 锚定宪法 · 违宪扫描

**法源**：`ak-pi-workflow-roles/CLAUDE.md` —「锚定宪法」「Soul 内容纪律」「记账位」  
**范围**：`content/prompts/`、`orchestrator/prompts/`、`orchestrator/image/souls/`（只读）

---

## 1. 邸报用 `<<DECISION>>` 定界，代码正则抠块

**位置**：`content/prompts/season_simulator.md:137-142`（消费：`ming_sim/settlement_payload.py:42`）

**违反条文**：「对自由文本的正则/措辞/表头机械依赖……视同缺陷」

**证据**：
```
格式（严格 JSON……每块独立一行的 `<<DECISION>>` 与 `<<END>>` 包裹）：
<<DECISION>>
{"title":...}
<<END>>
```

**说明**：prompt 把固定措辞定界符写成输出契约，下游 `_DECISION_RE` 用正则从自由邸报抠 JSON——典型「机器咬呈现」。

---

## 2. 要求 `reason` 散文塞事件名，供代码子串匹配

**位置**：`content/prompts/score_extractor_personnel_secret.md:46`；同形见 `score_extractor_military_external.md:30`、`season_simulator.md:108`（消费：`ming_sim/issues.py:3611-3621`）

**违反条文**：「机器要消费的信息必须以键、typed 字段或 schema 提供」；「文案措辞被当协议字段」

**证据**：
```
……必须写 `人物变更`，并在 `reason` / `原因` 里带上事件名或战役名，供同一信封的世界状态主账闸识别。
```
（代码：`if event_id in reason_text` / `anchor in reason_text`）

**说明**：归属本该是 typed `event_id` 键；prompt 却教模型把锚点写进白话 `reason`，闸门靠措辞包含判定。

---

## 3. 把 schema 字段名嵌进自由叙事当「抽取线索」

**位置**：`content/prompts/season_simulator.md:108`

**违反条文**：「对自由文本的……措辞……机械依赖」；「呈现为人服务，随时可重排」

**证据**：
```
文中要明写足够具体的「地区变化」「军队变化」「人物变更」线索……使下游能把战果归属到本次事件
```

**说明**：把内部字段名当成邸报必须出现的协议措辞，呈现层与契约层焊死。

---

## 4. 让 LLM 做整数/白名单/枚举的机械契约校验

**位置**：`content/prompts/score_extractor_shared.md:11`

**违反条文**（对照法源§0 精神 + 本路「该由代码做的机械校验」）：「『要求 X』不是授权代码检查 X」之对偶——机械形状校验应在 runtime，不应塞进角色注意力

**证据**：
```
3. **逐条核对契约**：……增量是整数、key 来自合法 id 集、正负方向对、单位对……受控枚举值合法。不合规的就改对或丢弃……
```

**说明**：integer / id 集 / 枚举合法性是确定性校验；prompt 逼 LLM 代跑，稀释专业抽取判断。

---

## 5. 让 LLM 对照盘面数值做 `resolve_condition` 机械结案

**位置**：`content/prompts/score_extractor_issues.md:138`

**违反条文**：同上——机械阈值比对属代码职分

**证据**：
```
`resolve_condition` 若含可量化阈值（如「民心>60」「unrest<30」……），直接拿 input 里……**当前数值**对照——阈值已达标就必须写 `结案局势 resolved`
```

**说明**：数值阈值达标判定是确定性运算；却写成档房书办必须在心里做的硬规则。

---

## 6. Collector soul 塞满 CLI/字段名/transport（非专业判断）

**位置**：`orchestrator/image/souls/collector.md:29-76`（同形污染：`verify.md:20-50`）

**违反条文**：Soul 内容纪律 —「字段名称、类型……→ Tool / output schema」；「只是 transport/API 说明的内容留在 schema」；准入检查第 2–3 问

**证据**：
```
| `$CLI progress-classify --round N --head H --pr P` | …
| `$CLI evidence-put …` | …
……交卷 `cargoPointer=<handle>` + 可选 sidecar body
```

**说明**：操作规程、精确字段名、CLI 形参占满注意力预算，违背「Soul 不是完整说明书」。

---

**orchestrator/prompts/**：抽查未见新增「STEP_COMPLETE 口令」类违例（多处明文禁口令）；typed `<tag>` + schema 字段属契约通道，未列入。`route-smoke.md` 的 exact nonce 是凭证探针契约，不记。
