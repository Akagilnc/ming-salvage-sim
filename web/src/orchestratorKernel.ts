export type IssueId = string | number;
export type IssueState = "open" | "closed" | "OPEN" | "CLOSED" | null | undefined;

export interface EpicIssue {
  id: IssueId;
  epicId: IssueId;
  state: IssueState;
}

export interface BlockedByEdge {
  issueId: IssueId;
  blockedByIssueId: IssueId;
}

export interface TopologyInput {
  epicId: IssueId;
  issues: EpicIssue[];
  blockedBy: BlockedByEdge[];
}

export type TopologyPlan =
  | {
      status: "ready";
      layers: IssueId[][];
      skippedClosedIssueIds: IssueId[];
      externalPrerequisites: [];
    }
  | {
      status: "external_prerequisite";
      layers: [];
      skippedClosedIssueIds: IssueId[];
      externalPrerequisites: BlockedByEdge[];
    };

export type TopologyErrorCode = "empty_epic" | "cycle";

export class TopologyError extends Error {
  readonly code: TopologyErrorCode;

  constructor(code: TopologyErrorCode, message: string) {
    super(message);
    this.name = "TopologyError";
    this.code = code;
  }
}

export type FindingClassification = "mechanical_bug" | "choice" | "ambiguous" | string | null | undefined;

export interface Finding {
  id: string;
  classification?: FindingClassification;
  claim_quote?: string;
  claimQuote?: string;
  location?: string;
}

export interface FindingRoute {
  status: "autonomous_repair" | "needs_decision" | "no_findings";
  autonomousBugFindings: Finding[];
  decisionFindings: Finding[];
}

export type FamilyReviewDecision = "converged" | "fix" | "escalate" | "abort";

export interface FamilyReviewGateInput {
  escalateCount: number;
  mechanicalCount: number;
  round: number;
  maxRounds: number;
}

export type ShipOutcome = "ready" | "needs-user" | "unconverged";

export interface ShipOutcomeInput {
  asked: boolean;
  gatesPassed: boolean;
  prCreated: boolean;
}

export interface ContinuationInput {
  layers: IssueId[][]; // the ordered topology layers (this epic's planned layers/slices)
  mergedNumbers: IssueId[]; // slices the family branch already has a commit for (by git state, NOT sub-issue open/close)
  dirty?: IssueId[]; // slices ruled "rework" that touch an already-merged slice -> redo even if a commit exists
}

export interface ContinuationLayer {
  todo: IssueId[]; // slices to run this segment (family branch lacks them OR they are dirty)
  skipped: IssueId[]; // git-skipped slices (merged and not dirty)
  dirty: IssueId[]; // slices in this layer flagged dirty (merged but to be redone; ⊂ todo)
}

export interface ContinuationResult {
  layers: ContinuationLayer[];
  todoTotal: number; // total todo across layers (0 = nothing to do; the whole epic is merged with no dirty)
}

export interface Dismissal {
  id?: string;
  claimQuote?: string;
  claim_quote?: string;
  location?: string;
}

export interface DismissalGateInput {
  finding: Finding;
  dismissed: Dismissal[];
}

export interface ModelReviewResult {
  model: string;
  available: boolean;
  reason?: string;
}

export interface DegradationInput {
  stage: "per_slice" | "family_5a_5b";
  results: ModelReviewResult[];
}

export interface DegradationJudgment {
  status: "continue" | "halt";
  availableModels: string[];
  missingModels: string[];
  flags: string[];
}

const isClosed = (state: IssueState): boolean => state?.toLowerCase() === "closed";
const sameId = (left: IssueId, right: IssueId): boolean => String(left) === String(right);
const idKey = (id: IssueId): string => String(id);
const byIssueIds = (left: BlockedByEdge, right: BlockedByEdge): number =>
  compareIssueKeys(idKey(left.issueId), idKey(right.issueId)) || compareIssueKeys(idKey(left.blockedByIssueId), idKey(right.blockedByIssueId));

export function layerEpicIssues(input: TopologyInput): TopologyPlan {
  const epicChildren = input.issues.filter((issue) => sameId(issue.epicId, input.epicId));
  if (epicChildren.length === 0) {
    throw new TopologyError("empty_epic", `Epic ${input.epicId} has no native sub-issues.`);
  }

  const byKey = new Map(input.issues.map((issue) => [idKey(issue.id), issue]));
  const openChildren = epicChildren.filter((issue) => !isClosed(issue.state));
  const openChildKeys = new Set(openChildren.map((issue) => idKey(issue.id)));
  const skippedClosedIssueIds = epicChildren
    .filter((issue) => isClosed(issue.state))
    .map((issue) => issue.id)
    .sort((left, right) => compareIssueKeys(idKey(left), idKey(right)));

  const externalPrerequisites = input.blockedBy
    .filter((edge) => {
      if (!openChildKeys.has(idKey(edge.issueId))) return false;
      if (openChildKeys.has(idKey(edge.blockedByIssueId))) return false;

      const blocker = byKey.get(idKey(edge.blockedByIssueId));
      return blocker === undefined || !isClosed(blocker.state);
    })
    .sort(byIssueIds);

  if (externalPrerequisites.length > 0) {
    return {
      status: "external_prerequisite",
      layers: [],
      skippedClosedIssueIds,
      externalPrerequisites
    };
  }

  const indegree = new Map<string, number>();
  const issueIdsByKey = new Map<string, IssueId>();
  const dependents = new Map<string, string[]>();

  for (const issue of openChildren) {
    const key = idKey(issue.id);
    indegree.set(key, 0);
    issueIdsByKey.set(key, issue.id);
    dependents.set(key, []);
  }

  for (const edge of input.blockedBy) {
    const issueKey = idKey(edge.issueId);
    const blockerKey = idKey(edge.blockedByIssueId);
    if (!openChildKeys.has(issueKey) || !openChildKeys.has(blockerKey)) continue;

    dependents.get(blockerKey)?.push(issueKey);
    indegree.set(issueKey, (indegree.get(issueKey) ?? 0) + 1);
  }

  const layers: IssueId[][] = [];
  let ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([key]) => key)
    .sort(compareIssueKeys);
  const emitted = new Set<string>();

  while (ready.length > 0) {
    const currentLayerKeys = ready;
    layers.push(currentLayerKeys.map((key) => issueIdsByKey.get(key) as IssueId));

    ready = [];
    for (const key of currentLayerKeys) {
      emitted.add(key);
      const nextKeys = dependents.get(key) ?? [];
      for (const nextKey of nextKeys) {
        const nextDegree = (indegree.get(nextKey) ?? 0) - 1;
        indegree.set(nextKey, nextDegree);
        if (nextDegree === 0) ready.push(nextKey);
      }
    }
    ready.sort(compareIssueKeys);
  }

  if (emitted.size !== openChildren.length) {
    const cycleIssueIds = [...indegree.entries()]
      .filter(([key, degree]) => degree > 0 && !emitted.has(key))
      .map(([key]) => key)
      .sort(compareIssueKeys)
      .join(", ");
    throw new TopologyError("cycle", `Open epic children contain a blocked_by cycle: ${cycleIssueIds}.`);
  }

  return {
    status: "ready",
    layers,
    skippedClosedIssueIds,
    externalPrerequisites: []
  };
}

export function routeFindings(findings: Finding[]): FindingRoute {
  const autonomousBugFindings: Finding[] = [];
  const decisionFindings: Finding[] = [];

  for (const finding of findings) {
    if (finding && finding.classification === "mechanical_bug") {
      autonomousBugFindings.push(finding);
    } else {
      decisionFindings.push(finding);
    }
  }

  if (decisionFindings.length > 0) {
    return { status: "needs_decision", autonomousBugFindings, decisionFindings };
  }
  if (autonomousBugFindings.length > 0) {
    return { status: "autonomous_repair", autonomousBugFindings, decisionFindings };
  }
  return { status: "no_findings", autonomousBugFindings, decisionFindings };
}

// Drives the family 5a/5b cmr loop (I5 routing + I1 abort). Counts come from a
// FindingRoute: escalateCount = decisionFindings.length, mechanicalCount =
// autonomousBugFindings.length. Escalation wins over an autonomous fix even when
// mechanical bugs coexist — a decision finding always returns the run to the
// main session. Only mechanical-only rounds consume the fix budget.
export function familyReviewGate(input: FamilyReviewGateInput): FamilyReviewDecision {
  const { escalateCount, mechanicalCount, round, maxRounds } = input;
  if (escalateCount > 0) return "escalate";
  if (mechanicalCount === 0) return "converged";
  return round < maxRounds ? "fix" : "abort";
}

// Maps a gstack-ship report to the orchestrator's terminal ship state (S5). An internal ASK
// (version-bump MINOR/MAJOR, pre-landing ASK, coverage hard gate) always returns the run to the
// user and is checked first; otherwise the run is ready only when the ship gates passed AND the
// family PR was created — anything else is unconverged.
export function shipOutcome(input: ShipOutcomeInput): ShipOutcome {
  if (input.asked) return "needs-user";
  return input.gatesPassed && input.prCreated ? "ready" : "unconverged";
}

// S6 cross-segment continuation. Skip a slice iff the family branch already has its commit AND it is
// not dirty; run it iff it is missing OR dirty. "Merged" is judged by family-branch git state (passed
// in as mergedNumbers), NOT sub-issue open/close — sub-issues only close on main merge, while the
// family PR is still open. A dirty slice (ruled "rework") is redone even if a commit exists. Membership
// is compared via idKey so a string id and a numeric id for the same slice match.
export function continuationPlan(input: ContinuationInput): ContinuationResult {
  const merged = new Set(input.mergedNumbers.map(idKey));
  const dirtyKeys = new Set((input.dirty ?? []).map(idKey));
  const layers: ContinuationLayer[] = input.layers.map((layer) => {
    const todo: IssueId[] = [];
    const skipped: IssueId[] = [];
    const layerDirty: IssueId[] = [];
    for (const slice of layer) {
      const key = idKey(slice);
      const isDirty = dirtyKeys.has(key);
      if (isDirty) layerDirty.push(slice);
      if (!merged.has(key) || isDirty) todo.push(slice);
      else skipped.push(slice);
    }
    return { todo, skipped, dirty: layerDirty };
  });
  const todoTotal = layers.reduce((sum, layer) => sum + layer.todo.length, 0);
  return { layers, todoTotal };
}

// S6 dismissal gate (I5 false-positive non-loop). A finding the user already ruled "doesn't count"
// (via the main session) is recorded by (id / claim / location) into the dismissal list. This does NOT
// remove it from the next segment's review (the full re-review discipline holds); it only answers
// "if this is re-raised, does it still HALT?" — matched → false (already ruled, don't HALT); unmatched
// → true (route normally, may escalate/HALT). Match on id, claim (claimQuote/claim_quote unified), or
// location — any one (cmr finding ids can drift across segments; claim has two casings).
export function dismissalGate(input: DismissalGateInput): boolean {
  const { finding, dismissed = [] } = input;
  if (!finding) return true; // a null/garbage finding cannot match a dismissal -> not dismissed (still HALT-eligible)
  const findingClaim = claimOf(finding);
  const matched = dismissed.some((entry) => {
    if (entry.id !== undefined && finding.id !== undefined && entry.id === finding.id) return true;
    const entryClaim = claimOf(entry);
    if (entryClaim !== undefined && findingClaim !== undefined && entryClaim === findingClaim) return true;
    if (entry.location !== undefined && finding.location !== undefined && entry.location === finding.location) return true;
    return false;
  });
  return !matched;
}

// Unify a claim's two casings: camelCase claimQuote takes precedence, else snake_case claim_quote
// (the cmr finding JSON's native form). They are synonyms.
function claimOf(value: { claimQuote?: string; claim_quote?: string } | null | undefined): string | undefined {
  if (!value) return undefined;
  return value.claimQuote !== undefined ? value.claimQuote : value.claim_quote;
}

// A merged slice's identity in the handoff: the slice (sub-issue) number and its per-slice REVIEWED
// commit (the stable commit produced by per-slice review in the slice's own worktree). The reviewed
// commit is NOT rewritten by an I10 family rebase / family-review fix (those rewrite the FAMILY
// branch commits), so it is a stable identifier of what each slice contributed. The current family
// branch tip is the top-level handoff `familyHead`; S6 git-skip probes the family branch
// (baseAtStart..familyHead) against these rather than trusting a per-slice family-branch hash.
export interface HandoffMergedSlice {
  number: IssueId;
  reviewedCommit: string;
}

// A dirty slice carries the user's decision text ("rework X") so the next run knows HOW to redo it,
// not just THAT it must (a bare number loses the decision; see I5 dirty vs dismissal).
export interface HandoffDirtySlice {
  number: IssueId;
  decision?: string;
}

export interface HandoffInput {
  status: ShipOutcome; // terminal state: 'ready' | 'needs-user' | 'unconverged'
  epic: IssueId; // parent epic issue
  familyBranch: string; // family branch name
  baseAtStart: string; // base SHA (the I10-verified startup target HEAD)
  familyHead?: string; // current family branch tip (refreshed post rebase / post family-review fix)
  merged?: HandoffMergedSlice[]; // merged slices + their stable per-slice reviewed commits
  dirty?: HandoffDirtySlice[]; // dirty slices not yet reworked (I5)
  flags?: string[]; // degradation / absent-voice flags from the load-bearing family gate
  prUrl?: string; // ready: the family PR gstack-ship created
  question?: string; // needs-user: the gstack-ship ASK question
  detail?: string; // unconverged: the blocking detail
  reason?: string; // terminal-state-specific reason code (gstack-ship-ask / gstack-ship-failed / ...)
}

export interface HandoffPayload {
  status: ShipOutcome;
  epic: IssueId;
  familyBranch: string;
  baseAtStart: string;
  familyHead: string | null;
  merged: HandoffMergedSlice[];
  dirty: HandoffDirtySlice[];
  question: string | null;
  detail: string | null;
  flags: string[];
  prUrl: string | null;
  reason?: string;
}

// §段间交接 — assembles the stable handoff payload every run returns to the main session.
// All three terminal states share one shape (missing fields filled with stable nulls/empty arrays)
// so the main session can consume it uniformly: terminal state / parent epic / family branch +
// base SHA / merged slices + commit hashes / dirty slices / pending question / blocking detail /
// degradation flags / ready PR URL. Pure: no IO, no project imports.
export function buildHandoffPayload(input: HandoffInput): HandoffPayload {
  const payload: HandoffPayload = {
    status: input.status,
    epic: input.epic,
    familyBranch: input.familyBranch,
    baseAtStart: input.baseAtStart,
    familyHead: input.familyHead ?? null,
    merged: input.merged ?? [],
    dirty: input.dirty ?? [],
    question: input.question ?? null,
    detail: input.detail ?? null,
    flags: input.flags ?? [],
    prUrl: input.prUrl ?? null
  };
  if (input.reason !== undefined) payload.reason = input.reason;
  return payload;
}

export function judgeReviewDegradation(input: DegradationInput): DegradationJudgment {
  const availableModels = uniqueModels(input.results.filter((result) => result.available).map((result) => result.model));
  const missingResults = uniqueResultsByModel(input.results.filter((result) => !result.available));
  const missingModels = missingResults.map((result) => result.model);

  if (input.stage === "per_slice" && availableModels.length === 1 && availableModels[0] === "codex") {
    return {
      status: "continue",
      availableModels,
      missingModels,
      flags: missingModels.includes("agy") ? ["per-slice agy unavailable; proceeding codex-only"] : ["per-slice codex-only review"]
    };
  }

  if (input.stage === "family_5a_5b" && availableModels.length < 2) {
    return {
      status: "halt",
      availableModels,
      missingModels,
      flags: ["family 5a/5b requires at least two available models"]
    };
  }

  if (availableModels.length < 2) {
    return {
      status: "halt",
      availableModels,
      missingModels,
      flags: ["review requires at least two available models unless the per-slice codex-only exception applies"]
    };
  }

  return {
    status: "continue",
    availableModels,
    missingModels,
    flags: missingResults.map((result) => `review degraded: ${result.model} unavailable${result.reason ? ` (${result.reason})` : ""}`)
  };
}

function compareIssueKeys(left: string, right: string): number {
  const leftIsDecimal = isDecimalIssueKey(left);
  const rightIsDecimal = isDecimalIssueKey(right);
  if (leftIsDecimal && rightIsDecimal) {
    const numericOrder = Number(left) - Number(right);
    return numericOrder || left.localeCompare(right);
  }
  if (leftIsDecimal) return -1;
  if (rightIsDecimal) return 1;
  return left.localeCompare(right);
}

function isDecimalIssueKey(key: string): boolean {
  return /^[0-9]+$/.test(key);
}

function uniqueModels(models: string[]): string[] {
  return [...new Set(models)];
}

function uniqueResultsByModel(results: ModelReviewResult[]): ModelReviewResult[] {
  const byModel = new Map<string, ModelReviewResult>();
  for (const result of results) {
    if (!byModel.has(result.model)) byModel.set(result.model, result);
  }
  return [...byModel.values()];
}
