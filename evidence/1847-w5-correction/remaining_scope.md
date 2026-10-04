# #1847 w5 correction — 真实核验剩余范围（本轮结清后）

Prior false claim (dddd600bb `evidence/1847-w5-class-report.md`): mechanical
`KEEP_*` rows =「逐项已验证去留」. Rejected: shape heuristics are not source→dest review.

## Scan vs human (do not conflate)

| Surface | Mechanical scan (still PENDING/POTENTIAL by design) | Human unresolved after group review |
|---|---|---|
| N6 | **2502** `PENDING_HUMAN` in `n6_members_classified.tsv` | **0** — all mapped in `candidate_to_group.tsv` |
| N11 | **617** `POTENTIAL_NOISE` + **20** `PENDING_HUMAN` | **0** |
| N12 | **176** `n12_literal_hits` | **0** |
| N13 | **95** `PENDING_HUMAN` | **0** |

Scanner contract unchanged: **never auto-`KEEP_*`**. Human KEEP/DELETE/EXEMPT live only in
`human_judgment.tsv` + row map `candidate_to_group.tsv`.

## This round (grouped human review)

- Grouping unit = real module / function family / datatype contract (shared source→dest + consumers).
- Apply script only maps rows → authored groups; **does not** invent KEEP from strip/slice/re.
- N13: all 95 live sites read for signal/close/terminate/kill; **no SIGKILL escalate**;
  `terminate(force=False)`; `_terminate_cli_process` SIGTERM+wait then pass; web shutdown
  `os.kill(pid, SIGTERM)` self; login_shell **no** `subprocess.run(timeout=)`.
- N11: live `__leverage_offsets_calibrated` / `float_v2` / `pairing_warnings` negative /
  帝国修正 domain mechanic → `KEEP_live`; vocab/comment/test without deletable retired symbol →
  `EXCLUDED_noise`; prior deletions → `DELETED_KNOWN`.
- N12: per-literal-group second-definition check → `CONVERGED_KNOWN` / `KEEP_single_def` /
  `KEEP_subset` / `KEEP_spike`; **no** new `DELETE_duplicate`; no cross-language transport layer.
- N6: transport-critical seams re-verified (ask_emperor/sendline, web chat HTTP, secret assemble,
  stream callbacks, declared_prose, report empty-gates). **No new free-prose transport rewrite**
  found → **no production code change this round**; no new hard-limit guardrail.

## Legal exceptions (not「未完成」)

- `EXEMPT_TEST` / `MECHANICAL_TEST` — tests/
- `EXEMPT_DOC` / `MECHANICAL_DOC` — comments/docs
- `KEEP_log_trace` — operator tlog/diag/error-pack previews
- `KEEP_form_ui` / formal id / empty-gate / compare-only / sqlite sanitize / structure chrome
- `KEEP_spike` — `spike_settle_tick` oracle mirror
- `KEEP_HARNESS_CONTEXT` — play_as_emperor CLI chunk window (not keyboard sendline)

## Explicit non-claims

- Scan `PENDING_HUMAN` count going to zero ≠ required (scanner must stay mechanical-only).
- Renaming buckets or clearing `KEEP_review_bucket` ≠ verification.
- Re-running `evidence/1847-mutation-probes.py` ≠ ask_emperor→PTY entry proof.
- This round did **not** re-run the 333-file focused pytest batch (no production code delta).

## Artifacts

| File | Role |
|---|---|
| `human_judgment.tsv` | Group judgments (source_contract + dest + callers) |
| `candidate_to_group.tsv` | Full candidate → group_id + human disposition |
| `judgment_summary.json` | Counts + unresolved=0 audit |
| `n6_ask_emperor_pty_mutation.py` | Real ask_emperor→PTY mutation (prior PASS retained) |
| `CORRECTION.md` | Self-check correction + commands |
