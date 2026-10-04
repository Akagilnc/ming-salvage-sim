# #1835 advisor-rescan 全表处置（HEAD=51a0c82e0）
谓词=类定义全文（形状/AST/消费者），非点名样本白名单。
## 完整性C1 旧核/兼容桥/平行路径
### 枚举命令
```
rg -n "^def (apply_|_apply_).*(metric|economy|levy|recovery|inertia|drift|class)" ming_sim
rg -n "apply_levy|apply_situation|apply_recovery|apply_issue_inertia" ming_sim/month_chain.py
AST: 同名 def 跨模块碰撞
```
### 成员全表与处置
|成员|语义分类|处置|依据|
|---|---|---|---|
|`entities.metric.apply.apply_metric_dict`|既定实体核（#1901）|保留|单一真源；非平行旧核|
|`entities.economy.apply._apply_economy_list`|既定实体核|保留|同上|
|`entities.social_class.apply._apply_class_dict`|既定实体核|保留|同上；situation_drift 已改接此口|
|`situation_drift.apply_situation_monthly_drift`|#1901 接缝|保留|month_chain:1411 唯一月漂移入口|
|`displaced_population.apply_levy_driven_transfers`|#1901 接缝|保留|month_chain:625 唯一加派入口|
|`entities.population.recovery._apply_recovery_driven_transfers`|#1901 回流|保留|month_chain:1860；displaced 回流副本已删|
|`issues.apply_issue_inertia_and_ongoing` / levy 旧核 / re-export 七符号|平行旧核|已删（上轮）|AST 无 def/reexport|
|`flows._apply_metric_dict/_apply_economy_list`|平行旧核|已删（上轮）|AST 无 def|
|`issues._apply_fiscal_levy_targets`|三饷终态钱面（非月漂移平行核）|保留|非 C1 类成员：属 fiscal_levy 终态通道，非 situation/displaced 双持|

实查 defs：
```
ming_sim/entities/metric/apply.py:13:def apply_metric_dict(
ming_sim/entities/population/recovery.py:34:def _apply_recovery_driven_transfers(
ming_sim/entities/economy/apply.py:11:def _apply_economy_list(
ming_sim/entities/social_class/apply.py:10:def _apply_class_dict(
ming_sim/situation_drift.py:239:def apply_situation_monthly_drift(
ming_sim/issues.py:630:def _apply_fiscal_levy_targets(
ming_sim/displaced_population.py:42:def apply_levy_driven_transfers(
```

month_chain 接线：
```
625:    from ming_sim.displaced_population import apply_levy_driven_transfers
631:        _applied, rejected = apply_levy_driven_transfers(db, commit=False, source=source)
1411:    from ming_sim.situation_drift import apply_situation_monthly_drift
1436:        rejections = apply_situation_monthly_drift(
1860:        from ming_sim.entities.population.recovery import _apply_recovery_driven_transfers
1861:        _apply_recovery_driven_transfers(db, state)
```

## 完整性C2 拒收藏成功载荷 / 特殊搬运
### 枚举
```
rg backlash_results|backlash_rejections|\.pop\(.*backlash|rejections\.extend\(backlash
```
### 成员全表
|成员|语义分类|处置|依据|
|---|---|---|---|
|`character/apply.py` backlog→`rejections.extend`|既有返回通道|保留|canonical 拒收交出|
|嵌套 `applied.backlash_results` / `.pop("backlash*")`|特殊搬运|已删|AST 无 backlash_results / pop|
|`credit_events._collect_reject_issue_ids`|cancels 显式 issue id 集|保留|非成功载荷嵌套拒收；读 cancels 信号|

实查：
```
ming_sim/entities/character/apply.py:624:            _backlash_applied, backlash_rejections = db.apply_power_deltas(
ming_sim/entities/character/apply.py:658:                rejections.extend(backlash_rejections)
```

## 完整性C3 无消费者接口 / 冗余运行态
|成员|消费者(AST)|处置|依据|
|---|---|---|---|
|`ordinal`|3 refs (3 prod)|SectionSpec.ordinal 已删|AST 取证|
|`ordered_sections`|0 refs (0 prod)|已删|AST 取证|
|`section_for_delta_key`|0 refs (0 prod)|已删|AST 取证|
|`declare_closed`|0 refs (0 prod)|本轮删除：仅 tests 3 处夹具，非自然归档借口|AST 取证|
|`TAG_STAY_ATTEND`|0 refs (0 prod)|本轮删除：定义无引用|AST 取证|
|`caller_transaction`|2 refs (2 prod)|run.py 局部变量承重：判词明示除外|AST 取证|

declare_closed 现查：
```
ming_sim/entities/affair/store.py:4:本 store 不提供 declare_closed / close 词表写口。
tests/test_month_translate_1840.py:746:    # 夹具直接写 closed 态；生产无 declare_closed 动作（ADR 0154）。
ming_sim/materials.py:414:    承接，本函数不依赖、也不调用任何 declare_closed 写口。
```

TAG_STAY_ATTEND 现查：
```
(none)
```

## 完整性C4 平行证明测试 / 仅测试消费生产摘要
|成员|处置|依据|
|---|---|---|
|`tests/test_settlement_fixed_point_1835.py`|已删|重复 month_chain 结局契约|
|`settlement.views.describe`|已删|仅测试断言消息消费者|
|既有 `view()` / 玩家行为契约测试|保留|边界：不删既有玩家契约|
|直接 `settle_delta` 行为案（affairs/origin/…）|保留|产品契约入口，非平行证明|

fixed_point 文件：`ls: tests/test_settlement_fixed_point_1835.py: No such file or directory`
describe：
```
ming_sim/cli_backend.py:1140:def describe_effective_model(llm_config: Any = None) -> str:
```

## 正确性C1（票面C5）事务 close 动作/守门
|成员|处置|依据|
|---|---|---|
|`affair/delta_section` close 解析+未了守门|已删|空允许集通用拒收|
|`close_from_declaration`|已删|AST 0|
|`ATTACH_RESULT_CLOSE` / `_ATTACH_CLOSE`|已删|AST 0|
|`AffairStore.declare_closed`|**本轮删除**|仅测试夹具消费者；C3/C5 禁「将来自然归档」借口；ADR 0154|
|`status` 列 / closed 态字段|保留|世界记录承接往事需要可读态；无写口动作|
|`test_affairs_1831` close 拒收契约|保留|既有玩家/声明拒收行为，非专属旧 close 守门测试|
|`test_month_translate_1840` 夹具|**本轮改 SQL UPDATE**|不经生产 declare_closed|

## 正确性C2（票面C6）退役 NL 口令 / 固定台词
|成员|语义分类|处置|票面/ADR 依据|
|---|---|---|---|
|`STAY_ATTEND_COMMANDS` / `AMBIGUOUS_CLOSE_COMMANDS` / 固定 cue「陛下是要退朝么？」 / `stay_attend_in_audience`|已裁撤 NL+固定台词|已删|#1812 待拍事项第5项；P7；ADR 0142|
|`TAG_STAY_ATTEND`|退役标签常量、无消费者|**本轮删除**|C3+C6；非历史投影真消费者|
|NL 软收夜「今日且到此」|同族 NL 软收夜（样本「今日就到这里吧」）|**本轮移出 COURT_BREAK_COMMANDS**|#1812 第5项类定义全文；非 ADR 0047 明确口令|
|`COURT_BREAK_COMMANDS`含 `退朝`/`下朝`/`q`/`quit`|明确退朝封闭集（按钮加速器）|**保留**|ADR 0047：退朝钮=「退朝」口令；ADR 0158：散夜钮=「退朝」；边界「不扩张删除无关命令」|
|`recognize_audience_command` / `CMD_CLOSE_NIGHT` / session `scene_chat` court_break 分派|明确退朝→收夜结构化判词|**保留**|同上；不产固定人物台词；只返回 court_action|
|CLI `terminal.py` COURT_BREAK 匹配|同封闭集加速器|**保留**|同一真源 constants.COURT_BREAK_COMMANDS|
|`MINISTER_DISMISS_COMMANDS`|大臣告退，非收夜|保留|类定义外|

COURT_BREAK 现查：
```
ming_sim/audience_night.py:1998:    本函数只匹配 COURT_BREAK_COMMANDS 明确封闭集，不重解析散文、不产固定人物台词。
ming_sim/audience_night.py:2000:    from ming_sim.constants import COURT_BREAK_COMMANDS
ming_sim/audience_night.py:2006:    if lowered in COURT_BREAK_COMMANDS or text in COURT_BREAK_COMMANDS:
ming_sim/constants.py:256:COURT_BREAK_COMMANDS = {"q", "quit", "退朝", "下朝"}
ming_sim/cli/terminal.py:15:    COURT_BREAK_COMMANDS,
ming_sim/cli/terminal.py:116:        if lowered in COURT_BREAK_COMMANDS:
ming_sim/cli/terminal.py:172:    if lowered in COURT_BREAK_COMMANDS or raw in COURT_BREAK_COMMANDS:
ming_sim/cli/terminal.py:534:        if lowered in COURT_BREAK_COMMANDS:
```
recognize / CMD_CLOSE_NIGHT 消费者：
```
# recognize_audience_command
ming_sim/session.py:995
ming_sim/audience_night.py:2031
web_app.py:2237
# CMD_CLOSE_NIGHT
ming_sim/session.py:1154
ming_sim/audience_night.py:144
ming_sim/audience_night.py:147
ming_sim/audience_night.py:2007
web_app.py:2237
```

## 正确性C3（票面C7）供料裁剪模型条件原文
传递链（不仅 resolve_condition）：
1. DB/knowledge 投影 → `_visible_affair_lines` 写入 `resolve_condition`/`fail_condition`/`situation(stage_text)` 字典（原值 str()，不 strip）
2. `_write…当前情况.txt`：判空用 `.strip()` 副本；写出 f-string 用原值
3. `_candidate_event_fact` → `_write_candidate_event_files`：`resolve_condition`/`fail_condition`/`precondition`/`summary` 原值直写
4. `knowledge._prose`：`str(text or "")` 不 strip
|成员|处置|依据|
|---|---|---|
|materials `_visible_affair_lines` strip-then-store|已改为保留原值|判词 C7|
|写出端 strip 判空|保留副本判空|边界允许|
|issues `commitment_condition_role` / db gate `.strip()` 匹配|保留|非供料写出链；本地匹配副本|
|content `clear_narrative` seed strip|保留|内容装载规范化，非模型声明供料链|
|tracker `_issue_condition_text`|保留原串（str/json）|不 strip 自由条件|
