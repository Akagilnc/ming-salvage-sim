# Worker output protocol

Every worker that receives `ORCHESTRATOR_OUTCOME_PATH` must write its terminal
machine result there before emitting the compatibility tag and completion signal.

The sidecar file must contain only the raw JSON object: no XML-style tag, no
completion signal, and no surrounding prose. After writing it, run:

```bash
python3 -m json.tool "$ORCHESTRATOR_OUTCOME_PATH" >/dev/null
```

If that command fails, rewrite the sidecar and rerun the check. Do not emit the
compatibility tag or completion signal until this parser check succeeds.
