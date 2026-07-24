# 0132 — 修复环判官化与完成机制统一（#919 并波宪法）

Status: Accepted（2026-07-15，owner 拍板；cmr 7 轮收敛，处置台账见 #919 评审记录）

一句话：修复环的收敛判断权从机械规则移交给**持久 verify 判官**（一个判断函数、多处开庭），完成的定义统一为**单迭代 + 干净退出 + 官方 typed 收据信封**，业务失败以**真名终态与非零退出码**呈现。

决策清单（详文与验收真源 = PRD #919 + #918 Grill D1-D8，本页只作宪法目录户口）：

- **判官身份**：reviewer 槽并入 verify——单一判官、persistent 跨轮记忆；真审卷 = Runner 唯一派发的每轮 fresh 腿，reviewer soul 走 provider-native instruction channel、与 task prompt 分离，腿只产 raw prose 交判官。S4 机械分类站溶解为判词三态 `converged | continue | escalate`（escalate 走既有决策门停车，答后原地 resume）。
- **毙单权**：判官按四理由（违宪/过度防御/事实不成立/越权加戏）毙单，毙单 = findings 状态翻 refuted，仅活单送修；fixer 的 refuse 通道保留为第二道闸。
- **机械法废除**：数量清零/轮数阈值式收敛判定、`CODER_REC_FALLBACK_AFTER_ROUNDS` 轮数推进、池隔离（pool separation）、completionSignal 全链、Ralph 多迭代预算——全数拆除。
- **换人**：advance_coder 归判官判词；推进目标无效则留守原 coder、结果回判官桌——run 永不因顺位问题退出。
- **完成机制**：全工位 `maxIterations=1` + sandcastle 官方 typed 收据信封（每站薄 schema 归统一契约模块；信封只含路由/完成态交通信号，业务 cargo 正文一律 opaque、runner 不读字）。
- **终局真相**：终态实名（`verify_failed` 大杂烩拆分）、fresh/resume 同名同码、终态→非零退出码纯映射、任何非成功终局必落盘 tagged S8 并出声。
- **两庭一机**：family 后段关环同样消费判官判词（第二台 open-count 数数机删除）；ADR 0030 的有序双闸（completeness→correctness）保留，各庭独立开庭、各自 converged 方进下一闸。

波及修订：ADR 0129 / 0130 / 0030 / 0131 的相关条款经本决策拍定修订，**随 #919 对应切片落地生效**（各 ADR 头部有修订预告；落地前按现文执行）。
