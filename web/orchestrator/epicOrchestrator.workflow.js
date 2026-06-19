export const meta = {
  name: 'epic-orchestrator',
  description: 'Discover native GitHub sub-issues plus blocked_by edges, plan one open slice, implement it in a worktree, verify, run per-slice codex+agy review, and merge the reviewed commit to the family branch.',
  whenToUse: 'Issue #220 S2: parent epic issue number -> one planned slice -> isolation:worktree implementation -> local verify -> per-slice codex+agy review -> family branch merge. Parallelism and family 5a/5b remain out of scope.',
  phases: [
    { title: 'Discover', detail: 'Read native sub-issues and native blocked_by edges with gh' },
    { title: 'Plan', detail: 'Run the drift-guarded inline S0 topology copy and choose the first ready slice only' },
    { title: 'Implement', detail: 'Run the implementation leg with isolation:"worktree" and I7/I8 instructions' },
    { title: 'Verify', detail: 'Run local verification commands before any review' },
    { title: 'Review', detail: 'Run per-slice codex + agy via Bash; agy uses diff-only for hidden worktrees and codex has grounding fallback' },
    { title: 'Merge', detail: 'Merge the reviewed commit to the family branch serially' }
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
    payload = run_gh([
        "api",
        "--paginate",
        "--slurp",
        "--method", "GET",
        "-H", "Accept: application/vnd.github+json",
        "-f", "per_page=100",
        path,
    ], f"api {path}")
    pages = json.loads(payload) if payload else []
    if all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages

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

export async function runEpicSingleSlicePipeline({ args, Bash, agent: agentRunner, log }) {
  const discovery = await runEpicDiscoveryWorkflow({ args, Bash, log });
  if (discovery.topology.status !== 'ready') {
    return { ...discovery, status: discovery.boundaryHandling.action };
  }

  const plannedIssue = discovery.orderedPlan[0]?.issues[0];
  if (!plannedIssue) {
    throw new Error('S2 single-slice pipeline requires at least one planned open slice.');
  }

  const normalizedArgs = normalizePipelineArgs(args, discovery.epicIssueNumber);
  const plannedSlice = {
    ...plannedIssue,
    isolation: 'worktree'
  };

  phaseIfAvailable('Implement');
  log?.(`Implementing one slice with worktree isolation: #${plannedSlice.issueNumber} ${plannedSlice.title ?? ''}`.trim());
  const runner = agentRunner ?? (typeof agent !== 'undefined' ? agent : undefined);
  if (typeof runner !== 'function') {
    throw new Error('S2 single-slice pipeline requires an agent runner for the implementation leg.');
  }

  const implementations = [];
  const verificationAttempts = [];
  const reviewAttempts = [];
  const reviewFixCommits = [];
  let implementation;
  let implementedCommit;
  let worktreePath;
  let verification;
  let review;
  let observabilityEvidence;

  for (let round = 1; round <= normalizedArgs.maxReviewRounds; round += 1) {
    implementation = await runner({
      isolation: 'worktree',
      issueNumber: plannedSlice.issueNumber,
      issue: plannedSlice,
      prompt:
        round === 1
          ? buildImplementationPrompt(discovery.epicIssueNumber, plannedSlice)
          : buildReviewFixPrompt(discovery.epicIssueNumber, plannedSlice, implementations.at(-1)?.commit, review, round, normalizedArgs.maxReviewRounds),
      ...(round === 1
        ? {}
        : {
            reviewFix: {
              failedCommit: implementations.at(-1)?.commit,
              failedReview: review,
              round,
              maxReviewRounds: normalizedArgs.maxReviewRounds
            }
          })
    });
    implementedCommit = implementation?.commit ?? implementation?.commitSha ?? implementation?.sha;
    worktreePath = implementation?.worktreePath ?? implementation?.path;
    if (!implementedCommit || !worktreePath) {
      throw new Error('Implementation leg must return a commit and worktreePath.');
    }
    if (implementations.length > 0 && implementedCommit === implementations.at(-1)?.commit) {
      throw new Error('I7 requires each review-fix round to return a new commit, not the failed commit.');
    }
    if (!isHiddenWorktreePath(worktreePath)) {
      throw new Error('Implementation worktree must be under a hidden-dot path so agy review is explicitly diff-only.');
    }
    observabilityEvidence = validateObservabilityEvidence(implementation?.observabilityEvidence);
    implementations.push({ commit: implementedCommit, worktreePath });
    if (round > 1) reviewFixCommits.push(implementedCommit);

    await Bash(`set -euo pipefail\n# enforce I7 commit discipline for slice ${shellQuote(plannedSlice.issueNumber)} round ${shellQuote(round)}\ngit -C ${shellQuote(worktreePath)} cat-file -e ${shellQuote(implementedCommit)}^{commit}\ngit -C ${shellQuote(worktreePath)} rev-list --parents -n 1 ${shellQuote(implementedCommit)} | awk 'NF >= 2 { ok=1 } END { exit ok ? 0 : 1 }'\ngit -C ${shellQuote(worktreePath)} diff --quiet`);

    phaseIfAvailable('Verify');
    verification = await runVerification({ Bash, worktreePath, verifyCommands: normalizedArgs.verifyCommands });
    verificationAttempts.push({ commit: implementedCommit, ...verification });
    if (verification.status !== 'passed') {
      return {
        ...discovery,
        outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
        status: 'verify_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    phaseIfAvailable('Review');
    review = await runPerSliceReview({ Bash, worktreePath, commit: implementedCommit, plannedSlice });
    reviewAttempts.push({ commit: implementedCommit, ...review });
    if (review.status === 'passed') break;

    if (round >= normalizedArgs.maxReviewRounds) {
      return {
        ...discovery,
        outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
        status: 'review_failed',
        plannedSlice,
        implementation: { commit: implementedCommit, worktreePath },
        implementations,
        verification,
        verificationAttempts,
        review,
        reviewAttempts,
        i1: { status: 'aborted', reason: 'max_review_rounds', maxReviewRounds: normalizedArgs.maxReviewRounds },
        i7: i7Evidence(implementedCommit, reviewFixCommits),
        i8: i8Evidence(observabilityEvidence)
      };
    }

    log?.(`Per-slice review failed for #${plannedSlice.issueNumber}; starting same-slice review-fix round ${round + 1}/${normalizedArgs.maxReviewRounds}.`);
  }

  phaseIfAvailable('Merge');
  const mergeResult = parseBashJson(
    await Bash(`set -euo pipefail\n# merge reviewed commit into family branch; reviewer=merge reviewed commit\nworktreePath=${shellQuote(worktreePath)}\nfamilyBranch=${shellQuote(normalizedArgs.familyBranch)}\nimplementedCommit=${shellQuote(implementedCommit)}\ngit -C "$worktreePath" fetch origin "$familyBranch" || true\nif git -C "$worktreePath" show-ref --verify --quiet refs/heads/\${familyBranch}; then\n  git -C "$worktreePath" switch \${familyBranch}\nelif git -C "$worktreePath" show-ref --verify --quiet refs/remotes/origin/\${familyBranch}; then\n  git -C "$worktreePath" switch -c \${familyBranch} --track origin/\${familyBranch}\nelse\n  git -C "$worktreePath" switch -c \${familyBranch} \${implementedCommit}^\nfi\ngit -C "$worktreePath" merge --no-ff "$implementedCommit" -m ${shellQuote(`merge reviewed slice #${plannedSlice.issueNumber}`)} >&2\nprintf '{"mergeCommit":"'\ngit -C "$worktreePath" rev-parse HEAD | tr -d '\\n'\nprintf '"}'`)
  );

  return {
    ...discovery,
    outOfScope: ['parallelism', 'family_5a_5b', 'online_pr_review_loop'],
    status: 'merged',
    plannedSlice,
    implementation: { commit: implementedCommit, worktreePath },
    implementations,
    verification,
    verificationAttempts,
    review,
    reviewAttempts,
    merge: {
      status: 'merged',
      familyBranch: normalizedArgs.familyBranch,
      reviewedCommit: implementedCommit,
      mergeCommit: mergeResult.mergeCommit
    },
    i7: i7Evidence(implementedCommit, reviewFixCommits),
    i8: i8Evidence(observabilityEvidence)
  };
}

function normalizePipelineArgs(rawArgs, epicIssueNumber) {
  const objectArgs = typeof rawArgs === 'object' && rawArgs !== null ? rawArgs : {};
  const requiredVerifyCommands = ['npm --prefix web run typecheck:orch', 'npm --prefix web test', 'npm --prefix web run build'];
  const extraVerifyCommands = Array.isArray(objectArgs.verifyCommands) ? objectArgs.verifyCommands.map((command) => String(command)) : [];
  const verifyCommands = [...new Set([...requiredVerifyCommands, ...extraVerifyCommands])];
  return {
    familyBranch: String(objectArgs.familyBranch ?? `family/epic-${epicIssueNumber}`),
    verifyCommands,
    maxReviewRounds: normalizePositiveInteger(objectArgs.maxReviewRounds, 3, 'maxReviewRounds')
  };
}

function normalizePositiveInteger(value, fallback, name) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer.`);
  }
  return parsed;
}

function buildImplementationPrompt(epicIssueNumber, plannedSlice) {
  return [
    `Implement epic #${epicIssueNumber} slice #${plannedSlice.issueNumber}: ${plannedSlice.title ?? ''}`,
    'Use isolation:"worktree". Produce exactly one slice commit for the initial implementation.',
    'I7: every review-fix round must be a new commit; never amend or squash review history.',
    'I8: enforce loud failures, locator logs, and gameplay DB consequences when applicable; for read-only/UI/tooling slices include substitute observability evidence.',
    'Return JSON-like data containing commit and worktreePath.'
  ].join('\n');
}

function buildReviewFixPrompt(epicIssueNumber, plannedSlice, failedCommit, failedReview, round, maxReviewRounds) {
  return [
    `Fix epic #${epicIssueNumber} slice #${plannedSlice.issueNumber}: ${plannedSlice.title ?? ''}`,
    `Same-slice review-fix round ${round}/${maxReviewRounds}; previous reviewed commit ${failedCommit} did not pass per-slice review.`,
    `Review findings: ${JSON.stringify(failedReview)}`,
    'Use the same isolation:"worktree" and fix only this slice.',
    'I7: create a NEW commit for this fix round; never amend, squash, or reuse the failed commit.',
    'After the fix the orchestrator will rerun local verify and codex+agy review.',
    'Return JSON-like data containing the new commit and worktreePath.'
  ].join('\n');
}

async function runVerification({ Bash, worktreePath, verifyCommands }) {
  const results = [];
  for (const command of verifyCommands) {
    const parsed = parseBashJson(
      await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\nout=$(mktemp)\nset +e\n( ${command} ) >"$out" 2>&1\nrc=$?\npython3 - "$rc" "$out" <<'PY'\nimport json, sys\nrc = int(sys.argv[1])\nwith open(sys.argv[2], encoding='utf-8', errors='replace') as handle:\n    output = handle.read()\nprint(json.dumps({"status": "passed" if rc == 0 else "failed", "exitCode": rc, "output": output}))\nPY`)
    );
    results.push({ command, ...parsed });
    if (parsed.status && parsed.status !== 'passed') {
      return { status: 'failed', commands: verifyCommands, results };
    }
  }
  return { status: 'passed', commands: verifyCommands, results };
}

async function runPerSliceReview({ Bash, worktreePath, commit, plannedSlice }) {
  const codex = parseReviewerJson(
    await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\n# reviewer=codex; full grounding fallback enabled: inspect repo files if diff alone is insufficient\n{\n  printf '%s\\n' 'Review the following git diff for correctness regressions.'\n  printf '%s\\n' 'Return only one JSON object on stdout with shape {"status":"passed"|"failed","findings":[...]}. Do not include markdown, prose, or diff-stat text outside the JSON object.'\n  printf '%s\\n' 'Diff stat for human context:'\n  git diff --stat ${shellQuote(`${commit}^`)} ${shellQuote(commit)}\n  printf '%s\\n' 'Full diff:'\n  git diff ${shellQuote(`${commit}^`)} ${shellQuote(commit)}\n} | codex exec --skip-git-repo-check --ephemeral -`),
    'codex'
  );
  const agy = parseReviewerJson(
    await Bash(`set -euo pipefail\ncd ${shellQuote(worktreePath)}\n# reviewer=agy; hidden worktree path forces diff-only review\ngit diff ${shellQuote(`${commit}^`)} ${shellQuote(commit)} | agy -p --sandbox --diff-only`),
    'agy'
  );
  const reviewers = [
    { model: 'codex', status: reviewStatus(codex), groundingFallback: true, findings: codex.findings ?? [] },
    { model: 'agy', status: reviewStatus(agy), diffOnly: true, hiddenWorktree: true, findings: agy.findings ?? [] }
  ];
  const failed = reviewers.find((reviewer) => reviewer.status !== 'passed');
  return {
    status: failed ? 'failed' : 'passed',
    sliceIssueNumber: plannedSlice.issueNumber,
    reviewers,
    flags: ['per-slice review uses codex+agy via Bash', 'agy is diff-only for hidden-dot worktrees', 'codex has full grounding fallback']
  };
}

function reviewStatus(reviewResult) {
  if (Array.isArray(reviewResult.findings) && reviewResult.findings.length > 0) return 'failed';
  return reviewResult.status === 'passed' ? 'passed' : 'failed';
}

function isHiddenWorktreePath(worktreePath) {
  return String(worktreePath).split('/').some((part) => part.startsWith('.') && part.length > 1);
}

function i7Evidence(commit, reviewFixCommits = []) {
  const evidence = { sliceCommit: commit, amendmentsForbidden: true, reviewFixesRequireNewCommits: true };
  if (reviewFixCommits.length > 0) evidence.reviewFixCommits = reviewFixCommits;
  return evidence;
}

function validateObservabilityEvidence(evidence) {
  if (!evidence || evidence.loudFailure !== true || evidence.locatorLogs !== true) {
    throw new Error('I8 observability evidence must include loudFailure:true and locatorLogs:true.');
  }
  if (!evidence.gameplayDbConsequences && !evidence.notApplicableReason) {
    throw new Error('I8 observability evidence must include gameplayDbConsequences or a notApplicableReason for read-only/UI/tooling slices.');
  }
  return evidence;
}

function i8Evidence(evidence) {
  return {
    required: true,
    loudFailure: evidence.loudFailure,
    locatorLogs: evidence.locatorLogs,
    gameplayDbConsequences: evidence.gameplayDbConsequences ?? 'N/A',
    notApplicableReason: evidence.notApplicableReason
  };
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
  const output = bashText(raw);
  if (output !== null) return JSON.parse(output);
  throw new Error('Bash did not return JSON output.');
}

function parseReviewerJson(raw, reviewerName) {
  const output = bashText(raw);
  if (output === null) throw new Error(`${reviewerName} review did not return output.`);

  try {
    return JSON.parse(output);
  } catch (fullOutputError) {
    const trimmed = output.trim();
    for (let index = trimmed.lastIndexOf('{'); index >= 0; index = trimmed.lastIndexOf('{', index - 1)) {
      try {
        return JSON.parse(trimmed.slice(index));
      } catch {
        // Keep scanning for a trailing reviewer JSON object after human context.
      }
    }
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).reverse();
    for (const line of lines) {
      if (!line.startsWith('{') || !line.endsWith('}')) continue;
      try {
        return JSON.parse(line);
      } catch {
        // Keep scanning for the explicit reviewer JSON object.
      }
    }
    throw new Error(`${reviewerName} review did not return parseable reviewer JSON: ${fullOutputError.message}`);
  }
}

function bashText(raw) {
  if (typeof raw === 'string') return raw;
  if (raw && typeof raw.output === 'string') return raw.output;
  if (raw && typeof raw.stdout === 'string') return raw.stdout;
  return null;
}

function phaseIfAvailable(title) {
  if (typeof phase !== 'undefined') phase(title);
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

if (typeof args !== 'undefined') {
  await runEpicSingleSlicePipeline({
    args,
    Bash,
    agent: typeof agent !== 'undefined' ? agent : undefined,
    log
  });
}
