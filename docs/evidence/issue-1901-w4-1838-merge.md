# #1901 第二次底座合并证据（claude/1812-w4 · #1838 orphan narration）

## 现场

| 项 | 实测 |
|---|---|
| 本支 | `ak-roles/1901-source-only-pay-w5` |
| merge 前 HEAD | `523b28dc3a085e92e5f70e21719cc8c529f907d4`（第一次底座合并） |
| 底座 tip | `b9890610870102bcba427eb19b003ae6ad291baf`（`claude/1812-w4`） |
| merge-base | `dd9184891820f25376bbea3a68b255225329427f` |
| 底座自 merge-base 两 commit | `f7df3c85d`（#1838 retire）→ `b98906108`（merge into W4） |

## 顾问最简策略（施工前）

1. 只预期两处 **modify/delete**：`tests/test_advance_without_edict_report_1345.py`、`tests/test_advance_without_edict_token_1351.py`（本支删、底座改）。其余交叉文件交 auto-merge。
2. 冲突一律 **保留本支删除**（`git rm`），不复活旧测试模块。
3. 不发明行为；#1812「无历史包袱全面重构」优先现役职责与复杂度。
4. 已删测试不复活作证明；只跑 merge 触及的现役测试文件。

## 两侧 commit / 票面证据

### 本支删除（#1901）

- commit：`c8215188fd2984b6004a1089d19a86b953e2393b`
- message：`ak-roles: fix #1901 J3 shape-dependent tests and J11 behavior proofs`
- 动作：两文件整模块删除（`-92` / `-85` 行）。
- 证据真源：`docs/evidence/issue-1901-j3-j11-w5.md`
  - `test_advance_without_edict_report_1345.py::test_advance_without_edict_shell_absent`：「删除只有名称钉的案；再扫发现模块只剩无人使用的夹具，整模块删除」
  - `test_advance_without_edict_token_1351.py` 与上同表：「删除无 test、无人导入的失效夹具；不另造同形测试」
- 票面 #1901：领域旧大块拆搬；owner「没有历史包袱的重构」；验收跟 #1812「被取代的旧代码…及只为旧代码存在的测试已删」。

### 底座修改（#1838）

- commit：`f7df3c85d1321cfb983b688eecf47f68cdc8e741`
- message：`ak-roles: fix(#1838): retire orphan narration support and test scaffolds`
- 对上述两测试文件的改动：**各删 2 行**夹具赋值  
  `session._scene_registry = None` / `session._beat_generator = None`  
  （与同 commit 对其余测试夹具去 orphan narration 接线同形）。
- 同 commit 生产侧：删 `ming_sim/audience_night.py` 的 `find_prior_speaker_still_present`；删 `ming_sim/cli/terminal.py` 的 `_fail_cli_chat_turn_scene` 等孤立旁白清理支持（整 commit `-118` 行，无新增行为）。
- 票面 #1838：旧独立旁白调用随被替代能力退役；「开夜、入殿、交接、退殿、收夜、场外传召不再各起独立旁白 LLM」。reopen 口径：该删没删干净的旧路继续清。

### 取舍

| 文件 | 冲突形态 | 处置 | 理由 |
|---|---|---|---|
| `tests/test_advance_without_edict_report_1345.py` | modify/delete（本支删 / 底座改） | **保留删除** | #1901 J3 已整模块退役（名称钉+无用夹具）。底座 #1838 仅从该夹具拆 orphan narration 属性；整删已蕴含该意图，复活会带回已废路径证明。 |
| `tests/test_advance_without_edict_token_1351.py` | 同上 | **保留删除** | 同上。 |

## 逐文件处置（本 merge 全部 staged 变更）

| 路径 | 来源 | 处置 |
|---|---|---|
| `ming_sim/audience_night.py` | 底座 #1838 | 接受：删 `find_prior_speaker_still_present` |
| `ming_sim/cli/terminal.py` | 底座 #1838 | 接受：删孤立 CLI chat-turn scene 失败清理支持 |
| `tests/month_chain_helpers.py` | 底座 #1838 | 接受：去 orphan narration 夹具接线 |
| `tests/test_advance_paths_atomic.py` | 两侧改 / auto-merge | 接受 auto-merge（去 orphan attrs，保留本支其余改动） |
| `tests/test_advance_without_edict_report_1345.py` | 冲突 | **删**（见上表） |
| `tests/test_advance_without_edict_token_1351.py` | 冲突 | **删**（见上表） |
| `tests/test_audience_background.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_audience_restore_505.py` | 底座 | 接受：去 orphan attrs |
| `tests/test_audience_translate_1837.py` | 底座 | 接受：去 orphan attrs |
| `tests/test_decree_forecast_1861.py` | 底座 | 接受：去 orphan attrs |
| `tests/test_fiscal_levy_effect.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_fiscal_substrate_bridge.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_issue_decree_token_1277.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_month_open_snapshot_1234.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_opening_gazette_delete_1356.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_pre_settle_transaction.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_public_sayings_1829.py` | 底座 | 接受：去 orphan attrs |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_scene_llm_1836.py` | 底座 | 接受：去 orphan attrs |
| `tests/test_secret_order_monthly_progress_566.py` | 两侧改 / auto-merge | 接受 auto-merge |
| `tests/test_web_audience_night_498.py` | 底座 | 接受：去 orphan attrs |
| `docs/evidence/issue-1901-w4-1838-merge.md` | 本 merge | 新增本回执 |

合并后核对：

- `session._scene_registry` / `session._beat_generator` 赋值在 `ming_sim/`+`tests/` 树中为零命中。
- `find_prior_speaker_still_present` 在 `audience_night.py` 中缺席。
- 两处已删测试文件不在工作树与 index。
- 无 `<<<<<<<` / `=======` / `>>>>>>>` 冲突标记。

## 聚焦测试（现役涉及文件；已删不复活）

命令（显式 bin 前缀；解释器为本机 `python3`，`python` 不存在）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_advance_paths_atomic.py \
  tests/test_audience_background.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translate_1837.py \
  tests/test_decree_forecast_1861.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_issue_decree_token_1277.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_pre_settle_transaction.py \
  tests/test_public_sayings_1829.py \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_scene_llm_1836.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_web_audience_night_498.py \
  -q --tb=line
```

结果（墙钟 `/usr/bin/time -p`）：

```
372 passed, 1 skipped in 31.87s
real 32.28
user 17.05
sys 12.07
EXIT:0
```

未跑：`tests/test_advance_without_edict_report_1345.py`、`tests/test_advance_without_edict_token_1351.py`（本支已删，不复活作证明）。

## 剩余工作

- 本合并本身无待决冲突、无待决产品决定。
- #1901 领域拆搬主线未因本底座合并宣告完成；后续仍按其票面与家族收尾节奏推进。
- 未 push、未开 PR（本回合禁止）。
