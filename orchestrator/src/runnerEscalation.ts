import type { Escalation } from "./types.js";

const RUNNER_SYNTHESIZED_FAILURE: unique symbol = Symbol(
  "runner-synthesized-failure",
);

/** Host-only failure marker. A worker JSON receipt cannot serialize this key. */
export type RunnerSynthesizedFailureEscalation = Escalation & {
  readonly [RUNNER_SYNTHESIZED_FAILURE]: true;
};

export function runnerSynthesizedFailureEscalation(
  escalation: Escalation,
): RunnerSynthesizedFailureEscalation {
  return {
    ...escalation,
    [RUNNER_SYNTHESIZED_FAILURE]: true,
  };
}

export function isRunnerSynthesizedFailureEscalation(
  escalation: Escalation,
): escalation is RunnerSynthesizedFailureEscalation {
  return RUNNER_SYNTHESIZED_FAILURE in escalation;
}
