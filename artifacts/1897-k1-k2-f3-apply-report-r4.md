# #1897 K1 / K2 / F3 apply 回执（第四轮）

- **角色**：修内司劳务引擎（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **基线**：保留 r1–r3 历史提交与报告；本轮独立新 commit
- **判词真源**：末份 `04-1897-judge-21651f2d0.json`；任务聚焦纠正 r3 **F3 假结清**
- **禁止项遵守**：无 amend／rewrite／push／PR／stash；无新增护栏／恢复协议／平行证明测试；不跑全量／真模型；七变量 BIN=/usr/bin/false + PYTHONDONTWRITEBYTECODE=1

**不宣称 merge 或关票。**

---

## 票面／法（本轮复读）

| 源 | 要点 |
|---|---|
| #1897 | 真实故障不伪装拒收；正文原样；删旧路；验收=#1812 |
| #1812 | 旧路清退＋复杂度；功能缺口／测试红→#1873 |
| 全局 #13/#14 | 删盯文／空壳／影子；闸负向保留；单一真源 |
| 锚定宪法 | 测试不得机械依赖自由文本 |
| P7 射程 | 界面固定话语≠人物回话／叙事 |

---

## r3 假结清纠错（本轮起因）

1. 成员表自身列出 `杨嗣昌御前低语`／`臣已入殿`／`边务如何`／`MIDCOURSE_ISSUE`，却宣称违规残留=0。
2. Python「2065 笼统合法」与「夹具回读豁免」未经语义核。
3. Web 368 只列前 20，未全读。
4. 空心只扫 `context+relation` 同案；分类器 `dispose_*` 自动标合法。

---

## 枚举（精确命令与输出）

### 扫描器

已删 `artifacts/1897-f3-enum-gen_tables.py`（自动分类器）。新审计脚本：

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
../Ming_LLM/.venv/bin/python artifacts/1897-f3-enum-scan.py
```

输出：

```text
{
 "python_candidates": 4386,
 "python_cjk": 2809,
 "web_candidates": 250,
 "web_cjk": 135,
 "consumer_calls": 86,
 "tests_with_consumers": 65,
 "note": "candidates only; legality requires hand semantic review"
}
OUT /tmp/1897-r4-f3-enum
```

### K1 / K2 复扫

```bash
rg -n --glob '*.py' '缺少案卷|密令进展缺少对应案卷' ming_sim
rg -n --glob '*.py' 'title_to_ids|按唯一标题' ming_sim tests
```

K1：`ValueError("密令进展缺少对应案卷")` 仍在 db／covert_progress。
K2：无 `title_to_ids`／`按唯一标题` 命中。

---

## 完整成员处置清单

见：

- [`artifacts/1897-k1-k2-f3-member-tables.md`](1897-k1-k2-f3-member-tables.md)
- [`artifacts/1897-f3-web-disposition-r4.txt`](1897-f3-web-disposition-r4.txt)（Web 250 条全量）
- [`artifacts/1897-f3-web-changed-assertions-r4.txt`](1897-f3-web-changed-assertions-r4.txt)
- [`artifacts/1897-f3-python-disposition-r4.txt`](1897-f3-python-disposition-r4.txt)

### 本轮主要处置文件

| 文件 | 处置 |
|---|---|
| `web/src/appDurableWiring.test.tsx` | 回话／议题／邸报正文锁→结构；清 MIDCOURSE 负向盯文 |
| `web/src/components/modals.test.tsx` | 场景／回话／史册正文→turn／segment 结构 |
| `web/src/components/decisionModal.test.tsx` | 题名／选项正文→section／option 结构 |
| `web/src/components/settlementGazettePanel.test.tsx` | 邸报正文→pre 存在 |
| `web/src/components/situation.test.tsx` | commitment／memorial／title→结构节点 |
| `web/src/components/settlementFaces.test.tsx` | 议题 title→closed-row |
| `web/src/mindreadingDelivery.test.tsx` | rows 正文→role@turn；pending 身份保持 |
| `web/src/ministerScrollLens.test.ts` | content 数组→role/speaker/turn/beat |
| `web/src/staleGuard.test.tsx` | 回话／历史正文→身份前缀 |
| `web/src/useSettlementFlow.test.tsx` | 史评正文→节点／busy |
| `tests/test_audience_restore_505.py` | 夹具问话／回话回读→turn/role |
| `tests/test_audience_scroll_539.py` | content 列表→role/speaker/audibility/beat |
| `tests/test_audience_continuous_507.py` | recap 正文→audible_entries_for id |
| `tests/test_recommendation_edges_635.py` | context==夹具→跨字段／身份保持 |
| `tests/test_relation_brew_636.py` | context 散文→origin/event_kind |
| `tests/test_relation_seed_638.py` | recent_context 片段→key |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | 邸报字面→库列同源 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | projection content→role/turn |
| `artifacts/1897-f3-enum-scan.py` | 新 AST 审计（不判合法） |
| 删除 `artifacts/1897-f3-enum-gen_tables.py` | 去自动分类器 |

---

## 聚焦实测（精确命令与输出）

前缀（七变量写全，无花括号伪命令）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
```

### Python

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-r4-pytest2 \
  tests/test_audience_restore_505.py \
  tests/test_audience_scroll_539.py \
  tests/test_audience_continuous_507.py \
  tests/test_recommendation_edges_635.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  tests/test_qa_t1_extraction_dual_source_1353.py
```

输出：

```text
125 passed, 1 warning in 7.18s
```

（另含 style／pay_order 等同族复测曾跑通；上列为本轮 Python 改动面最终命令。）

### Web

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5/web
npm test -- \
  src/appDurableWiring.test.tsx \
  src/components/modals.test.tsx \
  src/components/decisionModal.test.tsx \
  src/components/settlementGazettePanel.test.tsx \
  src/components/situation.test.tsx \
  src/mindreadingDelivery.test.tsx \
  src/ministerScrollLens.test.ts \
  src/useSettlementFlow.test.tsx \
  src/components/settlementFaces.test.tsx \
  src/staleGuard.test.tsx
```

输出：

```text
Test Files  10 passed (10)
     Tests  207 passed (207)
```

未跑全量。未跑真模型。`web/node_modules` 由本机 `npm ci` 安装且已被 `.gitignore` 忽略，不入提交。

### 修后残留窄扫

自由正文 FIELD_EQ／点名反例形状：`WEB_BAD=0`，`PY_BAD=0`。

---

## 完成前自查

| 问 | 答 |
|---|---|
| 是否纠正 r3 成员表反例假结清？ | 是 |
| Web 是否全候选语义处置表？ | 是（250 行文件） |
| 是否用自动分类器宣布结清？ | 否；已删 |
| 是否夹具正文豁免／非空换形保壳？ | 否 |
| 是否另造平行证明测试？ | 否 |
| 是否宣称票完成／merge？ | **否** |
| K1/K2？ | 复扫维持结清；本轮焦点 F3 |

---

## 结清声明（本轮授权类）

| 类 | 状态 |
|---|---|
| K1 | **维持结清**（复扫） |
| K2 | **维持结清**（复扫） |
| F3 | **本轮纠正后结清**（真扫＋逐项处置；非 r3 笼统 0） |

过程史 r1–r3 报告保留；本文件为 r4。trailing 空白已清理 r2／r3／本文件。
