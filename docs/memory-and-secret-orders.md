# 大臣记忆 & 密令系统文档

> 覆盖：提取→落库→检索→遗忘→注入提示词 全链路。

---

## 一、数据表（SQLite）

### `event_memories`

主记忆卡表，每条代表一个结构化历史事件摘要。

| 字段 | 说明 |
|------|------|
| `subject_type` | `character` / `faction` / `court` / `region` / `army` / `external_power` |
| `subject_id` | 主体名（大臣名、派系名、地区id…） |
| `event_type` | `edict_result` / `issue_progress` / `issue_success` / `issue_failure` / `appointment` / `punishment` / `promise` / `counsel` / `intel_report` / `private_audience` |
| `title` | ≤40字摘要 |
| `cause / process / outcome` | 各≤80字三段叙事 |
| `sentiment` | `positive` / `neutral` / `negative` / `mixed` |
| `importance` | 1–5，驱动检索评分与衰减TTL |
| `tags` | JSON数组，检索锚点（人名/地名/事项id…） |
| `source_kind` | 来源类型（见下节） |
| `source_id` | 来源定位id |
| `expires_turn` | 过期回合，NULL=永久 |
| UNIQUE | `(subject_type, subject_id, event_type, source_kind, source_id)` — upsert去重 |

**自动TTL（`upsert_event_memory`）：**

| importance | TTL（回合数） |
|------------|------------|
| 1 | +6 |
| 2 | +12 |
| 3 | +24 |
| 4 | +48 |
| 5 | NULL（永久） |

LLM显式传`expires_turn`时优先；否则按上表自动计算。

### `event_memory_sources`

每张记忆卡可挂多条原始摘录，便于大臣工具`recall_memory_detail`溯源。

| 字段 | 说明 |
|------|------|
| `memory_id` | FK → `event_memories.id`，CASCADE删 |
| `source_kind` | 同`_SOURCE_KINDS`集合 |
| `source_id` | 来源内部id（回合号 / directive_id / issue_id / `大臣名:turn` 等） |
| `excerpt` | ≤200字原文摘录 |
| `locator` | JSON，精确字段定位（`turn` / `directive_id` / `field`） |

**`source_kind` 合法值：**

```
directive          -- 诏书草案
decree             -- 正式颁诏全文
simulation_narrative -- 月末邸报叙事
extractor_output   -- applied 可见结果（raw delta 真源在 pending_resolve_context）
issue              -- 事项进度快照
chat_message       -- 召对聊天（大臣承诺/情报）
turn_report        -- 月末奏报
system             -- 规则层直接写入
```

### `chat_messages`

每轮召对逐条落库（`append_chat_message`），不丢进程重启。

### `secret_orders`

密令表，独立于`event_memories`。

| 字段 | 说明 |
|------|------|
| `minister_name` | 承办大臣 |
| `title` | ≤20字 |
| `content` | 任务详情 |
| `tags` | JSON数组，检索锚点 |
| `status` | `active` / `done` / `failed` |
| `result` | 结案说明 / 进展描述 |
| `turn_closed` | 结案回合 |
| 上限 | 同时active ≤ 20条，超限报错 |

---

## 二、提取链（每月末执行）

```
月末颁诏
  │
  ├─ 1. record_event_memories_from_resolution()     [memories.py]
  │       规则层直接写，不调LLM
  │       来源：decree / directives / extractor applied JSON
  │       内容：拟旨被采纳 / issue新立推进结案 / 任命惩处 / 派系变化 / 地区军队外势显著变化
  │
  ├─ 2. extract_event_memories_with_agent()         [memories.py]  ← 可选LLM路径
  │       agent：memory_extractor（prompts/memory_extractor.md）
  │       payload：turn + directives + decree_text + narrative + applied + extractor_output(applied view)
  │       输出：memories[] JSON → _write_llm_memories() → upsert_event_memory()
  │
  以上完成后：prune_event_memories_for_turn(per_subject=3)
    -- 同主体同回合超过3条时按importance降序删低价值的
```

**decree.py 调用顺序（`resolve_directives`）：**

```
step 4  record_event_memories_from_resolution   （规则层）
```

---

## 三、检索路径

### 3a. 大臣召见前注入（court_brief）

`registry.py → MinisterRegistry._brief_if_needed(character)`

每月首次召见时触发，以 **user message**（非 system prompt）喂入，保护前缀缓存。

```
build_court_brief(context)    → 本月钱粮/奏报/地区/军队/派系/事项
build_memory_brief(character, context)
  └─ db.get_recent_event_memories(turn, window=5, limit=100)
     -- 近5回合内所有event_memories，按turn/id升序
     -- 不按大臣过滤，全局注入（量大时靠limit=100兜底）
```

**注意**：`get_recent_event_memories`不做主体过滤，全量近5回合记忆都注入，
适合全局态势感知；精确召唤见3b。

### 3b. 大臣工具主动检索

大臣持有两个主动检索工具（`tools.py`）：

| 工具 | 函数 | 说明 |
|------|------|------|
| `recall_memory_detail` | `db.event_memory_detail(memory_id)` | 按id查单条记忆+原始摘录 |
| `recall_memories_by_time` | `db.conn.execute(turn=ref_turn)` + `get_memories_by_keywords` | 按年月+关键词回溯，ignore_expiry |

### 3c. 月末推演注入（simulator / extractor）

`decree.py → resolve_directives` step 1.8（#883 隔离架构）：

```
1. 近几回合章节记忆 → relevant_memories（公共轨：simulator + 各 extractor 可见）
2. 独立拉 active 密令 → group_secret_orders_for_sim 分「在办」组、剥英文 status（#48）；到期待裁承诺另并入公开 due_commitments
3. augment_secret_orders_with_due_commitments 把到期待裁承诺并入「待核议」分组
4. 注入分流（#883）：
   - simulator payload：只派生扁平 due_commitments（entry_kind=due_commitment 的公开承诺），永不预读密令正文
   - secret_orders 分组：只进 personnel_secret extractor 独立 rail；公共 extractor / 公共月报裁判不预读
```

**`get_memories_by_keywords` 评分公式：**

```
score = importance * 10
      + hit_count（tags命中关键词数）* 5
      + max(0, 8 - age)（时效加分）
```

**`get_relevant_event_memories`（大臣个人精准检索，目前未直接调用，备用）：**

```
score = importance * 10
      + 20（exact character match）
      + len(tag_matches) * 4
      + max(0, 10 - age)
      + 12（active issue命中）
```

---

## 四、遗忘机制

两层：

### 4a. 自动衰减（expires_turn）

写入时按importance自动计算TTL（见一、表格）。
`get_relevant_event_memories` / `get_memories_by_keywords` 默认过滤
`expires_turn IS NULL OR expires_turn >= current_turn`。
时间查询（`ignore_expiry=True`）绕过，历史档案永远可追溯。

### 4b. 每回合剪枝（prune_event_memories_for_turn）

```python
db.prune_event_memories_for_turn(state.turn, per_subject=3)
```

同一`(subject_type, subject_id)`在同一回合保留importance最高的3条，其余删除（CASCADE连带删sources）。
写完LLM记忆 & 规则记忆各调用一次。

---

## 五、密令系统

### 下达密令

大臣工具 `issue_secret_order(title, content, tags_json, assignee)` →

```
db.create_secret_order(state, assignee, title, content, tags)
  → INSERT secret_orders status='active'
  → 返回 __secret_order_registered__{id}__ 哨兵
      或降级 → __secret_order__<json> 哨兵（直接落库失败时）

session.py._apply_secret_order 截获哨兵 → 落库
```

上限：active ≤ 20条，超限直接报错给大臣。

### 汇报结果

大臣工具 `report_secret_order_result(order_id, status, result)` →

```
返回 __close_secret_order__<json> 哨兵
session.py._apply_close_secret_order 截获 → db.close_secret_order(order_id, status, result, turn)
  → UPDATE status=done/failed, turn_closed=当前回合
```

### 密令注入推演（#883 隔离）

月末 `resolve_directives` step 1.8：

```python
active_orders = db.list_secret_orders(status="active")[:20]
# group_secret_orders_for_sim 按状态分进中文键、剥英文 status
# （#48：status=active 只用来分组，绝不当字段进 LLM 输入——
#   若把英文 enum 当字段注入，下游叙事/UI 会冒出「孙承宗密旨（active）」）
secret_orders_for_sim = {
    "在办":   [...],   # active：承办中
    "待核议": [...],   # 公开 due_commitment ACK，不是密令 pending_review 真源
}
# 每条密令 {id, minister_name, title, content[:120], turn_issued, due_turn, progress, sim_note}（无 status）

# #883 数据流分流：
# - secret_orders 分组 → 只喂 personnel_secret extractor 独立 rail（核议主体）
# - simulator 公共轨 → 只见派生扁平 due_commitments，永不预读密令正文
# - 披露事件（source_id 前缀 secret_order_disclosure:）是简报升公开知识的唯一通道
```

---

## 六、已打通 / 已确认的边界

| 关注点 | 状态 | 位置 |
|--------|------|------|
| chat_messages 逐条持久化 | ✅ | `db.append_chat_message` |
| 规则层 + LLM层不重复source | ✅ | UNIQUE(subject_type,subject_id,event_type,source_kind,source_id) upsert |
| 密令及其派生不进共享 memory | ✅ | #883：专用密令简报结构隔离；披露事件是唯一公开化通道 |
| 注入不破前缀缓存 | ✅ | 全部走user message，不进system prompt |
| 时间查绕过衰减 | ✅ | `ignore_expiry=True` 路径 |
| 每月per_subject剪枝防膨胀 | ✅ | `prune_event_memories_for_turn(per_subject=3)` |

---

## 七、已知限制 / 潜在风险

1. **`build_memory_brief` 全量注入**：`get_recent_event_memories(window=5, limit=100)` 不过滤主体，
   近5回合若有大量记忆（100条+），会全部注入大臣brief，token压力大。
   当前兜底是limit=100，若记忆量爆炸需按character过滤或降低window。

2. **密令active上限20条**：超限直接报错，不降级。
   若玩家密令积压多，大臣会看到报错提示，需先结案旧令。

3. **prune per_subject=3**：同主体同回合只保3条，可能剪掉次要但有效的事件记忆。
   importance评分对此有保护（高importance优先保留）。
