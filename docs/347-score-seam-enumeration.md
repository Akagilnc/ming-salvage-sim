# #347 接缝枚举：国势 / 地区抽象分 · 玩家回流面

**核对日期：2026-08-18（本地日期 Asia/Tokyo；开工全量扫，非抄基线三处）**  
**本文档地位**：国势/地区抽象分「玩家回流面」清单的**唯一真源**。  
**非本票**：不实现 #347 本体（适配器扩展 / 守门扩面 / 定档词面）；不改 ADR/CONTEXT/CLAUDE。

Cross-ref：GitHub #347 应留评论指向本路径 `docs/347-score-seam-enumeration.md`。  
试玩读物：[`docs/4.5-playtest-guide.md`](4.5-playtest-guide.md)。

---

## 范围

**在范围内**——国势 / 地区**抽象设计分**到达皇帝（玩家）眼睛或耳朵的面：

| 族 | 字段（机面名 / 玩家标签） |
| --- | --- |
| 国势抽象 | `metrics["民心"]`、`metrics["皇威"]`（`SCORE_METRICS`） |
| 地区抽象 | `public_support`（民心）、`unrest`（动乱）、`gentry_resistance`（士绅阻力）、`military_pressure`（边防压力）——`REGION_SCORE_FIELDS` 同族 |
| 同构增量 | 上述字段在 effect / legacy / 回合变化文案中的 **±n / n%** 裸增量 |

**明确不在范围内**（本枚举不收）：

- 可数实物：银两、粮食万石、人口、田亩、兵额、城防门数、年月等
- 角色六轴 / 军心士气等（已有 0010/0122/军队五档词带谱系；#347 issue 正文 catch-all 含角色轴，但**本接缝枚举按 #548 票面收窄为国势/地区**）
- 局势 `bar_value` 进度条（议题进度，非国势/地区盘面分；若 #347 本体要扩，另开面集，不塞进本真源冒充）
- 纯机面：simulator / extractor / `inspect_*` 带数值版、审计 SQL
- #547（P4 守门扩新面，OPEN）：后落若改守门面集，以 issue/路径引用维持一致，**不在本文抄第二份面集**

概念只引用、不复制：

- [ADR 0010](adr/0010-presentation-adapter-read-contract.md) 决定 3（读端双变体 / P4 横切）
- [ADR 0025](adr/0025-mutiny-state-machine-loyalty-axis.md) D8（玩家回流面须经统一定性适配器）
- [ADR 0122](adr/0122-minister-p4-qualitative-bands.md)（五档词带同形先例）

---

## 复核口径（每次开工重扫）

```bash
# Web 呈现与消费
rg -n '民心|皇威|public_support|unrest|gentry_resistance|military_pressure' \
  web/src --glob '!**/*.{test,spec}.*'

# 状态下发与 humanize
rg -n '民心|皇威|public_support|unrest|gentry_resistance|military_pressure' \
  web_app.py

# CLI / 报告 / context 回流句
rg -n 'SCORE_METRICS|format_metric_delta|metric_bar|民心|皇威' \
  ming_sim/report.py ming_sim/context.py ming_sim/cli ming_sim/memories.py

# 地区 payload 与定性对照（已有定性路 ≠ 玩家 UI 已接）
rg -n 'region_payload|_public_support_description|region_detail|REGION_SCORE_FIELDS' \
  ming_sim/db.py ming_sim/constants.py
```

判定：「玩家回流」= 该字符串/数字会出现在 HUD、抽屉、地图、局势文案、CLI 打印、或经扮演/近臣叙事进皇帝耳目。  
机面-only 命中（extractor prompt、内部 SELECT）不入表。

---

## 玩家回流面清单

基线票面已实核三处（①③⑤）——下表为 **2026-08-18（本地日期 Asia/Tokyo）全量扫** 结果，不得只保留三行。

| # | 回流面 | 锚点（file:line） | 裸露形态 | 复核 grep |
| --- | --- | --- | --- | --- |
| 1 | Web 顶栏国势双值 | `web/src/components/gameHud.tsx:139-142` | `民心{int}` / `皇威{int}`，`scoreTone` 仅染色 | `hud2-lab">民心` 或 `metrics["民心"]` |
| 2 | Web 顶栏数据源（state 四键投影） | `web_app.py:1259-1265` `_display_metrics`；`:1343-1348` `state_payload["metrics"]` | JSON 裸 int 下发前端 | `"metrics": display_metrics` |
| 3 | Web 省份抽屉·列表 meta | `web/src/components/drawers.tsx:399` | `动乱{r.unrest}` 与月税并列 | `动乱{r.unrest}` |
| 4 | Web 省份抽屉·详情表 | `web/src/components/drawers.tsx:414-416` | `public_support` / `unrest` / `gentry_resistance` / `military_pressure` 四裸值 | `selected.public_support` |
| 5 | Web 地图·选中省情报表 | `web/src/components/map.tsx:785` | 民心/动乱裸值（同表粮食万石=实物，不在本枚举改） | `region.public_support` |
| 6 | Web 地区结构化 payload | `ming_sim/db.py:5978-6001` `region_payload` | 上列四字段 int 进 `state.regions` | `def region_payload` |
| 7 | Web 局势/结案效果摘要 | `web/src/format.ts:97-102` `formatEffectSummary` metrics 循环；regions 经 `appendScopedEffect`+`cnField`（`:216` 等标签） | `民心+N` / `皇威-N` / `…·民心±N` | `effect.metrics` 与 `formatIssueEffect` |
| 8 | Web 效果摘要消费点 | `web/src/components/situation.tsx:44,169,174`；`closedIssues.tsx:32` | 结案行/tip 展示上列摘要 | `formatIssueEffect` / `formatClosedEffect` |
| 9 | Web 帝国修正条 | `web/src/format.ts:268-271` `formatLegacyEffect`；`web/src/components/hud.tsx:254` `LegacyBar` | `民心+N%` / 地区字段% | `formatLegacyEffect` |
| 10 | Web 帝国修正服务端文案 | `web_app.py:327-346` `_humanize_legacy_effect` | 与上同构的 `民心{+/-n%}`，经 `effect_text` 下发 | `_humanize_legacy_effect` |
| 11 | CLI 回合头国势条 | `ming_sim/report.py:25-27`；入口 `ming_sim/cli/terminal.py:110-112` | `民心:  n/100` + `metric_bar` | `SCORE_METRICS` / `metric_bar` |
| 12 | CLI/报告·核心数值变化句 | `ming_sim/context.py:181-191` `format_metric_delta`；`ming_sim/report.py` 变化报告组装 | `民心+N`（非钱粮键走裸 int） | `format_metric_delta` |
| 13 | CLI/报告·地区变化句 | `ming_sim/report.py:35-48` `format_region_changes` | `〔省〕民心+N` 等 label+裸增量 | `format_region_changes` |
| 14 | 章节/时间线效果摘要 | `ming_sim/memories.py:109-120` `effect_brief` | 拼 `民心+N`、`皇威+N` 进效果句（经时间线/章节到玩家） | `effect_brief` 与 `metric_delta` |
| 15 | 扮演路径国势 context 拼串 | `ming_sim/context.py:155-162` `state_context` | 非钱粮 metrics 现为 `f"{key}{value}"` 裸拼；agent 回话可回流皇帝 | `def state_context` |

### 扫到但不入库的边界说明

| 命中 | 理由 |
| --- | --- |
| `map.tsx` unrest → 填色阈值（约 :41/:647）；`drawers.tsx:381-382` tone class | 用阈值派生色/级，**不直渲数字**；#347 本体若做「色即档」可再议，本表不列裸分面 |
| `hud.tsx:193-194` `HUD_SLOTS` 民心/皇威坐标 | 布局坑位，非数值渲染（数值在 `gameHud.tsx`） |
| `db.py` `region_report` / `region_detail(qualitative=True)`；`registry` 定性纪律句 | **已有定性出口**，说明适配器谱系可复用；但 Web 抽屉/地图未接这些出口——缺口仍在上表 3–6 |
| `tools.py` `inspect_*` / 非 qualitative `region_detail` | 机面，不入玩家回流表 |
| extractor / season_simulator prompts 中的字段表 | 机面契约，不入 |

---

## 定性插槽形态（只写「长这样」）

**复用**既有五档词带形状，**不定**档位切点与词面（切点/词面归 #347 本体，PRD OOS）。

### 形状（canonical 先例）

```text
词带：Dict[field, Tuple[w0, w1, w2, w3, w4]]   # 恰五档，劣→优或反义轴自洽
投影：qualitative_band(value, words) → 单一中文词/短词
       或 _qualitative_army_stat 式「标签：词」
切点惯例（形状参考，非本票法定）：≥80 / ≥60 / ≥40 / ≥20 / else
```

锚点：

- `ming_sim/db.py` `_ARMY_QUALITATIVE_WORDS`（约 :343）、`_qualitative_army_stat`（约 :353）
- `ming_sim/qualitative.py` `qualitative_band`（共享五档桶）
- ADR 0122：大臣六轴同形五档（角色轴先例；国势/地区轴平行扩展时抄形状不抄词）

### 插槽应落在哪

对上表每一「裸露形态」，#347 本体替换时：

1. **人面渲染缝**（HUD 字、表格 td、CLI print、effect 摘要拼句）只收 **短语**，不收 int。
2. **下发 JSON** 若仍带 int，须保证前端默认路径不直渲；或改为下发已投影的 display 字段（接 0010 读端双变体：机面数值版 / 玩家定性版）。
3. **扮演/近臣输入** 只喂定性版（P4 靠不喂，不靠「喂了再禁念」——0033/0010）。

### 树内已有国势/地区词带雏形（形态参照，非定稿）

| 字段 | 现成五档元组（实现可改词，本票不钉） | 位置 |
| --- | --- | --- |
| 民心 `public_support` | `("堪忧", "偏弱", "起伏", "尚可", "稳固")` | `db.py` `_public_support_description` ~:88-89 |
| 动乱 `unrest` | `("平静", "有患", "不安", "升高", "已炽")` | `db.py` `_unrest_description` ~:92-93 |
| 士绅阻力 | `("极弱", "偏弱", "中等", "偏强", "强")` | `region_detail(qualitative=True)` ~:6047 |
| 军事压力 | `("极低", "偏低", "中等", "偏高", "极高")` | 同 ~:6048 |
| 国势 民心/皇威 | 扮演纪律已要求定性（`registry.py` ~:111-113），**缺**与军队/上表同形的统一 HUD 词带出口 | #347 本体补 |

增量文案（`+N` / `+N%`）的定性说法（「民心小苏 / 皇威小损」类）**无**现成五档增量词带——属 #347 本体设计，本枚举只要求：插槽形状仍走「有序词带 → 单短语」，禁止继续拼裸整数。

---

## 与试玩 / 守门的关系

- ⛳4.5 试玩把上表未翻译面标为**已知债**（见 [`4.5-playtest-guide.md`](4.5-playtest-guide.md) 债 1–6：HUD / 地区 / 效果文案 / CLI 回合头 / 报告·时间线变化句 / 扮演 `state_context`），不误诊为呈现闸回归。两文同口径：枚举增面则指引债单同步补现象+归属。
- 新增卷轴各面（#478）**不得新漏**人物抽象裸分；国势/地区存量面翻译本体仍归 #347。
- #547 若扩 P4 守门面集：在 #547 / #347 留言引用本路径，更新时改**本文件**，禁止平行第二份面表。

---

## 修订记录

| 日 | 说明 |
| --- | --- |
| 2026-08-18（本地日期 Asia/Tokyo） | #548 初版：全量扫入库 15 面；基线三处含于 #1/#4/#5；定性插槽复用五档形状。 |
| 2026-08-18（本地日期 Asia/Tokyo） | #548 CodeRabbit minor：日期标明本地口径；试玩债单补 #12–#15（报告变化句 + `state_context`），与枚举闭合。 |
