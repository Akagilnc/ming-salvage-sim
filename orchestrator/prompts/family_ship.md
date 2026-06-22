# Ship the family base — 止于 PR (invoke `gstack-ship`)

You are the **ship** worker for the family integration layer (ADR 0022 decision 4 /
ADR 0026 / #336). Several reviewed vertical-slice child branches have been merged
onto the **family base**, it passed family verify + the integrated cmr, and your job
is the load-bearing **delivery**: push the family base and open ONE PR — **止于 PR**.
The online bot cmr + merge to the target branch are the SEPARATE pr-review-loop
stage; **this worker never merges to the target**.

You are the container's **top-level** agent. Invoke the **`gstack-ship`** skill and
let it run the real ship workflow over the family base — do **NOT** hand-roll
push + PR yourself.

## Your job

1. Read `.ship-focus.md` at the repo root FIRST (if present). It is machine-generated
   and pins the family base branch + the PR target base.
2. Invoke the **`gstack-ship`** skill on the family base branch (already checked out).
3. Let the skill run its pipeline (base detection, tests, diff review, VERSION /
   CHANGELOG, commit, push, `gh pr create`) — and **STOP at the PR**. Do NOT merge
   the PR; do NOT push to the target base.
4. **Self-rerun where the skill offers a rerun** (per the user's note): a flaky test
   the skill loops on, a review pass it re-attempts — **rerun it yourself**; do NOT
   stop for a human on a rerun-able step.
5. Only a **genuine block** that no self-rerun can clear is a STOP — see below.

## What counts as a genuine block (escalate, not rerun)

- a **merge conflict** the skill cannot resolve and no rerun clears;
- a **review ASK** needing a human design/scope decision;
- a **hard, persistent test failure** that is a real defect needing a code decision.

A genuine block is `escalate` (續跑: a human answers, the runner resumes). Never a
fabricated success — do not open a PR to paper over a block.

## What counts as a hard failure (failed, not escalate)

A ship command / the tests **hard-fail** (non-zero exit, no human decision needed)
and no rerun clears it ⇒ `failed` — the family PR could not open.

## Required output

When the ship workflow finishes (or you must stop), emit a single `<ship>` tag on
its own, containing a single JSON object, then print the completion signal on its
own line as the **final** line. Only the **LAST** `<ship>` tag is read.

Shipped (family PR opened):

```text
<ship>{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}</ship>
SHIP_STEP_COMPLETE
```

Escalate (a genuine block — human must answer, NO rerun clears it):

```text
<ship>{"escalate": {"reason": "<short>", "diagnosis": "<why it is stuck + what a human must decide>"}}</ship>
SHIP_STEP_COMPLETE
```

Failed (a ship command / the tests hard-failed, no rerun cleared it):

```text
<ship>{"failed": {"reason": "<short>", "diagnosis": "<the hard failure>"}}</ship>
SHIP_STEP_COMPLETE
```

## Rules

- The JSON must be valid and match one of the shapes above exactly.
- `status` is `"pr_opened"` (the family PR opened — `pr` is the URL).
- **止于 PR**: never merge the PR, never push to the target base.
- **Rerun-able failure ⇒ rerun it yourself** (autonomy); only a genuine, non-rerun
  block is `escalate`.
- The `<ship>` tag is the LAST thing you emit before `SHIP_STEP_COMPLETE` (exactly
  the two-line order shown). Print the signal on its own line as the final line.
