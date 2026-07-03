import { findingIdentityKey } from "../findings.js";
import type { FamilyCmrClassification } from "./cmrClassification.js";

export function fixableCmrFindingKeysFromClassification(
  classification: FamilyCmrClassification,
): readonly string[] | undefined {
  if (classification.blocking.length === 0) return undefined;
  if (classification.blocking.some((finding) => finding.action !== "fix_now")) {
    return undefined;
  }
  const blockingKeys = classification.blocking.map((finding) =>
    findingIdentityKey(finding),
  );
  const resultsByKey = new Map(
    classification.results.map((result) => [result.identityKey, result]),
  );
  for (const key of blockingKeys) {
    const result = resultsByKey.get(key);
    if (result?.classification !== "same_module_still_red") {
      return undefined;
    }
  }
  return [...new Set(blockingKeys)];
}
