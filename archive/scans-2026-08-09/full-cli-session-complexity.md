## 违宪清单（复杂度 · 限时扫描）

法源：SHARED **#12 复杂度即成本** / **#14 DRY**；本任务阈值「单函数>100行 / 嵌套>4 / god class / ≥3次未抽 / regex 可合并堆叠 / 死代码」。  
已知已报、**本轮不重复定罪**：`GameSession` god class、`GameSession.chat` 深嵌套、cli_backend 散文 regex（ADR 0142）。

---

### 1. [P0] CLI 会话落地巨函数 + 深嵌套

- **位置**：`ming_sim/session.py:1247` `GameSession.apply_cli_conversation_actions`
- **违反**：「单函数超百行」；「嵌套超4层」；#12「复杂度即成本」
- **证据**（量度）：**287 行**（L1247–1533）；AST nest≈**7**  
  `If@1357 → If@1358 → If@1381 → If@1387 → For@1388 → Try@1391 → ExceptHandler@1393`
- **说明**：确认/拟旨/密令/任免全挤进一函数状态机，远超 `chat` 已知案的另一条落地巨石。

---

### 2. [P0] 废路径未删（该死未死 ×3）

- **位置**：  
  - `ming_sim/session.py:1825` `_apply_secret_order`  
  - `ming_sim/session.py:1926` `_apply_close_secret_order`  
  - `ming_sim/cli_backend.py:554` `_run_codex_stream`
- **违反**：#12「被改动作废的旧物，随同改动删除」
- **证据**：全仓 `*.py` 仅见 **def**，无调用；流式路径已直调 `_iter_codex_stream_chunks`（`CliChat.invoke_stream`），密令已走 stage/pending
- **说明**：旧哨兵落库与未接线的 stream wrapper 仍占维护面。

---

### 3. [P1] 拟旨抽取超百行

- **位置**：`ming_sim/cli_backend.py:993` `extract_draft_intent`
- **违反**：「单函数超百行」
- **证据**：**153 行**（L993–1145）；nest≈2（长度违例，非嵌套）
- **说明**：前缀/补充/JSON 解析/字段规范化同堆一函数。

---

### 4. [P1] 颁诏结算超百行

- **位置**：`ming_sim/session.py:2047` `GameSession.resolve_turn`
- **违反**：「单函数超百行」
- **证据**：**148 行**（L2047–2194）；nest≈3
- **说明**：HITL 重发、settling 恢复、正常颁诏三叉未切开。

---

### 5. [P1] 任命落地超百行

- **位置**：`ming_sim/session.py:353` `apply_appointment`
- **违反**：「单函数超百行」
- **证据**：**136 行**（L353–488）；nest≈2
- **说明**：查重/升格/后宫/腾缺同函数串联。

---

### 6. [P1] 空白压缩同形未抽（≥3）

- **位置**：`ming_sim/cli_backend.py`（代表行 L1488 / L1545 / L1766 / L1790 / L1844 等）
- **违反**：#14 DRY「同一形状不许两份」
- **证据**：`re.sub(r"\s+", "", …)` **9 处**（L1488,1489,1545,1563,1567,1766,1777,1790,1844）
- **说明**：同一「去空白再比」原子散落守门族，改一处易漏。

---

### 7. [P2] 承办人 strip 三克隆 + lookahead 双份可合并

- **位置**：`ming_sim/cli_backend.py:1623` / `:1634` / `:1671`；lookahead `@1586` 与 `@1662`
- **违反**：#14；「regex 家族堆叠的可合并形态」（复杂度/DRY 角，**非**再定散文抠语义罪）
- **证据**：
```python
while len(name) > 2 and name[-1] in _ASSIGNEE_VERB_TAIL_CHARS:  # ×3
# 同形 lookahead 动词类 ×2：
(?=[，,。.…]|暗|密|调|督|拟|领|查|办|为|任|…|监|协|处|负|$)
```
- **说明**：hint / tail / imperative 共用剥尾与动词 lookahead，可收成一原子。

---

### 8. [P2] 另两处刚过百行（量度备案）

- **位置**：`ming_sim/cli_backend.py:447` `_iter_codex_stream_chunks`（**105** 行，nest≈4）；`:1874` `_extract_secret_order`（**104** 行，nest≈1）
- **违反**：「单函数超百行」
- **证据**：AST 行跨如上；前者 nest 贴上限、后者纯长度
- **说明**：刚越线；优先级低于上列巨函数。

---

### 本轮明确未新定罪 / 未坐实

- **God class**：`GameSession`（53 methods / ~1639 行）已有报告，不重复定罪；`CliChat` 仅 7 methods，不够格。
- **嵌套>4**：除已报 `chat` 外，新硬证只有 `apply_cli_conversation_actions`（上列 #1）。
- **大块注释死代码**：两文件未见。
- **≥3 次整函数体克隆**：未坐实。后台校验已结束：死代码与重复计数和清单一致——`_run_codex_stream` / `_apply_close_secret_order` 全仓无调用；assignee `while` 剥尾 ×3；`re.sub(r"\s+", "", …)` ×9。清单无需改动。
