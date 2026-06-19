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
  location?: string;
}

export interface FindingRoute {
  status: "autonomous_repair" | "needs_decision" | "no_findings";
  autonomousBugFindings: Finding[];
  decisionFindings: Finding[];
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
    throw new TopologyError("empty_epic", `Epic ${input.epicId} 没有原生子 issue。`);
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
    throw new TopologyError("cycle", `打开的 epic 子 issue 存在 blocked_by 环: ${cycleIssueIds}。`);
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
    if (finding.classification === "mechanical_bug") {
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
