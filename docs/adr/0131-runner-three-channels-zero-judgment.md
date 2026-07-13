Status: Accepted（2026-07-13 owner 当日裁决成文；本 ADR 为口谕的 canonical 落笔，被取代旧条款见「取代」节）

# 0131: runner 三通道零判断权——交通警察总纲（自报数 + fixer 判卷 + 一次上抛）

## 决定

runner 只准做三件事，三件之外零判断权：

(a) **数 exit code**——进程死活。真进程级失败（非零 exit / 抛异常 / 无完成信号）的有界机械重试挂在这条通道上（#598 崩溃半边、#853/#855 park-retry），不读任何字。

(b) **读 reviewer 自报的 open-count**——说几条就是几条：0 = 收敛关环，>0 = 派 fixer。count 是 worker 的申报（自报哨兵值；无哨兵形态的路径以其写下的行数为申报），runner 不派生、不复核、不拿数组长度对账、不读 severity/action 做二次分类。申报与卷面不符由 fixer 读卷时发现。

(c) **转决策门**——worker 自己按的 decision/raise 原样递给人，转运不裁决。

**从不读字。** 卷面对不对是下一个智慧体（fixer）的判断：读不懂 → raise（走决策门）或打回 reviewer。**卷面不可用**（信封提取不出：无 kind / 无计数 / 解码失败）→ **callerOwns，一次 escalate(kind=decision) 给人拍，零机械重派、零重写梯**。synthesizedFailure（runner 替 worker 合成的 escalate）仅允许由通道 (a) 的进程事实派生（崩溃重试耗尽的 infra 包），永不得由卷面判断合成。kill-axis（承 #873）：任何拆除不得以「换一个更温和的校验」收尾。卷面质量归交卷契约（ADR 0130，worker 侧 soul/skill）；发现搬运走 artifact pointer / findings 状态库（ADR 0129）。

## 取代（旧 ADR 已就地标过时并指针到本 ADR）

- **ADR 0050**「malformed 到 runner → 令同 worker 重写 cap 2 → infra escalation」及「outcome-guard 住 runner/image 层校验 format/schema/字段/证据」——**废止**。worker 发完成信号前自验半句仍成立（归 ADR 0130 交卷契约）。
- **ADR 0062** 信封宪法段「缺覆盖 = malformed outcome → 机械重试重派 reviewer」半句、typed-治理澄清段（「outcome-guard 必须在 worker 之外的 runner 层」及其形状/治理校验派生信封）——**废止**；0062 三通道母法与决策门 durable 语义保留，通道 (b) 语义改为本 ADR 自报数。0050 立法理由（被守护者自守漏洞）的新解法 = 下轮 fresh 复审验真 + fixer 逐条实证（0129 沿革段：形式核验本就拦不住填表完美的假话）。
- **ADR 0030** 裁定状态段（runner 覆盖断言 / 压制预算 / 翻案计数器）——0129 已拆，本 ADR 重申不得复活。
- **ADR 0129** 写入点校验条款**限缩**：不含 count-vs-array 对账（count=自报）；「拒收→同 worker 重写」梯废止——不可用一次 decision 上抛。findings 状态库、交通警察定理、fresh 终翻规则不变。
- **#598 验收第 1/5 条** malformed-shape lane（「过不了 runner 下游 schema 再校验 → 当 process-level malformed 机械重派」）——**废止**；进程崩 lane 保留。
- **#875 信封票 §1/§2**（count 由数组派生、写入点 count-vs-array 拒收 + 重写反馈）——**废止（S1b，2026-07-13）**；§3「下游禁一切 shape 处置」保留并加强（连数组长度都不数）。
- **orchestrator/README.md Constitution 节**「defective report = shape failure → 有界机械重派」corollary——按本 ADR 重写（同 PR）；其防拆测试钉 `test/adr-0062-regression-825.test.ts` 随实现翻转（#873 战役工单）。

## 后果

全部 runner 侧 isValid* 法庭、count 对账 / 重写梯、malformed 计次机械重派线按本 ADR 拆除；实现细节归 #873 战役工单，不进本 ADR。操作面镜像：`orchestrator/CLAUDE.md`「铁律 0」（评审判卷首读，与本 ADR 同源同 PR）。
