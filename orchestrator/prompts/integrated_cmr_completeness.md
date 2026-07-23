# Integrated CMR completeness court

## Task and inputs

Judge the landed completeness review papers for this family. The runner has
already dispatched the panel legs and written `.cmr-focus.md`,
`.cmr-route.json`, and the fix-findings landing referenced by
`$ORCHESTRATOR_FIX_FINDINGS_PATH` when set. Panel papers are available through
that landing's `panelLegTransports`.

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
