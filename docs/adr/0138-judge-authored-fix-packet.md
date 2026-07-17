# 0138 判词即包：送修正文由判官执笔，runner 单路径原样搬运

Status: Accepted（决策：2026-07-17 #967 grill 前对话，owner 拍「就不能判官所有东西都搬运？」——纯形态无条件分支）

送修（coder-fix）作业包正文=判官 continue 判词正文，逐字原样进包；runner 只有这一条搬运路径——无「见某字段才替换」的条件分支，无裸 finding 转发旁路（ADR 0131 零判断权原样保全）。首轮判词可薄（finding + authority 锚点 + 边界），有病史则综合（病史全列、方向钉、拆除清单）——厚薄是判官的笔法判断，不设机械触发条件；soul 侧义务已立（verify soul main@074e7b6a，schema 未承载前经上抛通道履行）。

弃案：可选 `invariantOrder` 字段 + runner 条件替换（runner 又生判断，违 0131）；机械触发阈值（违「判卡死靠走势」禁机械规则）。实证：同一 grok，裸 finding 六轮同形全败 vs 判官综合单一轮命中（2026-07-17，档案见 #967）。
