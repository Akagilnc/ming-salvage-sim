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
import { assertAcyclic, selectWave } from "./commander.js";
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
    // #294 (ADR 0022 decision 6③): hand the child its ledger-merged blockers so
    // its OWN single-slice S0 `blocked_by` gate uses the ledger-merged口径, not
    // GitHub `closed`. runChild only runs a child the commander released — i.e.
    // selectWave already confirmed every `child.blockedBy` is in the merged set —
    // so the whole `child.blockedBy` IS the set of family-base-merged blockers
    // for this child. Passing it makes the child's S0 treat a still-open-on-GitHub
    // blocker as satisfied, so a just-released child is not re-rejected (the agy R2
    // deadlock). A truly-open external blocker (not in child.blockedBy) is absent
    // here, so the child S0 still rejects it.
    family: {
      parentIssue,
      familyBase,
      noPush: true,
      mergedBlockers: child.blockedBy,
    },
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
  // ── #294: fail-closed cycle guard (ADR 0022 decisions 3①/4) ────────────────
  // BEFORE any scheduling: validate the children's intra-family `blocked_by`
  // graph is acyclic. A cycle makes selectWave return an empty wave forever (a
  // SILENT deadlock — the members never unblock), so the commander throws a
  // DependencyCycleError here and runFamily fails closed (the caller escalates to
  // a human per decision 4, who fixes the to-issues edges and re-runs). This runs
  // up front so nothing is fanned out / merged before the deadlock is caught.
  assertAcyclic(epic.children);
  // The verify-cmr hook: the injected impl (#296 / tests) or the #293 no-op module
  // default. The spine's call sites + fail-fast on `ok===false` are identical
  // either way (ADR 0022 decision 3④/⑤/⑥; acceptance-4 seam boundary).
  const verifyCmr = input.verifyCmr ?? runVerifyCmr;
  const childResults: FamilyChildResult[] = [];
  let familyHead: string | undefined;

  // Build the family result, accounting for EVERY epic child, and deriving an
  // HONEST family status (decision 3⑤ "不静默吞" — the result must not silently
  // look like success):
  //
  //   - every epic child gets a record. A child not run this invocation is
  //     LEDGER-AWARE: if it has a `merged` ledger entry (e.g. merged in a prior
  //     invocation — #298's resume truth), it is `"merged"` (per the
  //     FamilyChildStatus contract: "merged" ⇔ a merged ledger entry exists), NOT
  //     `"skipped"`. Only a child absent from BOTH this run's results AND the
  //     merged ledger (a blocker never merged / a fail-fast wave aborted before
  //     it ran) is `"skipped"`.
  //   - `status` is the verify outcome ONLY when a barrier was red
  //     (`verify_failed`, the most urgent). Otherwise the run is `"success"` iff
  //     EVERY child is merged, else `"incomplete"` (a child `failed`/`skipped` —
  //     the run did not fully close; the caller must not treat it as shippable).
  //
  // #293's happy path (all independent children merge, no-op verify passes) is
  // always `"success"`; the `incomplete`/`verify_failed`/ledger-merged branches
  // guard honesty for the failure + #294/#298 paths.
  const finalize = async (
    verifyFailedPhase?: VerifyCmrPhase,
  ): Promise<FamilyRunResult> => {
    const recorded = new Set(childResults.map((c) => c.issue));
    const ledgerMerged = await currentMerged(familyBackend);
    const extra: FamilyChildResult[] = epic.children
      .filter((c) => !recorded.has(c.issue))
      .map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "merged" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
    const children = [...childResults, ...extra];
    const status: FamilyRunStatus =
      verifyFailedPhase !== undefined
        ? "verify_failed"
        : children.every((c) => c.status === "merged")
          ? "success"
          : "incomplete";
    return {
      status,
      ...(verifyFailedPhase !== undefined ? { failedPhase: verifyFailedPhase } : {}),
      familyBase,
      familyHead,
      children,
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
      // not yet run are recorded "skipped"/"merged" by finalize(); the run is
      // observably `verify_failed` at the "wave" phase (NOT an indistinguishable
      // success).
      return await finalize("wave");
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
    return await finalize("final");
  }

  // Every barrier passed. finalize() derives "success" only if EVERY child
  // merged, else "incomplete" (a child failed / stayed blocked — not shippable).
  return await finalize();
}
