Status: Accepted（2026-07-09：grill-with-docs → #735 PRD → 本地设计 cmr completeness+correctness 收敛：grok-4.5 + composer-2.5-fast + agy）

# 0123: 文档发布与自动合并不以路径白名单为闸

S12（文档发布）真跑 `/gstack-document-release` 后，编排器不再用「改动路径是否落在文档白名单」决定发布成败或是否允许自动合并。文档发布 worker 自行核验成功收尾（`released`，含合法空跑）与其外部副作用；Runner 不读取路径、commit 或 PR。现行交付顺序只由 #869 定义，本 ADR 不授权 doc release 后直接合并，也不授权 Runner 按“是否产生 commit”分叉。此决定 supersede #602 验收里「doc-only 路径白名单」那一层。
