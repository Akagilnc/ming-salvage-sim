# 0145 — wave verify 红转判官重判轮,绿回执唯一收敛,判词契约新增 toolchain

Status: Accepted(2026-07-20 owner 拍;内容为 #1027 票面四条 owner 裁决的转写)

wave verify 红不再终局甩人:resume 既有判官形制开重判轮,但 converged 判词以**绿色机械重跑回执为硬前置**——测试红绿是事实不是意见,评审意见只指导修法。共享判词契约 `JudgeVerdictStatus` 新增第四终态 `toolchain`(wave 分诊判官宣告环境红,runner 照旧 `verify_failed` 甩人,零分类零读文)。被否:runner 侧 exit-code/盯文自分类(过度防御)、无判官旁路循环(第二套控制形状)。
