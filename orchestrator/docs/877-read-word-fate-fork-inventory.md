# #877 [873·S3] residual runner read-word fate-fork inventory

Sweep beyond S1 (#875 verifyCmr accounting court) and S2 (#876 git-truthing conviction).

Principle (#861 / #873): runner is a traffic cop — **exit code / findings count / decision gate**. Do not parse worker prose/state to branch fate. No milder validators.

## Inventory + disposition

| ID | Site | Pre-#877 fate | Action | Survival test |
|----|------|---------------|--------|---------------|
| R1 | `adjudicatePriorClaimedFixedFindings` (missing disposition / still-active reopen / key-payload throw) | contract_drift / reopen without findings[] | **Deleted** — findings-count only; never throws | `read-word-fate-fork-877.test.ts` R1; flipped `per-slice-cmr-369` |
| R2 | S4 no-progress escalate (still-active ×2 without repair evidence) | escalate `same_module_still_red` | **Deleted** | `read-word-fate-fork-877` R2; dogfood 307 no-progress scenarios |
| R3 | `recheckConvergenceConfirmsFixMarkedKeys` | contract_drift on bare post-fixer converge | **Hard DELETE** (function + runner court branch; not always-true shell) | R3 static absence nail + flipped online-review #743 tests |
| R4 | `enforceRunnerOwnedRecheck` contradiction kill | infra_failure / decision_gate on isRecheck mismatch | **Deleted kill** — force-normalize only | R4 unit; flipped r26 fails-closed |
| R5 | `verifyResultSemanticallyConsistent` disposition↔fixMarked set-equality | malformed verify → fail path | **Hard DELETE** semantic helper; type-shape only in `isValidVerifyResult` | R5 static absence + type-valid pins r24/r25 |
| R6 | dogfood `376-closure-context-missing` | contract_drift kill assert | **Flipped** to ship | dogfood-replay-451 |

## Left intentionally (not conviction courts)

| Site | Why kept |
|------|----------|
| Three-channel shape (`kind` / `converged` bool / findings array type) | Exit / findings / decision envelope |
| `classifyFindings` + trusted accepted_suppression → envelope count | ADR 0062 typed governance → findings count |
| CMR floor / required-leg skip | Real provider infra degradation |
| Tracked worktree dirty after read-only verify | Real dirty residue (S2 kept) |
| HEAD position reads | Routing plumbing (S4 head short-circuit) |
| Coder `committed` from git graph + advisory self-report discrepancy | Head-movement routing; not contract_drift death |
| `cmrLegAccountingFailure` pure helper | Not wired to abort after S1; unit tests only |
| Worker-raised `escalate` / decision gate park | Decision channel |
| Real infra durable abort (tsx missing, dispatch exhaust, etc.) | Real infra |

## Keep / do not re-add

- Do not reintroduce disposition coverage audits, fix-marked echo courts, isRecheck contradiction kills, or no-progress disposition thresholds.
- Prior finding handoff = landing artifact pointers; next fresh reviewer re-emits findings if still open.
