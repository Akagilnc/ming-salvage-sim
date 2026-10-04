# #1847 w5 自检修正（不删除历史卷宗）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-n6-n11-n12-n13`
- corrects: `dddd600bb` / `evidence/1847-w5-class-report.md` false「逐项已验证」claims
- prior dossier retained: `evidence/1847-w5-rescan/` (historical; scanner contract updated in place)
- this dossier: `evidence/1847-w5-correction/` (new references only)

## What was wrong

1. `scan_classify_n6_n13.py` `classify_n6_py` auto-wrote KEEP for any strip/slice/split by shape
   ("formal identity/key", "bounded structured field/id", "token/path/CSV") — not reading
   callers or source→dest contracts.
2. Clearing `KEEP_review_bucket` by swapping wording ≠ verification.
3. N11 `EXCLUDED_noise` from vocabulary scan without complete exclusion basis ≠ full class.
4. N12 literal-key scan claimed full-class exclude/KEEP.
5. Report treated `evidence/1847-mutation-probes.py` re-run as real entry proof — **referee rejected**
   that HTTP/UI probe as ask_emperor→PTY proof.

## What changed (minimal)

| Item | Change |
|---|---|
| Scanner | Auto rules → `PENDING_HUMAN` / `POTENTIAL_*` / `MECHANICAL_*` / `DELETED_KNOWN` only; **never KEEP_*** |
| Code | `scripts/play_as_emperor.py` `parse_emperor_output`: delete `input` `splitlines()[0]`; empty-gate on envelope; keep formal JSON locate strip |
| Human table | `human_judgment.tsv` — grouped reviews with source_contract + dest_path + callers |
| Mutation | `n6_ask_emperor_pty_mutation.py` real ask_emperor→PTY sendline; model stubbed; old strip/split/[:200] red, current green |
| Report | This file + `remaining_scope.md`; prior `1847-w5-class-report.md` superseded for verdict claims |

## Verification commands

```bash
# Mechanical rescan (no KEEP verdicts)
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-rescan/scan_classify_n6_n13.py

# Real N6 entry mutation (NOT 1847-mutation-probes.py)
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.py

# Focused seven-BIN tests (existing; no new permanent proof tests)
mkdir -p /tmp/1847-w5-correction/pytest
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_cli_backend.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_person_delta_adapter.py \
  tests/test_office_rank_562.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_month_chain_1847.py \
  -q --basetemp=/tmp/1847-w5-correction/pytest
```

Results captured:

- ask_emperor→PTY mutation: **EXIT=0 / real 1.22s** → `n6_ask_emperor_pty_mutation.txt`
- focused pytest: **333 passed in 13.64s** → `focused_pytest.txt`
- rescan: `n6_pending_human=2502`, auto `KEEP_*=0` → `rescan_run.txt` / `summary.json`
- 0055负向闸: retained (`tests/test_new_issues_section_rejections.py` + live decision_key refs)

## 自查二连 done

- 同类：形状猜契约冒充逐项验证；消灭 review 桶换文案；mutation-probes 冒称真入口
- 引入：删 splitlines 后 JSON 多行 input 保全；PTY 探针用单行长串避开 readline 语义；扫描器不再产 KEEP
