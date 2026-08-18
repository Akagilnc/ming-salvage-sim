# #474 / #556 全族 DoD 点检（#570 P-9）

全族分母 15 票。**逐票逐 AC** 附证据指针（测试名 / `文件:行号` / evidence 键）。仅勾选框不算。  
不通过 → 记债（见 [`474-playtest-guide.md`](474-playtest-guide.md)）；全量 pytest 在最终待合并状态跑绿；scripts 闸级手跑附证据。

---

## #571 S1 案卷底座

| AC | 证据指针 |
|---|---|
| 收夜逐条落案卷 + restore 列出 | `tests/test_decree_dossiers_571.py`（create/list/restore 族） |
| 密令应允同步案卷身份 | `tests/test_decree_dossiers_571.py`（secret_order 外键/时序） |
| 状态机四值 + 留中回流组合态 | `tests/test_decree_dossiers_571.py`（status 枚举/hold 回流） |
| 结构化载荷物化 / 叙事无重放义务 | `tests/test_decree_dossiers_571.py`；`docs/SETTLEMENT_FLOW.md:7-15` |
| 密令单向外键 + 人物终态挂钩结案 | `tests/test_decree_dossiers_571.py` |
| 撤回本轮不留幽灵 | `tests/test_decree_dossiers_571.py` |
| 未表态默认同意成案 | `tests/test_decree_dossiers_571.py` |
| origin_ref 反查承诺 | `tests/test_decree_dossiers_571.py`；`docs/DELTA_SCHEMA.md` origin 节 |
| 结算全量回归 | 全量 pytest |

## #557 S2 参与人名单＋委派链

| AC | 证据指针 |
|---|---|
| 双主办/协办职分落账 | `ming_sim/db.py` `append_decree_dossier_participants`；`tests/test_execution_joint_liability_565.py`（roster 追责读端） |
| 推演追加委派人正确 | `tests/test_execution_joint_liability_565.py` |
| 知情档落库 | `tests/test_execution_joint_liability_565.py`（知情档不入连坐读端） |
| append 不可静默覆盖 | `ming_sim/db.py` append 语义；关联单测见 565 roster 夹具 |

## #558 S3 效果 origin 回指

| AC | 证据指针 |
|---|---|
| 新效果可溯源案卷 | `tests/test_effect_origin_558.py` |
| 缺回指拒收 / 自发哨兵 | `tests/test_effect_origin_558.py` |
| 案卷无效果清单字段 | `tests/test_effect_origin_558.py` |
| 载荷类 dedup / 叙事涌现 | `tests/test_effect_origin_558.py`；`tests/test_personnel_origin_prompt_558.py`；`docs/DELTA_SCHEMA.md` origin 节 |

## #559 S4 案卷关联槽

| AC | 证据指针 |
|---|---|
| 护行→拨饷三链双向可达 | `tests/test_dossier_links_559.py` |
| 复述确认收窄 | `tests/test_dossier_links_559.py` |
| 不存在案卷拒收留痕 | `tests/test_dossier_links_559.py` |

## #560 S5 颁布关管线

| AC | 证据指针 |
|---|---|
| 注入打回零效果 / 顺颁照落 | `tests/test_promulgation_seam_560.py` |
| turn/atomic/ready 续跑 | `tests/test_promulgation_seam_560.py` |
| 坏 shape 拒收 | `tests/test_promulgation_seam_560.py` |
| stub 零新增等待 | `tests/test_promulgation_seam_560.py` |
| 聚类×入判×物化对照表 | `docs/SETTLEMENT_FLOW.md:7-15`；#513 回注 |
| pre_settle staging | `tests/test_promulgation_seam_560.py`；`docs/SETTLEMENT_FLOW.md:41` |
| advance_without_edict 同挂 | `tests/test_promulgation_seam_560.py` |
| 待判集=DB 全部准旨 | `tests/test_promulgation_seam_560.py` |
| ready skip turn-scoped | `tests/test_promulgation_seam_560.py` |
| verdict schema 全形 | `tests/test_promulgation_seam_560.py`；`ming_sim/strict_types.py` |

## #561 S6 颁布判官

| AC | 证据指针 |
|---|---|
| 大政令打回 / 寻常顺颁〔闸〕 | `scripts/promulgation_gate_561.py` → `docs/evidence/issue-561-gate.json` |
| 留中重判可改〔闸〕 | 同上 evidence `scenarios` |
| 默认同意与亲允同批〔CI〕 | `tests/test_promulgation_judge_561.py` |
| 上下文无 satisfaction〔CI〕 | `tests/test_promulgation_judge_561.py` |
| 受损清单持久化〔CI〕 | `tests/test_promulgation_judge_561.py` |
| 密令/内库豁免 | `tests/test_promulgation_judge_561.py` |
| schema 校验坏输出 | `tests/test_promulgation_judge_561.py` |
| break_rank 可选输入 | `tests/test_promulgation_judge_561.py` |
| 打回邸报无「已办成」 | `tests/test_promulgation_judge_561.py` |
| 单次批量调用预算 | `tests/test_promulgation_judge_561.py` |
| mode=中旨 两态〔闸〕 | `scripts/promulgation_gate_561.py` admin/vital midzhi 键 |

## #562 S7 品级带＋破格

| AC | 证据指针 |
|---|---|
| 品级带覆盖 allowed_types | `tests/test_office_rank_562.py` |
| 白身授巡抚打标 / 起复分支 | `tests/test_office_rank_562.py` |
| offices.json 单真源 | `tests/test_office_rank_562.py`；`content/offices.json` |
| 判官破格从严〔闸〕 | `scripts/break_rank_judge_gate_562.py` → `docs/evidence/issue-562-break-rank-judge.json` |

## #563 S8 批红三选

| AC | 证据指针 |
|---|---|
| 三选末态正确 | `tests/test_rescript_choices_563.py` |
| 留中下月重入 | `tests/test_rescript_choices_563.py` |
| 零打回无批红页 | `tests/test_rescript_choices_563.py` |
| 中旨两态 / unpromulgatable 禁强颁 | `tests/test_rescript_choices_563.py` |

## #564 S9 强颁/毁约代价

| AC | 证据指针 |
|---|---|
| 强颁 signed direction×intensity | `tests/test_override_breach_costs_564.py::test_force_land_survey_charges_three_costs_without_eunuch_reaction`；`test_signed_reactions_use_typed_direction_not_narrative_words` |
| 撤回三笔 / 收回零代价 | `tests/test_override_breach_costs_564.py` |
| 中旨标记 append-only + restore | `tests/test_override_breach_costs_564.py::test_costs_are_idempotent_and_survive_restore` |
| 撤回抑制 by_progress 双罚 | `tests/test_override_breach_costs_564.py` |
| 中旨打回反应无皇威 | `tests/test_override_breach_costs_564.py::test_midzhi_rejection_charges_only_parties_and_stigma_then_force_only_authority` |
| 正规打回零代价 + 幂等 | `tests/test_override_breach_costs_564.py::test_ordinary_rejection_has_zero_reaction_and_authority` |
| 毁约当事大臣定义 | `tests/test_override_breach_costs_564.py` |
| 毁约派系 BREACH_FACTION_REACTION | `tests/test_override_breach_costs_564.py` |
| 预先中旨顺颁三笔 | `tests/test_override_breach_costs_564.py` |
| 观感已故跳过 | `tests/test_override_breach_costs_564.py::test_breach_skips_dead_but_records_living_offstage_relations` |
| 强颁读当月最新 Judge 流水 | `tests/test_override_breach_costs_564.py` |
| 玩家面零裸数值 | `tests/test_p4_guard_new_surfaces_547.py` |

## #565 S10 执行格连坐

| AC | 证据指针 |
|---|---|
| 军令状到期必有执行格 | `tests/test_execution_joint_liability_565.py` |
| 中旨强授辞不拜〔闸；e2e 归 #570〕 | 口径 `tests/test_execution_joint_liability_565.py`；e2e `scripts/family_tail_acceptance_570.py` midzhi force |
| 委派链连坐归属 | `tests/test_execution_joint_liability_565.py` |
| 知情档不入连坐读端 | `tests/test_execution_joint_liability_565.py` |
| 已故跳过 / 在世非现任照落 | `tests/test_execution_joint_liability_565.py` |
| 执行格说明合并接口 | `tests/test_execution_joint_liability_565.py` |
| restore 无损 | `tests/test_execution_joint_liability_565.py`；`tests/test_family_tail_restore_570.py` |
| 增补①–⑥ 连坐机械 | `tests/test_execution_joint_liability_565.py`（fulfilled 零行 / 三值正例 / 幂等 / 引擎自判 failed 零行 / 已故 / validate_affected_parties） |

## #566 S11 月度进展/密奏

| AC | 证据指针 |
|---|---|
| 护行三月进展+密奏 | `tests/test_secret_order_monthly_progress_566.py` |
| 月中 restore 进展无损 | `tests/test_secret_order_monthly_progress_566.py`；`tests/test_family_tail_restore_570.py` |
| 短差不强制月报 | `tests/test_secret_order_monthly_progress_566.py` |
| 密奏与垂问同源 | `tests/test_secret_order_monthly_progress_566.py`；`tests/test_dossier_reported_progress_619.py` |
| 异常终态封口 | `tests/test_secret_order_monthly_progress_566.py` |

## #567 S12 在途拨帑对账

| AC | 证据指针 |
|---|---|
| 有护行折损优于无护行〔闸〕 | `tests/test_grant_reconciliation_567.py`（及闸级证据若有） |
| clamp 界内 | `tests/test_grant_reconciliation_567.py` |
| 对账容器分路 + restore | `tests/test_grant_reconciliation_567.py` |
| 机械落点闭环 | `tests/test_grant_reconciliation_567.py` |

## #568 S13 点策

| AC | 证据指针 |
|---|---|
| 试点清丈落案卷绑定对话轮 | `tests/test_strategy_selection_568.py` |
| 未选两策无结构化残留 | `tests/test_strategy_selection_568.py` |
| 裁决类豁免 | `tests/test_strategy_selection_568.py` |

## #569 S14 照账演与认账

| AC | 证据指针 |
|---|---|
| 推演输入含案卷清单+月度进展 | `tests/test_ledger_sim_recon_569.py`（A/payload keys） |
| 对账位缺省容忍 | `tests/test_ledger_sim_recon_569.py` |
| 中旨外廷反应时序〔闸〕 | `tests/test_ledger_sim_recon_569.py` 前置；闸级归本族证据 |
| 召对认账与案卷一致〔闸〕 | brief 机械 `tests/test_ledger_sim_recon_569.py` E；`tests/test_p4_guard_new_surfaces_547.py::test_family_dossier_brief_and_progress_keep_system_words_out` |
| 判决无关章节 diff 零 | `tests/test_ledger_sim_recon_569.py` scope |
| 机械 A–G | `tests/test_ledger_sim_recon_569.py` 各契约测 |

## #570 S15 族尾验收锚

| AC | 证据指针 |
|---|---|
| ① 验收锚全绿（P-3） | `scripts/family_tail_acceptance_570.py` → `docs/evidence/issue-570-acceptance-anchors.json` → `summary.checks`（cabinet / bare_rejected+force_three_costs / midzhi_force_e2e） |
| ② 月中 restore 四面 | `tests/test_family_tail_restore_570.py` |
| ③ 债单+试玩指引 | `docs/474-playtest-guide.md`；issue #570 交付评论 |
| ④ 中旨螺旋〔闸〕 | `scripts/midzhi_spiral_judge_gate_570.py` → `docs/evidence/issue-570-midzhi-spiral.json` → `summary.passed` / `summary.diagnosis`（红则债，不自豁、不造棘轮） |
| ⑤ P4 哨兵 | 确定性：`tests/test_p4_guard_new_surfaces_547.py`（含 `test_family_dossier_brief_and_progress_keep_system_words_out`）；LLM 三面：acceptance 闸 `p4_gazette_clean` / `p4_memorial_clean` / `p4_audience_brief_clean` |
| ⑥ 0055/0056 回注 | `docs/570-adr0055-backref-checklist.md`（8 项）；0056 靶点=空集，对齐 #564 Implementation Decisions |
| ⑦ 全族 DoD | 本文逐票逐 AC；全量 pytest 最终态绿 |

---

## 0056 口径点核（空集靶点）

- 无 0056 文档回注条款；不自造靶点。
- 与 #564 Implementation Decisions 对齐：signed `direction`×`intensity`、三笔、零反应不入清单——由 `tests/test_override_breach_costs_564.py` 锁；族尾闸 `_three_cost_legs` 复验同口径。
