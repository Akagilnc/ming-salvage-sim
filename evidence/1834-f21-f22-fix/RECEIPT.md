# 1834 F21/F22 修内司回执（自审修正轮）

HEAD_BASE: `5b645e867006107bd0e479a87cd70fa77c50ce7f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`

## 本轮纠正（对复核）

1. **ENUM_CMDS 无实际命令** → 重写 `ENUM_CMDS.txt`：每节含完整 `CMD:` shell、可复现 HIT_COUNT；2154/91 由 CMD1_PRIOR / CMD3_PRIOR 重现；scripts 扩谓词 CMD1_SCRIPTS=2230、CMD3_SCRIPTS=93；CMD2_ALL_ASSIGN=1155 作非名滤语义主集。
2. **appointed/registered/displaced 出类 KEEP** → 按用户/末判授权清除已作废结构：无生产赋值、仅透传/空 kwargs 的专属旧能力 **DELETE**（字段、`_chat_payload` 参数/透传、`types.ts`、`terminal` 专属打印、测试空 kwargs）。
3. **splitReportItems 非生产 KEEP** → 零调用且加工自由正文 → **DELETE**（F22 退役专属工具）。
4. **枚举仍缩窄** → F22 用 ChatTurn 全字段矩阵 + format 零调用文本工具 + 扩展符号集（非仅 compose）；F21 含 scripts，名滤不作唯一候选集。成员表列齐 CMD3_SCRIPTS 93 条。

## 根因（不变）

- **F21**：人读 `station` / 高亮短语在 map/物化/读取链曾被 strip 改写。
- **F22**：退役零消费者专属结构残留（含无赋值透传字段与死工具）。

## 生产改动（本轮增量）

| 类 | 增量 |
|---|---|
| F21 | 无新增 FIX；三站点保持；93 条名滤候选全归组 KEEP（机器键/判空/外壳等） |
| F22 | DELETE `appointed_minister`/`registered_minister`/`displaced_minister` 全链；DELETE `splitReportItems` |

## 真实入口旧红新绿

复用上轮真实方法（`git show ebcd2d1a1` 完整旧函数装入 mapper / parse / apply；伪变异仍撤销见 `MUTATION_FAKE_REVOKED.txt`）。stdout 见 `mutation_real_entry.out`（本轮复跑确认仍绿）。

## 聚焦测试

七前缀：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

- Python：`258 passed, 1 warning in 9.06s`（real 9.56s）→ `pytest-focus.out`
- Web：`Test Files 6 passed；Tests 164 passed；Duration 4.59s`（real 4.72s）→ `vitest-focus.out`

## 准确剩余 scope（不冒充全清）

- `web/src/format.ts` `EN_VALUE_CN`：零引用查找表，非自由正文加工；本轮不泛删。
- F21 CMD1_SCRIPTS 2230 / CMD2 1155 中非自由字段搬运的机器键/协议/展示切片：已语义 KEEP，若后续发现新同形自由字段写点再开。
- 冻结 evidence 内旧符号叙述：不改写。
- 本票其它未结类 / 接线票（#1861/#1840/#1843 等）：不在本回执范围。

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill。
- 未新建分类层或永久证明测试。
- 自查二连：同类型（专属零消费删 vs 现役共享留；名滤交叉 vs ALL_ASSIGN 主集）；引入（删透传不影响 answer/court_action 现役载荷）。
