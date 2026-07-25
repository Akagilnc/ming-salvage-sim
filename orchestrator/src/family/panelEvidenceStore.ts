import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { isFileNotFound } from "../fsErrors.js";
import type {
  FamilyPanelLegEvidence,
  IntegratedCmrPass,
} from "./types.js";

export const FAMILY_PANEL_LEG_EVIDENCE_PREFIX = "panel-leg-evidence";

/**
 * Complete durable panel-evidence store shared by production and cold-resume
 * tracers. Missing is empty; every other read/parse failure is fail-loud.
 */
export class FilePanelEvidenceStore {
  constructor(private readonly ledgerDir: string) {}

  path(pass: IntegratedCmrPass): string {
    return join(
      this.ledgerDir,
      `${FAMILY_PANEL_LEG_EVIDENCE_PREFIX}-${pass}.json`,
    );
  }

  read(pass: IntegratedCmrPass): FamilyPanelLegEvidence | undefined {
    const path = this.path(pass);
    let raw: string;
    try {
      raw = readFileSync(path, "utf8");
    } catch (err) {
      if (isFileNotFound(err)) return undefined;
      throw new Error(
        `readFamilyPanelLegEvidence: failed to read ${path} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw) as unknown;
    } catch (err) {
      throw new Error(
        `readFamilyPanelLegEvidence: invalid JSON at ${path} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`readFamilyPanelLegEvidence: expected object at ${path}`);
    }
    return parsed as FamilyPanelLegEvidence;
  }

  write(
    pass: IntegratedCmrPass,
    evidence: FamilyPanelLegEvidence,
  ): void {
    mkdirSync(this.ledgerDir, { recursive: true });
    writeFileSync(this.path(pass), `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  }
}
