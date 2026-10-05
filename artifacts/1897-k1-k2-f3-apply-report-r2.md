# #1897 K1 / K2 / F3 apply 回执（第二轮）

- **角色**：修内司劳务引擎（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **基线**：首轮 commit `28697c5ca` 保留不销毁；本轮在其上续修
- **判词真源**：末份 `04-1897-judge-21651f2d0.json` 末 payload；未结仅 K1 / K2 / F3
- **票面**：已 `gh issue view` #1897／#1812；ADR0005／ADR0142 已读
- **驳回点**：首轮 F3 枚举只扫点名 style/payorder/character_context，且称历史 75 表不重开——违反全仓机械枚举完整类边界；K2 文档附属物不得自称超范围；style 空壳须重审
- **禁止项遵守**：无 amend／rewrite／push／PR／stash；无新增护栏／恢复协议／账本／标题恢复器／平行证明测试；不跑全量／真模型；七变量 BIN=/usr/bin/false + PYTHONDONTWRITEBYTECODE=1

**不宣称 merge 或票完成。**

---

## 票面／ADR 阅读证据

| 源 | 读到的要点 |
|---|---|
| #1897 | 真实故障不伪装拒收；正文原样；删旧路；验收唯一真源=#1812 |
| #1812 | 重构验收：旧路清退＋复杂度；功能缺口／测试红不阻收敛→#1873 |
| ADR0005 | 代码侧真异常必须响亮；不得与 LLM 脏数据混流 |
| ADR0142 | 结构化事实只走显式契约；禁散文猜绑 |

---

## 完整成员表

见独立文件：[`artifacts/1897-k1-k2-f3-member-tables.md`](1897-k1-k2-f3-member-tables.md)  
枚举生成器副本：[`artifacts/1897-f3-enum-gen_tables.py`](1897-f3-enum-gen_tables.py)（亦可 `/tmp/1897-f3-enum/gen_tables.py`）

统计：Python 测试 235 文件；Web 测试 25 文件；F3 高置信现行命中 23 行（本轮清退后），全表含合法保留与余项，**不虚报整类结清**。

### 可执行枚举命令（摘要）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
# K1
rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests
# K2
rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests
rg -n '唯一标题|title_to_ids|标题补绑|标题重绑|猜绑' TODOS.md docs/test-cleanup-audit-1185.md
# F3 全仓
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$PY artifacts/1897-f3-enum-gen_tables.py
find tests -name '*.py' | wc -l
find web \( -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx' \) | wc -l
```

---

## K1

首轮已将进展／到期／结案缺案卷改为 `ValueError("密令进展缺少对应案卷")`。本轮按判词全文复扫进展／到期／结案故障链（含 `commit_pending_actions` 对非 typed Exception raise 且不标 failed）；未知／非 active 仍 `False`；供料读 soft-skip 按判词边界外保留（非擅自加「仅写接缝」窄化——判词边界本就写明进展／到期／结案）。

### 变异（秒级；`/tmp/1897-k1k2-mutation-probe.py`）

**绿（现行）**：

```text
progress/monthly/due/close → RAISE:密令进展缺少对应案卷；close 后 status=active；unknown→False
```

**红（装回旧真实逻辑：缺案卷 return False／rejected＋continue／半截 close）**：

```text
progress=False；monthly=[{rejected, reason:密令缺少案卷}]；due=[{rejected}]；close_status=done
```

---

## K2

生产 `title_to_ids` 已删（首轮）。本轮补附属物现役说明：

- `TODOS.md` #389：标明唯一标题猜绑已退休；残留改为「无显式共享键」
- `docs/test-cleanup-audit-1185.md`：保留过程史，改写现行测试名／负向闸／退休行

### 变异

**现行 `bind_decisions_to_candidate_events`**：

```text
title_only→None；explicit+改写标题→mao_wenlong；off-snapshot 同标题→None
```

**装回旧唯一标题补绑**：

```text
title_only→mao_wenlong；explicit 仍绑；off-snapshot 同标题→mao_wenlong（重绑）
```

`prepare_rescript_prewrite`（`session.py:2071`）调用同一 `bind_decisions_to_candidate_events`；本轮以该真实绑定入口＋`tests/test_decision_event_binding_389.py` 负向闸观察结构化 `event_id`。完整 desk／awaiting_decision 亲裁夹具未另造平行证明体系。

---

## F3

### 首轮 style 空壳重审

- 删除 `isinstance(ctx,str) and ctx`（类型／非空换形）
- 删除该案上的 temperament 日志垫衬（不以日志计数保「读 style」空壳）
- 真调用 `character_context_with_db`；外部契约改为 `project_relation_ledger` 结构化端点
- 闸类负向（blank／invalid_enum／hallucinated_id）保留
- 性情 `person_logs action=性情` 为结构化审计落账（非自由 style 正文锁）；与「用日志计数换掉唯一承重正文断言保空壳」不同——该案仍有独立 apply／inertia／rollback 入口

### 本轮另清高置信叙事盯文（全仓 AST 后语义复核）

| 文件 | 处置 |
|---|---|
| `test_credit_events_628.py` | 删 context 等值／成员／strip |
| `test_execution_joint_liability_565.py` | 删 execution_note 成员／等值；保留 outcome+restore |
| `test_relation_read_640.py` | 删 summary／context 散文锁 |
| `test_recommendation_edges_635.py` | 删 context==reason |
| `test_relation_store_632.py` | restore 不再等值 context |
| `test_audience_translation_1838.py` | 删 context 等值 |
| `test_authority_ledger_611.py` / `test_faction_brew_637.py` | 删 context 模板等值 |
| `test_six_sciences_seed_608.py` | 删 summary 史源成员 |
| `test_pay_order_override_653.py` | 首轮已删影子 SQL；本轮复扫无命中 |

余项（mock answer 透传、部分 summary/label 等）列入成员表，**据实不虚报结清**。

### F3 变异

```text
monkeypatch character_context_with_db → RuntimeError("shadow")
→ tests/_tmp_1897_f3_style_mut.py RED（1 failed）；删临时案后原案 GREEN（1 passed）
```

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
| style + binding + credit + execution_note + relation_* + recommendation + audience_translation + authority + faction_brew + six_sciences + pay_order | **138 passed** | **2.16s** |
| F3 mutant RED | **1 failed** | **0.63s** |
| F3 restored GREEN | **1 passed** | **0.68s** |
| K1/K2 mutation probe | 见上 | **~1.2s** |

未跑全量。未跑真模型。

---

## 完成前 advisor 自查

| 问 | 答 |
|---|---|
| F3 是否全仓机械枚举？ | 是；命令＋成员表落 artifacts |
| 是否用字段白名单宣布结清？ | 否；余项据实列出 |
| K2 文档是否补绑？ | 是；TODOS + cleanup audit |
| 是否新增机制？ | 否；只删简 |
| 是否宣称票完成？ | **否** |

---

## 余项

1. F3 成员表中 mock answer／部分 summary·label 余项未本轮清空。
2. 供料读缺案卷 soft-skip 仍边界外。
3. 不恢复「缺 id 仍能靠标题绑定事件」玩法。
4. 首轮报告 `artifacts/1897-k1-k2-f3-apply-report.md` 保留为过程史；本文件为第二轮回执。
