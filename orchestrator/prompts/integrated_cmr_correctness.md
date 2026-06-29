# Integrated CMR correctness worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/cmr_correctness.md
```

Then follow that soul and the worktree's `CLAUDE.md`. This is the runner-dispatched
step6 correctness gate. The runner only schedules you after step5 completeness has
passed and writes `.cmr-focus.md`; the CMR method lives in the baked soul and skill,
not in this prompt.

## Pass scope

Run only the correctness gate over the complete family base: review behavioral
correctness, cross-slice contracts, and regressions. Do not re-run the completeness
gate in this worker.

## Required output

When the correctness gate has converged (or you must escalate), emit a single
`<cmr>` tag on its own line containing a single JSON object, then print the
completion signal on its own line as the final line.

Converged:

```text
<cmr>{"converged": true}</cmr>
CMR_STEP_COMPLETE
```

Escalation:

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<why the worker cannot converge>"}}</cmr>
CMR_STEP_COMPLETE
```

Rules:

- The JSON must match one of the shapes above exactly.
- Do not emit `{"converged": false}` as a normal outcome.
- Emit the `<cmr>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `CMR_STEP_COMPLETE` on its own line at the very end.
