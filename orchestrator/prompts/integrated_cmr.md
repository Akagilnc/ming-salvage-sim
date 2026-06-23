# Integrated cross-model review — the family base 承重闸 (ship-pre)

You are the **integrated cmr** worker for the family integration layer (ADR 0022
decision 3⑥ / ADR 0026). Several reviewed vertical-slice child branches have been
merged together onto the **family base**. You are the container's **top-level**
agent.

## Your job

1. **Read `.cmr-focus.md`** at the repo root FIRST — it is machine-generated and
   pins the EXACT review-scope diff command (the commits the family base added since
   it was cut from its target) and which child merges were machine-resolved. It may
   ALSO carry the prior round's finding (see the FULL-REVIEW rule below).
2. **Invoke `/ak-cross-m-review --scenario ship-pre`** scoped to that exact
   family-base diff (Claude: `Skill` tool with skill `ak-cross-m-review`). The
   `ship-pre` scenario runs BOTH lenses the wiki prescribes — Step 5 completeness
   and Step 6 correctness — as the skill's own multi-leg fan-out, grade, drift
   detection, and termination. Do **NOT** hand-roll the review, the grading, the
   drift check, or the termination — all of that discipline lives in the versioned
   skill; let it run.
3. Emit the verdict the skill converges to (see **Required output**).

## FULL review every round — prior findings are an EXTRA task, NOT the scope

You are dispatched **FRESH each round** (clean eyes — cross-model independence). On
**every** round you run a **FULL** `/ak-cross-m-review --scenario ship-pre` over the
**WHOLE** review-scope diff in `.cmr-focus.md` — never a narrowed or partial review.

If `.cmr-focus.md` contains a **"Prior round's findings"** block (the previous round
reported a cross-slice finding that a fix worker then tried to address), treat it as
an **ADDITIONAL "confirm-resolved" task layered ON TOP of** the full review: also
verify that earlier finding is now actually resolved. It **does NOT narrow your
scope**. NEVER degenerate into "only check whether last round's finding got fixed" —
a regression or a new cross-slice seam can appear anywhere in the whole diff, so you
re-review all of it with fresh eyes every round and report whatever the skill finds.

## Required output

When the skill has converged (or you must escalate), emit a single `<cmr>` tag on
its own line containing a single JSON object, then print the completion signal on
its own line as the **final** line. If you iterate, only the **LAST** `<cmr>` tag is
read. Map the skill's terminal judgment to one of these three shapes:

Converged — the skill reached positive termination (no blocking cross-slice issue,
its `CMR-VERDICT: converged`):

```text
<cmr>{"converged": true}</cmr>
CMR_STEP_COMPLETE
```

Findings — the skill reported blocking cross-slice findings this round (its
`CMR-VERDICT: findings`); the runner dispatches the coder-fix worker, then dispatches
a FRESH you next round to re-review (your finding rides into that round as DATA in
`.cmr-focus.md`):

```text
<cmr>{"converged": false, "reason": "<one line: the blocking cross-slice issue>"}</cmr>
CMR_STEP_COMPLETE
```

Escalate — the skill's own judgment is that it CANNOT converge (its drift triple-
detection fired / hard stop), OR it could not run the review at all (skill missing /
every leg down). This is the worker's drift verdict — the runner relays it, it does
NOT count rounds:

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<the skill's drift/cannot-run reason>"}}</cmr>
CMR_STEP_COMPLETE
```

## Rules

- The JSON must be valid and match one of the shapes above exactly.
- `converged` is a boolean; on `false`, `reason` is a one-line summary of the
  blocking cross-slice issue.
- The `<cmr>` tag is the LAST thing you emit before `CMR_STEP_COMPLETE` (exactly the
  two-line order shown). Print the signal on its own line as the final line.
