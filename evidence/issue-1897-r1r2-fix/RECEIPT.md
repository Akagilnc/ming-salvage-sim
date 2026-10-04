# #1897 R1 续清回执（R2 已结清，本轮不改）

- 分支：`ak-roles/issue-1897-r1-r2-fix`
- 用户本轮：现场读 diff——`apply_army_deltas.reason` 已进转运列并删 `[:80]`，仍保留 `.strip()`（db.py 写 `army_logs` 仍改字）；`issues.py` fiscal_creates `note=…[:120]` 虽曾列例外，但是声明→共同 `create_fiscal_item` 写口自由 reason，共同写口已原样入库故上游裁剪须删。只删简化；不扩玩法；不改 R2。
- 未 push / 未开 PR / 未 amend / 未 stash

## 上下游核证

- `GameDB.apply_army_deltas`：`reason = … .strip()` → 传入 `_apply_army_pay_source_delta` / 各字段分支 → `INSERT INTO army_logs (…, reason, …)` —— 同一自由 reason 入库前改字。
- `issues._apply_score_extraction_body` fiscal_creates：`note=str(create.get('reason') or '')[:120]` → `GameDB.create_fiscal_item(..., note=)` → `fiscal_config.note` 与 `fiscal_config_creations.reason`（写口本轮已无 `[:240]`）—— 上游裁剪使原样入库无效。

## 本轮生产删改字

- `ming_sim/db.py:GameDB.apply_army_deltas` — 删 `reason` 的 `.strip()`
- `ming_sim/issues.py:_apply_score_extraction_body` — 删 fiscal_creates `note=…[:120]`

成员表：`members-exceptions.txt` §C 撤财政_creates 误例外；§D 补上两项 MUST_FIX。

## 聚焦测试

见 `focused-pytest-continuation.txt`（仅两文件；七 BIN=/usr/bin/false）。

前次 11 文件证据保留于 `focused-pytest.txt`（445 passed, 1 failed）；**本轮不重跑 11 文件，不伪称新的 445 结果**。

## 自查二连

- 同类型：army 共享写口 strip + fiscal_creates 上游 [:N] 已对齐共同写口原样；R2 未动
- 引入 bug：只删 `.strip()` / `[:120]`，无新机制/护栏/证明性测试；未补 #1873
