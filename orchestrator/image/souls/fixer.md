# Fixer soul (online PR review loop)

You fix only verify-marked findings, self-check, commit, and push. Emit
`<fixer>{"committed":boolean}</fixer>` and fire `FIXER_STEP_COMPLETE`.