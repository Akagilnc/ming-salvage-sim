/**
 * Test-only ledger fixtures retain the concrete bookkeeping payload selected by
 * their `event`; production's generic LedgerEntry intentionally exposes only
 * common fields.
 */
declare module "../src/types.js" {
  interface LedgerEntry {
    readonly branchHEAD?: string;
    readonly prNumber?: number;
    readonly remoteBranchName?: string;
    readonly mergedHeadOid?: string;
  }
}

export {};
