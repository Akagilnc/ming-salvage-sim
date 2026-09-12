# 大臣记忆 & 密令系统文档

> 覆盖：提取→落库→检索→遗忘→材料目录取阅 全链路。

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

每张记忆卡可挂多条原始摘录，供账本溯源与见闻投影；人物侧按需读材料目录，不把摘录预装进召对上下文。

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

密令的结构化差务合同不另开表，冻结在对应案卷的 `payload_json.covert_task_contract`；
每月实况进度继续写既有 `dossier_actual_progress`，承办人密奏则留在
`dossier_progress_json`。两轨职责分离：前者决定真实交付，后者只供玩家阅读。

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

### 3a. 大臣召见前供料（材料目录）

`registry.py → create_minister_agent` 经 `prepare_character_materials`（ADR 0155 / #1830 / #1833）。

开场只把最小集写入 instructions：本人身份与职位、在场诸人、当月日期、正经手事务一句、本场已说的话。派系档料在 system 的【派系档料】（`faction_context_with_db`）。

其余加工材料写入该次调用的材料目录，由模型自读：

- `人物/<名>/经历.txt`、`公事档案.txt`、`见闻.txt`
- `事务/<题>/当前情况.txt`
- `公开说法/`（按月）与 `公开说法/邸报/`（历月邸报全文）
- `INDEX.txt` 一行一项

API 通道：`list_materials` / `read_material`；CLI 通道以目录为 cwd、用自带只读工具。不预装全量盘面。

### 3b. 大臣按需取阅

旧按需查询工具已退役。旧事与公开记录按需读目录：

| 材料 | 路径 | 说明 |
|------|------|------|
| 个人经历 | `人物/<自己>/经历.txt` | 该人物可见事件记忆投影 |
| 见闻 | `人物/<自己>/见闻.txt` | 职务可见世界事实（钱粮/地区/军队/派系等按域） |
| 公开说法 / 邸报 | `公开说法/`、`公开说法/邸报/` | 按月公开记录与历月邸报全文 |

账本侧 `db.event_memory_detail` / `get_memories_by_keywords(..., ignore_expiry=True)` 仍是引擎检索，不挂大臣 tool。

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

大臣工具或旧按钮先转成同一条召对消息；工具返回带 `covert_task` 的
`__secret_order__` 载荷，由 `session.py` 暂存为 `pending_actions`：

```
召对提出密令
  → stage_pending_action(kind="secret_order", action="新建")
  → 皇帝应允，或结束回合默认同意
  → commit_pending_actions()
  → create_secret_order(..., covert_task=...)
  → 同一事务写 active 密令 + 已颁密令案卷 + covert_task_contract
```

确认写口不从标题、正文或标签反解析合同。缺少结构化差务类型时响亮失败，
不落空壳密令；active 上限仍为 20 条。

### 汇报结果

承办人逐月密奏只追加奏报轨，不再直接写 `done/failed`。月末先从真实效果、
案卷 `origin_ref` 与执行判决累计实况轨；到期后由确定性对账结案：

```
dossier_progress_json                         # 奏报轨，只供玩家阅读
dossier_actual_progress                       # 实况轨，只认真实交付
  → settle_due_secret_orders()
  → 交付差务：Σ actual_units 对比 covert_task_contract.delivery.target_units
  → 专题查核（investigation_target 非空）：Σ actual_units 对比
     target_progress_units(deadline_span, due_turn)，每个期限月计 1.0
     （无期限案经提交核议或奉旨即核变为当月到期时，最低按 1 个月配额）
  → db.close_secret_order(done/failed, player_facing_result, turn)
```

专题查核的月度实进度直接按当月执行态累计：忠实 `1.0`、打折 `0.5`、
阳奉阴违或反噬 `0.0`；是否新绑定事实线索不再决定当月差务进度。
非查核的交付差务仍只认与合同身份和来源案卷相符的真实交付数量。

奏报内容不能改变世界状态，也不能决定结案；恢复存档后两轨都从 DB 原边界继续。

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
| 召对开场不预装全量盘面 | ✅ | 最小集进 instructions；其余走材料目录自读（ADR 0155） |
| 时间查绕过衰减 | ✅ | `ignore_expiry=True` 路径 |
| 每月per_subject剪枝防膨胀 | ✅ | `prune_event_memories_for_turn(per_subject=3)` |

---

## 七、已知限制 / 潜在风险

1. **材料目录随邸报与经历增长**：召对开场只有最小集；旧事、见闻与历月邸报在目录里按需自读（ADR 0155），
   引擎不为召对预装近 N 回合全量 `event_memories`。目录体积随月增长，不另设硬上限或摘要层。

2. **密令active上限20条**：超限直接报错，不降级。
   若玩家密令积压多，大臣会看到报错提示，需先结案旧令。

3. **prune per_subject=3**：同主体同回合只保3条，可能剪掉次要但有效的事件记忆。
   importance评分对此有保护（高importance优先保留）。
