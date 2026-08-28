# 案卷 store 摘取（DossierStore）

Status: proposed（大理寺审理中，收敛后转 accepted；落地物归 issue #1571；grill 2026-08-27 三轮 12 题定稿，owner 逐轮确认，设计树原话存档 = <https://github.com/Akagilnc/ming-salvage-sim/issues/1571#issuecomment-5437649299>；依赖 ADR 0150 的目录法源与无兼容层纪律 0150-D8）

案卷的全部持久化读写与案卷表 schema 从 GameDB 摘出，归独立的 `DossierStore`（`ming_sim/entities/dossier/` 包，0150 实体目录法源的首例 store 形态），GameDB 侧不留任何转发 facade；verdict 效果物化（0150 决定 5）与判官 LLM 生产侧留外，不归它。

**为什么**：案卷是 GameDB 最大单一 concern 且为当前迭代主线，摊在 db.py 使每处语义改动牵动多个文件，私有常量与裸 SQL 已外泄成跨模块公共知识；摘取使案卷语义单真源化，facade 态（壳在、实现原地）已被 0150-D8 否决。不可逆的只有「归属 + 无 facade」这一刀；interface 形状、事务边界、纵切片、测试处置皆是可逆施工细节，真源在 issue #1571 与 `docs/evidence/issue-1571/` 四件，本 ADR 不双写。
