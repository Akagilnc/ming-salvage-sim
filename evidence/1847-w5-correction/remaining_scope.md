# #1847 w5 correction — 真实核验剩余范围

Prior false claim (dddd600bb `evidence/1847-w5-class-report.md`): mechanical
`KEEP_*` rows =「逐项已验证去留」. Rejected: shape heuristics are not source→dest review.

## Already human-reviewed this round (see `human_judgment.tsv`)

- N6 transport-critical groups: play_as_emperor parse/ask/sendline; agents stream callbacks;
  cli_backend prose compose / grounding / JSON parse / intent compare / trace; web chat
  empty-gate + highlights + settleStream + splitReportItems; web_app humanize/report gates;
  declaration_dispatch `_declared_prose`; month_chain report empty-gates; session run-row truncate.
- N6 code fix: `parse_emperor_output` removed `input` `splitlines()[0]` regression.
- N6 real entry mutation: `n6_ask_emperor_pty_mutation.py` (ask_emperor→PTY sendline).
  **Not** `evidence/1847-mutation-probes.py` (HTTP/UI — referee rejected as entry proof).
- N11 named DELETED_KNOWN + live KEEP (0055 / calibrated / pairing negative).
- N12 CONVERGED_KNOWN + spike + power subset human re-affirm.
- N13 warm delete + terminate(force=False) + login_shell no timeout.

## Remaining (honest counts; not「已结清」)

| Surface | What remains | Approx |
|---|---|---|
| N6 `PENDING_HUMAN` after rescan | Mechanical hits not covered by `human_judgment.tsv` groups | **2502** rows (incl. tests-filtered production bulk); human table covers transport-critical groups only |
| N6 db.py / issues.py / materials.py bulk identity strips | Same-source formal id strips can be group-reviewed further; not yet every fn cited | db.py 267 / issues 137 / materials 60 groups (pre-count) |
| N11 `POTENTIAL_NOISE` | Vocabulary hits need per-hit「有无退役机制符号」full-class exclusion basis | **617** |
| N11 `PENDING_HUMAN` named live-adjacent | calibrated / float_v2 / pairing / decision_key — KEEP only where human_judgment cites | **20** scan rows; KEEP subset in human table |
| N12 `n12_literal_hits` | Per-hit second-definition check before EXCLUDE | **176** |
| N13 `PENDING_HUMAN` | Production timeout/close/terminate hits need per-site no-kill confirm | **95** |
| Mutation coverage | ask_emperor→PTY done (1.22s PASS); other N6 seams (web chat HTTP, secret assemble) not re-probed this round | — |

## Explicit non-claims

- Shape `strip`/`slice`/`split` ≠ KEEP formal identity.
- Eliminating `KEEP_review_bucket` by renaming ≠ verification.
- Re-running `evidence/1847-mutation-probes.py` ≠ ask_emperor→PTY entry proof.
- N11/N12 symbol/key search ≠ full-class enum complete.
