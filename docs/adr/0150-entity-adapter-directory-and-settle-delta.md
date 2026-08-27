# 实体适配器目录与 settle_delta 落库编排器

Status: accepted（实现分波次，见末节；**supersedes ADR 0008 决定 8**；落地物归 issue #1572；r1 大理寺退回修订：内存态条款收窄不越 0008 决定 3 / settle_delta 边界收窄为内层子核 / source 与 origin_ref 拆正交 / canonical 与删桥同 fixed point；r2 附施工证据四件；r3 三审修订：RejectedItem 收窄为项级四字段、turn/section 归框架投影 / verdict 脏载荷重裁对齐 0005（行为修正，见决定 5）/ 证据勘误三件；r4 四审后修订：A 类落格与邸报文案纪律立法（决定 5 末，决策键 0150-D5-a/b，owner 裁定原话在卷）/ 决定 2 删 source 自洽伤 / 决定 6 直调口径改全仓 54/451 / 决定 8 测试波次自洽（45 迁 + 6 删 + 23 改径并入 PR-1））

ADR 0008 的段适配器契约只落地了一半：`ApplyContext`/`SectionResult` 生产侧零引用（死类型，只有给死类型发绿卡的测试），`apply_score_extraction` 仍是 1,344 行单体、~20 段硬编码 inline 循环，拒收形状散在 4 处，返回 39 键 ad-hoc dict（含恒空兼容键与双份键），且 GameDB 的 verdict 路径反向合成伪 delta 回调全机（≥5 处，layering 倒置靠懒 import 压住）。架构评审 2026-08-27 与 #1572 grill 结论：不打补丁、不留兼容层，全面重开 0008 决定 8「原地迁入、不大搬家」。

## 决定

1. **实体适配器目录成立**：写侧段适配器按实体入住 `ming_sim/entities/<entity>/`，兑现 ADR 0010 决定 1 的共置约定——读侧呈现适配器将来住进同一实体目录。登记沿用 0010 验收口径：**lazy import / 仅注册模块路径**的有序清单，不在初始化同步加载重模块（防与 GameDB 等循环依赖），无第二注册机制。**supersede 0008 决定 8**：当年「原地迁入」的理由（免与财政线撞文件）已随财政线落地而过期，inline 形态反而固化了契约的半落地。

2. **段契约承重化**：每段一个模块，`apply(items, ctx) → SectionResult`；`RejectedItem` 为全系统唯一拒收形状（单点定义）：**项级四字段 `item/reason/category/source`**——段只知道自己拒了什么；**`turn`/`section` 不进 `RejectedItem`**，由框架在拒收报告（rejection_reports / jsonl）投影时补。各段手拼 dict、decree 侧 `_collect_inline_rejections` 递归桥接（含其硬编码特例）、GameDB 三处 `owns_rejection_collector` 分支全部删除。**canonical 化与旧桥/旧 dict 删除是同一 fixed point**：旧桥删后未返回 SectionResult 的段无法组成 `SettlementOutcome`，故「全段返回 SectionResult + 框架集中补 turn/section + 拒收落库 + 删旧桥」必须一次到位；后续波次只可深化实体逻辑或迁移测试，不可再补契约。

3. **段不拥有事务与 reload 生命周期**（旧形态「调用方须懂实现细节」的根除）：段实现**不 commit、不判事务、不自包事务、不做内存态快照/恢复**——`commit=` 参数、`owns_transaction()` 判定、flows 式自包 atomic + metrics 快照全部不进入段的地平线；事务边界由编排器独占，回滚后的内存态由最外层统一 `reload_state_from_db`。内存态语义**沿用 ADR 0008 决定 3 不动**：事务期内正常写内存供同事务后续读取（必要运行态同步继续走既有写 seam），仅回滚后统一 reload。本决定不 supersede 0008 决定 3。

4. **段序 = 有序登记表**：目录内一张有序 lazy 清单，清单顺序即执行顺序与顺序约束的唯一真源（先建军再 army_delta、人物 pre/post-issue 拆分、财政 removes→creates→changes 等不再只活注释里），并承接 0008 的段白名单职责。登记表条目含段名/lazy path/delta_keys/空值工厂/extractor_owners，**同时承接 `simulation.py` 侧 `MODULE_FIELDS`/`EMPTY_EXTRACTION` 的真源职责**——二者消亡、改为从登记表派生的视图，不双写；无落库段的 7 个 delta 键（world_advance/emperor_fate/事件结局/dossier_progress_reports/faction_denunciations/dossier_reconciliations/covert_exec_selections）登记为框架段条目，防派生时缩键。不建 before/after 依赖声明机制——约束图稀疏稳定，声明机制是投机通用性。不为登记表新增启动断言护栏：三种漂移失败模式（无 owner 键被 `_sanitize_module_output` misroute 剔除、owner 不在 `EXTRACTION_MODULES` 则模块永不跑且既有测试即红、lazy path 写错 fail-loud import）均被既有 seam 响亮覆盖，派生视图不构成第二真源。

5. **依赖倒转**：`GameDB` 不再 import 结算编排层。verdict 效果物化上浮：案卷判决只写案卷表 + 产出效果意图（delta 片段），由编排层走对应段适配器落库。上浮时按三分类重裁失败语义（ADR 0052 只管颁布格/执行格两格，未授权任何软硬政策；现行若干路径的整批回滚实为违 0005 的脏载荷硬失败，迁移即修正）：**【A】LLM 脏载荷**（缺 holder/缺目标/非法 id/载荷校验不过）→ canonical `RejectedItem` 逐项拒收留痕、不带走同批其它 verdict——**这是对齐 ADR 0005 的可观察行为修正（现码 authorization/military_order/punishment/pacification 等路径为整批回滚）——行为变化告示：同批 verdict 不再被脏项带走，邸报提示按 provenance gate 出现；其中罚俸不足额从硬回滚改软 failed 是变化最大的一处**；**【B】合法执行失败** → soft：判决格保留、转 executing 后执行格落 failed/相应终值（现 assignment/referral 通道，保留不拉平）；**【C】代码/持久真源损坏/法源闸**（整批预验、强颁门、无合法案卷来源、payload 非对象）→ strict fail-loud 整批回滚。复用既有 `dossier_action_policy` 与 canonical delta/SectionResult，**不建第二政策表**；奏报轨（0073）仍永不入 apply。**A 类落格（决策键 0150-D5-a；四审 escalated 御前决策问题，owner 2026-08-27 裁定原话：「应该是1.但说法应该不出戏。比如类似查无此人，或者别的什么。不能说什么xxxx not found这种东西。」）**：RejectedItem 形成后案卷统一 transition `executing` → 执行格落 `failed` → close，与 B 类软通道同形收尾（区别只在拒收报告的 category 字段），RejectedItem 沿 assignment/referral 现有软通道另行留痕——不立重试机制、不按 action_type 分列映射（22 值矩阵保持迁移证据，不变成生产政策表）。**邸报文案纪律（决策键 0150-D5-b；owner 2026-08-27 原话：「简单来说就是 告诉llm 事实。让llm自己去编话。而不是代码写话/代码管llm说什么」；合 CLAUDE.md P6/P7）**：代码只供事实（item/category/reason 结构化字段），玩家可见措辞由 LLM 据实编织、保持 in-fiction（如「查无此人」式），代码不写话、不管 LLM 说什么——禁止把技术字符串（`not found` 类）直接透出给玩家。逐 action_type 现码行为 vs 迁移后口径的审计矩阵已附：**[docs/evidence/issue-1572/verdict-action-type-matrix.md](../evidence/issue-1572/verdict-action-type-matrix.md)**（22 值闭集 + 分型全覆盖；迁移证据，运行时政策真源仍是 `dossier_action_policy`）。

6. **新入口 `settle_delta(state, db, delta, ctx) → SettlementOutcome`**：它替换的是**内层落库子核** `apply_score_extraction`（整体退役删除，不留 deprecated 壳；全仓 AST 实点直调 **54 文件 / 451 调用点** = tests/+ming_sim/ 口径 52 文件 / 449 点 + `driver.py:255` + `scripts/promulgation_gate_561.py:242`，含 `decree.py:1400/1668/2411` 与 `driver.py:255` 三处显式 `delta_applier` 注入缝——迁约逐点见证据）。**外层共享核 `settle_with_delta`（ADR 0004，生产/driver 共用、返回 full_report）保留不动**——decree 两路、driver、恢复入口仍调 `settle_with_delta`，仅其内部真正的落库调用点改调 `settle_delta`，`SettlementOutcome`（聚合 SectionResult + 拒收报告，类型化，无恒空兼容键/双份键）供外层组装 full_report。现有返回 dict 39 键的逐键消费者盘点与 typed 投影表（含 13 个删除键与外层追加键）已附：**[docs/evidence/issue-1572/settlement-outcome-projection.md](../evidence/issue-1572/settlement-outcome-projection.md)**。

7. **provenance：source 与 origin_ref 正交，互不覆盖**。`ctx` 携带信封级 typed `source` 默认（player_decree|hitl_decision|secret_order|system_simulation|unknown，ADR 0008 决定 5 的五值可见性分类）；`origin_ref` 始终是独立的效果回指/授权字段（0073 轨），**不从 origin_ref 文本反猜 source、origin_ref 不覆盖 source**。混合来源的一次结算必须保持决定 4 的全局段序与原子性——不得按来源分组重复跑登记表；具体 typed 来源解析机制（项级 typed source、结构化来源映射或其它单次遍历方案）留实现择一。邸报 in-world 提示的 source gate 口径不变。

8. **迁移波次**：fixed point 前可有若干**单实现纯移动**的独立先行 PR（实现随迁、零行为差、零壳）；地基 PR（fixed point）= 目录 + canonical 类型 + 有序登记表 + **全部剩余实现的真实搬家** + `settle_delta` 接任内层子核 + 旧入口/旧桥删除——单 PR 内按实体分 commit 链，「全段返回 SectionResult + 删旧桥」与「实现入目录」不可分，壳态/半搬态只许存在于中间 commit、**不得独立落目标分支**。per-实体量化清单已附：**[docs/evidence/issue-1572/migration-inventory.md](../evidence/issue-1572/migration-inventory.md)**——迁移触及面 5,974 行 = 纯移动 ≈4,460 + 行为改动 ≈1,515（另 decree/db 侧删除 ~130 行）；PR-0a~0e 五个纯移动先行 PR、PR-1 地基 fixed point（**含直调旧入口测试的同步迁移**——45 个迁移函数 + 6 个死类型绿卡删除 + 主干·adapter 臂 23 个 import 机械改径，与旧入口退役/实现搬家不可分，不入 PR-1 则删入口即红）、PR-2 测试参数化塌缩（72 个公共主干函数，入口已在 PR-1 就位、不阻塞）、PR-3 实体深化示范、PR-4 verdict 上浮。issues.py 清算范围：落库段全搬；事件门闩求值引擎留（求值器非落库段）；呈现 helper（被 web_app 私有 import 的那组）顺手迁入对应实体目录读侧。

## Considered Options

- **目录薄壳 + 实现原地**（壳先立、搬家后续）：壳立在那、实现永远「后续再搬」，契约与实现两张皮的补丁态。否决——任何可独立合并的 PR 都不得是薄壳态（决定 8 的 PR 纪律即此否决的执行形）。
- **拒收边界转换桥接**（段内不动、壳出口归一）：桥接即补丁，且硬编码特例永续存在。否决——一刀切。
- **per-流程分段目录**（按 delta 顶层 key 切）：与 ADR 0010 的 per-实体共置轴对撞，读侧适配器将来无家可归。否决。
- **保留 `apply_score_extraction` 名/返回 dict**：兼容键与双份键就是病灶本身。否决。
- **#1571（案卷 store）先行或并票**：两票互阻最伤；案卷段按普通段进目录，#1571 后续沉实现、目录不动。采纳为 sequencing。
- **「段只写 DB、事务期内不碰内存态」**（本 ADR r0 原稿）：越权改写 0008 决定 3 的事务期内存语义，且与现码人物写缝同步 content/registry、门闩读 state.metrics 的事实冲突。否决，收窄为决定 3 现文。
- **`settle_delta` 取代 `settle_with_delta` 外层核**（r0 原稿 US16/17 口径）：撞 ADR 0004 的共享核契约。否决，收窄为决定 6 现文。
- **反向派生登记表**（从 MODULE_FIELDS 反推段序）：段序信息不在 MODULE_FIELDS 里，反推必成双写。否决——登记表为唯一手写真源，MODULE_FIELDS 派生（决定 4）。
- **RejectedItem 六位形状**（turn/section 入项）：段不知道也不必知道 turn/section；它们是聚合上下文，归框架在报告投影时补。否决——项级四字段（决定 2）。

## Consequences

- 0008 其余决定（事务边界、重跑契约、错误包、拒收报告分析优先，含决定 3 的事务期内存语义）全部继续有效；仅决定 8 被本 ADR supersede。决定 5 的 A 类重裁是对 0005 的**对齐**而非 supersede——现码 verdict 路径的脏载荷整批回滚本就违 0005。
- 0010 验收项「新建实体适配器目录/索引（lazy import）」由本 ADR 交付；人物呈现适配器（#1574）将来入住同一目录。
- 测试迁移路径：DB 态断言为主的集成测试不动（迁移正确性的必要证据——但非充分，须配 fixed-point 验收）；section_rejections 家族只把**公共主干**（真实 driver/adapter 入口 → 坏项拒收 + 同批好项落库 → rejection_reports）参数化塌缩，独立契约 tracer（rollback/jsonl、source A/B、恢复、动态财政、clamp、战略整封、issue 路严格度、event_pool、玩家可见 extraction、formatter 等）逐份保留；人物/财政/战略三域**迁移既有真 SQLite 行为测试**到新 adapter 入口，不新增第二套平行 fixture；`test_applier_contract.py` 只删死类型构造绿卡部分（SectionResult/ApplyContext 旧形状 4 项），`RejectedItem` 四字段守门与 collector 事务/镜像生命周期行为迁移保留。11+1 个文件、209 个测试函数的逐函数处置表已附：**[docs/evidence/issue-1572/test-disposition.md](../evidence/issue-1572/test-disposition.md)**（72 入参数化主干 / 86 保留 / 45 迁移 / 6 删除；**波次归属**：45 迁移 + 6 删除 + 主干·adapter 臂 23 个 import 机械改径随 PR-1 fixed point 同 PR——与旧入口退役/实现搬家不可分；72 主干参数化塌缩为 PR-2，入口已在 PR-1 就位、不阻塞合并）。
- 新实体落库 = 在目录加一个实体段模块 + 登记表一行，契约、拒收、provenance、事务语义免费继承——0008 的原承诺这次兑现。
