# r7 · 干净上下文 subagent(v7)

> 两个 fresh-context subagent 冷读 v7(只读该文档,不带前序)。2026-06-09。
> **价值:逮到六轮外部 CLI 几乎集体读过去的硬伤 —— 尤其「省内可支总公式」在 v7 被引用却没写出(v6/codex 给过,压缩时漏抄)。**

## opus 4.8 — 判定:spine 还不能锁(最深最狠)
5 处真分叉:
1. **「省内可支」总公式缺失(硬空洞)** —— §8 三次指向自己却没写出;整条现金流靠一个未定义符号。**架构级主梁缺失。**
2. **transfer_to efficiency 蒸发不入账** —— `efficiency<1` 时差额 `actual×(1−efficiency)` 凭空消失、无 sink;防印钱却变成凭空**销**钱,守恒只单向成立。
3. **⓪ 衰减时序矛盾 + new-action modifier 生效时点** —— §6.3「衰减在⓪前」vs §2「衰减是⓪内第一步」;「初值 N」未定义;本回合下旨的 modifier 当回合生不生效两人会写反。
4. **0-cost × 离散 set 互斥** —— §6.2(0-cost 不缩)与 §6.3(k<1 离散 set 不触发)对同一个 0-cost 离散 set action 给相反结论。
5. **实征产生式结构未定** —— 征收能力进不进 ⑦ 乘式、以什么算子进,是结构(spine)不是数值(待精验)。
+ B_i,old vs old+NewDebt 偿还消歧 · 付款/偿还优先级倒置无 rationale · 标题「省级基座」但内容单省(陕西),跨省 hub 分配零字,应声明「仅锁单省」。

## sonnet 4.6 — 判定:基本可锁,差两步
- 必补:① ⓪ 多 action 是「全部 resolve 再批量算 k」一句 ② transfer_to `efficiency` 未指定默认 1(否则一实现者默认 0=黑洞)。
- 字面有算式漏:省内可支总公式空洞;`省库库银结转=S` 与 §0 不变式的「本月支出是否含⓪成本」未封死。
- 顺手:B_i,old/new 偿还消歧;赈济 `Due_4` 来源(action amount?引擎?)要写明。
- 无架构返工,补两句即可。

## 横评要点
- **4/5 声(codex+agy+opus+sonnet)都点了「省内可支总公式缺失」+「transfer_to efficiency 差额去向」** —— 唯 grok 漏(第四轮仍 rubber-stamp「可锁」)。
- v7 是压缩时引入的**回退**:总公式 v6/codex 给过,v7 引用却没抄。fresh 眼睛逮住了 context-saturated 评审读过去的洞。
