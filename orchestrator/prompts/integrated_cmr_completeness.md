# Integrated CMR completeness court

## Task and inputs

Judge the current completeness court round for this family. Read the
fix-findings landing referenced by `$ORCHESTRATOR_FIX_FINDINGS_PATH` when set.
A typed `builderBeat` means this is the builder-receipt round: no panel paper is
expected, and an empty generation tombstone is not paper. Otherwise this is a
panel round; the runner has dispatched the panel legs (or recorded
producer-authored runtime skip reasons), with papers in `panelLegTransports`.
The runner also writes `.cmr-focus.md` and `.cmr-route.json`.

## Pass scope

Run only the completeness pass: decide whether the family base contains every
required slice surface and whether any slice was structurally swallowed before
correctness review. Do not perform the correctness pass here.

## Output

Return the official judge receipt and optional sidecar defined by the active
judge contract. The runner routes only that typed receipt. Always emit the
official `<judge>` receipt, including when
`$ORCHESTRATOR_OUTCOME_PATH` is set.

This is a single-iteration seat. Finish with a clean exit and a legal typed
receipt/sidecar; do not emit a STEP_COMPLETE password.
