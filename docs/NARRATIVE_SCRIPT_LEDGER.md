# Narrative Script Ledger — 回合三栏账

> 一句话：不引入外部 narrative canvas 产品，只借用「按时间片对齐 interaction / context / system」的思想，把每回合做成可审计的叙事对账单。

## 为什么需要它

当前探针最容易穿帮的地方不是「LLM 不会写」，而是：

- 玩家下旨了，邸报也写成了，但 DB 没有对应状态。
- 对话语境里发生过的事，context restore 后蒸发。
- 月饷、建军、任官、排程这类机械后果只活在叙事里，下一月读盘就账实不符。

所以这里借用 Narrative Studio / Canvas & Scripts 那种三层时间脚本思路：

- `Interaction`：玩家 / 皇帝在这个时间片做了什么。
- `Context`：当时叙事语境、人物动机、局势压力、已承诺事实是什么。
- `System`：数据库、delta、issue、财政、军队、人物状态实际发生了什么。

目标不是画故事树，而是把「玩家意图 → 叙事承诺 → 系统落库」绑在一起。

## 和 Narrative Design Canvas 的关系

Narrative Design Canvas 更适合概念期，用来校准：

- 玩家做什么。
- 故事发生什么。
- 玩家应该感到什么。

它回答的是「这个互动叙事应该是什么体验」。

回合三栏账回答的是另一个更工程的问题：

> 这个回合声称发生的事，是否真的进入了系统状态？

因此本项目暂不引入外部 canvas 工具、不上 MCP、不做可视化编辑器。先把它做成 driver / 结算后的审计结构。

## 基本结构

每个回合拆成若干时间帧：

```text
Frame 1 召见
Frame 2 拟旨
Frame 3 颁诏
Frame 4 邸报推演
Frame 5 delta 落库
Frame 6 下月读盘
```

每个 frame 固定三栏：

```text
Interaction:
  玩家 / 皇帝输入、选择、追问、下旨、亲裁。

Context:
  局势压力、人物动机、已知事实、叙事承诺。

System:
  真实 DB / delta / applied 结果。包括 metrics、issues、fiscal_config、
  armies、characters、regions、powers、memories 等。
```

## 回合级对账格式

结算后生成一份 report-only 对账报告：

```text
【回合三栏账】崇祯二年九月

玩家意图：
- 给天雄军月饷 100 万。
- 授卢象升荡寇将军。
- 镇蓟镇东协喜峰口。

叙事承诺：
- 邸报称天雄军成军。
- 卢象升已督镇喜峰口。
- 本军每月给饷训练。

系统落库：
- new_armies: tianxiong ✅
- office_changes: 卢象升 -> 荡寇将军 ✅
- fiscal_creates: 天雄军月饷 ❌

结论：
- 军籍与人事已落库。
- 月饷未落库；restore 后会穿帮。
```

第一版只报告，不拦截结算。等规则跑稳，再升级为硬闸。

## 第一阶段：Report-only

接入点：driver 固化后，在 `settle --delta <json>` 的末尾生成三栏账。

输入：

- `decree_text`：本月诏书。
- `narrative`：本月邸报 / 推演文本。
- `delta`：本月准备喂给 `apply_score_extraction` 的 JSON。
- `applied`：`apply_score_extraction` 返回值。
- DB 读回结果：结算后从数据库重新查状态，不信叙事自称。

输出：

- 本回合玩家意图摘要。
- 本回合叙事承诺摘要。
- 本回合系统证据清单。
- mismatch 列表。

原则：

- LLM 可以辅助抽取「叙事承诺」，但最后证据必须来自 DB / applied。
- 第一版不追求完美语义理解，优先覆盖已经踩坑的机械后果。
- 任何无法证明的叙事承诺都标 `unknown`，不要假装已落库。

## 第二阶段：接入 Driver

建议模块：

```text
ming_sim/narrative_ledger.py
```

建议函数：

```python
def extract_obligations(decree_text: str, narrative: str) -> list[dict]:
    """抽取本回合声称要发生 / 已发生的机械后果。"""

def collect_evidence(db, applied: dict) -> dict:
    """从 applied 与结算后 DB 读回证据。"""

def compare_obligations_to_evidence(obligations: list[dict], evidence: dict) -> list[dict]:
    """产出 mismatch / unknown / satisfied。"""

def format_ledger_report(result: dict) -> str:
    """格式化成用户可读的回合三栏账。"""
```

driver 流程：

```text
driver settle
  读取 decree_text
  读取 narrative
  读取 delta
  apply_score_extraction
  从 DB 读回真实状态
  生成三栏账
  打印 mismatch
```

## 第三阶段：升级为硬闸

report-only 跑几回合后，把高置信规则变成结算质量门。

建议硬闸规则：

### 钱粮

触发词：

- 每月
- 月支
- 月饷
- 常设
- 岁额折月
- 长供

要求：

- 必须有 `fiscal_creates` 或 `fiscal_changes`。
- 一次性支出必须有 `economy_moves`。

典型报错：

```text
叙事承诺存在常设月支，但 delta 未包含 fiscal_creates/fiscal_changes。
请补齐财政落库后重试。
```

### 军队

触发词：

- 练某军
- 募某营
- 成军
- 编练
- 分兵
- 调防

要求：

- 新军必须有 `new_armies`。
- 既有军队变化必须有 `army_delta`。
- 主将 / 镇地变化同时检查 `office_changes` 或 `army_delta.commander/station`。

### 人物

触发词：

- 授
- 任
- 调
- 罢
- 下狱
- 流放
- 致仕
- 赐号 / 赐名 / 赐头衔

要求：

- 任官 / 调任必须有 `office_changes`。
- 退场 / 惩处必须有 `character_status_changes`。
- 头衔目前无稳定字段，第一版先 report-only 标记，不做硬闸。

### 事项与工程

触发词：

- 立项
- 修成
- 竣工
- 了结
- 试点
- 推行

要求：

- 新政 / 工程必须有 `new_issues` 或既有 `issue_advances`。
- 结案叙事必须对应 `issue_advances` 推满、`close_issues`，或 DB 中 status 已 resolved。
- 已 resolved 的事实不得在无新旨情况下被叙述成「重新待办」。

### 排程

触发词：

- 下月
- 三月后
- 到期
- 届时
- 择日

要求：

- 第一版只警告。
- 后续若有排程实体，再要求落到 schedule / issue / secret_order 等稳定表。

## 与现有 TODO 的关系

它直接服务 `docs/TODO.md` 里的几条铁律：

- 带月经费的新政必须同产 `fiscal_creates`。
- 练新军 / 编新营必须同产 `new_armies` + `office_changes`。
- 决策当回合全量落库。
- restore 只读 DB 就能无损接续。

换句话说，回合三栏账不是新玩法系统，而是给现有结算链加一层审计。

## 不做什么

- 不引入外部 Narrative Studio / Fabletoria / MCP。
- 不把游戏改成预写分支树。
- 不让 LLM 仅凭邸报自证落库。
- 不在第一版就阻断所有结算。
- 不把所有叙事细节都强行结构化，只抓会影响 restore 和盘面的机械后果。

## 成功标准

第一阶段成功：

- 每回合能打印一份三栏账。
- 能发现「说了但没落库」的问题。
- 不误伤正常结算。

第二阶段成功：

- driver 中能稳定生成 mismatch 列表。
- 常见财政 / 军队 / 人事漏项能被自动指出。

第三阶段成功：

- 高置信漏项会阻止结算完成。
- 玩家看到的邸报事实，可以从 DB 读回证明。
- context restore 后不再靠「我记得」补世界状态。

## 核心原则

> Canvas 不当设计图，当对账单。

本项目的关键不是让叙事更会飞，而是让叙事飞过之后，在账本上留下影子。
