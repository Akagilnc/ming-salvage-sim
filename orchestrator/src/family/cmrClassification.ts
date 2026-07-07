import { classifyFindings } from "../findings.js";
import { findingIdentityKey } from "../findings.js";
import type { Finding, FindingDisposition } from "../types.js";
import type {
  FamilyModuleContext,
  SourcedModuleDeclaration,
} from "./moduleDeclaration.js";

/**
 * #604 slice 4 (ADR 0062): the routing classification values
 * (`same_module_still_red` / `owning_issue_still_red` / `cross_module_defer` /
 * `spec_conflict` / `infra_failure`) were removed along with the reviewer route
 * kinds. A finding is now either `blocking` (fix it and rerun), an
 * `accepted_suppressed` governance carrier, or the synthetic `not_converged`.
 */
export type FamilyCmrFindingClassification =
  | "not_converged"
  | "blocking"
  | "accepted_suppressed";

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

export interface CmrEnvelope {
  readonly blocking: ReadonlyArray<Finding>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly dispositions: ReadonlyArray<FindingDisposition>;
  readonly results: ReadonlyArray<FamilyCmrFindingResult>;
  readonly moduleContext: FamilyModuleContextSnapshot;
}

function normalizedModule(value: string): string {
  return value.trim().toLowerCase();
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
  // #604 slice 4 (ADR 0062): routing disposition kinds are gone, so a blocking
  // finding is never classified by a route kind — every blocking finding lands
  // in the single `blocking` bucket ("fix it and rerun").
  const classification: FamilyCmrFindingClassification = "blocking";
  return {
    identityKey: findingIdentityKey(finding),
    classification,
    attribution,
    ...(attribution.issue !== undefined
      ? { owningIssue: `#${attribution.issue}` }
      : {}),
    ...(disposition?.source !== undefined ? { source: disposition.source } : {}),
    // #604 correctness r1 (P2-c): a blocking finding's `reason` flows into the
    // ledger stopSummary/findingDescriptor. It MUST stay generic / identity-only —
    // `suggested_fix` (and other rich finding text) must NOT驻留 the ledger (F5,
    // ADR 0062); the rich content travels only in the live coder-fix landing
    // payload. So do NOT fall back to `finding.suggested_fix` here.
    reason: "blocking CMR finding requires coder-fix",
  };
}

export function deriveCmrEnvelope(input: {
  readonly familyIssue: number;
  readonly findings: ReadonlyArray<Finding>;
  readonly moduleContext: FamilyModuleContext;
  readonly priorDispositions?: ReadonlyArray<FindingDisposition>;
}): CmrEnvelope {
  const blocking: Finding[] = [];
  const deferred: Finding[] = [];
  const results: FamilyCmrFindingResult[] = [];
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

    // #604 slice 4 (ADR 0062): the `cross_module` routing kind is gone, so there
    // is no longer a cross-module deferred bucket — every non-accepted-suppressed
    // finding falls through to the shared single-finding classifier below, which
    // classifies it as blocking (findings.ts). `deferred` is retained by the
    // return shape but stays empty.

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
      results.push(resultForBlocking(finding, input.moduleContext));
    } else {
      results.push({
        identityKey: findingIdentityKey(finding),
        classification: "accepted_suppressed",
        attribution: attributionFor(finding, input.moduleContext),
        ...(finding.disposition?.source !== undefined
          ? { source: finding.disposition.source }
          : {}),
        reason: finding.disposition_reason ?? finding.disposition?.reason ?? "",
      });
    }
  }

  const scopedPriorDispositions = (input.priorDispositions ?? []).filter(
    (disposition) =>
      input.findings.some((finding) =>
        priorDispositionMatchesContext(finding, disposition, input.moduleContext),
      ),
  );
  // #604 correctness r2 (C1): the final classification's PRIOR input is ONLY the
  // real prior-round dispositions — NEVER this pass's own freshly-generated
  // suppressions. The pre-r2 code seeded the current-pass per-finding
  // dispositions back in as `prior`, so a brand-new suppression looked like a
  // re-submission against itself and was wrongly treated as a repeat round of an
  // already-suppressed finding. `classifyFindings` regenerates each finding's
  // fresh disposition itself, so the seeds were both redundant and harmful. The
  // per-finding pass above stays authoritative for the blocking/deferred/results
  // buckets. (Reopen/dispute budgets are governed by classifyFindings per ADR
  // 0030: a same/lower-severity maintenance re-submission is a zero-op, only an
  // upgrade reopens+blocks and only a real fix_now challenge spends a dispute.)
  const finalClassification = classifyFindings(
    findingsForFinalClassification,
    scopedPriorDispositions,
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
