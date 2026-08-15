## 违宪扫描 · `web_app.py`（限时量度，宁缺毋滥）

法源：`~/.claude/CLAUDE.md` SHARED **#12**（复杂度即成本 / 同形逻辑不许两份）、**#14**（DRY 硬规则）；扫描口径=单函数>100行 / 嵌套>4 / god 模块 / ≥3次未抽重复 / 死路由死码。

---

### 1. God 模块：单文件吞下整站 Web API
- **位置**：`web_app.py:1`（全文件）+ `web_app.py:602`（`WebGame`）
- **违反**：#12「复杂度即成本…删码/简化的方案压过加码」
- **证据**：
  - 总行数 **4328**
  - `@app.(get|post|…)` 端点 **61**
  - 顶层函数 **107**；`WebGame` **L602–2354 = 1753 行 / 67 methods**
- **说明**：菜单/召对/颁诏/存档/LLM/admin 全堆同一模块，已是典型 god file。

### 2. 单函数超百行 + 嵌套超 4：`_chat_stream_payload_commit`
- **位置**：`web_app.py:1810`
- **违反**：扫描口径「单函数超百行/嵌套超4层」；#12 复杂度
- **证据**：
  - 长度 **219** 行（L1810–2028）
  - 智能嵌套（elif 链不重复计深）**max=7**（AST 裸计可达 12）
  - 深处示例：`L1926–1940` 连续 `if`/`try`/`if`/`try`/`if`
- **说明**：流式召对 tool 落库整段未拆，长度与深度同时越线。

### 3. 单函数超百行 + 嵌套超 4：`chat_stream`
- **位置**：`web_app.py:2208`
- **违反**：同上
- **证据**：
  - 长度 **136** 行（L2208–2343）
  - 智能嵌套 **max=5**（`L2287` `with` 处达第 5 层）
- **说明**：流式编排本体仍超百行，且内部再嵌 worker/闸。

### 4. ≥3 次同形未抽：结算 steam 事件块
- **位置**：`web_app.py:3658` / `3722` / `3800`
- **违反**：#14「同一定义…只允许一个权威真源」；#12「同一形状的逻辑不许存在两份」
- **证据**：
```text
events = [
  steam_events.add_stat(...STAT_DECREES_ISSUED),
  steam_events.add_stat(...STAT_TURNS_PLAYED),
  steam_events.set_stat(...STAT_MAX_TURN_REACHED, int(game.state.turn)),
]
```
  - 出现于 issue / issue-stream / resolve-stream **3** 处（6-line shingle count=3）
- **说明**：同形结算后处理复制三份，未抽 helper。

### 5. ≥3 次同形未抽：stream worker 错误包样板
- **位置**：`web_app.py:3736` / `3743` / `3814` / `3821`
- **违反**：#14 DRY
- **证据**：
  - `"game" in locals() and "turn_before" in locals() and "failed_before" in locals()` **4** 次
  - 均包一层 `_new_secret_order_failure_payloads_for_turn(...)` 再 `__error__`
- **说明**：两条 SSE worker 的 ValueError/Exception 分支近乎拷贝。

### 6. ≥3 次同形未抽：tool args 兜底序列化
- **位置**：`web_app.py:1860` / `1878` / `1886` / `1895` / `1964`
- **违反**：#14 DRY
- **证据**：
  - `getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}` **5** 次
  - 多处紧接 `json.dumps(args, ensure_ascii=False)`
- **说明**：tool payload 读取样板在巨函数内重复未抽。

### 7. 嵌套超 4：`_drain_and_close_session`
- **位置**：`web_app.py:2547`
- **违反**：扫描口径「嵌套超4层」
- **证据**：
  - 长度 59（未超百行），智能嵌套 **max=6**
  - `L2592/2595/2602` 连续 `try` 处理 wal/shm
- **说明**：关库/归档旁路异常链叠得过深。

### 8. 死代码：`apply_llm_config` 无调用方
- **位置**：`web_app.py:940`
- **违反**：#12「被改动作废的旧物，随同改动删除」
- **证据**：
  - 唯一定义于 L940；仓内除 `CHANGELOG.md` 叙述外 **零引用**
  - 现活路径为 `build_llm_config` / `commit_llm_config` + `api_set_llm_config`
- **说明**：同步组合壳已废弃，仍留方法体。

---

### 未成立（明示）
- **死路由**：61 个 `@app.*` 均有装饰器注册；`api_menu_delete_save` 与 `api_delete_save` 是菜单/局内两条活路径，**非死路由**。
- **favorites 加载块**：`__init__`/`_rebuild_session` 仅 **2** 份同形，未达「≥3」门槛，不报。

**合计：8 条（按严重度 1→8）。**
