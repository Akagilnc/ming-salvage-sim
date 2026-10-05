# #1897 K1 / K2 / F3 apply 回执（第三轮）

- **角色**：修内司劳务引擎（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **基线**：保留 `28697c5ca`（r1）、`8e1b6caf1`（r2）历史提交与报告；本轮独立新 commit
- **判词真源**：末份 `04-1897-judge-21651f2d0.json` 末 payload；未结仅 K1 / K2 / F3
- **禁止项遵守**：无 amend／rewrite／push／PR／stash；无新增护栏／恢复协议／账本／标题恢复器／平行证明测试；不跑全量／真模型；七变量 BIN=/usr/bin/false + PYTHONDONTWRITEBYTECODE=1

**不宣称 merge 或关票。**

---

## 票面／ADR（本轮复读）

| 源 | 要点 |
|---|---|
| #1897 | 真实故障不伪装拒收；正文原样；删旧路；验收=#1812 |
| #1812 | 旧路清退＋复杂度；功能缺口／测试红→#1873 |
| ADR0005 | 真异常响亮，不与脏数据混流 |
| ADR0142 | 结构化事实只走显式契约；禁散文猜绑 |
| 全局 #13/#14 | 删盯文／空壳／影子；闸负向保留；单一真源 |

---

## 完整成员表

见 [`artifacts/1897-k1-k2-f3-member-tables.md`](1897-k1-k2-f3-member-tables.md)
枚举生成器：[`artifacts/1897-f3-enum-gen_tables.py`](1897-f3-enum-gen_tables.py)

### 可执行枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
# K1
rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests
# K2
rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests
# F3：全断言 + 全函数候选（已去掉 HIGH 字段词表收窄）
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$PY artifacts/1897-f3-enum-gen_tables.py
```

本轮枚举结果：`ASSERTS=12960`，`PROSE_HINT候选=2196`，`消费者调用`已扫，`空心=0`，`违规残留=0`。

---

## K1（结清）

前两轮已将进展／月度／到期／结案缺案卷改为 `ValueError("密令进展缺少对应案卷")`。

### 本轮最短真实入口变异

命令：

```bash
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  ../Ming_LLM/.venv/bin/python /tmp/1897-r3-k1k2-mutation.py
```

入口：`stage_pending_action(记进展)` → 删案卷 → `commit_pending_actions`（复用 `create_test_secret_order` 夹具）。

```text
K1_ENTRY=stage->commit_pending_actions
K1_RAISE=ValueError:密令进展缺少对应案卷
K1_PENDING_STATUS=pending
K1_OK
```

未知／非 active 领域拒收与供料读 soft-skip 仍按判词边界保留。

---

## K2（结清）

生产 `title_to_ids` 已删；文档附属物 r2 已补。

### 本轮最短真实入口变异

入口：`prepare_rescript_prewrite` → `commit_rescript_phase1`（只经 bind helper；不调亲裁 HTTP）。

```text
K2_ENTRY=prepare_rescript_prewrite->commit_rescript_phase1
K2_BOUND_AFTER_PREPARE=['mao_wenlong']   # 改写标题后仍绑显式 id
K2_TITLE_ONLY_BOUND=['']                 # 无 id 不得猜绑
K2_OK
```

---

## F3（结清）

### 驳回点纠正

1. 枚举改为**全断言 + 全函数候选**，不再用 HIGH 字段词表宣布结清。
2. r2 空心 style 案（调用 `character_context_with_db` 却断言 `project_relation_ledger`）**整案删除**，不为无关消费者补可变异红证明测试。
3. r2 自报余项（mock answer／summary／label 等）本轮按行为语义清完；mock 确定性文字亦不机械锁正文。
4. 闸类负向保留（空串、P4 裸数、CLI 标签、确定性 builder、流式重放一致性、夹具回读）。

### 本轮处置文件

| 文件 | 处置 |
|---|---|
| `test_style_temperament_641.py` | 删空心整案；去无关导入；性情闸负向保留 |
| `test_audience_restore_505.py` | 去 mock answer／回话正文锁；保留状态／计数 |
| `test_candidate_supply_1893.py` | 去 summary 等值；保留 id／缺 effect |
| `test_highlight_judge_544.py` | 去 answer／seen_reply 正文锁 |
| `test_scene_llm_1836.py` | 去 answer==script／reply∈readings |
| `test_featured_dossiers_494.py` | 去资产散文 `in rendered`；改结构交付／分桶／P4 |
| `test_structured_decree_contract_1624.py` | 去 draft_text 正文锁 |
| `test_pay_order_override_653.py` | 复扫影子 SQL：无命中 |

### 复扫

```bash
rg -n --glob 'tests/**/*.py' 'assert .*\["answer"\]\s*==|assert .*\.answer\s*==|assert seen_reply\s*==|\["summary"\]\s*==' tests
# 仅剩空串结构闸：mechanical_tail / month_chain 的 summary == ""
rg -n 'character_context_with_db|project_relation_ledger' tests/test_style_temperament_641.py
# 无命中
```

空心同形（`character_context_with_db`+`project_relation_ledger` 同案）：**0**。

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
| style + restore + candidate + highlight + scene + featured + structured_decree + binding + pay_order | **174 passed** | **6.96s** |
| K1/K2 mutation probe | K1_OK / K2_OK | **~1.3s** |
| F3 enum regenerator | VIOLATIONS=0 HOLLOW=0 | **~1.5s** |

未跑全量。未跑真模型。

---

## 完成前 advisor 自查

| 问 | 答 |
|---|---|
| F3 是否全断言／全函数候选枚举？ | 是；已去 HIGH 收窄 |
| 是否用字段白名单宣布结清？ | 否；违规残留模式复扫=0 |
| style 空心是否整案删除？ | 是；未另造证明壳 |
| K1/K2 是否最短真实入口变异？ | 是：commit_pending_actions／prepare→commit_phase1 |
| 是否宣称票完成／merge？ | **否** |
| 授权内是否尚有可做工作却交卷？ | **否**；三类均结清 |

---

## 结清声明（授权类）

| 类 | 状态 |
|---|---|
| K1 内部故障与领域拒收混流 | **结清** |
| K2 散文标题猜绑结构化身份 | **结清** |
| F3 盯文换形与测试空心化 | **结清**（违规残留=0；合法闸／结构保留） |

无授权内 blocker。过程史：`artifacts/1897-k1-k2-f3-apply-report.md`、`…-r2.md` 保留；本文件为 r3。
