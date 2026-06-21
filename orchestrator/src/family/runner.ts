/**
 * runFamily — the family spine (ADR 0022 decisions 1/2/3②/6, #293).
 *
 * The thinnest complete family closure:
 *   parent epic (children already cut + blocked_by)             [ADR 0022 dec.1]
 *     → commander.selectWave → the unblocked wave
 *     → fan out each child through the REUSED single-slice runOrchestrator,
 *       in family mode (cut from family base, S7 push = local no-op)  [dec.2/7]
 *     → merger.mergeChild → serial `git merge --no-ff` into family base [dec.3②]
 *       (which writes the append-only family-ledger entry)             [dec.5]
 *     → verify-cmr hook (no-op in #293)                            [dec.3④/⑥ seam]
 *     → loop until the commander returns an empty wave.
 *
 * The spine is a THIN scheduler: it OWNS none of the four extension modules'
 * logic — it only CALLS them (selectWave / runOrchestrator / mergeChild /
 * runVerifyCmr). That is the acceptance-4 boundary: #294 (waves), #295 (merge
 * conflict), #296 (verify+cmr), #298 (ledger) each grow THEIR module and the
 * spine keeps calling the same functions. #293 does NOT process conflicts, run
 * verify/cmr, or do crash-resume reconcile (those are the later slices).
 *
 * The wave loop is written generally (re-select after each wave from the merged
 * set) so #294's multi-wave dependency scheduling drops in WITHOUT a spine
 * rewrite — but #293's children are all independent, so it converges in one wave.
 */

import { runOrchestrator } from "../runner.js";
import type { Backend } from "../types.js";
import { selectWave } from "./commander.js";
import { mergedSet } from "./ledger.js";
import { mergeChild } from "./merger.js";
import { runVerifyCmr } from "./verifyCmr.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyChildResult,
  FamilyRunInput,
  FamilyRunResult,
  FamilyRunStatus,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

/**
 * Run a child slice through the reused single-slice runner in FAMILY MODE.
 *
 * Family context (ADR 0022 decision 2) is passed via RunInput.family so the
 * single-slice runner cuts from the family base + no-ops S7 push. The child is a
 * leaf (no sub-issues) so its own S0 gate passes unchanged; #293's wave is
 * all-unblocked children so the ledger口径 dependency check (dec.6③) is trivially
 * satisfied (empty blocked_by).
 */
async function runChild(
  child: ChildSlice,
  singleSliceBackend: Backend,
  parentIssue: number,
  familyBase: string,
): Promise<FamilyChildResult> {
  const result = await runOrchestrator({
    issueNumber: child.issue,
    backend: singleSliceBackend,
    family: { parentIssue, familyBase, noPush: true },
  });
  if (result.status === "success" && result.branch !== undefined) {
    // The single-slice run succeeded and produced a reviewed branch — but it is
    // NOT merged yet (the spine's serial-merge step does that, then flips this to
    // "merged" once the merge commit lands — ADR 0022 decision 5). So runChild
    // returns the transient "ran", never a premature "merged".
    return { issue: child.issue, status: "ran", branch: result.branch };
  }
  // #293 thinnest: a non-success child does not merge. (Richer per-child
  // failure / escalate handling is downstream; the spine records it as failed
  // so the wave's outcome is honest, not silently dropped.)
  return { issue: child.issue, status: "failed" };
}

/**
 * Read the current merged set from the family ledger (the commander's unblock
 * truth, ADR 0022 decision 6②). Re-read each wave so #294's dependency
 * scheduling sees the freshly-merged children.
 */
async function currentMerged(
  familyBackend: FamilyBackend,
): Promise<ReadonlySet<number>> {
  return mergedSet(await familyBackend.readFamilyLedger());
}

/**
 * The family spine entry point (#293).
 *
 * @returns the family base branch + its HEAD after all merges + per-child
 *   outcomes. Acceptance 1: N independent ready children → one wave → serially
 *   merged into the family base.
 */
export async function runFamily(
  input: FamilyRunInput,
): Promise<FamilyRunResult> {
  const { epic, familyBackend, singleSliceBackend, familyBase } = input;
  // The verify-cmr hook: the injected impl (#296 / tests) or the #293 no-op module
  // default. The spine's call sites + fail-fast on `ok===false` are identical
  // either way (ADR 0022 decision 3④/⑤/⑥; acceptance-4 seam boundary).
  const verifyCmr = input.verifyCmr ?? runVerifyCmr;
  const childResults: FamilyChildResult[] = [];
  let familyHead: string | undefined;

  // Build the family result, accounting for EVERY epic child. A child the wave
  // loop never scheduled (a blocker never merged, so it stayed blocked when the
  // loop terminated — or a fail-fast wave aborted before it ran) is recorded
  // `"skipped"`, never silently dropped from the result (decision 3⑤ "不静默吞").
  // #294's richer wave/cycle logic refines the skipped reason; #293 just keeps
  // the result honest.
  //
  // `status` makes the verify-cmr outcome OBSERVABLE (decision 3⑤ "不静默吞"): a
  // red barrier returns `status:"verify_failed"` + `failedPhase`, so the caller
  // can tell a red run from a clean `"success"` (a red final-verify must NOT look
  // like success). #293's no-op verify always passes, so a complete run is
  // `"success"`; the failure path is reached only via an injected `verifyCmr`.
  const finalize = (
    status: FamilyRunStatus,
    failedPhase?: VerifyCmrPhase,
  ): FamilyRunResult => {
    const recorded = new Set(childResults.map((c) => c.issue));
    const skipped: FamilyChildResult[] = epic.children
      .filter((c) => !recorded.has(c.issue))
      .map((c) => ({ issue: c.issue, status: "skipped" as const }));
    return {
      status,
      ...(failedPhase !== undefined ? { failedPhase } : {}),
      familyBase,
      familyHead,
      children: [...childResults, ...skipped],
    };
  };

  // The wave loop. Re-select from the merged set after each wave so a future
  // multi-wave epic (#294) advances as blockers merge; #293's all-unblocked
  // children converge in a single pass. Guard against a no-progress wave (a
  // child that failed to merge would otherwise re-select forever) by tracking
  // the set of children the spine has already ATTEMPTED.
  const attempted = new Set<number>();
  for (;;) {
    const merged = await currentMerged(familyBackend);
    const wave = selectWave(epic.children, merged).filter(
      (c) => !attempted.has(c.issue),
    );
    if (wave.length === 0) break;

    // ── fan out the wave: each child through the reused single-slice runner ──
    // ADR 0022 decision 2 (native fork + distinct branch) is the RealBackend's
    // job (each child run cuts its own distinct branch in the shared clone). The
    // wave-level fan-out POLICY — how the wave's children are run relative to each
    // other — lives in THIS loop, not in the Backend (the Backend interface is
    // per-child: prepareWorktree / runStep / push; it has no whole-wave method).
    // #293 runs the wave SERIALLY in the zero-container spine; #294 makes it
    // concurrent by turning this `for…await` into a `Promise.allSettled(wave.map(…))`
    // HERE — a local change to this fan-out loop, NOT a rewrite of the wave/merge/
    // verify structure around it. (Distinct child branches isolate the LOGICAL
    // work, but NOT git-level locks: concurrent `git worktree add` / ref updates on
    // the one shared clone contend on `.git/index.lock` / ref locks, so #294 must
    // serialize the git-mutating steps — a RealBackend concern, not the spine's.)
    // The spine's contract (one wave's children fanned out, then serially merged)
    // is identical either way.
    const ran: FamilyChildResult[] = [];
    for (const child of wave) {
      attempted.add(child.issue);
      ran.push(await runChild(child, singleSliceBackend, epic.issue, familyBase));
    }

    // ── serial merge: each reviewed child branch into the family base ──────────
    // merger.mergeChild does the `git merge --no-ff` (via the FamilyBackend seam)
    // AND writes the merged ledger entry (decision 5 order). The spine never does
    // the merge itself — that is the #295 seam boundary. A child is recorded
    // `"merged"` ONLY AFTER its merge commit lands (decision 5): runChild returns
    // `"ran"` (single-slice success, not yet merged), and we flip it to `"merged"`
    // here once mergeChild resolves — so a future #295 merge failure can leave the
    // child as `"ran"`/`"failed"` instead of a stale `"merged"`.
    for (const r of ran) {
      if (r.status === "ran" && r.branch !== undefined) {
        const mergeResult = await mergeChild(familyBackend, {
          childIssue: r.issue,
          childBranch: r.branch,
        });
        familyHead = mergeResult.familyHead;
        childResults.push({ issue: r.issue, status: "merged", branch: r.branch });
      } else {
        childResults.push({ issue: r.issue, status: r.status, branch: r.branch });
      }
    }

    // ── verify-cmr hook: per-wave barrier (#293 no-op seam, #296 fills) ─────────
    // Decision 3④: a red wave fails-fast — abort BEFORE selecting the next wave.
    // #293's no-op returns ok:true so the loop continues; the spine ALREADY acts
    // on `ok` and passes the phase + context, so #296 fills only the hook body
    // (run typecheck + tests in the family base) without touching this loop.
    const waveVerify = await verifyCmr({
      phase: "wave",
      familyBase,
      familyBackend,
    });
    if (!waveVerify.ok) {
      // Fail-fast (decision 3④): do not排下一波. #296's red wave lands here; the
      // family base + ledger are left for triage (decision 3⑤ "不静默吞"). Children
      // not yet run are recorded "skipped" by finalize(); the run is observably
      // `verify_failed` at the "wave" phase (NOT an indistinguishable success).
      return finalize("verify_failed", "wave");
    }
  }

  // ── verify-cmr hook: end-of-run barrier (#293 no-op seam, #296 fills) ─────────
  // Decision 3⑤/⑥: after all waves merge, run the 全量 verify + the load-bearing
  // integrated cross-model cmr (catches 跨片接缝). #293 no-op; the call site is
  // wired now so #296 fills only the "final" hook body, not the spine.
  const finalVerify = await verifyCmr({
    phase: "final",
    familyBase,
    familyBackend,
  });
  if (!finalVerify.ok) {
    // #296's failing integrated cmr lands here. #293 no-op never trips it. The
    // result carries the merged children AND `status:"verify_failed"`/`failedPhase:
    // "final"` so a red final verify is OBSERVABLY distinct from success — the
    // caller / PR step must NOT ship it (decision 3⑤ "不静默吞"); the family base +
    // ledger are left for triage.
    return finalize("verify_failed", "final");
  }

  return finalize("success");
}
