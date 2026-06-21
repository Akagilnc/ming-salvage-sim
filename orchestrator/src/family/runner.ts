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
} from "./types.js";

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
    return { issue: child.issue, status: "merged", branch: result.branch };
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
  const childResults: FamilyChildResult[] = [];
  let familyHead: string | undefined;

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
    // job; the spine just runs each child's runner. #293 runs them sequentially
    // in the zero-container spine; the real parallel fan-out is the RealBackend's
    // Promise.allSettled — the spine's contract (one wave's children, then merge)
    // is identical either way.
    const ran: FamilyChildResult[] = [];
    for (const child of wave) {
      attempted.add(child.issue);
      ran.push(await runChild(child, singleSliceBackend, epic.issue, familyBase));
    }

    // ── serial merge: each reviewed child branch into the family base ──────────
    // merger.mergeChild does the `git merge --no-ff` (via the FamilyBackend seam)
    // AND writes the merged ledger entry (decision 5 order). The spine never does
    // the merge itself — that is the #295 seam boundary.
    for (const r of ran) {
      if (r.status === "merged" && r.branch !== undefined) {
        const mergeResult = await mergeChild(familyBackend, {
          childIssue: r.issue,
          childBranch: r.branch,
        });
        familyHead = mergeResult.familyHead;
      }
      childResults.push(r);
    }

    // ── verify-cmr hook (#293 no-op seam, #296 fills) ──────────────────────────
    // Called at the wave barrier so #296 plugs the per-wave family verify
    // (fail-fast) in here without a spine rewrite.
    await runVerifyCmr();
  }

  return { familyBase, familyHead, children: childResults };
}
