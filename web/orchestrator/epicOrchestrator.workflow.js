export const meta = {
  name: 'epic-orchestrator',
  description: 'Discover native GitHub sub-issues plus blocked_by edges for an epic and return the thinnest ordered execution plan.',
  whenToUse: 'Issue #219 S1: parent epic issue number -> GitHub native sub-issues + native blocked_by -> S0 topology plan. Does not implement review/worktree/merge.',
  phases: [
    { title: 'Discover', detail: 'Read native sub-issues and native blocked_by edges with gh' },
    { title: 'Plan', detail: 'Run the drift-guarded inline S0 topology copy and return an ordered plan' }
  ]
};

class InlineTopologyError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'TopologyError';
    this.code = code;
  }
}

const isClosed = (state) => state?.toLowerCase() === 'closed';
const sameId = (left, right) => String(left) === String(right);
const idKey = (id) => String(id);
const byIssueIds = (left, right) =>
  compareIssueKeys(idKey(left.issueId), idKey(right.issueId)) || compareIssueKeys(idKey(left.blockedByIssueId), idKey(right.blockedByIssueId));

// Thin inline copy of web/src/orchestratorKernel.ts layerEpicIssues.
// Workflow sandboxes cannot import the TS authority directly; web/src/epicOrchestratorWorkflow.test.ts
// is the drift guard that behavior-diffs this copy against the S0 authority.
export function inlineLayerEpicIssues(input) {
  const epicChildren = input.issues.filter((issue) => sameId(issue.epicId, input.epicId));
  if (epicChildren.length === 0) {
    throw new InlineTopologyError('empty_epic', `Epic ${input.epicId} has no native sub-issues.`);
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
      status: 'external_prerequisite',
      layers: [],
      skippedClosedIssueIds,
      externalPrerequisites
    };
  }

  const indegree = new Map();
  const issueIdsByKey = new Map();
  const dependents = new Map();

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

  const layers = [];
  let ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([key]) => key)
    .sort(compareIssueKeys);
  const emitted = new Set();

  while (ready.length > 0) {
    const currentLayerKeys = ready;
    layers.push(currentLayerKeys.map((key) => issueIdsByKey.get(key)));

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
      .join(', ');
    throw new InlineTopologyError('cycle', `Open epic children contain a blocked_by cycle: ${cycleIssueIds}.`);
  }

  return {
    status: 'ready',
    layers,
    skippedClosedIssueIds,
    externalPrerequisites: []
  };
}

function compareIssueKeys(left, right) {
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

function isDecimalIssueKey(key) {
  return /^[0-9]+$/.test(key);
}

export function normalizeWorkflowArgs(rawArgs) {
  const rawEpic = typeof rawArgs === 'object' && rawArgs !== null && 'epicIssueNumber' in rawArgs ? rawArgs.epicIssueNumber : rawArgs;
  const epicIssueNumber = String(rawEpic ?? '').trim();
  if (!/^[0-9]+$/.test(epicIssueNumber)) {
    throw new Error('epic-orchestrator requires args to be a positive parent epic issue number, e.g. 217 or {"epicIssueNumber":217}.');
  }
  if (Number(epicIssueNumber) <= 0) {
    throw new Error('epic-orchestrator requires args to be a positive parent epic issue number, e.g. 217 or {"epicIssueNumber":217}.');
  }
  return epicIssueNumber;
}

export async function runEpicDiscoveryWorkflow({ args, Bash, log }) {
  const epicIssueNumber = normalizeWorkflowArgs(args);

  phaseIfAvailable('Discover');
  log?.(`Discovering native sub-issues and native blocked_by edges for epic #${epicIssueNumber}`);
  const discovered = parseBashJson(
    await Bash(`python3 - ${shellQuote(epicIssueNumber)} <<'PY'
import json
import os
import subprocess
import sys

GH_TIMEOUT_SECONDS = 30
epic = sys.argv[1]


def run_gh(args, context):
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"gh {context} timed out after {GH_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        raise SystemExit(f"gh {context} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout.strip()


def resolve_repo():
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        repo = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], "repo view")
    if not repo or "/" not in repo:
        raise SystemExit("Could not resolve GitHub repository. Set GITHUB_REPOSITORY or run inside a gh-linked repository.")
    return repo


REPO = resolve_repo()


def gh_json(path):
    payload = run_gh(["api", "-H", "Accept: application/vnd.github+json", path], f"api {path}")
    return json.loads(payload) if payload else []

children = gh_json(f"/repos/{REPO}/issues/{epic}/sub_issues")
child_numbers = {str(child["number"]) for child in children}
issues_by_key = {}
blocked_by = []

for child in children:
    child_number = str(child["number"])
    issues_by_key[child_number] = {
        "id": child["number"],
        "epicId": int(epic),
        "state": child.get("state"),
        "title": child.get("title", ""),
        "url": child.get("html_url", ""),
    }
    blockers = gh_json(f"/repos/{REPO}/issues/{child_number}/dependencies/blocked_by")
    for blocker in blockers:
        blocker_number = str(blocker["number"])
        blocked_by.append({"issueId": child["number"], "blockedByIssueId": blocker["number"]})
        if blocker_number not in issues_by_key:
            issues_by_key[blocker_number] = {
                "id": blocker["number"],
                "epicId": int(epic) if blocker_number in child_numbers else "__external__",
                "state": blocker.get("state"),
                "title": blocker.get("title", ""),
                "url": blocker.get("html_url", ""),
            }

print(json.dumps({
    "epicId": int(epic),
    "issues": list(issues_by_key.values()),
    "blockedBy": blocked_by,
}, ensure_ascii=False))
PY`)
  );

  const topologyInput = {
    epicId: discovered.epicId,
    issues: discovered.issues.map((issue) => ({ id: issue.id, epicId: issue.epicId, state: issue.state })),
    blockedBy: discovered.blockedBy
  };

  phaseIfAvailable('Plan');
  const topology = inlineLayerEpicIssues(topologyInput);
  const issueMetadata = Object.fromEntries(discovered.issues.map((issue) => [idKey(issue.id), { title: issue.title, state: issue.state, url: issue.url }]));
  const orderedPlan = buildOrderedExecutionPlan(topology, issueMetadata);
  const boundaryHandling = describeBoundaryHandling(topology);
  const result = {
    epicIssueNumber: Number(epicIssueNumber),
    topology,
    orderedPlan,
    boundaryHandling,
    outOfScope: ['review', 'worktree', 'merge']
  };

  log?.(`Ordered execution plan: ${JSON.stringify(orderedPlan)}`);
  log?.(`Boundary handling: ${JSON.stringify(boundaryHandling)}`);
  return result;
}

function buildOrderedExecutionPlan(topology, issueMetadata) {
  if (topology.status !== 'ready') return [];
  return topology.layers.map((layer, index) => ({
    layer: index + 1,
    issueNumbers: layer,
    issues: layer.map((issueId) => ({ issueNumber: issueId, ...(issueMetadata[idKey(issueId)] ?? {}) }))
  }));
}

function describeBoundaryHandling(topology) {
  if (topology.status === 'external_prerequisite') {
    return {
      action: 'return_to_main_session',
      reason: 'one or more unresolved blockers are outside this epic',
      externalPrerequisites: topology.externalPrerequisites
    };
  }
  return {
    action: 'continue',
    skippedClosedIssueIds: topology.skippedClosedIssueIds,
    note: 'empty epic and cycles throw TopologyError; closed child issues are skipped; closed blockers are treated as satisfied'
  };
}

function parseBashJson(raw) {
  if (typeof raw === 'string') return JSON.parse(raw);
  if (raw && typeof raw.output === 'string') return JSON.parse(raw.output);
  if (raw && typeof raw.stdout === 'string') return JSON.parse(raw.stdout);
  throw new Error('Bash did not return JSON output.');
}

function phaseIfAvailable(title) {
  if (typeof phase !== 'undefined') phase(title);
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

if (typeof args !== 'undefined') {
  await runEpicDiscoveryWorkflow({ args, Bash, log });
}
