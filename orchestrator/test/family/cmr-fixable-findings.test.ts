import { describe, expect, it } from "vitest";

import { findingIdentityKey } from "../../src/findings.js";
import { fixableCmrFindingKeysFromClassification } from "../../src/family/cmrFixableFindings.js";
import type { FamilyCmrClassification } from "../../src/family/cmrClassification.js";
import type { Finding } from "../../src/types.js";

const FIRST_FINDING: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "first same-module CMR blocker",
  location: "orchestrator/src/family/verifyCmr.ts:first",
  suggested_fix: "fix the first blocker",
  action: "fix_now",
};

const SECOND_FINDING: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "second same-module CMR blocker",
  location: "orchestrator/src/family/verifyCmr.ts:second",
  suggested_fix: "fix the second blocker",
  action: "fix_now",
};

const FIRST_KEY = findingIdentityKey(FIRST_FINDING);
const SECOND_KEY = findingIdentityKey(SECOND_FINDING);

function classificationWithResults(
  resultKeys: readonly string[],
): FamilyCmrClassification {
  return {
    blocking: [FIRST_FINDING, SECOND_FINDING],
    deferred: [],
    dispositions: [],
    results: resultKeys.map((identityKey) => ({
      identityKey,
      classification: "same_module_still_red",
      attribution: { method: "family_module" },
      reason: "same-module blocker",
    })),
    moduleContext: {
      currentModules: [],
      childModules: [],
      undevelopedModules: [],
    },
  };
}

describe("family CMR fixable finding key derivation", () => {
  it("requires every blocking finding to have a same-module classification result", () => {
    expect(
      fixableCmrFindingKeysFromClassification(classificationWithResults([FIRST_KEY])),
    ).toBeUndefined();
  });

  it("returns stable keys when every blocking finding is same-module fix_now", () => {
    expect(
      fixableCmrFindingKeysFromClassification(
        classificationWithResults([FIRST_KEY, SECOND_KEY]),
      ),
    ).toEqual([FIRST_KEY, SECOND_KEY]);
  });
});
