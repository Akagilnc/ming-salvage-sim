# 大臣职位变动技术文档

> 追踪切入点：`ming_sim/issues.py:apply_score_extraction`（主入口）、`ming_sim/session.py:apply_appointment`（建档落地）、`ming_sim/db.py:set_character_office`（调任写库）

---

## 一、触发路径总览

```
玩家回合
  ├─ 召见吏部尚书 → propose_appointment tool
  │     └─ 返回 __pending_appointment__<json>
  │           └─ session.chat 截获 → _apply_appointment → apply_appointment()
  │
  └─ 月末结算（decree.resolve_directives）
        ├─ simulator 生成邸报
        ├─ extractor 抽 JSON → 含 appointments / office_changes / character_status_changes
        └─ apply_score_extraction()
              ├─ [8] appointments       → 仅后宫纳妃
              ├─ [9] character_status_changes → 罢/狱/流/致仕/死
              └─ [10] office_changes    → 朝臣新任 + 调任（统一入口）
```

---

## 二、三条落地路径

### 路径 A：吏部铨选（实时，本回合即生效）

**触发**：吏部尚书（`office_type == "吏部"`）调用 `propose_appointment` tool。

**流程**：
1. `tools.propose_appointment()` → 返回 `__pending_appointment__<json>`
2. `session.chat()` 截获哨兵串 → 调 `_apply_appointment(payload, character)`
3. `_apply_appointment` → 调 `apply_appointment(db, state, content, registry, data)`
4. `apply_appointment()` 建档入库 + 注册 Agent，**本回合即可召见**

**payload 字段**：
```json
{"name": "孙传庭", "office": "陕西总督", "faction": "东林", "reason": "...", "replaces": "原任者名"}
```

- `replaces` 非空且对应 active → 原任者改 `dismissed`、office 清空（腾缺）
- 新建 `Character`，`office_type` 默认 `"待铨"`（LLM 不传则用此默认）
- 姓名查重：精确名 + aliases 命中即拒（`_find_existing_minister`）

---

### 路径 B：extractor office_changes（月末，结算生效）

**触发**：月末 extractor JSON 含 `office_changes` 数组。

**extractor 字段**：
```json
{
  "office_changes": [
    {"name": "孙传庭", "new_office": "陕西总督", "new_office_type": "督抚", "court_role": "", "reason": "..."}
  ]
}
```

**代码位置**：`issues.py:867–942`

**分支逻辑**（按 name 在不在册）：

| name 状态 | 路径 |
|-----------|------|
| 在册 `active` | `db.set_character_office()` 改 office（调任） |
| 不在册 / 非 active | 构造 appt payload → `apply_appointment()` 建新档（新任） |

**`new_office_type` 处理**：
- 在册调任：`set_character_office(name, new_office, new_office_type, source=reason)`
- `new_office_type` 为空 → `set_character_office` 不改 `office_type`

**`court_role` 处理**（首辅/次辅/六部尚书槽）：
1. 先清空已有同 `court_role` 的其他人：`UPDATE characters SET court_role='' WHERE court_role=? AND name!=?`
2. 再写入本人：`UPDATE characters SET court_role=? WHERE name=?`

**spillover**：extractor 把朝臣误塞进 `appointments` 数组时，代码自动转至 `office_changes` 处理（`spillover_office_changes` list，`issues.py:784–800`）。

---

### 路径 C：character_status_changes（月末，去职/死亡）

**触发**：extractor JSON 含 `character_status_changes`。

**字段**：
```json
{"name": "袁崇焕", "status": "imprisoned", "reason": "擅杀毛文龙"}
```

**合法 status 值**：`dismissed` / `imprisoned` / `exiled` / `retired` / `dead` / `offstage`

**落地**：`db.set_character_status()` → `issues.py:850`

**副作用**：
- 去职类（`dismissed` / `imprisoned` / `exiled` / `retired` / `dead`）：DB `office` 字段清空（`characters.office = ''`）
- 原职保留在 `character_offices` 表备档（可追溯历史任职）
- 内存 `content.characters[name].office = ""` 同步
- `offstage` / `active`（复职）：不动 office

---

## 三、后宫纳妃路径（特殊）

**触发**：`appointments` 数组中 `office_type == "后宫"` 的项。

**`apply_appointment()` 内后宫分支**（`session.py:154–189`）：
- 若 name 匹配 `candidate` 池 → `UPDATE`（保留原 style/skills/portrait_id）
- 否则新建 `Character`，`office_type = "后宫"`，`faction = "后宫"`
- Agent 用 `consort_agent_prompt` 注册

---

## 四、DB 表结构

```sql
-- 主表（当前状态）
characters (
  name TEXT PRIMARY KEY,
  office TEXT,           -- 当前官职；去职时清空
  office_type TEXT,      -- 内阁/吏部/督抚/边镇/…/后宫
  court_role TEXT,       -- 首辅/次辅/吏部尚书/… （空=无固定槽）
  status TEXT,           -- active/offstage/dismissed/imprisoned/exiled/retired/dead
  status_reason TEXT,
  status_changed_turn INTEGER
)

-- 备档（可追溯历任）
character_offices (
  character_name TEXT PRIMARY KEY,  -- 每人仅存最新一条
  office_title TEXT,
  office_type TEXT,
  source TEXT,           -- 初始设定/吏部铨选任命/诏书调任/…
  updated_at TIMESTAMP
)
```

`character_offices` 设计为"最新任职备档"而非完整履历，每次调任 UPSERT 覆盖。

---

## 五、关键约束

| 约束 | 位置 |
|------|------|
| 吏部专属 `propose_appointment` tool | `tools.py:526` |
| LLM 已判史实合理性，代码只查重 | `session.py:130` |
| 新建大臣默认 `office_type="待铨"` | `session.py:218` |
| 调任不改 status，仍 active | `db.py:1075` |
| 去职必清 office | `db.py:1047–1051` |
| court_role 全局唯一（新写入前清旧） | `issues.py:903–911` |

---

## 六、常见排查点

**问题：extractor 新任大臣 `office_type` 没更新**
→ extractor 没输出 `new_office_type`；在册者走 `set_character_office`，空 `office_type` 不改原值。
→ 修法：extractor prompt 明确要求填 `new_office_type`，或者调任后再补一次 `set_character_office`。

**问题：court_role 没写入**
→ 只有 `in_roster and cur_status == "active"` 的调任分支才处理 `court_role`（`issues.py:903`）。新建档走 `apply_appointment`，不处理 `court_role`，需下一回合才能通过 `office_changes` 再调。

**问题：吏部铨选本回合没效果**
→ 检查 `_apply_appointment` 是否被 `session.chat` 正确截获；`propose_appointment` 返回的哨兵串是否含正确 JSON。

**问题：被替换官员未去职**
→ `replaces` 字段为空，或对应 name 不在 `content.characters`，或该人 status 已非 active（代码只改 active 者）。
