# J6 完整候选处置表（权威）

谓词：monkeypatch.setattr、call_oracle、marker、fixed_translate、direction、prose/OperationalError、helper 命名；含 web mock 行。
不以点名文件限界。**边界替身不得默认合法**；须逐项外部契约/真实入口/实际结果。

权威数据：[`j6-full-disposition.json`](j6-full-disposition.json)  
Web 行（含第三方排除说明）：[`j6-web-members.json`](j6-web-members.json)  
原始 AST 枚举证据：[`j6-ast-candidates.json`](j6-ast-candidates.json)

已删本局重复拷贝：`j6-focus.json`、`j6-members.json`、`j18-members.json`（与权威表重复/窄枚举）。

## 本轮已逐项语义审（原 NEEDS_* 52）

处置见 JSON `audited=true`；其中代码侧 **FIX_APPLIED / FIX_APPLIED_RENAME = 9**：

| 处置 | 说明 |
|---|---|
| FIX_APPLIED | CLI「直到补齐」措辞锁；注入 OperationalError `match=` 文案；注入 reason 子串；ack narrative 子串→全文 |
| FIX_APPLIED_RENAME | `internal==substrate_hub` 标记锁 → 公开预算名碰撞 + ledger 精确额 |

其余 43 项已落 KEEP_*（seed 金样 / 闸类型 / 月链边界 / 原文无损 / 事务回滚等），**不再留 NEEDS_READ***。

## 处置计数（Python 焦点 618）

```
PENDING_STUB_DEFAULT: 308   ← 未结：默认边界戳记，非语义裁决
PENDING_OTHER_DEFAULT: 188  ← 未结：默认「未命中谓词」戳记
KEEP_MONTH_TRANSLATE_BOUNDARY: 28
KEEP_ORDERING_OR_QUAL: 15
KEEP_NAME_COLLISION: 10
KEEP_QUALITATIVE_DIRECTION: 10
FIX_APPLIED(+RENAME): 9
KEEP_BOUNDARY: 6
KEEP_SEED_GOLDEN: 5
KEEP_TX_BOUNDARY: 5
（其余 KEEP_* 各 ≤2；NEEDS_*=0）
```

## Web mock 行

- 自有 `web/src/**`：129 → `PENDING_WEB_UI_DEFAULT`（未逐项语义审；**未结**）
- `web/node_modules/**`：16 → `EXCLUDE_THIRD_PARTY`（**仅排除说明，不算自有测试处置**）

## 诚实未结

不得将 PENDING_* 归零宣称结清。本轮结清的是「NEEDS_READ* 未审桶」与已发现的违法文字锁/`internal` 标记类；**J6 整类仍未结**。
