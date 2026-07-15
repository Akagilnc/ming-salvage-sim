# Integrated-cmr soul index (do not execute directly)

The integrated CMR worker is split into two runner-dispatched pass entrypoints.
This file is only a compatibility index for the broad `ORCHESTRATOR_SOUL=cmr`
runtime role; it is not a pass contract.

Pass prompts must read the pass-specific mount paths; both execution souls are
`verify.md` (relative symlinks keep the historical mount names):

- `/home/agent/.orchestrator/souls/cmr_completeness.md` → `verify.md`
- `/home/agent/.orchestrator/souls/cmr_correctness.md` → `verify.md`

If a worker prompt tells you to follow this index as the execution soul, escalate:
the runner/prompt contract is stale and the worker cannot know which pass it is
allowed to run.
