# 经济模块

经济模块追踪皇帝真正关心的账：国库有没有钱，内库能不能救急，本月收了多少，花了多少，欠了多少。

国库、内库不是 0-100 状态条，而是实际钱粮整数，单位**万两**。全局 0-100 局势量表只有民心、皇威两项；边防压力、动乱、士绅阻力等落在各省 / 各军队字段里。

---

## 核心账户

| 账户 | 说明 |
|------|------|
| `国库` | 朝廷公开财政，军饷/赈灾/官俸/工程均从此出 |
| `内库` | 皇帝私库，适合救急和密支，玩家可主动挪用补国库 |

---

## 省级财政模型

### 数据来源

每省 `regions` 表存以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tax_per_turn` | INTEGER | 省级月税基准（万两），含田赋+辽饷+盐税+商税合计 |
| `gentry_resistance` | INTEGER 0-100 | 士绅阻力；政治/事件与材料投影用，**不**自动写入 `fiscal.settle` tick 输入 |
| `unrest` | INTEGER 0-100 | 民变压力；事件门与材料投影用，**不**自动写入 settle tick 输入 |
| `fiscal` | JSON | 税种细分 + `settle` 基座 + 腐败度，见下表 |

`fiscal` JSON 字段说明：

| key | 单位 | 说明 |
|-----|------|------|
| `guan_min_tian` | 万亩 | 官民田 |
| `wang_tian` | 万亩 | 藩王庄田，免税；没收后转皇庄 |
| `huang_tian` | 万亩 | 皇庄田亩记录（月收预算以 fiscal_config 皇庄基准为准） |
| `liao_xiang` | 万两/月 | 辽饷月摊派额（settle / 叙事用） |
| `salt_tax` | 万两/月 | 盐税月基数，hub 旁路汇总 |
| `commerce_tax` | 万两/月 | 商税月基数，hub 旁路汇总 |
| `corruption` | 0-100 | 腐败度；region_delta 可写，材料可读；**不**自动映射进 settle tick |
| `settle` | object | 省级财政基座 `st`/`p`；`settle_ming_province_substrate_ticks` 只读这里（及现役覆盖参数），与顶层士绅/民变/corruption 无自动耦合 |

---

### 月结算（现役唯一引擎＝`substrate_hub`）

旧 `calc_province_fiscal`（`collection_rate` / `transport_ratio` / `liao_ratio` 系数公式）已退出，**不再是现役月收核**。现役路径在 `flows.apply_fixed_period_flows`：

1. **中央 hub 拨付**：京运补 + 中央军饷份额优先占用月初国库（`_compute_substrate_hub_outbound`）。
2. **省级基座 tick**：明控且已 seed 的省走 `_advance_province_fiscal_substrate`（三饷/火耗/起运存留/宗禄/逋赋等，设计真源见 [FISCAL_PROVINCE_SUBSTRATE.md](../FISCAL_PROVINCE_SUBSTRATE.md)）。
3. **旁路入库**：省级起运到京、盐税/商税中央旁路入太仓；太仓人为/自然亏空入对应 container；军饷分源欠账（省/中央）由 hub 与省基座共同推进。
4. **建筑产出与维护、固定 fiscal_config 流水**仍在同一 `apply_fixed_period_flows` 内落账。

一次性诏书收支不经本 tick，走声明 `economy_moves`（见 [DELTA_SCHEMA.md](../DELTA_SCHEMA.md)）。人口口径＝「人」；无旧档 legacy 万人/旧公式分叉。

### 盘面压力如何仍影响钱粮（不经旧系数公式）

- 士绅阻力 / 民变 / 腐败等仍是省域与叙事压力字段，经局势、声明 `region_delta` 与基座参数影响可征可解，**不是**再套一层 `collection_rate = 1 - gentry/200` 的平行核。
- 清丈、治腐、抄没、增盐商税等仍应落到结构化声明（`region_delta` / `fiscal_changes` / `economy_moves` / 局势效果），restore 只读 DB 接续。

---

## 固定月度收支（`fiscal_config` + hub）

唯一定额预算源＝`flows.compute_budget_lines`（与 `apply_fixed_period_flows` 落账、UI 预算摘要同源）。

- **`fiscal_config` 的 base 已是全月值**：月额＝`round(base × rate / 100)`，**没有**「季度额 ÷3」换算。
- **国库收入**主项来自 substrate_hub 预算投影（省级起运/盐商税旁路等），不是旧 `calc_province_fiscal` 系数表。
- **国库支出**含中央军饷拟拨、京运补拟拨，以及 `iter_budget_items()` 读出的固定科目（宗室禄米、百官俸禄、工部、赈灾备用等——以 `content/fiscal_config.json` 为准，勿把下表当第二真源）。
- **建筑产出**按 `output_amount × condition / 100` 折算；**维护**按表中 `maintenance` 月值原额（不乘 condition）；维护账户按 category 分（内廷→内库，其余→国库）。
- **内库皇庄**：读 `fiscal_config.皇庄_base×皇庄_rate` 全月基准；预算只读 fiscal_config 基准，**没有**「`wang_tian_transfer` × 0.57 自动加内库月收」的平行核。

开局盈亏以实档 `compute_budget_lines` / 国库流水为准；下文不再维护一套过时估算表。

---

## 腐败度（`corruption`）

- 存储位置：`regions.fiscal` JSON，key=`corruption`，0-100（属省域 fiscal 字段族）。
- **写入**：声明 `region_delta` 等经领域 region 段落库；合法字段白名单见 constants / region 写核（`FISCAL_SCORE_FIELDS` 等）。
- **读取**：材料目录 / 世界段供料按身份投影省域实况；`ming_sim/simulation.py` 现役是声明字段契约与别名模块，**不再**承担「`json_extract(fiscal,'$.corruption')` 拼推演 payload」的旧职责。
- 整治贪腐等叙事须落到结构化声明；引擎只 clamp 与记账。

---

## 藩王庄田 / 皇庄

- 省域可有 `wang_tian` / `huang_tian` 等 fiscal 细分字段（见上表数据来源），用于盘面与叙事。
- **不存在**现役 `region_delta.wang_tian_transfer` 自动转田+按亩加内库月收的专用键；未知字段按 region 写核 `invalid_enum` 逐项拒收。
- 内库皇庄月收真源＝`fiscal_config.皇庄_base`（及 rate）；裁撤/调额改 config。抄没、转庄等须用合法声明字段（`region_delta` 白名单字段、`fiscal_changes`、`economy_moves`、局势效果等）显式落账，restore 只读 DB。
- 河南（福王）、湖广（楚王）、山西（晋王）等仍是主要藩王叙事省份，不是自动公式入口。

---

## 代码位置

| 功能 | 文件 | 函数/位置 |
|------|------|---------|
| 月度财政 tick（唯一入口） | `ming_sim/flows.py` | `apply_fixed_period_flows` |
| 唯一定额预算源 | `ming_sim/flows.py` | `compute_budget_lines` |
| 中央 hub 拨付 | `ming_sim/flows.py` | `_compute_substrate_hub_outbound` 等 |
| 省级基座推进 | `ming_sim/flows.py` | `_advance_province_fiscal_substrate` |
| 盐商税旁路 / 太仓亏空 | `ming_sim/flows.py` | `_substrate_hub_salt_commerce_income_split` 等 |
| 一次性收支声明段 | `ming_sim/entities/economy/` | `delta_section` / `apply` |
| 腐败度等省域 delta | 领域 `region` 段 → DB | `FISCAL_SCORE_FIELDS` 白名单 |
| 省级基座设计 | `docs/FISCAL_PROVINCE_SUBSTRATE.md` | spike / 参数真源 |
| 旧 `calc_province_fiscal` | — | **已删除，勿再引用为现役核** |
