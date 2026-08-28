# issue #1571 案卷 store 迁移边界总账（boundary inventory）

- **用途**：issue #1571（案卷 store 摘取，ADR 0151）大理寺一审打回项——补当前 HEAD 的完整迁移账：案卷表 / GameDB 方法 / 生产调用点 / 测试文件逐项映射到新 owner；`faction_denunciations` 处置；「25 个外部方法」按实测重算并证明归并路径。
- **基线**：分支 `kimi/issue-1571`，HEAD `e88cc29c`。下文所有 `db.py` 行号均指 `ming_sim/db.py` 在该 HEAD 的行号。
- **方法（AST 口径）**：python `ast` 解析 `db.py`（22,392 行，`GameDB` 536 个方法）与 `ming_sim/**` + 根目录生产脚本（`driver.py`/`web_app.py`/`main.py`/`launcher.py`/`spike_settle_tick.py`）+ `tests/**`；方法集以**定义行号区间**圈定（见 §0.1），外部使用以 `ast.Call`/`ast.Attribute` 按方法名匹配计数，命中点已抽核为 `db.` 调用。只给事实与映射，不给新设计。

## 0. 口径与判词/票面数字复核

### 0.1 concern 方法集口径

案卷 concern 方法 = 定义行落在以下区间的 `GameDB` 方法：

- 主块 db.py:11898-17217（`_migrate_legacy_pending_review_secret_orders` → `interrupt_dossiers_for_character`）
- 散点：db.py:18973-18991（读面 2 个）、db.py:19021-19066（`_ensure_directive_dossier`）、db.py:20255-20368（实况轨/效果读面 7 个）、db.py:20385-20564（参与人/knowledge 缝 4 个）
- 区间外 dossier 命名方法 5 个：db.py:3300（`_ensure_decree_dossier_locality_indexes`）、19085、19097、19139、20235

实测 **124 个**（区间内 119 + 区间外 5）。判词口径「约 115」与本文之差：判词未含区间外 5 个；区间内差 4 个疑为参与人/knowledge 缝 4 件（db.py:20385/20421/20465/20564）是否计入的口径差。**本文以 124 为账**，§2.2 逐项列出，无一遗漏。

### 0.2 判词/票面数字 vs 本文实测

| 项 | 票面/判词 | 本文实测 | 差异说明 |
|---|---|---|---|
| concern 方法数 | AST 广口径约 115 | 124（区间 119 + 区间外 5） | 口径差，见 §0.1 |
| 生产外部使用方法名 | 设计稿 25 → 判词 49 | 区间内 49 + 区间外 2 = **51** | 49 与判词一致；另有 `list_fiscal_effects_for_dossier`（db.py:20235）、`read_directive_dossier_payload`（db.py:19097）2 个区间外名被外调。设计稿「25」疑只数了 `db.xxx(` 直调公开方法，未计回调引用、私有外读与区间外名 |
| 裸 SQL 直读案卷表 | 底稿「10 处」（实列 13 行）；ADR「10 处散在 8 个模块」 | **14 处 / 7 个模块** | 底稿漏 `covert_levy.py:200`（直读 `faction_denunciations`，恰为判词点名表）；模块数实为 7 个文件（§3.2） |
| 测试调用面 | 判词 66 文件 / 1,449 函数 / 538 直调 | **69 文件 / 1,511 函数 / 538 直调函数 / 1,386 调用点** | 直调函数数 538 与判词完全一致；文件/函数差主要来自 2 个仅触 knowledge/roster 私有缝的文件（§4） |
| `record_dossier_decision` 测试调用 | ADR「59 次调用全在测试」 | 59 处测试调用点、生产外部 0 | 一致 |
| `transition_decree_dossier` | ADR「生产零调用」 | 跨模块生产调用 0；但 GameDB **密令区内部** 2 处调用（`close_secret_order`@db.py:21462、`mark_secret_order_in_progress`@db.py:21671）+ 12 处测试调用 | 修正票面：非零调用，内化时密令区 2 处一并改道 |

## 1. 表处置总账（13 张表 + 迁移组）

13 张表全部**进入** `DossierStore.ensure_schema(conn)`，**无留外表**。DDL 现址 db.py:1487-1728（连续块）：

| # | 表 | DDL 现址 | 处置 | 理由/备注 |
|---|---|---|---|---|
| 1 | `decree_dossiers` | db.py:1487-1537 | 进 ensure_schema | 案卷主表 |
| 2 | `decree_dossier_links` | db.py:1538-1552 | 进 | 关联槽（0054） |
| 3 | `decree_dossier_reconciliations` | db.py:1553-1570 | 进 | 护送对账子模块表（0058） |
| 4 | `decree_dossier_endorsements` | db.py:1571-1587 | 进 | 背书（0070） |
| 5 | `decree_dossier_link_rejections` | db.py:1588-1599 | 进 | 关联拒收留痕 |
| 6 | `decree_dossier_decisions` | db.py:1600-1621 | 进 | 判决历史 append-only |
| 7 | `dossier_reported_progress` | db.py:1622-1636 | 进 | 奏报轨（0073） |
| 8 | `dossier_supervision_presence` | db.py:1637-1652 | 进 | 监视子模块表（0077） |
| 9 | `dossier_loophole_exposures` | db.py:1653-1664 | 进 | 监视子模块表（0077） |
| 10 | `dossier_actual_progress` | db.py:1665-1682 | 进 | 实况轨（0073/#1504） |
| 11 | `faction_denunciations` | db.py:1683-1701 | **进（第 13 张表，随检举子模块）** | 判词点名处置：`target_dossier_id` 外键直指案卷（`FOREIGN KEY(target_dossier_id) REFERENCES decree_dossiers(id) ON DELETE CASCADE`，db.py:1696），锚定关系使「留外」不成立；ADR 0151 决定 2「dossier_id 锚定的卫星表不留 GameDB 飞地」原承诺与此一致，无需删除任何承诺 |
| 12 | `decree_cost_events` | db.py:1704-1719 | 进 | 连坐毁约代价流水 append-only（0056） |
| 13 | `pending_promulgation_verdicts` | db.py:1720-1728 | 进 | 待颁布判决两态持久化（ADR 0151 决定 7） |

块内附带的 `CREATE INDEX`（如 db.py:1698-1701、1718-1719）随各表随迁。

**迁移/回填 5 组（6 个方法）归属 ensure_schema 迁移组**，现全部由 `GameDB.init_schema`（db.py:876）调用，迁后 init_schema 改调 `ensure_schema` 成为编排点（ADR 0151 决定 8）：

| 方法 | 现址 | 现调用方 |
|---|---|---|
| `_migrate_legacy_pending_review_secret_orders` | db.py:11898-11969 | init_schema@876 |
| `_migrate_legacy_secret_order_dossiers` | db.py:11971-12035 | init_schema@876 |
| `_migrate_legacy_reaction_severity` | db.py:16038-16067 | init_schema@876 |
| `_migrate_reaction_value`（上者私有 helper，随迁） | db.py:16018-16036 | `_migrate_legacy_reaction_severity` 内部 |
| `_backfill_proposed_appointment_break_ranks` | db.py:14030-14051 | init_schema@876 |
| `_ensure_decree_dossier_locality_indexes` | db.py:3300-3311 | init_schema@876 |

## 2. 方法逐项投影表

### 2.1 全包公开面总账（实数 32 个公开入口，窄 interface 取向）

窄 interface 取向不变，但**不设数目封顶**（owner 只批了「~15」量级取向，未授权硬上限）；公开面实数与逐项职责如下表。**全包一张表**：store 本体入口 21 个 + supervision 子模块 7 个 + reconciliation 子模块 4 个 = **32 个公开入口**——子模块入口如实计入，不再有「子模块不计入」的豁免口径。**形态辨正（十二审修订）**：32 项并非同一形态——store 21 项是 `DossierStore` **实例方法**（真实调用形态 `store.x()`），supervision/reconciliation 11 项是**子模块函数**（真实调用形态 `supervision.x()`/`reconciliation.x()`，子模块为包内独立子模块自身入口，ADR 0151 决定 2）；实例方法不能冒写成模块级导出，逐项形态以下表三列为准。**包单一出口的准确表述**：包 `__init__` 只导出 `DossierStore` 类、`supervision` 与 `reconciliation` 两个子模块、包级 `ensure_schema(conn)`、公开常量（§2.3 公开化者，调用形态 = 包属性，不占 32 额度），此外零导出；32 项业务入口经类实例与子模块命名空间到达、不由 `__init__` 逐项平铺 re-export——外部 consumer 只 import `ming_sim/entities/dossier` 包一处，唯一 seam 承诺不变。`ensure_schema(conn)` 为包级 schema 函数，不占业务方法额度。四审修订：supervision 7 组成换一件——`trigger_supervision_countermeasures` 实读（db.py:13375-13452）确认夹带 issue 查重/创建/state 透传/自主 commit 点，按毁约/连坐同口径**拆分剔出公开面**（纯读半析出新公开纯读件 `list_supervision_countermeasure_candidates` 补位 #25），`accept_faction_denunciations` 改造保留公开（state→`turn:int` 纯标量、clamp 夹带段侧预解析、零 commit，逐项见 §2.2）——实数 32 不变。

**导出纪律（四审明文、十二审按真实形态改写）**：包 `__init__` 导出清单 = `DossierStore` 类 + `supervision`/`reconciliation` 子模块 + 包级 `ensure_schema(conn)` + 公开常量，此外零导出——32 项业务入口不逐项平铺 re-export（实例方法无法也不应冒写成模块级导出，子模块函数经子模块命名空间到达即为出口）；段适配器/编排层函数（含各拆分件的编排半——如 `trigger_supervision_countermeasures` 的 integrity 过滤/issue 创建半、段侧效果消费助手 `apply_breach_effects`/`apply_joint_liability_effects`/`apply_override_effects`）一律不得从 `ming_sim/entities/dossier/__init__` 导出冒充 store seam。

32 个公开入口逐项真实出口表（「导出径」= 包 `__init__` 导出 `DossierStore` 类/子模块后入口经其命名空间到达，不逐项平铺 re-export；调用方矩阵见 §3.1）：

| # | 公开入口 | 定义位置 | 调用形态 | `__init__` 导出径 | 职责 | 生产调用方（现入口，改径后来源） |
|---|---|---|---|---|---|---|
| 1 | `create` | `DossierStore` 实例方法 | `store.create(...)` | 随类导出 | 成案建档：批量 Plan→Validate-all→Write-once，单卷为变体 | rescript_actions.py:947；GameDB 内部 `_apply_pending_action`@db.py:18116、`create_secret_order`@db.py:21149 改道 |
| 2 | `attach_participants` | `DossierStore` 实例方法 | `store.attach_participants(...)` | 随类导出 | 参与人 roster 追加（`decree_dossiers.participant_roster` 族），含 roster 校验 | issues.py:7439；GameDB 内部 `_apply_pending_action`@db.py:18116 改道 |
| 3 | `attach_links` | `DossierStore` 实例方法 | `store.attach_links(...)` | 随类导出 | 关联槽追加 + 整批拒收留痕（`decree_dossier_links` / `decree_dossier_link_rejections` 族） | 生产无外部直达（仅测试/块内自用，见 pr-slices §4.6）；GameDB `commit_pending_actions`@db.py:17821、`_apply_pending_action`@db.py:18116 改道 |
| 4 | `attach_endorsements` | `DossierStore` 实例方法 | `store.attach_endorsements(...)` | 随类导出 | 背书追加（`decree_dossier_endorsements` 族），含背书校验 | GameDB `settle_endorsement_batch`@db.py:9826 改道 |
| 5 | `record_verdict` | `DossierStore` 实例方法 | `store.record_verdict(...)` | 随类导出 | 颁布写端深入口：校验→拒收归因→持久化→verdict 合并→状态转移+否决网快照（ADR 0151 决定 4） | decree.py:2534（`apply_dossier_promulgation`）、decree.py:2525（`apply_dossier_verdicts`） |
| 6 | `record_execution` | `DossierStore` 实例方法 | `store.record_execution(...)` | 随类导出 | 执行格记账：outcome 闭集校验、说明合并、联动关闭 | issues.py:8195、breach_plea.py:853/877、due_review.py:533；GameDB `close_secret_order`@db.py:21462 改道 |
| 7 | `record_progress` | `DossierStore` 实例方法 | `store.record_progress(...)` | 随类导出 | 进展追加：reported 奏报轨 / actual 实况轨双轨 + 月度批量 | issues.py:8209、breach_plea.py:858、due_review.py:542/550、decree.py:2720、covert_progress.py:521 |
| 8 | `close` | `DossierStore` 实例方法 | `store.close(...)` | 随类导出 | 关闭 / 按人物中断在飞案卷 | 生产无直达：经 `record_execution(close=True)` 与 GameDB `set_character_status`@db.py:5638（→`interrupt_dossiers_for_character`）到达；公开供编排/段适配器直调 |
| 9 | `record_override_judgment` | `DossierStore` 实例方法 | `store.record_override_judgment(...)` | 随类导出 | 强颁/中旨代价**纯判定写**：authority/parties cost_event 幂等写，返 frozen `OverrideEffects` 效果意图（实写才含项，撞键为 None 项）；不碰 state.metrics/factions/classes | GameDB `apply_dossier_promulgation`@db.py:15707-15711、`apply_dossier_verdicts`@db.py:17166-17172 内联点改道；效果半由段侧 `apply_override_effects` 消费（形状真源 = breach-liability-split §2） |
| 10 | `record_breach_judgment` | `DossierStore` 实例方法 | `store.record_breach_judgment(...)` | 随类导出 | 毁约**纯判定写**：资格读→门闩行→归属计算→satisfaction cost_event→案卷关闭，返 frozen `BreachEffects`（None=幂等拒/状态不合格）；不写关系边、不调 adjust_factions | breach_plea.py:738、issues.py:6032；效果半由段侧 `apply_breach_effects` 消费 |
| 11 | `record_joint_liability` | `DossierStore` 实例方法 | `store.record_joint_liability(...)` | 随类导出 | 连坐**纯判定写**：触发集过滤→门闩行→projection 读→satisfaction cost_event→execution_note 合并，返 frozen `JointLiabilityEffects`（None=非触发/撞键） | due_review.py:555、issues.py:8217；效果半由段侧 `apply_joint_liability_effects` 消费 |
| 12 | `validate_joint_liability_affected_parties` | `DossierStore` 实例方法 | `store.validate_joint_liability_affected_parties(...)` | 随类导出 | 连坐受影响方校验（纯参数 + factions/classes 名集 DB 读；breach-liability-split §2.1 定为公开） | issues.py:8194 |
| 13 | `list_execution_liability_parties` | `DossierStore` 实例方法 | `store.list_execution_liability_parties(...)` | 随类导出 | 连坐责任方名单读面（经 `participant_roster.project_execution_liability_parties` 纯函数投影） | 现码由 `apply_execution_joint_liability`@db.py:16365 内部调用；拆后供 store 判定写与段侧消费共用 |
| 14 | `list_backlash_terminal_dossiers` | `DossierStore` 实例方法 | `store.list_backlash_terminal_dossiers(...)` | 随类导出 | backlash 纯读组合：终值扫描（db.py:13916-13926）+ commitments 读；**仅限 13 表内读**——`dossier_has_beyond_intent` 实读 economy/fiscal 表（db.py:20346-20354 → 20255-20262），留 GameDB，beyond_intent 过滤由编排层组合 | decree.py:2334 所在结算段编排改道（breach-liability-split §2.1 同口径） |
| 15 | `get` | `DossierStore` 实例方法 | `store.get(...)` | 随类导出 | 单卷读取：by id / directive / secret_order + 授权判定派生 | 14 个模块（`get_decree_dossier` 一族，矩阵见 §3.1） |
| 16 | `list_dossiers` | `DossierStore` 实例方法 | `store.list_dossiers(...)` | 随类导出 | 列表读取五面：status 过滤 / simulation 面 / referenceable 面 / executable ids / 拨饷 provenance | decree.py:1051/1060/1124/1249/1256、simulation.py:1253/1266、driver.py:218、session.py、tools.py:628、web_app.py:2644 等 |
| 17 | `list_progress` | `DossierStore` 实例方法 | `store.list_progress(...)` | 随类导出 | 进展读取：奏报列表 / fork 态 / 月度 nudge / 实况轨与单位和 | issues.py:8205/9345、breach_plea.py:546、due_review.py:187/540、covert_progress.py:282/594/608、covert_levy.py:181、simulation.py:544/1346、decree.py:1059 |
| 18 | `list_links` | `DossierStore` 实例方法 | `store.list_links(...)` | 随类导出 | 关联槽 / 拒收 / 承诺 origin 读面 | decree.py:902、issues.py:5588 |
| 19 | `list_endorsements` | `DossierStore` 实例方法 | `store.list_endorsements(...)` | 随类导出 | 背书记录读面 | decree.py:323 |
| 20 | `list_decisions` | `DossierStore` 实例方法 | `store.list_decisions(...)` | 随类导出 | 判决历史读面（append-only） | decree.py:886 |
| 21 | `pending_verdicts` | `DossierStore` 实例方法 | `store.pending_verdicts(...)` | 随类导出 | 待颁布判决两态持久化对（save+get；全 store 唯一自主 commit 例外，ADR 0151 决定 7） | decree.py:1171（save）、decree.py:1148（get） |
| 22 | `record_monthly_supervision_presence` | `supervision` 子模块函数 | `supervision.record_monthly_supervision_presence(...)` | 随子模块导出 | 月度监视在场记录 | decree.py:2719 |
| 23 | `record_monthly_loophole_exposures_from_reconciliations` | `supervision` 子模块函数 | `supervision.record_monthly_loophole_exposures_from_reconciliations(...)` | 随子模块导出 | 对账衍生漏洞暴露记录 | decree.py:2732 |
| 24 | `build_supervision_judge_surface` | `supervision` 子模块函数 | `supervision.build_supervision_judge_surface(...)` | 随子模块导出 | 判官 surface 供数 | decree.py:952、due_review.py:194、simulation.py:1335 |
| 25 | `list_supervision_countermeasure_candidates` | `supervision` 子模块函数 | `supervision.list_supervision_countermeasure_candidates(...)` | 随子模块导出 | 监视反制候选**纯读**（自 `trigger_supervision_countermeasures` 纯读半析出）：presence 全库聚合 + 连续月判定（`derive_consecutive_months`≥12），仅限 13 表内 `dossier_supervision_presence` 读、纯参数、零 commit；返候选行（auditor/dossier_id/连续月数） | decree.py:2322 所在结算段编排改道——integrity 过滤（`character_faction_integrity`，GameDB-other）/issue 查重（`find_any_issue_by_origin`）/创建（`insert_issue`）/commit 留编排层消费候选行（同 #14 `list_backlash_terminal_dossiers` 口径） |
| 26 | `list_faction_denunciations` | `supervision` 子模块函数 | `supervision.list_faction_denunciations(...)` | 随子模块导出 | 检举读端 | covert_levy.py:200 裸 SQL 改道（§3.2 #12） |
| 27 | `build_faction_denunciation_facts` | `supervision` 子模块函数 | `supervision.build_faction_denunciation_facts(...)` | 随子模块导出 | 检举供事实 | issues.py:2556、simulation.py:859 |
| 28 | `accept_faction_denunciations` | `supervision` 子模块函数 | `supervision.accept_faction_denunciations(...)` | 随子模块导出 | 检举承接落库（**改造保留公开**：state→`turn:int` 纯标量；characters clamp 与派系读段侧预解析注入；commit 移除、段侧统一提交；实写仅 `faction_denunciations`，13 表内） | decree.py:2724 |
| 29 | `list_dossier_reconciliations` | `reconciliation` 子模块函数 | `reconciliation.list_dossier_reconciliations(...)` | 随子模块导出 | 对账记录读面 | issues.py:7857/7948 |
| 30 | `list_open_grant_reconciliations` | `reconciliation` 子模块函数 | `reconciliation.list_open_grant_reconciliations(...)` | 随子模块导出 | 未结对账读面 | simulation.py:1362 |
| 31 | `record_monthly_grant_reconciliations` | `reconciliation` 子模块函数 | `reconciliation.record_monthly_grant_reconciliations(...)` | 随子模块导出 | 月度对账写 | decree.py:2728 |
| 32 | `merge_grant_reconciliation_into_execution_note` | `reconciliation` 子模块函数 | `reconciliation.merge_grant_reconciliation_into_execution_note(...)` | 随子模块导出 | 对账结果并入 execution_note（经 store record_execution 私有子口） | issues.py:8199 |

**包内私有实现件清单（8 个，三审降私有）**：以下方法全仓 grep 实核**生产外部零调用**（`ming_sim/**` 除 db.py + 根目录生产脚本无命中），包内调用方均为子模块/store 内部件（AST 实核），属实现件而非 seam——测试直调不构成公开理由，一律不经 `__init__` 出口（不随类/子模块/公开常量导出），测试随片改道包内：

| 私有件 | 包内调用方（db.py 实核） | 备注 |
|---|---|---|
| `dossier_has_supervision_presence` | `record_monthly_loophole_exposures_from_reconciliations`@13106、`record_dossier_execution`@15580 | supervision 私有 |
| `record_monthly_supervision_facts` | 无（生产内外皆零调用，仅 tests/test_supervision_625.py 直调） | supervision 私有 |
| `record_loophole_exposure` | 同上 13106、15580 | supervision 私有 |
| `list_supervision_presence` | `list_supervision_history`@13270 | supervision 私有 |
| `list_loophole_exposures` | `build_supervision_judge_surface`@13325 | supervision 私有 |
| `list_supervision_history` | `build_supervision_judge_surface`@13325、`compose_supervision_report_origin`@13347 | supervision 私有 |
| `compose_supervision_report_origin` | `record_monthly_dossier_progress`@12781 | supervision 私有 |
| `list_monthly_grant_reconciliation_targets` | `list_open_grant_reconciliations`@12909、`record_monthly_grant_reconciliations`@12932 | reconciliation 私有 |

**不造 catch-all 的论证**（判词要求逐项成立论证，论证不住即拆，不为凑数合并）：

- 每个公开方法 = 单一生命周期事件（create/record_verdict/record_execution/record_progress/close/record_*_judgment 三连）或单一从属记录族读面；通用写口（`_commit_dossier_write` db.py:12422、代价流水 `_record_decree_cost` db.py:16069）全部留在 store 私有，不进公开面。
- `attach`（参与人/关联槽/背书三族合并）**论证不住，拆**：三族是不同从属记录族（roster 列 / links+rejections 表 / endorsements 表），生产时机亦不同（参与人 issues.py:7439 补录、关联槽成案/颁布期、背书 `settle_endorsement_batch`@db.py:9826 批次），只剩「追加」动作抽象相同——按判词「单一从属记录族」标准不成立，拆为 `attach_participants`/`attach_links`/`attach_endorsements` 三个实名入口（#2/#3/#4）。共用校验私有件（`_validate_dossier_endorsement` db.py:14880、`_normalize_participant_roster` db.py:20385、`_validate_participant_roster_references` db.py:20421）留 store 私有共享，不构成合并理由。
- `get` **论证成立，不拆**：四个读法（by id db.py:15000 / by directive 15038、15049 / by secret_order 15060 / 授权判定派生 15558）都是**同一从属记录族——案卷主表 `decree_dossiers` 行**的读取，lookup key 变体与派生判定（`dossier_authorizes_effects` 只读该行 payload）不改记录族；生命周期同为「单卷读取」。
- `pending_verdicts` **论证成立，不拆**：save+get 是同一从属记录族（`pending_promulgation_verdicts` 表，13 表之 13）的两态生命周期对（颁布前保存 / 结算领取消费），且为 ADR 0151 决定 7 全 store 唯一自主 commit 例外——两态必须同事务纪律成对存在，拆开反而破坏例外语义。
- `record_progress` 双轨 = ADR 0073 明文双口径（奏报/实况）同一生命周期事件的两条物理轨，不是杂物筐；两条轨各有独立私有写件（`_record_secret_dossier_progress` db.py:12526、`_record_general_dossier_progress` db.py:12568、实况轨 db.py:20264）。
- 毁约/连坐旧混合动词 `breach`/`apply_joint_liability` **消亡**：现码同时写 13 表内（案卷行、cost_events）与表外（metrics、factions、relation_edge_events），「既是 store 深入口又是段消费」双重身份矛盾；按 breach-liability-split §2 拆为 store 纯判定写（#9/#10/#11，纯参数、返 frozen dataclass 效果意图、None=幂等拒）+ 段侧效果消费助手（`apply_breach_effects`/`apply_joint_liability_effects`/`apply_override_effects`），旧名整体消亡不留转发（ADR 0151 决定 6）。

归并账（124 方法，与 §0.1 账平；公开面实数 32 = store 21 + supervision 7 + reconciliation 4——supervision 7 = 原 6 件 + `trigger_supervision_countermeasures` 纯读半析出新件补位，四审；另 8 个零外部调用实现件降包内私有、不经 `__init__` 出口）：

- 40 个现有公开命名方法 → store 公开 **19 个入口**（上表 #1-8、#10-13、#15-21）；
- 段适配器组 2 件析出 store 公开入口：`_apply_override_costs`+`_apply_authority_cost` 判定半 → `record_override_judgment`（#9）、`trigger_commitment_backlashes` 纯读半 → `list_backlash_terminal_dossiers`（#14）——store 公开合计 **21**；
- 29 个 → store 私有（原 25 + 颁赏纯件 4 个自段适配器改归，实读理由见 §2.2 各行）；
- 13 个 → supervision 子模块（6 公开 #22-24/#26-28 + 7 私有实现件；`trigger_supervision_countermeasures` 拆分移段适配器组，其纯读半析出 supervision 公开第 7 入口 `list_supervision_countermeasure_candidates`（#25）——析出新入口不占 124 方法额度）；6 个 → reconciliation 子模块（4 公开 #29-32 + 2 私有：`list_monthly_grant_reconciliation_targets`、`_grant_escort_presence`）；
- 20 个 → 段适配器（原 23 − 颁赏纯件 4 + `trigger_supervision_countermeasures` 自 supervision 拆入；含 `_apply_override_costs`/`_apply_authority_cost` 效果半、`trigger_commitment_backlashes` 与 `trigger_supervision_countermeasures` 编排半——拆分件方法体只计一次，标注双去向）；
- 10 个 → 留 GameDB；6 个 → ensure_schema 迁移组。

合计 40+29+13+6+20+10+6 = 124。**无整方法删除**——`transition_decree_dossier`/`record_dossier_decision` 按 ADR 0151 决定 5 内化为 `record_verdict` 私有子步骤而非删除。

### 2.2 逐项投影表（124 行，AST 区间口径全量）

| 方法 | db.py 现址 | 新 owner | 备注 |
|---|---|---|---|
| `_ensure_decree_dossier_locality_indexes` | db.py:3300-3311 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_migrate_legacy_pending_review_secret_orders` | db.py:11898-11969 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_migrate_legacy_secret_order_dossiers` | db.py:11971-12035 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_dossier_has_execution_surface` | db.py:12052-12057 | store 私有 |  |
| `_directive_dossier_action_type` | db.py:12060-12066 | store 私有 |  |
| `_directive_executor` | db.py:12069-12080 | store 私有 |  |
| `_normalize_directive_dossier_payload` | db.py:12082-12392 | store 私有 | 夹带点：收 content；GameDB 17497/17768/18116 与 rescript_actions.py:933 跨域共用，施工点名 |
| `_find_pacification_target` | db.py:12394-12420 | 段适配器 | content 检索 helper；rescript_actions.py:896、session.py:2478 |
| `_commit_dossier_write` | db.py:12422-12426 | store 私有 |  |
| `_normalize_dossier_mode` | db.py:12431-12435 | store 私有 |  |
| `_dossier_row` | db.py:12438-12484 | store 私有 |  |
| `_normalize_dossier_report_origin` | db.py:12492-12505 | store 私有 |  |
| `_coerce_dossier_progress_row` | db.py:12508-12524 | store 私有 |  |
| `_record_secret_dossier_progress` | db.py:12526-12566 | store 私有 |  |
| `_record_general_dossier_progress` | db.py:12568-12614 | store 私有 |  |
| `record_dossier_progress` | db.py:12616-12661 | store 公开:record_progress | 双轨（奏报/实况）+月度批量 |
| `list_dossier_progress` | db.py:12663-12692 | store 公开:list_progress |  |
| `_audit_fork_signals_for_source` | db.py:12694-12716 | store 私有 |  |
| `read_dossier_fork_state` | db.py:12718-12749 | store 公开:list_progress |  |
| `list_monthly_dossier_progress_nudges` | db.py:12751-12779 | store 公开:list_progress |  |
| `record_monthly_dossier_progress` | db.py:12781-12824 | store 公开:record_progress | 双轨（奏报/实况）+月度批量 |
| `_grant_escort_presence` | db.py:12826-12834 | 子模块 reconciliation |  |
| `list_monthly_grant_reconciliation_targets` | db.py:12836-12877 | 子模块 reconciliation（私有） | 零生产外部调用（grep 实核），包内被 12909/12932 用，见 §2.1 私有清单 |
| `list_dossier_reconciliations` | db.py:12879-12907 | 子模块 reconciliation |  |
| `list_open_grant_reconciliations` | db.py:12909-12930 | 子模块 reconciliation |  |
| `record_monthly_grant_reconciliations` | db.py:12932-13026 | 子模块 reconciliation |  |
| `dossier_has_supervision_presence` | db.py:13030-13041 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 13106/15580 用，见 §2.1 私有清单 |
| `record_monthly_supervision_presence` | db.py:13043-13104 | 子模块 supervision |  |
| `record_monthly_loophole_exposures_from_reconciliations` | db.py:13106-13140 | 子模块 supervision |  |
| `record_monthly_supervision_facts` | db.py:13142-13159 | 子模块 supervision（私有） | 生产内外零调用（仅测试直调），见 §2.1 私有清单 |
| `record_loophole_exposure` | db.py:13161-13196 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 13106/15580 用，见 §2.1 私有清单 |
| `list_supervision_presence` | db.py:13198-13234 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 13270 用，见 §2.1 私有清单 |
| `list_loophole_exposures` | db.py:13236-13268 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 13325 用，见 §2.1 私有清单 |
| `list_supervision_history` | db.py:13270-13323 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 13325/13347 用，见 §2.1 私有清单 |
| `build_supervision_judge_surface` | db.py:13325-13345 | 子模块 supervision |  |
| `compose_supervision_report_origin` | db.py:13347-13373 | 子模块 supervision（私有） | 零生产外部调用（grep 实核），包内被 12781 用，见 §2.1 私有清单 |
| `trigger_supervision_countermeasures` | db.py:13375-13452 | **拆分**：supervision 纯读件 + 编排层 | 四审实读：读 `dossier_supervision_presence`（13394-13401 裸 SELECT，13 表内）聚合+连续月判定（13409-13411）→ supervision 公开纯读件 `list_supervision_countermeasure_candidates`（§2.1 #25，纯参数零 commit，返 auditor/dossier_id/连续月数候选行）；`character_faction_integrity`@13412（经 handle 读 characters/factions=GameDB-other）/issue 查重 `find_any_issue_by_origin`@13416/创建 `insert_issue`@13425/state 透传（仅 13426 递 insert_issue）/commit@13450-13451 → 编排层（decree.py:2322 现传 commit=False，结算段事务内逐候选消费）；`derive_consecutive_months`/`COUNTERMEASURE_PRESENCE_MONTHS` 纯件随片收编 |
| `list_faction_denunciations` | db.py:13454-13501 | 子模块 supervision | 检举读端 |
| `build_faction_denunciation_facts` | db.py:13503-13680 | 子模块 supervision | 检举供事实；夹带点：跨表读（派系/处境）；issues.py:2556、simulation.py:859 |
| `accept_faction_denunciations` | db.py:13682-13836 | 子模块 supervision | 检举承接落库，**改造保留公开**（四审实读）：state 仅 13709 取 `state.turn` → 收窄 `turn:int` 纯标量；clamp 夹带 characters@13734-13737（检举人在场/faction）与 `character_faction_integrity`@13752（被检举人派系，GameDB-other）→ 段侧预解析注入纯参数；commit@13834-13835 移除归段侧（decree.py:2724 现传 commit=False）；实写仅 `faction_denunciations` INSERT@13799-13818（13 表内），读 `get_decree_dossier`@13743/`read_dossier_fork_state`@13754/去重 SELECT@13760-13768 皆 13 表内 |
| `trigger_commitment_backlashes` | db.py:13838-14014 | **拆分**：store list_backlash_terminal_dossiers + 编排层 | 纯读半（终值扫描 13916-13926 + `list_commitments_for_dossier` 13938）→ store 公开 `list_backlash_terminal_dossiers`；`dossier_has_beyond_intent`@13936 实读 economy/fiscal 表（留 GameDB），beyond_intent 过滤由编排层组合（breach-liability-split §2.1 同口径）；issue 创建/metrics 半（13973-14002 经 insert_issue/advance_issue/`_apply_metric_dict`）→ 编排层；decree.py:2334 |
| `merge_grant_reconciliation_into_execution_note` | db.py:14016-14028 | 子模块 reconciliation | 写 note 经 store record_execution 私有子口；issues.py:8199 |
| `_backfill_proposed_appointment_break_ranks` | db.py:14030-14051 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_grant_allocation_is_monthly` | db.py:14054-14055 | store 私有 | 纯 @staticmethod 载荷判别（零 DB/state，实读 db.py:14054-14055）；被包内 reconciliation（12856）、成案（14829）、provenance 读面共用——归段会造包→段反向调用，故自「段适配器」改归（修正一审口径，db.py 实读为准） |
| `_grant_allocation_is_honorific` | db.py:14058-14059 | store 私有 | 同上：纯 @staticmethod（14058-14059）；包内 reconciliation（12858）、成案/颁布格共用 |
| `_is_army_pay_grant_payload` | db.py:14062-14067 | store 私有 | 同上：纯 @staticmethod（14062-14067）；store 公开读面 `list_closed_army_pay_dossiers_for_provenance`@15334、成案 14623/14834 内部依赖 |
| `_normalize_army_pay_grant_payload` | db.py:14069-14112 | store 私有 | 纯 payload→payload（体内仅调上述三纯件，零 conn/state，实读 14069-14112）；包内 `_normalize_directive_dossier_payload`@12119、成案 14623 共用 |
| `_apply_army_pay_grant_effect` | db.py:14114-14161 | 段适配器 | grant 载荷判别+颁布物化 |
| `_create_grant_fiscal_item` | db.py:14163-14190 | 段适配器 | grant 载荷判别+颁布物化 |
| `_apply_grant_honorific_effect` | db.py:14192-14207 | 段适配器 | grant 载荷判别+颁布物化 |
| `create_decree_dossier` | db.py:14209-14259 | store 公开:create | 单卷形收为 create 变体；GameDB create_secret_order@21149 |
| `create_decree_dossiers` | db.py:14261-14549 | store 公开:create | 批量 ABI 为正形；rescript_actions.py:947、GameDB _apply_pending_action@18116 |
| `_create_decree_dossier_row` | db.py:14551-14865 | store 私有 |  |
| `_validate_dossier_delegations` | db.py:14868-14878 | store 私有 |  |
| `_validate_dossier_endorsement` | db.py:14880-14909 | store 私有 | attach/create 校验；跨域共用点名（settle_endorsement_batch@9826、insert_issue@19740、cli_backend.py:1907/1924） |
| `add_dossier_endorsement` | db.py:14911-14932 | store 公开:attach_endorsements | 背书族追加（attach 拆三之一，§2.1） |
| `list_dossier_endorsements` | db.py:14934-14945 | store 公开:list_endorsements | decree.py:323 |
| `append_decree_dossier_participants` | db.py:14947-14998 | store 公开:attach_participants | 参与人 roster 族追加（attach 拆三之一，§2.1） |
| `get_decree_dossier` | db.py:15000-15004 | store 公开:get |  |
| `_append_midzhi_stigma` | db.py:15006-15036 | store 私有 | record_verdict 私有子步骤 |
| `get_dossier_for_directive` | db.py:15038-15047 | store 公开:get |  |
| `list_dossiers_for_directive` | db.py:15049-15058 | store 公开:get |  |
| `get_dossier_for_secret_order` | db.py:15060-15065 | store 公开:get |  |
| `list_referenceable_dossiers` | db.py:15067-15117 | store 公开:list_dossiers |  |
| `_record_dossier_link_rejection` | db.py:15119-15128 | store 私有 | record_verdict 私有子步骤 |
| `add_dossier_links` | db.py:15130-15181 | store 公开:attach_links | 关联槽族追加 + 拒收留痕（attach 拆三之一，§2.1） |
| `list_dossier_links` | db.py:15183-15194 | store 公开:list_links | resolve_commitment_origin_ref 夹带点 state（issues.py:5588） |
| `list_dossier_link_rejections` | db.py:15196-15210 | store 公开:list_links | resolve_commitment_origin_ref 夹带点 state（issues.py:5588） |
| `list_commitments_for_dossier` | db.py:15212-15218 | store 公开:list_links | resolve_commitment_origin_ref 夹带点 state（issues.py:5588） |
| `resolve_commitment_origin_ref` | db.py:15220-15251 | store 公开:list_links | resolve_commitment_origin_ref 夹带点 state（issues.py:5588） |
| `list_decree_dossiers` | db.py:15253-15274 | store 公开:list_dossiers |  |
| `list_decree_dossier_decisions` | db.py:15276-15303 | store 公开:list_decisions | decree.py:886 |
| `list_closed_army_pay_dossiers_for_provenance` | db.py:15305-15343 | store 公开:list_dossiers | 拨饷 provenance 面；实读备注：体内补饷流水过滤（15337-15340 经 `list_economy_moves_for_dossier` 读 `economy_ledger`，非 13 表）随「effects 读面留 GameDB」上提调用方组合，store 面只出 closed grant_allocation 案卷集 + `_is_army_pay_grant_payload`（纯件）过滤 |
| `list_decree_dossiers_for_simulation` | db.py:15345-15403 | store 公开:list_dossiers |  |
| `executable_decree_dossier_ids` | db.py:15406-15413 | store 公开:list_dossiers |  |
| `transition_decree_dossier` | db.py:15415-15441 | store 私有 | record_verdict 私有子步骤 |
| `record_dossier_decision` | db.py:15443-15534 | store 私有 | record_verdict 私有子步骤 |
| `close_decree_dossier` | db.py:15536-15556 | store 公开:close | 生产经 record_execution(close=True)/set_character_status@5638 到达 |
| `dossier_authorizes_effects` | db.py:15558-15578 | store 公开:get |  |
| `record_dossier_execution` | db.py:15580-15631 | store 公开:record_execution | breach_plea.py:853/877、due_review.py:533、issues.py:8195、GameDB close_secret_order@21462 |
| `apply_dossier_promulgation` | db.py:15633-16002 | store 公开:record_verdict | decree.py:2534/2525；物化子调用上浮段适配器 |
| `_migrate_reaction_value` | db.py:16018-16036 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_migrate_legacy_reaction_severity` | db.py:16038-16067 | ensure_schema 迁移组 | 原调用方 GameDB.init_schema@876 |
| `_record_decree_cost` | db.py:16069-16080 | store 私有 | 代价流水写口/连坐读证 |
| `_current_judge_affected_parties` | db.py:16082-16105 | store 私有 | 代价流水写口/连坐读证 |
| `_apply_authority_cost` | db.py:16107-16123 | **拆分**：store record_override_judgment + 段 | 判定半（authority cost_event 幂等写 16111-16115）→ store 公开 `record_override_judgment`；效果半（state.metrics clamp 16116-16118 + metrics 表 upsert 16119-16123）→ 段 `apply_override_effects`（形状真源 breach-liability-split §2） |
| `_apply_override_costs` | db.py:16125-16162 | **拆分**：store record_override_judgment + 段 | 判定半（parties 批级闸 16134-16139、逐 party 校验+satisfaction cost_event 16141-16152）→ `record_override_judgment`；效果半（adjust_factions 16154-16156 / adjust_classes 16158-16160）→ 段 |
| `breach_decree_dossier` | db.py:16164-16246 | **拆分**：store record_breach_judgment + 段 | 判定半（资格读 16175-16182、门闩 16183-16187、归属计算 16191-16223、satisfaction cost_event 16229-16232、案卷关闭 16236-16245）→ store 公开 `record_breach_judgment`；效果半（metrics、record_relation_edge_event 16214-16218、adjust_factions 16233-16235）→ 段 `apply_breach_effects`；breach_plea.py:738、issues.py:6032 |
| `list_execution_liability_parties` | db.py:16248-16255 | store 公开:list_execution_liability_parties | 连坐名单读面（breach-liability-split §2.1 定为公开）；现由 `apply_execution_joint_liability`@16365 内部调用 |
| `merge_execution_note` | db.py:16257-16287 | store 私有 | record_execution 子口；包内 reconciliation 经此写 |
| `validate_joint_liability_affected_parties` | db.py:16289-16317 | store 公开:validate_joint_liability_affected_parties | 连坐受影响方校验（公开）；issues.py:8194 |
| `apply_execution_joint_liability` | db.py:16319-16411 | **拆分**：store record_joint_liability + 段 | 判定半（触发集过滤 16334-16335、门闩 16353-16357、projection/characters 读 16359-16383、satisfaction cost_event 16396-16399、execution_note 合并 16404-16410）→ store 公开 `record_joint_liability`；效果半（record_relation_edge_event 16389-16393、adjust_factions 16400-16402）→ 段 `apply_joint_liability_effects`；due_review.py:555、issues.py:8217 |
| `save_pending_promulgation_verdicts` | db.py:16413-16427 | store 公开:pending_verdicts | decree.py:1171/1148；唯一自主 commit 例外（ADR 决定7） |
| `get_pending_promulgation_verdicts` | db.py:16429-16448 | store 公开:pending_verdicts | decree.py:1171/1148；唯一自主 commit 例外（ADR 决定7） |
| `_apply_military_order_station_effect` | db.py:16450-16497 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_military_order_office_effect` | db.py:16499-16553 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_authorization_verdict_effect` | db.py:16555-16602 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_revoke_authority_verdict_effect` | db.py:16604-16638 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_revoke_decree_verdict_effect` | db.py:16640-16738 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_military_order_verdict_effect` | db.py:16740-16783 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_referral_verdict_effect` | db.py:16786-16874 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_assignment_verdict_effect` | db.py:16876-16969 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_punishment_verdict_effect` | db.py:16971-17072 | 段适配器 | verdict 效果物化（0150 决定5） |
| `_apply_pay_order_override_effect` | db.py:17074-17093 | 段适配器 | verdict 效果物化（0150 决定5） |
| `apply_dossier_verdicts` | db.py:17097-17177 | store 公开:record_verdict | decree.py:2534/2525；物化子调用上浮段适配器 |
| `interrupt_dossiers_for_character` | db.py:17179-17216 | store 公开:close | 生产经 record_execution(close=True)/set_character_status@5638 到达 |
| `list_office_effects_for_dossier` | db.py:18973-18981 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `list_skill_grants_for_dossier` | db.py:18983-18991 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `_ensure_directive_dossier` | db.py:19021-19066 | store 私有 |  |
| `_decode_directive_dossier_payload` | db.py:19085-19095 | 留 GameDB | turn_directives 读缝（directive concern）；action_materialize.py:477、cli/terminal.py:882、web_app.py:5014 |
| `read_directive_dossier_payload` | db.py:19097-19101 | 留 GameDB | turn_directives 读缝（directive concern）；action_materialize.py:477、cli/terminal.py:882、web_app.py:5014 |
| `ensure_dossiers_for_draft_directives` | db.py:19139-19183 | 段适配器 | 旨稿边界成案编排；生产零调用，27 处测试；夹带点 state/读 turn_directives |
| `list_fiscal_effects_for_dossier` | db.py:20235-20253 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `list_dossier_durable_effects` | db.py:20255-20262 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `record_dossier_actual_progress` | db.py:20264-20314 | store 公开:record_progress | 双轨（奏报/实况）+月度批量 |
| `list_dossier_actual_progress` | db.py:20316-20321 | store 公开:list_progress |  |
| `sum_dossier_actual_progress_units` | db.py:20323-20328 | store 公开:list_progress |  |
| `list_dossier_actual_rail` | db.py:20330-20344 | 段适配器 | 拆分：实况轨行→store list_progress；durable 效果行→效果读面组合 |
| `dossier_has_beyond_intent` | db.py:20346-20354 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `list_economy_moves_for_dossier` | db.py:20356-20368 | 留 GameDB | 读 office/skill/fiscal/economy 效果表，不触案卷表 |
| `_normalize_participant_roster` | db.py:20385-20419 | store 私有 | attach/create 校验；跨域共用点名（settle_endorsement_batch@9826、insert_issue@19740、cli_backend.py:1907/1924） |
| `_validate_participant_roster_references` | db.py:20421-20463 | store 私有 | attach/create 校验；跨域共用点名（settle_endorsement_batch@9826、insert_issue@19740、cli_backend.py:1907/1924） |
| `_character_knowledge_events` | db.py:20465-20562 | 留 GameDB | knowledge concern；夹带点：动态 SQL 涉 decree_dossiers（db.py:20540/20573），施工点名 |
| `_participant_roster_tables` | db.py:20564-20583 | 留 GameDB | knowledge concern；夹带点：动态 SQL 涉 decree_dossiers（db.py:20540/20573），施工点名 |

**类级常量随迁账**（`GameDB` 类属性，AST 圈定）：

| 常量 | db.py 现址 | 新 owner |
|---|---|---|
| `_DOSSIER_STATUSES` / `_DOSSIER_ACTION_TYPES` / `_DOSSIER_TRANSITIONS` | 12037-12044 | store 私有（状态机闭集） |
| `_PROMULGATION_BLOCKED_LAYERS` | 12045-12047 | store 私有 |
| `_DOSSIER_EXECUTION_OUTCOMES` | 12048-12051 | **store 公开常量**（单真源；supervision.py 平行闭集消亡，见 §3.3） |
| `DOSSIER_MODES` | 12428-12430 | store 公开常量（现已为公开命名） |
| `DOSSIER_REPORT_ORIGIN_NS` / `_MONTHLY` / `_VERDICT` | 12487-12489 | store 公开常量（同上） |
| `_OVERRIDE_AUTHORITY_COST` / `_REACTION_INTENSITY` / `_REACTION_SIGN` / `_BREACH_FACTION_REACTION` | 16004-16007 | store 私有（record_verdict/breach 代价参数） |
| `_JOINT_LIABILITY_COST_IDENTITY` | 16010 | store 私有 |
| `_EXECUTION_OUTCOME_INTENSITY` / `_JOINT_LIABILITY_TRIGGERS` / `_INTENSITY_DOWNGRADE` | 16011-16015 | **store 公开常量**（`_JOINT_LIABILITY_TRIGGERS` 现有 2 处外读，见 §3.3） |

## 3. 生产调用点账

### 3.1 外部使用方法 × 调用模块清单（51 名 = 判词 49 + 区间外 2）

AST 口径：`ming_sim/**`（除 db.py）+ 根目录 `driver.py`/`web_app.py` 中对该 124 名的 `Call`/`Attribute` 引用；同行多次引用去重。每行给出全部命中文件与行号、以及改径后的新入口。

| 旧方法名 | 生产调用点（file:line 全量） | 新入口 |
|---|---|---|
| `_character_knowledge_events` | knowledge.py:436,437 | 留 GameDB（knowledge concern） |
| `_find_pacification_target` | rescript_actions.py:896; session.py:2478 | 段适配器 |
| `_normalize_directive_dossier_payload` | rescript_actions.py:933 | store 私有（外读违规点名） |
| `_normalize_participant_roster` | cli_backend.py:1907 | store 私有（外读违规点名） |
| `_validate_participant_roster_references` | cli_backend.py:1924 | store 私有（外读违规点名） |
| `accept_faction_denunciations` | decree.py:2724 | 子模块 supervision（改造：turn 纯标量、clamp 段侧预解析、零 commit，§2.2） |
| `append_decree_dossier_participants` | issues.py:7439 | attach_participants |
| `apply_dossier_promulgation` | decree.py:2534 | record_verdict |
| `apply_dossier_verdicts` | decree.py:2525 | record_verdict |
| `apply_execution_joint_liability` | due_review.py:555; issues.py:8217 | record_joint_liability（判定写）+ 段效果消费 |
| `breach_decree_dossier` | breach_plea.py:738; issues.py:6032 | record_breach_judgment（判定写）+ 段效果消费 |
| `build_faction_denunciation_facts` | issues.py:2556; simulation.py:859 | 子模块 supervision |
| `build_supervision_judge_surface` | decree.py:952; due_review.py:194; simulation.py:1335 | 子模块 supervision |
| `create_decree_dossiers` | rescript_actions.py:947 | create |
| `dossier_authorizes_effects` | covert_levy.py:25; issues.py:115,243,6027; pay_order.py:321,411 | get |
| `dossier_has_beyond_intent` | issues.py:2577 | 留 GameDB |
| `executable_decree_dossier_ids` | decree.py:1256 | list_dossiers |
| `get_decree_dossier` | action_materialize.py:2108,2117; breach_plea.py:175,851; covert_levy.py:106; credit_events.py:249,297,312,545; due_review.py:145,512; issues.py:113,242,6019,7122,7447,8175; pay_order.py:314,405,406; population_pressure.py:86; simulation.py:1317; urge_lever.py:279,341 | get |
| `get_dossier_for_directive` | action_materialize.py:294; registry.py:627; session.py:2856 | get |
| `get_dossier_for_secret_order` | covert_progress.py:279,498,585; decree.py:760; issues.py:9343; simulation.py:1205 | get |
| `get_pending_promulgation_verdicts` | decree.py:1148 | pending_verdicts |
| `list_closed_army_pay_dossiers_for_provenance` | simulation.py:1266 | list_dossiers |
| `list_decree_dossier_decisions` | decree.py:886 | list_decisions |
| `list_decree_dossiers` | decree.py:1051,1060,1124 | list_dossiers |
| `list_decree_dossiers_for_simulation` | driver.py:218; decree.py:1249; simulation.py:1253 | list_dossiers |
| `list_dossier_durable_effects` | due_review.py:190; issues.py:2636; urge_lever.py:594 | 留 GameDB |
| `list_dossier_endorsements` | decree.py:323 | list_endorsements |
| `list_dossier_links` | decree.py:902 | list_links |
| `list_dossier_progress` | breach_plea.py:546; covert_progress.py:608; due_review.py:187,540; issues.py:8205,9345 | list_progress |
| `list_dossier_reconciliations` | issues.py:7857,7948 | 子模块 reconciliation |
| `list_economy_moves_for_dossier` | breach_plea.py:511; issues.py:7866; urge_lever.py:598 | 留 GameDB |
| `list_fiscal_effects_for_dossier` | breach_plea.py:518; issues.py:8026 | 留 GameDB |
| `list_monthly_dossier_progress_nudges` | decree.py:1059; simulation.py:544,1346 | list_progress |
| `list_open_grant_reconciliations` | simulation.py:1362 | 子模块 reconciliation |
| `list_referenceable_dossiers` | action_materialize.py:162; session.py:1788,1855,2200; tools.py:628; web_app.py:2644 | list_dossiers |
| `merge_grant_reconciliation_into_execution_note` | issues.py:8199 | 子模块 reconciliation |
| `read_directive_dossier_payload` | action_materialize.py:477; cli/terminal.py:882; web_app.py:5014 | 留 GameDB（directive 读缝） |
| `read_dossier_fork_state` | covert_levy.py:181; issues.py:2633 | list_progress |
| `record_dossier_actual_progress` | covert_progress.py:521 | record_progress |
| `record_dossier_execution` | breach_plea.py:853,877; due_review.py:533; issues.py:8195 | record_execution |
| `record_dossier_progress` | breach_plea.py:858; due_review.py:542,550; issues.py:8209 | record_progress |
| `record_monthly_dossier_progress` | decree.py:2720 | record_progress |
| `record_monthly_grant_reconciliations` | decree.py:2728 | 子模块 reconciliation |
| `record_monthly_loophole_exposures_from_reconciliations` | decree.py:2732 | 子模块 supervision |
| `record_monthly_supervision_presence` | decree.py:2719 | 子模块 supervision |
| `resolve_commitment_origin_ref` | issues.py:5588 | list_links |
| `save_pending_promulgation_verdicts` | decree.py:1171 | pending_verdicts |
| `sum_dossier_actual_progress_units` | covert_progress.py:282,594 | list_progress |
| `trigger_commitment_backlashes` | decree.py:2334 | 拆分：store list_backlash_terminal_dossiers + 编排层 |
| `trigger_supervision_countermeasures` | decree.py:2322 | 拆分：supervision `list_supervision_countermeasure_candidates`（纯读）+ 编排层（integrity 过滤/issue 查重/创建/commit） |
| `validate_joint_liability_affected_parties` | issues.py:8194 | validate_joint_liability_affected_parties（公开，record_joint_liability 配套校验） |

归并分布（51 名，逐行复算自洽：30+9+3+6+3=51）：30 名 → store 公开 19 入口；9 名 → 子模块（supervision 5 / reconciliation 4）；3 名 → 段适配器（`_find_pacification_target`、`trigger_commitment_backlashes` 编排半、`trigger_supervision_countermeasures` 编排半——后两者分别拆出 store 公开 `list_backlash_terminal_dossiers` 与 supervision 公开 `list_supervision_countermeasure_candidates`）；6 名 → 留 GameDB；3 名为**私有被外读**（`_normalize_directive_dossier_payload` rescript_actions.py:933、`_normalize_participant_roster` cli_backend.py:1907、`_validate_participant_roster_references` cli_backend.py:1924），与裸 SQL 同属收口对象。store 公开 21 入口中另 2 个（`record_override_judgment`、`list_backlash_terminal_dossiers`）析自段适配器组方法的判定/纯读半，不占本表 51 名；supervision 公开 7 入口对上表仅 5 名——`list_supervision_countermeasure_candidates` 析自段侧拆分纯读半、`list_faction_denunciations` 生产消费为裸 SQL 改道（§3.2 #12），均不占 51 名。

### 3.2 裸 SQL 直读案卷表：实测 14 处 / 7 模块（底稿「10 处」的修正）

AST/grep 口径：`ming_sim/**`（除 db.py）内含 13 张案卷表名的 SQL 字符串逐条人工核读。底稿列 13 行号称「10 处」、ADR 称「10 处散在 8 个模块」；实测 **14 处、7 个模块**——底稿漏 `covert_levy.py:200`（直读 `faction_denunciations`，恰为判词点名表），模块数为 7 个文件而非 8。行号为 SQL 语句起始行（底稿的 2037/361 为引用行漂移，实测 2038/363）。

| # | 模块：行 | 触及表与语义 | 新归宿 |
|---|---|---|---|
| 1 | action_materialize.py:2038 | `decree_dossiers`：可撤成命候选扫描（status IN promulgated/executing） | `list_dossiers`（status 面） |
| 2 | issues.py:2568-2572 | `decree_dossiers`：近 2 回合 transformed 结案扫描 | `list_dossiers` |
| 3 | issues.py:7907-7912 | `decree_dossiers`：grant_allocation 全量扫描 | `list_dossiers` |
| 4 | execution_pressure.py:347-350 | `decree_dossiers`：executing 案卷 region+participant_roster 装载 | `list_dossiers`（region 面） |
| 5 | execution_pressure.py:358-361 | `decree_dossiers`：executing 分省计数 | 同上 |
| 6 | execution_pressure.py:594-597 | `decree_dossiers`：executing 涉及省 distinct | 同上 |
| 7 | breach_plea.py:1246 | `decree_dossiers`：by id 取 executor_id/payload_json | `get` |
| 8 | covert_levy.py:17-21 | `decree_dossiers`：禁令案卷授权扫描（target_kind='dossier'） | `list_dossiers` |
| 9 | covert_levy.py:75-78 | `decree_dossiers ⋈ armies`：欠饷真值 join | 段适配器（跨 army 表 join；案卷侧经 `get`） |
| 10 | covert_levy.py:179 | `decree_dossiers`：全量 id 扫描 | `list_dossiers` |
| 11 | covert_levy.py:194 | `decree_dossier_links`：稽核链存在判定 | `list_links` |
| 12 | covert_levy.py:200 | `faction_denunciations`：origin 直读（底稿漏列） | 子模块 supervision `list_faction_denunciations` |
| 13 | decree.py:363 | `decree_dossier_decisions ⋈ decree_dossiers`：判决历史携 payload | `list_decisions`（携 payload 读面） |
| 14 | covert_progress.py:510 | `dossier_actual_progress`：同回合幂等查 | `record_progress` 实况轨内部（幂等写口子步骤） |

### 3.3 私有常量外读与平行闭集（3 处 + 表名常量）

| 对象 | 现址 | 外部触用点 | 处置 |
|---|---|---|---|
| `GameDB._JOINT_LIABILITY_TRIGGERS` | db.py:16014 | due_review.py:554、issues.py:8192 直读 | 转为 store 公开常量单真源，两处改引用 |
| `GameDB._DOSSIER_EXECUTION_OUTCOMES` | db.py:12048-12051 | supervision.py:43-46 抄录成平行闭集 `EXECUTION_FORMS`；db.py:13171/13174 反向 import 该抄录 | 平行闭集消亡，supervision 改引 store 公开常量；db.py:13171/13174 反向 import 随之消亡 |
| `supervision.py` 表名常量 `DENUNCIATION_TABLE`/`PRESENCE_TABLE`/`EXPOSURE_TABLE` | supervision.py:97/105/106 | tests 引用：test_faction_denunciation_627.py:29、test_supervision_625.py:43/48 | 常量消亡（子模块自给表名），测试改道 |

另：issues.py:8216 为注释文字引用 `_JOINT_LIABILITY_TRIGGERS`，随代码行更新。

### 3.4 GameDB 内部跨域调用点（concern 区间外调用 concern 方法的 GameDB 方法，16 个）

无 facade 纪律下这些内部调用方同样改径。AST 口径：db.py 内调用点落在 §0.1 区间之外的调用方方法：

| 调用方（GameDB 方法 @ 行） | 被调的 concern 方法 |
|---|---|
| `init_schema` @876 | 5 组迁移/回填（§1） |
| `set_character_status` @5638 | `interrupt_dossiers_for_character` |
| `effect_origin_rejection` @6730 | `get_decree_dossier`、`dossier_authorizes_effects` |
| `settle_endorsement_batch` @9826 | `add_dossier_endorsement`、`_validate_dossier_endorsement` |
| `_merge_directive_payload` @17497 | `_normalize_directive_dossier_payload`、`_decode_directive_dossier_payload`、`_normalize_participant_roster` |
| `_prepare_pending_directive` @17768 | `_normalize_directive_dossier_payload` |
| `commit_pending_actions` @17821 | `_record_dossier_link_rejection` |
| `_apply_pending_action` @18116 | `_directive_dossier_action_type`、`_directive_executor`、`_normalize_directive_dossier_payload`、`create_decree_dossier(s)`、`add_dossier_links`、`get_dossier_for_secret_order` |
| `confirm_directive` @19103 | `_ensure_directive_dossier`、`read_directive_dossier_payload` |
| `update_directive_text` @19205 | `get_dossier_for_directive` |
| `delete_directive` @19257 | `get_dossier_for_directive` |
| `insert_issue` @19740 | `_normalize_participant_roster` |
| `create_secret_order` @21149 | `create_decree_dossier` |
| `list_secret_orders` @21408 | `get_dossier_for_secret_order`、`list_dossier_progress` |
| `close_secret_order` @21462 | `get_dossier_for_secret_order`、`list_dossier_progress`、`record_dossier_progress`、`record_dossier_execution`、`transition_decree_dossier` |
| `mark_secret_order_in_progress` @21671 | `_commit_dossier_write`、`get_dossier_for_secret_order`、`transition_decree_dossier` |

## 4. 测试调用面粗账

AST 口径：`tests/**` 下每个 `test*` 函数体内对 §0.1 区间内 119 名的直接 `Call` 计数；文件/函数统计为「含 ≥1 个直调调用点的文件」及其内全部测试函数。

- **实测：69 个测试文件 / 1,511 个测试函数 / 538 个函数含直调 / 1,386 个直调调用点。**
- 判词口径 66 / 1,449 / 538：**直调函数数 538 完全一致**；文件差 3——其中 2 个已定位为仅触 knowledge/roster 私有缝、不涉案卷语义的文件（tests/test_secret_order_isolation_883.py 仅调 `_character_knowledge_events`；tests/test_qa_c_p0_1380_1355.py 仅调 `_validate_participant_roster_references`），判词或将其剔除，第 3 个疑为取数时点漂移；函数总数差 62 同理。
- ADR 票面「~830 个案卷测试函数机械改径」与 538 口径不同（疑含间接经用/宽口径计数）；本文以 AST 直调实测 538 为准。
- 若把区间外 5 名也计入直调名集：69 文件 / 1,511 函数 / 548 函数含直调 / 1,431 调用点（差 10 个函数全部来自 `ensure_dossiers_for_draft_directives`、`read_directive_dossier_payload` 等区间外名）。

逐文件明细（文件 | 测试函数数 | 含直调函数数 | 直调调用点数）：

| 文件 | 函数 | 含直调 | 调用点 |
|---|---|---|---|
| tests/test_advance_paths_atomic.py | 34 | 1 | 1 |
| tests/test_appointment_tenure_607.py | 6 | 1 | 5 |
| tests/test_army_pay_decree_1503.py | 18 | 16 | 36 |
| tests/test_assignment_materialize_520.py | 18 | 10 | 13 |
| tests/test_audience_background.py | 20 | 1 | 1 |
| tests/test_audience_night_498.py | 17 | 2 | 5 |
| tests/test_authority_ledger_611.py | 13 | 4 | 9 |
| tests/test_authorization_materialize_528.py | 12 | 6 | 8 |
| tests/test_breach_plea_623.py | 25 | 5 | 9 |
| tests/test_character_knowledge_489.py | 69 | 3 | 4 |
| tests/test_commitment_backlash_626.py | 14 | 14 | 34 |
| tests/test_covert_levy_651.py | 19 | 3 | 6 |
| tests/test_credit_events_628.py | 4 | 1 | 1 |
| tests/test_decree_commitment_creation_136.py | 33 | 1 | 1 |
| tests/test_decree_dossiers_571.py | 94 | 88 | 269 |
| tests/test_deformation_dual_rail_622.py | 9 | 4 | 25 |
| tests/test_dossier_endorsements_612.py | 11 | 8 | 44 |
| tests/test_dossier_links_559.py | 23 | 14 | 40 |
| tests/test_dossier_reported_progress_619.py | 8 | 8 | 37 |
| tests/test_driver.py | 44 | 2 | 2 |
| tests/test_due_review_621.py | 21 | 12 | 18 |
| tests/test_effect_origin_558.py | 13 | 1 | 2 |
| tests/test_execution_joint_liability_565.py | 12 | 9 | 16 |
| tests/test_execution_pressure_654.py | 46 | 21 | 49 |
| tests/test_execution_tenure_613.py | 11 | 2 | 5 |
| tests/test_executor_routing_721.py | 28 | 11 | 18 |
| tests/test_extractor_slot_routing_629.py | 6 | 3 | 6 |
| tests/test_faction_denunciation_627.py | 9 | 5 | 29 |
| tests/test_family_tail_615.py | 2 | 2 | 11 |
| tests/test_family_tail_restore_570.py | 1 | 1 | 7 |
| tests/test_fiscal_beyond_intent_1260.py | 9 | 3 | 11 |
| tests/test_grant_allocation_materialize_518.py | 17 | 13 | 30 |
| tests/test_grant_reconciliation_567.py | 8 | 7 | 23 |
| tests/test_impeachment_surge_655.py | 13 | 2 | 3 |
| tests/test_interim_path_materialize_529.py | 15 | 1 | 2 |
| tests/test_ledger_sim_recon_569.py | 9 | 5 | 21 |
| tests/test_military_order_materialize_521.py | 19 | 14 | 27 |
| tests/test_minister_context.py | 27 | 1 | 4 |
| tests/test_multi_directive_502.py | 17 | 2 | 2 |
| tests/test_multi_intent_utterance_519.py | 6 | 1 | 1 |
| tests/test_office_rank_562.py | 18 | 1 | 1 |
| tests/test_override_breach_costs_564.py | 21 | 21 | 54 |
| tests/test_p4_guard_new_surfaces_547.py | 5 | 2 | 10 |
| tests/test_pacification_materialize_522.py | 20 | 10 | 16 |
| tests/test_pay_order_override_653.py | 69 | 26 | 54 |
| tests/test_pay_order_override_extraction_653.py | 4 | 1 | 1 |
| tests/test_pending_actions.py | 83 | 5 | 8 |
| tests/test_pihong_dossier_1490.py | 40 | 10 | 24 |
| tests/test_promulgation_judge_561.py | 37 | 29 | 52 |
| tests/test_promulgation_seam_560.py | 19 | 16 | 49 |
| tests/test_punishment_materialize_517.py | 24 | 14 | 24 |
| tests/test_qa_c_p0_1380_1355.py | 17 | 1 | 1 |
| tests/test_referral_materialize_524.py | 16 | 9 | 13 |
| tests/test_refugee_loop_652.py | 21 | 9 | 19 |
| tests/test_relation_capture_633.py | 29 | 1 | 1 |
| tests/test_rescript_choices_563.py | 12 | 7 | 19 |
| tests/test_revoke_authority_materialize_523.py | 18 | 8 | 24 |
| tests/test_secret_dossier_participants_1252.py | 10 | 8 | 22 |
| tests/test_secret_order_injection.py | 4 | 1 | 1 |
| tests/test_secret_order_isolation_883.py | 41 | 2 | 4 |
| tests/test_secret_order_monthly_progress_566.py | 19 | 12 | 28 |
| tests/test_secret_order_payoff_1504.py | 24 | 12 | 49 |
| tests/test_session_cli_fallback.py | 84 | 4 | 4 |
| tests/test_state_reload.py | 15 | 1 | 1 |
| tests/test_strategy_selection_568.py | 6 | 3 | 3 |
| tests/test_supervision_625.py | 16 | 10 | 55 |
| tests/test_surcharge_causal_chain_650.py | 28 | 2 | 7 |
| tests/test_urge_lever_624.py | 23 | 3 | 4 |
| tests/test_web_audience_night_498.py | 8 | 2 | 3 |

---

**自查声明**：§1 表行号、§2.2 全部 124 行、§3.1 全部 51 行、§3.2/3.3/3.4 各行均带 file:line；§0.2/§4 计数均注明 AST 口径。复核脚本口径见 §0 头部；复算方式 = 以同名 AST 脚本在 HEAD `e88cc29c` 重跑（区间圈定 + `ast.Call`/`ast.Attribute` 名匹配 + `tests/**` 直调计数）。
