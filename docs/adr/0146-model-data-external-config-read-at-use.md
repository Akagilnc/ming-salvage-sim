# 0146 — 模型数据外置仓外配置,用时现读不留常量

Status: Accepted(2026-07-20 grill,#1004)

花名册与注册表数据行外置为 `~/.sc-orchestrator/` 配置文件(env 路径注入,同 route-presets 待遇);代码只留 provider 接线逻辑与 fail-closed shape 校验,名单用时现读——改名单=编辑文件,下一次派 worker 生效,零 PR 零监听(实证 #1003:加两候选走了 40 分钟 PR 仪式)。池表暂留代码,docs/CODER_ROSTER.md 降为指针。
