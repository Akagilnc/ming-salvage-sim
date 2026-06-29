# cmr 承重闸底线 = ≥1 强腿，否则 escalate

Status: Accepted（2026-06-29；本地 cmr 8 轮[完整性 4 + 正确性 4] + 线上 bot 3 轮双闸收敛，PR #425）

## 决定

家族 integrated cmr 承重闸的硬底线 = **至少一条「撑底线强腿」实际跑成**。**撑底线强腿只认 opus 或 codex**（单 opus 或单 codex 都算达标）；**agy/gemini 不撑底线，只是 bonus 腿**（有它更好、跨家族多一票，但不可靠、不能单独托起承重闸）。路线显式声明本路线想要哪几腿；声明的腿运行时死了 = **带 flag 跳过、不阻塞**。跌破底线（opus 与 codex 都没跑成）= **escalate，不跑没牙的 cmr** —— **即便 agy 还活也 escalate**（把整道闸托给一条爱挂的 gemini 不稳）。**便宜实验模型（glm/haiku/spark…）默认不当 cmr 腿**（它们是 coder 槽的；要当腿须显式提升）。

## 为什么

cmr 是承重闸，零撑底线强腿放行 = 没牙。bonus 腿（尤其 agy）是**不可预测中途死**（agy 常烧额度，见既往实证），为每种死亡组合预写一条路线不现实。故：路线**声明意图腿**（显式）+ 运行时**哪腿够不着就跳**（容错）+ **硬底线 ≥1 撑底线强腿**（跌破即停）。自动涌现：claude-tight → codex 单腿达标；codex 紧 → opus 单腿达标；codex+claude 双死 → 跌破底线 escalate（agy 即便活也不顶）。

**谓词的域 = 实际跑成的腿，执行后判**：先跑完声明的腿 → 收集真正成功的那批 → 对成功集判 `meetsFloor` → escalate 或放行。"实际跑成"是载重词（不是对声明腿判，是对成功腿判）。

## 关联

撑底线强腿 = opus / codex(gpt-5.5)；agy(gemini) = bonus 腿（跨家族加一票、但不撑底线）。**实现上 `meetsFloor` 查 ADR 0031 registry 的 `strong-leg` 标（从跑成的腿 slug 解析），不字面匹配 "opus"/"codex" 字符串**——codex 的真 slug 是 `gpt-5.5`、未来强模型（如 opus-v2）也靠标不靠串；本文「只认 opus/codex」是"哪些 slug 该带 `strong-leg` 标"的**政策**、非运行时的字符串判等。本底线是 ADR 0030 拆出的 integrated cmr worker 的运行不变式，与 ADR 0031 路线表的 cmr 腿槽配套（路线填意图腿、本 ADR 定运行时底线）。
