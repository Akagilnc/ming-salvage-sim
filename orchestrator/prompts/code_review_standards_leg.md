# Per-slice Standards-axis review leg

Issue: `$ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`) in `$ORCHESTRATOR_REPO`.
Fixed point: `$ORCHESTRATOR_REVIEW_FIXED_POINT`. Confirm it resolves
(`git rev-parse`), then review the three-dot range
`$ORCHESTRATOR_REVIEW_FIXED_POINT...HEAD` (and
`git log $ORCHESTRATOR_REVIEW_FIXED_POINT..HEAD --oneline`).

Task: Standards axis only — does the code conform to this repo's documented
coding standards? Report per file/hunk (a) every documented-standard breach
(cite file + rule) and (b) any baseline smell below (name it; quote the hunk).
Documented repo standards override the baseline. Baseline smells are judgement
calls. Skip anything tooling already enforces. Under 400 words. Emit non-empty
prose on stdout for the resident judge.

Do not invoke `/code-review`. Do not spawn nested agents or review legs.
Do not emit runner verdict, degradation, retry, or repair instructions.

## Smell baseline (Standards only)

- Mysterious Name — rename; if no honest name, design is murky.
- Duplicated Code — extract shared shape; call from both.
- Feature Envy — move method onto the data it envies.
- Data Clumps — bundle travelling fields into one type.
- Primitive Obsession — give the domain concept its own small type.
- Repeated Switches — polymorphism or one shared map.
- Shotgun Surgery — gather what changes together into one module.
- Divergent Change — split so each module changes for one reason.
- Speculative Generality — delete unused abstraction; inline until needed.
- Message Chains — hide `a.b().c().d()` behind one method.
- Middle Man — cut pure delegates; call the real target.
- Refused Bequest — drop inheritance; use composition.
