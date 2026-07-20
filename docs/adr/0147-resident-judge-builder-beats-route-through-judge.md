# 0147 判官切片常驻:builder 出拍无条件回判官,预审入环

Status: Accepted(决策:2026-07-20 #1008 grill,owner 逐条拍)

判官自派单起为切片常驻席、收敛退庭;一切 builder 拍(coder 首轮与 fixer 各轮,交计划或交施工不分)出拍由 runner 哑搬 resume 同一判官,判官以既有 JudgeVerdictStatus 判词(**零新状态**)定下一拍——continue=resume 同 builder(准/退/部分撤单等语义全住判词散文,ADR 0141「机器读枚举,活物读散文」),converged=出环;builder 与 reviewer 互不直连,fresh reviewer 保留为判官收货后的独立外闸(自审盲区实证:同家族审自己收敛产物 0 findings),其 findings 亦交判官裁。预审物为散文、不设模板;退回=同 worker 原工作区 resume 续(产出不丢),且通道**双向抗辩**——fixer 可举证承重翻案,「删压过加」删到举证为止;换棒/诊断令/上抛=判官走势全权,不设机械阈值(同 0138 弃案理由)。

弃案:预审专用二态/四态枚举(准退撤全是活物语义,溶进 continue+live-finding 计数);builder 直连 resume 判官不经 runner(worker 持控制面权力违 0144 socket 铁律,且丢台账落笔点与监工点);首轮 coder 豁免(多一个条件分支,方向错在首轮最贵,且 tdd 的「seam 事先确认」在容器内正缺对手方)。经济学依据:resume 判官≈免费,fresh 腿贵数量级。实证:codex 手搓判官实录(ak-cc-wiki raw ming-codex-judge-handlane-2026-07-18,§1/2/4/11/13/14/15)。
