# Worker output protocol

The first guarded role is `cmr`. A CMR worker that receives
`ORCHESTRATOR_OUTCOME_PATH` must route its terminal machine result through the
versioned outcome guard before emitting any compatibility tag or completion
signal. Other worker roles keep their prompt-specific sidecar contract until their
role schema is added to the guard.

Write the terminal JSON object to a draft file first, not directly to
`ORCHESTRATOR_OUTCOME_PATH`. Then run the guard with this shape, substituting the
worker role and completion signal from the prompt:

```bash
if [ -n "${ORCHESTRATOR_OUTCOME_PATH:-}" ]; then
  orchestrator-outcome-guard \
    --role "<worker-role>" \
    --draft "<draft-json-path>" \
    --outcome "$ORCHESTRATOR_OUTCOME_PATH" \
    --evidence-root "$PWD" \
    --completion-signal "<COMPLETION_SIGNAL>"
fi
```

If the command fails, read its error, fix the draft, and rerun the guard. The
guard writes the raw sidecar JSON and prints the compatibility tag plus completion
signal only after JSON shape, role schema, required fields, and referenced
evidence paths pass validation.

Do not print the compatibility tag or completion signal yourself when
`ORCHESTRATOR_OUTCOME_PATH` is set; let the guard emit them.
