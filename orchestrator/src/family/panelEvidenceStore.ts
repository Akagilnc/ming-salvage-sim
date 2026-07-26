import { randomUUID } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { isFileNotFound } from "../fsErrors.js";
import type { FamilyPanelLegEvidence, IntegratedCmrPass } from "./types.js";

export const FAMILY_PANEL_LEG_EVIDENCE_PREFIX = "panel-leg-evidence";

/**
 * Complete durable panel-evidence store shared by production and cold-resume
 * tracers. Missing is empty; filesystem/JSON failures are fail-loud. The
 * evidence body is professional-seat cargo, so this transport store does not
 * interpret or validate its fields (ADR 0062 / 0131).
 */
export class FilePanelEvidenceStore {
  private readonly rename: typeof renameSync;

  constructor(
    private readonly ledgerDir: string,
    ops: { readonly rename?: typeof renameSync } = {},
  ) {
    this.rename = ops.rename ?? renameSync;
  }

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
    const path = this.path(pass);
    const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
    try {
      writeFileSync(
        temporaryPath,
        `${JSON.stringify(evidence, null, 2)}\n`,
        { encoding: "utf8", flag: "wx" },
      );
      this.rename(temporaryPath, path);
    } catch (err) {
      try {
        rmSync(temporaryPath, { force: true });
      } catch (cleanupErr) {
        throw new Error(
          `writeFamilyPanelLegEvidence: failed to clean temporary file ` +
            `${temporaryPath} after write failure — ` +
            `${cleanupErr instanceof Error ? cleanupErr.message : String(cleanupErr)}`,
          { cause: err },
        );
      }
      throw err;
    }
  }
}
