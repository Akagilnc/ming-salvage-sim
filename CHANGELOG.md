# 更新日志

本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

## [0.49.14.0] - 2026-08-30

### Fixed
- **#1692 关闭抽屉不再截获键盘焦点**：关闭态的朝堂、后宫和共享右侧抽屉现在使用浏览器原生 `inert` 退出键盘焦点序列与无障碍树；打开态交互、单一遮罩、ESC 关闭和常驻 DOM 生命周期保持不变。

## [0.49.12.0] - 2026-08-30

### Added
- **#691 七派六轴价值矩阵闭集校验与目标感知读接口**：价值矩阵加载时校验七派、六轴及 42 格整数范围；新增目标感知的撞轴读接口，可按泛化范围返回相关派系的带方向立场，并将目标命门结果限定为目标派。该接口尚未接入政令执行或玩家呈现。

## [0.49.11.0] - 2026-08-30

### Fixed
- **#1684 晚到召对回话不再盖住拟诏台**：玩家离开召对并打开拟诏台后，后台回话即使随后指定下一位大臣，也只更新大臣归属，不会把当前界面强行切回召对；盖玺与退朝入口保持可操作。

## [0.49.10.0] - 2026-08-30

### Fixed
- **#1681 召对回话完成后立即显示最新卷轴**：流式回话到达持久化完成点时立刻重读权威夜卷轴，尾随落账结束后再刷新一次；玩家不再需要重新打开召对，便能看到刚完成的问答与随后到达的递话。
- **#1503 显式拟旨拨饷回到协饷单轨**：召对中带“拟旨如下”前缀的太仓或国库军饷指令，会由既有动作分类器形成结构化协饷载荷；即使模型先标成拟旨，只要载荷明确为协饷，也会沿原有拨款案卷颁布、扣库与销欠，不再悬在叙事里。发内帑和普通拟旨保持原路径。
- **#1621 关宁军令可以正常落印**：票拟现在会使用同批军务盘面的真实军队编号，并在生成阶段拒绝省份编号冒充军队或缺少受命人的军令；玩家选择“严守宁锦”等急务后不再收到“假军”错误，案卷会准确落到关宁军。
- **#1627 待澄清拟旨不再卡死月末**：亲裁期允许落印已冻结的准驳，颁诏前留下的待澄清拟旨继续留待后续核定。

## [0.49.9.0] - 2026-08-29

### Fixed
- **#1504 专题查核按御限如实结案**：每月执行成色会直接累计到案卷实况，期限届满时按一月一份的期限配额对账；忠实办满御限可完成，打折或反噬留下缺口则失败，不再因事实线索数量与差务目标口径不同而必败。无期限查核在承办人提交核议或奉旨即核后，同样按最低一月配额确定性结案。

## [0.49.8.0] - 2026-08-29

### Fixed
- **#1626 长差密令无新增事实也能正常过月**：只要本月仍有合资格案卷，档房会逐案提交如实密奏，不再把“尚无新增可核事实”误作空列表而令批红结算中止；没有候选时才提交空列表，契约文档同步采用同一资格范围。

## [0.49.5.0] - 2026-08-29

### Fixed
- **#1625 批红空案头不再误触重复结算**：结算已在后台继续时，页面不会再把暂时清空的案头误报成可恢复状态，避免再次空提交后出现“批不了、月份却自走”的错觉；真正的崩溃恢复仍可从原入口续跑。

## [0.49.2.0] - 2026-08-29

### Fixed
- **#1620 批红不再被官职名卡死**：票拟中的“陕西巡抚”“户部”等非人物称谓不会再写入案卷人物名册；合法案卷可继续成案，人物名册校验仍保持严格。
- 批红落印后的结算错误会显示在现有恢复面板中，玩家可以看见失败原因并重试，不再只剩无声的“待批”状态。

## [0.49.1.1] - 2026-08-29

### Fixed
- **#1624 批红目标范围自动对齐**：票拟会按最终目标类型统一写出地域范围；省份目标使用单省，局势等非省份目标使用无地域，不再因模型给出矛盾组合而在落印时秒拒。

## [0.49.1.0] - 2026-08-29

### Fixed
- **#1628 重复授权不再卡死整月**：同一人在同一范围已有生效授权时，重复案卷单独记为失败并关闭；同批其他案卷继续执行，玩家可以正常完成结算。

## [0.49.0.0] - 2026-08-29

### Added
- **#662 灾害/兵灾驱动入池**：流民池补齐 0087 四入口中天灾与兵祸两入口——发生与具体量级由 internal extractor 依据既有盘面（region 天灾/人祸字段、military_pressure 定性档、活跃局势 issue）、`class_population_balances` 与 `population_unit` 软判；代码仅校验正整数、实时源余额、合法方向与来源并做守恒记账。无事实不申报（无灾不入），不建引擎侧自动触发（与 extractor 无双驱动）。邸报/召对因果回响走既有 effect_brief／classes_brief 定性特征面（P4 零数值）；restore 只读 DB 接续，与加派/摊派入口合流同一本账。
- **#1504 密令实进度轨**：密令确认后冻结结构化差务合同，每月按真实效果、来源案卷与执行判决累计实进度；恢复存档后继续沿同一本账推进。

### Changed
- 密令到期成败改由累计交付与目标缺口确定；承办人密奏只负责向玩家报告，不再反向改写实况或决定结案。
- 同目标调查会先合并进既有案件，再应用在办上限；月报推送与主动垂问读取同一份持久进展。

### Fixed
- 密令确认时若缺少结构化差务类型会响亮失败并保留可重试候选；合法确认、默认准行、豁免与流式入口均写入同一合同，抽取失败不再伪造合同或落成空壳密令。
- 实际交付只认与合同身份、来源案卷相符的效果；查询失败不再伪装成“没有进展”，法理佐证也只消费已证成的事实子集。

### Removed
- 删除旧的 `secret_order_closes` 大模型结案真源、`pending_review` 中间状态及恢复时反向补合同的兼容路径，不再保留双真源。

## [0.48.17.0] - 2026-08-29

### Fixed
- **#1585 召对连场与收夜分段**：连场换人补齐交接退侍、分隔与新臣入殿，收夜补齐末位告退、分隔与收束；交接人物仍留殿中，独立场景并行生成，失败时完整回滚。

## [0.48.16.0] - 2026-08-29

### Fixed
- **#1566 远人传召不再瞬时空结束**：向尚在外地的大臣发起普通召对时，传召会由 LLM 生成“旨意已发、人在途中”的场景并写入同源卷轴。同步与流式入口同走 `_finish_offsite_summon_scene`：闸内组装 BeatInputs、闸外 `run_beat_generator`、闸内短写同一 ledger 行；不把未入殿写成 entrance；生成期间 load/reset 对 open ticket 返回 409。无跨请求共用生成任务 / Future coalesce。
- **#1566 场外密令回归真实密令管线**：带正式密令前缀的消息不再被所在地传召闸提前截走，能够正常生成回话并持久化密令。

## [0.48.15.0] - 2026-08-29

### Fixed
- **#1376 密令确认闸收口**：玩家修改暂存密令时，新正文由同一次 LLM 结构化判词携带并原地更新同一候选；修改后可当场准行或过月默认准行，拒绝后过月不会复活。
- 删除对玩家自由散文的修改前缀、承办人和元数据机械解析；三个真实入口共用同一确认、落库与结算链。
- 收紧 3 入口 × 3 语义的贯穿矩阵：按前后密令编号集合和候选载荷断言外部结果，不再锁定自由文本、stub 调用形状或重复回归。

## [0.48.14.0] - 2026-08-29

### Fixed
- **#1366 军饷预算时序分离**：省级财政基座的预算分列中央军饷拟拨与京运补拟拨，不再预演未来分配或精确损耗；全军理论应发仍由军务报告呈现。
- 固定财政结算继续按稳定 `army_pay` 身份防止重复扣款；结算后的国库报告从既有流水与财政容器分别显示国库实拨、实际到达、途中损耗。

## [0.48.13.0] - 2026-08-28

### Fixed
- **#1503 拨饷诏颁布即落账销欠**：显式拟旨中的结构化协饷载荷现在沿既有颁布案卷单轨扣库并核销指定军队欠饷；拒颁、留中与恢复重放不会误扣或二扣。
- **#1591 成案拒绝原因如实回传**：协饷拟旨被账本拒绝时，真实拒因会沿现有 HTTP 成案入口返回玩家，不再被笼统错误遮蔽；结构化 account 输入层把太仓归一为国库。
- 协饷成案必须显式提供金额、账户、补饷用途、军队目标类型与目标编号；缺项或无效目标会响亮失败，不再从自由文本猜测，也不再由邸报 extractor 补写第二笔账。
- 协饷的余额不足与超欠继续沿既有扣款上限处理；普通旨意及非补饷军队拨款不会误销欠。

## [0.48.12.0] - 2026-08-28

### Fixed
- **#1589 批红选择不再错绑决策**：所有批红选择现在必须显式携带对应的 `decision_key`；缺键、重复键或未知键会在任何领域写入前整批拒绝，合法的急务与普通决策混排、纯普通决策及中断重试仍沿同一 keyed 路径继续。

## [0.48.8.4] - 2026-08-28

### Changed
- CLI 大臣回话现在原样呈现，不再删改模型写出的自由文本；工作区隔离和角色输入约束保持不变。

## [0.48.8.3] - 2026-08-28

### Fixed
- **#1590 票拟区域目标可直接依拟**：急务票拟现在只从当月盘面的合法区域目录选择目标，并在展示前拒绝不存在的区域 id；玩家不再因系统把“宁远”等地点误当省区而在依拟时遇到整批批红中断。

## [0.48.8.1] - 2026-08-28

### Fixed
- **#1565 召对问话不再误建局势**：动作分类现在区分殿上当场说明、比较、开列与退朝后继续办理的真实交办；普通问对保持零动作，不再泄漏为长期挂在 HUD 的局势条。

## [0.48.4.0] - 2026-08-28

### Fixed
- **#1561 召对开场回归 LLM 真源**：删除固定 opening fallback、死 `production_beat_generator` 与“随侍在侧”正文模板；opening 只走既有 LLM materials seam，standing-roster 仍保留 typed tags/person_names。
- 普通空 `scene` 不再进召对卷轴；空 opening 复用既有空垫位，不用代码补写玩家可感文本。

## [0.48.3.0] - 2026-08-28

### Fixed
- **#1505 省节点驻军归并**：地图省节点现在按 typed `station_region` 汇入驻军；同一地点的驻军不再被拆成省节点与边镇节点两处显示。

## [0.48.2.0] - 2026-08-28

### Fixed
- **#1382 史册恢复**：`last_report` 改为从持久化月档投影，不再依赖 session 瞬态缓存；新开进程或重新打开 SQLite 后，状态页与史册仍读取同一份已提交月报。

## [0.48.1.0] - 2026-08-28

### Fixed
- **#1583 同批连续任命**：荐人快照统一按本批结算开始时的盘面校验；同一人物可按稳定案卷序连续调任，批内前序任免不再把后序案卷误判为陈旧并卡死月末结算，批外真实陈旧快照仍拒绝。

## [0.48.0.0] - 2026-08-27

### Added
- **#658 廷议站台闭环**：下部议现在先形成唯一旨意案卷；大臣站台写入可恢复的结构化背书，无人站台则保留为冷场案卷并登记待解事项。
- 皇帝可在既有自由下旨入口明确强推冷场案卷，复用原案卷落御笔手敕，不会另造第二道旨意。

### Changed
- 月末颁布只消费真正可颁的案卷，冷场案卷保持待议；御笔目标、背书来源与处置所据案卷统一采用严格的结构化编号和单一解析权威。

### Fixed
- 处置曾站台者后，辜负信用只在处罚真实颁布且命中原站台人时记账；非法、无关或被驳回的处置不再误写信用。
- 补齐旧存档迁移、同案卷幂等、恢复链与 Web/CLI 字段传输，并删除对大模型自由文本的机械扫描测试。

## [0.47.0.0] - 2026-08-27

### Added
- **#672 任命并传召**：任命离京人物时可同时发起传召；任命与传召先暂存，颁布后才一并授官、启程，并沿既有在途状态抵京候见。

### Fixed
- 打回、撤回、结算失败与重试不再留下半套任命或重复行程；恢复存档后仍从同一本账继续。
- 任命顶替多人时，外层提交后的名册刷新会覆盖全部受影响人物，并只接受统一的数据形态。

## [0.46.0.0] - 2026-07-31

### Fixed
- **#1145 线上评审 Runner 退回纯调度**：GitHub 查询、有限等待、证据整理与 post-fix retrigger 改由独立 **Collector** 席完成；**Verify** 只裁决 finding 并执笔 opaque fixer packet，修复结果回同一判官。Runner 只运输 `cargoPointer` / typed receipt，不再解释 PR comments、findings、threads、bot 完成度或 `committed`/`alreadySatisfied`。
- 删除宿主侧 `onlineReviewSideEffects` 双拥有残留与 host-typed plan cargo；durable 进度/回执改由 worker 自有 `.orchestrator-online-review-durable` + `bin.mjs`，崩溃复飞不重烧已完成等待。
- 补齐 Collector 路由/灵魂/契约与贯穿 production shared-tail 的边界 tracer（`online-review-runner-boundary-1145`）。

## [0.45.0.0] - 2026-07-26

### Added
- **#571 旨意案卷底座**：每条准旨与密令现在都有可恢复、可寻址的独立案卷，记录结构化目标、来源、四态生命周期，以及颁布与执行判决历史。

### Changed
- 月末结算改由案卷驱动旨意效果与溯源；结构化任免、拨款、授权等效果只在合法颁布后物化，叙事旨意继续经推演产生效果。
- 案卷采用确定性的「准旨→已颁→执行中→结案」生命周期；打回、留中、强颁与收回保留同一案卷和追加式判决历史。

### Fixed
- 密令异常终止、撤回本轮、默认同意、CLI 编辑与结算恢复现在同步维护案卷，避免幽灵执行、重复物化和结构化载荷丢失。
- 合并最新动作聚类管线后，拟旨仍保留 #515 的并行分类与回话正文，同时补齐 #571 案卷字段，后续改稿不会以空默认值覆盖原结构语义。

## [0.43.2.1] - 2026-07-26

### Fixed
- **#1141 coder-fix cargo ABI**：恢复 `coder_fix.md` 的 fixer 席运行时输入与 hand-in 契约（`fixPacketBody` / `escalationAnswer` / relay baton、`committed`+`commitsAdded` 按本 worker run 如实上报，以及 completed/refused/escalate 三例），避免修完却报 no-op。

## [0.43.2.0] - 2026-07-25

### Fixed
- **#1137 判官 session 恢复**：S6 判官续跑收到宿主返回的 session-not-found 失败回执时，按既有连续性丢失路径携既判史 fresh 重开；失败派发残留的 runner session id 不再覆盖最后一个真实判官 session。

## [0.43.1.0] - 2026-07-25

### Fixed
- **#1135 S6 判官模型迁移续跑**：旧判官 session 与当前 verify 席模型不兼容时，先持久化 `session_continuity_lost`，再携既判史与 owner answer 从同一 S6 边界 fresh 重开；原 scene、worktree 与已完成步骤保持不变。
- continuity-loss 台账写入失败时改为 `record_persist_failed` 响亮终止，且不会先派出新的 S6 判官；写入后若进程中断，复飞也不会重复追加同一条 loss 记录。

## [0.43.0.0] - 2026-07-25

### Added
- **#513 / #515 皇帝动作语法首批落地**：自由文本旨意改走统一动作聚类判词与列表形传输契约，由共享主意图选择后经既有确认闸门暂存、物化与撤回；自然语言新建密令在无旧令和已有旧令两种场景都按结构化判词正确落案。

### Changed
- **#527 召对快捷入口收敛**：移除替皇帝说话的五个询问 chips，只保留「拟旨」「下密令」两个意图前缀；Web 与 CLI 共用同一分类、字段校验和主意图选择规则。
- 动作字段统一由只读 `FieldSpec` 目录校验与归一，空白枚举按缺席处理，非空非法枚举继续响亮拒收。

### Fixed
- 分类器判为新建密令时不再被已有 active 密令的抽取结果误路由成更新，也不再依赖自由散文关键词或正则触发机械后果。
- 清除旧 registry 索引、重复草稿扫描、测试注入 helper 与前端 modal 测试夹具中的死路径，保留真实入口的 P5 并行、撤回与 chips 行为回归。

## [0.42.1.0] - 2026-07-25

### Changed
- 判官 Action 统一拥有 finding 状态写入、合法翻态与同 session 自纠；Runner 只运输 typed verdict 与判官原写的 fix packet。

### Fixed
- **#1128 resident judge 续跑**：明确 session 丢失时记录 `session_continuity_lost`，携既判史从原 S6 边界 fresh 重开；网络、鉴权与协议错误仍响亮失败。
- **#924 coder 续跑回归**：coder session 明确失效时继续保留 worktree 进度并 fresh-run，不因判官恢复改造误杀切片。

### Removed
- 删除 Runner 内 findings-store 投影、disposition/open-count 判路与 residual 法庭，以及依赖这些旧职责的陈旧测试。

## [0.42.0.0] - 2026-07-22

### Added
- **#1080–#1086 驻庭判官枢纽**：切片开工即开庭（#1081）；coder 施工前走计划相闭环（#1082）；fixer 拍一律经驻庭判官 hub（#1083）；非 continue 判词与保险丝挂 hub（#1084）；三环驻庭判官枢纽（#1085）；builder↔judge 每拍 ledger 与进度广播（#1086）。
- **#1080 open-court / 续跑硬化**：S1 开庭 escalate 可 resume；pure-judge receive 后外闸 panel legs；`forbidFreshRetry` 家族边；panel legs 在 judge resume 下保留 retry 预算；双字段 executable progress 清 quota park；S1 escalate 回执 stamp `modelSlug`。

### Changed
- 判官 station / open-court prompt 与 coder/fixer soul 对齐驻庭 hub 与计划相；`verifyCmr` 与 runner 路由收敛到单一 hub 边体。
- #598 SOE 单测预算抬到 heavy 档 120s（#1102 家族 stopgap）。

### Fixed
- 删除重复 non-continue 测试税（#1084）；判官 packet L1–L4 删死守卫、单旋转通道（#1086）。

## [0.41.0.0] - 2026-07-21

### Added
- **#498 召对夜与故事账本**：召见大臣不再是一问一答互不相干，而是汇入同一场「召对夜」——一条连续对话流 + 一本按时间序排列的故事账本，开场、传召、退下、收夜都留痕可查、可回看。
- **#500 在场推导**：谁此刻在殿上由传召、侍立、告退、在途等进出账实时推出；御前私语（如近侍递话）与殿上公开对话分层存放，旁人听不去不该听的话。
- **#502 一场问出多道旨意**：同一场召对里可以同时酝酿好几道旨意，各自随对话独立成稿；口头准驳能明确指向其中一道，含糊表态不会被默认放行。
- **#503 开场与收夜按情境生成**：入殿的开场白、退朝的收尾描写按人物、召法、时辰地点自然生长，不再套固定模板。
- **#507 连场召对**：一场召对可以接连传见多人，侍立在殿的大臣能在他人问对时插话，此起彼伏的「乾清宫一夜」由此成型。
- **#505 断线续夜**：召对夜中途断线或崩溃后重开，会接着最后一条已持久化的对话轮往下聊；生成到一半的回话作废并给重试，已经成立的账不回滚。
- **#506 撤回本轮**：可对刚结束的一轮召对整体反悔——该轮新记的账、暂存和已落地效果一并撤销；一旦收夜或翻篇，撤回的窗口就关上了。
- **#501 召对当场落账**：召对里的举荐、站台等紧要举动随对话即时记进故事账；万一漏记，系统会补录并弹出看得见的错误提示，不会悄悄漏掉。
- **#499 回话与查证并行**：大臣的回话生成、近侍读心解读等多个环节同时进行，减少玩家等待。

## [0.40.0.0] - 2026-07-21

### Added
- **#1073–#1075 model-data 外置配置**：你现在可以直接改 `orchestrator/config/model-data.json`（或设 `ORCHESTRATOR_MODEL_DATA_PATH`）增减 coder 名册与 model registry 数据行，无需为名单开 PR；每次派工/换棒现读文件（无进程内缓存），缺文件或坏形状 fail-closed。

### Changed
- **#1074 coder roster** 与 **#1075 model registry** 消费者统一从 model-data 加载数据行；provider 工厂与 quota pool 表仍留在代码（ADR 0146）。
- 文档 `docs/CODER_ROSTER.md` 改为指向外置配置真源，不再维护硬编码副本。

## [0.39.0.0] - 2026-07-20

### Added
- **#1067 / #1066 判官分诊环**：红 wave 转入判官分诊，判词契约新增 toolchain 终态，唯一绿回执收敛；`wave_verify_judge` 薄 promptFile 落地并入 family prompt 构造期清册。
- **#1063 admission GraphQL 兜底**：gh reads 在 REST 失败时新增 GraphQL fallback 通道，并丰富 gh HTTP 状态使 5xx 兜底真正触发。
- **#1062 admission 重试预算复用**：gh reads 复用既有 dispatchRetry 预算 + 15s backoff，不再另起一套重试节奏。

### Changed
- **#1069 判官 fix packet 五条落地**：消冗、去重言、补不收敛负案、四面零-spin 钉；`runFamily` 多波 spine tracer 全经判官 typed verdict。
- **#1068 verify 教学表**：改判词枚举态（消三态 vs 四行陈旧），toolchain 补第四终态（owner 亲批 follow-up 草案）；`wave_verify_judge` 对齐 `.cmr-focus.md`，删收敛法理复述。

### Fixed
- **#1071 cmr-worker.heavy 假红**：`testTimeout` 改为 load-tolerant，不再被负载拖垮判定为红。
- **#1076 稀疏判官 cargo 崩溃 + 失败原因透传**：`findingIdentityKey` 优先取 finding 自带 identityKey（ADR 0131，拓扑不再从 cargo 散文倒推身份），字段缺失时抛可诊断错误而非裸 TypeError（此崩溃曾致 #1069 六次 S5 进程暴毙）；失败终态的 `gateSummary` 持久化并透传进 `failureCause`，dispatch→infra_failure 黑洞消失。
- **#1058 名分守卫遗漏 caller 接缝**：显式名分（office_type ∈ PERSON_TITLE_KINDS）此前只在 DB 写侧受守卫，建 Character 与内存 re-infer 两处 caller 接缝仍会被 office 文本反推覆盖（如「诸生」撞词干误判为「生员」）；收敛到 `resolve_office_type_preserving_title` 单一入口，DB 与内存不再分岔。另修 3 处 seam 遗漏 `llm_config` 回落，避免在内存侧静默跳过 LLM 推断分支。

## [0.38.0.0] - 2026-07-19

### Changed
- 玩家在召对、邸报、旁白、读心与见闻中只会收到人物能力、忠诚、操守等定性判断；银两、兵额、年月和火炮等朝廷应报实数仍照常呈现。
- 月末结算、历史记录与命令行摘要统一使用玩家可见的叙事投影，避免浏览器或界面旁路暴露引擎账本。

### Fixed
- 密令创建与更新只释放本次涉及接令者的消息，非密令通道不再预先获得密文。
- 撤销密令时由外键级联清理对应简报，同时保留其他密令和既有历史记录。
- 人物事件与停止条件在进入叙事模型前统一投影，避免角色属性分从结构化上下文回流到散文。

### Removed
- 删除历史页账目标签、邸报详明弹窗、结算 extraction 负载及其前端组件。
- 删除对 LLM 自由散文做关键词擦洗的旧机制与盯文测试，改由结构化输入侧保证玩家只见定性人物描述。

## [0.37.0.0] - 2026-07-19

### Added
- **#969 编排器测试分层**：新增带类型检查的 `test:fast` 自检入口；纯逻辑测试可在快速池运行，真实进程、沙箱与 Git 仓测试仍由 full 闸完整覆盖。
- 新增机械税守卫，新测试若在 fast 池启动真实进程会直接失败，避免快速线随维护静默变慢。

### Changed
- 将编排器的进程、沙箱、真实后端、worker 与端到端测试迁入结构化 heavy 池，并抽取共享夹具，保留 full 契约覆盖的同时减少 coder/fixer 重复等待。
- coder 与 fixer 的交卷自检统一使用 fast；wave verify、final verify、CI 与 ship 继续使用 full。

### Fixed
- 修复 Grok 大提示通过管道重开 `/dev/stdin` 时失败的问题：提示改为权限受限的临时文件，并在正常退出、鉴权失败及 HUP/INT/TERM 中清理且保留原信号语义。
- 修复 Grok route-smoke 的 stdin 形状、探针环境与进程回收假红，并放宽真实 Git 端到端测试的合理超时预算。

### Removed
- 删除 dispatch、structured-output、ledger、scaffold smoke、real-backend 与废弃 focus 机制的重复测试钉；幸存测试继续覆盖同一外部契约。

## [0.36.0.0] - 2026-07-19

### Added
- **#484 / #488 / #494 人物底色补全**：新增郭允厚、李之藻、张缙彦、李从心、汤若望等史实人物，并为朝臣补齐党派认同、既往罪责、个人档料与派系立场；同一问题会因人而得到不同判断。
- **#491 近侍察言观色**：内廷近侍可依据自身所知，对大臣言外之意作定性回奏；结果随召对留档，撤销回合时一并回退。
- **#492 近臣查访**：可向近臣询问官缺、欠饷、军情等事项；回奏按其职分与实际见闻生成并持久留档。
- **#493 大臣荐人**：大臣可从本派网络或亲历见闻中具名推荐在职、候铨或起复人选；皇帝确认任用后保留举荐人和依据。

### Changed
- **#487 / #489 召对改为逐人视角**：每位大臣只依据本职、亲历事件、公开消息和获准密事作答；未参与、被排除或尚未明发的内容不再进入其上下文。
- 人物能力、忠诚、党派认同、城防、军备、建筑与势力等抽象量表统一改为定性表达，同时保留银两、兵额、月份、火炮等可核实数量。
- **#490 见闻与历史按来源延续**：邸报、章节记忆、结算叙事和回合恢复保留公开/私密来源边界；大臣回看旧事时仍只看到自己当时可知的部分。

### Fixed
- **#883 / #976 密旨隔离**：口谕在判定为密旨前先暂存，成旨后只进入承办人私密简报；以消息级来源追踪跨回合口谕、更新与确认，防止密旨正文及其改写泄入其他大臣、邸报或章节记忆。
- 修复召对、工具查询、流式 Web/CLI、历史档案和回合撤销中的越权读取与裸数值泄露；公开信息仍可正常传播，明确披露后的密旨才转为公共事件。

## [0.35.1.0] — 2026-07-19

### Fixed
- **#1019 跨 launcher 复飞**：答闸后的 park 子片在 session 已死/缺 resume 时降级为 fresh re-dispatch（答案进新 worker 上下文），不再终态回放旧 park/failed；failed 子片新 launcher 可重派且失败史留台账；mixed-wave 仍 durable 写 `child_decision_parked` 供后续答闸；真 infra 再派仍响亮失败。
- **#964 live probe 假红**：docker 路径不再把空 `HOME` 传给宿主机 CLI（修 sock 连不上）；选 target 前要求 `docker info` 通，无 daemon 则 soft-skip。

### Changed
- 废除 `child_answer_without_parked_state` fail-closed；改 `child_answer_fresh_redispatch` 审计路径；#970/#604 相关测试与契约注释对齐 #1019。

## [0.35.0.0] — 2026-07-18

### Added
- **#1009 编排器维护战役 III（八票并发）**：双舰实战修正合波。
- **#1002** 在线评审环 fixer 席接 `advanceCoder` 粘性通道（只改修理席）。
- **#1005 / ADR 0141** 腿散文合法：删 content-shape 拒收；transport 在场即开庭。
- **#1006** family fan-out 前 baseline 健康闸（容器 full；红不扇出 + 台账）。
- **#1007** 主动进度播报：`progress.jsonl` + 票号 stage/判词/处置 + `npm run status` + fail-open notify。
- **#1010** Sandcastle 取消缝：abort/idle 杀容器内 shell + 清临时文件（本地 pin 0.12.0 patch）。
- **#1012** fix-findings 挂载前 ensure 正规文件；EISDIR 不机械六连。
- **#1014** provision/ensure 写入 `.ledger-*/` 与 `.sandcastle/` 到 `.git/info/exclude`。
- **#1016** botPolling GraphQL reviewThreads 查询收尾括号修正（4 外层）。
- **ADR 0140 落地**：`npm run test:fast` vs full `npm test`；coder/fixer 自检走 fast。

### Fixed
- Baseline 红出口 dual-write progress terminal（#1007×#1006）。
- 生产 dist 可加载 cancel patch（TS emit，非仅 src .mjs）。
- GraphQL errors 仍 fail-closed（#1016 负向钉）。

### Changed
- vitest 机械 heavy 池（path + harness nature）；义务面对齐 souls / coder_fix / README。


## [0.34.0.0] — 2026-07-18

### Added
- **#985 pytest 套件瘦身（family/985）**：session 级只读 `read_game` fixture（真实 seed + SQLite `query_only`），纯读用例不再逐测重建整库。
- **#998 拒收矩阵共享 section helper**：`tests/section_rejection_helpers.py` 合并 ~10+ 文件重复 setup。
- **#995/#996 轻量盘面迁移账**：`tests/game_fixture_retained_inventory.tsv` + 选用约定 `tests/README.md`。

### Fixed
- **#994 settle_channel 全量离群**：隔离 chapter LLM / settle channel 共享态，根因后修而非标 slow。
- **#997 scout_report_label 固定税**：缩扫描范围至消费者，契约面保留。

### Changed
- 写库路径仍走 function-scope `game`（真实 `GameDB → seed_static_data → load_state`），不 mock 被测系统。

## [0.33.0.0] — 2026-07-17

### Added
- **#942 公共结果 ABI 切齐**：`completed` / `parked` / `failed` 与 OS exit 0/2/1 原子切换；失败必带 cause。
- **#952 typed `suppress` disposition**：内部终态 `suppressed`；写入点校验合法状态跳转；terminal-only continue 关庭。
- **#961 family Integrated Correctness 增量 checkpoint**（ADR 0139）：波次 verify 绿后全量 IC 并行子 coding；`lastCorrectnessConvergedHead` 庭记忆；Runner 不准入。
- **#964 grok 运行中 auth 失效 → typed failure**：禁止 headless device-auth 挂起；fail-fast 探针。
- **#977 拆除 pattern-brief 旁路信道**（ADR 0137）。
- **#978 判词即包**（ADR 0138）：`fixPacketBody` 唯一送修正文路径；缺 body 响亮失败。
- **#979 fixer 同链 resume**：同 findings 链复用 fixer session；`cmr_passed` 截断链界。
- **#981 grok-cap 忽略 AppleDouble / `.DS_Store`**：侧车不炸会话 integrity。

### Fixed
- Family CMR completeness：suppress-only 收敛、residual 不合成 fixPacketBody、family close 穿真实 store `from`。
- Family CMR correctness：IC hard-fail / quota-park 前 drain 本波 allSettled siblings，禁止假 `skipped`。
- #978/#952/#961/#964/#979/#981 切片 CR 多轮与 family base 插队合入。

### Changed
- Judge/fixer souls 对齐 ADR 0138 与 #979 resume 证词；merge main 时保留 family 侧 ADR 正文。

## [0.32.0.0] — 2026-07-17

### Added
- **#941 Landing Action**：`docRelease` 原子改名为 `landing`，承接 docs/push → readiness → merge → live MERGED → close/cleanup；删除 host auto-merge / familyAutoMerge 法庭。
- **#959 grok 会话 atomic temp+swap**：capture 同卷 staging、完整性校验、rename 替换；失败保留旧会话；并发同 slug 不混写。
- **#966 判官 session 台账派生**：`cmr_reviewed` ledger 为 sole truth；host session 缺失时 fresh + priorJudgeVerdicts。
- **#970 家族/子级 escalation 分型**：仅 decision park + sessionId 才注入 runChild；响亮 `child_answer_without_parked_state`。
- **#962 noSandbox `GIT_CONFIG_GLOBAL` 隔离**、**#957 Codex Sandcastle 原生 capture/resume**、**#938 wave 保留 sibling + 信任 merger**、**#940 typed-judge-only** online review。

### Changed
- **Online review dual-owner（K1）**：worker 应执行 reply/resolve/deferred；host `onlineReviewSideEffects` 作 fail-safe 直至 worker 真正拥有效果。
- **Landing process-root**：共享 `dispatchFamilyWorkerOrAbort`（mechanical retry + monitor + 429 rethrow）；resume 路径进 family quota wall。
- **Landing decision-park 账本统一**：fresh/resume 均 `recordFamilyEscalated(decision)`，可被 `familyEscalationState` 重入。

### Fixed
- Family CR R1–R3：landing park 双账本、poll/fetch 连续失败 decision_gate、hollow AC 降级、README 与 side-effect 真值对齐。
- Correctness K2：ledger sessionId 在 host 不存在时不再强制 resume。


## [0.31.0.0] — 2026-07-17

### Added
- **#934 family W1（#936 / #937 / #939）**：Runner 控制面切片合入 family base——ignition 准入先于 worksite 与 durable re-entry；统一 worker dispatch 终态并删除静默判刑；family verify 区分 operational error 与合法空命令。

### Changed
- **admission / Coder-Rec / tight**：`admitRouteFromEnv` 仅 preset；relay 改 route 后 `admitRelayBaton` 再过 tight；sticky re-hold 同 court。
- **receipt maxRetries**：与 #955 对齐，按 `resumeCapableForSlug` 布尔门，非 provider 字符串硬表。
- **family durable park/relay**：family 只写 family-ledger；禁用旁路 steps.jsonl 半双庭。

### Fixed
- **CR R1–R8 收口**：ledger shape / dual phrase / smoke dropped union / public silence proof / capacity relay persist 分类 / DRY adoption+baton / hashPrompt warn / branchExists fail-closed 等。
- **与 main 合流**：#955 grok resume 与 #965/#55a5cbff soul 哨兵删除；测试接缝改 Coder-Rec 而非 env 单槽。

## [0.30.1.1] — 2026-07-16

### Changed
- **#935 Runner 控制面 ADR**：以 #934 ID-001、ID-006、ID-016 为唯一契约，并前向取代 ADR 0131 / closed #929 中冲突的旧条款。

## [0.30.1.0] — 2026-07-16

### Added
- **#945 worker auth path-policy 一缝**：`provisionWorkerAuth` 共享核；`WorkerAuthPathPolicy` 注入 family（per-run mkdtemp，无 codex 不挂）与 slice（稳定 `auth-N` always-mount config+AGENTS）。

### Changed
- **`AuthPaths` 收缩**为 slice 稳定 codex 路径（`hostCodexAuthDir` + `srcCodexAuth`）；materialize 全归 `provisionWorkerAuth`。
- **`provisionFamilyWorkerAuth` / `mountAuth`** 改为薄包装，不再双份内联 credential 步骤。

### Fixed
- path-policy 边界测：always-mount AGENTS 断言；family 失败 mkdtemp 无泄漏。

## [0.30.0.0] — 2026-07-16

### Added
- **#916 路线表出码入配**：route preset 迁入 `orchestrator/config/route-presets.json`；换模型改配置即可，不再改代码表。
- **`gpt-5.6-sol-low` registry 词条**（`effort: low`），供 utility 席位使用。
- **`claude-tight` 厂阵**：coder/coderFix=`grok-4.5`；verify/cmr*=`gpt-5.6-sol`@medium；ship/merger/fixer/cleanup/docRelease=`sol-low`；cmrReview=sol+grok+agy(optional)。

### Changed
- **推理强度权威只在路线/registry**：删除 `effortForLiveOfficer` 与 `agentForSlug` 的 call-site effort 覆盖；live 与票面一致。
- **`billingPoolForModelRef`**：roster 未命中时按 registry provider 回落（`sol-low`/`sol-high` → `codex-5h`，不再误绑 SuperGrok）。

### Fixed
- **#913 family auth mount ×3 DRY**：`provisionFamilyWorkerAuth` 单缝；merger/cmr/ship 合流；`providerAuthFromCore` 统一投影。

## [0.29.0.0] — 2026-07-16

### Added
- **编排器 #919 修复环判官化**：持久 verify 判官三态（converged/continue/escalate）统一单切 S3/S6 与 family CMR 关环；毙单四理由 + 活单送修。
- **#924/#926/#927**：coder 持久会话 + 官方 typed 收据；advanceCoder 执行/留守同构（`executeAdvanceCoderSuggestion`）；coder 驳回信封盲路由回判官。
- **#922/#929**：终态实名与非零退出码映射；终局必落盘。
- **#930**：family 双闸共用判官机；open-count 第二关环删除。
- **全工位 T2 收据**：judge/coder/ship/merger/onlineReview 官方 thin envelope。

### Changed
- 完成定义统一为单迭代 + 干净退出 + typed 信封；`completionSignal` 退役。
- reviewer 模型槽并入 verify（#923）；池隔离拆除（#920）。
- residual 非 judge 纸 fail-loud unusable，禁止 open-count 铸 continue。

### Fixed
- empty continue 空转（family + 单切）fail-loud。
- family refuse keys 与单切同构；ship dual decision-gate 拆除。


## [0.28.1.0] — 2026-07-15

### Fixed
- **编排器 #915 agy 烟测空 `--print` 必死**：`agyPrintInvocation` 把 prompt 作为 `--print` 实参送达（agy 1.1.2 拒空 print、不吃 stdin），bare-ping 与 AgentProvider 共用同一 seam。
- 删除假 stdin 双通道与 `{ args }` 残袋；interactive 仍走 `--prompt-interactive`，与 print 分缝。

## [0.28.0.0] — 2026-07-15

### Added
- **编排器 #899 交通信号原生回炉**：reviewer open-count 与 decision gate 走 Sandcastle `Output.object` + `maxRetries: 2`；同 session 结构化重交归底层。
- 生产边界四案矩阵（首次合格 / bad→good / 耗尽 / 不可恢复）：single-slice、family CMR/coder-fix、ship decision-gate。
- `receiptRecovery` 统一 typed 收据契约；SOE 经 cause 链识别，兼容 Effect FiberFailure 包装后仍走 #598。

### Changed
- coder/ship 普通 cargo 保持 opaque：不绑 SO 形状修复；命运只认 exit + typed 信号。
- 不可用 open-count 不再合成 `findingsCount: 0` 或假 coder 席；按固定拓扑递 raw 给 fixer 路径。
- review-loop sparse cargo 完成 Action，不把 cargo 形态当 #598 形状 lane。

### Fixed
- SO 耗尽后 reviewer 同位机械重调，不发明 S5 fixer 派发。
- 并发环境下 StructuredOutputError 被 FiberFailure/ExecError 包装时，#598 仍正确归类。

## [0.27.0.0] — 2026-07-15

### Added
- **编排器 #905 路由正名**：`agy` 恢复为真 agy CLI；`grok-4.5` 一律走 SuperGrok；opencode 从 registry / 路由 / 镜像 / auth 全线拆除。
- **编排器 #906 Coder-Rec**：issue body 经 remark/GFM 剥净再解析；坏标记或未注册模型 admission fail-closed，禁止静默回落默认 coder。
- **编排器 #909 family 额度韧性**：family 沙箱与单切片共用 quota/idle/429 wrap；`QuotaWait` 不 leg-kill；park/relay 与 baton 真接线。
- **编排器 #911 soul 战役**：中文角色 soul 定稿落盘；容器 home 环境 dual-mount（Claude `CLAUDE.md` + Codex `AGENTS.md`）；skills 进 `~/.agents/skills` 并兼容 symlink。

### Fixed
- agy 多行 stdout 在 Sandcastle last-wins 下保留全文；跨 maxIter 累加器在每次 print/interactive 入口重置。
- agy headless `--print ''` + stdin 与 interactive `--prompt-interactive` 分缝；`--print-timeout` 使用 Go duration（`15m`）。
- family open-shipped / S3 cmrPass 单槽 / wall-hit knownLive / endgame wall 槽映射等 correctness 接线修复。
- grok bare-ping 与 worker 一致走 stdin prompt。

### Changed
- 去掉为过审而加的 live-pool 完备扩表与 prompt 真空回灌；#902 额度完备性缓交。
- 删除 soul/prompt 散文 inventory 类测试，只保留 dual-mount 等行为钉。

## [0.26.0.0] — 2026-07-13

### Added / Changed
- **#873 编排器生存版（核心重构）**：拆 runner 收账/git-truthing/读字法庭，切换为三通道路由（exit code / 自报 findings 数 / 决策门，ADR 0131）。
- **机械补丁**：head 未动短路 (#878)、腿瞬断重试 (#879)、交卷指针 (#880)、resume barrier (#881)。
- **S8 外围**：`externalCall` 仅装钟（无重试中台），重试归 `legTransientRetry`；route smoke 简化为裸 ping (#884)。
- 旧 tool-smoke 证据 helper 删除；bare-ping 唯一点火路径。

### Removed
- verifyCmr accounting courts、git-truthing conviction、no-progress 等 runner 内容法庭与零引用孤儿 helper。



## [0.25.0.0] - 2026-07-05

### 新增
- **省级财政一手史料 seed 扩展**：中原、京师、江南、边镇与南方/西南省份的田赋、起运、辽饷与宗禄种子补入《万历会计录》来源锚点，缺源省份保留 provisional 标记而不伪造一手数。
- **军饷漏斗守恒**：辽东、东江等纯军饷漏斗现在可同时保留史料总额与新增 pay-source 军队分摊，省级军饷欠容器会把 standalone 漏斗与逐军队欠饷一起校验。

### 变更
- **三饷与起运重算更严格**：历史饷率通道会把数字字符串和脏目标值重写为规范数值，并在剿饷/练饷回退时按当前事件状态重算起运定额。
- **财政文档同步一手核口径**：省级财政 substrate 文档更新陕西、南直隶、山东缺卷、辽东军饷与宗禄映射等口径说明。

### 修复
- **pay-source reconcile 不再吞掉史料军饷额**：有一手 `现额银两_年` 或纯军饷漏斗 posture 的地区，重建军队 pay-source 行时不会把原始军饷 Due 与 opening arrears 覆盖成逐军队合计。
- **容器守恒错误信息补足 standalone 分量**：省级/中央军饷双容器校验现在报告 `Σstandalone`，便于定位史料漏斗与逐军队欠饷之间的差额。

### 测试
- 新增财政 seed golden、宗禄省份映射、三饷规范化、起运回退、辽东/东江军饷漏斗与 pay-source 守恒覆盖；ship 验证为 `2134 passed, 13 skipped`（root pytest），财政 focused suite `225 passed`。

## [0.24.0.0] - 2026-07-04

### 新增
- **财政 substrate hub cutover**：中央财政固定流改经 `起运`、`盐税`、`商税`、`太仓亏空`、`边饷hub` 与 `中央军饷` hub 结算，国库入账、边镇/中央军饷出账与太仓/京运损耗可审计。
- **中央亏空审计容器**：新增 `C_太仓挪用`、`C_太仓纯亏空`、`C_京运克扣` 与 `C_京运运损`，并接入中央税源、人为损耗率和运输损耗率配置校验。
- **固定财政错误包覆盖**：hub cutover、无诏推进与固定财政路径补齐失败中止/error-pack 测试，缺失损耗率、人为挪用键或畸形固定流会响亮失败。

### 变更
- **预算与流水展示改用 cutover 名称**：web 预算 payload、钱粮摘要、提示词与文档同步展示 `起运/盐税/商税/太仓亏空/边饷hub/中央军饷`，并隐藏程序自动记账的 hub 固定流噪音。
- **中央军饷守恒校验收紧**：中央军饷、边饷 hub、起运净额与出账扣减统一走 substrate hub 守恒口径，CMR 多轮修正补齐负数、别名和缺项拒收边界。

### 修复
- **同名固定流不再被误跳过**：substrate hub 内部预算线带 `internal=substrate_hub` 标记，跳过逻辑不再按显示名误跳过玩家/LLM 创建的同名固定财政项。
- **损耗率配置不再静默归零**：太仓与京运 human loss-rate 键缺失时进入固定财政中止错误包，而不是默认当作 0 继续结算。
- **评审发现收口**：补齐无诏推进固定财政 abort 回归，移除 `record_issue_economy_move` 已废弃参数，并将中央损耗率 key 去重抽象记录为后续 issue #575。

### 测试
- 新增 substrate hub cutover、中央损耗、预算展示、固定财政 abort、同名固定流隔离与缺失配置 fail-loud 覆盖；PR 收尾验证为 `2101 passed, 13 skipped`（root pytest），fiscal bridge `146 passed`，财政/预算/事务 focused suite `175 passed`，Codex/Claude pre-landing 与 adversarial review 无阻塞发现。

## [0.23.0.0] - 2026-07-02

### 新增
- **worker outcome sidecar 协议**：coder、reviewer、CMR、merger 与 ship worker 现在会优先通过 runner 注入的 `.orchestrator-outcome.json` 交换结构化结果，stdout tag 只作为旧 runner 兼容层保留。
- **sidecar 落地文件隔离**：runner 会为 worker outcome 建立 state-dir landing file，并把 sandbox 内的 outcome 文件加入 git exclude，避免机器协议文件污染 slice diff。

### 变更
- **真实 backend 优先读机器协议**：当 outcome sidecar 挂载时，fresh reviewer 与 resume worker 不再让 Sandcastle typed output 先解析兼容 tag，避免有效 sidecar 被缺失或损坏的 stdout tag 短路。
- **worker runtime 文件排除命名更通用**：family backend 的 ship focus、CMR route、merger outcome 与 family ship outcome git-exclude helper 改为通用 optional runtime file 语义。

### 修复
- **落地提交恢复更保守**：只在 terminal S8(error) 明确来自 legacy `<coder>` tag 缺失时，才把已推进 HEAD 的 S2/S5 视作已落地提交继续跑后续步骤；其它 contract failure 仍保持 error。
- **恢复 ledger 保留合成输出**：protocol-failed landed commit 恢复时，会把合成的 coder output 写回继续使用的 prior ledger，避免后续 resume 缺少 S2/S5 输出真源。

### 测试
- 新增 worker outcome sidecar dispatch、malformed sidecar fail-closed、fresh/resume reviewer sidecar bypass、S2/S5 landed protocol recovery 与非恢复负例覆盖；ship 验证为 orchestrator typecheck 通过，Vitest `65 passed, 1 skipped`（`1097 passed, 1 skipped`），Codex review 通过。

## [0.22.0.0] - 2026-07-02

### 新增
- **三饷历史饷率通道**：崇祯四年辽饷升额、崇祯十年剿饷开征、崇祯十二年练饷开征与崇祯十三年剿饷议停现在会作为财政历史事件进入结算，省级 `settle.p` 当月置到目标饷率而不是逐月叠加。
- **加饷奏报估算**：月末推演 payload 新增 `fiscal_levy_memorial_estimates`，钱粮章可按事件账给出国总加征万两区间、军费覆盖口径与民间承压叙事。

### 变更
- **结算顺序补齐饷率前置**：`pre_settle` 与退朝无诏推进都会先落历史饷率，再跑固定财政 tick，确保同月省级财政读到新的三饷应征与起运定额。
- **事件结局标签更严格**：财政饷率事件声明封闭的 `terminal_reason_labels` 与默认结局，读取和玩家选择都会归一到白名单标签，非法配置或脏结局会响亮中止。
- **省级饷率基线可恢复**：饷率通道会持久化正赋起运、辽饷九厘、剿饷与练饷基线，失地、坏省级 fiscal payload 与恢复明控省份都按隔离、幂等口径处理。

### 修复
- **剿饷停征估算不再误报**：同回合停征或已驳回的剿饷不会继续出现在户部加饷奏报估算里。
- **无诏推进不再漏跑饷率事件**：退朝不下旨也会执行历史饷率前置 pass，避免只在颁诏结算路径生效。
- **事件 loader 覆盖默认结局负例**：新增配置负路径测试，锁定 `default_terminal_reason` 必须属于结局白名单。

### 测试
- 新增财政饷率 golden、同月 tick、玩家选择、停征、坏省隔离、失地恢复、奏报 payload 与 loader 负路径覆盖；ship 验证为 `2058 passed, 13 skipped`（root pytest），web Vitest `133 passed`，web build 通过。

## [0.21.0.0] - 2026-07-01

### 新增
- **family CMR 结论分类**：integrated CMR 现在能把同模块仍红、跨模块 defer、owning issue、spec conflict、infra failure 与受信 accepted suppression 分开记录，ship 前的 family gate 可以给出可执行的停止原因。
- **family stop summary 与 dogfood replay**：runner、family verify、ship 后 ledger 记录与 replay fixture 统一输出结构化 stop summary，历史 orchestration 回归可通过同一套 seam 重放和审计。
- **provider degraded 可观测性**：CMR/ship 路线会把 provider/auth/quota 降级记录到 metadata，并在强 leg 下限不满足时 fail closed。

### 变更
- **CMR 修复闭环更严格**：review/fix 进展必须有 scope-local diff、测试、fixture 或可信 ledger 证据；仅靠评审文字变化、旧 head、legacy disposition 或未授权 coordinator 答案不再让闭环继续前进。
- **family 模块边界更显式**：CMR 分类只信结构化 Module Declaration、runner 注入的 undeveloped module 与受信 suppression source，模块别名、fallback 文本和未声明目标会按安全路径阻塞。
- **worker/prompt 契约收紧**：coder、reviewer、integrated CMR 与 worker parser 文案同步 accepted_suppressed、prior disposition、provider degraded 与 source-auth 语义。

### 修复
- **accepted suppression 不能由 reviewer 自签**：`accepted_suppressed` 必须精确匹配 runner/family 注入的 source、scope、reason、finding identity 与 bounded reopen；#287 hub-loss 也不再从评审 prose 自动合成可信豁免。
- **CMR 成功摘要不再丢失材料结论**：跨模块 defer、accepted suppression、provider degraded、contract drift 与 final CMR head 会保留在 ledger / stop summary 中，后续 ship 和 resume 能读到真实状态。
- **resume / escalation 信任边界加固**：继续修复、human answer、ship worker contract drift、module startup failure 与 source-auth 场景按实际 ledger/git 状态分类，不再误当成普通成功。

### 测试
- 新增 family CMR 分类、verify-cmr fix loop、runner progress evidence、stop summary、provider degraded、real backend parser、worker prompt contract 与 dogfood replay 覆盖；ship 验证为 orchestrator typecheck 通过，Vitest `1033 passed, 1 skipped (1034 total)`，严格未使用符号检查通过。

## [0.20.0.0] - 2026-07-01

### 新增
- **军饷来源 spine**：明军新增省级/中央军饷份额与分源欠饷字段，月末欠饷、补饷、士气惩罚与旧档迁移统一走分源账户。
- **财政 substrate hub**：省级 settle tick 接入中央军饷 shadow hub，并为边饷/中央军饷固定流、财政账本与内容配置提供可审计的桥接路径。
- **补饷承诺结算**：持续承诺可按 arrears stop gate 补发旧欠，保留单军定向、多军范围池化、进度条与停止条件语义。

### 变更
- **补饷契约收紧**：普通 `economy_moves` 的 `purpose=补饷` 必须显式指定有效 `target_kind='army'` 与 `target_id`；缺失或不存在目标会拒收，不再自动改付其它军队。
- **军队展示补齐**：CLI、web 抽屉与地图节点展示军饷来源、分源欠饷、火器/炮兵与新军状态，避免只看到总欠饷。
- **提示词/文档同步**：score extractor、season simulator、世界观与 DELTA_SCHEMA/SETTLEMENT_FLOW 同步分源军饷、补饷目标和 hub cutover 边界。

### 修复
- **欠饷销账不再免费抹零**：小数欠饷尾数保留，不再因整数 ledger cap 被自动 writeoff。
- **承诺补饷池化限定范围**：多军 stop gate 的非定向补饷只会在 gate 声明的军队集合内按优先级分配，不再越界偿还无关军队。
- **免饷军转换保护**：带欠饷的明军不能直接切到土司/自筹军饷状态，必须先显式还款或核销。
- **预算流水去噪**：`边饷hub`/`中央军饷` 固定流不再作为一次性 economy movement 出现在 web 预算 payload。

### 测试
- 新增军饷来源迁移、财政 substrate bridge、补饷拒收、欠饷尾数、承诺补饷范围、军队展示与 web 预算覆盖；ship 验证为 `2014 passed, 13 skipped`（root pytest），web Vitest `133 passed`。

## [0.19.1.0] - 2026-06-30

### 新增
- **family escalation answer resume**：family decision escalation 现在可通过 append-only answer 事件恢复，答案会贯穿 CMR 与 ship worker，避免已回答的 family pause 卡死或丢上下文。
- **worker/toolchain preflight**：RealBackend 在启动 worker 前显式检查运行所需工具链，失败时给出可诊断的错误，而不是进入半启动状态。
- **family ship PR 复核口径**：family ship 与 resume skip 都会验证 PR 仍为 OPEN、目标 base / head branch 正确，并且 PR head OID 覆盖当前 family HEAD。

### 变更
- **resume truth 收紧**：runner 对 dead fallback、tagged S7 resume、worker throw、zero-commit child head、stale child head 与 headless ledger row 改为读取实际 git / ledger 真相后再恢复。
- **family ledger / reconcile 更严格**：reconcile baseline、merged / shipped / escalation / answer 行都按完整 shape 校验；坏行、过期 baseline、缺失 head 的 shipped marker 会 fail closed。
- **agent prompt trust boundary**：coder / reviewer / ship prompts 与 souls 明确 owner-authored brief、review/fix/ship 边界，以及 escalation answer 的数据流。

### 修复
- **PR ship marker 不再误绑定**：shipped marker 只在 PR head OID 与当前 family HEAD 完全一致时写入；legacy openFamilyPr 不能再用本地 HEAD 伪造 PR 覆盖。
- **resume skip 不再信过期 PR**：已有 shipped marker 只能作为候选；resume 前必须重新验证 PR 状态和 head OID，closed / retargeted / force-pushed / malformed ledger 情况都会升级失败而不是跳过 final barrier。
- **family escalation 不再误重开**：malformed answer、无进展 escalation、旧 pause ordering 与 tagged S7 resume 均按安全路径处理，避免重复执行或错误恢复。

### 测试
- 新增 RealBackend toolchain、resume session truth、family escalation answer、ledger/reconcile malformed rows、ship PR metadata、resume PR revalidation 与 family verify-cmr/spine 覆盖；ship 验证为 `1953 passed, 13 skipped`（root pytest），orchestrator typecheck 通过，orchestrator Vitest `912 passed, 1 skipped`，web build 通过。

## [0.19.0.0] - 2026-06-30

### 新增
- **family CMR pass 恢复锚点**：integrated CMR 的 completeness / correctness 通过记录现在会带上实际审核过的 family base HEAD 与模型路线 fingerprint，resume 只会跳过同一 HEAD、同一路线下已经通过的 pass。
- **CMR 后 HEAD 追踪**：family CMR worker 若在通过前提交 pass-local 修复，后续 correctness pass 与 ship worker 会读取并使用修复后的 family HEAD，避免在旧 head 上误判恢复状态。
- **测试路线隔离**：orchestrator Vitest 默认清理 route/model override 环境变量，单测默认走 normal 路线，同时仍允许个别测试显式切到 tight route。

### 变更
- **ADR 0030 runner-visible 评审闭环对齐**：CMR worker、runner、StepSpec 与 reviewer 相关文案同步为 runner-dispatched pass / review / fix 边界，去掉旧的「单 session 内隐藏完整循环」描述。
- **family sub-issue admission 拆分**：`parseSubIssueAdmission` 暴露完整准入结果与 skip reason；旧 `parseSubIssueNumbers` 保持兼容，只过滤 closed child，不再混入 ready / parent 过滤语义。

### 修复
- **CMR resume 不再跨路线误绿**：旧的 `cmr_passed` ledger 行缺少 route fingerprint 时会 fail closed；模型路线或 declared review legs 改变后，CMR pass 会重新跑而不是复用旧通过记录。
- **family ship 输入 head 更准确**：止于 PR 的 family ship worker 现在接收 CMR pass 收敛后的 family HEAD，减少 CMR 修复提交后 ship / ledger 状态错位的风险。

### 测试
- 新增 family ledger / verify-cmr resume guard、post-CMR HEAD 传递、route fingerprint、sub-issue admission 与 test route isolation 覆盖；ship 验证为 `1953 passed, 13 skipped`（root pytest），orchestrator Vitest `833 passed, 1 skipped`，orchestrator typecheck 通过。

## [0.18.1.0] - 2026-06-30

### 变更
- **财政 shadow spine 批量推进**：月末省级财政 shadow 现在一次扫描明控省 fiscal payload，再逐省推进已有 settle 基座，减少重复读取并保留坏基座隔离留痕。
- **省级 settle 元数据复用**：`regions.json` 的财政 settle 元数据改为共享默认组展开，17 省 seed 保持运行时语义不变，但内容包更易维护。
- **shadow spine 边界测试更稳**：批量桥测试改为验证流程调用边界，不再依赖 SQLite trace 文本细节。

### 修复
- **settle 元数据坏配置 fail-loud**：空 `_meta_defaults`、未知默认组、非对象 `_meta` 与错误的 `settle_meta_defaults` 容器会在内容加载时明确拒收，避免坏内容被当作缺省值吞掉。

### 测试
- 新增 settle 元数据展开与坏配置拒收覆盖，并验证 shadow spine 走批量桥、不回退到单省 reload；ship 验证为 `1948 passed, 13 skipped`（root pytest），覆盖审计 88%，ship review / red-team 无阻塞发现。

## [0.18.0.0] - 2026-06-29

### 新增
- **全省财政 shadow 基座**：明控且已 seed 的 17 个省现在都会在月末推进省级 `settle_tick` 基座，逐月累积省库、欠饷、官俸欠、宗禄欠、民欠与火耗截留。
- **史实量级财政种子**：陕西、边镇、京师/中原、江南核心、南方与西南省份补齐 `fiscal.settle` 开账与月参，并保留辽饷已 seed、剿饷/练饷待事件注入的元数据。

### 变更
- **财政 shadow spine 改为动态选择**：旧的陕西单省脊柱改为按 `controlled_by='ming'` 与 `fiscal.settle` 动态选择，失地省自然冻结，明控但无基座的旧档不会被自动创建基座。
- **shadow 日志更可审计**：月末 tlog 现在逐省打印实征、起运、火耗与末态欠账，并继续保持 shadow-only，不把起运额写入国库流水。
- **结算文档同步动态 spine 契约**：`docs/SETTLEMENT_FLOW.md` 与 ADR 0019 说明动态选择、坏基座隔离和全省 seed / hub cutover 的边界。

### 修复
- **坏财政基座不掀翻月末固定财政**： malformed `settle.st/p`、非 dict fiscal 容器与畸形 fiscal JSON 都会被隔离并 tlog 留痕；坏 fiscal 省当月固定税收出列，避免按默认容器造钱，失败 tick 不落库。
- **财政 golden 断言更稳**：`settle_tick` golden 改用 `math.isclose`，避免浮点表示细节造成误判，同时保持严格容差。

### 测试
- 新增全省 seed shape、逐省首 tick golden、多 tick 轨迹、动态 spine、失地冻结、旧档无基座、坏基座隔离、public fixed-flow malformed fiscal、shadow 不入国库与 malformed JSON 回归覆盖；ship 验证为 `1932 passed, 13 skipped`（root pytest），覆盖审计约 94%。

## [0.17.0.0] - 2026-06-29

### 新增
- **编排器模型路线预设**：runner、coder/reviewer/coder-fix、family ship、merger 与 integrated CMR 现在可按路线选择 claude/codex/agy 组合，并在 tight 路线破坏家族隔离时 fail closed。
- **双阶段 integrated CMR 闸**：family run 现在将完整性与正确性 CMR 拆成两道承重闸，分别使用独立 soul/prompt，并要求每个声明的 review leg 明确成功或跳过。
- **CMR finding 持久处置**：跨轮 review finding 支持稳定 identity、wont-fix/rejected 处置、claimed-fixed closure replay 与 prior disposition 校验，避免旧阻塞项在 resume/修复轮里丢失。

### 变更
- **worker 调度模型统一走注册表**：单切片、family、CMR、ship、merger 的 worker spec 都通过同一 model slug registry 解析实际 provider，未知 slug 与未声明 CMR leg 会直接拒收。
- **family ship/CMR worker 契约收紧**：ship worker 必须返回 `pr_opened`、family base branch 与非空 PR URL；CMR worker 必须满足 strong-leg floor、leg accounting 与 closure 检查后才允许进入下一步。

### 修复
- **CMR 闭环不再误绿**：补齐 CMR leg 计数、路由漂移、suppression replay、prior finding adjudication 与 corrupt ledger fail-closed 路径，防止未收敛或格式漂移的集成评审被当成通过。
- **merger/ship auth 与临时目录清理**：merger 支持路线选择的 codex/claude auth 装载，并在 worker 结束后清理临时 codex auth 目录；ship/CMR/merger 的缺失 auth 与启动异常会转为可定位的结构化失败。
- **family runner resume 边界加固**：修复已合并 child、aborted ledger、thin ledger、分页 sub-issue admission、非 runnable child 与 final ship marker 等恢复路径，避免重复合并、重复 ship 或静默跳过。

### 测试
- 新增 model route、per-slice CMR、family CMR/ship worker、verify-cmr、runner resume、ledger persistence、malformed output 与 route accounting 覆盖；ship 验证为 `1889 passed, 13 skipped`（root pytest），orchestrator Vitest `809 passed, 1 skipped`，orchestrator typecheck 通过。

## [0.16.0.0] - 2026-06-28

### 新增
- **召对写动作统一确认闸**：对话式拟旨、口头任免、密令新建/更新/催办/提交核议/记进展与后宫调教统一先暂存为待确认动作；皇帝可在召对中准/驳，不回则在颁诏/退朝检查点默认同意。
- **失败密令恢复入口**：密令落库失败会在 web 与 CLI 中持续显露为可重试项，支持跨回合保留签发时间与期限，并在重试成功后清理对应撤回入口。

### 修复
- **密令直写改为大臣确认路径**：兼容端点、工具调用、自然语言暗查请求不再绕过大臣回话直接创建密令，统一合并皇帝命令和大臣补充后再等待确认。
- **pending action 原子提交**：密令等非拟旨暂存动作的真实表副作用与 pending 状态更新现在处于同一事务，避免崩溃/异常后出现真实密令已创建但 pending 仍可重试导致重复落库。
- **恢复窗与结算边界收紧**：月末前半段完成后不再允许召对期即时写真表；恢复窗确认保留 pending 状态，由结算/退朝终端事务统一提交，防止半写。
- **确认作用域与失败提示校准**：确认/拒绝只作用于当前大臣、当前可见目标，并区分拟旨与非拟旨动作；失败提示按阶段决定是否可立即重试，不再承诺不存在的重试入口。

### 测试
- 新增 pending action、召对拟旨、密令确认/重试、CLI fallback、settlement write guard 与前端失败恢复覆盖；ship 验证为 `1862 passed, 13 skipped`，web Vitest `127 passed`，web build 通过，最终 codex ship review 无阻塞发现。

## [0.15.1.0] - 2026-06-28

### 变更
- **codex 推理强度文案校准**：codex 通道下的「关」现在标明「codex 最低=低」，避免玩家误以为可完全关闭模型推理预算。

### 修复
- **CLI 召对上下文持久化**：terminal 召对现在与 web 路径一样先落玩家发言、再调用大臣后端，并在失败时回滚半轮消息，密令短确认可以读取本回合前文。
- **推理能力状态刷新**：保存 LLM 配置后，菜单页与局中设置页会信任后端返回的 `reasoning_supported` / `reasoning_strengths`，并同步服务端归一后的 base URL、model 与 advanced 设置，避免保存后仍用旧启发式误启用推理强度。

### 测试
- 新增 CLI 召对落库/失败回滚、LLM 配置保存响应、菜单页推理能力刷新、codex 推理文案和 reasoning support helper 覆盖；ship 验证为 `1771 passed, 13 skipped`，web Vitest `108 passed`。

## [0.15.0.0] - 2026-06-27

### 新增
- **统一推理强度设置**：菜单页与局中 LLM 配置新增统一「推理强度」选择器，支持 API 与 CLI 通道分别保存 `off/low/medium/high`，并按 OpenAI、DashScope、Minimax、codex、claude 的能力自动启用或禁用。
- **密令确认上下文恢复**：玩家先与大臣商议任务、下一轮只用「密令」按钮确认时，系统会从最近相关召对中恢复皇帝任务和大臣实质补充，生成完整密令，而不是只保存确认短句。

### 变更
- **推理配置迁移到单一旋钮**：旧 `thinking_level` / `advanced_thinking_level` 会迁移到 `reasoning_strength`，保存时清空旧隐藏字段，避免旧配置继续暗中覆盖玩家的新选择；API/CLI 两个槽位互相保留各自的推理强度。
- **探报章节命名收敛**：邸报与军务抽取 prompt 统一改用「探子回报」，前端展示和原始样例同步跟进。
- **军务抽取契约收紧**：`派系变化` 只能使用合法派系 key，不再允许把 `armies`、army_id 或具体军号误写成派系；具体军队后果改走 `军队变化` / `新建军队`。

### 修复
- **API 密令前缀不再重复抽取**：API tool-call 已成功创建密令时，后置 fallback 不再额外发起一次会被丢弃的 LLM 抽取，减少等待和调用成本。
- **密令正文防串台**：确认式密令现在会排除无关早前问答，只保留最近相关任务跨度；同时保留前文大臣的承办人、步骤、保密要求和期限补充。
- **推理强度持久化边界**：切换 API/CLI 通道、清空强度回默认、advanced model 复用主配置、CLI runner 不支持推理强度等路径都按通道正确读写，不再丢失 inactive 槽设置。
- **家族合并测试断言对齐**：修正 orchestrator 家族 worktree 位置测试，使其断言当前实现使用的 `.worktrees/.epic-orchestrator` sibling 路径。

### 测试
- 新增 reasoning strength 运行时配置、CLI 后端映射、web 菜单状态、密令上下文恢复、军务 prompt 契约和探报标签覆盖；ship 验证为 `1767 passed, 13 skipped`，web Vitest `97 passed`，web build 通过。

## [0.14.1.0] - 2026-06-25

### 修复
- **取消飞行中的召对流**：客户端断连（SSE 流提前关闭）时，后端现在能可靠地将对应回合标记为 `failed`、删除其关联的用户提示消息，并清理内存中的对话历史用户条目；已完成回合的取消请求保持幂等，不触发任何副作用。
- **承诺进度条改用挂钟时间**：进度条月数改从 `origin_turn`（承诺创建回合）计算，消除月末滚动更新重试导致月数偏高的问题，使进度条与游戏时间线严格对齐；`origin_turn` 缺失/为 0/NULL 时回退到 `state.turn`（已履行 0 月），不再把绝对回合数泄进进度条。
- **取消守卫异常安全**：`chat_stream` 断连处理器现将清理操作包裹在 `try/except` 中，确保 DB 错误不会替换原始中断信号、破坏 HTTP 流式终止；清理异常会被记录日志而非静默吞掉。
- **取消检测前置 + 防御式关流**：进入阻塞读取前先探一次客户端断连；SSE `finally` 关流前先校验 `close` 可调用，避免迭代器/测试替身缺 `close` 时 `AttributeError` 掩盖原始异常。
- **消息 id 空值判断收紧**：`user_message_id` 与 `minister_message_id` 均改用显式 `is not None` 判断，防御性修复极端情况下 `id=0` 消息被误跳过删除 / 已完成回合被误判为未完成。

### 测试
- 新增取消守卫专项测试：关闭流标记失败/删消息、已完成取消保持幂等、SSE 断连检测端到端、不存在/无消息 id/竞态/正常完成等间隙用例；新增承诺进度条计时集成测试（挂钟推进、边界截断）。

## [0.14.0.0] - 2026-06-24

### 新增
- **行止超时兜底**（#346）：DB 新增 `transit_start_turn` 列，记录人物进入行止状态的回合；`force_transit_arrivals` 在每回合 `pre_settle` 中强制驱动滞留 ≥2 回合（或 `transit_start_turn=0` 旧数据哨兵）的人物到达目的地，防止行止人物因事件复杂度无限阻塞。到达顺序固定在事件终态评估之前。模拟器上下文新增 `transit_nudge` 字段，提示 LLM 哪些人物已兜底抵达。
- **实时召对短超时**（#353）：新增常量 `MINISTER_CHAT_CLI_TIMEOUT_SECONDS = 90.0`；`create_minister_agent` 通过 `dataclasses.replace` 克隆 LLM 配置并将超时降到 90 s，与月末结算的 300 s 超时完全解耦，避免召对等待超时影响结算管线。
- **召对取消按钮与计时**（#353）：前端 `ChatModal` 新增取消按钮（`.composer-cancel` 样式），通过 `AbortController` 中断飞行中的流式请求；弹窗同步显示已等待秒数（`elapsedSeconds`），关闭弹窗或回话结束时自动重置，多大臣并发时补充陈旧响应守卫防跨污染。
- **承诺进度条时间轴**（#348）：新增 `commitment_timed_bar_value(issue, state)` 函数，按已过回合数占总承诺周期比例返回进度条数值（`None` 表示无限期承诺）；`web_app.py` 在承诺类局势 payload 中注入 `bar_value` 字段，前端可直接驱动进度条渲染。

### 修复
- **承诺显示改用相对时长**（#348）：`commitment_display_text` 重构为从当前回合计算剩余回合数，消除因记录截止绝对值导致的「负剩余」和僵死部件堆积。
- **帝国修正不放大支出**（#341）：月末经济结算中，帝国修正系数（empire modifiers）现在只作用于收入项，`base < 0` 的支出项（军饷、俸禄、省级拨付等）直接原值落库，不再被修正放大，消除「下令 100 两、实际出账 130 两」的数值错误。
- **行止 re-emit 不刷新 `transit_start_turn`**（#346）：同目的地的重复行止事件（re-emit）保留原始 `transit_start_turn` 值；派生任命（引退→新任）的回滚路径对称还原 `transit_start_turn`，防止哨兵值被意外重置导致兜底逃逸。

### 测试
- 新增行止兜底（`transit_start_turn` 快照 / 恢复、`force_transit_arrivals` 原子性、re-emit 不刷新哨兵）、召对超时常量契约、`create_minister_agent` 超时上限和无副作用覆盖；ship 验证为 `1552 passed, 13 skipped`，Vitest 3 passed（预存在 `epicOrchestratorWorkflow.test.ts` 失败已收录 TODOS.md B13，非本分支引入）。

## [0.13.0.0] - 2026-06-20

### 新增
- **对话式拟旨**（#137，对齐 ADR 0006）：玩家在召对中用自然语言「拟旨吧 / 你拟一道旨」即可触发大臣草拟圣旨，不再必须点按钮；自然语言拟旨暂存为 `pending_actions(kind=directive)`，不走召对期的应允 / 拒绝即时提交或丢弃，颁诏时自动承接为 `turn_directives` 草案并入拟诏。「补充」走同一条 pending 原地更新（last-write-wins）。「不回 = 颁诏默认同意」路径在真实 Web 全栈接通（后端结算 → 前端 `pending_directive_count` → 拟诏按钮可用）。

### 修复
- pre-landing 跨模型评审（红队 + codex）收敛的若干个正确性 bug：
  - 确认闸不再误扫对话式拟旨草案（应允/拒绝其它待办时不会提前提交或静默删除草案）。
  - 拟诏 / 月末结算遇未决显式拟旨时**先拒绝再提交**，无部分提交副作用。
  - 撤回召对**精确删除**本次产生的草案（`committed_directive_id`），不误删同回合同大臣的无关草案，含补充（restore_row）路径。
  - 草案变化时**作废过时的生成诏书文本**，防止下发不含新草案 / 含已撤回内容的 stale 诏书。

## [0.12.6.0] - 2026-06-20

### 新增
- **圣旨承诺账本**：玩家下达“每月补饷直到补齐”“连续数月执行”“数月后复核”等旨意时，系统会把承诺写成可追踪局势，而不是只停留在邸报叙事里。
- **三类承诺形态**：支持持续直到达标、限期持续、未来一次性复核；到期待裁的承诺会进入密令待核议通道，并通过 `acknowledged` 收尾。
- **承诺进度呈现**：局势面板、详情弹窗、悬浮提示和大臣工具都会显示承诺类型、截止回合、终止条件和当前进展。

### 变更
- **承诺结算独立于普通局势惯性**：圣旨承诺不再按普通 issue 的衰减和惯性推进，而是逐月执行财政、指标、人物、势力、阶级、地区、军队等明确后果。
- **Extractor 契约收紧**：prompt、schema 和工具说明要求承诺必须显式写 `commitment_kind`、`origin_ref`、`ongoing_effects`、`stop_condition` 或未来 `end_turn`，拒收缺锚点、旧式人物条件、立即过期和不可月结的一次性实体效果。
- **承诺状态进入存档载体**：`issues` 表新增承诺字段，模拟器上下文和 web API 输出结构化承诺进度，恢复存档后仍能继续追踪。

### 修复
- **承诺不会空转或误结案**：修复持续效果被判定为有工作但月结不落库、指标被高 bar 折成 0、字符串数值被误判、当前回合截止立刻过期、旧 `resolve_condition` 形状生成死局势等边界。
- **待裁承诺 ACK 不触发奖惩**：未来一次性复核到期后只进入待核议，确认后 dropped，不会误跑 resolve/fail 的实体后果。

### 测试
- 新增承诺创建、schema、结算、恢复、ACK、人物安抚、大臣工具和 web 呈现覆盖；ship 验证为 `1429 passed, 13 skipped`，web Vitest `3 passed`，web build 通过。

## [0.12.5.0] - 2026-06-20

### 修复
- **地区控制者落库守门**：`region_delta.controlled_by` 现在只接受 `powers.id` 中存在的非空势力 id；`null`、空白和未知势力会逐项拒收留痕，不再污染地区控制权。
- **收复地区恢复逻辑保留**：合法 `controlled_by` 变更仍会落库；非明→明的收复路径继续触发 `on_restore` 覆盖，避免守门误伤既有收复流程。

### 文档
- `docs/DELTA_SCHEMA.md` 明确 `controlled_by` 不再是普通文本字段，而是受 `powers.id` 白名单约束的势力 id。

### 测试
- 新增无效控制者拒收、合法势力 id 落库、同批坏字段/好字段隔离与收复 hook 回归覆盖；ship 验证为 `1352 passed, 13 skipped`，`compileall` 通过。

## [0.12.4.0] - 2026-06-19

### 修复
- **事件结局标签本地重试**：历史事件提取器返回缺失或未知结局标签时，会只重跑 `issues` 模块并保留其它模块结果，避免一次坏标签丢掉整轮提取成果。
- **结局标签别名归一**：己巳之变等封闭事件结局支持同义标签规范化；超过重试上限后仍响亮失败，防止下游事件链吃到不明分支。

### 测试
- 新增事件结局标签别名、issues-only 重试和重试上限 fail-loud 覆盖；ship 验证为 `1316 passed, 13 skipped`，`compileall` 通过。

## [0.12.3.0] - 2026-06-19

### 新增
- **战略/外敌事件显式分类**：大凌河、林丹汗西迁、戊寅虏变、松锦决战、洛阳陷、开封围城、北京陷落等历史节点新增 `trigger_class=strategic_foreign` 与结构化 `trigger_gate`，己巳虏变也显式声明为空门控。
- **席位制战事软判**：战略/外敌事件的点名将领按战事席位和盘面结果处理，不再因历史人物提前死亡而直接作废候选。

### 变更
- **战略事件触发收口到主账结果**：`event_pool` 触发战略/外敌事件时，必须同信封落地区、军队、人物、势力或新军等世界状态主账结果；空触发会被拒收并保留明确原因。
- **事件分类消费改为配置驱动**：战略/外敌判定从硬编码事件 id 转为读取 `trigger_class`，后续新增同类事件需同时补内容分类与消费映射；缺消费映射会在内容绑定期响亮失败。

### 修复
- **战略事件文本锚点收窄**：普通河南治理或李自成势力变化不再因“洛阳/开封/河南/流寇”等泛地名被误当成未触发的城陷战果而拒收。

### 测试
- 新增 #194 覆盖：战略/外敌事件分类与门控精确矩阵、点名将死亡不作废、大凌河/林丹汗西迁缺主账拒收与主账落地触发。
- 全量验证：`1323 passed, 13 skipped`。

## [0.12.1.0] - 2026-06-18

### 新增
- **历史事件时间窗过期终态**：历史事件和 seed 事件可声明最晚触发时点；过最晚仍未满足前提门时会记录 `expired` 终态，之后即便盘面条件变为达标也不会再晚弹。

### 变更
- **开放窗显式化**：历史锚定事件必须显式声明 `trigger_end_year` 或 `open_window`；漏填不再静默当作永不过期，现有开放窗事件已逐一标明。
- **事件配置加载校验**：`trigger_month` / `trigger_end_month` 必须在 0-12 内，`open_window` 必须是 JSON boolean，且最晚时点不能早于最早时点；坏内容在加载期响亮失败。

### 修复
- **过期事件拒收路径**：`event_pool` 立项遇到已过期事件时会返回明确“过期终态”拒因，不再落成普通局势或被泛化成候选池不满足。
- **终态落账写路径收口**：候选池读取只过滤过期/作废/避过事件，不再顺手写库；结算前半段通过 `apply_event_terminal_states` 显式落 `event_triggers` 终态，并在外层事务内不提前 commit。

### 测试
- 新增事件窗口、开放窗、过期终态、自动触发过期、加载契约、候选读取只读和事务回滚覆盖；PR 最终全量验证为 `1313 passed, 13 skipped`，前端构建通过。

## [0.12.0.0] - 2026-06-18

### 新增
- **历史战事软判闭环**：戊寅虏变、松锦决战等战略/外敌事件不再只落一条长期局势；裁判可在同一信封写地区、军队、人物、势力和新军等主账结果，主账真实落地后才记录事件触发。
- **人物核心历史门**：毛文龙、袁崇焕、卢象升、洪承畴、孔有德、福王等历史人物事件新增结构化前提和避让逻辑；玩家已经改变人物状态、官职、去向、势力或生死时，历史节点会按盘面避让或转为已处理。
- **流寇分股势力模型**：李自成、张献忠等流寇从笼统 `bandits` 拆成独立势力股；招安、归明、剿股和反噬只作用于对应股，避免“招一人、削错股”。
- **事件结局字段**：新增 `事件结局` / `event_outcomes` 顶层字段，用于己巳之变这类有闭合结果标签的战略事件，并接入 extractor 白名单与误路由检查。

### 变更
- **战略战果契约收紧**：战略/外敌事件必须带有可验证的世界状态主账结果；地区、军队、人物、势力和新军战果都要带事件锚点，孤儿战果、缺结局标签、重复候选、过期候选和无主账结果都会被拒收。
- **人物变更与事件门对齐真实落地**：同状态处置/罢黜、同官职任命/调任、同去向行止、同势力易主等 no-op 不再消耗战略事件；别名、任命、易主反噬和内存回滚按真实写口预检。
- **历史事件 prompt/schema 对齐**：score extractor 与 season simulator prompt 明确战略事件、人物核心事件、流寇招安和 `power_updates` 写法，减少空触发、错字段和双减。

### 修复
- **战略信封原子性**：事件结果预检失败、人物反噬拒收、新军重复、势力字段非法或 power update 提前落库时，整组战果不落主账，避免事件已触发但盘面没有对应后果。
- **旧档与静态盘面回填**：旧 `event_pool` issue 回填为 `event_triggers` 时保留核心效果事件，旧 bandits 人物按静态内容迁到各自流寇势力股。
- **提取器误路由覆盖**：`event_outcomes` 能规范化为 `事件结局`，不会被当作跨模块错放字段丢弃或误报。

### 测试
- 新增和扩展历史事件、战略战果、人事变更、流寇分股、schema/prompt 和 extractor sanitizer 覆盖；PR 最终全量验证为 `1293 passed, 13 skipped`。

## [0.11.1.0] - 2026-06-18

### 修复
- **月末结算后半段事务闸门加固**：局势推进/撤销/结案、实体后果、地区/军队/建筑/阶级/势力副作用、密令更新与结案等写口统一尊重外层事务，避免内部 `commit` 提前落盘导致“结算失败但局部已生效”的半写存档。
- **事件候选池同回合重验**：`event_pool` 立项会同时检查输入时快照、当前候选池、同批去重和同回合人事变更后的前提门；同一事件重复 emit、候选窗口过期、人物状态/官职/缘由/去向/势力变化导致前提失效时，不再误立局势。
- **人事变更 runtime 回滚闭环**：外层事务回滚时，`state.metrics`、`content.characters` 和大臣 registry 的 agent/session 缓存一并回到事务前状态，避免 DB 已回滚但本进程仍保留未提交身份的幽灵大臣。
- **任命与易主闸门对齐真实落地**：同回合任命的别名归一、宗藩拒任、独占实职顶替、`reason_code/status_reason` 清理、`office_type` 推断和易主反噬对 `power.*` 前提门的影响，均按真实写口模拟后再决定是否立项。

## [0.11.0.0] - 2026-06-14

### 新增
- **省级财政基座 port（#66，Epic #65 / M3）**：把 22 轮跨模型评审收敛的 `spike_settle_tick.py`（v23.1）搬成真引擎代码。
  - `ming_sim/fiscal_tick.py` `settle_tick(st, p, actions)`：单省单月复式记账结算（⓪–⑪：action 相位/应征火耗实征民欠/起运存留分池漂没/拨付中饱/法定付款 waterfall 偿旧欠结转），4 独立守恒 oracle（现金/债务 per-account/C 分账/土地）每 tick 自校，坏输入→`ValueError`、守恒破→`FiscalConservationError`。
  - `tests/test_fiscal_tick.py`：G1–G22 末态硬期望 golden + G21 fail-loud 输入校验面 + G9 三 tick 死亡螺旋链（69 测）。
  - `GameDB.settle_province_tick`（`ming_sim/db.py`）：DB↔settle_tick 桥（读 `regions.fiscal.settle.{st,p}` → tick → 写回 `new_st`）。陕西（单省脊柱）种子 = v23 占位数（史实重标见 #70）。
  - 接入月末固定财政相位（`apply_fixed_period_flows`）**shadow 模式**：基座逐月演化+落库，但暂不驱动国库（占位数偏史实 3–10×，⑫国库 cutover 待 #70 重标后切）；fail-loud 但隔离（基座失败不掀翻 pre_settle 固定财政）。
  - 港口锁（ADR 0008）：FAIL tick 在 UPDATE 前 raise、绝不持久化。

## [0.10.0.0] - 2026-06-14

### 新增
- **人事档案 applier 契约（ADR 0009 C1）**：人物状态/名分/去向的落库从分散多入口（office_changes / character_status_changes / character_power_changes / appointments）统一收口到单一 `人物变更` delta + 契约化 applier。新增 `person_archive_contract.py`（状态/动作/缘由转移矩阵 + reason_code 规范化）、`person_delta_adapter.py`（旧四 key → `人物变更` 保真翻译，旧 key 仅作 ready=1 重试兼容、自然枯死）、`person_write_inventory.py`（直写 characters 表的写点清单 + AST 扫描守门）。
- **起复人才池视图**（offstage_ministers）：居家/致仕/削籍在世大臣带 reason_code/status_reason 进 simulator 盘面与 extractor 上下文，裁判/玩家看得见可起复之人。
- **三面同步（决定6）**：Character 携 reason_code/status_reason；处置/易主/顶替/起复后 DB 行、in-txn content、内存 Character 一致，reload 回滚兜底。

### 变更
- 历史 卒/登场 tick 经 `处置` 语义统一落库；易主置 active 并清旧滞留缘由（如「松山兵败被执」）+ 记 status_changed_turn。
- 在朝名单（court_roster）/ 起复人才池 / active_ministers 三处统一 roster 口径 = 大明、非后宫（active 外臣如皇太极、offstage 流寇如李自成不再混入）。
- 月末结算重排：inertia 漂移在留痕 + 章节记忆之前跑，使其追加的玩家可见人物变更并入 applied（SETTLEMENT_FLOW 同步）。
- extractor prompt 正向化（移除负向「不要X」指令）+ 教 reason_code by 缘由。

### 修复
- 新开档老档迁移：罢居府名不再硬写进 region_id 列（地名留 status_reason）；在途中文目的地经 `match_region_id_from_text` 解析成 region_id 落 transit_to（旧码中文 vs 英文 id 恒不等、transit_to 永不落）。
- 顶替全腾缺清 transit_to（被顶替者落听用候铨、不留赴老职路线）。

### 备注
- ship-pre 双闸：5a 完整性闸 PASS、5b 正确性闸 8 轮 cross-model review + 对抗性核验收敛（0 真 P0/P1）。
- Deferred findings（契约加固/审计/测试批）追踪于 [issue #97](https://github.com/Akagilnc/ming-salvage-sim/issues/97)。

## [0.9.0.0] - 2026-06-12

### 新增
- **结算落库拒收契约(ADR 0008 PR2)**:月末落库的 9 个 section(势力/人物易主/地区/军队/建军/财政三段)从「整段吞异常·裸奔崩整月·静默丢脏项」统一迁成**逐项拒收留痕**——LLM 脏数据(幻觉 id、查无此人/此地/此军、字段非法、值不可解析、负值)单项被拒并记进 `rejection_reports`(turn/section/原始项/原因/类别/来源),好项照落,坏一项不再带走整批;代码异常(bug 类)仍上抛回滚。**拒收报告从此有内容**:支撑「哪个 section 最常被喂脏」聚合,事务内落 DB、提交成功后镜像 jsonl(可回收副本)。
- 拒收记录带来源标记(provenance):引擎推演路标 `system_simulation`、探针 driver 路标 `unknown`,随行落 DB+jsonl(按来源细分到玩家诏书/HITL 留后续波次)。

### 变更
- **值语义集中到落库层(applier)单点守门**:财政三段的 key 规范化(strip/多重后缀拒)、direction 中文同义词归一、无损整数串转换、display 默认派生全部收口到 `apply_score_extraction`,cleaner 只做无损 canonicalize 不再吞脏——引擎路与探针 driver 路对同一输入同判(此前两路两判)。
- **国策结案路保留历史容忍语义**:`_apply_issue_entities` 对历史上本就 raise 的脏项升级中断,对历史 print-skip/静默走默认的脏项容忍并留痕(issue_strict 按整项历史谓词分类),不把历史可活的脏数据变成新的崩月路。
- 抽出 `atomic_and_reload` 上下文管理器,收编结算管线 6 处重复的「事务 + 回滚后从 DB 重载 + 链式上抛」模式;回合相位比较统一走 `TurnPhase` 枚举(落库仍是 `.value` 字符串)。
- 错误包/拒收镜像在测试中隔离到临时 user-data 目录(conftest autouse),不再污染真实 `data/error_packs`。

### 修复
- 财政新立项存在性检查覆盖 base+rate 双键:`田赋_base`(田赋默认只有 rate 行)撞 PK 崩整月,改为逐项拒收。
- `_stem_of` 对多重后缀垃圾 key(`辽饷_base_base`)返非法标记而非归一——此前会让裁撤路误删真科目并清零各省实收(不可逆)。
- 空 key / falsy delta(`False`/`0.0`)不再被「无操作短路」吞掉无痕;`delta` 在场脏值显式拒。
- 结算中回滚后内存重载自身再失败时,原异常裸传播(不二次包成 SettlementAbort、不基于脏态写错误包)。

## [0.8.0.0] - 2026-06-11

### 新增
- **月末结算全有或全无(ADR 0008 PR1)**:回合后半段(落库、章节记忆、局势惯性、结局判定、推进回合)收进单一事务——中途崩溃/出错时整段回滚,存档不再出现"国库扣了但军队没建"式半写;事务层经自定义连接(`applier.atomic`)实现,期间内层 `commit` 暂停、`executescript` 拒绝、回滚后自动续开事务,杜绝第三方代码逃逸出事务。
- **结算可恢复**:邸报与 delta 推演结果在结算前持久化(`extracted_ready` 判别列区分"真结果/占位/失败"),崩溃或中止后重开游戏即可从断点续跑——已就绪的结果直接重放落库,不再花一次 LLM 重推演;推演结果损坏或缺失时自动退回重推演,旨意原文跨进程存活。
- **响亮中止 + 错误包**:推演产物不合契约(shape 垃圾、损坏 JSON)时不再静默吞掉,改为中止结算并落一份五件套诊断包(DB 快照/上下文/错误链/manifest/拒收记录,永不覆盖旧包),玩家收到带重试指引的明确报错;另提供"重新推演"逃生口,把坏结果降级为非就绪(保留邸报字段)而非删行,避免新软死锁。
- **拒收报告带出处**:落库被拒的条目(白名单外字段、坏值)记录 provenance,事务内落 DB、提交后镜像 JSONL,事后可审计哪个环节产了坏数据。
- **恢复窗口 UI**:web 端 settling 相位显示恢复横幅 + "续跑结算"按钮;CLI 在恢复入口打印操作指引('back' 给出恢复路径而非静默循环),零草案下也能恢复。

### 变更
- 结算前半段(固定财政、局势播种)自带事务并提交——中止重试时前半段效果保持已落,不重复扣账(设计明文,非缺陷)。
- 回合相位新增 `settling`,作为单一真源下沉到 `models.py`;恢复窗口内冻结改盘操作(下旨草案、撤回、跳过等 7 个入口),web 对应端点返回 409,聊天提案在源头被挡。
- 召对中的口头应允改为延迟提交:恢复窗口内不再即时 commit,统一并入结算事务,杜绝跨事务半写。
- 退朝(无旨推进)在前半段已完成时拒绝执行——结算欠账不可跳过,只能续跑或重新推演。
- 事务回滚后内存状态一律从 DB 重载(含 content 重建),杜绝"DB 回滚了但内存还记得"的幽灵状态。
- 探针 driver 的结算路径与真实流程对齐:同样在 pre_settle 后持久化推演上下文,重试语义一致。
- 恢复窗口冻结范围扩大(评审修):全部即时写聊天路径(任免落地、编外人物登记、密令房四类操作、CLI 前缀密令)与自然语言抽取的新暂存动作一并冻结;窗前已暂存的动作不受影响,仍随结算事务统一提交。

### 修复
- 探针 driver 此前每月固定财政流水在异常路径下静默蒸发——现与结算同事务,要么全落要么全回滚。
- 毒推演结果反复重放导致的永久软死锁(重放→失败→重放)被逃生口切断。
- HITL 暂停时三件状态(相位/草案/上下文)改为同一事务写入,中断不再留下互相矛盾的半套状态。
- settling 相位与恢复上下文(引擎占位/driver 重试真源)改为同一事务提交,引擎与探针 driver 同修——崩在两笔之间不再留下"相位已 settling 但无恢复上下文"的存档,玩家手改的旨意原文不再因此蒸发。
- CLI 恢复期局势分支收到守门拒绝时留在本回合交互循环,不再重进回合重印回合头。

## [0.7.2.0] - 2026-06-10

### 新增
- **三饷计火耗（spec v23，2026-06-10 拍板）**：火耗应派从「只派正赋」改为 `(正赋+三饷)×火耗率`，正赋/三饷分量另立——百姓实际负担与官绅截留不再被系统性低估；三饷分量随辽/剿/练饷时间线注入消长。
- 财政基座 spike 新增 golden：G22 三饷火耗分量、G22b 三饷=0 退化边界、G14b 正赋应征 None≡缺省、G14c 穷省 k=0.5 清丈（钉结算 k 缩放与 oracle 重放两侧）。

### 变更
- 火耗对账 oracle 同步改为正赋/三饷两分量独立重算后相加（与结算同分量式，防极端量级下浮点求和序差致对账漂移），两分量并显式写入结算结果（下游直接消费、不解析 stdout）；`官民田_o` 从开账+诏令独立重放（不再读清丈后的运行时税基）——清丈类「两侧同搬」篡账现在被债务+C 两层 oracle 当场咬死。
- 全部 value golden 钉死 `省库库银` 与 `官民田/隐田` 末态；raise-golden 升级为验证具体守门消息；spike FAIL 时退出码为 1（自动化不再假绿），`sys.exit` 收进 `__main__` guard（import 不杀进程）。

### 修复
- 开账负值校验补齐 CLAIM 四科目（负军饷欠经偿还环凭空生钱）。
- param/Due/开账库存的 NaN/inf 入口拦截（NaN 军饷 Due 原可把整个资金池静默付空且五层断言全过）。
- Due 科目白名单（拼错科目原会让法定支出静默蒸发）；action 缺 type/非数值字段改为干净报错。
- 支付池透支 fail-loud + 浮点尘埃清零；`正赋应征=None` 语义钉死（视为缺省走亩额派生，其余参数拒 None）。
- 必填参数（三饷应征/火耗率/逋赋率/起运定额/Due）缺失改为干净报错而非 KeyError——不给默认 0（火耗率缺省成 0 = 静默改经济学）；开账 stock 为 None 前置拦截；率值/param/Due/开账全面型别守门（字符串/bool 原走半程 TypeError，bool 是 int 子类须显式拒）（G21t–w）。

### 移除
- spike 中只写不读的 Cin/Cout 流水字典（v13 同源对账残留）。

## [0.7.1.0] - 2026-06-10

### 新增
- **任免纳入聊天动作闸门(ADR 0006 三类全做)**：CLI 召对里口头任免(任命/升迁/调任/罢免/纳妃)走**独立检测** `extract_appointment_action`(与密令的 `extract_minister_actions` 不混)、随召对触发不挂密令 gate、覆盖大臣 + 太监、作用域=当前召对的大臣。暂存为 `kind=office`,颁诏 `commit_pending_actions` 透传 `content/registry` 落库。

### 变更
- **确认闸门由「颁诏批量同意 + UI 撤回面板」改为「对话确认」**：大臣(太监)in-character 领命复述;皇帝下一句**应允 → 当场 commit**该召对大臣暂存、**拒绝 → 丢**、不回 → 留、颁诏对没回的算同意。新增 `extract_confirmation_intent`,commit/drop 按 `minister_name` 过滤。
- **任免落地核归一**:抽出 `issues.apply_office_appointment` 作【唯一落地核】(在册且未死→改 active+授官+顶替去重+`office_type` 重算+内存/registry 同步;不在册→建档;dead/空 office 拒),**extractor 的 `office_changes` 与 CLI 任免 commit 共用**,杜绝两份会漂的实现;罢免加 ming-guard + alias + active 校验。
- minister prompt 加「in-character 领命并补充信息和要点」(后宫走 consort_agent 自有领命)。

### 修复
- `_displace_duplicate_offices` 剔除官员一个独占分项后,保留官职的 `office_type` 随之重算并同步 DB+内存(原只改 office、留陈旧 type,大臣 agent 按错类型建身份/工具)。

### 移除
- 拆掉自造的「待颁诏」前端确认 UI:`PendingActionsModal` + 顶部浮窗(`.pending-actions-fab`)+ pending 角标 + 撤回按钮 + 相关 state/type(确认改对话驱动;后端 `pending_actions` 表/暂存基建保留)。

## [0.7.0.0] - 2026-06-09

### 新增
- **聊天动作闸门(ADR 0006)**：CLI 后端召对里 LLM 从自然语言**推断**出的密令写动作(更新/催办/提交核议/记进展)与后宫调教,不再在召对当场直写真实表,改进 `pending_actions` 暂存表;颁诏时(`pre_settle` 最前 / 退朝 `advance_without_edict`)`commit_pending_actions` 在结算管线前批量落库(不拒绝即允许)。暂存行纳入召对 rollback(撤回召对一并删),落不了的标 `failed` 不留孤儿,commit 抛错被兜住不崩结算。**根治**:闲聊被判「更新密令」当场静默改既有密令 + 续期 + 谎报「已交付」(handoff 计划里 slice 4「action-gate」一直没实现)。
- **皇帝复核区**：`GET /api/pending_actions` + `POST /api/pending_actions/{id}/withdraw`(不存在 404 / 已落库或非本回合 409);前端「待颁诏」复核面板(列本回合暂存动作 + 逐条撤回)+ 顶部入口浮窗 + 召对暂存反馈提示(取代旧「密令已秘密交付」对更新动作的谎报)。

### 变更
- 流式与非流式召对路径共用 `apply_cli_conversation_actions` + 同样回传 `pending_action_id`,不漂移。
- 拟旨与「密令如下/拟旨如下」显式前缀按钮 = 玩家明示,仍直接落库,不入闸门(认可例外)。任命走 agno tool-call(api 通道)不在本片(ADR 0002 更大范围)。

## [0.6.1.0] - 2026-06-09

### 新增
- **游戏内 LLM 执行通道选择**：局中设置面板(gameMenu)新增 API / CLI 通道选择器 + CLI runner/model/超时输入。CLI 局开局后改设置不再被强制降级到 API、不再因空 key 误报；显式选 CLI 即可脱 key 续跑(#51)。

### 修复
- **真实流落库二级类型校验**：`validate_delta_shape` 抽成单一真源(`ming_sim.issues`),`apply_score_extraction` 落库前先校验容器/实体二级 dict 类型,畸形 delta 不再在 apply 内部「前字段落库、后字段崩」半落库;driver 仍在 pre_settle 前校验(#57)。
- **探针 driver 纯确定性**：driver 注入 channel=api 确定性配置,即便设了 `MING_SIM_LLM_BACKEND` 也不再 spawn legacy CLI enrichment(ADR-0004:dialogue-Claude 已自产完整 delta)(#54)。
- **CLI 空 cli_model 不漏 API model 名**:补 for_role/advanced 路径回归覆盖(RT2 已修工厂)(#52)。
- **runtime_llm.json 数值类型一致**:`_api_runtime_slot` 类型感知,preserve/fresh/load 三路 max_tokens(int)/timeout(float)同型(#53)。
- **in-game 设置 verify offload**:`api_set_llm_config` 把 LLM 连通性 verify(CLI smoke ~12s,只读)offload 到线程不卡 UI;commit(改 session 态)留在 event loop 同步跑(单人 CLI 串行探针下原子无 race)(#56)。
- `is_real_api_key` 拦截 `__keep__` sentinel,不当真 key(Red Team)。

### 修复(ship-pre 跨厂 CMR 续轮)
- **落库二级类型校验补全**:`_NESTED_DICT_FIELDS` 收敛为 `{region_delta, army_delta, power_updates}`(这三者 apply 逐 entity 写、坏项中途崩=部分已落库),faction/class 排除(apply 各自容忍旧扁平 int / 静默跳);所有 list 字段补「项必须是 dict」校验;None 字段容忍(与 apply `or {}` 一致)。
- **通道切换不丢 key**:`commit_llm_config` 对 CLI 通道 preserve/seed api 槽真实 key——已存槽有 key 则 preserve_api 保留;槽空但当前 session(可能来自 `OPENAI_API_KEY` env)有真实 key 则写进槽。api→cli→api 往返不丢 key。
- **配置 verify 失败不半写**:`api_set_llm_config` 加 `except HTTPException` 透传,verify 失败的干净 detail 不被二次包裹;失败时绝不 commit。
- **gameMenu CLI 字段从已存槽初始化**:用 persisted CLI 槽(`??` 容忍显式空)初始化,API 会话下不把 env 兜底的 API model 名当 cli_model 回传。

### 变更
- **单一真源收口**：`VALID_CHANNELS`、`CLI_DEFAULT_TIMEOUT_SECONDS`、`CODEX_DEFAULT_MODEL`/`CLAUDE_DEFAULT_MODEL` 常量化,替换散落字面量(#55)。
- `apply_llm_config` 拆成 `build_llm_config`(纯派生)/ `commit_llm_config`(落盘+重建)/ `apply_llm_config`(同步组合),支持 verify 与 commit 分离。

## [0.6.0.0] - 2026-06-09

### 新增
- **LLM 执行通道：API / CLI 并行、channel-aware**。`runtime_llm.json` 增双通道槽位（api / cli），`LLMConfig` 带 `channel` + `cli_runner`/`cli_model`/`cli_timeout_seconds`；readiness、模型构造、office 推断与落库 enrichment 全按当前 active channel 判定。脱-key 也能从菜单选 CLI 通道跑（`ApiSettingsModal` 加 channel 选择器）。`cli_backend_active(llm_config)` 单一真源门控 issue/office 的通道感知 enrichment。
- 单一真源 `llm_config.is_real_api_key` + `real_api_key_or_empty` + `CLI_BACKEND_PLACEHOLDER`：占位符只在 `create_chat_model` 构造 CliChat 那一刻注入，`LLMConfig.api_key` 对 CLI 通道永空；手动 key 输入口（getpass / 菜单 request / 局中 request）统一过滤占位符。`web_app._has_real_api_key` 委托同一真源。
- 架构决策记录：ADR 0001（API/CLI 双通道并行保留）、ADR 0002（用 action candidates 而非 tool-call 作游戏规则）。

### 变更
- `settle_with_delta` 增 `delta_applier` 注入闭包（与 `chapter_recorder`/`ending_summarizer` 同构）：merge base 的 ADR-0004 结算重构后，真实流经此闭包把 llm_config 送回落库 enrichment，结算核本体仍不依赖 llm_config；driver 默认 None 走确定性 apply（设 `MING_SIM_LLM_BACKEND` 时仍按 legacy env 判定）。

### 修复（pre-landing review）
- 显式 CLI 通道 `cli_model` 为空时不再把 API model 名（`llm_config.model`）当 `--model` 漏给 codex/claude，改回落 runner 默认（`cli_model_from_env`，agy 无 `--model` 故空）。
- 菜单 LLM 保存端点（`api_menu_save_llm` / `_menu_save_cli_llm`）的 verify smoke（CLI 子进程最长 `cli_timeout_seconds`）改经 `run_in_executor` offload，不再阻塞 asyncio event loop 卡住并发请求。
- 补测：`verify_llm_available` legacy env-only smoke 路径、`CliChat._call_cli` 未知 backend 兜底。

## [0.5.2] - 2026-06-08

### 修复
- 探针 driver `run_settle` 堵两处静默吞(codex 对抗 review）：falsy 非 dict 的 delta（`[]`/`""`/`0`）不再被 `or {}` 吞成空结算照样推进；未知顶层字段（拼写错如 `地区变更`↔`地区变化`）不再静默无效落库——两者结算前响亮报错、回合不半推进。

### 变更
- `docs/TODO.md` 移到根目录 `TODOS.md`（与 gstack 约定一致），标记城防炮(#4)/driver(#10)完成移入修复记录；CLAUDE.md 工作手册引用同步。

## [0.5.1] - 2026-06-08

### 新增
- **确定性结算核**：从 `decree.py` 抽出 `pre_settle`（固定财政 tick + auto_trigger）与 `settle_with_delta`（apply→turn_logs→章节记忆→inertia→clear→结局判定→next_period）。真实流程 `_settle_after_narrative`/`resolve_directives` 改调新核，behavior-preserving；章节记忆/结局总评做注入回调，使核不依赖 `llm_config`。真实流程与探针 driver 共用同一结算核（见 ADR 0004）。
- **探针 driver（`driver.py`）**：`state`（盘面快照）/ `settle --delta <json>`（注入我产的中文 schema delta 跑确定性结算、推进一回合）/ `dump`（地区快照）。`run_settle` 规范化中文 key→英文 canonical 并按 schema 校验各字段容器类型（畸形值结算前响亮报错、不半落库），落 narrative 到 turn_reports + canonical delta JSON 到 turn_extractions（供 replay/timeline 重建）；CLI `settle` 支持信封 `{narrative, decree_text, delta}`（裸 delta 兼容）。
- **城防炮 `region.cannon` delta 落库路径**：`地区变化` 新增 `城防炮` 字段，`apply_region_deltas` 特判路由到 `apply_region_cannon`（复用 `city_level×8` clamp，在白名单检查前），与军队 `随军大炮`（`cannon_equipment`）分域。

### 变更
- 城防炮补入 `REGION_FIELD_LABELS`（turn 日志显示「城防炮」而非回退英文 cannon）。
- CLAUDE.md「结算编排骨架」改述：driver 复用 `pre_settle`/`settle_with_delta`，不再自行复刻结算链（ADR 0004）。
- 新增架构决策记录：ADR 0003（人物相关 delta 合并为单 key + 显式动作意图，实现 deferred）、ADR 0004（探针 driver 复用引擎结算核）。

### 修复
- `db.py` 漏 import `LLMContractError` → 任何非法 `region_delta` 字段曾崩 `NameError`，现正确抛契约错（报清楚的合法字段清单）。
- 探针 driver 对畸形 delta（信封 `delta` 非 object、模块值容器类型不符）一律在动 DB 前响亮报错，不静默吞成空 delta 照样推进回合。

## [0.5.0] - 2026-06-08

### 新增
- **事件记忆系统**：每回合结算后自动提炼记忆卡，按人物/派系/官职类型建索引；大臣召见时注入「旧事记忆」块，上限5条，对话前后贯通。支持规则提取（`record_event_memories_from_resolution`）与 LLM 提取（`memory_extractor` agent）两条路径；每科目保留最近3条，超出自动剪枝。
- **推演记忆注入**：结算链新增 step 1.8——`memory_retrieval` agent 从本月诏书提取人名/地区/军队/势力/关键词（含可选 year/period），按 tags LIKE 匹配召回相关历史记忆（≤10条），注入 `season_simulator` 与 `score_extractor` payload；两个 prompt 同步说明字段含义与使用方式。
- **记忆自动衰减**：写入时按 importance 设 `expires_turn` TTL（importance 1→6回合、2→12、3→24、4→48、5→永久）；查询默认过滤过期记录，按年月查时可 `ignore_expiry=True` 追溯历史档案。
- **大臣按时间回忆**：新增 tool `recall_memories_by_time(year, period, keywords)`——时间查（精确该月，ignore_expiry）与关键词查（当前有效期内）合并去重返回；`memory-recall` skill 说明同步更新。
- **DB 索引**：`event_memories` 新增 `idx_event_memories_expiry(expires_turn, turn)` 加速过期过滤；`get_memories_by_keywords` 支持 `ignore_expiry` 参数。
- 后宫妃嫔卡片支持上传本机图片作专属立绘，存 `data/uploads/`，记入 `portrait_id`，重启后自动复用（`POST/DELETE/GET /api/consorts/{name}/portrait`）。
- 立绘工具脚本：`gen_portraits.py`（调生图接口出图）、`compress_portraits.py`（缩 512 压体积）、`portrait_status.py`（进度表）；附后宫预设图池与寝宫背景图。
- **军备两轴 + 城防（玩法机制）**：军队新增 `火器`（火器装备 0-100：鸟铳/三眼铳，野战+守城）与 `随军大炮`（随军红夷炮门数 0-12，攻坚利器但不利野战机动）；地区新增 `城市等级`（0-5 静态史实分级，京师 5）与 `城防炮`（城头红夷炮，上限 = 城市等级×8）。判战永远由 LLM 软判，引擎只 clamp 不算胜负。全层贯通（DB/extractor prompt/军表/大臣 inspect）。
- **CLI 后端探针（脱 api key）**：游戏可不依赖商业 api key 运行——LLM 后端在单一咽喉点改走本机 `agy`(默认)/`codex`/`claude` CLI（`MING_SIM_LLM_BACKEND=agy|codex|claude`），纯 subprocess，机器本地。补齐无 function-calling 带来的 toolcall 缺口（拟旨/密令入档、会话动作、地区/建筑 context 注入、国策实体后果补全）。详见 `docs/CHANGELOG_cli_backend.md`。

### 变更
- **推演 agent（season_simulator）改 skill+tool 模式**：不再把全量盘面静态塞入 payload；挂 10 个只读工具（`view_state`/`check_treasury`/`list_regions`/`inspect_region`/`list_armies`/`inspect_army`/`list_issues`/`inspect_issue`/`list_external_powers` + `submit_report`），按需查盘面，写完邸报调 `submit_report` 提交正文；`submit_report` docstring 承载完整奏章写作规范（结构/笔法/局势/末章/禁忌），`season_simulator.md` 从 141 行精简至 54 行。
- **结算 agent（score_extractor）改 skill+tool 模式**：payload 去掉 regions/armies/buildings/ministers 五张全表，只保留 narrative + issues摘要 + id列表 + fiscal_config；挂 7 个工具（`get_region`/`get_army`/`get_external_power`/`get_active_ministers`/`get_issue_detail`/`get_faction_class_state` + `submit_extraction`），按章节按需查当前值算 delta；`submit_extraction` docstring 承载完整 JSON schema、16 字段约束、档位标准与骨架示例，`score_extractor.md` 从 266 行精简至 50 行；去掉 `force_json_output`，改由 tool docstring 约束格式。
- **CLI 后端会话落地收敛单一真源**：`session.apply_cli_conversation_actions` 同时供命令行（`session.chat`）与 web 流式路径调用，杜绝两边逻辑漂移；官职分类改走 `content/offices.json` 参考表（替代旧正则词表），无 CLI 后端时落「待铨」graceful。
- **国策实体后果三结案路径对齐**：issue 经 tracker advance / close / 自然惯性（inertia）任一方式结案，都落 `effect_on_resolve/fail` 的建军/补兵/人物状态/帝国修正，不再只有部分路径生效。

### 修复
- 密令「更新」按精确 id 改对应那条（多条 active 时不再改错条），更新不清空原标签；催办对 pending_review 不抛错。
- CLI runner（agy/codex/claude）检查退出码/空输出即抛错，不把 auth/quota 失败当空回复或角色文本落库。
- 落库守门：国策效果字段非 dict 不再崩整月结算；`apply_score_extraction` 非法 delta 严格抛错不静默丢；CLI 后端国策保底有回报，绝不入空壳。
- 火器/随军大炮新档贯通（fresh seed 不再全 0），动态新建军可按 id/名查详情。

## [2026-05-24]

### 新增
- 后宫系统：打通选妃流程，司礼监从秀女池遴选候选呈选、降诏册封入宫；调教 tool 提权，妃嫔学技艺/改性子写入永久记忆；修复 candidate 升格。
- 人物据实奏对：大臣与月末邸报按在朝名册查现职状态，不再凭史实记忆乱报官职；朝堂名册按官品排序。

### 修复
- 财政：`economy_moves` 的 account 按钱实际出自哪库判定，不再按用途误判。

### 文档
- README 重写「已实现」为分模块表格；补后宫、省级财政、月度收支、人物头像等说明。
- 立绘提示词改现代古风；新增 GPL-3.0 许可证。

## [2026-05-23]

### 新增
- extractor：支持人事任命与人物状态变更落库；开局校准到 1627.10。
- 网页结算悬浮框加「本月一次性入账」段；建筑支出改走内库。

### 变更
- 推演重构：叙事零数值化，extractor 按章节扫描，prompt 瘦身。

## [2026-05-22]

### 新增
- 建筑系统：御窑厂/边堡/仓储/工坊/河工，等级状态维护产出按月落账，新建须立项推进；推演 token 优化与遥测。
- 网页地图节点重定位与取点工具；菜单改中央弹窗。

### 文档
- README 加游戏截图与头图。

### 杂项
- 移除 `.vscode` 出版本管理。

## [2026-05-22] — 首次公开发布

晚明对话式政略模拟器初版：月度回合制、大臣召见与拟旨、诏令结算、月末邸报、两京十三省与军队/外部势力盘面、CLI 与网页双端、本地存档、内容外置。
