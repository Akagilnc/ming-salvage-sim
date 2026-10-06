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
| `gentry_resistance` | INTEGER 0-100 | 士绅阻力；进入省级 settle / 政治压力 |
| `unrest` | INTEGER 0-100 | 民变压力；进入省级 settle / 事件门 |
| `fiscal` | JSON | 税种细分 + settle 基座 + 腐败度，见下表 |

`fiscal` JSON 字段说明：

| key | 单位 | 说明 |
|-----|------|------|
| `guan_min_tian` | 万亩 | 官民田 |
| `wang_tian` | 万亩 | 藩王庄田，免税；没收后转皇庄 |
| `huang_tian` | 万亩 | 皇庄田亩记录（月收预算以 fiscal_config 皇庄基准为准） |
| `liao_xiang` | 万两/月 | 辽饷月摊派额（settle / 叙事用） |
| `salt_tax` | 万两/月 | 盐税月基数，hub 旁路汇总 |
| `commerce_tax` | 万两/月 | 商税月基数，hub 旁路汇总 |
| `corruption` | 0-100 | 腐败度；region_delta 可写，推演材料可读 |
| `settle` | object | 省级财政基座 st/p；hub tick 真源 |

---

### 月结算（substrate hub）

现行月度国库收入不再走省级 flat 系数公式，而由 **substrate hub** 统一投影与落账：

1. **省级 settle tick**（`db.settle_province_tick` / `flows._advance_province_fiscal_substrate`）：明控且已 seed `settle` 基座的省推进三饷、火耗、起运、逋赋等账本。
2. **起运到京** → 国库；太仓人类/沉没漏损按 `fiscal_config` 中央损耗率拆分。
3. **盐税 / 商税** 仍从各省 `fiscal` 旁路汇总入中央（hub 侧通道）。
4. **京运补 / 中央军饷** 按饷源份额拟拨，经 hub outbound 扣账，不预演未来转运损耗。
5. **皇庄** 走 `fiscal_config.皇庄_base × 皇庄_rate` 入内库（预算与落账同源：`compute_budget_lines`）。
6. **fixed 科目**（宗禄、官俸等）由 `fiscal_config` 中 `budget_role=fixed` 项按 base×rate 遍历落账。

入口：`flows.apply_fixed_period_flows`（pre_settle 固定财政段）。预算展示同源：`flows.compute_budget_lines`。

设计细节见 `docs/FISCAL_PROVINCE_SUBSTRATE.md` 与 ADR 0019/0021（ADR 正文整理归 #1881）。

---

### 动态变化

**收入/压力路径（现行）：**
- 省级 settle 参数与士绅/民变/腐败进入 tick 账本，影响起运与地方存留
- 灾荒、加派、清丈等经人口池与 surcharge/levy 通道改应征与入池
- 整治贪腐 / 巡按 → `regions.fiscal.corruption` delta（仍由 region_delta 白名单写入）
- 盐税/商税基数改各省 `fiscal` 字段才进 hub 旁路；皇庄改 `fiscal_config`

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
- **LLM 触发条件**（`score_extractor.md`）：整治贪腐/巡按/抄家/杀士绅头领 → 负值 ±5~±20；放任失控 → 正值

---

## 藩王庄田没收

```
region_delta: {"henan": {"wang_tian_transfer": 40, "reason": "…"}}

apply 时：
  wang_tian -= 40
  huang_tian += 40
  同时：gentry_resistance 等政治反应由裁判另产
```

河南（福王）、湖广（楚王）、山西（晋王）是主要藩王省份。皇庄月收预算仍以 `fiscal_config.皇庄_base` 为现行基准。

---

## 代码位置

| 功能 | 文件 | 函数/位置 |
|------|------|---------|
| 月度财政落账 | `ming_sim/flows.py` | `apply_fixed_period_flows` |
| 预算同源 | `ming_sim/flows.py` | `compute_budget_lines` |
| 省级 settle 桥 | `ming_sim/db.py` | `settle_province_tick` |
| 腐败度 delta 落库 | `ming_sim/db.py` | `apply_region_deltas` → FISCAL_SCORE_FIELDS 分支 |
| 省级字段白名单 | `ming_sim/constants.py` | `FISCAL_SCORE_FIELDS` |
| fiscal_config 初始值 | `ming_sim/db.py` | `init_fiscal_config` |
