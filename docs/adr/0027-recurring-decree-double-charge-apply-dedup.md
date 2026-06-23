# 经常性拨款双扣消解：apply 端确定性 dedup（承诺主载体 wins）

Status: Proposed（2026-06-23，grill #339→#340 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

## 背景

ADR 0013 承诺载体已实现（#227–231）：经常性圣旨拨款应走**单一** issue `ongoing_effects.economy`（D1 主载体）。但实玩实证（turn5）每道经常性拨款仍**月扣两次**（徐光启令 50 → 扣 112/月）：两个**并行**的 extractor 模块对同一笔各自登记——`internal` 模块产 `新立月度收支`（fiscal_create，当成「常设月固定科目」），`issues` 模块产承诺 issue 带 `ongoing_effects.economy`（当成「圣旨承诺」）。两模块运行时互不可见，无人去重。

## 决定

**在 apply 端（`apply_score_extraction` 合并后的 delta）做确定性 dedup**：凡同批存在 `origin_kind=decree` 的承诺 issue-ongoing 占某账户某科目，则同批、同账户、**科目名归一化相符**的 `fiscal_create` 一律丢弃（承诺是主载体，ADR 0013 D1）。这是代码硬判、不依赖 LLM 自觉。

创建端 prompt 边界（`internal` 模块不给「圣旨拨款承诺」建 fiscal_create、只留给真·永久制度科目）**仅作减噪、非解法**——prompt 拦不住 LLM（本仓 keystone：确定性闸才承重）。

## Considered Options

- **纯创建端 prompt**：否决——prompt 会漏，不解决问题、只降撞车频率。
- **精确 provenance 匹配**（给 fiscal_create 加诏书 ref，按 ref 精确去重）：暂否——两条记录无共享 key，`internal` 从散文抽、给不出可靠诏书 id；为低概率残留上 schema/契约改不划算。可逆，留作升级路。

## Consequences

- 常见情形确定性消解：两模块读同一份邸报、科目名一致（实测皆「徐光启三务公费」）→ 账户+名一撞即丢，双扣消失。
- **残留**：两模块给同一笔起**不同名** → 漏匹（概率低，同源文本）。以**日志观测**兜底——「同批、同账户、有 decree 承诺却未匹配上的 fiscal_create」打日志当试玩信号；真在试玩看到漏，再升级到精确 provenance（可逆，不预先上 schema）。
- 范围：#340（吸收 #339 P0 双扣）。不含抬价（#341）、cap 口径（随单一载体自然月度封顶）、密令零扣（#340 同票另一面，同走「承诺=单一载体」）。
