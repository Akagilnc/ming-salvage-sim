## 违宪扫描（ADR 0142 · 6 分钟）

**法源锚点**：「引擎不得用关键词、正则或规则从 LLM 的**自由散文**抠取语义或结构化事实」；结构化事实只走「tool call / `pending_action` / extractor schema」——机器只咬契约，不咬呈现。辅引 ADR 0028 修订：「对自由散文的自然语言关键词／正则启发层废除」。

---

### 1. 大臣回话正则抠承办人 / 领命语
- **位置**：`ming_sim/cli_backend.py:1503`–`1713`（`_ACKNOWLEDGMENT_CLAUSE_RE`、`_ASSIGNEE_HINT_RE`、`_extract_assignee_hint`、`_choose_assignee`）
- **违反**：「不得用…正则…从 LLM 的自由散文抠取…结构化事实」；0142 弃案亦点名「潜台词关键词 parser=地雷」
- **证据**：
```1581:1586:ming_sim/cli_backend.py
_ASSIGNEE_HINT_RE = re.compile(
    r"(?:可\s*委\s*派|...|可\s*命)"
    r"\s*([\u4e00-\u9fa5·]{2,4})"
    ...
)
```
- **说明**：从大臣 LLM 回话用建议式/祈使式 regex 抽人名与动作词，再覆盖 typed `承办人` 字段。

### 2. 密令正文守门：分句/子串比对大臣散文
- **位置**：`ming_sim/cli_backend.py:1520`–`1570`（`_minister_material_clauses`、`_content_reflects_minister_supplements`）
- **违反**：「从 LLM 的自由散文抠取语义」；应用结构化契约而非散文核验
- **证据**：
```1525:1530:ming_sim/cli_backend.py
clauses = [seg.strip() for seg in _CLAUSE_SPLIT.split(reply or "") if seg.strip()]
...
if clause in _ACKNOWLEDGMENT_CLAUSE_EXACT or _ACKNOWLEDGMENT_CLAUSE_RE.match(clause):
    continue
```
- **说明**：机械剥「领命」句、再按子串判断 extractor JSON 是否「覆盖」回话，驱动兜底合并逻辑。

### 3. 剥 LLM 英文旁白驱动呈现
- **位置**：`ming_sim/cli_backend.py:835`–`857`（`_NARRATION_HEAD` / `_strip_agent_narration`），调用于 `:2188`
- **违反**：「此类 LLM 叙事的输出对引擎同样零解析零管辖」
- **证据**：
```835:852:ming_sim/cli_backend.py
_NARRATION_HEAD = re.compile(
    r"^\s*(I will\b|I'll\b|Let me\b|...)",
    re.IGNORECASE,
)
...
if _NARRATION_HEAD.match(ln):
```
- **说明**：对模型回话做行首英文计划 regex 剥离，引擎在管 LLM 文字细节。

### 4. 密令排除对象：从正文 regex 反推 typed 字段
- **位置**：`ming_sim/db.py:124`–`178`（`_SECRET_EXCLUSION_CLAUSE_RE` / `_recover_secret_order_exclusions`）
- **违反**：「该走 typed 字段却抠散文」；「需要结构化后果时从…结构化输入侧取，不从文字输出侧反推」
- **证据**：
```124:126:ming_sim/db.py
_SECRET_EXCLUSION_CLAUSE_RE = re.compile(
    r"(?:不走|不经|...|瞒住|...)\s*"
    r"([^，。；;\s]{2,40}?)(?=(?:知晓|...|$))"
)
```
- **说明**：结构化 `排除对象` 可缺时，从密令自由文本「瞒住/勿令…」clause 机械恢复名单。

### 5. 邸报散文嵌决策块 regex 解析
- **位置**：`ming_sim/settlement_payload.py:42`–`54`（`_DECISION_RE` / `parse_decision_blocks`）
- **违反**：「结构化事实…只走显式结构化契约通道」——非 tool/`pending_action`/extractor delta
- **证据**：
```42:54:ming_sim/settlement_payload.py
_DECISION_RE = re.compile(r"<<DECISION>>\s*(\{.*?\})\s*<<END>>", re.DOTALL)
...
for m in _DECISION_RE.finditer(narrative or ""):
```
- **说明**：从 simulator 邸报叙事抠 HITL 决策结构，散文载体扛契约。

### 6. CLI 回话尾嵌 `[[recommend_person:…]]` 伪 tool
- **位置**：`ming_sim/cli_backend.py:2050`–`2093`（`_CLI_RECOMMENDATION_CALL` / `_cli_recommendation_call`）
- **违反**：应用 tool call 契约，却用「散文末尾标记 + JSON」机械解析驱动 tool seam
- **证据**：
```2050:2051:ming_sim/cli_backend.py
_CLI_RECOMMENDATION_CALL = re.compile(
    r"\n?\[\[recommend_person:(\{.*?\})\]\]\s*$", re.DOTALL,
)
```
- **说明**：无 function-calling 时从模型自由文本尾标抠结构化荐人参数。

### 7. 回话关键词判断是否已「请定夺」
- **位置**：`ming_sim/session.py:1536`–`1545`（`_ensure_confirmation_cue`）
- **违反**：「不得用关键词…从 LLM 的自由散文抠取语义」
- **证据**：
```1541:1545:ming_sim/session.py
if any(term in text for term in (
    "定夺", "准驳", "准否", "准不准", "请旨", "是否准",
)):
    return text
```
- **说明**：用 contains 猜大臣回话是否已问准驳，决定是否追加确定性 cue。

### 8.（辅）确认目标族：皇帝自由文关键词分拣
- **位置**：`ming_sim/session.py:522`–`535`（`_confirmation_targets_for_message`）
- **违反**：ADR 0028「对自由散文的自然语言关键词／正则启发层废除」（确认判读只许结构化 LLM 判词）；与 0142 同族接缝
- **证据**：
```527:533:ming_sim/session.py
if any(token in text for token in ("密令", "密旨", "密谕")):
    family_targets.extend(secret)
if any(token in text for token in ("任免", "任命", ...)):
    family_targets.extend(office)
```
- **说明**：用「密令/任免/调教/圣旨」等词命中决定确认哪类 `pending_action`，非显式前缀/typed 判词。

---

**未计入（非 0142 咬面或属契约卫生）**：玩家显式前缀 `_DRAFT_PREFIXES`/`_SECRET_PREFIXES`（0028 结构性信号）；`strip_json_fence`/`_loads_lenient` 去 markdown fence（契约通道格式修复，非语义抠取）；`intelligence.py` 对皇帝问句的域关键词（输入非 LLM 输出）；seed/`office` 标题子串、文件名 regex。
