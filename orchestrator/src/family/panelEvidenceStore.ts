import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { isFileNotFound } from "../fsErrors.js";
import type {
  FamilyPanelLegEvidence,
  IntegratedCmrPass,
} from "./types.js";

export const FAMILY_PANEL_LEG_EVIDENCE_PREFIX = "panel-leg-evidence";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function assertPanelEvidenceCargo(
  parsed: Record<string, unknown>,
  path: string,
): void {
  const transports = parsed.panelLegTransports;
  if (transports !== undefined) {
    if (!Array.isArray(transports)) {
      throw new Error(
        `readFamilyPanelLegEvidence: invalid panel evidence cargo at ${path} — ` +
          "panelLegTransports must be an array",
      );
    }
    for (const [index, transport] of transports.entries()) {
      if (
        !isRecord(transport) ||
        !isNonEmptyString(transport.slug) ||
        typeof transport.exitCode !== "number" ||
        !Number.isFinite(transport.exitCode) ||
        !("stdout" in transport) ||
        (typeof transport.stdout !== "string" && transport.stdout !== null)
      ) {
        throw new Error(
          `readFamilyPanelLegEvidence: invalid panel evidence cargo at ${path} — ` +
            `panelLegTransports.${index} requires non-empty slug, finite ` +
            "exitCode, and verbatim string|null stdout",
        );
      }
    }
  }

  const skippedLegs = parsed.panelLegSkippedLegs;
  if (skippedLegs !== undefined) {
    if (!Array.isArray(skippedLegs)) {
      throw new Error(
        `readFamilyPanelLegEvidence: invalid panel evidence cargo at ${path} — ` +
          "panelLegSkippedLegs must be an array",
      );
    }
    for (const [index, skippedLeg] of skippedLegs.entries()) {
      if (
        !isRecord(skippedLeg) ||
        !isNonEmptyString(skippedLeg.slug) ||
        !isNonEmptyString(skippedLeg.reason)
      ) {
        throw new Error(
          `readFamilyPanelLegEvidence: invalid panel evidence cargo at ${path} — ` +
            `panelLegSkippedLegs.${index} requires non-empty slug and reason`,
        );
      }
    }
  }
}

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
    assertPanelEvidenceCargo(parsed as Record<string, unknown>, path);
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
