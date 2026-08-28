# 人物行旅尺度

本表按 [ADR 0094](../docs/adr/0094-province-weight-distance-graph-baked-travel-matrix.md) 的省级邻接图与 [ADR 0095](../docs/adr/0095-person-transit-deterministic-countdown.md) 的倒数语义校准；它记录内容尺度，不另定义引擎契约。

## 本次校准

省级距离是史实近似，而非驿路里程复原。京豫官道保留河南—北直隶 1.0；南直隶节点权重由 1.2 调为 2.2，使南京赴京不再与河南同月抵达；广东节点权重由 1.0 调为 0.6，江西—广东大庾岭边附加由 0.3 调为 0.0，以免南直隶尺度调整把广东锚推过三个月。大庾岭的地理阻隔仍由路径两端节点权重承载。

北极星三锚（同一启程回合，启程当月不减）：

| 人物与路线 | 矩阵距离 D / 速度系数 | 首次抵京候见 |
| --- | --- | --- |
| 孙传庭：河南→北直隶，常行 | 1.0 / 1.0 | T0+1 |
| 徐光启：南直隶→北直隶，加急 | 1.6 / 1.5 | T0+2 |
| 袁崇焕：广东→北直隶，常行 | 3.0 / 1.0 | T0+3 |

后续调参只改 `content/distance_graph.json` 并重烘，不改倒数引擎。`content/distance_matrix.json` 是生成物，命令为：

```bash
python3 scripts/bake_distance_matrix.py
```
