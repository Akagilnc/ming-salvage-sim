# 大臣职位变动技术文档

> 人物写契约：[`ADR 0009`](adr/0009-person-archive-applier-contract.md)；任免生效时点：[`ADR 0055`](adr/0055-promulgation-gate-at-settlement-effects-follow-verdict.md)；结算事务：[`SETTLEMENT_FLOW`](SETTLEMENT_FLOW.md)。本文只说明任免接线，不重复三份契约。

## 一、两条入口

```text
召对任免
  propose_appointment / 口头任免分类
    → pending_actions(kind=office)
    → 玩家确认或结束回合默认同意
    → commit_pending_actions：只成任免案卷，不授官
    → 颁布判决
       ├─ 打回 / 收回 / 留中：人物效果不落
       └─ 顺颁 / 强颁：apply_dossier_promulgation
            → _commit_office_action
            → apply_person_changes_only
            → 同一 outer atomic 内完成授官及可选传召启程
            → outer commit 后 registry.project_outcome

月末人物变化
  extractor 的「人物变更」
    → apply_score_extraction
    → ADR 0009 人物 applier
```

旧 `appointments` / `office_changes` / `character_status_changes` / `character_power_changes` 只为历史 delta 重放保留，由 sanitize 层翻译；新内容只写 `人物变更`，字段与动作见 ADR 0009 和 `docs/DELTA_SCHEMA.md`。

## 二、召对任免

`propose_appointment` 返回任免候选；`GameSession._stage_appointment_candidate` 将其写入 `pending_actions`，与口头任免共用确认闸。候选在这里尚未授官，也不能因该候选获得新职或传召资格。

候选载荷的核心字段：

```json
{
  "name": "孙传庭",
  "office": "陕西总督",
  "office_type": "督抚",
  "faction": "中立",
  "reason": "奉旨起复",
  "replaces": "原任者名",
  "summon_after": "是"
}
```

- `name`、`office` 为任命必需；罢免不需 `office`。
- `summon_after` 由任命/传召分类与合并接线保留；不另造第二份任免 schema。
- 撤回、拒绝或 undo 会同时清除尚未激活的 `office:<pending_id>` 传召 origin。
- 朝臣名册外目标在成案时只登记身份为 `offstage/待选`，不提前授官；月末自由文本凭空产生的陌生人物仍按 ADR 0009 `hallucinated_id` 拒收。

## 三、颁布与物化

`commit_pending_actions` 对 `kind=office` 的动作只创建 `decree_dossiers` 任免案卷。任免属于经外廷受判类，机械效果必须等颁布结果：

| 判决 | 人物结果 |
|---|---|
| 顺颁 / 强颁 | 通过 `apply_person_changes_only` 落任命、调任、罢免及其派生变化 |
| 打回 / 收回 | 零人物效果 |
| 留中 | 同一案卷留待后续判决，零人物效果 |

任命物化只走人物 adapter，不调用完整 `apply_score_extraction`，因此不会顺带重跑赈灾回流、议题或其他月末结算核。

### 任命并传召

`summon_after=是` 时，传召先以未激活故事账与任命同源暂存。只有任命成功后，`apply_dossier_promulgation` 才激活该 origin，并在同一 outer atomic 内沿既有传召状态机从人物当前所在地启程。

- 任命失败：任命、传召、在途状态全部回滚。
- 同人同夜多来源：既有 #670 单次消费规则保证只启程一次。
- 同地传召：仍记同一 origin，但不制造虚假路程。
- 结算提交成功后，受影响人物才由 `registry.project_outcome` 注册或刷新；事务内不碰运行时缓存。

## 四、人物与任职存储

```sql
characters (
  name TEXT PRIMARY KEY,
  office TEXT,
  office_type TEXT,
  court_role TEXT,
  status TEXT,
  status_reason TEXT,
  status_changed_turn INTEGER
)

character_offices (
  character_name TEXT PRIMARY KEY,
  office_title TEXT,
  office_type TEXT,
  source TEXT,
  updated_at TIMESTAMP
)
```

`characters` 保存当前名分和状态；`character_offices` 保存最近任职备档，不是完整履历。后者唯一写入方是颁布后的人物物化路径；起复、品级与破格判断只读，不得平行回写。

过程史与来源分别在 `person_logs`、案卷及同源 origin 中；不要从旁白反解析人物结构。

## 五、不变式

- 任免候选成案不等于生效；颁布结果才决定人物效果。
- 人物效果只走 ADR 0009 唯一 applier；任免局部写不得借完整月末 applier 搭便车。
- 任命、可选传召、案卷状态与结算写处于同一 outer atomic；失败不留半写。
- registry 只在 outer commit 成功后投影；回滚不得留下脏 Agent。
- `character_offices` 只存最近任职；完整过程看 `person_logs`。
- LLM 负责判断任免内容；代码只校验结构、状态转换并记账。

## 六、排查

| 现象 | 先查 |
|---|---|
| 玩家确认后尚未授官 | 正常；查任免案卷是否已进入颁布判决 |
| 结算后仍未授官 | 查案卷判决、`rejection_reports` 与人物 applier 回执 |
| 任命成功但未启程 | 查载荷 `summon_after`、未激活 origin 是否被正确提升，以及 #670 单次消费结果 |
| 失败后残留在途或脏 Agent | 属事务/outer-commit 投影缺陷；任命、传召、缓存必须一起核 |
| 月末陌生人物被拒 | 正常；先走史实人物补档或用户确认登记，再任命 |
