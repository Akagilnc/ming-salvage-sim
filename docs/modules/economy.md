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

## 固定月度科目（`fiscal_config`）

`content/fiscal_config.json` 中 base/rate **直接是月度**单位（万两 / %）。`flows.compute_budget_lines` 与 `apply_fixed_period_flows` 对 `budget_role=fixed` 项按 `round(base × rate / 100)` 落预算与账，**不再做季度÷3 换算**。真源以该 JSON 与 `db.init_fiscal_config` 为准；下表摘录现行默认月基准（rate=100 时的月额）。

### 国库 fixed 支出（摘录）

| 项目 | base（月） | 说明 |
|------|-----------|------|
| 宗室禄米 | 120 | 诸藩禄米月度账面；削藩可降 |
| 百官俸禄 | 25 | 在京百官（含地方折色） |
| 赈灾备用 | 5 | 制度性预留 |
| 工部 | 5 | 工部日常维护 |

军饷不在 fixed 目录：预算分列「中央军饷拟拨」「京运补拟拨」，实拨走 substrate hub。建筑维护按各建筑 condition 折算，不进 fiscal_config base。

### 内库 fixed（摘录）

| 项目 | base（月） | 方向 |
|------|-----------|------|
| 宫廷开支 | 7 | 支出 |
| 内廷俸禄 | 5 | 支出 |
| 妃嫔供奉 | 3 | 支出 |
| 织造 | 12 | 收入 |
| 矿税 | 3 | 收入 |
| 皇庄 | 20 | 收入（`budget_role=dynamic` 专路，仍读 fiscal_config 皇庄_base） |

国库动态收入（起运/盐/商/太仓亏空）与边饷 hub 见上文「月结算（substrate hub）」；开局量级以鲜库 `compute_budget_lines` 为准，不在本文锁死旧估算表。

---

## 腐败度（`corruption`）

- 存储位置：`regions.fiscal` JSON，key=`corruption`，0-100
- **写入**：`apply_region_deltas` 识别 `FISCAL_SCORE_FIELDS`，解析 JSON → patch → 写回
- **读取／供料**：世界段与大臣材料目录按需投影地区财政特征；不再经已退役的五模块 `score_extractor` 或独立 `score_extractor.md` 抽取。数值变更由月链声明 / region_delta 结构化落账。

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
