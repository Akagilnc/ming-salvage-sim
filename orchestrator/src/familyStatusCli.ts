/**
 * #1007 — `npm run status -- <ledgerDir>`
 *
 * Renders family status from progress.jsonl (+ family-ledger.jsonl when present).
 * Zero guessing: empty feed → explicit "no progress events".
 */
import { renderFamilyStatusFromDir } from "./progressBroadcast.js";

function main(argv: readonly string[]): number {
  const ledgerDir = argv[2]?.trim();
  if (ledgerDir === undefined || ledgerDir.length === 0) {
    console.error(
      "usage: npm run status -- <ledgerDir>\n" +
        "  e.g. npm run status -- ~/.sc-orchestrator/family-934-ledger",
    );
    return 2;
  }
  process.stdout.write(renderFamilyStatusFromDir(ledgerDir));
  return 0;
}

process.exitCode = main(process.argv);
