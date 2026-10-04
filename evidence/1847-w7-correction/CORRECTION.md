# #1847 w7 — 主席复检：废除伪结清脚本

## 主席指摘（成立）

`finalize_judgments.py` 用 `FREE_TEXT_NAMES` + snip 正则自动分桶：

- 所有 `read_text` → `G_IO` KEEP
- 所有未命中名字 → `G_NOT_TRANSPORT`
- 所有 slice → 展示截断 KEEP

这不是逐项阅读来源→去向，不能作法源或真实行为证明。

## 本轮清除（授权）

已删除本轮自建伪结清物：

- `finalize_judgments.py`
- `disposition_summary.json`（`unresolved_open_buckets=0` 伪收敛）
- `n6_map.tsv` / `n6_groups.tsv`
- `n11_closure.tsv`（种子列表冒充实消费者闭包）
- `n13_final.tsv`（机械 KEEP_*）
- `n14_map.tsv` / `n14_groups.tsv`（`assert a==b` 一律 `BEHAVIOR_EQUALITY`）

## 保留

- `scan_n6_n11_n13_n14.py` — **仅机械枚举**（`POTENTIAL_*` / `ABSENT` / `KEEP_LIVE_CONSUMER` 消费者图事实）；**永不**从名字表发明语义 KEEP
- `n13_lifecycle_probe.py` + `.json` — 真实入口生命周期变异（非源码判桶测试）
- 人工表：`human_n6.tsv` / `human_n11.tsv` / `human_n13.tsv` / `human_n14.tsv`

## 诚实口径

| 面 | 机械候选 | 报告列出 |
|---|---|---|
| N6 | 2894 `POTENTIAL_*`/`TEST_HIT` | 真类成员（残差）+ 合法同根例外（真实调用路径） |
| N11 | 24 闭包符号（旧消费者路径种子+独占 callee） | DELETED / KEEP_LIVE 及本轮删死投影 |
| N13 | 284 hits | 生产软生命周期位点 + 文档化 continue 契约 |
| N14 | 432 hits | 真成员残差/已修 + 例外；**不**把机械 `assert a==b` 当已审成员 |
