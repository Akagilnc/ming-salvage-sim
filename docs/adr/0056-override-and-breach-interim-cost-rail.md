# 0056: 强颁与毁约的 interim 代价轨——#226 排进本闸，修订 0013「无损可撤」

Status: Accepted（2026-07-04 随 PR #573 合入；决策：2026-07-03 #474 设计闸 grill 用户拍「强颁还是有点代价吧，扣皇威+分派系满意度，暂时简单粗暴」+「#226 同意排进」；**2026-08-12 owner correction**：satisfaction 反应可正/负/零，入清单不默认负向，废止「受损方/只扣减」；**精确机器 shape / 枚举 / 出场 / 映射 / 毁约派系源 = #564 Implementation Decisions**，本 ADR 只留不可逆政策）

**强颁**（批红页强颁；预先中旨直发经判官 mode=中旨 顺颁时同此——中旨非跳过判决，0055 cmr R2）当回合确定性落三笔：①皇威扣——皇威已有真牙（辽饷到账率随皇威折扣；扣皇威=真银少收）；②**分派系/阶级 signed satisfaction 反应**——颁布判官产出反应方 typed 清单 → **确定性代码**映射为 signed delta（faction→faction_delta、class→嵌套 class_delta；**不经 extractor LLM**）；③中旨标记（append-only `stigma_json`，项含既有 `reason`——**schema 归 S1 / 写入归 S8**；本轨只与①②齐套消费/验收，**不新增缘由字段或平行写口**）。**mode=中旨 被打回的 attempt 同样落②③（payload 效果与皇威扣不落）**——0011-5「白绕还多担污名」；判官对 mode=中旨 案卷无论判向一律输出非空反应方清单（正规案卷仅打回时输出）。**代价幂等**：三笔只在强颁或 mode=中旨 attempt 时落——正规打回零代价；幂等判据=代价流水存在性（与中旨标记解耦）；已落②③的中旨案卷强颁只补皇威；留中重判被再打回不重复落。

**不可逆语义（owner 2026-08-12）**：反应可正、可负、可零；**不得**因入清单就默认负向；零反应以省略表达。机器只消费 typed `direction`×`intensity`；判官自由叙事措辞**不参与**机器匹配（反盯文）。精确字段名、必填键、枚举、出场规则、确定性映射常量、毁约「当事大臣」与相关派系源 = **#564 Implementation Decisions**（唯一机器契约；#556 只指针、不另维护逐字副本）。

**毁约**（撤回成命 0041）走同一根轨：皇威＋当事大臣观感＋相关派系各一笔 signed satisfaction 反应——**#226 就此排进本闸**，显式修订 0013「无损可撤」（机械可撤性 cancellable='decree' 不变，新增代价落账）。人物观感 interim 复用既有 `relation_edge_events`（`event_kind=辜负`），禁止第二套人物观感表。satisfaction 在颁布/执行阻力路径今日零消费方；派系 satisfaction 的牙由 0057 执行走样环装上；阶级 satisfaction 本轨只落账。量级数值不进 ADR，playtest 调参。M12 血债棘轮建成后本轨被吸收。P4：呈现全定性，不露数。
