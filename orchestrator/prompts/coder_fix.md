# Coder fix worker entrypoint

## Runtime inputs

- `ORCHESTRATOR_ISSUE_NUMBER` / `ISSUE_NUMBER`, `ORCHESTRATOR_REPO`
- `.orchestrator-fix-findings.json`
- `ORCHESTRATOR_RELAY_BRIEF`

## Result transport

- Sidecar path: `ORCHESTRATOR_OUTCOME_PATH`
- Typed station receipt: `<coder>`
- Contract truth:
  `orchestrator/src/stationReceiptContracts.ts`
  (`coderStationReceiptSchema` / `decodeCoderEnvelope`)
