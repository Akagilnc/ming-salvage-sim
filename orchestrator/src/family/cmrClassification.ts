import { classifyFindings } from "../findings.js";
import { findingIdentityKey } from "../findings.js";
import type { Finding, FindingDisposition } from "../types.js";
import type {
  FamilyModuleContext,
  SourcedModuleDeclaration,
} from "./moduleDeclaration.js";

export type FamilyCmrFindingClassification =
  | "not_converged"
  | "same_module_still_red"
  | "owning_issue_still_red"
  | "accepted_suppressed"
  | "cross_module_defer"
  | "spec_conflict"
  | "infra_failure";

export interface FamilyCmrFindingResult {
  readonly identityKey: string;
  readonly classification: FamilyCmrFindingClassification;
  readonly attribution: {
    readonly method:
      | "child_module_scope"
      | "ambiguous_child_module_scope"
      | "family_module"
      | "missing_module_context"
      | "reviewer_disposition";
    readonly issue?: number;
    readonly module?: string;
    readonly source?: SourcedModuleDeclaration["source"];
  };
  readonly owningIssue?: string;
  readonly missingSurface?: string;
  readonly nextStep?: string;
  readonly targetModule?: string;
  readonly source?: string;
  readonly reason: string;
}

export interface FamilyModuleDeclarationSnapshot {
  readonly module: string;
  readonly moduleScope: ReadonlyArray<string>;
  readonly source: SourcedModuleDeclaration["source"];
  readonly issue?: number;
}

export interface FamilyModuleContextSnapshot {
  readonly currentModules: ReadonlyArray<FamilyModuleDeclarationSnapshot>;
  readonly childModules: ReadonlyArray<FamilyModuleDeclarationSnapshot>;
  readonly fallbackModule?: FamilyModuleDeclarationSnapshot;
  readonly undevelopedModules: ReadonlyArray<FamilyModuleDeclarationSnapshot>;
}

export interface FamilyCmrClassification {
  readonly blocking: ReadonlyArray<Finding>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly dispositions: ReadonlyArray<FindingDisposition>;
  readonly results: ReadonlyArray<FamilyCmrFindingResult>;
  readonly moduleContext: FamilyModuleContextSnapshot;
}

function normalizedModule(value: string): string {
  return value.trim().toLowerCase();
}

function normalizedModuleSlug(value: string): string {
  return normalizedModule(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function targetModuleIsOutsideCurrentModules(
  targetModule: string,
  currentModules: ReadonlySet<string>,
): boolean {
  const targetSlug = normalizedModuleSlug(targetModule);
  if (targetSlug.length === 0) return false;

  for (const currentModule of currentModules) {
    const currentSlug = normalizedModuleSlug(currentModule);
    if (currentSlug.length === 0) continue;
    if (targetSlug === currentSlug) {
      return false;
    }
  }

  return true;
}

function normalizedEvidenceText(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const normalizedContainsCache = new Map<string, RegExp>();

function containsNormalized(haystack: string, needle: string | undefined): boolean {
  const normalizedHaystack = normalizedEvidenceText(haystack);
  const normalizedNeedle = normalizedEvidenceText(needle);
  if (normalizedNeedle.length === 0) return false;
  let re = normalizedContainsCache.get(normalizedNeedle);
  if (re === undefined) {
    const boundary = String.raw`(?:^|[\s/.,:;()[\]])`;
    const tailBoundary = String.raw`(?:$|[\s/.,:;()[\]])`;
    re = new RegExp(`${boundary}${escapeRegExp(normalizedNeedle)}${tailBoundary}`);
    normalizedContainsCache.set(normalizedNeedle, re);
  }
  return re.test(normalizedHaystack);
}

function locationPath(location: string): string {
  const withoutLineColumn = location
    .trim()
    .replace(/:\d+(?::\d+)?(?::[^:/\\]+)?$/, "");
  const withoutSymbol = withoutLineColumn.replace(/:[^:/\\]+$/, "").trim();
  if (/^[A-Za-z]$/.test(withoutSymbol) && /^[A-Za-z]:$/.test(withoutLineColumn)) {
    return `${withoutSymbol}:`;
  }
  return withoutSymbol;
}

function pathMatchesScope(path: string, scope: string): boolean {
  const normalizedPath = path
    .replace(/\\/g, "/")
    .replace(/\/+$/, "")
    .toLowerCase();
  const normalizedScope = scope
    .trim()
    .replace(/\\/g, "/")
    .replace(/\/+$/, "")
    .toLowerCase();
  return (
    normalizedScope.length > 0 &&
    (normalizedPath === normalizedScope ||
      normalizedPath.startsWith(`${normalizedScope}/`))
  );
}

type ChildAttribution =
  | { readonly kind: "matched"; readonly declaration: SourcedModuleDeclaration }
  | { readonly kind: "ambiguous" }
  | { readonly kind: "none" };

function childAttribution(
  finding: Finding,
  context: FamilyModuleContext,
): ChildAttribution {
  const path = locationPath(finding.location);
  const matches = context.childModules.filter((decl) =>
    decl.moduleScope.some((scope) => pathMatchesScope(path, scope)),
  );
  if (matches.length === 1) return { kind: "matched", declaration: matches[0]! };
  if (matches.length > 1) return { kind: "ambiguous" };
  return { kind: "none" };
}

function declarationCoversFinding(
  declaration: SourcedModuleDeclaration,
  finding: Finding,
): boolean {
  const path = locationPath(finding.location);
  return declaration.moduleScope.some((scope) => pathMatchesScope(path, scope));
}

function fallbackModule(
  context: FamilyModuleContext,
): SourcedModuleDeclaration | undefined {
  return (
    context.fallbackModule ??
    context.currentModules.find((decl) => decl.source !== "child_issue")
  );
}

function attributionFor(
  finding: Finding,
  context: FamilyModuleContext,
): FamilyCmrFindingResult["attribution"] {
  const child = childAttribution(finding, context);
  if (child.kind === "ambiguous") {
    return { method: "ambiguous_child_module_scope" };
  }
  if (child.kind === "matched") {
    const declaration = child.declaration;
    return {
      method: "child_module_scope",
      issue: declaration.issue,
      module: declaration.module,
      source: declaration.source,
    };
  }
  const fallback = fallbackModule(context);
  const path = locationPath(finding.location);
  if (
    fallback !== undefined &&
    fallback.moduleScope.some((scope) => pathMatchesScope(path, scope))
  ) {
    return {
      method: "family_module",
      issue: fallback.issue,
      module: fallback.module,
      source: fallback.source,
    };
  }
  return { method: "missing_module_context" };
}

function moduleDeclarationSnapshot(
  declaration: SourcedModuleDeclaration,
): FamilyModuleDeclarationSnapshot {
  return {
    module: declaration.module,
    moduleScope: declaration.moduleScope,
    source: declaration.source,
    ...(declaration.issue !== undefined ? { issue: declaration.issue } : {}),
  };
}

function moduleContextSnapshot(
  context: FamilyModuleContext,
): FamilyModuleContextSnapshot {
  return {
    currentModules: context.currentModules.map(moduleDeclarationSnapshot),
    childModules: context.childModules.map(moduleDeclarationSnapshot),
    ...(context.fallbackModule !== undefined
      ? { fallbackModule: moduleDeclarationSnapshot(context.fallbackModule) }
      : {}),
    undevelopedModules: (context.undevelopedModules ?? []).map(
      moduleDeclarationSnapshot,
    ),
  };
}

function currentModuleNames(context: FamilyModuleContext): ReadonlySet<string> {
  return new Set(context.currentModules.map((decl) => normalizedModule(decl.module)));
}

function declaredUndevelopedTarget(
  targetModule: string | undefined,
  context: FamilyModuleContext,
): SourcedModuleDeclaration | undefined {
  const target = normalizedModule(targetModule ?? "");
  if (target.length === 0) return undefined;
  const targetSlug = normalizedModuleSlug(target);
  return (context.undevelopedModules ?? []).find((decl) => {
    const moduleName = normalizedModule(decl.module);
    const moduleSlug = normalizedModuleSlug(decl.module);
    return (
      target === moduleName ||
      targetSlug === moduleSlug ||
      decl.moduleScope.some((scope) => containsNormalized(scope, target))
    );
  });
}

function suppressionScopeMatchesContext(input: {
  readonly finding: Finding;
  readonly context: FamilyModuleContext;
  readonly scope?: string;
}): boolean {
  const child = childAttribution(input.finding, input.context);
  if (child.kind === "ambiguous") return false;
  const fallback = fallbackModule(input.context);
  const attributedDeclaration =
    (child.kind === "matched" ? child.declaration : undefined) ??
    (fallback !== undefined && declarationCoversFinding(fallback, input.finding)
      ? fallback
      : undefined);
  if (attributedDeclaration === undefined) return false;

  const scope = normalizedEvidenceText(input.scope);
  if (containsNormalized(scope, attributedDeclaration.module)) return true;
  if (
    attributedDeclaration.issue !== undefined &&
    containsNormalized(scope, `#${attributedDeclaration.issue}`)
  ) {
    return true;
  }

  return attributedDeclaration.moduleScope.some((moduleScope) =>
    containsNormalized(scope, moduleScope),
  );
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
  const dispositionIdentity =
    disposition.findingIdentity ?? findingIdentityKey(finding);
  const matchingSource = (context.acceptedSuppressionSources ?? []).find(
    (source) =>
      source.source === disposition.source &&
      source.scope === disposition.scope &&
      source.findingIdentity === dispositionIdentity &&
      source.boundedReopen === disposition.boundedReopen &&
      source.reason === disposition.reason,
  );
  if (matchingSource === undefined) return false;
  return (
    dispositionIdentity === findingIdentityKey(finding) &&
    suppressionScopeMatchesContext({
      finding,
      context,
      scope: matchingSource.scope,
    })
  );
}

function priorDispositionMatchesContext(
  finding: Finding,
  disposition: FindingDisposition,
  context: FamilyModuleContext,
): boolean {
  if (disposition.status !== "accepted_suppressed") return true;
  const matchingSource = (context.acceptedSuppressionSources ?? []).find(
    (source) =>
      source.source === disposition.source &&
      source.scope === disposition.scope &&
      source.findingIdentity === disposition.identityKey &&
      source.boundedReopen === disposition.boundedReopen &&
      source.reason === disposition.reason,
  );
  if (matchingSource === undefined) return false;
  return (
    disposition.identityKey === findingIdentityKey(finding) &&
    suppressionScopeMatchesContext({
      finding,
      context,
      scope: matchingSource.scope,
    })
  );
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
        : disposition?.kind === "infra_failure"
          ? "infra_failure"
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
    ...(disposition?.kind === "owning_issue_still_red" &&
    disposition.missingSurface !== undefined
      ? { missingSurface: disposition.missingSurface }
      : {}),
    ...(disposition?.kind === "owning_issue_still_red" &&
    disposition.nextStep !== undefined
      ? { nextStep: disposition.nextStep }
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
      const attribution = attributionFor(finding, input.moduleContext);
      const targetModule = normalizedModule(finding.disposition.targetModule ?? "");
      const undevelopedTarget = declaredUndevelopedTarget(
        finding.disposition.targetModule,
        input.moduleContext,
      );
      const findingIsInsideUndevelopedTarget =
        undevelopedTarget !== undefined &&
        declarationCoversFinding(undevelopedTarget, finding);
      if (
        undevelopedTarget !== undefined &&
        currentModules.size > 0 &&
        !currentModules.has(targetModule) &&
        targetModuleIsOutsideCurrentModules(targetModule, currentModules) &&
        (attribution.method !== "missing_module_context" ||
          findingIsInsideUndevelopedTarget)
      ) {
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
    const single = classifyFindings([finding], scopedPriorDispositions, {
      acceptedSuppressionSources: input.moduleContext.acceptedSuppressionSources,
    });
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
  const finalClassification = classifyFindings(
    findingsForFinalClassification,
    [...scopedPriorDispositions, ...seededDispositions],
    { acceptedSuppressionSources: input.moduleContext.acceptedSuppressionSources },
  );
  return {
    blocking,
    deferred,
    dispositions: finalClassification.dispositions,
    results,
    moduleContext: moduleContextSnapshot(input.moduleContext),
  };
}
