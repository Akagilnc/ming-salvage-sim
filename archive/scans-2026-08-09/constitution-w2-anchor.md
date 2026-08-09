扫描口径：法源「锚定宪法」——**机器只咬契约，不咬呈现**；对象为 PR #1087（`family/497`，#498–#507）合入 `main` 后的交付文件现状。在场/可闻性主干（`presence_effect`、口令常量标）未发现用开放 tags / 正文驱动机器态。

---

# W2 锚定宪法违宪清单

法源：`ak-pi-workflow-roles/CLAUDE.md`「锚定宪法」——「机器只咬契约，不咬呈现：对自由文本的正则/措辞/表头机械依赖、对图像的像素机械依赖，视同缺陷；机器要消费的信息必须以键、typed 字段或 schema 提供。呈现为人服务，随时可重排。」  
兼对照全局 SHARED #13「盯文（对自由文本建机械依赖）」与 PRD #497 Testing Decisions「不锁叙事文本」。

---

## P0 — 生产路径用呈现格式当机器输入

### 1. 入殿身份种子靠拆 `minister_dossier` 呈现串，不读 typed `identity`
- **位置** `ming_sim/beat_orchestration.py:220-222`（消费端）；对照真源 `ming_sim/context.py:217-226`（typed 字段已存在，再渲染成「身份：…；脾性：…」）
- **违反条文** 「对自由文本的…措辞/表头机械依赖」「机器要消费的信息必须以键、typed 字段或 schema 提供」
- **证据**
```python
if raw.startswith("身份："):
    raw = raw[3:]
return raw.split("；", 1)[0].strip()
```
- **说明** W2 #503 / #497 R2 引入 `_identity_snippet`：dossier JSON 已有 `identity` 键，生产却依赖呈现分隔符「身份：」「；」。表头/分段文案一改，入殿账种子即断。属机器咬呈现。

---

## P1 — 测试盯呈现文案 / 表头措辞

### 2. 开夜/收夜兜底正文 golden-text 硬等
- **位置** `tests/test_beat_orchestration_503.py:143`、`:148`、`:236`
- **违反条文** 「对自由文本的…机械依赖」；SHARED #13「盯文」；PRD「不锁叙事文本」
- **证据**
```python
assert _ledger_body(db, night_id, an.TAG_OPEN_NIGHT) == "乾清宫·戌时，召对夜启。"
assert _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT) == "退朝，今夜召对到此。"
```
- **说明** 锁引擎兜底日记措辞整句。呈现可重排，测试会假红。

### 3. 生产 beat 接线测用「初入殿」「召对夜启」作行为探针
- **位置** `tests/test_beat_orchestration_503.py:302-303`（另见 `:261-264` 对「戌时」「乾清宫」子串）
- **违反条文** 「对自由文本的…措辞机械依赖」；SHARED #13「盯文」
- **证据**
```python
assert "初入殿" in enter
assert open_body and "召对夜启" in open_body
```
- **说明** 用生产生成器固定措辞区分「接上编排缝」与「#498 兜底」。契约应是 typed 路由/非空/方差，不是文案标记。

### 4. 含糊追问 cue 锁中文序数呈现（「其一」「其十」「其10」）
- **位置** `tests/test_multi_directive_502.py:521-522`
- **违反条文** 「对自由文本的…措辞机械依赖」；SHARED #13「盯文」
- **证据**
```python
assert "其一" in cue and "其十" in cue
assert "其10" in cue
```
- **说明** #502 `_ensure_clarification_cue` 是呈现 post-pass。测试锁序数文案形态；IndexError 回归应用结构化候选长度等契约断言，不锁「其N」字面。

### 5. Web 恢复面锁按钮/提示中文文案
- **位置** `web/src/components/modals.test.tsx:398-401`、`:417-419`（W2 #497 R2 引入）
- **违反条文** 「对自由文本的…措辞机械依赖」；SHARED #13「盯文」
- **证据**
```typescript
expect(note?.textContent).toContain("重新生成回话");
(node) => node.textContent === "重新生成回话",
(node) => node.textContent === "重试补写",
```
- **说明** 已有 `data-testid="reply-retry"` / `"extraction-pending"`。仍用中文按钮字匹配点击目标——呈现改写即假红。

### 6. 连场/可闻性测用账正文散文作唯一可观察物
- **位置** `tests/test_audience_continuous_507.py:67-69`、`:109-114`、`:197-198` 等
- **违反条文** 「对自由文本的…机械依赖」；PRD「锁的是账的骨架：谁、序、可闻性、标签」
- **证据**
```python
assert "徐光启奏：宜用洪承畴督师陕西。" in recap
assert "此人跋扈" not in recap
```
- **说明** 过滤逻辑本身走 `audibility`/在场（合宪）；测试却用 fixture 正文子串当断言轴，未锁骨架字段。属盯文。

### 7. court_tension 路由测锁定性呈现词「满意」「势力」
- **位置** `tests/test_beat_orchestration_503.py:496-497`
- **违反条文** 「对自由文本的…措辞机械依赖」；SHARED #13「盯文」
- **证据**
```python
assert "满意" in inputs.court_tension or "势力" in inputs.court_tension
```
- **说明** 定性档文案是呈现层；改用词表即假红。非 typed 张力枚举/键。

---

## P2 — 系统口令走自由文本措辞集合

### 8. CLI 恢复命令靠玩家自由输入措辞集合匹配
- **位置** `ming_sim/cli/terminal.py:477-481`
- **违反条文** 「对自由文本的…措辞机械依赖」
- **证据**
```python
if low_q in {"重试回话", "retry reply", "retry_reply"}:
    ...
if low_q in {"重试补写", "retry extraction", "retry_extraction"}:
```
- **说明** W2 #505/#501：Web 同能力走按钮回调（typed）；CLI 把系统恢复口令嵌进「朕问」自由文本，靠措辞集合分流。呈现/用词一变即失灵。轻于 P0（非 LLM 散文解析），仍属咬措辞而非独立契约通道。

---

## 扫描备注（非条目）

- **未列入**：`presence_effect` / 口令常量标驱动在场（合宪）；`extract_directive_confirmation` 走 JSON schema（合宪）；合入文件中 W2 未改动的历史关键词快路径（如 `_ensure_confirmation_cue`、密令 `标签：`/`期限：` 行解析）——非本家族交付面增量。
- **命令/输出**：`gh issue view 497`、`gh api ... subIssues`、`gh pr view 1087 --json files`、`git show origin/main:...` 核对行号。
