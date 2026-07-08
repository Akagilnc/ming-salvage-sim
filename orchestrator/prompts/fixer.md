# Online review fixer worker (#600)

Soul: `fixer` (`/home/agent/.orchestrator/souls/fixer.md`)

## Params

- `.orchestrator-online-review.json` — bot snapshot + `fixMarkedFindingIdentityKeys` from the prior verify worker.

## Output

Emit `<fixer>` JSON and fire `FIXER_STEP_COMPLETE`:

```json
{"committed": true}
```

or `{"committed": false}` when nothing to fix.