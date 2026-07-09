Status: Proposed（2026-07-09：S12 grill-with-docs 收敛；待设计评审后 Accepted）

# 0123: 文档发布与自动合并不以路径白名单为闸

S12（文档发布）真跑 `/gstack-document-release` 后，编排器不再用「改动路径是否落在文档白名单」决定发布成败或是否允许自动合并。闸只认：文档发布 worker 成功收尾（`released`，含合法空跑）、有 commit 时已推到 PR 远端头，以及合并前对当前 tip 的 live readiness（CI / threads / ruleset）。理由：个人开发流程里该 skill 产出面固定，窄白名单会误杀合法文档改动且与「轻流程」目标相悖；脏 tip 仍由 live readiness 兜底。此决定 supersede #602 验收里「doc-only 路径白名单」那一层（其余：收敛后跑文档发布、非交互、对 post-doc tip 重查 readiness——仍有效）。
