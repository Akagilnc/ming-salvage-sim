# Worker output protocol

When `ORCHESTRATOR_OUTCOME_PATH` is set, write the prompt-specified terminal JSON
object directly to that path. Compatibility tags and completion signals are
optional telemetry; the runner consumes the process exit code, the typed outcome,
and any role-specific sentinel required by the prompt.
