# #875 Envelope 不变式全文票（Opus 转交 · 权威）

> 锚：**#875** / **#873 kill-axis** / **ADR 0129**（校验归写入点、runner 只查未决数）  
> 停窄轮 r5–r11 拉锯的唯一裁判文。实现与后续 cmr 必须服从本票。

## 背景（为何全文票）

S1 per-slice r5–r10 五轮全在啃同一未钉死点：runner「只数 count、不设 content court」定了，但没定 **count-only 遇到畸形 structured payload**（count=3 但 findings 空/长度不符）怎么办。  
r5「shape failure 不是 court」↔ r9「删 shape 协议法庭」= 同一不变式加深，不是新 bug。

## 裁决（直接套 ADR 0129）

### 1. 单一真源 = structured findings 数组

- **count 是数组的派生量**（open 行数 = 数组长度）。
- count **永不**作为独立字段被单独提供或单独采信。
- 「count=3 但数组为空」在设计上 **不存在**——因为 count 不是另填的数，就是数组数出来的。

### 2. shape 校验在写入/交卷点，不在下游读取点

- 复审员交结构化输出时，由 **写入接口 schema** 校验（字段齐；count 与数组自洽，或 **干脆不收 count 只收数组**）。
- 畸形 → **当场报错** 反馈写入方，由有判断力的复审员重交 / 全量重写（r6/r7「full rewrite、不 count 补、不凭空造 findings」= **写入点重试**，不是下游补数）。
- 这是 ADR 0129 写入点校验，合规。

### 3. runner / 下游信封只读派生 open-count

下游 **只做**：

- 读 structured findings 数组；
- **派生** open-count = 数组长度（或写入点已派生并保证自洽的只读视图）；
- 按三通道路由（exit / 未决数 / 决策门）。

下游 **禁止**：

- 再校验 count-vs-length；
- 按 shape 分叉命运；
- 补数、造 findings；
- 一切「count>0 但 structured 缺失/不符」的 durable abort / protocol court / infra 伪装（r5–r10 反复加的那些）——**整段删除**，错误层。

经过 §2 的写入点后，下游拿到的数组 **必然自洽**；没有畸形 payload 需要在下游处理。

### 4. kill-axis 澄清

| 合法 | 非法 |
|------|------|
| **写入点** schema（ADR 0129；写入方自纠） | **下游 runner** 对 worker 输出做 shape/质量法庭 |
| 三通道机械路由 | 换名字的「更温和」下游 validator |

### 5. 收敛判据

- 「count 与 structured 数组不符」在 **类型/schema 上不可表达**（count 无独立可采信入口；或写入点唯一入口且强制自洽）。
- 删光下游 r5–r10 畸形处理分支。
- 之后 per-slice 再提「count-vs-shape」类 finding = **复审员误解设计**，指回本裁决，**不再开新轮**。

## 实现扫描清单（§DELETE / §MOVE）

**DELETE（下游 `verifyCmr` / 读取路径）：**

1. findingsCount≠findings.length → abort  
2. count>0 无 structured → infra/protocol abort 或任何命运分叉（改为：不应到达；若旧数据则只派生 count=0/len 并三通道，不杀）  
3. 任何 runner 侧「补 structured / 凭 count 造 findings」  
4. 把 count 当独立权威字段与数组对质的逻辑  

**MOVE / KEEP（写入点 `classifyCmrOutcomePayload` / parse / writer）：**

1. 交卷 schema：**只收 findings 数组**（首选），或收 count 则 **必须** 与数组长度一致否则 **malformed 当场拒绝重交**（写入点，不是 live 路由法庭）。  
2. 解析成功后对外暴露：`findings` + **派生** `findingsCount = findings.length`（只读）。  
3. full outcome rewrite = 写入点重试路径，保留。  

**三通道 / 保留（非 court）：**

- `converged===false` → 永不 `recordCmrPassed`  
- 未决 open 数驱动 fix 派发  
- provider_degraded floor、真 infra、决策门  

## 测试钉

1. 写入点：count 与数组不符 → **parse/write reject**（malformed 重交），不进入「已成功 verdict 再在 verifyCmr 杀」。  
2. 成功 verdict：findingsCount **恒等于** findings.length（派生）。  
3. 下游 verifyCmr：**无** count-vs-length / count>0 无 findings 的 durable court 分支。  
4. `converged:false` 永不 cmr_passed。  
5. 既有 #875 存活测试与全量 `npm test` 绿。  

## 完成

单 commit：`codex: feat(orchestrator): #875 land Opus envelope invariant (ADR 0129 write-point)`  
自查二连：同型扫下游 court 清零；写入点 schema 自洽。  
**禁止**再为 count-vs-shape 开 r12。
