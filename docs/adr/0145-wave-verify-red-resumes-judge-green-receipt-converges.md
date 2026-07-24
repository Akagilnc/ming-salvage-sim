# 0145 — family verify 红转判官重判轮,绿回执唯一收敛,判词契约新增 toolchain

Status: Accepted(2026-07-20 owner 拍;内容为 #1027 票面四条 owner 裁决的转写。2026-07-22 修正:原转写以「wave verify」窄化了 owner 裁决——verify 全线只有一套机制,scope 是参数不是分层;checkpoint / final verify 同规适用,#1107 落地。原「仅 wave 分诊席」限定词判违宪删除。)

family 全量 verify(wave / correctness checkpoint / final)红不再终局甩人:resume 既有判官形制开重判轮,但 converged 判词以**绿色机械重跑回执为硬前置**——测试红绿是事实不是意见,评审意见只指导修法。共享判词契约 `JudgeVerdictStatus` 新增第四终态 `toolchain`(分诊判官宣告环境红,runner 照旧 `verify_failed` 甩人,零分类零读文)。被否:runner 侧 exit-code/盯文自分类(过度防御)、无判官旁路循环(第二套控制形状)、按调用点差异化处置(2026-07-22 owner:「全部都是一套机制…只是各自的职责和范围不同」)。
