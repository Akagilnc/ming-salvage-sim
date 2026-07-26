# Integrated CMR correctness court

## Task and inputs

Judge the landed correctness review papers for this family after completeness
has passed. Read the fix-findings landing referenced by
`$ORCHESTRATOR_FIX_FINDINGS_PATH` when set. A typed
`builderBeat: "construct"` means this is the builder-receipt round: no panel
paper is expected, and an empty generation tombstone is not paper. Otherwise
this is a panel round; the runner has
dispatched the panel legs (or recorded producer-authored runtime skip reasons),
with papers in `panelLegTransports`. The runner also writes `.cmr-focus.md` and
`.cmr-route.json`.

## Pass scope

Run only the correctness pass over the complete family base: decide behavioral
correctness, cross-slice contracts, and regressions. Do not repeat the
completeness pass here.

## Output

Return the official judge receipt and optional sidecar defined by the active
judge contract. The runner routes only that typed receipt. Always emit the
official `<judge>` receipt, including when
`$ORCHESTRATOR_OUTCOME_PATH` is set.

This is a single-iteration seat. Finish with a clean exit and a legal typed
receipt/sidecar; do not emit a STEP_COMPLETE password.
