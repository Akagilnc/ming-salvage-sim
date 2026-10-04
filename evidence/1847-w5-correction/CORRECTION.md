# #1847 w5 自检修正（不删除历史卷宗）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-n6-n11-n12-n13`
- corrects: `dddd600bb` / `evidence/1847-w5-class-report.md` false「逐项已验证」claims
- prior dossier retained: `evidence/1847-w5-rescan/` (historical; scanner contract updated in place)
- this dossier: `evidence/1847-w5-correction/` (new references only)
- continues from HEAD `0b82b9523` (ask_emperor transport fix retained)

## What was wrong

1. `scan_classify_n6_n13.py` `classify_n6_py` auto-wrote KEEP for any strip/slice/split by shape
   ("formal identity/key", "bounded structured field/id", "token/path/CSV") — not reading
   callers or source→dest contracts.
2. Clearing `KEEP_review_bucket` by swapping wording ≠ verification.
3. N11 `EXCLUDED_noise` from vocabulary scan without complete exclusion basis ≠ full class.
4. N12 literal-key scan claimed full-class exclude/KEEP.
5. Report treated `evidence/1847-mutation-probes.py` re-run as real entry proof — **referee rejected**
   that HTTP/UI probe as ask_emperor→PTY proof.
6. Leaving 2502/617/176/95 as「工作量未完成」≠ ticket completion.

## What changed (this continuation)

| Item | Change |
|---|---|
| Scanner | Unchanged: auto rules → `PENDING_HUMAN` / `POTENTIAL_*` / `MECHANICAL_*` / `DELETED_KNOWN` only; **never KEEP_*** |
| Code | **No production code delta this round** — transport seams re-read KEEP; no illegal SIGKILL/reachable free-prose rewrite found to delete |
| Human table | `human_judgment.tsv` — module/fn/datatype group reviews with source_contract + dest_path + callers |
| Full map | `candidate_to_group.tsv` — every scan candidate → group_id + human disposition; unresolved **0** |
| Summary | `judgment_summary.json` + `remaining_scope.md` (scan PENDING retained; human unresolved=0) |
| Mutation | Prior `n6_ask_emperor_pty_mutation.py` retained; web HTTP / secret assemble verified at source (no transport edit → no new mutation) |

## Class results (honest)

### N6

- Universe mechanical: 3118; scan `PENDING_HUMAN` **2502** (still mechanical — not auto-KEEP).
- Human: all 2502 mapped; dispositions = formal_id / empty_gate / form_ui / log_trace /
  compare_only / structure / sqlite_sanitize / KEEP (transport) — see `judgment_summary.json`.
- Transport re-verified: `parse_emperor_output`/`sendline`, `useChatActions.sendChat`,
  `web_app` chat handlers, `assemble_secret_order_content`, stream callbacks, `_declared_prose`.
- DELETE_FIX this round: **none** (prior input `splitlines()[0]` already removed at `0b82b9523`).

### N11

- Scan: 617 `POTENTIAL_NOISE` + 20 `PENDING_HUMAN` + 29 `DELETED_KNOWN`.
- Human: `KEEP_live` (calibrated / float_v2 / pairing_warnings negative / 帝国修正 domain) +
  `EXCLUDED_noise` (vocab/comment/test without deletable retired symbol) + prior `DELETED_KNOWN`.
- New residue deletes this round: **none**.

### N12

- Literal hits: 176; human per-group second-def check.
- `CONVERGED_KNOWN` / `KEEP_single_def` / `KEEP_subset` / `KEEP_spike`; **no** new duplicate delete;
  no cross-language transport layer invented.

### N13

- Scan `PENDING_HUMAN`: **95**; all sites confirmed.
- No reachable SIGKILL / `terminate(force=True)` / `close(force=True)` / `subprocess.run(timeout=)`
  on production paths; soft SIGTERM / resource `.close()` / thread/HTTP/SDK timeouts KEEP.
- Illegal reachable deletes this round: **none** (warm_keychain + login_shell timeout already gone).

## Verification commands

```bash
# Mechanical rescan (no KEEP verdicts) — optional; dossier already frozen
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

# Coverage audit (human unresolved must be 0)
python3 -c "import json; print(json.load(open('evidence/1847-w5-correction/judgment_summary.json')))"
```

Focused 333-file pytest **not** re-run this round: no production code change (user: 勿复跑无变化批次).

## 自查二连 done

- 同类：形状猜契约冒充逐项验证；消灭 review 桶换文案；mutation-probes 冒称真入口；以工作量交未完成
- 引入：分组判定须可核来源去向；脚本只做行→组映射、不作语义 KEEP；扫描 PENDING 保留与「人审未决=0」分开陈述
