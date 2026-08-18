# #474 / #556 全族 DoD 点检（#570 P-9）

全族分母 15 票。逐票附证据指针（测试名 / `文件:行号` / evidence 键）。仅勾选框不算。  
不通过 → 记债（见 [`474-playtest-guide.md`](474-playtest-guide.md)）；全量 pytest 在最终待合并状态跑绿；scripts 闸级手跑附证据。

| 票 | 主题 | 证据指针 |
|---|---|---|
| #571 | S1 案卷底座 | `tests/test_decree_dossiers_571.py`；`docs/SETTLEMENT_FLOW.md:7-15` |
| #557 | S2 参与人名单＋委派链 | 参与人写入/读取：`ming_sim/db.py` `append_decree_dossier_participants` / roster 归一；关联回归见 `tests/test_execution_joint_liability_565.py`（roster 追责） |
| #558 | S3 效果 origin 回指 | `tests/test_effect_origin_558.py`；`tests/test_personnel_origin_prompt_558.py`；`docs/DELTA_SCHEMA.md` origin 节 |
| #559 | S4 案卷关联 | `tests/test_dossier_links_559.py` |
| #560 | S5 颁布关管线 | `tests/test_promulgation_seam_560.py`；`docs/SETTLEMENT_FLOW.md:7-15` |
| #561 | S6 颁布判官 | `tests/test_promulgation_judge_561.py`；闸 `scripts/promulgation_gate_561.py` → `docs/evidence/issue-561-gate.json` |
| #562 | S7 破格标 | `tests/test_office_rank_562.py`；闸 `scripts/break_rank_judge_gate_562.py` → `docs/evidence/issue-562-break-rank-judge.json` |
| #563 | S8 批红三选 | `tests/test_rescript_choices_563.py` |
| #564 | S9 强颁/毁约代价 | `tests/test_override_breach_costs_564.py`；#564 Implementation Decisions（机器契约真源） |
| #565 | S10 执行格连坐 | `tests/test_execution_joint_liability_565.py` |
| #566 | S11 月度进展/密奏 | `tests/test_secret_order_monthly_progress_566.py`；`tests/test_dossier_reported_progress_619.py` |
| #567 | S12 在途拨帑对账 | `tests/test_grant_reconciliation_567.py` |
| #568 | S13 点策 | `tests/test_strategy_selection_568.py` |
| #569 | S14 照账演与认账 | `tests/test_ledger_sim_recon_569.py` |
| #570 | S15 族尾验收锚 | 本片：`scripts/family_tail_acceptance_570.py`、`scripts/midzhi_spiral_judge_gate_570.py`；`tests/test_family_tail_restore_570.py`；`tests/test_p4_guard_new_surfaces_547.py`（扩写）；证据 `docs/evidence/issue-570-*.json`；回注 [`570-adr0055-backref-checklist.md`](570-adr0055-backref-checklist.md)；指引 [`474-playtest-guide.md`](474-playtest-guide.md) |

## 0056 口径点核（空集靶点）

- 无 0056 文档回注条款；不自造靶点。
- 与 #564 Implementation Decisions 对齐：signed `direction`×`intensity`、三笔、零反应不入清单——由 `tests/test_override_breach_costs_564.py` 锁。
