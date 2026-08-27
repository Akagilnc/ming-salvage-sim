# 人物模块

人物模块定义大臣、太监、将领、地方官、宗室、士绅、商人、传教士和敌方人物。人物首先是对话对象，其次数值才用于结算。

## 核心数值

- `忠诚`：愿不愿意为皇帝办事和担责。
- `能力`：能不能把事办成。
- `清廉`：会不会贪、瞒、卖人情。
- `胆略`：遇到风险时敢不敢说真话、担责任、动手执行。
- `派系`：他主要受谁影响。

## 玩法重点

玩家通过召对判断人物：

- 他说的是真话还是场面话。
- 他是办事型、清谈型、投机型还是自保型。
- 给他权力会不会养成尾大不掉。
- 问责他会震慑朝堂，还是毁掉可用之人。

## 人物状态机

`characters` 表 `status` 列，七个取值：

- `active`：在朝，可召见。
- `offstage`：历史上崇祯元年（1628）尚未登场的名臣（洪承畴、卢象升、杨嗣昌、史可法、孙传庭等）。**不进朝臣名册、不能召见**，等历史登场年月到了再现身。
- `dismissed` / `imprisoned` / `exiled` / `retired` / `dead`：罢官 / 下狱 / 流戍 / 致仕 / 已故，均不能召见。

`set_character_status` 是改状态的唯一入口。

### 历史登场（offstage → active）

`characters.json` 里 `status:"offstage"` 的人物填 `debut_year` / `debut_month`（公历，登场年月）。每月初 `GameDB.apply_historical_debuts` 自动判定：到点的 offstage 人物转 `active`，本回合起进入朝臣名册可召见，并把 `{name, office, faction}` 喂给月末推演 agent（payload `debuts_this_turn`），由邸报简述其授官到任。与 `apply_historical_deaths`（历史卒）对称。`debut_year=0` 视为开局即在场。

### 吏部铨选任命（皇帝点名补人）

明朝官员数以千计，名册只收 30 余位主要人物。皇帝若强行点名起用名册外的某人（如把当时还是底层小官的史可法擢为浙江巡抚），由**吏部尚书**专属 court tool `propose_appointment(name, office, faction, reason)` 处理：

- 吏部尚书 Agent 凭历史知识自行裁断——查无此人、或纯属杜撰的名字直接据实回禀「查无此员」，史有其人且任命说得通才调 tool。不做无脑照办，也不做代码端字面校验（符合"无 fallback"约束：tool 只在 LLM 判定合理时才触发）。
- tool 触发后先进入任免暂存与颁布判决；顺颁后才物化人物、提交后投影运行时名册。完整时序见 [`docs/character-office-changes.md`](../character-office-changes.md)。
