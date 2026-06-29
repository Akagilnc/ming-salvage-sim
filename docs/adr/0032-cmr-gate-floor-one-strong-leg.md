# cmr 承重闸底线 = ≥1 强腿，否则 escalate

Status: Proposed（2026-06-29，grill 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

## 决定

家族 integrated cmr 承重闸的硬底线 = **至少一条强腿实际跑成**（单 opus 或单 codex 都算达标）。路线显式声明本路线想要哪几腿；声明的额外腿（agy/gemini 等）运行时死了 = **带 flag 跳过、不阻塞**。跌破底线（强腿全死）= **escalate，不跑零强腿的 cmr**（零强腿 = 橡皮图章，违背承重闸本意）。**便宜实验模型（glm/haiku/spark…）默认不当 cmr 腿**（它们是 coder 槽的；要当腿须显式提升）。

## 为什么

cmr 是承重闸，零强腿放行 = 没牙。但强腿之外的腿（尤其 agy）是**不可预测中途死**（agy 常烧额度，见既往实证），为每种死亡组合预写一条路线不现实。故：路线**声明意图腿**（显式）+ 运行时**哪腿够不着就跳**（容错）+ **硬底线 ≥1 强腿**（跌破即停）。自动涌现：claude-tight → codex 单腿达标；codex 紧 → opus 单腿达标；codex+claude 双死 → 跌破底线 escalate。

## 关联

强腿 = opus / codex(gpt-5.5) / gemini(agy) 这类。本底线是 ADR 0030 拆出的 integrated cmr worker 的运行不变式，与 ADR 0031 路线表的 cmr 腿槽配套（路线填意图腿、本 ADR 定运行时底线）。
