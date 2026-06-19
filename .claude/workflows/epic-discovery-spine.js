export const meta = {
  name: 'epic-discovery-spine',
  description: '发现 epic 原生子 issue 图并返回最薄有序执行计划',
  whenToUse: '用于 issue #219 S1：父 epic issue 号 -> gh 读取原生 sub-issues + native blocked_by -> S0 拓扑计划。不实现 review/worktree/merge。',
  phases: [
    { title: '发现', detail: '用 gh 读取原生 sub-issues 与 native blocked_by 边' },
    { title: '计划', detail: '运行内联 S0 拓扑副本并记录有序计划与边界处理' }
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
// Keep intentionally small; web/src/epicDiscoveryWorkflowInline.test.ts is the drift guard against S0 authority.
export function inlineLayerEpicIssues(input) {
  const epicChildren = input.issues.filter((issue) => sameId(issue.epicId, input.epicId));
  if (epicChildren.length === 0) {
    throw new InlineTopologyError('empty_epic', `Epic ${input.epicId} 没有原生子 issue。`);
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
    throw new InlineTopologyError('cycle', `打开的 epic 子 issue 存在 blocked_by 环: ${cycleIssueIds}。`);
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
    throw new Error('epic-discovery-spine 需要 args 是父 epic issue 号，例如 217 或 {"epicIssueNumber":217}。');
  }
  return epicIssueNumber;
}

export async function runEpicDiscoveryWorkflow({ args, Bash, log }) {
  const epicIssueNumber = normalizeWorkflowArgs(args);

  phaseIfAvailable('发现');
  log?.(`正在发现 epic #${epicIssueNumber} 的原生 sub-issues 与 native blocked_by`);
  const discovered = parseBashJson(
    await Bash(`python3 - ${shellQuote(epicIssueNumber)} <<'PY'
import json
import subprocess
import sys

REPO = "Akagilnc/ming-salvage-sim"
epic = sys.argv[1]


def gh_json(path):
    completed = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(f"gh api failed for {path}: {completed.stderr.strip() or completed.stdout.strip()}")
    payload = completed.stdout.strip()
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

  phaseIfAvailable('计划');
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

  log?.(`有序执行计划: ${JSON.stringify(orderedPlan)}`);
  log?.(`边界处理: ${JSON.stringify(boundaryHandling)}`);
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
      reason: '存在一个或多个未关闭 blocker 位于本 epic 外，需要回主 session',
      externalPrerequisites: topology.externalPrerequisites
    };
  }
  return {
    action: 'continue',
    skippedClosedIssueIds: topology.skippedClosedIssueIds,
    note: '空 epic 与成环会抛出 TopologyError；已关闭子 issue 会跳过；已关闭 blocker 视为已满足'
  };
}

function parseBashJson(raw) {
  if (typeof raw === 'string') return JSON.parse(raw);
  if (raw && typeof raw.output === 'string') return JSON.parse(raw.output);
  if (raw && typeof raw.stdout === 'string') return JSON.parse(raw.stdout);
  throw new Error('Bash 没有返回 JSON 输出。');
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
