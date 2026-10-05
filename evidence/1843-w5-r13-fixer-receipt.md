# #1843 修内司回执（w5 / F2-R13）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`  
分支：`ak-roles/issue-1843-w5-r13-f2-compat`  
冻结判词：`05-1843-judge-7402d3b80.json` 末份（两类未结）  
派单：`fix-packet.md`  
未 amend / stash / push / PR；七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。

## 两类处置

### F2-R13-1 旧兼容协议、双路径及专属支持

| 闭包 | 处置 |
|---|---|
| 财政军饷 legacy regime | **删除双路径**：预算/固定财政/军饷 settle/加派/surcharge 只走 substrate hub；删 cutover-off else、shadow 隔离臂、legacy 引擎拒收臂、pay_order legacy fail-loud；闸方法恒 True/`substrate_hub` 且不再读/写标记 |
| 旧人事顶层翻译与专属闸报告映射 | **删除**：`person_delta_adapter` 只吃 `人物变更`；删旧键翻译、`legacy_gate`/`legacy_partial`/`legacy_spillover`、报告映射与 `allow_legacy_partial_*`；声明入口对非空旧键拒收；结案 `character_status_changes` 响亮退役 |
| save_meta 孤儿存储 | **删除**：建表、写标、`_POPULATION_UNIT_KEY`、专属测试；`population_unit` 恒返「人」 |

**保留（真实消费/契约）**：substrate hub / army_pay 物理核；`population_unit` 读口；`EMPTY_EXTRACTION` / `ITEM_FIELD_ALIASES` / `_canonical_item_fields` / `read_beyond_intent_raw`；`normalize_person_changes(人物变更)`；帝国修正 `legacy_modifiers`/`_income_amount_after_legacy_modifier`（非财政 dual path）；`_agno_legacy_runs_blob`；web 事件门 `_humanize_legacy_gate`（同名异义，非人事 legacy_gate）。

成员表：`evidence/1843-w5-r13-class-a-members.tsv`  
复扫：`evidence/1843-w5-r13-class-rescan.tsv`

### F2-R13-2 非契约措辞锁、内部形状锁及重复断言

| 成员 | 处置 |
|---|---|
| `test_qa_a3`「常熟」in status_reason | **删**措辞锁；保留 office/status/非空 status_reason |
| `test_army_card_status_1501` 固定整句 `_GUANNING_STATUS` | **删**固定句；保留 DB 零改写、键集、共享出口含/不含 status |
| `test_rescript_draft_656` 索引名存在 | **删**；保留列存在/禁列负向 |
| fiscal bridge 四处重复 `rejected` 布尔 | **删**重复行；保留首条 rejected + 持久状态 |

**保留**：输入同值传递、结构化键集、真实拒收/异常/持久状态、必要结构化负向；#1471 HUD name/amount 负向（上轮 G1 已结，非本类误删）。

成员表：`evidence/1843-w5-r13-class-b-members.tsv`

## 纠正前回执错误结论

1. 不得以「表仍现役 / migration 名 / 引用数 / 测试仍引用 / 同文件有活代码 / 历史下界」豁免旧档兼容或双路径。  
2. 删迁移函数 ≠ 删兼容机制；本轮以消费链证明删标后预算仍 hub（267→267），施工前同操作会落到 legacy（267→155）。  
3. ADR 0021 老档续旧引擎、ADR 0009 决定11 历史 delta 翻译、ADR 0088 万人判别，已被后出旧档禁令与 #1843 票面排除，不得再作保留理由。  
4. 输入原文同值传递 ≠ 冻结非契约措辞；不得再把 status_reason/军队叙述整句锁当契约。  
5. 不把 web `_legacy_gate_*`（事件前提 humanize）误并入人事 `legacy_gate` 专属闸。

## 聚焦测试

完整文件清单（触及面，无 deselect）：

1. `tests/test_person_delta_adapter.py`
2. `tests/test_population_unit_648.py`
3. `tests/test_fiscal_substrate_bridge.py`
4. `tests/test_surcharge_causal_chain_650.py`
5. `tests/test_pay_order_override_653.py`
6. `tests/test_qa_a3_seed_data.py`
7. `tests/test_army_card_status_1501.py`
8. `tests/test_rescript_draft_656.py`
9. `tests/test_declaration_dispatch_1835.py`
10. `tests/test_month_chain_1843.py`
11. `tests/test_rejection_wiring.py`
12. `tests/test_issue_entities.py`
13. `tests/test_event_trigger_gate.py`

邻接补跑：`tests/test_power_section_rejections.py`、`tests/test_production_person_key_contract_558.py`、`tests/test_initiative_resolve_pairing.py`

命令前缀：七变量 + `PYTHONDONTWRITEBYTECODE=1` + `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider`

实测：`610 passed in 21.09s`（主聚焦）；邻接 `29 passed, 1 skipped in 1.34s`（后删 1 条跳过的旧键案）。日志：`/tmp/1843-r13-enum/pytest3.log`（仓内副本见下若拷贝）。

## 自查二连

- 同类型：双路径按旗标清理删旧枝；旧人事顶层与专属闸整闭包删；措辞/内部/重复按契约尺删。  
- 引入 bug：未删帝国修正/Agno legacy blob/C0 契约；hub 物理核与人物变更入口保留；事件门 humanize 未误删。

## 剩余项 / blocker

- 无 owner 决定 blocker。  
- always-True `is_*_enabled` / `fiscal_engine()` API 仍留作现役恒等读口（测试与调用方仍引用）；已无切换能力。若要求连 API 符号名一并消亡，属命名清理，不构成双路径。  
- 不宣称合并/关票。
