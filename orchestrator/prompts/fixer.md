# Online review fixer worker (#600)

You act only on **fix-marked** findings from the prior verify worker. Run a
same-class-bug scan and regression self-check, then commit fixes and push so bots
can re-review.

## Inputs

- `.orchestrator-online-review.json` — bot snapshot + round metadata.
- Fix only findings the verify worker marked for repair (identity keys in landing).

## Output

Emit `<fixer>` JSON:

```json
{"committed": true}
```

when you committed and pushed fixes, or `{"committed": false}` when nothing to fix.

Fire `FIXER_STEP_COMPLETE` when done.