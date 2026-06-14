# 四层票拟 + 中旨 + 执行层（决定4/5）— dig（2026-06-14，承 #112，圣旨颁布阻力网心脏）

> 全量在 task 输出：`/private/tmp/claude-501/.../tasks/wyw2m5rz7.output`（5-agent：ground颁旨链+四层史实 + 3路设计 + 合成）。**设计累积，待用户拍5问 + 跟整体走 CMR。最重最后，硬依赖血债 schema 先落。**

## 核心：resolve_directive(action, substrate, mode) 一次幕后纯函数
- 读全 substrate(dig-5矩阵/dig-4血债+失称度/dig-6认同度/ceiling)→短路出 ResolveResult{outcome, blocked_layer, exec_fidelity, per_layer诊断串, 反咬列表, 机械后果包}。**LLM 只叙事、零算账**(镜像 settle_tick)。
- **召对侦察=同函数 dry_run=True**(单一真源，侦察=实际resolve口径，玩家能信；严守只读不落库不推回合)。
- 彻底替换 estimate_resistance(tools.py:148 拍平启发式)；插 propose_directive(tools.py:254)后、落 directives 表前。build-upon ADR0004 pre_settle/settle同核 / 0008 atomic / 0009 reason_code。grep实证四层逻辑零存在=纯net-new。

## 四层（各读不同 substrate，故"同一道旨撞的层不同"）
1. **内阁票拟**(软否决:封还/拟温和版/辞职逼宫)——东林+中立把着，读dig-5东林礼法/祖制轴立场+dig-4血债floor。中旨绕此层。
2. **司礼监批红**(阉党承重功能=决定8)——阉党核心把着，读阉党satisfaction/leverage+dig-6 identity。**清了阉党→从"顺"翻"失能阻力"=自我致盲**(北极星；根因B1/#9退场leverage联动未做)。
3. **六科封驳**(硬否决，最关键，中旨天敌)——六科+御史，读①ceiling②是否中旨③**失称度**。破局核心层。
4. **部院执行**(阶段二:忠实/打折/阳奉阴违/反噬)——承办派把着，读dig-5立场+dig-4血债+dig-6 identity。FF-5承重功能负片在此(阉党瞒报/军队哗变/中立怠政/东林清议/宗室串联/西学撂挑子)。后果落issues停滞+factions离心，不扩status enum。

## ⭐ 破局机理（今晚所有设计汇成一回路）
抄既得权贵(命门，ceiling高会被挡)：硬推→血债+69(罗织、失称度饱和、六科顶封)。**聪明解=先查办坐实真罪**(走actor取证厂卫/政敌/苦主)→**旨意轴方向翻转**:"任性夺权(撞礼法)"→"依律惩贪(合礼法)"→**矩阵符号翻**:东林从封还变背书、六科无从科参→顺颁+血债+7。**同道旨走程序vs硬推差8.7倍。不是绕ceiling，是把动作从命门题变非命门题。** 串起失称度+矩阵+seed-guilt(真靶子)+actor取证+认同度(善待边缘人→反正→取证的刀)。史实锚=定逆案262人走程序清阉党 vs 国本之争硬撞祖制15年完败。

## 中旨
绕内阁(L1置0)=唯一买到的；六科照样封驳且陡升(MIDZHI_PENALTY)→行政旨几乎无伤、命门题照样打回(白绕还多担非正途污名)。代价曲线=命门陡/行政平。三代价落库(STIGMA reason_code→血债陡+edict_overdraw+污名)。provisional/未生效标记(H6，**钱拨了被封驳=没了**，status真闭涉钱W=1不全闭，转final放settle后半段atomic对before_turn幂等绝不放pre_settle)=第二刀。乱用→edict_overdraw螺旋但留窄路非钦定。

## 自检全过(10条) + 硬序
轻交互真没堆成CK3(一次resolve、blocked_layer只邸报复盘) / 读substrate对(逐条核dig值) / 破局非灭亡(ceiling硬墙但走程序压成顺颁、dig-2红线守死不内嵌判负) / 中旨provisional自洽(残留诚实标) / gaming扫三洞 / build-upon 0004/0008/0009。**硬序铁律=血债schema+矩阵42格值+identity列+seed-guilt 先落(现grep命中0全设计稿)，否则resolve读空值退化纸面、破局无substrate可读。别先搭四层框架。**

## scope
- **硬前置**：血债schema(血债/wariness/edict_overdraw列+centrifuge_log+失称度公式) + dig-5矩阵42值 + dig-6 identity列 + seed-guilt 预装。
- **第一刀**：resolve_directive确定性骨架，**只做阶段一颁布 顺颁/打回 两档**，替换estimate_resistance；召对dry-run只读；邸报复盘；打回→二次决策点。
- **defer第二刀**：中旨闸整套(provisional/edict_overdraw)；执行层四态细分(先粗做忠实/打折两档可选)；provisional生命周期；召对location闸(FF-4)。
- 评审：落sub-ADR走完整CMR(设计文档同等评审)；dig-6 kinship去max(1)改动带进重确认；初值拍后跑独立oracle+末态硬期望(镜像spike G1-G22方法学)。

## ✅ 用户拍板（2026-06-14）— 待填
1. **ceiling表**：lean 跟矩阵42格一起拍(co-依赖)；"出路杠杆恒可达"硬不变式先锁。【唯一真缺的设计块】
2. **第一刀切到哪**：lean 严格只颁布关顺颁/打回，执行层defer。
3. **中旨"一意孤行"第一刀**：lean 给但映射"硬推必碰壁打回"(埋伏笔)。
4. **合成口径**：Claude直接取 逐层短路出blocked_layer(实现细节，邸报/破局都要"卡哪层")。
5. **kinship改动评审捆绑**：lean 血债sub-ADR带它、四层票拟另起sub-ADR。
