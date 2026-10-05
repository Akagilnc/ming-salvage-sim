# #1843 修内司回执（w5 / F2-R13 acceptance fix）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r13-f2-compat`
冻结判词：`05-1843-judge-7402d3b80.json` 末份（F2-R13-1 / F2-R13-2）
派单：`fix-packet.md`
基线：`7402d3b80`；本轮在既有 r13 提交之上再修验收点。
未 amend / stash / push / PR；七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。不宣称合并/关票。

## 验收点处置

1. **CLAUDE.md**：`git diff 7402d3b80 HEAD -- CLAUDE.md` 曾擅改财政状态句；无亲审授权，已按 `7402d3b80` 原字节精准恢复该行（新提交，不 rewrite）。
2. **退休旗标壳**：`is_army_pay_source_cutover_enabled` / `is_substrate_hub_fiscal_engine_enabled` / `fiscal_engine` 生产零消费、仅测试断言 → 定义与专属断言删净；测试引用不作保留理由。
3. **evidence 行尾**：TSV CRLF、md 行尾空白已统一为 LF 且无 trailing whitespace；`git diff --check 7402d3b80 HEAD` 须干净。
4. **全仓机械枚举**：`evidence/1843-w5-r13-enum-commands.txt` 为可直接执行的完整 rg 命令（谓词覆盖票面+末判两类定义）；`class-a/b-members.tsv` 为逐名处置表；`class-rescan.tsv` 为施工后复扫。不新增生产扫描机制。
5. **#1471 HUD**：末判已**撤销 HUD 词扫豁免**。纠正上轮回执「G1 已结、负向词扫可留」的陈旧结论；**不恢复词扫**；**保留** `{name,amount}` 键集与输入保真。

## F2-R13-1 续删（消费链）

| 成员 | 处置 |
|---|---|
| 三旗标 API + qa_e1/pay_order/fiscal_bridge 专属断言 | DELETED |
| mutiny/projection/effect_origin 写入 `__army_pay_source_cutover`/`__fiscal_engine` 夹具 | DELETED |
| `test_mutiny_third_strike_318` `parametrize(cutover,(0,1))` 及 per-test 标记写入 | DELETED（坍为单路径行为案） |
| substrate hub / army_pay 物理核、C0/canonical/beyond_intent、人物变更入口、帝国修正、Agno blob、web 事件门 humanize | RETAIN |

## F2-R13-2

| 成员 | 处置 |
|---|---|
| 常熟措辞 / 军队固定句 / 索引名 / 重复 rejected / HUD 词扫 | DELETED（已结或确认不恢复） |
| 键集、输入同值、真实拒收/持久/分类、结构化名单 | RETAIN |

成员表：`evidence/1843-w5-r13-class-a-members.tsv`、`evidence/1843-w5-r13-class-b-members.tsv`
复扫：`evidence/1843-w5-r13-class-rescan.tsv`（仅 web `_legacy_gate_*` humanize + save_meta 注释）

## 纠正前回执错误结论

1. 不得以「测试仍引用」保留退休旗标壳。
2. 删迁移/恒等 True ≠ 可留双路径符号名；无生产消费者则删净。
3. **撤销**「#1471 HUD 负向豁免上轮 G1 已结」：末判撤销词扫豁免；仅保键集与输入保真。
4. 枚举不得只交临时脚本指针或聚合成员标签；须可执行命令 + 逐名表。

## 聚焦测试

七变量 + `PYTHONDONTWRITEBYTECODE=1` + venv python；触及面（含删 API 影响的 qa_e1）：

- `tests/test_qa_e1_numeric_presentation.py`
- `tests/test_fiscal_substrate_bridge.py`
- `tests/test_pay_order_override_653.py`
- `tests/test_mutiny_latch_315.py`
- `tests/test_mutiny_noop_whitelist_319.py`
- `tests/test_mutiny_third_strike_318.py`
- `tests/test_mutiny_progression_316.py`
- `tests/test_mutiny_redemption_317.py`
- `tests/test_player_army_projection_321.py`
- `tests/test_effect_origin_558.py`
- `tests/test_person_delta_adapter.py`
- `tests/test_population_unit_648.py`
- `tests/test_qa_a3_seed_data.py`
- `tests/test_army_card_status_1501.py`
- `tests/test_rescript_draft_656.py`

实测：`463 passed in 15.03s`。日志：`evidence/1843-w5-r13-pytest-focused.log`。

## 自查二连

- 同类型：旗标壳/无读者标记夹具/双路径矩阵按消费链删；枚举逐名定类；HUD 结论按末判纠正。
- 引入 bug：未动宪法/Soul/席位；未删 hub 物理核与键集；CLAUDE 恢复非改宪施工说明。

## 剩余项

- class-b 谓词宽扫下大量 RETAIN 为结构化契约误触，已逐名定类；若台院收紧非契约定义可再删。
- 不宣称合并/关票。
