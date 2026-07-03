# Worker output protocol

Every worker that receives `ORCHESTRATOR_OUTCOME_PATH` must write its terminal
machine result there before emitting the compatibility tag and completion signal.

The sidecar file must contain only the raw JSON object: no XML-style tag, no
completion signal, and no surrounding prose. After writing it, validate it when
the orchestrator provided a sidecar path:

```bash
if [ -n "${ORCHESTRATOR_OUTCOME_PATH:-}" ]; then
  python3 -c 'import json, sys; obj=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(obj, dict) else 1)' "$ORCHESTRATOR_OUTCOME_PATH" >/dev/null
fi
```

If that command fails, rewrite the sidecar and rerun the check. When the
orchestrator provided `ORCHESTRATOR_OUTCOME_PATH`, do not emit the compatibility
tag or completion signal until this object check succeeds.
