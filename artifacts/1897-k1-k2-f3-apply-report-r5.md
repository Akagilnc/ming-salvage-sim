# #1897 K1 / K2 / F3 apply 回执（第五轮）

- **角色**：修内司劳务引擎（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **判词真源**：末份 `04-1897-judge-21651f2d0.json`（K1／K2／F3）
- **本轮焦点**：纠正 **r4 F3 假结清**——跨字段／输入输出／集合 distinct／len／非空／type 的自由正文换形**不是**合法结构契约
- **禁止项遵守**：无 amend／rewrite／push／PR／stash；无新增审计分类器／通用机制／平行证明测试；不改法；不跑全量／真模型；七变量 BIN=/usr/bin/false

**不宣称 merge 或关票。**

---

## r4 假结清纠错（本轮起因）

r4 回执与 disposition 把下列**散文等值**标成「跨字段／同源合法」：

| 位置 | r4 误称 | 末判 F3／本轮法 |
|---|---|---|
| `tests/test_recommendation_edges_635.py` `all(e['context']==event['reason'])` | 跨字段合法 | **非法**：两自由正文字段等值 |
| 同文件 `len(contexts)==1` + `next(iter(contexts))!=reason2` | 身份保持 | **非法**：集合 distinct／与夹具不等仍锁正文 |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` `body==stored['report']` | 库列同源 | **非法**：投影与列的散文等值 |
| 同族 `detail==reason.strip()`、夹具子串、`isinstance`/`not.toBe("")`/`len` | 结构／非空 | **非法换形** |

**r4「跨字段就合法」与末判 F3 完全相反。本轮纠正该误报，不改法。**

无豁免：跨字段回读、raw preserve、流式重放、夹具正文。

---

## 票面／法（复读，未改）

| 源 | 要点 |
|---|---|
| 末判 F3 | 自由正文机械比较、专为其存在的证明案、影子／空壳测试按行为语义清退 |
| 全局 #13/#14 | 删盯文／空壳；闸负向保留；单一真源 |
| 锚定宪法 | 测试不得机械依赖自由文本 |
| P7 射程 | 界面固定话语≠人物回话／叙事 |
| #1812 | 旧路清退；功能缺口／测试红→#1873 |

---

## 枚举命令（精确）

### 既有静态候选（不自动判合法）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
../Ming_LLM/.venv/bin/python artifacts/1897-f3-enum-scan.py
```

### 本轮跨字段／换形复扫（tmp，不进仓分类器）

输出：`/tmp/1897-r5-cross-final.txt`（修后 `cross_total=22`；除去 KEEP 结构／错误通道后，仅余两条 UI 闸固定话语，见下）。

### K1 / K2 复扫

```bash
rg -n --glob '*.py' '缺少案卷|密令进展缺少对应案卷' ming_sim
rg -n --glob '*.py' 'title_to_ids|按唯一标题' ming_sim tests
```

- K1：`ValueError("密令进展缺少对应案卷")` 仍在 db／covert_progress（响亮故障）。
- K2：无 `title_to_ids`／`按唯一标题`。

---

## 完整成员处置（本轮动手面）

详见 [`artifacts/1897-f3-disposition-r5.txt`](1897-f3-disposition-r5.txt)。

### 清退／整案删除（无独立结构契约的正文证明）

| 成员 | 处置 |
|---|---|
| `test_real_entry_persists_raw_reason_verbatim` | **整案清退**（落账契约已由 `test_approved_recommendation_writes_both_edges_atomically` 等复用） |
| `merge_founding_segment_*` 四案（字节／逐字追加） | **整段删除** |
| `test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical` | 改为大体积落摘要**结构**（不锁字节） |
| recommendation `context==reason`／`len(contexts)`／`!=reason2` | 删 |
| qa_s2 `body==stored['report']`、夹具子串、`detail==reason.strip()` | 删；月份／409 闸保留并更名 |
| audience_scroll `content` 跨投影等值 | → role/speaker/chat_turn_id |
| relation_brew／seed 段正文等值、context 成员、整行逐字段 | → 水位／dimension／origin／id |
| chatFailures `temp===done.answer`／`length>0`／空 answer | → reset 次数／admission |
| appDurableWiring `gazetteReport not.toBe("")` | → `gazettePanel` 节点存在 |
| situation progress trim 非空 | → 节点存在 |
| cli／deepseek／draft／on_scene／month_recovery／surcharge／secret_order／opening_gazette 正文等值 | 按结构闸清退 |

### 保留（真实结构契约；不得虚称 verbatim）

| 成员 | 为何合法 |
|---|---|
| `reign_period_label` 月份投影相等／不等 | 历法标签身份 |
| recommendation 边 `origin`／`event_kind`／任命 office | 结构化落账 |
| relation `last_event_id`／`dimension`／pending 对 | 水位／身份 |
| HTTP 409、admission 码、error `code`／固定闸文案 | 闸／错误通道／P7 界面固定话语 |
| `_IN_FLIGHT_DETAIL`／`_GATE_BUSY_DETAIL` in text | UI 过月／忙闸固定话语（P7） |
| 人物名／office／closed reason_code／terminal_reason 枚举 | 结构化身份／闭集 |

---

## 聚焦实测（精确命令与输出）

前缀：

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
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-r5-pytest-final \
  tests/test_recommendation_edges_635.py \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  tests/test_audience_scroll_539.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_cli_backend.py \
  tests/test_cli_play_turn.py \
  tests/test_deepseek_thinking_disable_1797.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_on_scene_immediate_write_1839.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_continuous_507.py \
  tests/test_qa_t1_extraction_dual_source_1353.py
```

输出：`352 passed, 1 warning in 12.50s`

### Web

```bash
cd web && npm test -- \
  src/chatFailures.test.ts \
  src/appDurableWiring.test.tsx \
  src/components/situation.test.tsx
```

输出：`Test Files  3 passed (3) / Tests  70 passed (70)`

（r4 同族其余 web 文件本轮无再改断言形状；上列为触及面。）

---

## 完成前自查二连

| 问 | 答 |
|---|---|
| 是否纠正 r4「跨字段合法」假结清？ | **是** |
| 是否整案清退 `real_entry_persists_raw_reason_verbatim`？ | **是** |
| 是否仍用非空／len／type／跨字段正文等值换形保壳？ | **否** |
| 是否新增分类器／平行证明测试？ | **否** |
| 是否改法／amend／push／PR？ | **否** |
| K1/K2？ | 复扫维持结清 |
| 是否宣称 merge？ | **否** |

---

## 结清声明（本轮授权类）

| 类 | 状态 |
|---|---|
| K1 | **维持结清**（复扫） |
| K2 | **维持结清**（复扫） |
| F3 | **本轮纠正 r4 误报后结清**（全仓跨字段复扫＋行为语义处置；非词表豁免） |
