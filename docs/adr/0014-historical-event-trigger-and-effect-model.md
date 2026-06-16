# ADR 0014：历史事件触发与后果模型

- Status: Proposed（2026-06-16 grill-with-docs session 收敛；待评审闭环：本地 cmr + 线上 bot）
- 关联：#174（16 历史事件 trigger_gate 全空）、#12（毛文龙误触发根因）、ADR 0008（段适配器/拒收契约）、ADR 0009（人事动作）、ADR 0011（actor 博弈/#87 否决网）

## Context

`content/events.json` 16 个历史事件 `trigger_gate` 全部为空 → `_gate_passed(空)` 恒真 → 事件照日历硬弹（毛文龙在玩家已安抚前提下仍被误斩，#12 根因）。引擎侧前提门机制已就位（`issues.py:365` `gather_candidate_events` 已对历史事件跑 `_gate_passed`），缺的是结构化门 + 后果落库。

本 ADR 经一场 grill-with-docs 设计 session 收敛，固定「历史事件」这一有状态实体子类的**触发与后果模型**。核心立场：**设计驱动代码**——不让引擎现状（如 `GATE_TABLES` 不含 character、`power` 写白名单窄）反过来阉割设计，该改引擎就改。本项目连圣旨都可被否决（ADR 0011/#87），上游遗留的一个常量不是天条。

## Decision

### 1. 历史事件 = 三件套

- **触发门（trigger_gate）**：DB 状态谓词，纯 AND（全部满足才触发）。分三类：
  - **可避**：玩家处理史实成因即破任一条 → 跳过/改写。
  - **半可避**：外因消不掉（如后金主动入塞）但留改写口。
  - **天定**：空门 `{}`，到点必触发（纯天灾 / 不可取消的外患）。
- **确定性后果（guaranteed effect）**：每事件挂一份核心后果 delta，**触发即由引擎强制落库、不过 LLM**。事件的机械后果不赌 LLM 记得写（否则放空炮，违「决策即落库」铁律）。
- **LLM 叠加**：extractor 软判细节（波及范围、失守哪城、叙事），走现有 delta 管线。

### 2. character 进 GATE_TABLES（引擎改）

人物身份/死活/在任是历史事件的核心条件，不该用军/地区硬代理绕。`_eval_gate_key` / `_eval_gate_key_str`（`issues.py:192/278`）各加一个 `character` 分支（`SELECT {field} FROM characters WHERE name=?`），`GATE_TABLES` 加 `character`。可查 `status / faction / power_id / office`（文本）、`loyalty / ability / historical_death_year`（数值）。

### 3. 人物核心事件 = 玩家用人的后果

史实里袁崇焕、卢象升开局都**不在招祸的位子上**——是崇祯后来亲手起复/升迁才把他们放到前线，才有下狱、殉国。故这类事件**只在玩家把人放到位之后才触发**（diegetic：历史经皇帝之手发生）。门查「任命已写的可查信号」（所统军 `commander` / `power_id` / `office`），开局不在位则门 OFF；没任命就不触发。

配套：**修种子**——`armies.json` `guanning.commander` 当前=袁崇焕，与 `characters` 中袁崇焕「罢居东莞」矛盾、且 1627-10 史实袁已被逼走，关宁主帅不应是袁；改为 1627 真实态（袁为罢居/听用候铨，关宁主帅另置）。

### 4. 流寇 = 头目 + 股（分层）

流寇在 DB 是两个实体：**头目**（character，`power_id=bandits`）+ **股**（`power.bandits`，聚合 `military_strength`）。流寇事件**分层 gating**：头目身份（`character.李自成.power_id==bandits`）给「是不是流寇」，股实力（`power.bandits.military_strength`）给城破烈度。

**招安** = 易主（→ming）+ 任命武将名分 + **削股**（`power.bandits.military_strength` 按头目分量降）；**再叛** = 易主回 bandits（张献忠谷城再反正是「受抚→再叛」反向用例）。招安削股使「招抚 vs 清剿」都成破局 lever；招一个头目 ≠ 流寇全消（残部/换头目延续，符合史实）。受抚头目实际兵权 defer（首版只给名分）。

## 三个权衡（为何这样选）

- **确定性后果 vs 纯 LLM delta**：选引擎兜底。纯 LLM 不可靠、会放空炮；尤其「京师大疫→压低京营士气→喂甲申门」这条 A+B 链不能断在 LLM 漏写上。代价：每事件需作者预定义核心后果 delta。
- **character-gating vs 军/地区代理**：选改引擎加 character。代理（用所统军忠诚表达人物）既绕又对不上——卢象升不统兵、毛文龙的军 `commander`=「毛文龙旧部」非人名、袁崇焕「罢居」只活在 office 自由文本。引擎改小（两个求值器各加一分支）。
- **分层流寇 vs 单实体**：选分层。招安动头目、城破由股驱动，单实体表达不了「招了张李、流寇仍在」和「受抚→再叛」。

## Consequences

落 #174 的代码任务：
- **引擎**：character 进 `GATE_TABLES` + 两个求值器加分支。
- **schema**：事件确定性后果 delta 字段（`events.json`）+ 引擎「触发即落」的应用路（过现有 delta 管线落库；作者内容非 LLM 输出，不进 ADR 0008 的 LLM 拒收，但仍受瘦裁判一致性守门）。
- **内容**：16 事件逐个填 `trigger_gate`（新模型）+ 确定性后果 delta（逐事件史实核）。
- **种子修正**：`guanning` 主帅（1627 史实态）等。
- **招安/再叛**：确认走现有人事动作（易主+任命）+ 削股 delta，再叛对称。
- **测试**：已规避前提→不误触发；触发→确定性后果必落库；招安→削股+头目易主落库；再叛对称。

不在本 ADR（归实现期/后续）：受抚头目实际兵权（残部并入明军番号）；招安圣旨被阶层否决（#87）；军事压力等纯软判字段的「确定降法」（暂接受软判，确认有 DB 列可记录即可）。
