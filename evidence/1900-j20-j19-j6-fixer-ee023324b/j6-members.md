# J6／J17 成员表：盯文、退役配套、前置遮蔽伪证

## 类定义（末份判词）
清除盯文、退役行为配套及被其他前置失败遮蔽的证明。必要负向须让其余前置合法、实际经过所保失败行为，并在外部结果上具有辨别力；复用已有测试；保留拒收、回滚及同步；不放松断言、不以替身吞行为；不另禁并发/同步、不加生产测试钩子。J17 来源负回退并入本类。

## 枚举命令
- `rg -n 'dossier_reconciliations' tests ming_sim docs --glob '!evidence/**'`
- `rg -n 'decree/event_pool|过月中断|interrupted after|士气大振' tests --glob '*.py'`
- `rg -n 'write_gate_already_held' tests --glob '*.py'`
- `rg -n '施动者.: .甲.|受动者.: .乙.' tests/test_relation_capture_633.py`
- 输出见同目录 `j6-enum-cmds.txt`

## 成员与语义核验

| 成员 | 语义 | 处置 |
|---|---|---|
| tests/test_rejection_wiring.py:69–105 `dossier_reconciliations` 提案 + 空对账宣称回滚 | 退役提案；无崩溃时空对账无辨别力 | 删除退役提案夹具与对账空断言；保留拒收 flush 后崩溃 → 无行/无 jsonl 回滚 |
| tests/test_rejection_wiring.py:124 `"decree/event_pool" in reason` | 盯文 | 改断言 section + category 结构化；reason 仅非空 |
| tests/test_rejection_wiring.py:240 `"士气大振"/"非法字段" in reason` | 盯文 | 改断言 category/section 结构化 |
| tests/test_month_chain_1843.py:123、322 注入异常消息子串 | 盯文 | 删除子串断言；保留 cause 类型 + 落账/暂存外部结果 |
| tests/test_qa_t1…:356–388 held 闸无草案即 ValueError | 前置遮蔽持闸 | 补 allow_empty_decree + 替 resolve_directives（非被测）使到达持闸落相位；断言相位与闸仍由调用方持有 |
| tests/test_relation_capture_633.py:209–260 甲→乙 来源负向且去掉同批合法项 | J17 回退：端点拒收遮蔽来源闸 | 恢复真人物 + 同批合法「盘面自发」项；禁用来源闸须红 |
| shape_garbage / non_string 用甲乙 | 失败点在 shape，早于端点/来源 | 保留（非本类遮蔽） |
| tests/test_grant_reconciliation_567 等 list_dossier_reconciliations | 引擎核账真源读缝，非退役提案 | 保留 |
| docs 退役说明 / EMPTY_EXTRACTION 已删键 | 说明 | 保留；不把提案写回 |

## 保留
- 真实拒收落库与 jsonl 同步
- flush 后崩溃回滚无行无镜像
- SettlementAbort 恢复后续跑
- 来源/端点合法正向与结构化拒收负向

| tests/test_section4_rejections.py 同类盯文 | 语义同 inertia 案 | 已改结构化 |
