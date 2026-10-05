# #1834 修内司回执 · F18 / F19 / F20（末份判词 ecdbc39ab）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`

**分支**：`ak-roles/1834-f18-f19-f20-ecdbc39ab`

**基线 HEAD（开工）**：`ecdbc39abd7a4c93ef1383047832707c92ca75cd`

**首修 commit**：`79f63e9360345e674135a68a5cc80b1307f3778f`

**本轮自验补修 commit**：`d64e170538464d6041eb80e748b567929588a5cf`

**派单**：`…/01a1097a-bf6b-726c-bacb-5208aa0e1d03@fixer/fix-packet.md`

**末份判词**：`…/attachments/03-1834-judge-ecdbc39ab.json` 末 payload（唯一未结）

**共同测试前缀**：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

方向：Python 死码删除优先于兼容 shim；实例不是白名单；全仓含 docs/archive/evidence 机械枚举后语义归类。

未改治理法源：`AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `docs/adr/**` 无 diff。

### 自验纠偏（相对首修回执）

1. 首修声称 `git diff --check ecdbc39ab HEAD`「无输出＝干净」不实。实测对 `report.md` 首段 metadata 行（原 L3–L8）报 trailing whitespace；本轮去掉行尾空格并据实重记。
2. 首修 F18/F19 命令排除 `docs/**`/`archive/**`/`evidence/**`，F20 只扫单目录，且保留表把 `compose_secret_order_landing_recovery` 仅因字段存在记成「共享能力」。本轮改为全仓宽词枚举 + 调用点证明，并删除零调用 compose 专属死码。

---

## 1. F18 — 已退役口令仍由代码裁断并代写人物台词

### 根因

`#1812` 待拍第5项已裁定「留下听着」「今日就到这里吧」不再由代码识别；场景模型照常演、转译声明在场与退下。生产曾保留口令封闭集、`scene_chat` 专用早退，以及 `_ensure_close_night_confirm_cue` 代写「陛下是要退朝么？」大臣台词（P7 人物对话）。

### 覆盖范围

全仓（含 `docs/` `archive/` `evidence/` `ming_sim/` `tests/` `web/`）。命令见 `enum_f18_cmd.sh`；复扫原文 `enum_f18_after.txt`（= `enum_f18_full.txt`）。

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
| 本片证据自指 | `evidence/1834-f18-f19-f20-fix/**` before/after/report | KEEP（本回执） |
| 冻结历史处置／探针 | `docs/evidence/issue-1571/**`、`evidence/1834-fixer-f3-f14/**` 等记旧 TAG_STAY_ATTEND／口令史 | KEEP（冻结记录，不重写） |

**保留（现役）**：`COURT_BREAK_COMMANDS` / `CMD_CLOSE_NIGHT`；`MINISTER_DISMISS_COMMANDS`；场景调用 + `audience_translate` 统一转译。

---

## 2. F19 — 被统一转译取代的密令抽取闭包及专用测试

### 根因

现役 `declaration_dispatch` 直接承接 `commission.secret_order`；`cli_backend._extract_secret_order` 及其拼装／词表／案卷确认闭包仅被专用测试引用，仍被维护——退役机制的复杂度缺陷。

### 覆盖范围

全仓。命令见 `enum_f19_cmd.sh`；复扫 `enum_f19_after.txt`。宽词覆盖抽取闭包符号全文，并加 `name(` 调用点证明，避免「仅定义／仅字段」冒充消费者。

### 成员表（抽取闭包）

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `_CLAUSE_SPLIT` … `_extract_secret_order` 整段闭包 | DELETED（首修） | 专属抽取；生产无调用 |
| 仅服务该闭包的 import／注释现役指称 | DELETED／FIXED（首修） | 随闭包 |
| 4 个专用测试 + `_so_json` | DELETED（首修） | 只为旧闭包存在 |
| `compose_secret_order_landing_recovery` | DELETED（本轮） | 全仓 `compose_secret_order_landing_recovery(` 仅见 def，零真实调用 |
| `_SECRET_LANDING_GAP_LABELS` / `_secret_landing_gap_feature` | DELETED（本轮） | 仅被上述 compose 使用 |

### 共享／投影面：真实消费者核查

| 符号 | 真实调用／消费 | 处置 | 保留依据 |
| --- | --- | --- | --- |
| `secret_order_can_land(` | `declaration_dispatch.py` 现役 `if not secret_order_can_land(...)` | KEEP | 现役落库闸 |
| `secret_order_landing_gaps(` | 仅被 `secret_order_can_land` 调用 | KEEP | 同上闸的 typed gaps |
| `compose_secret_order_landing_recovery(` | **无调用点**（def 不算消费） | DELETED | 不得以字段存在冒充共享能力 |
| `ChatTurnResult.secret_order_landing_recovery` + `web_app` 透传 | 仅 `getattr`/`payload` 字段传递；**从不调用 compose、无生产者赋值** | KEEP（投影字段） | 字段≠compose 消费者；前端无引用；不扩删 API 面 |
| `test_typed_secret_exclusions_canonicalize_roster_alias_and_office` | 测 `db.canonical_secret_order_exclusions` | KEEP | 真共享契约，非抽取闭包 |

### 全仓命中语义归类（复扫后）

| 类 | 命中概要 | 处置 |
| --- | --- | --- |
| 生产抽取闭包 | 仅「已删」注释一行 | KEPT（注释） |
| 现役落库闸 | `can_land` / `landing_gaps` 定义 + dispatch 调用 | KEEP |
| 零调用 compose 族 | 已删 | DELETED |
| 冻结文档／审计／旧 evidence | `TODOS.md`、`docs/**`、`archive/**`、旧 enum 记 `_extract_secret_order` 史 | KEEP（冻结，不重写；非现役生产） |
| 本片证据自指 | 本目录 before/after/report | KEEP |

### 测试删除必要成本

删 4 个只绑抽取闭包的专用案 + `_so_json`；未新造平行证明测试。保留 typed exclusions。净减复杂度，符合 #1812「只为旧代码存在的测试已删」。

---

## 3. F20 — 现行证据导航仍指向已撤销的处置真源

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

代码本轮有变动（删 compose 族），按此前七个 false 环境变量复跑：

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
  -p no:cacheprovider --basetemp=/tmp/1834-f18-f19-f20-pytest2 --tb=short
```

完整输出：`pytest_focus.txt` — **143 passed, 1 warning in 7.03s**（`/usr/bin/time -p`：real 7.56 / user 4.15 / sys 1.40）。

未跑全量。

---

## 5. 差异自检

- 首修后 `git diff --check ecdbc39ab HEAD` **有输出**：`report.md` L3–L8 trailing whitespace（EXIT=2）。本轮已去掉行尾空格。
- 提交前 `git diff --cached --check`：无输出（EXIT=0）。
- 提交后 `git diff --check ecdbc39ab HEAD`：见 `diff_check.txt` 末段（须无 trailing whitespace）。
- `git diff --stat ecdbc39ab HEAD`：见 `diff_stat.txt`
- 禁项：无 push／PR／amend／stash／kill；未新增模型／提示器／兼容层／分类层／证明性测试；冻结历史未改写正文；未复制法源进治理文件

---

## 6. 阻断

无真实阻断。
