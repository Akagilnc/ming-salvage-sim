# #1834 修内司回执 · F18 / F19 / F20（末份判词 ecdbc39ab）+ F19-R

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`

**分支**：`ak-roles/1834-f18-f19-f20-ecdbc39ab`

**基线 HEAD（开工）**：`ecdbc39abd7a4c93ef1383047832707c92ca75cd`

**首修 commit**：`79f63e9360345e674135a68a5cc80b1307f3778f`

**本轮自验补修 commit（删 compose 族）**：`d64e170538464d6041eb80e748b567929588a5cf`

**上轮（删 secret_order 恢复投影）**：`949621fc0f4fb97700135839f4784962e8aa20d4`

**本轮（F19-R：前缀分派 / compose_decree 恢复族）**：提交后见 `git rev-parse HEAD`（报告不预写未来 SHA）

**派单**：`…/01a1097a-bf6b-726c-bacb-5208aa0e1d03@fixer/fix-packet.md`

**末份判词**：`…/attachments/03-1834-judge-ecdbc39ab.json` 末 payload（唯一未结）+ 用户 session 新封驳 F19-R

**共同测试前缀**：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

方向：Python 死码删除优先于兼容 shim；实例不是白名单；全仓含 docs/archive/evidence 机械枚举后语义归类；零消费者投影不得以「不扩删 API 面」保留（全局删旧物、#1812）。

未改治理法源：`AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `docs/adr/**` 无 diff。F18 / F20 已办结，本轮不重开。

### 自验纠偏（相对前序回执）

1. 首修声称 `git diff --check ecdbc39ab HEAD`「无输出＝干净」不实。实测对 `report.md` 首段 metadata 行（原 L3–L8）报 trailing whitespace；已去掉行尾空格并据实重记。
2. 首修 F18/F19 命令排除 `docs/**`/`archive/**`/`evidence/**`，F20 只扫单目录，且保留表把 `compose_secret_order_landing_recovery` 仅因字段存在记成「共享能力」。已改为全仓宽词枚举 + 调用点证明，并删除零调用 compose 专属死码。
3. 上轮仍把 `ChatTurnResult.secret_order_landing_recovery` + `web_app` 透传记成 KEEP（投影字段／不扩删 API 面）。事实查询：`rg -n secret_order_landing_recovery ming_sim web_app.py web tests` 仅字段声明与参数透传，无生产赋值、无前端消费者——属刚删 compose 的专属零消费者投影。本轮同类删除；报告成员表据实改 DELETED。
4. 上轮自建 `enum_f18/19/20_full.txt` 与对应 `_after.txt` 完全相同（`cmp` 恒等），重复存储数千行且枚举含自身回声。本轮删除三个 `_full.txt` 副本；报告与命令只指 `_after.txt`（保留独立 `_before` 与 `*_cmd.sh`）；未另造脚本层／新分类。
5. **F19-R**：前缀分派代码已不存在，但 `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` / `_matched_prefix` 与 ~1256 失真说明仍在；`compose_decree_validation_recovery` 零调用；`ChatTurnResult.decree_validation_failure` 无生产赋值、仅 `web_app` 透传——与刚删 `secret_order` 恢复族同形。本轮按完整类「只为已退役密令/拟旨前缀分派与零调用 compose 恢复存在」全仓自扫并删除；三顶层单引用候选语义判 KEEP（见下）。

---

## 1. F18 — 已退役口令仍由代码裁断并代写人物台词（已办结）

### 根因

`#1812` 待拍第5项已裁定「留下听着」「今日就到这里吧」不再由代码识别；场景模型照常演、转译声明在场与退下。生产曾保留口令封闭集、`scene_chat` 专用早退，以及 `_ensure_close_night_confirm_cue` 代写「陛下是要退朝么？」大臣台词（P7 人物对话）。

### 覆盖范围

全仓（含 `docs/` `archive/` `evidence/` `ming_sim/` `tests/` `web/`）。命令见 `enum_f18_cmd.sh`；复扫原文 `enum_f18_after.txt`。

宽词：`AMBIGUOUS_CLOSE_*` / `STAY_ATTEND_*` / `TAG_STAY_ATTEND` / `stay_attend_in_audience` / `_ensure_close_night_confirm_cue` / `陛下是要退朝么` / `ambiguous_close` / `stay_attend` / 退役口令原文；并追现役 `recognize_audience_command` / `COURT_BREAK_*` / `MINISTER_DISMISS_*`。

### 成员表（修前生产 → 处置）

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `constants.py` `AMBIGUOUS_CLOSE_COMMANDS` / `STAY_ATTEND_COMMANDS` | DELETED | 退役口令封闭集 |
| `audience_night.py` `TAG_STAY_ATTEND` / `CMD_AMBIGUOUS_CLOSE` / `CMD_STAY_ATTEND` | DELETED | 仅服务退役裁断 |
| `audience_night.py` `stay_attend_in_audience` | DELETED | 口令写缝；零转译消费者 |
| `recognize_audience_command` stay/ambiguous 分支 | DELETED | 仅留 `COURT_BREAK` |
| `session.py` `_ensure_close_night_confirm_cue` + 「陛下是要退朝么？」 | DELETED | 代写人物台词 |
| `session.py` `scene_chat` ambiguous/stay 早退 | DELETED | 复用场景／转译接缝 |
| `cli/terminal.py` stay 口令分支 | DELETED | 同形退役裁断 |
| `test_scene_stay_attend_uses_actual_protagonist_not_virtual_speaker` | DELETED | 专用测试，随机制删 |

### 全仓命中语义归类（复扫后）

| 类 | 命中概要 | 处置 |
| --- | --- | --- |
| 生产裁断／台词补写 | `ming_sim/` 无符号定义／调用；仅删后说明注释 4 处 | KEPT（注释，非裁断） |
| 现役退朝／退下 | `COURT_BREAK_COMMANDS` / `CMD_CLOSE_NIGHT` / `MINISTER_DISMISS_COMMANDS` / `recognize_audience_command` | KEEP（现役） |
| 本片证据自指 | `evidence/1834-f18-f19-f20-fix/**` before/after/report/cmd | KEEP（本回执） |
| 冻结历史处置／探针 | `docs/evidence/issue-1571/**`、`evidence/1834-fixer-f3-f14/**` 等记旧 TAG_STAY_ATTEND／口令史 | KEEP（冻结记录，不重写） |

**保留（现役）**：`COURT_BREAK_COMMANDS` / `CMD_CLOSE_NIGHT`；`MINISTER_DISMISS_COMMANDS`；场景调用 + `audience_translate` 统一转译。

---

## 2. F19 / F19-R — 被统一转译取代的密令抽取闭包、前缀分派残留与零调用 compose 恢复

### 根因

现役 `declaration_dispatch` 直接承接 `commission.secret_order`；`cli_backend._extract_secret_order` 及其拼装／词表／案卷确认闭包仅被专用测试引用，仍被维护——退役机制的复杂度缺陷。

**F19-R 追加**：前缀分派实现已不存在，但 `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` / `_matched_prefix` 与失真「据此分派」说明仍在；`compose_decree_validation_recovery` 零调用；`decree_validation_failure` 仅字段／web 透传、无生产赋值——与已删 `secret_order_landing_recovery` 同形。

### 覆盖范围

全仓。命令见 `enum_f19_cmd.sh`（含 F19-R CMD7–14）；复扫 `enum_f19_after.txt`。宽词覆盖抽取闭包、前缀分派、compose 恢复投影，并加 `name(` 调用点证明。不限定 secret 词面。

### 成员表（抽取闭包 + F19-R 完整类）

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `_CLAUSE_SPLIT` … `_extract_secret_order` 整段闭包 | DELETED（首修） | 专属抽取；生产无调用 |
| 仅服务该闭包的 import／注释现役指称 | DELETED／FIXED（首修） | 随闭包 |
| 4 个专用测试 + `_so_json` | DELETED（首修） | 只为旧闭包存在 |
| `compose_secret_order_landing_recovery` | DELETED（上轮） | 全仓仅见 def，零真实调用 |
| `_SECRET_LANDING_GAP_LABELS` / `_secret_landing_gap_feature` | DELETED（上轮） | 仅被上述 compose 使用 |
| `ChatTurnResult.secret_order_landing_recovery` | DELETED（上轮） | 仅字段声明；无生产者赋值 |
| `web_app._chat_payload` secret_order 恢复透传 | DELETED（上轮） | 专属零消费者投影 |
| `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` | DELETED（F19-R） | 前缀分派已退役；零消费者 |
| `_matched_prefix` | DELETED（F19-R） | 仅服务前缀分派；`name(` 零调用 |
| ~1256「据此分派」失真说明 + 零跟随的「大臣会话动作抽取」注释 | DELETED／FIXED（F19-R） | 失真说明；改为「已删」短注 |
| `compose_decree_validation_recovery` | DELETED（F19-R） | 全仓 `compose_decree_validation_recovery(` 仅曾见 def |
| `ChatTurnResult.decree_validation_failure` | DELETED（F19-R） | 无生产赋值；与 compose 同族投影 |
| `web_app._chat_payload` decree_validation_failure 参数／键／两处 getattr | DELETED（F19-R） | 零消费者透传；前端无类型／引用 |

### 共享／投影面 + 顶层单引用候选

| 符号 | 真实调用／消费 | 处置 | 保留／删除依据 |
| --- | --- | --- | --- |
| `secret_order_can_land(` | `declaration_dispatch.py` 现役 | KEEP | 现役落库闸 |
| `secret_order_landing_gaps(` | 仅被 `secret_order_can_land` 调用 | KEEP | 同上闸 typed gaps |
| `_compose_inworld_fact_report` / `compose_unknown_participant_inworld_report` | 现役参与者升级回禀 | KEEP | 非 decree/secret 恢复专属；现役共享 |
| `require_fresh_cli_trace(` | `scripts/{promulgation_gate_561,break_rank_judge_gate_562,midzhi_spiral_judge_gate_570,family_tail_acceptance_570}.py` | KEEP | **非本类**：CLI 闸新鲜 trace 守卫（#1256）；有真实调用 |
| `night_dossiers_ready(` | 仅 def；零调用 | KEEP | **非本类**：#1842 收夜案卷水位谓词，非前缀分派／compose 恢复；不扩删出类 |
| `_target_active_officeholder(` | 仅 def；零调用 | KEEP | **非本类**：R2 任命暂存／在职罢免判定，非前缀／compose 恢复；不扩删出类 |
| `directive_confirmation_ambiguous`（对照扫） | 字段 + web 透传 + `web/src/types.ts` | KEEP | **非本类**：#502 多道准驳含糊；非前缀／compose 恢复 |
| `compose_decree_validation_recovery(` / `decree_validation_failure` | 无调用／无赋值 | DELETED | 本类零调用 compose + 空恢复投影 |
| `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` / `_matched_prefix(` | 无消费 | DELETED | 本类退役前缀分派残留 |

### 全仓命中语义归类（F19-R 复扫后）

| 类 | 命中概要 | 处置 |
| --- | --- | --- |
| 生产抽取闭包／前缀分派／decree compose 恢复 | `ming_sim`/`web_app`/`tests`/`web` **PROD_CLEAN** | DELETED |
| 现役落库闸 + inworld 共享 compose | `can_land` / `landing_gaps` / unknown-participant | KEEP |
| 冻结文档／审计／旧 evidence | archive constitution 记旧 `_DRAFT_PREFIXES`；F16 disposition 记旧 `_matched_prefix` | KEEP（冻结，不重写） |
| 本片证据自指 | 本目录 before/after/report/cmd | KEEP |
| 出类零调用谓词 | `night_dossiers_ready` / `_target_active_officeholder` | KEEP（出类；依据见上） |

### 测试删除必要成本

删 4 个只绑抽取闭包的专用案 + `_so_json`（首修）；F19-R 未新造平行证明测试。保留 typed exclusions。净减复杂度，符合 #1812「只为旧代码存在的测试已删」。

---

## 3. F20 — 现行证据导航仍指向已撤销的处置真源（已办结）

### 根因

`F17_F3R_REVOCATION.txt` 曾把 Current F16 指到已标 `REVOKED_PACKAGING_KEEP` 的 `f16_hand_verify_after_ruling.*`。

### 覆盖范围

全仓。命令见 `enum_f20_cmd.sh`；复扫 `enum_f20_after.txt`。枚举全部 `*REVOKED*` 标记文件与 `Current F16` / `Disposition authority` / 相关 basename 引用链。

### 撤销材料清单与引用链

| 材料 | 标记 | 现行导航是否冒称权威 | 处置 |
| --- | --- | --- | --- |
| `f16_hand_verify_after_ruling.tsv` + `.METHOD.txt` | `*.REVOKED_PACKAGING_KEEP.txt` | 否（Current 已改指 disposition_after） | KEPT 冻结失败记录，不重写 METHOD 正文 |
| `f16_hand_member_table.tsv` | `*.REVOKED_TEMPLATE.txt` | 否（stub 首行声明非权威） | KEPT 冻结 |
| `enum_f16_rewrite_shapes_rerun.txt` / `enum_f16_all_candidates.txt` / `enum_f16_ast_rewrite.tsv` | `REVOKED_STUB` 首行 | 否 | KEPT 冻结 |
| `enum_f16_supply_path_after.tsv` | `*.REVOKED_STALE.txt` | 否 | KEPT 冻结 |
| `f3r_hand_member_table` 旧 AST 自动表 | `*.REVOKED_AST_AUTO.txt` | 否；Current F3-R 指向手读合并表 | KEPT 冻结 |
| `mutation_old_red` / `probe_new_green` | `*.REVOKED_METHOD.txt` | 否；Current F17=current-side only | KEPT 冻结 |

### 现行导航真源（唯一权威组）

| 导航点 | 现行指向 | 状态 |
| --- | --- | --- |
| `F17_F3R_REVOCATION.txt` Current F16 | `f16_disposition_after_counterexample.{tsv,METHOD.txt}` + `f16_disposition_member_locs.tsv` | FIXED（首修）；复扫确认 |
| `f16_disposition_after_counterexample.METHOD.txt` Disposition authority | 同上 tsv（16 组） | 现行权威 |
| `evidence/1834-f16-f3-f3r-f17-fix/report.md` | 引用 disposition_after 为权威组表；F17-R 行引用本导航文件 | 链闭环；未冒称 hand_verify |
| `f16_hand_verify_after_ruling.METHOD.txt` 内仍写 Disposition authority=hand_verify | 冻结 METHOD 正文 | KEPT 不重写；有 `REVOKED_PACKAGING_KEEP` 伴侣；**不算现行导航成员** |

全仓 `Current F16 evidence = f16_hand_verify`：无现行命中。`Disposition authority = f16_hand_verify`：仅冻结 METHOD（及本目录枚举回声）。

未重做分类机制或变异脚本。

---

## 4. 聚焦测试

F19-R 本轮代码有变动（删前缀常量／`_matched_prefix`／`compose_decree_validation_recovery`／`decree_validation_failure` 投影），按七个 false 环境变量复跑既有触面：

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_cli_backend.py \
  tests/test_audience_translate_1837.py \
  tests/test_scene_llm_1836.py \
  tests/test_cli_transport_1465.py \
  tests/test_material_directory_1830.py \
  tests/test_world_materials_1834.py \
  tests/test_web_chat_serialization_393.py \
  -p no:cacheprovider --basetemp=/tmp/1834-f18-f19-f20-pytest-f19r --tb=short
```

完整输出：`pytest_focus.txt` — **149 passed, 1 warning in 5.79s**（`/usr/bin/time -p`：real 6.44 / user 3.76 / sys 1.14）。stderr 另有 highlight_judge degraded 轨迹（`llm_config is None`，七 false 前缀下既有降级路径），未计入失败。

未跑全量。F18／F20 未重开、未复测专用面。

---

## 5. 差异自检

- 提交前对工作态跑 `git diff --check ecdbc39ab`（见 `diff_check.txt`；空＝无 whitespace 错误）。
- `git diff --stat ecdbc39ab`：见 `diff_stat.txt`
- 禁项：无 push／PR／amend／stash／kill；未新增模型／提示器／兼容层／分类层／证明性测试；冻结历史未改写正文；未复制法源进治理文件；未盖章连环 commit；报告不预写未来 SHA。

---

## 6. 阻断

无真实阻断。
