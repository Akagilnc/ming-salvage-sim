# #1891/#1899 CLEANUP-C1 已删符号测试闭包回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。  
范围：**仅** CLEANUP-C1（测试对已删生产符号打补丁／断言）；**CHOICE 不送修**（不变 CHOICE）。

## 撤回（范围结论；旧 choice-cleanup 仅追加本条，不变 CHOICE）

**撤回「3233 OK＝全类闭合」**。主助手核 `/tmp/cleanup-c1-audit/runtime_verified.json`：只存摘要，无全成员运行解析；`verdict_counts` 仍有 **192 `skip_unresolved_target`／17 `skip_non_prod`／4 `skip_dynamic_attr`**；`AUDIT_COMMANDS.sh` 仅红 pytest、无枚举。未 resolve 不得空口 0；不得把 OK 摘要充全类闭合。

## 环境

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
TMPROOT=$(mktemp -d /tmp/cleanup-c1-closure.XXXXXX)   # 本轮实测：/tmp/cleanup-c1-closure.ptPlBb
mkdir -p "$TMPROOT/logs" "$TMPROOT/user" "$TMPROOT/pytest"
export MING_SIM_USER_DATA_DIR="$TMPROOT/user"
```

审计＝一次性标准库 `ast` + `importlib`（`docs/reports/1891-1899-deleted-symbol-ENUMERATE_AND_RESOLVE.py`）；**不**新造仓内永久扫描框架／测试。候选表由 AST 枚举生成，**不以判词名单为种子**。

## 精确枚举命令

```bash
# 全员枚举 + 初解析（写出 all_sites_members.{json,tsv} + runtime.json）
$PY docs/reports/1891-1899-deleted-symbol-ENUMERATE_AND_RESOLVE.py "$TMPROOT/logs"
# 深解析（type(db)/game 解包/local ctor/实例链）+ 取证复分类：见本轮 logs/deep_resolve.log
# 命令副本：docs/reports/1891-1899-deleted-symbol-AUDIT_COMMANDS.sh
```

**范围（响亮排错）**：

- 解析：`tests/**/*.py`（230 文件，含 helpers／conftest）；`docs/raw` 不在 tests 下＝不入本扫。
- 种类：`monkeypatch.setattr`（对象／字符串）／`patch` 字符串／`patch.object`／生产 import 别名上的 `direct_attr_ref`。
- **排除假阳性（响亮）**：无 `ming_sim|web_app|…` 字面量的 HTTP `client.patch` 等不收录；`raising=False`／`create=True` 缺符单独判决、不自动 OK；非 const 属性名→`skip_dynamic_attr`；非生产模块→`skip_non_prod`；OK＝运行时 `hasattr`／MRO／dataclass 字段／实例协议，**不是**「ClassDef 类体静态有 def」单判。

## 全员计数（闭包后；附表真源）

| 项 | 数 |
| --- | ---: |
| sites_total | **3447** |
| OK | **3434** |
| MISSING（真残留，取证 AttributeError） | **1** → 已删案 |
| skip_unresolved_target（闭包后） | **0**（逐项 scope／fixture／ctor 核完） |
| skip_non_prod | **9**（明确 stdlib／经模块挂到 stdlib） |
| skip_dynamic_attr | **6**（含原 4 + 2 协议 setattr） |

对照旧摘要（不得再当闭合）：OK 3233／unresolved 192／nonprod 17／dynamic 4／MISSING 1。  
原 192＝缺 import 别名即 skip、无成员表；本轮深解析后归入 OK（`type(db)`→`GameDB`、game 解包、`CliChat` 局部构造、实例链等）。原 17 nonprod 中 8 条为 `db.affairs`／`game.session` 等实例链→OK；余 9＝真非生产。原 4 dynamic＝`cli_backend` 上 `_run_*`／`attr` 循环；另 2＝`setattr(character, field)`／`MethodType` 测试双协议。

**类判据／实例协议（具体成员，非空口）**：

- `type(db)`／`db`／`fresh_db` → `ming_sim.db.GameDB`（conftest `game`／`GameDB(...)`）。
- `content` → `ming_sim.content.GameContent`（含 dataclass 字段如 `event_by_id`）。
- `state` → `ming_sim.models.GameState`（`GameDB.load_state` 返回注解）。
- `cc = CliChat(...)` → `ming_sim.cli_backend.CliChat`（局部构造赋值，非按名猜）。
- `game.session`／`web_game.session` → `ming_sim.session.GameSession`；`runtime.db`／`game.db` → `GameDB`。
- `queue.barrier`：静态曾误绑 `get_session_write_queue` 函数→假 MISSING；**真实 pytest PASSED** → OK。

### 附表

| 文件 | 内容 |
| --- | --- |
| `docs/reports/1891-1899-deleted-symbol-sites.tsv` | **3447** 全成员 TSV |
| `docs/reports/1891-1899-deleted-symbol-sites.json` | 全成员 JSON（含推断／来源字段） |
| `docs/reports/1891-1899-deleted-symbol-runtime.json` | 闭包摘要（含 forensics） |
| `docs/reports/1891-1899-deleted-symbol-missing.json` | 删前 MISSING=1 |
| `docs/reports/1891-1899-deleted-symbol-nonprod.json` + `*-nonprod-cards.json` | 9 非生产逐项 |
| `docs/reports/1891-1899-deleted-symbol-dynamic.json` + `*-dynamic-cards.json` | dynamic 协议＋现役 `_run_*` 核验 |
| `docs/reports/1891-1899-deleted-symbol-ENUMERATE_AND_RESOLVE.py` | 可复跑枚举本体 |
| `docs/reports/1891-1899-deleted-symbol-AUDIT_COMMANDS.sh` | 命令壳 |

正文不逐句抄 3k OK 行；核对走 TSV／JSON。

## 真残留与处置

| nodeid | 取证 | 处置 |
| --- | --- | --- |
| `tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement` | `AttributeError: module 'ming_sim.decree' has no attribute '_next_attempt'`；**1 failed in 0.67s**（史：`/tmp/cleanup-c1-narrow-red.log`；本轮 forensic 0.69s） | **删除该 test 整段**（内含专属 `_boom`）；不恢复 `decree._next_attempt`；不改挂 |

**KEEP**：

- `ming_sim.error_pack._next_attempt`（现役；`write_error_pack` 调用）。
- `tests/test_error_pack.py::test_next_attempt_skips_malformed_and_foreign_entries`（及 attempt 目录派生邻案）。
- 其余 3434 OK／9 nonprod／6 dynamic＝非本类删案对象。

根因史：`670e69f97` 结算灌注 attempt＋本案 → `#1843` 去调用点 → `b1900c284` 去 decree 绑定 → setattr 红。案证的是已退役「结算中派生失败回落」，不是改 patch 到 `error_pack`。

## 聚焦测试（七 BIN + 新 user／basetemp + no cache）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
export MING_SIM_USER_DATA_DIR="$TMPROOT/user"
$PY -m pytest -q --tb=short -p no:cacheprovider --basetemp="$TMPROOT/pytest/focus" \
  tests/test_rejection_wiring.py \
  tests/test_error_pack.py::test_next_attempt_skips_malformed_and_foreign_entries \
  tests/test_error_pack.py::test_attempt_derived_from_existing_dirs \
  tests/test_mechanical_tail_1845.py::test_web_barrier_resumes_pending_tail_before_join
```

史：邻批 **1 failed, 20 passed**（唯一红＝上案；`/tmp/cleanup-c1-audit/neighbor-green.log`）。  
删后本轮：`/tmp/cleanup-c1-closure.ptPlBb/logs/focus-post-delete.log` → **19 passed in 1.09s**（`test_rejection_wiring` 整文件 −1 案 + error_pack 两案 + barrier 邻案）。

## 自查二连

1. **同类**：全 3447 落表；原 192／17／4 不空口清零——逐项深解析＋卡片；真 MISSING 仅 `_next_attempt` 且有 AttributeError；`error_pack` 保留；无判词名单种子；无永久扫描测试框架。
2. **引入 bug**：只删退役专属案；不恢复符号／不兼容 shim／不改挂 error_pack；不改 CHOICE；barrier 假阳性以 PASSED 取证回 OK，未误删。
