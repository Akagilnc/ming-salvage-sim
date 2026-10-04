# #1902 修内司 N1–N7 回执（自验补全）

- 分支：`ak-roles/1902-n1-n7-fixer-ccbdf378a`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`ccbdf378a`
- 本轮提交：`ef5bd0f315971e5bec77c8b10b1144b14813635a`
- 判词真源：末份 `03-1902-judge-ccbdf378a.json` payload（N1–N7）
- 枚举原始输出：`evidence/issue-1902/n1-n7-enum.out`（由下方内嵌脚本 tee；**不是**可执行脚本）
- 临时目录：`/tmp/ming1902-n1n7-selfverify/`（探针/变异；不入库永久扫描器）

七 BIN 前缀（下文一律完整写出，禁止省略）：

```bash
with_bins() {
  env \
    MING_SIM_AGY_BIN=/usr/bin/false \
    MING_SIM_CODEX_BIN=/usr/bin/false \
    MING_SIM_CLAUDE_BIN=/usr/bin/false \
    MING_SIM_CURSOR_BIN=/usr/bin/false \
    MING_SIM_KIMI_BIN=/usr/bin/false \
    MING_SIM_GROK_BIN=/usr/bin/false \
    MING_SIM_PI_BIN=/usr/bin/false \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}
```

方向检索：[pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) 作进程内临时变异；复用既有 `for_role` / `llm_config_from_runtime`，不另造投影。

---

## 枚举命令（全仓可重放；覆盖生产 + 全部 Python/Web 测试）

`n1-n7-enum.out` 是 JSON 结果，**不可** `python3 evidence/issue-1902/n1-n7-enum.out`。重放用下方内嵌脚本：

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-n1n7-selfverify
mkdir -p "$TMP"
cd "$ROOT"

python3 <<'PY' | tee "$TMP/enum_all.out" evidence/issue-1902/n1-n7-enum.out
import json, pathlib, re, subprocess
ROOT = pathlib.Path("/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5")

def rel(p):
    return str(p.relative_to(ROOT))

PROD_PY = sorted((ROOT/"ming_sim").rglob("*.py"))
if (ROOT/"web_app.py").exists():
    PROD_PY.append(ROOT/"web_app.py")
TEST_PY = sorted((ROOT/"tests").rglob("test_*.py"))
TEST_WEB = sorted((ROOT/"web/src").rglob("*.test.ts")) + sorted((ROOT/"web/src").rglob("*.test.tsx"))
ALL_TEST = TEST_PY + TEST_WEB

# N1：拟旨意图解析失败/缺键/非法枚举被洗成合法「无」；补交泛化句
n1 = []
for path in PROD_PY:
    src = path.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        if 'return {"draft_action": "无"' in line or "未返回拟旨意图" in line or 'draft_action": "无"' in line:
            n1.append(f"{rel(path)}:{i}:{line.strip()[:140]}")

# N2：入口自造生效 LLMConfig / 相对 llm_config_from_runtime 的共同生效规则副本
n2 = []
for path in PROD_PY:
    src = path.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        if any(k in line for k in (
            "LLMConfig(", "llm_config_from_runtime(", "_llm_config_from_runtime(",
            "for_role(", "_advanced_llm_config_for_verify",
        )):
            n2.append(f"{rel(path)}:{i}:{line.strip()[:140]}")

# N3：恢复集合身份/筛选不在会话共核
n3 = []
pat3 = re.compile(
    r"pending_audience_reply_retries|get_interrupted_reply_retries|"
    r"list_hall_chat_turns|get_post_reply_retries|def reply_retries"
)
for path in PROD_PY:
    src = path.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        if pat3.search(line):
            n3.append(f"{rel(path)}:{i}:{line.strip()[:140]}")

# N4：入口 getattr 缺方法降级到同步收夜/auto_close
n4 = []
pat4 = re.compile(
    r"getattr\(.*(close_night|schedule_close|auto_close)|"
    r"_auto_close_open_night_gate_free|schedule_close_night_after_chat_if_needed"
)
for path in PROD_PY:
    src = path.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        if pat4.search(line):
            n4.append(f"{rel(path)}:{i}:{line.strip()[:140]}")

# N5：共享抽取不可达旧模式 / 退役 kwargs 兼容槽
n5 = []
pat5 = re.compile(
    r"draft_count|has_pending_draft|existing_candidates|existing_draft_text|"
    r"成品旨稿|_retired_mode|\*\*extract_kwargs"
)
for path in PROD_PY + TEST_PY:
    src = path.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        if pat5.search(line):
            n5.append(f"{rel(path)}:{i}:{line.strip()[:140]}")

# N6：全仓测试 — 非契约措辞 / 弱结构 / 内部 identity / 来源留痕
n6_wording, n6_weak, n6_internal, n6_source = [], [], [], []
for path in ALL_TEST:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if re.search(r'assert\s+["\'].*(应拨|实拨|不足额)', s) or (
            "assert" in s and " in " in s
            and any(w in s for w in ("应拨", "实拨", "不足额"))
            and "execution_note" in s
        ):
            n6_wording.append(f"{rel(path)}:{i}:{s[:140]}")
        nearby = "\n".join(lines[max(0, i - 2): i + 8])
        if "status_code" in s and "!=" in s and "500" in s and "error_pack_path" not in nearby:
            n6_weak.append(f"{rel(path)}:{i}:{s[:140]}")
        if re.search(
            r"origin_context\s+in\s+\w+\s+or\s+criterion|"
            r"criterion_text\s+in\s+\w+\s+or\s+origin",
            s,
        ):
            n6_weak.append(f"{rel(path)}:{i}:{s[:140]}")
        if "json.dumps" in s and "category" in s and " in " in s:
            n6_weak.append(f"{rel(path)}:{i}:{s[:140]}")
        if (
            re.search(r"assert\s+\w+\s+is\s+\w+", s)
            and "None" not in s and " is not " not in s
            and "True" not in s and "False" not in s
        ):
            n6_internal.append(f"{rel(path)}:{i}:{s[:140]}")
        if "pollError" in s or ("console.warn" in s and "assert" in s):
            n6_source.append(f"{rel(path)}:{i}:{s[:140]}")

r = subprocess.run(
    ["git", "diff", "10e64fbef", "--", "docs/evidence/issue-1901-w4-1838-merge.md"],
    cwd=str(ROOT), capture_output=True, text=True,
)
print(json.dumps({
    "scope": {"prod_py": len(PROD_PY), "test_py": len(TEST_PY), "test_web": len(TEST_WEB)},
    "n1_candidates": n1,
    "n2_llmconfig_sites": n2,
    "n3_restore_prod_sites": n3,
    "n4_lifecycle_sites": n4,
    "n5_dead_mode_sites": n5,
    "n6_wording_candidates": n6_wording,
    "n6_weak_structure_candidates": n6_weak,
    "n6_internal_identity_candidates": n6_internal,
    "n6_source_retention_sites": n6_source,
    "n7_diff_empty": r.stdout.strip() == "",
    "counts": {
        "n1": len(n1), "n2": len(n2), "n3": len(n3), "n4": len(n4), "n5": len(n5),
        "n6_wording": len(n6_wording), "n6_weak": len(n6_weak),
        "n6_internal": len(n6_internal), "n6_source": len(n6_source),
    },
}, ensure_ascii=False, indent=2))
PY
```

实测 scope：`prod_py=95`，`test_py=222`，`test_web=25`。完整 JSON 见 `n1-n7-enum.out`。

---

## 成员表（语义分类；点名只是样本）

### N1 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `extract_draft_intent` 解析失败 / 缺「拟旨意图」/ 非法枚举 → `draft_action=无` | **修** | 改 `ValueError` 真因分句 |
| `resubmit_draft_admission_payload` 泛化「未返回拟旨意图」 | **保留** | 仅承接模型明确合法「无」；非法产物不再落到此句 |
| 首抽 LLM `Exception` → `_log` 后返回合法「无」 | **保留** | 公开 degrade 合法；公开点= `_log(...)` 调用，**不**靠注释自称公开；**无须**核查日志是否真落痕 |
| `acting_appointment` 短路返回「无」 | **保留** | 署理交回人事链，非解析失败洗「无」 |
| 合法「无」短路返回 | **保留** | 票面 boundary：明确合法「无」≠解析失败 |

### N2 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `WebGame.build_llm_config` / `_menu_save_cli_llm` / `api_menu_save_llm` 自造生效 `LLMConfig` | **修** | 表单/编辑收成 runtime 后只走 `llm_config_from_runtime` |
| `/api/menu/status` 共核投影 | **保留** | 既结 F2 |
| `_advanced_llm_config_for_verify` | **修（复用）** | 改为 `for_role(config, "simulator")`；仅活动 advanced 烟测切片，**无**第二套共同生效规则 |
| `cli_backend` 闸脚本 `LLMConfig(...)` | **保留** | 非 Web/运行档生效路径 |
| `llm_config.for_role` / `llm_config_from_runtime` 内 `LLMConfig(` | **保留** | 共核权威实现本身 |

### N3 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `WebGame.reply_retries(殿上)` 自查夜/轮筛中断集 | **修** | 中断集改 `session.pending_audience_reply_retries()` |
| 同函数 post_reply 按本夜 `list_hall_chat_turns` 过滤 | **保留** | boundary：Web post_reply 适配；与共核中断筛**同形过滤器用于不同表**，非再造中断身份规则 |
| 非殿上 `interrupted_reply_retries(minister)` + post_reply | **保留** | boundary：非殿上请求适配 |
| `can_undo_last_chat` / 在飞轮 `list_hall_chat_turns` | **保留** | 撤回/在飞，非恢复集合副本 |
| CLI `pending_audience_reply_retries` 消费者 | **保留** | 既结共核消费者 |
| DB `list_hall_chat_turns` / `get_*_retries` | **保留** | 取数原语 |

### N4 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `terminal.py` / `web_app.py` `getattr(schedule/close)`→`auto_close` | **修** | 直调 `schedule_close_night_after_chat_if_needed`；复扫 getattr 降级 **0** |
| `_auto_close_open_night_gate_free` | **保留** | 过月屏障真路径，非缺方法替身 |
| 测试壳补齐同形收夜方法 | **修（测试）** | 不把生产降级加回 |

### N5 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `draft_count>1` / 补充合并 / 候选指认整支 | **删** | 无生产消费者 |
| `**_retired_mode_kwargs` 忽略槽 | **删** | 无消费者旧参数忽略=兼容机制；N5 已删模式，**不得**为残缺测试留吞参 |
| heal `**extract_kwargs` 转发槽 | **删** | 同因；`harvest_participants` 改显式传参 |
| 调用端 `draft_count=` 等 | **无残留** | 传入即 `TypeError` |
| 单旨 + `correction_feedback` + heal/resubmit | **保留** | 现役补交必要承接 |

### N6 — **结清**（全仓类定义，非七文件白名单）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_decree_dossiers_571` JSON 字串搜 category | **修** | 钉 `economy_moves_rejections[0]["category"]` |
| `test_error_pack` 只查 `!=500` | **修** | 恢复 `stage`/`error_pack_path`/`turn`（`!=500` 与结构并存，非单独弱断言） |
| chat stream `provider_message` 只查非空 | **修** | 钉横幅进 `provider_message`、不进 message |
| due_review `origin or criterion` | **修** | 二者均须在 opening |
| `useSettlementFlow` pollError 留痕 | **修** | 恢复 `console.warn` 带原 Error（来源契约，非措辞锁） |
| 不足额/应拨/实拨词面锁（含 dossiers） | **删** | 非契约措辞 |
| `test_execution_joint_liability_565` merge 夹具用应拨/实拨字面 | **修** | 全仓复扫命中；改为中性「追加备注甲」——测的是 merge 往返，不是诊断词面 |
| config constants identity / modals 不代笔负向 / placeholder 字数下界 | **删** | 内部/呈现非法证明 |
| `assert write_gate is self.gate` 等 6 条 object identity | **保留** | 闸/队列/reload/名册**行为** identity，非配置常量内部证明 |
| pollError 来源留痕 3 行 | **保留** | 必要异常来源契约 |

### N7 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `docs/evidence/issue-1901-w4-1838-merge.md` 硬换行差分 | **撤销** | `git diff 10e64fbef -- …` 空；不恢复尾随空白门槛 |

---

## 变异证据（真实命令 + 断言红/绿）

探针全文在 `/tmp/ming1902-n1n7-selfverify/mutations/`（临时；不入库）。命令与实测：

### N1 洗「无」→ 泛化句 RED；修复 GREEN

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n1_wash_mutation.py
```

临时探针要点：`MonkeyPatch` 把 `extract_draft_intent` 换成旧 wash（非 dict/缺键/非法枚举一律 `draft_action=无`），对三种非法 raw 走真实 `resubmit_draft_admission_payload`，**断言**均落到同一 `ValueError("结算补交重写未返回拟旨意图")`（RED）；`undo` 后**断言**三分句含「无法解析」/「拟旨意图」/「非法」，合法「无」仍泛化句（GREEN）。

```text
N1_MUTATION_RED_RESULTS [('not-json{{{', 'GENERIC_WASH_OK'), ('{"其它":1}', 'GENERIC_WASH_OK'), ('{"拟旨意图":"胡说"}', 'GENERIC_WASH_OK')]
N1_MUTATION_RED_ASSERT_PASS: old wash collapses all to generic ValueError
N1_RESTORE_GREEN_RESULTS [('无法解析', '拟旨意图抽取结果无法解析'), ('拟旨意图', '拟旨意图抽取缺「拟旨意图」键'), ('非法', "拟旨意图枚举非法：'胡说'")]
N1_RESTORE_GREEN_ASSERT_PASS
```

### N2 本地 LLMConfig 副本 RED；共核投影 GREEN

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n2_projection.py
```

RED：把 `web_app._llm_config_from_runtime` 换成入口自造 `LLMConfig`（同时对真实 `lc.llm_config_from_runtime` 计数），POST `/api/menu/llm` 得 200 且 `shared_projection_calls=0`，**断言 `shared_projection_calls >= 1` 失败**。GREEN：两端都走真实投影，`shared_projection_calls=1`，status 200（烟测 `_verify_llm_configs_or_raise` 临时空实现，避免七 BIN false 挡保存）。

```text
N2_RED_STATUS 200 shared_projection_calls 0
N2_MUTATION_RED_ASSERT_FAIL_AS_EXPECTED: expected shared projection, got 0
N2_GREEN_STATUS 200 shared_projection_calls 1
N2_RESTORE_GREEN_ASSERT_PASS
```

### N3 / N4 / N5 / N6 / N7 断言探针

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n3_semantics.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n4_getattr.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n5_no_sink.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n6_recheck.py
git diff 10e64fbef -- docs/evidence/issue-1901-w4-1838-merge.md   # 空
```

```text
N3_SEMANTICS_ASSERT_PASS
N4_GETATTR_HITS []
N4_NO_GETATTR_DEGRADE_ASSERT_PASS
N5_NO_SINK_ASSERT_PASS (... harvest_participants: bool = False ...)
N6_WORDING_REMAINING []
N6_RECHECK_ASSERT_PASS
N7_EMPTY_ASSERT_PASS
```

N5 额外：`extract_draft_intent(..., draft_count=2)` / heal 同参 → `TypeError`（无吞参兼容）。

---

## 聚焦测试（七 BIN 完整前缀；触及面；未跑全量）

```bash
with_bins env PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-n1n7-selfverify/focus \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_decree_dossiers_571.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_error_pack.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_due_review_621.py \
  tests/test_llm_channel_config.py \
  tests/test_web_llm_runtime_config.py \
  tests/test_cli_entry_1902.py \
  tests/test_web_entry_1902.py \
  tests/test_audience_restore_505.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_execution_joint_liability_565.py \
  tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes \
  tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades
# → 345 passed in 11.48s
# 随后补跑：tests/test_execution_joint_liability_565.py::test_execution_note_merge_interface_and_restore → 1 passed in 1.53s

cd web && with_bins npm test -- --cache=false \
  src/useSettlementFlow.test.tsx src/components/modals.test.tsx
# → 2 files / 76 passed；Duration 1.02s
```

测试契约：复用/收紧既有入口案；删死模式与非法证明；**不为 finding 新增平行证明测试**；不为 N5 留 kwargs 兼容。

最小必要成本：pytest 聚焦 ~11.5s + 565 补跑 ~1.5s + vitest ~1.0s + 变异探针 ~数秒。

---

## 临时探针全文（系统临时目录；交卷可据回执重放）

### 临时探针全文 `n1_wash_mutation.py`

```python
"""Temporary N1 mutation probe: restore old wash→«无» then assert distinct failures; undo; green."""
import importlib
import ming_sim.cli_backend as cb
from pytest import MonkeyPatch

# --- RED: restore old wash semantics for parse/missing/illegal ---
src = open(cb.__file__, encoding='utf-8').read()
# Locate extract_draft_intent body markers; monkeypatch _loads_lenient path via wrapper

_orig = cb.extract_draft_intent

def _washed(player_message, minister_reply, llm_config=None, content=None,
            correction_feedback="", pay_order_facts="", db=None, harvest_participants=False):
    """Old N1 bug: any non-dict / missing key / illegal enum → draft_action=无."""
    raw = ""
    try:
        raw, _ = cb._run_backend_for_config("x", llm_config, tag="draft_intent")
    except Exception as exc:
        if str(correction_feedback or "").strip():
            raise
        cb._log(f"拟旨意图抽取失败：{exc}")
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}
    obj = cb._loads_lenient(raw)
    if not isinstance(obj, dict):
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}  # WASH
    if "拟旨意图" not in obj:
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}  # WASH
    _raw = str(obj.get("拟旨意图") if obj.get("拟旨意图") is not None else "").strip()
    if _raw not in {"无", "拟旨"}:
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}  # WASH
    if _raw == "无":
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}
    # minimal拟旨 stub
    return {"draft_action": "拟旨", "draft_text": minister_reply or "", "target_candidate": "",
            "dossier_action_type": "policy"}

mp = MonkeyPatch()
mp.setattr(cb, "extract_draft_intent", _washed)
# also wash through heal by patching same name used inside heal module namespace
importlib.reload  # noqa: keep import for clarity

illegal_payloads = [
    ("not-json{{{", "无法解析"),
    ('{"其它":1}', "缺"),
    ('{"拟旨意图":"胡说"}', "枚举"),
]

failures = []
for raw, expect_substr in illegal_payloads:
    def _run(prompt, llm_config=None, tag=""):
        return raw, {}
    mp.setattr(cb, "_run_backend_for_config", _run)
    try:
        cb.resubmit_draft_admission_payload(
            decree_text="着户部核边饷",
            failure_reason="probe",
            bad_payload={"mode": "普通"},
            llm_config=None,
            db=None,
            content=None,
        )
        failures.append((raw, "NO_RAISE"))
    except ValueError as e:
        msg = str(e)
        # Under washed extract, resubmit only sees draft_action=无 → generic sentence
        if msg != "结算补交重写未返回拟旨意图":
            failures.append((raw, f"UNEXPECTED:{msg}"))
        else:
            failures.append((raw, "GENERIC_WASH_OK"))

print("N1_MUTATION_RED_RESULTS", failures)
assert all(v == "GENERIC_WASH_OK" for _, v in failures), failures
print("N1_MUTATION_RED_ASSERT_PASS: old wash collapses all to generic ValueError")

# --- GREEN: undo wash; expect distinct reasons ---
mp.undo()
# re-import fresh? monkeypatch undo restores extract_draft_intent
assert cb.extract_draft_intent is _orig or cb.extract_draft_intent.__name__ == "extract_draft_intent"

green = []
cases = [
    ("not-json{{{", "无法解析"),
    ('{"其它":1}', "拟旨意图"),
    ('{"拟旨意图":"胡说"}', "非法"),
]
for raw, needle in cases:
    def _run(prompt, llm_config=None, tag="", _raw=raw):
        return _raw, {}
    with MonkeyPatch().context() as m:
        m.setattr(cb, "_run_backend_for_config", _run)
        try:
            cb.resubmit_draft_admission_payload(
                decree_text="着户部核边饷",
                failure_reason="probe",
                bad_payload={"mode": "普通"},
                llm_config=None,
                db=None,
                content=None,
            )
            green.append((needle, "NO_RAISE"))
        except ValueError as e:
            green.append((needle, str(e)))

print("N1_RESTORE_GREEN_RESULTS", green)
assert all(n in msg for n, msg in green), green
# legal 无 still generic
with MonkeyPatch().context() as m:
    m.setattr(cb, "_run_backend_for_config", lambda *a, **k: ('{"拟旨意图":"无"}', {}))
    try:
        cb.resubmit_draft_admission_payload(
            decree_text="着户部核边饷", failure_reason="probe",
            bad_payload={"mode": "普通"}, llm_config=None, db=None, content=None,
        )
        raise SystemExit("legal none should raise")
    except ValueError as e:
        assert str(e) == "结算补交重写未返回拟旨意图", e
print("N1_RESTORE_GREEN_ASSERT_PASS")
```

### 临时探针全文 `n2_projection.py`

```python
"""N2: restore Web-local LLMConfig builder → shared projection counter stays 0 (RED);
restore fix → counter >=1 (GREEN). Asserts, not prints."""
import asyncio
import web_app
import ming_sim.llm_config as lc
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from ming_sim.llm_config import LLMConfig

body = {
    "channel": "cli",
    "cli_runner": "codex",
    "cli_model": "gpt-5.5",
    "reasoning_strength": "low",
    "advanced_reasoning_strength": "high",
    "model": "m",
    "base_url": "https://x/v1",
    "api_key": "",
    "timeout_seconds": 60,
    "thinking_level": "",
    "advanced_model": "",
    "advanced_base_url": "",
    "advanced_api_key": "",
    "advanced_thinking_level": "",
}

_real = lc.llm_config_from_runtime

def _local_copy(runtime, **kwargs):
    """Old N2 bug shape: entry self-builds effective LLMConfig (shared core not called)."""
    cli = runtime.get("cli") if isinstance(runtime.get("cli"), dict) else {}
    return LLMConfig(
        api_key="",
        base_url="",
        model=str(cli.get("model") or kwargs.get("model") or ""),
        channel="cli",
        cli_runner=str(cli.get("runner") or ""),
        cli_model=str(cli.get("model") or ""),
        timeout_seconds=float(runtime.get("timeout_seconds") or 60),
        reasoning_strength=str(runtime.get("reasoning_strength") or ""),
    )

shared = {"n": 0}
def _count_real(*a, **k):
    shared["n"] += 1
    return _real(*a, **k)

# --- RED ---
shared["n"] = 0
with MonkeyPatch().context() as mp:
    mp.setattr(lc, "llm_config_from_runtime", _count_real)
    # Web menu uses web_app._llm_config_from_runtime alias — point it at local copy
    mp.setattr(web_app, "_llm_config_from_runtime", _local_copy)
    mp.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: None)
    r = TestClient(web_app.app).post("/api/menu/llm", json=body)
    print("N2_RED_STATUS", r.status_code, "shared_projection_calls", shared["n"])
    assert r.status_code == 200, (r.status_code, r.text[:300])
    red_failed = False
    try:
        assert shared["n"] >= 1, f"expected shared projection, got {shared['n']}"
    except AssertionError as e:
        red_failed = True
        print("N2_MUTATION_RED_ASSERT_FAIL_AS_EXPECTED:", e)
    assert red_failed, "RED must fail the shared-projection assertion"

# --- GREEN ---
shared["n"] = 0
with MonkeyPatch().context() as mp:
    mp.setattr(lc, "llm_config_from_runtime", _count_real)
    mp.setattr(web_app, "_llm_config_from_runtime", _count_real)
    mp.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: None)
    r = TestClient(web_app.app).post("/api/menu/llm", json=body)
    print("N2_GREEN_STATUS", r.status_code, "shared_projection_calls", shared["n"])
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert shared["n"] >= 1, shared
print("N2_RESTORE_GREEN_ASSERT_PASS")
```

### 临时探针全文 `n3_semantics.py`

```python
import inspect, web_app, ming_sim.session as session
src = inspect.getsource(web_app.WebGame.reply_retries)
assert "pending_audience_reply_retries" in src
assert "get_post_reply_retries" in src
# interrupted hall path must not re-implement get_interrupted_reply_retries(SCENE) filter itself
# (post_reply may still filter by hall ids — allowed adaptation)
hall_branch = src.split("非殿上")[0]
assert "get_interrupted_reply_retries" not in hall_branch or "pending_audience_reply_retries" in hall_branch
assert "pending_audience_reply_retries" in hall_branch
# session core owns night+hall filter for interrupted
csrc = inspect.getsource(session.GameSession.pending_audience_reply_retries)
assert "list_hall_chat_turns" in csrc and "get_interrupted_reply_retries" in csrc
print("N3_SEMANTICS_ASSERT_PASS")
```

### 临时探针全文 `n4_getattr.py`

```python
import pathlib, re
ROOT = pathlib.Path('.')
hits = []
for rel in ['ming_sim/cli/terminal.py', 'web_app.py']:
    text = (ROOT/rel).read_text(encoding='utf-8')
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r'getattr\(.*(close_night|schedule_close|auto_close)', line):
            hits.append(f'{rel}:{i}:{line.strip()}')
print('N4_GETATTR_HITS', hits)
assert hits == [], hits
print('N4_NO_GETATTR_DEGRADE_ASSERT_PASS')
```

### 临时探针全文 `n5_no_sink.py`

```python
import inspect, ming_sim.cli_backend as cb
sig = inspect.signature(cb.extract_draft_intent)
assert "kwargs" not in str(sig) and "_retired" not in str(sig), sig
sig2 = inspect.signature(cb.extract_draft_intent_with_roster_heal)
assert "extract_kwargs" not in str(sig2) and "kwargs" not in str(sig2), sig2
try:
    cb.extract_draft_intent("a","b", draft_count=2)
    raise SystemExit("should TypeError")
except TypeError:
    pass
print("N5_NO_SINK_ASSERT_PASS", sig)
```

### 临时探针全文 `n6_recheck.py`

```python
import pathlib, re
ROOT = pathlib.Path('.')
wording = []
for path in list((ROOT/'tests').rglob('test_*.py')) + list((ROOT/'web/src').rglob('*.test.ts*')):
    text = path.read_text(encoding='utf-8')
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r'assert\s+["\'].*(应拨|实拨|不足额)', line) or (
            'assert' in line and ' in ' in line and any(w in line for w in ('应拨','实拨','不足额'))
            and 'execution_note' in line
        ):
            wording.append(f'{path.relative_to(ROOT)}:{i}:{line.strip()[:120]}')
print('N6_WORDING_REMAINING', wording)
assert wording == [], wording
# error_pack keeps structure fields
ep = (ROOT/'tests/test_error_pack.py').read_text(encoding='utf-8')
assert 'error_pack_path' in ep and 'stage' in ep and 'turn' in ep
# due_review both required
dr = (ROOT/'tests/test_due_review_621.py').read_text(encoding='utf-8')
assert 'assert origin_context in opening' in dr and 'assert criterion_text in opening' in dr
# settlement pollError retained
us = (ROOT/'web/src/useSettlementFlow.test.tsx').read_text(encoding='utf-8')
assert 'pollError' in us and 'warn.mock.calls' in us
print('N6_RECHECK_ASSERT_PASS')
```

## 结清总表

| 类 | 状态 |
|---|---|
| N1 | **结清** |
| N2 | **结清**（含 advanced 烟测改 `for_role`） |
| N3 | **结清**（post_reply 夜筛保留为适配） |
| N4 | **结清** |
| N5 | **结清**（退役 kwargs 槽已删） |
| N6 | **结清**（全仓复扫后无措辞/弱结构残留） |
| N7 | **结清** |

无「合法保留却写未结待庭」项。功能缺口/家族复杂度仍归 #1812/#1873，本票不设。

自查二连 done。
