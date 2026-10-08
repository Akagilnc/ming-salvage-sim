# verdict 逐 action_type 失败语义矩阵（#1572 / ADR 0150 迁移证据）

用途：大理寺判词要求随开工稿附的当前-head 迁移审计矩阵——逐一覆盖 `DOSSIER_ACTION_TYPES` 闭集及 payload 分型，列明各 action_type 在 verdict 物化阶段的 effect_owner、execution_surface、效果意图/目标段、脏数据拒收、合法执行失败、代码异常、颁布格/执行格/status 转移与原子性，供实体适配器目录 + `settle_delta` 落库编排器替代 `apply_score_extraction` 的迁移施工核对。**本矩阵仅作迁移证据，运行时政策真源仍是 `dossier_action_policy`，不得成为第二生产政策表。**

- HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`（Merge PR #1557；本文件所有行号以此 commit 实读为准）
- 闭集真源：`ming_sim/decree_vocabulary.py:3-19`（`DOSSIER_ACTION_TYPES`，22 值）
- 政策真源：`ming_sim/decree_vocabulary.py:64-78`（`DOSSIER_ACTION_POLICY` 推导表）＋ `:81-101`（`dossier_action_policy()`，grant_allocation payload 分型豁免）
- verdict 物化分支：`ming_sim/db.py:15403-15771`（`apply_dossier_promulgation`）
- verdict 批量入口：`ming_sim/db.py:16859-16936`（`apply_dossier_verdicts`）
- 失败语义法源：ADR 0005（按「谁的错」分流）＋ ADR 0008 决定 1（段适配器契约/RejectedItem 逐项拒收；决定 8 已由 0150 supersede，其余决定继续有效）。ADR 0052 只规定颁布格/执行格两格语义，**未授权** verdict 物化的软硬分流政策——本矩阵的软硬口径以 0005/0008 为准。

## 0. 三分类口径（全矩阵共用）

按 ADR 0005「谁的错」分流 + 0008 决定 1 契约，verdict 物化阶段的失败只许三态：

- **【A】LLM 脏载荷**（幻觉 id / 枚举非法 / 类型错 / 引用不存在实体）：**只拒该项、留痕、不带走整批**（0005 底线；0008 决定 1 → canonical `RejectedItem`（item/原因/类别/source）入拒收报告，邸报提示按 provenance gate）。
- **【B】合法执行失败**（载荷合法，世界状态使效果落不足：库银不足、cap 等）：soft——**判决格保留＋执行格 failed＋close**，不掀整批（现行 assignment/referral 软通道范式）。
- **【C】代码 / 持久真源损坏 / 法源闸**（schema 漂移、持久化案卷自相矛盾、颁布门、免代价旁路闸）：**strict fail-loud 上抛回滚，绝不吞**（0005 代码侧；0008「代码异常上抛」＋事务原子单元）。

§3 每行先记**现码行为**（逐行核实 db.py 所得），再记**迁移后口径**；现码把 A/B 类失败升格为 `ValueError` 整批回滚者，标注「**现码违 0005，迁移重裁**」。

## 1. 公共框架（22 个 action_type 共享，逐行核实；均为 C 类，迁移保留 fail-loud）

| 环节 | 行号（HEAD） | 语义 | 分类 |
|---|---|---|---|
| 判决合法性与状态门 | `db.py:15225-15251`（`record_dossier_decision`） | decision 四值闭集外 → `ValueError`；blocked_layer 闭集外 → `ValueError`；非 proposed 案卷写判决 → `ValueError`；留中案卷当月重判 → `ValueError` | C（判决缝输入契约，非 LLM 效果载荷） |
| 打回/留中/收回零写 | `db.py:15417-15429` | decision ∉ {promulgated, force_promulgated} → 只落 `record_dossier_decision`（＋中旨打回 stigma `:15425-15428`）后 return，**任何 action_type 零物化**。颁布格：rejected→`proposed`＋`rescript_pending=1`（`:15254-15255`）；hold→`proposed`＋`held_turn=当月`（`:15256-15259,15264-15267`）；withdrawn→`closed`（`:15260-15263`） | 法源闸，不变 |
| 强颁门 | `db.py:15430-15449` | 只承接「打回＋批红待抉择」或「留中跨月下月重判」组合态，违者 `ValueError`（`:15439,15442,15445-15446`）；先验 Judge 证据再写状态（`:15447-15449`） | C（法源闸） |
| payload 形体校验 | `db.py:15490-15492` | `payload_json` 解析非 dict → `ValueError("案卷 payload 非对象")` | C（payload 是成案时写入的持久真源，非对象=持久真源损坏） |
| 政策查表 | `db.py:15493` | `dossier_action_policy(row["action_type"], payload)`——唯一运行时政策真源的消费点 | — |
| idle_start 早退 | `db.py:15495-15505` | assignment / military_order 携空缺信号 → 只 transition `executing`，不预物化、不捏造终局 | 合法路径，非失败 |
| narrative / immediate 分支 | `db.py:15509-15561` | narrative → 只 transition `executing`（`:15510-15513`）；immediate → fulfilled「成案时即生效」close（`:15556-15560`）；grant_allocation 内库 immediate 走专门核验分支（`:15514-15555`，见 §3 行 6′） | — |
| payload 分发器 | `db.py:15562-15762` | 逐 action_type elif 链（见 §3）；无匹配分支者落尾部 | — |
| 尾部分支 | `db.py:15763-15771` | execution_surface ∈ {terminal, immediate} → `record_dossier_execution(fulfilled,"颁布即终局",close=True)`；in_transit → transition `executing` | — |
| 整批预验（先验后写） | `db.py:16864-16886` | 首写之前：verdict 非对象 → `ValueError`；案卷不存在 → `KeyError`；`validate_verdict_affected_parties`；rejected 须过 `validate_rejection_verdict`。任一不过整批不启动 | C（verdict 信封是 Judge 契约产物，非 LLM 效果载荷） |
| 单案原子性 | `db.py:15412` | `apply_dossier_promulgation` 本体 `with atomic(self)`：任一物化异常 → 本案全部写入回滚 | C 类失败的落点 |
| 整批原子性 | `db.py:16890-16892` → `decree.py:1742-1781` | `atomic_and_reload`（反向 lazy import `from ming_sim.decree import atomic_and_reload`，`db.py:16890`）：任一 verdict 抛异常 → SQLite 整批回滚，最外层 `_atomic_depth==0` 时 `reload_state_from_db` 刷净内存游戏态，原异常 fail-loud 上抛 | C 类失败的落点；A/B 类迁移后不再触达此路径 |
| 消费同事务 | `db.py:16932-16936` | `DELETE FROM pending_promulgation_verdicts WHERE turn=?` 与效果物化同属一个 atomic 单元；外层结算回滚则效果与消费同滚 | 不变 |

## 2. 政策表（`dossier_action_policy` 推导，22 值全覆盖）

推导规则：external_review 豁免集 `decree_vocabulary.py:47-49`；effect_owner（immediate/narrative/payload）`:39-50,67-71`；execution_surface（terminal/in_transit）`:51-62,72-74`。grant_allocation 的 payload 分型豁免 `:85-100`。

| action_type | external_review | effect_owner | execution_surface |
|---|---|---|---|
| policy | 受审 | narrative | in_transit |
| appointment | 受审 | payload | in_transit |
| acting_appointment | 受审 | payload | in_transit |
| assignment | 受审 | payload | in_transit |
| military_order | 受审 | payload | in_transit |
| grant_allocation | 受审（account=内库 → 豁免） | payload（内库 → immediate） | in_transit（加衔/荫叙 → terminal；cadence=每月 → terminal；payload.execution_surface 仅可 immediate/in_transit，非法值 `ValueError`，`:97-99`） |
| authorization | 受审 | payload | terminal |
| secret_authorization | 豁免 | payload | terminal |
| secret_investigation | 豁免 | narrative | in_transit |
| protection | 豁免 | narrative | in_transit |
| strategy_selection | 受审 | narrative | in_transit |
| approve_reject | 受审 | narrative | in_transit |
| secret_order | 豁免 | immediate | terminal |
| special_decree | 受审 | narrative | in_transit |
| revoke_decree | 受审 | payload | terminal |
| punishment | 受审 | payload | terminal |
| pacification | 受审 | payload | terminal |
| referral | 受审 | payload | in_transit |
| revoke_authority | 受审 | payload | terminal |
| dismiss_assignment | 受审 | payload | terminal |
| pay_order_override | 受审 | payload | terminal |
| prohibit_covert_levy | 受审 | payload | terminal |

## 3. 逐 action_type 失败语义矩阵（现码行为 vs 迁移后口径）

「现码行为」列逐条标分类（【A】/【B】/【C】，口径见 §0）；「迁移后口径」列给出 0150 施工应对齐的目标语义。顺颁后 status/执行格转移与原子性为现码实读；A 类重裁的落格已由 0150 决定 5 立法（统一 executing→failed→close，RejectedItem 沿软通道留痕），本矩阵不重复立法。

| # | action_type | 物化分支（HEAD 行号） | 效果意图 / 目标段 | 现码行为（失败逐条分类） | 迁移后口径 | 顺颁后 status/执行格转移（现码） | 原子性（现码） |
|---|---|---|---|---|---|---|---|
| 1 | policy | 无（narrative，`:15510-15513`） | 效果归 simulator/extractor 叙事轨；verdict 阶段零物化 | 仅公共框架（C 类） | 一致，不受影响 | proposed→promulgated→executing | 批内 atomic；无物化写，回滚面=判决写 |
| 2 | appointment | `:15562-15580` → `_commit_office_action` `:18165+`（朝臣唯一落地核 `apply_office_appointment`） | 人物段：任免/升迁/调任落官职档案；pending_action_id 挂承办候选 | 缺 name（`:18181-18182`）/任别非法（`:18197-18200`）/recommendation 毒形（`:18204-18208`）→ False → `:15578` raise `ValueError` 整批回滚【A-硬，**现码违 0005**】；落地核 dead 拒/空 office 拒同升格【A-硬，违 0005】；content=None（`:18177-18178`）→ False【C 运行环境，硬】 | A 类重裁为 canonical RejectedItem 逐项拒收留痕、不掀整批；C 类保留 fail-loud | 成功 → executing（in_transit，`:15768-15771`） | 硬失败 → 本案回滚，批内后续 verdict 同滚 |
| 3 | acting_appointment | **无分支**（elif 链 `:15562-15762` 不覆盖；db.py 全仓仅 `:14518` admission 承办路由处出现） | 无 verdict 物化路径。署理实效走既有人事候选链（#529，`cli_backend.py:2203-2204,2344-2345`），非案卷判后物化 | 仅公共框架 | 一致；**显式记：不受 verdict 物化迁移影响** | 落尾部 → executing（`:15768-15771`），无效果写 | 无物化写 |
| 4 | assignment | `:15745-15750` → `_apply_assignment_verdict_effect` `:16645-16731` | initiative 段：`new_issues` 槽（主办 participant_roster＋可选军令状承诺/分段里程碑 #620） | 缺主办 → `:16663` raise `ValueError`【C：owner 出持久案卷 roster，成案时已经 strict 校验，verdict 期缺失=持久真源矛盾，硬合理】；cap「分身乏术」/承诺毒形 → 槽内逐项 rejected → `:16723-16730` transition executing＋record failed close＋return False【软，不掀整批；但 A 类毒形与 B 类 cap 混记同一 failed】 | C 类保留 fail-loud；软通道保留「不带走整批」，迁移按 §0 细分：毒形 marker 缺失等 A 类 → RejectedItem 留痕，cap 等 B 类 → 执行格 failed | 成功 → executing；软拒 → executing＋执行格 failed 结案 | 软拒属正常提交；硬失败回滚 |
| 5 | military_order | `:15757-15762` → `_apply_military_order_verdict_effect` `:16509-16553`（station 面 `:16219-16266`；office 面 `:16268-16322`） | 军队段：既有军 station/station_region 经 `apply_army_deltas`（不得 new_armies）；人物段：职守变更经 `_apply_person_changes` 唯一核 | 缺 army_id（`:16233`）/引用未入库军队（`:16238-16240`）/army 写核拒（`:16266`）/职守变更全拒（`:16322`）→ 全 `ValueError` 整批回滚【A-硬，**现码违 0005**】；station=当前站幂等 noop 成功（`:16258-16259`）【合法，非失败】 | A 类重裁为 RejectedItem 逐项拒收留痕；幂等 noop 语义保留 | 成功 → executing（due_turn 已在案卷列）；idle_start 信号早退 executing（`:15495-15505`） | 硬失败 → 本案回滚（同批职守变更不被空接受误伤，`:16258-16259`） |
| 6 | grant_allocation（默认/拨饷/每月/荣誉分型） | `:15581-15655`；荣誉型 → `_apply_grant_honorific_effect` `:13962-13977`；每月 → `_create_grant_fiscal_item` `:13933-13960`；拨饷 → `_apply_army_pay_grant_effect` `:13884+` | 钱粮段：一次性拨帑经 `record_issue_economy_move`（拨饷/协饷走补饷销欠缝 ADR 0023 clamp）；fiscal_config 段：每月常项建科目；人物段：加衔/荫叙只落 person_log 叙事标签 | amount≤0（`:15589/15603`）/account 非国库内库（`:15594`）/加衔荫叙缺目标（`:13970-13971`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；常项建项失败（`:13958-13959`）【C 持久面，硬】；拨饷欠资（库银不足且军仍欠，`:15612-15629`）/其它拨帑不足额（`:15643-15655`）→ record failed close return【B-软，合法执行失败】 | A 类重裁为 RejectedItem；B 类软通道保留（判决格保留＋执行格 failed）；C 类保留 fail-loud | 荣誉/每月（terminal）→ fulfilled「颁布即终局」；默认 in_transit 足额 → executing；软拒 → failed 结案 | 软拒正常提交；硬失败回滚 |
| 6′ | grant_allocation（内库 immediate 分型） | `:15514-15555`（核验分支，非物化） | 成案时已物化；verdict 阶段只核验：每月查 fiscal 科目 `_base` 键（`:15516-15533`），一次性查实拨 delta（`:15534-15555`） | 科目未建 → failed「拨帑常项未建」（`:15523-15528`）；不足额 → failed（`:15537-15546`，in_transit 先 transition executing）【B-软】 | 一致，保留 | 足额：terminal → fulfilled「成案时建月度科目/成案时足额拨付」；in_transit → executing | 核验写（failed/fulfilled）随批 atomic |
| 7 | authorization | `:15725-15730` → `_apply_authorization_verdict_effect` `:16324-16371` | 授权段：`authority_changes` 授予槽（holder_id＋privilege＋scope＋dossier_id），不直写 authority_records/skill_grants | 缺 holder/privilege/scope（`:16352-16353`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；授予槽逐项被拒 → `:16369-16371` 升格 raise `ValueError`【A-硬，违 0005——`apply_score_extraction` 本已逐项拒收留痕，本缝把单项拒收升格为整批回滚】 | A 类重裁：保持槽内逐项拒收即 RejectedItem，不得升格整批 | 成功 → fulfilled「颁布即终局」（terminal，`:15763-15767`） | 硬失败回滚 |
| 8 | secret_authorization | `:15731-15734` = `pass`（密授不归本片，#528） | **无物化路径**；privileges 只经 authority_changes 生产，密授案卷判后零写 | 仅公共框架 | 一致；**显式记：不受影响** | 落尾部 → fulfilled「颁布即终局」（terminal） | 无物化写 |
| 9 | secret_investigation | 无（narrative） | 同 #1 policy | 仅公共框架 | 一致，不受影响 | → executing | 同 #1 |
| 10 | protection | 无（narrative） | 同 #1 | 仅公共框架 | 一致，不受影响 | → executing | 同 #1 |
| 11 | strategy_selection | 无（narrative） | 同 #1 | 仅公共框架 | 一致，不受影响 | → executing | 同 #1 |
| 12 | approve_reject | 无（narrative） | 同 #1 | 仅公共框架 | 一致，不受影响 | → executing | 同 #1 |
| 13 | secret_order | 无 verdict 物化（immediate，`:15556-15560`） | 成案（admission）时已物化；verdict 阶段只记终局 | 仅公共框架 | 一致；**不受影响** | 已颁始态 → fulfilled「成案时即生效」close | 无物化写 |
| 14 | special_decree | 无（narrative） | 同 #1 | 仅公共框架 | 一致，不受影响 | → executing | 同 #1 |
| 15 | revoke_decree | `:15740-15744` → `_apply_revoke_decree_verdict_effect` `:16409-16507` | 案卷段：终结目标承诺/旨意（0056 breach 代价轨）＋捆带授权收回＋同源停 tick；非 undo 不删旧账 | 缺目标（`:16450`）/目标事项不存在（`:16463`）/非 initiative（`:16465`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；无合法案卷来源（standalone issue 免代价旁路已删，`:16475`）→ `ValueError`【C 法源闸，硬合理】；目标挂 active 承诺 → `try_defer_revoke_to_breach_plea` 延期挽留（`:16487-16496`）【合法延期，非失败】 | A 类重裁为 RejectedItem；C 类法源闸保留 fail-loud；挽留延期路径不变 | 立即路径 `apply_persist_revoke_tail`（`:16499-16507`）→ fulfilled「颁布即终局」；延期路径本案卷仍落尾部 fulfilled（目标案卷的 breach/close 延迟到坚持后） | 硬失败回滚 |
| 16 | punishment | `:15664-15668` → `_apply_punishment_verdict_effect` `:16733-16834` | 人物段：处置类（下狱/赐死/流放/削籍）经 `_apply_person_changes`；宥赦（放归/昭雪）回迁 active；钱粮段：罚俸减项；廷杖只落 person_log | 缺 target（`:16741`）/未知 punish_action（`:16834`）/罚俸缺正数 amount（`:16804`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；人物效果全拒（`:16784`）【A-硬，违 0005】；宥赦回迁非法态（`:16789-16792`，对已死/未处置目标下旨=幻觉载荷）【A-硬，违 0005】；罚俸不足额/零落账（`:16819-16822`）→ `ValueError`【B 类合法执行失败（库银不足）但现码硬回滚，**违 0005 且违 B 类落格范式**】 | A 类重裁为 RejectedItem；罚俸不足额重裁为 B 类软通道（判决格保留＋执行格 failed）；无 C 类新增 | 成功 → fulfilled「颁布即终局」（terminal） | 硬失败回滚 |
| 17 | pacification | `:15669-15724` | 人物段：目标易主 ming 经 `_apply_person_changes`（#190 唯一核）＋原势力反噬削弱（ADR 0009 决定 3） | 缺 canonical target（`:15676`）/目标不存在（`:15682`）/原势力空或 ming 不可反噬（`:15685-15687`）/易主物化全拒（`:15724`）→ 全 `ValueError` 整批回滚【A-硬，**现码违 0005**】 | A 类重裁为 RejectedItem | 成功 → fulfilled「颁布即终局」（terminal） | 硬失败回滚 |
| 18 | referral | `:15751-15756` → `_apply_referral_verdict_effect` `:16555-16643` | initiative 段：下议 initiative（participants 仅机关/职司、end_turn、commitment_kind=until_stop） | 缺 responsible_bodies（`:16572-16578`）/participants 含个人名（`:16591-16597`）/缺 end_turn（`:16609-16615`）/initiative 槽被拒（`:16636-16642`）→ 一律 transition executing＋record failed close＋return False【软，不掀整批合 0005 底线；但前三项是 A 类脏载荷、与 B 类执行失败混记同一 failed 通道】 | 软通道「不带走整批」保留；迁移按 §0 细分：A 类 → RejectedItem 留痕（邸报按 provenance gate），B 类 → 执行格 failed | 成功 → executing（in_transit）；软拒 → executing＋failed 结案 | 软拒正常提交；硬失败回滚 |
| 19 | revoke_authority | `:15735-15739` → `_apply_revoke_authority_verdict_effect` `:16373-16407` | 授权段：`authority_changes` 收回槽（authority_id＋dossier_id） | 缺/非法 authority_id（`:16384-16391`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；收回槽逐项被拒 → `:16405-16407` 升格 raise `ValueError`【A-硬，违 0005——同 authorization，槽内拒收被升格整批回滚】 | A 类重裁：保持槽内逐项拒收即 RejectedItem，不得升格整批 | 成功 → fulfilled「颁布即终局」 | 硬失败回滚 |
| 20 | dismiss_assignment | `:15562-15580`（与 appointment 同分支，`_office_action=罢免`） | 人物段：罢免唯一核（alias 解析＋ming-guard，外藩/后宫/不在册不接，`:18175`） | 同 appointment：`_commit_office_action` False → `:15578` `ValueError` 整批回滚【A-硬，**现码违 0005**；其中 content=None 属 C 类】 | 同 appointment：A 类重裁 RejectedItem，C 类保留 fail-loud | 成功 → fulfilled「颁布即终局」（terminal，区别于 appointment 的 executing） | 硬失败回滚 |
| 21 | pay_order_override | `:15656-15663` → `_apply_pay_order_override_effect` `:16836-16857` → `materialize_pay_order_decree` 唯一入口 | fiscal_config 段：偿还序 override＋折发系数；键族唯一持久真源，案卷只是颁布门＋origin_ref（ADR 0055/0090） | payload.entries 非空列表校验（`:16846-16847`）→ `ValueError` 整批回滚【A-硬，**现码违 0005**】；materialize 内部整批先验后写 fail-loud，其中真实案卷资格＋颁布门复验【C 法源闸，硬合理】、entries 单项脏【A 类，现码随整批 fail-loud，违 0005「只拒该项」】；打回零写（§1） | A 类（entries 形体/单项脏）重裁为逐项 RejectedItem；C 类（颁布门/资格闸）保留 fail-loud；生效时点语义（下一结算起、当月不追溯，F1.3）不变 | 成功 → fulfilled「颁布即终局」（terminal，`:16856-16857` 注释：终局由尾部统一写） | 物化落结算尾段 atomic 内；硬失败回滚 |
| 22 | prohibit_covert_levy | **无分支**（elif 链不覆盖；db.py 全仓零引用） | **无 verdict 物化代码**。效果=案卷存在本身：`covert_levy.active_prohibition_dossier`（`covert_levy.py:14-25`）以 `status IN ('promulgated','closed')` 的该案卷为暗渠摊派稽核链的授权条件 | 仅公共框架 | 一致；**显式记：不受影响**（消费端读案卷状态，不读效果表） | 落尾部 → fulfilled「颁布即终局」（terminal）；status 到 promulgated 即被稽核链消费 | 无物化写 |

## 4. 无物化路径者汇总（显式记不受影响）

- **narrative 六值**（policy / strategy_selection / approve_reject / special_decree / secret_investigation / protection）：verdict 阶段只 transition `executing`，效果归 simulator/extractor 叙事轨，无物化代码。
- **immediate 一值**（secret_order）：成案时已物化，verdict 阶段只记 fulfilled。
- **payload 但无分支三值**（acting_appointment / secret_authorization / prohibit_covert_levy）：elif 分发器 `db.py:15562-15762` 均不覆盖，落尾部按 execution_surface 写 executing 或 fulfilled；实效分别在人事候选链（#529）、不归本片（#528）、案卷状态消费（#651）。迁移施工不得为它们发明物化路径。

## 5. 附注

- 本矩阵是 #1572 / ADR 0150 的**迁移证据快照**（HEAD `3ef603c68bb7b7276b4948a55ff0ecbfee63da71`），描述现状以便段适配器迁移逐项对齐失败语义；**运行时政策真源仍是 `dossier_action_policy`（`ming_sim/decree_vocabulary.py:64-101`）**，本文件不构成第二生产政策表，政策漂移以真源为准、以守门测试为闸。
- **失败语义法源更正**（三审修订）：ADR 0052 只规定颁布格/执行格两格语义，未授权 verdict 物化的软硬分流政策；分流真源 = ADR 0005（按「谁的错」分流：LLM 数据侧的错只拒该项留痕、不带走整批）＋ ADR 0008 决定 1（段适配器契约 `apply(items, ctx) → {applied, rejected}`，代码异常上抛绝不吞）。0008 决定 8 已由 0150 supersede，其余决定继续有效。
- **行为修正告示（已随 ADR 0150 决定 5 在卷）**：现码把大量 LLM 脏载荷（缺 holder/privilege/scope、缺目标、非法 authority_id、物化核逐项拒收等）升格为 `ValueError` 整批回滚（§3 标注「现码违 0005」各行）；迁移时将其重裁为 canonical RejectedItem 逐项拒收是**对齐 0005 的行为修正**——可观察行为会变：同批其它 verdict 不再被单案脏载荷带走回滚，邸报拒收提示按 provenance gate 出现。
- 现码已合 0005 的软通道（assignment/referral 逐项软拒、grant 欠资/不足额 failed close）保留「不带走整批」语义，迁移只做 A/B 细分留痕，不拉平、不回退成硬回滚。
