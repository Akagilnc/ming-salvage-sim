# 0140 canonical 测试入口分层：fast 自检线 + full 全量闸线，机械税种判据

Status: Accepted（决策：2026-07-18 #969 grill Q1/Q2，owner 连拍——修宪分层 + 机械判据）

编排器 canonical 测试入口拆两级：`fast`（纯逻辑测试）与 `full`（现全量）。归池用机械税种判据：凡起真进程/真沙箱/真 git 仓的测试（real-sandbox SO 系、e2e-driver 等）进 heavy 池，其余全进 fast——按测试性质自动落池（vitest project/目录约定），无手挑名单、零策展税。义务面同步改写（修 #965 立的「交卷自检=canonical 全量」）：fixer/coder 自检=fast；wave verify、final verify、CI、ship 闸=full——全量兜底三道不动，heavy 面回归最晚在 wave verify 被抓。

弃案：手挑 smoke 名单（名单必腐：新测试默认漏在名单外，fast 覆盖静默退化，另计策展税）；纯技术分池不修宪（969-slice/969-profile 实测：70s 起跑税〔setup 28s + import 45s〕是固定税，纯删测≈无效；不砍 fixer 自检路径的重复全量，就砍不到燃烧大头——一个家族战役烧几十遍全量）。
