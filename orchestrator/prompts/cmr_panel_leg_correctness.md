# Family CMR panel leg — correctness (Trace–Break–Prove)

This panel leg covers the family integrated CMR **correctness** pass. The runner
dispatched it as a first-class worker (not a
nested CLI inside the judge). Review the assigned clone / focus scope and emit
**prose** correctness evidence on stdout.

## Rules

- Do not call another model/agent CLI, dispatch a panel, or emit runner verdict
  / degradation / retry instructions.
- Content shape is not a gate (ADR 0141): pure prose is legal paper; the judge
  distills anchors and dispositions.

## Lens: Trace–Break–Prove

A finding is a counterexample to claimed behavior, not advice. Style preference,
speculation, and hardening ideas without wrong observable behavior are not
findings.

### 1. Trace

For each material behavior changed by the focus diff, trace a real entry point,
the normal successful path, at least one failure boundary relevant to this
change, and the observable result promised by the authority. Follow shared
types and state across the whole diff — do not stop at the changed line.

### 2. Break

Try to produce a concrete counterexample: choose an input or state allowed by
the authority, follow it through the traced path, and when runnable execute the
narrowest useful probe.

### 3. Prove

Submit only candidates with a concrete counterexample (or an exact
unverifiable gap naming the missing evidence). Stop on coverage of the mapped
surface, not on finding count.

Finish inside one iteration. Clean exit + non-empty review stdout = present.
