# Worker output protocol

When `ORCHESTRATOR_OUTCOME_PATH` is set, write the prompt-specified terminal JSON
object directly to that path. Compatibility tags and completion signals are
optional telemetry. The runner consumes only three probes: the process exit code,
the presence of an escalation block, and a self-reported count sentinel. The full
typed outcome remains cargo for downstream intelligent workers; workers must still
write the complete receipt required by their prompt.
