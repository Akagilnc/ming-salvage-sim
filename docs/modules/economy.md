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
| `gentry_resistance` | INTEGER 0-100 | 士绅阻力，影响实收率 |
| `unrest` | INTEGER 0-100 | 民变压力，影响实收率和解运比 |
| `fiscal` | JSON | 税种细分 + 腐败度，见下表 |

`fiscal` JSON 字段说明：

| key | 单位 | 说明 |
|-----|------|------|
| `guan_min_tian` | 万亩 | 官民田，田赋→国库 |
| `wang_tian` | 万亩 | 藩王庄田，免税；没收后转皇庄 |
| `huang_tian` | 万亩 | 皇庄，仅北直隶有，地租→内库 |
| `liao_xiang` | 万两/月 | 辽饷月摊派额 |
| `salt_tax` | 万两/月 | 盐税月基数，产盐省才>0 |
| `commerce_tax` | 万两/月 | 商税月基数 |
| `corruption` | 0-100 | 腐败度，影响解运比 |

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

## 固定月度支出（`fiscal_config`）

所有 base 为**季度额**，`monthly_amount(base × rate / 100)` = 月额（约 ÷3）。

### 国库支出

| 项目 | base（季） | rate | 月额（估） | 说明 |
|------|-----------|------|----------|------|
| 宗室禄米 | 360 | 70% | ~84万 | 最大包袱，削藩可降 |
| 九边补给 | 270 | 90% | ~81万 | 九边粮草，非军饷 |
| 各军军饷 | — | — | ~150万 | 按优先级逐军发放 |
| 百官俸禄 | 90 | 100% | ~30万 | 含地方折色 |
| 建筑维护 | — | — | ~75万 | 各省建筑月维护 |
| 赈灾备用 | 15 | 100% | ~5万 | 制度性预留 |
| 工部 | 15 | 100% | ~5万 | 工部日常 |

**月支出合计约 430万两**

### 内库支出

| 项目 | base（季） | rate | 月额 |
|------|-----------|------|------|
| 宫廷开支 | 22 | 100% | ~7万 |
| 内廷俸禄 | 15 | 100% | ~5万 |
| 妃嫔供奉 | 10 | 100% | ~3万 |

### 内库收入

| 项目 | base（季） | rate | 月额 |
|------|-----------|------|------|
| 皇庄 | 60 | 100% | ~20万 |
| 织造 | 35 | 100% | ~12万 |
| 矿税 | 10 | 100% | ~3万 |

---

## 开局月净

| 账户 | 月收入 | 月支出 | 月净 |
|------|--------|--------|------|
| 国库 | ~398 | ~430 | **~-32** |
| 内库 | ~35 | ~15 | **~+20** |

国库持续亏损，逼玩家开源节流。内库正向积累，作为救急储备。

---

## 腐败度（`corruption`）

- 存储位置：`regions.fiscal` JSON，key=`corruption`，0-100
- **读取**：`simulation.py` 把 `json_extract(fiscal,'$.corruption')` 喂进推演 payload
- **写入**：`apply_region_deltas` 识别 `FISCAL_SCORE_FIELDS`，解析 JSON → patch → 写回
- **声明触发**（经 `region_delta` / 局势效果，旧 `score_extractor` 已退役）：整治贪腐/巡按/抄家等叙事须落到结构化字段；引擎只 clamp 与记账

---

## 藩王庄田没收

```
execution_evaluator 输出：
  region_delta: {"henan": {"wang_tian_transfer": 40, "reason": "查抄福王庄田"}}

apply 时：
  wang_tian -= 40
  huang_tian += 40
  内库月增量 += 40 × 0.57 = 23万两/月（持续）
  同时：gentry_resistance +15，党争压力上升
```

河南（福王）、湖广（楚王）、山西（晋王）是主要藩王省份。

---

## 代码位置

| 功能 | 文件 | 函数/位置 |
|------|------|---------|
| 月度财政 tick（唯一入口） | `ming_sim/flows.py` | `apply_fixed_period_flows` |
| 中央 hub 拨付 | `ming_sim/flows.py` | `_compute_substrate_hub_outbound` 等 |
| 省级基座推进 | `ming_sim/flows.py` | `_advance_province_fiscal_substrate` |
| 盐商税旁路 / 太仓亏空 | `ming_sim/flows.py` | `_substrate_hub_salt_commerce_income_split` 等 |
| 一次性收支声明段 | `ming_sim/entities/economy/` | `delta_section` / `apply` |
| 腐败度等省域 delta | 领域 `region` 段 → DB | `FISCAL_SCORE_FIELDS` 白名单 |
| 省级基座设计 | `docs/FISCAL_PROVINCE_SUBSTRATE.md` | spike / 参数真源 |
| 旧 `calc_province_fiscal` | — | **已删除，勿再引用为现役核** |
