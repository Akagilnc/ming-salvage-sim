# #1834 四类未结修复回执（末份判词 beff66c17 · r3 纠正枚举收窄）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f15-f16-f13-f3r-beff66c17`
**基线**：`beff66c17`；上轮提交 `0f5da1cd9` 被复核指枚举仍收窄。
**判词真源**：`attachments/01-1834-judge-beff66c17.json` 末份 payload（F15 / F16 / F13 / F3-R）

## 上轮收窄（诚实纠正）

| 类 | `0f5da1cd9` 问题 |
| --- | --- |
| F16 | `enum_four_class.py` 用自由正文字段名正则 + 只扫 `[:digits]`，漏 `s[:spec.max_len]`、建筑 status、势力/地区/军队文本字段、breach reason 等 |
| F15 | 硬编码只扫 `materials.py`+`month_chain.py` 两文件 |
| F13 | 只扫 `object.__setattr__`/`index_lines`，未列普通 `setattr` |
| F3-R | 只 `in/notin→eq`、窗口 5/8 行；未列同断言重复、`==` 涵盖存在、逆序 |

**本轮做法**：机械候选 = 最简单 `rg` 全仓列出 / AST 列出全部相关断言分组 → **人工语义逐条判定**成员。候选列表不是类定义的穷尽证明；报告不把启发式说成穷尽。已删窄脚本 `scripts/enum_four_class.py`。

**共同测试前缀**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 1. F16「自由正文在供料来源中被截断」

### 类定义

写入或投影进材料目录 / 公共供料可读事实的自由正文，被无依据长度切片、strip 后切片或改写裁断。

### 可核枚举命令（机械候选，非语义分类器）

```bash
rg -n '\[:\d+\]' ming_sim --glob '*.py'
rg -n '\[:\s*[A-Za-z_][A-Za-z0-9_\.]*\s*\]' ming_sim --glob '*.py'
rg -n 'strip\(\)\[:|\.strip\(\)\[:' ming_sim --glob '*.py'
rg -n 'spec\.max_len|s\[: spec\.max_len\]' ming_sim --glob '*.py'
# 落盘：evidence/1834-four-class-fix/enum_f16_all_candidates.txt
```

### 成员表（FIX — 本轮新修 / 确认有消费者）

| 成员 | 消费者 | 处置 |
| --- | --- | --- |
| `action_clusters` `s[:spec.max_len]` | title/stop_condition/ongoing_effects/stages 等 → issues → 材料 | **FIX→删切片** |
| `db.add_building` `status[:160]` / `name[:60]` | `buildings_report` → 世界盘面「营建」 | **FIX** |
| `db` REGION/ARMY/BUILDING_TEXT `strip()[:160]` | region/army/building report → 盘面 | **FIX** |
| `db.apply_power_rename` status/last_action `[:200]` | `power_report` → 盘面「边防」 | **FIX** |
| `db` 撤旨 `reason[:400]` | 案卷/材料可读链 | **FIX** |
| `breach_plea` reason/title `[:400/:120]` | due_review note → 案卷实况 | **FIX** |
| 上轮已删：case_summary[:48]、fiscal reason[:240]、staged [:200/:240]、due content[:120]、flows/issues 等 | 材料供料链 | 维持 |

### 候选保留（KEEP — 有依据，不是「不是样本」）

| 候选 | 保留依据 |
| --- | --- |
| `materials._safe_segment` `clean[:48]` | 路径段身份哈希前缀，非 LLM 供料正文 |
| raise/tlog/print/`provider_message`/`raw[:800]` | 错误预览或日志，不进材料目录 |
| `reason_code[:40]`、`controlled_by`/`station_region` id 切片 | 机读码 / 势力·地区 id |
| region/army/building **change-log** `reason[:80]` | 仅入 `*_logs`；盘面走 report 定性字段，不投影 change-reason |
| `power_updates`/`character_power` reason[:120] 入 logs/返回值 | 不投影进材料盘面正文 |
| `narrative_hint[:200]` | 注释「仅展示用，不喂 simulator」；材料不读该列 |
| `options[:3]`/`situations[:12]`/列表 `[:N]` | 列表长度，非正文裁断 |
| `breach_plea` `hit[:3]` | 人名列表长度 |
| 边缘 `.strip()` 判空 / 键规范化 | 不成内容中段裁断；材料 opening 对 raw body 已禁 strip |
| agno `truncate_*` / session keep | run 历史截断，非供料自由正文 |
| `office_rank`/`cli` marker 切分 | 解析边界，非存储裁剪 |

### strip 残留消费者检查

材料投影：`materials.py` 对 `stage_text`/affair body 判空只用局部 stripped 副本，opening/目录写 raw（既有 P6 注释）。未发现新的「strip 后切片自由正文再写入材料」生产路径；本轮删除的是仍进盘面/案卷的长度裁剪。

### 真实入口变异（完整命令）

```bash
# 旧逻辑红（含本轮漏网建筑 status[:160]）
MING_SIM_*_BIN=/usr/bin/false ../Ming_LLM/.venv/bin/python \
  evidence/1834-four-class-fix/scripts/mutation_old_red.py
# → mutation_old_red.json：verdict=true；F16_building_old_red stored_len=160,full=false

# 现行入口绿（含建筑 status 全文进材料、max_len 切片已删）
MING_SIM_*_BIN=/usr/bin/false ../Ming_LLM/.venv/bin/python \
  evidence/1834-four-class-fix/scripts/probe_four_class.py
# → probe_new_green.json：F16 building_status_full=true, building_in_materials=true,
#    max_len_slice_absent=true；case/fiscal/staged 仍 full
```

原始执行输出落盘于上述 json；未把 raw 终端混行当源码。`git diff --check` 工作树无 blank-EOF；上轮提交内 3 处 blank-EOF 随本提交覆盖。

---

## 2. F15「公共供料绕过秘密来源边界」

### 类定义

公共 / 邸报作者输入投影，在已启用秘密案卷排除时，仍供出密令关联事务的名称 / 起因等元数据，或同形平行再判 secret。

### 可核枚举命令

```bash
rg -n 'prepare_gazette_author_materials|prepare_world_materials|_gazette_feed|_month_fact_materials|public_feed|exclude_secret_order|secret_order_dossier_ids|affair_ids_for_dossiers|is_secret_order_origin|起因：|exclude_affair_ids|for_public_feed|public_layer_events|build_character_knowledge' \
  --glob '*.py' -g '!evidence/**' -g '!tests/**'
# → enum_f15_all_candidates.txt
```

### 全仓公共出口成员表

| 出口 | 处置 | 依据 |
| --- | --- | --- |
| `prepare_gazette_author_materials` | **KEEP** | `exclude_secret_order_dossiers=True` + `public_feed=True` |
| `prepare_world_materials` | **KEEP（接线已修）** | `secret_affairs = affair_ids_for_dossiers(secret_dossiers)` → `_world_affair_lines(exclude_affair_ids=…)` 整事务丢 name/origin |
| `_world_affair_lines` | **KEEP** | 唯一事务元数据投影；排除集生效 |
| `affair_ids_for_dossiers` | **KEEP** | 从已过滤案卷 id 派生，不平行重判 `secret_order_id` |
| `secret_order_dossier_ids` | **KEEP** | 秘密案卷边界真源 |
| `_gazette_feed` / `_month_fact_materials` | **KEEP** | `secret_order_dossier_ids` + `is_secret_order_origin` 滤密令来源 |
| `public_layer_events(for_public_feed=True)` / `build_character_knowledge(public_feed=True)` | **KEEP** | 公开说法公共边界；不供事务 name/origin 旁路 |
| `prepare_character_materials` / `prepare_scene_materials` | **KEEP** | 人物/场景树；密令文件仅对当事人，非公共邸报出口 |
| `prepare_world_materials` 默认（世界段） | **KEEP** | 默认可含密令关联事务；公共旁路问题在 gazette/`public_feed` 路径 |
| `secret_order_affair_ids` 平行函数 | **无成员** | 上轮已删；复扫无 |
| `decree_forecast`→`prepare_world_materials` | **KEEP** | 世界预推，非公共作者出口 |

### 变异

见上：`mutation_old_red` 清空 exclude → opening/文件可见密令名；`probe` 现行 `clean=true`。

---

## 3. F13「已退役索引副本仍被动态恢复」

### 类定义

冻结 dataclass / 材料载体上，用 `__setattr__`/`setattr`/动态属性恢复**已退役、无消费者**的镜像字段（不限 `index_lines`）。

### 可核枚举命令

```bash
rg -n 'object\.__setattr__|__setattr__\(|\bsetattr\(|index_lines|__dict__\[' \
  --glob '*.py' -g '!evidence/**'
# → enum_f13_all_candidates.txt
```

### 成员表

| 成员 | 处置 | 依据 |
| --- | --- | --- |
| `PreparedMaterials.index_lines` + `object.__setattr__` | 上轮已删 | 生产 `object.__setattr__` / `index_lines` **0 命中** |
| `ming_sim` 普通 `setattr`（llm_transport/decree/session/issues） | **KEEP** | 分别为模型包装、state 字段同步、异常附着、人物属性拷贝——非退役材料镜像 |
| tests `monkeypatch.setattr` | **KEEP** | 测试替身，非生产动态副本 |
| `INDEX.txt` 文件 | **KEEP** | 人读索引文件真源，非对象镜像字段 |

**无未修成员。** 探针：`before=false, after=false, clean=true`。

---

## 4. F3-R「测试恢复留下重复断言」

### 类定义

同主体上弱断言已被强断言逻辑蕴含（含同断言重复、存在⊂相等、逆序等）。删弱留强；时序检查点不算重复。

### 可核枚举命令

```bash
# AST：同函数全部 assert 分组（无窗口上限）→ enum_f3r_py_all_candidates.txt
# 种类计数：DUPLICATE_ASSERT=229, LEN_THEN_EQ_CAND=94, EQ_THEN_IN_REVERSE=19,
#           NOTIN_THEN_EQ_FULL=6（本轮扫描）
# JS expect 分组 → enum_f3r_js_all_candidates.txt
# 种类：JS_DUP=30, JS_WEAK_THEN_STRONG=17, JS_STRONG_THEN_WEAK=1
```

（实现：一次性 AST 列出；**人工判定**，不把窗口启发式当穷尽。）

### 成员表（真重复 → FIX）

| 成员 | 处置 |
| --- | --- |
| 判词样本 + 上轮已删弱 in/null | 维持 |
| `drawers.test.tsx` `after.not.toBeNull` ⊂ `after.toEqual(dragged)` | **本轮 FIX→删弱** |

### 候选保留（人工）

| 候选型 | 依据 |
| --- | --- |
| `NOTIN_THEN_EQ_FULL`（session_write_queue / qa_t1） | 屏障前「未出现」与屏障后 `order==…` 时序检查点 |
| 大量 `DUPLICATE_ASSERT` | 多为变异前/后同一谓词重断言，非弱⊂强 |
| `LEN_THEN_EQ_CAND` | 粗启发式假阳：`len(x)>=n` 与无关主语 `==` 同函数共现 |
| `EQ_THEN_IN_REVERSE` | 多为精确相等后再否定无关键（反例检查），非弱重复 |
| `JS_WEAK_THEN_STRONG` 如 `resume.not.toBeNull` → `resume!.disabled.toBe(false)` | **不同属性**；存在性不被 disabled 相等蕴含 |
| `body.not.toBeNull` → `body?.textContent ?? "".toBe("")` | 空串路径在 null 时仍可通过；须保留存在检查 |
| `JS_DUP` waitFor/多次 resolveCount | 异步栅栏或阶段重复观测 |

---

## 聚焦测试（不全量）

**Python**（375 passed，14.20s）→ `pytest_focus.txt`：

```text
MING_SIM_*_BIN=/usr/bin/false ../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py … tests/test_breach_plea_623.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-r3-audit/pytest-focus
```

**Web**（152 passed，4.36s）→ `vitest_focus.txt`：

```text
cd web && npm test -- src/appDurableWiring.test.tsx \
  src/components/settlementGazettePanel.test.tsx src/components/modals.test.tsx \
  src/components/drawers.test.tsx src/components/map.test.tsx \
  src/components/situation.test.tsx
```

邻票 `test_commitment_progress_contexts_are_structured` 依判词归 #1873，不夹入。

---

## 逐类结果

| 类 | 结果 | 未结 |
| --- | --- | --- |
| F15 | 全仓公共出口人工表；生产旁路仍清；旧红新绿 | 无 |
| F16 | 广扫后修 max_len/盘面文本字段/breach；KEEP 有依据 | 无 |
| F13 | 广扫 setattr；无退役动态副本成员 | 无 |
| F3-R | 广扫断言分组；真重复已删；时序/假阳 KEEP | 无 |

复杂度：删裁剪与弱断言；无摘要/护栏/兼容层/永久证明测。取证脚本仅 `probe_four_class.py` + `mutation_old_red.py`。

未 push / 未开 PR / 未 stash / 未 amend / 未 kill。
