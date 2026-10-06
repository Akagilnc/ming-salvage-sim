# #1853 fixer enum commands（完整可复核）

谓词覆盖末判词两类定义全文；**不**收窄到符号名 `db`、生产目录、或 `fail_chat_turn`/`append` 等少数方法。
本目录脚本为真源；下方命令可在工作树根直接复跑。

## Class1 — J8-R2：成功构造 GameDB 后必备能力缺失兼容

边界：已交入成功构造 GameDB 后的能力缺失兼容（`hasattr` / `getattr(..., default)` / `callable(getattr(...))` / `except AttributeError` 把必备 `conn`/API 洗成跳过或空结果）。
保留：`game_db is None` / `getattr(game,"db",None)`、缺业务行/空名单、`error_pack` 诊断、`flows` 划痕清理。

```bash
python3 artifacts/1853-fixer-enum/enum_class1_gamedb_capability.py
```

脚本行为：
- 全仓 `*.py` AST 枚举（跳过 `.venv`/`node_modules`/`archive` 等）
- 收集全部 `getattr` / `hasattr` / `callable` / `AttributeError` 兼容分支
- GameDB API 名表写入 `gamedb_api_names.txt`
- 原始命中 → `class1-raw.tsv`；分类关注面 → `class1-post.tsv`
- `IN_CLASS_J8R2` 含：GameDB 接收者（别名不限 `db`）上的软探测，以及 try 体触及 `db.conn`/GameDB API 且 `except AttributeError` 的兼容分支

辅助对照（非分类真源，仅肉眼扫）：

```bash
rg -n --glob '*.py' --glob '!.venv/**' --glob '!**/node_modules/**' --glob '!archive/**' \
  -e 'hasattr\(' -e 'getattr\(' -e 'callable\(' -e 'except \(AttributeError' -e 'except AttributeError' \
  .
```

## Class2 — TEST-PARALLEL：测试复制持久化/回滚 + 退役轻量专属测试

边界：替身复制被测持久化/回滚业务，或续养已退役 lightweight/connless 专用测试。
保留：负向受理、单写、排队、并发契约；只做故障注入/门闩观测且不复制回滚规则的协作替身。

```bash
python3 artifacts/1853-fixer-enum/enum_class2_test_parallel.py
```

脚本行为：
- 全仓 `tests/**/*.py` AST 枚举
- 持久化/回滚方法集：`fail_chat_turn` / `append_chat_message` / `persist_minister_reply` / `capture_chat_rollback_snapshot` / `create_chat_turn` / `undo_chat_turn` / `rollback_chat_turn` / `restore_chat_rollback_snapshot` / `delete_chat_message` / `update_chat_message`（不限前几项样本）
- 退役标记：`lightweight` / `without_durable_identity` / `connless` / `_noop_atomic` / `_atomic_connless`
- 原始+分类 → `class2-raw.tsv` / `class2-post.tsv`
- `COPY_ROLLBACK_LOGIC` / `RETIRED_LIGHTWEIGHT_TEST` 为须清退；其余 KEEP_* 须在回执说明不复制回滚

辅助对照：

```bash
rg -n --glob '*.py' \
  -e 'def fail_chat_turn' -e 'def append_chat_message' -e 'def persist_minister_reply' \
  -e 'def capture_chat_rollback_snapshot' -e 'def create_chat_turn' -e 'def undo_chat_turn' \
  -e '_noop_atomic' -e '_atomic_connless' -e 'lightweight' -e 'without_durable_identity' \
  -e 'msgs\[:-1\]' -e 'messages = msgs' \
  tests/
```

## 复扫期望

- Class1：`IN_CLASS_J8R2=0`；保留 `KEEP_error_pack_diag` + `KEEP_runtime_scratch` + 未交库 `KEEP_unhanded_db_or_optional_holder`
- Class2：`COPY_ROLLBACK_LOGIC=0`、`RETIRED_LIGHTWEIGHT_TEST=0`；协作替身均为 `KEEP_*` 且方法体无 `msgs[:-1]` / 消息回滚复制
