# Worker outcome rewrite entrypoint

Read the output protocol first (live-mounted):

```text
/home/agent/.orchestrator/souls/output_protocol.md
```

You are resuming the same worker session only to repair its terminal control
envelope. The runner already has the worker's artifacts and local memory; do not
run semantic review, do not fix code, do not create commits, do not rerun CMR,
and do not infer a route from prose. Reconstruct the valid worker outcome JSON
from existing artifacts, logs, and memory only.

Runner context:

- worker kind: `{{WORKER_KIND}}`
- CMR pass: `{{CMR_PASS}}`
- rewrite attempt: `{{ATTEMPT}}`
- previous protocol failure: `{{FAILURE_REASON}}`
- completion signal: `{{COMPLETION_SIGNAL}}`

When `$ORCHESTRATOR_OUTCOME_PATH` is set, write a draft JSON file outside tracked
source files, then run the versioned guard:

```bash
orchestrator-outcome-guard \
  --role "cmr" \
  --draft "<draft-json-path>" \
  --outcome "$ORCHESTRATOR_OUTCOME_PATH" \
  --evidence-root "$PWD" \
  --completion-signal "{{COMPLETION_SIGNAL}}"
```

Let the guard emit the compatibility `<cmr>` tag and completion signal. If the
guard fails, fix only the draft outcome shape and rerun the guard.
