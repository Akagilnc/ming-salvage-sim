# #634 票面修正案（2026-08-23，ID-12 判官读面入正文＋Blocked-by 对齐；judge run 01a02d87-42bb…@judge）

> 本文件为 GitHub issue #634 票面修订的仓内审计副本（apply 腿 run 结算载体）。票面正文以 https://github.com/Akagilnc/ming-salvage-sim/issues/634 为准。均为票面文本级修复、零范围变更、零代码改动。

## 修法一：2026-08-23 评论修正案（ID-12）全文并入正文验收节

来源：票前审 run 01a02ca4-6885…@judge（continue）；法源 #640 庭裁 r1 F1 明文将「实际召对判官接入」指派归本票；head 上 `project_relation_ledger` 零生产调用方。

并入验收节末条原文：

> - 召对判官输入面经 `ming_sim/relation_read.project_relation_ledger(viewer=None)` 单一接缝接入账本全知机面（ID-12，2026-08-23 庭裁修正案，run 01a02ca4-6885…@judge）。机械验收沿用 #640 已交付契约：① fixture 断言判官上下文含账本读面、有账与无账行为可辨；② 判官机面为 `viewer=None` 全知面，与角色裁切面不混用。禁平行表/第二套序列化/缓存；DTO 五字段白名单与 TD-7 哨兵口径照抄 #640 冻结文本——引用不复制。

## 修法二：陈旧「Blocked-by：S1」行改写

正文尾部「Blocked-by：S1。」与原生 metadata 不符（原生 blocked-by 为 #632+#633，均已 CLOSED，逐票核实）。改写为：

> Blocked-by：#632、#633（原生 metadata，均已关闭）。

## 范围声明

- 仅 issue #634 正文文本＋本审计副本；r1/r2 修正案原文一字未动。
- 零代码、零测试改动；施工线凭完整票面（八项验收＋r1/r2/r3 修正案）另启。
