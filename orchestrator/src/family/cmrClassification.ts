import { classifyFindings } from "../findings.js";
import { findingIdentityKey } from "../findings.js";
import type { Finding, FindingDisposition } from "../types.js";

export interface ModuleDeclaration {
  readonly module: string;
  readonly moduleScope: ReadonlyArray<string>;
}

export interface SourcedModuleDeclaration extends ModuleDeclaration {
  readonly source: "child_issue" | "family_issue" | "run_option";
  readonly issue?: number;
}

export interface FamilyModuleContext {
  readonly currentModules: ReadonlyArray<SourcedModuleDeclaration>;
  readonly childModules: ReadonlyArray<SourcedModuleDeclaration>;
}

export function sourcedModuleDeclaration(
  declaration: ModuleDeclaration | undefined,
  source: SourcedModuleDeclaration["source"],
  issue?: number,
): SourcedModuleDeclaration | undefined {
  if (declaration === undefined) return undefined;
  return {
    ...declaration,
    source,
    ...(issue !== undefined ? { issue } : {}),
  };
}

export function buildFamilyModuleContext(input: {
  readonly childModules: ReadonlyArray<SourcedModuleDeclaration | undefined>;
  readonly familyModule?: SourcedModuleDeclaration;
  readonly runOptionModule?: SourcedModuleDeclaration;
}): FamilyModuleContext {
  const childModules = input.childModules.filter(
    (decl): decl is SourcedModuleDeclaration => decl !== undefined,
  );
  const currentModules =
    childModules.length > 0
      ? childModules
      : input.familyModule !== undefined
        ? [input.familyModule]
        : input.runOptionModule !== undefined
          ? [input.runOptionModule]
          : [];
  return { currentModules, childModules };
}

export type FamilyCmrFindingClassification =
  | "not_converged"
  | "same_module_still_red"
  | "owning_issue_still_red"
  | "accepted_suppressed"
  | "cross_module_defer"
  | "spec_conflict";

export interface FamilyCmrFindingResult {
  readonly identityKey: string;
  readonly classification: FamilyCmrFindingClassification;
  readonly attribution: {
    readonly method:
      | "child_module_scope"
      | "family_module"
      | "missing_module_context"
      | "reviewer_disposition"
      | "known_suppression";
    readonly issue?: number;
    readonly module?: string;
    readonly source?: SourcedModuleDeclaration["source"];
  };
  readonly owningIssue?: string;
  readonly targetModule?: string;
  readonly source?: string;
  readonly reason: string;
}

export interface FamilyCmrClassification {
  readonly blocking: ReadonlyArray<Finding>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly dispositions: ReadonlyArray<FindingDisposition>;
  readonly results: ReadonlyArray<FamilyCmrFindingResult>;
}

const MODULE_DECLARATION_HEADING = /^##\s+Module Declaration\s*$/im;

function trimComment(line: string): string {
  const hash = line.indexOf("#");
  return (hash >= 0 ? line.slice(0, hash) : line).trimEnd();
}

function unquoteScalar(value: string): string | undefined {
  const trimmed = value.trim();
  if (trimmed.length === 0) return undefined;
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  if (trimmed.includes("{") || trimmed.includes("}") || trimmed.includes("[")) {
    return undefined;
  }
  return trimmed;
}

function parseModuleDeclarationYaml(yaml: string): ModuleDeclaration | undefined {
  let moduleName: string | undefined;
  const moduleScope: string[] = [];
  let inScope = false;

  for (const rawLine of yaml.split(/\r?\n/)) {
    const line = trimComment(rawLine);
    if (line.trim().length === 0) continue;

    const topLevel = /^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$/.exec(line);
    if (topLevel !== null && !/^\s/.test(line)) {
      const [, key, rawValue] = topLevel;
      if (key !== "module" && key !== "module_scope") return undefined;
      if (key === "module") {
        if (moduleName !== undefined) return undefined;
        moduleName = unquoteScalar(rawValue ?? "");
        if (moduleName === undefined || moduleName.length === 0) return undefined;
        inScope = false;
        continue;
      }
      if ((rawValue ?? "").trim().length > 0) return undefined;
      inScope = true;
      continue;
    }

    if (!inScope) return undefined;
    const item = /^\s*-\s*(.+?)\s*$/.exec(line);
    if (item === null) return undefined;
    const scope = unquoteScalar(item[1] ?? "");
    if (scope === undefined || scope.length === 0) return undefined;
    moduleScope.push(scope);
  }

  if (moduleName === undefined) return undefined;
  return { module: moduleName, moduleScope };
}

/**
 * Parse a family/child issue's structured module declaration.
 *
 * The contract intentionally ignores titles, prose, temporary logs, and any YAML
 * outside the exact `## Module Declaration` section.
 */
export function parseModuleDeclaration(body: string): ModuleDeclaration | undefined {
  const heading = MODULE_DECLARATION_HEADING.exec(body);
  if (heading === null) return undefined;
  const afterHeading = body.slice(heading.index + heading[0].length);
  const fence = /^\s*```(?:ya?ml)\s*\n([\s\S]*?)\n```\s*/i.exec(afterHeading);
  if (fence === null) return undefined;
  return parseModuleDeclarationYaml(fence[1] ?? "");
}

function normalizedModule(value: string): string {
  return value.trim().toLowerCase();
}

function normalizedEvidenceText(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function containsNormalized(haystack: string, needle: string | undefined): boolean {
  const normalizedNeedle = normalizedEvidenceText(needle);
  return normalizedNeedle.length > 0 && haystack.includes(normalizedNeedle);
}

function locationPath(location: string): string {
  return location.split(":", 1)[0]?.trim() ?? location.trim();
}

function pathMatchesScope(path: string, scope: string): boolean {
  const normalizedPath = path.replace(/\\/g, "/");
  const normalizedScope = scope.trim().replace(/\\/g, "/");
  return (
    normalizedScope.length > 0 &&
    (normalizedPath === normalizedScope ||
      normalizedPath.startsWith(`${normalizedScope}/`))
  );
}

function childAttribution(
  finding: Finding,
  context: FamilyModuleContext,
): SourcedModuleDeclaration | undefined {
  const path = locationPath(finding.location);
  const matches = context.childModules.filter((decl) =>
    decl.moduleScope.some((scope) => pathMatchesScope(path, scope)),
  );
  return matches.length === 1 ? matches[0] : undefined;
}

function fallbackModule(
  context: FamilyModuleContext,
): SourcedModuleDeclaration | undefined {
  return context.currentModules[0];
}

function attributionFor(
  finding: Finding,
  context: FamilyModuleContext,
): FamilyCmrFindingResult["attribution"] {
  const child = childAttribution(finding, context);
  if (child !== undefined) {
    return {
      method: "child_module_scope",
      issue: child.issue,
      module: child.module,
      source: child.source,
    };
  }
  const fallback = fallbackModule(context);
  if (fallback !== undefined) {
    return {
      method: "family_module",
      issue: fallback.issue,
      module: fallback.module,
      source: fallback.source,
    };
  }
  return { method: "missing_module_context" };
}

function currentModuleNames(context: FamilyModuleContext): ReadonlySet<string> {
  return new Set(context.currentModules.map((decl) => normalizedModule(decl.module)));
}

function hasExplicitSuppressionSource(source: string | undefined): boolean {
  const normalized = normalizedEvidenceText(source);
  return /(^|\s)#\d+\b|\bissue\s+#?\d+\b|\badr\s*0*\d+\b|\buser\b/.test(
    normalized,
  );
}

function suppressionScopeMatchesContext(input: {
  readonly finding: Finding;
  readonly context: FamilyModuleContext;
  readonly scope?: string;
  readonly targetModule?: string;
}): boolean {
  const attribution = attributionFor(input.finding, input.context);
  if (attribution.method === "missing_module_context") return false;

  const scope = normalizedEvidenceText(input.scope);
  const targetModule = normalizedModule(input.targetModule ?? "");
  const currentModules = currentModuleNames(input.context);
  if (targetModule.length > 0 && currentModules.has(targetModule)) {
    return true;
  }

  if (containsNormalized(scope, attribution.module)) return true;
  if (
    attribution.issue !== undefined &&
    scope.includes(`#${attribution.issue}`)
  ) {
    return true;
  }

  return input.context.currentModules.some((decl) => {
    if (containsNormalized(scope, decl.module)) return true;
    if (decl.issue !== undefined && scope.includes(`#${decl.issue}`)) return true;
    return decl.moduleScope.some((moduleScope) =>
      containsNormalized(scope, moduleScope),
    );
  });
}

function acceptedSuppressionFindingMatchesContext(
  finding: Finding,
  context: FamilyModuleContext,
): boolean {
  if (
    finding.disposition?.kind !== "accepted_suppressed" ||
    (finding.action !== "wont_fix" && finding.action !== "rejected")
  ) {
    return true;
  }
  const disposition = finding.disposition;
  return (
    disposition.findingIdentity === findingIdentityKey(finding) &&
    hasExplicitSuppressionSource(disposition.source) &&
    suppressionScopeMatchesContext({
      finding,
      context,
      scope: disposition.scope,
      targetModule: disposition.targetModule,
    })
  );
}

function priorDispositionMatchesContext(
  finding: Finding,
  disposition: FindingDisposition,
  context: FamilyModuleContext,
): boolean {
  if (disposition.status !== "accepted_suppressed") return true;
  return (
    disposition.identityKey === findingIdentityKey(finding) &&
    hasExplicitSuppressionSource(disposition.source) &&
    suppressionScopeMatchesContext({
      finding,
      context,
      scope: disposition.scope,
      targetModule: disposition.targetModule,
    })
  );
}

const SEVERITY_RANK: Readonly<Record<Finding["severity"], number>> = {
  clarity: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

const KNOWN_287_HUB_LOSS_ACCEPTED_SEVERITY: Finding["severity"] = "medium";

function exceedsKnown287HubLossAcceptedSeverity(finding: Finding): boolean {
  return (
    SEVERITY_RANK[finding.severity] >
    SEVERITY_RANK[KNOWN_287_HUB_LOSS_ACCEPTED_SEVERITY]
  );
}

function isKnown287HubLossFinding(familyIssue: number, finding: Finding): boolean {
  if (familyIssue !== 287) return false;
  const text = `${finding.claim_quote}\n${finding.location}`.toLowerCase();
  if (/(#287[-\s]?owned|local integration|stub contract)/i.test(text)) {
    return false;
  }
  return (
    /adr0023|d9|transport[-\s]?loss|central\s+c_?\s+accounts|hub oracle|adr0021/i.test(
      text,
    ) && /hub|adr0021|transport[-\s]?loss|central\s+c_?\s+accounts/i.test(text)
  );
}

function acceptedSuppressionDisposition(finding: Finding): FindingDisposition {
  return {
    identityKey: findingIdentityKey(finding),
    status: "accepted_suppressed",
    reason:
      "#287 ADR0023 D9 central transport-loss C_ accounts are accepted as #261/ADR0021 hub implementation scope",
    severity: finding.severity,
    reopenAttempts: 0,
    source: "#303",
    scope: "#287 hub-loss / central C_ accounts finding only; not #287 local integration or stub-contract failures",
    targetModule: "#261/ADR0021 hub implementation",
    boundedReopen:
      "reopen if severity escalates, new evidence changes the scope, or the finding targets #287-owned local integration/stub contract behavior",
  };
}

function resultForBlocking(
  finding: Finding,
  context: FamilyModuleContext,
): FamilyCmrFindingResult {
  const attribution = attributionFor(finding, context);
  const disposition = finding.disposition;
  const classification: FamilyCmrFindingClassification =
    disposition?.kind === "owning_issue_still_red"
      ? "owning_issue_still_red"
      : disposition?.kind === "spec_conflict"
        ? "spec_conflict"
        : "same_module_still_red";
  return {
    identityKey: findingIdentityKey(finding),
    classification,
    attribution,
    ...(disposition?.kind === "owning_issue_still_red"
      ? { owningIssue: disposition.owningIssue }
      : attribution.issue !== undefined
        ? { owningIssue: `#${attribution.issue}` }
        : {}),
    ...(disposition?.targetModule !== undefined
      ? { targetModule: disposition.targetModule }
      : {}),
    ...(disposition?.source !== undefined ? { source: disposition.source } : {}),
    reason: disposition?.reason ?? finding.disposition_reason ?? finding.suggested_fix,
  };
}

function resultForDeferred(
  finding: Finding,
  context: FamilyModuleContext,
): FamilyCmrFindingResult {
  const disposition = finding.disposition;
  return {
    identityKey: findingIdentityKey(finding),
    classification: "cross_module_defer",
    attribution: attributionFor(finding, context),
    targetModule: disposition?.targetModule,
    reason: disposition?.reason ?? finding.suggested_fix,
  };
}

export function classifyFamilyCmrFindings(input: {
  readonly familyIssue: number;
  readonly findings: ReadonlyArray<Finding>;
  readonly moduleContext: FamilyModuleContext;
  readonly priorDispositions?: ReadonlyArray<FindingDisposition>;
}): FamilyCmrClassification {
  const blocking: Finding[] = [];
  const deferred: Finding[] = [];
  const results: FamilyCmrFindingResult[] = [];
  const seededDispositions: FindingDisposition[] = [];
  const findingsForFinalClassification: Finding[] = [];
  const currentModules = currentModuleNames(input.moduleContext);

  for (const finding of input.findings) {
    if (isKnown287HubLossFinding(input.familyIssue, finding)) {
      if (exceedsKnown287HubLossAcceptedSeverity(finding)) {
        blocking.push(finding);
        results.push(resultForBlocking(finding, input.moduleContext));
        continue;
      }

      const disposition = acceptedSuppressionDisposition(finding);
      seededDispositions.push(disposition);
      results.push({
        identityKey: disposition.identityKey,
        classification: "accepted_suppressed",
        attribution: { method: "known_suppression" },
        source: disposition.source,
        targetModule: disposition.targetModule,
        reason: disposition.reason,
      });
      continue;
    }

    if (
      !acceptedSuppressionFindingMatchesContext(finding, input.moduleContext)
    ) {
      blocking.push(finding);
      results.push(resultForBlocking(finding, input.moduleContext));
      continue;
    }

    if (
      finding.action === "defer" &&
      finding.disposition?.kind === "cross_module"
    ) {
      findingsForFinalClassification.push(finding);
      const targetModule = normalizedModule(finding.disposition.targetModule ?? "");
      if (currentModules.size > 0 && !currentModules.has(targetModule)) {
        deferred.push(finding);
        results.push(resultForDeferred(finding, input.moduleContext));
      } else {
        blocking.push(finding);
        results.push(resultForBlocking(finding, input.moduleContext));
      }
      continue;
    }

    const scopedPriorDispositions = (input.priorDispositions ?? []).filter(
      (disposition) =>
        priorDispositionMatchesContext(finding, disposition, input.moduleContext),
    );
    const single = classifyFindings([finding], scopedPriorDispositions);
    findingsForFinalClassification.push(finding);
    if (single.blocking.length > 0) {
      blocking.push(finding);
      results.push(resultForBlocking(finding, input.moduleContext));
    } else if (single.deferred.length > 0) {
      deferred.push(finding);
      results.push(resultForDeferred(finding, input.moduleContext));
    } else {
      results.push({
        identityKey: findingIdentityKey(finding),
        classification: "accepted_suppressed",
        attribution: attributionFor(finding, input.moduleContext),
        ...(finding.disposition?.source !== undefined
          ? { source: finding.disposition.source }
          : {}),
        ...(finding.disposition?.targetModule !== undefined
          ? { targetModule: finding.disposition.targetModule }
          : {}),
        reason: finding.disposition_reason ?? finding.disposition?.reason ?? "",
      });
    }
    seededDispositions.push(...single.dispositions);
  }

  const scopedPriorDispositions = (input.priorDispositions ?? []).filter(
    (disposition) =>
      input.findings.some((finding) =>
        priorDispositionMatchesContext(finding, disposition, input.moduleContext),
      ),
  );
  const finalClassification = classifyFindings(findingsForFinalClassification, [
    ...scopedPriorDispositions,
    ...seededDispositions,
  ]);
  return {
    blocking,
    deferred,
    dispositions: finalClassification.dispositions,
    results,
  };
}
