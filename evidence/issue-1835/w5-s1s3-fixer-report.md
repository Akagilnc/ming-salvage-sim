# #1835-w5 S1/S2/S3 修内司施工报告（证据复核修订）

- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5`
- **分支**：`ak-roles/issue-1835-w5-s1s3-fixer`
- **基线 HEAD（施工前）**：`356eb5f128518ba39936bf9d4ab07fa6f65a2ac7`
- **前次交卷提交（留史）**：`66f7b9a97b9c8c0a0d87de2909f236a26c05b696`
- **派单**：`01a10a10-85d2-7837-a403-5700d62a6461@fixer/fix-packet.md`
- **冻结判词**：`attachments/05-1835-judge-356eb5f12.json`（**payloads 末份**唯一界定未结类）
- **未结类（末份原文）**：S1 canonical 拒收迁约；S2 领域准入平行权威；S3 退役协议附属物／错约说明／重复测试
- **不宣称 merge／关票**

## 本修订相对前次交卷的问题

前次报告谓词收窄，导致证据不可复核：

1. S1 只枚举「同时双写」，漏单独旧 dict 拒收生产／消费
2. S3 只点名 `_module_rejections` 与 reason 战役名样本，漏退役附属物、错约说明、全部 helper-only 迁约测
3. 枚举命令指向临时 enum 脚本，仓内不存在，不可复跑

本修订：按类定义全文全仓机械枚举；查到合法范围内真实成员一并删简；枚举脚本与 JSON／成员表入仓；消除报告行尾空格（前次 `git diff HEAD^ HEAD --check` exit 2）。

## 枚举命令（可复现）

脚本：`evidence/issue-1835/w5-s1s3-enum.py`

谓词覆盖类定义全文：

- **S1**：单独旧 dict 失败生产（`rejected/invalid: True`）；单独消费（`.get("rejected"|"invalid")` / `["rejected"]`）；同函数双写／双扫；保留 invalid 停续不在删除之列
- **S2**：预检字段白名单／整数平行／势力／炮转移早拒／实体缺失早拒／valid_fields；整封 owner 函数标志位
- **S3**：退役特免与附属名（`_module_rejections` / `EMPTY_EXTRACTION` / 现役错指 `apply_score_extraction`）；现行 docs 战役名锚点／缺 `event_id` 示例；迁约面 helper-only／旧 dict 形状断言

```sh
# 现行工作树
ENUM_ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5 \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/issue-1835/w5-s1s3-enum.py \
  > evidence/issue-1835/w5-s1s3-enum-current.json

# 基线 356（git archive 到临时目录后同脚本）
TMP=$(mktemp -d)
git archive 356eb5f128518ba39936bf9d4ab07fa6f65a2ac7 | tar -x -C "$TMP"
mkdir -p "$TMP/evidence/issue-1835"
cp evidence/issue-1835/w5-s1s3-enum.py "$TMP/evidence/issue-1835/"
ENUM_ROOT="$TMP" \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  "$TMP/evidence/issue-1835/w5-s1s3-enum.py" \
  > evidence/issue-1835/w5-s1s3-enum-baseline-356.json
rm -rf "$TMP"
```

产物：

| 文件 | 含义 |
|---|---|
| `w5-s1s3-enum.py` | 枚举脚本 |
| `w5-s1s3-enum-baseline-356.json` | 356 基线全仓命中 |
| `w5-s1s3-enum-current.json` | 现行 HEAD 全仓命中 |
| `w5-s1s3-members.md` | 成员表与逐成员处置 |

counts：`356 → 现行` = S1 `23→9`，S2 `19→1`，S3 `33→23`（现行残留均为有依据保留／历史名残留，见成员表）。

## 成员处置摘要

### S1（canonical 拒收生产与消费）

| 成员 | 处置 | 依据 |
|---|---|---|
| `covert_progress` dict 回声 + 双写 applied | **已删**（66f7） | 只返回／append `RejectedItem` |
| `month_chain` Phase-3 扫 applied `.get("rejected"/"invalid")` | **已删**（66f7） | 只认 `RejectedItem.category==invalid_enum` 停续 |
| 测试侧 `applied.get("rejected")` 过滤／断言（payoff／month_translate） | **本轮删简** | 单独旧 dict 消费残留 |
| disposition expected 未断言的 `rejected: True` 键 | **本轮删简** | 退役附属键 |
| `due_review` 本地 `{"rejected": True}` | **保留** | 召对待办结果协议；无结算 RejectedItem 双形消费者 |
| `decree_vocabulary["rejected"]`／声明输入 `.get("invalid")` | **保留** | 非拒收通道 |

**invalid 停续合法性**：`month_chain._step_4a_secret_order_supply` 仍在 `invalid_enum` 时 raise，并置 `secret_orders_supply_invalid`；入口案 `test_invalid_declaration_stops_month_chain_and_marks_invalid` 承接。

### S2（领域准入平行权威）

| 成员 | 处置 | 依据 |
|---|---|---|
| 预检字段白名单／`_int_delta_error`／controlled_by／炮转移预判／实体缺失早拒 | **已删**（66f7） | 复用写核拒收 |
| `_strategic_event_result_preflight_error` 整封 | **保留** | 写核拒收→整封失败；noop／结局标签矛盾＝信封规则 |
| 现行枚举 `has_field_whitelist_return/has_int_delta_helper/has_cannon_prejudge_msg` | **均为 false** | 平行准入已退 |

**事件整封归属合法性**：预检仍 savepoint 调 `apply_region_deltas`／`apply_army_delta_with_cannon_transfer`／power 写核，拒收则整封失败并 rollback；与领域准入副本分离，符合判词「事件整封归属职责与领域准入职责分开」。

### S3（退役附属物／错约说明／重复测试）

| 成员 | 处置 | 依据 |
|---|---|---|
| `sanitize_delta_shape` `_module_rejections` 特免 | **已删**（66f7） | 与未知顶层同形拒收 |
| `DELTA_SCHEMA` reason 战役名正教／示例缺 `event_id` | **已对齐**（66f7） | 显式 `event_id`；现行仅负向「不得靠 reason」 |
| `test_retired_legacy_person_keys_normalize_to_nothing_*` | **已删**（66f7） | helper-only；入口负向案已承接 |
| `test_normalize_person_changes_keeps_new_key_items`／`ignores_non_item_shapes` | **本轮删除** | helper-only；`action` 别名迁入既有入口易主案 |
| `credit_events` 仍写 `apply_score_extraction` 为现役入口 | **本轮对齐** | 改为 `settle_delta`／声明分派 |
| 测试名／注释中的 `apply_score_extraction` 历史残留 | **保留** | 非生产特免、非错约教法 |
| 退役史注（simulation／declaration_dispatch／settlement 包说明） | **保留** | 标明已退役 |

## 顾问复核（代码变更合法性）

- **canonical invalid 停续**：合法保留；生产只经 `RejectedItem.category`，不经 applied dict
- **事件整封归属**：合法保留；不再平行做领域字段／整数／炮转移准入
- **未新增**兼容桥／政策表／预演框架／护栏／恢复机制／证明性测试
- **未** amend／stash／push／开 PR

## 聚焦测试（实测）

```sh
rm -rf /tmp/1835-w5-s1s3-retest && mkdir -p /tmp/1835-w5-s1s3-retest/user /tmp/1835-w5-s1s3-retest/pytest
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_TRACE=0 PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR=/tmp/1835-w5-s1s3-retest/user \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1835-w5-s1s3-retest/pytest \
  tests/test_secret_order_payoff_1504.py \
  tests/test_month_chain_1847.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_person_delta_adapter.py \
  tests/test_event_trigger_gate.py \
  tests/test_enrich_list_guards.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_rejection_wiring.py \
  tests/test_month_translate_1840.py \
  tests/test_credit_events_628.py \
  tests/test_region_cannon_delta.py
```

结果见 `w5-s1s3-focused-tests.txt`。未跑全量、未打真模型。

## 未结／阻断

- 本局 S1/S2/S3 施工面：按全文谓词复扫无行动残留
- 不以 commit 冒称已 merge／关票
- 判词正确性 C1/C2 功能事实仍按 #1812 留 #1873；本报告不声称已登记
