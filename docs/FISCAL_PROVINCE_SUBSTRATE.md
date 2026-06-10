# 省级财政基座 · 草表 v23(spike G1–G22 · 三饷计火耗)

> **范围:仅锁单省 spine(陕西);跨省 hub deferred;`拨付net/gross` 为 tick 外部入参(测试默认 0)。**
> **对账方法学(r13–r15 逐层返工锤定)**:三类断言(现金守恒/债务 per-account/C per-account)的期望值**全用独立 oracle**——只从 tick 输入(`st` 开账快照 + `p` params + `actions`)重算,**绝不读 settlement 的任何中间量**(火耗应派/起运池/实征/k/省内可支)。否则校验项与被校验项同源=tautology,一致 relabel 照样过(opus 逐层逮到三层:per-account 流水→上游 param→力度系数 k)。
> spike **G1–G22 全 PASS**(5层断言+输入校验面完整[action字段/rate/param量纲/开账stock 负值全 fail-loud];r21 补 param/stock 负值校验,防负Due/负起运/负拨付凭空生钱);自变异实证:中饱→省库、火耗→省库、军饷新债→官俸欠、虚增火耗×2、起运去 clamp、k 砍半、漏三饷火耗、三饷火耗×2 —— **现金/总量守恒全 PASS,但独立 oracle 当场 FAIL**。残留仅 `o_pool` 读省内可支(C-oracle 兜底,已注释)。
> 评审 r1–r15(panel=codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 账户模型(三类 · spike 口径)
- **CASH(真金,跨账户守恒,万两)**:`省库库银`(A-stock,跨期)· `C_地方截留`(火耗实收)· `C_中饱` · `C_漂没` · `C_eff损耗`。
- **BOUNDARY(系统边界,记净流,非引擎余额)**:`民间`(征收 source:实征+火耗实收 从此交出现金)· `受款方`(支付 sink:起运到京 + 实付 + 偿旧欠 流入)。
- **CLAIM(债权债务,非现金 memo)**:`B.民欠旧赋`(民欠官,债权)· `B.军饷欠/官俸欠/宗禄欠`(官欠受款方,负债)。
- **Flow(每 tick 清零)**:正赋/三饷/火耗应派 · 实征 · 火耗实收 · 起运池/省内池 · 起运到京 · 拨付net · 清欠/追赃/挪借入库 · 省内可支 · 应付/实付 · 新增欠账 · 偿还。
- **钱类 CASH/CLAIM stock 只经 `delta`/`transfer_to` 变动,禁 `set`、禁 `scale` modifier。**

## 0.1 守恒不变式(spike G1–G7 实测残差 0;含 r11 修正)
**主断言(现金双边平)**:
```
Δ(Σ CASH) == CASH_in − CASH_out
  CASH_in  = 实征 + 火耗实收 + 清欠 + 拨付gross        (民间补缴 / 京饷注入)
  CASH_out = 起运到京 + Σ实付(军饷/官俸/宗禄/赈济) + Σ偿旧欠 + Σ(补饷/行政 action 现金支付)
  注:挪借火耗 / 追赃(C↔省库)是 CASH 内部转移,ΣCASH 不变,不计边界流。
      拨付以 gross 入(net→省库、中饱→C_中饱,均留 ΣCASH 内)。
```
**断言用「独立 oracle」(r13/opus 关键:期望值必须从 tick 输入参数独立重算,不能用落账时同源记的流水——否则校验项与被校验项穿一条裤子=tautology,一致 relabel 照样过)**:
**C 灰账 per-account · 独立 oracle**:每个 C_ 子账户期望从 params 重算 —`C_中饱应得≡拨付gross×中饱率`、`C_漂没应得≡起运池×漂没率`、`C_地方截留应得≡火耗应派×(1−逋赋率)−挪借出`(火耗应派=(正赋+三饷)×火耗率,v23)、`C_eff损耗应得≡Σ(transfer actual×(1−eff))`;断言 `实际落账==应得`。
**债务 per-account · 独立 oracle**:从 Due(param)+claim0+action入参 重跑 waterfall/偿还,固定科目映射(军饷→军饷欠…),断言每科目 `claim==重算值`。
> **自变异实证(spike)**:中饱→省库、火耗实收→省库、军饷新债→官俸欠 三种**一致 relabel**(落账+记账同步搬),现金/总量守恒全 PASS,但独立 oracle 的 per-account C / 债务 **当场 FAIL**。旧的「同源流水」式(v13)放过这些,独立 oracle 堵住。
**每笔 `transfer_to` 三方平**:`source减 = target增(actual×eff) + C_eff损耗增(actual×(1−eff))`(`actual=min(amount,source)`;BOUNDARY 账户 民间/京/受款方 **无余额 clamp**)。
> 旧式「三本账总额=拨付−起运」及 v11 漏 拨付net 的式子**均作废**:r11/opus 变异测试实锤 —— 旧式是 tautology(火耗应派≡火耗实收+火耗未收,永真),v11 式漏 拨付net(设 20 跑出残差+20)。现式 spike G1–G7 全 PASS。
> **port 安全锁(r22/opus 实证)**:债务 oracle 的 `o_pool` 读运行时 `省内可支`(唯一残留同源),故**现金守恒层是债务 oracle 的兜底,绝不可删**——能污染 `o_pool` 的 bug 必然改动现金可支量、从而破现金守恒;「既现金中性又改 `省内可支`」的 bug 自相矛盾不存在。port 写 pytest 时删现金守恒断言会让债务 oracle 单独退化成 tautology。

## 1. 单位制 + cost_type(同 v10)
年额÷12·月额万两/月·stock万两·税额两/亩·年(非0-1)·真率0-1。action「银」amount=每tick成本,cost_type=one_time/recurring。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫,同 v10)
⓪ Flow清零→modifier衰减→**收集本tick action→先算 k(`k=min(1,Stock_start/Σ_{cost>0}银Cost)`,Stock_start=上月结转)→再按 k 执行 action**(transfer 此时执行)。**0-cost action 的 amount 不受 k 缩**(spec §6);clamp 到 0 的成本仍占 ΣCost 分母(=预算承诺语义,守恒不破,非 bug)。`省库库银_post=Stock_start−Σ(k·银Cost)`。
①折月 ②③应征 ④火耗应派→民负担(未实收不积欠)⑤⑥负担率/逋赋率(灾→下限)⑦实征→可支、火耗实收→C、民欠→B ⑧`起运池=min(实征,定额)`/`省内池=max(0,实征−起运池)` ⑨漂没→C ⑩拨付gross扣/net→可支/中饱→C ⑪付款+偿还+结转(省库库银_new=S,覆盖写)⑫(全局)国库入账。

## 3. 付款 waterfall / 4–5. schema / 6. 执行归一化(同 v10)
1军饷>2官俸>3宗禄>4赈济(Due_4=action amount,NewDebt_4≡0);民欠=清欠/蠲免无官偿还;火耗实收进C需「挪借火耗」action 转出。
k=action力度系数(ΣCost仅含action银,Due不入;Cost>0 action其 delta/scale/transfer_to.amount 全×k;0-cost不缩)。modifier `V_final=clamp(V_base×∏max(0,1+scale)+Σdelta)`,V_base静态不复利,钱类Stock禁set/scale。transfer_to source/target 类型白名单(CASH/CLAIM/BOUNDARY 或指定 Flow)。
**现金 action 二选一**(防双扣):支付类(补饷/赈济)= 银 Cost 即该笔支付,不再另记 Due;行政成本类 = Cost 扣省库,另带 effect。(spike G2 已验补饷 k=0.333 无双扣。)

## 6.6 golden-tick(spike 实测 · G1–G22 全 PASS,5 层断言:现金守恒/债务对账/C per-account 对账/末态硬期望/土地守恒)
见 [spike_settle_tick.py](../spike_settle_tick.py),已执行,残差均 0:
- **G1** 基线 · **G2** 补饷 k=0.333(死亡螺旋+无双扣)· **G3** 清丈(官民田3050→3350,当 tick 扣成本2)· **G4** 挪借火耗(C 内部转移)· **G5** 漂没.1+中饱.1+拨付30(漂没→C_漂没/中饱→C_中饱/net→省库)· **G6** 超额补饷 clamp(欠5补30只还5)· **G7** 清欠(民间补缴现金入)。
- **G8** 挪借 eff=0.8 → 激活 C_eff损耗(2→损耗账户),per-account 对账平。
- **G9** 三 tick 链(穷省+recurring 营建):死亡螺旋实显——军饷欠 30→61→97→133(期初→各tick末态)、火耗在 C_地方截留 累积 9.8→19.6→29.4(官绅肥/官衙穷),每 tick 5 层断言均 PASS。
- **G10** 追赃 · **G11** 多 costed 共享 k · **G12** 赈济 Due>0 · **G13** 拨付+追赃同 tick · **G14** 动态税基(清丈抬税基)· **G15** 双债户偿还序(军饷>官俸)· **G16** 清丈枯竭+土地守恒 · **G17** 赈济饿死(unmet_relief)· **G22** 三饷火耗分量(三饷30→C_地方截留12.6,漏派必 FAIL)。
- **5 层断言**:现金守恒 / 债务 per-account oracle / C per-account oracle / **末态硬期望常量(第4类独立锚)** / **土地守恒(Δ(官民田+隐田)=0)**;+ 输入校验 fail-loud(eff/amount/cost/rates 越界、补饷带 amount → raise);+ 输出 `unmet_relief`。
- **自变异实证(全被某层 FAIL)**:中饱→省库、火耗→省库、军饷新债→官俸欠、虚增火耗×2、起运去 clamp、k 砍半、补饷只减欠不扣省库、清丈×2、偿还序 flip、清丈凭空造地、unmet 漏算、漏三饷火耗、三饷火耗×2。
- 仍待补(port TODO):recurring k=0 停工语义、跨 tick「期初==上tick期末」断言、arrears_allowed。

## 6.7 可执行 spike(golden 种子)
`spike_settle_tick.py` = 纯 dict 复式记账原型(非引擎、throwaway),实现 ⓪–⑪ + §0.1 守恒断言,跑 G1/G2 打印逐步流水 + 守恒 PASS/FAIL。**它就是将来真引擎 golden test 的种子**:port 进 `ming_sim` 时把 G1–Gn 转成 pytest 断言即可。

## 7–8. 状态/派生/螺旋/铁律/实现规约(同 v10)
死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性,G2 已显现)、5 铁律见 ADR 0007;逋赋率 clamp(0,1)、民欠蠲免 max(0,·);实现规约五条 + §6.6/6.7。

## 9. r16 整体评审落字(设计澄清 + port TODO)
**已锤定的语义(写进 spec,防 port/LLM 裁判踩坑):**
- **现金 action 的 cost 必须真扣**:征收/转移类 action(清欠/挪借/追赃/蠲免)若带 `cost`,该成本必须真从省库扣(走行政成本路径),否则禁带 cost。**不许「cost 进 k 分母却从不落账」**(否则静默吞成本只缩力度)。`补饷` 的 cost 即支付本身,且 `≤ 当前军饷欠`(超额部分不花,见 G6);`补饷` 不接受 `amount` 字段。
- **§2⓪ 公式精度**:`省库库银_post=Stock_start−Σ(k·银Cost)` 仅在所有 costed action 花满时取等;补饷 clamp 到欠额时实际 `省库库银_post ≥ 公式值`(余款不花)。LLM 裁判须知:这是「圣旨锁了预算却没花完」的官僚损耗,不是省库凭空增加。
- **C 账户可回收性**(三道漏不对称,LLM 裁判据此叙事):`C_地方截留`→「挪借火耗」可回收 · `C_中饱`→「追赃」可回收 · **`C_漂没`/`C_eff损耗`=不可回收 sink**(运损/行政摩擦,沉没)。
- **C_中饱 vs C_eff损耗 叙事区分**:`C_中饱`=主动贪腐(有人拿走,触发弹劾/民愤)· `C_eff损耗`=行政摩擦/运耗(烧掉,无主),裁判勿混为贪腐。
- **死亡螺旋的「破局」出口(铁律①:非剧本死局)**:确定性账本里下行=参数+action,**上行通道完全交给 LLM 软判**——招抚流民→逋赋率降、追赃/挪借→现金注入、清丈→税基扩、缓起运/截留京运(改起运定额,代价由 LLM 判:京师缺饷/户部弹劾)。账本读起来「单调恶化」是表象,出口在软判,不是必死。
- **赈济**:未付不积欠(NewDebt_4≡0),但引擎须输出 `unmet_relief`(=Due_4−实付)给 LLM,否则裁判看不见「灾民没拿到钱」。
- **挪借/追赃 时序不对称**(r18/sonnet):挪借在 ⓪ 执行,取的是 **tick 开始前的 C 存量**;本 tick 新增的火耗实收(⑦)/中饱(⑩)要下 tick 才能挪。史实:官员当月收的火耗,皇帝当月调不动。
- **偿还/付款三债户优先级**已 golden 钉死全序:军饷↔官俸(G15)、官俸↔宗禄(G18 waterfall / G19 repay);征收/转移类 action 禁带 cost(spike fail-loud,防幽灵预算压 k)。

**史实校准(spec §1 已标⚠️,port 前必做):**
- spike base 数值是**游戏校准占位、比率关系对、绝对量级偏史实约 3–10×**(正赋 720万/年 vs 陕西实际约150–250万),`官民田` 单位=万亩;port 时按 Sources[1][2] 重标,勿把占位当史实锚点。
- **三饷按时间线拆**:辽饷(万历末起,崇祯四年增)/剿饷(崇祯十年,1637)/练饷(**崇祯十二年,1639** —— 杨嗣昌十一年议、十二年行;原误作十一年),seed 不能把三者都当开局常量;字段可叫 `三饷应征` 但分量分时间线注入。1629 开局只该有辽饷。
- **三饷计火耗(2026-06-10 拍板,v23 实装)**:`火耗应派=正赋火耗+三饷火耗=(正赋+三饷)×火耗率`,两分量另立(三饷分量随辽/剿/练饷时间线注入而消长)。史实依据:三饷亦以银征、同样加耗。v22 前曾误标「有意简化」——该取舍从未真正决策过;补全后 golden 全部手推重算(base 参数下 C_地方截留 8.4→9.8,差值=三饷火耗 10×0.2×0.7=1.4),G22 专钉三饷分量(漏派则必 FAIL)。

**port TODO(spike→真引擎时补,非当前 spine 缺陷):**
- recurring obligation 持久化:k=0(穷省)时军事/俸禄类强制转 Due 成债(停饷即叛),工程营建类挂起进度 0——需 spec 显式锁。
- 跨 tick「期初==上 tick 期末」显式断言;`arrears_allowed` funding mode(赊欠/开空票,晚明味,未付进欠账+LLM 判怨气);同类 action 建议合并(重复按 list 序执行,累计不超总欠)。

## 待精验
各 f() 具体形 · G3–G5 golden 数字 · 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
