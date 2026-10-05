# #1897 K1 / K2 / F3 apply 回执

- **角色**：修内司劳务引擎（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`（自 `21651f2d0` 新开）
- **判词真源**：末份 `04-1897-judge-21651f2d0.json` 末 payload；未结仅 K1 / K2 / F3
- **票面**：#1897（总票 #1812）；ADR0005 / ADR0142
- **官方检索**：Python 异常应在可恢复边界外传播，勿把内部故障洗成业务拒收（Real Python exception handling；OpenSSF pyscg-0016 Propagate Exceptions）。本仓复用既有 `ValueError("密令进展缺少对应案卷")`（`mark_secret_order_in_progress` / `_update_secret_order_sim_note`）。
- **禁止项遵守**：无 amend / rewrite / push / PR / stash；无新增护栏／恢复协议／账本／标题恢复器／平行证明测试；不跑全量／真模型；七变量 BIN=/usr/bin/false。

**不宣称 merge 或票完成。**

---

## 施工前 advisor 自查

| 问 | 答 |
|---|---|
| 能否删除优先？ | 是：K2 删标题猜绑；F3 删空心案／盯文案；K1 改既有接缝为 raise，不造新协议 |
| 是否复用既有故障契约？ | 是：与 `mark_secret_order_in_progress` 同文 `ValueError`；`commit_pending_actions` 对非 typed 领域拒收已 `raise` 保留 pending |
| 是否越权补案卷／护栏？ | 否 |
| 质量法 #13/#14 | F3 删影子 SQL／空心消费者；必要行为走 `character_context_with_db` + 结构化日志计数，不锁 style 散文 |

---

## K1 内部故障与领域拒收混流

### 边界（判词原文）

已合法准入的在办密令，其必需案卷关系缺失时的进展、到期、结案接缝。

### 枚举命令

```bash
rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests
rg -n --glob '*.py' -A3 -B3 'get_dossier_for_secret_order' ming_sim
rg -n '密令缺少案卷|密令进展缺少对应案卷' ming_sim --glob '*.py'
```

### 完整成员处置表

| # | 成员 | 接缝 | 原状 | 处置 | 依据 |
|---:|---|---|---|---|---|
| 1 | `db._note_secret_order_report` active 缺案卷 `return False` | 进展 | 洗成 False → pending `failed` | **改 raise** `ValueError("密令进展缺少对应案卷")` | ADR0005；复用 mark 同文 |
| 2 | `db.update_secret_order_progress`（经 #1） | 进展 | 同上 | **随 #1** | 同上 |
| 3 | `db.submit_secret_order_for_review` 非空 claim（经 #1）；空 claim 仍走 mark | 进展／核议 | mark 已 raise | **保留**（#1 对齐） | 既有 mark 契约 |
| 4 | `db._update_secret_order_sim_note_in_transaction` 缺案卷 raise | 实况进展 | 已 raise | **合法保留** | 已是响亮故障 |
| 5 | `db.mark_secret_order_in_progress` 缺案卷 raise | 在办轴 | 已 raise | **合法保留**（真源句） | 判词点名既有实现 |
| 6 | `db.close_secret_order` 缺案卷仍写 `status=done` | 结案 | 半截成功 | **改 raise** 后再写轴 | 不得可成功 |
| 7 | `covert_progress.apply_monthly_covert_actual_progress` 缺案卷 `rejected`+continue | 月度进展 | 拒收跳过 | **改 raise** | 不得可拒收／可跳过 |
| 8 | `covert_progress.settle_due_secret_orders` 缺案卷 `rejected`+continue | 到期 | 拒收后月链仍可标阶段完成 | **改 raise** | 不得可跳过；故障中止阶段 |
| 9 | `month_chain` Phase4 / drift 调 `settle_due_secret_orders` | 到期编排 | 依赖 #8 软拒收 | **随 #8**（异常走既有 `_abort_4a`／atomic） | 不另造恢复协议 |
| 10 | `_note` / progress 对 unknown／non-active `return False` | 进展 | 领域拒收 | **合法保留** | 判词：未知／非 active 仍逐项拒收 |
| 11 | apply 内 fidelity／查案声明 `invalid_enum` rejected | 进展 | 领域坏项 | **合法保留** | 真正领域坏项 |
| 12 | `find_active_investigation_order_id` dossier None continue | 查找 | soft skip | **边界外保留** | 非进展／到期／结案写接缝 |
| 13 | `month_chain._attach_investigation_facts` / `build_secret_orders_supply_feed` 缺案卷空 notes | 供料读 | soft skip | **边界外保留** | 读／供料，非本类写接缝 |
| 14 | `materials` 密令实况原文 dossier None continue | 供料读 | soft skip | **边界外保留** | 同上 |
| 15 | `merge_investigation_confirmation` 已 raise CovertContractError | 查案合流 | 已响亮 | **合法保留** | 已符合方向 |
| 16 | `due_review`「案卷不存在」rejected | 到期复核他域 | 领域拒收 | **边界外保留** | 非密令必需案卷关系写接缝 |
| 17 | `declaration_dispatch` 核议／进展对非 active 的 `invalid_state` | 声明准入 | 领域拒收 | **合法保留** | 未知／非 active |

### 根因

active 密令缺案卷是内部关系故障，却在进展写口返回 False、在月度进展／到期结案返回 `rejected` 并 continue，结案口甚至只改密令轴不写执行格。`commit_pending_actions` 把 False 标成 `failed` 终结暂存；月链把软拒收当可完成阶段。既有 `mark_secret_order_in_progress` 已对同类缺失 raise——混流来自分叉处理，不是缺少新协议。

### 修改后复扫

```text
ming_sim/covert_progress.py:1840 raise ValueError("密令进展缺少对应案卷")
ming_sim/covert_progress.py:2082 raise ValueError("密令进展缺少对应案卷")
ming_sim/db.py:22023 raise（close）
ming_sim/db.py:22094 raise（_note）
ming_sim/db.py:22207 / 22236 既有 raise 保留
「密令缺少案卷」rejected 生产路径：已无
```

### 临时变异证据（秒级；已删 `tests/_tmp_1897_k1k2f3_probe.py`）

- 删案卷后：`update_secret_order_progress` / `apply_monthly_covert_actual_progress` / `settle_due_secret_orders` / `close_secret_order` → `ValueError("密令进展缺少对应案卷")`；close 后 status 仍 `active`。
- unknown id／status=`done` → `update_secret_order_progress` 仍 `False`（领域拒收）。
- `commit_pending_actions` 缺案卷 → raise，pending 仍 `pending`。
- 对照变异：monkeypatch `_note_secret_order_report`→`return False` → pending 被标 `failed`（旧混流形状）。

---

## K2 散文标题猜绑结构化身份

### 边界（判词原文）

呈现标题用于补造或重绑 event_id 的旧兼容路径及其附属物。

### 枚举命令

```bash
rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|unique.*title|按.*标题|标题.*绑' ming_sim tests
rg -n 'title_to_ids|按唯一标题|binds_from_unique_title' ming_sim tests --glob '*.py'
```

### 完整成员处置表

| # | 成员 | 原状 | 处置 | 依据 |
|---:|---|---|---|---|
| 1 | `settlement_payload.bind_decisions_to_candidate_events` `title_to_ids` 唯一标题补／重绑 | 生产兼容 | **删除**标题索引与补绑分支 | ADR0142／#1812 旧路清退 |
| 2 | 同函数：候选内显式 `event_id` 采信 | 显式引用 | **合法保留** | 沿现有显式结构化引用 |
| 3 | 同函数：`dossier:` + rescript capability 保留 | 批红前缀 | **合法保留** | #1490/#1492；非标题猜绑 |
| 4 | 同函数：off-snapshot 显式 id 解绑 | 防污染终态账 | **合法保留**（无标题回退） | 显式路径 |
| 5 | `session.prepare_rescript_prewrite` 调 bind | 亲裁入口 | **保留调用**；注释去掉「标题重绑」 | 承接显式绑定 |
| 6 | `tests/test_decision_event_binding_389.py` 标题补绑／标题重绑案 | 锁定旧兼容 | **改／删**：缺 id／off-snapshot 均不解绑靠标题 | 附属物清退 |
| 7 | `test_pihong_*` dossier: 前缀 bind 闸 | 结构化前缀 | **合法保留** | 非标题猜绑 |
| 8 | `docs/test-cleanup-audit-1185.md` 旧 keep 行 | 文档史 | **未改**（非生产路径；余项） | 不扩文档施工 |
| 9 | `TODOS.md` #389 标题残留叙述 | 文档 | **未改**（余项） | 本轮不恢复全部事件功能 |

### 根因

`bind_decisions_to_candidate_events` 在缺 id／off-snapshot 时用呈现标题唯一匹配补造 `event_id`，亲裁入口经 `prepare_rescript_prewrite` 落入选择账——标题改写即可改变结构化身份。

### 修改后复扫

```text
title_to_ids / 按唯一标题 / binds_from_unique_title：生产与测试 .py 无命中
```

### 临时变异证据

- 标题「标题证据」仅 title、无 id → 无 `event_id`。
- 显式 `mao_wenlong` + 标题「改写标题」→ 仍绑定 `mao_wenlong`。
- off-snapshot id + 同标题 → 解绑（不再标题重绑）。

---

## F3 盯文换形与测试空心化

### 边界（判词原文）

自由正文机械比较、专为其存在的证明案，以及修理后复制生产规则或不再调用所称消费者的测试。

### 枚举命令

```bash
rg -n --glob 'tests/*.py' -e 'assert\s+.+\bstyle\b' tests/test_style_temperament_641.py
# 扩扫 before/after 经 helper：
rg -n '_style_row|assert .*style' tests/test_style_temperament_641.py
rg -n --glob 'tests/*.py' 'turn_region_summary|settle_官俸欠_|settle_宗禄欠_' tests/test_pay_order_override_653.py
rg -n --glob 'tests/*.py' 'character_context_with_db' tests/
# 语义：函数名含消费者但 body 无调用
python3 - <<'PY'
# （见施工记录）扫描 test_* 是否 invoke character_context_with_db(
PY
```

### 完整成员处置表

| # | 成员 | 形状 | 处置 | 依据 |
|---:|---|---|---|---|
| 1 | `test_style_temperament_641.py` 各案 `_style_row` / `content...style` before／after 等值／不等 | 自由 style 正文机械比较 | **删除散文比较**；改 `person_logs` 性情计数 + applied 结构 | 边界全文；非字段词表收窄 |
| 2 | 同文件闸负向 `rejected`/`invalid_enum`/`hallucinated_id` | 闸类负向 | **合法保留**（结构化 category／item） | 质量法闸负向不可删 |
| 3 | `test_character_context_with_db_reads_own_style_and_viewer_ledger` 不调用 `character_context_with_db` | 空心／影子 | **改为真调用**消费者；关系账仍 `project_relation_ledger` 结构断言；不锁返回散文 | 判词点名样本 |
| 4 | `test_pay_order_override_653.py::test_turn_region_summary_claim_audit_rows_do_not_consume_limit` 复制 `NOT LIKE settle_*欠_*` SQL，不调 `turn_region_summary` | 影子规则空心 | **整案删除** | 删非法案而非换断言洗绿 |
| 5 | `test_featured_dossiers_494.py` 真调用 `character_context_with_db` | 他域真入口 | **合法保留** | 非空心 |
| 6 | `turn_region_summary` 生产实现 | 生产 | **不动** | 只删影子测试 |
| 7 | 历史 F3 词表大表（artifacts/1897-f3-member-table-75.md）中已结 FORM_ENUM／SSE／GATE_NEG 等 | 他轮结清 | **本轮不重开**；本轮谓词命中仅上表 1–4 | 不得以旧窄词表宣布结清；本轮按现行边界语义扫 |

### 根因

性情测试用自由 style 正文 before／after 充当「已写入」身份；自称读 `character_context_with_db` 的案不再调用该消费者；claim 过滤案复制生产 SQL 而不经 `turn_region_summary`——变异生产函数抛错测试仍绿。

### 修改后复扫

```text
test_style_temperament_641.py：无 _style_row；有 character_context_with_db( 真调用
test_pay_order_override_653.py：无 settle_官俸欠_ 影子 SQL／无 test_turn_region_summary_claim
```

### 临时变异证据

- monkeypatch `tests.test_style_temperament_641.character_context_with_db` → `RuntimeError`：该案红（MUTATION_F3_style_test）。
- 跳过新增永久测试：与任务「不为证明修复造永久测试」／质量法⑤冲突；证据用 `/tmp` 与已删 `tests/_tmp_*` 探针。

---

## 聚焦实测

前缀：

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

| 批次 | 结果 | 墙钟 |
|---|---|---|
| 探针 + binding + style + pihong bind 二闸（focused-6） | **25 passed** | real **1.45s** |
| 上列 + progress verbatim + dossier progress 二案 + pay_order revoke + 对照变异（focused-7） | **30 passed** | real **1.85s** |

未跑全量。未跑真模型。

### 失败诚实留存

- 临时探针曾误用颁布当月调用 `apply_monthly_covert_actual_progress`（`_is_issuance_turn` 跳过）→ 伪「未 raise」；将 `turn_issued` 置为上月后复现真 raise。属探针误构，非生产回退。
- `docs/test-cleanup-audit-1185.md` / `TODOS.md` 仍有旧「标题补绑」叙述：文档余项，未本轮改。

### 测试改动必要成本

| 文件 | 净变化意图 |
|---|---|
| `tests/test_decision_event_binding_389.py` | 去掉标题猜绑锁定；保留显式 id／解绑契约 |
| `tests/test_style_temperament_641.py` | 去 style 盯文；接真消费者；闸负向保留 |
| `tests/test_pay_order_override_653.py` | 删除空心影子 SQL 整案 |

生产 diffstat：`7 files changed, 73 insertions(+), 180 deletions(-)`（含测试；删除优先）。

---

## 完成前 advisor 自查

| 问 | 答 |
|---|---|
| 三类是否按完整 boundary 枚举而非只修样本？ | 是；表内含合法保留与边界外项 |
| 是否新增护栏／恢复／账本／标题恢复器？ | 否 |
| F3 是否靠字段词表洗绿？ | 否；按消费者调用与正文比较语义处置 |
| 暂存是否在真故障下保留？ | 是（raise → commit_pending 不标 failed） |
| 是否宣称 merge／关票？ | **否** |

---

## 余项

1. 文档史中的标题补绑表述（`TODOS.md` / cleanup audit）未同步。
2. 供料读路径对缺案卷 soft skip（K1 表 #12–14）不在本类写接缝；若后续要把读路径也响亮化，另裁。
3. 不恢复「缺 id 仍能绑定事件」的玩法；按 #1812／判词 K2，本轮门槛不是恢复全部事件功能。
4. 本回执不表示 #1897 已 merge 或票关闭。
