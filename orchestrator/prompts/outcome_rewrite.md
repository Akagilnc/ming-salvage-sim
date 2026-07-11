# Reviewer findings-count supplement

You are resuming the same reviewer session only to supplement its missing
constitutional count fragment. Do not redo or extend the review, do not fix
code, do not create commits, and do not rewrite the prior outcome JSON.

Runner context:

- worker kind: `{{WORKER_KIND}}`
- CMR pass: `{{CMR_PASS}}`
- rewrite attempt: `{{ATTEMPT}}`
- previous failure: `{{FAILURE_REASON}}`

Emit exactly one line, using the findings already present in your completed
review and no new analysis:

```text
findings = x
```

Replace `x` with the non-negative integer count. Emit nothing else.
