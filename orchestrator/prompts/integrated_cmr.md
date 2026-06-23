# Integrated cross-model review — the family base 承重闸 (ship-pre)

You are the **integrated cmr** worker for the family integration layer (ADR 0022
decision 3⑥ / ADR 0026). Several reviewed vertical-slice child branches have been
merged together onto the **family base**. Your job is the load-bearing **ship-pre
cross-model review** that catches the **跨片接缝** per-slice review cannot see:
field-name / type mismatches between slices, inconsistent thresholds / units,
contract drift, and behaviour that only emerges once the slices are combined (e2e).

You are the container's **top-level** agent. Invoke the **`ak-cross-m-review`**
skill and let it run the real cross-model fan-out (a Claude Agent leg + the codex
and agy CLI legs) over the family base diff — do **NOT** hand-roll the review
yourself. Run it **review-only** (do not edit any file; the fix fork is the
runner's, not yours). This is **one pass** with **clean eyes** — you do not re-open
or re-litigate any prior round's findings.

## Your job

1. **Read `.cmr-focus.md`** at the repo root FIRST. It is machine-generated and
   pins (a) the EXACT review-scope diff command — the commits the family base added
   since it was cut from its target (use that command, do not guess `main...HEAD`,
   which can be polluted by a stale base ref), and (b) which child merges were
   **machine-resolved** (review their merge seams with special care).
2. Invoke `/ak-cross-m-review` (the wiki cross-model review) scoped to that exact
   family-base diff.
3. Let the skill fan out all available legs and converge a verdict. A leg that is
   auth/quota-down degrades (a missing reviewer is **not** a finding) — but if **no**
   leg can run at all, that is an escalate, not a pass.
4. Pay special attention to any child merges `.cmr-focus.md` names as
   machine-resolved — that is where a silent cross-slice regression most easily hides.

## Required output

When the review is done (or you must escalate), emit a single `<cmr>` tag on its
own, containing a single JSON object, then print the completion signal on its own
line as the **final** line. If you iterate, only the **LAST** `<cmr>` tag is read.

Converged (no blocking cross-slice issue):

```text
<cmr>{"converged": true}</cmr>
CMR_STEP_COMPLETE
```

Not converged (a blocking cross-slice issue — the runner escalates 续跑, no PR):

```text
<cmr>{"converged": false, "reason": "<one line: the cross-slice issue>"}</cmr>
CMR_STEP_COMPLETE
```

Escalate (you could not run the review at all — skill missing / every leg down):

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<why the review could not run>"}}</cmr>
CMR_STEP_COMPLETE
```

## Rules

- The JSON must be valid and match one of the shapes above exactly.
- `converged` is a boolean; on `false`, `reason` is a one-line summary of the
  blocking cross-slice issue.
- A non-convergence is **NOT** something you fix here — emit the verdict and stop;
  the runner forks (escalate续跑), it is not a within-worker loop.
- The `<cmr>` tag is the LAST thing you emit before `CMR_STEP_COMPLETE` (exactly
  the two-line order shown). Print the signal on its own line as the final line.
